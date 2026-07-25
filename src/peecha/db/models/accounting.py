"""مدل‌های ماژول حسابداری (دفتر کل).

معادل db/schema/003_accounting_core.sql
"""

from __future__ import annotations

import datetime
import decimal

from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    Date,
    ForeignKey,
    Numeric,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from peecha.db.base import Base


class FiscalYear(Base):
    __tablename__ = "fiscal_years"
    __table_args__ = (
        UniqueConstraint("company_id", "code"),
        CheckConstraint("end_date > start_date", name="ck_fiscal_years_dates"),
        {"schema": "acc"},
    )

    fiscal_year_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    code: Mapped[str] = mapped_column(String(20))
    start_date: Mapped[datetime.date] = mapped_column(Date)
    end_date: Mapped[datetime.date] = mapped_column(Date)
    is_closed: Mapped[bool] = mapped_column(Boolean, default=False)


class FiscalPeriod(Base):
    __tablename__ = "fiscal_periods"
    __table_args__ = (
        UniqueConstraint("fiscal_year_id", "period_no"),
        CheckConstraint("end_date > start_date", name="ck_fiscal_periods_dates"),
        {"schema": "acc"},
    )

    fiscal_period_id: Mapped[int] = mapped_column(primary_key=True)
    fiscal_year_id: Mapped[int] = mapped_column(ForeignKey("acc.fiscal_years.fiscal_year_id"))
    period_no: Mapped[int] = mapped_column(SmallInteger)
    start_date: Mapped[datetime.date] = mapped_column(Date)
    end_date: Mapped[datetime.date] = mapped_column(Date)
    is_closed: Mapped[bool] = mapped_column(Boolean, default=False)


class AccountNature(Base):
    __tablename__ = "account_natures"
    __table_args__ = {"schema": "acc"}

    nature_id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)


class AccountCategory(Base):
    __tablename__ = "account_categories"
    __table_args__ = {"schema": "acc"}

    category_id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)


class AccountType(Base):
    __tablename__ = "account_types"
    __table_args__ = {"schema": "acc"}

    account_type_id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)  # PERMANENT | TEMPORARY


class CashFlowSection(Base):
    """طبقه‌بندیِ حساب از نقطه‌نظرِ صورتِ گردشِ وجوهِ نقد — عملیاتی/
    سرمایه‌گذاری/تامینِ مالی؛ برخلافِ نوع/دسته/ماهیت، اختیاری است (فقط
    حساب‌هایِ ترازنامه‌ایِ غیرِنقدی به آن نیاز دارند)."""

    __tablename__ = "cash_flow_sections"
    __table_args__ = {"schema": "acc"}

    cash_flow_section_id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)  # OPERATING | INVESTING | FINANCING


class LiquidityClass(Base):
    """طبقه‌بندیِ حساب از نقطه‌نظرِ نقدینگی — جاری/غیرِجاری/موجودی؛
    اختیاری، فقط برایِ حساب‌هایِ دارایی/بدهی که در نسبتِ جاری/آنی
    (گزارشِ نسبت‌هایِ مالی) باید دیده شوند."""

    __tablename__ = "liquidity_classes"
    __table_args__ = {"schema": "acc"}

    liquidity_class_id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)  # CURRENT | CURRENT_INVENTORY | NON_CURRENT


class ChartOfAccount(Base):
    __tablename__ = "chart_of_accounts"
    __table_args__ = (
        UniqueConstraint("company_id", "full_code"),
        {"schema": "acc"},
    )

    account_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    parent_account_id: Mapped[int | None] = mapped_column(ForeignKey("acc.chart_of_accounts.account_id"))
    segment_code: Mapped[str] = mapped_column(String(20))
    full_code: Mapped[str] = mapped_column(String(100))
    account_level: Mapped[int] = mapped_column(SmallInteger)  # 1=گروه 2=کل 3=معین
    nature_id: Mapped[int] = mapped_column(ForeignKey("acc.account_natures.nature_id"))
    category_id: Mapped[int] = mapped_column(ForeignKey("acc.account_categories.category_id"))
    account_type_id: Mapped[int] = mapped_column(ForeignKey("acc.account_types.account_type_id"))
    cash_flow_section_id: Mapped[int | None] = mapped_column(
        ForeignKey("acc.cash_flow_sections.cash_flow_section_id")
    )
    liquidity_class_id: Mapped[int | None] = mapped_column(ForeignKey("acc.liquidity_classes.liquidity_class_id"))
    is_postable: Mapped[bool] = mapped_column(Boolean, default=False)
    currency_id: Mapped[int | None] = mapped_column(ForeignKey("core.currencies.currency_id"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    parent: Mapped[ChartOfAccount | None] = relationship(remote_side="ChartOfAccount.account_id")


class CompanyAccountingSettings(Base):
    __tablename__ = "company_accounting_settings"
    __table_args__ = {"schema": "acc"}

    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"), primary_key=True)
    profit_and_loss_account_id: Mapped[int | None] = mapped_column(ForeignKey("acc.chart_of_accounts.account_id"))
    retained_earnings_account_id: Mapped[int | None] = mapped_column(ForeignKey("acc.chart_of_accounts.account_id"))


class ChartOfAccountLevelConfig(Base):
    """تنظیماتِ رقم/بازه‌یِ هر سطحِ کدینگِ حساب‌ها — اختیاری؛ سطحی که ردیفی
    این‌جا نداشته باشد بدونِ محدودیت می‌ماند. بعدِ اولینِ سندِ شرکت، سرویس
    اجازه‌ی تغییرِ این تنظیمات را نمی‌دهد (چکِ تراکنشی، نه اینجا)."""

    __tablename__ = "chart_of_account_level_config"
    __table_args__ = {"schema": "acc"}

    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"), primary_key=True)
    account_level: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    code_length: Mapped[int | None] = mapped_column(SmallInteger)
    range_from: Mapped[int | None] = mapped_column(BigInteger)
    range_to: Mapped[int | None] = mapped_column(BigInteger)


class DetailLevelDigitConfig(Base):
    """تعدادِ رقمِ سراسریِ هر سطحِ تفصیلی (۱ تا ۴) — یکسان برایِ همه‌ی
    گروه‌ها (کالا/بانک/مشتری/...)؛ فقط بازه‌ی از-تا مخصوصِ هر گروه می‌ماند
    (acc.detail_group_levels). اختیاری؛ سطحی که ردیفی این‌جا نداشته باشد
    بدونِ محدودیتِ طول می‌ماند. هم‌الگو با acc.chart_of_account_level_config."""

    __tablename__ = "detail_level_digit_config"
    __table_args__ = {"schema": "acc"}

    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"), primary_key=True)
    level_no: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    code_length: Mapped[int | None] = mapped_column(SmallInteger)


class DetailDimensionType(Base):
    __tablename__ = "detail_dimension_types"
    __table_args__ = (UniqueConstraint("company_id", "code"), {"schema": "acc"})

    dimension_type_id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    code: Mapped[str] = mapped_column(String(30))  # CUSTOMER, VENDOR, COST_CENTER, PROJECT, ...
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # سقفِ تعدادِ سطحِ سلسله‌مراتبِ حساب‌هایِ تفصیلیِ این گروه (۱ تا ۴).
    max_level_no: Mapped[int] = mapped_column(SmallInteger, default=4)
    # رنگِ اختصاصیِ این گروه (مثلاً "#15A672") — طبقِ درخواستِ صریح، در فهرستِ
    # تفصیلی‌ها و کمبویِ تفصیلیِ سندِ حسابداری استفاده می‌شود.
    color: Mapped[str | None] = mapped_column(String(7))


class DetailAccount(Base):
    __tablename__ = "detail_accounts"
    __table_args__ = (UniqueConstraint("company_id", "dimension_type_id", "code"), {"schema": "acc"})

    detail_account_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    dimension_type_id: Mapped[int] = mapped_column(ForeignKey("acc.detail_dimension_types.dimension_type_id"))
    code: Mapped[str] = mapped_column(String(30))
    name: Mapped[str | None] = mapped_column(String(200))
    person_group_id: Mapped[int | None] = mapped_column(ForeignKey("acc.person_groups.person_group_id"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    parent_detail_account_id: Mapped[int | None] = mapped_column(ForeignKey("acc.detail_accounts.detail_account_id"))
    level_no: Mapped[int] = mapped_column(SmallInteger, default=1)
    extra_fields: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    parent: Mapped[DetailAccount | None] = relationship(remote_side="DetailAccount.detail_account_id")


class DetailGroupLevel(Base):
    """طولِ کدِ هر سطح (۱ تا ۴) به تفکیکِ گروهِ تفصیلی — اختیاری؛ گروهی که
    ردیفی این‌جا نداشته باشد تخت/بدونِ محدودیتِ طول می‌ماند (سازگار با
    گروه‌های موجود مثلِ مشتری/مرکز هزینه که پیش از این ویژگی ساخته شده‌اند)."""

    __tablename__ = "detail_group_levels"
    __table_args__ = {"schema": "acc"}

    dimension_type_id: Mapped[int] = mapped_column(
        ForeignKey("acc.detail_dimension_types.dimension_type_id"), primary_key=True
    )
    # ۰ = بدونِ محدودیت به گروهِ خاصِ اشخاص؛ فقط برایِ نوع‌بُعدِ PERSON مقداری
    # غیرِصفر می‌گیرد تا مشتری/تامین‌کننده/پرسنل مستقل از هم پیکربندی شوند.
    person_group_id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, default=0)
    level_no: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    range_from: Mapped[int | None] = mapped_column(BigInteger)
    range_to: Mapped[int | None] = mapped_column(BigInteger)


class DetailGroupField(Base):
    """تعریفِ فیلدِ اختصاصیِ یک گروهِ تفصیلی — طبقِ درخواستِ صریح، کاربر
    باید بتواند برایِ گروهِ تازه‌تعریف‌شده (مثلاً «بانک») ویژگی‌هایی شبیهِ
    مشتری تعریف کند؛ مقدارِ هر فیلد در DetailAccount.extra_fields (JSONB،
    کلید=field_key) ذخیره می‌شود."""

    __tablename__ = "detail_group_fields"
    __table_args__ = (
        UniqueConstraint("dimension_type_id", "person_group_id", "field_key"),
        {"schema": "acc"},
    )

    detail_group_field_id: Mapped[int] = mapped_column(primary_key=True)
    dimension_type_id: Mapped[int] = mapped_column(ForeignKey("acc.detail_dimension_types.dimension_type_id"))
    person_group_id: Mapped[int] = mapped_column(SmallInteger, default=0)
    field_key: Mapped[str] = mapped_column(String(50))
    label: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(20))  # text | decimal | date | boolean
    is_required: Mapped[bool] = mapped_column(Boolean, default=False)
    sort_order: Mapped[int] = mapped_column(SmallInteger, default=0)


class AccountDetailDimension(Base):
    __tablename__ = "account_detail_dimensions"
    __table_args__ = {"schema": "acc"}

    account_id: Mapped[int] = mapped_column(ForeignKey("acc.chart_of_accounts.account_id"), primary_key=True)
    dimension_type_id: Mapped[int] = mapped_column(
        ForeignKey("acc.detail_dimension_types.dimension_type_id"), primary_key=True
    )
    is_required: Mapped[bool] = mapped_column(Boolean, default=True)


class PersonGroup(Base):
    """گروهِ تفصیلیِ اشخاص (مشتری/تامین‌کننده/پرسنل) — طبقه‌بندیِ هر شخص،
    و مبنایِ محدودکردنِ یک معین به گروهِ خاصی (acc.account_person_groups)."""

    __tablename__ = "person_groups"
    __table_args__ = (UniqueConstraint("company_id", "code"), {"schema": "acc"})

    person_group_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    # سقفِ تعدادِ سطحِ سلسله‌مراتبِ اشخاصِ این گروه (۱ تا ۴)؛ پیش‌فرض ۱ یعنی
    # تخت (رفتارِ فعلی)، مدیر می‌تواند بالا ببرد (مثلاً مشتری=۲).
    max_level_no: Mapped[int] = mapped_column(SmallInteger, default=1)
    code: Mapped[str] = mapped_column(String(20))  # CUSTOMER, SUPPLIER, PERSONNEL
    name: Mapped[str] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # رنگِ اختصاصیِ این زیرگروه — هم‌الگو با DetailDimensionType.color.
    color: Mapped[str | None] = mapped_column(String(7))


class AccountPersonGroup(Base):
    """کدام معین‌ها به کدام گروه(ها)ی تفصیلی محدودند."""

    __tablename__ = "account_person_groups"
    __table_args__ = {"schema": "acc"}

    account_id: Mapped[int] = mapped_column(ForeignKey("acc.chart_of_accounts.account_id"), primary_key=True)
    person_group_id: Mapped[int] = mapped_column(ForeignKey("acc.person_groups.person_group_id"), primary_key=True)


class CustomerDetail(Base):
    __tablename__ = "customer_details"
    __table_args__ = {"schema": "acc"}

    detail_account_id: Mapped[int] = mapped_column(ForeignKey("acc.detail_accounts.detail_account_id"), primary_key=True)
    economic_code: Mapped[str | None] = mapped_column(String(30))
    national_id: Mapped[str | None] = mapped_column(String(20))
    phone: Mapped[str | None] = mapped_column(String(30))
    mobile: Mapped[str | None] = mapped_column(String(30))
    address: Mapped[str | None] = mapped_column(String(400))
    credit_limit: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 2))
    notes: Mapped[str | None] = mapped_column(String(500))


class SupplierDetail(Base):
    __tablename__ = "supplier_details"
    __table_args__ = {"schema": "acc"}

    detail_account_id: Mapped[int] = mapped_column(ForeignKey("acc.detail_accounts.detail_account_id"), primary_key=True)
    economic_code: Mapped[str | None] = mapped_column(String(30))
    national_id: Mapped[str | None] = mapped_column(String(20))
    phone: Mapped[str | None] = mapped_column(String(30))
    mobile: Mapped[str | None] = mapped_column(String(30))
    address: Mapped[str | None] = mapped_column(String(400))
    bank_account_no: Mapped[str | None] = mapped_column(String(40))
    notes: Mapped[str | None] = mapped_column(String(500))


class PersonnelDetail(Base):
    __tablename__ = "personnel_details"
    __table_args__ = {"schema": "acc"}

    detail_account_id: Mapped[int] = mapped_column(ForeignKey("acc.detail_accounts.detail_account_id"), primary_key=True)
    national_id: Mapped[str | None] = mapped_column(String(20))
    personnel_no: Mapped[str | None] = mapped_column(String(30))
    position_title: Mapped[str | None] = mapped_column(String(100))
    phone: Mapped[str | None] = mapped_column(String(30))
    mobile: Mapped[str | None] = mapped_column(String(30))
    hire_date: Mapped[datetime.date | None] = mapped_column(Date)
    bank_account_no: Mapped[str | None] = mapped_column(String(40))
    notes: Mapped[str | None] = mapped_column(String(500))


class JournalEntryType(Base):
    __tablename__ = "journal_entry_types"
    __table_args__ = {"schema": "acc"}

    entry_type_id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)  # NORMAL, OPENING, CLOSING, ADJUSTING


class JournalEntryStatus(Base):
    __tablename__ = "journal_entry_statuses"
    __table_args__ = {"schema": "acc"}

    status_id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)  # TEMPORARY, PERMANENT, REVERSED, CANCELLED


class JournalEntry(Base):
    __tablename__ = "journal_entries"
    __table_args__ = (UniqueConstraint("company_id", "fiscal_year_id", "temporary_no"), {"schema": "acc"})

    journal_entry_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    fiscal_year_id: Mapped[int] = mapped_column(ForeignKey("acc.fiscal_years.fiscal_year_id"))
    temporary_no: Mapped[int]
    permanent_no: Mapped[int | None]  # فقط سرویس تایید (کارتابل) این را پر می‌کند؛ پس از آن غیرقابل‌تغییر (تریگر DB)
    document_date: Mapped[datetime.date] = mapped_column(Date)
    alternative_number: Mapped[str | None] = mapped_column(String(50))  # شماره عطف/بایگانیِ دستی
    source_system: Mapped[str] = mapped_column(String(20), default="MANUAL")
    entry_type_id: Mapped[int] = mapped_column(ForeignKey("acc.journal_entry_types.entry_type_id"))
    status_id: Mapped[int] = mapped_column(ForeignKey("acc.journal_entry_statuses.status_id"))
    description: Mapped[str | None]
    is_system_generated: Mapped[bool] = mapped_column(Boolean, default=False)
    reversed_entry_id: Mapped[int | None] = mapped_column(ForeignKey("acc.journal_entries.journal_entry_id"))
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("sec.users.user_id"))
    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())
    posted_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    posted_at: Mapped[datetime.datetime | None]

    lines: Mapped[list["JournalEntryLine"]] = relationship(back_populates="journal_entry")


class JournalEntryLine(Base):
    __tablename__ = "journal_entry_lines"
    __table_args__ = (
        UniqueConstraint("journal_entry_id", "line_no"),
        CheckConstraint(
            "(debit_amount_fc > 0 AND credit_amount_fc = 0) OR (credit_amount_fc > 0 AND debit_amount_fc = 0)",
            name="ck_journal_entry_lines_one_sided",
        ),
        {"schema": "acc"},
    )

    line_id: Mapped[int] = mapped_column(primary_key=True)
    journal_entry_id: Mapped[int] = mapped_column(ForeignKey("acc.journal_entries.journal_entry_id"))
    line_no: Mapped[int] = mapped_column(SmallInteger)
    account_id: Mapped[int] = mapped_column(ForeignKey("acc.chart_of_accounts.account_id"))
    description: Mapped[str | None]
    tax_code: Mapped[str | None] = mapped_column(String(30))
    currency_id: Mapped[int] = mapped_column(ForeignKey("core.currencies.currency_id"))
    exchange_rate: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 6), default=1)
    debit_amount_fc: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=0)
    credit_amount_fc: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=0)
    # ستون‌های GENERATED ALWAYS AS ... STORED در دیتابیس؛ Computed() به SQLAlchemy
    # می‌گوید این ستون‌ها را در INSERT/UPDATE نفرستد، فقط بعد از commit بخواند.
    debit_amount_base: Mapped[decimal.Decimal] = mapped_column(
        Numeric(18, 2), Computed("round(debit_amount_fc * exchange_rate, 2)")
    )
    credit_amount_base: Mapped[decimal.Decimal] = mapped_column(
        Numeric(18, 2), Computed("round(credit_amount_fc * exchange_rate, 2)")
    )

    journal_entry: Mapped[JournalEntry] = relationship(back_populates="lines")


class JournalEntryLineDetail(Base):
    __tablename__ = "journal_entry_line_details"
    __table_args__ = {"schema": "acc"}

    line_id: Mapped[int] = mapped_column(ForeignKey("acc.journal_entry_lines.line_id"), primary_key=True)
    dimension_type_id: Mapped[int] = mapped_column(
        ForeignKey("acc.detail_dimension_types.dimension_type_id"), primary_key=True
    )
    detail_account_id: Mapped[int] = mapped_column(ForeignKey("acc.detail_accounts.detail_account_id"))


class StatementTemplate(Base):
    """یک الگویِ گزارشِ سفارشی (طراحِ گزارش، فازِ ۲) — مجموعه‌ای از ردیف‌هایِ
    ترتیب‌دار که هرکدام از جمعِ چند حساب یا چند ردیفِ دیگر ساخته می‌شود."""

    __tablename__ = "statement_templates"
    __table_args__ = {"schema": "acc"}

    template_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    name: Mapped[str] = mapped_column(String(200))
    statement_type: Mapped[str] = mapped_column(String(20))  # INCOME_STATEMENT|BALANCE_SHEET|CASH_FLOW|CUSTOM
    display_order: Mapped[int] = mapped_column(default=0)


class StatementRow(Base):
    __tablename__ = "statement_rows"
    __table_args__ = {"schema": "acc"}

    row_id: Mapped[int] = mapped_column(primary_key=True)
    template_id: Mapped[int] = mapped_column(ForeignKey("acc.statement_templates.template_id"))
    row_order: Mapped[int]
    label: Mapped[str] = mapped_column(String(300))
    row_type: Mapped[str] = mapped_column(String(20))  # HEADER|ACCOUNTS|FORMULA
    indent_level: Mapped[int] = mapped_column(SmallInteger, default=0)
    is_bold: Mapped[bool] = mapped_column(Boolean, default=False)


class StatementRowAccount(Base):
    __tablename__ = "statement_row_accounts"
    __table_args__ = {"schema": "acc"}

    row_id: Mapped[int] = mapped_column(ForeignKey("acc.statement_rows.row_id"), primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("acc.chart_of_accounts.account_id"), primary_key=True)
    sign: Mapped[int] = mapped_column(SmallInteger)


class StatementRowRef(Base):
    __tablename__ = "statement_row_refs"
    __table_args__ = {"schema": "acc"}

    row_id: Mapped[int] = mapped_column(ForeignKey("acc.statement_rows.row_id"), primary_key=True)
    ref_row_id: Mapped[int] = mapped_column(ForeignKey("acc.statement_rows.row_id"), primary_key=True)
    sign: Mapped[int] = mapped_column(SmallInteger)
