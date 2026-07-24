"""موتورِ محاسبه‌یِ خامِ گزارش‌هایِ حسابداری — بدونِ هیچ UI.

هیچ کوئریِ balance/aggregation‌ای در کدِ قبلی وجود نداشت (فقط CRUD/اعتبارسنجیِ
ساختاری در chart_of_accounts.py/detail_dimensions.py)؛ این ماژول از رویِ
acc.journal_entry_lines (ستون‌هایِ GENERATED محاسبه‌شده‌یِ debit_amount_base/
credit_amount_base) مانده/گردشِ حساب‌ها را می‌سازد.

طبقِ محدودیتِ شناخته‌شده: در سیستمِ فعلی هیچ سندِ اختتامیه‌ای وجود ندارد، پس
«مانده‌ی اول» همیشه یعنی «جمعِ همه‌چیز پیش از تاریخِ شروعِ بازه» (نه مانده‌ی
بعدِ یک بستنِ رسمی).

طبقِ درخواستِ صریح، هر تابعِ سطحِ سند/گردش سه فیلترِ پیشرفته‌یِ مشترک را
می‌پذیرد:
- status_filter: "EXCLUDE_DRAFT" (پیش‌فرض، بدونِ پیش‌نویس) | "ALL" (شاملِ
  پیش‌نویس) | "DRAFT_ONLY" (فقط پیش‌نویس).
- cost_center_id: محدودکردنِ گردش به یک حسابِ تفصیلیِ مشخص (معمولاً مرکزِ
  هزینه یا پروژه) — از رویِ acc.journal_entry_line_details.
- document_no_filter: محدودکردن به یک شماره‌یِ سندِ (temporary_no) مشخص.
"""

from __future__ import annotations

import datetime
import decimal
from dataclasses import dataclass

from sqlalchemy import func, select

from peecha.db.base import new_session
from peecha.db.models.accounting import (
    AccountDetailDimension,
    ChartOfAccount,
    DetailDimensionType,
    JournalEntry,
    JournalEntryLine,
    JournalEntryLineDetail,
    JournalEntryStatus,
)
from peecha.services import chart_of_accounts as coa_service
from peecha.services import detail_dimensions as dimensions_service

_ZERO = decimal.Decimal("0")


def _apply_status_filter(query, status_filter: str):
    if status_filter == "ALL":
        return query
    query = query.join(JournalEntryStatus, JournalEntryStatus.status_id == JournalEntry.status_id)
    if status_filter == "DRAFT_ONLY":
        return query.where(JournalEntryStatus.code == "DRAFT")
    return query.where(JournalEntryStatus.code != "DRAFT")  # "EXCLUDE_DRAFT"


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
    status_filter: str,
    *,
    cost_center_id: int | None = None,
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
    if cost_center_id is not None:
        query = query.join(
            JournalEntryLineDetail, JournalEntryLineDetail.line_id == JournalEntryLine.line_id
        ).where(JournalEntryLineDetail.detail_account_id == cost_center_id)
    if date_from is not None:
        query = query.where(JournalEntry.document_date >= date_from)
    if date_to is not None:
        query = query.where(JournalEntry.document_date <= date_to)
    query = _apply_status_filter(query, status_filter)
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
    status_filter: str,
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
    query = _apply_status_filter(query, status_filter)
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
    status_filter: str = "EXCLUDE_DRAFT",
    cost_center_id: int | None = None,
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
            _raw_account_sums(
                session, company_id, None, _day_before(date_from), status_filter, cost_center_id=cost_center_id
            )
            if date_from is not None
            else {}
        )
        period_leaf = _raw_account_sums(
            session, company_id, date_from, date_to, status_filter, cost_center_id=cost_center_id
        )

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
    status_filter: str = "EXCLUDE_DRAFT",
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
            _raw_detail_sums(session, company_id, dimension_type_id, None, _day_before(date_from), status_filter)
            if date_from is not None
            else {}
        )
        period_leaf = _raw_detail_sums(session, company_id, dimension_type_id, date_from, date_to, status_filter)

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


@dataclass
class JournalBookLineRow:
    document_date: datetime.date
    temporary_no: int
    description: str
    account_full_code: str
    account_name: str
    debit: decimal.Decimal
    credit: decimal.Decimal


def list_journal_book_lines(
    company_id: int,
    date_from: datetime.date | None,
    date_to: datetime.date | None,
    *,
    status_filter: str = "EXCLUDE_DRAFT",
    cost_center_id: int | None = None,
    document_no_filter: int | None = None,
) -> list[JournalBookLineRow]:
    """دفترِ روزنامه: ردیف‌هایِ سند+سطر به‌ترتیبِ تاریخ/شماره/شماره‌یِ ردیف —
    برایِ تحریرِ دفاترِ قانونی."""
    accounts_by_id = {a.account_id: a for a in coa_service.list_accounts(company_id)}
    with new_session() as session:
        query = (
            select(JournalEntryLine, JournalEntry.document_date, JournalEntry.temporary_no, JournalEntry.description)
            .join(JournalEntry, JournalEntry.journal_entry_id == JournalEntryLine.journal_entry_id)
            .where(JournalEntry.company_id == company_id)
        )
        if cost_center_id is not None:
            query = query.join(
                JournalEntryLineDetail, JournalEntryLineDetail.line_id == JournalEntryLine.line_id
            ).where(JournalEntryLineDetail.detail_account_id == cost_center_id)
        if document_no_filter is not None:
            query = query.where(JournalEntry.temporary_no == document_no_filter)
        if date_from is not None:
            query = query.where(JournalEntry.document_date >= date_from)
        if date_to is not None:
            query = query.where(JournalEntry.document_date <= date_to)
        query = _apply_status_filter(query, status_filter)
        query = query.order_by(JournalEntry.document_date, JournalEntry.temporary_no, JournalEntryLine.line_no)
        rows = session.execute(query).all()

    result: list[JournalBookLineRow] = []
    for line, document_date, temporary_no, entry_description in rows:
        account = accounts_by_id.get(line.account_id)
        result.append(
            JournalBookLineRow(
                document_date=document_date,
                temporary_no=temporary_no,
                description=line.description or entry_description or "",
                account_full_code=account.full_code if account else "",
                account_name=account.name if account else "",
                debit=line.debit_amount_base,
                credit=line.credit_amount_base,
            )
        )
    return result


@dataclass
class LedgerLineRow:
    document_date: datetime.date
    temporary_no: int
    description: str
    debit: decimal.Decimal
    credit: decimal.Decimal
    running_debit: decimal.Decimal
    running_credit: decimal.Decimal


def list_ledger_entries(
    company_id: int,
    date_from: datetime.date | None,
    date_to: datetime.date | None,
    *,
    account_id: int | None = None,
    detail_account_id: int | None = None,
    status_filter: str = "EXCLUDE_DRAFT",
    cost_center_id: int | None = None,
    document_no_filter: int | None = None,
) -> tuple[decimal.Decimal, decimal.Decimal, list[LedgerLineRow]]:
    """گردشِ زمانیِ یک حسابِ کدینگیِ مشخص (account_id) یا یک حسابِ تفصیلیِ
    مشخص (detail_account_id)، با مانده‌یِ رواگرد — برایِ دفترِ کل/معین/تفصیلی
    و مرورِ حساب‌ها. دقیقاً یکی از این دو پارامتر باید داده شود."""
    if (account_id is None) == (detail_account_id is None):
        raise ValueError("دقیقاً یکی از account_id یا detail_account_id باید داده شود.")

    with new_session() as session:
        opening_debit, opening_credit = _ZERO, _ZERO
        if date_from is not None:
            opening_query = (
                select(
                    func.coalesce(func.sum(JournalEntryLine.debit_amount_base), 0),
                    func.coalesce(func.sum(JournalEntryLine.credit_amount_base), 0),
                )
                .select_from(JournalEntryLine)
                .join(JournalEntry, JournalEntry.journal_entry_id == JournalEntryLine.journal_entry_id)
                .where(JournalEntry.company_id == company_id, JournalEntry.document_date < date_from)
            )
            if detail_account_id is not None:
                opening_query = opening_query.join(
                    JournalEntryLineDetail, JournalEntryLineDetail.line_id == JournalEntryLine.line_id
                ).where(JournalEntryLineDetail.detail_account_id == detail_account_id)
            else:
                opening_query = opening_query.where(JournalEntryLine.account_id == account_id)
            if cost_center_id is not None:
                cc_alias = select(JournalEntryLineDetail.line_id).where(
                    JournalEntryLineDetail.detail_account_id == cost_center_id
                )
                opening_query = opening_query.where(JournalEntryLine.line_id.in_(cc_alias))
            opening_query = _apply_status_filter(opening_query, status_filter)
            debit_sum, credit_sum = session.execute(opening_query).one()
            opening_debit, opening_credit = decimal.Decimal(debit_sum), decimal.Decimal(credit_sum)

        line_query = (
            select(JournalEntryLine, JournalEntry.document_date, JournalEntry.temporary_no, JournalEntry.description)
            .join(JournalEntry, JournalEntry.journal_entry_id == JournalEntryLine.journal_entry_id)
            .where(JournalEntry.company_id == company_id)
        )
        if detail_account_id is not None:
            line_query = line_query.join(
                JournalEntryLineDetail, JournalEntryLineDetail.line_id == JournalEntryLine.line_id
            ).where(JournalEntryLineDetail.detail_account_id == detail_account_id)
        else:
            line_query = line_query.where(JournalEntryLine.account_id == account_id)
        if cost_center_id is not None:
            cc_alias = select(JournalEntryLineDetail.line_id).where(
                JournalEntryLineDetail.detail_account_id == cost_center_id
            )
            line_query = line_query.where(JournalEntryLine.line_id.in_(cc_alias))
        if document_no_filter is not None:
            line_query = line_query.where(JournalEntry.temporary_no == document_no_filter)
        if date_from is not None:
            line_query = line_query.where(JournalEntry.document_date >= date_from)
        if date_to is not None:
            line_query = line_query.where(JournalEntry.document_date <= date_to)
        line_query = _apply_status_filter(line_query, status_filter)
        line_query = line_query.order_by(
            JournalEntry.document_date, JournalEntry.temporary_no, JournalEntryLine.line_no
        )
        rows = session.execute(line_query).all()

    running_debit, running_credit = opening_debit, opening_credit
    result: list[LedgerLineRow] = []
    for line, document_date, temporary_no, entry_description in rows:
        running_debit += line.debit_amount_base
        running_credit += line.credit_amount_base
        result.append(
            LedgerLineRow(
                document_date=document_date,
                temporary_no=temporary_no,
                description=line.description or entry_description or "",
                debit=line.debit_amount_base,
                credit=line.credit_amount_base,
                running_debit=running_debit,
                running_credit=running_credit,
            )
        )
    return opening_debit, opening_credit, result


def _net_income(
    company_id: int, date_from: datetime.date | None, date_to: datetime.date, status_filter: str
) -> decimal.Decimal:
    """سودِ خالصِ یک بازه — جمعِ سطحِ گروه (۱) کافی است، چون رول‌آپِ گروه
    از قبل شاملِ همه‌یِ زیرمجموعه‌هایِ همان دسته‌بندی است (دوباره‌شماری در
    سطوحِ پایین‌تر رخ نمی‌دهد)."""
    balances = compute_account_balances(company_id, date_from, date_to, status_filter=status_filter)
    total_revenue = sum(
        (r.period_credit - r.period_debit for r in balances if r.category_code == "REVENUE" and r.account_level == 1),
        _ZERO,
    )
    total_expense = sum(
        (r.period_debit - r.period_credit for r in balances if r.category_code == "EXPENSE" and r.account_level == 1),
        _ZERO,
    )
    return total_revenue - total_expense


@dataclass
class IncomeStatementRow:
    full_code: str
    name: str
    category_code: str  # REVENUE | EXPENSE
    current_amount: decimal.Decimal
    previous_amount: decimal.Decimal


@dataclass
class IncomeStatementResult:
    rows: list[IncomeStatementRow]
    total_revenue: decimal.Decimal
    total_expense: decimal.Decimal
    net_income: decimal.Decimal


def compute_income_statement(
    company_id: int,
    date_from: datetime.date,
    date_to: datetime.date,
    *,
    status_filter: str = "EXCLUDE_DRAFT",
    cost_center_id: int | None = None,
) -> IncomeStatementResult:
    """صورتِ سود و زیان — حساب‌هایِ REVENUE/EXPENSE در سطحِ کل، به‌همراهِ
    مقایسه با همان بازه در یک سالِ پیش (برایِ مقایسه‌یِ روندی، نه سالِ مالیِ
    قانونی — چون سیستم مفهومِ صریحِ «سالِ مالیِ قبل» را جدول‌بندی‌شده ندارد)."""
    previous_from = date_from - datetime.timedelta(days=365)
    previous_to = date_to - datetime.timedelta(days=365)

    current_balances = compute_account_balances(
        company_id, date_from, date_to, status_filter=status_filter, cost_center_id=cost_center_id
    )
    previous_balances = compute_account_balances(
        company_id, previous_from, previous_to, status_filter=status_filter, cost_center_id=cost_center_id
    )
    previous_by_id = {r.account_id: r for r in previous_balances}

    rows: list[IncomeStatementRow] = []
    for r in current_balances:
        if r.category_code not in ("REVENUE", "EXPENSE") or r.account_level != 2:
            continue
        if r.category_code == "REVENUE":
            current_amount = r.period_credit - r.period_debit
        else:
            current_amount = r.period_debit - r.period_credit
        prev = previous_by_id.get(r.account_id)
        if prev is None:
            previous_amount = _ZERO
        elif r.category_code == "REVENUE":
            previous_amount = prev.period_credit - prev.period_debit
        else:
            previous_amount = prev.period_debit - prev.period_credit
        rows.append(
            IncomeStatementRow(
                full_code=r.full_code,
                name=r.name,
                category_code=r.category_code,
                current_amount=current_amount,
                previous_amount=previous_amount,
            )
        )

    total_revenue = sum(
        (
            r.period_credit - r.period_debit
            for r in current_balances
            if r.category_code == "REVENUE" and r.account_level == 1
        ),
        _ZERO,
    )
    total_expense = sum(
        (
            r.period_debit - r.period_credit
            for r in current_balances
            if r.category_code == "EXPENSE" and r.account_level == 1
        ),
        _ZERO,
    )
    return IncomeStatementResult(
        rows=rows, total_revenue=total_revenue, total_expense=total_expense, net_income=total_revenue - total_expense
    )


@dataclass
class BalanceSheetRow:
    full_code: str
    name: str
    category_code: str  # ASSET | LIABILITY | EQUITY
    balance: decimal.Decimal


@dataclass
class BalanceSheetResult:
    asset_rows: list[BalanceSheetRow]
    liability_rows: list[BalanceSheetRow]
    equity_rows: list[BalanceSheetRow]
    total_assets: decimal.Decimal
    total_liabilities: decimal.Decimal
    total_equity: decimal.Decimal
    accumulated_earnings: decimal.Decimal


def compute_balance_sheet(
    company_id: int,
    as_of_date: datetime.date,
    *,
    status_filter: str = "EXCLUDE_DRAFT",
    cost_center_id: int | None = None,
) -> BalanceSheetResult:
    """ترازنامه — حساب‌هایِ ترازنامه‌ای (account_type=PERMANENT) در سطحِ کل،
    تا as_of_date. چون سیستم سندِ اختتامیه ندارد و هیچ حسابِ «سودِ انباشته»یِ
    واقعی هرگز بستانکار نمی‌شود، سودِ خالصِ *تجمعیِ از ابتدا* (نه فقط سالِ
    مالیِ جاری — چون مرزِ سالِ مالی این‌جا معنایِ حسابداریِ واقعی ندارد) به‌عنوانِ
    یک ردیفِ محاسبه‌شده به حقوقِ صاحبانِ سهام اضافه می‌شود؛ این تنها راهی است
    که ترازنامه همیشه (دارایی = بدهی + حقوقِ صاحبانِ سهام) بماند."""
    balances = compute_account_balances(
        company_id, None, as_of_date, status_filter=status_filter, cost_center_id=cost_center_id
    )

    asset_rows: list[BalanceSheetRow] = []
    liability_rows: list[BalanceSheetRow] = []
    equity_rows: list[BalanceSheetRow] = []
    total_assets = total_liabilities = total_equity = _ZERO

    for r in balances:
        if r.account_type_code != "PERMANENT" or r.account_level != 2:
            continue
        if r.category_code == "ASSET":
            balance = r.closing_debit - r.closing_credit
            asset_rows.append(BalanceSheetRow(r.full_code, r.name, r.category_code, balance))
            total_assets += balance
        elif r.category_code == "LIABILITY":
            balance = r.closing_credit - r.closing_debit
            liability_rows.append(BalanceSheetRow(r.full_code, r.name, r.category_code, balance))
            total_liabilities += balance
        elif r.category_code == "EQUITY":
            balance = r.closing_credit - r.closing_debit
            equity_rows.append(BalanceSheetRow(r.full_code, r.name, r.category_code, balance))
            total_equity += balance

    accumulated_earnings = _net_income(company_id, None, as_of_date, status_filter)
    total_equity += accumulated_earnings

    return BalanceSheetResult(
        asset_rows=asset_rows,
        liability_rows=liability_rows,
        equity_rows=equity_rows,
        total_assets=total_assets,
        total_liabilities=total_liabilities,
        total_equity=total_equity,
        accumulated_earnings=accumulated_earnings,
    )


@dataclass
class CashFlowLineRow:
    document_date: datetime.date
    temporary_no: int
    description: str
    counter_account_name: str
    receipt: decimal.Decimal
    payment: decimal.Decimal


def compute_cash_flow_direct(
    company_id: int,
    date_from: datetime.date | None,
    date_to: datetime.date | None,
    *,
    status_filter: str = "EXCLUDE_DRAFT",
    cost_center_id: int | None = None,
    document_no_filter: int | None = None,
) -> tuple[decimal.Decimal, list[CashFlowLineRow]]:
    """صورتِ گردشِ وجوهِ نقد به روشِ مستقیم — از رویِ حساب‌هایِ نیازمندِ بُعدِ
    صندوق/بانک: دریافت=بدهکار، پرداخت=بستانکار، شرح از طرفِ مقابلِ سند.
    طبقِ محدودیتِ شناخته‌شده: چون طبقه‌بندیِ عملیاتی/سرمایه‌گذاری/تامینِ
    مالی رویِ حساب‌ها وجود ندارد، روشِ غیرمستقیم پیاده نشده."""
    accounts_by_id = {a.account_id: a for a in coa_service.list_accounts(company_id)}
    with new_session() as session:
        cash_type_ids = list(
            session.scalars(
                select(DetailDimensionType.dimension_type_id).where(
                    DetailDimensionType.company_id == company_id,
                    DetailDimensionType.code.in_(
                        [dimensions_service.CASH_BOX_CODE, dimensions_service.BANK_ACCOUNT_CODE]
                    ),
                )
            ).all()
        )
        cash_account_ids = (
            set(
                session.scalars(
                    select(AccountDetailDimension.account_id).where(
                        AccountDetailDimension.dimension_type_id.in_(cash_type_ids)
                    )
                ).all()
            )
            if cash_type_ids
            else set()
        )

        opening_balance = _ZERO
        if date_from is not None and cash_account_ids:
            opening_query = (
                select(
                    func.coalesce(func.sum(JournalEntryLine.debit_amount_base), 0),
                    func.coalesce(func.sum(JournalEntryLine.credit_amount_base), 0),
                )
                .select_from(JournalEntryLine)
                .join(JournalEntry, JournalEntry.journal_entry_id == JournalEntryLine.journal_entry_id)
                .where(
                    JournalEntry.company_id == company_id,
                    JournalEntryLine.account_id.in_(cash_account_ids),
                    JournalEntry.document_date < date_from,
                )
            )
            if cost_center_id is not None:
                cc_alias = select(JournalEntryLineDetail.line_id).where(
                    JournalEntryLineDetail.detail_account_id == cost_center_id
                )
                opening_query = opening_query.where(JournalEntryLine.line_id.in_(cc_alias))
            opening_query = _apply_status_filter(opening_query, status_filter)
            od, oc = session.execute(opening_query).one()
            opening_balance = decimal.Decimal(od) - decimal.Decimal(oc)

        cash_lines: list = []
        if cash_account_ids:
            line_query = (
                select(
                    JournalEntryLine, JournalEntry.document_date, JournalEntry.temporary_no, JournalEntry.description
                )
                .join(JournalEntry, JournalEntry.journal_entry_id == JournalEntryLine.journal_entry_id)
                .where(JournalEntry.company_id == company_id, JournalEntryLine.account_id.in_(cash_account_ids))
            )
            if cost_center_id is not None:
                cc_alias = select(JournalEntryLineDetail.line_id).where(
                    JournalEntryLineDetail.detail_account_id == cost_center_id
                )
                line_query = line_query.where(JournalEntryLine.line_id.in_(cc_alias))
            if document_no_filter is not None:
                line_query = line_query.where(JournalEntry.temporary_no == document_no_filter)
            if date_from is not None:
                line_query = line_query.where(JournalEntry.document_date >= date_from)
            if date_to is not None:
                line_query = line_query.where(JournalEntry.document_date <= date_to)
            line_query = _apply_status_filter(line_query, status_filter)
            line_query = line_query.order_by(
                JournalEntry.document_date, JournalEntry.temporary_no, JournalEntryLine.line_no
            )
            cash_lines = session.execute(line_query).all()

        entry_ids = {line.journal_entry_id for line, *_ in cash_lines}
        other_lines_by_entry: dict[int, list] = {}
        if entry_ids:
            other_rows = session.scalars(
                select(JournalEntryLine).where(JournalEntryLine.journal_entry_id.in_(entry_ids))
            ).all()
            for other_line in other_rows:
                other_lines_by_entry.setdefault(other_line.journal_entry_id, []).append(other_line)

    rows: list[CashFlowLineRow] = []
    for line, document_date, temporary_no, entry_description in cash_lines:
        others = [o for o in other_lines_by_entry.get(line.journal_entry_id, []) if o.line_id != line.line_id]
        counter_names = "، ".join(
            accounts_by_id[o.account_id].name for o in others if o.account_id in accounts_by_id
        )
        rows.append(
            CashFlowLineRow(
                document_date=document_date,
                temporary_no=temporary_no,
                description=line.description or entry_description or "",
                counter_account_name=counter_names or "—",
                receipt=line.debit_amount_base,
                payment=line.credit_amount_base,
            )
        )
    return opening_balance, rows


@dataclass
class EquityChangeRow:
    full_code: str
    name: str
    opening_balance: decimal.Decimal
    increases: decimal.Decimal
    decreases: decimal.Decimal
    closing_balance: decimal.Decimal


def compute_equity_changes(
    company_id: int,
    date_from: datetime.date,
    date_to: datetime.date,
    *,
    status_filter: str = "EXCLUDE_DRAFT",
) -> list[EquityChangeRow]:
    """صورتِ تغییراتِ حقوقِ صاحبانِ سهام — حساب‌هایِ EQUITY در سطحِ کل:
    مانده‌ی اول + افزایش (گردشِ بستانکار) - کاهش (گردشِ بدهکار) = مانده‌ی آخر."""
    balances = compute_account_balances(company_id, date_from, date_to, status_filter=status_filter)
    rows: list[EquityChangeRow] = []
    for r in balances:
        if r.category_code != "EQUITY" or r.account_level != 2:
            continue
        rows.append(
            EquityChangeRow(
                full_code=r.full_code,
                name=r.name,
                opening_balance=r.opening_credit - r.opening_debit,
                increases=r.period_credit,
                decreases=r.period_debit,
                closing_balance=r.closing_credit - r.closing_debit,
            )
        )
    return rows
