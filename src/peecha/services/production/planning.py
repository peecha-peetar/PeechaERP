"""برنامه‌ریزی تولید — R269: برنامهٔ تولید (روز/هفته/ماه)، MRP سبک، بار ظرفیت و تقویم تولید.

MRP از داده‌های موجود ERP می‌خواند: سفارش‌های فروش باز (همان فرمول «تعهد سفارش» در گزارش‌های انبار)، حداقل
موجودی (inv.reorder_policies)، دستورهای تولید باز، فهرست مواد، موجودی/رزرو (inv.stock_balance) و سفارش‌های خرید باز.
پیشنهاد «خرید» به «درخواست خرید» موجود و پیشنهاد «تولید» به دستور تولید تبدیل می‌شود.
"""

from __future__ import annotations

import datetime
import decimal
from collections import defaultdict
from types import SimpleNamespace

from sqlalchemy import func, select

from peecha.db.base import new_session
from peecha.db.models.inventory import BomHeader, BomLine, Item, ReorderPolicy, StockBalance
from peecha.db.models.production import (
    ItemProductionProfile, MrpLine, MrpRun, OrderMaterial, OrderOperation, ProductionOrder, ProductionPlan,
    ProductionPlanLine, RoutingOperation, WorkCenter,
)
from peecha.services.production import common as c
from peecha.services.production import master as pm

ZERO = c.ZERO
_OPEN_PRODUCTION = ("DRAFT", "PLANNED", "RELEASED", "IN_PROGRESS", "ON_HOLD")
PLAN_STATUS = {"DRAFT": "پیش‌نویس", "APPROVED": "تاییدشده", "CLOSED": "بسته"}
ACTION_LABELS = {"PURCHASE": "خرید", "PRODUCE": "تولید", "NONE": "-"}


# =====================================================================================
# برنامهٔ تولید
# =====================================================================================
def create_plan(company_id: int, user_id: int, code: str, name: str, start_date: datetime.date, end_date: datetime.date,
                period_type: str = "MONTH", notes: str | None = None) -> int:
    if period_type not in ("DAY", "WEEK", "MONTH"):
        raise ValueError("دورهٔ برنامه نامعتبر است.")
    if not code.strip() or not name.strip() or end_date < start_date:
        raise ValueError("کد، نام و بازهٔ تاریخ معتبر الزامی است.")
    with new_session() as session:
        if session.scalar(select(ProductionPlan.plan_id).where(ProductionPlan.company_id == company_id, ProductionPlan.code == code.strip())):
            raise ValueError("این کد برنامه قبلاً تعریف شده است.")
        row = ProductionPlan(company_id=company_id, code=code.strip(), name=name.strip(), period_type=period_type,
                             start_date=start_date, end_date=end_date, status_code="DRAFT", notes=notes, created_by_user_id=user_id)
        session.add(row)
        session.flush()
        c.audit(session, company_id, user_id, "ProductionPlan", row.plan_id, "CREATE", {"code": code})
        session.commit()
        return row.plan_id


def _plan(session, company_id: int, plan_id: int, editable: bool = False) -> ProductionPlan:
    plan = session.get(ProductionPlan, plan_id)
    if plan is None or plan.company_id != company_id:
        raise ValueError("برنامهٔ تولید نامعتبر است.")
    if editable and plan.status_code != "DRAFT":
        raise ValueError("فقط برنامهٔ پیش‌نویس قابل ویرایش است.")
    return plan


def add_plan_line(company_id: int, plan_id: int, item_id: int, planned_date: datetime.date, quantity,
                  work_center_id: int | None = None, source_type: str = "MANUAL", sales_order_line_id: int | None = None,
                  notes: str | None = None) -> int:
    quantity = decimal.Decimal(quantity)
    if quantity <= 0:
        raise ValueError("مقدار باید بزرگ‌تر از صفر باشد.")
    with new_session() as session:
        plan = _plan(session, company_id, plan_id, editable=True)
        c.item_of(session, company_id, item_id)
        if not plan.start_date <= planned_date <= plan.end_date:
            raise ValueError("تاریخ ردیف خارج از بازهٔ برنامه است.")
        if pm.effective_bom_id(session, item_id, planned_date) is None:
            raise ValueError(f"برای «{c.item_label(session, item_id)}» فهرست مواد معتبری وجود ندارد.")
        work_center_id = work_center_id or _main_work_center(session, item_id)
        row = ProductionPlanLine(plan_id=plan_id, item_id=item_id, planned_date=planned_date, quantity=quantity,
                                 work_center_id=work_center_id, source_type=source_type, sales_order_line_id=sales_order_line_id,
                                 notes=notes)
        session.add(row)
        session.commit()
        return row.line_id


def _main_work_center(session, item_id: int) -> int | None:
    rid = pm.default_routing_id(session, item_id)
    return session.scalar(select(RoutingOperation.work_center_id).where(
        RoutingOperation.routing_id == rid).order_by(RoutingOperation.seq).limit(1)) if rid else None


def remove_plan_line(company_id: int, line_id: int) -> None:
    with new_session() as session:
        row = session.get(ProductionPlanLine, line_id)
        if row is None:
            raise ValueError("ردیف برنامه نامعتبر است.")
        _plan(session, company_id, row.plan_id, editable=True)
        session.delete(row)
        session.commit()


def update_plan(company_id: int, user_id: int, plan_id: int, code: str, name: str, start_date: datetime.date,
                end_date: datetime.date, period_type: str = "MONTH", notes: str | None = None) -> None:
    """R280: ویرایش سر برنامهٔ پیش‌نویس."""
    if period_type not in ("DAY", "WEEK", "MONTH"):
        raise ValueError("دورهٔ برنامه نامعتبر است.")
    if not code.strip() or not name.strip() or end_date < start_date:
        raise ValueError("کد، نام و بازهٔ تاریخ معتبر الزامی است.")
    with new_session() as session:
        plan = _plan(session, company_id, plan_id, editable=True)
        dup = session.scalar(select(ProductionPlan.plan_id).where(ProductionPlan.company_id == company_id,
                                                                  ProductionPlan.code == code.strip()))
        if dup is not None and dup != plan_id:
            raise ValueError("این کد برنامه قبلاً تعریف شده است.")
        outside = session.scalar(select(func.count()).select_from(ProductionPlanLine).where(
            ProductionPlanLine.plan_id == plan_id,
            (ProductionPlanLine.planned_date < start_date) | (ProductionPlanLine.planned_date > end_date)))
        if outside:
            raise ValueError("تاریخ بعضی ردیف‌های برنامه خارج از بازهٔ جدید است — ابتدا آن ردیف‌ها را اصلاح کنید.")
        plan.code, plan.name, plan.start_date, plan.end_date, plan.period_type = code.strip(), name.strip(), start_date, end_date, period_type
        plan.notes = notes if notes is not None else plan.notes
        c.audit(session, company_id, user_id, "ProductionPlan", plan_id, "UPDATE", {"code": plan.code})
        session.commit()


def delete_plan(company_id: int, user_id: int, plan_id: int) -> None:
    """R280: حذف برنامه‌ای که هیچ ردیفش به دستور تولید تبدیل نشده است."""
    with new_session() as session:
        plan = _plan(session, company_id, plan_id)
        if session.scalar(select(ProductionPlanLine.line_id).where(ProductionPlanLine.plan_id == plan_id,
                                                                   ProductionPlanLine.order_id.is_not(None)).limit(1)):
            raise ValueError("بخشی از این برنامه به دستور تولید تبدیل شده است و قابل حذف نیست.")
        session.query(ProductionPlanLine).filter(ProductionPlanLine.plan_id == plan_id).delete()
        c.audit(session, company_id, user_id, "ProductionPlan", plan_id, "DELETE", {"code": plan.code})
        session.delete(plan)
        session.commit()


def update_plan_line(company_id: int, line_id: int, item_id: int, planned_date: datetime.date, quantity) -> None:
    """R280: ویرایش ردیف برنامهٔ پیش‌نویس."""
    quantity = decimal.Decimal(quantity)
    if quantity <= 0:
        raise ValueError("مقدار باید بزرگ‌تر از صفر باشد.")
    with new_session() as session:
        row = session.get(ProductionPlanLine, line_id)
        if row is None:
            raise ValueError("ردیف برنامه نامعتبر است.")
        plan = _plan(session, company_id, row.plan_id, editable=True)
        c.item_of(session, company_id, item_id)
        if not plan.start_date <= planned_date <= plan.end_date:
            raise ValueError("تاریخ ردیف خارج از بازهٔ برنامه است.")
        if item_id != row.item_id:
            if pm.effective_bom_id(session, item_id, planned_date) is None:
                raise ValueError(f"برای «{c.item_label(session, item_id)}» فهرست مواد معتبری وجود ندارد.")
            row.work_center_id = _main_work_center(session, item_id)
        row.item_id, row.planned_date, row.quantity = item_id, planned_date, quantity
        session.commit()


def _period_dates(plan: ProductionPlan) -> list[datetime.date]:
    """تاریخ شروع هر بازهٔ برنامه (روزانه/هفتگی/ماهانهٔ شمسی)."""
    from peecha.services.fixed_assets.common import add_months, period_of

    dates, d = [], plan.start_date
    while d <= plan.end_date:
        dates.append(d)
        if plan.period_type == "DAY":
            d += datetime.timedelta(days=1)
        elif plan.period_type == "WEEK":
            d += datetime.timedelta(days=7)
        else:
            d = max(add_months(period_of(d)[1], 1), d + datetime.timedelta(days=1))
    return dates


def generate_from_sales_orders(company_id: int, plan_id: int) -> int:
    """ردیف برنامه برای ماندهٔ سفارش‌های فروش باز (کالاهای ساختنی، کسر موجودی آزاد و دستورهای باز)."""
    demand = open_sales_demand(company_id)
    added = 0
    with new_session() as session:
        plan = _plan(session, company_id, plan_id, editable=True)
        existing = set(session.scalars(select(ProductionPlanLine.sales_order_line_id).where(
            ProductionPlanLine.plan_id == plan_id, ProductionPlanLine.sales_order_line_id.is_not(None))))
        free = _free_supply(session, company_id)
        for d in sorted(demand, key=lambda x: x.date):
            if d.line_id in existing or not _is_made(session, d.item_id):
                continue
            use = min(free.get(d.item_id, ZERO), d.quantity)
            free[d.item_id] = free.get(d.item_id, ZERO) - use
            qty = d.quantity - use
            if qty <= 0:
                continue
            date = min(max(d.date, plan.start_date), plan.end_date)
            session.add(ProductionPlanLine(plan_id=plan_id, item_id=d.item_id, planned_date=date, quantity=c.qty(qty),
                                           work_center_id=_main_work_center(session, d.item_id), source_type="SALES_ORDER", sales_order_line_id=d.line_id,
                                           notes=f"سفارش فروش {d.document_no}"))
            added += 1
        session.commit()
    return added


def generate_from_min_stock(company_id: int, plan_id: int) -> int:
    """ردیف برنامه برای کالاهای ساختنی که موجودی آزاد + تامین باز به حداقل موجودی نمی‌رسد."""
    added = 0
    with new_session() as session:
        plan = _plan(session, company_id, plan_id, editable=True)
        free = _free_supply(session, company_id)
        for item_id, min_qty, max_qty in session.execute(
                select(ReorderPolicy.item_id, func.sum(ReorderPolicy.min_qty), func.sum(ReorderPolicy.max_qty))
                .where(ReorderPolicy.company_id == company_id).group_by(ReorderPolicy.item_id)).all():
            if not min_qty or not _is_made(session, item_id):
                continue
            projected = free.get(item_id, ZERO)
            if projected >= decimal.Decimal(min_qty):
                continue
            qty = decimal.Decimal(max_qty or min_qty) - projected
            session.add(ProductionPlanLine(plan_id=plan_id, item_id=item_id, planned_date=plan.start_date, quantity=c.qty(qty),
                                           work_center_id=_main_work_center(session, item_id), source_type="MIN_STOCK", notes="رسیدن به حداقل/حداکثر موجودی"))
            added += 1
        session.commit()
    return added


def approve_plan(company_id: int, user_id: int, plan_id: int) -> None:
    with new_session() as session:
        plan = _plan(session, company_id, plan_id, editable=True)
        if not session.scalar(select(func.count()).select_from(ProductionPlanLine).where(ProductionPlanLine.plan_id == plan_id)):
            raise ValueError("برنامه ردیفی ندارد.")
        plan.status_code = "APPROVED"
        c.audit(session, company_id, user_id, "ProductionPlan", plan_id, "APPROVE", {})
        session.commit()


def convert_plan_to_orders(company_id: int, user_id: int, plan_id: int) -> list[int]:
    """ساخت دستور تولید (پیش‌نویس) برای ردیف‌های تبدیل‌نشدهٔ برنامهٔ تاییدشده."""
    from peecha.services.production import orders as po

    created = []
    with new_session() as session:
        plan = _plan(session, company_id, plan_id)
        if plan.status_code != "APPROVED":
            raise ValueError("ابتدا برنامه را تایید کنید.")
        for ln in session.scalars(select(ProductionPlanLine).where(ProductionPlanLine.plan_id == plan_id,
                                                                   ProductionPlanLine.order_id.is_(None)).with_for_update()):
            prof = session.get(ItemProductionProfile, ln.item_id)
            lead = prof.lead_time_days if prof else 0
            f = po.OrderFields(item_id=ln.item_id, planned_qty=ln.quantity, start_date=ln.planned_date - datetime.timedelta(days=lead),
                               due_date=ln.planned_date, work_center_id=ln.work_center_id, sales_order_line_id=ln.sales_order_line_id)
            po._apply_defaults(session, company_id, f)
            po._validate(session, company_id, f)
            order = po._insert_order(session, company_id, user_id, f)
            order.plan_line_id = ln.line_id
            ln.order_id = order.order_id
            created.append(order.order_id)
        c.audit(session, company_id, user_id, "ProductionPlan", plan_id, "CONVERT", {"orders": len(created)})
        session.commit()
    return created


def list_plans(company_id: int) -> list[ProductionPlan]:
    with new_session() as session:
        rows = list(session.scalars(select(ProductionPlan).where(ProductionPlan.company_id == company_id)
                                    .order_by(ProductionPlan.start_date.desc())))
        for r in rows:
            session.expunge(r)
        return rows


def plan_lines(company_id: int, plan_id: int) -> list[SimpleNamespace]:
    with new_session() as session:
        _plan(session, company_id, plan_id)
        rows = list(session.scalars(select(ProductionPlanLine).where(ProductionPlanLine.plan_id == plan_id)
                                    .order_by(ProductionPlanLine.planned_date, ProductionPlanLine.line_id)))
        labels = c.item_labels(session, [r.item_id for r in rows])
        codes = dict(session.execute(select(ProductionOrder.order_id, ProductionOrder.order_code).where(
            ProductionOrder.order_id.in_([r.order_id for r in rows if r.order_id] or [-1]))).all())
        return [SimpleNamespace(line_id=r.line_id, item_id=r.item_id, item_label=labels.get(r.item_id, ""), planned_date=r.planned_date,
                                quantity=r.quantity, work_center_id=r.work_center_id, source_type=r.source_type,
                                order_id=r.order_id, order_code=codes.get(r.order_id, ""), notes=r.notes) for r in rows]


def plan_summary(company_id: int, plan_id: int) -> list[SimpleNamespace]:
    """جمع برنامه به تفکیک بازه (روز/هفته/ماه) و کالا."""
    with new_session() as session:
        plan = _plan(session, company_id, plan_id)
        starts = _period_dates(plan)
        lines = list(session.scalars(select(ProductionPlanLine).where(ProductionPlanLine.plan_id == plan_id)))
        labels = c.item_labels(session, [r.item_id for r in lines])
    buckets: dict[tuple, decimal.Decimal] = defaultdict(lambda: ZERO)
    for ln in lines:
        start = max(s for s in starts if s <= ln.planned_date)
        buckets[(start, ln.item_id)] += decimal.Decimal(ln.quantity)
    return [SimpleNamespace(period_start=k[0], item_id=k[1], item_label=labels.get(k[1], ""), quantity=v)
            for k, v in sorted(buckets.items())]


# =====================================================================================
# داده‌هایِ تقاضا/عرضه (از ماژول‌هایِ موجود)
# =====================================================================================
def open_sales_demand(company_id: int) -> list[SimpleNamespace]:
    """ماندهٔ فاکتورنشدهٔ سفارش‌های فروش باز — همان فرمول «تعهد سفارش»."""
    from peecha.services import purchase_reports as base
    from peecha.services.purchase_reports_ext import _OPEN_ORDER_STATUSES

    ctx = base._ctx(company_id)
    pairs = base._lines(company_id, ("SALES_ORDER",), _OPEN_ORDER_STATUSES, None, ctx, dated=False)
    billed = base._invoiced_base_by_source_line(company_id, "SALES_INVOICE", [ln.line_id for _d, ln in pairs])
    out = []
    for doc, ln in pairs:
        remaining = decimal.Decimal(ln.quantity_base) - billed.get(ln.line_id, ZERO)
        if remaining > 0:
            date = ln.expected_delivery_date or doc.requested_delivery_date or doc.document_date
            out.append(SimpleNamespace(item_id=ln.item_id, quantity=remaining, date=date, line_id=ln.line_id,
                                       document_no=doc.document_no))
    return out


def open_purchase_supply(company_id: int) -> dict[int, decimal.Decimal]:
    """ماندهٔ دریافت‌نشدهٔ سفارش‌های خرید باز به تفکیک کالا."""
    from peecha.services import purchase_reports as base
    from peecha.services.purchase_reports_ext import _OPEN_ORDER_STATUSES

    ctx = base._ctx(company_id)
    pairs = base._lines(company_id, ("PURCHASE_ORDER",), _OPEN_ORDER_STATUSES, None, ctx, dated=False)
    invoiced = base._invoiced_base_by_source_line(company_id, "PURCHASE_INVOICE", [ln.line_id for _d, ln in pairs])
    out: dict[int, decimal.Decimal] = defaultdict(lambda: ZERO)
    for doc, ln in pairs:
        received = max(decimal.Decimal(base._received_base(doc, ln) or 0), invoiced.get(ln.line_id, ZERO))
        remaining = decimal.Decimal(ln.quantity_base) - received
        if remaining > 0:
            out[ln.item_id] += remaining
    return out


def _stock(session, company_id: int) -> tuple[dict, dict]:
    on_hand, reserved = defaultdict(lambda: ZERO), defaultdict(lambda: ZERO)
    for item_id, q, r in session.execute(select(StockBalance.item_id, func.sum(StockBalance.quantity_on_hand),
                                                func.sum(StockBalance.quantity_reserved))
                                         .where(StockBalance.company_id == company_id).group_by(StockBalance.item_id)).all():
        on_hand[item_id], reserved[item_id] = decimal.Decimal(q or 0), decimal.Decimal(r or 0)
    return on_hand, reserved


def _production_supply(session, company_id: int) -> dict[int, decimal.Decimal]:
    out = defaultdict(lambda: ZERO)
    for o in session.scalars(select(ProductionOrder).where(ProductionOrder.company_id == company_id,
                                                           ProductionOrder.status_code.in_(_OPEN_PRODUCTION))):
        out[o.item_id] += o.remaining_qty
    return out


def _free_supply(session, company_id: int) -> dict[int, decimal.Decimal]:
    on_hand, reserved = _stock(session, company_id)
    prod = _production_supply(session, company_id)
    items = set(on_hand) | set(prod)
    return {i: on_hand[i] - reserved[i] + prod[i] for i in items}


def _is_made(session, item_id: int) -> bool:
    prof = session.get(ItemProductionProfile, item_id)
    return pm.effective_bom_id(session, item_id) is not None and (prof is None or prof.make_or_buy == "MAKE")


# =====================================================================================
# MRP
# =====================================================================================
def _levels(session, company_id: int) -> dict[int, int]:
    """سطح پایین‌ترین کاربرد هر کالا در فهرست موادهای فعال (low-level code)."""
    edges = defaultdict(set)
    for parent, child in session.execute(select(BomHeader.finished_item_id, BomLine.component_item_id)
                                         .join(BomLine, BomLine.bom_id == BomHeader.bom_id)
                                         .join(Item, Item.item_id == BomHeader.finished_item_id)
                                         .where(Item.company_id == company_id, BomHeader.status_code == "ACTIVE")).all():
        edges[parent].add(child)
    level: dict[int, int] = defaultdict(int)
    changed, guard = True, 0
    while changed and guard < 20:
        changed, guard = False, guard + 1
        for parent, children in edges.items():
            for ch in children:
                if level[ch] < level[parent] + 1:
                    level[ch] = level[parent] + 1
                    changed = True
    return level


def _lot_size(prof: ItemProductionProfile | None, qty: decimal.Decimal) -> decimal.Decimal:
    if prof is None or qty <= 0:
        return qty
    if prof.min_lot_qty and qty < prof.min_lot_qty:
        qty = decimal.Decimal(prof.min_lot_qty)
    if prof.lot_multiple_qty:
        m = decimal.Decimal(prof.lot_multiple_qty)
        qty = (qty / m).to_integral_value(rounding=decimal.ROUND_CEILING) * m
    return qty


def run_mrp(company_id: int, user_id: int | None = None, horizon_days: int = 30, include_sales: bool = True,
            include_min_stock: bool = True, include_plans: bool = True, include_orders: bool = True) -> int:
    """MRP سطح‌به‌سطح: نیاز ناخالص (مستقل + وابسته) − موجودی آزاد − تامین باز + حداقل موجودی ← نیاز خالص و پیشنهاد."""
    today = datetime.date.today()
    horizon = today + datetime.timedelta(days=horizon_days)
    sales = open_sales_demand(company_id) if include_sales else []
    po_supply = open_purchase_supply(company_id)
    with new_session() as session:
        on_hand, reserved = _stock(session, company_id)
        prod_supply = _production_supply(session, company_id)
        levels = _levels(session, company_id)
        independent: dict[int, decimal.Decimal] = defaultdict(lambda: ZERO)
        dependent: dict[int, decimal.Decimal] = defaultdict(lambda: ZERO)
        need_date: dict[int, datetime.date] = {}
        sources: dict[int, list] = defaultdict(list)

        def note(item_id, qty, date, src):
            if date and (item_id not in need_date or date < need_date[item_id]):
                need_date[item_id] = date
            sources[item_id].append({"source": src, "qty": str(c.qty(qty))})

        for d in sales:
            if d.date <= horizon:
                independent[d.item_id] += d.quantity
                note(d.item_id, d.quantity, d.date, f"SO {d.document_no}")
        if include_plans:
            for ln in session.scalars(select(ProductionPlanLine).join(ProductionPlan, ProductionPlan.plan_id == ProductionPlanLine.plan_id)
                                      .where(ProductionPlan.company_id == company_id, ProductionPlan.status_code == "APPROVED",
                                             ProductionPlanLine.order_id.is_(None), ProductionPlanLine.planned_date <= horizon)):
                independent[ln.item_id] += decimal.Decimal(ln.quantity)
                note(ln.item_id, ln.quantity, ln.planned_date, "PLAN")
        if include_orders:  # نیازِ موادِ دستورهایِ باز
            for o in session.scalars(select(ProductionOrder).where(ProductionOrder.company_id == company_id,
                                                                   ProductionOrder.status_code.in_(_OPEN_PRODUCTION))):
                mats = list(session.scalars(select(OrderMaterial).where(OrderMaterial.order_id == o.order_id)))
                if mats:
                    for m in mats:
                        rem = max(ZERO, decimal.Decimal(m.planned_qty) - m.consumed_qty - decimal.Decimal(m.reserved_qty))
                        if rem > 0 and not m.is_optional:
                            dependent[m.item_id] += rem
                            note(m.item_id, rem, o.start_date, o.order_code)
                elif o.bom_id:
                    from peecha.services.production.orders import material_plan

                    for r in material_plan(session, company_id, o.item_id, o.bom_id, o.planned_qty):
                        if not r.line.is_optional:
                            dependent[r.line.component_item_id] += r.gross
                            note(r.line.component_item_id, r.gross, o.start_date, o.order_code)
        min_stock = {i: decimal.Decimal(q or 0) for i, q in session.execute(
            select(ReorderPolicy.item_id, func.sum(ReorderPolicy.min_qty)).where(ReorderPolicy.company_id == company_id)
            .group_by(ReorderPolicy.item_id)).all()} if include_min_stock else {}
        items = set(independent) | set(dependent) | {i for i, q in min_stock.items() if q}
        # پردازشِ سطح‌به‌سطح: پیشنهادِ تولیدِ هر سطح نیازِ وابستهٔ سطحِ بعد را می‌سازد
        result: dict[int, SimpleNamespace] = {}
        processed: set[int] = set()
        while True:
            pending = [i for i in items if i not in processed]
            if not pending:
                break
            lvl = min(levels.get(i, 0) for i in pending)
            for item_id in [i for i in pending if levels.get(i, 0) == lvl]:
                processed.add(item_id)
                prof = session.get(ItemProductionProfile, item_id)
                made = _is_made(session, item_id)
                gross = independent[item_id] + dependent[item_id]
                available = on_hand[item_id] - reserved[item_id]
                receipts = po_supply.get(item_id, ZERO) + prod_supply.get(item_id, ZERO)
                ms = min_stock.get(item_id, ZERO)
                net = max(ZERO, gross + ms - available - receipts)
                qty = _lot_size(prof, net) if net > 0 else ZERO
                action = ("PRODUCE" if made else "PURCHASE") if qty > 0 else "NONE"
                lead = (prof.lead_time_days if prof else None)
                if lead is None or (not made and not prof):
                    lead = (session.get(Item, item_id).purchase_lead_time_days or 0) if not made else 0
                nd = need_date.get(item_id) or (today if net > 0 else None)
                result[item_id] = SimpleNamespace(
                    item_id=item_id, level=lvl, make_or_buy="MAKE" if made else "BUY", gross=gross, independent=independent[item_id],
                    dependent=dependent[item_id], on_hand=on_hand[item_id], reserved=reserved[item_id], available=available,
                    receipts=receipts, min_stock=ms, net=net, action=action, qty=qty, need_date=nd,
                    release_date=(nd - datetime.timedelta(days=lead)) if nd else None, sources=sources[item_id])
                if action == "PRODUCE":
                    bom_id = pm.effective_bom_id(session, item_id)
                    from peecha.services.production.orders import material_plan

                    for r in material_plan(session, company_id, item_id, bom_id, qty):
                        if r.line.is_optional:
                            continue
                        child = r.line.component_item_id
                        dependent[child] += r.gross
                        rel = result[item_id].release_date
                        if rel and (child not in need_date or rel < need_date[child]):
                            need_date[child] = rel
                        sources[child].append({"source": f"MRP {c.item_label(session, item_id)}", "qty": str(r.gross)})
                        if child not in items:
                            items.add(child)
                        if child in processed:  # حلقهٔ سطح (نباید رخ دهد) -- دوباره پردازش شود
                            processed.discard(child)
        run = MrpRun(company_id=company_id, horizon_date=horizon, created_by_user_id=user_id, lines_count=len(result),
                     params={"sales": include_sales, "min_stock": include_min_stock, "plans": include_plans, "orders": include_orders})
        session.add(run)
        session.flush()
        for r in result.values():
            session.add(MrpLine(run_id=run.run_id, item_id=r.item_id, level=r.level, make_or_buy=r.make_or_buy,
                                gross_requirement=c.qty(r.gross), independent_demand=c.qty(r.independent),
                                dependent_demand=c.qty(r.dependent), on_hand=c.qty(r.on_hand), reserved=c.qty(r.reserved),
                                available=c.qty(r.available), scheduled_receipts=c.qty(r.receipts), min_stock=c.qty(r.min_stock),
                                net_requirement=c.qty(r.net), suggested_action=r.action, suggested_qty=c.qty(r.qty),
                                need_date=r.need_date, release_date=r.release_date, details={"sources": r.sources[:50]}))
        c.audit(session, company_id, user_id, "MrpRun", run.run_id, "CREATE", {"lines": len(result)})
        session.commit()
        return run.run_id


def mrp_lines(company_id: int, run_id: int | None = None) -> list[SimpleNamespace]:
    with new_session() as session:
        if run_id is None:
            run_id = session.scalar(select(func.max(MrpRun.run_id)).where(MrpRun.company_id == company_id))
            if run_id is None:
                return []
        run = session.get(MrpRun, run_id)
        if run is None or run.company_id != company_id:
            raise ValueError("محاسبهٔ نیاز مواد (MRP) نامعتبر است.")
        rows = list(session.scalars(select(MrpLine).where(MrpLine.run_id == run_id).order_by(MrpLine.level, MrpLine.item_id)))
        labels = c.item_labels(session, [r.item_id for r in rows])
        return [SimpleNamespace(**{k: getattr(r, k) for k in (
            "mrp_line_id", "run_id", "item_id", "level", "make_or_buy", "gross_requirement", "independent_demand", "dependent_demand",
            "on_hand", "reserved", "available", "scheduled_receipts", "min_stock", "net_requirement", "suggested_action",
            "suggested_qty", "need_date", "release_date", "converted_ref")}, item_label=labels.get(r.item_id, ""),
            shortage=r.net_requirement, action_label=ACTION_LABELS[r.suggested_action]) for r in rows]


def convert_mrp(company_id: int, user_id: int, mrp_line_ids: list[int]) -> SimpleNamespace:
    """پیشنهاد «تولید» ← دستور تولید پیش‌نویس؛ پیشنهاد «خرید» ← یک «درخواست خرید» موجود (ماژول تدارکات)."""
    from peecha.services import purchase_requests as pr_service
    from peecha.services.production import orders as po

    orders, request_id = [], None
    with new_session() as session:
        rows = list(session.scalars(select(MrpLine).join(MrpRun, MrpRun.run_id == MrpLine.run_id).where(
            MrpLine.mrp_line_id.in_(mrp_line_ids), MrpRun.company_id == company_id, MrpLine.converted_ref.is_(None))))
        snapshot = [(r.mrp_line_id, r.item_id, r.suggested_action, decimal.Decimal(r.suggested_qty), r.need_date, r.release_date)
                    for r in rows if r.suggested_action != "NONE"]
    refs: dict[int, str] = {}
    buy = [s for s in snapshot if s[2] == "PURCHASE"]
    if buy:
        today = datetime.date.today()
        request_id = pr_service.create_request(company_id, user_id, pr_service.RequestFields(
            request_date=today, required_date=max(today, min((s[4] for s in buy if s[4]), default=today)),
            description="پیشنهاد MRP تولید"))
        with new_session() as session:
            uoms = dict(session.execute(select(Item.item_id, Item.base_uom_id).where(Item.item_id.in_([s[1] for s in buy]))).all())
        for mid, item_id, _a, qty, nd, _rd in buy:
            pr_service.add_line(request_id, company_id, item_id, uoms[item_id], qty, required_date=max(nd or today, today))
            refs[mid] = f"PR#{request_id}"
    for mid, item_id, _a, qty, nd, rd in [s for s in snapshot if s[2] == "PRODUCE"]:
        today = datetime.date.today()
        start = max(rd or today, today)
        oid = po.create_order(company_id, user_id, po.OrderFields(item_id=item_id, planned_qty=qty, start_date=start,
                                                                  due_date=max(nd or start, start)))
        orders.append(oid)
        refs[mid] = po.get_order(company_id, oid).order_code
    with new_session() as session:
        for mid, ref in refs.items():
            session.get(MrpLine, mid).converted_ref = ref
        c.audit(session, company_id, user_id, "MrpRun", 0, "CONVERT", {"orders": len(orders), "purchase_request": request_id})
        session.commit()
    return SimpleNamespace(order_ids=orders, purchase_request_id=request_id)


# =====================================================================================
# ظرفیت و تقویم
# =====================================================================================
def _order_load(session, company_id: int) -> list[tuple]:
    """(مرکز کاری، دستور، شروع، پایان، ساعت باقیمانده) برای دستورهای باز — ساعت مانده = استاندارد عملیات × نسبت مانده."""
    out = []
    for o in session.scalars(select(ProductionOrder).where(ProductionOrder.company_id == company_id,
                                                           ProductionOrder.status_code.in_(_OPEN_PRODUCTION))):
        ops = list(session.scalars(select(OrderOperation).where(OrderOperation.order_id == o.order_id)))
        ratio = o.remaining_qty / decimal.Decimal(o.planned_qty)
        if ops:
            for op in ops:
                if op.status_code in ("DONE", "SKIPPED"):
                    continue
                hours = max(decimal.Decimal(op.std_labor_hours), decimal.Decimal(op.std_machine_hours),
                            decimal.Decimal(op.std_elapsed_hours)) * ratio
                out.append((op.work_center_id, o, o.start_date, o.due_date, hours))
        elif o.routing_id:
            for op in session.scalars(select(RoutingOperation).where(RoutingOperation.routing_id == o.routing_id)):
                out.append((op.work_center_id, o, o.start_date, o.due_date, pm.op_hours(op, o.remaining_qty).elapsed_hours))
        else:
            out.append((o.work_center_id, o, o.start_date, o.due_date, ZERO))
    return out


def capacity_load(company_id: int, date_from: datetime.date, date_to: datetime.date) -> list[SimpleNamespace]:
    """بار در برابر ظرفیت هر مرکز کاری در بازه (بار هر دستور یکنواخت روی روزهای شروع تا پایانش پخش می‌شود)."""
    with new_session() as session:
        centers = {w.work_center_id: w for w in session.scalars(select(WorkCenter).where(
            WorkCenter.company_id == company_id, WorkCenter.is_active.is_(True)))}
        load: dict[int, decimal.Decimal] = defaultdict(lambda: ZERO)
        orders: dict[int, set] = defaultdict(set)
        for wc_id, order, start, end, hours in _order_load(session, company_id):
            if wc_id is None or hours <= 0:
                continue
            span = (end - start).days + 1
            overlap = (min(end, date_to) - max(start, date_from)).days + 1
            if overlap <= 0:
                continue
            load[wc_id] += hours * decimal.Decimal(overlap) / decimal.Decimal(span)
            orders[wc_id].add(order.order_code)
        for ln in session.scalars(select(ProductionPlanLine).join(ProductionPlan, ProductionPlan.plan_id == ProductionPlanLine.plan_id)
                                  .where(ProductionPlan.company_id == company_id, ProductionPlan.status_code == "APPROVED",
                                         ProductionPlanLine.order_id.is_(None),
                                         ProductionPlanLine.planned_date.between(date_from, date_to))):
            rid = pm.default_routing_id(session, ln.item_id)
            for op in session.scalars(select(RoutingOperation).where(RoutingOperation.routing_id == rid)) if rid else []:
                if op.work_center_id:
                    load[op.work_center_id] += pm.op_hours(op, ln.quantity).elapsed_hours
        out = []
        for wc_id, wc in centers.items():
            cap = pm.capacity_hours(wc, date_from, date_to)
            used = c.money(load[wc_id])
            util = c.money(used * 100 / cap) if cap else (decimal.Decimal(100) if used else ZERO)
            out.append(SimpleNamespace(work_center_id=wc_id, code=wc.code, name=wc.name, capacity_hours=cap, load_hours=used,
                                       utilization=util, overloaded=used > cap, free_hours=max(ZERO, cap - used),
                                       orders=sorted(orders[wc_id])))
        return sorted(out, key=lambda x: -x.utilization)


def calendar(company_id: int, date_from: datetime.date, date_to: datetime.date, work_center_id: int | None = None
             ) -> list[SimpleNamespace]:
    """تقویم تولید: چه چیزی، چه مقدار، چه روزی، در چه خط/مرکز کاری — دستورهای باز (پخش روزانه) + ردیف‌های برنامه."""
    from peecha.services.production.orders import STATUS_LABELS

    out = []
    with new_session() as session:
        wcs = {w.work_center_id: w.name for w in session.scalars(select(WorkCenter).where(WorkCenter.company_id == company_id))}
        orders = list(session.scalars(select(ProductionOrder).where(
            ProductionOrder.company_id == company_id, ProductionOrder.status_code.in_(_OPEN_PRODUCTION + ("COMPLETED",)),
            ProductionOrder.start_date <= date_to, ProductionOrder.due_date >= date_from)))
        plan_rows = list(session.scalars(select(ProductionPlanLine).join(ProductionPlan, ProductionPlan.plan_id == ProductionPlanLine.plan_id)
                                         .where(ProductionPlan.company_id == company_id, ProductionPlan.status_code != "CLOSED",
                                                ProductionPlanLine.order_id.is_(None),
                                                ProductionPlanLine.planned_date.between(date_from, date_to))))
        labels = c.item_labels(session, [o.item_id for o in orders] + [p.item_id for p in plan_rows])
        for o in orders:
            if work_center_id and o.work_center_id != work_center_id:
                continue
            span = (o.due_date - o.start_date).days + 1
            per_day = c.qty(decimal.Decimal(o.planned_qty) / span)
            day = max(o.start_date, date_from)
            while day <= min(o.due_date, date_to):
                out.append(SimpleNamespace(date=day, kind="ORDER", ref=o.order_code, order_id=o.order_id, item_id=o.item_id,
                                           item_label=labels.get(o.item_id, ""), quantity=per_day, total_quantity=o.planned_qty,
                                           work_center_id=o.work_center_id, work_center=wcs.get(o.work_center_id, ""),
                                           status=STATUS_LABELS[o.status_code],
                                           late=o.due_date < datetime.date.today() and o.status_code != "COMPLETED"))
                day += datetime.timedelta(days=1)
        for p in plan_rows:
            if work_center_id and p.work_center_id != work_center_id:
                continue
            out.append(SimpleNamespace(date=p.planned_date, kind="PLAN", ref=f"برنامه #{p.plan_id}", order_id=None, item_id=p.item_id,
                                       item_label=labels.get(p.item_id, ""), quantity=p.quantity, total_quantity=p.quantity,
                                       work_center_id=p.work_center_id, work_center=wcs.get(p.work_center_id, ""),
                                       status="برنامه", late=False))
    return sorted(out, key=lambda x: (x.date, x.work_center, x.ref))
