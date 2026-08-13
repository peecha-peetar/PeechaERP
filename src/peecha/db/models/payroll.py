"""مدل‌های اطلاعاتِ پایه و قوانینِ حقوق و دستمزد (payroll.*).

معادل db/schema/044_payroll_core.sql (فصلِ ۴ و ۵) و
db/schema/045_payroll_pay_items_engine.sql (فصلِ ۶ تا ۱۱).
"""

from __future__ import annotations

import datetime
import decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Numeric, SmallInteger, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from peecha.db.base import Base


class MinimumWageRate(Base):
    __tablename__ = "minimum_wage_rates"
    __table_args__ = {"schema": "payroll"}

    minimum_wage_rate_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("core.companies.company_id"))
    effective_from: Mapped[datetime.date] = mapped_column(Date)
    effective_to: Mapped[datetime.date | None] = mapped_column(Date)
    monthly_amount: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2))
    daily_amount: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 2))
    hourly_amount: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 2))


class CompanyPayrollSettings(Base):
    __tablename__ = "company_settings"
    __table_args__ = {"schema": "payroll"}

    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"), primary_key=True)
    standard_month_days: Mapped[int] = mapped_column(SmallInteger, default=30)
    calculation_basis: Mapped[str] = mapped_column(String(10), default="DAILY")
    rounding_rule: Mapped[str] = mapped_column(String(20), default="NONE")
    default_pay_day: Mapped[int | None] = mapped_column(SmallInteger)
    payslip_currency_id: Mapped[int | None] = mapped_column(ForeignKey("core.currencies.currency_id"))
    salary_payable_gl_account_id: Mapped[int | None] = mapped_column(ForeignKey("acc.chart_of_accounts.account_id"))
    salary_payable_detail_account_id: Mapped[int | None] = mapped_column(ForeignKey("acc.detail_accounts.detail_account_id"))


class PayrollPolicy(Base):
    __tablename__ = "policies"
    __table_args__ = {"schema": "payroll"}

    policy_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("core.companies.company_id"))
    policy_code: Mapped[str] = mapped_column(String(60))
    effective_from: Mapped[datetime.date] = mapped_column(Date)
    effective_to: Mapped[datetime.date | None] = mapped_column(Date)
    value_numeric: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 4))
    value_text: Mapped[str | None] = mapped_column(String(500))


class PayrollPeriod(Base):
    __tablename__ = "periods"
    __table_args__ = {"schema": "payroll"}

    period_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    jalali_year: Mapped[int] = mapped_column(SmallInteger)
    jalali_month: Mapped[int] = mapped_column(SmallInteger)
    period_start_date: Mapped[datetime.date] = mapped_column(Date)
    period_end_date: Mapped[datetime.date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="OPEN")


class PayItemDefinition(Base):
    __tablename__ = "pay_item_definitions"
    __table_args__ = {"schema": "payroll"}

    pay_item_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    code: Mapped[str] = mapped_column(String(60))
    name: Mapped[str] = mapped_column(String(200))
    item_type: Mapped[str] = mapped_column(String(20))
    calculation_method: Mapped[str] = mapped_column(String(30))
    formula_expression: Mapped[str | None] = mapped_column(String(1000))
    fixed_amount: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 2))
    percentage: Mapped[decimal.Decimal | None] = mapped_column(Numeric(9, 4))
    is_prorated: Mapped[bool] = mapped_column(Boolean, default=False)
    is_taxable: Mapped[bool] = mapped_column(Boolean, default=False)
    is_insurable: Mapped[bool] = mapped_column(Boolean, default=False)
    is_continuous_benefit: Mapped[bool] = mapped_column(Boolean, default=False)
    calculation_phase: Mapped[str] = mapped_column(String(20))
    gl_account_id: Mapped[int | None] = mapped_column(ForeignKey("acc.chart_of_accounts.account_id"))
    detail_account_id: Mapped[int | None] = mapped_column(ForeignKey("acc.detail_accounts.detail_account_id"))
    description_template: Mapped[str | None] = mapped_column(String(300))
    display_order: Mapped[int] = mapped_column(SmallInteger, default=0)
    description: Mapped[str | None] = mapped_column(String(500))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    eligibility_condition: Mapped[str | None] = mapped_column(String(500))
    is_cash: Mapped[bool] = mapped_column(Boolean, default=True)
    tax_exempt_ceiling_policy_code: Mapped[str | None] = mapped_column(String(60))
    insurance_exempt_ceiling_policy_code: Mapped[str | None] = mapped_column(String(60))
    is_court_order: Mapped[bool] = mapped_column(Boolean, default=False)
    deduction_priority: Mapped[int | None] = mapped_column(SmallInteger)


class PayrollDescriptionTemplate(Base):
    """شرحِ خودکارِ ردیف‌هایِ سندِ حقوق برایِ حساب‌هایی که به یک pay_item
    خاص وصل نیستند (حقوقِ پرداختنی/بانک، سهمِ کارفرمایِ بیمه) — هم‌الگو
    با treasury.description_templates."""

    __tablename__ = "description_templates"
    __table_args__ = {"schema": "payroll"}

    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"), primary_key=True)
    template_key: Mapped[str] = mapped_column(String(30), primary_key=True)
    template_text: Mapped[str] = mapped_column(Text)


class EmployeePayComponent(Base):
    __tablename__ = "employee_pay_components"
    __table_args__ = {"schema": "payroll"}

    component_id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("hr.employees.employee_id"))
    pay_item_id: Mapped[int] = mapped_column(ForeignKey("payroll.pay_item_definitions.pay_item_id"))
    amount: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 2))
    effective_from: Mapped[datetime.date] = mapped_column(Date)
    effective_to: Mapped[datetime.date | None] = mapped_column(Date)


class DeductionEntry(Base):
    __tablename__ = "deduction_entries"
    __table_args__ = {"schema": "payroll"}

    deduction_entry_id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("hr.employees.employee_id"))
    pay_item_id: Mapped[int] = mapped_column(ForeignKey("payroll.pay_item_definitions.pay_item_id"))
    period_id: Mapped[int] = mapped_column(ForeignKey("payroll.periods.period_id"))
    amount: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2))
    reason: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(20), default="PENDING")
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class InsuranceConfig(Base):
    __tablename__ = "insurance_configs"
    __table_args__ = {"schema": "payroll"}

    insurance_config_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("core.companies.company_id"))
    effective_from: Mapped[datetime.date] = mapped_column(Date)
    effective_to: Mapped[datetime.date | None] = mapped_column(Date)
    employee_rate: Mapped[decimal.Decimal] = mapped_column(Numeric(6, 4))
    employer_rate: Mapped[decimal.Decimal] = mapped_column(Numeric(6, 4))
    unemployment_rate: Mapped[decimal.Decimal] = mapped_column(Numeric(6, 4))
    insurable_wage_ceiling_policy_code: Mapped[str | None] = mapped_column(String(60))
    insurable_wage_floor: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 2))
    employer_expense_gl_account_id: Mapped[int | None] = mapped_column(ForeignKey("acc.chart_of_accounts.account_id"))
    employer_expense_detail_account_id: Mapped[int | None] = mapped_column(ForeignKey("acc.detail_accounts.detail_account_id"))


class TaxBracket(Base):
    __tablename__ = "tax_brackets"
    __table_args__ = {"schema": "payroll"}

    tax_bracket_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("core.companies.company_id"))
    effective_from: Mapped[datetime.date] = mapped_column(Date)
    effective_to: Mapped[datetime.date | None] = mapped_column(Date)
    bracket_order: Mapped[int] = mapped_column(SmallInteger)
    from_annual_amount: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2))
    to_annual_amount: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 2))
    rate: Mapped[decimal.Decimal] = mapped_column(Numeric(6, 4))


class TaxExemption(Base):
    __tablename__ = "tax_exemptions"
    __table_args__ = {"schema": "payroll"}

    tax_exemption_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("core.companies.company_id"))
    effective_from: Mapped[datetime.date] = mapped_column(Date)
    effective_to: Mapped[datetime.date | None] = mapped_column(Date)
    annual_exemption_amount: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2))


class EmployeeAnnualTaxLedger(Base):
    __tablename__ = "employee_annual_tax_ledger"
    __table_args__ = {"schema": "payroll"}

    ledger_id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("hr.employees.employee_id"))
    tax_year: Mapped[int] = mapped_column(SmallInteger)
    cumulative_taxable_income: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=0)
    cumulative_tax_calculated: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=0)
    cumulative_tax_paid: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=0)
    status: Mapped[str] = mapped_column(String(10), default="OPEN")


class PayrollRun(Base):
    __tablename__ = "runs"
    __table_args__ = {"schema": "payroll"}

    run_id: Mapped[int] = mapped_column(primary_key=True)
    period_id: Mapped[int] = mapped_column(ForeignKey("payroll.periods.period_id"))
    run_no: Mapped[int] = mapped_column(SmallInteger)
    run_type: Mapped[str] = mapped_column(String(20), default="REGULAR")
    scope_org_unit_id: Mapped[int | None] = mapped_column(ForeignKey("hr.organizational_units.org_unit_id"))
    status: Mapped[str] = mapped_column(String(20), default="DRAFT")
    started_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    triggered_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    error_log: Mapped[str | None] = mapped_column(String(2000))


class Payslip(Base):
    __tablename__ = "payslips"
    __table_args__ = {"schema": "payroll"}

    payslip_id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("payroll.runs.run_id"))
    employee_id: Mapped[int] = mapped_column(ForeignKey("hr.employees.employee_id"))
    contract_id: Mapped[int] = mapped_column(ForeignKey("hr.employment_contracts.contract_id"))
    period_id: Mapped[int] = mapped_column(ForeignKey("payroll.periods.period_id"))
    gross_amount: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2))
    total_deductions: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2))
    net_pay: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2))
    status: Mapped[str] = mapped_column(String(20), default="DRAFT")
    correction_of_payslip_id: Mapped[int | None] = mapped_column(ForeignKey("payroll.payslips.payslip_id"))


class PayslipLine(Base):
    __tablename__ = "payslip_lines"
    __table_args__ = {"schema": "payroll"}

    payslip_line_id: Mapped[int] = mapped_column(primary_key=True)
    payslip_id: Mapped[int] = mapped_column(ForeignKey("payroll.payslips.payslip_id"))
    pay_item_id: Mapped[int] = mapped_column(ForeignKey("payroll.pay_item_definitions.pay_item_id"))
    pay_item_code_snapshot: Mapped[str] = mapped_column(String(60))
    label_snapshot: Mapped[str] = mapped_column(String(200))
    amount: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2))
    phase: Mapped[str] = mapped_column(String(20))


class OvertimeRule(Base):
    __tablename__ = "overtime_rules"
    __table_args__ = {"schema": "payroll"}

    overtime_rule_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    code: Mapped[str] = mapped_column(String(30))
    multiplier: Mapped[decimal.Decimal] = mapped_column(Numeric(6, 4))
    stacking_mode: Mapped[str] = mapped_column(String(20), default="ADDITIVE")
    max_monthly_hours_policy_code: Mapped[str | None] = mapped_column(String(60))
    effective_from: Mapped[datetime.date] = mapped_column(Date)
    effective_to: Mapped[datetime.date | None] = mapped_column(Date)


class OvertimeEntry(Base):
    __tablename__ = "overtime_entries"
    __table_args__ = {"schema": "payroll"}

    overtime_entry_id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("hr.employees.employee_id"))
    period_id: Mapped[int] = mapped_column(ForeignKey("payroll.periods.period_id"))
    overtime_rule_id: Mapped[int] = mapped_column(ForeignKey("payroll.overtime_rules.overtime_rule_id"))
    hours: Mapped[decimal.Decimal] = mapped_column(Numeric(7, 2))
    status: Mapped[str] = mapped_column(String(20), default="PENDING_APPROVAL")


class Loan(Base):
    __tablename__ = "loans"
    __table_args__ = {"schema": "payroll"}

    loan_id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("hr.employees.employee_id"))
    loan_type: Mapped[str] = mapped_column(String(10))
    principal_amount: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2))
    fee_rate: Mapped[decimal.Decimal] = mapped_column(Numeric(6, 4), default=0)
    installments_count: Mapped[int] = mapped_column(SmallInteger)
    start_period_id: Mapped[int] = mapped_column(ForeignKey("payroll.periods.period_id"))
    funding_source: Mapped[str | None] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(20), default="REQUESTED")
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LoanInstallment(Base):
    __tablename__ = "loan_installments"
    __table_args__ = {"schema": "payroll"}

    loan_installment_id: Mapped[int] = mapped_column(primary_key=True)
    loan_id: Mapped[int] = mapped_column(ForeignKey("payroll.loans.loan_id"))
    installment_no: Mapped[int] = mapped_column(SmallInteger)
    due_period_id: Mapped[int] = mapped_column(ForeignKey("payroll.periods.period_id"))
    amount: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2))
    status: Mapped[str] = mapped_column(String(20), default="PENDING")


class BankPaymentBatch(Base):
    __tablename__ = "bank_payment_batches"
    __table_args__ = {"schema": "payroll"}

    batch_id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("payroll.runs.run_id"))
    bank_id: Mapped[int] = mapped_column(ForeignKey("treasury.banks.bank_id"))
    total_amount: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2))
    status: Mapped[str] = mapped_column(String(20), default="DRAFT")
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BankPaymentLine(Base):
    __tablename__ = "bank_payment_lines"
    __table_args__ = {"schema": "payroll"}

    line_id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("payroll.bank_payment_batches.batch_id"))
    payslip_id: Mapped[int] = mapped_column(ForeignKey("payroll.payslips.payslip_id"))
    employee_id: Mapped[int] = mapped_column(ForeignKey("hr.employees.employee_id"))
    bank_account_no: Mapped[str] = mapped_column(String(40))
    amount: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2))
    line_status: Mapped[str] = mapped_column(String(20), default="PENDING")


class PayrollJournalEntryLink(Base):
    __tablename__ = "journal_entry_links"
    __table_args__ = {"schema": "payroll"}

    run_id: Mapped[int] = mapped_column(ForeignKey("payroll.runs.run_id"), primary_key=True)
    journal_entry_id: Mapped[int] = mapped_column(ForeignKey("acc.journal_entries.journal_entry_id"))
