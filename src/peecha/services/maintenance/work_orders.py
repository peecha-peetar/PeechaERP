"""دستور کار نگهداری (R312): ایجاد ← برنامه‌ریزی ← واگذاری ← اجرا (تعلیق/ادامه) ← انجام‌شده ← آزمون و تأیید ←
آماده‌به‌کاری ماشین ← بستن؛ بازگشایی مجاز و لغو با علت. «انجام‌شده» به‌تنهایی نه تأیید ایمنی است نه آماده‌به‌کاری.
"""

from __future__ import annotations

import datetime
import decimal
from dataclasses import dataclass, field
from types import SimpleNamespace

from sqlalchemy import func, select

from peecha.db.base import new_session
from peecha.db.models.audit import ActivityLog
from peecha.db.models.fixed_assets import Asset
from peecha.db.models.maintenance import (
    DowntimeEvent, FailureCode, PmPlan, WorkOrder, WorkOrderCost, WorkOrderLabor, WorkOrderPart, WorkOrderTask,
    WorkOrderTechnician, WorkRequest,
)
from peecha.services import stock_controls
from peecha.services.fixed_assets.common import CLOSED_STATUSES
from peecha.services.maintenance import availability
from peecha.services.maintenance import common as c

ENTITY = "MntWorkOrder"
_EDITABLE = ("OPEN", "PLANNED", "ASSIGNED", "IN_PROGRESS", "ON_HOLD")


@dataclass
class TaskInput:
    description: str
    result_type: str = "CHECK"
    min_value: decimal.Decimal | None = None
    max_value: decimal.Decimal | None = None
    uom_label: str | None = None
    is_mandatory: bool = True
    is_safety: bool = False


@dataclass
class WorkOrderInput:
    asset_id: int
    work_type_code: str
    title: str
    description: str | None = None
    priority_code: str = "NORMAL"
    responsible_user_id: int | None = None
    planned_start: datetime.datetime | None = None
    planned_end: datetime.datetime | None = None
    estimated_hours: decimal.Decimal | None = None
    requires_shutdown: bool = False
    safety_instructions: str | None = None
    required_skills: str | None = None
    machine_stopped: bool = False          # دستور کار اضطراری مستقیم: شروع توقف از همین لحظه
    stopped_at: datetime.datetime | None = None
    capital_candidate: bool = False
    tasks: list[TaskInput] = field(default_factory=list)


def lock(session, company_id: int, work_order_id: int) -> WorkOrder:
    wo = session.scalar(select(WorkOrder).where(WorkOrder.work_order_id == work_order_id).with_for_update())
    if wo is None or wo.company_id != company_id:
        raise ValueError("دستور کار نامعتبر است.")
    return wo


def _ensure(wo: WorkOrder, allowed: tuple[str, ...], action: str) -> None:
    if wo.status_code not in allowed:
        raise ValueError(f"دستور کار در وضعیت «{c.WO_STATUS_LABELS[wo.status_code]}» است و {action} ممکن نیست.")


def _set_status(session, wo: WorkOrder, user_id: int | None, status: str, operation: str, **changes) -> None:
    previous = wo.status_code
    wo.status_code = status
    session.flush()
    c.audit(session, wo.company_id, user_id, ENTITY, wo.work_order_id, operation,
            {"status_code": [previous, status], **changes})


def _validate(data: WorkOrderInput) -> None:
    if data.work_type_code not in c.WORK_TYPE_LABELS:
        raise ValueError("نوع کار نامعتبر است.")
    if data.priority_code not in c.PRIORITY_LABELS:
        raise ValueError("اولویت نامعتبر است.")
    if not (data.title or "").strip():
        raise ValueError("عنوان دستور کار الزامی است.")
    if data.planned_start and data.planned_end and c.aware(data.planned_end) < c.aware(data.planned_start):
        raise ValueError("پایان برنامه‌ریزی‌شده نمی‌تواند پیش از شروع باشد.")
    if data.estimated_hours is not None and c.dec(data.estimated_hours) < 0:
        raise ValueError("زمان تخمینی منفی نمی‌تواند باشد.")
    for t in data.tasks:
        _validate_task(t)


def _validate_task(t: TaskInput) -> None:
    if not (t.description or "").strip():
        raise ValueError("شرح ردیف چک‌لیست الزامی است.")
    if t.result_type not in c.RESULT_TYPE_LABELS:
        raise ValueError("نوع نتیجهٔ چک‌لیست نامعتبر است.")
    if t.min_value is not None and t.max_value is not None and c.dec(t.min_value) > c.dec(t.max_value):
        raise ValueError("حداقل مجاز از حداکثر بیشتر است.")


def create_in_session(session, company_id: int, user_id: int | None, data: WorkOrderInput, request_id: int | None = None,
                      pm_plan_id: int | None = None, pm_due_date: datetime.date | None = None,
                      idempotency_key: str | None = None) -> WorkOrder:
    _validate(data)
    asset = c.asset_of(session, company_id, data.asset_id)
    if asset.status_code in CLOSED_STATUSES:
        raise ValueError("این تجهیز واگذار شده و دستور کار نمی‌پذیرد.")
    status = "PLANNED" if data.planned_start else "OPEN"
    wo = WorkOrder(
        company_id=company_id, wo_no=c.next_no(session, WorkOrder, WorkOrder.wo_no, company_id), asset_id=data.asset_id,
        request_id=request_id, pm_plan_id=pm_plan_id, pm_due_date=pm_due_date, work_type_code=data.work_type_code,
        priority_code=data.priority_code, title=data.title.strip(), description=(data.description or "").strip() or None,
        status_code=status, responsible_user_id=data.responsible_user_id, planned_start=c.aware(data.planned_start),
        planned_end=c.aware(data.planned_end), estimated_hours=data.estimated_hours, requires_shutdown=data.requires_shutdown,
        safety_instructions=(data.safety_instructions or "").strip() or None,
        required_skills=(data.required_skills or "").strip() or None, capital_candidate=data.capital_candidate,
        idempotency_key=idempotency_key, created_by_user_id=user_id)
    session.add(wo)
    session.flush()
    for seq, t in enumerate(data.tasks, start=1):
        session.add(_task_row(wo.work_order_id, seq, t))
    c.audit(session, company_id, user_id, ENTITY, wo.work_order_id, "CREATE",
            {"wo_no": wo.wo_no, "asset_id": wo.asset_id, "work_type": wo.work_type_code, "status_code": [None, status],
             "request_id": request_id, "pm_plan_id": pm_plan_id, "pm_due_date": str(pm_due_date) if pm_due_date else None})
    if data.machine_stopped:
        availability.start(session, company_id, user_id, data.asset_id, data.stopped_at or c.now(), "BREAKDOWN",
                           request_id=request_id, work_order_id=wo.work_order_id)
    return wo


def _task_row(work_order_id: int, seq: int, t: TaskInput) -> WorkOrderTask:
    return WorkOrderTask(work_order_id=work_order_id, seq=seq, description=t.description.strip(), result_type=t.result_type,
                         min_value=t.min_value, max_value=t.max_value, uom_label=(t.uom_label or "").strip() or None,
                         is_mandatory=t.is_mandatory, is_safety=t.is_safety)


def create(company_id: int, user_id: int, data: WorkOrderInput, idempotency_key: str | None = None) -> int:
    """دستور کار مستقیم (بدون درخواست)؛ برای خرابی اضطراری با machine_stopped توقف هم شروع می‌شود."""
    with new_session() as session:
        if idempotency_key:
            done = session.scalar(select(WorkOrder.work_order_id).where(WorkOrder.company_id == company_id,
                                                                        WorkOrder.idempotency_key == idempotency_key))
            if done:
                return done
        c.require(company_id, user_id, c.FORM_PLAN, "CREATE", session=session)
        wo = create_in_session(session, company_id, user_id, data, idempotency_key=idempotency_key)
        session.commit()
        return wo.work_order_id


def update_plan(company_id: int, user_id: int, work_order_id: int, *, title: str | None = None, description: str | None = None,
                priority_code: str | None = None, responsible_user_id: int | None = None,
                planned_start: datetime.datetime | None = None, planned_end: datetime.datetime | None = None,
                estimated_hours=None, requires_shutdown: bool | None = None, safety_instructions: str | None = None,
                required_skills: str | None = None, capital_candidate: bool | None = None) -> None:
    with new_session() as session:
        c.require(company_id, user_id, c.FORM_PLAN, session=session)
        wo = lock(session, company_id, work_order_id)
        _ensure(wo, _EDITABLE, "ویرایش برنامه")
        before = {}

        def put(attr, value):
            old = getattr(wo, attr)
            if value is not None and value != old:
                before[attr] = [str(old) if old is not None else None, str(value)]
                setattr(wo, attr, value)

        if priority_code is not None and priority_code not in c.PRIORITY_LABELS:
            raise ValueError("اولویت نامعتبر است.")
        put("title", (title or "").strip() or None)
        put("description", (description or "").strip() or None)
        put("priority_code", priority_code)
        put("responsible_user_id", responsible_user_id)
        put("planned_start", c.aware(planned_start))
        put("planned_end", c.aware(planned_end))
        put("estimated_hours", c.dec(estimated_hours) if estimated_hours is not None else None)
        put("requires_shutdown", requires_shutdown)
        put("safety_instructions", (safety_instructions or "").strip() or None)
        put("required_skills", (required_skills or "").strip() or None)
        put("capital_candidate", capital_candidate)
        if wo.planned_start and wo.planned_end and c.aware(wo.planned_end) < c.aware(wo.planned_start):
            raise ValueError("پایان برنامه‌ریزی‌شده نمی‌تواند پیش از شروع باشد.")
        if wo.status_code == "OPEN" and wo.planned_start:
            _set_status(session, wo, user_id, "PLANNED", "PLAN", **before)
        elif before:
            session.flush()
            c.audit(session, company_id, user_id, ENTITY, work_order_id, "UPDATE", before)
        session.commit()


def assign(company_id: int, user_id: int, work_order_id: int, technician_ids: list[int], lead_user_id: int | None = None) -> None:
    """واگذاری به تکنسین‌ها (جایگزین فهرست قبلی)."""
    ids = list(dict.fromkeys(t for t in technician_ids if t))
    if not ids:
        raise ValueError("دست‌کم یک تکنسین انتخاب کنید.")
    if lead_user_id is not None and lead_user_id not in ids:
        raise ValueError("سرگروه باید از میان تکنسین‌های انتخاب‌شده باشد.")
    with new_session() as session:
        c.require(company_id, user_id, c.FORM_PLAN, session=session)
        wo = lock(session, company_id, work_order_id)
        _ensure(wo, _EDITABLE, "واگذاری")
        old = sorted(session.scalars(select(WorkOrderTechnician.user_id).where(WorkOrderTechnician.work_order_id == work_order_id)))
        for row in session.scalars(select(WorkOrderTechnician).where(WorkOrderTechnician.work_order_id == work_order_id)):
            session.delete(row)
        session.flush()
        lead = lead_user_id or ids[0]
        for uid in ids:
            session.add(WorkOrderTechnician(work_order_id=work_order_id, user_id=uid, is_lead=uid == lead,
                                            assigned_by_user_id=user_id))
        if wo.responsible_user_id is None:
            wo.responsible_user_id = lead
        if wo.status_code in ("OPEN", "PLANNED"):
            _set_status(session, wo, user_id, "ASSIGNED", "ASSIGN", technicians=[old, sorted(ids)])
        else:
            session.flush()
            c.audit(session, company_id, user_id, ENTITY, work_order_id, "ASSIGN", {"technicians": [old, sorted(ids)]})
        session.commit()


def refer(company_id: int, user_id: int, work_order_id: int, to_user_id: int, note: str) -> None:
    """ارجاع مسئولیت دستور کار به فرد دیگر (با علت)."""
    if not (note or "").strip():
        raise ValueError("علت ارجاع را بنویسید.")
    with new_session() as session:
        c.require(company_id, user_id, c.FORM_PLAN, session=session)
        wo = lock(session, company_id, work_order_id)
        _ensure(wo, _EDITABLE + ("COMPLETED",), "ارجاع")
        old = wo.responsible_user_id
        wo.responsible_user_id = to_user_id
        session.flush()
        c.audit(session, company_id, user_id, ENTITY, work_order_id, "REFER",
                {"responsible_user_id": [old, to_user_id], "note": note.strip()})
        session.commit()


def start(company_id: int, user_id: int, work_order_id: int, at: datetime.datetime | None = None) -> None:
    """شروع اجرا؛ کار نیازمند توقف ماشین، اگر توقف بازی نباشد توقف برنامه‌ریزی‌شده را از همین لحظه شروع می‌کند."""
    at = c.aware(at) or c.now()
    with new_session() as session:
        c.require(company_id, user_id, c.FORM_EXECUTE, session=session)
        wo = lock(session, company_id, work_order_id)
        _ensure(wo, ("OPEN", "PLANNED", "ASSIGNED"), "شروع")
        wo.actual_start = wo.actual_start or at
        if wo.requires_shutdown:
            availability.start(session, company_id, user_id, wo.asset_id, at, "PLANNED", request_id=wo.request_id,
                               work_order_id=wo.work_order_id)
        _set_status(session, wo, user_id, "IN_PROGRESS", "START", actual_start=wo.actual_start.isoformat())
        session.commit()


def hold(company_id: int, user_id: int, work_order_id: int, reason: str) -> None:
    if not (reason or "").strip():
        raise ValueError("علت توقف موقت الزامی است.")
    with new_session() as session:
        c.require(company_id, user_id, c.FORM_EXECUTE, session=session)
        wo = lock(session, company_id, work_order_id)
        _ensure(wo, ("OPEN", "PLANNED", "ASSIGNED", "IN_PROGRESS"), "توقف موقت")
        wo.hold_reason = reason.strip()
        _set_status(session, wo, user_id, "ON_HOLD", "HOLD", reason=reason.strip())
        session.commit()


def resume(company_id: int, user_id: int, work_order_id: int) -> None:
    with new_session() as session:
        c.require(company_id, user_id, c.FORM_EXECUTE, session=session)
        wo = lock(session, company_id, work_order_id)
        _ensure(wo, ("ON_HOLD",), "ادامه")
        has_tech = session.scalar(select(func.count()).where(WorkOrderTechnician.work_order_id == work_order_id))
        target = "IN_PROGRESS" if wo.actual_start else ("ASSIGNED" if has_tech else ("PLANNED" if wo.planned_start else "OPEN"))
        wo.hold_reason = None
        _set_status(session, wo, user_id, target, "RESUME")
        session.commit()


def add_task(company_id: int, user_id: int, work_order_id: int, task: TaskInput) -> int:
    _validate_task(task)
    with new_session() as session:
        c.require(company_id, user_id, c.FORM_EXECUTE, session=session)
        wo = lock(session, company_id, work_order_id)
        _ensure(wo, _EDITABLE, "افزودن ردیف چک‌لیست")
        seq = (session.scalar(select(func.max(WorkOrderTask.seq)).where(WorkOrderTask.work_order_id == work_order_id)) or 0) + 1
        row = _task_row(work_order_id, seq, task)
        session.add(row)
        session.flush()
        c.audit(session, company_id, user_id, ENTITY, work_order_id, "TASK_ADD", {"task_id": row.task_id, "seq": seq})
        session.commit()
        return row.task_id


def record_task(company_id: int, user_id: int, task_id: int, done: bool = True, value_numeric=None,
                value_text: str | None = None) -> bool | None:
    """نتیجهٔ ردیف چک‌لیست؛ خروجی = در محدودهٔ مجاز بودن (برای مقدار عددی) یا انجام‌شدن."""
    with new_session() as session:
        c.require(company_id, user_id, c.FORM_EXECUTE, session=session)
        task = session.get(WorkOrderTask, task_id)
        if task is None:
            raise ValueError("ردیف چک‌لیست نامعتبر است.")
        wo = lock(session, company_id, task.work_order_id)
        _ensure(wo, ("IN_PROGRESS",), "ثبت نتیجهٔ چک‌لیست")
        old = [task.is_done, str(task.value_numeric) if task.value_numeric is not None else task.value_text]
        if task.result_type == "NUMERIC":
            if value_numeric is None or value_numeric == "":
                raise ValueError("مقدار اندازه‌گیری‌شده را وارد کنید.")
            v = c.dec(value_numeric)
            task.value_numeric = v
            task.is_ok = (task.min_value is None or v >= task.min_value) and (task.max_value is None or v <= task.max_value)
            task.is_done = True
        elif task.result_type == "TEXT":
            if not (value_text or "").strip():
                raise ValueError("شرح نتیجه را بنویسید.")
            task.value_text, task.is_done, task.is_ok = value_text.strip()[:500], True, True
        else:
            task.is_done, task.is_ok = bool(done), bool(done)
            task.value_text = (value_text or "").strip()[:500] or None
        task.done_by_user_id, task.done_at = user_id, c.now()
        session.flush()
        c.audit(session, company_id, user_id, ENTITY, wo.work_order_id, "TASK",
                {"task_id": task_id, "seq": task.seq, "result": [old, [task.is_done, str(task.value_numeric)
                                                                      if task.value_numeric is not None else task.value_text]],
                 "is_ok": task.is_ok})
        session.commit()
        return task.is_ok


def add_labor(company_id: int, user_id: int, work_order_id: int, worker_user_id: int, work_date: datetime.date, hours,
              note: str | None = None, idempotency_key: str | None = None) -> int:
    """ساعت کار تکنسین؛ مبلغ = ساعت × نرخ دستمزد همان کارمند (اطلاعاتی؛ حقوق در حقوق‌ودستمزد هزینه می‌شود)."""
    from peecha.db.models.hr import Employee
    from peecha.db.models.production import WorkCenter
    from peecha.services.production import master as pm

    hours = c.dec(hours)
    if hours <= 0 or hours > 24:
        raise ValueError("ساعت کار باید بین ۰ و ۲۴ باشد.")
    with new_session() as session:
        c.require(company_id, user_id, c.FORM_EXECUTE, session=session)
        wo = lock(session, company_id, work_order_id)
        if idempotency_key:
            done = session.scalar(select(WorkOrderLabor.labor_id).where(WorkOrderLabor.work_order_id == work_order_id,
                                                                        WorkOrderLabor.idempotency_key == idempotency_key))
            if done:
                return done
        _ensure(wo, ("IN_PROGRESS", "ON_HOLD", "COMPLETED"), "ثبت ساعت کار")
        employee_id = session.scalar(select(Employee.employee_id).where(Employee.company_id == company_id,
                                                                        Employee.user_id == worker_user_id))
        asset = session.get(Asset, wo.asset_id)
        wc_id = session.scalar(select(WorkCenter.work_center_id).where(WorkCenter.company_id == company_id,
                                                                       WorkCenter.code == asset.work_center_code)) \
            if asset.work_center_code else None
        rate, _ot = pm.labor_rate_for(session, company_id, employee_id, None if employee_id else wc_id)
        row = WorkOrderLabor(work_order_id=work_order_id, user_id=worker_user_id, employee_id=employee_id, work_date=work_date,
                             hours=hours, hourly_rate=c.money(rate), amount=c.money(hours * rate),
                             note=(note or "").strip() or None, idempotency_key=idempotency_key, created_by_user_id=user_id)
        session.add(row)
        session.flush()
        c.audit(session, company_id, user_id, ENTITY, work_order_id, "LABOR",
                {"labor_id": row.labor_id, "user_id": worker_user_id, "hours": str(hours), "amount": str(row.amount)})
        session.commit()
        return row.labor_id


def _missing_tasks(session, work_order_id: int) -> list[WorkOrderTask]:
    return list(session.scalars(select(WorkOrderTask).where(WorkOrderTask.work_order_id == work_order_id,
                                                            WorkOrderTask.is_mandatory.is_(True),
                                                            WorkOrderTask.is_done.is_(False)).order_by(WorkOrderTask.seq)))


def complete(company_id: int, user_id: int, work_order_id: int, completion_note: str, *, at: datetime.datetime | None = None,
             problem_code_id: int | None = None, cause_code_id: int | None = None, remedy_code_id: int | None = None,
             root_cause_note: str | None = None) -> None:
    """ثبت «انجام‌شده» توسط تکنسین؛ ماشین هنوز آماده نیست تا آزمون و آماده‌به‌کاری ثبت شود."""
    if not (completion_note or "").strip():
        raise ValueError("شرح کار انجام‌شده را بنویسید.")
    at = c.aware(at) or c.now()
    with new_session() as session:
        c.require(company_id, user_id, c.FORM_EXECUTE, session=session)
        wo = lock(session, company_id, work_order_id)
        _ensure(wo, ("IN_PROGRESS",), "ثبت انجام کار")
        missing = _missing_tasks(session, work_order_id)
        if missing:
            raise ValueError("ردیف‌های الزامی چک‌لیست هنوز انجام نشده‌اند: " + "، ".join(str(t.seq) for t in missing[:10]))
        for kind, code_id in (("PROBLEM", problem_code_id), ("CAUSE", cause_code_id), ("REMEDY", remedy_code_id)):
            if code_id is not None:
                fc = session.get(FailureCode, code_id)
                if fc is None or fc.company_id != company_id or fc.kind_code != kind:
                    raise ValueError(f"کد «{c.FAILURE_KIND_LABELS[kind]}» نامعتبر است.")
        if wo.actual_start and at < c.aware(wo.actual_start):
            raise ValueError("زمان پایان کار نمی‌تواند پیش از شروع آن باشد.")
        wo.actual_end, wo.completed_by_user_id, wo.completed_at = at, user_id, c.now()
        wo.completion_note = completion_note.strip()[:1000]
        wo.problem_code_id, wo.cause_code_id, wo.remedy_code_id = problem_code_id, cause_code_id, remedy_code_id
        wo.root_cause_note = (root_cause_note or "").strip()[:1000] or None
        wo.verification_result = wo.verification_note = None
        wo.verified_by_user_id = wo.verified_at = None
        _set_status(session, wo, user_id, "COMPLETED", "COMPLETE", actual_end=at.isoformat())
        session.commit()


def _technicians(session, work_order_id: int) -> set[int]:
    return set(session.scalars(select(WorkOrderTechnician.user_id).where(WorkOrderTechnician.work_order_id == work_order_id)))


def verify(company_id: int, user_id: int, work_order_id: int, result: str, note: str | None = None) -> None:
    """آزمون و تأیید ایمنی: «قبول» → آزمون‌شده؛ «مردود» → برگشت به اجرا با علت."""
    if result not in c.VERIFY_LABELS:
        raise ValueError("نتیجهٔ آزمون نامعتبر است.")
    if result == "FAIL" and not (note or "").strip():
        raise ValueError("علت مردودی آزمون را بنویسید.")
    with new_session() as session:
        c.require(company_id, user_id, c.FORM_VERIFY, session=session)
        wo = lock(session, company_id, work_order_id)
        _ensure(wo, ("COMPLETED",), "آزمون و تأیید")
        if c.is_on(company_id, stock_controls.MNT_SEPARATE_VERIFY, session) and \
                (user_id == wo.completed_by_user_id or user_id in _technicians(session, work_order_id)):
            raise ValueError("آزمون و تأیید باید توسط فردی غیر از تکنسین همین دستور کار ثبت شود.")
        if result == "PASS":
            bad = list(session.scalars(select(WorkOrderTask).where(WorkOrderTask.work_order_id == work_order_id,
                                                                   WorkOrderTask.is_safety.is_(True),
                                                                   WorkOrderTask.is_ok.isnot(True))))
            if bad:
                raise ValueError("ردیف‌های ایمنی چک‌لیست قبول نشده‌اند: " + "، ".join(str(t.seq) for t in bad[:10]))
        wo.verification_result, wo.verification_note = result, (note or "").strip()[:1000] or None
        wo.verified_by_user_id, wo.verified_at = user_id, c.now()
        if result == "PASS":
            _set_status(session, wo, user_id, "VERIFIED", "VERIFY", result=result, note=note)
        else:
            wo.completed_by_user_id = wo.completed_at = None
            wo.actual_end = None
            _set_status(session, wo, user_id, "IN_PROGRESS", "VERIFY", result=result, note=note)
        session.commit()


def linked_downtime(session, wo: WorkOrder) -> DowntimeEvent | None:
    ev = session.scalar(select(DowntimeEvent).where(DowntimeEvent.work_order_id == wo.work_order_id,
                                                    DowntimeEvent.available_at.is_(None)).with_for_update())
    if ev is None and wo.request_id is not None:
        ev = session.scalar(select(DowntimeEvent).where(DowntimeEvent.request_id == wo.request_id,
                                                        DowntimeEvent.available_at.is_(None)).with_for_update())
    return ev


def release_machine(company_id: int, user_id: int, work_order_id: int, available_at: datetime.datetime | None = None,
                    note: str | None = None) -> None:
    """آماده‌به‌کاری ماشین — فقط پس از آزمون «قبول»."""
    with new_session() as session:
        c.require(company_id, user_id, c.FORM_VERIFY, session=session)
        wo = lock(session, company_id, work_order_id)
        if wo.status_code != "VERIFIED" or wo.verification_result != "PASS":
            raise ValueError("آماده‌به‌کاری فقط پس از آزمون و تأیید «قبول» دستور کار ثبت می‌شود.")
        ev = linked_downtime(session, wo)
        if ev is None:
            raise ValueError("برای این دستور کار توقف بازی ثبت نشده است.")
        ev.work_order_id = ev.work_order_id or wo.work_order_id
        availability.release(session, company_id, user_id, ev, available_at, note)
        c.audit(session, company_id, user_id, ENTITY, work_order_id, "RELEASE_MACHINE",
                {"downtime_id": ev.downtime_id, "available_at": ev.available_at.isoformat()})
        session.commit()


def close_blockers(session, wo: WorkOrder) -> list[str]:
    """دلایل بسته‌نشدن (برای پیام و برای نمایش در صفحه)."""
    out = []
    if wo.status_code != "VERIFIED" or wo.verification_result != "PASS":
        out.append("آزمون و تأیید «قبول» ثبت نشده است.")
    if _missing_tasks(session, wo.work_order_id):
        out.append("ردیف‌های الزامی چک‌لیست کامل نیست.")
    if linked_downtime(session, wo) is not None:
        out.append("آماده‌به‌کاری ماشین ثبت نشده است.")
    pending = session.scalar(select(func.count()).where(WorkOrderCost.work_order_id == wo.work_order_id,
                                                        WorkOrderCost.status_code.in_(("DRAFT", "PENDING_APPROVAL")),
                                                        WorkOrderCost.accounting_code != "NONE"))
    if pending:
        out.append(f"{pending} ردیف هزینه هنوز تعیین تکلیف مالی نشده یا منتظر تأیید مالی است.")
    return out


def close(company_id: int, user_id: int, work_order_id: int, note: str | None = None) -> None:
    from peecha.services.maintenance import parts, pm

    with new_session() as session:
        c.require(company_id, user_id, c.FORM_VERIFY, session=session)
        wo = lock(session, company_id, work_order_id)
        _ensure(wo, ("VERIFIED",), "بستن")
        from peecha.services.maintenance import costs

        costs.refresh_pending(session, wo.work_order_id)
        blockers = close_blockers(session, wo)
        if blockers:
            raise ValueError("دستور کار بسته نمی‌شود: " + " ".join(blockers))
        parts.release_reservations(session, wo.work_order_id)
        wo.closed_by_user_id, wo.closed_at = user_id, c.now()
        if wo.pm_plan_id:
            pm.on_work_order_closed(session, wo, user_id)
        _set_status(session, wo, user_id, "CLOSED", "CLOSE", note=note)
        session.commit()


def reopen(company_id: int, user_id: int, work_order_id: int, reason: str) -> None:
    """بازگشایی مجاز (با علت): برگشت به اجرا؛ آزمون دوباره لازم است."""
    if not (reason or "").strip():
        raise ValueError("علت بازگشایی الزامی است.")
    with new_session() as session:
        c.require(company_id, user_id, c.FORM_VERIFY, session=session)
        wo = lock(session, company_id, work_order_id)
        _ensure(wo, ("CLOSED",), "بازگشایی")
        wo.reopened_count = (wo.reopened_count or 0) + 1
        wo.verification_result = wo.verification_note = None
        wo.verified_by_user_id = wo.verified_at = None
        wo.completed_by_user_id = wo.completed_at = None
        wo.closed_by_user_id = wo.closed_at = None
        wo.actual_end = None
        _set_status(session, wo, user_id, "IN_PROGRESS", "REOPEN", reason=reason.strip(), reopened_count=wo.reopened_count)
        session.commit()


def cancel(company_id: int, user_id: int, work_order_id: int, reason: str) -> None:
    from peecha.services.maintenance import parts

    if not (reason or "").strip():
        raise ValueError("علت لغو الزامی است.")
    with new_session() as session:
        c.require(company_id, user_id, c.FORM_PLAN, session=session)
        wo = lock(session, company_id, work_order_id)
        _ensure(wo, _EDITABLE, "لغو")
        if wo.pm_plan_id:
            plan = session.get(PmPlan, wo.pm_plan_id)
            if plan is not None and plan.is_active:
                raise ValueError("دستور کار پیشگیرانه لغو نمی‌شود؛ برای جابه‌جایی سررسید، تعویق با تأیید ثبت کنید.")
        net = session.scalar(select(func.coalesce(func.sum(WorkOrderPart.issued_qty - WorkOrderPart.returned_qty), 0))
                             .where(WorkOrderPart.work_order_id == work_order_id))
        if c.dec(net) > 0:
            raise ValueError("قطعه برای این دستور کار صادر شده است؛ پیش از لغو، قطعه‌های مصرف‌نشده را به انبار برگردانید.")
        financial = session.scalar(select(func.count()).where(WorkOrderCost.work_order_id == work_order_id,
                                                              WorkOrderCost.status_code.in_(("PENDING_APPROVAL", "POSTED",
                                                                                             "LINKED"))))
        if financial:
            raise ValueError("هزینهٔ ثبت‌شده یا منتظر تأیید مالی دارد و لغو نمی‌شود.")
        if linked_downtime(session, wo) is not None:
            raise ValueError("ماشین این دستور کار متوقف است؛ لغو به معنای آماده‌بودن ماشین نیست. "
                             "ابتدا آماده‌به‌کاری را ثبت کنید یا توقف را به دستور کار دیگری بسپارید.")
        parts.release_reservations(session, work_order_id)
        for cost in session.scalars(select(WorkOrderCost).where(WorkOrderCost.work_order_id == work_order_id,
                                                                WorkOrderCost.status_code == "DRAFT")):
            cost.status_code = "CANCELLED"
        _set_status(session, wo, user_id, "CANCELLED", "CANCEL", reason=reason.strip())
        session.commit()


# --- خواندن ---------------------------------------------------------------------------------
def _row(wo: WorkOrder, asset: Asset, names: dict[int, str]) -> SimpleNamespace:
    return SimpleNamespace(
        work_order_id=wo.work_order_id, wo_no=wo.wo_no, asset_id=asset.asset_id, asset_code=asset.asset_code,
        asset_name=asset.name, asset_label=c.asset_label(asset), production_line=asset.production_line,
        work_type_code=wo.work_type_code, work_type_label=c.WORK_TYPE_LABELS[wo.work_type_code],
        priority_code=wo.priority_code, priority_label=c.PRIORITY_LABELS[wo.priority_code], title=wo.title,
        status_code=wo.status_code, status_label=c.WO_STATUS_LABELS[wo.status_code], hold_reason=wo.hold_reason,
        responsible_user_id=wo.responsible_user_id, responsible_name=names.get(wo.responsible_user_id, ""),
        planned_start=wo.planned_start, planned_end=wo.planned_end, actual_start=wo.actual_start, actual_end=wo.actual_end,
        request_id=wo.request_id, pm_plan_id=wo.pm_plan_id, pm_due_date=wo.pm_due_date, requires_shutdown=wo.requires_shutdown,
        created_at=wo.created_at, closed_at=wo.closed_at, reopened_count=wo.reopened_count)


def board(company_id: int, *, status_codes: tuple[str, ...] | None = None, asset_id: int | None = None,
          work_type_code: str | None = None, responsible_user_id: int | None = None, technician_user_id: int | None = None,
          include_closed: bool = False, search: str | None = None, limit: int = 500) -> list[SimpleNamespace]:
    with new_session() as session:
        q = select(WorkOrder, Asset).join(Asset, Asset.asset_id == WorkOrder.asset_id).where(WorkOrder.company_id == company_id)
        if status_codes:
            q = q.where(WorkOrder.status_code.in_(status_codes))
        elif not include_closed:
            q = q.where(WorkOrder.status_code.in_(c.OPEN_WO))
        if asset_id:
            q = q.where(WorkOrder.asset_id == asset_id)
        if work_type_code:
            q = q.where(WorkOrder.work_type_code == work_type_code)
        if responsible_user_id:
            q = q.where(WorkOrder.responsible_user_id == responsible_user_id)
        if technician_user_id:
            q = q.where(WorkOrder.work_order_id.in_(select(WorkOrderTechnician.work_order_id).where(
                WorkOrderTechnician.user_id == technician_user_id)))
        if search:
            like = f"%{search.strip()}%"
            q = q.where(WorkOrder.title.ilike(like) | Asset.asset_code.ilike(like) | Asset.name.ilike(like))
        rows = session.execute(q.order_by(WorkOrder.wo_no.desc()).limit(limit)).all()
        names = c.user_names(session, [wo.responsible_user_id for wo, _a in rows])
        return [_row(wo, a, names) for wo, a in rows]


def my_work(company_id: int, user_id: int) -> list[SimpleNamespace]:
    """دستورهای باز واگذارشده به من یا به مسئولیت من (صفحهٔ تکنسین موبایل)."""
    mine = {r.work_order_id: r for r in board(company_id, technician_user_id=user_id)}
    for r in board(company_id, responsible_user_id=user_id):
        mine.setdefault(r.work_order_id, r)
    return sorted(mine.values(), key=lambda r: (["URGENT", "HIGH", "NORMAL", "LOW"].index(r.priority_code), r.wo_no))


def get(company_id: int, work_order_id: int) -> SimpleNamespace:
    from peecha.services.maintenance import costs

    with new_session() as session:
        wo = session.get(WorkOrder, work_order_id)
        if wo is None or wo.company_id != company_id:
            raise ValueError("دستور کار نامعتبر است.")
        costs.refresh_pending(session, work_order_id)
        session.commit()
        asset = session.get(Asset, wo.asset_id)
        techs = list(session.scalars(select(WorkOrderTechnician).where(WorkOrderTechnician.work_order_id == work_order_id)))
        tasks = list(session.scalars(select(WorkOrderTask).where(WorkOrderTask.work_order_id == work_order_id)
                                     .order_by(WorkOrderTask.seq)))
        labor = list(session.scalars(select(WorkOrderLabor).where(WorkOrderLabor.work_order_id == work_order_id)
                                     .order_by(WorkOrderLabor.work_date, WorkOrderLabor.labor_id)))
        names = c.user_names(session, [wo.responsible_user_id, wo.completed_by_user_id, wo.verified_by_user_id,
                                       wo.closed_by_user_id, wo.created_by_user_id] + [t.user_id for t in techs]
                             + [ln.user_id for ln in labor] + [t.done_by_user_id for t in tasks])
        out = _row(wo, asset, names)
        codes = {f.failure_code_id: f"{f.code} — {f.name}" for f in session.scalars(select(FailureCode).where(
            FailureCode.failure_code_id.in_([x for x in (wo.problem_code_id, wo.cause_code_id, wo.remedy_code_id) if x])))}
        request = session.get(WorkRequest, wo.request_id) if wo.request_id else None
        out.__dict__.update(
            description=wo.description, estimated_hours=wo.estimated_hours, safety_instructions=wo.safety_instructions,
            required_skills=wo.required_skills, completion_note=wo.completion_note, root_cause_note=wo.root_cause_note,
            problem_code_id=wo.problem_code_id, cause_code_id=wo.cause_code_id, remedy_code_id=wo.remedy_code_id,
            problem_label=codes.get(wo.problem_code_id, ""), cause_label=codes.get(wo.cause_code_id, ""),
            remedy_label=codes.get(wo.remedy_code_id, ""), capital_candidate=wo.capital_candidate,
            completed_by=names.get(wo.completed_by_user_id, ""), completed_at=wo.completed_at,
            verification_result=wo.verification_result, verification_label=c.VERIFY_LABELS.get(wo.verification_result, ""),
            verification_note=wo.verification_note, verified_by=names.get(wo.verified_by_user_id, ""), verified_at=wo.verified_at,
            closed_by=names.get(wo.closed_by_user_id, ""), created_by=names.get(wo.created_by_user_id, ""),
            request_no=request.request_no if request else None, completed_by_user_id=wo.completed_by_user_id,
            technicians=[SimpleNamespace(user_id=t.user_id, name=names.get(t.user_id, ""), is_lead=t.is_lead) for t in techs],
            tasks=[SimpleNamespace(task_id=t.task_id, seq=t.seq, description=t.description, result_type=t.result_type,
                                   result_label=c.RESULT_TYPE_LABELS[t.result_type], min_value=t.min_value,
                                   max_value=t.max_value, uom_label=t.uom_label, is_mandatory=t.is_mandatory,
                                   is_safety=t.is_safety, is_done=t.is_done, value_numeric=t.value_numeric,
                                   value_text=t.value_text, is_ok=t.is_ok, done_by=names.get(t.done_by_user_id, ""),
                                   done_at=t.done_at) for t in tasks],
            labor=[SimpleNamespace(labor_id=ln.labor_id, user_id=ln.user_id, name=names.get(ln.user_id, ""),
                                   work_date=ln.work_date, hours=ln.hours, hourly_rate=ln.hourly_rate, amount=ln.amount,
                                   note=ln.note) for ln in labor],
            downtime=[d for d in availability.list_downtimes(company_id, asset_id=wo.asset_id)
                      if d.work_order_id == work_order_id or (wo.request_id and d.request_id == wo.request_id)],
            blockers=close_blockers(session, wo) if wo.status_code in c.OPEN_WO else [],
        )
    from peecha.services.maintenance import parts

    out.parts = parts.list_parts(company_id, work_order_id)
    out.costs = costs.list_costs(company_id, work_order_id)
    out.cost_summary = costs.summary(company_id, work_order_id)
    return out


def history(company_id: int, work_order_id: int) -> list[SimpleNamespace]:
    """تاریخچهٔ وضعیت و رویدادها (از همان ردپای سیستم)."""
    labels = {"CREATE": "ایجاد", "PLAN": "برنامه‌ریزی", "ASSIGN": "واگذاری", "REFER": "ارجاع", "START": "شروع",
              "HOLD": "توقف موقت", "RESUME": "ادامه", "TASK": "نتیجهٔ چک‌لیست", "TASK_ADD": "افزودن ردیف چک‌لیست",
              "LABOR": "ساعت کار", "COMPLETE": "انجام‌شده", "VERIFY": "آزمون و تأیید", "RELEASE_MACHINE": "آماده‌به‌کاری ماشین",
              "CLOSE": "بستن", "REOPEN": "بازگشایی", "CANCEL": "لغو", "UPDATE": "ویرایش", "PART_ISSUE": "صدور قطعه",
              "PART_RETURN": "برگشت قطعه", "PART_ADD": "افزودن قطعه", "PART_RESERVE": "رزرو قطعه",
              "PURCHASE_REQUEST": "درخواست خرید قطعه", "COST_ADD": "ثبت هزینه", "COST_POST": "ثبت مالی هزینه",
              "COST_LINK": "اتصال به فاکتور خرید", "COST_NONE": "هزینهٔ بدون ثبت مالی", "COST_CANCEL": "لغو هزینه",
              "ATTACH": "پیوست"}
    with new_session() as session:
        rows = list(session.scalars(select(ActivityLog).where(ActivityLog.company_id == company_id, ActivityLog.entity_type == ENTITY,
                                                              ActivityLog.entity_id == work_order_id).order_by(ActivityLog.log_id)))
        names = c.user_names(session, [r.user_id for r in rows])
        out = []
        for r in rows:
            ch = dict(r.changes or {})
            op = ch.pop("operation", r.action)
            status = ch.get("status_code")
            out.append(SimpleNamespace(at=r.created_at, user=names.get(r.user_id, ""), operation=op,
                                       operation_label=labels.get(op, op),
                                       from_status=c.WO_STATUS_LABELS.get(status[0], "") if isinstance(status, list) and status[0] else "",
                                       to_status=c.WO_STATUS_LABELS.get(status[1], "") if isinstance(status, list) else "",
                                       note=ch.get("reason") or ch.get("note") or "", changes=ch))
        return out
