"""R381: حق مأموریت و هزینهٔ مأموریت — صورت‌حساب روی مرخصی «مأموریت» تاییدشده.

- حق مأموریت روزانه یا مبلغ ثابت است یا درصدی از حقوق پایهٔ روزانهٔ قرارداد فعال (حقوق ماهانه ÷ روزهای استاندارد ماه
  در تنظیمات حقوق)؛ نرخ هنگام ساخت یا ویرایش صورت‌حساب ثبت می‌شود و با تغییر بعدی تنظیمات عوض نمی‌شود.
- هزینه‌های مأموریت (ایاب و ذهاب، اقامت، غذا، سایر) با شمارهٔ رسید جدا ثبت می‌شوند.
- مسیر: پیش‌نویس ← ارسال ← تایید یا رد ← صدور سند. سند از همان سرویس سند حسابداری ساخته می‌شود (موقت، تا حسابدار مثل
  بقیهٔ اسناد تاییدش کند): بدهکار حساب هزینهٔ مأموریت، بستانکار حساب پرداختنی با تفصیلی پرسنلی همان کارمند؛ پرداخت با
  همان فرم پرداخت خزانه به تفصیلی کارمند انجام می‌شود.
- به محاسبهٔ حقوق، بیمه و مالیات حقوق چیزی افزوده نمی‌شود.
"""

from __future__ import annotations

import datetime
import decimal
from dataclasses import dataclass

from sqlalchemy import func, select

from peecha.db.base import new_session
from peecha.db.models.accounting import DetailAccount
from peecha.db.models.hr import Employee, EmploymentContract, LeaveRequest, MissionClaim, MissionClaimExpense, MissionSettings

FORM_CODE = "hr_missions"
METHODS = {"FIXED": "مبلغ ثابت روزانه", "PERCENT": "درصد حقوق پایهٔ روزانه"}
EXPENSE_TYPES = {"TRANSPORT": "ایاب و ذهاب", "LODGING": "اقامت", "MEALS": "غذا", "OTHER": "سایر"}
STATUSES = {"DRAFT": "پیش‌نویس", "SUBMITTED": "منتظر تایید", "APPROVED": "تاییدشده", "REJECTED": "ردشده", "POSTED": "سند صادر شد"}
EDITABLE = ("DRAFT", "REJECTED")
ZERO = decimal.Decimal(0)
_CENT = decimal.Decimal("0.01")


@dataclass
class Settings:
    per_diem_method: str = "FIXED"
    daily_amount: decimal.Decimal = ZERO
    daily_percent: decimal.Decimal = ZERO
    expense_gl_account_id: int | None = None
    expense_detail_account_id: int | None = None
    payable_gl_account_id: int | None = None


@dataclass
class ExpenseRow:
    expense_id: int
    expense_type: str
    type_label: str
    description: str
    receipt_no: str
    amount: decimal.Decimal


@dataclass
class ClaimRow:
    claim_id: int
    claim_no: int
    employee_id: int
    employee_name: str
    leave_request_id: int
    from_date: datetime.date
    to_date: datetime.date
    destination: str
    purpose: str
    days: decimal.Decimal
    daily_rate: decimal.Decimal
    per_diem_amount: decimal.Decimal
    expenses_amount: decimal.Decimal
    total_amount: decimal.Decimal
    status_code: str
    status_label: str
    decision_note: str
    journal_entry_id: int | None
    created_by_user_id: int | None


@dataclass
class MissionRow:
    """مرخصی مأموریت تاییدشده‌ای که هنوز صورت‌حساب ندارد."""
    leave_request_id: int
    employee_id: int
    employee_name: str
    from_date: datetime.date
    to_date: datetime.date
    days: decimal.Decimal
    reason: str


def can_approve(company_id: int, user_id: int | None) -> bool:
    from peecha.services import roles

    return bool(user_id) and (roles.is_manager(user_id, company_id) or roles.user_has_permission(user_id, company_id, FORM_CODE, "APPROVE"))


def _audit(session, company_id: int, user_id: int | None, entity_id: int, action: str, changes: dict) -> None:
    from peecha.services.audit import log_activity

    log_activity(session, company_id=company_id, user_id=user_id, entity_type="MissionClaim", entity_id=entity_id, action=action,
                 changes=changes)


# --- تنظیمات -----------------------------------------------------------------------------------------------------------
def get_settings(company_id: int) -> Settings:
    with new_session() as session:
        row = session.get(MissionSettings, company_id)
        if row is None:
            return Settings()
        return Settings(row.per_diem_method, decimal.Decimal(row.daily_amount), decimal.Decimal(row.daily_percent),
                        row.expense_gl_account_id, row.expense_detail_account_id, row.payable_gl_account_id)


def save_settings(company_id: int, user_id: int | None, settings: Settings) -> None:
    if settings.per_diem_method not in METHODS:
        raise ValueError("روش محاسبهٔ حق مأموریت نامعتبر است.")
    amount, percent = decimal.Decimal(settings.daily_amount or 0), decimal.Decimal(settings.daily_percent or 0)
    if amount < 0 or not ZERO <= percent <= 1000:
        raise ValueError("مبلغ یا درصد حق مأموریت نامعتبر است.")
    if not can_approve(company_id, user_id):
        raise ValueError("تنظیم حق مأموریت با مدیر سیستم یا دارندهٔ مجوز تایید صورت‌حساب مأموریت است.")
    with new_session() as session:
        row = session.get(MissionSettings, company_id)
        if row is None:
            row = MissionSettings(company_id=company_id)
            session.add(row)
        row.per_diem_method, row.daily_amount, row.daily_percent = settings.per_diem_method, amount, percent
        row.expense_gl_account_id, row.expense_detail_account_id = settings.expense_gl_account_id, settings.expense_detail_account_id
        row.payable_gl_account_id = settings.payable_gl_account_id
        row.updated_by_user_id, row.updated_at = user_id, datetime.datetime.now().astimezone()
        session.flush()
        from peecha.services.audit import log_activity

        log_activity(session, company_id=company_id, user_id=user_id, entity_type="MissionSettings", entity_id=company_id,
                     action="UPDATE", changes={"method": settings.per_diem_method, "daily_amount": str(amount), "daily_percent": str(percent)})
        session.commit()


def daily_rate(company_id: int, employee_id: int, on_date: datetime.date) -> decimal.Decimal:
    """حق مأموریت یک روز این کارمند در این تاریخ با تنظیمات فعلی."""
    st = get_settings(company_id)
    if st.per_diem_method == "FIXED":
        return st.daily_amount.quantize(_CENT)
    from peecha.services import payroll as payroll_service

    with new_session() as session:
        base = session.scalar(select(EmploymentContract.base_salary).where(
            EmploymentContract.employee_id == employee_id, EmploymentContract.status == "ACTIVE",
            EmploymentContract.start_date <= on_date,
            (EmploymentContract.end_date.is_(None)) | (EmploymentContract.end_date >= on_date))
            .order_by(EmploymentContract.start_date.desc()).limit(1))
    if base is None:
        raise ValueError("این کارمند در تاریخ مأموریت قرارداد فعال ندارد؛ حق مأموریت درصدی حساب نمی‌شود.")
    month_days = payroll_service.get_company_settings(company_id).standard_month_days or 30
    return (decimal.Decimal(base) / month_days * st.daily_percent / 100).quantize(_CENT)


# --- صورت‌حساب ---------------------------------------------------------------------------------------------------------
def eligible_missions(company_id: int, employee_id: int | None = None) -> list[MissionRow]:
    with new_session() as session:
        claimed = select(MissionClaim.leave_request_id)
        q = (select(LeaveRequest, Employee).join(Employee, Employee.employee_id == LeaveRequest.employee_id)
             .where(LeaveRequest.company_id == company_id, LeaveRequest.leave_type == "MISSION",
                    LeaveRequest.status_code == "APPROVED", LeaveRequest.leave_request_id.not_in(claimed)))
        if employee_id:
            q = q.where(LeaveRequest.employee_id == employee_id)
        return [MissionRow(r.leave_request_id, r.employee_id, f"{e.first_name} {e.last_name}".strip(), r.from_date, r.to_date,
                           decimal.Decimal(r.days or 0), r.reason or "")
                for r, e in session.execute(q.order_by(LeaveRequest.from_date.desc()))]


def _span_days(leave: LeaveRequest) -> int:
    return (leave.to_date - leave.from_date).days + 1


def _check_days(days, leave: LeaveRequest) -> decimal.Decimal:
    days = decimal.Decimal(days if days is not None else (leave.days or _span_days(leave)))
    if days <= 0 or days > _span_days(leave):
        raise ValueError("روزهای مأموریت باید بیشتر از صفر و حداکثر به اندازهٔ فاصلهٔ تاریخ شروع تا پایان مأموریت باشد.")
    return days


def _load(session, company_id: int, claim_id: int, lock: bool = False) -> MissionClaim:
    q = select(MissionClaim).where(MissionClaim.claim_id == claim_id)
    row = session.scalar(q.with_for_update() if lock else q)
    if row is None or row.company_id != company_id:
        raise ValueError("صورت‌حساب مأموریت نامعتبر است.")
    return row


def _editable(row: MissionClaim) -> None:
    if row.status_code not in EDITABLE:
        raise ValueError(f"صورت‌حساب در وضعیت «{STATUSES[row.status_code]}» است و تغییر نمی‌کند.")


def create_claim(company_id: int, user_id: int | None, leave_request_id: int, destination: str, purpose: str = "",
                 days=None) -> int:
    destination = (destination or "").strip()
    if not destination:
        raise ValueError("مقصد مأموریت را وارد کنید.")
    with new_session() as session:
        leave = session.get(LeaveRequest, leave_request_id)
        if leave is None or leave.company_id != company_id or leave.leave_type != "MISSION":
            raise ValueError("مرخصی مأموریت نامعتبر است.")
        if leave.status_code != "APPROVED":
            raise ValueError("صورت‌حساب فقط برای مأموریت تاییدشده ساخته می‌شود.")
        if session.scalar(select(MissionClaim.claim_id).where(MissionClaim.leave_request_id == leave_request_id)):
            raise ValueError("این مأموریت قبلاً صورت‌حساب دارد.")
        days = _check_days(days, leave)
        rate = daily_rate(company_id, leave.employee_id, leave.from_date)
        no = (session.scalar(select(func.max(MissionClaim.claim_no)).where(MissionClaim.company_id == company_id)) or 0) + 1
        row = MissionClaim(company_id=company_id, claim_no=no, employee_id=leave.employee_id, leave_request_id=leave_request_id,
                           destination=destination[:200], purpose=(purpose or "").strip()[:500] or None, days=days,
                           daily_rate=rate, per_diem_amount=(rate * days).quantize(_CENT), expenses_amount=ZERO,
                           created_by_user_id=user_id)
        session.add(row)
        session.flush()
        _audit(session, company_id, user_id, row.claim_id, "CREATE", {"claim_no": no, "leave_request_id": leave_request_id,
                                                                      "days": str(days), "daily_rate": str(rate)})
        session.commit()
        return row.claim_id


def update_claim(company_id: int, user_id: int | None, claim_id: int, destination: str, purpose: str = "", days=None) -> None:
    """ویرایش پیش‌نویس یا صورت‌حساب ردشده؛ نرخ روزانه با تنظیمات فعلی دوباره حساب می‌شود."""
    destination = (destination or "").strip()
    if not destination:
        raise ValueError("مقصد مأموریت را وارد کنید.")
    with new_session() as session:
        row = _load(session, company_id, claim_id, lock=True)
        _editable(row)
        leave = session.get(LeaveRequest, row.leave_request_id)
        row.days = _check_days(days, leave)
        row.daily_rate = daily_rate(company_id, row.employee_id, leave.from_date)
        row.per_diem_amount = (row.daily_rate * row.days).quantize(_CENT)
        row.destination, row.purpose = destination[:200], (purpose or "").strip()[:500] or None
        _audit(session, company_id, user_id, claim_id, "UPDATE", {"days": str(row.days), "daily_rate": str(row.daily_rate)})
        session.commit()


def _sum_expenses(session, claim_id: int) -> decimal.Decimal:
    return decimal.Decimal(session.scalar(select(func.coalesce(func.sum(MissionClaimExpense.amount), 0))
                                          .where(MissionClaimExpense.claim_id == claim_id)))


def add_expense(company_id: int, user_id: int | None, claim_id: int, expense_type: str, amount, description: str = "",
                receipt_no: str = "") -> int:
    if expense_type not in EXPENSE_TYPES:
        raise ValueError("نوع هزینه نامعتبر است.")
    amount = decimal.Decimal(amount or 0)
    if amount <= 0:
        raise ValueError("مبلغ هزینه باید بیشتر از صفر باشد.")
    with new_session() as session:
        row = _load(session, company_id, claim_id, lock=True)
        _editable(row)
        exp = MissionClaimExpense(claim_id=claim_id, expense_type=expense_type, amount=amount.quantize(_CENT),
                                  description=(description or "").strip()[:300] or None, receipt_no=(receipt_no or "").strip()[:50] or None)
        session.add(exp)
        session.flush()
        row.expenses_amount = _sum_expenses(session, claim_id)
        _audit(session, company_id, user_id, claim_id, "UPDATE", {"expense_added": expense_type, "amount": str(amount)})
        session.commit()
        return exp.expense_id


def delete_expense(company_id: int, user_id: int | None, expense_id: int) -> None:
    with new_session() as session:
        exp = session.get(MissionClaimExpense, expense_id)
        if exp is None:
            raise ValueError("هزینه یافت نشد.")
        row = _load(session, company_id, exp.claim_id, lock=True)
        _editable(row)
        session.delete(exp)
        session.flush()
        row.expenses_amount = _sum_expenses(session, row.claim_id)
        _audit(session, company_id, user_id, row.claim_id, "UPDATE", {"expense_deleted": exp.expense_type, "amount": str(exp.amount)})
        session.commit()


def delete_claim(company_id: int, user_id: int | None, claim_id: int) -> None:
    with new_session() as session:
        row = _load(session, company_id, claim_id, lock=True)
        _editable(row)
        _audit(session, company_id, user_id, claim_id, "DELETE", {"claim_no": row.claim_no})
        session.delete(row)
        session.commit()


def submit(company_id: int, user_id: int | None, claim_id: int) -> None:
    with new_session() as session:
        row = _load(session, company_id, claim_id, lock=True)
        _editable(row)
        if row.per_diem_amount + row.expenses_amount <= 0:
            raise ValueError("جمع صورت‌حساب صفر است؛ نرخ حق مأموریت را تنظیم یا هزینه‌ای ثبت کنید.")
        row.status_code = "SUBMITTED"
        _audit(session, company_id, user_id, claim_id, "SUBMIT", {"total": str(row.per_diem_amount + row.expenses_amount)})
        session.commit()


def _decide(company_id: int, user_id: int | None, claim_id: int, to: str, note: str) -> None:
    if not can_approve(company_id, user_id):
        raise ValueError("تایید یا رد صورت‌حساب مأموریت با مدیر سیستم یا دارندهٔ مجوز تایید آن است.")
    with new_session() as session:
        row = _load(session, company_id, claim_id, lock=True)
        if row.status_code != "SUBMITTED":
            raise ValueError("فقط صورت‌حساب ارسال‌شده تایید یا رد می‌شود.")
        row.status_code, row.decided_by_user_id = to, user_id
        row.decided_at, row.decision_note = datetime.datetime.now().astimezone(), (note or "").strip()[:500] or None
        _audit(session, company_id, user_id, claim_id, "APPROVE" if to == "APPROVED" else "REJECT", {"note": row.decision_note})
        session.commit()


def approve(company_id: int, user_id: int | None, claim_id: int, note: str = "") -> None:
    _decide(company_id, user_id, claim_id, "APPROVED", note)


def reject(company_id: int, user_id: int | None, claim_id: int, note: str) -> None:
    if not (note or "").strip():
        raise ValueError("دلیل رد صورت‌حساب را بنویسید.")
    _decide(company_id, user_id, claim_id, "REJECTED", note)


def _details(session, detail_account_id: int | None) -> dict[int, int]:
    da = session.get(DetailAccount, detail_account_id) if detail_account_id else None
    return {da.dimension_type_id: da.detail_account_id} if da is not None else {}


def post(company_id: int, user_id: int, claim_id: int, entry_date: datetime.date | None = None) -> int:
    """سند موقت صورت‌حساب تاییدشده؛ اگر سندش بعداً حذف شده باشد، دوباره صادر می‌شود."""
    from peecha import numerals
    from peecha.services import journal_entries as je_service

    if not can_approve(company_id, user_id):
        raise ValueError("صدور سند مأموریت با مدیر سیستم یا دارندهٔ مجوز تایید صورت‌حساب مأموریت است.")
    st = get_settings(company_id)
    if st.expense_gl_account_id is None or st.payable_gl_account_id is None:
        raise ValueError("حساب هزینهٔ مأموریت و حساب پرداختنی به کارکنان را در تنظیمات مأموریت انتخاب کنید.")
    with new_session() as session:
        row = _load(session, company_id, claim_id)
        if not (row.status_code == "APPROVED" or (row.status_code == "POSTED" and row.journal_entry_id is None)):
            raise ValueError("فقط برای صورت‌حساب تاییدشده سند صادر می‌شود.")
        emp = session.get(Employee, row.employee_id)
        leave = session.get(LeaveRequest, row.leave_request_id)
        name = f"{emp.first_name} {emp.last_name}".strip()
        title = f"مأموریت {numerals.to_persian_digits(str(row.claim_no))} {name} به {row.destination}"
        expense_details = _details(session, st.expense_detail_account_id)
        lines = []
        if row.per_diem_amount > 0:
            lines.append(je_service.LineInput(st.expense_gl_account_id, f"حق مأموریت — {title}", row.per_diem_amount, ZERO,
                                              details=dict(expense_details)))
        if row.expenses_amount > 0:
            lines.append(je_service.LineInput(st.expense_gl_account_id, f"هزینهٔ مأموریت — {title}", row.expenses_amount, ZERO,
                                              details=dict(expense_details)))
        total = row.per_diem_amount + row.expenses_amount
        lines.append(je_service.LineInput(st.payable_gl_account_id, f"پرداختنی {title}", ZERO, total,
                                          details=_details(session, emp.personnel_detail_account_id)))
        date = entry_date or leave.to_date
    result = je_service.create_journal_entry(company_id, user_id, date, title, lines)
    with new_session() as session:
        row = _load(session, company_id, claim_id, lock=True)
        row.status_code, row.journal_entry_id, row.posted_at = "POSTED", result.journal_entry_id, datetime.datetime.now().astimezone()
        _audit(session, company_id, user_id, claim_id, "EXECUTE", {"operation": "MISSION_POST", "journal_entry_id": result.journal_entry_id,
                                                                   "total": str(total)})
        session.commit()
    return result.journal_entry_id


# --- فهرست --------------------------------------------------------------------------------------------------------------
def list_claims(company_id: int, *, status: str | None = None, employee_id: int | None = None,
                ids: list[int] | None = None) -> list[ClaimRow]:
    with new_session() as session:
        q = (select(MissionClaim, Employee, LeaveRequest).join(Employee, Employee.employee_id == MissionClaim.employee_id)
             .join(LeaveRequest, LeaveRequest.leave_request_id == MissionClaim.leave_request_id)
             .where(MissionClaim.company_id == company_id))
        if status:
            q = q.where(MissionClaim.status_code == status)
        if employee_id:
            q = q.where(MissionClaim.employee_id == employee_id)
        if ids:
            q = q.where(MissionClaim.claim_id.in_(ids))
        out = []
        for c, e, lv in session.execute(q.order_by(MissionClaim.claim_no.desc())):
            pending_post = c.status_code == "POSTED" and c.journal_entry_id is None
            status_code = "APPROVED" if pending_post else c.status_code
            out.append(ClaimRow(c.claim_id, c.claim_no, c.employee_id, f"{e.first_name} {e.last_name}".strip(), c.leave_request_id,
                                lv.from_date, lv.to_date, c.destination, c.purpose or "", c.days, c.daily_rate, c.per_diem_amount,
                                c.expenses_amount, c.per_diem_amount + c.expenses_amount, status_code, STATUSES[status_code],
                                c.decision_note or "", c.journal_entry_id, c.created_by_user_id))
        return out


def get_claim(company_id: int, claim_id: int) -> ClaimRow:
    rows = list_claims(company_id, ids=[claim_id])
    if not rows:
        raise ValueError("صورت‌حساب مأموریت نامعتبر است.")
    return rows[0]


def list_expenses(claim_id: int) -> list[ExpenseRow]:
    with new_session() as session:
        return [ExpenseRow(x.expense_id, x.expense_type, EXPENSE_TYPES[x.expense_type], x.description or "", x.receipt_no or "", x.amount)
                for x in session.scalars(select(MissionClaimExpense).where(MissionClaimExpense.claim_id == claim_id)
                                         .order_by(MissionClaimExpense.expense_id))]


def pending_counts(company_id: int) -> tuple[int, int]:
    """(منتظر تایید، تاییدشدهٔ بی‌سند)."""
    with new_session() as session:
        waiting = session.scalar(select(func.count()).where(MissionClaim.company_id == company_id,
                                                            MissionClaim.status_code == "SUBMITTED")) or 0
        to_post = session.scalar(select(func.count()).where(
            MissionClaim.company_id == company_id,
            (MissionClaim.status_code == "APPROVED") | ((MissionClaim.status_code == "POSTED") & MissionClaim.journal_entry_id.is_(None)))) or 0
    return waiting, to_post
