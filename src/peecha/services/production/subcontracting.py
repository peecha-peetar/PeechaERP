"""R383: پیمانکاری فرعی تولید — همان دستور تولید، ساخت نزد پیمانکار بیرونی.

- دستور صادرشده به یک پیمانکار (تامین‌کننده) و یک انبار «نزد پیمانکار» سپرده می‌شود؛ انبار مواد همهٔ ردیف‌های دستور همین
  انبار می‌شود. موجودی آن انبار همچنان دارایی شرکت است.
- ارسال مواد = سند انتقال انبار از انبار شرکت به انبار نزد پیمانکار (همان موتور انبار).
- رسید محصول از پیمانکار: ۱) دستمزد پیمانکار (مقدار × نرخ هر واحد) مثل دستمزد جذب‌شده به کالای در جریان ساخت می‌رود
  (بدهکار WIP، بستانکار نقش «دستمزد پیمانکاری جذب‌شدهٔ تولید»)؛ ۲) مواد به نسبت مقدار ساخته‌شده از انبار نزد پیمانکار مصرف
  می‌شود؛ ۳) رسید محصول با همان منطق رسید تولید ثبت می‌شود.
- فاکتور خدمات پیمانکار با فاکتور خرید معمول ثبت می‌شود؛ اگر حساب هزینهٔ خدمت همان حساب نقش «دستمزد پیمانکاری جذب‌شده»
  باشد، بدهکار فاکتور و بستانکار جذب یکدیگر را خنثی می‌کنند و هزینه در بهای محصول می‌ماند.
"""

from __future__ import annotations

import datetime
import decimal
from types import SimpleNamespace

from sqlalchemy import func, select

from peecha.db.base import new_session
from peecha.db.models.accounting import DetailAccount
from peecha.db.models.inventory import Item, Warehouse
from peecha.db.models.production import OrderMaterial, OrderTransaction, ProductionOrder, SubcontractOrder
from peecha.services import inventory_documents as inv_docs
from peecha.services.production import common as c

ZERO = decimal.Decimal(0)


def _orders():
    from peecha.services.production import orders

    return orders


def _warehouse(session, company_id: int, warehouse_id: int | None) -> Warehouse:
    wh = session.get(Warehouse, warehouse_id) if warehouse_id else None
    if wh is None or wh.company_id != company_id:
        raise ValueError("انبار نامعتبر است.")
    return wh


def _sub(session, company_id: int, order_id: int) -> SubcontractOrder:
    row = session.get(SubcontractOrder, order_id)
    if row is None or row.company_id != company_id:
        raise ValueError("این دستور تولید به پیمانکار سپرده نشده است.")
    return row


def assign(company_id: int, user_id: int, order_id: int, subcontractor_detail_account_id: int, warehouse_id: int,
           fee_per_unit=0, notes: str = "") -> None:
    """سپردن دستور صادرشده به پیمانکار، یا تغییر نرخ و انبار پیش از هر رسید."""
    po = _orders()
    fee = c.money(fee_per_unit)
    if fee < 0:
        raise ValueError("نرخ دستمزد پیمانکار نمی‌تواند منفی باشد.")
    with new_session() as session:
        order = po.lock_order(session, company_id, order_id)
        if order.status_code not in po.WORKING_STATUSES:
            raise ValueError("اول دستور تولید را صادر کنید؛ دستور در وضعیت «" + po.STATUS_LABELS[order.status_code] + "» است.")
        party = session.get(DetailAccount, subcontractor_detail_account_id)
        if party is None or party.company_id != company_id:
            raise ValueError("پیمانکار نامعتبر است.")
        wh = _warehouse(session, company_id, warehouse_id)
        if wh.warehouse_id == order.fg_warehouse_id:
            raise ValueError("انبار نزد پیمانکار نباید همان انبار محصول باشد.")
        row = session.get(SubcontractOrder, order_id)
        if row is not None and decimal.Decimal(order.produced_qty) > 0 and row.warehouse_id != wh.warehouse_id:
            raise ValueError("پس از رسید محصول، انبار نزد پیمانکار عوض نمی‌شود.")
        if row is None:
            row = SubcontractOrder(order_id=order_id, company_id=company_id, created_by_user_id=user_id)
            session.add(row)
        row.subcontractor_detail_account_id, row.warehouse_id, row.fee_per_unit = party.detail_account_id, wh.warehouse_id, fee
        row.notes = (notes or "").strip()[:500] or None
        order.material_warehouse_id = wh.warehouse_id
        for m in session.scalars(select(OrderMaterial).where(OrderMaterial.order_id == order_id)):
            m.warehouse_id = wh.warehouse_id
        c.audit(session, company_id, user_id, "ProductionOrder", order_id, "SUBCONTRACT",
                {"subcontractor": party.detail_account_id, "warehouse_id": wh.warehouse_id, "fee_per_unit": str(fee)})
        session.commit()


def _stock(session, item_id: int, warehouse_id: int) -> decimal.Decimal:
    return _orders()._stock_in(session, item_id, warehouse_id)


def send_materials(company_id: int, user_id: int, order_id: int, from_warehouse_id: int,
                   quantities: dict[int, decimal.Decimal] | None = None, date: datetime.date | None = None) -> int:
    """سند انتقال مواد به انبار نزد پیمانکار. quantities: ردیف مواد ← مقدار؛ None یعنی کمبود هر ردیف (نیاز کل دستور منهای
    مصرف‌شده و موجودی همان کالا نزد پیمانکار). برمی‌گرداند: شناسهٔ سند انبار."""
    po = _orders()
    date = date or datetime.date.today()
    with new_session() as session:
        order = po.lock_order(session, company_id, order_id)
        sub = _sub(session, company_id, order_id)
        src = _warehouse(session, company_id, from_warehouse_id)
        if src.warehouse_id == sub.warehouse_id:
            raise ValueError("انبار مبدا همان انبار نزد پیمانکار است.")
        wanted: list[tuple[int, decimal.Decimal]] = []
        for m in session.scalars(select(OrderMaterial).where(OrderMaterial.order_id == order_id).order_by(OrderMaterial.line_no)):
            if quantities is not None:
                q = decimal.Decimal(quantities.get(m.material_id, 0) or 0)
            else:
                q = decimal.Decimal(m.planned_qty) - m.consumed_qty - _stock(session, m.item_id, sub.warehouse_id)
            if q < 0 and quantities is not None:
                raise ValueError("مقدار ارسال نمی‌تواند منفی باشد.")
            if q > 0:
                wanted.append((m.item_id, c.qty(q)))
        if not wanted:
            raise ValueError("مقداری برای ارسال نیست؛ مواد این دستور نزد پیمانکار کافی است.")
        lines = []
        for item_id, q in wanted:
            uom = session.get(Item, item_id).base_uom_id
            left = q
            for bin_id, avail in po._bins_with_stock(session, item_id, src.warehouse_id, free_only=False):
                take = min(avail, left)
                if take <= 0:
                    break
                lines.append(inv_docs.LineFields(item_id=item_id, uom_id=uom, quantity=take, quantity_base=take, bin_location_id=bin_id,
                                                 conversion_factor=c.ONE))
                left -= take
            if left > 0:
                raise ValueError(f"موجودی «{c.item_label(session, item_id)}» در انبار مبدا کافی نیست (کمبود {c.qty(left).normalize()}).")
        result, _ids = inv_docs.create_and_post_in_session(
            session, company_id, user_id, "TRANSFER", date,
            inv_docs.DocumentHeaderFields(source_warehouse_id=src.warehouse_id, destination_warehouse_id=sub.warehouse_id,
                                          counterparty_detail_account_id=sub.subcontractor_detail_account_id,
                                          reference_no=order.order_code, description=f"ارسال مواد به پیمانکار — {order.order_code}"),
            lines)
        c.audit(session, company_id, user_id, "ProductionOrder", order_id, "SUBCONTRACT_SEND",
                {"stock_document_id": result.stock_document_id, "lines": len(lines)})
        session.commit()
        return result.stock_document_id


def receive(company_id: int, user_id: int, order_id: int, quantity, date: datetime.date | None = None, final: bool = False,
            idempotency_key: str | None = None) -> int:
    """رسید محصول ساخته‌شده نزد پیمانکار: دستمزد پیمانکار، مصرف مواد از انبار نزد پیمانکار و رسید محصول (یک تراکنش)."""
    from peecha.services.production import costing as pcost

    po = _orders()
    q = decimal.Decimal(quantity or 0)
    if q <= 0:
        raise ValueError("مقدار دریافتی از پیمانکار باید بیشتر از صفر باشد.")
    date = date or datetime.date.today()
    with new_session() as session:
        if (done := po._replayed(session, idempotency_key)) is not None:
            return done.txn_id
        order = po.lock_order(session, company_id, order_id)
        po._ensure_working(order)
        sub = _sub(session, company_id, order_id)
        fee = c.money(q * decimal.Decimal(sub.fee_per_unit))
        if fee > 0:
            c.require_roles(session, company_id, (c.WIP, c.SUBCONTRACT_APPLIED))
            pcost._conversion_txn(session, order, "SUBCONTRACT", c.SUBCONTRACT_APPLIED, fee, date, user_id,
                                  f"{idempotency_key}:fee" if idempotency_key else None, None, quantity=q,
                                  details={"subcontractor": sub.subcontractor_detail_account_id, "fee_per_unit": str(sub.fee_per_unit)})
        po._backflush(session, order, decimal.Decimal(order.produced_qty) + q, date, user_id, idempotency_key)
        txn = po._receive(session, order, po.ReceiptInput(q, final=final), date, user_id, idempotency_key)
        c.audit(session, company_id, user_id, "ProductionOrder", order_id, "SUBCONTRACT_RECEIVE",
                {"quantity": str(q), "fee": str(fee), "final": final})
        session.commit()
        return txn.txn_id


def materials(company_id: int, order_id: int) -> list[SimpleNamespace]:
    """ردیف‌های مواد دستور: نیاز، مصرف‌شده و موجودی همان کالا نزد پیمانکار."""
    with new_session() as session:
        sub = _sub(session, company_id, order_id)
        rows = list(session.scalars(select(OrderMaterial).where(OrderMaterial.order_id == order_id).order_by(OrderMaterial.line_no)))
        labels = c.item_labels(session, [m.item_id for m in rows])
        return [SimpleNamespace(material_id=m.material_id, item_id=m.item_id, item_label=labels.get(m.item_id, ""),
                                planned_qty=decimal.Decimal(m.planned_qty), consumed_qty=m.consumed_qty,
                                at_subcontractor=_stock(session, m.item_id, sub.warehouse_id), is_optional=m.is_optional)
                for m in rows]


def list_subcontracts(company_id: int, open_only: bool = False) -> list[SimpleNamespace]:
    po = _orders()
    with new_session() as session:
        q = (select(SubcontractOrder, ProductionOrder).join(ProductionOrder, ProductionOrder.order_id == SubcontractOrder.order_id)
             .where(SubcontractOrder.company_id == company_id))
        if open_only:
            q = q.where(ProductionOrder.status_code.in_(po.ACTIVE_STATUSES))
        pairs = list(session.execute(q.order_by(ProductionOrder.order_id.desc())))
        ids = [o.order_id for _s, o in pairs]
        fees = dict(session.execute(select(OrderTransaction.order_id, func.sum(OrderTransaction.amount)).where(
            OrderTransaction.order_id.in_(ids or [0]), OrderTransaction.txn_type == "SUBCONTRACT").group_by(OrderTransaction.order_id)).all())
        labels = c.item_labels(session, [o.item_id for _s, o in pairs])
        parties = {d.detail_account_id: d for d in session.scalars(select(DetailAccount).where(
            DetailAccount.detail_account_id.in_([s.subcontractor_detail_account_id for s, _o in pairs] or [0])))}
        whs = {w.warehouse_id: w for w in session.scalars(select(Warehouse).where(
            Warehouse.warehouse_id.in_([s.warehouse_id for s, _o in pairs] or [0])))}
        out = []
        for s, o in pairs:
            party, wh = parties.get(s.subcontractor_detail_account_id), whs.get(s.warehouse_id)
            out.append(SimpleNamespace(
                order_id=o.order_id, order_code=o.order_code, item_label=labels.get(o.item_id, ""),
                subcontractor_detail_account_id=s.subcontractor_detail_account_id,
                subcontractor=f"{party.code} {party.name or ''}".strip() if party else "", warehouse_id=s.warehouse_id,
                warehouse=f"{wh.code} {wh.name}" if wh else "", planned_qty=decimal.Decimal(o.planned_qty),
                produced_qty=decimal.Decimal(o.produced_qty), remaining_qty=o.remaining_qty, fee_per_unit=decimal.Decimal(s.fee_per_unit),
                fee_total=c.money(fees.get(o.order_id) or 0), status_code=o.status_code,
                status_label=po.STATUS_LABELS[o.status_code], notes=s.notes or ""))
        return out


def assignable_orders(company_id: int) -> list[SimpleNamespace]:
    """دستورهای صادرشده یا در حال اجرا که هنوز به پیمانکار سپرده نشده‌اند."""
    po = _orders()
    with new_session() as session:
        taken = select(SubcontractOrder.order_id)
        rows = list(session.scalars(select(ProductionOrder).where(
            ProductionOrder.company_id == company_id, ProductionOrder.status_code.in_(po.WORKING_STATUSES),
            ProductionOrder.order_id.not_in(taken)).order_by(ProductionOrder.order_id.desc())))
        labels = c.item_labels(session, [o.item_id for o in rows])
        return [SimpleNamespace(order_id=o.order_id, order_code=o.order_code, item_label=labels.get(o.item_id, ""),
                                planned_qty=decimal.Decimal(o.planned_qty)) for o in rows]
