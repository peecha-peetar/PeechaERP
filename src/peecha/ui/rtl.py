"""پشتیبانی فارسی/عربی برای Kivy.

نکته‌ی مهم فنی: بر خلاف فریم‌ورک‌هایی مثل Qt یا Flutter، Kivy از RTL و
شکل‌دهی حروف فارسی/عربی (letter shaping/joining) به‌صورت بومی پشتیبانی
نمی‌کند — یک Label ساده در Kivy حروف را جدا از هم و به ترتیب اشتباه نشان
می‌دهد. برای همین هر متن فارسی/عربی قبل از نمایش باید از `shape()` عبور
کند (ترکیب arabic_reshaper + python-bidi، الگوی استاندارد جامعه‌ی Kivy
برای این مشکل). این یک محدودیت واقعی فریم‌ورک انتخاب‌شده است، نه یک جزئیات
پیاده‌سازی قابل چشم‌پوشی.

نکته‌ی دوم (خاصِ ویندوز): بسته‌ی kivy_deps.sdl2 روی ویندوز یک SDL2_ttf
با HarfBuzزِ داخلی همراه می‌آورد که خودش هم حروفِ فارسی/عربی را می‌چسباند
و هم (وقتی صریحاً `font_direction="rtl"` + `font_script_name="Arab"` روی
ویجت ست شده باشد — طبق app.py/widgets.kv) جهتِ متن را برمی‌گرداند. این
تأییدشده با چند دور تستِ واقعی روی Kivy 2.3.1 + kivy_deps.sdl2 0.8.0:
  - متنِ خام + بدونِ این دو ویژگی: حروف چسبیده ولی جهت برعکس.
  - متنِ ازقبل با `arabic_reshaper`+`get_display` آماده‌شده (پایپ‌لاینِ
    زیر) + بدونِ این دو ویژگی: HarfBuzz دوباره روی متنِ ازقبل‌چسبیده/
    ازقبل‌برگشته کار می‌کند و کاملاً به‌هم می‌ریزد یا حروف را جدا می‌کند.
  - متنِ خام + `font_direction="rtl"` + `font_script_name="Arab"`: هم
    چسبیدنِ درست، هم جهتِ درست — تنها حالتِ درست روی ویندوز.
برای همین روی ویندوز `shape()` اصلاً دست به متن نمی‌زند (کارِ چسباندن/
برگرداندنِ جهت را کاملاً به Kivy/HarfBuzz — با آن دو ویژگیِ ست‌شده در
widgets.kv/widgets.py — می‌سپارد)؛ روی بقیه‌ی سیستم‌عامل‌ها (بدونِ
HarfBuzزِ خودکار) پایپ‌لاینِ دستیِ قبلی بدونِ تغییر باقی می‌ماند.
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
        return text
    return get_display(_reshaper.reshape(text))
