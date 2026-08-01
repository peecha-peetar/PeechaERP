"""سرویس صدور سند حسابداری (دفتر روزنامه).

هر سند در این مرحله با شماره‌ی موقت (temporary_no) و وضعیت TEMPORARY ثبت
می‌شود؛ تخصیص شماره‌ی دائم (permanent_no) طبق طراحی دیتابیس فقط از طریق
approve_journal_entry انجام می‌شود — یا مستقیم (بدونِ گردشِ کارِ تعریف‌شده)
یا از طریقِ کارتابل (services/cartable.py؛ در پایینِ همین فایل به‌عنوانِ
handlerِ form_code="journal_entry" ثبت‌نام شده) — و بعد از آن دیگر قابل
تغییر نیست (تریگر tr_journal_entries_prevent_permanent_no_change).

سال مالی هم به‌صورت خودکار از روی fiscal_year_start_month/day شرکت و
تاریخِ سند محاسبه و در صورت نبود ساخته می‌شود — چون هنوز صفحه‌ی مدیریت سال
مالی وجود ندارد و بدون آن هیچ سندی قابل ثبت نیست.
"""

from __future__ import annotations

import datetime
import decimal
from dataclasses import dataclass, field

import jdatetime
from sqlalchemy import func, select

from peecha import numerals
from peecha.db.base import new_session
from peecha.db.models.accounting import (
    AccountDetailDimension,
    AccountPersonGroup,
    ChartOfAccount,
    DetailAccount,
    FiscalPeriod,
    FiscalYear,
    JournalEntry,
    JournalEntryLine,
    JournalEntryLineDetail,
    JournalEntryStatus,
    JournalEntryType,
)
from peecha.db.models.core import Company, CompanyCurrency
from peecha.db.models.security import User
from peecha.services import audit as audit_service
from peecha.services import detail_dimensions as dimensions_service

_BASE_QUANT = decimal.Decimal("0.01")


def company_has_any_entries(company_id: int) -> bool:
    """آیا این شرکت حتی یک سند ثبت‌شده دارد — برایِ قفل‌کردنِ تنظیماتِ
    کدینگ (تعدادِ رقم/بازه‌ی حساب‌ها و گروه‌هایِ تفصیلی) بعدِ اولین سند،
    طبقِ درخواستِ صریح."""
    with new_session() as session:
        return (
            session.scalar(
                select(func.count()).select_from(JournalEntry).where(JournalEntry.company_id == company_id)
            )
            > 0
        )


def _lines_snapshot(lines) -> list[dict]:
    """نسخه‌ی قابلِ‌سریالایز (JSON) از ردیف‌های سند — برایِ ردِ حسابرسی."""
    return [
        {
            "account_id": ln.account_id,
            "description": ln.description,
            "debit": str(ln.debit),
            "credit": str(ln.credit),
            "currency_id": ln.currency_id,
            "exchange_rate": str(ln.exchange_rate) if ln.exchange_rate is not None else None,
            "tax_code": ln.tax_code,
        }
        for ln in lines
    ]


def _snapshot_existing_entry(session, journal_entry_id: int) -> dict:
    """نسخه‌ی قابلِ‌سریالایزِ سند و ردیف‌هایش، خوانده‌شده از همان
    session — برایِ ثبتِ «قبل» در ردِ حسابرسیِ ویرایش/حذف."""
    entry = session.get(JournalEntry, journal_entry_id)
    lines = session.scalars(
        select(JournalEntryLine)
        .where(JournalEntryLine.journal_entry_id == journal_entry_id)
        .order_by(JournalEntryLine.line_no)
    ).all()
    status = session.get(JournalEntryStatus, entry.status_id)
    return {
        "document_date": entry.document_date.isoformat(),
        "description": entry.description,
        "alternative_number": entry.alternative_number,
        "status": status.code if status is not None else None,
        "lines": [
            {
                "account_id": ln.account_id,
                "description": ln.description,
                "debit": str(ln.debit_amount_fc),
                "credit": str(ln.credit_amount_fc),
                "currency_id": ln.currency_id,
                "exchange_rate": str(ln.exchange_rate),
                "tax_code": ln.tax_code,
            }
            for ln in lines
        ],
    }


@dataclass
class LineInput:
    account_id: int
    description: str
    debit: decimal.Decimal
    credit: decimal.Decimal
    # نگاشتِ dimension_type_id -> detail_account_id — برای ردیف‌هایی که
    # حسابشان نوع‌بُعدِ تفصیلیِ الزامی دارد (acc.account_detail_dimensions).
    details: dict[int, int] = field(default_factory=dict)
    # None یعنی ارزِ پایه‌ی شرکت (نرخ همیشه ۱، نیازی به exchange_rate نیست).
    currency_id: int | None = None
    exchange_rate: decimal.Decimal | None = None
    tax_code: str | None = None


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
    alternative_number: str
    registration_at: datetime.datetime
    created_by_name: str = ""
    company_name: str = ""
    fiscal_year_code: str = ""
    permanent_no: int | None = None


def _validate_lines(lines: list[LineInput], *, require_balance: bool = True) -> list[LineInput]:
    real_lines = [ln for ln in lines if ln.debit != 0 or ln.credit != 0]
    if require_balance and len(real_lines) < 2:
        raise ValueError("سند حسابداری باید حداقل دو ردیف (یک بدهکار و یک بستانکار) داشته باشد.")
    for ln in real_lines:
        if (ln.debit != 0) == (ln.credit != 0):
            raise ValueError("هر ردیف باید یا بدهکار یا بستانکار باشد، نه هر دو یا هیچ‌کدام.")
    return real_lines


def _base_amount(amount: decimal.Decimal, exchange_rate: decimal.Decimal) -> decimal.Decimal:
    return (amount * exchange_rate).quantize(_BASE_QUANT, rounding=decimal.ROUND_HALF_UP)


@dataclass
class _ResolvedLine:
    line: LineInput
    currency_id: int
    exchange_rate: decimal.Decimal


def _resolve_lines(
    session, company: Company, real_lines: list[LineInput], *, require_balance: bool = True
) -> list[_ResolvedLine]:
    """اعتبارسنجیِ حساب‌ها/ابعادِ تفصیلی + تعیینِ ارز و نرخِ هر ردیف — ارزِ
    مشخص‌نشده یعنی ارزِ پایه (نرخ ۱)؛ ارزِ غیرِپایه باید هم برای شرکت فعال
    باشد و هم (اگر حساب به ارزِ خاصی محدود شده) با ارزِ حساب یکی باشد.
    require_balance=False برای سندِ پیش‌نویس: حساب/بُعد/ارز هنوز اعتبارسنجی
    می‌شوند (چون مقادیرِ نامعتبر هیچ‌وقت نباید ذخیره شوند)، فقط شرطِ تساویِ
    جمعِ بدهکار/بستانکار موقتاً نادیده گرفته می‌شود."""
    account_ids = [ln.account_id for ln in real_lines]
    accounts = session.scalars(select(ChartOfAccount).where(ChartOfAccount.account_id.in_(account_ids))).all()
    accounts_by_id = {a.account_id: a for a in accounts}

    required_by_account: dict[int, set[int]] = {}
    if account_ids:
        rows = session.execute(
            select(AccountDetailDimension.account_id, AccountDetailDimension.dimension_type_id).where(
                AccountDetailDimension.account_id.in_(account_ids), AccountDetailDimension.is_required.is_(True)
            )
        ).all()
        for account_id, dimension_type_id in rows:
            required_by_account.setdefault(account_id, set()).add(dimension_type_id)

    # طبقِ درخواستِ صریح: یک معین می‌تواند به گروهِ تفصیلیِ خاصی (مشتری/
    # تامین‌کننده/پرسنل) محدود شود — اگر محدود بود، «بدون تفصیلی» دیگر کافی
    # نیست و انتخابِ الزامی از همان گروه لازم است.
    required_person_groups_by_account: dict[int, set[int]] = {}
    if account_ids:
        rows = session.execute(
            select(AccountPersonGroup.account_id, AccountPersonGroup.person_group_id).where(
                AccountPersonGroup.account_id.in_(account_ids)
            )
        ).all()
        for account_id, person_group_id in rows:
            required_person_groups_by_account.setdefault(account_id, set()).add(person_group_id)

    enabled_currency_ids = {company.base_currency_id} | set(
        session.scalars(
            select(CompanyCurrency.currency_id).where(
                CompanyCurrency.company_id == company.company_id, CompanyCurrency.is_active.is_(True)
            )
        ).all()
    )

    # تفصیلیِ اشخاص برخلافِ نوع‌بُعدهای اختیاری (مرکزِ هزینه/پروژه) برایِ
    # هر ردیف الزامی است — اگر کاربر شخصی انتخاب نکرده باشد، همین‌جا
    # مقدارِ پیش‌فرضِ «بدون تفصیلی» جایگزین می‌شود تا ترازِ سطحِ تفصیلی
    # همیشه کامل بماند.
    person_dimension_type_id = dimensions_service.ensure_person_dimension(session, company.company_id)
    no_detail_account = session.scalar(
        select(DetailAccount).where(
            DetailAccount.company_id == company.company_id,
            DetailAccount.dimension_type_id == person_dimension_type_id,
            DetailAccount.code == dimensions_service.NO_DETAIL_CODE,
        )
    )
    no_detail_account_id = no_detail_account.detail_account_id

    all_provided_detail_ids = {v for ln in real_lines for v in ln.details.values()}
    detail_accounts_by_id: dict[int, DetailAccount] = {}
    if all_provided_detail_ids:
        detail_accounts_by_id = {
            d.detail_account_id: d
            for d in session.scalars(
                select(DetailAccount).where(DetailAccount.detail_account_id.in_(all_provided_detail_ids))
            ).all()
        }

    resolved: list[_ResolvedLine] = []
    for ln in real_lines:
        account = accounts_by_id.get(ln.account_id)
        if account is None or account.company_id != company.company_id:
            raise ValueError("یکی از حساب‌های انتخاب‌شده نامعتبر است.")
        if not account.is_postable:
            raise ValueError(f"حساب «{account.full_code}» قابل ثبت سند نیست.")

        # نکته‌ی مهم (باگِ پیداشده در حسابرسی): این‌جا قبلاً هر ردیفی که سمتِ
        # مخالفِ ماهیتِ حساب بود (مثلاً بستانکارکردنِ حسابی با ماهیتِ
        # «بدهکار») را رد می‌کرد. این با خودِ متنِ راهنمای فیلدِ ماهیت هم در
        # تناقض بود («ماهیت یعنی این حساب *معمولاً* با بدهکار زیاد می‌شود» —
        # یعنی گرایشِ غالب، نه قیدِ مطلق) و عملاً ثبتِ ابتدایی‌ترین اسنادِ
        # حسابداری را غیرِممکن می‌کرد: وصولِ مطالبات (بستانکارکردنِ حسابِ
        # دریافتنیِ بدهکار-ماهیت)، پرداختِ بدهی (بدهکارکردنِ حسابِ پرداختنیِ
        # بستانکار-ماهیت)، برگشت از فروش، خروجِ کالا از انبار و... همه یک
        # ردیف در سمتِ «مخالف» نیاز دارند. جایِ دیگری از سیستم هم (گزارش‌ها،
        # ترازنامه) بر مبنایِ category_code حساب (دارایی/بدهی/...) کار
        # می‌کند نه nature_id — یعنی ماهیت فقط برایِ نمایش/راهنماست، نه یک
        # قیدِ حسابداری. پس این کنترل حذف شد؛ تنها قیدِ واقعیِ حسابداری
        # همان تراز بودنِ کلِ سند است (پایین‌تر بررسی می‌شود).

        required = required_by_account.get(ln.account_id, set())
        missing = required - set(ln.details.keys())
        if missing:
            raise ValueError(f"برای حساب «{account.full_code}» انتخابِ ابعادِ تفصیلیِ الزامی فراموش شده است.")

        required_person_groups = required_person_groups_by_account.get(ln.account_id)
        person_detail_account_id = ln.details.get(person_dimension_type_id)
        if required_person_groups:
            person_row = detail_accounts_by_id.get(person_detail_account_id) if person_detail_account_id else None
            if (
                person_row is None
                or person_row.code == dimensions_service.NO_DETAIL_CODE
                or person_row.person_group_id not in required_person_groups
            ):
                raise ValueError(
                    f"برایِ حساب «{account.full_code}» انتخابِ یک تفصیلیِ اشخاص از گروهِ مجازِ همین حساب الزامی است."
                )
        elif person_dimension_type_id not in ln.details:
            ln.details[person_dimension_type_id] = no_detail_account_id

        currency_id = ln.currency_id or company.base_currency_id
        if account.currency_id is not None and account.currency_id != currency_id:
            raise ValueError(f"حساب «{account.full_code}» فقط با ارزِ مشخص‌شده‌ی خودش قابل ثبت است.")
        if currency_id not in enabled_currency_ids:
            raise ValueError(f"ارزِ انتخاب‌شده برای ردیفِ حساب «{account.full_code}» برای این شرکت فعال نیست.")

        if currency_id == company.base_currency_id:
            exchange_rate = decimal.Decimal(1)
        else:
            if not ln.exchange_rate or ln.exchange_rate <= 0:
                raise ValueError(f"نرخِ ارز برای ردیفِ حساب «{account.full_code}» مشخص نشده است.")
            exchange_rate = ln.exchange_rate

        resolved.append(_ResolvedLine(line=ln, currency_id=currency_id, exchange_rate=exchange_rate))

    detail_account_ids = {value for ln in real_lines for value in ln.details.values()}
    if detail_account_ids:
        valid_detail_accounts = session.scalars(
            select(DetailAccount.detail_account_id).where(
                DetailAccount.detail_account_id.in_(detail_account_ids), DetailAccount.company_id == company.company_id
            )
        ).all()
        if set(valid_detail_accounts) != detail_account_ids:
            raise ValueError("یکی از حساب‌های تفصیلیِ انتخاب‌شده نامعتبر است.")

    if require_balance:
        total_debit = sum((_base_amount(r.line.debit, r.exchange_rate) for r in resolved), decimal.Decimal(0))
        total_credit = sum((_base_amount(r.line.credit, r.exchange_rate) for r in resolved), decimal.Decimal(0))
        if total_debit != total_credit:
            raise ValueError(
                f"سند تراز نیست: جمع بدهکار (معادلِ ارزِ پایه) {numerals.format_amount(total_debit)} "
                f"با جمع بستانکار {numerals.format_amount(total_credit)} برابر نیست."
            )

    return resolved


def fiscal_year_bounds(
    start_month: int, start_day: int, on_date: datetime.date
) -> tuple[str, datetime.date, datetime.date]:
    jalali = jdatetime.date.fromgregorian(date=on_date)
    year = jalali.year
    if jalali < jdatetime.date(year, start_month, start_day):
        year -= 1
    start = jdatetime.date(year, start_month, start_day)
    end = jdatetime.date(year + 1, start_month, start_day) - datetime.timedelta(days=1)
    return str(year), start.togregorian(), end.togregorian()


def peek_next_temporary_no(company_id: int, document_date: datetime.date) -> int:
    """پیش‌نمایشِ شماره‌یِ موقتی که سندِ تازه (اگر همین حالا ذخیره شود)
    خواهد گرفت — طبقِ درخواستِ صریح، بالایِ فرمِ سندِ جدید نمایش داده
    می‌شود، پیش از ذخیره. کاملاً read-only است (برخلافِ
    _get_or_create_fiscal_year که در مسیرِ ذخیره‌یِ واقعی صدا زده می‌شود،
    این تابع سالِ مالیِ تازه نمی‌سازد — اگر سالِ مالیِ این تاریخ هنوز
    وجود نداشته باشد، یعنی این اولین سندِ آن سال خواهد بود، پس ۱ برمی‌گردد)."""
    with new_session() as session:
        company = session.get(Company, company_id)
        if company is None:
            return 1
        code, _start, _end = fiscal_year_bounds(
            company.fiscal_year_start_month, company.fiscal_year_start_day, document_date
        )
        fiscal_year = session.scalar(
            select(FiscalYear).where(FiscalYear.company_id == company_id, FiscalYear.code == code)
        )
        if fiscal_year is None:
            return 1
        return (
            session.scalar(
                select(func.max(JournalEntry.temporary_no)).where(
                    JournalEntry.company_id == company_id,
                    JournalEntry.fiscal_year_id == fiscal_year.fiscal_year_id,
                )
            )
            or 0
        ) + 1


def _get_or_create_fiscal_year(session, company: Company, on_date: datetime.date) -> FiscalYear:
    code, start, end = fiscal_year_bounds(company.fiscal_year_start_month, company.fiscal_year_start_day, on_date)
    fiscal_year = session.scalar(
        select(FiscalYear).where(FiscalYear.company_id == company.company_id, FiscalYear.code == code)
    )
    if fiscal_year is None:
        fiscal_year = FiscalYear(company_id=company.company_id, code=code, start_date=start, end_date=end)
        session.add(fiscal_year)
        session.flush()
    return fiscal_year


def _ensure_fiscal_year_open(fiscal_year: FiscalYear) -> None:
    """باگِ پیداشده در حسابرسی: صفحه‌ی سال‌هایِ مالی به کاربر اجازه‌یِ
    «بستن» سالِ مالی را می‌دهد (fiscal_years.set_closed) و انتظارِ منطقیِ
    هر کاربرِ حسابداری این است که بعدِ بستن، دیگر نتوان در آن سال سند ثبت/
    ویرایش کرد؛ ولی قبل از این تابع، create/update_journal_entry اصلاً
    is_closed را نگاه نمی‌کردند — یعنی «بستن سالِ مالی» در عمل هیچ اثری
    نداشت. این تابع همان قیدِ ازپیش‌مستندشده در docs/accounting-module.md
    («باز بودنِ دوره‌ی مالیِ تاریخِ سند») را واقعاً اعمال می‌کند."""
    if fiscal_year.is_closed:
        raise ValueError(
            f"سالِ مالیِ «{fiscal_year.code}» بسته است؛ ثبت یا ویرایشِ سند در این سال ممکن نیست."
        )


def _ensure_fiscal_period_open(session, fiscal_year_id: int, document_date: datetime.date) -> None:
    """طبقِ حسابرسیِ صریح: جدولِ FiscalPeriod (دوره‌هایِ ماهانه‌یِ هر سالِ
    مالی) ساخته می‌شد ولی هیچ‌جای برنامه چک نمی‌شد — یعنی بستنِ یک دوره‌ی
    ماهانه در عمل هیچ اثری نداشت. اگر برایِ این سالِ مالی اصلاً دوره‌ای
    تعریف نشده باشد (مثلاً سالِ مالی به‌صورتِ خودکار از رویِ اولین سند ساخته
    شده، نه از صفحه‌ی «سال‌های مالی»)، این چک بی‌اثر می‌ماند — دوره‌بندی
    اختیاری است، نه اجباری."""
    period = session.scalar(
        select(FiscalPeriod).where(
            FiscalPeriod.fiscal_year_id == fiscal_year_id,
            FiscalPeriod.start_date <= document_date,
            FiscalPeriod.end_date >= document_date,
        )
    )
    if period is not None and period.is_closed:
        raise ValueError(
            f"دوره‌ی مالیِ شامل تاریخِ {numerals.format_jalali_date(document_date)} بسته است؛ "
            "ثبت یا ویرایشِ سند در این دوره ممکن نیست."
        )


def create_journal_entry(
    company_id: int,
    created_by_user_id: int,
    document_date: datetime.date,
    description: str,
    lines: list[LineInput],
    alternative_number: str = "",
    as_draft: bool = False,
) -> JournalEntryResult:
    require_balance = not as_draft
    real_lines = _validate_lines(lines, require_balance=require_balance)

    with new_session() as session:
        company = session.get(Company, company_id)
        if company is None:
            raise ValueError("شرکت نامعتبر است.")

        resolved_lines = _resolve_lines(session, company, real_lines, require_balance=require_balance)

        status_code = "DRAFT" if as_draft else "TEMPORARY"
        entry_type = session.scalar(select(JournalEntryType).where(JournalEntryType.code == "NORMAL"))
        status = session.scalar(select(JournalEntryStatus).where(JournalEntryStatus.code == status_code))
        if entry_type is None or status is None:
            raise ValueError("داده‌ی پایه‌ی نوع/وضعیت سند در دیتابیس یافت نشد.")

        fiscal_year = _get_or_create_fiscal_year(session, company, document_date)
        _ensure_fiscal_year_open(fiscal_year)
        _ensure_fiscal_period_open(session, fiscal_year.fiscal_year_id, document_date)

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
            alternative_number=alternative_number or None,
            entry_type_id=entry_type.entry_type_id,
            status_id=status.status_id,
            description=description or None,
            created_by_user_id=created_by_user_id,
        )
        session.add(entry)
        session.flush()

        for line_no, resolved in enumerate(resolved_lines, start=1):
            ln = resolved.line
            line = JournalEntryLine(
                journal_entry_id=entry.journal_entry_id,
                line_no=line_no,
                account_id=ln.account_id,
                description=ln.description or None,
                tax_code=ln.tax_code or None,
                currency_id=resolved.currency_id,
                exchange_rate=resolved.exchange_rate,
                debit_amount_fc=ln.debit,
                credit_amount_fc=ln.credit,
            )
            session.add(line)
            session.flush()
            for dimension_type_id, detail_account_id in ln.details.items():
                session.add(
                    JournalEntryLineDetail(
                        line_id=line.line_id,
                        dimension_type_id=dimension_type_id,
                        detail_account_id=detail_account_id,
                    )
                )

        audit_service.log_activity(
            session,
            company_id=company_id,
            user_id=created_by_user_id,
            entity_type="JournalEntry",
            entity_id=entry.journal_entry_id,
            action="CREATE",
            changes={
                "after": {
                    "document_date": document_date.isoformat(),
                    "description": description,
                    "alternative_number": alternative_number or None,
                    "status": status_code,
                    "lines": _lines_snapshot([r.line for r in resolved_lines]),
                }
            },
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

        # طبقِ درخواستِ صریح: کاربرِ صادرکننده، نامِ شرکت و سالِ مالی هم در
        # فهرستِ اسناد نمایش داده شود.
        company = session.get(Company, company_id)
        company_name = company.display_name if company is not None else ""
        user_ids = {e.created_by_user_id for e in entries}
        user_names = (
            dict(session.execute(select(User.user_id, User.full_name).where(User.user_id.in_(user_ids))).all())
            if user_ids
            else {}
        )
        fiscal_year_ids = {e.fiscal_year_id for e in entries}
        fiscal_year_codes = (
            dict(
                session.execute(
                    select(FiscalYear.fiscal_year_id, FiscalYear.code).where(
                        FiscalYear.fiscal_year_id.in_(fiscal_year_ids)
                    )
                ).all()
            )
            if fiscal_year_ids
            else {}
        )

        return [
            JournalEntrySummary(
                journal_entry_id=e.journal_entry_id,
                temporary_no=e.temporary_no,
                document_date=e.document_date,
                description=e.description or "",
                status_code=status_codes[e.status_id],
                total_amount=totals.get(e.journal_entry_id, decimal.Decimal(0)),
                alternative_number=e.alternative_number or "",
                registration_at=e.created_at,
                created_by_name=user_names.get(e.created_by_user_id, ""),
                company_name=company_name,
                fiscal_year_code=fiscal_year_codes.get(e.fiscal_year_id, ""),
                permanent_no=e.permanent_no,
            )
            for e in entries
        ]


def list_recent_line_descriptions(company_id: int, limit: int = 300) -> list[str]:
    """فهرستِ متمایزِ شرح‌های قبلاً واردشده برای ردیف‌های سند — برای
    پیشنهادِ زنده هنگامِ تایپ در فیلدِ «شرح ردیف» (طبق درخواستِ صریح)."""
    with new_session() as session:
        rows = session.execute(
            select(JournalEntryLine.description)
            .join(JournalEntry, JournalEntry.journal_entry_id == JournalEntryLine.journal_entry_id)
            .where(JournalEntry.company_id == company_id, JournalEntryLine.description.isnot(None))
            .order_by(JournalEntryLine.line_id.desc())
            .limit(limit)
        ).all()
        seen: dict[str, None] = {}
        for (description,) in rows:
            text = (description or "").strip()
            if text and text not in seen:
                seen[text] = None
        return list(seen.keys())


def list_recent_entry_descriptions(company_id: int, limit: int = 300) -> list[str]:
    """فهرستِ متمایزِ شرح‌هایِ قبلاً واردشده برایِ سرِ سند (نه ردیف‌ها) —
    طبقِ درخواستِ صریح، برایِ پیشنهادِ زنده هنگامِ تایپِ «شرحِ سند»."""
    with new_session() as session:
        rows = session.execute(
            select(JournalEntry.description)
            .where(JournalEntry.company_id == company_id, JournalEntry.description.isnot(None))
            .order_by(JournalEntry.journal_entry_id.desc())
            .limit(limit)
        ).all()
        seen: dict[str, None] = {}
        for (description,) in rows:
            text = (description or "").strip()
            if text and text not in seen:
                seen[text] = None
        return list(seen.keys())


def get_journal_entry_lines(journal_entry_id: int) -> list[LineInput]:
    with new_session() as session:
        lines = session.scalars(
            select(JournalEntryLine)
            .where(JournalEntryLine.journal_entry_id == journal_entry_id)
            .order_by(JournalEntryLine.line_no)
        ).all()

        line_ids = [ln.line_id for ln in lines]
        details_by_line: dict[int, dict[int, int]] = {}
        if line_ids:
            rows = session.execute(
                select(
                    JournalEntryLineDetail.line_id,
                    JournalEntryLineDetail.dimension_type_id,
                    JournalEntryLineDetail.detail_account_id,
                ).where(JournalEntryLineDetail.line_id.in_(line_ids))
            ).all()
            for line_id, dimension_type_id, detail_account_id in rows:
                details_by_line.setdefault(line_id, {})[dimension_type_id] = detail_account_id

        return [
            LineInput(
                account_id=ln.account_id,
                description=ln.description or "",
                debit=ln.debit_amount_fc,
                credit=ln.credit_amount_fc,
                details=details_by_line.get(ln.line_id, {}),
                currency_id=ln.currency_id,
                exchange_rate=ln.exchange_rate,
                tax_code=ln.tax_code,
            )
            for ln in lines
        ]


def update_journal_entry(
    journal_entry_id: int,
    company_id: int,
    document_date: datetime.date,
    description: str,
    lines: list[LineInput],
    changed_by_user_id: int | None = None,
    alternative_number: str = "",
    as_draft: bool = False,
) -> None:
    require_balance = not as_draft
    real_lines = _validate_lines(lines, require_balance=require_balance)

    with new_session() as session:
        entry = session.get(JournalEntry, journal_entry_id)
        if entry is None or entry.company_id != company_id:
            raise ValueError("سند نامعتبر است.")
        status = session.get(JournalEntryStatus, entry.status_id)
        if status is None or status.code not in ("TEMPORARY", "DRAFT"):
            raise ValueError("فقط سندهای با وضعیت موقت یا پیش‌نویس قابل ویرایش‌اند.")

        company = session.get(Company, company_id)
        if company is None:
            raise ValueError("شرکت نامعتبر است.")
        resolved_lines = _resolve_lines(session, company, real_lines, require_balance=require_balance)

        # سالِ مالیِ فعلیِ سند (پیش از ویرایش) هم اگر بسته باشد، ویرایش مجاز
        # نیست — نه فقط سالِ مالیِ تاریخِ تازه. سپس سالِ مالیِ تاریخِ تازه هم
        # باید باز باشد (ممکن است کاربر تاریخ را به سالِ دیگری برده باشد).
        current_fiscal_year = session.get(FiscalYear, entry.fiscal_year_id)
        if current_fiscal_year is not None:
            _ensure_fiscal_year_open(current_fiscal_year)
            _ensure_fiscal_period_open(session, current_fiscal_year.fiscal_year_id, entry.document_date)
        new_fiscal_year = _get_or_create_fiscal_year(session, company, document_date)
        _ensure_fiscal_year_open(new_fiscal_year)
        _ensure_fiscal_period_open(session, new_fiscal_year.fiscal_year_id, document_date)

        before_snapshot = _snapshot_existing_entry(session, journal_entry_id)

        status_code = "DRAFT" if as_draft else "TEMPORARY"
        new_status = session.scalar(select(JournalEntryStatus).where(JournalEntryStatus.code == status_code))
        if new_status is None:
            raise ValueError("داده‌ی پایه‌ی وضعیتِ سند در دیتابیس یافت نشد.")

        entry.document_date = document_date
        entry.description = description or None
        entry.alternative_number = alternative_number or None
        entry.status_id = new_status.status_id
        if new_fiscal_year.fiscal_year_id != entry.fiscal_year_id:
            # باگِ پیداشده در حسابرسی: ویرایشِ تاریخِ سند به سالِ مالیِ دیگر،
            # fiscal_year_id را هیچ‌وقت به‌روز نمی‌کرد — یعنی سند همچنان زیرِ
            # سالِ مالیِ قدیمی می‌ماند (کدِ سالِ مالیِ نمایش‌داده‌شده در فهرستِ
            # اسناد غلط می‌شد) و شماره‌گذاریِ temporary_no هم دیگر با شماره‌گذاریِ
            # سالِ مالیِ واقعی‌اش هم‌خوان نمی‌ماند. این‌جا هم fiscal_year_id
            # به‌روز می‌شود و هم temporary_no در سالِ مالیِ جدید دوباره تخصیص
            # می‌یابد (وگرنه ممکن بود با یک سندِ دیگر در همان سالِ مالی به یک
            # عددِ temporary_no برخورد/تناقض کند، چون یکتاییِ این عدد در دیتابیس
            # per (company_id, fiscal_year_id) تعریف شده).
            entry.fiscal_year_id = new_fiscal_year.fiscal_year_id
            next_no = (
                session.scalar(
                    select(func.max(JournalEntry.temporary_no)).where(
                        JournalEntry.company_id == company_id,
                        JournalEntry.fiscal_year_id == new_fiscal_year.fiscal_year_id,
                    )
                )
                or 0
            ) + 1
            entry.temporary_no = next_no

        old_line_ids = list(
            session.scalars(
                select(JournalEntryLine.line_id).where(JournalEntryLine.journal_entry_id == entry.journal_entry_id)
            ).all()
        )
        if old_line_ids:
            session.execute(
                JournalEntryLineDetail.__table__.delete().where(JournalEntryLineDetail.line_id.in_(old_line_ids))
            )
        session.execute(JournalEntryLine.__table__.delete().where(JournalEntryLine.journal_entry_id == entry.journal_entry_id))

        for line_no, resolved in enumerate(resolved_lines, start=1):
            ln = resolved.line
            line = JournalEntryLine(
                journal_entry_id=entry.journal_entry_id,
                line_no=line_no,
                account_id=ln.account_id,
                description=ln.description or None,
                tax_code=ln.tax_code or None,
                currency_id=resolved.currency_id,
                exchange_rate=resolved.exchange_rate,
                debit_amount_fc=ln.debit,
                credit_amount_fc=ln.credit,
            )
            session.add(line)
            session.flush()
            for dimension_type_id, detail_account_id in ln.details.items():
                session.add(
                    JournalEntryLineDetail(
                        line_id=line.line_id,
                        dimension_type_id=dimension_type_id,
                        detail_account_id=detail_account_id,
                    )
                )

        audit_service.log_activity(
            session,
            company_id=company_id,
            user_id=changed_by_user_id,
            entity_type="JournalEntry",
            entity_id=journal_entry_id,
            action="UPDATE",
            changes={
                "before": before_snapshot,
                "after": {
                    "document_date": document_date.isoformat(),
                    "description": description,
                    "alternative_number": alternative_number or None,
                    "status": status_code,
                    "lines": _lines_snapshot([r.line for r in resolved_lines]),
                },
            },
        )

        session.commit()


def delete_journal_entry(journal_entry_id: int, company_id: int, changed_by_user_id: int | None = None) -> None:
    with new_session() as session:
        entry = session.get(JournalEntry, journal_entry_id)
        if entry is None or entry.company_id != company_id:
            raise ValueError("سند نامعتبر است.")
        status = session.get(JournalEntryStatus, entry.status_id)
        if status is None or status.code not in ("TEMPORARY", "DRAFT"):
            raise ValueError("فقط سندهای با وضعیت موقت یا پیش‌نویس قابل حذف‌اند.")
        fiscal_year = session.get(FiscalYear, entry.fiscal_year_id)
        if fiscal_year is not None:
            _ensure_fiscal_year_open(fiscal_year)
            _ensure_fiscal_period_open(session, fiscal_year.fiscal_year_id, entry.document_date)

        before_snapshot = _snapshot_existing_entry(session, journal_entry_id)

        line_ids = list(
            session.scalars(
                select(JournalEntryLine.line_id).where(JournalEntryLine.journal_entry_id == journal_entry_id)
            ).all()
        )
        if line_ids:
            session.execute(
                JournalEntryLineDetail.__table__.delete().where(JournalEntryLineDetail.line_id.in_(line_ids))
            )
        session.execute(JournalEntryLine.__table__.delete().where(JournalEntryLine.journal_entry_id == journal_entry_id))
        session.delete(entry)

        audit_service.log_activity(
            session,
            company_id=company_id,
            user_id=changed_by_user_id,
            entity_type="JournalEntry",
            entity_id=journal_entry_id,
            action="DELETE",
            changes={"before": before_snapshot},
        )

        session.commit()


def _next_permanent_no(session, company_id: int, fiscal_year_id: int) -> int:
    return (
        session.scalar(
            select(func.max(JournalEntry.permanent_no)).where(
                JournalEntry.company_id == company_id,
                JournalEntry.fiscal_year_id == fiscal_year_id,
            )
        )
        or 0
    ) + 1


def approve_journal_entry(journal_entry_id: int, company_id: int, posted_by_user_id: int) -> int:
    """طبقِ حسابرسیِ صریح: طراحیِ دیتابیس از اول یک گردشِ کارِ «تاییدِ
    کارتابل» را پیش‌بینی کرده بود (ستون‌هایِ posted_by_user_id/posted_at
    و تریگرِ tr_journal_entries_prevent_permanent_no_change) ولی هیچ
    سرویسی این گردشِ کار را پیاده نمی‌کرد — یعنی هر سندی برایِ همیشه
    TEMPORARY می‌ماند و permanent_no همیشه NULL بود. این تابع همان
    تاییدِ کارتابل است: سندِ TEMPORARY را به PERMANENT ارتقا می‌دهد و
    شماره‌یِ دائمِ واقعی می‌گیرد (بعد از این، طبقِ تریگرِ دیتابیس دیگر
    قابلِ‌تغییر نیست؛ create/update/delete هم همین حالا فقط
    TEMPORARY/DRAFT را می‌پذیرند، پس سندِ دائم به‌طورِ طبیعی غیرقابلِ‌
    ویرایش/حذف می‌شود)."""
    with new_session() as session:
        entry = session.get(JournalEntry, journal_entry_id)
        if entry is None or entry.company_id != company_id:
            raise ValueError("سند نامعتبر است.")
        status = session.get(JournalEntryStatus, entry.status_id)
        if status is None or status.code != "TEMPORARY":
            raise ValueError("فقط سندهایِ موقت قابلِ تایید (ارتقا به دائم) هستند.")
        fiscal_year = session.get(FiscalYear, entry.fiscal_year_id)
        if fiscal_year is not None:
            _ensure_fiscal_year_open(fiscal_year)
            _ensure_fiscal_period_open(session, fiscal_year.fiscal_year_id, entry.document_date)

        permanent_status = session.scalar(select(JournalEntryStatus).where(JournalEntryStatus.code == "PERMANENT"))
        if permanent_status is None:
            raise ValueError("داده‌ی پایه‌ی وضعیتِ «دائم» در دیتابیس یافت نشد.")

        next_no = _next_permanent_no(session, company_id, entry.fiscal_year_id)
        entry.permanent_no = next_no
        entry.status_id = permanent_status.status_id
        entry.posted_by_user_id = posted_by_user_id
        entry.posted_at = datetime.datetime.now()

        audit_service.log_activity(
            session,
            company_id=company_id,
            user_id=posted_by_user_id,
            entity_type="JournalEntry",
            entity_id=journal_entry_id,
            action="APPROVE",
            changes={"after": {"status": "PERMANENT", "permanent_no": next_no}},
        )

        session.commit()
        return next_no


def reverse_journal_entry(journal_entry_id: int, company_id: int, created_by_user_id: int) -> JournalEntryResult:
    """سندِ برگشتی (اصلاحیه) برایِ یک سندِ دائم. طبقِ طراحیِ دیتابیس، سندِ
    دائم دیگر قابلِ‌ویرایش/حذف نیست، پس تنها راهِ خنثی‌کردنِ اثرش، سندی
    تازه با بدهکار/بستانکارِ معکوسِ همان ردیف‌هاست (ستونِ خودِ مدل هم
    reversed_entry_id دارد، دقیقاً برایِ همین). سندِ برگشتی بلافاصله
    خودش هم دائم می‌شود (نه موقتِ منتظرِ تاییدِ جداگانه) چون هدفش خنثی‌
    کردنِ فوریِ اثرِ یک سندِ ازپیش‌دائم در دفاتر است."""
    with new_session() as session:
        original = session.get(JournalEntry, journal_entry_id)
        if original is None or original.company_id != company_id:
            raise ValueError("سند نامعتبر است.")
        original_status = session.get(JournalEntryStatus, original.status_id)
        if original_status is None or original_status.code != "PERMANENT":
            raise ValueError("فقط سندهایِ دائم قابلِ برگشت‌زدن‌اند.")

        company = session.get(Company, company_id)
        if company is None:
            raise ValueError("شرکت نامعتبر است.")

        document_date = datetime.date.today()
        fiscal_year = _get_or_create_fiscal_year(session, company, document_date)
        _ensure_fiscal_year_open(fiscal_year)
        _ensure_fiscal_period_open(session, fiscal_year.fiscal_year_id, document_date)

        original_lines = session.scalars(
            select(JournalEntryLine)
            .where(JournalEntryLine.journal_entry_id == journal_entry_id)
            .order_by(JournalEntryLine.line_no)
        ).all()

        entry_type = session.scalar(select(JournalEntryType).where(JournalEntryType.code == "NORMAL"))
        permanent_status = session.scalar(select(JournalEntryStatus).where(JournalEntryStatus.code == "PERMANENT"))
        reversed_status = session.scalar(select(JournalEntryStatus).where(JournalEntryStatus.code == "REVERSED"))
        if entry_type is None or permanent_status is None or reversed_status is None:
            raise ValueError("داده‌ی پایه‌ی نوع/وضعیتِ سند در دیتابیس یافت نشد.")

        next_temp_no = (
            session.scalar(
                select(func.max(JournalEntry.temporary_no)).where(
                    JournalEntry.company_id == company_id,
                    JournalEntry.fiscal_year_id == fiscal_year.fiscal_year_id,
                )
            )
            or 0
        ) + 1
        next_permanent_no = _next_permanent_no(session, company_id, fiscal_year.fiscal_year_id)

        original_no = original.permanent_no
        reversal = JournalEntry(
            company_id=company_id,
            fiscal_year_id=fiscal_year.fiscal_year_id,
            temporary_no=next_temp_no,
            permanent_no=next_permanent_no,
            document_date=document_date,
            entry_type_id=entry_type.entry_type_id,
            status_id=permanent_status.status_id,
            description=f"سندِ برگشتیِ سندِ دائمِ شماره‌ی {original_no}",
            is_system_generated=True,
            reversed_entry_id=original.journal_entry_id,
            created_by_user_id=created_by_user_id,
            posted_by_user_id=created_by_user_id,
            posted_at=datetime.datetime.now(),
        )
        session.add(reversal)
        session.flush()

        for line_no, ln in enumerate(original_lines, start=1):
            details = session.scalars(
                select(JournalEntryLineDetail).where(JournalEntryLineDetail.line_id == ln.line_id)
            ).all()
            new_line = JournalEntryLine(
                journal_entry_id=reversal.journal_entry_id,
                line_no=line_no,
                account_id=ln.account_id,
                description=ln.description,
                tax_code=ln.tax_code,
                currency_id=ln.currency_id,
                exchange_rate=ln.exchange_rate,
                debit_amount_fc=ln.credit_amount_fc,
                credit_amount_fc=ln.debit_amount_fc,
            )
            session.add(new_line)
            session.flush()
            for d in details:
                session.add(
                    JournalEntryLineDetail(
                        line_id=new_line.line_id,
                        dimension_type_id=d.dimension_type_id,
                        detail_account_id=d.detail_account_id,
                    )
                )

        original.status_id = reversed_status.status_id

        audit_service.log_activity(
            session,
            company_id=company_id,
            user_id=created_by_user_id,
            entity_type="JournalEntry",
            entity_id=journal_entry_id,
            action="REVERSE",
            changes={"after": {"status": "REVERSED", "reversed_by_entry_id": reversal.journal_entry_id}},
        )
        audit_service.log_activity(
            session,
            company_id=company_id,
            user_id=created_by_user_id,
            entity_type="JournalEntry",
            entity_id=reversal.journal_entry_id,
            action="CREATE",
            changes={"after": {"status": "PERMANENT", "reverses_entry_id": journal_entry_id}},
        )

        session.commit()
        return JournalEntryResult(journal_entry_id=reversal.journal_entry_id, temporary_no=next_temp_no)


# --- ثبت‌نامِ handlerِ کارتابل (services/cartable.py) ------------------------
# طبقِ درخواستِ صریح («سیستمِ کارتابلِ قابلِ‌گسترش برایِ همه‌یِ ماژول‌ها»):
# این‌جا فقط سه callback ثبت می‌شود، بدونِ هیچ منطقِ تازه‌ای — approve_journal_entry
# همان تابعِ ازپیش‌تست‌شده‌ای است که قبلاً مستقیم از UI صدا زده می‌شد؛ حالا
# وقتی گردشِ کاری برایِ form_code="journal_entry" تعریف شده باشد، آخرین
# مرحله‌یِ تاییدِ کارتابل همین تابع را صدا می‌زند.


def _cartable_on_approved(company_id: int, source_record_id: int, approved_by_user_id: int) -> None:
    approve_journal_entry(source_record_id, company_id, approved_by_user_id)


def _cartable_on_rejected(company_id: int, source_record_id: int, rejected_by_user_id: int, reason: str) -> None:
    """سندِ ردشده به پیش‌نویس برمی‌گردد تا صادرکننده اصلاح و دوباره ارسال کند."""
    with new_session() as session:
        entry = session.get(JournalEntry, source_record_id)
        if entry is None or entry.company_id != company_id:
            return
        draft_status = session.scalar(select(JournalEntryStatus).where(JournalEntryStatus.code == "DRAFT"))
        entry.status_id = draft_status.status_id
        audit_service.log_activity(
            session,
            company_id=company_id,
            user_id=rejected_by_user_id,
            entity_type="JournalEntry",
            entity_id=source_record_id,
            action="UPDATE",
            changes={"after": {"status": "DRAFT", "rejection_reason": reason}},
        )
        session.commit()


def _cartable_describe(company_id: int, source_record_id: int) -> str:
    with new_session() as session:
        entry = session.get(JournalEntry, source_record_id)
        if entry is None or entry.company_id != company_id:
            return f"سندِ حسابداری #{source_record_id}"
        return f"سندِ حسابداری موقتِ شماره‌ی {numerals.to_persian_digits(str(entry.temporary_no))} — {entry.description or 'بدونِ شرح'}"


def _register_cartable_handler() -> None:
    from peecha.services import cartable as cartable_service

    cartable_service.register_handler(
        "journal_entry",
        on_approved=_cartable_on_approved,
        on_rejected=_cartable_on_rejected,
        describe=_cartable_describe,
    )


_register_cartable_handler()
