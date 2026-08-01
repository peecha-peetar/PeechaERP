"""مدل‌های ماژولِ خزانه‌داری (نگاشتِ حساب‌ها، دسته‌چک، چک‌هایِ دریافتی/پرداختی).

معادل db/schema/024_treasury.sql
"""

from __future__ import annotations

import datetime
import decimal

from sqlalchemy import ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from peecha.db.base import Base


class TreasuryAccountMapping(Base):
    __tablename__ = "account_mappings"
    __table_args__ = {"schema": "treasury"}

    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"), primary_key=True)
    mapping_key: Mapped[str] = mapped_column(String(30), primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("acc.chart_of_accounts.account_id"))


class Checkbook(Base):
    __tablename__ = "checkbooks"
    __table_args__ = {"schema": "treasury"}

    checkbook_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    bank_account_detail_id: Mapped[int] = mapped_column(ForeignKey("acc.detail_accounts.detail_account_id"))
    start_no: Mapped[int]
    end_no: Mapped[int]
    next_no: Mapped[int]
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")


class CheckStatus(Base):
    __tablename__ = "check_statuses"
    __table_args__ = {"schema": "treasury"}

    status_id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20))
    applies_to: Mapped[str] = mapped_column(String(10))  # RECEIVED | ISSUED


class ReceivedCheck(Base):
    __tablename__ = "received_checks"
    __table_args__ = {"schema": "treasury"}

    received_check_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    check_no: Mapped[str] = mapped_column(String(30))
    drawee_bank_name: Mapped[str | None] = mapped_column(String(150))
    drawer_name: Mapped[str | None] = mapped_column(String(150))
    amount: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2))
    due_date: Mapped[datetime.date]
    received_date: Mapped[datetime.date]
    counterparty_detail_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("acc.detail_accounts.detail_account_id")
    )
    status_id: Mapped[int] = mapped_column(ForeignKey("treasury.check_statuses.status_id"))
    source_journal_entry_id: Mapped[int] = mapped_column(ForeignKey("acc.journal_entries.journal_entry_id"))
    endorsed_to_issued_check_id: Mapped[int | None] = mapped_column(
        ForeignKey("treasury.issued_checks.issued_check_id")
    )
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("sec.users.user_id"))
    created_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")


class IssuedCheck(Base):
    __tablename__ = "issued_checks"
    __table_args__ = {"schema": "treasury"}

    issued_check_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    checkbook_id: Mapped[int | None] = mapped_column(ForeignKey("treasury.checkbooks.checkbook_id"))
    check_no: Mapped[str] = mapped_column(String(30))
    bank_account_detail_id: Mapped[int] = mapped_column(ForeignKey("acc.detail_accounts.detail_account_id"))
    payee_name: Mapped[str | None] = mapped_column(String(150))
    amount: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2))
    due_date: Mapped[datetime.date]
    issue_date: Mapped[datetime.date]
    counterparty_detail_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("acc.detail_accounts.detail_account_id")
    )
    status_id: Mapped[int] = mapped_column(ForeignKey("treasury.check_statuses.status_id"))
    source_journal_entry_id: Mapped[int] = mapped_column(ForeignKey("acc.journal_entries.journal_entry_id"))
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("sec.users.user_id"))
    created_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")
