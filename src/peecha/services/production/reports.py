"""گزارش‌هایِ تولید -- R270 (همان موتور و صفحهٔ عمومیِ گزارش؛ فقط خواندنی از دستورها/تراکنش‌هایِ تولید).

دابل‌کلیک: (شناسهٔ دستور، «PRD_ORDER») صفحهٔ مرکزیِ همان دستور.
"""

from __future__ import annotations

import datetime
import decimal
from collections import defaultdict

from sqlalchemy import func, select

from peecha.db.base import new_session
from peecha.db.models.inventory import Item, StockBalance, Warehouse
from peecha.db.models.production import (
    CostAllocationRow, CostPool, LaborEntry, MachineEntry, OrderMaterial, OrderOperation, OrderOutput, OrderTransaction,
    ProductionOrder, WorkCenter,
)
from peecha.services.production import common as c
from peecha.services.purchase_reports import DATE, INT, MONEY, PERCENT, QTY, TEXT, ReportDef, ReportResult

ZERO = c.ZERO
_HUNDRED = decimal.Decimal(100)
_G_PROD, _G_MAT, _G_COST, _G_INV, _G_MGMT = "تولید", "مواد", "بهایِ تمام‌شده", "موجودیِ تولید", "مدیریتی"
_ITEM = ("item",)
_ITEM_WH = ("item", "warehouse")
_STATUS_OPT = (("status", "وضعیت", (("ALL", "همه"), ("OPEN", "باز"), ("COMPLETED", "تکمیل/بسته"))),)


def _ref(order_id):
    return (order_id, "PRD_ORDER")


def _pct(a, b):
    return (decimal.Decimal(a) * _HUNDRED / decimal.Decimal(b)).quantize(decimal.Decimal("0.1")) if b else None


def _orders(session, company_id: int, f, by_activity: bool = True):
    """دستورهایی که در بازه فعالیت (تراکنش) داشته‌اند یا بازهٔ برنامه‌شان با بازه هم‌پوشانی دارد."""
    q = select(ProductionOrder).where(ProductionOrder.company_id == company_id, ProductionOrder.status_code != "CANCELLED")
    if f.item_id:
        q = q.where(ProductionOrder.item_id == f.item_id)
    if f.branch_id:
        q = q.where(ProductionOrder.branch_id == f.branch_id)
    if f.warehouse_id:
        q = q.where(ProductionOrder.fg_warehouse_id == f.warehouse_id)
    status = str(f.options.get("status") or "ALL")
    if status == "OPEN":
        q = q.where(ProductionOrder.status_code.in_(("DRAFT", "PLANNED", "RELEASED", "IN_PROGRESS", "ON_HOLD")))
    elif status == "COMPLETED":
        q = q.where(ProductionOrder.status_code.in_(("COMPLETED", "CLOSED")))
    active = select(OrderTransaction.order_id).where(OrderTransaction.txn_date.between(f.date_from, f.date_to))
    overlap = (ProductionOrder.start_date <= f.date_to) & (ProductionOrder.due_date >= f.date_from)
    q = q.where(overlap | ProductionOrder.order_id.in_(active)) if by_activity else q.where(overlap)
    return list(session.scalars(q.order_by(ProductionOrder.order_no)))


def _txns(session, company_id: int, f, types: tuple, order_ids=None):
    q = select(OrderTransaction).where(OrderTransaction.company_id == company_id, OrderTransaction.txn_type.in_(types),
                                       OrderTransaction.txn_date.between(f.date_from, f.date_to))
    if order_ids is not None:
        q = q.where(OrderTransaction.order_id.in_(order_ids or [-1]))
    return list(session.scalars(q.order_by(OrderTransaction.txn_date, OrderTransaction.txn_id)))


def _status_label(code):
    from peecha.services.production.orders import STATUS_LABELS

    return STATUS_LABELS.get(code, code)


# =====================================================================================
# تولید
# =====================================================================================
def orders_report(company_id: int, f) -> ReportResult:
    r = ReportResult([("دستور", TEXT), ("محصول", TEXT), ("وضعیت", TEXT), ("شروع", DATE), ("پایان", DATE), ("برنامه", QTY),
                      ("تولید", QTY), ("ضایعات", QTY), ("پیشرفت", PERCENT), ("تأخیر", TEXT)], no_total={8})
    with new_session() as session:
        rows = _orders(session, company_id, f)
        labels = c.item_labels(session, [o.item_id for o in rows])
        today = datetime.date.today()
        for o in rows:
            late = o.due_date < today and o.status_code not in ("COMPLETED", "CLOSED")
            r.add([o.order_code, labels.get(o.item_id, ""), _status_label(o.status_code), o.start_date, o.due_date, o.planned_qty,
                   o.produced_qty, o.scrapped_qty, o.progress_percent.quantize(decimal.Decimal("0.1")),
                   f"{(today - o.due_date).days} روز" if late else ""], _ref(o.order_id))
    return r


def _production_rows(session, company_id, f):
    """رسیدهایِ محصولِ اصلی در بازه (خالص از برگشت‌ها) همراهِ دستور."""
    out = []
    orders = {o.order_id: o for o in session.scalars(select(ProductionOrder).where(ProductionOrder.company_id == company_id))}
    for t in _txns(session, company_id, f, ("RECEIPT", "REVERSAL")):
        if t.txn_type == "REVERSAL" and (t.details or {}).get("of") != "RECEIPT":
            continue
        o = orders.get(t.order_id)
        if o is None or (f.item_id and o.item_id != f.item_id) or (f.branch_id and o.branch_id != f.branch_id):
            continue
        sign = 1 if t.txn_type == "RECEIPT" else 1  # ردیفِ برگشت خودش مقدار/مبلغِ منفی دارد
        out.append((o, t, decimal.Decimal(t.quantity) * sign, decimal.Decimal(t.amount) * sign))
    return out


def _by(dimension: str):
    titles = {"PRODUCT": "محصول", "WAREHOUSE": "انبارِ محصول", "BRANCH": "شعبه", "PERIOD": "دوره", "WORK_CENTER": "مرکزِ کاری"}

    def report(company_id: int, f) -> ReportResult:
        from peecha.services.fixed_assets.common import period_of

        agg: dict[str, list] = defaultdict(lambda: [set(), ZERO, ZERO])
        with new_session() as session:
            rows = _production_rows(session, company_id, f)
            labels = c.item_labels(session, [o.item_id for o, *_ in rows])
            whs = dict(session.execute(select(Warehouse.warehouse_id, Warehouse.name).where(Warehouse.company_id == company_id)).all())
            wcs = dict(session.execute(select(WorkCenter.work_center_id, WorkCenter.name).where(WorkCenter.company_id == company_id)).all())
            from peecha.db.models.commercial import Branch

            branches = dict(session.execute(select(Branch.branch_id, Branch.name).where(Branch.company_id == company_id)).all())
            for o, t, q, amount in rows:
                key = {"PRODUCT": lambda: labels.get(o.item_id, ""), "WAREHOUSE": lambda: whs.get(o.fg_warehouse_id, ""),
                       "BRANCH": lambda: branches.get(o.branch_id, ""), "PERIOD": lambda: period_of(t.txn_date)[0],
                       "WORK_CENTER": lambda: wcs.get(o.work_center_id, "")}[dimension]() or f"بدونِ {titles[dimension]}"
                g = agg[key]
                g[0].add(o.order_id)
                g[1] += q
                g[2] += amount
        r = ReportResult([(titles[dimension], TEXT), ("تعدادِ دستور", INT), ("مقدارِ تولید", QTY), ("بهایِ تولید", MONEY),
                          ("بهایِ واحد", MONEY)], no_total={4}, note="رسیدهایِ محصولِ اصلی در بازه (خالص از برگشتِ تولید).")
        order = sorted(agg.items()) if dimension == "PERIOD" else sorted(agg.items(), key=lambda kv: -kv[1][2])
        for key, (ids, q, amount) in order:
            r.add([key, len(ids), q, amount, c.money(amount / q) if q else None])
        return r
    return report


# =====================================================================================
# مواد
# =====================================================================================
def material_consumption(company_id: int, f) -> ReportResult:
    r = ReportResult([("تاریخ", DATE), ("دستور", TEXT), ("ماده", TEXT), ("نوع", TEXT), ("مقدار", QTY), ("مبلغ", MONEY)],
                     note="حواله (+) و برگشتِ مواد (−) به دستورهایِ تولید.")
    with new_session() as session:
        txns = [t for t in _txns(session, company_id, f, ("ISSUE", "RETURN")) if not f.item_id or t.item_id == f.item_id]
        codes = dict(session.execute(select(ProductionOrder.order_id, ProductionOrder.order_code)
                                     .where(ProductionOrder.company_id == company_id)).all())
        labels = c.item_labels(session, [t.item_id for t in txns])
        for t in txns:
            sign = 1 if t.txn_type == "ISSUE" else -1
            r.add([t.txn_date, codes.get(t.order_id, ""), labels.get(t.item_id, ""), "مصرف" if sign > 0 else "برگشت",
                   decimal.Decimal(t.quantity) * sign, decimal.Decimal(t.amount) * sign], _ref(t.order_id))
    return r


def _material_rows(session, company_id, f):
    from peecha.services.production import master as pm

    for o in _orders(session, company_id, f):
        if o.status_code in ("DRAFT", "PLANNED"):
            continue
        for m in session.scalars(select(OrderMaterial).where(OrderMaterial.order_id == o.order_id)):
            std = ZERO if m.is_optional else pm.line_requirement(m.quantity_per_base, m.quantity_type, m.scrap_percent,
                                                                 o.produced_qty, m.batch_size_qty)[1]
            yield o, m, std


def material_variance(company_id: int, f) -> ReportResult:
    r = ReportResult([("دستور", TEXT), ("ماده", TEXT), ("استاندارد برایِ تولید", QTY), ("مصرفِ واقعی", QTY), ("اختلاف", QTY),
                      ("اختلاف٪", PERCENT), ("انحرافِ مقداری (ریال)", MONEY), ("انحرافِ نرخ (ریال)", MONEY)], no_total={2, 3, 5},
                     note="استاندارد = BOM × تولیدِ سالم (با ضایعاتِ مجاز). مثال: ۱۰۰ کیلو استاندارد، ۱۰۶ واقعی ← +۶.")
    with new_session() as session:
        rows = list(_material_rows(session, company_id, f))
        labels = c.item_labels(session, [m.item_id for _o, m, _s in rows])
        for o, m, std in rows:
            if not m.consumed_qty and not std:
                continue
            diff = m.consumed_qty - std
            unit = decimal.Decimal(m.standard_unit_cost or 0)
            r.add([o.order_code, labels.get(m.item_id, ""), std, m.consumed_qty, diff, _pct(diff, std), c.money(diff * unit),
                   c.money(m.consumed_amount - m.consumed_qty * unit)], _ref(o.order_id))
    return r


def material_waste(company_id: int, f) -> ReportResult:
    r = ReportResult([("دستور", TEXT), ("ماده", TEXT), ("نوع", TEXT), ("مقدار", QTY), ("ارزش", MONEY), ("علت", TEXT)],
                     note="ضایعاتِ ثبت‌شدهٔ ماده + مصرفِ بیش از استاندارد (هدررفت).")
    with new_session() as session:
        codes = dict(session.execute(select(ProductionOrder.order_id, ProductionOrder.order_code)
                                     .where(ProductionOrder.company_id == company_id)).all())
        scraps = [t for t in _txns(session, company_id, f, ("SCRAP",)) if (t.details or {}).get("kind") == "MATERIAL"]
        rows = list(_material_rows(session, company_id, f))
        labels = c.item_labels(session, [t.item_id for t in scraps] + [m.item_id for _o, m, _s in rows])
        for t in scraps:
            m = session.get(OrderMaterial, t.material_id)
            unit = c.qty(m.consumed_amount / m.consumed_qty) if m and m.consumed_qty else ZERO
            r.add([codes.get(t.order_id, ""), labels.get(t.item_id, ""), "ضایعاتِ ثبت‌شده", t.quantity, c.money(t.quantity * unit),
                   t.reason or ""], _ref(t.order_id))
        for o, m, std in rows:
            over = m.consumed_qty - std
            if over > 0 and o.produced_qty:
                r.add([o.order_code, labels.get(m.item_id, ""), "مصرفِ مازاد", over, c.money(over * decimal.Decimal(m.standard_unit_cost or 0)),
                       ""], _ref(o.order_id))
    return r


def material_requirement(company_id: int, f) -> ReportResult:
    from peecha.services.production.orders import AVAILABILITY_LABELS, availability

    r = ReportResult([("دستور", TEXT), ("ماده", TEXT), ("نیاز", QTY), ("مصرف‌شده", QTY), ("مانده", QTY), ("موجود", QTY),
                      ("رزرو", QTY), ("کمبود", QTY), ("وضعیت", TEXT)], note="نیازِ موادِ دستورهایِ باز در برابرِ موجودیِ انبار.")
    with new_session() as session:
        orders = [o for o in _orders(session, company_id, f, by_activity=False)
                  if o.status_code in ("DRAFT", "PLANNED", "RELEASED", "IN_PROGRESS", "ON_HOLD")]
    for o in orders:
        for a in availability(company_id, o.order_id):
            if f.item_id and a.item_id != f.item_id:
                continue
            r.add([o.order_code, a.item_label, a.required, a.consumed, a.remaining, a.available, a.reserved, a.shortage,
                   AVAILABILITY_LABELS[a.status]], _ref(o.order_id))
    return r


# =====================================================================================
# بهایِ تمام‌شده
# =====================================================================================
def _costed(session, company_id, f):
    from peecha.services.production.costing import order_costs

    for o in _orders(session, company_id, f):
        if o.status_code in ("DRAFT", "PLANNED"):
            continue
        yield o, order_costs(session, o)


def production_cost(company_id: int, f) -> ReportResult:
    r = ReportResult([("دستور", TEXT), ("محصول", TEXT), ("مواد", MONEY), ("دستمزد", MONEY), ("ماشین", MONEY), ("سربار", MONEY),
                      ("جانبی/بازیافت", MONEY), ("بهایِ کل", MONEY), ("تولید", QTY), ("بهایِ واحد", MONEY)], no_total={9},
                     note="بهایِ کل = مواد + دستمزد + ماشین + سربار − ارزشِ جانبی − بازیافتِ ضایعات.")
    with new_session() as session:
        rows = list(_costed(session, company_id, f))
        labels = c.item_labels(session, [o.item_id for o, _ in rows])
        for o, k in rows:
            r.add([o.order_code, labels.get(o.item_id, ""), k.material, k.labor, k.machine, k.overhead,
                   -(k.byproduct_credit + k.scrap_recovery), k.total, k.produced, k.actual_unit_cost if k.produced else None],
                  _ref(o.order_id))
    return r


def unit_cost(company_id: int, f) -> ReportResult:
    r = ReportResult([("محصول", TEXT), ("تعدادِ دستور", INT), ("تولید", QTY), ("بهایِ کل", MONEY), ("بهایِ واحدِ واقعی", MONEY),
                      ("بهایِ استانداردِ واحد", MONEY), ("حداقل", MONEY), ("حداکثر", MONEY)], no_total={4, 5, 6, 7})
    agg = defaultdict(lambda: [0, ZERO, ZERO, ZERO, [], ZERO])
    with new_session() as session:
        rows = list(_costed(session, company_id, f))
        labels = c.item_labels(session, [o.item_id for o, _ in rows])
        for o, k in rows:
            if not k.produced:
                continue
            g = agg[o.item_id]
            g[0] += 1
            g[1] += k.produced
            g[2] += k.total - k.co_product_amount
            g[3] += k.standard_unit_cost * k.produced
            g[4].append(k.actual_unit_cost)
    for item_id, (n, q, total, std, units, _x) in agg.items():
        r.add([labels.get(item_id, ""), n, q, total, c.money(total / q), c.money(std / q), min(units), max(units)])
    return r


def std_vs_actual(company_id: int, f) -> ReportResult:
    r = ReportResult([("دستور", TEXT), ("محصول", TEXT), ("تولید", QTY), ("بهایِ استاندارد", MONEY), ("بهایِ واقعی", MONEY),
                      ("انحراف", MONEY), ("انحراف٪", PERCENT), ("استانداردِ واحد", MONEY), ("واقعیِ واحد", MONEY)],
                     no_total={6, 7, 8}, note="مثال: استاندارد ۱٬۰۰۰٬۰۰۰ و واقعی ۱٬۰۷۵٬۰۰۰ ← انحرافِ +۷۵٬۰۰۰ (نامساعد).")
    with new_session() as session:
        rows = list(_costed(session, company_id, f))
        labels = c.item_labels(session, [o.item_id for o, _ in rows])
        for o, k in rows:
            if not k.produced:
                continue
            actual = k.total - k.co_product_amount
            r.add([o.order_code, labels.get(o.item_id, ""), k.produced, k.standard_total, actual, k.variance,
                   _pct(k.variance, k.standard_total), k.standard_unit_cost, k.actual_unit_cost], _ref(o.order_id))
    return r


def cost_variance(company_id: int, f) -> ReportResult:
    from peecha.services.production.costing import VARIANCE_LABELS, variance_analysis

    codes = list(VARIANCE_LABELS)
    r = ReportResult([("دستور", TEXT)] + [(VARIANCE_LABELS[k], MONEY) for k in codes],
                     note="مثبت = نامساعد (هزینهٔ بیشتر از استاندارد)؛ منفی = مساعد.")
    with new_session() as session:
        for o in _orders(session, company_id, f):
            if not o.produced_qty:
                continue
            v = {x.code: x.amount for x in variance_analysis(session, o)}
            r.add([o.order_code] + [v.get(k, ZERO) for k in codes], _ref(o.order_id))
    return r


def overhead_allocation(company_id: int, f) -> ReportResult:
    r = ReportResult([("تاریخ", DATE), ("دستور", TEXT), ("منبع", TEXT), ("مبنا", TEXT), ("مقدارِ مبنا", QTY), ("مبلغ", MONEY)],
                     no_total={4}, note="سربارِ جذب‌شده: نرخِ از پیش تعیین‌شده رویِ ساعت + سرشکنِ استخرهایِ هزینه.")
    with new_session() as session:
        codes = dict(session.execute(select(ProductionOrder.order_id, ProductionOrder.order_code)
                                     .where(ProductionOrder.company_id == company_id)).all())
        pools = {p.pool_id: p for p in session.scalars(select(CostPool).where(CostPool.company_id == company_id))}
        bases = {a.txn_id: a.basis_value for a in session.scalars(select(CostAllocationRow).join(
            CostPool, CostPool.pool_id == CostAllocationRow.pool_id).where(CostPool.company_id == company_id))}
        for t in _txns(session, company_id, f, ("OVERHEAD",)):
            d = t.details or {}
            pool = pools.get(d.get("pool_id"))
            source = f"استخرِ {pool.code} -- {pool.name}" if pool else "نرخِ مرکزِ کاری/عملیات"
            basis = c.OVERHEAD_BASES.get(d.get("basis", ""), d.get("basis", ""))
            r.add([t.txn_date, codes.get(t.order_id, ""), source, basis, bases.get(t.txn_id, t.quantity), t.amount], _ref(t.order_id))
    return r


def labor_cost(company_id: int, f) -> ReportResult:
    from peecha.db.models.hr import Employee

    r = ReportResult([("تاریخ", DATE), ("دستور", TEXT), ("عملیات", TEXT), ("کارمند", TEXT), ("ساعت", QTY), ("اضافه‌کار", QTY),
                      ("نرخ", MONEY), ("مبلغ", MONEY), ("نوع", TEXT)], no_total={6})
    with new_session() as session:
        codes = dict(session.execute(select(ProductionOrder.order_id, ProductionOrder.order_code)
                                     .where(ProductionOrder.company_id == company_id)).all())
        for e in session.scalars(select(LaborEntry).where(LaborEntry.company_id == company_id,
                                                          LaborEntry.work_date.between(f.date_from, f.date_to))
                                 .order_by(LaborEntry.work_date)):
            op = session.get(OrderOperation, e.order_operation_id) if e.order_operation_id else None
            emp = session.get(Employee, e.employee_id) if e.employee_id else None
            r.add([e.work_date, codes.get(e.order_id, ""), op.name if op else "", f"{emp.first_name} {emp.last_name}" if emp else "",
                   e.hours, e.overtime_hours, e.rate, e.amount, "استاندارد (خودکار)" if e.is_standard else "واقعی"], _ref(e.order_id))
    return r


def machine_cost(company_id: int, f) -> ReportResult:
    from peecha.db.models.fixed_assets import Asset

    r = ReportResult([("تاریخ", DATE), ("دستور", TEXT), ("عملیات", TEXT), ("ماشین", TEXT), ("ساعت", QTY), ("نرخ", MONEY),
                      ("مبلغ", MONEY), ("نوع", TEXT)], no_total={5})
    with new_session() as session:
        codes = dict(session.execute(select(ProductionOrder.order_id, ProductionOrder.order_code)
                                     .where(ProductionOrder.company_id == company_id)).all())
        for e in session.scalars(select(MachineEntry).where(MachineEntry.company_id == company_id,
                                                            MachineEntry.work_date.between(f.date_from, f.date_to))
                                 .order_by(MachineEntry.work_date)):
            op = session.get(OrderOperation, e.order_operation_id) if e.order_operation_id else None
            asset = session.get(Asset, e.asset_id) if e.asset_id else None
            r.add([e.work_date, codes.get(e.order_id, ""), op.name if op else "", f"{asset.asset_code} {asset.name}" if asset else "",
                   e.hours, e.rate, e.amount, "استاندارد (خودکار)" if e.is_standard else "واقعی"], _ref(e.order_id))
    return r


# =====================================================================================
# موجودیِ تولید
# =====================================================================================
def wip_report(company_id: int, f) -> ReportResult:
    r = ReportResult([("دستور", TEXT), ("محصول", TEXT), ("وضعیت", TEXT), ("مواد", MONEY), ("تبدیل (دستمزد/ماشین/سربار)", MONEY),
                      ("انتقال به محصول", MONEY), ("ماندهٔ WIP", MONEY), ("تولیدشده", QTY), ("مانده", QTY)],
                     note="ماندهٔ کالایِ در جریانِ ساخت در پایانِ بازه = Σ ورودی − Σ انتقال (همخوان با حسابِ WIP).")
    with new_session() as session:
        rows = session.execute(select(OrderTransaction.order_id, OrderTransaction.txn_type, func.sum(OrderTransaction.wip_delta))
                               .where(OrderTransaction.company_id == company_id, OrderTransaction.txn_date <= f.date_to)
                               .group_by(OrderTransaction.order_id, OrderTransaction.txn_type)).all()
        agg = defaultdict(lambda: [ZERO, ZERO, ZERO])
        for oid, t, v in rows:
            v = decimal.Decimal(v or 0)
            if t in ("ISSUE", "RETURN"):
                agg[oid][0] += v
            elif t in ("LABOR", "MACHINE", "OVERHEAD"):
                agg[oid][1] += v
            else:
                agg[oid][2] += v
        orders = {o.order_id: o for o in session.scalars(select(ProductionOrder).where(ProductionOrder.order_id.in_(list(agg) or [-1])))}
        labels = c.item_labels(session, [o.item_id for o in orders.values()])
        for oid, (mat, conv, out) in sorted(agg.items()):
            o = orders[oid]
            bal = mat + conv + out
            if bal == 0 or (f.item_id and o.item_id != f.item_id):
                continue
            r.add([o.order_code, labels.get(o.item_id, ""), _status_label(o.status_code), mat, conv, -out, bal, o.produced_qty,
                   o.remaining_qty], _ref(oid))
    return r


def _stock_by_kind(kinds: tuple, note: str):
    def report(company_id: int, f) -> ReportResult:
        r = ReportResult([("کالا", TEXT), ("انبار", TEXT), ("موجودی", QTY), ("بهایِ میانگین", MONEY), ("ارزش", MONEY)], no_total={3},
                         note=note)
        with new_session() as session:
            q = (select(StockBalance.item_id, StockBalance.warehouse_id, func.sum(StockBalance.quantity_on_hand),
                        func.sum(StockBalance.quantity_on_hand * StockBalance.average_unit_cost))
                 .join(Item, Item.item_id == StockBalance.item_id)
                 .where(StockBalance.company_id == company_id, Item.item_kind_code.in_(kinds))
                 .group_by(StockBalance.item_id, StockBalance.warehouse_id))
            if f.item_id:
                q = q.where(StockBalance.item_id == f.item_id)
            if f.warehouse_id:
                q = q.where(StockBalance.warehouse_id == f.warehouse_id)
            rows = [x for x in session.execute(q).all() if x[2]]
            labels = c.item_labels(session, [x[0] for x in rows])
            whs = dict(session.execute(select(Warehouse.warehouse_id, Warehouse.name).where(Warehouse.company_id == company_id)).all())
            for item_id, wh, qty, value in rows:
                qty, value = decimal.Decimal(qty), decimal.Decimal(value or 0)
                r.add([labels.get(item_id, ""), whs.get(wh, ""), qty, c.money(value / qty) if qty else None, c.money(value)])
        return r
    return report


def scrap_report(company_id: int, f) -> ReportResult:
    r = ReportResult([("تاریخ", DATE), ("دستور", TEXT), ("کالا", TEXT), ("نوع", TEXT), ("مقدار", QTY), ("ارزشِ بازیافت", MONEY),
                      ("زیانِ غیرعادی", MONEY), ("علت", TEXT)])
    with new_session() as session:
        codes = dict(session.execute(select(ProductionOrder.order_id, ProductionOrder.order_code)
                                     .where(ProductionOrder.company_id == company_id)).all())
        txns = _txns(session, company_id, f, ("SCRAP", "VARIANCE"))
        labels = c.item_labels(session, [t.item_id for t in txns])
        for t in txns:
            kind = (t.details or {}).get("kind")
            if t.txn_type == "VARIANCE" and kind != "ABNORMAL_SCRAP":
                continue
            label = {"PRODUCT": "ضایعاتِ محصول", "MATERIAL": "ضایعاتِ ماده", "ABNORMAL_SCRAP": "ضایعاتِ غیرعادی"}.get(kind, "")
            r.add([t.txn_date, codes.get(t.order_id, ""), labels.get(t.item_id, ""), label, t.quantity,
                   t.amount if t.txn_type == "SCRAP" else ZERO, t.amount if t.txn_type == "VARIANCE" else ZERO, t.reason or ""],
                  _ref(t.order_id))
    return r


def byproducts(company_id: int, f) -> ReportResult:
    r = ReportResult([("تاریخ", DATE), ("دستور", TEXT), ("کالا", TEXT), ("نوع", TEXT), ("مقدار", QTY), ("ارزش", MONEY)],
                     note="محصولِ جانبی با ارزشِ بازیافت از بهایِ محصولِ اصلی کسر شده؛ محصولِ مشترک با روشِ تخصیص.")
    with new_session() as session:
        codes = dict(session.execute(select(ProductionOrder.order_id, ProductionOrder.order_code)
                                     .where(ProductionOrder.company_id == company_id)).all())
        txns = _txns(session, company_id, f, ("BY_PRODUCT", "CO_PRODUCT"))
        labels = c.item_labels(session, [t.item_id for t in txns])
        for t in txns:
            r.add([t.txn_date, codes.get(t.order_id, ""), labels.get(t.item_id, ""), c.OUTPUT_TYPES[t.txn_type], t.quantity, t.amount],
                  _ref(t.order_id))
    return r


# =====================================================================================
# مدیریتی
# =====================================================================================
def profitability(company_id: int, f) -> ReportResult:
    from peecha.db.models.commercial import CommercialDocument, CommercialDocumentLine

    r = ReportResult([("محصول", TEXT), ("فیِ فروش", MONEY), ("بهایِ واقعیِ تولید", MONEY), ("حاشیهٔ ناخالص", MONEY),
                      ("حاشیه٪", PERCENT), ("بهایِ استاندارد", MONEY), ("بهایِ میانگینِ موجودی", MONEY), ("فروش (مقدار)", QTY)],
                     no_total={1, 2, 3, 4, 5, 6}, note="فیِ فروش = میانگینِ فاکتورهایِ فروشِ بازه؛ بهایِ تولید = میانگینِ رسیدهایِ تولیدِ بازه.")
    with new_session() as session:
        made = defaultdict(lambda: [ZERO, ZERO])
        for o, _t, q, amount in _production_rows(session, company_id, f):
            made[o.item_id][0] += q
            made[o.item_id][1] += amount
        labels = c.item_labels(session, list(made))
        from peecha.services import inventory_engine as engine

        for item_id, (q, amount) in made.items():
            if not q:
                continue
            sq, sv = session.execute(select(func.sum(CommercialDocumentLine.quantity_base),
                                            func.sum(CommercialDocumentLine.quantity * CommercialDocumentLine.unit_price))
                                     .join(CommercialDocument, CommercialDocument.document_id == CommercialDocumentLine.document_id)
                                     .where(CommercialDocument.company_id == company_id, CommercialDocumentLine.item_id == item_id,
                                            CommercialDocument.document_type_code == "SALES_INVOICE",
                                            CommercialDocument.status_code == "POSTED",
                                            CommercialDocument.document_date.between(f.date_from, f.date_to))).one()
            price = c.money(decimal.Decimal(sv) / decimal.Decimal(sq)) if sq else None
            actual = c.money(amount / q)
            try:
                std = c.money(engine._standard_cost(session, item_id, f.date_to))
            except ValueError:
                std = None
            avg = engine._current_average_cost(session, item_id, None)
            margin = (price - actual) if price is not None else None
            r.add([labels.get(item_id, ""), price, actual, margin, _pct(margin, price) if price else None, std,
                   c.money(avg) if avg is not None else None, decimal.Decimal(sq or 0)])
    return r


def cost_trend(company_id: int, f) -> ReportResult:
    from peecha.services.fixed_assets.common import period_of

    r = ReportResult([("دوره", TEXT), ("محصول", TEXT), ("تولید", QTY), ("بهایِ کل", MONEY), ("بهایِ واحد", MONEY), ("تغییر٪", PERCENT)],
                     no_total={4, 5})
    agg = defaultdict(lambda: [ZERO, ZERO])
    with new_session() as session:
        for o, t, q, amount in _production_rows(session, company_id, f):
            agg[(o.item_id, period_of(t.txn_date)[0])][0] += q
            agg[(o.item_id, period_of(t.txn_date)[0])][1] += amount
        labels = c.item_labels(session, [k[0] for k in agg])
    last: dict[int, decimal.Decimal] = {}
    for (item_id, period), (q, amount) in sorted(agg.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        unit = c.money(amount / q) if q else None
        prev = last.get(item_id)
        r.add([period, labels.get(item_id, ""), q, amount, unit, _pct(unit - prev, prev) if unit is not None and prev else None])
        if unit is not None:
            last[item_id] = unit
    return r


def efficiency(company_id: int, f) -> ReportResult:
    r = ReportResult([("دستور", TEXT), ("محصول", TEXT), ("تحققِ برنامه٪", PERCENT), ("کاراییِ مواد٪", PERCENT),
                      ("کاراییِ دستمزد٪", PERCENT), ("کاراییِ ماشین٪", PERCENT), ("ضایعات٪", PERCENT), ("تأخیر (روز)", INT)],
                     no_total={2, 3, 4, 5, 6}, note="کارایی = استاندارد ÷ واقعی × ۱۰۰ (بالاتر از ۱۰۰ = بهتر از استاندارد).")
    with new_session() as session:
        from peecha.services.production import master as pm

        orders = [o for o in _orders(session, company_id, f) if o.produced_qty]
        labels = c.item_labels(session, [o.item_id for o in orders])
        for o in orders:
            std_mat = act_mat = ZERO
            for m in session.scalars(select(OrderMaterial).where(OrderMaterial.order_id == o.order_id)):
                if m.is_optional:
                    continue
                std = pm.line_requirement(m.quantity_per_base, m.quantity_type, m.scrap_percent, o.produced_qty, m.batch_size_qty)[1]
                std_mat += std * decimal.Decimal(m.standard_unit_cost or 0)
                act_mat += m.consumed_qty * decimal.Decimal(m.standard_unit_cost or 0)
            ops = list(session.scalars(select(OrderOperation).where(OrderOperation.order_id == o.order_id)))
            ratio = decimal.Decimal(o.produced_qty) / decimal.Decimal(o.planned_qty)
            std_l = sum((decimal.Decimal(op.std_labor_hours) * ratio for op in ops), ZERO)
            act_l = decimal.Decimal(session.scalar(select(func.coalesce(func.sum(LaborEntry.hours + LaborEntry.overtime_hours), 0))
                                                   .where(LaborEntry.order_id == o.order_id)) or 0)
            std_m = sum((decimal.Decimal(op.std_machine_hours) * ratio for op in ops), ZERO)
            act_m = decimal.Decimal(session.scalar(select(func.coalesce(func.sum(MachineEntry.hours), 0))
                                                   .where(MachineEntry.order_id == o.order_id)) or 0)
            end = o.actual_end_date or datetime.date.today()
            r.add([o.order_code, labels.get(o.item_id, ""), _pct(o.produced_qty, o.planned_qty), _pct(std_mat, act_mat),
                   _pct(std_l, act_l), _pct(std_m, act_m), _pct(o.scrapped_qty, decimal.Decimal(o.produced_qty) + decimal.Decimal(o.scrapped_qty)),
                   max(0, (end - o.due_date).days)], _ref(o.order_id))
    return r


def capacity(company_id: int, f) -> ReportResult:
    from peecha.services.production.planning import capacity_load

    r = ReportResult([("مرکزِ کاری", TEXT), ("ظرفیت (ساعت)", QTY), ("بار (ساعت)", QTY), ("آزاد (ساعت)", QTY), ("بهره‌برداری٪", PERCENT),
                      ("وضعیت", TEXT), ("دستورها", TEXT)], no_total={4}, note="ظرفیت = روزهایِ کاری × شیفت × ساعت × راندمان.")
    for x in capacity_load(company_id, f.date_from, f.date_to):
        r.add([f"{x.code} -- {x.name}", x.capacity_hours, x.load_hours, x.free_hours, x.utilization,
               "اضافه‌بار" if x.overloaded else "عادی", "، ".join(x.orders[:8])])
    return r


def scrap_analysis(company_id: int, f) -> ReportResult:
    from peecha.services.production.orders import normal_scrap_percent

    r = ReportResult([("محصول", TEXT), ("تولیدِ سالم", QTY), ("ضایعات", QTY), ("ضایعات٪", PERCENT), ("حدِ عادی٪", PERCENT),
                      ("ارزشِ بازیافت", MONEY), ("زیانِ غیرعادی", MONEY), ("وضعیت", TEXT)], no_total={3, 4})
    agg = defaultdict(lambda: [ZERO, ZERO, ZERO, ZERO, ZERO])
    with new_session() as session:
        for o in _orders(session, company_id, f):
            g = agg[o.item_id]
            g[0] += decimal.Decimal(o.produced_qty)
            g[1] += decimal.Decimal(o.scrapped_qty)
            g[2] = max(g[2], normal_scrap_percent(session, o))
            for t in session.scalars(select(OrderTransaction).where(OrderTransaction.order_id == o.order_id,
                                                                    OrderTransaction.txn_type.in_(("SCRAP", "VARIANCE")))):
                if t.txn_type == "SCRAP" and (t.details or {}).get("kind") == "PRODUCT":
                    g[3] += t.amount
                elif t.reason == "ABNORMAL_SCRAP":
                    g[4] += t.amount
        labels = c.item_labels(session, list(agg))
    for item_id, (good, scrap, normal, recovery, abnormal) in agg.items():
        if not scrap:
            continue
        pct = _pct(scrap, good + scrap)
        r.add([labels.get(item_id, ""), good, scrap, pct, normal, recovery, abnormal, "غیرعادی" if pct and pct > normal else "عادی"])
    return r


def trace(company_id: int, f) -> ReportResult:
    """ردیابی: محصول ← دستور ← BOM ← مصرفِ مواد ← بچ/لات ← تامین‌کننده (و برعکس با فیلترِ کالا رویِ ماده)."""
    from peecha.db.models.inventory import Batch, LotMovement, StockDocumentLine
    from peecha.services import detail_dimensions as dims

    direction = str(f.options.get("direction") or "DOWN")
    r = ReportResult([("دستور", TEXT), ("محصول", TEXT), ("بچِ محصول", TEXT), ("ماده", TEXT), ("بچِ ماده", TEXT), ("مقدارِ مصرف", QTY),
                      ("تامین‌کننده", TEXT), ("BOM", TEXT)], note="بالا به پایین: از محصول؛ پایین به بالا: کالایِ فیلتر = ماده.")
    with new_session() as session:
        q = select(ProductionOrder).where(ProductionOrder.company_id == company_id, ProductionOrder.status_code != "CANCELLED")
        if f.item_id and direction == "DOWN":
            q = q.where(ProductionOrder.item_id == f.item_id)
        if f.item_id and direction == "UP":
            q = q.where(ProductionOrder.order_id.in_(select(OrderMaterial.order_id).where(OrderMaterial.item_id == f.item_id)))
        orders = list(session.scalars(q.where(ProductionOrder.order_id.in_(
            select(OrderTransaction.order_id).where(OrderTransaction.txn_date.between(f.date_from, f.date_to))))))

        def lots(stock_document_id, item_id, sign):
            rows = session.execute(select(Batch.batch_no, LotMovement.supplier_detail_account_id, func.sum(LotMovement.quantity_base))
                                   .join(StockDocumentLine, StockDocumentLine.line_id == LotMovement.stock_document_line_id)
                                   .outerjoin(Batch, Batch.batch_id == LotMovement.batch_id)
                                   .where(StockDocumentLine.stock_document_id == stock_document_id, LotMovement.item_id == item_id)
                                   .group_by(Batch.batch_no, LotMovement.supplier_detail_account_id)).all()
            return [(b or "", s, decimal.Decimal(qty) * sign) for b, s, qty in rows]

        labels = c.item_labels(session, [o.item_id for o in orders])
        for o in orders:
            txns = list(session.scalars(select(OrderTransaction).where(OrderTransaction.order_id == o.order_id)))
            out_batches = sorted({b for t in txns if t.txn_type == "RECEIPT" and t.stock_document_id
                                  for b, _s, _q in lots(t.stock_document_id, o.item_id, 1) if b}) or [""]
            for t in txns:
                if t.txn_type != "ISSUE" or (f.item_id and direction == "UP" and t.item_id != f.item_id):
                    continue
                found = lots(t.stock_document_id, t.item_id, -1) if t.stock_document_id else []
                label = c.item_label(session, t.item_id)
                for b, s, qty in found or [("", None, decimal.Decimal(t.quantity))]:
                    supplier = dims.get_detail_account_label(s) if s else ""
                    r.add([o.order_code, labels.get(o.item_id, ""), "، ".join(out_batches), label, b, qty, supplier,
                           f"BOM #{o.bom_id}"], _ref(o.order_id))
    return r


_NONE = ()
PRODUCTION_REPORTS: list[ReportDef] = [
    ReportDef("PRD_ORDERS", "دستورهایِ تولید", orders_report, ("item", "warehouse", "branch"), "وضعیت، برنامه، تولید، پیشرفت و تأخیر.",
              "range", _G_PROD, options=_STATUS_OPT),
    ReportDef("PRD_BY_PRODUCT", "تولید به تفکیکِ محصول", _by("PRODUCT"), _ITEM, "مقدار و بهایِ تولید هر محصول.", "range", _G_PROD),
    ReportDef("PRD_BY_WAREHOUSE", "تولید به تفکیکِ انبار", _by("WAREHOUSE"), _ITEM, "انبارِ محصولِ دستورها.", "range", _G_PROD),
    ReportDef("PRD_BY_BRANCH", "تولید به تفکیکِ شعبه", _by("BRANCH"), ("item", "branch"), "شعبهٔ دستورها.", "range", _G_PROD),
    ReportDef("PRD_BY_PERIOD", "تولید به تفکیکِ دوره", _by("PERIOD"), _ITEM, "ماه‌هایِ شمسی.", "range", _G_PROD),
    ReportDef("PRD_BY_WORK_CENTER", "تولید به تفکیکِ مرکزِ کاری", _by("WORK_CENTER"), _ITEM, "خط/مرکزِ اصلیِ دستور.", "range", _G_PROD),
    ReportDef("PRD_MATERIAL_CONSUMPTION", "مصرفِ مواد", material_consumption, _ITEM, "حواله و برگشتِ موادِ تولید.", "range", _G_MAT),
    ReportDef("PRD_MATERIAL_VARIANCE", "انحرافِ مواد", material_variance, _ITEM, "استاندارد در برابرِ مصرفِ واقعی.", "range", _G_MAT),
    ReportDef("PRD_MATERIAL_WASTE", "ضایعات و هدررفتِ مواد", material_waste, _ITEM, "ضایعاتِ ثبت‌شده و مصرفِ مازاد.", "range", _G_MAT),
    ReportDef("PRD_MATERIAL_REQUIREMENT", "نیازِ مواد", material_requirement, _ITEM, "نیاز، موجودی، رزرو و کمبودِ دستورهایِ باز.",
              "range", _G_MAT),
    ReportDef("PRD_COST", "بهایِ تمام‌شدهٔ تولید", production_cost, ("item", "branch"), "عناصرِ بهایِ هر دستور.", "range", _G_COST),
    ReportDef("PRD_UNIT_COST", "بهایِ واحدِ محصول", unit_cost, _ITEM, "بهایِ واحدِ واقعی/استاندارد هر محصول.", "range", _G_COST),
    ReportDef("PRD_STD_VS_ACTUAL", "استاندارد در برابرِ واقعی", std_vs_actual, _ITEM, "انحرافِ کلِ هر دستور.", "range", _G_COST),
    ReportDef("PRD_COST_VARIANCE", "تحلیلِ انحرافِ بها", cost_variance, _ITEM, "نرخ/مصرفِ مواد، نرخ/کاراییِ دستمزد و ماشین، سربار، "
              "مقدار، ضایعات.", "range", _G_COST),
    ReportDef("PRD_OVERHEAD", "تخصیصِ سربار", overhead_allocation, _NONE, "سربارِ جذب‌شده به تفکیکِ منبع و مبنا.", "range", _G_COST),
    ReportDef("PRD_LABOR", "هزینهٔ دستمزد", labor_cost, _NONE, "ساعت × نرخِ هر کارمند/عملیات.", "range", _G_COST),
    ReportDef("PRD_MACHINE", "هزینهٔ ماشین", machine_cost, _NONE, "ساعت × نرخِ هر ماشین.", "range", _G_COST),
    ReportDef("PRD_WIP", "کالایِ در جریانِ ساخت (WIP)", wip_report, _ITEM, "ماندهٔ WIP هر دستور.", "as_of", _G_INV),
    ReportDef("PRD_SEMI_STOCK", "موجودیِ نیمه‌ساخته", _stock_by_kind(("SEMI_FINISHED",), "کالاهایِ نوعِ نیمه‌ساخته."), _ITEM_WH,
              "موجودی و ارزشِ نیمه‌ساخته‌ها.", "none", _G_INV),
    ReportDef("PRD_FG_STOCK", "موجودیِ محصولِ نهایی", _stock_by_kind(("FINISHED_GOOD",), "کالاهایِ نوعِ محصولِ نهایی."), _ITEM_WH,
              "موجودی و ارزشِ محصولات.", "none", _G_INV),
    ReportDef("PRD_SCRAP", "ضایعات", scrap_report, _NONE, "ضایعاتِ محصول/ماده، بازیافت و زیانِ غیرعادی.", "range", _G_INV),
    ReportDef("PRD_BYPRODUCTS", "محصولاتِ جانبی و مشترک", byproducts, _NONE, "رسیدهایِ جانبی و مشترک.", "range", _G_INV),
    ReportDef("PRD_PROFITABILITY", "سودآوریِ تولید", profitability, _ITEM, "فیِ فروش، بهایِ تولید و حاشیهٔ ناخالص.", "range", _G_MGMT),
    ReportDef("PRD_COST_TREND", "روندِ بهایِ تمام‌شده", cost_trend, _ITEM, "بهایِ واحدِ ماهانه و درصدِ تغییر.", "range", _G_MGMT),
    ReportDef("PRD_EFFICIENCY", "کاراییِ تولید", efficiency, _ITEM, "تحققِ برنامه، کاراییِ مواد/دستمزد/ماشین و تأخیر.", "range",
              _G_MGMT),
    ReportDef("PRD_CAPACITY", "بهره‌برداری از ظرفیت", capacity, _NONE, "بار در برابرِ ظرفیتِ هر مرکزِ کاری.", "range", _G_MGMT),
    ReportDef("PRD_SCRAP_ANALYSIS", "تحلیلِ ضایعات", scrap_analysis, _ITEM, "درصدِ ضایعات در برابرِ حدِ عادی.", "range", _G_MGMT),
    ReportDef("PRD_TRACE", "ردیابیِ تولید (Traceability)", trace, _ITEM, "محصول ← دستور ← مواد ← بچ ← تامین‌کننده و برعکس.", "range",
              _G_MGMT, options=(("direction", "جهت", (("DOWN", "از محصول به مواد"), ("UP", "از ماده به محصولات"))),)),
]
