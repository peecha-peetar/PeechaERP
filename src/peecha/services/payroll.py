"""سرویسِ اطلاعاتِ پایه و قوانینِ حقوق و دستمزد (payroll.*) — فازِ ۲ از
ماژولِ حقوق و دستمزد (فصلِ ۴ و ۵ از سندِ طراحی).

الگویِ نسخه‌بندی: هر ردیفِ حداقل‌دستمزد/قانون یک بازه‌یِ effective_from/to
دارد؛ company_id می‌تواند NULL باشد یعنی «پیش‌فرضِ سراسری». resolve_policy
دقیقاً همان الگویِ عمومیِ فصلِ ۱۸ است — تنظیمِ تازه در آینده فقط یک ردیفِ
policy_code تازه لازم دارد، نه تغییرِ ساختاری."""

from __future__ import annotations

import datetime
import decimal
from dataclasses import dataclass

from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.payroll import (
    CompanyPayrollSettings,
    DeductionEntry,
    EmployeeAnnualTaxLedger,
    EmployeePayComponent,
    InsuranceConfig,
    MinimumWageRate,
    PayItemDefinition,
    PayrollDescriptionTemplate,
    PayrollPeriod,
    PayrollPolicy,
    PayslipLine,
    TaxBracket,
    TaxExemption,
)
from peecha.services import payroll_formula

# فهرستِ ثابتِ کدهایِ قانونِ کارِ ایران (فصلِ ۵) — کد، برچسبِ فارسی، مقدارِ
# پیش‌فرض (که در db/schema/044_payroll_core.sql به‌صورتِ سراسری seed شده).
POLICY_DEFINITIONS: list[tuple[str, str]] = [
    ("DAILY_WORKING_HOURS_MAX", "حداکثر ساعتِ کاریِ روزانه"),
    ("WEEKLY_WORKING_HOURS_MAX", "حداکثر ساعتِ کاریِ هفتگی"),
    ("PROBATION_PERIOD_MAX_MONTHS_UNSKILLED", "حداکثر دورهٔ آزمایشی — کارگرِ ساده (ماه)"),
    ("PROBATION_PERIOD_MAX_MONTHS_SKILLED", "حداکثر دورهٔ آزمایشی — متخصص (ماه)"),
    ("RESIGNATION_NOTICE_PERIOD_DAYS", "مهلتِ اطلاعِ قبلیِ استعفا (روز)"),
    ("ANNUAL_LEAVE_ACCRUAL_DAYS_PER_MONTH", "نرخِ تعلقِ مرخصیِ استحقاقی (روز/ماه)"),
    ("ANNUAL_LEAVE_CARRY_OVER_MAX_DAYS", "سقفِ انتقالِ مرخصی به سالِ بعد (روز)"),
    ("SEVERANCE_MONTHS_SALARY_PER_YEAR", "سنوات — ماه‌حقوق به‌ازایِ هر سال"),
    ("YEAR_END_BONUS_MIN_DAYS_OF_MIN_WAGE", "کفِ عیدی (روزِ حداقل‌دستمزد)"),
    ("YEAR_END_BONUS_MAX_DAYS_OF_MIN_WAGE", "سقفِ عیدی (روزِ حداقل‌دستمزد)"),
    ("RETIREMENT_AGE_YEARS_MALE", "سنِ بازنشستگی — مرد (سال)"),
    ("RETIREMENT_AGE_YEARS_FEMALE", "سنِ بازنشستگی — زن (سال)"),
    ("RETIREMENT_MIN_INSURANCE_YEARS", "حداقلِ سابقهٔ بیمه برایِ بازنشستگی (سال)"),
    ("SALARY_PAYMENT_DEADLINE_DAYS", "مهلتِ قانونیِ پرداختِ حقوق (روز)"),
    ("TERMINATION_NOTICE_PERIOD_DAYS", "مهلتِ اخطارِ اخراج (روز)"),
    ("INSURANCE_WAGE_CEILING_MULTIPLE_OF_MIN_WAGE", "سقفِ مزدِ مشمولِ بیمه (چندبرابرِ حداقل‌دستمزد)"),
]

_CALCULATION_BASIS_CHOICES = ("DAILY", "HOURLY")
_ROUNDING_RULE_CHOICES = ("NONE", "ROUND_1000", "ROUND_100", "TRUNCATE")


def apply_rounding_rule(amount: decimal.Decimal, rounding_rule: str) -> decimal.Decimal:
    """طبقِ rounding_rule تنظیماتِ شرکت (فصلِ ۴) گردکردنِ یک مبلغ."""
    if rounding_rule == "ROUND_1000":
        unit = decimal.Decimal(1000)
        return (amount / unit).to_integral_value(rounding=decimal.ROUND_HALF_UP) * unit
    if rounding_rule == "ROUND_100":
        unit = decimal.Decimal(100)
        return (amount / unit).to_integral_value(rounding=decimal.ROUND_HALF_UP) * unit
    if rounding_rule == "TRUNCATE":
        return amount.to_integral_value(rounding=decimal.ROUND_DOWN)
    return amount


# ---------------------------------------------------------------------
# حداقلِ دستمزدِ مصوب
# ---------------------------------------------------------------------
@dataclass
class MinimumWageRateRow:
    minimum_wage_rate_id: int
    effective_from: datetime.date
    effective_to: datetime.date | None
    monthly_amount: decimal.Decimal
    daily_amount: decimal.Decimal | None
    hourly_amount: decimal.Decimal | None


def list_minimum_wage_rates(company_id: int) -> list[MinimumWageRateRow]:
    with new_session() as session:
        rows = session.scalars(
            select(MinimumWageRate)
            .where(MinimumWageRate.company_id == company_id)
            .order_by(MinimumWageRate.effective_from.desc())
        ).all()
        return [
            MinimumWageRateRow(
                r.minimum_wage_rate_id, r.effective_from, r.effective_to, r.monthly_amount, r.daily_amount, r.hourly_amount
            )
            for r in rows
        ]


def _overlaps(a_from: datetime.date, a_to: datetime.date | None, b_from: datetime.date, b_to: datetime.date | None) -> bool:
    a_to = a_to or datetime.date.max
    b_to = b_to or datetime.date.max
    return a_from <= b_to and b_from <= a_to


def _check_minimum_wage_overlap(
    session, company_id: int, effective_from: datetime.date, effective_to: datetime.date | None, exclude_id: int | None
) -> None:
    existing = session.scalars(select(MinimumWageRate).where(MinimumWageRate.company_id == company_id)).all()
    for row in existing:
        if exclude_id is not None and row.minimum_wage_rate_id == exclude_id:
            continue
        if _overlaps(effective_from, effective_to, row.effective_from, row.effective_to):
            raise ValueError("این بازه با یک دورهٔ حداقل‌دستمزدِ دیگر هم‌پوشانی دارد.")


def create_minimum_wage_rate(
    company_id: int,
    effective_from: datetime.date,
    effective_to: datetime.date | None,
    monthly_amount: decimal.Decimal,
    daily_amount: decimal.Decimal | None,
    hourly_amount: decimal.Decimal | None,
) -> int:
    if effective_to is not None and effective_to < effective_from:
        raise ValueError("تاریخِ پایان نمی‌تواند قبل از تاریخِ شروع باشد.")
    if monthly_amount <= 0:
        raise ValueError("مبلغِ ماهانه باید مثبت باشد.")
    with new_session() as session:
        _check_minimum_wage_overlap(session, company_id, effective_from, effective_to, None)
        row = MinimumWageRate(
            company_id=company_id,
            effective_from=effective_from,
            effective_to=effective_to,
            monthly_amount=monthly_amount,
            daily_amount=daily_amount,
            hourly_amount=hourly_amount,
        )
        session.add(row)
        session.commit()
        return row.minimum_wage_rate_id


def update_minimum_wage_rate(
    minimum_wage_rate_id: int,
    company_id: int,
    effective_from: datetime.date,
    effective_to: datetime.date | None,
    monthly_amount: decimal.Decimal,
    daily_amount: decimal.Decimal | None,
    hourly_amount: decimal.Decimal | None,
) -> None:
    if effective_to is not None and effective_to < effective_from:
        raise ValueError("تاریخِ پایان نمی‌تواند قبل از تاریخِ شروع باشد.")
    if monthly_amount <= 0:
        raise ValueError("مبلغِ ماهانه باید مثبت باشد.")
    with new_session() as session:
        row = session.get(MinimumWageRate, minimum_wage_rate_id)
        if row is None:
            raise ValueError("این دورهٔ حداقل‌دستمزد یافت نشد.")
        _check_minimum_wage_overlap(session, company_id, effective_from, effective_to, minimum_wage_rate_id)
        row.effective_from = effective_from
        row.effective_to = effective_to
        row.monthly_amount = monthly_amount
        row.daily_amount = daily_amount
        row.hourly_amount = hourly_amount
        session.commit()


def delete_minimum_wage_rate(minimum_wage_rate_id: int) -> None:
    with new_session() as session:
        row = session.get(MinimumWageRate, minimum_wage_rate_id)
        if row is not None:
            session.delete(row)
            session.commit()


def get_current_minimum_wage(company_id: int, as_of_date: datetime.date) -> MinimumWageRateRow | None:
    """اول تفاوتِ اختصاصیِ همان شرکت را برایِ این تاریخ می‌جوید؛ اگر
    نبود، به مقدارِ سراسری (company_id IS NULL) برمی‌گردد."""
    with new_session() as session:
        for target_company_id in (company_id, None):
            row = session.scalar(
                select(MinimumWageRate).where(
                    MinimumWageRate.company_id == target_company_id,
                    MinimumWageRate.effective_from <= as_of_date,
                    (MinimumWageRate.effective_to.is_(None)) | (MinimumWageRate.effective_to >= as_of_date),
                )
            )
            if row is not None:
                return MinimumWageRateRow(
                    row.minimum_wage_rate_id, row.effective_from, row.effective_to, row.monthly_amount, row.daily_amount, row.hourly_amount
                )
    return None


# ---------------------------------------------------------------------
# تنظیماتِ کلیِ حقوق‌ودستمزدِ شرکت
# ---------------------------------------------------------------------
@dataclass
class CompanySettingsRow:
    standard_month_days: int
    calculation_basis: str
    rounding_rule: str
    default_pay_day: int | None
    payslip_currency_id: int | None
    salary_payable_gl_account_id: int | None = None
    salary_payable_detail_account_id: int | None = None


def get_company_settings(company_id: int) -> CompanySettingsRow:
    with new_session() as session:
        row = session.get(CompanyPayrollSettings, company_id)
        if row is None:
            return CompanySettingsRow(30, "DAILY", "NONE", None, None, None, None)
        return CompanySettingsRow(
            row.standard_month_days, row.calculation_basis, row.rounding_rule, row.default_pay_day,
            row.payslip_currency_id, row.salary_payable_gl_account_id, row.salary_payable_detail_account_id,
        )


_UNSET = object()


def save_company_settings(
    company_id: int,
    standard_month_days: int,
    calculation_basis: str,
    rounding_rule: str,
    default_pay_day: int | None,
    payslip_currency_id: int | None,
    salary_payable_gl_account_id: int | None = _UNSET,
    salary_payable_detail_account_id: int | None = _UNSET,
) -> None:
    """⚠ salary_payable_gl_account_id/salary_payable_detail_account_id
    فقط وقتی صریحاً پاس داده شوند تغییر می‌کنند (پیش‌فرضِ سنتینلِ
    _UNSET) — چامهایِ قدیمی‌ترِ این تابع این پارامترها را نمی‌شناسند و
    نباید مقدارِ ازقبل‌تنظیم‌شده را با None پاک کنند."""
    if standard_month_days <= 0:
        raise ValueError("تعدادِ روزهایِ استانداردِ ماه باید مثبت باشد.")
    if calculation_basis not in _CALCULATION_BASIS_CHOICES:
        raise ValueError("مبنایِ محاسبه نامعتبر است.")
    if rounding_rule not in _ROUNDING_RULE_CHOICES:
        raise ValueError("قاعدهٔ گردکردن نامعتبر است.")
    if default_pay_day is not None and not (1 <= default_pay_day <= 31):
        raise ValueError("روزِ پرداخت باید بینِ ۱ تا ۳۱ باشد.")
    with new_session() as session:
        row = session.get(CompanyPayrollSettings, company_id)
        if row is None:
            row = CompanyPayrollSettings(company_id=company_id)
            session.add(row)
        row.standard_month_days = standard_month_days
        row.calculation_basis = calculation_basis
        row.rounding_rule = rounding_rule
        row.default_pay_day = default_pay_day
        row.payslip_currency_id = payslip_currency_id
        if salary_payable_gl_account_id is not _UNSET:
            row.salary_payable_gl_account_id = salary_payable_gl_account_id
        if salary_payable_detail_account_id is not _UNSET:
            row.salary_payable_detail_account_id = salary_payable_detail_account_id
        session.commit()


# ---------------------------------------------------------------------
# قوانینِ حقوق و دستمزد (Payroll Policies) — resolve_policy عمومی
# ---------------------------------------------------------------------
@dataclass
class PolicyRow:
    policy_code: str
    label: str
    value_numeric: decimal.Decimal | None
    value_text: str | None
    effective_from: datetime.date
    is_company_override: bool


def resolve_policy(company_id: int, policy_code: str, as_of_date: datetime.date) -> PayrollPolicy | None:
    """الگویِ عمومیِ فصلِ ۱۸: اول override اختصاصیِ همان شرکت برایِ این
    تاریخ، وگرنه مقدارِ سراسری (company_id IS NULL)."""
    with new_session() as session:
        for target_company_id in (company_id, None):
            row = session.scalar(
                select(PayrollPolicy).where(
                    PayrollPolicy.company_id == target_company_id,
                    PayrollPolicy.policy_code == policy_code,
                    PayrollPolicy.effective_from <= as_of_date,
                    (PayrollPolicy.effective_to.is_(None)) | (PayrollPolicy.effective_to >= as_of_date),
                )
            )
            if row is not None:
                session.expunge(row)
                return row
    return None


def resolve_policy_value(company_id: int, policy_code: str, as_of_date: datetime.date) -> decimal.Decimal | None:
    row = resolve_policy(company_id, policy_code, as_of_date)
    return row.value_numeric if row is not None else None


def list_policies(company_id: int, as_of_date: datetime.date | None = None) -> list[PolicyRow]:
    as_of_date = as_of_date or datetime.date.today()
    result = []
    with new_session() as session:
        for code, label in POLICY_DEFINITIONS:
            company_row = session.scalar(
                select(PayrollPolicy).where(
                    PayrollPolicy.company_id == company_id,
                    PayrollPolicy.policy_code == code,
                    PayrollPolicy.effective_from <= as_of_date,
                    (PayrollPolicy.effective_to.is_(None)) | (PayrollPolicy.effective_to >= as_of_date),
                )
            )
            row = company_row
            is_override = row is not None
            if row is None:
                row = session.scalar(
                    select(PayrollPolicy).where(
                        PayrollPolicy.company_id.is_(None),
                        PayrollPolicy.policy_code == code,
                        PayrollPolicy.effective_from <= as_of_date,
                        (PayrollPolicy.effective_to.is_(None)) | (PayrollPolicy.effective_to >= as_of_date),
                    )
                )
            if row is None:
                result.append(PolicyRow(code, label, None, None, as_of_date, False))
            else:
                result.append(PolicyRow(code, label, row.value_numeric, row.value_text, row.effective_from, is_override))
    return result


def set_policy(
    company_id: int,
    policy_code: str,
    effective_from: datetime.date,
    value_numeric: decimal.Decimal | None,
    value_text: str | None = None,
) -> None:
    """یک ردیفِ تازه برایِ (company_id, policy_code) ثبت می‌کند — طبقِ
    سندِ طراحی (فصلِ ۱۸): «ردیفِ قبلی با effective_to بسته و دست‌نخورده
    باقی می‌ماند» تا محاسبهٔ دوره‌هایِ گذشته درست بماند."""
    if value_numeric is None and value_text is None:
        raise ValueError("مقداری برایِ این قانون وارد کنید.")
    with new_session() as session:
        open_row = session.scalar(
            select(PayrollPolicy).where(
                PayrollPolicy.company_id == company_id,
                PayrollPolicy.policy_code == policy_code,
                PayrollPolicy.effective_to.is_(None),
            )
        )
        if open_row is not None:
            if open_row.effective_from >= effective_from:
                raise ValueError("تاریخِ اجرا باید بعد از تاریخِ اجرایِ نسخهٔ فعلی باشد.")
            open_row.effective_to = effective_from - datetime.timedelta(days=1)
        session.add(
            PayrollPolicy(
                company_id=company_id,
                policy_code=policy_code,
                effective_from=effective_from,
                value_numeric=value_numeric,
                value_text=value_text,
            )
        )
        session.commit()


# ---------------------------------------------------------------------
# موتورِ عمومیِ آیتمِ حقوقی (فصلِ ۶) + تکمیل‌هایِ مزایا (فصلِ ۷) و
# کسورات (فصلِ ۸)
# ---------------------------------------------------------------------
_ITEM_TYPE_CHOICES = ("EARNING", "BENEFIT", "DEDUCTION", "INSURANCE", "TAX")
_CALCULATION_METHOD_CHOICES = (
    "BASE_SALARY_FROM_CONTRACT",
    "FIXED",
    "PERCENTAGE_OF_BASE",
    "FORMULA",
    "MANUAL",
    "SYSTEM_TAX_ENGINE",
)
_CALCULATION_PHASE_CHOICES = ("EARNING_PHASE", "INSURANCE_PHASE", "DEDUCTION_PHASE", "TAX_PHASE")


@dataclass
class PayItemRow:
    pay_item_id: int
    code: str
    name: str
    item_type: str
    calculation_method: str
    formula_expression: str | None
    fixed_amount: decimal.Decimal | None
    percentage: decimal.Decimal | None
    is_prorated: bool
    is_taxable: bool
    is_insurable: bool
    is_continuous_benefit: bool
    calculation_phase: str
    gl_account_id: int | None
    detail_account_id: int | None
    description_template: str | None
    display_order: int
    description: str | None
    is_active: bool
    eligibility_condition: str | None
    is_cash: bool
    tax_exempt_ceiling_policy_code: str | None
    insurance_exempt_ceiling_policy_code: str | None
    is_court_order: bool
    deduction_priority: int | None


def _pay_item_row(p: PayItemDefinition) -> PayItemRow:
    return PayItemRow(
        p.pay_item_id, p.code, p.name, p.item_type, p.calculation_method, p.formula_expression,
        p.fixed_amount, p.percentage, p.is_prorated, p.is_taxable, p.is_insurable, p.is_continuous_benefit,
        p.calculation_phase, p.gl_account_id, p.detail_account_id, p.description_template,
        p.display_order, p.description, p.is_active,
        p.eligibility_condition, p.is_cash, p.tax_exempt_ceiling_policy_code, p.insurance_exempt_ceiling_policy_code,
        p.is_court_order, p.deduction_priority,
    )


def list_pay_items(company_id: int, item_type: str | None = None, active_only: bool = False) -> list[PayItemRow]:
    with new_session() as session:
        query = select(PayItemDefinition).where(PayItemDefinition.company_id == company_id)
        if item_type is not None:
            query = query.where(PayItemDefinition.item_type == item_type)
        if active_only:
            query = query.where(PayItemDefinition.is_active)
        rows = session.scalars(query.order_by(PayItemDefinition.display_order, PayItemDefinition.code)).all()
        return [_pay_item_row(p) for p in rows]


def get_pay_item(pay_item_id: int) -> PayItemRow | None:
    with new_session() as session:
        p = session.get(PayItemDefinition, pay_item_id)
        return _pay_item_row(p) if p is not None else None


def _validate_pay_item_formula(company_id: int, formula_expression: str | None, own_code: str | None) -> None:
    if not formula_expression:
        return
    node = payroll_formula.parse_formula(formula_expression)
    referenced = payroll_formula.extract_item_refs(node)
    if own_code is not None and own_code in referenced:
        raise ValueError("فرمول نمی‌تواند به خودِ همین آیتم ارجاع بدهد.")
    if not referenced:
        return
    with new_session() as session:
        existing_codes = {
            code
            for (code,) in session.execute(
                select(PayItemDefinition.code).where(PayItemDefinition.company_id == company_id)
            )
        }
    missing = referenced - existing_codes
    if missing:
        raise ValueError(f"آیتم‌هایِ ارجاع‌داده‌شده در فرمول تعریف نشده‌اند: {', '.join(sorted(missing))}")


def _validate_pay_item_fields(
    item_type: str,
    calculation_method: str,
    calculation_phase: str,
    formula_expression: str | None,
    eligibility_condition: str | None,
) -> None:
    if item_type not in _ITEM_TYPE_CHOICES:
        raise ValueError("نوعِ آیتم نامعتبر است.")
    if calculation_method not in _CALCULATION_METHOD_CHOICES:
        raise ValueError("روشِ محاسبه نامعتبر است.")
    if calculation_phase not in _CALCULATION_PHASE_CHOICES:
        raise ValueError("فازِ محاسبه نامعتبر است.")
    if calculation_method == "FORMULA" and not formula_expression:
        raise ValueError("برایِ روشِ فرمول، عبارتِ فرمول الزامی است.")
    if eligibility_condition:
        payroll_formula.parse_condition(eligibility_condition)


def create_pay_item(
    company_id: int,
    code: str,
    name: str,
    item_type: str,
    calculation_method: str,
    calculation_phase: str,
    *,
    formula_expression: str | None = None,
    fixed_amount: decimal.Decimal | None = None,
    percentage: decimal.Decimal | None = None,
    is_prorated: bool = False,
    is_taxable: bool = False,
    is_insurable: bool = False,
    is_continuous_benefit: bool = False,
    gl_account_id: int | None = None,
    detail_account_id: int | None = None,
    description_template: str | None = None,
    display_order: int = 0,
    description: str | None = None,
    eligibility_condition: str | None = None,
    is_cash: bool = True,
    tax_exempt_ceiling_policy_code: str | None = None,
    insurance_exempt_ceiling_policy_code: str | None = None,
    is_court_order: bool = False,
    deduction_priority: int | None = None,
) -> int:
    code = code.strip()
    name = name.strip()
    if not code or not name:
        raise ValueError("کد و نام الزامی است.")
    _validate_pay_item_fields(item_type, calculation_method, calculation_phase, formula_expression, eligibility_condition)
    _validate_pay_item_formula(company_id, formula_expression, None)
    with new_session() as session:
        exists = session.scalar(
            select(PayItemDefinition).where(PayItemDefinition.company_id == company_id, PayItemDefinition.code == code)
        )
        if exists is not None:
            raise ValueError("این کد قبلاً استفاده شده است.")
        if calculation_method == "BASE_SALARY_FROM_CONTRACT":
            base_exists = session.scalar(
                select(PayItemDefinition).where(
                    PayItemDefinition.company_id == company_id,
                    PayItemDefinition.calculation_method == "BASE_SALARY_FROM_CONTRACT",
                )
            )
            if base_exists is not None:
                raise ValueError("فقط یک آیتمِ «حقوقِ پایه از قرارداد» در هر شرکت مجاز است.")
        item = PayItemDefinition(
            company_id=company_id, code=code, name=name, item_type=item_type,
            calculation_method=calculation_method, formula_expression=formula_expression,
            fixed_amount=fixed_amount, percentage=percentage, is_prorated=is_prorated,
            is_taxable=is_taxable, is_insurable=is_insurable, is_continuous_benefit=is_continuous_benefit,
            calculation_phase=calculation_phase, gl_account_id=gl_account_id, detail_account_id=detail_account_id,
            description_template=description_template, display_order=display_order,
            description=description, eligibility_condition=eligibility_condition, is_cash=is_cash,
            tax_exempt_ceiling_policy_code=tax_exempt_ceiling_policy_code,
            insurance_exempt_ceiling_policy_code=insurance_exempt_ceiling_policy_code,
            is_court_order=is_court_order, deduction_priority=deduction_priority,
        )
        session.add(item)
        session.commit()
        return item.pay_item_id


def update_pay_item(
    pay_item_id: int,
    name: str,
    item_type: str,
    calculation_method: str,
    calculation_phase: str,
    *,
    formula_expression: str | None = None,
    fixed_amount: decimal.Decimal | None = None,
    percentage: decimal.Decimal | None = None,
    is_prorated: bool = False,
    is_taxable: bool = False,
    is_insurable: bool = False,
    is_continuous_benefit: bool = False,
    gl_account_id: int | None = None,
    detail_account_id: int | None = None,
    description_template: str | None = None,
    display_order: int = 0,
    description: str | None = None,
    is_active: bool = True,
    eligibility_condition: str | None = None,
    is_cash: bool = True,
    tax_exempt_ceiling_policy_code: str | None = None,
    insurance_exempt_ceiling_policy_code: str | None = None,
    is_court_order: bool = False,
    deduction_priority: int | None = None,
) -> None:
    name = name.strip()
    if not name:
        raise ValueError("نام الزامی است.")
    with new_session() as session:
        item = session.get(PayItemDefinition, pay_item_id)
        if item is None:
            raise ValueError("این آیتمِ حقوقی یافت نشد.")
        _validate_pay_item_fields(item_type, calculation_method, calculation_phase, formula_expression, eligibility_condition)
        _validate_pay_item_formula(item.company_id, formula_expression, item.code)
        if calculation_method == "BASE_SALARY_FROM_CONTRACT" and item.calculation_method != "BASE_SALARY_FROM_CONTRACT":
            base_exists = session.scalar(
                select(PayItemDefinition).where(
                    PayItemDefinition.company_id == item.company_id,
                    PayItemDefinition.calculation_method == "BASE_SALARY_FROM_CONTRACT",
                )
            )
            if base_exists is not None:
                raise ValueError("فقط یک آیتمِ «حقوقِ پایه از قرارداد» در هر شرکت مجاز است.")
        item.name = name
        item.item_type = item_type
        item.calculation_method = calculation_method
        item.calculation_phase = calculation_phase
        item.formula_expression = formula_expression
        item.fixed_amount = fixed_amount
        item.percentage = percentage
        item.is_prorated = is_prorated
        item.is_taxable = is_taxable
        item.is_insurable = is_insurable
        item.is_continuous_benefit = is_continuous_benefit
        item.gl_account_id = gl_account_id
        item.detail_account_id = detail_account_id
        item.description_template = description_template
        item.display_order = display_order
        item.description = description
        item.is_active = is_active
        item.eligibility_condition = eligibility_condition
        item.is_cash = is_cash
        item.tax_exempt_ceiling_policy_code = tax_exempt_ceiling_policy_code
        item.insurance_exempt_ceiling_policy_code = insurance_exempt_ceiling_policy_code
        item.is_court_order = is_court_order
        item.deduction_priority = deduction_priority
        session.commit()


def delete_pay_item(pay_item_id: int) -> None:
    with new_session() as session:
        item = session.get(PayItemDefinition, pay_item_id)
        if item is None:
            return
        used_in_payslip = session.scalar(select(PayslipLine).where(PayslipLine.pay_item_id == pay_item_id))
        if used_in_payslip is not None:
            raise ValueError("این آیتم در فیش‌هایِ محاسبه‌شده استفاده شده و قابلِ حذف نیست.")
        referencing = [
            other
            for other in session.scalars(
                select(PayItemDefinition).where(PayItemDefinition.company_id == item.company_id)
            ).all()
            if other.formula_expression
            and item.code in payroll_formula.extract_item_refs(payroll_formula.parse_formula(other.formula_expression))
        ]
        if referencing:
            codes = ", ".join(o.code for o in referencing)
            raise ValueError(f"این آیتم در فرمولِ آیتم‌هایِ دیگر استفاده شده است: {codes}")
        session.execute(
            EmployeePayComponent.__table__.delete().where(EmployeePayComponent.pay_item_id == pay_item_id)
        )
        session.delete(item)
        session.commit()


# ---------------------------------------------------------------------
# تخصیصِ آیتم به کارمندِ خاص (فصلِ ۶)
# ---------------------------------------------------------------------
@dataclass
class EmployeePayComponentRow:
    component_id: int
    employee_id: int
    pay_item_id: int
    pay_item_code: str
    pay_item_name: str
    amount: decimal.Decimal | None
    effective_from: datetime.date
    effective_to: datetime.date | None


def list_employee_pay_components(employee_id: int) -> list[EmployeePayComponentRow]:
    with new_session() as session:
        rows = session.execute(
            select(EmployeePayComponent, PayItemDefinition)
            .join(PayItemDefinition, PayItemDefinition.pay_item_id == EmployeePayComponent.pay_item_id)
            .where(EmployeePayComponent.employee_id == employee_id)
            .order_by(EmployeePayComponent.effective_from.desc())
        ).all()
        return [
            EmployeePayComponentRow(
                c.component_id, c.employee_id, c.pay_item_id, p.code, p.name, c.amount, c.effective_from, c.effective_to
            )
            for c, p in rows
        ]


def set_employee_pay_component(
    employee_id: int,
    pay_item_id: int,
    amount: decimal.Decimal | None,
    effective_from: datetime.date,
    effective_to: datetime.date | None,
) -> int:
    if effective_to is not None and effective_to < effective_from:
        raise ValueError("تاریخِ پایان نمی‌تواند قبل از تاریخِ شروع باشد.")
    with new_session() as session:
        component = EmployeePayComponent(
            employee_id=employee_id, pay_item_id=pay_item_id, amount=amount,
            effective_from=effective_from, effective_to=effective_to,
        )
        session.add(component)
        session.commit()
        return component.component_id


def delete_employee_pay_component(component_id: int) -> None:
    with new_session() as session:
        component = session.get(EmployeePayComponent, component_id)
        if component is not None:
            session.delete(component)
            session.commit()


# ---------------------------------------------------------------------
# کسرِ موردی (فصلِ ۸ — Ad-hoc Deduction Entry)
# ---------------------------------------------------------------------
@dataclass
class DeductionEntryRow:
    deduction_entry_id: int
    employee_id: int
    pay_item_id: int
    pay_item_code: str
    pay_item_name: str
    period_id: int
    amount: decimal.Decimal
    reason: str | None
    status: str


def list_deduction_entries(period_id: int) -> list[DeductionEntryRow]:
    with new_session() as session:
        rows = session.execute(
            select(DeductionEntry, PayItemDefinition)
            .join(PayItemDefinition, PayItemDefinition.pay_item_id == DeductionEntry.pay_item_id)
            .where(DeductionEntry.period_id == period_id)
        ).all()
        return [
            DeductionEntryRow(
                d.deduction_entry_id, d.employee_id, d.pay_item_id, p.code, p.name, d.period_id, d.amount, d.reason, d.status
            )
            for d, p in rows
        ]


def create_deduction_entry(
    employee_id: int, pay_item_id: int, period_id: int, amount: decimal.Decimal, reason: str | None
) -> int:
    if amount <= 0:
        raise ValueError("مبلغِ کسر باید مثبت باشد.")
    with new_session() as session:
        pay_item = session.get(PayItemDefinition, pay_item_id)
        if pay_item is None or pay_item.item_type != "DEDUCTION":
            raise ValueError("این آیتم از نوعِ کسورات نیست.")
        if pay_item.is_court_order and not (reason and reason.strip()):
            raise ValueError("برایِ کسرِ حکمِ دادگاه، دلیل/توضیح الزامی است.")
        entry = DeductionEntry(
            employee_id=employee_id, pay_item_id=pay_item_id, period_id=period_id,
            amount=amount, reason=reason, status="PENDING",
        )
        session.add(entry)
        session.commit()
        return entry.deduction_entry_id


def set_deduction_entry_status(deduction_entry_id: int, status: str) -> None:
    if status not in ("PENDING", "APPROVED", "APPLIED", "DEFERRED", "CANCELLED"):
        raise ValueError("وضعیتِ نامعتبر.")
    with new_session() as session:
        entry = session.get(DeductionEntry, deduction_entry_id)
        if entry is None:
            raise ValueError("این کسرِ موردی یافت نشد.")
        entry.status = status
        session.commit()


# ---------------------------------------------------------------------
# بیمهٔ تأمین اجتماعی (فصلِ ۹)
# ---------------------------------------------------------------------
@dataclass
class InsuranceConfigRow:
    insurance_config_id: int
    effective_from: datetime.date
    effective_to: datetime.date | None
    employee_rate: decimal.Decimal
    employer_rate: decimal.Decimal
    unemployment_rate: decimal.Decimal
    insurable_wage_ceiling_policy_code: str | None
    insurable_wage_floor: decimal.Decimal | None
    employer_expense_gl_account_id: int | None
    employer_expense_detail_account_id: int | None
    is_company_override: bool


@dataclass
class InsuranceResult:
    insurable_wage: decimal.Decimal
    employee_share: decimal.Decimal
    employer_share: decimal.Decimal


def _insurance_config_row(c: InsuranceConfig, is_override: bool) -> InsuranceConfigRow:
    return InsuranceConfigRow(
        c.insurance_config_id, c.effective_from, c.effective_to, c.employee_rate, c.employer_rate,
        c.unemployment_rate, c.insurable_wage_ceiling_policy_code, c.insurable_wage_floor,
        c.employer_expense_gl_account_id, c.employer_expense_detail_account_id, is_override,
    )


def list_insurance_configs(company_id: int) -> list[InsuranceConfigRow]:
    with new_session() as session:
        rows = session.scalars(
            select(InsuranceConfig).where(InsuranceConfig.company_id == company_id).order_by(InsuranceConfig.effective_from.desc())
        ).all()
        return [_insurance_config_row(c, True) for c in rows]


def get_insurance_config(company_id: int, as_of_date: datetime.date) -> InsuranceConfigRow | None:
    with new_session() as session:
        for target_company_id, is_override in ((company_id, True), (None, False)):
            row = session.scalar(
                select(InsuranceConfig).where(
                    InsuranceConfig.company_id == target_company_id,
                    InsuranceConfig.effective_from <= as_of_date,
                    (InsuranceConfig.effective_to.is_(None)) | (InsuranceConfig.effective_to >= as_of_date),
                )
            )
            if row is not None:
                return _insurance_config_row(row, is_override)
    return None


def create_insurance_config(
    company_id: int,
    effective_from: datetime.date,
    effective_to: datetime.date | None,
    employee_rate: decimal.Decimal,
    employer_rate: decimal.Decimal,
    unemployment_rate: decimal.Decimal,
    insurable_wage_ceiling_policy_code: str | None,
    insurable_wage_floor: decimal.Decimal | None,
    employer_expense_gl_account_id: int | None = None,
    employer_expense_detail_account_id: int | None = None,
) -> int:
    for rate in (employee_rate, employer_rate, unemployment_rate):
        if rate < 0 or rate > 1:
            raise ValueError("نرخ‌هایِ بیمه باید بینِ ۰ تا ۱۰۰٪ باشند.")
    if effective_to is not None and effective_to < effective_from:
        raise ValueError("تاریخِ پایان نمی‌تواند قبل از تاریخِ شروع باشد.")
    with new_session() as session:
        existing = session.scalars(select(InsuranceConfig).where(InsuranceConfig.company_id == company_id)).all()
        for row in existing:
            if _overlaps(effective_from, effective_to, row.effective_from, row.effective_to):
                raise ValueError("این بازه با یک تنظیمِ بیمهٔ دیگر هم‌پوشانی دارد.")
        config = InsuranceConfig(
            company_id=company_id, effective_from=effective_from, effective_to=effective_to,
            employee_rate=employee_rate, employer_rate=employer_rate, unemployment_rate=unemployment_rate,
            insurable_wage_ceiling_policy_code=insurable_wage_ceiling_policy_code,
            insurable_wage_floor=insurable_wage_floor,
            employer_expense_gl_account_id=employer_expense_gl_account_id,
            employer_expense_detail_account_id=employer_expense_detail_account_id,
        )
        session.add(config)
        session.commit()
        return config.insurance_config_id


def delete_insurance_config(insurance_config_id: int) -> None:
    with new_session() as session:
        config = session.get(InsuranceConfig, insurance_config_id)
        if config is not None:
            session.delete(config)
            session.commit()


def compute_insurance(company_id: int, as_of_date: datetime.date, insurable_wage_total: decimal.Decimal) -> InsuranceResult:
    """طبقِ فرمولِ فصلِ ۹: مزد_مشمول = min(max(جمعِ آیتم‌هایِ مشمول, کف), سقف).
    سهمِ کارمند/کارفرما از رویِ همان مزدِ مشمول (نه جمعِ خام) محاسبه می‌شود."""
    config = get_insurance_config(company_id, as_of_date)
    if config is None:
        raise ValueError("هیچ تنظیماتِ بیمه‌ای برایِ این تاریخ تعریف نشده است.")
    floor = config.insurable_wage_floor
    if floor is None:
        min_wage = get_current_minimum_wage(company_id, as_of_date)
        floor = min_wage.monthly_amount if min_wage is not None else decimal.Decimal(0)
    wage = max(insurable_wage_total, floor)
    if config.insurable_wage_ceiling_policy_code:
        multiple = resolve_policy_value(company_id, config.insurable_wage_ceiling_policy_code, as_of_date)
        if multiple is not None:
            min_wage = get_current_minimum_wage(company_id, as_of_date)
            if min_wage is not None:
                ceiling = min_wage.monthly_amount * multiple
                wage = min(wage, ceiling)
    employee_share = wage * config.employee_rate
    employer_share = wage * (config.employer_rate + config.unemployment_rate)
    return InsuranceResult(wage, employee_share, employer_share)


# ---------------------------------------------------------------------
# مالیات بر درآمدِ حقوق (فصلِ ۱۰) — نظامِ تجمعیِ سالانه
# ---------------------------------------------------------------------
@dataclass
class TaxBracketRow:
    tax_bracket_id: int
    bracket_order: int
    from_annual_amount: decimal.Decimal
    to_annual_amount: decimal.Decimal | None
    rate: decimal.Decimal


@dataclass
class AnnualTaxLedgerRow:
    employee_id: int
    tax_year: int
    cumulative_taxable_income: decimal.Decimal
    cumulative_tax_calculated: decimal.Decimal
    cumulative_tax_paid: decimal.Decimal
    status: str


def get_tax_brackets(company_id: int, as_of_date: datetime.date) -> list[TaxBracketRow]:
    """اولویت با پلکان‌هایِ اختصاصیِ همان شرکت برایِ این تاریخ؛ اگر
    نبود، پلکان‌هایِ سراسری. تنها یکی از این دو مجموعه برگردانده می‌شود
    (بدونِ ترکیب)."""
    with new_session() as session:
        for target_company_id in (company_id, None):
            rows = session.scalars(
                select(TaxBracket)
                .where(
                    TaxBracket.company_id == target_company_id,
                    TaxBracket.effective_from <= as_of_date,
                    (TaxBracket.effective_to.is_(None)) | (TaxBracket.effective_to >= as_of_date),
                )
                .order_by(TaxBracket.bracket_order)
            ).all()
            if rows:
                return [TaxBracketRow(r.tax_bracket_id, r.bracket_order, r.from_annual_amount, r.to_annual_amount, r.rate) for r in rows]
    return []


def _validate_tax_brackets(brackets: list[tuple[decimal.Decimal, decimal.Decimal | None, decimal.Decimal]]) -> None:
    if not brackets:
        raise ValueError("دستِ‌کم یک پلکان لازم است.")
    previous_to = decimal.Decimal(0)
    previous_rate = decimal.Decimal(-1)
    for i, (from_amount, to_amount, rate) in enumerate(brackets):
        if from_amount != previous_to:
            raise ValueError("پلکان‌ها باید پیوسته باشند (بدونِ شکاف/هم‌پوشانی).")
        if to_amount is not None and to_amount <= from_amount:
            raise ValueError("سقفِ هر پلکان باید بزرگ‌تر از کفِ آن باشد.")
        if rate < previous_rate:
            raise ValueError("نرخِ پلکان‌ها باید صعودی باشد.")
        if to_amount is None and i != len(brackets) - 1:
            raise ValueError("فقط آخرین پلکان می‌تواند بدونِ سقف باشد.")
        previous_rate = rate
        if to_amount is not None:
            previous_to = to_amount


def set_tax_brackets(
    company_id: int,
    effective_from: datetime.date,
    brackets: list[tuple[decimal.Decimal, decimal.Decimal | None, decimal.Decimal]],
) -> None:
    """کلِ مجموعه‌یِ پلکان‌هایِ یک شرکت را از یک تاریخ به‌بعد جایگزین
    می‌کند (نه ردیف‌به‌ردیف) — چون پیوستگیِ پلکان‌ها یک قاعده‌یِ سطحِ
    مجموعه است، نه سطحِ تک‌ردیف. نسخهٔ قبلی (اگر بازه‌ی بازی داشت) با
    همان effective_from بسته و دست‌نخورده باقی می‌ماند."""
    _validate_tax_brackets(brackets)
    with new_session() as session:
        open_rows = session.scalars(
            select(TaxBracket).where(TaxBracket.company_id == company_id, TaxBracket.effective_to.is_(None))
        ).all()
        for row in open_rows:
            if row.effective_from >= effective_from:
                raise ValueError("تاریخِ اجرا باید بعد از تاریخِ اجرایِ نسخهٔ فعلی باشد.")
            row.effective_to = effective_from - datetime.timedelta(days=1)
        for order, (from_amount, to_amount, rate) in enumerate(brackets, start=1):
            session.add(
                TaxBracket(
                    company_id=company_id, effective_from=effective_from, bracket_order=order,
                    from_annual_amount=from_amount, to_annual_amount=to_amount, rate=rate,
                )
            )
        session.commit()


def apply_tax_brackets(brackets: list[TaxBracketRow], taxable_base: decimal.Decimal) -> decimal.Decimal:
    """مالیاتِ تجمعیِ محاسبه‌شده رویِ یک پایهٔ مشمولِ تجمعی — جمعِ
    مالیاتِ هر پلکان تا جایی که پایه اجازه می‌دهد (فرمولِ گام ۵ فصلِ ۱۰)."""
    if taxable_base <= 0:
        return decimal.Decimal(0)
    total = decimal.Decimal(0)
    for bracket in sorted(brackets, key=lambda b: b.bracket_order):
        if taxable_base <= bracket.from_annual_amount:
            break
        upper = bracket.to_annual_amount if bracket.to_annual_amount is not None else taxable_base
        upper = min(upper, taxable_base)
        chunk = upper - bracket.from_annual_amount
        if chunk > 0:
            total += chunk * bracket.rate
    return total


def get_tax_exemption(company_id: int, as_of_date: datetime.date) -> decimal.Decimal | None:
    with new_session() as session:
        for target_company_id in (company_id, None):
            row = session.scalar(
                select(TaxExemption).where(
                    TaxExemption.company_id == target_company_id,
                    TaxExemption.effective_from <= as_of_date,
                    (TaxExemption.effective_to.is_(None)) | (TaxExemption.effective_to >= as_of_date),
                )
            )
            if row is not None:
                return row.annual_exemption_amount
    return None


def set_tax_exemption(company_id: int, effective_from: datetime.date, annual_exemption_amount: decimal.Decimal) -> None:
    if annual_exemption_amount < 0:
        raise ValueError("سقفِ معافیت نمی‌تواند منفی باشد.")
    with new_session() as session:
        open_row = session.scalar(
            select(TaxExemption).where(TaxExemption.company_id == company_id, TaxExemption.effective_to.is_(None))
        )
        if open_row is not None:
            if open_row.effective_from >= effective_from:
                raise ValueError("تاریخِ اجرا باید بعد از تاریخِ اجرایِ نسخهٔ فعلی باشد.")
            open_row.effective_to = effective_from - datetime.timedelta(days=1)
        session.add(TaxExemption(company_id=company_id, effective_from=effective_from, annual_exemption_amount=annual_exemption_amount))
        session.commit()


def get_annual_tax_ledger(employee_id: int, tax_year: int) -> AnnualTaxLedgerRow:
    with new_session() as session:
        row = session.scalar(
            select(EmployeeAnnualTaxLedger).where(
                EmployeeAnnualTaxLedger.employee_id == employee_id, EmployeeAnnualTaxLedger.tax_year == tax_year
            )
        )
        if row is None:
            return AnnualTaxLedgerRow(employee_id, tax_year, decimal.Decimal(0), decimal.Decimal(0), decimal.Decimal(0), "OPEN")
        return AnnualTaxLedgerRow(
            row.employee_id, row.tax_year, row.cumulative_taxable_income, row.cumulative_tax_calculated, row.cumulative_tax_paid, row.status
        )


def compute_monthly_tax(
    employee_id: int,
    company_id: int,
    tax_year: int,
    months_elapsed_in_tax_year: int,
    taxable_income_this_month: decimal.Decimal,
    as_of_date: datetime.date,
) -> decimal.Decimal:
    """الگوریتمِ گام‌به‌گامِ فصلِ ۱۰ — مالیاتِ این ماه را محاسبه و
    employee_annual_tax_ledger را به‌روزرسانی می‌کند؛ مالیاتِ منفی صفر
    در نظر گرفته می‌شود (طبقِ یادداشتِ سند)."""
    brackets = get_tax_brackets(company_id, as_of_date)
    if not brackets:
        raise ValueError("هیچ پلکانِ مالیاتی‌ای برایِ این تاریخ تعریف نشده است.")
    annual_exemption = get_tax_exemption(company_id, as_of_date) or decimal.Decimal(0)

    with new_session() as session:
        ledger = session.scalar(
            select(EmployeeAnnualTaxLedger).where(
                EmployeeAnnualTaxLedger.employee_id == employee_id, EmployeeAnnualTaxLedger.tax_year == tax_year
            )
        )
        if ledger is None:
            ledger = EmployeeAnnualTaxLedger(employee_id=employee_id, tax_year=tax_year)
            session.add(ledger)
            session.flush()

        cumulative_income = ledger.cumulative_taxable_income + taxable_income_this_month
        cumulative_exemption = (annual_exemption / decimal.Decimal(12)) * months_elapsed_in_tax_year
        taxable_base = max(decimal.Decimal(0), cumulative_income - cumulative_exemption)
        cumulative_tax = apply_tax_brackets(brackets, taxable_base)
        tax_this_month = cumulative_tax - ledger.cumulative_tax_paid
        if tax_this_month < 0:
            tax_this_month = decimal.Decimal(0)

        ledger.cumulative_taxable_income = cumulative_income
        ledger.cumulative_tax_calculated = cumulative_tax
        ledger.cumulative_tax_paid = ledger.cumulative_tax_paid + tax_this_month
        session.commit()
        return tax_this_month


# ---------------------------------------------------------------------
# دوره‌هایِ حقوقی (پیش‌نیازِ فصلِ ۱۱)
# ---------------------------------------------------------------------
@dataclass
class PeriodRow:
    period_id: int
    jalali_year: int
    jalali_month: int
    period_start_date: datetime.date
    period_end_date: datetime.date
    status: str


def list_periods(company_id: int) -> list[PeriodRow]:
    with new_session() as session:
        rows = session.scalars(
            select(PayrollPeriod)
            .where(PayrollPeriod.company_id == company_id)
            .order_by(PayrollPeriod.jalali_year.desc(), PayrollPeriod.jalali_month.desc())
        ).all()
        return [PeriodRow(r.period_id, r.jalali_year, r.jalali_month, r.period_start_date, r.period_end_date, r.status) for r in rows]


def create_period(
    company_id: int, jalali_year: int, jalali_month: int, period_start_date: datetime.date, period_end_date: datetime.date
) -> int:
    if not (1 <= jalali_month <= 12):
        raise ValueError("ماه باید بینِ ۱ تا ۱۲ باشد.")
    if period_end_date < period_start_date:
        raise ValueError("تاریخِ پایان نمی‌تواند قبل از تاریخِ شروع باشد.")
    with new_session() as session:
        exists = session.scalar(
            select(PayrollPeriod).where(
                PayrollPeriod.company_id == company_id,
                PayrollPeriod.jalali_year == jalali_year,
                PayrollPeriod.jalali_month == jalali_month,
            )
        )
        if exists is not None:
            raise ValueError("این دوره قبلاً ثبت شده است.")
        period = PayrollPeriod(
            company_id=company_id, jalali_year=jalali_year, jalali_month=jalali_month,
            period_start_date=period_start_date, period_end_date=period_end_date,
        )
        session.add(period)
        session.commit()
        return period.period_id


# ---------------------------------------------------------------------
# شرحِ خودکارِ سندِ حقوق (فصلِ ۱۶) — برایِ ردیف‌هایی که به یک pay_item
# خاص وصل نیستند (حقوقِ پرداختنی/بانک، سهمِ کارفرمایِ بیمه)؛ هم‌الگو با
# treasury.description_templates، ولی جدولِ اختصاصیِ خودِ payroll تا
# مرزِ ماژول‌ها به‌هم نریزد. شرحِ هر pay_item از رویِ ستونِ
# description_template روی خودِ آن ردیف (payroll_journal.py) خوانده
# می‌شود، نه از این جدول.
PAYROLL_DESCRIPTION_KEYS = ("PAYROLL_PAYABLE", "PAYROLL_INSURANCE_EMPLOYER")
DEFAULT_PAYROLL_DESCRIPTION = "سندِ حقوق و دستمزد — دورهٔ {دوره} — اجرایِ شمارهٔ {اجرا}"


def get_payroll_description_template(company_id: int, template_key: str) -> str:
    with new_session() as session:
        row = session.get(PayrollDescriptionTemplate, (company_id, template_key))
        if row is not None:
            return row.template_text
    return DEFAULT_PAYROLL_DESCRIPTION


def set_payroll_description_template(company_id: int, template_key: str, template_text: str) -> None:
    if template_key not in PAYROLL_DESCRIPTION_KEYS:
        raise ValueError("کلیدِ قالبِ شرح نامعتبر است.")
    with new_session() as session:
        existing = session.get(PayrollDescriptionTemplate, (company_id, template_key))
        if existing is None:
            session.add(PayrollDescriptionTemplate(company_id=company_id, template_key=template_key, template_text=template_text))
        else:
            existing.template_text = template_text
        session.commit()


class _SafeFormatDict(dict):
    def __missing__(self, key):
        return ""


def render_payroll_description(template_text: str, context: dict[str, str]) -> str:
    """جایگذاریِ امنِ جای‌گذارها — کلیدِ ناشناخته/نبود به‌جایِ خطا، رشتهٔ
    خالی می‌شود؛ فرمتِ نامعتبر هم به‌جایِ کرش، همان متنِ خام را
    برمی‌گرداند (تایپوی کاربر در قالب نباید صدورِ سند را خراب کند)."""
    try:
        return template_text.format_map(_SafeFormatDict(context)).strip()
    except (ValueError, IndexError, KeyError):
        return template_text
