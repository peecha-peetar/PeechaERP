"""R360: سلف‌سرویس کارمند در موبایل — فیش حقوقی قطعی‌شده، درخواست و لغو مرخصی، و حضور و تأخیر خود کاربر.

فقط دادهٔ کارمندی که به همین کاربر وصل است (پروندهٔ پرسنلی ← کاربر)؛ فرم و مجوز جداگانه لازم نیست چون هر کس فقط
پروندهٔ خودش را می‌بیند. نازک: منطق در hr_leave، payroll_payslip و hr_shifts.
"""

from __future__ import annotations

import datetime
import decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.hr import Employee
from peecha.db.models.payroll import PayrollPeriod, Payslip
from peecha.services import hr_leave, hr_shifts, payroll_payslip
from peecha_api.deps import AuthContext, get_current_context, get_idempotency_key
from peecha_api.idempotency import IdempotentReplay, run_idempotent

router = APIRouter(prefix="/self", tags=["self-service"])
_CTX = Depends(get_current_context)
_KEY = Depends(get_idempotency_key)
_VISIBLE_PAYSLIPS = ("FINALIZED", "DELIVERED")


def _employee(ctx: AuthContext) -> Employee:
    employee_id = hr_leave.employee_of_user(ctx.company_id, ctx.user_id)
    if employee_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="پروندهٔ پرسنلی به کاربر شما وصل نیست.")
    with new_session() as session:
        emp = session.get(Employee, employee_id)
        session.expunge(emp)
        return emp


def _num(v) -> str | None:
    return None if v is None else str(v)


@router.get("/profile")
def profile(ctx: AuthContext = _CTX) -> dict:
    e = _employee(ctx)
    return {"employee_id": e.employee_id, "employee_code": e.employee_code, "name": f"{e.first_name} {e.last_name}".strip(),
            "leave_types": hr_leave.LEAVE_TYPES, "leave_statuses": hr_leave.STATUSES}


@router.get("/payslips")
def payslips(ctx: AuthContext = _CTX) -> list[dict]:
    e = _employee(ctx)
    with new_session() as session:
        rows = session.execute(select(Payslip, PayrollPeriod).join(PayrollPeriod, PayrollPeriod.period_id == Payslip.period_id)
                               .where(Payslip.employee_id == e.employee_id, Payslip.status.in_(_VISIBLE_PAYSLIPS))
                               .order_by(PayrollPeriod.jalali_year.desc(), PayrollPeriod.jalali_month.desc(),
                                         Payslip.payslip_id.desc())).all()
    return [{"payslip_id": p.payslip_id, "jalali_year": period.jalali_year, "jalali_month": period.jalali_month,
             "gross_amount": _num(p.gross_amount), "total_deductions": _num(p.total_deductions), "net_pay": _num(p.net_pay),
             "status": p.status} for p, period in rows]


@router.get("/payslips/{payslip_id}")
def payslip(payslip_id: int, ctx: AuthContext = _CTX) -> dict:
    e = _employee(ctx)
    with new_session() as session:
        p = session.get(Payslip, payslip_id)
        mine = p is not None and p.employee_id == e.employee_id and p.status in _VISIBLE_PAYSLIPS
    if not mine:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="این فیش پیدا نشد.")
    d = payroll_payslip.get_printable_payslip(payslip_id)
    line = lambda ln: {"code": ln.code, "label": ln.label, "amount": _num(ln.amount)}  # noqa: E731
    return {"payslip_id": d.payslip_id, "employee_code": d.employee_code, "employee_name": d.employee_full_name,
            "jalali_year": d.jalali_year, "jalali_month": d.jalali_month, "gross_amount": _num(d.gross_amount),
            "total_deductions": _num(d.total_deductions), "net_pay": _num(d.net_pay),
            "earnings": [line(ln) for ln in d.earning_lines], "deductions": [line(ln) for ln in d.deduction_lines]}


def _leave(r: hr_leave.LeaveRow) -> dict:
    return {"leave_request_id": r.leave_request_id, "leave_type": r.leave_type, "leave_type_label": r.leave_type_label,
            "from_date": r.from_date.isoformat(), "to_date": r.to_date.isoformat(), "days": _num(r.days), "hours": _num(r.hours),
            "reason": r.reason, "status_code": r.status_code, "status_label": r.status_label, "decision_note": r.decision_note}


@router.get("/leave")
def my_leave(ctx: AuthContext = _CTX) -> list[dict]:
    return [_leave(r) for r in hr_leave.list_requests(ctx.company_id, employee_id=_employee(ctx).employee_id)]


class LeaveIn(BaseModel):
    leave_type: str
    from_date: datetime.date
    to_date: datetime.date
    hours: decimal.Decimal | None = None
    reason: str = ""


@router.post("/leave", status_code=status.HTTP_201_CREATED)
def request_leave(body: LeaveIn, ctx: AuthContext = _CTX, idempotency_key: str | None = _KEY) -> dict:
    """ثبت و ارسال مرخصی برای تایید (اگر فرایند تایید مرخصی فعال باشد، همان‌جا شروع می‌شود)."""
    employee_id = _employee(ctx).employee_id

    def compute():
        return hr_leave.create_request(ctx.company_id, ctx.user_id, employee_id, body.leave_type, body.from_date, body.to_date,
                                       hours=body.hours, reason=body.reason, submit=True)

    try:
        return run_idempotent(idempotency_key, "self_leave", ctx.user_id, ctx.company_id, status.HTTP_201_CREATED, compute,
                              lambda rid: _leave(hr_leave.get(ctx.company_id, rid)))
    except IdempotentReplay as replay:
        return replay.body
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/leave/{leave_request_id}/cancel")
def cancel_leave(leave_request_id: int, ctx: AuthContext = _CTX) -> dict:
    employee_id = _employee(ctx).employee_id
    try:
        if hr_leave.get(ctx.company_id, leave_request_id).employee_id != employee_id:
            raise ValueError("این درخواست مال شما نیست.")
        hr_leave.cancel(ctx.company_id, leave_request_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _leave(hr_leave.get(ctx.company_id, leave_request_id))


@router.get("/attendance")
def my_attendance(days: int = 31, ctx: AuthContext = _CTX) -> dict:
    """روزهای اخیر با شیفت: وضعیت، ورود و خروج، تأخیر و تعجیل؛ به‌علاوهٔ خلاصهٔ همان بازه."""
    employee_id = _employee(ctx).employee_id
    end = datetime.date.today()
    start = end - datetime.timedelta(days=max(1, min(days, 92)) - 1)
    rows = hr_shifts.daily_report(ctx.company_id, start, end, employee_id)
    summary = next(iter(hr_shifts.summary(ctx.company_id, start, end, employee_id)), None)
    hm = lambda t: t.strftime("%H:%M") if t else None  # noqa: E731
    return {"date_from": start.isoformat(), "date_to": end.isoformat(),
            "days": [{"work_date": r.work_date.isoformat(), "kind": r.kind, "kind_label": r.kind_label, "shift": r.shift_label,
                      "clock_in": hm(r.clock_in), "clock_out": hm(r.clock_out), "late_minutes": r.late_minutes,
                      "early_minutes": r.early_minutes, "extra_minutes": r.extra_minutes, "pending": r.pending}
                     for r in reversed(rows)],
            "summary": None if summary is None else {
                "workdays": summary.workdays, "present": summary.present, "absent": summary.absent, "leave": summary.leave,
                "late_days": summary.late_days, "late_minutes": summary.late_minutes, "early_minutes": summary.early_minutes,
                "extra_minutes": summary.extra_minutes}}
