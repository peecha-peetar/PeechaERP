"""پشتیبانی فارسی/عربی برای Kivy.

نکته‌ی مهم فنی: بر خلاف فریم‌ورک‌هایی مثل Qt یا Flutter، Kivy از RTL و
شکل‌دهی حروف فارسی/عربی (letter shaping/joining) به‌صورت بومی پشتیبانی
نمی‌کند — یک Label ساده در Kivy حروف را جدا از هم و به ترتیب اشتباه نشان
می‌دهد. برای همین هر متن فارسی/عربی قبل از نمایش باید از `shape()` عبور
کند (ترکیب arabic_reshaper + python-bidi، الگوی استاندارد جامعه‌ی Kivy
برای این مشکل). این یک محدودیت واقعی فریم‌ورک انتخاب‌شده است، نه یک جزئیات
پیاده‌سازی قابل چشم‌پوشی.

نکته‌ی دوم (خاصِ ویندوز): بسته‌ی kivy_deps.sdl2 روی ویندوز یک SDL2_ttf
با HarfBuzزِ داخلی همراه می‌آورد که خودش هم حروفِ فارسی/عربی را به‌درستی
می‌چسباند (بر خلافِ لینوکس که معمولاً SDL2_ttf سیستم بدونِ HarfBuzz است).
اگر رویِ ویندوز metن را با `arabic_reshaper` هم از قبل بچسبانیم، همان
چسباندن دوباره توسطِ HarfBuzz روی حروفِ از‌قبل‌چسبیده انجام می‌شود و کاملاً
به‌هم می‌ریزد (تأییدشده با تستِ واقعی روی Kivy 2.3.1 + kivy_deps.sdl2
0.8.0). چسباندنِ خودِ HarfBuzz جهتِ متن را برنمی‌گرداند، پس مرحله‌ی
`get_display` (فقط برگرداندنِ جهت، بدونِ `reshape`) همچنان لازم است. برای
همین: روی ویندوز فقط `get_display` صدا زده می‌شود، روی بقیه‌ی
سیستم‌عامل‌ها (که HarfBuzزِ خودکار ندارند) هر دو مرحله مثلِ قبل.
"""

from __future__ import annotations

import arabic_reshaper
from bidi.algorithm import get_display
from kivy.utils import platform

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
    if platform == "win":
        return get_display(text)
    return get_display(_reshaper.reshape(text))
