"""R347: لیست بیمهٔ تأمین اجتماعی و لیست مالیات حقوق یک دوره، از روی فیش‌های قطعی (قطعی‌شده یا تحویل‌شده).

خروجی جدول است (اکسل)، نه فایل دیسکت رسمی تأمین اجتماعی (DSKKAR/DSKWOR) یا قالب سامانهٔ مالیاتی؛ مشخصات رسمی آن
فایل‌ها در دسترس و آزمون‌پذیر نبود. مزد مشمول و روزهای کارکرد از R347 در خود فیش ذخیره می‌شود؛ برای فیش‌های قدیمی‌تر
و اصلاحی، مزد مشمول از «سهم بیمهٔ کارمند ÷ نرخ» و کارکرد از «روزهای استاندارد ماه» به دست می‌آید."""

from __future__ import annotations

import datetime
import decimal
from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import select

from peecha import numerals
from peecha.db.base import new_session
from peecha.db.models.hr import Employee, EmploymentContract, LookupValue, Position, Termination
from peecha.db.models.payroll import PayItemDefinition, Payslip, PayslipLine, PayrollPeriod
from peecha.services import payroll as payroll_service

_ZERO = decimal.Decimal(0)
_CENT = decimal.Decimal("0.01")
_FINAL = ("FINALIZED", "DELIVERED")


def valid_national_id(value: str | None) -> bool:
    """کنترل رقم کد ملی ده‌رقمی."""
    digits = numerals.to_ascii_digits((value or "").strip())
    if len(digits) != 10 or not digits.isdigit() or len(set(digits)) == 1:
        return False
    remainder = sum(int(d) * (10 - i) for i, d in enumerate(digits[:9])) % 11
    check = int(digits[9])
    return check == remainder if remainder < 2 else check == 11 - remainder


@dataclass
class InsuranceRow:
    employee_id: int
    employee_code: str
    insurance_no: str
    national_id: str
    first_name: str
    last_name: str
    father_name: str
    id_card_no: str
    id_issue_place: str
    birth_date: datetime.date | None
    gender: str
    nationality: str
    job_code: str
    job_title: str
    start_date: datetime.date | None
    end_date: datetime.date | None
    days: int
    daily_wage: decimal.Decimal
    monthly_wage: decimal.Decimal
    benefits: decimal.Decimal
    insurable_wage: decimal.Decimal
    total_pay: decimal.Decimal
    employee_share: decimal.Decimal
    employer_share: decimal.Decimal
    unemployment_share: decimal.Decimal


@dataclass
class InsuranceList:
    jalali_year: int
    jalali_month: int
    workshop_code: str
    workshop_name: str
    employer_name: str
    workshop_address: str
    contract_row: str
    rows: list[InsuranceRow] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    def total(self, attr: str) -> decimal.Decimal:
        return sum((getattr(r, attr) for r in self.rows), _ZERO)


@dataclass
class TaxRow:
    employee_id: int
    employee_code: str
    national_id: str
    first_name: str
    last_name: str
    hire_date: datetime.date | None
    end_date: datetime.date | None
    continuous: decimal.Decimal
    non_continuous: decimal.Decimal
    gross: decimal.Decimal
    employee_insurance: decimal.Decimal
    taxable_income: decimal.Decimal
    tax: decimal.Decimal


@dataclass
class TaxList:
    jalali_year: int
    jalali_month: int
    rows: list[TaxRow] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    def total(self, attr: str) -> decimal.Decimal:
        return sum((getattr(r, attr) for r in self.rows), _ZERO)


@dataclass
class _Slips:
    """جمع فیش‌های قطعی یک کارمند در دوره."""
    employee: Employee
    contract: EmploymentContract
    gross: decimal.Decimal = _ZERO
    insurable: decimal.Decimal = _ZERO
    days: int = 0
    taxable: decimal.Decimal = _ZERO
    by_phase: dict = field(default_factory=lambda: defaultdict(lambda: _ZERO))
    earnings: list = field(default_factory=list)  # (PayItemDefinition | None, amount)


def _period(session, company_id: int, period_id: int) -> PayrollPeriod:
    period = session.get(PayrollPeriod, period_id)
    if period is None or period.company_id != company_id:
        raise ValueError("دورهٔ حقوق یافت نشد.")
    return period


def _collect(session, period: PayrollPeriod, standard_days: int, employee_rate: decimal.Decimal | None) -> list[_Slips]:
    payslips = session.scalars(select(Payslip).where(Payslip.period_id == period.period_id, Payslip.status.in_(_FINAL))
                               .order_by(Payslip.payslip_id)).all()
    items = {p.pay_item_id: p for p in session.scalars(select(PayItemDefinition).where(
        PayItemDefinition.company_id == period.company_id))}
    out: dict[int, _Slips] = {}
    for payslip in payslips:
        lines = session.scalars(select(PayslipLine).where(PayslipLine.payslip_id == payslip.payslip_id)).all()
        slips = out.get(payslip.employee_id)
        if slips is None:
            slips = out[payslip.employee_id] = _Slips(session.get(Employee, payslip.employee_id),
                                                      session.get(EmploymentContract, payslip.contract_id))
        slips.gross += payslip.gross_amount
        for line in lines:
            slips.by_phase[line.phase] += line.amount
            if line.phase == "EARNING_PHASE":
                slips.earnings.append((items.get(line.pay_item_id), line.amount))
        share = sum((l.amount for l in lines if l.phase == "INSURANCE_PHASE"), _ZERO)
        if payslip.insurable_wage is not None:
            slips.insurable += payslip.insurable_wage
        elif employee_rate:
            slips.insurable += (share / employee_rate).quantize(_CENT)
        slips.days = max(slips.days, payslip.worked_days if payslip.worked_days is not None else standard_days)
        if payslip.taxable_income is not None:
            slips.taxable += payslip.taxable_income
        else:
            taxable = sum((a for item, a in _earnings(lines, items) if item is not None and item.is_taxable), _ZERO)
            slips.taxable += max(_ZERO, taxable - share)
    return sorted(out.values(), key=lambda s: s.employee.employee_code)


def _earnings(lines, items):
    return [(items.get(l.pay_item_id), l.amount) for l in lines if l.phase == "EARNING_PHASE"]


def _end_date(session, employee_id: int, period: PayrollPeriod) -> datetime.date | None:
    return session.scalar(select(Termination.termination_date).where(
        Termination.employee_id == employee_id, Termination.termination_date >= period.period_start_date,
        Termination.termination_date <= period.period_end_date).order_by(Termination.termination_date.desc()))


def _name(employee: Employee) -> str:
    return f"{employee.first_name} {employee.last_name or ''}".strip()


def _in_period(value: datetime.date | None, period: PayrollPeriod) -> datetime.date | None:
    return value if value is not None and period.period_start_date <= value <= period.period_end_date else None


def insurance_list(company_id: int, period_id: int) -> InsuranceList:
    settings = payroll_service.get_company_settings(company_id)
    with new_session() as session:
        period = _period(session, company_id, period_id)
        config = payroll_service.get_insurance_config(company_id, period.period_start_date)
        result = InsuranceList(period.jalali_year, period.jalali_month, settings.sso_workshop_code or "",
                               settings.sso_workshop_name or "", settings.sso_employer_name or "",
                               settings.sso_workshop_address or "", settings.sso_contract_row or "")
        if not result.workshop_code:
            result.problems.append("کد کارگاه در «تنظیمات حقوق ← مشخصات کارگاه» وارد نشده است.")
        if not result.employer_name:
            result.problems.append("نام کارفرما در «تنظیمات حقوق ← مشخصات کارگاه» وارد نشده است.")
        if config is None:
            result.problems.append("تنظیمات بیمه برای این دوره تعریف نشده است؛ سهم کارفرما صفر آمده است.")
        slips_list = _collect(session, period, settings.standard_month_days, config.employee_rate if config else None)
        if not slips_list:
            result.problems.append("فیش قطعی‌شده‌ای برای این دوره نیست.")
        genders = {v.lookup_value_id: v.name for v in session.scalars(select(LookupValue))}
        for slips in slips_list:
            e, contract = slips.employee, slips.contract
            position = session.get(Position, contract.position_id) if contract else None
            insurable = slips.insurable
            base = sum((a for item, a in slips.earnings
                        if item is not None and item.is_insurable and item.calculation_method == "BASE_SALARY_FROM_CONTRACT"), _ZERO)
            monthly_wage = min(base, insurable)
            days = slips.days
            row = InsuranceRow(
                e.employee_id, e.employee_code, e.social_security_no or "", e.national_id or "", e.first_name, e.last_name,
                e.father_name or "", e.id_card_no or "", e.id_issue_place or "", e.date_of_birth,
                genders.get(e.gender_lookup_id, ""), "ایرانی" if e.nationality_code in (None, "IR") else "غیرایرانی",
                e.insurance_job_code or "", position.title if position else "",
                _in_period(e.hire_date, period), _end_date(session, e.employee_id, period), days,
                (monthly_wage / days).quantize(_CENT) if days else _ZERO, monthly_wage, insurable - monthly_wage, insurable,
                slips.gross, slips.by_phase["INSURANCE_PHASE"],
                (insurable * config.employer_rate).quantize(_CENT) if config else _ZERO,
                (insurable * config.unemployment_rate).quantize(_CENT) if config else _ZERO,
            )
            result.rows.append(row)
            missing = [label for label, ok in (
                ("شمارهٔ بیمه", row.insurance_no), ("کد ملی معتبر", valid_national_id(row.national_id)),
                ("نام پدر", row.father_name), ("شمارهٔ شناسنامه", row.id_card_no), ("تاریخ تولد", row.birth_date),
                ("جنسیت", row.gender), ("کد شغل", row.job_code)) if not ok]
            if missing:
                result.problems.append(f"{_name(e)} ({e.employee_code}): {'، '.join(missing)} وارد نشده است.")
        return result


def tax_list(company_id: int, period_id: int) -> TaxList:
    settings = payroll_service.get_company_settings(company_id)
    with new_session() as session:
        period = _period(session, company_id, period_id)
        config = payroll_service.get_insurance_config(company_id, period.period_start_date)
        result = TaxList(period.jalali_year, period.jalali_month)
        slips_list = _collect(session, period, settings.standard_month_days, config.employee_rate if config else None)
        if not slips_list:
            result.problems.append("فیش قطعی‌شده‌ای برای این دوره نیست.")
        for slips in slips_list:
            e = slips.employee
            continuous = sum((a for item, a in slips.earnings if item is not None and (
                item.is_continuous_benefit or item.calculation_method == "BASE_SALARY_FROM_CONTRACT")), _ZERO)
            earned = sum((a for _item, a in slips.earnings), _ZERO)
            result.rows.append(TaxRow(
                e.employee_id, e.employee_code, e.national_id or "", e.first_name, e.last_name, e.hire_date,
                _end_date(session, e.employee_id, period), continuous, earned - continuous, earned,
                slips.by_phase["INSURANCE_PHASE"], slips.taxable, slips.by_phase["TAX_PHASE"]))
            if not valid_national_id(e.national_id):
                result.problems.append(f"{_name(e)} ({e.employee_code}): کد ملی معتبر وارد نشده است.")
        return result


def _date(value: datetime.date | None) -> str:
    return numerals.format_jalali_date(value) if value else ""


INSURANCE_HEADERS = [
    "ردیف", "شمارهٔ بیمه", "کد ملی", "نام", "نام خانوادگی", "نام پدر", "شمارهٔ شناسنامه", "محل صدور", "تاریخ تولد",
    "جنسیت", "ملیت", "کد شغل", "شغل", "تاریخ شروع به کار", "تاریخ ترک کار", "روزهای کارکرد", "دستمزد روزانه",
    "دستمزد ماهانه", "مزایای ماهانهٔ مشمول", "جمع دستمزد و مزایای مشمول", "جمع کل دستمزد و مزایا (مشمول و غیرمشمول)",
    "حق بیمهٔ سهم بیمه‌شده", "حق بیمهٔ سهم کارفرما", "بیمهٔ بیکاری",
]
_INSURANCE_SUMS = ("days", "monthly_wage", "benefits", "insurable_wage", "total_pay", "employee_share", "employer_share",
                   "unemployment_share")


def insurance_table(data: InsuranceList) -> tuple[list[str], list[list], list]:
    """(سرستون‌ها، ردیف‌ها، ردیف جمع) برای اکسل/چاپ؛ مبالغ عدد خام‌اند."""
    rows = [[i, r.insurance_no, r.national_id, r.first_name, r.last_name, r.father_name, r.id_card_no, r.id_issue_place,
             _date(r.birth_date), r.gender, r.nationality, r.job_code, r.job_title, _date(r.start_date), _date(r.end_date),
             r.days, r.daily_wage, r.monthly_wage, r.benefits, r.insurable_wage, r.total_pay, r.employee_share,
             r.employer_share, r.unemployment_share] for i, r in enumerate(data.rows, start=1)]
    footer = ["جمع"] + [""] * 14 + [sum(r.days for r in data.rows), ""] + [data.total(a) for a in _INSURANCE_SUMS[1:]]
    return INSURANCE_HEADERS, rows, footer


TAX_HEADERS = [
    "ردیف", "کد پرسنلی", "کد ملی", "نام", "نام خانوادگی", "تاریخ استخدام", "تاریخ پایان کار", "حقوق و مزایای مستمر",
    "مزایای غیرمستمر", "جمع حقوق و مزایا", "حق بیمهٔ سهم کارمند", "درآمد مشمول مالیات", "مالیات کسرشده",
]
_TAX_SUMS = ("continuous", "non_continuous", "gross", "employee_insurance", "taxable_income", "tax")


def tax_table(data: TaxList) -> tuple[list[str], list[list], list]:
    rows = [[i, r.employee_code, r.national_id, r.first_name, r.last_name, _date(r.hire_date), _date(r.end_date),
             r.continuous, r.non_continuous, r.gross, r.employee_insurance, r.taxable_income, r.tax]
            for i, r in enumerate(data.rows, start=1)]
    footer = ["جمع"] + [""] * 6 + [data.total(a) for a in _TAX_SUMS]
    return TAX_HEADERS, rows, footer
