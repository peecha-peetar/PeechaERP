"""ابزارهای پردازش ورودی عددی/تاریخی فارسی.

کاربر فارسی‌زبان معمولاً ارقام فارسی (۰۱۲۳...) یا عربی (٠١٢٣...) تایپ
می‌کند، اما Decimal و jdatetime پایتون فقط ارقام ASCII را می‌پذیرند؛ پس
هر ورودی کاربر قبل از پردازش باید از این تابع عبور کند.
"""

from __future__ import annotations

import datetime
import decimal

import jdatetime

_PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
_ARABIC_DIGITS = "٠١٢٣٤٥٦٧٨٩"
_ASCII_DIGITS = "0123456789"
_TO_ASCII_MAP = str.maketrans(_PERSIAN_DIGITS + _ARABIC_DIGITS, _ASCII_DIGITS * 2)
_TO_PERSIAN_MAP = str.maketrans(_ASCII_DIGITS, _PERSIAN_DIGITS)


def to_ascii_digits(text: str) -> str:
    return text.translate(_TO_ASCII_MAP)


def to_persian_digits(text: str) -> str:
    """برعکسِ to_ascii_digits — برای نمایش (نه پردازش/ذخیره‌سازی)."""
    return text.translate(_TO_PERSIAN_MAP)


def format_amount(value: decimal.Decimal | int) -> str:
    return to_persian_digits(f"{value:,}")


def format_money(value: decimal.Decimal | int, decimal_places: int = 0, symbol: str | None = None) -> str:
    """نمایشِ مبلغ برایِ ارزِ فعالِ شرکت — تعدادِ رقمِ اعشار طبقِ تنظیماتِ
    همان ارز (نه یک عددِ ثابت)، با گروه‌بندیِ سه‌رقمی و ارقامِ فارسی."""
    quant = decimal.Decimal(1).scaleb(-decimal_places) if decimal_places > 0 else decimal.Decimal(1)
    quantized = decimal.Decimal(value).quantize(quant, rounding=decimal.ROUND_HALF_UP)
    text = to_persian_digits(f"{quantized:,}")
    return f"{text} {symbol}" if symbol else text


def format_company_amount(value: decimal.Decimal | int, symbol: str | None = None) -> str:
    """نمایشِ مبلغ طبقِ تعدادِ رقمِ اعشارِ ارزِ پایه‌یِ *شرکتِ جاری*ِ سشن --
    برایِ جاهایی که استفاده از format_money با پاس‌دادنِ دستیِ
    decimal_places در هر محل عملی نیست (مثلاً یک ستونِ جدول در یک حلقه).
    فقط برایِ مبالغِ واقعیِ پولی استفاده شود -- نرخِ ارز/درصد/کمیت را با
    format_amount یا فرمتِ اختصاصیِ خودشان نشان بده، نه این تابع را، چون
    آن‌ها معمولاً نیازمندِ دقتِ اعشاریِ متفاوتی از ارزِ پایه‌اند."""
    from peecha import session as app_session
    from peecha.services import companies as companies_service

    decimal_places = 0
    if app_session.current_company is not None:
        decimal_places = companies_service.get_base_currency_decimal_places(app_session.current_company.company_id)
    return format_money(value, decimal_places, symbol)


def parse_decimal(text: str) -> decimal.Decimal:
    normalized = to_ascii_digits(text).strip().replace(",", "")
    if not normalized:
        return decimal.Decimal(0)
    try:
        return decimal.Decimal(normalized)
    except decimal.InvalidOperation as exc:
        raise ValueError(f"مقدار عددی نامعتبر: {text}") from exc


def parse_jalali_date(text: str) -> datetime.date:
    normalized = to_ascii_digits(text).strip().replace("-", "/")
    parts = normalized.split("/")
    if len(parts) != 3:
        raise ValueError("تاریخ باید به‌صورت ۱۴۰۳/۰۴/۲۸ وارد شود.")
    try:
        year, month, day = (int(p) for p in parts)
        return jdatetime.date(year, month, day).togregorian()
    except ValueError as exc:
        raise ValueError("تاریخ باید به‌صورت ۱۴۰۳/۰۴/۲۸ وارد شود.") from exc


def format_jalali_date(value: datetime.date) -> str:
    return to_persian_digits(jdatetime.date.fromgregorian(date=value).strftime("%Y/%m/%d"))


def format_jalali_datetime(value: datetime.datetime) -> str:
    """تاریخ+ساعتِ محلی — برای ردیف‌های ردِ حسابرسی که به‌ثانیه اهمیت دارند."""
    local_value = value.astimezone() if value.tzinfo is not None else value
    date_part = jdatetime.date.fromgregorian(date=local_value.date()).strftime("%Y/%m/%d")
    return to_persian_digits(f"{date_part} {local_value.strftime('%H:%M')}")


_ONES_WORDS = ["", "یک", "دو", "سه", "چهار", "پنج", "شش", "هفت", "هشت", "نه"]
_TEENS_WORDS = [
    "ده", "یازده", "دوازده", "سیزده", "چهارده", "پانزده", "شانزده", "هفده", "هجده", "نوزده",
]
_TENS_WORDS = ["", "", "بیست", "سی", "چهل", "پنجاه", "شصت", "هفتاد", "هشتاد", "نود"]
_HUNDREDS_WORDS = [
    "", "صد", "دویست", "سیصد", "چهارصد", "پانصد", "ششصد", "هفتصد", "هشتصد", "نهصد",
]
_SCALE_WORDS = ["", "هزار", "میلیون", "میلیارد", "تریلیون", "کوادریلیون"]


def _three_digit_group_to_words(n: int) -> str:
    parts = []
    hundreds, remainder = divmod(n, 100)
    if hundreds:
        parts.append(_HUNDREDS_WORDS[hundreds])
    if 10 <= remainder <= 19:
        parts.append(_TEENS_WORDS[remainder - 10])
    else:
        tens, ones = divmod(remainder, 10)
        if tens:
            parts.append(_TENS_WORDS[tens])
        if ones:
            parts.append(_ONES_WORDS[ones])
    return " و ".join(parts)


def number_to_words(n: int) -> str:
    """عددِ صحیحِ غیرمنفی را به حروفِ فارسی تبدیل می‌کند (مثلاً ۱۲۵۰۰۰ →
    «صد و بیست و پنج هزار»)."""
    if n < 0:
        return "منفی " + number_to_words(-n)
    if n == 0:
        return "صفر"

    groups: list[int] = []
    remaining = n
    while remaining > 0:
        groups.append(remaining % 1000)
        remaining //= 1000
    if len(groups) > len(_SCALE_WORDS):
        # عددی بزرگ‌تر از بزرگ‌ترین مقیاسِ پشتیبانی‌شده — به رقم برمی‌گردیم
        # تا خطا ندهد (این حجم مبلغ در عمل پیش نمی‌آید).
        return to_persian_digits(str(n))

    parts = []
    for index in reversed(range(len(groups))):
        group_value = groups[index]
        if group_value == 0:
            continue
        words = _three_digit_group_to_words(group_value)
        if index > 0:
            words += " " + _SCALE_WORDS[index]
        parts.append(words)
    return " و ".join(parts)


def amount_to_words(value: decimal.Decimal | int, *, unit: str = "ریال") -> str:
    """مبلغ به حروف — برای نمایشِ زنده‌ی زیرِ فیلدهای مبلغ. بخشِ اعشاری
    (اگر باشد) جداگانه به حروف اضافه می‌شود."""
    value = decimal.Decimal(value)
    if value == 0:
        return f"{number_to_words(0)} {unit}".strip()
    is_negative = value < 0
    value = abs(value)
    integer_part = int(value)
    fractional_part = value - integer_part

    words = number_to_words(integer_part)
    if fractional_part:
        # بخشِ اعشاری را به‌صورتِ عددِ صحیحِ سمتِ راستِ ممیز به حروف
        # می‌بریم (مثلاً ۱۲۵۰.۵۰ → «... و پنجاه صدم»).
        scale = fractional_part.as_tuple().exponent
        digits_after_point = -scale if scale < 0 else 0
        fractional_int = int((fractional_part * (10**digits_after_point)).to_integral_value())
        if fractional_int:
            denom_words = {1: "دهم", 2: "صدم", 3: "هزارم"}.get(digits_after_point, "")
            words += f" و {number_to_words(fractional_int)} {denom_words}".rstrip()

    result = f"{words} {unit}".strip()
    return f"منفی {result}" if is_negative else result
