"""پشتیبانی فارسی/عربی برای Kivy.

نکته‌ی مهم فنی: بر خلاف فریم‌ورک‌هایی مثل Qt یا Flutter، Kivy از RTL و
شکل‌دهی حروف فارسی/عربی (letter shaping/joining) به‌صورت بومی پشتیبانی
نمی‌کند — یک Label ساده در Kivy حروف را جدا از هم و به ترتیب اشتباه نشان
می‌دهد. برای همین هر متن فارسی/عربی قبل از نمایش باید از `shape()` عبور
کند (ترکیب arabic_reshaper + python-bidi، الگوی استاندارد جامعه‌ی Kivy
برای این مشکل). این یک محدودیت واقعی فریم‌ورک انتخاب‌شده است، نه یک جزئیات
پیاده‌سازی قابل چشم‌پوشی.
"""

from __future__ import annotations

import arabic_reshaper
from bidi.algorithm import get_display

_reshaper = arabic_reshaper.ArabicReshaper(
    configuration={
        "delete_harakat": False,
        "support_ligatures": True,
    }
)


def shape(text: str) -> str:
    """متن فارسی/عربی را برای نمایش صحیح در Kivy آماده می‌کند.

    برای متن خالص لاتین/عددی بی‌اثر است، پس صدا زدنش روی هر رشته‌ای امن است.
    """
    if not text:
        return text
    return get_display(_reshaper.reshape(text))
