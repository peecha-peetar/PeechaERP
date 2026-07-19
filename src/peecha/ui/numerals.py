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
_DIGIT_MAP = str.maketrans(_PERSIAN_DIGITS + _ARABIC_DIGITS, _ASCII_DIGITS * 2)


def to_ascii_digits(text: str) -> str:
    return text.translate(_DIGIT_MAP)


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
    return jdatetime.date.fromgregorian(date=value).strftime("%Y/%m/%d")
