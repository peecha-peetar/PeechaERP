"""مدل‌های بودجه‌ریزی و کنترل بودجه (schema bud) — R313. معادل db/schema/223_budgeting.sql."""

from __future__ import annotations

import datetime
import decimal

from sqlalchemy import BigInteger, ForeignKey, Numeric, SmallInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from peecha.db.base import Base

_BUD = {"schema": "bud"}


class BudgetSettings(Base):
    __tablename__ = "settings"
    __table_args__ = _BUD

    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"), primary_key=True)
    policy_code: Mapped[str] = mapped_column(String(10), default="WARN")
    warn_percent: Mapped[decimal.Decimal] = mapped_column(Numeric(5, 2), default=90)
    control_level: Mapped[str] = mapped_column(String(12), default="ANNUAL")
    unbudgeted_policy: Mapped[str] = mapped_column(String(10), default="ALLOW")
    updated_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    updated_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")


class Budget(Base):
    __tablename__ = "budgets"
    __table_args__ = _BUD

    budget_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    fiscal_year_id: Mapped[int] = mapped_column(ForeignKey("acc.fiscal_years.fiscal_year_id"))
    code: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(150))
    period_type: Mapped[str] = mapped_column(String(10))
    date_from: Mapped[datetime.date]
    date_to: Mapped[datetime.date]
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    created_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")


class BudgetPeriod(Base):
    __tablename__ = "budget_periods"
    __table_args__ = _BUD

    period_id: Mapped[int] = mapped_column(primary_key=True)
    budget_id: Mapped[int] = mapped_column(ForeignKey("bud.budgets.budget_id", ondelete="CASCADE"))
    period_no: Mapped[int] = mapped_column(SmallInteger)
    date_from: Mapped[datetime.date]
    date_to: Mapped[datetime.date]
    label: Mapped[str] = mapped_column(String(40))
    is_closed: Mapped[bool] = mapped_column(default=False)
    closed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    closed_at: Mapped[datetime.datetime | None]
    close_note: Mapped[str | None] = mapped_column(Text)


class ControlKey(Base):
    __tablename__ = "control_keys"
    __table_args__ = _BUD

    key_id: Mapped[int] = mapped_column(primary_key=True)
    budget_id: Mapped[int] = mapped_column(ForeignKey("bud.budgets.budget_id", ondelete="CASCADE"))
    basis_code: Mapped[str] = mapped_column(String(10))
    account_id: Mapped[int | None] = mapped_column(ForeignKey("acc.chart_of_accounts.account_id"))
    cost_center_detail_account_id: Mapped[int | None] = mapped_column(ForeignKey("acc.detail_accounts.detail_account_id"))
    project_detail_account_id: Mapped[int | None] = mapped_column(ForeignKey("acc.detail_accounts.detail_account_id"))
    branch_id: Mapped[int | None] = mapped_column(ForeignKey("comm.branches.branch_id"))
    org_unit_id: Mapped[int | None] = mapped_column(ForeignKey("hr.organizational_units.org_unit_id"))
    category_id: Mapped[int | None] = mapped_column(ForeignKey("inv.item_categories.category_id"))
    purchase_type_id: Mapped[int | None] = mapped_column(ForeignKey("comm.purchase_types.purchase_type_id"))


class BudgetVersion(Base):
    __tablename__ = "budget_versions"
    __table_args__ = _BUD

    version_id: Mapped[int] = mapped_column(primary_key=True)
    budget_id: Mapped[int] = mapped_column(ForeignKey("bud.budgets.budget_id", ondelete="CASCADE"))
    version_no: Mapped[int] = mapped_column(SmallInteger)
    kind_code: Mapped[str] = mapped_column(String(12))
    status_code: Mapped[str] = mapped_column(String(12), default="DRAFT")
    based_on_version_id: Mapped[int | None] = mapped_column(ForeignKey("bud.budget_versions.version_id"))
    title: Mapped[str] = mapped_column(String(150))
    description: Mapped[str | None] = mapped_column(Text)
    valid_from: Mapped[datetime.date]
    valid_to: Mapped[datetime.date]
    prepared_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    created_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")
    submitted_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    submitted_at: Mapped[datetime.datetime | None]
    reviewed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    reviewed_at: Mapped[datetime.datetime | None]
    approved_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    approved_at: Mapped[datetime.datetime | None]
    published_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    published_at: Mapped[datetime.datetime | None]
    reject_reason: Mapped[str | None] = mapped_column(Text)


class BudgetLine(Base):
    __tablename__ = "budget_lines"
    __table_args__ = _BUD

    line_id: Mapped[int] = mapped_column(primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("bud.budget_versions.version_id", ondelete="CASCADE"))
    key_id: Mapped[int] = mapped_column(ForeignKey("bud.control_keys.key_id"))
    line_no: Mapped[int] = mapped_column(SmallInteger)
    proposed_amount: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2))
    approved_amount: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 2))
    previous_amount: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 2))
    policy_code: Mapped[str | None] = mapped_column(String(10))
    warn_percent: Mapped[decimal.Decimal | None] = mapped_column(Numeric(5, 2))
    responsible_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    note: Mapped[str | None] = mapped_column(Text)


class LinePeriodAmount(Base):
    __tablename__ = "line_period_amounts"
    __table_args__ = _BUD

    line_id: Mapped[int] = mapped_column(ForeignKey("bud.budget_lines.line_id", ondelete="CASCADE"), primary_key=True)
    period_no: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    amount: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2))


class VersionDecision(Base):
    __tablename__ = "version_decisions"
    __table_args__ = _BUD

    decision_id: Mapped[int] = mapped_column(primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("bud.budget_versions.version_id", ondelete="CASCADE"))
    action_code: Mapped[str] = mapped_column(String(12))
    from_status: Mapped[str | None] = mapped_column(String(12))
    to_status: Mapped[str] = mapped_column(String(12))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    decided_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")
    comment: Mapped[str | None] = mapped_column(Text)


class ConsumptionEntry(Base):
    __tablename__ = "consumption_entries"
    __table_args__ = _BUD

    entry_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    budget_id: Mapped[int] = mapped_column(ForeignKey("bud.budgets.budget_id"))
    key_id: Mapped[int] = mapped_column(ForeignKey("bud.control_keys.key_id"))
    kind_code: Mapped[str] = mapped_column(String(8))
    source_type: Mapped[str] = mapped_column(String(20))
    source_document_id: Mapped[int] = mapped_column(BigInteger)
    source_line_id: Mapped[int] = mapped_column(BigInteger)
    source_no: Mapped[int | None]
    period_date: Mapped[datetime.date]
    amount: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2))
    amount_fc: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 2))
    currency_id: Mapped[int | None] = mapped_column(ForeignKey("core.currencies.currency_id"))
    exchange_rate: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 6))
    event_code: Mapped[str] = mapped_column(String(16))
    note: Mapped[str | None] = mapped_column(Text)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    created_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")


class BudgetException(Base):
    __tablename__ = "exceptions"
    __table_args__ = _BUD

    exception_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    budget_id: Mapped[int | None] = mapped_column(ForeignKey("bud.budgets.budget_id"))
    key_id: Mapped[int | None] = mapped_column(ForeignKey("bud.control_keys.key_id"))
    source_type: Mapped[str] = mapped_column(String(20))
    source_document_id: Mapped[int] = mapped_column(BigInteger)
    source_no: Mapped[int | None]
    level_code: Mapped[str] = mapped_column(String(10))
    excess_amount: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2))
    reason: Mapped[str | None] = mapped_column(Text)
    status_code: Mapped[str] = mapped_column(String(10), default="PENDING")
    requested_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    requested_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")
    decided_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    decided_at: Mapped[datetime.datetime | None]
    decision_note: Mapped[str | None] = mapped_column(Text)
    used_at: Mapped[datetime.datetime | None]


class ControlEvent(Base):
    __tablename__ = "control_events"
    __table_args__ = _BUD

    event_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    budget_id: Mapped[int | None] = mapped_column(ForeignKey("bud.budgets.budget_id"))
    key_id: Mapped[int | None] = mapped_column(ForeignKey("bud.control_keys.key_id"))
    source_type: Mapped[str] = mapped_column(String(20))
    source_document_id: Mapped[int] = mapped_column(BigInteger)
    source_no: Mapped[int | None]
    stage_code: Mapped[str] = mapped_column(String(16))
    outcome_code: Mapped[str] = mapped_column(String(16))
    policy_code: Mapped[str | None] = mapped_column(String(10))
    budget_amount: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 2))
    consumed_before: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 2))
    delta: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 2))
    available_after: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 2))
    exception_id: Mapped[int | None] = mapped_column(ForeignKey("bud.exceptions.exception_id"))
    message: Mapped[str | None] = mapped_column(Text)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    created_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")


class CommitmentClosure(Base):
    __tablename__ = "commitment_closures"
    __table_args__ = _BUD

    closure_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    document_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("comm.commercial_documents.document_id"))
    line_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("comm.commercial_document_lines.line_id"))
    closed_qty_base: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 6))
    reason: Mapped[str] = mapped_column(Text)
    closed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    closed_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")
    reopened_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    reopened_at: Mapped[datetime.datetime | None]
    reopen_note: Mapped[str | None] = mapped_column(Text)
