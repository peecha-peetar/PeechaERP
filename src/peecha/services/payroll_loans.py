"""سرویسِ وام، مساعده و اقساط با کسرِ خودکار (فصلِ ۱۳).

قسط_ماهانه = (مبلغِ‌اصل × (۱ + نرخِ‌کارمزد)) ÷ تعدادِ‌اقساط، گردشده طبقِ
rounding_rule (فصلِ ۴)؛ باقیماندهٔ گردکردن به آخرین قسط اضافه می‌شود تا
مجموعِ اقساط دقیقاً برابرِ اصل+کارمزد باشد."""

from __future__ import annotations

import datetime
import decimal
from dataclasses import dataclass

import jdatetime
from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.payroll import Loan, LoanInstallment, PayrollPeriod
from peecha.services import audit as audit_service
from peecha.services import payroll as payroll_service

_LOAN_TYPES = ("LOAN", "ADVANCE")
_ACTIVE_STATUSES = ("DISBURSED", "ACTIVE")


def _jalali_month_bounds(jalali_year: int, jalali_month: int) -> tuple[datetime.date, datetime.date]:
    start = jdatetime.date(jalali_year, jalali_month, 1)
    if jalali_month == 12:
        next_start = jdatetime.date(jalali_year + 1, 1, 1)
    else:
        next_start = jdatetime.date(jalali_year, jalali_month + 1, 1)
    end = next_start - datetime.timedelta(days=1)
    return start.togregorian(), end.togregorian()


def _get_or_create_next_period(session, company_id: int, current: PayrollPeriod) -> PayrollPeriod:
    if current.jalali_month == 12:
        next_year, next_month = current.jalali_year + 1, 1
    else:
        next_year, next_month = current.jalali_year, current.jalali_month + 1
    existing = session.scalar(
        select(PayrollPeriod).where(
            PayrollPeriod.company_id == company_id, PayrollPeriod.jalali_year == next_year, PayrollPeriod.jalali_month == next_month
        )
    )
    if existing is not None:
        return existing
    start_date, end_date = _jalali_month_bounds(next_year, next_month)
    period = PayrollPeriod(
        company_id=company_id, jalali_year=next_year, jalali_month=next_month,
        period_start_date=start_date, period_end_date=end_date, status="OPEN",
    )
    session.add(period)
    session.flush()
    return period


@dataclass
class LoanRow:
    loan_id: int
    employee_id: int
    loan_type: str
    principal_amount: decimal.Decimal
    fee_rate: decimal.Decimal
    installments_count: int
    start_period_id: int
    funding_source: str | None
    status: str
    created_at: datetime.datetime


def _loan_row(loan: Loan) -> LoanRow:
    return LoanRow(
        loan.loan_id, loan.employee_id, loan.loan_type, loan.principal_amount, loan.fee_rate,
        loan.installments_count, loan.start_period_id, loan.funding_source, loan.status, loan.created_at,
    )


def list_loans(employee_id: int | None = None) -> list[LoanRow]:
    with new_session() as session:
        query = select(Loan).order_by(Loan.created_at)
        if employee_id is not None:
            query = query.where(Loan.employee_id == employee_id)
        return [_loan_row(loan) for loan in session.scalars(query).all()]


def get_loan(loan_id: int) -> LoanRow | None:
    with new_session() as session:
        loan = session.get(Loan, loan_id)
        return _loan_row(loan) if loan is not None else None


def create_loan(
    employee_id: int, loan_type: str, principal_amount: decimal.Decimal, fee_rate: decimal.Decimal,
    installments_count: int, start_period_id: int, funding_source: str | None,
) -> int:
    if loan_type not in _LOAN_TYPES:
        raise ValueError("نوعِ وام نامعتبر است.")
    if principal_amount <= 0:
        raise ValueError("مبلغِ اصل باید بزرگ‌تر از صفر باشد.")
    if fee_rate < 0:
        raise ValueError("نرخِ کارمزد نمی‌تواند منفی باشد.")
    if installments_count < 1:
        raise ValueError("تعدادِ اقساط باید حداقل ۱ باشد.")
    with new_session() as session:
        loan = Loan(
            employee_id=employee_id, loan_type=loan_type, principal_amount=principal_amount, fee_rate=fee_rate,
            installments_count=installments_count, start_period_id=start_period_id, funding_source=funding_source,
            status="REQUESTED",
        )
        session.add(loan)
        session.commit()
        return loan.loan_id


def approve_loan(loan_id: int) -> None:
    with new_session() as session:
        loan = session.get(Loan, loan_id)
        if loan is None:
            raise ValueError("این وام یافت نشد.")
        if loan.status != "REQUESTED":
            raise ValueError("فقط وامِ درخواست‌شده قابلِ تایید است.")
        loan.status = "APPROVED"
        session.commit()


def reject_loan(loan_id: int) -> None:
    with new_session() as session:
        loan = session.get(Loan, loan_id)
        if loan is None:
            raise ValueError("این وام یافت نشد.")
        if loan.status != "REQUESTED":
            raise ValueError("فقط وامِ درخواست‌شده قابلِ رد است.")
        loan.status = "REJECTED"
        session.commit()


def cancel_loan(loan_id: int) -> None:
    with new_session() as session:
        loan = session.get(Loan, loan_id)
        if loan is None:
            raise ValueError("این وام یافت نشد.")
        if loan.status not in ("REQUESTED", "APPROVED"):
            raise ValueError("وامِ پرداخت‌شده دیگر قابلِ لغو نیست.")
        loan.status = "CANCELLED"
        session.commit()


def disburse_loan(loan_id: int, company_id: int) -> None:
    """وامِ APPROVED را DISBURSED می‌کند و جدولِ اقساط را طبقِ فرمولِ فصلِ ۱۳ می‌سازد."""
    with new_session() as session:
        loan = session.get(Loan, loan_id)
        if loan is None:
            raise ValueError("این وام یافت نشد.")
        if loan.status != "APPROVED":
            raise ValueError("فقط وامِ تایید‌شده قابلِ پرداخت است.")
        settings = payroll_service.get_company_settings(company_id)
        total_payable = loan.principal_amount * (decimal.Decimal(1) + loan.fee_rate)
        raw_installment = total_payable / decimal.Decimal(loan.installments_count)
        rounded_installment = payroll_service.apply_rounding_rule(raw_installment, settings.rounding_rule)

        current_period = session.get(PayrollPeriod, loan.start_period_id)
        if current_period is None:
            raise ValueError("دورهٔ شروعِ کسر یافت نشد.")
        allocated = decimal.Decimal(0)
        for installment_no in range(1, loan.installments_count + 1):
            if installment_no == loan.installments_count:
                amount = total_payable - allocated
            else:
                amount = rounded_installment
                allocated += amount
            session.add(
                LoanInstallment(
                    loan_id=loan.loan_id, installment_no=installment_no, due_period_id=current_period.period_id,
                    amount=amount, status="PENDING",
                )
            )
            if installment_no < loan.installments_count:
                current_period = _get_or_create_next_period(session, company_id, current_period)
        loan.status = "DISBURSED"
        session.commit()


@dataclass
class LoanInstallmentRow:
    loan_installment_id: int
    loan_id: int
    installment_no: int
    due_period_id: int
    amount: decimal.Decimal
    status: str


def _installment_row(i: LoanInstallment) -> LoanInstallmentRow:
    return LoanInstallmentRow(i.loan_installment_id, i.loan_id, i.installment_no, i.due_period_id, i.amount, i.status)


def list_installments(loan_id: int) -> list[LoanInstallmentRow]:
    with new_session() as session:
        rows = session.scalars(
            select(LoanInstallment).where(LoanInstallment.loan_id == loan_id).order_by(LoanInstallment.installment_no)
        ).all()
        return [_installment_row(i) for i in rows]


@dataclass
class DueInstallmentRow:
    loan_installment_id: int
    loan_id: int
    employee_id: int
    amount: decimal.Decimal
    loan_created_at: datetime.datetime


def list_due_installments(employee_id: int, period_id: int) -> list[DueInstallmentRow]:
    """اقساطِ سررسیدِ یک کارمند در یک دوره، به‌ترتیبِ تاریخِ ایجادِ وام (قدیمی‌تر اول) — فصلِ ۸/۱۳."""
    with new_session() as session:
        rows = session.execute(
            select(LoanInstallment, Loan)
            .join(Loan, Loan.loan_id == LoanInstallment.loan_id)
            .where(
                Loan.employee_id == employee_id,
                LoanInstallment.due_period_id == period_id,
                LoanInstallment.status == "PENDING",
                Loan.status.in_(_ACTIVE_STATUSES),
            )
            .order_by(Loan.created_at)
        ).all()
        return [DueInstallmentRow(i.loan_installment_id, i.loan_id, loan.employee_id, i.amount, loan.created_at) for i, loan in rows]


def _refresh_loan_status(session, loan_id: int) -> None:
    loan = session.get(Loan, loan_id)
    if loan is None or loan.status not in _ACTIVE_STATUSES:
        return
    installments = session.scalars(select(LoanInstallment).where(LoanInstallment.loan_id == loan_id)).all()
    if all(i.status in ("DEDUCTED", "WAIVED") for i in installments):
        loan.status = "SETTLED"
    elif any(i.status == "DEDUCTED" for i in installments):
        loan.status = "ACTIVE"


def mark_installment_deducted(loan_installment_id: int) -> None:
    with new_session() as session:
        installment = session.get(LoanInstallment, loan_installment_id)
        if installment is None:
            raise ValueError("این قسط یافت نشد.")
        if installment.status != "PENDING":
            raise ValueError("فقط قسطِ در‌انتظار قابلِ کسر است.")
        installment.status = "DEDUCTED"
        _refresh_loan_status(session, installment.loan_id)
        session.commit()


def defer_installment(loan_installment_id: int, company_id: int) -> int:
    """طبقِ سناریوی سند: خالص کفافِ قسط را نمی‌دهد → این قسط DEFERRED و
    یک ردیفِ تازه به‌همان مبلغ برایِ دورهٔ بعد ساخته می‌شود."""
    with new_session() as session:
        installment = session.get(LoanInstallment, loan_installment_id)
        if installment is None:
            raise ValueError("این قسط یافت نشد.")
        if installment.status != "PENDING":
            raise ValueError("فقط قسطِ در‌انتظار قابلِ تعویق است.")
        current_period = session.get(PayrollPeriod, installment.due_period_id)
        next_period = _get_or_create_next_period(session, company_id, current_period)
        max_no = session.scalar(
            select(LoanInstallment.installment_no).where(LoanInstallment.loan_id == installment.loan_id).order_by(LoanInstallment.installment_no.desc())
        )
        new_installment = LoanInstallment(
            loan_id=installment.loan_id, installment_no=(max_no or 0) + 1, due_period_id=next_period.period_id,
            amount=installment.amount, status="PENDING",
        )
        installment.status = "DEFERRED"
        session.add(new_installment)
        session.flush()
        session.commit()
        return new_installment.loan_installment_id


def waive_installment(loan_installment_id: int, reason: str, company_id: int, user_id: int | None) -> None:
    if not reason or not reason.strip():
        raise ValueError("برایِ بخششِ قسط ذکرِ دلیل الزامی است.")
    with new_session() as session:
        installment = session.get(LoanInstallment, loan_installment_id)
        if installment is None:
            raise ValueError("این قسط یافت نشد.")
        if installment.status != "PENDING":
            raise ValueError("فقط قسطِ در‌انتظار قابلِ بخشش است.")
        installment.status = "WAIVED"
        _refresh_loan_status(session, installment.loan_id)
        audit_service.log_activity(
            session, company_id=company_id, user_id=user_id, entity_type="payroll.loan_installments",
            entity_id=loan_installment_id, action="UPDATE", changes={"after": {"status": "WAIVED"}, "reason": reason},
        )
        session.commit()


def total_outstanding_balance(loan_id: int) -> decimal.Decimal:
    with new_session() as session:
        rows = session.scalars(select(LoanInstallment).where(LoanInstallment.loan_id == loan_id, LoanInstallment.status == "PENDING")).all()
        return sum((i.amount for i in rows), decimal.Decimal(0))
