"""مدل‌های افتتاحیه و انتقال اطلاعات (schema opn) — R314. معادل db/schema/224_opening_balances.sql."""

from __future__ import annotations

import datetime
import decimal

from sqlalchemy import BigInteger, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from peecha.db.base import Base

_OPN = {"schema": "opn"}


class OpeningSettings(Base):
    __tablename__ = "settings"
    __table_args__ = _OPN

    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"), primary_key=True)
    difference_policy: Mapped[str] = mapped_column(String(10), default="BLOCK")
    difference_account_id: Mapped[int | None] = mapped_column(ForeignKey("acc.chart_of_accounts.account_id"))
    updated_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    updated_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")


class OpeningRun(Base):
    __tablename__ = "runs"
    __table_args__ = _OPN

    run_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    fiscal_year_id: Mapped[int] = mapped_column(ForeignKey("acc.fiscal_years.fiscal_year_id"))
    code: Mapped[str] = mapped_column(String(30))
    title: Mapped[str] = mapped_column(String(200))
    kind_code: Mapped[str] = mapped_column(String(12), default="ORIGINAL")
    corrects_run_id: Mapped[int | None] = mapped_column(ForeignKey("opn.runs.run_id"))
    balance_date: Mapped[datetime.date]
    go_live_date: Mapped[datetime.date]
    currency_id: Mapped[int] = mapped_column(ForeignKey("core.currencies.currency_id"))
    status_code: Mapped[str] = mapped_column(String(12), default="DRAFT")
    notes: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    created_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")
    posted_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    posted_at: Mapped[datetime.datetime | None]
    locked_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    locked_at: Mapped[datetime.datetime | None]
    cancel_reason: Mapped[str | None] = mapped_column(Text)


class RunModule(Base):
    __tablename__ = "run_modules"
    __table_args__ = _OPN

    run_id: Mapped[int] = mapped_column(ForeignKey("opn.runs.run_id", ondelete="CASCADE"), primary_key=True)
    module_code: Mapped[str] = mapped_column(String(20), primary_key=True)
    status_code: Mapped[str] = mapped_column(String(12), default="NOT_STARTED")
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    approver_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    submitted_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    submitted_at: Mapped[datetime.datetime | None]
    approved_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    approved_at: Mapped[datetime.datetime | None]
    posted_at: Mapped[datetime.datetime | None]
    reject_reason: Mapped[str | None] = mapped_column(Text)


class ImportBatch(Base):
    __tablename__ = "import_batches"
    __table_args__ = _OPN

    batch_id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("opn.runs.run_id", ondelete="CASCADE"))
    module_code: Mapped[str] = mapped_column(String(20))
    version_no: Mapped[int]
    source_code: Mapped[str] = mapped_column(String(8), default="FILE")
    file_name: Mapped[str | None] = mapped_column(String(255))
    file_hash: Mapped[str | None] = mapped_column(String(64))
    row_count: Mapped[int] = mapped_column(default=0)
    valid_count: Mapped[int] = mapped_column(default=0)
    invalid_count: Mapped[int] = mapped_column(default=0)
    posted_skipped: Mapped[int] = mapped_column(default=0)
    uploaded_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    uploaded_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")


class StagedRow(Base):
    __tablename__ = "staged_rows"
    __table_args__ = _OPN

    row_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("opn.runs.run_id", ondelete="CASCADE"))
    module_code: Mapped[str] = mapped_column(String(20))
    row_key: Mapped[str] = mapped_column(String(300))
    batch_id: Mapped[int | None] = mapped_column(ForeignKey("opn.import_batches.batch_id"))
    source_row_no: Mapped[int | None]
    payload: Mapped[dict] = mapped_column(JSONB)
    resolved: Mapped[dict | None] = mapped_column(JSONB)
    status_code: Mapped[str] = mapped_column(String(10), default="INVALID")
    errors: Mapped[list | None] = mapped_column(JSONB)
    warnings: Mapped[list | None] = mapped_column(JSONB)
    amount: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=0)
    target_type: Mapped[str | None] = mapped_column(String(30))
    target_id: Mapped[int | None] = mapped_column(BigInteger)
    journal_entry_id: Mapped[int | None] = mapped_column(ForeignKey("acc.journal_entries.journal_entry_id"))
    posted_at: Mapped[datetime.datetime | None]
    updated_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    updated_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")


class Posting(Base):
    __tablename__ = "postings"
    __table_args__ = _OPN

    posting_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("opn.runs.run_id", ondelete="CASCADE"))
    module_code: Mapped[str] = mapped_column(String(20))
    step_key: Mapped[str] = mapped_column(String(200))
    status_code: Mapped[str] = mapped_column(String(10), default="PENDING")
    target_type: Mapped[str | None] = mapped_column(String(30))
    target_id: Mapped[int | None] = mapped_column(BigInteger)
    journal_entry_id: Mapped[int | None] = mapped_column(ForeignKey("acc.journal_entries.journal_entry_id"))
    reversal_journal_entry_id: Mapped[int | None] = mapped_column(ForeignKey("acc.journal_entries.journal_entry_id"))
    row_count: Mapped[int] = mapped_column(default=0)
    amount: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=0)
    message: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(default=0)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    started_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")
    finished_at: Mapped[datetime.datetime | None]


class OpeningEvent(Base):
    __tablename__ = "events"
    __table_args__ = _OPN

    event_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("opn.runs.run_id", ondelete="CASCADE"))
    module_code: Mapped[str | None] = mapped_column(String(20))
    event_code: Mapped[str] = mapped_column(String(20))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    created_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")
    comment: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict | None] = mapped_column(JSONB)
