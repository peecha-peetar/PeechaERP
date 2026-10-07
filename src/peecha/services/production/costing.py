"""هزینه‌یابی تولید — R268: دستمزد، ماشین، سربار، موتور عمومی سرشکن (مخزن هزینه)، بهای استاندارد (چندسطحی)،
بهای واقعی، تحلیل انحراف و بستن دوره‌ای.

بهای مواد همیشه از موتور انبار می‌آید (همان روش قیمت‌گذاری هر کالا: FIFO/LIFO/میانگین/استاندارد/...)؛ این ماژول
روش قیمت‌گذاری مستقلی ندارد. دستمزد/ماشین/سربار «جذب‌شده» ثبت می‌شوند (بدهکار کالای در جریان ساخت / بستانکار حساب جذب)؛ هزینهٔ
واقعی حقوق و استهلاک همچنان در ماژول‌های خودشان ثبت می‌شود.
"""

from __future__ import annotations

import datetime
import decimal
from dataclasses import dataclass
from types import SimpleNamespace

from sqlalchemy import func, select

from peecha.db.base import new_session
from peecha.db.models.fixed_assets import MachineCostAllocation
from peecha.db.models.inventory import BomHeader, BomLine, StandardCost
from peecha.db.models.production import (
    BomOutput, CostAllocationRow, CostClosing, CostPool, ItemProductionProfile, LaborEntry, MachineEntry, OrderCostSummary,
    OrderMaterial, OrderOperation, OrderOutput, OrderTransaction, OrderVariance, ProductionOrder, RoutingOperation, StandardCostCard,
    WorkCenter,
)
from peecha.services.production import common as c
from peecha.services.production import master as pm

ZERO, ONE = c.ZERO, c.ONE
_HUNDRED = decimal.Decimal(100)

VARIANCE_LABELS = {
    "MATERIAL_PRICE": "انحراف نرخ مواد", "MATERIAL_USAGE": "انحراف مصرف مواد", "LABOR_RATE": "انحراف نرخ دستمزد",
    "LABOR_EFFICIENCY": "انحراف کارایی دستمزد", "MACHINE_RATE": "انحراف نرخ ماشین", "MACHINE_EFFICIENCY": "انحراف کارایی ماشین",
    "OVERHEAD": "انحراف سربار", "PRODUCTION_QUANTITY": "انحراف مقدار تولید", "SCRAP": "انحراف ضایعات",
    "TOTAL": "انحراف کل تولید",
}
POOL_CATEGORIES = {"ELECTRICITY": "برق", "GAS": "گاز", "DEPRECIATION": "استهلاک", "MAINTENANCE": "تعمیرات و نگهداری",
                   "RENT": "اجارهٔ کارخانه", "INSURANCE": "بیمه", "INDIRECT": "هزینهٔ غیرمستقیم تولید",
                   "OVERHEAD": "سربار کارخانه", "OTHER": "سایر"}


# =====================================================================================
# دوره
# =====================================================================================
def period_is_closed(session, company_id: int, date: datetime.date) -> bool:
    code = c_period(date)[0]
    return session.scalar(select(CostClosing.closing_id).where(CostClosing.company_id == company_id,
                                                               CostClosing.period_code == code,
                                                               CostClosing.status_code == "FINALIZED")) is not None


def ensure_period_open(session, company_id: int, date: datetime.date) -> None:
    if period_is_closed(session, company_id, date):
        raise ValueError(f"دورهٔ بهای {c_period(date)[0]} بسته شده است و ثبت تولید در آن مجاز نیست.")


def c_period(date: datetime.date):
    from peecha.services.fixed_assets.common import period_of

    return period_of(date)


def c_period_from_code(code: str):
    from peecha.services.fixed_assets.common import period_from_code

    return period_from_code(code)


# =====================================================================================
# دستمزد / ماشین / سربار
# =====================================================================================
def _orders():
    from peecha.services.production import orders as po

    return po


def _conversion_txn(session, order: ProductionOrder, txn_type: str, role: str, amount: decimal.Decimal, date: datetime.date,
                    user_id: int, key: str | None, op_id: int | None, quantity=ZERO, details=None,
                    credit_dims: tuple | None = None) -> OrderTransaction:
    po = _orders()
    amount = c.money(amount)
    dims = (order.cost_center_detail_account_id, order.project_detail_account_id)
    je = c.post_journal(session, order.company_id, user_id, date, f"{order.order_code} -- {po.TXN_LABELS[txn_type]}",
                        [(c.WIP, amount, ZERO, dims), (role, ZERO, amount, credit_dims or dims)]) if amount else None
    return po.record(session, order, txn_type, date, user_id, quantity=quantity, amount=amount, wip_delta=amount,
                     order_operation_id=op_id, journal_entry_id=je, key=key, details=details)


def _op_of(session, order: ProductionOrder, op_id: int | None) -> OrderOperation | None:
    if op_id is None:
        return None
    op = session.get(OrderOperation, op_id)
    if op is None or op.order_id != order.order_id:
        raise ValueError("عملیات دستور نامعتبر است.")
    return op


def _overhead_for(session, order: ProductionOrder, op: OrderOperation | None, labor_hours: decimal.Decimal,
                  machine_hours: decimal.Decimal, date, user_id, key) -> None:
    """سربار با نرخ از پیش تعیین‌شده روی مبنای واقعی (ساعت کار یا ماشین، طبق تنظیمات)."""
    if op is None or not op.overhead_rate:
        return
    basis = c.settings(session, order.company_id).default_overhead_basis
    hours = machine_hours if basis == "MACHINE_HOURS" else labor_hours
    if basis not in ("LABOR_HOURS", "MACHINE_HOURS") or hours <= 0:
        return
    _conversion_txn(session, order, "OVERHEAD", c.OVERHEAD_APPLIED, decimal.Decimal(op.overhead_rate) * hours, date, user_id,
                    f"{key}:oh" if key else None, op.order_operation_id, quantity=hours,
                    details={"basis": basis, "rate": str(op.overhead_rate)})


@dataclass
class LaborInput:
    hours: decimal.Decimal
    order_operation_id: int | None = None
    employee_id: int | None = None
    overtime_hours: decimal.Decimal = ZERO
    rate: decimal.Decimal | None = None
    work_date: datetime.date | None = None
    cost_center_detail_account_id: int | None = None
    notes: str | None = None


def record_labor(company_id: int, user_id: int, order_id: int, data: LaborInput, idempotency_key: str | None = None) -> int:
    """دستمزد مستقیم = ساعت × نرخ (+ اضافه‌کار × نرخ × ضریب). بدهکار کالای در جریان ساخت / بستانکار دستمزد جذب‌شده."""
    po = _orders()
    hours, overtime = decimal.Decimal(data.hours or 0), decimal.Decimal(data.overtime_hours or 0)
    if hours < 0 or overtime < 0 or hours + overtime <= 0:
        raise ValueError("ساعت کار باید بزرگ‌تر از صفر باشد.")
    date = data.work_date or datetime.date.today()
    with new_session() as session:
        if idempotency_key and (done := session.scalar(select(LaborEntry.entry_id).join(
                OrderTransaction, OrderTransaction.txn_id == LaborEntry.txn_id).where(OrderTransaction.idempotency_key == idempotency_key))):
            return done
        order = po.lock_order(session, company_id, order_id)
        po._ensure_working(order) if order.status_code != "COMPLETED" else None
        c.require_roles(session, company_id, (c.WIP, c.LABOR_APPLIED))
        op = _op_of(session, order, data.order_operation_id)
        entry = _labor(session, order, op, data.employee_id, hours, overtime, data.rate, date, user_id, idempotency_key,
                       data.cost_center_detail_account_id, False, data.notes)
        session.commit()
        return entry.entry_id


def _labor(session, order, op, employee_id, hours, overtime, rate, date, user_id, key, cost_center, is_standard,
           notes=None) -> LaborEntry:
    wc_id = op.work_center_id if op else order.work_center_id
    std_rate = decimal.Decimal(op.labor_rate) if op is not None and op.labor_rate else None
    base_rate, multiplier = pm.labor_rate_for(session, order.company_id, employee_id, wc_id, std_rate)
    rate = decimal.Decimal(rate) if rate is not None else base_rate
    ot_rate = c.money(rate * multiplier)
    amount = c.money(hours * rate + overtime * ot_rate)
    credit_dims = (cost_center or order.cost_center_detail_account_id, order.project_detail_account_id)
    txn = _conversion_txn(session, order, "LABOR", c.LABOR_APPLIED, amount, date, user_id, key,
                          op.order_operation_id if op else None, quantity=hours + overtime,
                          details={"employee_id": employee_id, "rate": str(rate), "standard": is_standard}, credit_dims=credit_dims)
    entry = LaborEntry(company_id=order.company_id, order_id=order.order_id, order_operation_id=op.order_operation_id if op else None,
                       employee_id=employee_id, work_center_id=wc_id, work_date=date, hours=hours, overtime_hours=overtime,
                       rate=rate, overtime_rate=ot_rate, amount=amount, cost_center_detail_account_id=cost_center,
                       is_standard=is_standard, txn_id=txn.txn_id, notes=notes, created_by_user_id=user_id)
    session.add(entry)
    if op is not None:
        op.actual_labor_hours = decimal.Decimal(op.actual_labor_hours) + hours + overtime
        if op.status_code == "PENDING":
            op.status_code, op.started_at = "IN_PROGRESS", datetime.datetime.now()
    session.flush()
    _overhead_for(session, order, op, hours + overtime, ZERO, date, user_id, key)
    c.audit(session, order.company_id, user_id, "ProductionOrder", order.order_id, "LABOR",
            {"hours": str(hours), "overtime": str(overtime), "rate": str(rate), "amount": str(amount), "standard": is_standard})
    return entry


@dataclass
class MachineInput:
    hours: decimal.Decimal
    order_operation_id: int | None = None
    asset_id: int | None = None
    rate: decimal.Decimal | None = None
    work_date: datetime.date | None = None


def record_machine(company_id: int, user_id: int, order_id: int, data: MachineInput, idempotency_key: str | None = None) -> int:
    """هزینهٔ ماشین = ساعت × نرخ (نرخ: دستی ← عملیات ← مرکز کاری ← ماژول دارایی). تخصیص در fa.machine_cost_allocations
    هم به کد دستور ثبت می‌شود."""
    po = _orders()
    hours = decimal.Decimal(data.hours or 0)
    if hours <= 0:
        raise ValueError("ساعت ماشین باید بزرگ‌تر از صفر باشد.")
    date = data.work_date or datetime.date.today()
    with new_session() as session:
        if idempotency_key and (done := session.scalar(select(MachineEntry.entry_id).join(
                OrderTransaction, OrderTransaction.txn_id == MachineEntry.txn_id).where(OrderTransaction.idempotency_key == idempotency_key))):
            return done
        order = po.lock_order(session, company_id, order_id)
        po._ensure_working(order) if order.status_code != "COMPLETED" else None
        c.require_roles(session, company_id, (c.WIP, c.MACHINE_APPLIED))
        op = _op_of(session, order, data.order_operation_id)
        entry = _machine(session, order, op, data.asset_id, hours, data.rate, date, user_id, idempotency_key, False)
        session.commit()
        return entry.entry_id


def _machine(session, order, op, asset_id, hours, rate, date, user_id, key, is_standard) -> MachineEntry:
    po = _orders()
    asset_id = asset_id or (op.asset_id if op else None)
    wc_id = op.work_center_id if op else order.work_center_id
    if rate is None:
        rate = decimal.Decimal(op.machine_rate) if op is not None and op.machine_rate else None
    if rate is None and wc_id:
        wc = session.get(WorkCenter, wc_id)
        rate = decimal.Decimal(wc.machine_rate) if wc and wc.machine_rate else None
    if rate is None and asset_id:
        rate = po._asset_rate(session, asset_id, date)
    rate = decimal.Decimal(rate or 0)
    amount = c.money(hours * rate)
    txn = _conversion_txn(session, order, "MACHINE", c.MACHINE_APPLIED, amount, date, user_id, key,
                          op.order_operation_id if op else None, quantity=hours,
                          details={"asset_id": asset_id, "rate": str(rate), "standard": is_standard})
    alloc_id = None
    if asset_id:
        alloc = MachineCostAllocation(company_id=order.company_id, asset_id=asset_id, period_code=c_period(date)[0],
                                      production_order_ref=order.order_code, hours=hours, rate_per_hour=rate, amount=amount,
                                      cost_center_detail_account_id=order.cost_center_detail_account_id)
        session.add(alloc)
        session.flush()
        alloc_id = alloc.allocation_id
    entry = MachineEntry(company_id=order.company_id, order_id=order.order_id, order_operation_id=op.order_operation_id if op else None,
                         work_center_id=wc_id, asset_id=asset_id, work_date=date, hours=hours, rate=rate, amount=amount,
                         is_standard=is_standard, fa_allocation_id=alloc_id, txn_id=txn.txn_id, created_by_user_id=user_id)
    session.add(entry)
    if op is not None:
        op.actual_machine_hours = decimal.Decimal(op.actual_machine_hours) + hours
    session.flush()
    _overhead_for(session, order, op, ZERO, hours, date, user_id, key)
    return entry


def apply_standard_conversion(session, order: ProductionOrder, produced_total: decimal.Decimal, date: datetime.date,
                              user_id: int, key: str | None) -> None:
    """«محاسبهٔ خودکار بها»: برای عملیاتی که ساعت واقعی برایش ثبت نشده، دستمزد/ماشین استاندارد به نسبت تولید تجمعی
    جذب می‌شود (سربار هم همراهش). عملیاتی که ساعت واقعی دارد دست نمی‌خورد."""
    ratio = decimal.Decimal(produced_total) / decimal.Decimal(order.planned_qty)
    for op in session.scalars(select(OrderOperation).where(OrderOperation.order_id == order.order_id).order_by(OrderOperation.seq)):
        manual_labor = session.scalar(select(func.count()).select_from(LaborEntry).where(
            LaborEntry.order_operation_id == op.order_operation_id, LaborEntry.is_standard.is_(False)))
        if not manual_labor and op.std_labor_hours and op.labor_rate:
            done = decimal.Decimal(session.scalar(select(func.coalesce(func.sum(LaborEntry.hours), 0)).where(
                LaborEntry.order_operation_id == op.order_operation_id, LaborEntry.is_standard.is_(True))) or 0)
            gap = (decimal.Decimal(op.std_labor_hours) * ratio).quantize(decimal.Decimal("0.0001")) - done
            if gap > 0:
                c.require_roles(session, order.company_id, (c.LABOR_APPLIED,))
                _labor(session, order, op, None, gap, ZERO, op.labor_rate, date, user_id,
                       f"{key}:l{op.seq}" if key else None, None, True)
        manual_machine = session.scalar(select(func.count()).select_from(MachineEntry).where(
            MachineEntry.order_operation_id == op.order_operation_id, MachineEntry.is_standard.is_(False)))
        if not manual_machine and op.std_machine_hours and op.machine_rate:
            done = decimal.Decimal(session.scalar(select(func.coalesce(func.sum(MachineEntry.hours), 0)).where(
                MachineEntry.order_operation_id == op.order_operation_id, MachineEntry.is_standard.is_(True))) or 0)
            gap = (decimal.Decimal(op.std_machine_hours) * ratio).quantize(decimal.Decimal("0.0001")) - done
            if gap > 0:
                c.require_roles(session, order.company_id, (c.MACHINE_APPLIED,))
                _machine(session, order, op, None, gap, op.machine_rate, date, user_id, f"{key}:m{op.seq}" if key else None, True)


def list_labor(company_id: int, order_id: int) -> list[LaborEntry]:
    with new_session() as session:
        rows = list(session.scalars(select(LaborEntry).where(LaborEntry.company_id == company_id, LaborEntry.order_id == order_id)
                                    .order_by(LaborEntry.entry_id)))
        for r in rows:
            session.expunge(r)
        return rows


def list_machine(company_id: int, order_id: int) -> list[MachineEntry]:
    with new_session() as session:
        rows = list(session.scalars(select(MachineEntry).where(MachineEntry.company_id == company_id, MachineEntry.order_id == order_id)
                                    .order_by(MachineEntry.entry_id)))
        for r in rows:
            session.expunge(r)
        return rows


# =====================================================================================
# موتورِ عمومیِ سرشکن + استخرِ هزینه
# =====================================================================================
def allocate(total, bases: dict) -> dict:
    """سرشکن total به نسبت مبناها (کلید ← مقدار)؛ گردکردن روی بزرگ‌ترین سهم. مبنای صفر = خطا."""
    total = c.money(total)
    positive = {k: decimal.Decimal(v) for k, v in bases.items() if decimal.Decimal(v) > 0}
    base = sum(positive.values(), ZERO)
    if base <= 0:
        raise ValueError("مبنای سرشکن برای هیچ دستوری مقدار ندارد.")
    shares = {k: c.money(total * v / base) for k, v in positive.items()}
    biggest = max(positive, key=lambda k: positive[k])
    shares[biggest] += total - sum(shares.values(), ZERO)
    return shares


def save_pool(company_id: int, code: str, name: str, period_code: str, amount, basis: str, category: str = "OVERHEAD",
              work_center_id: int | None = None, notes: str | None = None, user_id: int | None = None,
              pool_id: int | None = None) -> int:
    if basis not in c.OVERHEAD_BASES:
        raise ValueError("مبنای سرشکن نامعتبر است.")
    if category not in POOL_CATEGORIES:
        raise ValueError("نوع هزینه نامعتبر است.")
    amount = decimal.Decimal(amount)
    if amount < 0 or not code.strip() or not name.strip():
        raise ValueError("کد، نام و مبلغ معتبر الزامی است.")
    code_p, _s, _e = c_period_from_code(period_code)
    with new_session() as session:
        row = session.get(CostPool, pool_id) if pool_id else CostPool(company_id=company_id, allocated_amount=ZERO, status_code="OPEN")
        if row is None or row.company_id != company_id:
            raise ValueError("مخزن هزینه نامعتبر است.")
        if pool_id and row.allocated_amount:
            raise ValueError("مخزن سرشکن‌شده قابل ویرایش نیست.")
        row.code, row.name, row.period_code, row.amount, row.basis = code.strip(), name.strip(), code_p, amount, basis
        row.category, row.work_center_id, row.notes = category, work_center_id, notes
        if pool_id is None:
            session.add(row)
        session.flush()
        c.audit(session, company_id, user_id, "CostPool", row.pool_id, "CREATE" if pool_id is None else "UPDATE",
                {"amount": str(amount), "basis": basis, "period": code_p})
        session.commit()
        return row.pool_id


def list_pools(company_id: int, period_code: str | None = None) -> list[CostPool]:
    with new_session() as session:
        q = select(CostPool).where(CostPool.company_id == company_id)
        if period_code:
            q = q.where(CostPool.period_code == period_code)
        rows = list(session.scalars(q.order_by(CostPool.period_code.desc(), CostPool.code)))
        for r in rows:
            session.expunge(r)
        return rows


def pool_bases(session, company_id: int, pool: CostPool) -> dict[int, decimal.Decimal]:
    """مبنای هر دستور باز دارای فعالیت در دورهٔ مخزن."""
    _code, start, end = c_period_from_code(pool.period_code)
    orders_q = select(ProductionOrder.order_id).where(ProductionOrder.company_id == company_id,
                                                      ProductionOrder.status_code.in_(("RELEASED", "IN_PROGRESS", "ON_HOLD", "COMPLETED")))
    if pool.work_center_id:
        orders_q = orders_q.where(ProductionOrder.order_id.in_(select(OrderOperation.order_id).where(
            OrderOperation.work_center_id == pool.work_center_id)))
    ids = set(session.scalars(orders_q))
    if not ids:
        return {}

    def txn_sum(types, col):
        return {oid: decimal.Decimal(v or 0) for oid, v in session.execute(
            select(OrderTransaction.order_id, func.sum(col)).where(OrderTransaction.order_id.in_(ids),
                                                                  OrderTransaction.txn_type.in_(types),
                                                                  OrderTransaction.txn_date.between(start, end))
            .group_by(OrderTransaction.order_id)).all()}

    if pool.basis == "LABOR_HOURS":
        return txn_sum(("LABOR",), OrderTransaction.quantity)
    if pool.basis == "MACHINE_HOURS":
        return txn_sum(("MACHINE",), OrderTransaction.quantity)
    if pool.basis == "QUANTITY":
        return txn_sum(("RECEIPT",), OrderTransaction.quantity)
    if pool.basis == "MATERIAL_COST":
        issued, returned = txn_sum(("ISSUE",), OrderTransaction.amount), txn_sum(("RETURN",), OrderTransaction.amount)
        return {k: v - returned.get(k, ZERO) for k, v in issued.items()}
    if pool.basis == "LABOR_COST":
        return txn_sum(("LABOR",), OrderTransaction.amount)
    return {}


def preview_pool(company_id: int, pool_id: int, manual: dict[int, decimal.Decimal] | None = None) -> list[SimpleNamespace]:
    with new_session() as session:
        pool = session.get(CostPool, pool_id)
        if pool is None or pool.company_id != company_id:
            raise ValueError("مخزن هزینه نامعتبر است.")
        bases = _bases_for(session, company_id, pool, manual)
        shares = _shares(pool, bases)
        codes = dict(session.execute(select(ProductionOrder.order_id, ProductionOrder.order_code)
                                     .where(ProductionOrder.order_id.in_(list(shares) or [-1]))).all())
        return [SimpleNamespace(order_id=k, order_code=codes.get(k, ""), basis_value=bases.get(k, ZERO), amount=v)
                for k, v in shares.items()]


def _bases_for(session, company_id, pool, manual):
    if pool.basis in ("PERCENTAGE", "MANUAL"):
        if not manual:
            raise ValueError("برای سرشکن درصدی/دستی، سهم هر دستور را وارد کنید.")
        if pool.basis == "PERCENTAGE" and sum(decimal.Decimal(v) for v in manual.values()) != _HUNDRED:
            raise ValueError("جمع درصدها باید ۱۰۰ باشد.")
        return {int(k): decimal.Decimal(v) for k, v in manual.items()}
    return pool_bases(session, company_id, pool)


def _shares(pool: CostPool, bases: dict) -> dict:
    remaining = decimal.Decimal(pool.amount) - decimal.Decimal(pool.allocated_amount)
    if pool.basis == "MANUAL":
        if c.money(sum(bases.values(), ZERO)) != c.money(remaining):
            raise ValueError(f"جمع مبالغ دستی ({c.money(sum(bases.values(), ZERO))}) با ماندهٔ مخزن ({c.money(remaining)}) برابر نیست.")
        return {k: c.money(v) for k, v in bases.items() if v}
    return allocate(remaining, bases)


def allocate_pool(company_id: int, user_id: int, pool_id: int, manual: dict[int, decimal.Decimal] | None = None,
                  date: datetime.date | None = None) -> list[SimpleNamespace]:
    """سرشکن مخزن روی دستورها: بدهکار کالای در جریان ساخت هر دستور / بستانکار سربار جذب‌شده — اتمیک (همه یا هیچ)."""
    po = _orders()
    with new_session() as session:
        pool = session.scalar(select(CostPool).where(CostPool.pool_id == pool_id).with_for_update())
        if pool is None or pool.company_id != company_id:
            raise ValueError("مخزن هزینه نامعتبر است.")
        if pool.status_code == "ALLOCATED":
            raise ValueError("این مخزن قبلاً سرشکن شده است.")
        c.require_roles(session, company_id, (c.WIP, c.OVERHEAD_APPLIED))
        _code, _start, end = c_period_from_code(pool.period_code)
        date = date or min(end, datetime.date.today())
        shares = _shares(pool, _bases_for(session, company_id, pool, manual))
        bases = _bases_for(session, company_id, pool, manual)
        out = []
        for order_id, amount in shares.items():
            order = po.lock_order(session, company_id, order_id)
            if order.status_code in ("CLOSED", "CANCELLED", "DRAFT", "PLANNED"):
                raise ValueError(f"دستور {order.order_code} باز نیست و سربار نمی‌پذیرد.")
            txn = _conversion_txn(session, order, "OVERHEAD", c.OVERHEAD_APPLIED, amount, date, user_id,
                                  f"pool:{pool_id}:{order_id}", None, details={"pool_id": pool_id, "basis": pool.basis})
            session.add(CostAllocationRow(pool_id=pool_id, order_id=order_id, basis_value=bases.get(order_id, ZERO), amount=amount,
                                          txn_id=txn.txn_id))
            out.append(SimpleNamespace(order_id=order_id, order_code=order.order_code, amount=amount))
        pool.allocated_amount = decimal.Decimal(pool.allocated_amount) + sum((x.amount for x in out), ZERO)
        pool.status_code = "ALLOCATED"
        c.audit(session, company_id, user_id, "CostPool", pool_id, "ALLOCATE",
                {"orders": len(out), "amount": str(pool.allocated_amount), "basis": pool.basis})
        session.commit()
        return out


# =====================================================================================
# بهایِ واقعی / استاندارد / انحراف
# =====================================================================================
def _sum(session, order_id: int, types: tuple, col=OrderTransaction.amount, where=None) -> decimal.Decimal:
    q = select(func.coalesce(func.sum(col), 0)).where(OrderTransaction.order_id == order_id, OrderTransaction.txn_type.in_(types))
    if where is not None:
        q = q.where(where)
    return decimal.Decimal(session.scalar(q) or 0)


def order_costs(session, order: ProductionOrder) -> SimpleNamespace:
    """بهای واقعی و استاندارد دستور (برای مقدار تولید سالم) به تفکیک عنصر."""
    oid = order.order_id
    produced = decimal.Decimal(order.produced_qty)
    planned = decimal.Decimal(order.planned_qty)
    ratio = produced / planned if planned else ZERO
    material = _sum(session, oid, ("ISSUE",)) - _sum(session, oid, ("RETURN",))
    labor, machine, overhead = (_sum(session, oid, (t,)) for t in ("LABOR", "MACHINE", "OVERHEAD"))
    by_credit = _sum(session, oid, ("BY_PRODUCT",)) - _sum(session, oid, ("REVERSAL",), where=OrderTransaction.details["of"].astext == "BY_PRODUCT")
    scrap_recovery = _sum(session, oid, ("SCRAP",))
    abnormal = _sum(session, oid, ("VARIANCE",), where=OrderTransaction.reason == "ABNORMAL_SCRAP")
    residual = _sum(session, oid, ("VARIANCE",), where=OrderTransaction.reason == "CLOSE_RESIDUAL")
    co_amount = sum((decimal.Decimal(o.produced_amount) for o in session.scalars(select(OrderOutput).where(
        OrderOutput.order_id == oid, OrderOutput.output_type == "CO_PRODUCT"))), ZERO)
    gross = material + labor + machine + overhead
    net = gross - by_credit - scrap_recovery - abnormal
    main_amount = decimal.Decimal(session.scalar(select(func.coalesce(func.sum(OrderOutput.produced_amount), 0)).where(
        OrderOutput.order_id == oid, OrderOutput.output_type == "MAIN")) or 0)
    # استاندارد برایِ مقدارِ تولیدِ سالم
    mats = list(session.scalars(select(OrderMaterial).where(OrderMaterial.order_id == oid)))
    material_std = sum((pm.line_requirement(m.quantity_per_base, m.quantity_type, m.scrap_percent, produced, m.batch_size_qty)[1]
                        * decimal.Decimal(m.standard_unit_cost or 0) for m in mats if not m.is_optional), ZERO)
    ops = list(session.scalars(select(OrderOperation).where(OrderOperation.order_id == oid)))
    basis = c.settings(session, order.company_id).default_overhead_basis
    labor_std = sum((decimal.Decimal(o.std_labor_hours) * ratio * decimal.Decimal(o.labor_rate) for o in ops), ZERO)
    machine_std = sum((decimal.Decimal(o.std_machine_hours) * ratio * decimal.Decimal(o.machine_rate) for o in ops), ZERO)
    overhead_std = sum(((decimal.Decimal(o.std_machine_hours) if basis == "MACHINE_HOURS" else decimal.Decimal(o.std_labor_hours))
                        * ratio * decimal.Decimal(o.overhead_rate) for o in ops), ZERO)
    by_std = sum((decimal.Decimal(o.planned_qty) * ratio * decimal.Decimal(o.recovery_value_per_unit or 0)
                  for o in session.scalars(select(OrderOutput).where(OrderOutput.order_id == oid, OrderOutput.output_type == "BY_PRODUCT"))),
                 ZERO)
    std_total = material_std + labor_std + machine_std + overhead_std - by_std
    std_unit = decimal.Decimal(order.standard_unit_cost or 0)
    to_main = net - co_amount
    actual_unit = c.qty(to_main / produced) if produced else ZERO
    return SimpleNamespace(
        material=c.money(material), labor=c.money(labor), machine=c.money(machine), overhead=c.money(overhead),
        gross=c.money(gross), byproduct_credit=c.money(by_credit), scrap_recovery=c.money(scrap_recovery),
        abnormal_scrap=c.money(abnormal), co_product_amount=c.money(co_amount), total=c.money(net),
        received_main=c.money(main_amount), close_residual=c.money(residual), actual_unit_cost=actual_unit,
        material_std=c.money(material_std), labor_std=c.money(labor_std), machine_std=c.money(machine_std),
        overhead_std=c.money(overhead_std), byproduct_std=c.money(by_std), std_total=c.money(std_total),
        standard_unit_cost=std_unit, standard_total=c.money(std_unit * produced),
        variance=c.money(to_main - std_unit * produced) if produced else ZERO, produced=produced)


def variance_analysis(session, order: ProductionOrder) -> list[SimpleNamespace]:
    oid = order.order_id
    costs = order_costs(session, order)
    produced = costs.produced
    rows: list[tuple[str, decimal.Decimal, decimal.Decimal | None]] = []
    price = usage = ZERO
    for m in session.scalars(select(OrderMaterial).where(OrderMaterial.order_id == oid)):
        std_unit = decimal.Decimal(m.standard_unit_cost or 0)
        std_qty = ZERO if m.is_optional else pm.line_requirement(m.quantity_per_base, m.quantity_type, m.scrap_percent, produced,
                                                                  m.batch_size_qty)[1]
        price += m.consumed_amount - m.consumed_qty * std_unit
        usage += (m.consumed_qty - std_qty) * std_unit
    rows += [("MATERIAL_PRICE", price, None), ("MATERIAL_USAGE", usage, None)]
    ops = list(session.scalars(select(OrderOperation).where(OrderOperation.order_id == oid)))
    ratio = produced / decimal.Decimal(order.planned_qty)
    for kind, actual_amount, hours_col, rate_col, entry in (
            ("LABOR", costs.labor, "std_labor_hours", "labor_rate", LaborEntry),
            ("MACHINE", costs.machine, "std_machine_hours", "machine_rate", MachineEntry)):
        std_hours = sum((decimal.Decimal(getattr(o, hours_col)) * ratio for o in ops), ZERO)
        std_amount = sum((decimal.Decimal(getattr(o, hours_col)) * ratio * decimal.Decimal(getattr(o, rate_col)) for o in ops), ZERO)
        std_rate = std_amount / std_hours if std_hours else ZERO
        hours_expr = (LaborEntry.hours + LaborEntry.overtime_hours) if entry is LaborEntry else MachineEntry.hours
        actual_hours = decimal.Decimal(session.scalar(select(func.coalesce(func.sum(hours_expr), 0)).where(entry.order_id == oid)) or 0)
        if not std_hours and actual_amount:
            rows += [(f"{kind}_RATE", actual_amount, actual_hours), (f"{kind}_EFFICIENCY", ZERO, ZERO)]
            continue
        rows += [(f"{kind}_RATE", actual_amount - actual_hours * std_rate, actual_hours),
                 (f"{kind}_EFFICIENCY", (actual_hours - std_hours) * std_rate, actual_hours - std_hours)]
    rows.append(("OVERHEAD", costs.overhead - costs.overhead_std, None))
    std_unit = costs.standard_unit_cost
    rows.append(("PRODUCTION_QUANTITY", (produced - decimal.Decimal(order.planned_qty)) * std_unit,
                 produced - decimal.Decimal(order.planned_qty)))
    po = _orders()
    allowed = po.normal_scrap_percent(session, order) * decimal.Decimal(order.planned_qty) / _HUNDRED
    extra_scrap = max(ZERO, decimal.Decimal(order.scrapped_qty) - allowed)
    rows.append(("SCRAP", extra_scrap * std_unit, decimal.Decimal(order.scrapped_qty)))
    rows.append(("TOTAL", costs.variance, None))
    return [SimpleNamespace(code=k, label=VARIANCE_LABELS[k], amount=c.money(v), quantity=q) for k, v, q in rows]


def get_order_costs(company_id: int, order_id: int) -> SimpleNamespace:
    with new_session() as session:
        order = session.get(ProductionOrder, order_id)
        if order is None or order.company_id != company_id:
            raise ValueError("دستور تولید نامعتبر است.")
        return order_costs(session, order)


def get_variances(company_id: int, order_id: int) -> list[SimpleNamespace]:
    with new_session() as session:
        order = session.get(ProductionOrder, order_id)
        if order is None or order.company_id != company_id:
            raise ValueError("دستور تولید نامعتبر است.")
        return variance_analysis(session, order)


def store_summary(session, order: ProductionOrder) -> SimpleNamespace:
    """خلاصهٔ بها و انحراف‌ها هنگام بستن (برای گزارش‌ها و بستن دوره)."""
    costs = order_costs(session, order)
    row = session.get(OrderCostSummary, order.order_id) or OrderCostSummary(order_id=order.order_id)
    row.computed_at, row.produced_qty = datetime.datetime.now(), order.produced_qty
    for a, b in (("material_std", "material_std"), ("material_actual", "material"), ("labor_std", "labor_std"), ("labor_actual", "labor"),
                 ("machine_std", "machine_std"), ("machine_actual", "machine"), ("overhead_std", "overhead_std"),
                 ("overhead_actual", "overhead"), ("byproduct_credit", "byproduct_credit"), ("scrap_recovery", "scrap_recovery"),
                 ("total_std", "standard_total"), ("total_actual", "total")):
        setattr(row, a, getattr(costs, b))
    row.std_unit_cost, row.actual_unit_cost = costs.standard_unit_cost, costs.actual_unit_cost
    session.merge(row)
    session.query(OrderVariance).filter(OrderVariance.order_id == order.order_id).delete()
    for v in variance_analysis(session, order):
        session.add(OrderVariance(order_id=order.order_id, variance_code=v.code, amount=v.amount, quantity=v.quantity))
    session.flush()
    return costs


# =====================================================================================
# بهایِ استاندارد (Roll-up چندسطحی)
# =====================================================================================
def _component_cost(session, company_id: int, item_id: int, date: datetime.date, cache: dict, depth: int) -> decimal.Decimal:
    po = _orders()
    prof = session.get(ItemProductionProfile, item_id)
    bom_id = pm.effective_bom_id(session, item_id, date)
    if bom_id is not None and (prof is None or prof.make_or_buy == "MAKE") and depth < 10:
        return _rollup(session, company_id, item_id, date, cache, depth + 1).total
    std = po._standard_unit_cost(session, item_id, date)
    return std if std is not None else po._cost_estimate(session, item_id, None, date)


def _rollup(session, company_id: int, item_id: int, date: datetime.date, cache: dict, depth: int = 0) -> SimpleNamespace:
    if item_id in cache:
        return cache[item_id]
    bom_id = pm.effective_bom_id(session, item_id, date)
    if bom_id is None:
        raise ValueError(f"برای «{c.item_label(session, item_id)}» فهرست مواد معتبری وجود ندارد.")
    bom = session.get(BomHeader, bom_id)
    batch = decimal.Decimal(bom.batch_size_qty)
    material, details = ZERO, []
    for ln in session.scalars(select(BomLine).where(BomLine.bom_id == bom_id).order_by(BomLine.line_no)):
        if ln.is_optional:
            continue
        base = decimal.Decimal(ln.quantity_per) * decimal.Decimal(ln.conversion_factor or 1)
        scrap = decimal.Decimal(ln.scrap_percent or 0) or decimal.Decimal(bom.scrap_percent or 0)
        _n, gross = pm.line_requirement(base, ln.quantity_type or "VARIABLE", scrap, batch, batch)
        per_unit = gross / batch
        unit_cost = _component_cost(session, company_id, ln.component_item_id, date, cache, depth)
        material += per_unit * unit_cost
        details.append({"item_id": ln.component_item_id, "qty_per_unit": str(c.qty(per_unit)), "unit_cost": str(c.qty(unit_cost))})
    labor = machine = overhead = ZERO
    routing_id = bom.routing_id or pm.default_routing_id(session, item_id)
    basis = c.settings(session, company_id).default_overhead_basis
    if routing_id:
        for op in session.scalars(select(RoutingOperation).where(RoutingOperation.routing_id == routing_id)):
            wc = session.get(WorkCenter, op.work_center_id) if op.work_center_id else None
            h = pm.op_hours(op, batch)
            lr = decimal.Decimal(op.labor_rate if op.labor_rate is not None else (wc.labor_rate if wc else 0))
            mr = decimal.Decimal(op.machine_rate if op.machine_rate is not None else (wc.machine_rate if wc else 0))
            orate = decimal.Decimal(op.overhead_rate if op.overhead_rate is not None else (wc.overhead_rate if wc else 0))
            labor += h.labor_hours * lr / batch
            machine += h.machine_hours * mr / batch
            overhead += (h.machine_hours if basis == "MACHINE_HOURS" else h.labor_hours) * orate / batch
    by_credit = sum((decimal.Decimal(o.quantity_per) / batch * decimal.Decimal(o.recovery_value_per_unit or 0)
                     for o in session.scalars(select(BomOutput).where(BomOutput.bom_id == bom_id, BomOutput.output_type == "BY_PRODUCT"))),
                    ZERO)
    total = material + labor + machine + overhead - by_credit
    result = SimpleNamespace(item_id=item_id, bom_id=bom_id, routing_id=routing_id, material=c.qty(material), labor=c.qty(labor),
                             machine=c.qty(machine), overhead=c.qty(overhead), byproduct_credit=c.qty(by_credit),
                             total=c.qty(total), details=details, level=depth)
    cache[item_id] = result
    return result


def rollup_standard_cost(company_id: int, item_id: int, date: datetime.date | None = None, write: bool = False,
                         user_id: int | None = None) -> list[SimpleNamespace]:
    """بهای استاندارد چندسطحی (مواد + دستمزد + ماشین + سربار − جانبی). با write=True کارت ثبت و جمع در
    inv.standard_costs (همان جدول بهای استاندارد موتور انبار) نوشته می‌شود — برای محصول و نیمه‌ساخته‌هایش."""
    date = date or datetime.date.today()
    with new_session() as session:
        c.item_of(session, company_id, item_id)
        cache: dict = {}
        _rollup(session, company_id, item_id, date, cache)
        results = sorted(cache.values(), key=lambda r: -r.level)
        if write:
            for r in results:
                session.add(StandardCostCard(company_id=company_id, item_id=r.item_id, effective_date=date, bom_id=r.bom_id,
                                             routing_id=r.routing_id, material_cost=r.material, labor_cost=r.labor,
                                             machine_cost=r.machine, overhead_cost=r.overhead, byproduct_credit=r.byproduct_credit,
                                             total_cost=r.total, details={"components": r.details}, created_by_user_id=user_id))
                existing = session.get(StandardCost, (r.item_id, date))
                old = str(existing.standard_unit_cost) if existing else None
                if existing is None:
                    session.add(StandardCost(item_id=r.item_id, effective_date=date, standard_unit_cost=r.total))
                else:
                    existing.standard_unit_cost = r.total
                c.audit(session, company_id, user_id, "StandardCost", r.item_id, "COST_UPDATE",
                        {"standard_unit_cost": [old, str(r.total)], "date": date.isoformat()})
            session.commit()
        labels = c.item_labels(session, [r.item_id for r in results])
        for r in results:
            r.item_label = labels.get(r.item_id, "")
        return results


def standard_cost_cards(company_id: int, item_id: int | None = None) -> list[StandardCostCard]:
    with new_session() as session:
        q = select(StandardCostCard).where(StandardCostCard.company_id == company_id)
        if item_id:
            q = q.where(StandardCostCard.item_id == item_id)
        rows = list(session.scalars(q.order_by(StandardCostCard.card_id.desc())))
        for r in rows:
            session.expunge(r)
        return rows


# =====================================================================================
# بستنِ دوره‌ایِ بها
# =====================================================================================
def period_preview(company_id: int, period_code: str) -> SimpleNamespace:
    code, start, end = c_period_from_code(period_code)
    with new_session() as session:
        return _period_numbers(session, company_id, code, start, end)


def _period_numbers(session, company_id: int, code: str, start: datetime.date, end: datetime.date) -> SimpleNamespace:
    def total(types, where=None):
        q = select(func.coalesce(func.sum(OrderTransaction.amount), 0)).where(
            OrderTransaction.company_id == company_id, OrderTransaction.txn_type.in_(types),
            OrderTransaction.txn_date.between(start, end))
        if where is not None:
            q = q.where(where)
        return decimal.Decimal(session.scalar(q) or 0)

    order_ids = set(session.scalars(select(OrderTransaction.order_id).where(
        OrderTransaction.company_id == company_id, OrderTransaction.txn_date.between(start, end)).distinct()))
    wip = decimal.Decimal(session.scalar(select(func.coalesce(func.sum(OrderTransaction.wip_delta), 0)).where(
        OrderTransaction.company_id == company_id, OrderTransaction.txn_date <= end)) or 0)
    pools = list(session.scalars(select(CostPool).where(CostPool.company_id == company_id, CostPool.period_code == code)))
    open_pools = [p.code for p in pools if p.status_code != "ALLOCATED" and p.amount]
    unclosed = list(session.scalars(select(ProductionOrder.order_code).where(
        ProductionOrder.company_id == company_id, ProductionOrder.status_code == "COMPLETED",
        ProductionOrder.actual_end_date.between(start, end))))
    in_progress = list(session.scalars(select(ProductionOrder.order_code).where(
        ProductionOrder.order_id.in_(order_ids or {-1}), ProductionOrder.status_code.in_(("RELEASED", "IN_PROGRESS", "ON_HOLD")))))
    st = c.settings(session, company_id)
    blockers = [f"مخزن سرشکن‌نشده: {', '.join(open_pools)}"] if open_pools else []
    if st.require_cost_closing and unclosed:
        blockers.append(f"دستورهای تکمیل‌شدهٔ بسته‌نشده: {', '.join(unclosed)}")
    return SimpleNamespace(
        period_code=code, period_start=start, period_end=end, orders_count=len(order_ids), wip_balance=c.money(wip),
        material_total=c.money(total(("ISSUE",)) - total(("RETURN",))), labor_total=c.money(total(("LABOR",))),
        machine_total=c.money(total(("MACHINE",))), overhead_applied=c.money(total(("OVERHEAD",))),
        overhead_pools=c.money(sum((decimal.Decimal(p.amount) for p in pools), ZERO)),
        output_total=c.money(total(("RECEIPT", "CO_PRODUCT", "BY_PRODUCT"))),
        variance_total=c.money(total(("VARIANCE",))), in_progress=in_progress, unclosed=unclosed, open_pools=open_pools,
        blockers=blockers)


def close_period(company_id: int, user_id: int, period_code: str) -> int:
    """بستن دوره: ارقام کالای در جریان ساخت/بهای واقعی/سربار/انحراف نهایی و ثبت تولید در آن دوره قفل می‌شود."""
    code, start, end = c_period_from_code(period_code)
    with new_session() as session:
        session.execute(select(CostClosing.closing_id).where(CostClosing.company_id == company_id).with_for_update()).all()
        if period_is_closed(session, company_id, start):
            raise ValueError(f"دورهٔ {code} قبلاً بسته شده است.")
        n = _period_numbers(session, company_id, code, start, end)
        if n.blockers:
            raise ValueError("بستن دوره ممکن نیست: " + " | ".join(n.blockers))
        for oid in session.scalars(select(ProductionOrder.order_id).where(
                ProductionOrder.company_id == company_id, ProductionOrder.status_code == "CLOSED",
                ProductionOrder.closed_at >= datetime.datetime.combine(start, datetime.time.min))):
            store_summary(session, session.get(ProductionOrder, oid))
        row = CostClosing(company_id=company_id, period_code=code, period_start=start, period_end=end, status_code="FINALIZED",
                          orders_count=n.orders_count, wip_balance=n.wip_balance, material_total=n.material_total,
                          labor_total=n.labor_total, machine_total=n.machine_total, overhead_applied=n.overhead_applied,
                          overhead_pools=n.overhead_pools, output_total=n.output_total, variance_total=n.variance_total,
                          details={"in_progress": n.in_progress}, finalized_by_user_id=user_id)
        session.add(row)
        session.flush()
        c.audit(session, company_id, user_id, "CostClosing", row.closing_id, "PERIOD_CLOSE",
                {"period": code, "wip": str(n.wip_balance), "variance": str(n.variance_total)})
        session.commit()
        return row.closing_id


def reopen_period(company_id: int, user_id: int, period_code: str, reason: str) -> None:
    if not (reason or "").strip():
        raise ValueError("دلیل بازگشایی الزامی است.")
    code, _s, _e = c_period_from_code(period_code)
    with new_session() as session:
        row = session.scalar(select(CostClosing).where(CostClosing.company_id == company_id, CostClosing.period_code == code,
                                                       CostClosing.status_code == "FINALIZED").with_for_update())
        if row is None:
            raise ValueError("این دوره بسته نیست.")
        row.status_code, row.reopened_by_user_id, row.reopened_at, row.reopen_reason = (
            "REOPENED", user_id, datetime.datetime.now(), reason)
        c.audit(session, company_id, user_id, "CostClosing", row.closing_id, "PERIOD_REOPEN", {"period": code, "reason": reason})
        session.commit()


def list_closings(company_id: int) -> list[CostClosing]:
    with new_session() as session:
        rows = list(session.scalars(select(CostClosing).where(CostClosing.company_id == company_id)
                                    .order_by(CostClosing.period_code.desc(), CostClosing.closing_id.desc())))
        for r in rows:
            session.expunge(r)
        return rows

