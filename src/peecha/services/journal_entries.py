"""سرویس صدور سند حسابداری (دفتر روزنامه).

هر سند در این مرحله با شماره‌ی موقت (temporary_no) و وضعیت TEMPORARY ثبت
می‌شود؛ تخصیص شماره‌ی دائم (permanent_no) طبق طراحی دیتابیس فقط از طریق
تاییدِ کارتابل انجام می‌شود (هنوز ساخته نشده) و بعد از آن دیگر قابل تغییر
نیست (تریگر tr_journal_entries_prevent_permanent_no_change).

سال مالی هم به‌صورت خودکار از روی fiscal_year_start_month/day شرکت و
تاریخِ سند محاسبه و در صورت نبود ساخته می‌شود — چون هنوز صفحه‌ی مدیریت سال
مالی وجود ندارد و بدون آن هیچ سندی قابل ثبت نیست.
"""

from __future__ import annotations

import datetime
import decimal
from dataclasses import dataclass

import jdatetime
from sqlalchemy import func, select

from peecha.db.base import new_session
from peecha.db.models.accounting import (
    ChartOfAccount,
    FiscalYear,
    JournalEntry,
    JournalEntryLine,
    JournalEntryStatus,
    JournalEntryType,
)
from peecha.db.models.core import Company


@dataclass
class LineInput:
    account_id: int
    description: str
    debit: decimal.Decimal
    credit: decimal.Decimal


@dataclass
class JournalEntryResult:
    journal_entry_id: int
    temporary_no: int


@dataclass
class JournalEntrySummary:
    journal_entry_id: int
    temporary_no: int
    document_date: datetime.date
    description: str
    status_code: str
    total_amount: decimal.Decimal


def _validate_lines(lines: list[LineInput]) -> tuple[list[LineInput], decimal.Decimal]:
    real_lines = [ln for ln in lines if ln.debit != 0 or ln.credit != 0]
    if len(real_lines) < 2:
        raise ValueError("سند حسابداری باید حداقل دو ردیف (یک بدهکار و یک بستانکار) داشته باشد.")
    for ln in real_lines:
        if (ln.debit != 0) == (ln.credit != 0):
            raise ValueError("هر ردیف باید یا بدهکار یا بستانکار باشد، نه هر دو یا هیچ‌کدام.")
    total_debit = sum((ln.debit for ln in real_lines), decimal.Decimal(0))
    total_credit = sum((ln.credit for ln in real_lines), decimal.Decimal(0))
    if total_debit != total_credit:
        raise ValueError(f"سند متعادل نیست: جمع بدهکار {total_debit} با جمع بستانکار {total_credit} برابر نیست.")
    return real_lines, total_debit


def _validate_accounts(session, company_id: int, real_lines: list[LineInput]) -> None:
    account_ids = [ln.account_id for ln in real_lines]
    accounts = session.scalars(select(ChartOfAccount).where(ChartOfAccount.account_id.in_(account_ids))).all()
    accounts_by_id = {a.account_id: a for a in accounts}
    for ln in real_lines:
        account = accounts_by_id.get(ln.account_id)
        if account is None or account.company_id != company_id:
            raise ValueError("یکی از حساب‌های انتخاب‌شده نامعتبر است.")
        if not account.is_postable:
            raise ValueError(f"حساب «{account.full_code}» قابل ثبت سند نیست.")


def _fiscal_year_bounds(
    start_month: int, start_day: int, on_date: datetime.date
) -> tuple[str, datetime.date, datetime.date]:
    jalali = jdatetime.date.fromgregorian(date=on_date)
    year = jalali.year
    if jalali < jdatetime.date(year, start_month, start_day):
        year -= 1
    start = jdatetime.date(year, start_month, start_day)
    end = jdatetime.date(year + 1, start_month, start_day) - datetime.timedelta(days=1)
    return str(year), start.togregorian(), end.togregorian()


def _get_or_create_fiscal_year(session, company: Company, on_date: datetime.date) -> FiscalYear:
    code, start, end = _fiscal_year_bounds(company.fiscal_year_start_month, company.fiscal_year_start_day, on_date)
    fiscal_year = session.scalar(
        select(FiscalYear).where(FiscalYear.company_id == company.company_id, FiscalYear.code == code)
    )
    if fiscal_year is None:
        fiscal_year = FiscalYear(company_id=company.company_id, code=code, start_date=start, end_date=end)
        session.add(fiscal_year)
        session.flush()
    return fiscal_year


def create_journal_entry(
    company_id: int,
    created_by_user_id: int,
    document_date: datetime.date,
    description: str,
    lines: list[LineInput],
) -> JournalEntryResult:
    real_lines, _total = _validate_lines(lines)

    with new_session() as session:
        company = session.get(Company, company_id)
        if company is None:
            raise ValueError("شرکت نامعتبر است.")

        _validate_accounts(session, company_id, real_lines)

        entry_type = session.scalar(select(JournalEntryType).where(JournalEntryType.code == "NORMAL"))
        status = session.scalar(select(JournalEntryStatus).where(JournalEntryStatus.code == "TEMPORARY"))
        if entry_type is None or status is None:
            raise ValueError("داده‌ی پایه‌ی نوع/وضعیت سند در دیتابیس یافت نشد.")

        fiscal_year = _get_or_create_fiscal_year(session, company, document_date)

        next_no = (
            session.scalar(
                select(func.max(JournalEntry.temporary_no)).where(
                    JournalEntry.company_id == company_id,
                    JournalEntry.fiscal_year_id == fiscal_year.fiscal_year_id,
                )
            )
            or 0
        ) + 1

        entry = JournalEntry(
            company_id=company_id,
            fiscal_year_id=fiscal_year.fiscal_year_id,
            temporary_no=next_no,
            permanent_no=None,
            document_date=document_date,
            entry_type_id=entry_type.entry_type_id,
            status_id=status.status_id,
            description=description or None,
            created_by_user_id=created_by_user_id,
        )
        session.add(entry)
        session.flush()

        for line_no, ln in enumerate(real_lines, start=1):
            session.add(
                JournalEntryLine(
                    journal_entry_id=entry.journal_entry_id,
                    line_no=line_no,
                    account_id=ln.account_id,
                    description=ln.description or None,
                    currency_id=company.base_currency_id,
                    exchange_rate=decimal.Decimal(1),
                    debit_amount_fc=ln.debit,
                    credit_amount_fc=ln.credit,
                )
            )

        session.commit()
        return JournalEntryResult(journal_entry_id=entry.journal_entry_id, temporary_no=entry.temporary_no)


def list_journal_entries(company_id: int) -> list[JournalEntrySummary]:
    with new_session() as session:
        entries = session.scalars(
            select(JournalEntry)
            .where(JournalEntry.company_id == company_id)
            .order_by(JournalEntry.document_date.desc(), JournalEntry.temporary_no.desc())
        ).all()
        entry_ids = [e.journal_entry_id for e in entries]
        totals: dict[int, decimal.Decimal] = {}
        if entry_ids:
            rows = session.execute(
                select(JournalEntryLine.journal_entry_id, func.sum(JournalEntryLine.debit_amount_fc))
                .where(JournalEntryLine.journal_entry_id.in_(entry_ids))
                .group_by(JournalEntryLine.journal_entry_id)
            ).all()
            totals = dict(rows)

        status_codes = dict(session.execute(select(JournalEntryStatus.status_id, JournalEntryStatus.code)).all())

        return [
            JournalEntrySummary(
                journal_entry_id=e.journal_entry_id,
                temporary_no=e.temporary_no,
                document_date=e.document_date,
                description=e.description or "",
                status_code=status_codes[e.status_id],
                total_amount=totals.get(e.journal_entry_id, decimal.Decimal(0)),
            )
            for e in entries
        ]


def get_journal_entry_lines(journal_entry_id: int) -> list[LineInput]:
    with new_session() as session:
        lines = session.scalars(
            select(JournalEntryLine)
            .where(JournalEntryLine.journal_entry_id == journal_entry_id)
            .order_by(JournalEntryLine.line_no)
        ).all()
        return [
            LineInput(
                account_id=ln.account_id,
                description=ln.description or "",
                debit=ln.debit_amount_fc,
                credit=ln.credit_amount_fc,
            )
            for ln in lines
        ]


def update_journal_entry(
    journal_entry_id: int,
    company_id: int,
    document_date: datetime.date,
    description: str,
    lines: list[LineInput],
) -> None:
    real_lines, _total = _validate_lines(lines)

    with new_session() as session:
        entry = session.get(JournalEntry, journal_entry_id)
        if entry is None or entry.company_id != company_id:
            raise ValueError("سند نامعتبر است.")
        status = session.get(JournalEntryStatus, entry.status_id)
        if status is None or status.code != "TEMPORARY":
            raise ValueError("فقط سندهای با وضعیت موقت قابل ویرایش‌اند.")

        _validate_accounts(session, company_id, real_lines)

        entry.document_date = document_date
        entry.description = description or None

        session.execute(JournalEntryLine.__table__.delete().where(JournalEntryLine.journal_entry_id == entry.journal_entry_id))

        company = session.get(Company, company_id)
        for line_no, ln in enumerate(real_lines, start=1):
            session.add(
                JournalEntryLine(
                    journal_entry_id=entry.journal_entry_id,
                    line_no=line_no,
                    account_id=ln.account_id,
                    description=ln.description or None,
                    currency_id=company.base_currency_id,
                    exchange_rate=decimal.Decimal(1),
                    debit_amount_fc=ln.debit,
                    credit_amount_fc=ln.credit,
                )
            )
        session.commit()


def delete_journal_entry(journal_entry_id: int, company_id: int) -> None:
    with new_session() as session:
        entry = session.get(JournalEntry, journal_entry_id)
        if entry is None or entry.company_id != company_id:
            raise ValueError("سند نامعتبر است.")
        status = session.get(JournalEntryStatus, entry.status_id)
        if status is None or status.code != "TEMPORARY":
            raise ValueError("فقط سندهای با وضعیت موقت قابل حذف‌اند.")

        session.execute(JournalEntryLine.__table__.delete().where(JournalEntryLine.journal_entry_id == journal_entry_id))
        session.delete(entry)
        session.commit()
