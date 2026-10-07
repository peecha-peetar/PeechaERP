"""R279: تعداد رقم اعشار مقدار (طبق واحد) و مبلغ (طبق ارز پایهٔ شرکت) — یک مرجع برای همهٔ فرم‌ها و گزارش‌ها.

مقادیر از تنظیمات «واحدهای اندازه‌گیری» و «ارزها» خوانده و چند ثانیه نگه داشته می‌شوند تا جدول‌های
بزرگ برای هر سلول به دیتابیس نروند؛ پس از ویرایش تنظیمات، حداکثر پس از چند ثانیه اثر می‌کند."""

from __future__ import annotations

import decimal
import time

from sqlalchemy import select

_TTL_SECONDS = 5.0
_MAX_DECIMALS = 6
_cache: dict[tuple, tuple[float, object]] = {}


def _cached(key: tuple, loader):
    now = time.monotonic()
    hit = _cache.get(key)
    if hit is not None and now - hit[0] < _TTL_SECONDS:
        return hit[1]
    value = loader()
    _cache[key] = (now, value)
    return value


def invalidate() -> None:
    _cache.clear()


def _company_id(company_id: int | None) -> int | None:
    if company_id is not None:
        return company_id
    from peecha import session as app_session

    return app_session.current_company.company_id if app_session.current_company is not None else None


def uom_decimals_map(company_id: int | None = None) -> dict[int, int]:
    """uom_id → تعداد رقم اعشار مجاز (واحدی که اعشار ندارد = ۰)."""
    cid = _company_id(company_id)

    def load() -> dict[int, int]:
        from peecha.db.base import new_session
        from peecha.db.models.inventory import Uom

        with new_session() as session:
            query = select(Uom.uom_id, Uom.decimal_places, Uom.allow_decimal)
            if cid is not None:
                query = query.where((Uom.company_id == cid) | (Uom.company_id.is_(None)))
            return {uid: (dp if allow and dp else 0) for uid, dp, allow in session.execute(query)}

    return _cached(("uom", cid), load)


def item_base_uom_map(company_id: int | None = None) -> dict[int, int]:
    """item_id → base_uom_id."""
    cid = _company_id(company_id)

    def load() -> dict[int, int]:
        from peecha.db.base import new_session
        from peecha.db.models.inventory import Item

        with new_session() as session:
            query = select(Item.item_id, Item.base_uom_id)
            if cid is not None:
                query = query.where(Item.company_id == cid)
            return {iid: uid for iid, uid in session.execute(query) if uid is not None}

    return _cached(("item_uom", cid), load)


def qty_decimals(uom_id: int | None = None, item_id: int | None = None, default: int | None = None) -> int | None:
    """اعشار مقدار: اول واحد انتخاب‌شده، بعد واحد پایهٔ کالا؛ اگر هیچ‌کدام معلوم نبود، default."""
    if uom_id is None and item_id is not None:
        uom_id = item_base_uom_map().get(item_id)
        if uom_id is None:  # کالای تازه‌ساخت هنوز در حافظهٔ موقت نیست
            _cache.pop(("item_uom", _company_id(None)), None)
            uom_id = item_base_uom_map().get(item_id)
    if uom_id is not None:
        found = uom_decimals_map().get(uom_id)
        if found is not None:
            return found
    return default


def money_decimals(company_id: int | None = None) -> int:
    cid = _company_id(company_id)
    if cid is None:
        return 0

    def load() -> int:
        from peecha.services import companies as companies_service

        return companies_service.get_base_currency_decimal_places(cid)

    return _cached(("money", cid), load)


def quantize(value, decimals: int) -> decimal.Decimal:
    quant = decimal.Decimal(1).scaleb(-decimals) if decimals > 0 else decimal.Decimal(1)
    return decimal.Decimal(value).quantize(quant, rounding=decimal.ROUND_HALF_UP)


def trimmed_decimals(value) -> int:
    """کمترین تعداد اعشاری که مقدار واقعاً دارد (۵٫۰۰۰ → ۰، ۲٫۵۰ → ۱)."""
    normalized = decimal.Decimal(value).normalize()
    exponent = normalized.as_tuple().exponent
    return min(_MAX_DECIMALS, max(0, -exponent)) if isinstance(exponent, int) else 0


def format_qty(value, uom_id: int | None = None, item_id: int | None = None, decimals: int | None = None) -> str:
    """نمایش مقدار با اعشار واحد آن؛ اگر واحد معلوم نیست، بدون صفرهای اضافهٔ انتهایی."""
    from peecha import numerals

    if value is None or value == "":
        return ""
    if decimals is None:
        decimals = qty_decimals(uom_id, item_id)
    if decimals is None:
        decimals = trimmed_decimals(value)
    return numerals.format_money(value, decimals)


def format_amount(value) -> str:
    """مبلغ با اعشار ارز پایهٔ شرکت."""
    from peecha import numerals

    if value is None or value == "":
        return ""
    return numerals.format_money(value, money_decimals())


def plain(value, decimals: int | None = None) -> str:
    """عدد برای فیلد قابل ویرایش: بدون جداکنندهٔ هزارگان و بدون نماد علمی (۱۰۰ نه 1E+2)، با ارقام فارسی."""
    from peecha import numerals

    if value is None or value == "":
        return ""
    number = decimal.Decimal(value)
    if decimals is None:
        decimals = trimmed_decimals(number)
    return numerals.to_persian_digits(f"{quantize(number, decimals):f}")
