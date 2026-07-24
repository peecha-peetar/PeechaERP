"""موتورِ محاسبه‌یِ خامِ گزارش‌هایِ حسابداری — بدونِ هیچ UI.

هیچ کوئریِ balance/aggregation‌ای در کدِ قبلی وجود نداشت (فقط CRUD/اعتبارسنجیِ
ساختاری در chart_of_accounts.py/detail_dimensions.py)؛ این ماژول از رویِ
acc.journal_entry_lines (ستون‌هایِ GENERATED محاسبه‌شده‌یِ debit_amount_base/
credit_amount_base) مانده/گردشِ حساب‌ها را می‌سازد.

طبقِ محدودیتِ شناخته‌شده: در سیستمِ فعلی هیچ سندِ اختتامیه‌ای وجود ندارد، پس
«مانده‌ی اول» همیشه یعنی «جمعِ همه‌چیز پیش از تاریخِ شروعِ بازه» (نه مانده‌ی
بعدِ یک بستنِ رسمی)."""

from __future__ import annotations

import datetime
import decimal
from dataclasses import dataclass

from sqlalchemy import func, select

from peecha.db.base import new_session
from peecha.db.models.accounting import (
    ChartOfAccount,
    JournalEntry,
    JournalEntryLine,
    JournalEntryLineDetail,
    JournalEntryStatus,
)
from peecha.services import chart_of_accounts as coa_service
from peecha.services import detail_dimensions as dimensions_service

_ZERO = decimal.Decimal("0")


@dataclass
class AccountBalanceRow:
    """مانده/گردشِ یک حساب (یا یک حسابِ تفصیلی) در یک بازه — دو تابعِ
    compute_account_balances/compute_detail_balances هردو همین شکل را
    برمی‌گردانند تا صفحه‌یِ گزارش بتواند بدونِ دانستنِ منبع، یکسان رندر کند."""

    account_id: int
    full_code: str
    name: str
    account_level: int
    parent_account_id: int | None
    nature_code: str
    category_code: str
    account_type_code: str
    opening_debit: decimal.Decimal
    opening_credit: decimal.Decimal
    period_debit: decimal.Decimal
    period_credit: decimal.Decimal
    closing_debit: decimal.Decimal
    closing_credit: decimal.Decimal


def _day_before(value: datetime.date | None) -> datetime.date | None:
    return value - datetime.timedelta(days=1) if value is not None else None


def _raw_account_sums(
    session,
    company_id: int,
    date_from: datetime.date | None,
    date_to: datetime.date | None,
    include_draft: bool,
) -> dict[int, tuple[decimal.Decimal, decimal.Decimal]]:
    query = (
        select(
            JournalEntryLine.account_id,
            func.coalesce(func.sum(JournalEntryLine.debit_amount_base), 0),
            func.coalesce(func.sum(JournalEntryLine.credit_amount_base), 0),
        )
        .join(JournalEntry, JournalEntry.journal_entry_id == JournalEntryLine.journal_entry_id)
        .where(JournalEntry.company_id == company_id)
    )
    if date_from is not None:
        query = query.where(JournalEntry.document_date >= date_from)
    if date_to is not None:
        query = query.where(JournalEntry.document_date <= date_to)
    if not include_draft:
        query = query.join(JournalEntryStatus, JournalEntryStatus.status_id == JournalEntry.status_id).where(
            JournalEntryStatus.code != "DRAFT"
        )
    query = query.group_by(JournalEntryLine.account_id)
    return {
        account_id: (decimal.Decimal(debit), decimal.Decimal(credit))
        for account_id, debit, credit in session.execute(query).all()
    }


def _raw_detail_sums(
    session,
    company_id: int,
    dimension_type_id: int,
    date_from: datetime.date | None,
    date_to: datetime.date | None,
    include_draft: bool,
) -> dict[int, tuple[decimal.Decimal, decimal.Decimal]]:
    query = (
        select(
            JournalEntryLineDetail.detail_account_id,
            func.coalesce(func.sum(JournalEntryLine.debit_amount_base), 0),
            func.coalesce(func.sum(JournalEntryLine.credit_amount_base), 0),
        )
        .join(JournalEntryLine, JournalEntryLine.line_id == JournalEntryLineDetail.line_id)
        .join(JournalEntry, JournalEntry.journal_entry_id == JournalEntryLine.journal_entry_id)
        .where(JournalEntry.company_id == company_id, JournalEntryLineDetail.dimension_type_id == dimension_type_id)
    )
    if date_from is not None:
        query = query.where(JournalEntry.document_date >= date_from)
    if date_to is not None:
        query = query.where(JournalEntry.document_date <= date_to)
    if not include_draft:
        query = query.join(JournalEntryStatus, JournalEntryStatus.status_id == JournalEntry.status_id).where(
            JournalEntryStatus.code != "DRAFT"
        )
    query = query.group_by(JournalEntryLineDetail.detail_account_id)
    return {
        detail_account_id: (decimal.Decimal(debit), decimal.Decimal(credit))
        for detail_account_id, debit, credit in session.execute(query).all()
    }


def _rollup_sums(
    ids: list[int],
    parent_map: dict[int, int | None],
    leaf_sums: dict[int, tuple[decimal.Decimal, decimal.Decimal]],
) -> dict[int, tuple[decimal.Decimal, decimal.Decimal]]:
    """جمعِ هر گره = مانده‌یِ مستقیمِ خودش (اگر برگ باشد) + جمعِ رول‌آپ‌شده‌یِ
    همه‌یِ فرزندانش — یک‌بار برایِ درختِ حساب‌ها (گروه/کل/معین) و یک‌بار برایِ
    درختِ حساب‌هایِ تفصیلی (تا ۴ سطح) استفاده می‌شود، چون هردو ساختارِ
    parent_id یکسانی دارند."""
    children: dict[int, list[int]] = {}
    for node_id in ids:
        parent_id = parent_map.get(node_id)
        if parent_id is not None:
            children.setdefault(parent_id, []).append(node_id)

    memo: dict[int, tuple[decimal.Decimal, decimal.Decimal]] = {}

    def resolve(node_id: int) -> tuple[decimal.Decimal, decimal.Decimal]:
        if node_id in memo:
            return memo[node_id]
        debit, credit = leaf_sums.get(node_id, (_ZERO, _ZERO))
        for child_id in children.get(node_id, []):
            child_debit, child_credit = resolve(child_id)
            debit += child_debit
            credit += child_credit
        memo[node_id] = (debit, credit)
        return memo[node_id]

    for node_id in ids:
        resolve(node_id)
    return memo


def compute_account_balances(
    company_id: int,
    date_from: datetime.date | None,
    date_to: datetime.date | None,
    *,
    include_draft: bool = False,
) -> list[AccountBalanceRow]:
    """مانده/گردشِ همه‌یِ حساب‌ها (هر سه سطحِ گروه/کل/معین)، رول‌آپ‌شده از
    رویِ حساب‌هایِ قابلِ‌ثبتِ سند (سطحِ معین) که تنها سطحی هستند که مستقیماً
    رویِ journal_entry_lines رخ می‌دهند."""
    accounts = coa_service.list_accounts(company_id)
    ids = [a.account_id for a in accounts]
    with new_session() as session:
        parent_map = dict(
            session.execute(
                select(ChartOfAccount.account_id, ChartOfAccount.parent_account_id).where(
                    ChartOfAccount.company_id == company_id
                )
            ).all()
        )
        opening_leaf = (
            _raw_account_sums(session, company_id, None, _day_before(date_from), include_draft)
            if date_from is not None
            else {}
        )
        period_leaf = _raw_account_sums(session, company_id, date_from, date_to, include_draft)

    opening_rolled = _rollup_sums(ids, parent_map, opening_leaf)
    period_rolled = _rollup_sums(ids, parent_map, period_leaf)

    rows: list[AccountBalanceRow] = []
    for a in accounts:
        opening_debit, opening_credit = opening_rolled.get(a.account_id, (_ZERO, _ZERO))
        period_debit, period_credit = period_rolled.get(a.account_id, (_ZERO, _ZERO))
        rows.append(
            AccountBalanceRow(
                account_id=a.account_id,
                full_code=a.full_code,
                name=a.name,
                account_level=a.account_level,
                parent_account_id=parent_map.get(a.account_id),
                nature_code=a.nature_code,
                category_code=a.category_code,
                account_type_code=a.account_type_code,
                opening_debit=opening_debit,
                opening_credit=opening_credit,
                period_debit=period_debit,
                period_credit=period_credit,
                closing_debit=opening_debit + period_debit,
                closing_credit=opening_credit + period_credit,
            )
        )
    return rows


def compute_detail_balances(
    company_id: int,
    dimension_type_id: int,
    date_from: datetime.date | None,
    date_to: datetime.date | None,
    *,
    include_draft: bool = False,
) -> list[AccountBalanceRow]:
    """معادلِ compute_account_balances ولی در سطحِ حساب‌هایِ تفصیلیِ یک
    نوع‌بُعدِ مشخص (مثلاً مشتریان یا مراکزِ هزینه)، رول‌آپ‌شده رویِ سلسله‌مراتبِ
    تا ۴سطحیِ acc.detail_accounts.parent_detail_account_id."""
    detail_rows = [
        r for r in dimensions_service.list_all_detail_accounts(company_id) if r.dimension_type_id == dimension_type_id
    ]
    ids = [r.detail_account_id for r in detail_rows]
    parent_map = {r.detail_account_id: r.parent_detail_account_id for r in detail_rows}

    with new_session() as session:
        opening_leaf = (
            _raw_detail_sums(session, company_id, dimension_type_id, None, _day_before(date_from), include_draft)
            if date_from is not None
            else {}
        )
        period_leaf = _raw_detail_sums(session, company_id, dimension_type_id, date_from, date_to, include_draft)

    opening_rolled = _rollup_sums(ids, parent_map, opening_leaf)
    period_rolled = _rollup_sums(ids, parent_map, period_leaf)

    rows: list[AccountBalanceRow] = []
    for r in detail_rows:
        opening_debit, opening_credit = opening_rolled.get(r.detail_account_id, (_ZERO, _ZERO))
        period_debit, period_credit = period_rolled.get(r.detail_account_id, (_ZERO, _ZERO))
        rows.append(
            AccountBalanceRow(
                account_id=r.detail_account_id,
                full_code=r.full_code,
                name=r.name or "",
                account_level=r.level_no,
                parent_account_id=r.parent_detail_account_id,
                nature_code="BOTH",
                category_code="",
                account_type_code="",
                opening_debit=opening_debit,
                opening_credit=opening_credit,
                period_debit=period_debit,
                period_credit=period_credit,
                closing_debit=opening_debit + period_debit,
                closing_credit=opening_credit + period_credit,
            )
        )
    return rows
