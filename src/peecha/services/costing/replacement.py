"""بهایِ جایگزینی (Replacement Cost) و منابعِ قیمتِ روشِ NIFO -- R258.

NIFO با لایه‌هایِ واقعی مخلوط نمی‌شود: موجودی با بهایِ دفتری (میانگین) بستانکار می‌شود و بهایِ تمام‌شده
با بهایِ جایگزینی؛ اختلاف به حسابِ مغایرتِ بها می‌رود (inventory_engine).
"""

from __future__ import annotations

import datetime
import decimal
from dataclasses import dataclass

from sqlalchemy import or_, select

from peecha.db.base import new_session
from peecha.db.models.commercial import CommercialDocument, CommercialDocumentLine, PriceList, PriceListItem
from peecha.db.models.inventory import Item, ReplacementCost, StockDocument, StockDocumentLine, StockLedger

_ZERO = decimal.Decimal(0)
SOURCES = {
    "MANUAL": "بهایِ جایگزینیِ دستی",
    "LAST_RECEIPT": "آخرین رسیدِ خرید",
    "LAST_PURCHASE_PRICE": "آخرین قیمتِ فاکتورِ خرید",
    "LAST_PURCHASE_ORDER": "آخرین سفارشِ خرید",
    "SUPPLIER_PRICE": "فهرستِ قیمتِ تامین‌کننده",
}
DEFAULT_ORDER = ["MANUAL", "LAST_RECEIPT", "LAST_PURCHASE_PRICE", "LAST_PURCHASE_ORDER", "SUPPLIER_PRICE"]


def _manual(session, item_id, warehouse_id, as_of):
    row = session.scalar(
        select(ReplacementCost).where(
            ReplacementCost.item_id == item_id, ReplacementCost.effective_date <= as_of,
            or_(ReplacementCost.warehouse_id == warehouse_id, ReplacementCost.warehouse_id.is_(None)))
        .order_by(ReplacementCost.warehouse_id.is_(None), ReplacementCost.effective_date.desc(),
                  ReplacementCost.replacement_cost_id.desc()).limit(1))
    return row.unit_cost if row is not None else None


def _last_receipt(session, item_id, warehouse_id, as_of):
    return session.scalar(
        select(StockLedger.unit_cost)
        .join(StockDocumentLine, StockDocumentLine.line_id == StockLedger.stock_document_line_id)
        .join(StockDocument, StockDocument.stock_document_id == StockDocumentLine.stock_document_id)
        .where(StockLedger.item_id == item_id, StockLedger.movement_direction == "IN", StockLedger.unit_cost > 0,
               StockDocument.document_type_code == "RECEIPT", StockLedger.movement_date <= as_of)
        .order_by(StockLedger.movement_date.desc(), StockLedger.ledger_id.desc()).limit(1))


def _last_commercial(session, item_id, as_of, doc_type, statuses):
    row = session.execute(
        select(CommercialDocumentLine.unit_price, CommercialDocumentLine.conversion_factor)
        .join(CommercialDocument, CommercialDocument.document_id == CommercialDocumentLine.document_id)
        .where(CommercialDocumentLine.item_id == item_id, CommercialDocument.document_type_code == doc_type,
               CommercialDocument.status_code.in_(statuses), CommercialDocument.document_date <= as_of,
               CommercialDocumentLine.unit_price > 0)
        .order_by(CommercialDocument.document_date.desc(), CommercialDocumentLine.line_id.desc()).limit(1)).first()
    if row is None:
        return None
    price, factor = row
    return price / factor if factor else price


def _supplier_price(session, item_id, as_of):
    from peecha.services import unit_conversion as uc

    row = session.execute(
        select(PriceListItem.unit_price, PriceListItem.uom_id)
        .join(PriceList, PriceList.price_list_id == PriceListItem.price_list_id)
        .where(PriceListItem.item_id == item_id, PriceList.price_list_type_code == "PURCHASE", PriceList.is_active.is_(True),
               PriceList.valid_from <= as_of, or_(PriceList.valid_to.is_(None), PriceList.valid_to >= as_of))
        .order_by(PriceList.valid_from.desc(), PriceListItem.price_list_item_id.desc()).limit(1)).first()
    if row is None:
        return None
    factor = uc.get_factor(item_id, row[1])
    return row[0] / factor if factor else row[0]


def replacement_cost(session, company_id: int, item_id: int, warehouse_id: int | None, as_of: datetime.date,
                     sources: list[str] | None = None) -> tuple[decimal.Decimal, str] | None:
    """اولین قیمتِ معتبر (مثبت) به ترتیبِ منابعِ تنظیم‌شده -- بهایِ هر واحدِ پایه."""
    for code in sources or DEFAULT_ORDER:
        if code == "MANUAL":
            value = _manual(session, item_id, warehouse_id, as_of)
        elif code == "LAST_RECEIPT":
            value = _last_receipt(session, item_id, warehouse_id, as_of)
        elif code == "LAST_PURCHASE_PRICE":
            value = _last_commercial(session, item_id, as_of, "PURCHASE_INVOICE", ("POSTED",))
        elif code == "LAST_PURCHASE_ORDER":
            value = _last_commercial(session, item_id, as_of, "PURCHASE_ORDER", ("CONFIRMED", "APPROVED", "POSTED"))
        elif code == "SUPPLIER_PRICE":
            value = _supplier_price(session, item_id, as_of)
        else:
            continue
        if value is not None and value > 0:
            return decimal.Decimal(value), code
    return None


def get_replacement_cost(company_id: int, item_id: int, warehouse_id: int | None = None,
                         as_of: datetime.date | None = None) -> tuple[decimal.Decimal, str] | None:
    from peecha.services.costing.engine import company_settings

    with new_session() as session:
        return replacement_cost(session, company_id, item_id, warehouse_id, as_of or datetime.date.today(),
                                company_settings(session, company_id).nifo_sources)


@dataclass
class ReplacementCostRow:
    replacement_cost_id: int
    item_id: int
    warehouse_id: int | None
    unit_cost: decimal.Decimal
    effective_date: datetime.date
    source_code: str
    note: str | None


def set_replacement_cost(company_id: int, item_id: int, unit_cost: decimal.Decimal, effective_date: datetime.date,
                         warehouse_id: int | None = None, uom_id: int | None = None, note: str | None = None,
                         user_id: int | None = None) -> int:
    """بهایِ جایگزینیِ دستی (به ازایِ واحدِ داده‌شده؛ به واحدِ پایه تبدیل و ذخیره می‌شود) -- با Audit."""
    from peecha.services import audit as audit_service
    from peecha.services import unit_conversion as uc

    unit_cost = decimal.Decimal(unit_cost)
    if unit_cost <= 0:
        raise ValueError("بهایِ جایگزینی باید مثبت باشد.")
    with new_session() as session:
        item = session.get(Item, item_id)
        if item is None or item.company_id != company_id:
            raise ValueError("کالا نامعتبر است.")
    base_cost = unit_cost / uc.get_factor(item_id, uom_id) if uom_id is not None else unit_cost
    with new_session() as session:
        previous = _manual(session, item_id, warehouse_id, effective_date)
        row = ReplacementCost(company_id=company_id, item_id=item_id, warehouse_id=warehouse_id, unit_cost=base_cost,
                              effective_date=effective_date, source_code="MANUAL", note=note, created_by_user_id=user_id)
        session.add(row)
        session.flush()
        audit_service.log_activity(session, company_id=company_id, user_id=user_id, entity_type="ReplacementCost",
                                   entity_id=row.replacement_cost_id, action="CREATE",
                                   changes={"item_id": item_id, "unit_cost": [str(previous) if previous is not None else None,
                                                                              str(base_cost)],
                                            "effective_date": effective_date.isoformat(), "reason": note})
        session.commit()
        return row.replacement_cost_id


def list_replacement_costs(company_id: int, item_id: int | None = None) -> list[ReplacementCostRow]:
    with new_session() as session:
        q = select(ReplacementCost).where(ReplacementCost.company_id == company_id)
        if item_id is not None:
            q = q.where(ReplacementCost.item_id == item_id)
        return [ReplacementCostRow(r.replacement_cost_id, r.item_id, r.warehouse_id, r.unit_cost, r.effective_date,
                                   r.source_code, r.note)
                for r in session.scalars(q.order_by(ReplacementCost.effective_date.desc(), ReplacementCost.replacement_cost_id.desc()))]
