"""R295: درخواست مرخصی — ثبت، ارسال، تصمیم و لغو. تایید چندمرحله‌ای از موتور گردش کار (قالب «تایید مرخصی»)."""

from __future__ import annotations

import datetime
import decimal
from dataclasses import dataclass

from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.hr import Employee, LeaveRequest

LEAVE_TYPES = {"ANNUAL": "استحقاقی", "SICK": "استعلاجی", "UNPAID": "بدون حقوق", "HOURLY": "ساعتی", "MISSION": "مأموریت"}
STATUSES = {"DRAFT": "پیش‌نویس", "SUBMITTED": "در انتظار تایید", "APPROVED": "تاییدشده", "REJECTED": "ردشده",
            "CANCELLED": "لغوشده"}


@dataclass
class LeaveRow:
    leave_request_id: int
    employee_id: int
    employee_name: str
    leave_type: str
    leave_type_label: str
    from_date: datetime.date
    to_date: datetime.date
    days: decimal.Decimal
    hours: decimal.Decimal | None
    reason: str
    status_code: str
    status_label: str
    requested_by_user_id: int | None
    decision_note: str


def _employee(session, company_id: int, employee_id: int) -> Employee:
    emp = session.get(Employee, employee_id)
    if emp is None or emp.company_id != company_id:
        raise ValueError("کارمند یافت نشد.")
    return emp


def employee_of_user(company_id: int, user_id: int) -> int | None:
    with new_session() as session:
        return session.scalar(select(Employee.employee_id).where(Employee.company_id == company_id, Employee.user_id == user_id))


def create_request(company_id: int, user_id: int, employee_id: int, leave_type: str, from_date: datetime.date,
                   to_date: datetime.date, *, hours: decimal.Decimal | None = None, reason: str = "",
                   submit: bool = False) -> int:
    if leave_type not in LEAVE_TYPES:
        raise ValueError("نوع مرخصی نامعتبر است.")
    if not from_date or not to_date or to_date < from_date:
        raise ValueError("تاریخ پایان مرخصی نباید پیش از تاریخ شروع باشد.")
    if leave_type == "HOURLY" and (hours is None or hours <= 0):
        raise ValueError("برای مرخصی ساعتی، تعداد ساعت را وارد کنید.")
    with new_session() as session:
        _employee(session, company_id, employee_id)
        overlap = session.scalar(select(LeaveRequest.leave_request_id).where(
            LeaveRequest.company_id == company_id, LeaveRequest.employee_id == employee_id,
            LeaveRequest.status_code.in_(("SUBMITTED", "APPROVED")), LeaveRequest.from_date <= to_date,
            LeaveRequest.to_date >= from_date))
        if overlap and leave_type != "HOURLY":
            raise ValueError("برای این بازه یک مرخصی دیگر ثبت شده است.")
        days = decimal.Decimal(0) if leave_type == "HOURLY" else decimal.Decimal((to_date - from_date).days + 1)
        row = LeaveRequest(company_id=company_id, employee_id=employee_id, leave_type=leave_type, from_date=from_date,
                           to_date=to_date, hours=hours, days=days, reason=(reason or "").strip() or None,
                           status_code="SUBMITTED" if submit else "DRAFT", requested_by_user_id=user_id)
        session.add(row)
        session.commit()
        return row.leave_request_id


def _transition(company_id: int, leave_request_id: int, allowed: tuple[str, ...], to: str, user_id: int | None = None,
                note: str | None = None) -> None:
    with new_session() as session:
        row = session.scalar(select(LeaveRequest).where(LeaveRequest.leave_request_id == leave_request_id).with_for_update())
        if row is None or row.company_id != company_id:
            raise ValueError("درخواست مرخصی نامعتبر است.")
        if row.status_code not in allowed:
            raise ValueError(f"درخواست در وضعیت «{STATUSES[row.status_code]}» است و این کار مجاز نیست.")
        row.status_code = to
        if to in ("APPROVED", "REJECTED"):
            row.decided_by_user_id, row.decided_at = user_id, datetime.datetime.now()
            row.decision_note = (note or "").strip() or None
        session.commit()


def submit(company_id: int, leave_request_id: int) -> None:
    _transition(company_id, leave_request_id, ("DRAFT",), "SUBMITTED")


def approve(company_id: int, leave_request_id: int, user_id: int | None, note: str = "") -> None:
    _transition(company_id, leave_request_id, ("SUBMITTED",), "APPROVED", user_id, note)


def reject(company_id: int, leave_request_id: int, user_id: int | None, note: str = "") -> None:
    _transition(company_id, leave_request_id, ("SUBMITTED",), "REJECTED", user_id, note)


def cancel(company_id: int, leave_request_id: int) -> None:
    _transition(company_id, leave_request_id, ("DRAFT", "SUBMITTED"), "CANCELLED")


def get(company_id: int, leave_request_id: int) -> LeaveRow:
    rows = list_requests(company_id, ids=[leave_request_id])
    if not rows:
        raise ValueError("درخواست مرخصی نامعتبر است.")
    return rows[0]


def list_requests(company_id: int, *, employee_id: int | None = None, status: str | None = None,
                  ids: list[int] | None = None) -> list[LeaveRow]:
    with new_session() as session:
        q = select(LeaveRequest, Employee).join(Employee, Employee.employee_id == LeaveRequest.employee_id).where(
            LeaveRequest.company_id == company_id)
        if employee_id:
            q = q.where(LeaveRequest.employee_id == employee_id)
        if status:
            q = q.where(LeaveRequest.status_code == status)
        if ids:
            q = q.where(LeaveRequest.leave_request_id.in_(ids))
        return [LeaveRow(r.leave_request_id, r.employee_id, f"{e.first_name} {e.last_name}".strip(), r.leave_type,
                         LEAVE_TYPES[r.leave_type], r.from_date, r.to_date, r.days, r.hours, r.reason or "", r.status_code,
                         STATUSES[r.status_code], r.requested_by_user_id, r.decision_note or "")
                for r, e in session.execute(q.order_by(LeaveRequest.from_date.desc(), LeaveRequest.leave_request_id.desc()))]
