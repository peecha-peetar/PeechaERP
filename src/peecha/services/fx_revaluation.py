"""R349: تسعیر ارز — ماندهٔ ارزی هر (حساب دائم، تفصیلی‌ها، ارز) در تاریخ تسعیر با نرخ همان روز به ریال برگردانده و
تفاوتش به حساب سود یا زیان تسعیر برده می‌شود.

ماندهٔ ریالی یک ارز = ریال ردیف‌های همان ارز + ردیف‌های ریالی اصلاح ثبت‌شده برای همان ارز (acc.fx_position_adjustments:
تسعیرهای قبلی و گردکردن انتقال سال). پس تسعیر دوباره فقط تفاوت جدید را ثبت می‌کند و ماندهٔ صفرشدهٔ ارزی (تسویه با نرخ
دیگر) هم بسته می‌شود. سند «موقت» است و تا پیش از قطعی‌شدن برمی‌گردد."""

from __future__ import annotations

import datetime
import decimal
from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import func, select

from peecha import numerals
from peecha.db.base import new_session
from peecha.db.models.accounting import (
    AccountType, ChartOfAccount, CompanyAccountingSettings, DetailAccount, FiscalYear, FxPositionAdjustment, FxRevaluation,
    JournalEntry, JournalEntryLine, JournalEntryLineDetail, JournalEntryStatus,
)
from peecha.db.models.core import Company, Currency
from peecha.services import chart_of_accounts as coa_service, currencies as currencies_service
from peecha.services import journal_entries as je_service

_ZERO = decimal.Decimal(0)
_CENT = decimal.Decimal("0.01")
Key = tuple  # (account_id, ((dimension_type_id, detail_account_id), ...), currency_id)


def balances(session, company_id: int, fiscal_year_id: int, *, as_of: datetime.date | None = None,
             exclude_tag: str | None = None) -> dict[Key, tuple[decimal.Decimal, decimal.Decimal]]:
    """(حساب، تفصیلی‌ها، ارز) ← (ماندهٔ ارزی، ماندهٔ ریالی)، از اسناد غیرپیش‌نویس سال؛ ارز پایه هم یک ارز است."""
    draft = select(JournalEntryStatus.status_id).where(JournalEntryStatus.code == "DRAFT").scalar_subquery()
    query = (select(JournalEntryLine.line_id, JournalEntryLine.account_id, JournalEntryLine.currency_id,
                    func.coalesce(JournalEntryLine.debit_amount_fc, 0) - func.coalesce(JournalEntryLine.credit_amount_fc, 0),
                    func.coalesce(JournalEntryLine.debit_amount_base, 0) - func.coalesce(JournalEntryLine.credit_amount_base, 0))
             .join(JournalEntry, JournalEntry.journal_entry_id == JournalEntryLine.journal_entry_id)
             .where(JournalEntry.company_id == company_id, JournalEntry.fiscal_year_id == fiscal_year_id,
                    JournalEntry.status_id != draft))
    if as_of is not None:
        query = query.where(JournalEntry.document_date <= as_of)
    if exclude_tag is not None:
        query = query.where(JournalEntry.alternative_number.is_distinct_from(exclude_tag))
    rows = session.execute(query).all()
    details: dict[int, list] = defaultdict(list)
    adjusted: dict[int, int] = {}
    line_ids = [r[0] for r in rows]
    for start in range(0, len(line_ids), 5000):
        chunk = line_ids[start:start + 5000]
        for line_id, dim, detail in session.execute(
                select(JournalEntryLineDetail.line_id, JournalEntryLineDetail.dimension_type_id,
                       JournalEntryLineDetail.detail_account_id).where(JournalEntryLineDetail.line_id.in_(chunk))):
            details[line_id].append((dim, detail))
        adjusted.update(session.execute(select(FxPositionAdjustment.line_id, FxPositionAdjustment.currency_id)
                                        .where(FxPositionAdjustment.line_id.in_(chunk))).all())
    out: dict[Key, list] = defaultdict(lambda: [_ZERO, _ZERO])
    for line_id, account_id, currency_id, fc, base in rows:
        key = (account_id, tuple(sorted(details.get(line_id, ()))), adjusted.get(line_id, currency_id))
        out[key][0] += decimal.Decimal(fc) if line_id not in adjusted else _ZERO
        out[key][1] += decimal.Decimal(base)
    return {k: (v[0], v[1]) for k, v in out.items() if v[0] or v[1]}


def register_adjustments(session, journal_entry_id: int, currencies_by_line_no: dict[int, int]) -> None:
    """ردیف‌های ریالی سند را به ارزی که اصلاح می‌کنند نسبت می‌دهد (line_no ← currency_id)."""
    if not currencies_by_line_no:
        return
    for line_id, line_no in session.execute(select(JournalEntryLine.line_id, JournalEntryLine.line_no).where(
            JournalEntryLine.journal_entry_id == journal_entry_id)):
        if line_no in currencies_by_line_no:
            session.add(FxPositionAdjustment(line_id=line_id, currency_id=currencies_by_line_no[line_no]))


def _base_currency(session, company_id: int) -> int:
    return session.get(Company, company_id).base_currency_id


@dataclass
class PositionRow:
    account_id: int
    account_label: str
    details: tuple
    currency_id: int
    currency_code: str
    fc_balance: decimal.Decimal
    base_before: decimal.Decimal
    rate: decimal.Decimal | None
    base_after: decimal.Decimal | None
    difference: decimal.Decimal | None
    details_label: str = ""


@dataclass
class Preview:
    fiscal_year_id: int
    rows: list[PositionRow] = field(default_factory=list)
    rates: dict[int, decimal.Decimal] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)

    @property
    def gain(self) -> decimal.Decimal:
        return sum((r.difference for r in self.rows if r.difference and r.difference > 0), _ZERO)

    @property
    def loss(self) -> decimal.Decimal:
        return -sum((r.difference for r in self.rows if r.difference and r.difference < 0), _ZERO)


def _year_of(session, company_id: int, as_of: datetime.date) -> FiscalYear:
    year = session.scalar(select(FiscalYear).where(FiscalYear.company_id == company_id, FiscalYear.start_date <= as_of,
                                                   FiscalYear.end_date >= as_of))
    if year is None:
        raise ValueError("برای این تاریخ سال مالی تعریف نشده است.")
    return year


def preview(company_id: int, as_of: datetime.date, rates: dict[int, decimal.Decimal] | None = None) -> Preview:
    """مانده‌های ارزی حساب‌های دائم و تفاوت تسعیرشان؛ rates نرخ‌های واردشده (بقیه از آخرین نرخ ثبت‌شده)."""
    chosen = {k: decimal.Decimal(v) for k, v in (rates or {}).items() if v}
    with new_session() as session:
        year = _year_of(session, company_id, as_of)
        base_currency = _base_currency(session, company_id)
        labels = {a.account_id: f"{a.full_code} — {a.name}" for a in coa_service.list_postable_accounts(company_id)}
        permanent = {account_id: labels.get(account_id, "") for account_id in session.scalars(
            select(ChartOfAccount.account_id).join(AccountType, AccountType.account_type_id == ChartOfAccount.account_type_id)
            .where(ChartOfAccount.company_id == company_id, AccountType.code == "PERMANENT"))}
        codes = dict(session.execute(select(Currency.currency_id, Currency.iso_code)).all())
        result = Preview(year.fiscal_year_id)
        for (account_id, details, currency_id), (fc, base) in sorted(
                balances(session, company_id, year.fiscal_year_id, as_of=as_of).items(), key=lambda kv: kv[0]):
            if currency_id == base_currency or account_id not in permanent:
                continue
            if currency_id not in chosen:
                chosen[currency_id] = currencies_service.get_latest_rate(company_id, currency_id, as_of)
            rate = chosen[currency_id]
            after = (fc * rate).quantize(_CENT) if rate else None
            result.rows.append(PositionRow(account_id, permanent[account_id], details, currency_id, codes.get(currency_id, ""),
                                           fc, base, rate, after, (after - base) if after is not None else None))
        detail_ids = {detail for r in result.rows for _dim, detail in r.details}
        names = dict(session.execute(select(DetailAccount.detail_account_id, DetailAccount.name).where(
            DetailAccount.detail_account_id.in_(detail_ids))).all()) if detail_ids else {}
        for r in result.rows:
            r.details_label = "، ".join(names.get(detail) or "" for _dim, detail in r.details)
        result.rates = {r.currency_id: r.rate for r in result.rows if r.rate}
        missing = sorted({r.currency_code for r in result.rows if r.rate is None})
        if missing:
            result.problems.append(f"نرخ ارز {'، '.join(missing)} برای این تاریخ ثبت نشده است.")
        settings = session.get(CompanyAccountingSettings, company_id)
        if result.gain and (settings is None or settings.fx_gain_account_id is None):
            result.problems.append("حساب سود تسعیر ارز مشخص نشده است.")
        if result.loss and (settings is None or settings.fx_loss_account_id is None):
            result.problems.append("حساب زیان تسعیر ارز مشخص نشده است.")
        return result


def run(company_id: int, as_of: datetime.date, user_id: int, rates: dict[int, decimal.Decimal] | None = None,
        account_ids: set[int] | None = None) -> int | None:
    """سند تسعیر را می‌سازد و شناسهٔ آن را برمی‌گرداند؛ None یعنی تفاوتی نبود. account_ids: فقط این حساب‌ها."""
    info = preview(company_id, as_of, rates)
    if info.problems:
        raise ValueError(" ".join(info.problems))
    rows = [r for r in info.rows if r.difference and (account_ids is None or r.account_id in account_ids)]
    if not rows:
        return None
    with new_session() as session:
        if session.scalar(select(FxRevaluation.revaluation_id).where(
                FxRevaluation.company_id == company_id, FxRevaluation.revaluation_date == as_of)):
            raise ValueError("برای این تاریخ قبلاً تسعیر انجام شده است؛ برای اجرای دوباره، ابتدا آن را برگردانید.")
        settings = session.get(CompanyAccountingSettings, company_id)
        description = f"تسعیر ارز {numerals.format_jalali_date(as_of)}"
        lines, currencies = [], {}
        for index, row in enumerate(rows, start=1):
            amount = row.difference
            lines.append(je_service.LineInput(row.account_id, f"{description} — {row.currency_code}",
                                              amount if amount > 0 else _ZERO, -amount if amount < 0 else _ZERO,
                                              details=dict(row.details)))
            currencies[index] = row.currency_id
        gain = sum((r.difference for r in rows if r.difference > 0), _ZERO)
        loss = -sum((r.difference for r in rows if r.difference < 0), _ZERO)
        if gain:
            lines.append(je_service.LineInput(settings.fx_gain_account_id, description, _ZERO, gain))
        if loss:
            lines.append(je_service.LineInput(settings.fx_loss_account_id, description, loss, _ZERO))
        entry = je_service.create_journal_entry(company_id, user_id, as_of, description, lines, entry_type_code="ADJUSTING",
                                                session=session, allow_base_on_currency_accounts=True)
        register_adjustments(session, entry.journal_entry_id, currencies)
        session.add(FxRevaluation(company_id=company_id, revaluation_date=as_of, journal_entry_id=entry.journal_entry_id,
                                  rates={str(r.currency_id): str(r.rate) for r in rows}, created_by_user_id=user_id))
        session.commit()
        return entry.journal_entry_id


@dataclass
class RevaluationRow:
    revaluation_id: int
    revaluation_date: datetime.date
    journal_entry_id: int
    temporary_no: int
    status_code: str
    rates: dict


def list_revaluations(company_id: int) -> list[RevaluationRow]:
    with new_session() as session:
        rows = session.execute(
            select(FxRevaluation, JournalEntry.temporary_no, JournalEntryStatus.code)
            .join(JournalEntry, JournalEntry.journal_entry_id == FxRevaluation.journal_entry_id)
            .join(JournalEntryStatus, JournalEntryStatus.status_id == JournalEntry.status_id)
            .where(FxRevaluation.company_id == company_id).order_by(FxRevaluation.revaluation_date.desc())).all()
        return [RevaluationRow(r.revaluation_id, r.revaluation_date, r.journal_entry_id, no, status, dict(r.rates))
                for r, no, status in rows]


def undo(revaluation_id: int, company_id: int) -> None:
    """سند تسعیر را حذف می‌کند (ردیف‌های اصلاح و سابقهٔ تسعیر هم با آن پاک می‌شوند)؛ فقط پیش از قطعی‌شدن."""
    with new_session() as session:
        row = session.get(FxRevaluation, revaluation_id)
        if row is None or row.company_id != company_id:
            raise ValueError("تسعیر یافت نشد.")
        status = session.scalar(select(JournalEntryStatus.code).join(
            JournalEntry, JournalEntry.status_id == JournalEntryStatus.status_id).where(
            JournalEntry.journal_entry_id == row.journal_entry_id))
        if status != "TEMPORARY":
            raise ValueError("سند تسعیر قطعی شده است؛ برگرداندن فقط با سند برگشتی ممکن است.")
        journal_entry_id = row.journal_entry_id
    je_service.delete_journal_entry(journal_entry_id, company_id)


def get_accounts(company_id: int) -> tuple[int | None, int | None]:
    """(حساب سود تسعیر، حساب زیان تسعیر)."""
    with new_session() as session:
        row = session.get(CompanyAccountingSettings, company_id)
        return (row.fx_gain_account_id, row.fx_loss_account_id) if row else (None, None)


def save_accounts(company_id: int, gain_account_id: int | None, loss_account_id: int | None) -> None:
    with new_session() as session:
        for account_id in filter(None, (gain_account_id, loss_account_id)):
            account = session.get(ChartOfAccount, account_id)
            if account is None or account.company_id != company_id or not account.is_postable:
                raise ValueError("حساب انتخاب‌شده معتبر یا قابل ثبت سند نیست.")
        row = session.get(CompanyAccountingSettings, company_id) or CompanyAccountingSettings(company_id=company_id)
        row.fx_gain_account_id, row.fx_loss_account_id = gain_account_id, loss_account_id
        session.add(row)
        session.commit()
