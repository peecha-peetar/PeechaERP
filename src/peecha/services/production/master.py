"""اطلاعات پایهٔ تولید — R266: فهرست مواد (نسخه‌دار، چندسطحی، جانبی/مشترک)، مسیر تولید، مرکز کاری، ماشین، دستمزد، عملیات.

فهرست مواد همان inv.bom_headers/bom_lines است. نسخه‌ای که در دستور تولید صادرشده استفاده شده قفل می‌شود و فقط با ساختن
نسخهٔ تازه تغییر می‌کند (ردیف‌های فهرست مواد هنگام صدور دستور هم روی خود دستور کپی می‌شوند)، پس سوابق قبلی ثابت می‌مانند.
"""

from __future__ import annotations

import datetime
import decimal
from dataclasses import dataclass
from types import SimpleNamespace

from sqlalchemy import func, or_, select

from peecha.db.base import new_session
from peecha.db.models.fixed_assets import Asset
from peecha.db.models.inventory import BomHeader, BomLine, Item
from peecha.db.models.production import (
    BomOutput, ItemProductionProfile, LaborRate, Operation, Routing, RoutingOperation, WorkCenter, WorkCenterMachine,
)
from peecha.services.production import common as c

ZERO, ONE = c.ZERO, c.ONE
_HUNDRED = decimal.Decimal(100)
_SIXTY = decimal.Decimal(60)


def _expunge(session, rows):
    for r in rows:
        session.expunge(r)
    return rows


# =====================================================================================
# مرکزِ کاری / ماشین / دستمزد / عملیات
# =====================================================================================
@dataclass
class WorkCenterFields:
    code: str
    name: str
    center_type: str = "LINE"
    branch_id: int | None = None
    warehouse_id: int | None = None
    cost_center_detail_account_id: int | None = None
    operator_count: int = 1
    shifts_per_day: int = 1
    hours_per_shift: decimal.Decimal = decimal.Decimal(8)
    working_days_per_week: int = 6
    hourly_capacity_qty: decimal.Decimal | None = None
    efficiency_percent: decimal.Decimal = _HUNDRED
    labor_rate: decimal.Decimal = ZERO
    machine_rate: decimal.Decimal = ZERO
    overhead_rate: decimal.Decimal = ZERO
    is_active: bool = True


def save_work_center(company_id: int, fields: WorkCenterFields, work_center_id: int | None = None,
                     user_id: int | None = None) -> int:
    if not fields.code.strip() or not fields.name.strip():
        raise ValueError("کد و نام مرکز کاری الزامی است.")
    if fields.center_type not in c.CENTER_TYPES:
        raise ValueError("نوع مرکز کاری نامعتبر است.")
    for label, v in (("نرخ دستمزد", fields.labor_rate), ("نرخ ماشین", fields.machine_rate), ("نرخ سربار", fields.overhead_rate)):
        if decimal.Decimal(v or 0) < 0:
            raise ValueError(f"{label} نمی‌تواند منفی باشد.")
    with new_session() as session:
        dup = session.scalar(select(WorkCenter.work_center_id).where(WorkCenter.company_id == company_id,
                                                                     WorkCenter.code == fields.code.strip()))
        if dup is not None and dup != work_center_id:
            raise ValueError("این کد مرکز کاری قبلاً تعریف شده است.")
        row = session.get(WorkCenter, work_center_id) if work_center_id else WorkCenter(company_id=company_id)
        if row is None or row.company_id != company_id:
            raise ValueError("مرکز کاری نامعتبر است.")
        before = {k: str(getattr(row, k, None)) for k in ("labor_rate", "machine_rate", "overhead_rate", "cost_center_detail_account_id")}
        for k, v in fields.__dict__.items():
            setattr(row, k, v.strip() if isinstance(v, str) else v)
        if work_center_id is None:
            session.add(row)
        session.flush()
        after = {k: str(getattr(row, k)) for k in before}
        c.audit(session, company_id, user_id, "WorkCenter", row.work_center_id, "CREATE" if work_center_id is None else "UPDATE",
                {k: [before[k], after[k]] for k in before if before[k] != after[k]})
        session.commit()
        return row.work_center_id


def list_work_centers(company_id: int, active_only: bool = False) -> list[WorkCenter]:
    with new_session() as session:
        q = select(WorkCenter).where(WorkCenter.company_id == company_id)
        if active_only:
            q = q.where(WorkCenter.is_active.is_(True))
        return _expunge(session, list(session.scalars(q.order_by(WorkCenter.code))))


def get_work_center(company_id: int, work_center_id: int) -> WorkCenter:
    with new_session() as session:
        row = session.get(WorkCenter, work_center_id)
        if row is None or row.company_id != company_id:
            raise ValueError("مرکز کاری نامعتبر است.")
        session.expunge(row)
        return row


def link_machine(company_id: int, work_center_id: int, asset_id: int, user_id: int | None = None) -> None:
    """ماشین = دارایی ثابت «ماشین تولیدی» (ماژول دارایی‌ها)."""
    with new_session() as session:
        wc = session.get(WorkCenter, work_center_id)
        asset = session.get(Asset, asset_id)
        if wc is None or wc.company_id != company_id or asset is None or asset.company_id != company_id:
            raise ValueError("مرکز کاری یا دارایی نامعتبر است.")
        if not asset.is_production_machine:
            raise ValueError("این دارایی در ماژول دارایی‌ها «ماشین تولیدی» تعریف نشده است.")
        if session.get(WorkCenterMachine, (work_center_id, asset_id)) is None:
            session.add(WorkCenterMachine(work_center_id=work_center_id, asset_id=asset_id))
            c.audit(session, company_id, user_id, "WorkCenter", work_center_id, "LINK_MACHINE", {"asset_id": asset_id})
        session.commit()


def unlink_machine(company_id: int, work_center_id: int, asset_id: int) -> None:
    with new_session() as session:
        row = session.get(WorkCenterMachine, (work_center_id, asset_id))
        wc = session.get(WorkCenter, work_center_id)
        if row is not None and wc is not None and wc.company_id == company_id:
            session.delete(row)
            session.commit()


def work_center_machines(company_id: int, work_center_id: int) -> list[SimpleNamespace]:
    """ماشین‌های لینک‌شده + دارایی‌هایی که «کد مرکز کار»شان در ماژول دارایی همین کد است."""
    with new_session() as session:
        wc = session.get(WorkCenter, work_center_id)
        if wc is None or wc.company_id != company_id:
            raise ValueError("مرکز کاری نامعتبر است.")
        linked = set(session.scalars(select(WorkCenterMachine.asset_id).where(WorkCenterMachine.work_center_id == work_center_id)))
        rows = session.scalars(select(Asset).where(Asset.company_id == company_id, Asset.is_production_machine.is_(True),
                                                   or_(Asset.asset_id.in_(linked or {-1}), Asset.work_center_code == wc.code)))
        return [SimpleNamespace(asset_id=a.asset_id, code=a.asset_code, name=a.name, machine_rate=a.machine_rate,
                                status_code=a.status_code, linked=a.asset_id in linked) for a in rows]


def capacity_hours(wc: WorkCenter, date_from: datetime.date, date_to: datetime.date) -> decimal.Decimal:
    """ظرفیت ساعتی مؤثر در بازه = روزهای کاری × شیفت × ساعت شیفت × راندمان."""
    days = (date_to - date_from).days + 1
    if days <= 0:
        return ZERO
    working = sum(1 for i in range(days) if ((date_from + datetime.timedelta(days=i)).weekday() + 2) % 7 < wc.working_days_per_week)
    return (decimal.Decimal(working) * wc.daily_hours * decimal.Decimal(wc.efficiency_percent) / _HUNDRED).quantize(
        decimal.Decimal("0.01"))


def save_labor_rate(company_id: int, code: str, name: str, hourly_rate, employee_id: int | None = None,
                    overtime_multiplier=decimal.Decimal("1.4"), labor_rate_id: int | None = None, is_active: bool = True,
                    user_id: int | None = None) -> int:
    hourly_rate = decimal.Decimal(hourly_rate)
    if not code.strip() or not name.strip() or hourly_rate < 0:
        raise ValueError("کد، نام و نرخ معتبر الزامی است.")
    with new_session() as session:
        dup = session.scalar(select(LaborRate.labor_rate_id).where(LaborRate.company_id == company_id, LaborRate.code == code.strip()))
        if dup is not None and dup != labor_rate_id:
            raise ValueError("این کد نرخ دستمزد قبلاً تعریف شده است.")
        row = session.get(LaborRate, labor_rate_id) if labor_rate_id else LaborRate(company_id=company_id)
        old = str(row.hourly_rate) if labor_rate_id else None
        row.code, row.name, row.employee_id, row.hourly_rate = code.strip(), name.strip(), employee_id, hourly_rate
        row.overtime_multiplier, row.is_active = decimal.Decimal(overtime_multiplier), is_active
        if labor_rate_id is None:
            session.add(row)
        session.flush()
        c.audit(session, company_id, user_id, "LaborRate", row.labor_rate_id, "CREATE" if labor_rate_id is None else "UPDATE",
                {"hourly_rate": [old, str(hourly_rate)]})
        session.commit()
        return row.labor_rate_id


def list_labor_rates(company_id: int) -> list[LaborRate]:
    with new_session() as session:
        return _expunge(session, list(session.scalars(select(LaborRate).where(LaborRate.company_id == company_id)
                                                      .order_by(LaborRate.code))))


def labor_rate_for(session, company_id: int, employee_id: int | None, work_center_id: int | None,
                   fallback: decimal.Decimal | None = None) -> tuple[decimal.Decimal, decimal.Decimal]:
    """(نرخ ساعتی، ضریب اضافه‌کار): نرخ کارمند ← نرخ عملیات/مسیر ← نرخ مرکز کاری."""
    if employee_id is not None:
        row = session.scalar(select(LaborRate).where(LaborRate.company_id == company_id, LaborRate.employee_id == employee_id,
                                                     LaborRate.is_active.is_(True)))
        if row is not None:
            return decimal.Decimal(row.hourly_rate), decimal.Decimal(row.overtime_multiplier)
    if fallback:
        return decimal.Decimal(fallback), decimal.Decimal("1.4")
    if work_center_id is not None:
        wc = session.get(WorkCenter, work_center_id)
        if wc is not None:
            return decimal.Decimal(wc.labor_rate), decimal.Decimal("1.4")
    return ZERO, decimal.Decimal("1.4")


def save_operation(company_id: int, code: str, name: str, default_work_center_id: int | None = None,
                   default_setup_minutes=ZERO, default_run_minutes=ZERO, is_qc: bool = False,
                   operation_id: int | None = None) -> int:
    if not code.strip() or not name.strip():
        raise ValueError("کد و نام عملیات الزامی است.")
    with new_session() as session:
        dup = session.scalar(select(Operation.operation_id).where(Operation.company_id == company_id, Operation.code == code.strip()))
        if dup is not None and dup != operation_id:
            raise ValueError("این کد عملیات قبلاً تعریف شده است.")
        row = session.get(Operation, operation_id) if operation_id else Operation(company_id=company_id, is_active=True)
        row.code, row.name, row.default_work_center_id = code.strip(), name.strip(), default_work_center_id
        row.default_setup_minutes, row.default_run_minutes, row.is_qc = (decimal.Decimal(default_setup_minutes),
                                                                         decimal.Decimal(default_run_minutes), is_qc)
        if operation_id is None:
            session.add(row)
        session.commit()
        return row.operation_id


def list_operations(company_id: int) -> list[Operation]:
    with new_session() as session:
        return _expunge(session, list(session.scalars(select(Operation).where(Operation.company_id == company_id)
                                                      .order_by(Operation.code))))


# =====================================================================================
# مشخصاتِ تولیدیِ کالا
# =====================================================================================
PROFILE_FIELDS = ("make_or_buy", "production_uom_id", "consumption_uom_id", "min_lot_qty", "max_lot_qty", "lot_multiple_qty",
                  "lead_time_days", "standard_scrap_percent", "weight_per_unit", "backflush")


def save_item_profile(company_id: int, item_id: int, user_id: int | None = None, **fields) -> None:
    with new_session() as session:
        c.item_of(session, company_id, item_id)
        row = session.get(ItemProductionProfile, item_id)
        if row is None:
            row = ItemProductionProfile(item_id=item_id, company_id=company_id, make_or_buy="MAKE", lead_time_days=0,
                                        standard_scrap_percent=ZERO)
            session.add(row)
        changes = {}
        for k, v in fields.items():
            if k not in PROFILE_FIELDS:
                raise ValueError(f"فیلد نامعتبر: {k}")
            if k == "make_or_buy" and v not in ("MAKE", "BUY"):
                raise ValueError("نوع تامین باید «ساخت» یا «خرید» باشد.")
            if getattr(row, k, None) != v:
                changes[k] = [str(getattr(row, k, None)), str(v)]
                setattr(row, k, v)
        if row.min_lot_qty and row.max_lot_qty and row.max_lot_qty < row.min_lot_qty:
            raise ValueError("حداکثر تولید از حداقل کمتر است.")
        session.flush()
        if changes:
            c.audit(session, company_id, user_id, "ItemProductionProfile", item_id, "UPDATE", changes)
        session.commit()


def item_profile(session, item_id: int) -> ItemProductionProfile | None:
    return session.get(ItemProductionProfile, item_id)


def get_item_profile(company_id: int, item_id: int) -> SimpleNamespace:
    with new_session() as session:
        c.item_of(session, company_id, item_id)
        row = session.get(ItemProductionProfile, item_id)
        values = {k: getattr(row, k) if row else None for k in PROFILE_FIELDS}
        values["make_or_buy"] = values["make_or_buy"] or "MAKE"
        values["lead_time_days"] = values["lead_time_days"] or 0
        values["standard_scrap_percent"] = values["standard_scrap_percent"] or ZERO
        return SimpleNamespace(item_id=item_id, **values)


def check_lot_size(session, item_id: int, quantity: decimal.Decimal) -> None:
    prof = session.get(ItemProductionProfile, item_id)
    if prof is None:
        return
    if prof.min_lot_qty and quantity < prof.min_lot_qty:
        raise ValueError(f"مقدار تولید از حداقل تعریف‌شده ({prof.min_lot_qty.normalize()}) کمتر است.")
    if prof.max_lot_qty and quantity > prof.max_lot_qty:
        raise ValueError(f"مقدار تولید از حداکثر تعریف‌شده ({prof.max_lot_qty.normalize()}) بیشتر است.")


# =====================================================================================
# مسیرِ تولید
# =====================================================================================
@dataclass
class RoutingOpFields:
    seq: int
    name: str
    work_center_id: int | None = None
    operation_id: int | None = None
    asset_id: int | None = None
    labor_count: decimal.Decimal = ONE
    setup_minutes: decimal.Decimal = ZERO
    run_minutes: decimal.Decimal = ZERO
    queue_minutes: decimal.Decimal = ZERO
    move_minutes: decimal.Decimal = ZERO
    machine_minutes: decimal.Decimal | None = None
    labor_rate: decimal.Decimal | None = None
    machine_rate: decimal.Decimal | None = None
    overhead_rate: decimal.Decimal | None = None
    scrap_percent: decimal.Decimal = ZERO
    is_qc: bool = False
    description: str | None = None


def create_routing(company_id: int, item_id: int, name: str | None = None, operations: list[RoutingOpFields] | None = None,
                   copy_from_routing_id: int | None = None, make_default: bool | None = None,
                   user_id: int | None = None) -> int:
    with new_session() as session:
        c.item_of(session, company_id, item_id)
        version = (session.scalar(select(func.max(Routing.version_no)).where(Routing.item_id == item_id)) or 0) + 1
        has_default = session.scalar(select(Routing.routing_id).where(Routing.item_id == item_id, Routing.is_default.is_(True)))
        row = Routing(company_id=company_id, item_id=item_id, version_no=version, name=name, status_code="ACTIVE",
                      is_default=False)
        session.add(row)
        session.flush()
        if copy_from_routing_id:
            src = session.get(Routing, copy_from_routing_id)
            if src is None or src.company_id != company_id:
                raise ValueError("مسیر مبدأ نامعتبر است.")
            for op in session.scalars(select(RoutingOperation).where(RoutingOperation.routing_id == copy_from_routing_id)):
                data = {k: getattr(op, k) for k in RoutingOpFields.__dataclass_fields__}
                session.add(RoutingOperation(routing_id=row.routing_id, **data))
        for op in operations or []:
            _add_op(session, company_id, row.routing_id, op)
        if make_default or (make_default is None and has_default is None):
            _set_default_routing(session, row)
        c.audit(session, company_id, user_id, "Routing", row.routing_id, "CREATE", {"item_id": item_id, "version": version})
        session.commit()
        return row.routing_id


def _set_default_routing(session, row: Routing) -> None:
    for other in session.scalars(select(Routing).where(Routing.item_id == row.item_id, Routing.is_default.is_(True))):
        other.is_default = False
    session.flush()
    row.is_default = True
    session.flush()


def set_default_routing(company_id: int, routing_id: int) -> None:
    with new_session() as session:
        row = session.get(Routing, routing_id)
        if row is None or row.company_id != company_id:
            raise ValueError("مسیر تولید نامعتبر است.")
        _set_default_routing(session, row)
        session.commit()


def _add_op(session, company_id: int, routing_id: int, op: RoutingOpFields) -> RoutingOperation:
    if op.seq <= 0 or not op.name.strip():
        raise ValueError("ترتیب و نام عملیات الزامی است.")
    if session.scalar(select(RoutingOperation.routing_operation_id).where(RoutingOperation.routing_id == routing_id,
                                                                          RoutingOperation.seq == op.seq)):
        raise ValueError(f"ترتیب {op.seq} در این مسیر تکراری است.")
    if op.work_center_id is not None:
        wc = session.get(WorkCenter, op.work_center_id)
        if wc is None or wc.company_id != company_id:
            raise ValueError("مرکز کاری نامعتبر است.")
    for v in (op.setup_minutes, op.run_minutes, op.queue_minutes, op.move_minutes):
        if decimal.Decimal(v or 0) < 0:
            raise ValueError("زمان‌ها نمی‌توانند منفی باشند.")
    row = RoutingOperation(routing_id=routing_id, **{k: (v.strip() if isinstance(v, str) else v) for k, v in op.__dict__.items()})
    session.add(row)
    session.flush()
    return row


def add_routing_operation(company_id: int, routing_id: int, op: RoutingOpFields, user_id: int | None = None) -> int:
    with new_session() as session:
        routing = session.get(Routing, routing_id)
        if routing is None or routing.company_id != company_id:
            raise ValueError("مسیر تولید نامعتبر است.")
        row = _add_op(session, company_id, routing_id, op)
        c.audit(session, company_id, user_id, "Routing", routing_id, "ADD_OPERATION", {"seq": op.seq, "name": op.name})
        session.commit()
        return row.routing_operation_id


def update_routing_operation(company_id: int, routing_operation_id: int, op: RoutingOpFields, user_id: int | None = None) -> None:
    with new_session() as session:
        row = session.get(RoutingOperation, routing_operation_id)
        routing = session.get(Routing, row.routing_id) if row else None
        if routing is None or routing.company_id != company_id:
            raise ValueError("عملیات مسیر نامعتبر است.")
        dup = session.scalar(select(RoutingOperation.routing_operation_id).where(
            RoutingOperation.routing_id == row.routing_id, RoutingOperation.seq == op.seq))
        if dup is not None and dup != routing_operation_id:
            raise ValueError(f"ترتیب {op.seq} در این مسیر تکراری است.")
        before = {k: str(getattr(row, k)) for k in op.__dict__}
        for k, v in op.__dict__.items():
            setattr(row, k, v)
        c.audit(session, company_id, user_id, "Routing", routing.routing_id, "UPDATE_OPERATION",
                {k: [before[k], str(v)] for k, v in op.__dict__.items() if before[k] != str(v)})
        session.commit()


def remove_routing_operation(company_id: int, routing_operation_id: int, user_id: int | None = None) -> None:
    with new_session() as session:
        row = session.get(RoutingOperation, routing_operation_id)
        routing = session.get(Routing, row.routing_id) if row else None
        if routing is None or routing.company_id != company_id:
            raise ValueError("عملیات مسیر نامعتبر است.")
        c.audit(session, company_id, user_id, "Routing", routing.routing_id, "REMOVE_OPERATION", {"seq": row.seq, "name": row.name})
        session.delete(row)
        session.commit()


def list_routings(company_id: int, item_id: int | None = None) -> list[Routing]:
    with new_session() as session:
        q = select(Routing).where(Routing.company_id == company_id)
        if item_id:
            q = q.where(Routing.item_id == item_id)
        return _expunge(session, list(session.scalars(q.order_by(Routing.item_id, Routing.version_no))))


def routing_operations(company_id: int, routing_id: int) -> list[RoutingOperation]:
    with new_session() as session:
        routing = session.get(Routing, routing_id)
        if routing is None or routing.company_id != company_id:
            raise ValueError("مسیر تولید نامعتبر است.")
        return _expunge(session, list(session.scalars(select(RoutingOperation).where(RoutingOperation.routing_id == routing_id)
                                                      .order_by(RoutingOperation.seq))))


def default_routing_id(session, item_id: int) -> int | None:
    return session.scalar(select(Routing.routing_id).where(Routing.item_id == item_id, Routing.is_default.is_(True),
                                                           Routing.status_code == "ACTIVE"))


def op_hours(op, quantity: decimal.Decimal) -> SimpleNamespace:
    """ساعت استاندارد یک عملیات برای یک مقدار: آماده‌سازی + اجرا × مقدار (و ساعت ماشین)."""
    quantity = decimal.Decimal(quantity)
    run = decimal.Decimal(op.run_minutes or 0) * quantity
    setup = decimal.Decimal(op.setup_minutes or 0)
    machine_minutes = decimal.Decimal(op.machine_minutes) * quantity if op.machine_minutes is not None else (
        run + setup if op.asset_id or (op.machine_rate or 0) else ZERO)
    labor_hours = (setup + run) / _SIXTY * decimal.Decimal(op.labor_count or 0)
    elapsed = (setup + run + decimal.Decimal(op.queue_minutes or 0) + decimal.Decimal(op.move_minutes or 0)) / _SIXTY
    return SimpleNamespace(labor_hours=labor_hours.quantize(decimal.Decimal("0.0001")),
                           machine_hours=(machine_minutes / _SIXTY).quantize(decimal.Decimal("0.0001")),
                           elapsed_hours=elapsed.quantize(decimal.Decimal("0.0001")))


# =====================================================================================
# BOM
# =====================================================================================
@dataclass
class BomFields:
    batch_size_qty: decimal.Decimal = ONE
    scrap_percent: decimal.Decimal = ZERO
    name: str | None = None
    valid_from: datetime.date | None = None
    valid_to: datetime.date | None = None
    routing_id: int | None = None
    production_time_minutes: int | None = None
    notes: str | None = None
    status_code: str = "ACTIVE"


@dataclass
class BomLineFields:
    component_item_id: int
    quantity: decimal.Decimal
    uom_id: int | None = None
    scrap_percent: decimal.Decimal = ZERO
    quantity_type: str = "VARIABLE"
    component_type: str = "MATERIAL"
    warehouse_id: int | None = None
    operation_seq: int | None = None
    substitute_item_id: int | None = None
    is_optional: bool = False
    notes: str | None = None


@dataclass
class BomOutputFields:
    item_id: int
    output_type: str
    quantity_per: decimal.Decimal
    recovery_value_per_unit: decimal.Decimal | None = None
    sales_value_per_unit: decimal.Decimal | None = None
    weight_per_unit: decimal.Decimal | None = None
    cost_share_percent: decimal.Decimal | None = None


def _bom_company(session, bom: BomHeader) -> int:
    return session.scalar(select(Item.company_id).where(Item.item_id == bom.finished_item_id))


def _get_bom(session, company_id: int, bom_id: int, for_edit: bool = False) -> BomHeader:
    bom = session.get(BomHeader, bom_id)
    if bom is None or _bom_company(session, bom) != company_id:
        raise ValueError("فهرست مواد (BOM) نامعتبر است.")
    if for_edit and bom.is_locked:
        raise ValueError(f"نسخهٔ {bom.version_no} این فهرست مواد در دستور تولید استفاده شده و قفل است — برای تغییر، نسخهٔ تازه بسازید.")
    return bom


def _validate_bom_fields(fields: BomFields) -> None:
    if decimal.Decimal(fields.batch_size_qty) <= 0:
        raise ValueError("مقدار تولید فهرست مواد باید بزرگ‌تر از صفر باشد.")
    if not ZERO <= decimal.Decimal(fields.scrap_percent or 0) < _HUNDRED:
        raise ValueError("درصد ضایعات نامعتبر است.")
    if fields.valid_from and fields.valid_to and fields.valid_to < fields.valid_from:
        raise ValueError("تاریخ پایان اعتبار پیش از تاریخ شروع است.")
    if fields.status_code not in c.BOM_STATUS:
        raise ValueError("وضعیت فهرست مواد نامعتبر است.")


def create_bom_version(company_id: int, item_id: int, fields: BomFields | None = None, copy_from_bom_id: int | None = None,
                       make_default: bool | None = None, user_id: int | None = None) -> int:
    """نسخهٔ تازهٔ فهرست مواد؛ با copy_from تمام ردیف‌ها و خروجی‌ها کپی می‌شوند. اولین نسخهٔ کالا خودکار پیش‌فرض می‌شود."""
    fields = fields or BomFields()
    _validate_bom_fields(fields)
    with new_session() as session:
        item = c.item_of(session, company_id, item_id)
        if not item.is_stock_tracked:
            raise ValueError("کالای تولیدی باید موجودی‌محور باشد.")
        version = (session.scalar(select(func.max(BomHeader.version_no)).where(BomHeader.finished_item_id == item_id)) or 0) + 1
        has_default = session.scalar(select(BomHeader.bom_id).where(BomHeader.finished_item_id == item_id,
                                                                    BomHeader.is_default.is_(True)))
        bom = BomHeader(finished_item_id=item_id, version_no=version, batch_size_qty=decimal.Decimal(fields.batch_size_qty),
                        production_time_minutes=fields.production_time_minutes,
                        scrap_percent=decimal.Decimal(fields.scrap_percent or 0), is_active=fields.status_code == "ACTIVE",
                        name=fields.name, status_code=fields.status_code, is_default=False, valid_from=fields.valid_from,
                        valid_to=fields.valid_to, routing_id=fields.routing_id, notes=fields.notes, is_locked=False)
        session.add(bom)
        session.flush()
        if copy_from_bom_id:
            src = _get_bom(session, company_id, copy_from_bom_id)
            for ln in session.scalars(select(BomLine).where(BomLine.bom_id == src.bom_id).order_by(BomLine.line_no)):
                session.add(BomLine(bom_id=bom.bom_id, line_no=ln.line_no, **{k: getattr(ln, k) for k in _LINE_COPY}))
            for out in session.scalars(select(BomOutput).where(BomOutput.bom_id == src.bom_id)):
                session.add(BomOutput(bom_id=bom.bom_id, **{k: getattr(out, k) for k in BomOutputFields.__dataclass_fields__}))
            if fields.routing_id is None:
                bom.routing_id = src.routing_id
        if bom.status_code == "ACTIVE" and (make_default or (make_default is None and has_default is None)):
            _set_default_bom(session, bom)
        c.audit(session, company_id, user_id, "BOM", bom.bom_id, "CREATE",
                {"item_id": item_id, "version": version, "copy_from": copy_from_bom_id})
        session.commit()
        return bom.bom_id


_LINE_COPY = ("component_item_id", "quantity_per", "scrap_percent", "uom_id", "conversion_factor", "quantity_type",
              "component_type", "warehouse_id", "operation_seq", "substitute_item_id", "is_optional", "notes")


def update_bom(company_id: int, bom_id: int, fields: BomFields, user_id: int | None = None, reason: str | None = None) -> None:
    """ویرایش سر فهرست مواد. نسخهٔ قفل‌شده فقط اعتبار/وضعیت (بایگانی) را می‌پذیرد."""
    _validate_bom_fields(fields)
    with new_session() as session:
        bom = _get_bom(session, company_id, bom_id)
        changed = {k: [str(getattr(bom, k)), str(v)] for k, v in fields.__dict__.items() if _differs(getattr(bom, k), v)}
        if bom.is_locked and set(changed) - {"valid_to", "status_code", "name", "notes"}:
            raise ValueError("این نسخه قفل است؛ فقط پایان اعتبار، وضعیت و توضیحات قابل تغییر است — نسخهٔ تازه بسازید.")
        for k, v in fields.__dict__.items():
            setattr(bom, k, v)
        bom.is_active = fields.status_code == "ACTIVE"
        if fields.status_code != "ACTIVE" and bom.is_default:
            bom.is_default = False
        if changed:
            c.audit(session, company_id, user_id, "BOM", bom_id, "UPDATE", {**changed, "reason": reason})
        session.commit()


def _differs(a, b) -> bool:
    if isinstance(a, decimal.Decimal) or isinstance(b, decimal.Decimal):
        return decimal.Decimal(a or 0) != decimal.Decimal(b or 0)
    return a != b


def _set_default_bom(session, bom: BomHeader) -> None:
    for other in session.scalars(select(BomHeader).where(BomHeader.finished_item_id == bom.finished_item_id,
                                                         BomHeader.is_default.is_(True))):
        other.is_default = False
    session.flush()
    bom.is_default = True
    session.flush()


def set_default_bom(company_id: int, bom_id: int, user_id: int | None = None) -> None:
    with new_session() as session:
        bom = _get_bom(session, company_id, bom_id)
        if bom.status_code != "ACTIVE":
            raise ValueError("فقط نسخهٔ فعال می‌تواند پیش‌فرض شود.")
        _set_default_bom(session, bom)
        c.audit(session, company_id, user_id, "BOM", bom_id, "SET_DEFAULT", {})
        session.commit()


def _line_values(session, company_id: int, bom: BomHeader, f: BomLineFields) -> dict:
    comp = c.item_of(session, company_id, f.component_item_id)
    if comp.item_id == bom.finished_item_id:
        raise ValueError("یک کالا نمی‌تواند جزو مواد خودش باشد.")
    if not comp.is_stock_tracked:
        raise ValueError(f"جزء «{c.item_label(session, comp.item_id)}» موجودی‌محور نیست.")
    quantity = decimal.Decimal(f.quantity)
    if quantity <= 0:
        raise ValueError("مقدار مصرف باید بزرگ‌تر از صفر باشد.")
    if f.quantity_type not in ("VARIABLE", "FIXED"):
        raise ValueError("نوع مقدار نامعتبر است.")
    if f.component_type not in c.COMPONENT_TYPES:
        raise ValueError("نوع جزء نامعتبر است.")
    if not ZERO <= decimal.Decimal(f.scrap_percent or 0) < _HUNDRED:
        raise ValueError("درصد ضایعات نامعتبر است.")
    if f.substitute_item_id is not None:
        c.item_of(session, company_id, f.substitute_item_id)
    if _creates_cycle(session, bom.finished_item_id, comp.item_id):
        raise ValueError("افزودن این جزء حلقه در فهرست مواد چندسطحی ایجاد می‌کند (کالا به‌طور غیرمستقیم جزو خودش می‌شود).")
    return dict(component_item_id=comp.item_id, quantity_per=quantity, uom_id=f.uom_id,
                conversion_factor=c.factor(session, comp.item_id, f.uom_id), scrap_percent=decimal.Decimal(f.scrap_percent or 0),
                quantity_type=f.quantity_type, component_type=f.component_type, warehouse_id=f.warehouse_id,
                operation_seq=f.operation_seq, substitute_item_id=f.substitute_item_id, is_optional=f.is_optional,
                notes=f.notes)


def _creates_cycle(session, parent_item_id: int, component_item_id: int) -> bool:
    """آیا parent در زیرشاخهٔ component (از طریق فهرست موادهای فعال آن) هست؟"""
    seen, stack = set(), [component_item_id]
    while stack:
        node = stack.pop()
        if node == parent_item_id:
            return True
        if node in seen:
            continue
        seen.add(node)
        stack.extend(session.scalars(select(BomLine.component_item_id).join(BomHeader, BomHeader.bom_id == BomLine.bom_id)
                                     .where(BomHeader.finished_item_id == node, BomHeader.status_code == "ACTIVE")))
    return False


def add_bom_component(company_id: int, bom_id: int, fields: BomLineFields, user_id: int | None = None) -> int:
    with new_session() as session:
        bom = _get_bom(session, company_id, bom_id, for_edit=True)
        values = _line_values(session, company_id, bom, fields)
        next_no = (session.scalar(select(func.max(BomLine.line_no)).where(BomLine.bom_id == bom_id)) or 0) + 1
        line = BomLine(bom_id=bom_id, line_no=next_no, **values)
        session.add(line)
        session.flush()
        c.audit(session, company_id, user_id, "BOM", bom_id, "ADD_COMPONENT",
                {"item_id": fields.component_item_id, "quantity": str(fields.quantity)})
        session.commit()
        return line.bom_line_id


def update_bom_component(company_id: int, bom_line_id: int, fields: BomLineFields, user_id: int | None = None,
                         reason: str | None = None) -> None:
    with new_session() as session:
        line = session.get(BomLine, bom_line_id)
        if line is None:
            raise ValueError("ردیف فهرست مواد نامعتبر است.")
        bom = _get_bom(session, company_id, line.bom_id, for_edit=True)
        values = _line_values(session, company_id, bom, fields)
        changes = {k: [str(getattr(line, k)), str(v)] for k, v in values.items() if _differs(getattr(line, k), v)}
        for k, v in values.items():
            setattr(line, k, v)
        if changes:
            c.audit(session, company_id, user_id, "BOM", bom.bom_id, "UPDATE_COMPONENT",
                    {"line_no": line.line_no, **changes, "reason": reason})
        session.commit()


def remove_bom_component(company_id: int, bom_line_id: int, user_id: int | None = None) -> None:
    with new_session() as session:
        line = session.get(BomLine, bom_line_id)
        if line is None:
            raise ValueError("ردیف فهرست مواد نامعتبر است.")
        bom = _get_bom(session, company_id, line.bom_id, for_edit=True)
        c.audit(session, company_id, user_id, "BOM", bom.bom_id, "REMOVE_COMPONENT",
                {"line_no": line.line_no, "item_id": line.component_item_id, "quantity": str(line.quantity_per)})
        session.delete(line)
        session.commit()


def save_bom_output(company_id: int, bom_id: int, fields: BomOutputFields, user_id: int | None = None) -> int:
    if fields.output_type not in ("BY_PRODUCT", "CO_PRODUCT"):
        raise ValueError("نوع خروجی باید «جانبی» یا «مشترک» باشد.")
    if decimal.Decimal(fields.quantity_per) <= 0:
        raise ValueError("مقدار خروجی باید بزرگ‌تر از صفر باشد.")
    with new_session() as session:
        bom = _get_bom(session, company_id, bom_id, for_edit=True)
        item = c.item_of(session, company_id, fields.item_id)
        if item.item_id == bom.finished_item_id:
            raise ValueError("محصول اصلی نمی‌تواند خروجی جانبی/مشترک خودش باشد.")
        row = session.scalar(select(BomOutput).where(BomOutput.bom_id == bom_id, BomOutput.item_id == fields.item_id))
        if row is None:
            row = BomOutput(bom_id=bom_id, item_id=fields.item_id, output_type=fields.output_type, quantity_per=ONE)
            session.add(row)
        for k, v in fields.__dict__.items():
            setattr(row, k, v)
        session.flush()
        c.audit(session, company_id, user_id, "BOM", bom_id, "SAVE_OUTPUT",
                {"item_id": fields.item_id, "type": fields.output_type, "quantity": str(fields.quantity_per)})
        session.commit()
        return row.bom_output_id


def remove_bom_output(company_id: int, bom_output_id: int, user_id: int | None = None) -> None:
    with new_session() as session:
        row = session.get(BomOutput, bom_output_id)
        if row is None:
            raise ValueError("خروجی فهرست مواد نامعتبر است.")
        _get_bom(session, company_id, row.bom_id, for_edit=True)
        c.audit(session, company_id, user_id, "BOM", row.bom_id, "REMOVE_OUTPUT", {"item_id": row.item_id})
        session.delete(row)
        session.commit()


def lock_bom(session, bom_id: int) -> None:
    bom = session.get(BomHeader, bom_id)
    if bom is not None and not bom.is_locked:
        bom.is_locked = True


def list_bom_versions(company_id: int, item_id: int | None = None) -> list[SimpleNamespace]:
    with new_session() as session:
        q = select(BomHeader).join(Item, Item.item_id == BomHeader.finished_item_id).where(Item.company_id == company_id)
        if item_id:
            q = q.where(BomHeader.finished_item_id == item_id)
        rows = list(session.scalars(q.order_by(BomHeader.finished_item_id, BomHeader.version_no)))
        labels = c.item_labels(session, [r.finished_item_id for r in rows])
        counts = dict(session.execute(select(BomLine.bom_id, func.count()).where(BomLine.bom_id.in_([r.bom_id for r in rows] or [-1]))
                                      .group_by(BomLine.bom_id)).all())
        return [SimpleNamespace(bom_id=r.bom_id, item_id=r.finished_item_id, item_label=labels.get(r.finished_item_id, ""),
                                code=f"BOM-{r.finished_item_id}-V{r.version_no}", version_no=r.version_no, name=r.name,
                                batch_size_qty=r.batch_size_qty, scrap_percent=r.scrap_percent, status_code=r.status_code or "ACTIVE",
                                is_default=r.is_default, is_locked=r.is_locked, valid_from=r.valid_from, valid_to=r.valid_to,
                                routing_id=r.routing_id, production_time_minutes=r.production_time_minutes, notes=r.notes,
                                component_count=counts.get(r.bom_id, 0)) for r in rows]


def bom_components(company_id: int, bom_id: int) -> list[SimpleNamespace]:
    with new_session() as session:
        _get_bom(session, company_id, bom_id)
        rows = list(session.scalars(select(BomLine).where(BomLine.bom_id == bom_id).order_by(BomLine.line_no)))
        labels = c.item_labels(session, [r.component_item_id for r in rows] + [r.substitute_item_id for r in rows])
        return [SimpleNamespace(bom_line_id=r.bom_line_id, line_no=r.line_no, item_id=r.component_item_id,
                                item_label=labels.get(r.component_item_id, ""), quantity=r.quantity_per, uom_id=r.uom_id,
                                conversion_factor=r.conversion_factor or ONE,
                                base_quantity=decimal.Decimal(r.quantity_per) * decimal.Decimal(r.conversion_factor or 1),
                                scrap_percent=r.scrap_percent, quantity_type=r.quantity_type or "VARIABLE",
                                component_type=r.component_type or "MATERIAL", warehouse_id=r.warehouse_id,
                                operation_seq=r.operation_seq, substitute_item_id=r.substitute_item_id,
                                substitute_label=labels.get(r.substitute_item_id, ""), is_optional=r.is_optional,
                                notes=r.notes) for r in rows]


def bom_outputs(company_id: int, bom_id: int) -> list[BomOutput]:
    with new_session() as session:
        _get_bom(session, company_id, bom_id)
        return _expunge(session, list(session.scalars(select(BomOutput).where(BomOutput.bom_id == bom_id)
                                                      .order_by(BomOutput.bom_output_id))))


def effective_bom_id(session, item_id: int, on_date: datetime.date | None = None) -> int | None:
    """نسخهٔ معتبر در تاریخ: پیش‌فرض فعال (اگر در بازهٔ اعتبار است)، وگرنه آخرین نسخهٔ فعال معتبر."""
    on_date = on_date or datetime.date.today()
    valid = ((BomHeader.valid_from.is_(None)) | (BomHeader.valid_from <= on_date)) & (
        (BomHeader.valid_to.is_(None)) | (BomHeader.valid_to >= on_date))
    base = select(BomHeader.bom_id).where(BomHeader.finished_item_id == item_id, BomHeader.status_code == "ACTIVE", valid)
    return (session.scalar(base.where(BomHeader.is_default.is_(True)))
            or session.scalar(base.order_by(BomHeader.version_no.desc())))


def get_effective_bom_id(company_id: int, item_id: int, on_date: datetime.date | None = None) -> int | None:
    with new_session() as session:
        c.item_of(session, company_id, item_id)
        return effective_bom_id(session, item_id, on_date)


def line_requirement(quantity_per_base: decimal.Decimal, quantity_type: str, scrap_percent: decimal.Decimal,
                     order_qty: decimal.Decimal, batch_size: decimal.Decimal) -> tuple[decimal.Decimal, decimal.Decimal]:
    """(نیاز خالص، نیاز با ضایعات). متغیر: سرانه × (مقدار ÷ دستهٔ BOM)؛ ثابت: یک بار برای کل دستور.
    مثال: ۱۰۰ کیلو با ۳٪ ضایعات ← ۱۰۳ کیلو."""
    net = decimal.Decimal(quantity_per_base) if quantity_type == "FIXED" else (
        decimal.Decimal(quantity_per_base) * decimal.Decimal(order_qty) / decimal.Decimal(batch_size or 1))
    gross = net * (ONE + decimal.Decimal(scrap_percent or 0) / _HUNDRED)
    return c.qty(net), c.qty(gross)


def explode(company_id: int, item_id: int, quantity, on_date: datetime.date | None = None, bom_id: int | None = None,
            max_levels: int = 10) -> list[SimpleNamespace]:
    """انفجار چندسطحی فهرست مواد: هر نیمه‌ساختهٔ «ساختنی» که فهرست مواد معتبر دارد باز می‌شود. خروجی ردیف به ردیف با سطح و مسیر."""
    quantity = decimal.Decimal(quantity)
    out: list[SimpleNamespace] = []
    with new_session() as session:
        c.item_of(session, company_id, item_id)

        def walk(parent: int, qty_needed: decimal.Decimal, level: int, path: tuple[int, ...], forced_bom: int | None):
            bid = forced_bom or effective_bom_id(session, parent, on_date)
            if bid is None or level > max_levels:
                return
            bom = session.get(BomHeader, bid)
            header_scrap = decimal.Decimal(bom.scrap_percent or 0)
            for ln in session.scalars(select(BomLine).where(BomLine.bom_id == bid).order_by(BomLine.line_no)):
                if ln.is_optional:
                    continue
                base = decimal.Decimal(ln.quantity_per) * decimal.Decimal(ln.conversion_factor or 1)
                scrap = decimal.Decimal(ln.scrap_percent or 0) or header_scrap
                net, gross = line_requirement(base, ln.quantity_type or "VARIABLE", scrap, qty_needed, bom.batch_size_qty)
                prof = session.get(ItemProductionProfile, ln.component_item_id)
                child_bom = effective_bom_id(session, ln.component_item_id, on_date)
                makes = child_bom is not None and (prof is None or prof.make_or_buy == "MAKE")
                out.append(SimpleNamespace(level=level, parent_item_id=parent, item_id=ln.component_item_id, bom_id=bid,
                                           bom_line_id=ln.bom_line_id, net_qty=net, gross_qty=gross, scrap_percent=scrap,
                                           component_type=ln.component_type or "MATERIAL", is_made=makes,
                                           warehouse_id=ln.warehouse_id, path=path + (ln.component_item_id,)))
                if makes and ln.component_item_id not in path:
                    walk(ln.component_item_id, gross, level + 1, path + (ln.component_item_id,), None)

        walk(item_id, quantity, 1, (item_id,), bom_id)
        labels = c.item_labels(session, [r.item_id for r in out])
        for r in out:
            r.item_label = labels.get(r.item_id, "")
    return out


def where_used(company_id: int, component_item_id: int) -> list[SimpleNamespace]:
    with new_session() as session:
        c.item_of(session, company_id, component_item_id)
        rows = session.execute(select(BomHeader.bom_id, BomHeader.finished_item_id, BomHeader.version_no, BomHeader.status_code,
                                      BomLine.quantity_per).join(BomLine, BomLine.bom_id == BomHeader.bom_id)
                               .where(BomLine.component_item_id == component_item_id)
                               .order_by(BomHeader.finished_item_id, BomHeader.version_no)).all()
        labels = c.item_labels(session, [r[1] for r in rows])
        return [SimpleNamespace(bom_id=r[0], item_id=r[1], item_label=labels.get(r[1], ""), version_no=r[2],
                                status_code=r[3], quantity_per=r[4]) for r in rows]


def validate_bom(company_id: int, bom_id: int) -> list[str]:
    """مشکلات فهرست مواد پیش از استفاده در دستور تولید (خالی = سالم)."""
    issues: list[str] = []
    with new_session() as session:
        bom = _get_bom(session, company_id, bom_id)
        lines = list(session.scalars(select(BomLine).where(BomLine.bom_id == bom_id)))
        if not [ln for ln in lines if not ln.is_optional]:
            issues.append("فهرست مواد هیچ جزء اجباری ندارد.")
        if bom.status_code != "ACTIVE":
            issues.append("نسخهٔ فهرست مواد فعال نیست.")
        for ln in lines:
            comp = session.get(Item, ln.component_item_id)
            if comp is None or comp.lifecycle_status_code != "ACTIVE":
                issues.append(f"جزء «{c.item_label(session, ln.component_item_id)}» فعال نیست.")
            if _creates_cycle(session, bom.finished_item_id, ln.component_item_id):
                issues.append(f"جزء «{c.item_label(session, ln.component_item_id)}» حلقه ایجاد می‌کند.")
    return issues


def quick_bom(company_id: int, item_id: int, components: list[tuple[int, decimal.Decimal]], batch_size=ONE,
              user_id: int | None = None) -> int:
    """ساخت سریع فهرست مواد (کاربر ساده): فقط کالا و مقدار؛ بقیه پیش‌فرض."""
    bom_id = create_bom_version(company_id, item_id, BomFields(batch_size_qty=decimal.Decimal(batch_size)), user_id=user_id)
    for comp, q in components:
        add_bom_component(company_id, bom_id, BomLineFields(component_item_id=comp, quantity=decimal.Decimal(q)), user_id=user_id)
    return bom_id

