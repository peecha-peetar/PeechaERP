"""کوئری‌های داشبورد — همه واقعی روی دیتابیس، بدون داده‌ی ساختگی.

چون هنوز هیچ ماژولی به‌جز حسابداری (نصفه) و مدیریت کاربر ساخته نشده، از
KPIهای نمونه‌ی طراحی (فروش، موجودی انبار، ...) که هنوز داده‌ای برایشان
نداریم صرف‌نظر شده؛ به‌جایش چیزهایی نشان داده می‌شود که همین حالا صادقانه
قابل‌محاسبه‌اند.
"""

from __future__ import annotations

import datetime
import decimal
from dataclasses import dataclass

import jdatetime
from sqlalchemy import func, select

from peecha.db.base import new_session
from peecha.db.models.accounting import (
    AccountCategory, ChartOfAccount, DetailAccount, FiscalYear, JournalEntry, JournalEntryStatus,
)
from peecha.db.models.commercial import CommercialDocument
from peecha.db.models.core import Company
from peecha.db.models.hr import Employee
from peecha.db.models.security import User

_ZERO = decimal.Decimal("0")

_JE_STATUS_LABELS = {
    "DRAFT": "پیش‌نویس", "TEMPORARY": "موقت", "PERMANENT": "دائم",
    "REVERSED": "برگشت‌خورده", "CANCELLED": "ابطال‌شده",
}

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


# =======================================================================
# طبقِ درخواستِ صریح («برایِ هر ماژول داشبوردِ مخصوصِ خودش»): از این‌جا
# به بعد، هر تابع دقیقاً یک ماژول (حسابداری/خزانه‌داری/انبار/فروش/خرید/
# منابعِ‌انسانی) را می‌پوشاند -- طبقِ همان اصلِ اولِ این فایل («همه واقعی
# رویِ دیتابیس، بدونِ داده‌یِ ساختگی»)، فقط از رویِ سرویس‌هایِ ازپیش‌
# تست‌شده‌یِ همان ماژول (نه SQLِ موازیِ تازه) محاسبه می‌شود.
# =======================================================================


def journal_entries_by_status(company_id: int | None) -> list[tuple[str, int]]:
    """طبقِ تبِ «حسابداری»: شکستِ تعدادِ اسنادِ حسابداری بر اساسِ وضعیت
    (پیش‌نویس/موقت/دائم/برگشت‌خورده/ابطال‌شده)."""
    with new_session() as db_session:
        stmt = select(JournalEntryStatus.code, func.count()).join(
            JournalEntry, JournalEntry.status_id == JournalEntryStatus.status_id
        )
        if company_id is not None:
            stmt = stmt.where(JournalEntry.company_id == company_id)
        stmt = stmt.group_by(JournalEntryStatus.code)
        rows = db_session.execute(stmt).all()
    return [(_JE_STATUS_LABELS.get(code, code), count) for code, count in rows]


def open_fiscal_years_count(company_id: int | None) -> int:
    with new_session() as db_session:
        stmt = select(func.count()).select_from(FiscalYear).where(FiscalYear.is_closed.is_(False))
        if company_id is not None:
            stmt = stmt.where(FiscalYear.company_id == company_id)
        return db_session.scalar(stmt) or 0


@dataclass
class TreasurySummary:
    pending_received_checks_count: int = 0
    pending_received_checks_amount: decimal.Decimal = _ZERO
    pending_issued_checks_count: int = 0
    pending_issued_checks_amount: decimal.Decimal = _ZERO
    overdue_installments_count: int = 0
    overdue_installments_amount: decimal.Decimal = _ZERO


def treasury_summary(company_id: int | None) -> TreasurySummary:
    """طبقِ تبِ «خزانه‌داری»: چک‌هایِ دریافتیِ هنوز-نزدِ-صندوق، چک‌هایِ
    پرداختیِ هنوز-وصول‌نشده، و اقساطِ معوقه -- هرکدام از همان سرویسِ
    ازپیش‌تست‌شده‌یِ خودشان."""
    summary = TreasurySummary()
    if company_id is None:
        return summary
    from peecha.services import installments as installments_service
    from peecha.services import treasury as treasury_service

    received = treasury_service.list_received_checks(company_id, ["IN_HAND"])
    summary.pending_received_checks_count = len(received)
    summary.pending_received_checks_amount = sum((r.amount for r in received), _ZERO)

    issued = treasury_service.list_issued_checks(company_id, ["ISSUED"])
    summary.pending_issued_checks_count = len(issued)
    summary.pending_issued_checks_amount = sum((r.amount for r in issued), _ZERO)

    overdue = installments_service.list_installments(company_id, status_codes=["OVERDUE"])
    summary.overdue_installments_count = len(overdue)
    summary.overdue_installments_amount = sum((l.remaining_amount for l in overdue), _ZERO)
    return summary


@dataclass
class InventorySummary:
    total_value: decimal.Decimal = _ZERO
    active_items_count: int = 0
    warehouses_count: int = 0
    negative_balance_count: int = 0


def inventory_summary(company_id: int | None) -> InventorySummary:
    """طبقِ تبِ «انبار»: ارزشِ کلِ موجودی، تعدادِ کالا/انبارِ فعال، و
    تعدادِ ردیف‌هایِ موجودیِ منفی (نشانه‌یِ خطایِ ثبت -- نه یک وضعیتِ
    عادی)."""
    summary = InventorySummary()
    if company_id is None:
        return summary
    from peecha.services import inventory_catalog as catalog_service
    from peecha.services import inventory_engine as engine_service
    from peecha.services import inventory_locations as locations_service

    balances = engine_service.list_balances(company_id)
    summary.total_value = sum((b.total_value for b in balances), _ZERO)
    summary.negative_balance_count = sum(1 for b in balances if b.quantity_on_hand < 0)
    summary.active_items_count = len(catalog_service.list_items(company_id, active_only=True))
    summary.warehouses_count = len(locations_service.list_warehouses(company_id, active_only=True))
    return summary


def inventory_value_by_warehouse(company_id: int | None, limit: int = 6) -> list[tuple[str, decimal.Decimal]]:
    if company_id is None:
        return []
    from peecha.services import inventory_engine as engine_service
    from peecha.services import inventory_locations as locations_service

    balances = engine_service.list_balances(company_id)
    totals: dict[int, decimal.Decimal] = {}
    for b in balances:
        totals[b.warehouse_id] = totals.get(b.warehouse_id, _ZERO) + b.total_value
    labels = {w.warehouse_id: (w.name or w.code) for w in locations_service.list_warehouses(company_id)}
    rows = [(labels.get(wid, str(wid)), value) for wid, value in totals.items() if value != _ZERO]
    rows.sort(key=lambda pair: pair[1], reverse=True)
    return rows[:limit]


@dataclass
class CommercialSummary:
    this_month_total: decimal.Decimal = _ZERO
    unsettled_count: int = 0
    unsettled_amount: decimal.Decimal = _ZERO


def commercial_summary(company_id: int | None, document_type_code: str) -> CommercialSummary:
    """طبقِ تب‌هایِ «فروش»/«خرید»: جمعِ فاکتورهایِ ثبتِ‌نهایی‌شده‌یِ همین
    ماه، و تعداد/مبلغِ فاکتورهایِ هنوز-تسویه‌نشده (از سرویسِ تسویه)."""
    summary = CommercialSummary()
    if company_id is None:
        return summary
    from peecha.services import commercial_settlements as settlements_service

    today = datetime.date.today()
    with new_session() as db_session:
        stmt = select(func.coalesce(func.sum(CommercialDocument.total_amount), 0)).where(
            CommercialDocument.company_id == company_id,
            CommercialDocument.document_type_code == document_type_code,
            CommercialDocument.status_code == "POSTED",
            func.date_trunc("month", CommercialDocument.document_date) == datetime.date(today.year, today.month, 1),
        )
        summary.this_month_total = db_session.scalar(stmt) or _ZERO

    unsettled = settlements_service.list_unsettled_invoices(company_id, document_type_code)
    summary.unsettled_count = len(unsettled)
    summary.unsettled_amount = sum((u.remaining_amount for u in unsettled), _ZERO)
    return summary


def commercial_amount_per_month(
    company_id: int | None, document_type_code: str, months: int = 6
) -> tuple[list[str], list[decimal.Decimal]]:
    """معادلِ journal_entries_per_month، برایِ جمعِ مبلغِ فاکتورهایِ
    ثبتِ‌نهایی‌شده‌یِ یک نوعِ سند (فروش/خرید) در N ماهِ اخیر."""
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

    counts_by_ym: dict[tuple[int, int], decimal.Decimal] = {}
    if company_id is not None:
        with new_session() as db_session:
            stmt = select(
                func.date_trunc("month", CommercialDocument.document_date).label("bucket"),
                func.coalesce(func.sum(CommercialDocument.total_amount), 0),
            ).where(
                CommercialDocument.company_id == company_id,
                CommercialDocument.document_type_code == document_type_code,
                CommercialDocument.status_code == "POSTED",
            ).group_by("bucket")
            rows = db_session.execute(stmt).all()
        counts_by_ym = {(row.bucket.year, row.bucket.month): row[1] for row in rows}

    labels: list[str] = []
    values: list[decimal.Decimal] = []
    for y, m in ym_buckets:
        jalali = jdatetime.date.fromgregorian(date=datetime.date(y, m, 1))
        labels.append(PERSIAN_MONTHS[jalali.month - 1])
        values.append(counts_by_ym.get((y, m), _ZERO))
    return labels, values


def top_counterparties(
    company_id: int | None, document_type_code: str, limit: int = 5
) -> list[tuple[str, decimal.Decimal]]:
    """طبقِ تب‌هایِ «فروش»/«خرید»: پُرفروش‌ترین مشتریان / پُرخریدترین
    تامین‌کنندگان (بر اساسِ جمعِ مبلغِ فاکتورهایِ ثبتِ‌نهایی‌شده)."""
    if company_id is None:
        return []
    with new_session() as db_session:
        stmt = (
            select(
                CommercialDocument.counterparty_detail_account_id,
                DetailAccount.code, DetailAccount.name,
                func.coalesce(func.sum(CommercialDocument.total_amount), 0),
            )
            .join(DetailAccount, DetailAccount.detail_account_id == CommercialDocument.counterparty_detail_account_id)
            .where(
                CommercialDocument.company_id == company_id,
                CommercialDocument.document_type_code == document_type_code,
                CommercialDocument.status_code == "POSTED",
            )
            .group_by(CommercialDocument.counterparty_detail_account_id, DetailAccount.code, DetailAccount.name)
            .order_by(func.sum(CommercialDocument.total_amount).desc())
            .limit(limit)
        )
        rows = db_session.execute(stmt).all()
    return [(f"{code} — {name}" if name else code, total) for _party_id, code, name, total in rows]


@dataclass
class HrSummary:
    total_employees: int = 0
    active_employees: int = 0


def hr_summary(company_id: int | None) -> HrSummary:
    summary = HrSummary()
    if company_id is None:
        return summary
    with new_session() as db_session:
        summary.total_employees = db_session.scalar(
            select(func.count()).select_from(Employee).where(Employee.company_id == company_id)
        ) or 0
        summary.active_employees = db_session.scalar(
            select(func.count()).select_from(Employee).where(
                Employee.company_id == company_id, Employee.status == "ACTIVE"
            )
        ) or 0
    return summary
