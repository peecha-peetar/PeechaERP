"""R303 — رزرو موجودی: یک نقطهٔ مشترک برای وظایف انبار، تولید و سفارش فروش.

هر رزرو یک ردیف inv.stock_reservations است و ماندهٔ فعالش هم‌زمان در stock_balance.quantity_reserved
همان محل نگه داشته می‌شود (پایهٔ «موجودی آزاد» و کنترل WMS_ENFORCE_RESERVATION در موتور انبار).
"""

from __future__ import annotations

import datetime
import decimal
from types import SimpleNamespace

from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.inventory import BinLocation, Item, StockBalance, StockDocument, StockDocumentLine, StockReservation, \
    WarehouseTask
from peecha.services import audit as audit_service
from peecha.services import stock_controls

SALES_ORDER = "SALES_ORDER_LINE"
PICK_TASK = "WMS_PICK_TASK"
_ZERO = decimal.Decimal(0)
_UNRESERVABLE_BIN_STATUSES = ("BLOCKED", "MAINTENANCE", "QUARANTINE")


def remaining(res: StockReservation) -> decimal.Decimal:
    return decimal.Decimal(res.quantity) - decimal.Decimal(res.fulfilled_quantity_base or 0)


def hold(session, res: StockReservation, delta: decimal.Decimal) -> None:
    """مقدار رزرو محل را به‌اندازهٔ delta (مثبت یا منفی) تغییر می‌دهد."""
    if res.bin_location_id is None or not delta:
        return
    bal = session.scalar(select(StockBalance).where(
        StockBalance.item_id == res.item_id, StockBalance.warehouse_id == res.warehouse_id,
        StockBalance.bin_location_id == res.bin_location_id, StockBalance.batch_id.is_(None)).with_for_update())
    if bal is not None:
        bal.quantity_reserved = max(_ZERO, decimal.Decimal(bal.quantity_reserved or 0) + decimal.Decimal(delta))


def add(session, *, company_id: int, item_id: int, warehouse_id: int, bin_location_id: int | None,
        quantity: decimal.Decimal, source_type: str, source_id: int) -> StockReservation:
    res = StockReservation(company_id=company_id, item_id=item_id, warehouse_id=warehouse_id, bin_location_id=bin_location_id,
                           quantity=quantity, fulfilled_quantity_base=_ZERO, source_type_code=source_type,
                           source_record_id=source_id, status_code="ACTIVE")
    session.add(res)
    session.flush()
    hold(session, res, quantity)
    return res


def fulfil(session, res: StockReservation, quantity: decimal.Decimal) -> decimal.Decimal:
    take = min(remaining(res), decimal.Decimal(quantity))
    if take <= 0:
        return _ZERO
    res.fulfilled_quantity_base = decimal.Decimal(res.fulfilled_quantity_base or 0) + take
    hold(session, res, -take)
    if remaining(res) <= 0:
        res.status_code, res.released_at = "FULFILLED", datetime.datetime.now()
    return take


def release(session, res: StockReservation, status: str = "CANCELLED") -> None:
    hold(session, res, -remaining(res))
    res.status_code, res.released_at = status, datetime.datetime.now()


def active(session, source_type: str, source_ids, lock: bool = True) -> list[StockReservation]:
    ids = [i for i in source_ids if i is not None]
    if not ids:
        return []
    q = select(StockReservation).where(
        StockReservation.source_type_code == source_type, StockReservation.source_record_id.in_(ids),
        StockReservation.status_code == "ACTIVE").order_by(StockReservation.reservation_id)
    return list(session.scalars(q.with_for_update() if lock else q))


def free_bins(session, item_id: int, warehouse_id: int) -> list[tuple[int, decimal.Decimal]]:
    """محل‌های دارای موجودی آزاد (فیزیکی − رزرو)، بیشترین اول؛ محل مسدود/تعمیر/قرنطینه رزرو نمی‌شود."""
    rows = session.execute(
        select(StockBalance.bin_location_id, StockBalance.quantity_on_hand, StockBalance.quantity_reserved)
        .join(BinLocation, BinLocation.bin_location_id == StockBalance.bin_location_id)
        .where(StockBalance.item_id == item_id, StockBalance.warehouse_id == warehouse_id, StockBalance.batch_id.is_(None),
               StockBalance.quantity_on_hand > 0, BinLocation.status_code.not_in(_UNRESERVABLE_BIN_STATUSES))
        .order_by(StockBalance.bin_location_id)).all()
    out = [(b, decimal.Decimal(q) - decimal.Decimal(r or 0)) for b, q, r in rows]
    return sorted([x for x in out if x[1] > 0], key=lambda x: (-x[1], x[0]))


# =====================================================================
# سفارش فروش (کلید WMS_SALES_ORDER_RESERVATION)
# =====================================================================
def _order_lines(session, document_id: int):
    from peecha.db.models.commercial import CommercialDocumentLine

    return list(session.scalars(select(CommercialDocumentLine).where(CommercialDocumentLine.document_id == document_id)
                                .order_by(CommercialDocumentLine.line_no)))


def reserve_order_lines(session, doc, lines) -> list[tuple[int, decimal.Decimal]]:
    """رزرو هرچه از هر ردیف هنوز رزرو نشده؛ خروجی = کمبودها [(کالا، مقدار)]. کمبود مانع نیست."""
    short = []
    for ln in lines:
        item = session.get(Item, ln.item_id) if ln.item_id else None
        warehouse_id = ln.warehouse_id or doc.warehouse_id
        if item is None or not item.is_stock_tracked or warehouse_id is None:
            continue
        held = sum((remaining(r) for r in active(session, SALES_ORDER, [ln.line_id])), _ZERO)
        need = decimal.Decimal(ln.quantity_base) - held
        for bin_id, free in free_bins(session, ln.item_id, warehouse_id):
            if need <= 0:
                break
            take = min(free, need)
            add(session, company_id=doc.company_id, item_id=ln.item_id, warehouse_id=warehouse_id, bin_location_id=bin_id,
                quantity=take, source_type=SALES_ORDER, source_id=ln.line_id)
            need -= take
        if need > 0:
            short.append((ln.item_id, need))
    return short


def reserve_sales_order(company_id: int, document_id: int, user_id: int | None = None) -> SimpleNamespace | None:
    """با تایید سفارش فروش. None یعنی کلید خاموش است یا سند سفارش فروش نیست."""
    from peecha.db.models.commercial import CommercialDocument

    if not stock_controls.is_on(company_id, stock_controls.SALES_ORDER_RESERVATION):
        return None
    with new_session() as session:
        doc = session.get(CommercialDocument, document_id)
        if doc is None or doc.company_id != company_id or doc.document_type_code != "SALES_ORDER":
            return None
        short = reserve_order_lines(session, doc, _order_lines(session, document_id))
        audit_service.log_activity(session, company_id=company_id, user_id=user_id, entity_type="CommercialDocument",
                                   entity_id=document_id, action="UPDATE",
                                   changes={"operation": "STOCK_RESERVE", "short": {str(i): str(q) for i, q in short}})
        session.commit()
    return SimpleNamespace(short=short)


def release_sales_order(company_id: int, document_id: int, user_id: int | None = None, status: str = "CANCELLED") -> int:
    """با لغو یا بازگشت به پیش‌نویس سفارش؛ مستقل از کلید (رزرو باقی‌مانده هرگز نباید گیر کند)."""
    with new_session() as session:
        line_ids = [ln.line_id for ln in _order_lines(session, document_id)]
        rows = active(session, SALES_ORDER, line_ids)
        for res in rows:
            release(session, res, status)
        if rows:
            audit_service.log_activity(session, company_id=company_id, user_id=user_id, entity_type="CommercialDocument",
                                       entity_id=document_id, action="UPDATE",
                                       changes={"operation": "STOCK_RELEASE", "reservations": len(rows)})
        session.commit()
        return len(rows)


def order_line_reserved(session, order_line_id: int) -> decimal.Decimal:
    return sum((remaining(r) for r in active(session, SALES_ORDER, [order_line_id])), _ZERO)


def order_reservation_summary(company_id: int, document_id: int) -> dict[int, decimal.Decimal]:
    """ردیف سفارش → مقدار رزرو فعال (برای نمایش در فرم سفارش)."""
    with new_session() as session:
        out = {}
        for ln in _order_lines(session, document_id):
            out[ln.line_id] = order_line_reserved(session, ln.line_id)
        return out


# =====================================================================
# مصرف رزرو خود سند هنگام ثبت (پیش از موتور، در همان تراکنش)
# =====================================================================
_OUT_TYPES = ("ISSUE", "TRANSFER", "RETURN_OUT")


def _issued_for_order_line(session, order_line_id: int) -> decimal.Decimal:
    """مقدار خارج‌شده از انبار برای یک ردیف سفارش (فاکتورهایی که سند انبارشان ثبت شده)، به واحد همان ردیف."""
    from peecha.db.models.commercial import CommercialDocumentLine

    rows = session.execute(
        select(CommercialDocumentLine.quantity)
        .join(StockDocumentLine, StockDocumentLine.line_id == CommercialDocumentLine.stock_document_line_id)
        .join(StockDocument, StockDocument.stock_document_id == StockDocumentLine.stock_document_id)
        .where(CommercialDocumentLine.source_line_id == order_line_id, StockDocument.status_code == "POSTED")).all()
    return sum((decimal.Decimal(q) for (q,) in rows), _ZERO)


def _line_links(session, lines) -> dict[int, tuple]:
    """ردیف سند انبار → (ردیف سند بازرگانی، [ردیف بازرگانی و ردیف سفارش مبدا]، [وظایف برداشت])."""
    from peecha.db.models.commercial import CommercialDocumentLine

    comm_by_stock = {cl.stock_document_line_id: cl for cl in session.scalars(select(CommercialDocumentLine).where(
        CommercialDocumentLine.stock_document_line_id.in_([ln.line_id for ln in lines] or [-1])))}
    out = {}
    for ln in lines:
        cl = comm_by_stock.get(ln.line_id)
        comm_ids = [i for i in ([cl.line_id, cl.source_line_id] if cl is not None else []) if i]
        task_ids = list(session.scalars(select(WarehouseTask.task_id).where(
            WarehouseTask.task_type_code == "PICK",
            (WarehouseTask.source_stock_line_id == ln.line_id) | (WarehouseTask.source_commercial_line_id.in_(comm_ids or [-1])))))
        out[ln.line_id] = (cl, comm_ids, task_ids)
    return out


def _document_lines(session, stock_document_id: int):
    return list(session.scalars(select(StockDocumentLine).where(StockDocumentLine.stock_document_id == stock_document_id)
                                .order_by(StockDocumentLine.line_no)))


def linked_reservations(session, stock_document_id: int) -> list[StockReservation]:
    """رزروهای فعالی که همین سند برایشان صادر شده (بدون قفل؛ برای انتخاب محل)."""
    out = []
    for _cl, comm_ids, task_ids in _line_links(session, _document_lines(session, stock_document_id)).values():
        out += active(session, SALES_ORDER, comm_ids, lock=False) + active(session, PICK_TASK, task_ids, lock=False)
    return out


def consume_for_stock_document(session, stock_document_id: int, include_picks: bool = False) -> decimal.Decimal:
    """رزروهایی که همین سند برایشان صادر شده (سفارش فروش مبدا و، با کلید رعایت رزرو، وظیفهٔ برداشت همین ردیف)
    مصرف می‌شوند تا کنترل رزرو موتور، رزرو خود سند را مانع نبیند. خروجی = جمع مقدار مصرف‌شده."""
    from peecha.db.models.commercial import CommercialDocumentLine

    doc = session.get(StockDocument, stock_document_id)
    if doc is None or doc.document_type_code not in _OUT_TYPES:
        return _ZERO
    lines = _document_lines(session, stock_document_id)
    if not lines:
        return _ZERO
    links = _line_links(session, lines)
    total = _ZERO
    order_lines: set[int] = set()
    for ln in lines:
        cl, comm_ids, task_ids = links[ln.line_id]
        rows = active(session, SALES_ORDER, comm_ids) + (active(session, PICK_TASK, task_ids) if include_picks else [])
        left = decimal.Decimal(ln.quantity_base)
        for res in rows:
            if left <= 0:
                break
            left -= fulfil(session, res, left)
        total += decimal.Decimal(ln.quantity_base) - left
        if cl is not None and cl.source_line_id:
            order_lines.add(cl.source_line_id)
    session.flush()
    # ردیف سفارشی که کاملاً خارج شده: باقی رزروش (مثلاً تحویل کمتر از سفارش) آزاد می‌شود
    for order_line_id in order_lines:
        order_line = session.get(CommercialDocumentLine, order_line_id)
        if order_line is None:
            continue
        target = order_line.warehouse_delivered_quantity if order_line.warehouse_delivered_quantity is not None \
            else order_line.quantity
        if _issued_for_order_line(session, order_line_id) >= decimal.Decimal(target):
            for res in active(session, SALES_ORDER, [order_line_id]):
                release(session, res, "FULFILLED")
    return total
