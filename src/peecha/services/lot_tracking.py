"""ردیابیِ بچ/سریال/تاریخِ انقضا و کالایِ امانی بر اساسِ تامین‌کننده -- R227.

موجودیِ کمّی همچنان فقط در موتورِ انبار (inventory_engine) است و دست نمی‌خورد؛
این سرویس لایهٔ ردیابی است:
- ورودیِ کاربر (شمارهٔ بچ، تاریخِ تولید/انقضا، سریال) رویِ ردیفِ سندِ انبار یا
  ردیفِ سندِ بازرگانی (سفارشِ خرید در تاییدِ رسید، فاکتورِ خرید، امانیِ ورودی).
- با هر ثبتِ سندِ انبار (inventory_documents.post_stock_document) حرکتِ هر
  بچ/سریال/تامین‌کننده در inv.lot_movements ثبت می‌شود؛ خروجی‌ها اگر بچ/سریال
  مشخص نشده باشد، خودکار FEFO (زودانقضاترین اول) تخصیص می‌یابند -- فروشِ واقعی
  هرگز به‌خاطرِ نبودِ اطلاعاتِ ردیابی رد نمی‌شود.
- کالایِ امانیِ ورودی (حتی بدونِ بچ/سریال) با تامین‌کننده‌اش ردیابی می‌شود و با
  تسویه (تبدیل به فاکتورِ خرید) مالکیتش از «امانی» به «خریداری‌شده» منتقل می‌شود.
"""

from __future__ import annotations

import datetime
import decimal
from dataclasses import dataclass

from sqlalchemy import func, select

from peecha.db.base import new_session
from peecha.db.models.accounting import DetailAccount
from peecha.db.models.commercial import CommercialDocument, CommercialDocumentLine
from peecha.db.models.inventory import (
    Batch, Item, LineTrackingEntry, LotMovement, SerialMovement, SerialNumber, StockDocument, StockDocumentLine, StockLedger,
    Warehouse,
)

_ZERO = decimal.Decimal(0)
_INBOUND_TYPES = ("RECEIPT", "RETURN_IN", "CONSIGNMENT_IN")
_OUTBOUND_TYPES = ("ISSUE", "RETURN_OUT", "CONSIGN_RETURN")
# سندهایی که ورودیِ کاملِ اطلاعاتِ ردیابی برایشان اجباری است (کاربر جایِ واردکردن دارد)
_REQUIRED_STOCK_TYPES = ("RECEIPT",)
_REQUIRED_COMMERCIAL_TYPES = ("PURCHASE_INVOICE", "CONSIGNMENT_IN")


@dataclass
class TrackingEntry:
    quantity: decimal.Decimal
    batch_no: str | None = None
    manufacture_date: datetime.date | None = None
    expiry_date: datetime.date | None = None
    serial_no: str | None = None
    # R228: انتخابِ منبع در خروج -- امانی/خریداری‌شدهٔ یک تامین‌کنندهٔ مشخص
    supplier_detail_account_id: int | None = None
    is_consignment: bool | None = None


@dataclass
class LotBalanceRow:
    item_id: int
    item_label: str
    warehouse_id: int
    warehouse_label: str
    batch_id: int | None
    batch_no: str | None
    manufacture_date: datetime.date | None
    expiry_date: datetime.date | None
    serial_id: int | None
    serial_no: str | None
    supplier_detail_account_id: int | None
    supplier_name: str | None
    is_consignment: bool
    quantity: decimal.Decimal


@dataclass
class TraceRow:
    movement_id: int
    created_at: datetime.datetime
    item_label: str
    warehouse_label: str
    batch_no: str | None
    serial_no: str | None
    supplier_name: str | None
    is_consignment: bool
    quantity: decimal.Decimal
    document_label: str


# ---------------------------------------------------------------------
# ورودیِ کاربر
# ---------------------------------------------------------------------
def item_tracking_flags(item_id: int) -> tuple[bool, bool, bool]:
    """(بچ، سریال، انقضا)"""
    with new_session() as session:
        item = session.get(Item, item_id)
        if item is None:
            return False, False, False
        return bool(item.track_batch), bool(item.track_serial), bool(item.track_expiry)


def has_pools(company_id: int, item_id: int) -> bool:
    """کالایی که (حتی بدونِ بچ/سریال) سابقهٔ ردیابی دارد -- مثلاً امانیِ تامین‌کننده."""
    with new_session() as session:
        return session.scalar(
            select(func.count()).select_from(LotMovement).where(
                LotMovement.company_id == company_id, LotMovement.item_id == item_id,
            )
        ) > 0


def expected_tracking(company_id: int, item_id: int, warehouse_id: int) -> list[TrackingEntry]:
    """موجودیِ دفتریِ هر بچ/سریال در انبار (برایِ انبارگردانی) -- بدونِ تفکیکِ تامین‌کننده."""
    totals: dict[tuple, decimal.Decimal] = {}
    for r in list_lot_balances(company_id, item_id=item_id, warehouse_id=warehouse_id):
        key = (r.batch_no, r.serial_no, r.expiry_date, r.manufacture_date)
        totals[key] = totals.get(key, _ZERO) + r.quantity
    return [
        TrackingEntry(q, batch_no=k[0], serial_no=k[1], expiry_date=k[2], manufacture_date=k[3])
        for k, q in totals.items() if q > 0
    ]


def is_tracked(item_id: int) -> bool:
    batch, serial, _expiry = item_tracking_flags(item_id)
    return batch or serial


def _line_owner(session, stock_line_id: int | None, commercial_line_id: int | None, cycle_count_line_id: int | None = None):
    if sum(x is not None for x in (stock_line_id, commercial_line_id, cycle_count_line_id)) != 1:
        raise ValueError("دقیقاً یکی از ردیفِ سندِ انبار، سندِ بازرگانی یا انبارگردانی باید مشخص باشد.")
    if cycle_count_line_id is not None:
        from peecha.db.models.inventory import CycleCountLine, CycleCountSession

        line = session.get(CycleCountLine, cycle_count_line_id)
        if line is None:
            raise ValueError("ردیفِ انبارگردانی نامعتبر است.")
        count = session.get(CycleCountSession, line.session_id)
        status = "DRAFT" if count.status_code == "COUNTING" else "POSTED"
        # در انبارگردانی مقدارِ شمارش همان جمعِ ردیف‌هایِ ردیابی است (سقف ندارد)
        return line, count.company_id, None, status
    if stock_line_id is not None:
        line = session.get(StockDocumentLine, stock_line_id)
        if line is None:
            raise ValueError("ردیفِ سند نامعتبر است.")
        doc = session.get(StockDocument, line.stock_document_id)
        return line, doc.company_id, line.quantity_base, doc.status_code
    line = session.get(CommercialDocumentLine, commercial_line_id)
    if line is None:
        raise ValueError("ردیفِ سند نامعتبر است.")
    doc = session.get(CommercialDocument, line.document_id)
    status = doc.status_code
    # R231: سفارشِ ثبتِ نهایی‌شده اثرِ انبار ندارد؛ انباردار تا پیش از تاییدِ رسید
    # بچ/سریال را وارد می‌کند (وگرنه تاییدِ رسید بن‌بست می‌شد).
    if status == "POSTED" and doc.document_type_code in ("PURCHASE_ORDER", "SALES_ORDER") and doc.warehouse_approved_at is None:
        status = "APPROVED"
    return line, doc.company_id, line.quantity_base, status


def _item_name(session, item: Item) -> str:
    account = session.get(DetailAccount, item.item_detail_account_id) if item.item_detail_account_id else None
    return (account.name or account.code) if account is not None else str(item.item_id)


def _validate_entries(item: Item, entries: list[TrackingEntry], total_base: decimal.Decimal, name: str = "") -> None:
    name = name or str(item.item_id)
    serials: set[str] = set()
    total = _ZERO
    for e in entries:
        quantity = decimal.Decimal(e.quantity)
        if quantity <= 0:
            raise ValueError("مقدارِ هر ردیفِ ردیابی باید بزرگ‌تر از صفر باشد.")
        if item.track_batch and not (e.batch_no or "").strip():
            raise ValueError(f"برایِ «{name}» شمارهٔ بچ الزامی است.")
        if item.track_expiry and e.expiry_date is None:
            raise ValueError(f"برایِ «{name}» تاریخِ انقضا الزامی است.")
        if e.manufacture_date and e.expiry_date and e.expiry_date < e.manufacture_date:
            raise ValueError("تاریخِ انقضا نمی‌تواند پیش از تاریخِ تولید باشد.")
        if item.track_serial:
            serial = (e.serial_no or "").strip()
            if not serial:
                raise ValueError(f"برایِ «{name}» شمارهٔ سریالِ هر عدد الزامی است.")
            if quantity != 1:
                raise ValueError("هر سریال دقیقاً یک عدد است.")
            if serial in serials:
                raise ValueError(f"سریالِ «{serial}» تکراری است.")
            serials.add(serial)
        total += quantity
    if total_base is not None and total > total_base:
        raise ValueError(f"جمعِ مقدارِ ردیابی ({total.normalize()}) از مقدارِ ردیف ({total_base.normalize()}) بیشتر است.")


def set_line_tracking(
    company_id: int, entries: list[TrackingEntry], *, stock_line_id: int | None = None,
    commercial_line_id: int | None = None, cycle_count_line_id: int | None = None,
) -> None:
    """جایگزینیِ کاملِ اطلاعاتِ ردیابیِ یک ردیف (مقادیر به واحدِ پایه)."""
    with new_session() as session:
        line, line_company_id, total_base, status_code = _line_owner(
            session, stock_line_id, commercial_line_id, cycle_count_line_id,
        )
        if line_company_id != company_id:
            raise ValueError("ردیفِ سند نامعتبر است.")
        if status_code in ("POSTED", "CANCELLED", "CORRECTED"):
            raise ValueError("اطلاعاتِ ردیابیِ سندِ ثبت‌شده/لغوشده قابلِ‌تغییر نیست.")
        item = session.get(Item, line.item_id)
        _validate_entries(item, entries, total_base, _item_name(session, item))
        session.query(LineTrackingEntry).filter(_owner_filter(stock_line_id, commercial_line_id, cycle_count_line_id)).delete()
        for e in entries:
            session.add(LineTrackingEntry(
                company_id=company_id, stock_line_id=stock_line_id, commercial_line_id=commercial_line_id,
                cycle_count_line_id=cycle_count_line_id,
                batch_no=(e.batch_no or "").strip() or None, manufacture_date=e.manufacture_date,
                expiry_date=e.expiry_date, serial_no=(e.serial_no or "").strip() or None,
                quantity=decimal.Decimal(e.quantity), supplier_detail_account_id=e.supplier_detail_account_id,
                is_consignment=e.is_consignment,
            ))
        session.commit()


def _owner_filter(stock_line_id=None, commercial_line_id=None, cycle_count_line_id=None):
    if stock_line_id is not None:
        return LineTrackingEntry.stock_line_id == stock_line_id
    if commercial_line_id is not None:
        return LineTrackingEntry.commercial_line_id == commercial_line_id
    return LineTrackingEntry.cycle_count_line_id == cycle_count_line_id


def get_line_tracking(
    *, stock_line_id: int | None = None, commercial_line_id: int | None = None, cycle_count_line_id: int | None = None,
) -> list[TrackingEntry]:
    with new_session() as session:
        return _own_entries(
            session, stock_line_id=stock_line_id, commercial_line_id=commercial_line_id, cycle_count_line_id=cycle_count_line_id,
        )


def _own_entries(session, *, stock_line_id=None, commercial_line_id=None, cycle_count_line_id=None) -> list[TrackingEntry]:
    q = select(LineTrackingEntry).where(_owner_filter(stock_line_id, commercial_line_id, cycle_count_line_id))
    return [
        TrackingEntry(
            e.quantity, e.batch_no, e.manufacture_date, e.expiry_date, e.serial_no,
            e.supplier_detail_account_id, e.is_consignment,
        )
        for e in session.scalars(q.order_by(LineTrackingEntry.entry_id))
    ]


def _commercial_entries(session, commercial_line_id: int) -> list[TrackingEntry]:
    """ورودیِ خودِ ردیف؛ وگرنه زنجیرهٔ مبدا (فاکتور ← سفارشِ رسیده/امانی)."""
    line_id, depth = commercial_line_id, 0
    while line_id is not None and depth < 6:
        entries = _own_entries(session, commercial_line_id=line_id)
        if entries:
            return entries
        line = session.get(CommercialDocumentLine, line_id)
        line_id, depth = (line.source_line_id if line is not None else None), depth + 1
    return []


def get_effective_commercial_tracking(commercial_line_id: int) -> list[TrackingEntry]:
    with new_session() as session:
        return _commercial_entries(session, commercial_line_id)


def _commercial_context(session, stock_line_id: int):
    """(ردیفِ بازرگانی، سندِ بازرگانی) برایِ ردیفِ سندِ انبارِ صادرشده از سندِ بازرگانی."""
    comm_line = session.scalar(
        select(CommercialDocumentLine).where(CommercialDocumentLine.stock_document_line_id == stock_line_id)
    )
    if comm_line is None:
        return None, None
    return comm_line, session.get(CommercialDocument, comm_line.document_id)


def _entries_for_stock_line(session, stock_line: StockDocumentLine) -> list[TrackingEntry]:
    entries = _own_entries(session, stock_line_id=stock_line.line_id)
    if entries:
        return entries
    comm_line, _doc = _commercial_context(session, stock_line.line_id)
    if comm_line is not None:
        return _commercial_entries(session, comm_line.line_id)
    return []


# ---------------------------------------------------------------------
# ثبت (پیش و پس از موتورِ انبار)
# ---------------------------------------------------------------------
def _directions(doc: StockDocument) -> list[tuple[str, int | None]]:
    t = doc.document_type_code
    if t == "TRANSFER":
        return [("OUT", doc.source_warehouse_id), ("IN", doc.destination_warehouse_id)]
    if t in _INBOUND_TYPES:
        return [("IN", doc.destination_warehouse_id)]
    if t in _OUTBOUND_TYPES:
        return [("OUT", doc.source_warehouse_id)]
    if t == "ADJUSTMENT":
        return [("IN", doc.destination_warehouse_id)] if doc.destination_warehouse_id else [("OUT", doc.source_warehouse_id)]
    return []


def validate_before_post(stock_document_id: int, company_id: int) -> None:
    """ورودیِ کاملِ بچ/سریال/انقضا برایِ رسیدِ انبار، فاکتورِ خرید و امانیِ ورودی."""
    with new_session() as session:
        doc = session.get(StockDocument, stock_document_id)
        if doc is None or doc.company_id != company_id:
            return
        if doc.document_type_code not in _INBOUND_TYPES:
            return
        for line in session.scalars(
            select(StockDocumentLine).where(StockDocumentLine.stock_document_id == stock_document_id)
            .order_by(StockDocumentLine.line_no)
        ):
            item = session.get(Item, line.item_id)
            if item is None or not (item.track_batch or item.track_serial):
                continue
            _comm_line, comm_doc = _commercial_context(session, line.line_id)
            required = (
                comm_doc.document_type_code in _REQUIRED_COMMERCIAL_TYPES if comm_doc is not None
                else doc.document_type_code in _REQUIRED_STOCK_TYPES
            )
            if not required:
                continue
            entries = _entries_for_stock_line(session, line)
            total = sum((decimal.Decimal(e.quantity) for e in entries), _ZERO)
            if total != line.quantity_base:
                kinds = "/".join(k for k, on in (("بچ", item.track_batch), ("انقضا", item.track_expiry), ("سریال", item.track_serial)) if on)
                raise ValueError(
                    f"اطلاعاتِ {kinds}ِ «{_item_name(session, item)}» کامل نیست -- {total.normalize()} از {line.quantity_base.normalize()} "
                    "وارد شده. از دکمهٔ «ردیابی» (بچ/سریال/انقضا) رویِ همان ردیف وارد کنید."
                )
            _validate_entries(item, entries, line.quantity_base, _item_name(session, item))
            if item.track_serial:
                for e in entries:
                    existing = session.scalar(select(SerialNumber).where(
                        SerialNumber.company_id == company_id, SerialNumber.item_id == item.item_id,
                        SerialNumber.serial_no == e.serial_no,
                    ))
                    if existing is not None and existing.status_code == "IN_STOCK":
                        raise ValueError(f"سریالِ «{e.serial_no}» از قبل در انبار موجود است.")


def _get_or_create_batch(session, company_id: int, item_id: int, e: TrackingEntry, supplier_id: int | None,
                         source_line_id: int | None) -> Batch | None:
    if not e.batch_no:
        return None
    batch = session.scalar(select(Batch).where(Batch.item_id == item_id, Batch.batch_no == e.batch_no))
    if batch is None:
        batch = Batch(
            company_id=company_id, item_id=item_id, batch_no=e.batch_no, manufacture_date=e.manufacture_date,
            expiry_date=e.expiry_date, supplier_detail_account_id=supplier_id, source_line_id=source_line_id,
        )
        session.add(batch)
        session.flush()
    else:
        batch.expiry_date = batch.expiry_date or e.expiry_date
        batch.manufacture_date = batch.manufacture_date or e.manufacture_date
        batch.supplier_detail_account_id = batch.supplier_detail_account_id or supplier_id
    return batch


def _pools(session, company_id: int, item_id: int, warehouse_id: int | None = None):
    """استخرهایِ مثبت: (warehouse, batch, serial, supplier, consignment) -> مقدار."""
    q = (
        select(
            LotMovement.warehouse_id, LotMovement.batch_id, LotMovement.serial_id,
            LotMovement.supplier_detail_account_id, LotMovement.is_consignment,
            func.sum(LotMovement.quantity_base), func.min(LotMovement.movement_id),
        )
        .where(LotMovement.company_id == company_id, LotMovement.item_id == item_id)
        .group_by(
            LotMovement.warehouse_id, LotMovement.batch_id, LotMovement.serial_id,
            LotMovement.supplier_detail_account_id, LotMovement.is_consignment,
        )
    )
    if warehouse_id is not None:
        q = q.where(LotMovement.warehouse_id == warehouse_id)
    return [r for r in session.execute(q).all() if r[5] > 0]


def _bin_pools(session, company_id: int, item_id: int, bin_id: int) -> dict[tuple, decimal.Decimal]:
    """R251: موجودیِ هر استخر در یک محل (از ستونِ محلِ حرکت‌ها)."""
    rows = session.execute(
        select(LotMovement.batch_id, LotMovement.serial_id, LotMovement.supplier_detail_account_id, LotMovement.is_consignment,
               func.sum(LotMovement.quantity_base))
        .where(LotMovement.company_id == company_id, LotMovement.item_id == item_id, LotMovement.bin_location_id == bin_id)
        .group_by(LotMovement.batch_id, LotMovement.serial_id, LotMovement.supplier_detail_account_id, LotMovement.is_consignment)).all()
    return {(r[0], r[1], r[2], r[3]): r[4] for r in rows if r[4] > 0}


def _allocate_out(session, company_id: int, item: Item, warehouse_id: int, quantity: decimal.Decimal,
                  entries: list[TrackingEntry], preferred_supplier_id: int | None, prefer_consignment: bool,
                  bin_id: int | None = None):
    """[(batch_id, serial_id, supplier_id, is_consignment, qty)] از استخرهایِ همین انبار.
    R251: اگر محلِ خروج معلوم است، اول از استخرهایِ موجود در همان محل (تا سقفِ موجودیِ محل)."""
    pools = _pools(session, company_id, item.item_id, warehouse_id)
    if not pools:
        return []
    in_bin = _bin_pools(session, company_id, item.item_id, bin_id) if bin_id is not None else {}
    batch_expiry = {
        b.batch_id: b.expiry_date for b in session.scalars(
            select(Batch).where(Batch.batch_id.in_({p[1] for p in pools if p[1] is not None}))
        )
    }
    remaining_by_pool = {(p[1], p[2], p[3], p[4]): p[5] for p in pools}
    first_seen = {(p[1], p[2], p[3], p[4]): p[6] for p in pools}
    result = []

    def take(keys, wanted):
        nonlocal result
        for key in keys:
            if wanted <= 0:
                break
            available = remaining_by_pool.get(key, _ZERO)
            if available <= 0:
                continue
            q = min(available, wanted)
            remaining_by_pool[key] = available - q
            result.append((key[0], key[1], key[2], key[3], q))
            wanted -= q
        return wanted

    def take_in_bin(keys, wanted):
        for key in keys:
            if wanted <= 0:
                break
            q = min(in_bin.get(key, _ZERO), remaining_by_pool.get(key, _ZERO), wanted)
            if q <= 0:
                continue
            remaining_by_pool[key] -= q
            in_bin[key] -= q
            result.append((key[0], key[1], key[2], key[3], q))
            wanted -= q
        return wanted

    def ordered(keys):
        return sorted(keys, key=lambda k: (
            0 if (preferred_supplier_id is not None and k[2] == preferred_supplier_id) else 1,
            0 if (prefer_consignment and k[3]) else 1,
            batch_expiry.get(k[0]) or datetime.date.max,
            first_seen[k],
        ))

    wanted = quantity
    for e in entries:
        keys = list(remaining_by_pool)
        if e.serial_no:
            serial = session.scalar(select(SerialNumber).where(
                SerialNumber.company_id == company_id, SerialNumber.item_id == item.item_id,
                SerialNumber.serial_no == e.serial_no,
            ))
            keys = [k for k in keys if serial is not None and k[1] == serial.serial_id]
        elif e.batch_no:
            batch = session.scalar(select(Batch).where(Batch.item_id == item.item_id, Batch.batch_no == e.batch_no))
            keys = [k for k in keys if batch is not None and k[0] == batch.batch_id]
        if e.supplier_detail_account_id is not None:
            keys = [k for k in keys if k[2] == e.supplier_detail_account_id]
        if e.is_consignment is not None:
            keys = [k for k in keys if bool(k[3]) == bool(e.is_consignment)]
        requested = min(decimal.Decimal(e.quantity), wanted)
        left = take(ordered(keys), requested)
        wanted -= requested - left
    if wanted > 0 and in_bin:
        wanted = take_in_bin(ordered(list(in_bin)), wanted)
    if wanted > 0:
        take(ordered(list(remaining_by_pool)), wanted)
    return result


def _set_serial_state(session, serial_id: int, line_id: int, to_status: str, from_wh: int | None, to_wh: int | None,
                      to_bin: int | None = None) -> None:
    serial = session.get(SerialNumber, serial_id)
    if serial is None:
        return
    session.add(SerialMovement(
        serial_id=serial_id, stock_document_line_id=line_id, from_status_code=serial.status_code,
        to_status_code=to_status, from_warehouse_id=from_wh, to_warehouse_id=to_wh,
    ))
    serial.status_code = to_status
    serial.current_warehouse_id = to_wh
    serial.current_bin_location_id = to_bin if to_status == "IN_STOCK" else None  # R252: محلِ فعلیِ سریال


def apply_after_post(stock_document_id: int, company_id: int) -> None:
    with new_session() as session:
        doc = session.get(StockDocument, stock_document_id)
        if doc is None or doc.company_id != company_id:
            return
        directions = _directions(doc)
        if not directions:
            return
        lines = session.scalars(
            select(StockDocumentLine).where(StockDocumentLine.stock_document_id == stock_document_id)
            .order_by(StockDocumentLine.line_no)
        ).all()
        # R251: محلِ هر جهت از دفترِ انبار (موتور پیش از این ثبت کرده است)
        ledger_bin = {
            (lid, wid, d): b for lid, wid, d, b in session.execute(
                select(StockLedger.stock_document_line_id, StockLedger.warehouse_id, StockLedger.movement_direction,
                       func.min(StockLedger.bin_location_id))
                .where(StockLedger.stock_document_line_id.in_([ln.line_id for ln in lines] or [-1]))
                .group_by(StockLedger.stock_document_line_id, StockLedger.warehouse_id, StockLedger.movement_direction)).all()
        }
        for line in lines:
            item = session.get(Item, line.item_id)
            if item is None:
                continue
            comm_line, comm_doc = _commercial_context(session, line.line_id)
            supplier_id = (
                comm_doc.counterparty_detail_account_id if comm_doc is not None else doc.counterparty_detail_account_id
            )
            is_consignment_in = comm_doc is not None and comm_doc.document_type_code == "CONSIGNMENT_IN"
            tracked = bool(item.track_batch or item.track_serial)
            # R228: انتخابِ منبع (تامین‌کننده/امانی) برایِ کالایِ بدونِ بچ/سریال هم خوانده می‌شود
            entries = _entries_for_stock_line(session, line)
            transfer_pools: list[tuple] = []
            for direction, warehouse_id in directions:
                if warehouse_id is None:
                    continue
                if direction == "OUT":
                    prefer_supplier = supplier_id if doc.document_type_code in ("RETURN_OUT", "CONSIGN_RETURN") else None
                    out_bin = ledger_bin.get((line.line_id, warehouse_id, "OUT"))
                    allocations = _allocate_out(
                        session, company_id, item, warehouse_id, line.quantity_base, entries,
                        prefer_supplier, prefer_consignment=doc.document_type_code == "CONSIGN_RETURN",
                        bin_id=out_bin if line.bin_location_id is not None else None,
                    )
                    for batch_id, serial_id, sup, cons, q in allocations:
                        session.add(LotMovement(
                            company_id=company_id, item_id=item.item_id, warehouse_id=warehouse_id, batch_id=batch_id,
                            serial_id=serial_id, supplier_detail_account_id=sup, is_consignment=cons,
                            stock_document_line_id=line.line_id, quantity_base=-q, bin_location_id=out_bin,
                        ))
                        if serial_id is not None and doc.document_type_code != "TRANSFER":
                            status = "RETURNED" if doc.document_type_code in ("RETURN_OUT", "CONSIGN_RETURN") else "SOLD"
                            _set_serial_state(session, serial_id, line.line_id, status, warehouse_id, None)
                    transfer_pools = allocations
                    continue
                # ورودی
                in_bin = ledger_bin.get((line.line_id, warehouse_id, "IN"))
                if doc.document_type_code == "TRANSFER":
                    for batch_id, serial_id, sup, cons, q in transfer_pools:
                        session.add(LotMovement(
                            company_id=company_id, item_id=item.item_id, warehouse_id=warehouse_id, batch_id=batch_id,
                            serial_id=serial_id, supplier_detail_account_id=sup, is_consignment=cons,
                            stock_document_line_id=line.line_id, quantity_base=q, bin_location_id=in_bin,
                        ))
                        if serial_id is not None:
                            _set_serial_state(session, serial_id, line.line_id, "IN_STOCK", directions[0][1], warehouse_id, in_bin)
                    continue
                total = sum((decimal.Decimal(e.quantity) for e in entries), _ZERO)
                if tracked and entries and total == line.quantity_base:
                    for e in entries:
                        batch = _get_or_create_batch(session, company_id, item.item_id, e, supplier_id, line.line_id)
                        serial_id = None
                        if e.serial_no:
                            serial = session.scalar(select(SerialNumber).where(
                                SerialNumber.company_id == company_id, SerialNumber.item_id == item.item_id,
                                SerialNumber.serial_no == e.serial_no,
                            ))
                            if serial is None:
                                serial = SerialNumber(
                                    company_id=company_id, item_id=item.item_id, serial_no=e.serial_no,
                                    batch_id=batch.batch_id if batch else None, current_warehouse_id=warehouse_id,
                                    current_bin_location_id=in_bin, status_code="IN_STOCK", source_line_id=line.line_id,
                                )
                                session.add(serial)
                                session.flush()
                                session.add(SerialMovement(
                                    serial_id=serial.serial_id, stock_document_line_id=line.line_id,
                                    from_status_code=None, to_status_code="IN_STOCK", to_warehouse_id=warehouse_id,
                                ))
                            else:
                                _set_serial_state(session, serial.serial_id, line.line_id, "IN_STOCK", None, warehouse_id, in_bin)
                            serial_id = serial.serial_id
                        session.add(LotMovement(
                            company_id=company_id, item_id=item.item_id, warehouse_id=warehouse_id,
                            batch_id=batch.batch_id if batch else None, serial_id=serial_id,
                            supplier_detail_account_id=supplier_id, is_consignment=is_consignment_in,
                            stock_document_line_id=line.line_id, quantity_base=decimal.Decimal(e.quantity), bin_location_id=in_bin,
                        ))
                elif is_consignment_in:
                    # کالایِ امانیِ بدونِ بچ/سریال: فقط با تامین‌کننده ردیابی می‌شود
                    session.add(LotMovement(
                        company_id=company_id, item_id=item.item_id, warehouse_id=warehouse_id,
                        supplier_detail_account_id=supplier_id, is_consignment=True,
                        stock_document_line_id=line.line_id, quantity_base=line.quantity_base, bin_location_id=in_bin,
                    ))
        session.commit()


def reverse_document_movements(stock_document_id: int, company_id: int) -> None:
    """برگشتِ کاملِ سند (inventory_engine.reverse_stock_document): حرکت‌هایِ ردیابی هم معکوس می‌شوند."""
    with new_session() as session:
        line_ids = list(session.scalars(
            select(StockDocumentLine.line_id).where(StockDocumentLine.stock_document_id == stock_document_id)
        ))
        if not line_ids:
            return
        for m in session.scalars(select(LotMovement).where(LotMovement.stock_document_line_id.in_(line_ids))).all():
            session.add(LotMovement(
                company_id=m.company_id, item_id=m.item_id, warehouse_id=m.warehouse_id, batch_id=m.batch_id,
                serial_id=m.serial_id, supplier_detail_account_id=m.supplier_detail_account_id,
                is_consignment=m.is_consignment, stock_document_line_id=m.stock_document_line_id,
                quantity_base=-m.quantity_base, bin_location_id=m.bin_location_id,
            ))
            if m.serial_id is not None:
                serial = session.get(SerialNumber, m.serial_id)
                if serial is not None:
                    serial.status_code = "IN_STOCK" if m.quantity_base < 0 else "RETURNED"
                    serial.current_warehouse_id = m.warehouse_id if m.quantity_base < 0 else None
                    serial.current_bin_location_id = m.bin_location_id if m.quantity_base < 0 else None
        session.commit()


def mirror_tracking_for_reversal(original_stock_document_id: int, reversal_stock_document_id: int) -> None:
    """سندِ برگشتیِ خودکار (حذفِ سندِ ثبت‌شده) دقیقاً همان بچ/سریال‌ها را برمی‌گرداند."""
    with new_session() as session:
        original_lines = session.scalars(
            select(StockDocumentLine).where(StockDocumentLine.stock_document_id == original_stock_document_id)
            .order_by(StockDocumentLine.line_no)
        ).all()
        reversal_lines = session.scalars(
            select(StockDocumentLine).where(StockDocumentLine.stock_document_id == reversal_stock_document_id)
            .order_by(StockDocumentLine.line_no)
        ).all()
        for orig, rev in zip(original_lines, reversal_lines):
            for m in session.scalars(
                select(LotMovement).where(LotMovement.stock_document_line_id == orig.line_id, LotMovement.quantity_base > 0)
            ):
                batch = session.get(Batch, m.batch_id) if m.batch_id else None
                serial = session.get(SerialNumber, m.serial_id) if m.serial_id else None
                if batch is None and serial is None:
                    continue
                session.add(LineTrackingEntry(
                    company_id=m.company_id, stock_line_id=rev.line_id, batch_no=batch.batch_no if batch else None,
                    expiry_date=batch.expiry_date if batch else None, serial_no=serial.serial_no if serial else None,
                    quantity=m.quantity_base,
                ))
        session.commit()


def settle_consignment(invoice_document_id: int, company_id: int) -> None:
    """تسویهٔ امانیِ ورودی (فاکتورِ خرید از رویِ امانی): مالکیتِ همان مقدار از
    «امانیِ تامین‌کننده» به «خریداری‌شده» منتقل می‌شود (بچ/سریال/انبار حفظ می‌شود)."""
    with new_session() as session:
        invoice = session.get(CommercialDocument, invoice_document_id)
        if invoice is None or invoice.company_id != company_id:
            return
        for line in session.scalars(
            select(CommercialDocumentLine).where(CommercialDocumentLine.document_id == invoice_document_id)
        ).all():
            if line.source_line_id is None:
                continue
            wanted = line.quantity_base
            pools = [
                p for p in _pools(session, company_id, line.item_id)
                if p[4] and p[3] == invoice.counterparty_detail_account_id
            ]
            pools.sort(key=lambda p: p[6])
            for warehouse_id, batch_id, serial_id, supplier_id, _cons, available, _first in pools:
                if wanted <= 0:
                    break
                q = min(available, wanted)
                for sign, cons in ((-1, True), (1, False)):
                    session.add(LotMovement(
                        company_id=company_id, item_id=line.item_id, warehouse_id=warehouse_id, batch_id=batch_id,
                        serial_id=serial_id, supplier_detail_account_id=supplier_id, is_consignment=cons,
                        commercial_line_id=line.line_id, quantity_base=sign * q,
                    ))
                wanted -= q
        session.commit()


# ---------------------------------------------------------------------
# گزارش و ردیابی
# ---------------------------------------------------------------------
def _labels(session, company_id: int):
    items = dict(session.execute(
        select(Item.item_id, func.concat(DetailAccount.code, " — ", func.coalesce(DetailAccount.name, "")))
        .join(DetailAccount, DetailAccount.detail_account_id == Item.item_detail_account_id)
        .where(Item.company_id == company_id)
    ).all())
    warehouses = {w.warehouse_id: w.name for w in session.scalars(select(Warehouse).where(Warehouse.company_id == company_id))}
    return items, warehouses


def list_lot_balances(
    company_id: int, item_id: int | None = None, warehouse_id: int | None = None,
    supplier_detail_account_id: int | None = None, consignment_only: bool = False,
    expiring_before: datetime.date | None = None,
) -> list[LotBalanceRow]:
    with new_session() as session:
        q = (
            select(
                LotMovement.item_id, LotMovement.warehouse_id, LotMovement.batch_id, LotMovement.serial_id,
                LotMovement.supplier_detail_account_id, LotMovement.is_consignment, func.sum(LotMovement.quantity_base),
            )
            .where(LotMovement.company_id == company_id)
            .group_by(
                LotMovement.item_id, LotMovement.warehouse_id, LotMovement.batch_id, LotMovement.serial_id,
                LotMovement.supplier_detail_account_id, LotMovement.is_consignment,
            )
        )
        if item_id is not None:
            q = q.where(LotMovement.item_id == item_id)
        if warehouse_id is not None:
            q = q.where(LotMovement.warehouse_id == warehouse_id)
        if supplier_detail_account_id is not None:
            q = q.where(LotMovement.supplier_detail_account_id == supplier_detail_account_id)
        if consignment_only:
            q = q.where(LotMovement.is_consignment.is_(True))
        rows = [r for r in session.execute(q).all() if r[6] > 0]
        items, warehouses = _labels(session, company_id)
        batches = {b.batch_id: b for b in session.scalars(select(Batch).where(Batch.batch_id.in_({r[2] for r in rows if r[2]})))}
        serials = {s.serial_id: s for s in session.scalars(select(SerialNumber).where(SerialNumber.serial_id.in_({r[3] for r in rows if r[3]})))}
        suppliers = dict(session.execute(
            select(DetailAccount.detail_account_id, DetailAccount.name).where(DetailAccount.detail_account_id.in_({r[4] for r in rows if r[4]}))
        ).all())
        result = []
        for it, wh, b, s, sup, cons, qty in rows:
            batch = batches.get(b)
            if expiring_before is not None and (batch is None or batch.expiry_date is None or batch.expiry_date > expiring_before):
                continue
            result.append(LotBalanceRow(
                it, items.get(it, str(it)), wh, warehouses.get(wh, str(wh)), b, batch.batch_no if batch else None,
                batch.manufacture_date if batch else None, batch.expiry_date if batch else None,
                s, serials[s].serial_no if s in serials else None, sup, suppliers.get(sup), bool(cons), qty,
            ))
        result.sort(key=lambda r: (r.item_label, r.expiry_date or datetime.date.max, r.batch_no or "", r.serial_no or ""))
        return result


def trace(company_id: int, *, batch_no: str | None = None, serial_no: str | None = None,
          item_id: int | None = None, supplier_detail_account_id: int | None = None) -> list[TraceRow]:
    """تاریخچهٔ کاملِ حرکتِ یک بچ/سریال/کالایِ یک تامین‌کننده -- از ورود تا خروج."""
    with new_session() as session:
        q = select(LotMovement).where(LotMovement.company_id == company_id)
        if item_id is not None:
            q = q.where(LotMovement.item_id == item_id)
        if batch_no:
            batch_ids = list(session.scalars(select(Batch.batch_id).where(Batch.company_id == company_id, Batch.batch_no == batch_no)))
            q = q.where(LotMovement.batch_id.in_(batch_ids or [-1]))
        if serial_no:
            serial_ids = list(session.scalars(select(SerialNumber.serial_id).where(
                SerialNumber.company_id == company_id, SerialNumber.serial_no == serial_no,
            )))
            q = q.where(LotMovement.serial_id.in_(serial_ids or [-1]))
        if supplier_detail_account_id is not None:
            q = q.where(LotMovement.supplier_detail_account_id == supplier_detail_account_id)
        movements = session.scalars(q.order_by(LotMovement.movement_id)).all()
        items, warehouses = _labels(session, company_id)
        result = []
        for m in movements:
            batch = session.get(Batch, m.batch_id) if m.batch_id else None
            serial = session.get(SerialNumber, m.serial_id) if m.serial_id else None
            supplier = session.get(DetailAccount, m.supplier_detail_account_id) if m.supplier_detail_account_id else None
            result.append(TraceRow(
                m.movement_id, m.created_at, items.get(m.item_id, ""), warehouses.get(m.warehouse_id, ""),
                batch.batch_no if batch else None, serial.serial_no if serial else None,
                supplier.name if supplier else None, m.is_consignment, m.quantity_base, _document_label(session, m),
            ))
        return result


_STOCK_TITLES = {
    "RECEIPT": "رسیدِ انبار", "ISSUE": "حوالهٔ انبار", "TRANSFER": "انتقال", "RETURN_IN": "برگشت از فروش",
    "RETURN_OUT": "برگشت به تامین‌کننده", "ADJUSTMENT": "اصلاحِ انبار", "CONSIGNMENT_IN": "امانیِ ورودی",
}


def _document_label(session, m: LotMovement) -> str:
    if m.stock_document_line_id is not None:
        line = session.get(StockDocumentLine, m.stock_document_line_id)
        doc = session.get(StockDocument, line.stock_document_id) if line else None
        if doc is not None:
            return f"{_STOCK_TITLES.get(doc.document_type_code, doc.document_type_code)} {doc.document_no}"
    if m.commercial_line_id is not None:
        line = session.get(CommercialDocumentLine, m.commercial_line_id)
        doc = session.get(CommercialDocument, line.document_id) if line else None
        if doc is not None:
            return f"تسویهٔ امانی -- فاکتورِ خرید {doc.document_no}"
    return ""
