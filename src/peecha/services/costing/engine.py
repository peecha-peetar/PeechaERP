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
    CompanyCostingSettings, CostAllocation, CostingMethod, CostLayer, Item, StockBalance, StockLedger,
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
NOT_YET_AVAILABLE = {"NIFO": "روشِ بهایِ جایگزینی (NIFO) در نسخهٔ بعد (R258) فعال می‌شود."}
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


def consume_layers(session, *, company_id: int, item_id: int, warehouse_id: int, quantity: decimal.Decimal, method: str,
                   preferred_source_line_id: int | None = None) -> tuple[list[strategies.Pick], decimal.Decimal]:
    """مصرفِ لایه‌ها طبقِ راهبردِ روش؛ preferred_source_line_id (برگشت به تامین‌کننده) لایهٔ همان رسید را اول مصرف می‌کند.
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
    if remaining > 0:
        more, remaining = strategy.pick(layers, remaining)
        picks += more
    for p in picks:
        p.layer.remaining_quantity -= p.quantity
        if p.layer.remaining_quantity == 0:
            p.layer.status_code = "CONSUMED"
    session.flush()
    return picks, remaining


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
