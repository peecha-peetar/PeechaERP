"""کوئری‌های داشبورد — همه واقعی روی دیتابیس، بدون داده‌ی ساختگی.

چون هنوز هیچ ماژولی به‌جز حسابداری (نصفه) و مدیریت کاربر ساخته نشده، از
KPIهای نمونه‌ی طراحی (فروش، موجودی انبار، ...) که هنوز داده‌ای برایشان
نداریم صرف‌نظر شده؛ به‌جایش چیزهایی نشان داده می‌شود که همین حالا صادقانه
قابل‌محاسبه‌اند.
"""

from __future__ import annotations

import datetime

import jdatetime
from sqlalchemy import func, select

from peecha.db.base import new_session
from peecha.db.models.accounting import AccountCategory, ChartOfAccount, JournalEntry
from peecha.db.models.core import Company
from peecha.db.models.security import User

PERSIAN_MONTHS = [
    "فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
    "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند",
]

CATEGORY_LABELS = {
    "ASSET": "دارایی",
    "LIABILITY": "بدهی",
    "EQUITY": "حقوق صاحبان سهام",
    "REVENUE": "درآمد",
    "COGS": "بهایِ تمام‌شده",
    "EXPENSE": "هزینه",
    "STATISTICAL": "حساب‌هایِ آماری",
}


def count_companies() -> int:
    with new_session() as db_session:
        return db_session.scalar(select(func.count()).select_from(Company)) or 0


def count_users() -> int:
    with new_session() as db_session:
        return db_session.scalar(select(func.count()).select_from(User)) or 0


def count_chart_of_accounts(company_id: int | None) -> int:
    with new_session() as db_session:
        stmt = select(func.count()).select_from(ChartOfAccount)
        if company_id is not None:
            stmt = stmt.where(ChartOfAccount.company_id == company_id)
        return db_session.scalar(stmt) or 0


def count_journal_entries(company_id: int | None) -> int:
    with new_session() as db_session:
        stmt = select(func.count()).select_from(JournalEntry)
        if company_id is not None:
            stmt = stmt.where(JournalEntry.company_id == company_id)
        return db_session.scalar(stmt) or 0


def journal_entries_per_month(company_id: int | None, months: int = 6) -> tuple[list[str], list[int]]:
    """تعداد اسناد حسابداری ثبت‌شده به تفکیک ماه (شمسی) در N ماه اخیر."""
    today = datetime.date.today()
    year, month = today.year, today.month
    ym_buckets: list[tuple[int, int]] = []
    for _ in range(months):
        ym_buckets.append((year, month))
        month -= 1
        if month == 0:
            month = 12
            year -= 1
    ym_buckets.reverse()

    with new_session() as db_session:
        stmt = select(
            func.date_trunc("month", JournalEntry.document_date).label("bucket"),
            func.count(),
        )
        if company_id is not None:
            stmt = stmt.where(JournalEntry.company_id == company_id)
        stmt = stmt.group_by("bucket")
        rows = db_session.execute(stmt).all()

    counts_by_ym = {(row.bucket.year, row.bucket.month): row[1] for row in rows}
    labels: list[str] = []
    values: list[int] = []
    for y, m in ym_buckets:
        jalali = jdatetime.date.fromgregorian(date=datetime.date(y, m, 1))
        labels.append(PERSIAN_MONTHS[jalali.month - 1])
        values.append(counts_by_ym.get((y, m), 0))
    return labels, values


def chart_of_accounts_by_category(company_id: int | None) -> list[tuple[str, int]]:
    """تعداد حساب‌های تعریف‌شده به تفکیک نوع (دارایی/بدهی/...) — فقط
    دسته‌هایی که واقعاً حسابی در آن‌ها تعریف شده برگردانده می‌شود."""
    with new_session() as db_session:
        stmt = select(AccountCategory.code, func.count(ChartOfAccount.account_id)).join(
            ChartOfAccount, ChartOfAccount.category_id == AccountCategory.category_id
        )
        if company_id is not None:
            stmt = stmt.where(ChartOfAccount.company_id == company_id)
        stmt = stmt.group_by(AccountCategory.code)
        rows = db_session.execute(stmt).all()
    return [(CATEGORY_LABELS.get(code, code), count) for code, count in rows]
