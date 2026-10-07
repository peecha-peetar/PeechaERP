"""دستور تولید — R267: چرخهٔ وضعیت، رزرو، مصرف/برگشت، رسید محصول (اصلی/جانبی/مشترک)، ضایعات، کالای در جریان ساخت، اتمام/بستن.

اتمیک بودن: هر عملیات در یک تراکنش انجام می‌شود — سند انبار (موتور انبار با session)، سند حسابداری (موتور سند با
session)، تراکنش دستور و ارقام کش‌شده؛ اگر هر مرحله خطا بدهد کل تراکنش برمی‌گردد.
تکرارنشدن: هر عملیات کلید idempotency می‌پذیرد؛ درخواست تکراری همان نتیجهٔ قبلی را برمی‌گرداند.

حساب‌ها (نقش‌محور، در نگاشت حساب‌های انبار):
  مصرف مواد    بدهکار کالای در جریان ساخت / بستانکار موجودی            (حواله با COGS ← WIP)
  برگشت مواد   بدهکار موجودی / بستانکار کالای در جریان ساخت            (رسید با «مازاد اصلاح» ← WIP)
  رسید محصول   بدهکار موجودی محصول / بستانکار کالای در جریان ساخت      (همان)
  ضایعات غیرعادی بدهکار زیان ضایعات / بستانکار کالای در جریان ساخت
  ماندهٔ کالای در جریان ساخت در بستن ← انحراف تولید
"""

from __future__ import annotations

import datetime
import decimal
from dataclasses import dataclass, field
from types import SimpleNamespace

from sqlalchemy import func, select

from peecha.db.base import new_session
from peecha.db.models.inventory import (
    BomHeader, BomLine, Item, StockBalance, StockLedger, StockReservation, Warehouse,
)
from peecha.db.models.production import (
    BomOutput, ItemProductionProfile, OrderMaterial, OrderOperation, OrderOutput, OrderTransaction, ProductionOrder,
    Routing, RoutingOperation, WorkCenter,
)
from peecha.services import inventory_documents as inv_docs
from peecha.services import inventory_engine as engine
from peecha.services.production import common as c
from peecha.services.production import master as pm

ZERO, ONE = c.ZERO, c.ONE
_HUNDRED = decimal.Decimal(100)
RESERVATION_SOURCE = "PRODUCTION_ORDER"

STATUS_LABELS = {"DRAFT": "پیش‌نویس", "PLANNED": "برنامه‌ریزی‌شده", "RELEASED": "صادرشده", "IN_PROGRESS": "در حال تولید",
                 "ON_HOLD": "متوقف", "COMPLETED": "تکمیل‌شده", "CLOSED": "بسته‌شده", "CANCELLED": "لغوشده"}
TXN_LABELS = {"ISSUE": "مصرف مواد", "RETURN": "برگشت مواد", "RECEIPT": "رسید محصول", "BY_PRODUCT": "محصول جانبی",
              "CO_PRODUCT": "محصول مشترک", "SCRAP": "ضایعات", "LABOR": "دستمزد", "MACHINE": "ماشین", "OVERHEAD": "سربار",
              "VARIANCE": "انحراف", "REVERSAL": "برگشت تولید"}
ACTIVE_STATUSES = ("RELEASED", "IN_PROGRESS", "ON_HOLD")
WORKING_STATUSES = ("RELEASED", "IN_PROGRESS")
EDITABLE_STATUSES = ("DRAFT", "PLANNED")
AVAILABILITY_LABELS = {"GREEN": "موجود", "YELLOW": "بخشی موجود", "RED": "کمبود"}

_ISSUE_ROLES = {"COGS": c.WIP}
_RECEIPT_ROLES = {"INVENTORY_ADJUSTMENT_GAIN": c.WIP, "INVENTORY_COST_VARIANCE": c.VARIANCE}


# =====================================================================================
# ابزار
# =====================================================================================
def lock_order(session, company_id: int, order_id: int) -> ProductionOrder:
    order = session.scalar(select(ProductionOrder).where(ProductionOrder.order_id == order_id).with_for_update())
    if order is None or order.company_id != company_id:
        raise ValueError("دستور تولید نامعتبر است.")
    return order


def _replayed(session, key: str | None):
    if not key:
        return None
    return session.scalar(select(OrderTransaction).where(OrderTransaction.idempotency_key == key))


def wip_balance(session, order_id: int) -> decimal.Decimal:
    return decimal.Decimal(session.scalar(select(func.coalesce(func.sum(OrderTransaction.wip_delta), 0))
                                          .where(OrderTransaction.order_id == order_id)) or 0)


def record(session, order: ProductionOrder, txn_type: str, date: datetime.date, user_id: int | None, *, item_id=None,
           quantity=ZERO, amount=ZERO, wip_delta=ZERO, material_id=None, output_id=None, order_operation_id=None,
           stock_document_id=None, journal_entry_id=None, reason=None, details=None, key=None,
           reversed_txn_id=None) -> OrderTransaction:
    from peecha.services.production import costing as pcost

    pcost.ensure_period_open(session, order.company_id, date)
    txn = OrderTransaction(company_id=order.company_id, order_id=order.order_id, txn_type=txn_type, txn_date=date,
                           item_id=item_id, quantity=c.qty(quantity), amount=c.money(amount), wip_delta=c.money(wip_delta),
                           material_id=material_id, output_id=output_id, order_operation_id=order_operation_id,
                           stock_document_id=stock_document_id, journal_entry_id=journal_entry_id, reason=reason,
                           details=details, idempotency_key=key, reversed_txn_id=reversed_txn_id, created_by_user_id=user_id)
    session.add(txn)
    session.flush()
    return txn


def _cost_estimate(session, item_id: int, warehouse_id: int | None, date: datetime.date) -> decimal.Decimal:
    """بهای برآوردی واحد از موتور انبار: میانگین فعلی انبار ← آخرین بهای ثبت‌شده ← بهای استاندارد."""
    value = engine._current_average_cost(session, item_id, warehouse_id) if warehouse_id else None
    if value is None:
        value = engine._last_known_unit_cost(session, item_id)
    if value is None:
        try:
            value = engine._standard_cost(session, item_id, date)
        except ValueError:
            value = ZERO
    return decimal.Decimal(value or 0)


def _standard_unit_cost(session, item_id: int, date: datetime.date) -> decimal.Decimal | None:
    try:
        return decimal.Decimal(engine._standard_cost(session, item_id, date))
    except ValueError:
        return None


def _stock_in(session, item_id: int, warehouse_id: int) -> decimal.Decimal:
    return decimal.Decimal(session.scalar(select(func.coalesce(func.sum(StockBalance.quantity_on_hand), 0)).where(
        StockBalance.item_id == item_id, StockBalance.warehouse_id == warehouse_id)) or 0)


def _reserved_in(session, item_id: int, warehouse_id: int) -> decimal.Decimal:
    return decimal.Decimal(session.scalar(select(func.coalesce(func.sum(StockBalance.quantity_reserved), 0)).where(
        StockBalance.item_id == item_id, StockBalance.warehouse_id == warehouse_id)) or 0)


def _status(available: decimal.Decimal, need: decimal.Decimal) -> str:
    if need <= 0 or available >= need:
        return "GREEN"
    return "YELLOW" if available > 0 else "RED"


def _header(order: ProductionOrder, description: str, **kw) -> inv_docs.DocumentHeaderFields:
    return inv_docs.DocumentHeaderFields(cost_center_detail_account_id=order.cost_center_detail_account_id,
                                         project_detail_account_id=order.project_detail_account_id,
                                         reference_no=order.order_code, description=f"{order.order_code} -- {description}", **kw)


def _dims(order: ProductionOrder) -> tuple:
    return (order.cost_center_detail_account_id, order.project_detail_account_id)


def _ledger_amounts(session, line_ids: list[int], direction: str) -> dict[int, decimal.Decimal]:
    out: dict[int, decimal.Decimal] = {}
    for lid, q, uc in session.execute(select(StockLedger.stock_document_line_id, StockLedger.quantity_base, StockLedger.unit_cost)
                                      .where(StockLedger.stock_document_line_id.in_(line_ids or [-1]),
                                             StockLedger.movement_direction == direction)):
        out[lid] = out.get(lid, ZERO) + c.money(decimal.Decimal(q) * decimal.Decimal(uc))
    return out


def _je_role_amount(session, company_id: int, journal_entry_id: int | None, role: str, debit: bool) -> decimal.Decimal | None:
    from peecha.db.models.accounting import JournalEntryLine

    if journal_entry_id is None:
        return None
    account_id = c.role_account(session, company_id, role)
    col = JournalEntryLine.debit_amount_fc if debit else JournalEntryLine.credit_amount_fc
    return decimal.Decimal(session.scalar(select(func.coalesce(func.sum(col), 0)).where(
        JournalEntryLine.journal_entry_id == journal_entry_id, JournalEntryLine.account_id == account_id)) or 0)


# =====================================================================================
# ایجاد / ویرایش
# =====================================================================================
@dataclass
class OrderFields:
    item_id: int
    planned_qty: decimal.Decimal
    start_date: datetime.date | None = None
    due_date: datetime.date | None = None
    bom_id: int | None = None
    routing_id: int | None = None
    material_warehouse_id: int | None = None
    wip_warehouse_id: int | None = None
    fg_warehouse_id: int | None = None
    scrap_warehouse_id: int | None = None
    branch_id: int | None = None
    cost_center_detail_account_id: int | None = None
    project_detail_account_id: int | None = None
    work_center_id: int | None = None
    priority: int = 3
    responsible_user_id: int | None = None
    notes: str | None = None
    sales_order_line_id: int | None = None
    parent_order_id: int | None = None
    joint_cost_method: str | None = None


def _apply_defaults(session, company_id: int, f: OrderFields) -> None:
    st = c.settings(session, company_id)
    item = c.item_of(session, company_id, f.item_id)
    f.start_date = f.start_date or datetime.date.today()
    if f.due_date is None:
        prof = session.get(ItemProductionProfile, f.item_id)
        f.due_date = f.start_date + datetime.timedelta(days=(prof.lead_time_days if prof else 0))
    if f.bom_id is None:
        f.bom_id = pm.effective_bom_id(session, f.item_id, f.start_date)
    bom = session.get(BomHeader, f.bom_id) if f.bom_id else None
    if f.routing_id is None:
        f.routing_id = (bom.routing_id if bom else None) or pm.default_routing_id(session, f.item_id)
    f.material_warehouse_id = f.material_warehouse_id or st.default_material_warehouse_id or item.default_warehouse_id
    f.fg_warehouse_id = f.fg_warehouse_id or st.default_fg_warehouse_id or item.default_warehouse_id
    f.wip_warehouse_id = f.wip_warehouse_id or st.default_production_warehouse_id
    f.scrap_warehouse_id = f.scrap_warehouse_id or st.default_scrap_warehouse_id
    if f.material_warehouse_id is not None:
        wh = session.get(Warehouse, f.material_warehouse_id)
        if wh is not None:
            f.fg_warehouse_id = f.fg_warehouse_id or wh.finished_goods_warehouse_id
            f.scrap_warehouse_id = f.scrap_warehouse_id or wh.scrap_warehouse_id
    f.cost_center_detail_account_id = f.cost_center_detail_account_id or st.default_cost_center_detail_account_id
    if f.work_center_id is None and f.routing_id:
        f.work_center_id = session.scalar(select(RoutingOperation.work_center_id).where(
            RoutingOperation.routing_id == f.routing_id).order_by(RoutingOperation.seq).limit(1))
    if f.cost_center_detail_account_id is None and f.work_center_id:
        wc = session.get(WorkCenter, f.work_center_id)
        f.cost_center_detail_account_id = wc.cost_center_detail_account_id if wc else None
    f.joint_cost_method = f.joint_cost_method or st.default_joint_cost_method


def _validate(session, company_id: int, f: OrderFields) -> None:
    f.planned_qty = decimal.Decimal(f.planned_qty)
    if f.planned_qty <= 0:
        raise ValueError("مقدار تولید باید بزرگ‌تر از صفر باشد.")
    item = c.item_of(session, company_id, f.item_id)
    if not item.is_stock_tracked:
        raise ValueError("کالای تولیدی باید موجودی‌محور باشد.")
    if f.bom_id is None:
        raise ValueError(f"برای «{c.item_label(session, f.item_id)}» هیچ فهرست مواد معتبری تعریف نشده است.")
    bom = session.get(BomHeader, f.bom_id)
    if bom is None or bom.finished_item_id != f.item_id:
        raise ValueError("فهرست مواد با محصول دستور هم‌خوان نیست.")
    if f.routing_id is not None:
        routing = session.get(Routing, f.routing_id)
        if routing is None or routing.company_id != company_id:
            raise ValueError("مسیر تولید نامعتبر است.")
    if f.due_date < f.start_date:
        raise ValueError("تاریخ پایان پیش از تاریخ شروع است.")
    if not 1 <= int(f.priority) <= 5:
        raise ValueError("اولویت باید بین ۱ تا ۵ باشد.")
    if f.joint_cost_method not in c.JOINT_METHODS:
        raise ValueError("روش تخصیص تولید مشترک نامعتبر است.")
    pm.check_lot_size(session, f.item_id, f.planned_qty)


def create_order(company_id: int, user_id: int, fields: OrderFields, idempotency_key: str | None = None) -> int:
    with new_session() as session:
        if idempotency_key:
            existing = session.scalar(select(ProductionOrder.order_id).where(ProductionOrder.idempotency_key == idempotency_key))
            if existing:
                return existing
        _apply_defaults(session, company_id, fields)
        _validate(session, company_id, fields)
        order = _insert_order(session, company_id, user_id, fields, idempotency_key)
        session.commit()
        return order.order_id


def _insert_order(session, company_id: int, user_id: int, f: OrderFields, key: str | None = None) -> ProductionOrder:
    st = c.settings(session, company_id)
    session.execute(select(ProductionOrder.order_id).where(ProductionOrder.company_id == company_id).with_for_update()).all()
    no = (session.scalar(select(func.max(ProductionOrder.order_no)).where(ProductionOrder.company_id == company_id)) or 0) + 1
    item = session.get(Item, f.item_id)
    order = ProductionOrder(company_id=company_id, order_no=no, order_code=f"{st.order_prefix}-{no}", item_id=f.item_id,
                            uom_id=item.base_uom_id, status_code="DRAFT", produced_qty=ZERO, scrapped_qty=ZERO,
                            created_by_user_id=user_id, idempotency_key=key,
                            **{k: v for k, v in f.__dict__.items() if k != "item_id"})
    session.add(order)
    session.flush()
    c.audit(session, company_id, user_id, "ProductionOrder", order.order_id, "CREATE",
            {"code": order.order_code, "item_id": f.item_id, "qty": str(f.planned_qty)})
    return order


def update_order(company_id: int, user_id: int, order_id: int, fields: OrderFields, reason: str | None = None) -> None:
    with new_session() as session:
        order = lock_order(session, company_id, order_id)
        if order.status_code not in EDITABLE_STATUSES:
            raise ValueError("فقط دستور پیش‌نویس/برنامه‌ریزی‌شده قابل ویرایش است.")
        _apply_defaults(session, company_id, fields)
        _validate(session, company_id, fields)
        changes = {}
        for k, v in fields.__dict__.items():
            if getattr(order, k) != v:
                changes[k] = [str(getattr(order, k)), str(v)]
                setattr(order, k, v)
        if changes:
            c.audit(session, company_id, user_id, "ProductionOrder", order_id, "UPDATE", {**changes, "reason": reason})
        session.commit()


def plan_order(company_id: int, user_id: int, order_id: int) -> None:
    _transition(company_id, user_id, order_id, ("DRAFT",), "PLANNED")


def _transition(company_id: int, user_id: int, order_id: int, allowed: tuple, to: str, reason: str | None = None) -> None:
    with new_session() as session:
        order = lock_order(session, company_id, order_id)
        if order.status_code not in allowed:
            raise ValueError(f"دستور در وضعیت «{STATUS_LABELS[order.status_code]}» است و این عملیات مجاز نیست.")
        before = order.status_code
        order.status_code = to
        if to == "ON_HOLD":
            order.hold_reason = reason
        c.audit(session, company_id, user_id, "ProductionOrder", order_id, to, {"status": [before, to], "reason": reason})
        session.commit()


# =====================================================================================
# بررسیِ مواد / رزرو
# =====================================================================================
def material_plan(session, company_id: int, item_id: int, bom_id: int, quantity: decimal.Decimal) -> list[SimpleNamespace]:
    """نیاز سطح اول فهرست مواد برای مقدار (با ضایعات)."""
    bom = session.get(BomHeader, bom_id)
    rows = []
    for ln in session.scalars(select(BomLine).where(BomLine.bom_id == bom_id).order_by(BomLine.line_no)):
        base = decimal.Decimal(ln.quantity_per) * decimal.Decimal(ln.conversion_factor or 1)
        scrap = decimal.Decimal(ln.scrap_percent or 0) or decimal.Decimal(bom.scrap_percent or 0)
        net, gross = pm.line_requirement(base, ln.quantity_type or "VARIABLE", scrap, quantity, bom.batch_size_qty)
        rows.append(SimpleNamespace(line=ln, base=base, scrap=scrap, net=net, gross=gross))
    return rows


def availability(company_id: int, order_id: int | None = None, *, item_id: int | None = None, quantity=None,
                 bom_id: int | None = None, warehouse_id: int | None = None) -> list[SimpleNamespace]:
    """موجود / رزرو / نیاز / کمبود برای هر ماده — برای دستور موجود یا پیش از ساختن (ویزارد)."""
    with new_session() as session:
        if order_id is not None:
            order = session.get(ProductionOrder, order_id)
            if order is None or order.company_id != company_id:
                raise ValueError("دستور تولید نامعتبر است.")
            mats = list(session.scalars(select(OrderMaterial).where(OrderMaterial.order_id == order_id).order_by(OrderMaterial.line_no)))
            if mats:
                specs = [(m.item_id, m.warehouse_id or order.material_warehouse_id, m.planned_qty, m.consumed_qty,
                          m.reserved_qty, m.component_type, m.is_optional, m.material_id) for m in mats]
            else:
                specs = [(r.line.component_item_id, r.line.warehouse_id or order.material_warehouse_id, r.gross, ZERO, ZERO,
                          r.line.component_type or "MATERIAL", r.line.is_optional, None)
                         for r in material_plan(session, company_id, order.item_id, order.bom_id, order.planned_qty)]
        else:
            bom_id = bom_id or pm.effective_bom_id(session, item_id)
            if bom_id is None:
                raise ValueError("فهرست مواد معتبری برای این کالا وجود ندارد.")
            warehouse_id = warehouse_id or c.settings(session, company_id).default_material_warehouse_id
            specs = [(r.line.component_item_id, r.line.warehouse_id or warehouse_id, r.gross, ZERO, ZERO,
                      r.line.component_type or "MATERIAL", r.line.is_optional, None)
                     for r in material_plan(session, company_id, item_id, bom_id, decimal.Decimal(quantity))]
        labels = c.item_labels(session, [s[0] for s in specs])
        out = []
        for iid, wh, required, consumed, own_reserved, ctype, optional, mid in specs:
            on_hand = _stock_in(session, iid, wh) if wh else ZERO
            reserved_all = _reserved_in(session, iid, wh) if wh else ZERO
            available = max(ZERO, on_hand - reserved_all + decimal.Decimal(own_reserved))
            need = max(ZERO, decimal.Decimal(required) - decimal.Decimal(consumed))
            shortage = max(ZERO, need - available)
            out.append(SimpleNamespace(material_id=mid, item_id=iid, item_label=labels.get(iid, ""), warehouse_id=wh,
                                       component_type=ctype, is_optional=optional, required=c.qty(required),
                                       consumed=c.qty(consumed), remaining=c.qty(need), on_hand=c.qty(on_hand),
                                       reserved=c.qty(own_reserved), reserved_by_others=c.qty(reserved_all - own_reserved),
                                       available=c.qty(available), shortage=c.qty(shortage),
                                       status=_status(available, need)))
        return out


def _bins_with_stock(session, item_id: int, warehouse_id: int, free_only: bool) -> list[tuple[int, decimal.Decimal]]:
    rows = session.execute(select(StockBalance.bin_location_id, StockBalance.quantity_on_hand, StockBalance.quantity_reserved)
                           .where(StockBalance.item_id == item_id, StockBalance.warehouse_id == warehouse_id,
                                  StockBalance.batch_id.is_(None), StockBalance.quantity_on_hand > 0)).all()
    out = [(b, decimal.Decimal(q) - (decimal.Decimal(r or 0) if free_only else ZERO)) for b, q, r in rows]
    return sorted([x for x in out if x[1] > 0], key=lambda x: -x[1])


def _reserve_material(session, order: ProductionOrder, m: OrderMaterial) -> decimal.Decimal:
    wh = m.warehouse_id or order.material_warehouse_id
    need = decimal.Decimal(m.planned_qty) - m.consumed_qty - decimal.Decimal(m.reserved_qty)
    if wh is None or need <= 0 or m.is_optional:
        return ZERO
    done = ZERO
    for bin_id, free in _bins_with_stock(session, m.item_id, wh, free_only=True):
        take = min(free, need - done)
        if take <= 0:
            break
        res = StockReservation(company_id=order.company_id, item_id=m.item_id, warehouse_id=wh, bin_location_id=bin_id,
                               quantity=take, source_type_code=RESERVATION_SOURCE, source_record_id=m.material_id,
                               status_code="ACTIVE")
        session.add(res)
        _hold(session, res, take)
        done += take
    m.reserved_qty = decimal.Decimal(m.reserved_qty) + done
    return done


def _hold(session, res: StockReservation, delta: decimal.Decimal) -> None:
    """همان ستون رزرو ماندهٔ موجودی (هم‌الگو با رزرو وظایف انبار) تا موجودی آزاد کم شود."""
    bal = session.scalar(select(StockBalance).where(
        StockBalance.item_id == res.item_id, StockBalance.warehouse_id == res.warehouse_id,
        StockBalance.bin_location_id == res.bin_location_id, StockBalance.batch_id.is_(None)).with_for_update())
    if bal is not None:
        bal.quantity_reserved = max(ZERO, decimal.Decimal(bal.quantity_reserved or 0) + delta)


def _consume_reservation(session, m: OrderMaterial, quantity: decimal.Decimal, status_if_all: str = "FULFILLED") -> None:
    left = decimal.Decimal(quantity)
    for res in session.scalars(select(StockReservation).where(
            StockReservation.source_type_code == RESERVATION_SOURCE, StockReservation.source_record_id == m.material_id,
            StockReservation.status_code == "ACTIVE").order_by(StockReservation.reservation_id).with_for_update()):
        if left <= 0:
            break
        remaining = decimal.Decimal(res.quantity) - decimal.Decimal(res.fulfilled_quantity_base)
        take = min(remaining, left)
        res.fulfilled_quantity_base = decimal.Decimal(res.fulfilled_quantity_base) + take
        _hold(session, res, -take)
        if res.fulfilled_quantity_base >= res.quantity:
            res.status_code, res.released_at = status_if_all, datetime.datetime.now()
        left -= take
        m.reserved_qty = max(ZERO, decimal.Decimal(m.reserved_qty) - take)


def _release_all(session, order_id: int) -> None:
    for m in session.scalars(select(OrderMaterial).where(OrderMaterial.order_id == order_id)):
        for res in session.scalars(select(StockReservation).where(
                StockReservation.source_type_code == RESERVATION_SOURCE, StockReservation.source_record_id == m.material_id,
                StockReservation.status_code == "ACTIVE").with_for_update()):
            _hold(session, res, -(decimal.Decimal(res.quantity) - decimal.Decimal(res.fulfilled_quantity_base)))
            res.status_code, res.released_at = "CANCELLED", datetime.datetime.now()
        m.reserved_qty = ZERO


def reserve_materials(company_id: int, user_id: int, order_id: int) -> decimal.Decimal:
    with new_session() as session:
        order = lock_order(session, company_id, order_id)
        if order.status_code not in ACTIVE_STATUSES:
            raise ValueError("رزرو فقط برای دستور صادرشده/در حال تولید ممکن است.")
        total = sum((_reserve_material(session, order, m) for m in session.scalars(
            select(OrderMaterial).where(OrderMaterial.order_id == order_id))), ZERO)
        c.audit(session, company_id, user_id, "ProductionOrder", order_id, "RESERVE", {"quantity": str(total)})
        session.commit()
        return total


def unreserve_materials(company_id: int, user_id: int, order_id: int) -> None:
    with new_session() as session:
        lock_order(session, company_id, order_id)
        _release_all(session, order_id)
        c.audit(session, company_id, user_id, "ProductionOrder", order_id, "UNRESERVE", {})
        session.commit()


# =====================================================================================
# صدور
# =====================================================================================
def release_order(company_id: int, user_id: int, order_id: int, reserve: bool | None = None) -> list[SimpleNamespace]:
    """صدور: کپی ثابت فهرست مواد/مسیر روی دستور، قفل نسخهٔ فهرست مواد، بررسی موجودی (هشدار/توقف طبق تنظیمات) و رزرو."""
    shortages = [a for a in availability(company_id, order_id) if a.status != "GREEN" and not a.is_optional]
    with new_session() as session:
        order = lock_order(session, company_id, order_id)
        if order.status_code not in EDITABLE_STATUSES:
            raise ValueError(f"دستور در وضعیت «{STATUS_LABELS[order.status_code]}» است و قابل صدور نیست.")
        st = c.settings(session, company_id)
        _preflight(session, company_id, order, st)
        issues = pm.validate_bom(company_id, order.bom_id)
        if issues:
            raise ValueError("فهرست مواد دستور مشکل دارد: " + " ".join(issues))
        if shortages and st.shortage_policy == "BLOCK" and not st.allow_negative_material:
            raise ValueError("کمبود مواد: " + "، ".join(f"{a.item_label} ({a.shortage.normalize()})" for a in shortages))
        _snapshot(session, company_id, order)
        pm.lock_bom(session, order.bom_id)
        order.status_code, order.released_at = "RELEASED", datetime.datetime.now()
        if reserve if reserve is not None else st.auto_reservation:
            for m in session.scalars(select(OrderMaterial).where(OrderMaterial.order_id == order_id)):
                _reserve_material(session, order, m)
        c.audit(session, company_id, user_id, "ProductionOrder", order_id, "RELEASE",
                {"bom_id": order.bom_id, "shortages": len(shortages), "planned_unit_cost": str(order.planned_unit_cost)})
        session.commit()
    return shortages


def _preflight(session, company_id: int, order: ProductionOrder, st) -> None:
    """کنترل‌های «Block»: فهرست مواد، انبارها، مرکز هزینه، نگاشت حساب."""
    if order.bom_id is None:
        raise ValueError("فهرست مواد برای این دستور تعیین نشده است.")
    if order.material_warehouse_id is None:
        raise ValueError("انبار مواد مشخص نشده است.")
    if order.fg_warehouse_id is None:
        raise ValueError("انبار محصول مشخص نشده است.")
    if st.require_cost_center and order.cost_center_detail_account_id is None:
        raise ValueError("مرکز هزینه برای دستور تولید الزامی است.")
    c.require_roles(session, company_id, (c.WIP,))
    if engine._resolve_role_account(session, company_id, "INVENTORY_ASSET") is None:
        raise ValueError("حساب موجودی تعیین نشده است.")


def _snapshot(session, company_id: int, order: ProductionOrder) -> None:
    session.query(OrderMaterial).filter(OrderMaterial.order_id == order.order_id).delete()
    session.query(OrderOutput).filter(OrderOutput.order_id == order.order_id).delete()
    session.query(OrderOperation).filter(OrderOperation.order_id == order.order_id).delete()
    session.flush()
    bom = session.get(BomHeader, order.bom_id)
    date = order.start_date
    material_cost = ZERO
    for i, r in enumerate(material_plan(session, company_id, order.item_id, order.bom_id, order.planned_qty), start=1):
        ln = r.line
        wh = ln.warehouse_id or order.material_warehouse_id
        std = _standard_unit_cost(session, ln.component_item_id, date)
        unit = std if std is not None else _cost_estimate(session, ln.component_item_id, wh, date)
        if not ln.is_optional:
            material_cost += r.gross * unit
        session.add(OrderMaterial(order_id=order.order_id, line_no=i, item_id=ln.component_item_id, bom_line_id=ln.bom_line_id,
                                  component_type=ln.component_type or "MATERIAL", warehouse_id=ln.warehouse_id,
                                  operation_seq=ln.operation_seq, quantity_type=ln.quantity_type or "VARIABLE",
                                  quantity_per_base=r.base, batch_size_qty=bom.batch_size_qty, scrap_percent=r.scrap,
                                  planned_qty=r.gross, standard_unit_cost=c.qty(unit), is_optional=ln.is_optional,
                                  substitute_item_id=ln.substitute_item_id))
    factor = decimal.Decimal(order.planned_qty) / decimal.Decimal(bom.batch_size_qty)
    session.add(OrderOutput(order_id=order.order_id, item_id=order.item_id, output_type="MAIN", planned_qty=order.planned_qty))
    by_credit = ZERO
    for out in session.scalars(select(BomOutput).where(BomOutput.bom_id == order.bom_id)):
        planned = c.qty(decimal.Decimal(out.quantity_per) * factor)
        if out.output_type == "BY_PRODUCT":
            by_credit += planned * decimal.Decimal(out.recovery_value_per_unit or 0)
        session.add(OrderOutput(order_id=order.order_id, item_id=out.item_id, output_type=out.output_type, planned_qty=planned,
                                recovery_value_per_unit=out.recovery_value_per_unit, sales_value_per_unit=out.sales_value_per_unit,
                                weight_per_unit=out.weight_per_unit, cost_share_percent=out.cost_share_percent))
    conversion = ZERO
    if order.routing_id:
        for op in session.scalars(select(RoutingOperation).where(RoutingOperation.routing_id == order.routing_id)
                                  .order_by(RoutingOperation.seq)):
            wc = session.get(WorkCenter, op.work_center_id) if op.work_center_id else None
            hours = pm.op_hours(op, order.planned_qty)
            labor_rate = decimal.Decimal(op.labor_rate if op.labor_rate is not None else (wc.labor_rate if wc else 0))
            machine_rate = decimal.Decimal(op.machine_rate if op.machine_rate is not None else (wc.machine_rate if wc else 0))
            overhead_rate = decimal.Decimal(op.overhead_rate if op.overhead_rate is not None else (wc.overhead_rate if wc else 0))
            if op.asset_id and not machine_rate:
                machine_rate = _asset_rate(session, op.asset_id, date)
            conversion += hours.labor_hours * labor_rate + hours.machine_hours * machine_rate + hours.labor_hours * overhead_rate
            session.add(OrderOperation(order_id=order.order_id, seq=op.seq, name=op.name, work_center_id=op.work_center_id,
                                       asset_id=op.asset_id, labor_rate=labor_rate, machine_rate=machine_rate,
                                       overhead_rate=overhead_rate, std_labor_hours=hours.labor_hours,
                                       std_machine_hours=hours.machine_hours, std_elapsed_hours=hours.elapsed_hours,
                                       status_code="PENDING"))
    planned_total = material_cost + conversion - by_credit
    order.planned_unit_cost = c.qty(max(ZERO, planned_total) / decimal.Decimal(order.planned_qty))
    order.standard_unit_cost = _standard_unit_cost(session, order.item_id, date) or order.planned_unit_cost
    session.flush()


def _asset_rate(session, asset_id: int, date: datetime.date) -> decimal.Decimal:
    """نرخ ماشین از ماژول دارایی (نرخ دستی یا استهلاک دوره ÷ ساعت کارکرد)."""
    from peecha.db.models.fixed_assets import Asset

    asset = session.get(Asset, asset_id)
    if asset is None:
        return ZERO
    if asset.machine_rate:
        return decimal.Decimal(asset.machine_rate)
    try:
        from peecha.services.fixed_assets import common as fa_common, production as fa_prod

        info = fa_prod.machine_rate(asset.company_id, asset_id, fa_common.period_of(date)[0])
        return decimal.Decimal(info.rate or 0)
    except ValueError:
        return ZERO


# =====================================================================================
# شروع / توقف
# =====================================================================================
def start_order(company_id: int, user_id: int, order_id: int, date: datetime.date | None = None) -> None:
    with new_session() as session:
        order = lock_order(session, company_id, order_id)
        if order.status_code != "RELEASED":
            raise ValueError("فقط دستور صادرشده قابل شروع است.")
        order.status_code = "IN_PROGRESS"
        order.actual_start_date = order.actual_start_date or date or datetime.date.today()
        first = session.scalar(select(OrderOperation).where(OrderOperation.order_id == order_id).order_by(OrderOperation.seq).limit(1))
        if first is not None and first.status_code == "PENDING":
            first.status_code, first.started_at = "IN_PROGRESS", datetime.datetime.now()
        c.audit(session, company_id, user_id, "ProductionOrder", order_id, "START", {"status": ["RELEASED", "IN_PROGRESS"]})
        session.commit()


def hold_order(company_id: int, user_id: int, order_id: int, reason: str) -> None:
    if not (reason or "").strip():
        raise ValueError("دلیل توقف الزامی است.")
    _transition(company_id, user_id, order_id, ("RELEASED", "IN_PROGRESS"), "ON_HOLD", reason)


def resume_order(company_id: int, user_id: int, order_id: int) -> None:
    with new_session() as session:
        order = lock_order(session, company_id, order_id)
        if order.status_code != "ON_HOLD":
            raise ValueError("دستور متوقف نیست.")
        order.status_code = "IN_PROGRESS" if order.actual_start_date else "RELEASED"
        order.hold_reason = None
        c.audit(session, company_id, user_id, "ProductionOrder", order_id, "RESUME", {})
        session.commit()


def set_operation_status(company_id: int, user_id: int, order_operation_id: int, status: str,
                         completed_qty: decimal.Decimal | None = None) -> None:
    if status not in ("PENDING", "IN_PROGRESS", "DONE", "SKIPPED"):
        raise ValueError("وضعیت عملیات نامعتبر است.")
    with new_session() as session:
        op = session.get(OrderOperation, order_operation_id)
        order = lock_order(session, company_id, op.order_id) if op else None
        if order is None:
            raise ValueError("عملیات دستور نامعتبر است.")
        if order.status_code not in WORKING_STATUSES:
            raise ValueError("دستور فعال نیست.")
        op.status_code = status
        if status == "IN_PROGRESS" and op.started_at is None:
            op.started_at = datetime.datetime.now()
        if status == "DONE":
            op.finished_at = datetime.datetime.now()
            op.completed_qty = decimal.Decimal(completed_qty) if completed_qty is not None else order.planned_qty
            nxt = session.scalar(select(OrderOperation).where(OrderOperation.order_id == order.order_id,
                                                              OrderOperation.seq > op.seq, OrderOperation.status_code == "PENDING")
                                 .order_by(OrderOperation.seq).limit(1))
            if nxt is not None:
                nxt.status_code, nxt.started_at = "IN_PROGRESS", datetime.datetime.now()
        if order.status_code == "RELEASED" and status in ("IN_PROGRESS", "DONE"):
            order.status_code, order.actual_start_date = "IN_PROGRESS", order.actual_start_date or datetime.date.today()
        c.audit(session, company_id, user_id, "ProductionOrder", order.order_id, "OPERATION",
                {"seq": op.seq, "status": status})
        session.commit()


# =====================================================================================
# مصرفِ مواد
# =====================================================================================
@dataclass
class IssueLine:
    material_id: int
    quantity: decimal.Decimal
    item_id: int | None = None          # کالایِ جایگزین (اگر در BOM تعریف شده)
    warehouse_id: int | None = None


def _ensure_working(order: ProductionOrder) -> None:
    if order.status_code not in WORKING_STATUSES:
        raise ValueError(f"دستور در وضعیت «{STATUS_LABELS[order.status_code]}» است و این عملیات مجاز نیست.")


def issue_materials(company_id: int, user_id: int, order_id: int, lines: list[IssueLine], date: datetime.date | None = None,
                    idempotency_key: str | None = None, reason: str | None = None) -> list[int]:
    """ثبت مصرف واقعی مواد (حوالهٔ انبار، بدهکار WIP)."""
    with new_session() as session:
        if (done := _replayed(session, idempotency_key)) is not None:
            return [done.txn_id]
        order = lock_order(session, company_id, order_id)
        _ensure_working(order)
        txns = _issue(session, order, lines, date or datetime.date.today(), user_id, idempotency_key, reason)
        if order.status_code == "RELEASED":
            order.status_code, order.actual_start_date = "IN_PROGRESS", order.actual_start_date or date or datetime.date.today()
        session.commit()
        return [t.txn_id for t in txns]


def _issue(session, order: ProductionOrder, lines: list[IssueLine], date: datetime.date, user_id: int, key: str | None,
           reason: str | None = None, backflush: bool = False) -> list[OrderTransaction]:
    st = c.settings(session, order.company_id)
    by_wh: dict[int, list[tuple[OrderMaterial, IssueLine, int]]] = {}
    for ln in lines:
        q = decimal.Decimal(ln.quantity)
        if q <= 0:
            continue
        m = session.get(OrderMaterial, ln.material_id)
        if m is None or m.order_id != order.order_id:
            raise ValueError("ردیف مواد دستور نامعتبر است.")
        item_id = ln.item_id or m.item_id
        if item_id not in (m.item_id, m.substitute_item_id):
            raise ValueError("کالای مصرفی با ردیف فهرست مواد یا جایگزین تعریف‌شده هم‌خوان نیست.")
        if not st.allow_over_consumption and m.consumed_qty + q > decimal.Decimal(m.planned_qty):
            raise ValueError(f"مصرف «{c.item_label(session, m.item_id)}» از مقدار استاندارد بیشتر می‌شود و در تنظیمات مجاز نیست.")
        wh = ln.warehouse_id or m.warehouse_id or order.material_warehouse_id
        by_wh.setdefault(wh, []).append((m, ln, item_id))
    txns: list[OrderTransaction] = []
    for n, (wh, group) in enumerate(by_wh.items()):
        doc_lines, owners = [], []
        for m, ln, item_id in group:
            q = decimal.Decimal(ln.quantity)
            uom = session.get(Item, item_id).base_uom_id
            bins = _bins_with_stock(session, item_id, wh, free_only=False)
            left = q
            for bin_id, avail in bins:
                take = min(avail, left)
                if take <= 0:
                    break
                doc_lines.append(inv_docs.LineFields(item_id=item_id, uom_id=uom, quantity=take, quantity_base=take,
                                                     bin_location_id=bin_id, conversion_factor=ONE))
                owners.append((m, item_id, take))
                left -= take
            if left > 0:
                if not st.allow_negative_material:
                    raise ValueError(f"موجودی «{c.item_label(session, item_id)}» در انبار کافی نیست "
                                     f"(کمبود {c.qty(left).normalize()}).")
                doc_lines.append(inv_docs.LineFields(item_id=item_id, uom_id=uom, quantity=left, quantity_base=left,
                                                     conversion_factor=ONE))
                owners.append((m, item_id, left))
        result, line_ids = inv_docs.create_and_post_in_session(
            session, order.company_id, user_id, "ISSUE", date, _header(order, "مصرف مواد" + (" (Backflush)" if backflush else ""),
                                                                       source_warehouse_id=wh),
            doc_lines, role_overrides=_ISSUE_ROLES)
        amounts = _ledger_amounts(session, line_ids, "OUT")
        je_wip = _je_role_amount(session, order.company_id, result.journal_entry_id, c.WIP, debit=True)
        per_line = [amounts.get(lid, ZERO) for lid in line_ids]
        if je_wip is not None and per_line and sum(per_line) != je_wip:  # NIFO: بهایِ جایگزینی در سند
            per_line[-1] += je_wip - sum(per_line)
        for i, ((m, item_id, q), amount) in enumerate(zip(owners, per_line)):
            m.issued_qty = decimal.Decimal(m.issued_qty) + q
            m.issued_amount = decimal.Decimal(m.issued_amount) + amount
            _consume_reservation(session, m, q)
            k = key if (key and n == 0 and i == 0) else (f"{key}:{n}:{i}" if key else None)
            txns.append(record(session, order, "ISSUE", date, user_id, item_id=item_id, quantity=q, amount=amount,
                               wip_delta=amount, material_id=m.material_id, stock_document_id=result.stock_document_id,
                               journal_entry_id=result.journal_entry_id, reason=reason, key=k,
                               details={"backflush": True} if backflush else None))
        c.audit(session, order.company_id, user_id, "ProductionOrder", order.order_id, "ISSUE",
                {"stock_document_id": result.stock_document_id, "lines": len(owners), "reason": reason})
    return txns


def issue_all_remaining(company_id: int, user_id: int, order_id: int, date: datetime.date | None = None,
                        idempotency_key: str | None = None) -> list[int]:
    """مصرف کامل باقیماندهٔ استاندارد (دکمهٔ «ثبت مصرف» برای کاربر ساده)."""
    with new_session() as session:
        if (done := _replayed(session, idempotency_key)) is not None:
            return [done.txn_id]
        mats = list(session.scalars(select(OrderMaterial).where(OrderMaterial.order_id == order_id)))
        lines = [IssueLine(m.material_id, decimal.Decimal(m.planned_qty) - m.consumed_qty) for m in mats
                 if not m.is_optional and decimal.Decimal(m.planned_qty) > m.consumed_qty]
    if not lines:
        raise ValueError("ماده‌ای برای مصرف باقی نمانده است.")
    return issue_materials(company_id, user_id, order_id, lines, date, idempotency_key)


def _backflush(session, order: ProductionOrder, produced_after: decimal.Decimal, date: datetime.date, user_id: int,
               key: str | None) -> None:
    """مصرف خودکار بر اساس فهرست مواد تا سطح «تولید تجمعی» (فقط کمبود مصرف نسبت به استاندارد)."""
    lines = []
    for m in session.scalars(select(OrderMaterial).where(OrderMaterial.order_id == order.order_id)):
        if m.is_optional:
            continue
        _net, target = pm.line_requirement(m.quantity_per_base, m.quantity_type, m.scrap_percent, produced_after, m.batch_size_qty)
        gap = target - m.consumed_qty
        if gap > 0:
            lines.append(IssueLine(m.material_id, c.qty(gap)))
    if lines:
        _issue(session, order, lines, date, user_id, f"{key}:bf" if key else None, backflush=True)


# =====================================================================================
# برگشتِ مواد
# =====================================================================================
def return_materials(company_id: int, user_id: int, order_id: int, lines: list[IssueLine], date: datetime.date | None = None,
                     idempotency_key: str | None = None, reason: str | None = None) -> list[int]:
    """برگشت مواد مصرف‌نشده به انبار با همان بهای میانگین حوالهٔ همین دستور (بستانکار WIP)."""
    date = date or datetime.date.today()
    with new_session() as session:
        if (done := _replayed(session, idempotency_key)) is not None:
            return [done.txn_id]
        order = lock_order(session, company_id, order_id)
        if order.status_code not in ACTIVE_STATUSES + ("COMPLETED",):
            raise ValueError(f"دستور در وضعیت «{STATUS_LABELS[order.status_code]}» است و برگشت مواد مجاز نیست.")
        by_wh: dict[int, list] = {}
        for ln in lines:
            q = decimal.Decimal(ln.quantity)
            if q <= 0:
                continue
            m = session.get(OrderMaterial, ln.material_id)
            if m is None or m.order_id != order_id:
                raise ValueError("ردیف مواد دستور نامعتبر است.")
            if q > m.consumed_qty:
                raise ValueError(f"مقدار برگشت «{c.item_label(session, m.item_id)}» از مقدار خالص حواله‌شده "
                                 f"({m.consumed_qty.normalize()}) بیشتر است.")
            unit = c.qty(m.consumed_amount / m.consumed_qty) if m.consumed_qty else ZERO
            wh = ln.warehouse_id or m.warehouse_id or order.material_warehouse_id
            by_wh.setdefault(wh, []).append((m, q, unit))
        txns = []
        for n, (wh, group) in enumerate(by_wh.items()):
            doc_lines = [inv_docs.LineFields(item_id=m.item_id, uom_id=session.get(Item, m.item_id).base_uom_id, quantity=q,
                                             quantity_base=q, unit_cost=unit, conversion_factor=ONE) for m, q, unit in group]
            result, line_ids = inv_docs.create_and_post_in_session(
                session, company_id, user_id, "RECEIPT", date, _header(order, "برگشت مواد", destination_warehouse_id=wh),
                doc_lines, role_overrides=_RECEIPT_ROLES)
            for i, (m, q, unit) in enumerate(group):
                amount = c.money(unit * q)
                m.returned_qty = decimal.Decimal(m.returned_qty) + q
                m.returned_amount = decimal.Decimal(m.returned_amount) + amount
                k = idempotency_key if (idempotency_key and n == 0 and i == 0) else (f"{idempotency_key}:{n}:{i}" if idempotency_key else None)
                txns.append(record(session, order, "RETURN", date, user_id, item_id=m.item_id, quantity=q, amount=amount,
                                   wip_delta=-amount, material_id=m.material_id, stock_document_id=result.stock_document_id,
                                   journal_entry_id=result.journal_entry_id, reason=reason, key=k))
            c.audit(session, company_id, user_id, "ProductionOrder", order_id, "RETURN",
                    {"stock_document_id": result.stock_document_id, "reason": reason})
        session.commit()
        return [t.txn_id for t in txns]


# =====================================================================================
# ثبتِ تولید (رسیدِ محصول + جانبی + مشترک)
# =====================================================================================
@dataclass
class ReceiptInput:
    quantity: decimal.Decimal
    outputs: dict[int, decimal.Decimal] = field(default_factory=dict)   # کالایِ جانبی/مشترک → مقدار
    batch_no: str | None = None
    serial_nos: list[str] | None = None
    final: bool = False
    joint_method: str | None = None
    manual_shares: dict[int, decimal.Decimal] | None = None   # برایِ PERCENTAGE (درصد) یا MANUAL (مبلغ) -- کلید: item_id
    sales_values: dict[int, decimal.Decimal] | None = None    # ارزشِ فروش/خالصِ بازیافتنیِ واحد (SALES_VALUE / NRV)


def report_production(company_id: int, user_id: int, order_id: int, data: ReceiptInput, date: datetime.date | None = None,
                      idempotency_key: str | None = None) -> int:
    """رسید محصول به انبار با بهای واقعی کالای در جریان ساخت (بهای برنامه‌ای، حداکثر تا ماندهٔ کالای در جریان ساخت؛ رسید نهایی کل مانده را می‌برد)."""
    date = date or datetime.date.today()
    with new_session() as session:
        if (done := _replayed(session, idempotency_key)) is not None:
            return done.txn_id
        order = lock_order(session, company_id, order_id)
        _ensure_working(order)
        txn = _receive(session, order, data, date, user_id, idempotency_key)
        session.commit()
        return txn.txn_id


def _weights(session, order: ProductionOrder, joint: list[tuple[OrderOutput, decimal.Decimal]], method: str,
             manual: dict[int, decimal.Decimal] | None, sales_values: dict[int, decimal.Decimal] | None = None
             ) -> list[decimal.Decimal]:
    def weight_of(o: OrderOutput) -> decimal.Decimal:
        if o.weight_per_unit:
            return decimal.Decimal(o.weight_per_unit)
        prof = session.get(ItemProductionProfile, o.item_id)
        if prof is not None and prof.weight_per_unit:
            return decimal.Decimal(prof.weight_per_unit)
        item = session.get(Item, o.item_id)
        return decimal.Decimal(item.weight_kg or 0)

    if method == "QUANTITY":
        return [q for _o, q in joint]
    if method == "WEIGHT":
        return [q * weight_of(o) for o, q in joint]
    if method in ("SALES_VALUE", "NRV"):
        values = sales_values or {}
        return [q * decimal.Decimal(values.get(o.item_id, o.sales_value_per_unit or _sales_price(session, o.item_id)))
                for o, q in joint]
    if method in ("PERCENTAGE", "MANUAL"):
        shares = manual or {}
        values = [decimal.Decimal(shares.get(o.item_id, o.cost_share_percent or 0)) for o, _q in joint]
        if method == "PERCENTAGE" and sum(values) != _HUNDRED:
            raise ValueError("جمع درصدهای تخصیص تولید مشترک باید ۱۰۰ باشد.")
        return values
    raise ValueError("روش تخصیص تولید مشترک نامعتبر است.")


def _sales_price(session, item_id: int) -> decimal.Decimal:
    """میانگین فی فروش ثبت‌شده (فاکتورهای فروش) — مبنای پیش‌فرض «ارزش فروش»."""
    from peecha.db.models.commercial import CommercialDocument, CommercialDocumentLine

    q, v = session.execute(select(func.sum(CommercialDocumentLine.quantity), func.sum(CommercialDocumentLine.quantity * CommercialDocumentLine.unit_price))
                           .join(CommercialDocument, CommercialDocument.document_id == CommercialDocumentLine.document_id)
                           .where(CommercialDocumentLine.item_id == item_id, CommercialDocument.document_type_code == "SALES_INVOICE",
                                  CommercialDocument.status_code == "POSTED")).one()
    return decimal.Decimal(v) / decimal.Decimal(q) if q else ZERO


def allocate_joint(total: decimal.Decimal, weights: list[decimal.Decimal], method: str = "QUANTITY") -> list[decimal.Decimal]:
    """سرشکن هزینهٔ مشترک بر اساس وزن‌ها؛ گردکردن روی آخرین سهم. MANUAL = مبلغ مستقیم."""
    if method == "MANUAL":
        if c.money(sum(weights)) != c.money(total):
            raise ValueError(f"جمع مبالغ دستی ({c.money(sum(weights))}) با هزینهٔ مشترک ({c.money(total)}) برابر نیست.")
        return [c.money(w) for w in weights]
    base = sum(weights)
    if base <= 0:
        raise ValueError("مبنای تخصیص تولید مشترک صفر است (وزن/ارزش فروش محصولات تعریف نشده).")
    shares = [c.money(total * w / base) for w in weights]
    if shares:
        shares[-1] += c.money(total) - sum(shares)
    return shares


def _receive(session, order: ProductionOrder, data: ReceiptInput, date: datetime.date, user_id: int,
             key: str | None) -> OrderTransaction:
    st = c.settings(session, order.company_id)
    q = decimal.Decimal(data.quantity)
    if q < 0:
        raise ValueError("مقدار تولید نمی‌تواند منفی باشد.")
    outputs = {o.item_id: o for o in session.scalars(select(OrderOutput).where(OrderOutput.order_id == order.order_id))}
    main = next((o for o in outputs.values() if o.output_type == "MAIN"), None)
    if main is None:
        raise ValueError("دستور صادر نشده است.")
    extra = [(outputs[iid], decimal.Decimal(v)) for iid, v in data.outputs.items() if decimal.Decimal(v) > 0]
    for iid in data.outputs:
        if iid not in outputs or outputs[iid].output_type == "MAIN":
            raise ValueError("کالای خروجی در فهرست مواد این دستور تعریف نشده است.")
    if q == 0 and not extra:
        raise ValueError("مقدار تولید صفر است.")
    remaining = order.remaining_qty
    final = data.final or (q > 0 and q >= remaining)
    if st.auto_consumption or _profile_backflush(session, order.item_id):
        _backflush(session, order, decimal.Decimal(order.produced_qty) + q, date, user_id, key)
    if st.auto_cost_calculation:
        from peecha.services.production import costing as pcost

        pcost.apply_standard_conversion(session, order, decimal.Decimal(order.produced_qty) + q, date, user_id, key)
    wip = max(ZERO, wip_balance(session, order.order_id))
    by_items = [(o, v, c.money(decimal.Decimal(o.recovery_value_per_unit or 0) * v)) for o, v in extra if o.output_type == "BY_PRODUCT"]
    by_sum = sum((x[2] for x in by_items), ZERO)
    co = [(o, v) for o, v in extra if o.output_type == "CO_PRODUCT"]
    joint = ([(main, q)] if q > 0 else []) + co
    if not joint:
        pull = min(wip, by_sum)
    elif final:
        pull = wip
    else:
        pull = min(wip, c.money(decimal.Decimal(order.planned_unit_cost or 0) * q) + by_sum)
    by_total = min(pull, by_sum)
    joint_pool = pull - by_total
    by_values = [(o, v, c.money(val * by_total / by_sum) if by_sum else ZERO) for o, v, val in by_items]
    if by_values:
        by_values[-1] = (by_values[-1][0], by_values[-1][1], by_values[-1][2] + by_total - sum(x[2] for x in by_values))
    method = data.joint_method or order.joint_cost_method or "QUANTITY"
    if data.joint_method and data.joint_method != order.joint_cost_method:
        if data.joint_method not in c.JOINT_METHODS:
            raise ValueError("روش تخصیص تولید مشترک نامعتبر است.")
        order.joint_cost_method = data.joint_method
    shares = (allocate_joint(joint_pool, _weights(session, order, joint, method, data.manual_shares, data.sales_values), method)
              if len(joint) > 1 else [c.money(joint_pool)] * len(joint))
    lines, owners, tracking = [], [], {}
    for (o, v), amount in zip(joint, shares):
        owners.append((o, v, amount, "RECEIPT" if o.output_type == "MAIN" else "CO_PRODUCT"))
    for o, v, value in by_values:
        owners.append((o, v, value, "BY_PRODUCT"))
    for idx, (o, v, amount, _t) in enumerate(owners):
        item = session.get(Item, o.item_id)
        unit = c.qty(amount / v) if v else ZERO
        lines.append(inv_docs.LineFields(item_id=o.item_id, uom_id=item.base_uom_id, quantity=v, quantity_base=v, unit_cost=unit,
                                         conversion_factor=ONE))
        tracking[idx] = _tracking_for(session, order, item, v, date, data if o.output_type == "MAIN" else None)
    result, line_ids = inv_docs.create_and_post_in_session(
        session, order.company_id, user_id, "RECEIPT", date, _header(order, "رسید محصول تولید", destination_warehouse_id=order.fg_warehouse_id),
        lines, role_overrides=_RECEIPT_ROLES, tracking=tracking)
    first = None
    for i, (o, v, amount, ttype) in enumerate(owners):
        unit = c.qty(amount / v) if v else ZERO
        posted = c.money(unit * v)
        o.produced_qty = decimal.Decimal(o.produced_qty) + v
        o.produced_amount = decimal.Decimal(o.produced_amount) + posted
        k = key if (key and i == 0) else (f"{key}:{i}" if key else None)
        t = record(session, order, ttype, date, user_id, item_id=o.item_id, quantity=v, amount=posted, wip_delta=-posted,
                   output_id=o.output_id, stock_document_id=result.stock_document_id, journal_entry_id=result.journal_entry_id,
                   key=k, details={"final": final, "joint_method": method if len(joint) > 1 else None})
        first = first or t
    order.produced_qty = decimal.Decimal(order.produced_qty) + q
    if q > 0:
        for op in session.scalars(select(OrderOperation).where(OrderOperation.order_id == order.order_id)):
            op.completed_qty = max(decimal.Decimal(op.completed_qty), decimal.Decimal(order.produced_qty))
    if order.status_code == "RELEASED":
        order.status_code, order.actual_start_date = "IN_PROGRESS", order.actual_start_date or date
    c.audit(session, order.company_id, user_id, "ProductionOrder", order.order_id, "RECEIPT",
            {"quantity": str(q), "outputs": {str(k): str(v) for k, v in data.outputs.items()}, "pull": str(pull),
             "stock_document_id": result.stock_document_id})
    return first


def _profile_backflush(session, item_id: int) -> bool:
    prof = session.get(ItemProductionProfile, item_id)
    return bool(prof and prof.backflush)


def _tracking_for(session, order: ProductionOrder, item: Item, quantity: decimal.Decimal, date: datetime.date,
                  data: ReceiptInput | None) -> list:
    """بچ/سریال محصول: بچ پیش‌فرض = کد دستور؛ سریال‌ها اگر داده نشده باشند خودکار ساخته می‌شوند."""
    from peecha.services.lot_tracking import TrackingEntry

    if not (item.track_batch or item.track_serial):
        return []
    batch = (data.batch_no if data and data.batch_no else order.order_code) if item.track_batch else None
    expiry = date + datetime.timedelta(days=item.shelf_life_days) if item.track_expiry and item.shelf_life_days else None
    if item.track_expiry and expiry is None:
        raise ValueError(f"«{c.item_label(session, item.item_id)}» تاریخ انقضا می‌خواهد ولی عمر مفید (shelf life) تعریف نشده است.")
    if not item.track_serial:
        return [TrackingEntry(quantity=quantity, batch_no=batch, manufacture_date=date, expiry_date=expiry)]
    if quantity != quantity.to_integral_value():
        raise ValueError("کالای سریال‌دار باید با مقدار صحیح تولید شود.")
    serials = list((data.serial_nos if data else None) or [])
    if not serials:
        start = int(decimal.Decimal(session.scalar(select(func.coalesce(func.sum(OrderOutput.produced_qty), 0)).where(
            OrderOutput.order_id == order.order_id, OrderOutput.item_id == item.item_id)) or 0))
        serials = [f"{order.order_code}-{start + i + 1:04d}" for i in range(int(quantity))]
    if len(serials) != int(quantity):
        raise ValueError("تعداد سریال‌ها با مقدار تولید برابر نیست.")
    return [TrackingEntry(quantity=ONE, batch_no=batch, manufacture_date=date, expiry_date=expiry, serial_no=s) for s in serials]


def reverse_production(company_id: int, user_id: int, txn_id: int, reason: str, date: datetime.date | None = None,
                       idempotency_key: str | None = None) -> int:
    """برگشت تولید: محصول رسیدشده با حواله از انبار محصول به کالای در جریان ساخت برمی‌گردد (ردیف برگشتی؛ ردیف اصلی دست نمی‌خورد)."""
    if not (reason or "").strip():
        raise ValueError("دلیل برگشت تولید الزامی است.")
    date = date or datetime.date.today()
    with new_session() as session:
        if (done := _replayed(session, idempotency_key)) is not None:
            return done.txn_id
        txn = session.get(OrderTransaction, txn_id)
        if txn is None or txn.company_id != company_id or txn.txn_type not in ("RECEIPT", "CO_PRODUCT", "BY_PRODUCT"):
            raise ValueError("فقط رسید محصول قابل برگشت است.")
        if session.scalar(select(OrderTransaction.txn_id).where(OrderTransaction.reversed_txn_id == txn_id)):
            raise ValueError("این رسید قبلاً برگشت خورده است.")
        order = lock_order(session, company_id, txn.order_id)
        if order.status_code in ("CLOSED", "CANCELLED"):
            raise ValueError("دستور بسته/لغوشده قابل تغییر نیست — ابتدا دستور را بازگشایی کنید.")
        item = session.get(Item, txn.item_id)
        q = decimal.Decimal(txn.quantity)
        result, line_ids = inv_docs.create_and_post_in_session(
            session, company_id, user_id, "ISSUE", date, _header(order, f"برگشت تولید -- {reason}", source_warehouse_id=order.fg_warehouse_id),
            [inv_docs.LineFields(item_id=txn.item_id, uom_id=item.base_uom_id, quantity=q, quantity_base=q, conversion_factor=ONE,
                                 bin_location_id=(_bins_with_stock(session, txn.item_id, order.fg_warehouse_id, False) or [(None, 0)])[0][0])],
            role_overrides=_ISSUE_ROLES)
        amount = sum(_ledger_amounts(session, line_ids, "OUT").values(), ZERO)
        out = session.get(OrderOutput, txn.output_id)
        out.produced_qty = decimal.Decimal(out.produced_qty) - q
        out.produced_amount = decimal.Decimal(out.produced_amount) - amount
        if txn.txn_type == "RECEIPT":
            order.produced_qty = decimal.Decimal(order.produced_qty) - q
            if order.status_code == "COMPLETED":
                order.status_code = "IN_PROGRESS"
        rev = record(session, order, "REVERSAL", date, user_id, item_id=txn.item_id, quantity=-q, amount=-amount, wip_delta=amount,
                     output_id=txn.output_id, stock_document_id=result.stock_document_id, journal_entry_id=result.journal_entry_id,
                     reason=reason, key=idempotency_key, reversed_txn_id=txn_id, details={"of": txn.txn_type})
        c.audit(session, company_id, user_id, "ProductionOrder", order.order_id, "REVERSE_RECEIPT",
                {"txn_id": txn_id, "quantity": str(q), "reason": reason})
        session.commit()
        return rev.txn_id


# =====================================================================================
# ضایعات
# =====================================================================================
def report_scrap(company_id: int, user_id: int, order_id: int, quantity, reason: str, *, material_id: int | None = None,
                 scrap_item_id: int | None = None, recovery_value_per_unit=None, date: datetime.date | None = None,
                 idempotency_key: str | None = None) -> int:
    """ضایعات محصول (یا ثبت ضایعات ماده برای تحلیل). ضایعات قابل فروش با ارزش بازیافت به انبار ضایعات می‌رود
    (بستانکار WIP)؛ مازاد «ضایعات عادی» (درصد تنظیمات/کالا) به زیان ضایعات غیرعادی منتقل می‌شود."""
    quantity = decimal.Decimal(quantity)
    if quantity <= 0:
        raise ValueError("مقدار ضایعات باید بزرگ‌تر از صفر باشد.")
    date = date or datetime.date.today()
    with new_session() as session:
        if (done := _replayed(session, idempotency_key)) is not None:
            return done.txn_id
        order = lock_order(session, company_id, order_id)
        _ensure_working(order)
        if material_id is not None:  # ضایعاتِ ماده: فقط ثبتِ تحلیلی (مصرفِ واقعی قبلاً در حواله آمده)
            m = session.get(OrderMaterial, material_id)
            if m is None or m.order_id != order_id:
                raise ValueError("ردیف مواد دستور نامعتبر است.")
            t = record(session, order, "SCRAP", date, user_id, item_id=m.item_id, quantity=quantity, material_id=material_id,
                       reason=reason, key=idempotency_key, details={"kind": "MATERIAL"})
            c.audit(session, company_id, user_id, "ProductionOrder", order_id, "SCRAP_MATERIAL", {"item_id": m.item_id, "qty": str(quantity)})
            session.commit()
            return t.txn_id
        order.scrapped_qty = decimal.Decimal(order.scrapped_qty) + quantity
        recovery = ZERO
        doc_id = je_id = None
        if scrap_item_id is not None:
            wh = order.scrap_warehouse_id or order.fg_warehouse_id
            rate = decimal.Decimal(recovery_value_per_unit or 0)
            recovery = min(max(ZERO, wip_balance(session, order_id)), c.money(rate * quantity))
            unit = c.qty(recovery / quantity)
            item = c.item_of(session, company_id, scrap_item_id)
            result, _ids = inv_docs.create_and_post_in_session(
                session, company_id, user_id, "RECEIPT", date, _header(order, "ضایعات قابل بازیافت", destination_warehouse_id=wh),
                [inv_docs.LineFields(item_id=scrap_item_id, uom_id=item.base_uom_id, quantity=quantity, quantity_base=quantity,
                                     unit_cost=unit, conversion_factor=ONE)], role_overrides=_RECEIPT_ROLES)
            recovery, doc_id, je_id = c.money(unit * quantity), result.stock_document_id, result.journal_entry_id
        t = record(session, order, "SCRAP", date, user_id, item_id=scrap_item_id or order.item_id, quantity=quantity, amount=recovery,
                   wip_delta=-recovery, stock_document_id=doc_id, journal_entry_id=je_id, reason=reason, key=idempotency_key,
                   details={"kind": "PRODUCT", "recovery_rate": str(recovery_value_per_unit or 0)})
        _abnormal_scrap(session, order, date, user_id, idempotency_key)
        c.audit(session, company_id, user_id, "ProductionOrder", order_id, "SCRAP",
                {"qty": str(quantity), "recovery": str(recovery), "reason": reason})
        session.commit()
        return t.txn_id


def normal_scrap_percent(session, order: ProductionOrder) -> decimal.Decimal:
    st = c.settings(session, order.company_id)
    prof = session.get(ItemProductionProfile, order.item_id)
    return max(decimal.Decimal(st.abnormal_scrap_percent or 0), decimal.Decimal(prof.standard_scrap_percent if prof else 0))


def _abnormal_scrap(session, order: ProductionOrder, date: datetime.date, user_id: int, key: str | None) -> None:
    """واحدهای ضایعات بیش از حد عادی × بهای برنامه‌ای ← زیان ضایعات (یک بار برای هر واحد)."""
    allowed = normal_scrap_percent(session, order) * decimal.Decimal(order.planned_qty) / _HUNDRED
    abnormal_units = max(ZERO, decimal.Decimal(order.scrapped_qty) - allowed)
    booked = decimal.Decimal(session.scalar(select(func.coalesce(func.sum(OrderTransaction.quantity), 0)).where(
        OrderTransaction.order_id == order.order_id, OrderTransaction.txn_type == "VARIANCE",
        OrderTransaction.reason == "ABNORMAL_SCRAP")) or 0)
    new_units = abnormal_units - booked
    if new_units <= 0:
        return
    amount = min(max(ZERO, wip_balance(session, order.order_id)), c.money(new_units * decimal.Decimal(order.planned_unit_cost or 0)))
    je = c.post_journal(session, order.company_id, user_id, date, f"{order.order_code} -- ضایعات غیرعادی",
                        [(c.SCRAP_LOSS, amount, ZERO, _dims(order)), (c.WIP, ZERO, amount, _dims(order))]) if amount else None
    record(session, order, "VARIANCE", date, user_id, item_id=order.item_id, quantity=new_units, amount=amount, wip_delta=-amount,
           journal_entry_id=je, reason="ABNORMAL_SCRAP", key=f"{key}:abn" if key else None,
           details={"kind": "ABNORMAL_SCRAP", "allowed_units": str(allowed)})


# =====================================================================================
# اتمام / بستن / بازگشایی / لغو
# =====================================================================================
def complete_order(company_id: int, user_id: int, order_id: int, final: ReceiptInput | None = None,
                   date: datetime.date | None = None, idempotency_key: str | None = None) -> None:
    """اتمام تولید (اختیاری با رسید نهایی). مقدار تولید صفر = توقف."""
    date = date or datetime.date.today()
    with new_session() as session:
        if idempotency_key and _replayed(session, idempotency_key) is not None:
            return
        order = lock_order(session, company_id, order_id)
        if order.status_code == "ON_HOLD":
            raise ValueError("دستور متوقف را ابتدا ادامه دهید.")
        _ensure_working(order)
        st = c.settings(session, company_id)
        if final is not None and (decimal.Decimal(final.quantity) > 0 or final.outputs):
            final.final = True
            _receive(session, order, final, date, user_id, f"{idempotency_key}:rcv" if idempotency_key else None)
        if decimal.Decimal(order.produced_qty) <= 0:
            raise ValueError("مقدار تولید صفر است — ابتدا تولید را ثبت کنید.")
        if not st.allow_under_consumption:
            for m in session.scalars(select(OrderMaterial).where(OrderMaterial.order_id == order_id)):
                _net, std = pm.line_requirement(m.quantity_per_base, m.quantity_type, m.scrap_percent, order.produced_qty,
                                                m.batch_size_qty)
                if not m.is_optional and m.consumed_qty < std:
                    raise ValueError(f"مصرف «{c.item_label(session, m.item_id)}» کمتر از استاندارد است و در تنظیمات مجاز نیست.")
        if st.auto_cost_calculation:
            from peecha.services.production import costing as pcost

            pcost.apply_standard_conversion(session, order, decimal.Decimal(order.produced_qty), date, user_id,
                                            f"{idempotency_key}:cmp" if idempotency_key else None)
        _release_all(session, order_id)
        for op in session.scalars(select(OrderOperation).where(OrderOperation.order_id == order_id,
                                                               OrderOperation.status_code.in_(("PENDING", "IN_PROGRESS")))):
            op.status_code, op.finished_at = "DONE", datetime.datetime.now()
        order.status_code, order.completed_at = "COMPLETED", datetime.datetime.now()
        order.actual_end_date = date
        c.audit(session, company_id, user_id, "ProductionOrder", order_id, "COMPLETE",
                {"produced": str(order.produced_qty), "scrapped": str(order.scrapped_qty)})
        if idempotency_key:
            record(session, order, "VARIANCE", date, user_id, reason="COMPLETE_MARK", key=idempotency_key,
                   details={"kind": "MARKER"})
        session.commit()


def closing_checklist(company_id: int, order_id: int) -> list[SimpleNamespace]:
    """کنترل‌های پیش از بستن (بند ۴۵)."""
    with new_session() as session:
        order = session.get(ProductionOrder, order_id)
        if order is None or order.company_id != company_id:
            raise ValueError("دستور تولید نامعتبر است.")
        return _checklist(session, order)


def _checklist(session, order: ProductionOrder) -> list[SimpleNamespace]:
    txns = list(session.scalars(select(OrderTransaction).where(OrderTransaction.order_id == order.order_id)))
    types = {t.txn_type for t in txns}
    open_res = session.scalar(select(func.count()).select_from(StockReservation).where(
        StockReservation.source_type_code == RESERVATION_SOURCE, StockReservation.status_code == "ACTIVE",
        StockReservation.source_record_id.in_(select(OrderMaterial.material_id).where(OrderMaterial.order_id == order.order_id))))
    missing_je = [t.txn_id for t in txns if t.stock_document_id and t.amount and t.journal_entry_id is None]
    st = c.settings(session, order.company_id)
    has_conversion = bool(types & {"LABOR", "MACHINE", "OVERHEAD"})
    has_ops = session.scalar(select(func.count()).select_from(OrderOperation).where(OrderOperation.order_id == order.order_id))
    item = lambda key, label, ok, note="": SimpleNamespace(key=key, label=label, ok=bool(ok), note=note)  # noqa: E731
    return [
        item("STATUS", "تولید تکمیل شده", order.status_code == "COMPLETED", STATUS_LABELS[order.status_code]),
        item("CONSUMPTION", "مصرف مواد ثبت شده", "ISSUE" in types),
        item("RETURN", "رزرو باز/مواد برگشت‌نشده ندارد", not open_res, f"{open_res} رزرو باز" if open_res else ""),
        item("RECEIPT", "رسید محصول ثبت شده", decimal.Decimal(order.produced_qty) > 0),
        item("SCRAP", "ضایعات بررسی شده", True, f"{decimal.Decimal(order.scrapped_qty).normalize()} واحد"),
        item("COST", "بهای تمام‌شده محاسبه شده", has_conversion or not has_ops or not st.auto_cost_calculation),
        item("OVERHEAD", "سربار تخصیص یافته", "OVERHEAD" in types or not has_ops, ""),
        item("ACCOUNTING", "اسناد حسابداری کامل", not missing_je, f"{len(missing_je)} تراکنش بی‌سند" if missing_je else ""),
        item("VARIANCE", "انحراف‌ها محاسبه شده", True, ""),
    ]


BLOCKING_CHECKS = ("STATUS", "CONSUMPTION", "RECEIPT", "ACCOUNTING")


def close_order(company_id: int, user_id: int, order_id: int, date: datetime.date | None = None,
                reason: str | None = None) -> SimpleNamespace:
    """بستن: ماندهٔ کالای در جریان ساخت به انحراف تولید، ثبت خلاصهٔ بها/انحراف، قفل دستور."""
    date = date or datetime.date.today()
    with new_session() as session:
        order = lock_order(session, company_id, order_id)
        if order.status_code == "CLOSED":
            raise ValueError("دستور قبلاً بسته شده است.")
        failed = [x for x in _checklist(session, order) if not x.ok and x.key in BLOCKING_CHECKS]
        if failed:
            raise ValueError("پیش از بستن: " + "، ".join(x.label for x in failed))
        _release_all(session, order_id)
        residual = wip_balance(session, order_id)
        je = None
        if residual:
            lines = [(c.VARIANCE, residual, ZERO, _dims(order)), (c.WIP, ZERO, residual, _dims(order))] if residual > 0 else [
                (c.WIP, -residual, ZERO, _dims(order)), (c.VARIANCE, ZERO, -residual, _dims(order))]
            je = c.post_journal(session, company_id, user_id, date, f"{order.order_code} -- انحراف بستن دستور تولید", lines)
            record(session, order, "VARIANCE", date, user_id, item_id=order.item_id, amount=residual, wip_delta=-residual,
                   journal_entry_id=je, reason="CLOSE_RESIDUAL", details={"kind": "CLOSE_RESIDUAL"})
        from peecha.services.production import costing as pcost

        summary = pcost.store_summary(session, order)
        order.status_code, order.closed_at, order.closed_by_user_id = "CLOSED", datetime.datetime.now(), user_id
        c.audit(session, company_id, user_id, "ProductionOrder", order_id, "CLOSE",
                {"residual": str(residual), "journal_entry_id": je, "reason": reason,
                 "actual_unit_cost": str(summary.actual_unit_cost)})
        session.commit()
        return SimpleNamespace(residual=residual, journal_entry_id=je, summary=summary)


def reopen_order(company_id: int, user_id: int, order_id: int, reason: str) -> None:
    """بازگشایی (مجوز ویژه در UI): دستور بسته به «تکمیل‌شده» برمی‌گردد؛ اسناد قبلی دست نمی‌خورند."""
    if not (reason or "").strip():
        raise ValueError("دلیل بازگشایی الزامی است.")
    with new_session() as session:
        order = lock_order(session, company_id, order_id)
        if order.status_code != "CLOSED":
            raise ValueError("فقط دستور بسته قابل بازگشایی است.")
        from peecha.services.production import costing as pcost

        if pcost.period_is_closed(session, company_id, order.closed_at.date() if order.closed_at else datetime.date.today()):
            raise ValueError("دورهٔ بهای این دستور بسته شده است — ابتدا بستن دوره را بازگشایی کنید.")
        order.status_code, order.closed_at, order.closed_by_user_id = "IN_PROGRESS", None, None
        c.audit(session, company_id, user_id, "ProductionOrder", order_id, "REOPEN", {"reason": reason})
        session.commit()


def cancel_order(company_id: int, user_id: int, order_id: int, reason: str) -> None:
    if not (reason or "").strip():
        raise ValueError("دلیل لغو الزامی است.")
    with new_session() as session:
        order = lock_order(session, company_id, order_id)
        if order.status_code in ("COMPLETED", "CLOSED", "CANCELLED"):
            raise ValueError("دستور تکمیل/بسته/لغوشده قابل لغو نیست.")
        if decimal.Decimal(order.produced_qty) > 0 or wip_balance(session, order_id) != 0:
            raise ValueError("این دستور تولید یا کالای در جریان ساخت دارد — ابتدا مواد را برگشت و تولید را برگشت بزنید.")
        _release_all(session, order_id)
        before = order.status_code
        order.status_code = "CANCELLED"
        c.audit(session, company_id, user_id, "ProductionOrder", order_id, "CANCEL", {"status": [before, "CANCELLED"], "reason": reason})
        session.commit()


# =====================================================================================
# حذف / بازگشت به پیش‌نویس (R280) — فقط دستورِ بدونِ گردش
# =====================================================================================
def order_has_movement(session, order_id: int) -> bool:
    """گردش = هر تراکنش تولید (مصرف، تولید، ضایعات...)، دستمزد، ساعت ماشین یا سرشکن هزینه روی دستور."""
    from peecha.db.models.production import CostAllocationRow, LaborEntry, MachineEntry

    for model in (OrderTransaction, LaborEntry, MachineEntry, CostAllocationRow):
        if session.scalar(select(model.order_id).where(model.order_id == order_id).limit(1)) is not None:
            return True
    return False


def _require_no_movement(session, order: ProductionOrder, action: str) -> None:
    if order_has_movement(session, order.order_id):
        raise ValueError(f"دستور {order.order_code} گردش دارد (مصرف، تولید، دستمزد یا هزینه ثبت شده) و قابل {action} نیست — "
                         "در صورت نیاز آن را لغو کنید.")


def _clear_snapshot(session, order: ProductionOrder) -> None:
    _release_all(session, order.order_id)
    session.query(OrderMaterial).filter(OrderMaterial.order_id == order.order_id).delete()
    session.query(OrderOutput).filter(OrderOutput.order_id == order.order_id).delete()
    session.query(OrderOperation).filter(OrderOperation.order_id == order.order_id).delete()
    session.flush()


def revert_to_draft(company_id: int, user_id: int, order_id: int) -> None:
    """دستور صادرشده/شروع‌شده‌ای که هنوز گردشی ندارد به پیش‌نویس برمی‌گردد تا ویرایش شود (رزروها آزاد می‌شوند)."""
    with new_session() as session:
        order = lock_order(session, company_id, order_id)
        if order.status_code in EDITABLE_STATUSES:
            return
        if order.status_code not in ("RELEASED", "IN_PROGRESS", "ON_HOLD", "CANCELLED"):
            raise ValueError(f"دستور در وضعیت «{STATUS_LABELS[order.status_code]}» قابل بازگشت به پیش‌نویس نیست.")
        _require_no_movement(session, order, "بازگشت به پیش‌نویس")
        _clear_snapshot(session, order)
        before = order.status_code
        order.status_code, order.released_at, order.hold_reason = "DRAFT", None, None
        session.flush()
        pm.refresh_bom_lock(session, order.bom_id)
        c.audit(session, company_id, user_id, "ProductionOrder", order_id, "REVERT_TO_DRAFT", {"status": [before, "DRAFT"]})
        session.commit()


def delete_order(company_id: int, user_id: int, order_id: int) -> None:
    """حذف کامل دستور بدون گردش (هر وضعیتی جز تکمیل/بسته)."""
    from peecha.db.models.production import OrderCostSummary, OrderVariance, ProductionPlanLine

    with new_session() as session:
        order = lock_order(session, company_id, order_id)
        if order.status_code in ("COMPLETED", "CLOSED"):
            raise ValueError("دستور تکمیل/بسته‌شده قابل حذف نیست.")
        _require_no_movement(session, order, "حذف")
        _clear_snapshot(session, order)
        session.query(OrderCostSummary).filter(OrderCostSummary.order_id == order_id).delete()
        session.query(OrderVariance).filter(OrderVariance.order_id == order_id).delete()
        for child in session.scalars(select(ProductionOrder).where(ProductionOrder.parent_order_id == order_id)):
            child.parent_order_id = None
        for line in session.scalars(select(ProductionPlanLine).where(ProductionPlanLine.order_id == order_id)):
            line.order_id = None
        bom_id, code = order.bom_id, order.order_code
        c.audit(session, company_id, user_id, "ProductionOrder", order_id, "DELETE", {"code": code, "item_id": order.item_id,
                                                                                    "qty": str(order.planned_qty)})
        session.delete(order)
        session.flush()
        pm.refresh_bom_lock(session, bom_id)
        session.commit()


# =====================================================================================
# چندسطحی
# =====================================================================================
def create_child_orders(company_id: int, user_id: int, order_id: int, shortage_only: bool = True) -> list[int]:
    """دستور تولید نیمه‌ساخته‌ها (مرحله‌به‌مرحله): خروجی فرزند به انبار مواد دستور والد می‌رود."""
    created = []
    with new_session() as session:
        parent = lock_order(session, company_id, order_id)
        avail = {a.item_id: a for a in availability(company_id, order_id)}
        plan = material_plan(session, company_id, parent.item_id, parent.bom_id, parent.planned_qty)
        for r in plan:
            comp = r.line.component_item_id
            prof = session.get(ItemProductionProfile, comp)
            child_bom = pm.effective_bom_id(session, comp, parent.start_date)
            if child_bom is None or (prof is not None and prof.make_or_buy == "BUY") or r.line.is_optional:
                continue
            exists = session.scalar(select(ProductionOrder.order_id).where(
                ProductionOrder.parent_order_id == order_id, ProductionOrder.item_id == comp,
                ProductionOrder.status_code != "CANCELLED"))
            if exists:
                continue
            qty_needed = avail[comp].shortage if shortage_only and comp in avail else r.gross
            if qty_needed <= 0:
                continue
            lead = prof.lead_time_days if prof else 0
            due = parent.start_date
            f = OrderFields(item_id=comp, planned_qty=qty_needed, start_date=due - datetime.timedelta(days=lead), due_date=due,
                            fg_warehouse_id=r.line.warehouse_id or parent.material_warehouse_id, parent_order_id=order_id,
                            branch_id=parent.branch_id, cost_center_detail_account_id=parent.cost_center_detail_account_id,
                            project_detail_account_id=parent.project_detail_account_id, priority=parent.priority)
            _apply_defaults(session, company_id, f)
            f.planned_qty = c.qty(f.planned_qty)
            _validate(session, company_id, f)
            created.append(_insert_order(session, company_id, user_id, f).order_id)
        session.commit()
    return created


# =====================================================================================
# خواندن
# =====================================================================================
def list_orders(company_id: int, status: str | None = None, item_id: int | None = None, search: str | None = None,
                date_from: datetime.date | None = None, date_to: datetime.date | None = None) -> list[SimpleNamespace]:
    with new_session() as session:
        q = select(ProductionOrder).where(ProductionOrder.company_id == company_id)
        if status:
            q = q.where(ProductionOrder.status_code == status)
        if item_id:
            q = q.where(ProductionOrder.item_id == item_id)
        if date_from:
            q = q.where(ProductionOrder.due_date >= date_from)
        if date_to:
            q = q.where(ProductionOrder.start_date <= date_to)
        rows = list(session.scalars(q.order_by(ProductionOrder.order_no.desc())))
        labels = c.item_labels(session, [r.item_id for r in rows])
        out = []
        for r in rows:
            label = labels.get(r.item_id, "")
            if search and search not in label and search not in r.order_code:
                continue
            out.append(SimpleNamespace(order_id=r.order_id, order_code=r.order_code, item_id=r.item_id, item_label=label,
                                       planned_qty=r.planned_qty, produced_qty=r.produced_qty, scrapped_qty=r.scrapped_qty,
                                       progress=r.progress_percent, status_code=r.status_code,
                                       status_label=STATUS_LABELS[r.status_code], start_date=r.start_date, due_date=r.due_date,
                                       priority=r.priority, work_center_id=r.work_center_id, parent_order_id=r.parent_order_id,
                                       is_late=r.status_code in ACTIVE_STATUSES + ("DRAFT", "PLANNED") and r.due_date < datetime.date.today()))
        return out


def get_order(company_id: int, order_id: int) -> ProductionOrder:
    with new_session() as session:
        order = session.get(ProductionOrder, order_id)
        if order is None or order.company_id != company_id:
            raise ValueError("دستور تولید نامعتبر است.")
        session.expunge(order)
        return order


def order_view(company_id: int, order_id: int) -> SimpleNamespace:
    """همهٔ اطلاعات صفحهٔ مرکزی دستور: سر دستور، مواد، عملیات، خروجی‌ها، هزینه‌ها، تراکنش‌ها."""
    from peecha.services.production import costing as pcost

    avail = {a.material_id: a for a in availability(company_id, order_id)}
    with new_session() as session:
        order = session.get(ProductionOrder, order_id)
        if order is None or order.company_id != company_id:
            raise ValueError("دستور تولید نامعتبر است.")
        mats = list(session.scalars(select(OrderMaterial).where(OrderMaterial.order_id == order_id).order_by(OrderMaterial.line_no)))
        ops = list(session.scalars(select(OrderOperation).where(OrderOperation.order_id == order_id).order_by(OrderOperation.seq)))
        outs = list(session.scalars(select(OrderOutput).where(OrderOutput.order_id == order_id).order_by(OrderOutput.output_id)))
        txns = list(session.scalars(select(OrderTransaction).where(OrderTransaction.order_id == order_id)
                                    .order_by(OrderTransaction.txn_id)))
        labels = c.item_labels(session, [order.item_id] + [m.item_id for m in mats] + [o.item_id for o in outs]
                               + [t.item_id for t in txns])
        wcs = {w.work_center_id: w.name for w in session.scalars(select(WorkCenter).where(WorkCenter.company_id == company_id))}
        materials = [SimpleNamespace(material_id=m.material_id, item_id=m.item_id, item_label=labels.get(m.item_id, ""),
                                     component_type=m.component_type, required=m.planned_qty, reserved=m.reserved_qty,
                                     issued=m.issued_qty, returned=m.returned_qty, consumed=m.consumed_qty,
                                     remaining=max(ZERO, decimal.Decimal(m.planned_qty) - m.consumed_qty),
                                     consumed_amount=m.consumed_amount, standard_unit_cost=m.standard_unit_cost,
                                     availability=avail.get(m.material_id).status if m.material_id in avail else "GREEN",
                                     is_optional=m.is_optional) for m in mats]
        operations = [SimpleNamespace(order_operation_id=o.order_operation_id, seq=o.seq, name=o.name,
                                      work_center=wcs.get(o.work_center_id, ""), status_code=o.status_code,
                                      std_labor_hours=o.std_labor_hours, actual_labor_hours=o.actual_labor_hours,
                                      std_machine_hours=o.std_machine_hours, actual_machine_hours=o.actual_machine_hours,
                                      completed_qty=o.completed_qty) for o in ops]
        outputs = [SimpleNamespace(output_id=o.output_id, item_id=o.item_id, item_label=labels.get(o.item_id, ""),
                                   output_type=o.output_type, planned_qty=o.planned_qty, produced_qty=o.produced_qty,
                                   produced_amount=o.produced_amount) for o in outs]
        transactions = [SimpleNamespace(txn_id=t.txn_id, txn_type=t.txn_type, label=TXN_LABELS.get(t.txn_type, t.txn_type),
                                        date=t.txn_date, item_id=t.item_id, item_label=labels.get(t.item_id, ""), quantity=t.quantity, amount=t.amount,
                                        wip_delta=t.wip_delta, stock_document_id=t.stock_document_id,
                                        journal_entry_id=t.journal_entry_id, reason=t.reason,
                                        reversed=t.txn_id in {x.reversed_txn_id for x in txns}) for t in txns
                        if not (t.details or {}).get("kind") == "MARKER"]
        costs = pcost.order_costs(session, order)
        return SimpleNamespace(order=SimpleNamespace(**{k: getattr(order, k) for k in (
            "order_id", "order_code", "item_id", "bom_id", "routing_id", "planned_qty", "produced_qty", "scrapped_qty", "status_code",
            "start_date", "due_date", "actual_start_date", "actual_end_date", "material_warehouse_id", "fg_warehouse_id",
            "scrap_warehouse_id", "cost_center_detail_account_id", "priority", "hold_reason", "parent_order_id",
            "planned_unit_cost", "standard_unit_cost", "joint_cost_method", "work_center_id")},
            item_label=labels.get(order.item_id, ""), status_label=STATUS_LABELS[order.status_code],
            progress=order.progress_percent, remaining_qty=order.remaining_qty),
            materials=materials, operations=operations, outputs=outputs, transactions=transactions, costs=costs,
            wip=wip_balance(session, order_id))
