"""مدل‌های ماژول حسابداری (دفتر کل).

معادل db/schema/003_accounting_core.sql
"""

from __future__ import annotations

import datetime
import decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Computed,
    Date,
    ForeignKey,
    Numeric,
    SmallInteger,
    String,
    UniqueConstraint,
)
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


class DetailDimensionType(Base):
    __tablename__ = "detail_dimension_types"
    __table_args__ = (UniqueConstraint("company_id", "code"), {"schema": "acc"})

    dimension_type_id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    code: Mapped[str] = mapped_column(String(30))  # CUSTOMER, VENDOR, COST_CENTER, PROJECT, ...
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class DetailAccount(Base):
    __tablename__ = "detail_accounts"
    __table_args__ = (UniqueConstraint("company_id", "dimension_type_id", "code"), {"schema": "acc"})

    detail_account_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    dimension_type_id: Mapped[int] = mapped_column(ForeignKey("acc.detail_dimension_types.dimension_type_id"))
    code: Mapped[str] = mapped_column(String(30))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class AccountDetailDimension(Base):
    __tablename__ = "account_detail_dimensions"
    __table_args__ = {"schema": "acc"}

    account_id: Mapped[int] = mapped_column(ForeignKey("acc.chart_of_accounts.account_id"), primary_key=True)
    dimension_type_id: Mapped[int] = mapped_column(
        ForeignKey("acc.detail_dimension_types.dimension_type_id"), primary_key=True
    )
    is_required: Mapped[bool] = mapped_column(Boolean, default=True)


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
    entry_type_id: Mapped[int] = mapped_column(ForeignKey("acc.journal_entry_types.entry_type_id"))
    status_id: Mapped[int] = mapped_column(ForeignKey("acc.journal_entry_statuses.status_id"))
    description: Mapped[str | None]
    is_system_generated: Mapped[bool] = mapped_column(Boolean, default=False)
    reversed_entry_id: Mapped[int | None] = mapped_column(ForeignKey("acc.journal_entries.journal_entry_id"))
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("sec.users.user_id"))
    created_at: Mapped[datetime.datetime]
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
