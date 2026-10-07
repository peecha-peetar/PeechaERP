"""ارزش‌گذاری موجودی، اطلاعات بهای کالا و تاریخچهٔ بها — R259 (فقط خواندنی).

مبنای ارزش در هر تاریخ همان دفتر انبار (inv.stock_ledger: ورود منهای خروج با بهای ثبت‌شده) به‌اضافهٔ
لاگ اصلاح بهای تاریخ‌دار (inv.cost_adjustment_log) است — همان مبنایی که سند حسابداری موجودی دارد؛
سیستم موجودی موازی ساخته نمی‌شود. ریز بچ/سریال ارزش جاری از لایه‌های باز (روش‌های لایه‌ای).
"""

from __future__ import annotations

import datetime
import decimal
from types import SimpleNamespace

from sqlalchemy import case, func, select

from peecha.db.base import new_session
from peecha.db.models.inventory import (
    Batch, CostAdjustmentLog, CostAllocation, CostLayer, Item, SerialNumber, StockDocument, StockDocumentLine, StockLedger,
)
from peecha.services.costing import engine as costing_engine
from peecha.services.costing import replacement as costing_replacement
from peecha.services.costing import strategies

_ZERO = decimal.Decimal(0)


def positions(company_id: int, as_of: datetime.date | None = None, item_id: int | None = None,
              warehouse_id: int | None = None) -> dict[tuple[int, int], tuple[decimal.Decimal, decimal.Decimal]]:
    """(کالا، انبار) → (مقدار، ارزش) تا پایان as_of از دفتر انبار + اصلاحات بهای تاریخ‌دار."""
    as_of = as_of or datetime.date.today()
    sign = case((StockLedger.movement_direction == "IN", 1), else_=-1)
    with new_session() as session:
        q = (select(StockLedger.item_id, StockLedger.warehouse_id, func.sum(sign * StockLedger.quantity_base),
                    func.sum(sign * StockLedger.quantity_base * func.coalesce(StockLedger.unit_cost, 0)))
             .where(StockLedger.company_id == company_id, StockLedger.movement_date <= as_of)
             .group_by(StockLedger.item_id, StockLedger.warehouse_id))
        a = (select(CostAdjustmentLog.item_id, CostAdjustmentLog.warehouse_id, func.sum(CostAdjustmentLog.inventory_value_delta))
             .where(CostAdjustmentLog.company_id == company_id, CostAdjustmentLog.adjusted_on <= as_of)
             .group_by(CostAdjustmentLog.item_id, CostAdjustmentLog.warehouse_id))
        if item_id is not None:
            q, a = q.where(StockLedger.item_id == item_id), a.where(CostAdjustmentLog.item_id == item_id)
        if warehouse_id is not None:
            q, a = q.where(StockLedger.warehouse_id == warehouse_id), a.where(CostAdjustmentLog.warehouse_id == warehouse_id)
        out = {(i, w): [decimal.Decimal(qty or 0), decimal.Decimal(val or 0)] for i, w, qty, val in session.execute(q).all()}
        for i, w, delta in session.execute(a).all():
            out.setdefault((i, w), [_ZERO, _ZERO])[1] += decimal.Decimal(delta or 0)
    return {k: (v[0], v[1].quantize(decimal.Decimal("0.01"))) for k, v in out.items()}


def lot_values(company_id: int, item_id: int | None = None, warehouse_id: int | None = None) -> list[SimpleNamespace]:
    """ارزش جاری لایه‌های باز به تفکیک کالا/انبار/بچ/سریال (روش‌های لایه‌ای)."""
    with new_session() as session:
        q = (select(CostLayer.item_id, CostLayer.warehouse_id, CostLayer.batch_id, CostLayer.serial_id,
                    func.sum(CostLayer.remaining_quantity), func.sum(CostLayer.remaining_quantity * CostLayer.unit_cost))
             .where(CostLayer.company_id == company_id, CostLayer.remaining_quantity > 0)
             .group_by(CostLayer.item_id, CostLayer.warehouse_id, CostLayer.batch_id, CostLayer.serial_id))
        if item_id is not None:
            q = q.where(CostLayer.item_id == item_id)
        if warehouse_id is not None:
            q = q.where(CostLayer.warehouse_id == warehouse_id)
        rows = session.execute(q).all()
        batches = dict(session.execute(select(Batch.batch_id, Batch.batch_no).where(
            Batch.batch_id.in_({r[2] for r in rows if r[2]} or {-1}))).all())
        serials = dict(session.execute(select(SerialNumber.serial_id, SerialNumber.serial_no).where(
            SerialNumber.serial_id.in_({r[3] for r in rows if r[3]} or {-1}))).all())
    return [SimpleNamespace(item_id=i, warehouse_id=w, batch_no=batches.get(b, ""), serial_no=serials.get(s, ""),
                            quantity=qty, unit_cost=(val / qty) if qty else _ZERO, value=val)
            for i, w, b, s, qty, val in rows]


def effective_method(company_id: int, item_id: int) -> str:
    with new_session() as session:
        item = session.get(Item, item_id)
        return costing_engine.effective_method(item, costing_engine.company_settings(session, company_id).method)


def last_purchase_cost(company_id: int, item_id: int) -> decimal.Decimal | None:
    with new_session() as session:
        return costing_replacement._last_receipt(session, item_id, None, datetime.date.today())


def item_cost_info(company_id: int, item_id: int) -> SimpleNamespace:
    """بخش «اطلاعات بها» در فرم کالا: بهای جاری/میانگین/آخرین خرید/جایگزینی، ارزش موجودی و روش."""
    pos = positions(company_id, item_id=item_id)
    qty = sum((v[0] for v in pos.values()), _ZERO)
    value = sum((v[1] for v in pos.values()), _ZERO)
    method = effective_method(company_id, item_id)
    current = None
    if strategies.is_layer_method(method):
        with new_session() as session:
            layers = list(session.scalars(select(CostLayer).where(
                CostLayer.item_id == item_id, CostLayer.remaining_quantity > 0)))
        nxt = strategies.get_strategy(method).order(layers)
        current = nxt[0].unit_cost if nxt else None  # بهایِ نخستین لایه‌ای که خروجِ بعدی از آن می‌آید
    average = (value / qty) if qty > 0 else None
    replacement = costing_replacement.get_replacement_cost(company_id, item_id)
    with new_session() as session:
        pending = session.scalar(select(func.count()).select_from(CostAllocation).where(
            CostAllocation.item_id == item_id, CostAllocation.costing_status_code != "CALCULATED")) or 0
    return SimpleNamespace(
        method=method, method_label=strategies.METHOD_LABELS.get(method, method), quantity=qty, inventory_value=value,
        current_cost=current if current is not None else average, average_cost=average,
        last_purchase_cost=last_purchase_cost(company_id, item_id),
        replacement_cost=replacement[0] if replacement else None,
        replacement_source=costing_replacement.SOURCES.get(replacement[1], "") if replacement else "",
        pending_allocations=pending)


def cost_history(company_id: int, item_id: int | None = None, date_from: datetime.date | None = None,
                 date_to: datetime.date | None = None) -> list[SimpleNamespace]:
    """تاریخچهٔ بها: هر ورود (بهای ورودی) و هر خروج (بهای تخصیص‌یافته) با سند، تامین‌کننده، انبار و روش."""
    from peecha.services import detail_dimensions as dimensions_service

    date_from = date_from or datetime.date(1900, 1, 1)
    date_to = date_to or datetime.date.today()
    out = []
    with new_session() as session:
        q = (select(StockLedger.movement_date, StockLedger.item_id, StockLedger.warehouse_id, StockLedger.unit_cost,
                    StockLedger.quantity_base, StockDocument.document_type_code, StockDocument.document_no,
                    StockDocument.stock_document_id, StockDocument.counterparty_detail_account_id)
             .join(StockDocumentLine, StockDocumentLine.line_id == StockLedger.stock_document_line_id)
             .join(StockDocument, StockDocument.stock_document_id == StockDocumentLine.stock_document_id)
             .where(StockLedger.company_id == company_id, StockLedger.movement_direction == "IN",
                    StockLedger.movement_date.between(date_from, date_to), StockLedger.unit_cost.is_not(None)))
        if item_id is not None:
            q = q.where(StockLedger.item_id == item_id)
        for d, i, w, cost, qty, dtype, dno, did, cp in session.execute(q).all():
            out.append(SimpleNamespace(date=d, item_id=i, warehouse_id=w, unit_cost=cost, quantity=qty, direction="IN",
                                       source=dtype, document_no=dno, document_id=did, method="",
                                       supplier=dimensions_service.get_detail_account_label(cp) if cp else ""))
        a = (select(CostAllocation.movement_date, CostAllocation.item_id, CostAllocation.warehouse_id,
                    func.sum(CostAllocation.quantity_base * CostAllocation.unit_cost), func.sum(CostAllocation.quantity_base),
                    CostAllocation.costing_method_code, StockDocument.document_type_code, StockDocument.document_no,
                    StockDocument.stock_document_id)
             .join(StockDocumentLine, StockDocumentLine.line_id == CostAllocation.stock_document_line_id)
             .join(StockDocument, StockDocument.stock_document_id == StockDocumentLine.stock_document_id)
             .where(CostAllocation.company_id == company_id, CostAllocation.movement_date.between(date_from, date_to))
             .group_by(CostAllocation.movement_date, CostAllocation.item_id, CostAllocation.warehouse_id,
                       CostAllocation.costing_method_code, StockDocument.document_type_code, StockDocument.document_no,
                       StockDocument.stock_document_id, CostAllocation.stock_document_line_id))
        if item_id is not None:
            a = a.where(CostAllocation.item_id == item_id)
        for d, i, w, val, qty, method, dtype, dno, did in session.execute(a).all():
            out.append(SimpleNamespace(date=d, item_id=i, warehouse_id=w, unit_cost=(val / qty) if qty else _ZERO, quantity=qty,
                                       direction="OUT", source=dtype, document_no=dno, document_id=did, method=method, supplier=""))
    out.sort(key=lambda r: (r.date, 0 if r.direction == "IN" else 1, r.document_no or 0))
    return out


def summary(company_id: int, date_from: datetime.date, date_to: datetime.date) -> SimpleNamespace:
    """شاخص‌های داشبورد بهای تمام‌شده."""
    pos = positions(company_id, date_to)
    value = sum((v[1] for v in pos.values()), _ZERO)
    qty = sum((v[0] for v in pos.values() if v[0] > 0), _ZERO)
    with new_session() as session:
        cogs = session.scalar(
            select(func.coalesce(func.sum(CostAllocation.quantity_base * CostAllocation.unit_cost), 0))
            .join(StockDocumentLine, StockDocumentLine.line_id == CostAllocation.stock_document_line_id)
            .join(StockDocument, StockDocument.stock_document_id == StockDocumentLine.stock_document_id)
            .where(CostAllocation.company_id == company_id, StockDocument.document_type_code == "ISSUE",
                   CostAllocation.movement_date.between(date_from, date_to))) or _ZERO
        layers = session.scalar(select(func.count()).select_from(CostLayer).where(
            CostLayer.company_id == company_id, CostLayer.remaining_quantity > 0)) or 0
        pending = session.scalar(select(func.count()).select_from(CostAllocation).where(
            CostAllocation.company_id == company_id, CostAllocation.costing_status_code != "CALCULATED")) or 0
    return SimpleNamespace(inventory_value=value, quantity=qty, average_cost=(value / qty) if qty else None,
                           cogs=decimal.Decimal(cogs), open_layers=layers, pending=pending)
