"""موتورِ محاسبهٔ حقوق (فصلِ ۱۱) — همه‌یِ اجزایِ فصل‌هایِ ۶ تا ۱۰ را برایِ
یک دورهٔ حقوقی، برایِ همه‌یِ کارمندانِ واجدِ شرایط، یکپارچه اجرا می‌کند.

ترتیبِ فازها دقیقاً طبقِ سند: EARNING → INSURANCE → TAX → DEDUCTION
(مالیات باید بعدِ بیمه محاسبه شود چون درآمدِ مشمولِ مالیات، سهمِ بیمهٔ
کارمند را کسر می‌کند — فصلِ ۱۰).

Idempotent: اجرایِ دوباره‌یِ یک run در وضعیتِ غیرِنهایی (DRAFT/CALCULATED)
نتایجِ قبلی را کامل بازنویسی می‌کند؛ خطایِ یک کارمندِ خاص کلِ run را
متوقف نمی‌کند (آن کارمند در errors فهرست و بقیه ادامه می‌یابند)."""

from __future__ import annotations

import datetime
import decimal
from dataclasses import dataclass, field

from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.hr import Employee, EmploymentContract
from peecha.db.models.payroll import PayItemDefinition, Payslip, PayslipLine, PayrollPeriod, PayrollRun
from peecha.services import hr_attendance
from peecha.services import payroll as payroll_service
from peecha.services import payroll_formula
from peecha.services import payroll_loans
from peecha.services import payroll_overtime

_SYSTEM_INSURANCE_ITEM_CODE = "SOCIAL_INSURANCE_EMPLOYEE"
_SYSTEM_TAX_ITEM_CODE = "INCOME_TAX"
_SYSTEM_OVERTIME_ITEM_CODE = "OVERTIME_PAY"
_SYSTEM_LOAN_ITEM_CODE = "LOAN_INSTALLMENT_DEDUCTION"


@dataclass
class EmployeeCalculationError:
    employee_id: int
    message: str


@dataclass
class RunResult:
    run_id: int
    employees_calculated: int
    employees_failed: int
    total_gross: decimal.Decimal
    total_net: decimal.Decimal
    errors: list[EmployeeCalculationError] = field(default_factory=list)


def _ensure_system_pay_item(
    company_id: int, code: str, name: str, item_type: str, phase: str, is_taxable: bool = False, is_insurable: bool = False
) -> int:
    with new_session() as session:
        existing = session.scalar(
            select(PayItemDefinition).where(PayItemDefinition.company_id == company_id, PayItemDefinition.code == code)
        )
        if existing is not None:
            return existing.pay_item_id
    return payroll_service.create_pay_item(
        company_id, code, name, item_type, "SYSTEM_TAX_ENGINE", phase, is_taxable=is_taxable, is_insurable=is_insurable,
    )


def create_run(period_id: int, run_type: str = "REGULAR", scope_org_unit_id: int | None = None) -> int:
    with new_session() as session:
        max_run_no = session.scalar(
            select(PayrollRun.run_no).where(PayrollRun.period_id == period_id).order_by(PayrollRun.run_no.desc())
        )
        run = PayrollRun(
            period_id=period_id, run_no=(max_run_no or 0) + 1, run_type=run_type,
            scope_org_unit_id=scope_org_unit_id, status="DRAFT",
        )
        session.add(run)
        session.commit()
        return run.run_id


def _target_employees(session, company_id: int, period_start: datetime.date, period_end: datetime.date, scope_org_unit_id: int | None):
    query = (
        select(Employee, EmploymentContract)
        .join(EmploymentContract, EmploymentContract.employee_id == Employee.employee_id)
        .where(
            Employee.company_id == company_id,
            EmploymentContract.status == "ACTIVE",
            EmploymentContract.start_date <= period_end,
            (EmploymentContract.end_date.is_(None)) | (EmploymentContract.end_date >= period_start),
        )
    )
    if scope_org_unit_id is not None:
        query = query.where(EmploymentContract.org_unit_id == scope_org_unit_id)
    return session.execute(query).all()


def _resolve_worked_days(company_id: int, employee_id: int, period: PayrollPeriod, calendar_days: int) -> int:
    """کارکردِ واقعی از رویِ حضوروغیابِ تاییدشده (services/hr_attendance.py)
    برایِ همین کارمند در بازهٔ دوره؛ اگر هیچ رکوردی ثبت نشده باشد (شرکتی
    که هنوز از این ماژول استفاده نمی‌کند)، طبقِ رفتارِ قبلی، کارکردِ
    کامل فرض می‌شود تا رفتارِ موجود نشکند."""
    summary = hr_attendance.compute_attendance_summary(
        company_id, period.period_start_date, period.period_end_date, employee_id
    )
    if not summary:
        return calendar_days
    return summary[0].present_days


def _calculate_employee(
    company_id: int,
    employee: Employee,
    contract: EmploymentContract,
    period: PayrollPeriod,
    pay_items: list[payroll_service.PayItemRow],
    formula_asts: dict[str, object],
    execution_order: list[str],
    settings: payroll_service.CompanySettingsRow,
) -> tuple[decimal.Decimal, decimal.Decimal, decimal.Decimal, list[tuple[int, str, str, decimal.Decimal, str]]]:
    """یک کارمند را محاسبه می‌کند؛ (gross, total_deductions, net,
    lines) را برمی‌گرداند. lines: (pay_item_id, code, name, amount, phase)."""
    calendar_days = settings.standard_month_days
    worked_days = _resolve_worked_days(company_id, employee.employee_id, period, calendar_days)
    variables = {
        "BASE_SALARY": contract.base_salary,
        "WORKED_DAYS": decimal.Decimal(worked_days),
        "CALENDAR_DAYS": decimal.Decimal(calendar_days),
        "CHILDREN_COUNT": decimal.Decimal(0),
        "WEEKLY_HOURS": decimal.Decimal(0),
    }
    items_by_code = {p.code: p for p in pay_items}
    resolved: dict[str, decimal.Decimal] = {}
    lines: list[tuple[int, str, str, decimal.Decimal, str]] = []

    def policy_resolver(code: str) -> decimal.Decimal | None:
        return payroll_service.resolve_policy_value(company_id, code, period.period_start_date)

    def is_eligible(item: payroll_service.PayItemRow) -> bool:
        if not item.eligibility_condition:
            return True
        node = payroll_formula.parse_condition(item.eligibility_condition)
        return bool(payroll_formula.evaluate(node, variables, resolved, policy_resolver))

    def prorate(amount: decimal.Decimal, item: payroll_service.PayItemRow) -> decimal.Decimal:
        if item.is_prorated and calendar_days:
            return amount * decimal.Decimal(worked_days) / decimal.Decimal(calendar_days)
        return amount

    # فازِ ۱: EARNING (شاملِ BENEFIT)
    gross = decimal.Decimal(0)
    insurable_total = decimal.Decimal(0)
    taxable_total = decimal.Decimal(0)
    for code in execution_order:
        item = items_by_code[code]
        if item.item_type not in ("EARNING", "BENEFIT") or item.calculation_phase != "EARNING_PHASE":
            continue
        if not is_eligible(item):
            resolved[code] = decimal.Decimal(0)
            continue
        if item.calculation_method == "BASE_SALARY_FROM_CONTRACT":
            amount = prorate(contract.base_salary, item)
        elif item.calculation_method == "FIXED":
            amount = prorate(item.fixed_amount or decimal.Decimal(0), item)
        elif item.calculation_method == "PERCENTAGE_OF_BASE":
            amount = prorate(contract.base_salary * (item.percentage or decimal.Decimal(0)) / decimal.Decimal(100), item)
        elif item.calculation_method == "FORMULA":
            node = formula_asts[code]
            amount = payroll_formula.evaluate(node, variables, resolved, policy_resolver)
        elif item.calculation_method == "MANUAL":
            amount = _employee_component_amount(employee.employee_id, item.pay_item_id, period.period_start_date)
        else:
            amount = decimal.Decimal(0)
        resolved[code] = amount
        if item.is_cash:
            gross += amount
        if item.is_insurable:
            insurable_total += amount
        if item.is_taxable:
            taxable_total += amount
        lines.append((item.pay_item_id, item.code, item.name, amount, "EARNING_PHASE"))

    # اضافه‌کاری (فصلِ ۱۲) — pay_item سیستمیِ EARNING، مشمولِ بیمه و مالیات
    continuous_benefits_total = sum(
        (resolved.get(item.code, decimal.Decimal(0)) for item in pay_items if item.is_continuous_benefit),
        decimal.Decimal(0),
    )
    overtime_pay = payroll_overtime.compute_overtime_pay(
        company_id, employee.employee_id, period.period_id, contract.base_salary, continuous_benefits_total, calendar_days
    )
    if overtime_pay > 0:
        overtime_item_id = _ensure_system_pay_item(
            company_id, _SYSTEM_OVERTIME_ITEM_CODE, "اضافه‌کاری", "EARNING", "EARNING_PHASE", is_taxable=True, is_insurable=True
        )
        gross += overtime_pay
        insurable_total += overtime_pay
        taxable_total += overtime_pay
        lines.append((overtime_item_id, _SYSTEM_OVERTIME_ITEM_CODE, "اضافه‌کاری", overtime_pay, "EARNING_PHASE"))

    # فازِ ۲: INSURANCE
    insurance_result = payroll_service.compute_insurance(company_id, period.period_start_date, insurable_total)
    insurance_item_id = _ensure_system_pay_item(company_id, _SYSTEM_INSURANCE_ITEM_CODE, "بیمهٔ سهمِ کارمند", "INSURANCE", "INSURANCE_PHASE")
    lines.append((insurance_item_id, _SYSTEM_INSURANCE_ITEM_CODE, "بیمهٔ سهمِ کارمند", insurance_result.employee_share, "INSURANCE_PHASE"))

    # فازِ ۳: TAX (طبقِ فصلِ ۱۰: کسرِ سهمِ بیمهٔ کارمند از درآمدِ مشمولِ مالیات)
    taxable_income_this_month = max(decimal.Decimal(0), taxable_total - insurance_result.employee_share)
    tax_year = period.jalali_year
    months_elapsed = period.jalali_month
    tax_amount = payroll_service.compute_monthly_tax(
        employee.employee_id, company_id, tax_year, months_elapsed, taxable_income_this_month, period.period_start_date
    )
    tax_item_id = _ensure_system_pay_item(company_id, _SYSTEM_TAX_ITEM_CODE, "مالیاتِ حقوق", "TAX", "TAX_PHASE")
    lines.append((tax_item_id, _SYSTEM_TAX_ITEM_CODE, "مالیاتِ حقوق", tax_amount, "TAX_PHASE"))

    # فازِ ۴: DEDUCTION (اولویت: حکمِ دادگاه، سپس عددِ کوچک‌ترِ deduction_priority؛
    # اقساطِ وام/مساعده به‌عنوانِ اولویتِ ۴ — فصلِ ۱۳)
    remaining = gross - insurance_result.employee_share - tax_amount
    dedn_lines, total_deductions, _loan_settlement = resolve_deductions(
        employee.employee_id, company_id, period.period_id, period.period_start_date, remaining
    )
    lines.extend(dedn_lines)

    net_pay = gross - insurance_result.employee_share - tax_amount - total_deductions
    return gross, total_deductions, net_pay, lines


def resolve_deductions(
    employee_id: int, company_id: int, period_id: int, as_of_date: datetime.date, remaining: decimal.Decimal
) -> tuple[list[tuple[int, str, str, decimal.Decimal, str]], decimal.Decimal, list[tuple[int, decimal.Decimal, bool]]]:
    """اعمالِ فازِ DEDUCTION رویِ remaining (خالص پیش از کسورات). عمومی
    است تا هم موتور (هنگامِ محاسبه) و هم تسویه‌حسابِ فیش (فصلِ ۱۴، پس از
    APPROVED شدنِ run) بتوانند دقیقاً همان نتیجه را بازتولید کنند.
    خروجیِ سوم: (loan_installment_id, amount, was_applied) برایِ هر
    قسطِ وام — تسویه‌حساب از رویِ همین لیست، DEDUCTED/DEFERRED می‌کند."""
    deduction_requests = _collect_deduction_requests(employee_id, company_id, period_id, as_of_date)
    lines: list[tuple[int, str, str, decimal.Decimal, str]] = []
    total_deductions = decimal.Decimal(0)
    loan_settlement: list[tuple[int, decimal.Decimal, bool]] = []
    for pay_item_id, code, name, requested, loan_installment_id in deduction_requests:
        if loan_installment_id is not None:
            # طبقِ سناریویِ سند: خالص کفافِ قسط را نمی‌دهد → کلِ آن قسط
            # DEFERRED می‌شود (نه کسرِ جزئی) — فصلِ ۱۳
            applied = requested if remaining >= requested else decimal.Decimal(0)
            loan_settlement.append((loan_installment_id, applied, applied > 0))
        else:
            applied = max(decimal.Decimal(0), min(requested, remaining))
        remaining -= applied
        total_deductions += applied
        if applied > 0:
            lines.append((pay_item_id, code, name, applied, "DEDUCTION_PHASE"))
    return lines, total_deductions, loan_settlement


def _employee_component_amount(employee_id: int, pay_item_id: int, as_of_date: datetime.date) -> decimal.Decimal:
    with new_session() as session:
        from peecha.db.models.payroll import EmployeePayComponent

        row = session.scalar(
            select(EmployeePayComponent).where(
                EmployeePayComponent.employee_id == employee_id,
                EmployeePayComponent.pay_item_id == pay_item_id,
                EmployeePayComponent.effective_from <= as_of_date,
                (EmployeePayComponent.effective_to.is_(None)) | (EmployeePayComponent.effective_to >= as_of_date),
            )
        )
        return row.amount if row is not None and row.amount is not None else decimal.Decimal(0)


def _collect_deduction_requests(
    employee_id: int, company_id: int, period_id: int, as_of_date: datetime.date
) -> list[tuple[int, str, str, decimal.Decimal, int | None]]:
    """اقلامِ فازِ DEDUCTION: کسوراتِ دستی/موردی، به‌علاوهٔ اقساطِ وامِ
    سررسیدشده (فصلِ ۱۳) به‌عنوانِ اولویتِ ۴. آخرین عنصرِ هر تاپل،
    loan_installment_id است (فقط برایِ ردیف‌هایِ وام؛ بقیه None) —
    برایِ اینکه تسویه‌حسابِ فیش (فصلِ ۱۴) بتواند دقیقاً بفهمد کدام قسط
    با چه مبلغی اعمال شد، بدونِ محاسبهٔ دوباره."""
    with new_session() as session:
        from peecha.db.models.payroll import DeductionEntry, EmployeePayComponent

        manual = session.execute(
            select(EmployeePayComponent, PayItemDefinition)
            .join(PayItemDefinition, PayItemDefinition.pay_item_id == EmployeePayComponent.pay_item_id)
            .where(
                EmployeePayComponent.employee_id == employee_id,
                PayItemDefinition.item_type == "DEDUCTION",
                EmployeePayComponent.effective_from <= as_of_date,
                (EmployeePayComponent.effective_to.is_(None)) | (EmployeePayComponent.effective_to >= as_of_date),
            )
        ).all()
        adhoc = session.execute(
            select(DeductionEntry, PayItemDefinition)
            .join(PayItemDefinition, PayItemDefinition.pay_item_id == DeductionEntry.pay_item_id)
            .where(
                DeductionEntry.employee_id == employee_id,
                DeductionEntry.period_id == period_id,
                DeductionEntry.status == "APPROVED",
            )
        ).all()
        requests = [
            (p.pay_item_id, p.code, p.name, c.amount or decimal.Decimal(0), p.is_court_order, p.deduction_priority or 999, None)
            for c, p in manual
        ] + [
            (p.pay_item_id, p.code, p.name, d.amount, p.is_court_order, p.deduction_priority or 999, None)
            for d, p in adhoc
        ]

    due_installments = payroll_loans.list_due_installments(employee_id, period_id)
    if due_installments:
        loan_item_id = _ensure_system_pay_item(
            company_id, _SYSTEM_LOAN_ITEM_CODE, "قسطِ وام/مساعده", "DEDUCTION", "DEDUCTION_PHASE"
        )
        requests += [
            (loan_item_id, _SYSTEM_LOAN_ITEM_CODE, "قسطِ وام/مساعده", due.amount, False, 4, due.loan_installment_id)
            for due in due_installments
        ]

    requests.sort(key=lambda r: (not r[4], r[5]))
    return [(pay_item_id, code, name, amount, loan_installment_id) for pay_item_id, code, name, amount, _, _, loan_installment_id in requests]


def run_payroll(run_id: int) -> RunResult:
    with new_session() as session:
        run = session.get(PayrollRun, run_id)
        if run is None:
            raise ValueError("این اجرا یافت نشد.")
        if run.status not in ("DRAFT", "CALCULATING", "CALCULATED"):
            raise ValueError("این اجرا در وضعیتِ نهایی است و دیگر قابلِ بازاجرا نیست.")
        period = session.get(PayrollPeriod, run.period_id)
        if period is None:
            raise ValueError("دورهٔ حقوقی یافت نشد.")
        company_id = period.company_id
        run.status = "CALCULATING"
        run.started_at = datetime.datetime.now(datetime.timezone.utc)
        session.commit()

        # idempotency: بازنویسیِ کاملِ نتایجِ قبلیِ همین run
        old_payslip_ids = [pid for (pid,) in session.execute(select(Payslip.payslip_id).where(Payslip.run_id == run_id))]
        if old_payslip_ids:
            session.execute(PayslipLine.__table__.delete().where(PayslipLine.payslip_id.in_(old_payslip_ids)))
            session.execute(Payslip.__table__.delete().where(Payslip.run_id == run_id))
            session.commit()

        targets = _target_employees(session, company_id, period.period_start_date, period.period_end_date, run.scope_org_unit_id)

    pay_items = payroll_service.list_pay_items(company_id, active_only=True)
    settings = payroll_service.get_company_settings(company_id)
    formula_asts = {
        item.code: payroll_formula.parse_formula(item.formula_expression)
        for item in pay_items
        if item.calculation_method == "FORMULA" and item.formula_expression
    }
    execution_order = payroll_formula.topological_order(formula_asts)
    leaf_codes = [item.code for item in pay_items if item.code not in formula_asts]
    execution_order = leaf_codes + [c for c in execution_order if c not in leaf_codes]

    errors: list[EmployeeCalculationError] = []
    total_gross = decimal.Decimal(0)
    total_net = decimal.Decimal(0)
    calculated = 0

    for employee, contract in targets:
        try:
            gross, total_deductions, net_pay, lines = _calculate_employee(
                company_id, employee, contract, period, pay_items, formula_asts, execution_order, settings
            )
        except ValueError as exc:
            errors.append(EmployeeCalculationError(employee.employee_id, str(exc)))
            continue
        with new_session() as session:
            payslip = Payslip(
                run_id=run_id, employee_id=employee.employee_id, contract_id=contract.contract_id,
                period_id=period.period_id, gross_amount=gross, total_deductions=total_deductions,
                net_pay=net_pay, status="DRAFT",
            )
            session.add(payslip)
            session.flush()
            for pay_item_id, code, name, amount, phase in lines:
                session.add(
                    PayslipLine(
                        payslip_id=payslip.payslip_id, pay_item_id=pay_item_id, pay_item_code_snapshot=code,
                        label_snapshot=name, amount=amount, phase=phase,
                    )
                )
            session.commit()
        total_gross += gross
        total_net += net_pay
        calculated += 1

    with new_session() as session:
        run = session.get(PayrollRun, run_id)
        run.status = "CALCULATED"
        run.finished_at = datetime.datetime.now(datetime.timezone.utc)
        run.error_log = "; ".join(f"کارمندِ #{e.employee_id}: {e.message}" for e in errors) or None
        session.commit()

    return RunResult(run_id, calculated, len(errors), total_gross, total_net, errors)


@dataclass
class RunRow:
    run_id: int
    run_no: int
    run_type: str
    status: str
    started_at: datetime.datetime | None
    finished_at: datetime.datetime | None
    error_log: str | None


def list_runs(period_id: int) -> list[RunRow]:
    with new_session() as session:
        rows = session.scalars(select(PayrollRun).where(PayrollRun.period_id == period_id).order_by(PayrollRun.run_no)).all()
        return [RunRow(r.run_id, r.run_no, r.run_type, r.status, r.started_at, r.finished_at, r.error_log) for r in rows]


def approve_run(run_id: int) -> None:
    with new_session() as session:
        run = session.get(PayrollRun, run_id)
        if run is None:
            raise ValueError("این اجرا یافت نشد.")
        if run.status != "CALCULATED":
            raise ValueError("فقط اجرایی که محاسبه شده قابلِ تایید است.")
        run.status = "APPROVED"
        session.commit()


@dataclass
class PayslipSummaryRow:
    payslip_id: int
    employee_id: int
    employee_name: str
    gross_amount: decimal.Decimal
    total_deductions: decimal.Decimal
    net_pay: decimal.Decimal


def list_payslips(run_id: int) -> list[PayslipSummaryRow]:
    with new_session() as session:
        rows = session.execute(
            select(Payslip, Employee)
            .join(Employee, Employee.employee_id == Payslip.employee_id)
            .where(Payslip.run_id == run_id)
            .order_by(Employee.employee_code)
        ).all()
        return [
            PayslipSummaryRow(
                p.payslip_id, p.employee_id, f"{e.first_name} {e.last_name}", p.gross_amount, p.total_deductions, p.net_pay
            )
            for p, e in rows
        ]


@dataclass
class PayslipLineRow:
    pay_item_code: str
    label: str
    amount: decimal.Decimal
    phase: str


def list_payslip_lines(payslip_id: int) -> list[PayslipLineRow]:
    with new_session() as session:
        rows = session.scalars(select(PayslipLine).where(PayslipLine.payslip_id == payslip_id)).all()
        return [PayslipLineRow(r.pay_item_code_snapshot, r.label_snapshot, r.amount, r.phase) for r in rows]
