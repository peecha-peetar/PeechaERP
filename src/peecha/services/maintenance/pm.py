"""نگهداری پیشگیرانه (R312): برنامهٔ تقویمی / کارکردی / هرکدام زودتر، تولید دستور کار بدون تکرار، تعویق با تأیید.

سررسید تقویمی = سررسید تعویق‌یافتهٔ تأییدشده، یا آخرین انجام + فاصله، یا تاریخ شروع برنامه.
سررسید کارکردی = کارکرد ثبت‌شدهٔ دارایی (fa.asset_usage، جمع واحدها) از آخرین انجام ≥ فاصلهٔ کارکرد.
بدون هیچ دادهٔ کارکرد، وضعیت کارکردی «دادهٔ کارکرد ثبت نشده» است و برنامهٔ «هرکدام زودتر» فقط با تقویم کار می‌کند.
تکرار نمی‌شود: قفل ردیف برنامه + ایندکس یکتای (برنامه، سررسید) + یک دستور کار باز برای هر برنامه.
"""

from __future__ import annotations

import datetime
import decimal
from dataclasses import dataclass, field
from types import SimpleNamespace

from sqlalchemy import func, select

from peecha.db.base import new_session
from peecha.db.models.fixed_assets import Asset, AssetUsage
from peecha.db.models.maintenance import PmPlan, PmPlanPart, PmPlanTask, PmPostponement, WorkOrder
from peecha.services.fixed_assets.common import CLOSED_STATUSES
from peecha.services.maintenance import common as c
from peecha.services.maintenance import work_orders as wos

ENTITY = "MntPmPlan"
STATE_LABELS = {"OK": "در موعد نیست", "DUE": "سررسید", "OVERDUE": "گذشته از سررسید", "NO_DATA": "دادهٔ کارکرد ثبت نشده",
                "OPEN_WO": "دستور کار باز دارد", "INACTIVE": "غیرفعال"}


@dataclass
class PlanInput:
    code: str
    asset_id: int
    title: str
    work_type_code: str = "PREVENTIVE"
    trigger_code: str = "CALENDAR"
    interval_days: int | None = None
    meter_interval: decimal.Decimal | None = None
    lead_days: int = 0
    start_date: datetime.date | None = None
    estimated_hours: decimal.Decimal | None = None
    safety_instructions: str | None = None
    required_skills: str | None = None
    requires_shutdown: bool = False
    responsible_user_id: int | None = None
    is_active: bool = True
    tasks: list[wos.TaskInput] = field(default_factory=list)
    parts: list[tuple[int, int | None, decimal.Decimal]] = field(default_factory=list)   # (کالا، انبار، مقدار)


def _validate(d: PlanInput) -> None:
    if not (d.code or "").strip() or not (d.title or "").strip():
        raise ValueError("کد و عنوان برنامه الزامی است.")
    if d.work_type_code not in c.PM_TYPES:
        raise ValueError("نوع کار برنامهٔ پیشگیرانه نامعتبر است.")
    if d.trigger_code not in c.TRIGGER_LABELS:
        raise ValueError("مبنای سررسید نامعتبر است.")
    if d.trigger_code in ("CALENDAR", "BOTH") and not (d.interval_days and d.interval_days > 0):
        raise ValueError("فاصلهٔ تقویمی (روز) را وارد کنید.")
    if d.trigger_code in ("METER", "BOTH") and not (d.meter_interval and c.dec(d.meter_interval) > 0):
        raise ValueError("فاصلهٔ کارکرد را وارد کنید.")
    if (d.lead_days or 0) < 0:
        raise ValueError("روزهای پیش از سررسید منفی نمی‌تواند باشد.")
    for t in d.tasks:
        wos._validate_task(t)
    for _item, _wh, qty in d.parts:
        if c.dec(qty) <= 0:
            raise ValueError("مقدار قطعهٔ برنامه باید مثبت باشد.")


def save_plan(company_id: int, user_id: int, data: PlanInput, plan_id: int | None = None) -> int:
    _validate(data)
    with new_session() as session:
        c.require(company_id, user_id, c.FORM_MANAGE, session=session)
        asset = c.asset_of(session, company_id, data.asset_id)
        if asset.status_code in CLOSED_STATUSES:
            raise ValueError("این تجهیز واگذار شده است.")
        dup = session.scalar(select(PmPlan.plan_id).where(PmPlan.company_id == company_id, PmPlan.code == data.code.strip()))
        if dup is not None and dup != plan_id:
            raise ValueError("این کد برنامه قبلاً تعریف شده است.")
        if plan_id:
            plan = session.scalar(select(PmPlan).where(PmPlan.plan_id == plan_id).with_for_update())
            if plan is None or plan.company_id != company_id:
                raise ValueError("برنامهٔ پیشگیرانه نامعتبر است.")
        else:
            plan = PmPlan(company_id=company_id, created_by_user_id=user_id, meter_at_last=_meter(session, data.asset_id))
            session.add(plan)
        before = {k: str(getattr(plan, k, None)) for k in ("trigger_code", "interval_days", "meter_interval", "is_active")}
        plan.code, plan.asset_id, plan.title = data.code.strip(), data.asset_id, data.title.strip()
        plan.work_type_code, plan.trigger_code = data.work_type_code, data.trigger_code
        plan.interval_days = data.interval_days if data.trigger_code in ("CALENDAR", "BOTH") else None
        plan.meter_interval = c.dec(data.meter_interval) if data.trigger_code in ("METER", "BOTH") else None
        plan.lead_days, plan.start_date = data.lead_days or 0, data.start_date or plan.start_date or datetime.date.today()
        plan.estimated_hours, plan.requires_shutdown = data.estimated_hours, data.requires_shutdown
        plan.safety_instructions = (data.safety_instructions or "").strip() or None
        plan.required_skills = (data.required_skills or "").strip() or None
        plan.responsible_user_id, plan.is_active = data.responsible_user_id, data.is_active
        session.flush()
        for t in session.scalars(select(PmPlanTask).where(PmPlanTask.plan_id == plan.plan_id)):
            session.delete(t)
        for p in session.scalars(select(PmPlanPart).where(PmPlanPart.plan_id == plan.plan_id)):
            session.delete(p)
        session.flush()
        for seq, t in enumerate(data.tasks, start=1):
            session.add(PmPlanTask(plan_id=plan.plan_id, seq=seq, description=t.description.strip(), result_type=t.result_type,
                                   min_value=t.min_value, max_value=t.max_value, uom_label=(t.uom_label or "").strip() or None,
                                   is_mandatory=t.is_mandatory, is_safety=t.is_safety))
        for item_id, wh, qty in data.parts:
            session.add(PmPlanPart(plan_id=plan.plan_id, item_id=item_id, warehouse_id=wh, quantity=c.dec(qty)))
        after = {k: str(getattr(plan, k)) for k in before}
        c.audit(session, company_id, user_id, ENTITY, plan.plan_id, "UPDATE" if plan_id else "CREATE",
                {k: [before[k], after[k]] for k in before if before[k] != after[k]} | {"tasks": len(data.tasks)})
        session.commit()
        return plan.plan_id


def _meter(session, asset_id: int) -> decimal.Decimal:
    return c.dec(session.scalar(select(func.coalesce(func.sum(AssetUsage.units), 0)).where(AssetUsage.asset_id == asset_id)))


def _has_usage(session, asset_id: int) -> bool:
    return session.scalar(select(AssetUsage.usage_id).where(AssetUsage.asset_id == asset_id).limit(1)) is not None


def _open_wo(session, plan_id: int) -> WorkOrder | None:
    return session.scalar(select(WorkOrder).where(WorkOrder.pm_plan_id == plan_id, WorkOrder.status_code.in_(c.OPEN_WO))
                          .order_by(WorkOrder.work_order_id.desc()))


def calendar_due(plan: PmPlan) -> datetime.date | None:
    if plan.trigger_code == "METER":
        return None
    if plan.next_due_date:
        return plan.next_due_date
    if plan.last_completed_date:
        return plan.last_completed_date + datetime.timedelta(days=plan.interval_days)
    return plan.start_date


def due_info(session, plan: PmPlan, today: datetime.date | None = None) -> SimpleNamespace:
    """وضعیت سررسید یک برنامه (بدون نوشتن)."""
    today = today or datetime.date.today()
    cal = calendar_due(plan)
    meter_now = meter_used = meter_left = None
    meter_state = None
    if plan.trigger_code in ("METER", "BOTH"):
        if not _has_usage(session, plan.asset_id):
            meter_state = "NO_DATA"
        else:
            meter_now = _meter(session, plan.asset_id)
            meter_used = meter_now - c.dec(plan.meter_at_last)
            meter_left = c.dec(plan.meter_interval) - meter_used
            meter_state = "DUE" if meter_left <= 0 else "OK"
    open_wo = _open_wo(session, plan.plan_id)
    due_date = cal
    if meter_state == "DUE":
        # سررسید کارکردی امروز است؛ اگر سررسید تقویمی زودتر بوده همان می‌ماند
        due_date = min(cal, today) if cal else today
    if not plan.is_active:
        state = "INACTIVE"
    elif open_wo is not None:
        state = "OPEN_WO"
    elif plan.trigger_code == "METER" and meter_state == "NO_DATA":
        state = "NO_DATA"
    elif due_date is not None and due_date < today:
        state = "OVERDUE"
    elif due_date is not None and due_date - datetime.timedelta(days=plan.lead_days or 0) <= today:
        state = "DUE"
    else:
        state = "OK"
    return SimpleNamespace(plan_id=plan.plan_id, due_date=due_date, calendar_due=cal, meter_state=meter_state,
                           meter_now=meter_now, meter_used=meter_used, meter_left=meter_left, state=state,
                           state_label=STATE_LABELS[state], open_work_order_id=open_wo.work_order_id if open_wo else None)


def generate_due(company_id: int, user_id: int | None, as_of: datetime.date | None = None,
                 plan_ids: list[int] | None = None) -> list[int]:
    """ساخت دستور کار برای برنامه‌های سررسید؛ اجرای دوباره (حتی هم‌زمان) دستور تکراری نمی‌سازد."""
    as_of = as_of or datetime.date.today()
    created: list[int] = []
    with new_session() as session:
        if user_id is not None:
            c.require(company_id, user_id, c.FORM_PLAN, "CREATE", session=session)
        q = select(PmPlan.plan_id).where(PmPlan.company_id == company_id, PmPlan.is_active.is_(True))
        if plan_ids:
            q = q.where(PmPlan.plan_id.in_(plan_ids))
        ids = list(session.scalars(q.order_by(PmPlan.plan_id)))
    for pid in ids:
        with new_session() as session:
            plan = session.scalar(select(PmPlan).where(PmPlan.plan_id == pid).with_for_update())
            asset = session.get(Asset, plan.asset_id)
            if not plan.is_active or asset is None or asset.status_code in CLOSED_STATUSES:
                continue
            info = due_info(session, plan, as_of)
            if info.state not in ("DUE", "OVERDUE"):
                continue
            exists = session.scalar(select(WorkOrder.work_order_id).where(WorkOrder.pm_plan_id == pid,
                                                                          WorkOrder.pm_due_date == info.due_date))
            if exists:
                continue
            created.append(_create_wo(session, plan, info.due_date, user_id).work_order_id)
            session.commit()
    return created


def _create_wo(session, plan: PmPlan, due: datetime.date, user_id: int | None) -> WorkOrder:
    from peecha.services.maintenance import parts

    tasks = [wos.TaskInput(t.description, t.result_type, t.min_value, t.max_value, t.uom_label, t.is_mandatory, t.is_safety)
             for t in session.scalars(select(PmPlanTask).where(PmPlanTask.plan_id == plan.plan_id).order_by(PmPlanTask.seq))]
    start = datetime.datetime.combine(due, datetime.time(8, 0)).astimezone()
    end = start + datetime.timedelta(hours=float(plan.estimated_hours or 1))
    data = wos.WorkOrderInput(asset_id=plan.asset_id, work_type_code=plan.work_type_code, title=plan.title,
                              description=f"برنامهٔ پیشگیرانهٔ {plan.code}", priority_code="NORMAL",
                              responsible_user_id=plan.responsible_user_id, planned_start=start, planned_end=end,
                              estimated_hours=plan.estimated_hours, requires_shutdown=plan.requires_shutdown,
                              safety_instructions=plan.safety_instructions, required_skills=plan.required_skills, tasks=tasks)
    wo = wos.create_in_session(session, plan.company_id, user_id, data, pm_plan_id=plan.plan_id, pm_due_date=due)
    parts.add_parts_in_session(session, wo.work_order_id, user_id,
                               [(p.item_id, p.warehouse_id, p.quantity) for p in session.scalars(
                                   select(PmPlanPart).where(PmPlanPart.plan_id == plan.plan_id))], None)
    c.audit(session, plan.company_id, user_id, ENTITY, plan.plan_id, "GENERATE",
            {"work_order_id": wo.work_order_id, "due_date": str(due)})
    return wo


def on_work_order_closed(session, wo: WorkOrder, user_id: int | None) -> None:
    """بستن دستور پیشگیرانه: آخرین انجام = پایان واقعی کار، شمارنده = کارکرد فعلی، تعویق مصرف‌شده پاک."""
    plan = session.scalar(select(PmPlan).where(PmPlan.plan_id == wo.pm_plan_id).with_for_update())
    if plan is None:
        return
    done = (c.aware(wo.actual_end) or c.now()).date()
    old = [str(plan.last_completed_date), str(plan.meter_at_last)]
    plan.last_completed_date = max(done, plan.last_completed_date or done)
    plan.meter_at_last = _meter(session, plan.asset_id)
    plan.next_due_date = None
    c.audit(session, plan.company_id, user_id, ENTITY, plan.plan_id, "COMPLETE",
            {"work_order_id": wo.work_order_id, "last": [old, [str(plan.last_completed_date), str(plan.meter_at_last)]]})


def record_meter(company_id: int, user_id: int, asset_id: int, date: datetime.date, units, note: str | None = None) -> int:
    """ثبت کارکرد/شمارنده در همان کارکرد دارایی (fa.asset_usage، منبع «شمارنده»)."""
    from peecha.services.fixed_assets import depreciation

    c.require(company_id, user_id, c.FORM_EXECUTE)
    return depreciation.record_usage(company_id, user_id, asset_id, date, c.dec(units), source_code="METER", note=note)


# --- تعویق ----------------------------------------------------------------------------------
def request_postponement(company_id: int, user_id: int, plan_id: int, new_due_date: datetime.date, reason: str) -> int:
    if not (reason or "").strip():
        raise ValueError("علت تعویق الزامی است.")
    with new_session() as session:
        c.require(company_id, user_id, c.FORM_PLAN, session=session)
        plan = session.scalar(select(PmPlan).where(PmPlan.plan_id == plan_id).with_for_update())
        if plan is None or plan.company_id != company_id:
            raise ValueError("برنامهٔ پیشگیرانه نامعتبر است.")
        info = due_info(session, plan)
        old = info.due_date
        if old is None:
            raise ValueError("این برنامه سررسید تقویمی ندارد که به تعویق بیفتد.")
        open_wo = _open_wo(session, plan_id)
        if open_wo is not None and open_wo.pm_due_date:
            old = open_wo.pm_due_date
        if new_due_date <= old:
            raise ValueError("تاریخ جدید باید بعد از سررسید فعلی باشد.")
        if session.scalar(select(PmPostponement.postponement_id).where(PmPostponement.plan_id == plan_id,
                                                                       PmPostponement.status_code == "PENDING")):
            raise ValueError("برای این برنامه یک درخواست تعویق منتظر تأیید است.")
        row = PmPostponement(plan_id=plan_id, work_order_id=open_wo.work_order_id if open_wo else None, old_due_date=old,
                             new_due_date=new_due_date, reason=reason.strip()[:300], status_code="PENDING",
                             requested_by_user_id=user_id)
        session.add(row)
        session.flush()
        c.audit(session, company_id, user_id, ENTITY, plan_id, "POSTPONE_REQUEST",
                {"postponement_id": row.postponement_id, "old": str(old), "new": str(new_due_date), "reason": reason})
        session.commit()
        return row.postponement_id


def decide_postponement(company_id: int, user_id: int, postponement_id: int, approve: bool, note: str | None = None) -> None:
    """تأیید یا رد تعویق؛ درخواست‌کننده خودش تأیید نمی‌کند (مگر مدیر کل سیستم)."""
    from peecha.db.models.security import User

    with new_session() as session:
        c.require(company_id, user_id, c.FORM_APPROVE, session=session)
        row = session.scalar(select(PmPostponement).where(PmPostponement.postponement_id == postponement_id).with_for_update())
        plan = session.scalar(select(PmPlan).where(PmPlan.plan_id == row.plan_id).with_for_update()) if row else None
        if row is None or plan is None or plan.company_id != company_id:
            raise ValueError("درخواست تعویق نامعتبر است.")
        if row.status_code != "PENDING":
            raise ValueError("این درخواست تعویق قبلاً تعیین تکلیف شده است.")
        user = session.get(User, user_id)
        if row.requested_by_user_id == user_id and not (user and user.is_super_admin):
            raise ValueError("درخواست‌کنندهٔ تعویق نمی‌تواند خودش آن را تأیید یا رد کند.")
        if not approve and not (note or "").strip():
            raise ValueError("علت رد را بنویسید.")
        row.status_code = "APPROVED" if approve else "REJECTED"
        row.decided_by_user_id, row.decided_at = user_id, c.now()
        if approve:
            plan.next_due_date = row.new_due_date
            wo = session.get(WorkOrder, row.work_order_id) if row.work_order_id else None
            if wo is not None and wo.status_code in ("OPEN", "PLANNED", "ASSIGNED", "ON_HOLD") and wo.pm_due_date == row.old_due_date:
                shift = row.new_due_date - row.old_due_date
                wo.pm_due_date = row.new_due_date
                if wo.planned_start:
                    wo.planned_start = c.aware(wo.planned_start) + shift
                if wo.planned_end:
                    wo.planned_end = c.aware(wo.planned_end) + shift
                c.audit(session, company_id, user_id, wos.ENTITY, wo.work_order_id, "UPDATE",
                        {"pm_due_date": [str(row.old_due_date), str(row.new_due_date)], "postponement_id": postponement_id})
        c.audit(session, company_id, user_id, ENTITY, plan.plan_id, "APPROVE" if approve else "REJECT",
                {"postponement_id": postponement_id, "note": note})
        session.commit()


def list_postponements(company_id: int, pending_only: bool = True) -> list[SimpleNamespace]:
    with new_session() as session:
        q = select(PmPostponement, PmPlan, Asset).join(PmPlan, PmPlan.plan_id == PmPostponement.plan_id).join(
            Asset, Asset.asset_id == PmPlan.asset_id).where(PmPlan.company_id == company_id)
        if pending_only:
            q = q.where(PmPostponement.status_code == "PENDING")
        rows = session.execute(q.order_by(PmPostponement.postponement_id.desc())).all()
        names = c.user_names(session, [r.requested_by_user_id for r, _p, _a in rows])
        return [SimpleNamespace(postponement_id=r.postponement_id, plan_id=p.plan_id, plan_code=p.code, plan_title=p.title,
                                asset_label=c.asset_label(a), old_due_date=r.old_due_date, new_due_date=r.new_due_date,
                                reason=r.reason, status_code=r.status_code, status_label=c.POSTPONE_STATUS_LABELS[r.status_code],
                                requested_by=names.get(r.requested_by_user_id, ""), requested_by_user_id=r.requested_by_user_id)
                for r, p, a in rows]


# --- خواندن ---------------------------------------------------------------------------------
def list_plans(company_id: int, asset_id: int | None = None, include_inactive: bool = True,
               today: datetime.date | None = None) -> list[SimpleNamespace]:
    with new_session() as session:
        q = select(PmPlan, Asset).join(Asset, Asset.asset_id == PmPlan.asset_id).where(PmPlan.company_id == company_id)
        if asset_id:
            q = q.where(PmPlan.asset_id == asset_id)
        if not include_inactive:
            q = q.where(PmPlan.is_active.is_(True))
        out = []
        for plan, asset in session.execute(q.order_by(PmPlan.code)).all():
            info = due_info(session, plan, today)
            out.append(SimpleNamespace(
                plan_id=plan.plan_id, code=plan.code, title=plan.title, asset_id=asset.asset_id, asset_label=c.asset_label(asset),
                work_type_label=c.WORK_TYPE_LABELS[plan.work_type_code], trigger_label=c.TRIGGER_LABELS[plan.trigger_code],
                trigger_code=plan.trigger_code, interval_days=plan.interval_days, meter_interval=plan.meter_interval,
                lead_days=plan.lead_days, last_completed_date=plan.last_completed_date, is_active=plan.is_active,
                requires_shutdown=plan.requires_shutdown, due=info))
        return out


def get_plan(company_id: int, plan_id: int) -> SimpleNamespace:
    with new_session() as session:
        plan = session.get(PmPlan, plan_id)
        if plan is None or plan.company_id != company_id:
            raise ValueError("برنامهٔ پیشگیرانه نامعتبر است.")
        tasks = [wos.TaskInput(t.description, t.result_type, t.min_value, t.max_value, t.uom_label, t.is_mandatory, t.is_safety)
                 for t in session.scalars(select(PmPlanTask).where(PmPlanTask.plan_id == plan_id).order_by(PmPlanTask.seq))]
        parts = [(p.item_id, p.warehouse_id, p.quantity) for p in session.scalars(select(PmPlanPart).where(PmPlanPart.plan_id == plan_id))]
        return SimpleNamespace(plan_id=plan.plan_id, data=PlanInput(
            code=plan.code, asset_id=plan.asset_id, title=plan.title, work_type_code=plan.work_type_code,
            trigger_code=plan.trigger_code, interval_days=plan.interval_days, meter_interval=plan.meter_interval,
            lead_days=plan.lead_days, start_date=plan.start_date, estimated_hours=plan.estimated_hours,
            safety_instructions=plan.safety_instructions, required_skills=plan.required_skills,
            requires_shutdown=plan.requires_shutdown, responsible_user_id=plan.responsible_user_id, is_active=plan.is_active,
            tasks=tasks, parts=parts), due=due_info(session, plan))


def calendar(company_id: int, date_from: datetime.date, date_to: datetime.date, asset_id: int | None = None) -> list[SimpleNamespace]:
    """تقویم نگهداری پیشگیرانه: دستورهای ساخته‌شده + سررسیدهای پیش‌بینی‌شدهٔ تقویمی در بازه."""
    today = datetime.date.today()
    out = []
    with new_session() as session:
        q = select(WorkOrder, Asset).join(Asset, Asset.asset_id == WorkOrder.asset_id).where(
            WorkOrder.company_id == company_id, WorkOrder.pm_plan_id.isnot(None),
            WorkOrder.pm_due_date.between(date_from, date_to))
        if asset_id:
            q = q.where(WorkOrder.asset_id == asset_id)
        seen = set()
        for wo, asset in session.execute(q).all():
            seen.add((wo.pm_plan_id, wo.pm_due_date))
            late = wo.status_code in c.OPEN_WO and wo.pm_due_date < today
            out.append(SimpleNamespace(date=wo.pm_due_date, kind="WORK_ORDER", plan_id=wo.pm_plan_id, work_order_id=wo.work_order_id,
                                       wo_no=wo.wo_no, asset_label=c.asset_label(asset), title=wo.title,
                                       status_label=c.WO_STATUS_LABELS[wo.status_code], overdue=late,
                                       requires_shutdown=wo.requires_shutdown))
        pq = select(PmPlan, Asset).join(Asset, Asset.asset_id == PmPlan.asset_id).where(
            PmPlan.company_id == company_id, PmPlan.is_active.is_(True), PmPlan.trigger_code != "METER")
        if asset_id:
            pq = pq.where(PmPlan.asset_id == asset_id)
        for plan, asset in session.execute(pq).all():
            due = calendar_due(plan)
            if due is None:
                continue
            open_wo = _open_wo(session, plan.plan_id)
            if open_wo is not None and open_wo.pm_due_date:
                due = open_wo.pm_due_date + datetime.timedelta(days=plan.interval_days)   # بعدی پس از دستور باز
            guard = 0
            while due <= date_to and guard < 400:
                guard += 1
                if due >= date_from and (plan.plan_id, due) not in seen:
                    out.append(SimpleNamespace(date=due, kind="FORECAST", plan_id=plan.plan_id, work_order_id=None, wo_no=None,
                                               asset_label=c.asset_label(asset), title=plan.title, status_label="پیش‌بینی",
                                               overdue=due < today, requires_shutdown=plan.requires_shutdown))
                due += datetime.timedelta(days=plan.interval_days)
    return sorted(out, key=lambda r: (r.date, r.asset_label))
