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

from peecha import session

_LOCALES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "locales")
_SOURCE_CATALOG_PATH = os.path.join(_LOCALES_DIR, "_source.json")

_lock = threading.Lock()
_catalog_cache: dict[str, dict[str, str]] = {}
_source_cache: dict[str, str] | None = None


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
    همان فارسی بماند)."""
    source = _load_source_catalog()
    if text in source:
        return
    with _lock:
        source = _load_source_catalog()
        if text in source:
            return
        source[text] = text
        _write_json(_SOURCE_CATALOG_PATH, source)


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
    # تا بعداً با ویرایشِ همان فایل قابل‌اصلاح باشد.
    with _lock:
        catalog = _load_catalog(language.code)
        if text not in catalog:
            catalog[text] = text
            _write_json(_catalog_path(language.code), catalog)
    return text
