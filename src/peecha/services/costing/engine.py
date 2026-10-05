"""موتورِ بهایِ تمام‌شده -- تنها نقطهٔ ساخت/مصرفِ لایه و ثبتِ تخصیصِ بهایِ خروج (R257).

همهٔ توابع درونِ session و تراکنشِ خودِ inventory_engine.post_stock_document اجرا می‌شوند (نه تراکنشِ جدا)،
تا ثبتِ دفترِ انبار، لایه‌ها، تخصیص و سندِ حسابداری با هم موفق یا با هم برگشت بخورند.

هم‌زمانی: پیش از مصرف، یک قفلِ تراکنشیِ PostgreSQL رویِ (کالا، انبار) گرفته می‌شود و لایه‌ها هم
FOR UPDATE خوانده می‌شوند؛ قیدِ دیتابیسیِ remaining_quantity BETWEEN 0 AND original_quantity
هم آخرین سدِ مصرفِ بیش از موجودیِ لایه است.
"""

from __future__ import annotations

import datetime
import decimal
from types import SimpleNamespace

from sqlalchemy import func, select, text

from peecha.db.models.inventory import (
    Batch, CompanyCostingSettings, CostAllocation, CostingMethod, CostLayer, Item, LotMovement, SerialNumber, StockBalance,
    StockLedger,
)
from peecha.services.costing import strategies

_ZERO = decimal.Decimal(0)
NEGATIVE_POLICIES = {
    "WAREHOUSE": "پیروی از تنظیمِ هر انبار (رفتارِ قبلی)",
    "BLOCK": "مسدود -- خروجِ بیش از موجودی مجاز نیست",
    "PENDING": "مجاز، بهایِ نهایی «در انتظار» تا محاسبهٔ مجدد",
    "FALLBACK": "مجاز با آخرین بهایِ معتبر",
}
# روش‌هایی که جدولشان آماده است ولی موتورشان در تحویلِ بعد فعال می‌شود
NOT_YET_AVAILABLE: dict[str, str] = {}
STATUS_LABELS = {
    "CALCULATED": "محاسبه‌شده", "PENDING": "در انتظار", "RECALCULATION_REQUIRED": "نیازمندِ محاسبهٔ مجدد", "ERROR": "خطا",
}


def company_settings(session, company_id: int) -> SimpleNamespace:
    row = session.get(CompanyCostingSettings, company_id)
    method = None
    if row is not None:
        m = session.get(CostingMethod, row.default_costing_method_id)
        method = m.code if m is not None else None
    return SimpleNamespace(
        method=method or "WEIGHTED_AVERAGE",
        negative_policy=(row.negative_stock_policy if row is not None else None) or "WAREHOUSE",
        nifo_sources=[s for s in ((row.nifo_price_sources if row is not None else "") or "").split(",") if s],
        allow_item_override=row.allow_item_override if row is not None else True,
    )


def effective_method(item: Item, company_method: str | None) -> str:
    return item.costing_method_code or company_method or "WEIGHTED_AVERAGE"


def lock_item_warehouse(session, item_id: int, warehouse_id: int) -> None:
    """قفلِ تراکنشی (تا پایانِ همین تراکنش) -- دو خروجِ هم‌زمانِ همان کالا/انبار پشتِ‌سرِهم اجرا می‌شوند."""
    session.execute(text("SELECT pg_advisory_xact_lock(:i, :w)"), {"i": int(item_id), "w": int(warehouse_id)})


def create_layer(session, *, company_id: int, item_id: int, warehouse_id: int, ledger_id: int, quantity: decimal.Decimal,
                 unit_cost: decimal.Decimal, receipt_date: datetime.date, source_type: str, source_line_id: int | None,
                 batch_id: int | None = None, serial_id: int | None = None) -> CostLayer:
    layer = CostLayer(
        company_id=company_id, item_id=item_id, warehouse_id=warehouse_id, stock_ledger_id=ledger_id,
        received_at=datetime.datetime.combine(receipt_date, datetime.time.min), receipt_date=receipt_date,
        original_quantity=quantity, remaining_quantity=quantity, unit_cost=unit_cost, source_type_code=source_type,
        source_line_id=source_line_id, batch_id=batch_id, serial_id=serial_id, status_code="OPEN",
    )
    session.add(layer)
    session.flush()
    return layer


def _open_layers(session, item_id: int, warehouse_id: int) -> list[CostLayer]:
    # ترتیبِ ثابتِ قفل (شناسه) برایِ پیشگیری از Deadlock؛ ترتیبِ مصرف را راهبرد تعیین می‌کند
    return list(session.scalars(
        select(CostLayer).where(CostLayer.item_id == item_id, CostLayer.warehouse_id == warehouse_id,
                                CostLayer.remaining_quantity > 0)
        .order_by(CostLayer.cost_layer_id).with_for_update()))


def ensure_opening_layer(session, company_id: int, item_id: int, warehouse_id: int) -> CostLayer | None:
    """موجودیِ فعلی که لایه ندارد (مثلاً پیش از انتخابِ روشِ لایه‌ای) → یک لایهٔ OPENING_BALANCE با میانگینِ فعلی،
    با قدیمی‌ترین تاریخ تا در FIFO اول مصرف شود. قابلِ ردیابی: source_type_code و ردیفِ دفترِ انبارِ مرجع."""
    on_hand, value = session.execute(
        select(func.coalesce(func.sum(StockBalance.quantity_on_hand), 0),
               func.coalesce(func.sum(StockBalance.quantity_on_hand * StockBalance.average_unit_cost), 0))
        .where(StockBalance.item_id == item_id, StockBalance.warehouse_id == warehouse_id, StockBalance.quantity_on_hand > 0)
    ).one()
    layered = session.scalar(select(func.coalesce(func.sum(CostLayer.remaining_quantity), 0)).where(
        CostLayer.item_id == item_id, CostLayer.warehouse_id == warehouse_id)) or _ZERO
    gap = decimal.Decimal(on_hand) - decimal.Decimal(layered)
    if gap <= 0:
        return None
    ref = session.execute(
        select(StockLedger.ledger_id, StockLedger.movement_date).where(
            StockLedger.item_id == item_id, StockLedger.warehouse_id == warehouse_id, StockLedger.movement_direction == "IN")
        .order_by(StockLedger.movement_date, StockLedger.ledger_id).limit(1)).first()
    if ref is None:
        return None
    unit_cost = (decimal.Decimal(value) / decimal.Decimal(on_hand)) if on_hand else _ZERO
    return create_layer(session, company_id=company_id, item_id=item_id, warehouse_id=warehouse_id, ledger_id=ref[0],
                        quantity=gap, unit_cost=unit_cost, receipt_date=ref[1], source_type="OPENING_BALANCE",
                        source_line_id=None)


def line_lots(session, company_id: int, item_id: int, stock_line) -> list[tuple[int | None, int | None, decimal.Decimal]]:
    """(batch_id, serial_id, مقدار)ِ مشخص‌شده برایِ ردیف پیش از ثبت (ورودیِ ردیابیِ خودِ ردیف یا ردیفِ بازرگانی)."""
    from peecha.services import lot_tracking

    out = []
    for e in lot_tracking._entries_for_stock_line(session, stock_line):
        serial_id = batch_id = None
        if e.serial_no:
            serial = session.scalar(select(SerialNumber).where(
                SerialNumber.company_id == company_id, SerialNumber.item_id == item_id, SerialNumber.serial_no == e.serial_no))
            serial_id = serial.serial_id if serial is not None else None
            batch_id = serial.batch_id if serial is not None else None
        elif e.batch_no:
            batch = session.scalar(select(Batch).where(Batch.item_id == item_id, Batch.batch_no == e.batch_no))
            batch_id = batch.batch_id if batch is not None else None
        if serial_id is not None or batch_id is not None:
            out.append((batch_id, serial_id, decimal.Decimal(e.quantity)))
    return out


def consume_layers(session, *, company_id: int, item_id: int, warehouse_id: int, quantity: decimal.Decimal, method: str,
                   preferred_source_line_id: int | None = None,
                   lots: list[tuple[int | None, int | None, decimal.Decimal]] | None = None,
                   ) -> tuple[list[strategies.Pick], decimal.Decimal]:
    """مصرفِ لایه‌ها طبقِ راهبردِ روش؛ preferred_source_line_id (برگشت به تامین‌کننده) لایهٔ همان رسید را اول مصرف می‌کند.
    lots (شناساییِ ویژه): لایه‌هایِ همان سریال/بچ اول -- به ترتیبِ راهبرد درونِ همان بچ.
    خروجی: (انتخاب‌ها، مقدارِ تأمین‌نشده -- کمبود)."""
    lock_item_warehouse(session, item_id, warehouse_id)
    ensure_opening_layer(session, company_id, item_id, warehouse_id)
    layers = _open_layers(session, item_id, warehouse_id)
    strategy = strategies.get_strategy(method)
    picks: list[strategies.Pick] = []
    remaining = quantity
    if preferred_source_line_id is not None:
        own = [lyr for lyr in layers if lyr.source_line_id == preferred_source_line_id]
        picks, remaining = strategies.Fifo().pick(own, remaining)
        layers = [lyr for lyr in layers if lyr not in own]
    for batch_id, serial_id, lot_qty in lots or []:
        if remaining <= 0:
            break
        own = [lyr for lyr in layers if (lyr.serial_id == serial_id if serial_id is not None else lyr.batch_id == batch_id)
               and lyr.remaining_quantity > sum((p.quantity for p in picks if p.layer is lyr), _ZERO)]
        avail = [strategies.Pick(lyr, lyr.remaining_quantity - sum((p.quantity for p in picks if p.layer is lyr), _ZERO))
                 for lyr in own]
        want = min(lot_qty, remaining)
        for cand in strategy.order([a.layer for a in avail]):
            if want <= 0:
                break
            free = next(a.quantity for a in avail if a.layer is cand)
            take = min(free, want)
            picks.append(strategies.Pick(cand, take))
            want -= take
            remaining -= take
    if remaining > 0:
        used = {}
        for p in picks:
            used[id(p.layer)] = used.get(id(p.layer), _ZERO) + p.quantity
        rest = [lyr for lyr in layers if lyr.remaining_quantity > used.get(id(lyr), _ZERO)]
        for cand in strategy.order(rest):
            if remaining <= 0:
                break
            take = min(cand.remaining_quantity - used.get(id(cand), _ZERO), remaining)
            picks.append(strategies.Pick(cand, take))
            remaining -= take
    for p in picks:
        p.layer.remaining_quantity -= p.quantity
        if p.layer.remaining_quantity == 0:
            p.layer.status_code = "CONSUMED"
    session.flush()
    sync_balance_average(session, item_id, warehouse_id)  # R259
    return picks, remaining


def sync_balance_average(session, item_id: int, warehouse_id: int) -> None:
    """روش‌هایِ لایه‌ای: میانگینِ ماندهٔ انبار = ارزشِ لایه‌هایِ باز / مقدارشان، تا ارزشِ مانده با حسابداری یکی بماند."""
    qty, value = session.execute(
        select(func.coalesce(func.sum(CostLayer.remaining_quantity), 0),
               func.coalesce(func.sum(CostLayer.remaining_quantity * CostLayer.unit_cost), 0))
        .where(CostLayer.item_id == item_id, CostLayer.warehouse_id == warehouse_id, CostLayer.remaining_quantity > 0)).one()
    if not qty:
        return
    avg = decimal.Decimal(value) / decimal.Decimal(qty)
    for bal in session.scalars(select(StockBalance).where(StockBalance.item_id == item_id, StockBalance.warehouse_id == warehouse_id)):
        bal.average_unit_cost = avg


def negative_outcome(policy: str, warehouse_allows_negative: bool, shortage: decimal.Decimal) -> str | None:
    """None = مجاز نیست (خطا)؛ وگرنه وضعیتِ بهایِ بخشِ کمبود."""
    if shortage <= 0:
        return "CALCULATED"
    if policy == "BLOCK":
        return None
    if policy == "PENDING":
        return "PENDING"
    if policy == "FALLBACK":
        return "CALCULATED"
    return "CALCULATED" if warehouse_allows_negative else None


def record_allocation(session, *, company_id: int, stock_line_id: int, item_id: int, warehouse_id: int, method: str,
                      quantity: decimal.Decimal, unit_cost: decimal.Decimal, movement_date: datetime.date,
                      layer_id: int | None = None, status: str = "CALCULATED", note: str | None = None) -> None:
    if quantity <= 0:
        return
    session.add(CostAllocation(
        company_id=company_id, stock_document_line_id=stock_line_id, item_id=item_id, warehouse_id=warehouse_id,
        cost_layer_id=layer_id, costing_method_code=method, quantity_base=quantity, unit_cost=unit_cost or _ZERO,
        movement_date=movement_date, costing_status_code=status, note=note))


def split_layers_by_lot(stock_document_id: int) -> int:
    """پس از ثبتِ ردیابی (apply_after_post): لایهٔ تازهٔ بی‌بچ/سریالِ هر ردیفِ ورودی به تفکیکِ بچ/سریالِ واقعی شکسته
    می‌شود (هنوز مصرف‌نشده، پس بها و مقدارِ کل عوض نمی‌شود) -- پایهٔ شناساییِ ویژه و بهایِ هر بچ/سریال."""
    from peecha.db.base import new_session
    from peecha.db.models.inventory import StockDocumentLine

    split = 0
    with new_session() as session:
        line_ids = list(session.scalars(select(StockDocumentLine.line_id).where(
            StockDocumentLine.stock_document_id == stock_document_id)))
        for line_id in line_ids:
            moves = session.execute(
                select(LotMovement.warehouse_id, LotMovement.batch_id, LotMovement.serial_id, func.sum(LotMovement.quantity_base))
                .where(LotMovement.stock_document_line_id == line_id, LotMovement.quantity_base > 0,
                       (LotMovement.batch_id.is_not(None)) | (LotMovement.serial_id.is_not(None)))
                .group_by(LotMovement.warehouse_id, LotMovement.batch_id, LotMovement.serial_id)).all()
            if not moves:
                continue
            fresh = list(session.scalars(select(CostLayer).where(
                CostLayer.source_line_id == line_id, CostLayer.batch_id.is_(None), CostLayer.serial_id.is_(None),
                CostLayer.remaining_quantity == CostLayer.original_quantity).order_by(CostLayer.cost_layer_id).with_for_update()))
            for wh_id, batch_id, serial_id, qty in moves:
                qty = decimal.Decimal(qty)
                for layer in [lyr for lyr in fresh if lyr.warehouse_id == wh_id]:
                    if qty <= 0 or layer.original_quantity <= 0:
                        continue
                    take = min(qty, layer.original_quantity)
                    if take == layer.original_quantity:
                        layer.batch_id, layer.serial_id = batch_id, serial_id
                        fresh.remove(layer)
                    else:
                        layer.original_quantity -= take
                        layer.remaining_quantity -= take
                        session.add(CostLayer(
                            company_id=layer.company_id, item_id=layer.item_id, warehouse_id=layer.warehouse_id,
                            stock_ledger_id=layer.stock_ledger_id, received_at=layer.received_at, receipt_date=layer.receipt_date,
                            original_quantity=take, remaining_quantity=take, unit_cost=layer.unit_cost,
                            source_type_code=layer.source_type_code, source_line_id=layer.source_line_id,
                            batch_id=batch_id, serial_id=serial_id, status_code="OPEN"))
                    qty -= take
                    split += 1
        session.commit()
    return split


def lot_issue_cost(session, source_line_id: int, serial_ids: list[int], batch_ids: list[int]) -> decimal.Decimal | None:
    """بهایِ واقعیِ همان سریال/بچی که در خروجِ مرجع مصرف شده بود (برگشت از فروشِ کالایِ ردیابی‌شده)."""
    q = (select(func.sum(CostAllocation.quantity_base * CostAllocation.unit_cost), func.sum(CostAllocation.quantity_base))
         .join(CostLayer, CostLayer.cost_layer_id == CostAllocation.cost_layer_id)
         .where(CostAllocation.stock_document_line_id == source_line_id))
    if serial_ids:
        q = q.where(CostLayer.serial_id.in_(serial_ids))
    elif batch_ids:
        q = q.where(CostLayer.batch_id.in_(batch_ids))
    else:
        return None
    value, qty = session.execute(q).one()
    return (decimal.Decimal(value) / decimal.Decimal(qty)) if qty else None
