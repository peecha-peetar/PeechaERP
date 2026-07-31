"""سرویسِ چندارزی: فهرستِ سراسریِ ارزها (core.currencies)، ارزهای فعالِ هر
شرکت (core.company_currencies) و نرخِ روزانه‌ی تبدیل به ارزِ پایه
(core.exchange_rates).

ارزِ پایه‌ی هر شرکت (Company.base_currency_id) همیشه با نرخِ ۱ محاسبه
می‌شود و نیازی به ثبتِ نرخ ندارد؛ فقط برای ارزهای غیرِپایه که شرکت آن‌ها
را فعال کرده باشد، نرخِ روزانه لازم است."""

from __future__ import annotations

import datetime
import decimal
from dataclasses import dataclass

from sqlalchemy import func, select

from peecha.db.base import new_session
from peecha.db.models.accounting import ChartOfAccount, JournalEntryLine
from peecha.db.models.core import Company, CompanyCurrency, Currency, ExchangeRate


@dataclass
class CurrencyRow:
    currency_id: int
    iso_code: str
    symbol: str | None
    decimal_places: int
    is_active: bool


@dataclass
class CompanyCurrencyRow:
    currency_id: int
    iso_code: str
    is_base: bool
    is_enabled: bool


@dataclass
class ExchangeRateRow:
    exchange_rate_id: int
    rate_date: datetime.date
    rate_to_base: decimal.Decimal


def list_all_currencies() -> list[CurrencyRow]:
    with new_session() as session:
        rows = session.scalars(select(Currency).order_by(Currency.iso_code)).all()
        return [
            CurrencyRow(
                currency_id=c.currency_id,
                iso_code=c.iso_code,
                symbol=c.symbol,
                decimal_places=c.decimal_places,
                is_active=c.is_active,
            )
            for c in rows
        ]


def create_currency(iso_code: str, symbol: str | None, decimal_places: int) -> Currency:
    if decimal_places < 0 or decimal_places > 6:
        raise ValueError("رقم اعشار باید بین ۰ تا ۶ باشد.")
    iso_code = iso_code.strip().upper()
    with new_session() as session:
        if session.scalar(select(Currency).where(Currency.iso_code == iso_code)):
            raise ValueError("این کدِ ارز قبلاً تعریف شده است.")
        currency = Currency(iso_code=iso_code, symbol=(symbol or None), decimal_places=decimal_places, is_active=True)
        session.add(currency)
        session.commit()
        session.refresh(currency)
        session.expunge(currency)
        return currency


def update_currency(currency_id: int, iso_code: str, symbol: str | None, decimal_places: int, is_active: bool) -> None:
    if decimal_places < 0 or decimal_places > 6:
        raise ValueError("رقم اعشار باید بین ۰ تا ۶ باشد.")
    iso_code = iso_code.strip().upper()
    with new_session() as session:
        currency = session.get(Currency, currency_id)
        if currency is None:
            raise ValueError("ارز نامعتبر است.")
        duplicate = session.scalar(
            select(Currency).where(Currency.iso_code == iso_code, Currency.currency_id != currency_id)
        )
        if duplicate is not None:
            raise ValueError("این کدِ ارز قبلاً تعریف شده است.")
        currency.iso_code = iso_code
        currency.symbol = symbol or None
        currency.decimal_places = decimal_places
        currency.is_active = is_active
        session.commit()


def delete_currency(currency_id: int) -> None:
    with new_session() as session:
        currency = session.get(Currency, currency_id)
        if currency is None:
            raise ValueError("ارز نامعتبر است.")

        base_of_company = session.scalar(
            select(func.count()).select_from(Company).where(Company.base_currency_id == currency_id)
        )
        if base_of_company:
            raise ValueError("این ارز، ارزِ پایه‌ی یک یا چند شرکت است؛ قابل حذف نیست.")

        used_in_accounts = session.scalar(
            select(func.count()).select_from(ChartOfAccount).where(ChartOfAccount.currency_id == currency_id)
        )
        if used_in_accounts:
            raise ValueError("این ارز روی یک یا چند حسابِ کدینگ تنظیم شده؛ قابل حذف نیست.")

        used_in_lines = session.scalar(
            select(func.count()).select_from(JournalEntryLine).where(JournalEntryLine.currency_id == currency_id)
        )
        if used_in_lines:
            raise ValueError("این ارز در سندهای حسابداری استفاده شده؛ قابل حذف نیست.")

        session.execute(CompanyCurrency.__table__.delete().where(CompanyCurrency.currency_id == currency_id))
        session.execute(ExchangeRate.__table__.delete().where(ExchangeRate.currency_id == currency_id))
        session.delete(currency)
        session.commit()


def list_company_currencies(company_id: int) -> list[CompanyCurrencyRow]:
    """همه‌ی ارزهای فعالِ سراسری (به‌جز ارزِ پایه‌ی همین شرکت که همیشه
    ضمنی فعال است) + وضعیتِ فعال/غیرفعال‌بودنِ هرکدام برایِ این شرکتِ خاص."""
    with new_session() as session:
        company = session.get(Company, company_id)
        if company is None:
            return []
        currencies = session.scalars(
            select(Currency).where(Currency.is_active).order_by(Currency.iso_code)
        ).all()
        enabled_ids = set(
            session.scalars(
                select(CompanyCurrency.currency_id).where(
                    CompanyCurrency.company_id == company_id, CompanyCurrency.is_active.is_(True)
                )
            ).all()
        )
        return [
            CompanyCurrencyRow(
                currency_id=c.currency_id,
                iso_code=c.iso_code,
                is_base=c.currency_id == company.base_currency_id,
                is_enabled=c.currency_id == company.base_currency_id or c.currency_id in enabled_ids,
            )
            for c in currencies
        ]


def set_company_currency(company_id: int, currency_id: int, is_active: bool) -> None:
    with new_session() as session:
        company = session.get(Company, company_id)
        if company is None:
            raise ValueError("شرکت نامعتبر است.")
        if currency_id == company.base_currency_id:
            return  # ارزِ پایه همیشه ضمنی فعال است؛ نیازی به ردیفِ جدا ندارد
        row = session.get(CompanyCurrency, (company_id, currency_id))
        if row is None:
            session.add(CompanyCurrency(company_id=company_id, currency_id=currency_id, is_active=is_active))
        else:
            row.is_active = is_active
        session.commit()


def list_transactable_currencies(company_id: int) -> list[CurrencyRow]:
    """ارزِ پایه + ارزهای غیرِپایه‌ای که شرکت فعال کرده — برای انتخابگرِ
    ارزِ ردیفِ سند."""
    with new_session() as session:
        company = session.get(Company, company_id)
        if company is None:
            return []
        enabled_ids = set(
            session.scalars(
                select(CompanyCurrency.currency_id).where(
                    CompanyCurrency.company_id == company_id, CompanyCurrency.is_active.is_(True)
                )
            ).all()
        )
        enabled_ids.add(company.base_currency_id)
        currencies = session.scalars(
            select(Currency)
            .where(Currency.currency_id.in_(enabled_ids), Currency.is_active.is_(True))
            .order_by(Currency.iso_code)
        ).all()
        return [
            CurrencyRow(
                currency_id=c.currency_id,
                iso_code=c.iso_code,
                symbol=c.symbol,
                decimal_places=c.decimal_places,
                is_active=c.is_active,
            )
            for c in currencies
        ]


def list_exchange_rates(company_id: int, currency_id: int) -> list[ExchangeRateRow]:
    with new_session() as session:
        rows = session.scalars(
            select(ExchangeRate)
            .where(ExchangeRate.company_id == company_id, ExchangeRate.currency_id == currency_id)
            .order_by(ExchangeRate.rate_date.desc())
        ).all()
        return [
            ExchangeRateRow(exchange_rate_id=r.exchange_rate_id, rate_date=r.rate_date, rate_to_base=r.rate_to_base)
            for r in rows
        ]


def set_exchange_rate(company_id: int, currency_id: int, rate_date: datetime.date, rate_to_base: decimal.Decimal) -> None:
    if rate_to_base <= 0:
        raise ValueError("نرخِ تبدیل باید بزرگ‌تر از صفر باشد.")
    with new_session() as session:
        existing = session.scalar(
            select(ExchangeRate).where(
                ExchangeRate.company_id == company_id,
                ExchangeRate.currency_id == currency_id,
                ExchangeRate.rate_date == rate_date,
            )
        )
        if existing is None:
            session.add(
                ExchangeRate(
                    company_id=company_id, currency_id=currency_id, rate_date=rate_date, rate_to_base=rate_to_base
                )
            )
        else:
            existing.rate_to_base = rate_to_base
        session.commit()


def delete_exchange_rate(exchange_rate_id: int, company_id: int) -> None:
    with new_session() as session:
        rate = session.get(ExchangeRate, exchange_rate_id)
        if rate is None or rate.company_id != company_id:
            raise ValueError("نرخِ ارز نامعتبر است.")
        session.delete(rate)
        session.commit()


def get_latest_rate(company_id: int, currency_id: int, on_date: datetime.date) -> decimal.Decimal | None:
    """آخرین نرخِ ثبت‌شده در همان روز یا قبل‌تر از آن — برای پیش‌پرکردنِ
    خودکارِ نرخِ ردیفِ سند وقتی تاریخِ سند/ارز مشخص می‌شود."""
    with new_session() as session:
        return session.scalar(
            select(ExchangeRate.rate_to_base)
            .where(
                ExchangeRate.company_id == company_id,
                ExchangeRate.currency_id == currency_id,
                ExchangeRate.rate_date <= on_date,
            )
            .order_by(ExchangeRate.rate_date.desc())
            .limit(1)
        )


def _http_get_json(url: str, timeout: float = 8.0) -> dict:
    """جداشده از fetch_live_rate تا در تست بدونِ اتصالِ واقعیِ اینترنت
    قابلِ monkeypatch باشد."""
    import json
    import urllib.request

    request = urllib.request.Request(url, headers={"User-Agent": "PeechaERP/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_live_rate(base_iso_code: str, target_iso_code: str) -> decimal.Decimal:
    """نرخِ «۱ واحدِ ارزِ مقصد = چند واحدِ ارزِ پایه» را از یک سرویسِ عمومیِ
    رایگانِ نرخِ ارز می‌گیرد (بدونِ نیازِ به کلیدِ API).

    محدودیتِ صادقانه: این سرویس‌هایِ عمومی معمولاً نرخِ رسمی/بینِ‌بانکی
    را می‌دهند، نه نرخِ بازارِ آزادِ ایران — برایِ ریال ممکن است در دسترس
    نباشد یا با نرخِ واقعیِ بازار خیلی فرق داشته باشد. این تابع همیشه
    فقط یک عددِ پیشنهادی برمی‌گرداند؛ کاربر باید قبل از ثبت آن را
    بررسی/ویرایش کند."""
    url = f"https://open.er-api.com/v6/latest/{target_iso_code.upper()}"
    try:
        data = _http_get_json(url)
    except Exception as exc:
        raise ValueError(f"دریافتِ نرخ از اینترنت ناموفق بود: {exc}") from exc
    if data.get("result") != "success":
        raise ValueError("سرویسِ نرخِ ارز پاسخِ نامعتبر داد.")
    rates = data.get("rates") or {}
    rate = rates.get(base_iso_code.upper())
    if rate is None:
        raise ValueError(f"نرخِ «{base_iso_code}» در پاسخِ سرویس پیدا نشد؛ ممکن است این ارز پشتیبانی نشود.")
    try:
        return decimal.Decimal(str(rate))
    except decimal.InvalidOperation as exc:
        raise ValueError("سرویسِ نرخِ ارز عددِ نامعتبر برگرداند.") from exc


_NAVASAN_URL = "http://api.navasan.tech/latest/"


def fetch_navasan_rate(api_key: str, item_key: str) -> decimal.Decimal:
    """نرخِ یک آیتمِ مشخص (مثلاً بازارِ آزادِ دلار یا دلارِ دولتی/نیمایی)
    را از سرویسِ اختصاصیِ ایرانیِ navasan.tech می‌گیرد — طبقِ درخواستِ
    صریح، بر خلافِ fetch_live_rate، این سرویس امکانِ تفکیکِ نرخِ بازارِ
    آزاد از نرخِ دولتی را دارد (بسته به نوعِ آیتمِ انتخابی).

    محدودیتِ صادقانه: نام‌گذاریِ دقیقِ آیتم‌ها (مثلِ usd_sell) بینِ
    پلن‌هایِ مختلفِ navasan.tech ممکن است فرق داشته باشد و این تابع
    آن را حدس نمی‌زند — کلیدِ دقیق را باید از داشبوردِ حسابِ خودتان در
    navasan.tech بردارید."""
    if not api_key:
        raise ValueError("کلیدِ API را وارد کنید.")
    if not item_key:
        raise ValueError("کلیدِ آیتمِ نرخ (مثلاً usd_sell) را وارد کنید.")
    url = f"{_NAVASAN_URL}?api_key={api_key}"
    try:
        data = _http_get_json(url)
    except Exception as exc:
        raise ValueError(f"دریافتِ نرخ از navasan.tech ناموفق بود: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("سرویسِ navasan.tech پاسخِ نامعتبر داد.")
    item = data.get(item_key)
    if item is None:
        raise ValueError(
            f"آیتمِ «{item_key}» در پاسخِ navasan.tech پیدا نشد — کلیدِ دقیق را از داشبوردِ حسابِ خودتان بردارید."
        )
    value = item.get("value") if isinstance(item, dict) else item
    try:
        return decimal.Decimal(str(value).replace(",", "").strip())
    except decimal.InvalidOperation as exc:
        raise ValueError("navasan.tech عددِ نامعتبر برگرداند.") from exc
