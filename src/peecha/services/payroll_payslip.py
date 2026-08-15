"""سرویسِ تولید/قطعی‌سازیِ فیشِ حقوقی (فصلِ ۱۴).

گردشِ کار: DRAFT (هم‌زمان با run=CALCULATED) → FINALIZED (پس از
APPROVED شدنِ run، غیرقابل‌ویرایش) → DELIVERED → (در صورتِ خطا) یک
فیشِ CORRECTED تازه ساخته می‌شود؛ اصل هرگز حذف/ویرایش نمی‌شود.

قطعی‌سازی، تسویه‌حسابِ واقعیِ اقساطِ وام را هم انجام می‌دهد: تا این
لحظه (در حینِ محاسبه) وضعیتِ قسط‌ها دست‌نخورده مانده تا بازاجرا (پیش از
APPROVED) idempotent بماند؛ resolve_deductions با همان ورودی‌هایِ
ثبت‌شده (gross_amount و مبالغِ بیمه/مالیاتِ ذخیره‌شده) دقیقاً همان
نتیجهٔ محاسبه را بازتولید و روی هر قسط DEDUCTED یا DEFERRED اعمال
می‌کند."""

from __future__ import annotations

import decimal
from dataclasses import dataclass, field

from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.hr import Employee
from peecha.db.models.payroll import Payslip, PayslipLine, PayrollPeriod, PayrollRun
from peecha.services import payroll_engine
from peecha.services import payroll_loans


@dataclass
class FinalizationResult:
    run_id: int
    finalized_count: int
    loan_installments_deducted: int
    loan_installments_deferred: int


def finalize_payslips_for_run(run_id: int) -> FinalizationResult:
    with new_session() as session:
        run = session.get(PayrollRun, run_id)
        if run is None:
            raise ValueError("این اجرا یافت نشد.")
        if run.status != "APPROVED":
            raise ValueError("فقط اجرایِ تاییدشده قابلِ قطعی‌سازیِ فیش است.")
        period = session.get(PayrollPeriod, run.period_id)
        company_id = period.company_id
        period_id = period.period_id
        as_of_date = period.period_start_date
        draft_payslip_ids = [
            p.payslip_id
            for p in session.scalars(select(Payslip).where(Payslip.run_id == run_id, Payslip.status == "DRAFT"))
        ]

    finalized_count = 0
    deducted_count = 0
    deferred_count = 0

    for payslip_id in draft_payslip_ids:
        with new_session() as session:
            payslip = session.get(Payslip, payslip_id)
            phase_totals: dict[str, decimal.Decimal] = {}
            for line in session.scalars(select(PayslipLine).where(PayslipLine.payslip_id == payslip_id)):
                phase_totals[line.phase] = phase_totals.get(line.phase, decimal.Decimal(0)) + line.amount
            remaining = (
                payslip.gross_amount
                - phase_totals.get("INSURANCE_PHASE", decimal.Decimal(0))
                - phase_totals.get("TAX_PHASE", decimal.Decimal(0))
            )
            employee_id = payslip.employee_id
            payslip.status = "FINALIZED"
            session.commit()
            finalized_count += 1

        _, _, loan_settlement = payroll_engine.resolve_deductions(employee_id, company_id, period_id, as_of_date, remaining)
        for loan_installment_id, _amount, was_applied in loan_settlement:
            if was_applied:
                payroll_loans.mark_installment_deducted(loan_installment_id)
                deducted_count += 1
            else:
                payroll_loans.defer_installment(loan_installment_id, company_id)
                deferred_count += 1

    return FinalizationResult(run_id, finalized_count, deducted_count, deferred_count)


def deliver_payslip(payslip_id: int) -> None:
    with new_session() as session:
        payslip = session.get(Payslip, payslip_id)
        if payslip is None:
            raise ValueError("این فیش یافت نشد.")
        if payslip.status != "FINALIZED":
            raise ValueError("فقط فیشِ نهایی‌شده قابلِ ارسال/تحویل است.")
        payslip.status = "DELIVERED"
        session.commit()


def create_correction_payslip(
    original_payslip_id: int,
    gross_amount: decimal.Decimal,
    total_deductions: decimal.Decimal,
    net_pay: decimal.Decimal,
    lines: list[tuple[int, str, str, decimal.Decimal, str]],
) -> int:
    """فیشِ اصلاحی: اصل هرگز ویرایش نمی‌شود، فقط به CORRECTED می‌رود و
    correction_of_payslip_id به آن اشاره می‌کند."""
    with new_session() as session:
        original = session.get(Payslip, original_payslip_id)
        if original is None:
            raise ValueError("فیشِ اصلی یافت نشد.")
        if original.status not in ("FINALIZED", "DELIVERED"):
            raise ValueError("فقط فیشِ نهایی‌شده قابلِ اصلاح است.")
        correction = Payslip(
            run_id=original.run_id, employee_id=original.employee_id, contract_id=original.contract_id,
            period_id=original.period_id, gross_amount=gross_amount, total_deductions=total_deductions,
            net_pay=net_pay, status="FINALIZED", correction_of_payslip_id=original.payslip_id,
        )
        session.add(correction)
        session.flush()
        for pay_item_id, code, name, amount, phase in lines:
            session.add(
                PayslipLine(
                    payslip_id=correction.payslip_id, pay_item_id=pay_item_id, pay_item_code_snapshot=code,
                    label_snapshot=name, amount=amount, phase=phase,
                )
            )
        original.status = "CORRECTED"
        session.commit()
        return correction.payslip_id


@dataclass
class PrintablePayslipLine:
    code: str
    label: str
    amount: decimal.Decimal
    phase: str


@dataclass
class PrintablePayslip:
    payslip_id: int
    employee_code: str
    employee_full_name: str
    jalali_year: int
    jalali_month: int
    status: str
    gross_amount: decimal.Decimal
    total_deductions: decimal.Decimal
    net_pay: decimal.Decimal
    earning_lines: list[PrintablePayslipLine] = field(default_factory=list)
    deduction_lines: list[PrintablePayslipLine] = field(default_factory=list)


def get_printable_payslip(payslip_id: int) -> PrintablePayslip:
    """استفادهٔ مستقیم از همین داده برایِ report_export.py — بدونِ موتورِ چاپِ تازه (طبقِ سند)."""
    with new_session() as session:
        payslip = session.get(Payslip, payslip_id)
        if payslip is None:
            raise ValueError("این فیش یافت نشد.")
        employee = session.get(Employee, payslip.employee_id)
        period = session.get(PayrollPeriod, payslip.period_id)
        lines = session.scalars(select(PayslipLine).where(PayslipLine.payslip_id == payslip_id)).all()
        earning_lines = [
            PrintablePayslipLine(l.pay_item_code_snapshot, l.label_snapshot, l.amount, l.phase)
            for l in lines
            if l.phase == "EARNING_PHASE"
        ]
        deduction_lines = [
            PrintablePayslipLine(l.pay_item_code_snapshot, l.label_snapshot, l.amount, l.phase)
            for l in lines
            if l.phase in ("INSURANCE_PHASE", "TAX_PHASE", "DEDUCTION_PHASE")
        ]
        return PrintablePayslip(
            payslip.payslip_id, employee.employee_code, f"{employee.first_name} {employee.last_name}",
            period.jalali_year, period.jalali_month, payslip.status,
            payslip.gross_amount, payslip.total_deductions, payslip.net_pay, earning_lines, deduction_lines,
        )
