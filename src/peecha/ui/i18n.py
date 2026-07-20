"""ترجمه‌ی متن‌های ثابتِ رابط کاربری (عنوانِ فرم‌ها، دکمه‌ها، برچسب‌ها،
پیام‌ها) — نه اطلاعاتِ واردشده‌ی کاربر (نامِ حساب/شرکت/کاربر و مانند آن؛
آن‌ها همیشه دقیقاً همان‌طور که کاربر تایپ کرده باقی می‌مانند).

طبق درخواستِ صریح:
  ۱. وقتی زبانی ساخته می‌شود، خودکار ترجمه شود.
  ۲. ترجمه‌ها در فایل‌های جداگانه (نه فقط دیتابیس) ذخیره شوند تا بعداً با
     ویرایشِ همان فایل قابل‌اصلاح باشند.
  ۳. اگر بعداً فرم/متنِ تازه‌ای اضافه شود، هم به فایلِ منبع (فارسی) و هم
     به فایلِ هر زبانِ دیگری که تعریف شده افزوده شود، تا چیزی از قلم
     نیفتد (حتی اگر ترجمه‌ی واقعی‌اش را بعداً کسی/چیزی اصلاح کند).

معماری: کلیدِ ترجمه خودِ متنِ منبعِ فارسی است (الگوی gettext) — نه یک
کلیدِ دلخواهِ جداگانه — چون این‌طوری وصل‌کردنِ tr() به کدِ موجود فقط یک
پیچیدنِ ساده‌ی shape("متن") → shape(tr("متن")) است، بدونِ نیاز به
نگه‌داریِ نگاشتِ کلید↔متن در جای دیگر.

فایل‌ها در src/peecha/locales/<کدِ زبان>.json — یک دیکشنریِ تخت
{"متنِ فارسی": "ترجمه"}. زبانِ پیش‌فرض (فارسی) فایلی ندارد چون ترجمه‌اش
خودِ متن است؛ اما هر متنِ تازه‌ای که از tr() عبور کند در یک فایلِ
«فهرستِ منبع» (_source.json) هم ثبت می‌شود تا هنگامِ ساختِ زبانِ بعدی،
هیچ رشته‌ای جا نیفتد.
"""

from __future__ import annotations

import json
import os
import threading

from kivy.clock import Clock

from peecha import session

_LOCALES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "locales")
_SOURCE_CATALOG_PATH = os.path.join(_LOCALES_DIR, "_source.json")

_lock = threading.Lock()
_catalog_cache: dict[str, dict[str, str]] = {}
_source_cache: dict[str, str] | None = None

# ثبتِ خودکارِ رشته‌ها (اولین‌بار که tr() یک متنِ تازه می‌بیند) قبلاً هر بار
# بلافاصله کلِ فایلِ کاتالوگ را روی دیسک می‌نوشت — چون tr() از داخلِ صدها
# بایندینگِ KV در یک ساخت‌وسازِ دسته‌ایِ صفحه‌ها (مثلاً بالا آمدنِ برنامه)
# پشت‌سرهم صدا زده می‌شود، این یعنی ده‌ها نوشتنِ همزمانِ دیسک روی خودِ ترد UI
# — که علتِ هنگ‌کردنِ محسوسِ برنامه بود. راه‌حل: فقط در حافظه علامت‌گذاری کن و
# نوشتنِ واقعی را با یک تاخیرِ کوتاه دسته‌ای کن (debounce) تا این انفجارِ
# نوشتن به یک نوشتنِ واحد تبدیل شود.
_dirty_source = False
_dirty_languages: set[str] = set()
_flush_event = None


def _schedule_flush() -> None:
    global _flush_event
    if _flush_event is not None:
        _flush_event.cancel()
    _flush_event = Clock.schedule_once(_flush_dirty, 0.3)


def _flush_dirty(_dt: float | None = None) -> None:
    global _dirty_source, _flush_event
    _flush_event = None
    with _lock:
        if _dirty_source:
            _write_json(_SOURCE_CATALOG_PATH, _source_cache or {})
            _dirty_source = False
        for code in _dirty_languages:
            _write_json(_catalog_path(code), _catalog_cache.get(code, {}))
        _dirty_languages.clear()


def flush_now() -> None:
    """نوشتنِ فوریِ هر تغییرِ معوق — برای فراخوانی صریح قبلِ بستنِ برنامه."""
    if _flush_event is not None:
        _flush_event.cancel()
    _flush_dirty()


def _catalog_path(language_code: str) -> str:
    return os.path.join(_LOCALES_DIR, f"{language_code}.json")


def _read_json(path: str) -> dict[str, str]:
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _write_json(path: str, data: dict[str, str]) -> None:
    os.makedirs(_LOCALES_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)


def _load_source_catalog() -> dict[str, str]:
    global _source_cache
    if _source_cache is None:
        _source_cache = _read_json(_SOURCE_CATALOG_PATH)
    return _source_cache


def _register_source_string(text: str) -> None:
    """هر متنِ فارسیِ تازه‌ای که از tr() عبور کند در فهرستِ منبع ثبت
    می‌شود — همان مکانیزمی که تضمین می‌کند فرم‌های تازه‌ی آینده هم در
    فایل‌های ترجمه ظاهر شوند (حتی اگر مقدارِ ترجمه‌شان تا اصلاحِ دستی
    همان فارسی بماند). نوشتنِ روی دیسک بلافاصله نیست، دسته‌ای/تاخیردار
    است (نگاه کن به توضیحِ _schedule_flush بالا)."""
    global _dirty_source
    source = _load_source_catalog()
    if text in source:
        return
    with _lock:
        source = _load_source_catalog()
        if text in source:
            return
        source[text] = text
        _dirty_source = True
    _schedule_flush()


def _load_catalog(language_code: str) -> dict[str, str]:
    if language_code not in _catalog_cache:
        _catalog_cache[language_code] = _read_json(_catalog_path(language_code))
    return _catalog_cache[language_code]


def invalidate_cache(language_code: str | None = None) -> None:
    """بعدِ نوشتنِ مستقیمِ فایل (مثلاً بعدِ generate_translation_file)
    باید کشِ همین ماژول هم خالی شود، وگرنه نسخه‌ی قدیمی در حافظه می‌ماند."""
    global _source_cache
    if language_code is None:
        _catalog_cache.clear()
        _source_cache = None
    else:
        _catalog_cache.pop(language_code, None)


def list_source_strings() -> list[str]:
    """فهرستِ همه‌ی متن‌های فارسیِ قابل‌ترجمه — برای صفحه‌ی «ترجمه‌ها»."""
    return sorted(_load_source_catalog().keys())


def get_catalog(language_code: str) -> dict[str, str]:
    """کپیِ کاتالوگِ یک زبان — برای نمایش/ویرایش در صفحه‌ی «ترجمه‌ها»."""
    return dict(_load_catalog(language_code))


def set_translation(language_code: str, source_text: str, translated_text: str) -> None:
    """ذخیره‌ی دستیِ یک ترجمه (از فرمِ صفحه‌ی «ترجمه‌ها») — بلافاصله هم در
    فایل نوشته می‌شود هم کشِ همین جلسه را به‌روز می‌کند."""
    catalog = _load_catalog(language_code)
    catalog[source_text] = translated_text
    _write_json(_catalog_path(language_code), catalog)


def update_catalog(language_code: str, updates: dict[str, str]) -> None:
    """ذخیره‌ی دسته‌ای — برای نتیجه‌ی «ترجمه با سرویسِ آنلاین»."""
    if not updates:
        return
    catalog = _load_catalog(language_code)
    catalog.update(updates)
    _write_json(_catalog_path(language_code), catalog)


def tr(text: str) -> str:
    """ترجمه‌ی یک متنِ ثابتِ رابط کاربری به زبانِ فعلاً انتخاب‌شده
    (session.current_language). برای زبانِ پیش‌فرض یا وقتی زبانی انتخاب
    نشده، خودِ متن (فارسی) برگردانده می‌شود."""
    if not text:
        return text
    _register_source_string(text)

    language = session.current_language
    if language is None or language.is_default:
        return text

    catalog = _load_catalog(language.code)
    if text in catalog:
        return catalog[text]

    # رشته‌ای که هنوز برای این زبان ترجمه نشده — فعلاً فارسی نمایش داده
    # می‌شود، اما هم‌زمان در فایلِ همین زبان ثبت می‌شود (با مقدارِ فارسی)
    # تا بعداً با ویرایشِ همان فایل قابل‌اصلاح باشد. نوشتنِ روی دیسک دسته‌ای/
    # تاخیردار است، نه بلافاصله (نگاه کن به توضیحِ _schedule_flush بالا).
    newly_added = False
    with _lock:
        catalog = _load_catalog(language.code)
        if text not in catalog:
            catalog[text] = text
            _dirty_languages.add(language.code)
            newly_added = True
    if newly_added:
        _schedule_flush()
    return text
