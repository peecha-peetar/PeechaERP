"""منابع انسانی: مرخصی، اضافه‌کاری و درخواست عمومی کارکنان."""

from __future__ import annotations

import decimal

from sqlalchemy import text

from peecha.db.base import new_session
from peecha.db.models.hr import Employee, LeaveRequest
from peecha.db.models.payroll import OvertimeEntry
from peecha.services.workflow import model_events, registry
from peecha.services.workflow.adapters._common import jdate, user_name
from peecha.services.workflow.common import WorkflowError, display
from peecha.services.workflow.model_events import Watch
from peecha.services.workflow.registry import ActionContext, ActionSpec, EntityAdapter, FieldSpec, ParamSpec


def _emp(session, company_id: int, employee_id: int) -> Employee:
    emp = session.get(Employee, employee_id)
    if emp is None or emp.company_id != company_id:
        raise WorkflowError("کارمند پیدا نشد.")
    return emp


def _reason(ctx: ActionContext) -> str:
    return (ctx.params.get("reason") or ctx.context.get("last_comment") or "").strip()


# --- مرخصی -------------------------------------------------------------------------------------------------
def leave_context(company_id: int, leave_request_id: int) -> dict:
    from peecha.services import hr_leave

    try:
        r = hr_leave.get(company_id, leave_request_id)
    except ValueError as exc:
        raise WorkflowError(str(exc)) from exc
    with new_session() as session:
        emp = _emp(session, company_id, r.employee_id)
        return {"leave_request_id": r.leave_request_id, "employee_id": r.employee_id, "employee_name": r.employee_name,
                "employee_user_id": emp.user_id, "leave_type": r.leave_type, "leave_type_label": r.leave_type_label,
                "from_date": r.from_date, "to_date": r.to_date, "days": r.days, "hours": r.hours, "reason": r.reason,
                "status": r.status_code, "requested_by": r.requested_by_user_id or emp.user_id,
                "requested_by_name": user_name(session, r.requested_by_user_id)}


def _leave_approve(ctx: ActionContext) -> dict:
    from peecha.services import hr_leave

    hr_leave.approve(ctx.company_id, int(ctx.entity_id), ctx.user_id, _reason(ctx))
    return {"status": "APPROVED"}


def _leave_reject(ctx: ActionContext) -> dict:
    from peecha.services import hr_leave

    hr_leave.reject(ctx.company_id, int(ctx.entity_id), ctx.user_id, _reason(ctx))
    return {"status": "REJECTED"}


def _leave_status(*statuses: str):
    def check(company_id: int, leave_request_id: int) -> bool:
        with new_session() as session:
            r = session.get(LeaveRequest, leave_request_id)
            return r is not None and r.status_code in statuses
    return check


def _leave_card(company_id: int, leave_request_id: int) -> list[tuple[str, str]]:
    c = leave_context(company_id, leave_request_id)
    span = f"{jdate(c['from_date'])} تا {jdate(c['to_date'])}"
    amount = f"{display(c['hours'])} ساعت" if c["hours"] else f"{display(c['days'])} روز"
    return [("کارمند", c["employee_name"]), ("نوع مرخصی", c["leave_type_label"]), ("بازه", span), ("مدت", amount),
            ("دلیل", c["reason"] or "—")]


registry.register_adapter(EntityAdapter(
    "LEAVE_REQUEST", "درخواست مرخصی", "HR", leave_context,
    fields=(FieldSpec("days", "تعداد روز", "number"), FieldSpec("hours", "تعداد ساعت", "number"),
            FieldSpec("leave_type", "نوع مرخصی", "choice", {"ANNUAL": "استحقاقی", "SICK": "استعلاجی", "UNPAID": "بدون حقوق",
                                                              "HOURLY": "ساعتی", "MISSION": "مأموریت"}),
            FieldSpec("employee_user_id", "کاربر کارمند", "user"), FieldSpec("from_date", "از تاریخ", "date"),
            FieldSpec("to_date", "تا تاریخ", "date")),
    events={"LEAVE_REQUEST_CREATED": "ثبت درخواست مرخصی", "LEAVE_REQUEST_SUBMITTED": "ارسال درخواست مرخصی",
            "LEAVE_REQUEST_APPROVED": "تایید مرخصی", "LEAVE_REQUEST_REJECTED": "رد مرخصی"},
    actions={"approve": ActionSpec("approve", "تایید مرخصی", _leave_approve, is_done=_leave_status("APPROVED")),
             "reject": ActionSpec("reject", "رد مرخصی", _leave_reject, is_done=_leave_status("REJECTED"),
                                  params=(ParamSpec("reason", "دلیل"),))},
    title=lambda c: f"مرخصی {c.get('leave_type_label')} — {c.get('employee_name')}",
    owner=lambda cid, eid: leave_context(cid, eid)["requested_by"], approval_context=_leave_card,
    open_nav="HR_LEAVE_REQUESTS", open_method="open_request", submitter_field="requested_by", gate_statuses=("APPROVED",),
    gate_label="تا تایید فرایند، مرخصی تایید نمی‌شود", form_code="hr_leave_requests"))

model_events.watch(Watch(LeaveRequest, lambda r: "LEAVE_REQUEST", actor=lambda r: r.requested_by_user_id))


# --- اضافه‌کاری --------------------------------------------------------------------------------------------
def overtime_context(company_id: int, overtime_entry_id: int) -> dict:
    with new_session() as session:
        e = session.get(OvertimeEntry, overtime_entry_id)
        if e is None:
            raise WorkflowError("اضافه‌کاری پیدا نشد.")
        emp = _emp(session, company_id, e.employee_id)
        return {"overtime_entry_id": e.overtime_entry_id, "employee_id": e.employee_id,
                "employee_name": f"{emp.first_name} {emp.last_name}".strip(), "employee_user_id": emp.user_id,
                "hours": decimal.Decimal(e.hours), "period_id": e.period_id, "status": e.status}


def _ot_set(status: str):
    def run(ctx: ActionContext) -> dict:
        from peecha.services import payroll_overtime

        payroll_overtime.set_overtime_entry_status(int(ctx.entity_id), status)
        return {"status": status}
    return run


def _ot_status(*statuses: str):
    def check(company_id: int, entry_id: int) -> bool:
        with new_session() as session:
            e = session.get(OvertimeEntry, entry_id)
            return e is not None and e.status in statuses
    return check


def _ot_company(conn, e: OvertimeEntry) -> int | None:
    return conn.execute(text("SELECT company_id FROM hr.employees WHERE employee_id = :e"), {"e": e.employee_id}).scalar()


registry.register_adapter(EntityAdapter(
    "OVERTIME", "اضافه‌کاری", "HR", overtime_context,
    fields=(FieldSpec("hours", "ساعت اضافه‌کاری", "number"), FieldSpec("employee_user_id", "کاربر کارمند", "user"),
            FieldSpec("period_id", "دورهٔ حقوق", "number")),
    events={"OVERTIME_CREATED": "ثبت اضافه‌کاری", "OVERTIME_PENDING_APPROVAL": "اضافه‌کاری در انتظار تایید",
            "OVERTIME_APPROVED": "تایید اضافه‌کاری"},
    actions={"approve": ActionSpec("approve", "تایید اضافه‌کاری", _ot_set("APPROVED"), is_done=_ot_status("APPROVED")),
             "reject": ActionSpec("reject", "رد اضافه‌کاری", _ot_set("REJECTED"), is_done=_ot_status("REJECTED"))},
    title=lambda c: f"اضافه‌کاری {display(c.get('hours'))} ساعت — {c.get('employee_name')}",
    owner=lambda cid, eid: overtime_context(cid, eid)["employee_user_id"],
    approval_context=lambda cid, eid: (lambda c: [("کارمند", c["employee_name"]), ("ساعت", display(c["hours"]))])(
        overtime_context(cid, eid)),
    open_nav="HR_PAYROLL_OVERTIME", submitter_field="employee_user_id", gate_statuses=("APPROVED",),
    gate_label="تا تایید فرایند، اضافه‌کاری تایید نمی‌شود", form_code="payroll_overtime_entries"))

model_events.watch(Watch(OvertimeEntry, lambda e: "OVERTIME", status_attr="status", company_id=_ot_company))


# --- درخواست عمومی کارکنان (گواهی اشتغال، تجهیزات، ...) --------------------------------------------------------
def employee_context(company_id: int, employee_id: int) -> dict:
    with new_session() as session:
        emp = _emp(session, company_id, employee_id)
        return {"employee_id": emp.employee_id, "employee_code": emp.employee_code,
                "employee_name": f"{emp.first_name} {emp.last_name}".strip(), "employee_user_id": emp.user_id,
                "hire_date": emp.hire_date, "status": emp.status}


registry.register_adapter(EntityAdapter(
    "EMPLOYEE", "درخواست کارکنان", "HR", employee_context,
    fields=(FieldSpec("employee_user_id", "کاربر کارمند", "user"), FieldSpec("hire_date", "تاریخ استخدام", "date")),
    title=lambda c: f"درخواست {c.get('employee_name')}",
    owner=lambda cid, eid: employee_context(cid, eid)["employee_user_id"],
    approval_context=lambda cid, eid: (lambda c: [("کارمند", c["employee_name"]), ("کد پرسنلی", c["employee_code"]),
                                                  ("تاریخ استخدام", jdate(c["hire_date"]))])(employee_context(cid, eid)),
    submitter_field="employee_user_id", form_code="hr_leave_requests"))
