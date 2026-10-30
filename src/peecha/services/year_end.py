"""R346: پایان سال مالی — بستن حساب‌های موقت، انتقال سود و زیان به سود (زیان) انباشته، سند اختتامیه و سند افتتاحیهٔ
سال بعد؛ هر چهار سند در یک تراکنش و با حفظ ماندهٔ هر تفصیلی (مشتری، تأمین‌کننده، ...).

اسناد «موقت» ساخته می‌شوند و سال قفل نمی‌شود: کاربر بررسی و قطعی می‌کند و بعد سال را می‌بندد؛ تا پیش از قطعی‌شدن،
undo_year_end همه را برمی‌گرداند. مانده‌ها بر پایهٔ همهٔ اسناد غیرپیش‌نویس (همان قاعدهٔ تراز آزمایشی) است؛ ماندهٔ ارزی
(R349) با همان ارز و مبلغ ارزی به سال بعد می‌رود و باقی‌ماندهٔ گردکردن ریالی‌اش به همان ارز نسبت داده می‌شود."""

from __future__ import annotations

import datetime
import decimal
from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import func, select

from peecha import numerals
from peecha.db.base import new_session
from peecha.db.models.accounting import (
    AccountType, ChartOfAccount, CompanyAccountingSettings, FiscalYear, JournalEntry, JournalEntryStatus,
)
from peecha.db.models.core import Company
from peecha.services import fx_revaluation, journal_entries as je_service

_ZERO = decimal.Decimal(0)
_CENT = decimal.Decimal("0.01")


def _tag(fiscal_year: FiscalYear) -> str:
    return f"پایان سال {fiscal_year.code}"


@dataclass
class YearEndPreview:
    fiscal_year_code: str
    start_date: datetime.date
    end_date: datetime.date
    next_start: datetime.date
    net_income: decimal.Decimal  # مثبت = سود
    temporary_rows: int
    permanent_rows: int
    problems: list[str] = field(default_factory=list)
    already_done: bool = False


@dataclass
class YearEndResult:
    closing_temporary_id: int | None
    transfer_id: int | None
    closing_id: int | None
    opening_id: int | None
    net_income: decimal.Decimal


def _balances(session, company_id: int, fiscal_year_id: int, exclude_tag: str | None = None) -> dict[tuple, tuple]:
    """(حساب، تفصیلی‌ها، ارز) ← (ماندهٔ ارزی، ماندهٔ ریالی)؛ بدون اسناد پایان سال، اگر exclude_tag."""
    return fx_revaluation.balances(session, company_id, fiscal_year_id, exclude_tag=exclude_tag)


def _by_account(positions: dict) -> dict[tuple[int, tuple], decimal.Decimal]:
    """ماندهٔ ریالی هر (حساب، تفصیلی‌ها) با همهٔ ارزها."""
    out: dict = defaultdict(lambda: _ZERO)
    for (account_id, details, _currency), (_fc, base) in positions.items():
        out[(account_id, details)] += base
    return {k: v for k, v in out.items() if v}


def _account_kinds(session, company_id: int) -> dict[int, str]:
    return dict(session.execute(
        select(ChartOfAccount.account_id, AccountType.code)
        .join(AccountType, AccountType.account_type_id == ChartOfAccount.account_type_id)
        .where(ChartOfAccount.company_id == company_id)).all())


def _year(session, company_id: int, fiscal_year_id: int) -> FiscalYear:
    year = session.get(FiscalYear, fiscal_year_id)
    if year is None or year.company_id != company_id:
        raise ValueError("سال مالی نامعتبر است.")
    return year


def _existing(session, company_id: int, fiscal_year: FiscalYear) -> list[JournalEntry]:
    return list(session.scalars(select(JournalEntry).where(
        JournalEntry.company_id == company_id, JournalEntry.alternative_number == _tag(fiscal_year))))


def _problems(session, company_id: int, fiscal_year: FiscalYear, settings) -> list[str]:
    problems = []
    if fiscal_year.is_closed:
        problems.append(f"سال مالی «{fiscal_year.code}» بسته است؛ برای اجرای پایان سال، ابتدا آن را باز کنید.")
    if settings is None or settings.retained_earnings_account_id is None:
        problems.append("حساب «سود (زیان) انباشته» در تنظیمات حسابداری مشخص نشده است.")
    drafts = session.scalar(select(func.count()).select_from(JournalEntry).join(
        JournalEntryStatus, JournalEntryStatus.status_id == JournalEntry.status_id).where(
        JournalEntry.company_id == company_id, JournalEntry.fiscal_year_id == fiscal_year.fiscal_year_id,
        JournalEntryStatus.code == "DRAFT"))
    if drafts:
        problems.append(f"{numerals.to_persian_digits(str(drafts))} سند پیش‌نویس در این سال مانده است؛ "
                        "ابتدا ثبت یا حذفشان کنید.")
    return problems


def preview(company_id: int, fiscal_year_id: int) -> YearEndPreview:
    with new_session() as session:
        year = _year(session, company_id, fiscal_year_id)
        settings = session.get(CompanyAccountingSettings, company_id)
        kinds = _account_kinds(session, company_id)
        balances = _by_account(_balances(session, company_id, fiscal_year_id, _tag(year)))
        temporary = {k: v for k, v in balances.items() if kinds.get(k[0]) == "TEMPORARY"}
        return YearEndPreview(
            fiscal_year_code=year.code, start_date=year.start_date, end_date=year.end_date,
            next_start=year.end_date + datetime.timedelta(days=1), net_income=-sum(temporary.values(), _ZERO),
            temporary_rows=len(temporary), permanent_rows=len(balances) - len(temporary),
            problems=_problems(session, company_id, year, settings), already_done=bool(_existing(session, company_id, year)))


def _lines_reversing(balances: dict, description: str) -> list[je_service.LineInput]:
    return [je_service.LineInput(account_id, description, -amount if amount < 0 else _ZERO, amount if amount > 0 else _ZERO,
                                 details=dict(details))
            for (account_id, details), amount in sorted(balances.items(), key=lambda kv: (kv[0][0], kv[0][1]))]


def _position_lines(positions: dict, description: str, base_currency: int, sign: int) -> tuple[list, dict[int, int]]:
    """ردیف‌های سند برای مانده‌های (حساب، تفصیلی‌ها، ارز)، با علامت sign (‎-1 برای بستن، ‎+1 برای افتتاح)؛ ماندهٔ ارزی با
    همان ارز و نرخ میانگین (ریال ÷ ارز) و باقی‌ماندهٔ گردکردن با ردیف ریالی که به همان ارز نسبت داده می‌شود."""
    lines, currencies = [], {}

    def add(account_id, details, amount, currency_id=None, rate=None, adjusts=None):
        amount *= sign
        lines.append(je_service.LineInput(account_id, description, amount if amount > 0 else _ZERO,
                                          -amount if amount < 0 else _ZERO, details=dict(details),
                                          currency_id=currency_id, exchange_rate=rate))
        if adjusts is not None:
            currencies[len(lines)] = adjusts

    for (account_id, details, currency_id), (fc, base) in sorted(positions.items(), key=lambda kv: kv[0]):
        if currency_id == base_currency:
            add(account_id, details, base)
            continue
        if fc:
            rate = abs(base / fc).quantize(decimal.Decimal("0.000001")) if base else decimal.Decimal(1)
            converted = (abs(fc) * rate).quantize(_CENT) * (1 if fc > 0 else -1)
            add(account_id, details, fc, currency_id, rate)
            base -= converted
        if base:
            add(account_id, details, base, adjusts=currency_id)
    return lines, currencies


def _line(account_id: int, description: str, amount: decimal.Decimal) -> je_service.LineInput:
    """amount مثبت = بدهکار."""
    return je_service.LineInput(account_id, description, amount if amount > 0 else _ZERO, -amount if amount < 0 else _ZERO)


def close_year(company_id: int, fiscal_year_id: int, user_id: int) -> YearEndResult:
    with new_session() as session:
        year = _year(session, company_id, fiscal_year_id)
        settings = session.get(CompanyAccountingSettings, company_id)
        problems = _problems(session, company_id, year, settings)
        if problems:
            raise ValueError(" ".join(problems))
        if _existing(session, company_id, year):
            raise ValueError("پایان این سال قبلاً اجرا شده است؛ برای اجرای دوباره، ابتدا آن را برگردانید.")
        tag, end, next_start = _tag(year), year.end_date, year.end_date + datetime.timedelta(days=1)
        retained, summary = settings.retained_earnings_account_id, settings.profit_and_loss_account_id
        kinds = _account_kinds(session, company_id)
        base_currency = session.get(Company, company_id).base_currency_id
        positions = _balances(session, company_id, fiscal_year_id)
        temporary = {k: v for k, v in _by_account(positions).items()
                     if kinds.get(k[0]) == "TEMPORARY" and k[0] not in (summary, retained)}
        permanent = {k: v for k, v in positions.items() if (k[0], k[1]) not in temporary}
        net_debit = sum(temporary.values(), _ZERO)  # مثبت یعنی زیان
        target = summary or retained
        ids = {}

        def bump(account_id: int, amount: decimal.Decimal) -> None:
            fc, base = permanent.get((account_id, (), base_currency), (_ZERO, _ZERO))
            permanent[(account_id, (), base_currency)] = (fc + amount, base + amount)

        def create(key, date, description, lines, entry_type, currencies=None):
            if lines:
                ids[key] = je_service.create_journal_entry(company_id, user_id, date, description, lines, tag,
                                                           entry_type_code=entry_type, session=session,
                                                           allow_base_on_currency_accounts=True).journal_entry_id
                fx_revaluation.register_adjustments(session, ids[key], currencies or {})

        description = f"بستن حساب‌های موقت سال {year.code}"
        create("temporary", end, description,
               _lines_reversing(temporary, description) + ([_line(target, description, net_debit)] if net_debit else []), "CLOSING")
        if net_debit:
            bump(target, net_debit)
        summary_base = permanent.get((summary, (), base_currency), (_ZERO, _ZERO))[1] if summary else _ZERO
        if summary_base:
            description = f"انتقال سود و زیان سال {year.code} به سود (زیان) انباشته"
            create("transfer", end, description,
                   [_line(summary, description, -summary_base), _line(retained, description, summary_base)], "CLOSING")
            bump(summary, -summary_base)
            bump(retained, summary_base)
        permanent = {k: v for k, v in permanent.items() if v[0] or v[1]}
        if sum((base for _fc, base in permanent.values()), _ZERO) != 0:
            raise ValueError("مانده‌های پایان سال تراز نیست؛ ابتدا اسناد نامتوازن را اصلاح کنید.")
        description = f"سند اختتامیهٔ سال {year.code}"
        lines, currencies = _position_lines(permanent, description, base_currency, -1)
        create("closing", end, description, lines, "CLOSING", currencies)
        description = f"سند افتتاحیه — انتقال مانده‌ها از سال {year.code}"
        lines, currencies = _position_lines(permanent, description, base_currency, 1)
        create("opening", next_start, description, lines, "OPENING", currencies)
        session.commit()
        return YearEndResult(ids.get("temporary"), ids.get("transfer"), ids.get("closing"), ids.get("opening"), -net_debit)


def undo_year_end(company_id: int, fiscal_year_id: int) -> int:
    """اسناد پایان سال را حذف می‌کند؛ فقط تا وقتی هیچ‌کدام قطعی نشده است."""
    with new_session() as session:
        year = _year(session, company_id, fiscal_year_id)
        entries = _existing(session, company_id, year)
        if not entries:
            raise ValueError("برای این سال سند پایان سالی وجود ندارد.")
        temporary = session.scalar(select(JournalEntryStatus.status_id).where(JournalEntryStatus.code == "TEMPORARY"))
        if any(e.status_id != temporary for e in entries):
            raise ValueError("بخشی از اسناد پایان سال قطعی شده است؛ برگرداندن فقط با سند برگشتی ممکن است.")
        ids = [e.journal_entry_id for e in entries]
    for journal_entry_id in ids:
        je_service.delete_journal_entry(journal_entry_id, company_id)
    return len(ids)


def get_settings(company_id: int) -> tuple[int | None, int | None]:
    """(حساب سود (زیان) انباشته، حساب خلاصهٔ سود و زیان)."""
    with new_session() as session:
        row = session.get(CompanyAccountingSettings, company_id)
        return (row.retained_earnings_account_id, row.profit_and_loss_account_id) if row else (None, None)


def save_settings(company_id: int, retained_earnings_account_id: int, profit_and_loss_account_id: int | None) -> None:
    if not retained_earnings_account_id:
        raise ValueError("حساب «سود (زیان) انباشته» الزامی است.")
    if retained_earnings_account_id == profit_and_loss_account_id:
        raise ValueError("حساب خلاصهٔ سود و زیان باید با حساب سود (زیان) انباشته فرق داشته باشد.")
    with new_session() as session:
        for account_id in filter(None, (retained_earnings_account_id, profit_and_loss_account_id)):
            account = session.get(ChartOfAccount, account_id)
            if account is None or account.company_id != company_id or not account.is_postable:
                raise ValueError("حساب انتخاب‌شده معتبر یا قابل ثبت سند نیست.")
        row = session.get(CompanyAccountingSettings, company_id) or CompanyAccountingSettings(company_id=company_id)
        row.retained_earnings_account_id = retained_earnings_account_id
        row.profit_and_loss_account_id = profit_and_loss_account_id
        session.add(row)
        session.commit()
