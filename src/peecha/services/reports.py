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
import statistics
from dataclasses import dataclass

import jdatetime
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
from peecha.services import statement_templates as statement_templates_service

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
    cash_flow_section_code: str | None = None
    liquidity_class_code: str | None = None


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
                cash_flow_section_code=a.cash_flow_section_code,
                liquidity_class_code=a.liquidity_class_code,
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
class CashFlowIndirectSectionRow:
    full_code: str
    name: str
    amount: decimal.Decimal


@dataclass
class CashFlowIndirectResult:
    net_income: decimal.Decimal
    operating_rows: list[CashFlowIndirectSectionRow]
    net_operating: decimal.Decimal
    investing_rows: list[CashFlowIndirectSectionRow]
    net_investing: decimal.Decimal
    financing_rows: list[CashFlowIndirectSectionRow]
    net_financing: decimal.Decimal
    net_change_in_cash: decimal.Decimal


def compute_cash_flow_indirect(
    company_id: int,
    date_from: datetime.date,
    date_to: datetime.date,
    *,
    status_filter: str = "EXCLUDE_DRAFT",
) -> CashFlowIndirectResult:
    """صورتِ گردشِ وجوهِ نقد به روشِ غیرمستقیم — از سودِ خالص شروع می‌شود و
    با تغییرِ حساب‌هایِ ترازنامه‌ایِ برچسب‌خورده با یک بخشِ وجوهِ نقد
    (acc.cash_flow_sections، از `financial_statement_mapping.py` تنظیم
    می‌شود) تعدیل می‌کند. حساب‌هایِ بدونِ برچسب (از‌جمله خودِ صندوق/بانک،
    که مبنایِ نقد است نه یک تغییرِ نقدی) نادیده گرفته می‌شوند.

    قراردادِ علامت (هرسه بخش با همین قاعده): افزایشِ بدهی/حقوقِ صاحبانِ
    سهام = ورودِ نقد (+)، افزایشِ دارایی = خروجِ نقد (-)."""
    net_income = _net_income(company_id, date_from, date_to, status_filter)
    balances = compute_account_balances(company_id, date_from, date_to, status_filter=status_filter)

    operating_rows: list[CashFlowIndirectSectionRow] = []
    investing_rows: list[CashFlowIndirectSectionRow] = []
    financing_rows: list[CashFlowIndirectSectionRow] = []
    net_operating = net_income
    net_investing = _ZERO
    net_financing = _ZERO

    for r in balances:
        if r.account_level != 2 or r.cash_flow_section_code is None:
            continue
        if r.category_code == "ASSET":
            amount = r.period_credit - r.period_debit  # افزایشِ دارایی (بدهکار) = خروجِ نقد
        elif r.category_code in ("LIABILITY", "EQUITY"):
            amount = r.period_credit - r.period_debit  # افزایشِ بدهی/سرمایه (بستانکار) = ورودِ نقد
        else:
            continue
        if amount == _ZERO:
            continue
        row = CashFlowIndirectSectionRow(full_code=r.full_code, name=r.name, amount=amount)
        if r.cash_flow_section_code == "OPERATING":
            operating_rows.append(row)
            net_operating += amount
        elif r.cash_flow_section_code == "INVESTING":
            investing_rows.append(row)
            net_investing += amount
        elif r.cash_flow_section_code == "FINANCING":
            financing_rows.append(row)
            net_financing += amount

    return CashFlowIndirectResult(
        net_income=net_income,
        operating_rows=operating_rows,
        net_operating=net_operating,
        investing_rows=investing_rows,
        net_investing=net_investing,
        financing_rows=financing_rows,
        net_financing=net_financing,
        net_change_in_cash=net_operating + net_investing + net_financing,
    )


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


@dataclass
class CustomStatementLine:
    label: str
    row_type: str  # HEADER | ACCOUNTS | FORMULA
    indent_level: int
    is_bold: bool
    amount: decimal.Decimal | None  # None فقط برایِ HEADER


def compute_custom_statement(
    template_id: int,
    company_id: int,
    date_from: datetime.date | None,
    date_to: datetime.date,
    *,
    status_filter: str = "EXCLUDE_DRAFT",
) -> list[CustomStatementLine]:
    """گزارشِ سفارشی (طراحِ گزارش، فازِ ۲) — هر ردیفِ ACCOUNTS از جمعِ
    چند حسابِ دلخواه (هر سطحی: گروه/کل/معین، با علامتِ +/−) ساخته می‌شود؛
    مانده/گردشِ هر حساب از `compute_account_balances` می‌آید که خودش برایِ
    همه‌یِ سطوح رول‌آپ‌شده است، پس نیازی به کوئریِ تازه نیست. حسابِ
    PERMANENT (ترازنامه‌ای) → مانده‌یِ تجمعی تا date_to؛ TEMPORARY (موقت) →
    گردشِ همان دوره — دقیقاً همان قراردادِ compute_balance_sheet/
    compute_income_statement. هر ردیفِ FORMULA از جمعِ چند ردیفِ دیگرِ
    همین الگو ساخته می‌شود؛ حلِ بازگشتی+memo باعث می‌شود ترتیبِ row_order
    برایِ محاسبه مهم نباشد (فقط برایِ نمایش) و حلقه‌هایِ فرمولی با
    ValueError روشن رد شوند، نه کرش/بازگشتِ بی‌نهایت."""
    rows = statement_templates_service.list_rows(template_id)
    rows_by_id = {r.row_id: r for r in rows}
    balances_by_id = {
        b.account_id: b
        for b in compute_account_balances(company_id, date_from, date_to, status_filter=status_filter)
    }

    memo: dict[int, decimal.Decimal | None] = {}
    resolving: set[int] = set()

    def resolve(row_id: int) -> decimal.Decimal | None:
        if row_id in memo:
            return memo[row_id]
        if row_id in resolving:
            raise ValueError("حلقه در فرمولِ ردیف‌هایِ الگویِ گزارش.")
        resolving.add(row_id)
        row = rows_by_id[row_id]
        if row.row_type == "ACCOUNTS":
            total = _ZERO
            for account_id, sign in row.account_refs:
                b = balances_by_id.get(account_id)
                if b is None:
                    continue
                value = (
                    (b.closing_debit - b.closing_credit)
                    if b.account_type_code == "PERMANENT"
                    else (b.period_debit - b.period_credit)
                )
                total += sign * value
        elif row.row_type == "FORMULA":
            total = _ZERO
            for ref_row_id, sign in row.formula_refs:
                ref_value = resolve(ref_row_id)
                total += sign * (ref_value if ref_value is not None else _ZERO)
        else:  # HEADER
            total = None
        resolving.discard(row_id)
        memo[row_id] = total
        return total

    return [
        CustomStatementLine(
            label=r.label,
            row_type=r.row_type,
            indent_level=r.indent_level,
            is_bold=r.is_bold,
            amount=resolve(r.row_id) if r.row_type != "HEADER" else None,
        )
        for r in rows
    ]


@dataclass
class FinancialRatioRow:
    label: str
    value: decimal.Decimal | None  # None = غیرِقابلِ‌محاسبه (مخرج صفر)
    kind: str  # PERCENTAGE | RATIO | CURRENCY


def _safe_div(numerator: decimal.Decimal, denominator: decimal.Decimal) -> decimal.Decimal | None:
    return (numerator / denominator) if denominator else None


def _liquidity_totals(
    company_id: int, date_to: datetime.date, status_filter: str
) -> tuple[decimal.Decimal, decimal.Decimal, decimal.Decimal]:
    """دارایی‌هایِ جاری، سهمِ موجودی از آن‌ها، و بدهی‌هایِ جاری — از رویِ
    liquidity_class_code که در «نگاشتِ صورت‌هایِ مالی»/کدینگِ حسابداری
    تنظیم می‌شود (CURRENT/CURRENT_INVENTORY برایِ دارایی، CURRENT برایِ
    بدهی؛ NULL یعنی در نسبتِ جاری/آنی دیده نمی‌شود)."""
    balances = compute_account_balances(company_id, None, date_to, status_filter=status_filter)
    current_assets = _ZERO
    inventory_assets = _ZERO
    current_liabilities = _ZERO
    for r in balances:
        if r.account_level != 2:
            continue
        if r.category_code == "ASSET" and r.liquidity_class_code in ("CURRENT", "CURRENT_INVENTORY"):
            amount = r.closing_debit - r.closing_credit
            current_assets += amount
            if r.liquidity_class_code == "CURRENT_INVENTORY":
                inventory_assets += amount
        elif r.category_code == "LIABILITY" and r.liquidity_class_code == "CURRENT":
            current_liabilities += r.closing_credit - r.closing_debit
    return current_assets, inventory_assets, current_liabilities


def compute_financial_ratios(
    company_id: int,
    date_from: datetime.date,
    date_to: datetime.date,
    *,
    status_filter: str = "EXCLUDE_DRAFT",
) -> list[FinancialRatioRow]:
    """نسبت‌هایِ سودآوری/اهرمی/نقدینگی — رویِ compute_balance_sheet/
    compute_income_statement موجود سوار می‌شود. نسبت‌هایِ نقدینگی (جاری/
    آنی) فقط برایِ حساب‌هایی محاسبه می‌شوند که liquidity_class_code‌شان
    در کدینگِ حسابداری/نگاشتِ صورت‌هایِ مالی تنظیم شده باشد — اگر هیچ
    حسابی طبقه‌بندی نشده باشد، این دو نسبت None برمی‌گردند (نه صفرِ
    گمراه‌کننده)."""
    bs = compute_balance_sheet(company_id, date_to, status_filter=status_filter)
    inc = compute_income_statement(company_id, date_from, date_to, status_filter=status_filter)
    current_assets, inventory_assets, current_liabilities = _liquidity_totals(company_id, date_to, status_filter)
    quick_assets = current_assets - inventory_assets
    return [
        FinancialRatioRow("حاشیه‌یِ سودِ خالص", _safe_div(inc.net_income, inc.total_revenue), "PERCENTAGE"),
        FinancialRatioRow("بازده‌یِ دارایی‌ها (ROA)", _safe_div(inc.net_income, bs.total_assets), "PERCENTAGE"),
        FinancialRatioRow(
            "بازده‌یِ حقوقِ صاحبانِ سهام (ROE)", _safe_div(inc.net_income, bs.total_equity), "PERCENTAGE"
        ),
        FinancialRatioRow("نسبتِ بدهی", _safe_div(bs.total_liabilities, bs.total_assets), "PERCENTAGE"),
        FinancialRatioRow(
            "نسبتِ بدهی به حقوقِ صاحبانِ سهام", _safe_div(bs.total_liabilities, bs.total_equity), "RATIO"
        ),
        FinancialRatioRow("نسبتِ مالکانه", _safe_div(bs.total_equity, bs.total_assets), "PERCENTAGE"),
        FinancialRatioRow("نسبتِ جاری", _safe_div(current_assets, current_liabilities), "RATIO"),
        FinancialRatioRow("نسبتِ آنی", _safe_div(quick_assets, current_liabilities), "RATIO"),
        FinancialRatioRow("سرمایه‌یِ در گردش", current_assets - current_liabilities, "CURRENCY"),
    ]


_JALALI_MONTH_NAMES = [
    "فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
    "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند",
]


def _jalali_period_label(year: int, month: int, granularity: str) -> str:
    if granularity == "YEARLY":
        return str(year)
    if granularity == "QUARTERLY":
        quarter = (month - 1) // 3 + 1
        return f"فصلِ {quarter} {year}"
    return f"{_JALALI_MONTH_NAMES[month - 1]} {year}"


def generate_jalali_periods(
    end_date: datetime.date, granularity: str, count: int
) -> list[tuple[datetime.date, datetime.date, str]]:
    """`count` دوره‌یِ متوالیِ جلالی (ماهانه/فصلی/سالانه) که به دوره‌یِ
    شاملِ end_date ختم می‌شوند؛ قدیمی‌ترین دوره اول. هر دوره یک تاپلِ
    (تاریخِ میلادیِ شروع، تاریخِ میلادیِ پایان، برچسبِ فارسی) است."""
    step = {"MONTHLY": 1, "QUARTERLY": 3, "YEARLY": 12}[granularity]
    end_jalali = jdatetime.date.fromgregorian(date=end_date)

    if granularity == "YEARLY":
        anchor_total = end_jalali.year * 12
    elif granularity == "QUARTERLY":
        quarter_start_month = (end_jalali.month - 1) // 3 * 3 + 1
        anchor_total = end_jalali.year * 12 + (quarter_start_month - 1)
    else:
        anchor_total = end_jalali.year * 12 + (end_jalali.month - 1)

    periods: list[tuple[datetime.date, datetime.date, str]] = []
    for i in range(count):
        start_total = anchor_total - i * step
        start_year, start_month0 = divmod(start_total, 12)
        start_month = start_month0 + 1
        start = jdatetime.date(start_year, start_month, 1)

        end_total = start_total + step
        end_year, end_month0 = divmod(end_total, 12)
        end_month = end_month0 + 1
        end = jdatetime.date(end_year, end_month, 1) - datetime.timedelta(days=1)

        label = _jalali_period_label(start_year, start_month, granularity)
        periods.append((start.togregorian(), end.togregorian(), label))

    periods.reverse()
    return periods


@dataclass
class PeriodComparisonRow:
    full_code: str
    name: str
    category_code: str  # REVENUE | EXPENSE
    amounts: list[decimal.Decimal]


@dataclass
class PeriodComparisonResult:
    period_labels: list[str]
    rows: list[PeriodComparisonRow]
    net_income_by_period: list[decimal.Decimal]


def compute_period_comparison(
    company_id: int,
    periods: list[tuple[datetime.date, datetime.date, str]],
    *,
    status_filter: str = "EXCLUDE_DRAFT",
) -> PeriodComparisonResult:
    """مقایسه‌یِ دوره‌ای (ماه‌به‌ماه/فصل‌به‌فصل/سال‌به‌سال) — برایِ هر دوره،
    مانده/گردشِ حساب‌هایِ REVENUE/EXPENSهِ سطحِ ۱ را رول‌آپ‌شده می‌گیرد
    (هم‌الگو با compute_income_statement)."""
    balances_by_period = [
        compute_account_balances(company_id, date_from, date_to, status_filter=status_filter)
        for date_from, date_to, _label in periods
    ]

    sample_by_account: dict[int, AccountBalanceRow] = {}
    for balances in balances_by_period:
        for r in balances:
            if r.category_code in ("REVENUE", "EXPENSE") and r.account_level == 1:
                sample_by_account.setdefault(r.account_id, r)

    rows: list[PeriodComparisonRow] = []
    for account_id, sample in sorted(sample_by_account.items(), key=lambda kv: kv[1].full_code):
        amounts: list[decimal.Decimal] = []
        for balances in balances_by_period:
            r = next((b for b in balances if b.account_id == account_id), None)
            if r is None:
                amounts.append(_ZERO)
                continue
            if sample.category_code == "REVENUE":
                amounts.append(r.period_credit - r.period_debit)
            else:
                amounts.append(r.period_debit - r.period_credit)
        rows.append(PeriodComparisonRow(sample.full_code, sample.name, sample.category_code, amounts))

    net_income_by_period = [
        _net_income(company_id, date_from, date_to, status_filter) for date_from, date_to, _label in periods
    ]

    return PeriodComparisonResult(
        period_labels=[label for _f, _t, label in periods],
        rows=rows,
        net_income_by_period=net_income_by_period,
    )


@dataclass
class AnomalyRow:
    kind_label: str
    document_date: datetime.date | None
    temporary_no: int | None
    description: str
    detail: str


def _stale_draft_anomalies(
    session, company_id: int, date_from: datetime.date | None, date_to: datetime.date | None, stale_draft_days: int
) -> list[AnomalyRow]:
    now = datetime.datetime.now(datetime.timezone.utc)
    cutoff = now - datetime.timedelta(days=stale_draft_days)
    query = (
        select(JournalEntry)
        .join(JournalEntryStatus, JournalEntryStatus.status_id == JournalEntry.status_id)
        .where(
            JournalEntry.company_id == company_id,
            JournalEntryStatus.code == "DRAFT",
            JournalEntry.created_at <= cutoff,
        )
    )
    if date_from is not None:
        query = query.where(JournalEntry.document_date >= date_from)
    if date_to is not None:
        query = query.where(JournalEntry.document_date <= date_to)
    rows: list[AnomalyRow] = []
    for entry in session.scalars(query).all():
        age_days = (now - entry.created_at).days
        rows.append(
            AnomalyRow(
                kind_label="اسنادِ موقتِ معوق",
                document_date=entry.document_date,
                temporary_no=entry.temporary_no,
                description=entry.description or "—",
                detail=f"{age_days} روز در وضعیتِ پیش‌نویس مانده است.",
            )
        )
    return rows


def _entries_in_range(session, company_id: int, date_from: datetime.date | None, date_to: datetime.date | None):
    query = select(JournalEntry).where(JournalEntry.company_id == company_id)
    if date_from is not None:
        query = query.where(JournalEntry.document_date >= date_from)
    if date_to is not None:
        query = query.where(JournalEntry.document_date <= date_to)
    return session.scalars(query).all()


def _missing_description_anomalies(
    session, company_id: int, date_from: datetime.date | None, date_to: datetime.date | None
) -> list[AnomalyRow]:
    entries = [e for e in _entries_in_range(session, company_id, date_from, date_to) if not e.description]
    if not entries:
        return []
    entry_ids = [e.journal_entry_id for e in entries]
    lines = session.scalars(select(JournalEntryLine).where(JournalEntryLine.journal_entry_id.in_(entry_ids))).all()
    entries_with_line_desc = {line.journal_entry_id for line in lines if line.description}
    rows: list[AnomalyRow] = []
    for entry in entries:
        if entry.journal_entry_id in entries_with_line_desc:
            continue
        rows.append(
            AnomalyRow(
                kind_label="سندهایِ بدونِ شرح",
                document_date=entry.document_date,
                temporary_no=entry.temporary_no,
                description="—",
                detail="نه سند و نه هیچ‌کدام از سطرهایش شرح دارند.",
            )
        )
    return rows


def _possible_duplicate_anomalies(
    session, company_id: int, date_from: datetime.date | None, date_to: datetime.date | None
) -> list[AnomalyRow]:
    entries = _entries_in_range(session, company_id, date_from, date_to)
    if not entries:
        return []
    entry_ids = [e.journal_entry_id for e in entries]
    lines = session.scalars(select(JournalEntryLine).where(JournalEntryLine.journal_entry_id.in_(entry_ids))).all()
    lines_by_entry: dict[int, list] = {}
    for line in lines:
        lines_by_entry.setdefault(line.journal_entry_id, []).append(line)

    groups: dict[tuple, list] = {}
    for entry in entries:
        entry_lines = lines_by_entry.get(entry.journal_entry_id, [])
        total_debit = sum((line.debit_amount_base for line in entry_lines), _ZERO)
        account_ids = frozenset(line.account_id for line in entry_lines)
        key = (entry.document_date, total_debit, account_ids)
        groups.setdefault(key, []).append(entry)

    rows: list[AnomalyRow] = []
    for group_entries in groups.values():
        if len(group_entries) < 2:
            continue
        numbers = "، ".join(str(e.temporary_no) for e in group_entries)
        for entry in group_entries:
            rows.append(
                AnomalyRow(
                    kind_label="احتمالِ سندِ تکراری",
                    document_date=entry.document_date,
                    temporary_no=entry.temporary_no,
                    description=entry.description or "—",
                    detail=f"با شماره‌هایِ {numbers} هم‌تاریخ، هم‌مبلغ و هم‌حساب است.",
                )
            )
    return rows


def _outlier_transaction_anomalies(
    session,
    company_id: int,
    date_from: datetime.date | None,
    date_to: datetime.date | None,
    outlier_z: float,
) -> list[AnomalyRow]:
    query = (
        select(JournalEntryLine, JournalEntry.document_date, JournalEntry.temporary_no, JournalEntry.description)
        .join(JournalEntry, JournalEntry.journal_entry_id == JournalEntryLine.journal_entry_id)
        .where(JournalEntry.company_id == company_id)
    )
    if date_from is not None:
        query = query.where(JournalEntry.document_date >= date_from)
    if date_to is not None:
        query = query.where(JournalEntry.document_date <= date_to)
    line_rows = session.execute(query).all()

    # به‌ازایِ هر حساب، لیستِ (ردیفِ خام، مبلغ) را نگه می‌داریم — نه فقط
    # مبلغ‌ها — چون آمارِ هر تراکنش باید leave-one-out باشد (میانگین/
    # انحرافِ‌معیارِ *بقیه‌یِ* تراکنش‌هایِ همان حساب، نه شاملِ خودش)؛ وگرنه
    # خودِ مبلغِ پرت آن‌قدر انحرافِ‌معیار را بالا می‌برد که دیگر پرت به‌نظر
    # نمی‌رسد (باگی که در تستِ واقعی پیدا شد: یک تراکنشِ ۵۰۰۰۰تایی میانِ
    # ۵ تراکنشِ ~۱۰۰تایی، وقتی خودش هم در میانگین/انحراف حساب می‌شد،
    # اصلاً تشخیص داده نمی‌شد).
    entries_by_account: dict[int, list[tuple]] = {}
    for row in line_rows:
        line = row[0]
        amount = line.debit_amount_base or line.credit_amount_base
        if amount:
            entries_by_account.setdefault(line.account_id, []).append((row, amount))

    accounts_by_id = {a.account_id: a for a in coa_service.list_accounts(company_id)}
    rows: list[AnomalyRow] = []
    for account_id, entries in entries_by_account.items():
        if len(entries) < 5:
            continue
        amounts_float = [float(a) for _row, a in entries]
        for idx, (row, amount) in enumerate(entries):
            others = amounts_float[:idx] + amounts_float[idx + 1 :]
            mean = statistics.mean(others)
            stdev = statistics.pstdev(others)
            if stdev == 0 or float(amount) <= mean + outlier_z * stdev:
                continue
            line, document_date, temporary_no, entry_description = row
            account = accounts_by_id.get(account_id)
            rows.append(
                AnomalyRow(
                    kind_label="تراکنشِ نامتعارف",
                    document_date=document_date,
                    temporary_no=temporary_no,
                    description=line.description or entry_description or "—",
                    detail=(
                        f"مبلغِ {amount:,.0f} برایِ حسابِ «{account.name if account else ''}» نسبت به میانگینِ "
                        f"سایرِ تراکنش‌هایِ آن حساب ({mean:,.0f}) بسیار بزرگ است."
                    ),
                )
            )
    return rows


def detect_document_anomalies(
    company_id: int,
    date_from: datetime.date | None,
    date_to: datetime.date | None,
    *,
    stale_draft_days: int = 7,
    detect_outliers: bool = True,
    outlier_z: float = 3.0,
) -> list[AnomalyRow]:
    """چهار بررسیِ مشخص و صادقانه (نه یک «موتورِ AI مبهم»): اسنادِ موقتِ
    معوق، سندهایِ بدونِ شرح، احتمالِ سندِ تکراری، تراکنشِ نامتعارفِ آماری.
    عمداً بدونِ status_filter — این چک‌ها ذاتاً رویِ همه‌یِ وضعیت‌ها کار
    می‌کنند (چکِ اول دقیقاً هدفش خودِ پیش‌نویس‌هاست)."""
    with new_session() as session:
        rows: list[AnomalyRow] = []
        rows.extend(_stale_draft_anomalies(session, company_id, date_from, date_to, stale_draft_days))
        rows.extend(_missing_description_anomalies(session, company_id, date_from, date_to))
        rows.extend(_possible_duplicate_anomalies(session, company_id, date_from, date_to))
        if detect_outliers:
            rows.extend(_outlier_transaction_anomalies(session, company_id, date_from, date_to, outlier_z))
    return rows
