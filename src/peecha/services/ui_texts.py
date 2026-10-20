"""R316: عنوان دلخواه و ترجمهٔ متن‌های رابط کاربری همهٔ فرم‌ها.

کلید هر متن، خود متن فارسی اصلی است (هش‌شده)، در همان جدول عمومی core.translations
(entity_type='UiText')؛ پس بدون مهاجرت و برای هر فرمی که بعداً اضافه شود هم کار می‌کند.
برای زبان پیش‌فرض یعنی «عنوان دلخواه فیلد»، برای زبان‌های دیگر یعنی «ترجمه»."""

from __future__ import annotations

import hashlib

from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.core import Language, Translation

ENTITY_TYPE = "UiText"
_COLONS = ":：؛ "
_cache: dict[int, dict[str, str]] = {}
_default: list[int | None] = []


def normalize(text: str) -> str:
    return (text or "").strip().rstrip(_COLONS).strip()


def key(text: str) -> str:
    return "T" + hashlib.sha1(normalize(text).encode("utf-8")).hexdigest()[:40]


def default_language_id() -> int | None:
    if _default:
        return _default[0]
    with new_session() as session:
        lang = session.scalar(select(Language).where(Language.is_default.is_(True)).order_by(Language.language_id))
        if lang is None:
            lang = session.scalar(select(Language).order_by(Language.sort_order, Language.language_id))
        _default[:] = [lang.language_id if lang else None]
        return _default[0]


def active_language_id() -> int | None:
    from peecha import session as app_session

    lang = app_session.current_language
    return lang.language_id if lang is not None else default_language_id()


def overrides(language_id: int | None) -> dict[str, str]:
    """کلید ← متن دلخواه برای یک زبان (با حافظهٔ موقت)."""
    if language_id is None:
        return {}
    if language_id not in _cache:
        with new_session() as session:
            rows = session.execute(select(Translation.property_name, Translation.value).where(
                Translation.entity_type == ENTITY_TYPE, Translation.language_id == language_id)).all()
        _cache[language_id] = {k: v for k, v in rows}
    return _cache[language_id]


def clear_cache() -> None:
    _cache.clear()
    _default.clear()


def lookup(text: str, language_id: int | None) -> str | None:
    """متن جایگزین با همان دونقطهٔ انتهایی متن اصلی؛ None یعنی بدون تغییر."""
    source = normalize(text)
    if not source or language_id is None:
        return None
    value = overrides(language_id).get(key(source))
    if not value:
        return None
    return value + (text or "").strip()[len(source):]


def save(language_id: int, pairs: list[tuple[str, str | None]]) -> int:
    """[(متن اصلی، متن دلخواه یا خالی برای بازگشت به اصلی)] در یک تراکنش؛ تعداد تغییرها."""
    if language_id is None:
        raise ValueError("ابتدا زبان را انتخاب کنید.")
    changed = 0
    with new_session() as session:
        existing = {t.property_name: t for t in session.scalars(select(Translation).where(
            Translation.entity_type == ENTITY_TYPE, Translation.language_id == language_id))}
        for source, value in pairs:
            source, value = normalize(source), (value or "").strip()
            if not source:
                continue
            if len(value) > 400:
                raise ValueError(f"متن «{value[:30]}…» بیش از ۴۰۰ نویسه است.")
            k = key(source)
            row = existing.get(k)
            if not value or value == source:
                if row is not None:
                    session.delete(row)
                    existing.pop(k)
                    changed += 1
                continue
            if row is None:
                row = Translation(entity_type=ENTITY_TYPE, entity_id=0, property_name=k, language_id=language_id, value=value)
                session.add(row)
                existing[k] = row
                changed += 1
            elif row.value != value:
                row.value = value
                changed += 1
        session.commit()
    _cache.pop(language_id, None)
    return changed


def current_values(language_id: int | None, sources: list[str]) -> dict[str, str]:
    """متن اصلی ← متن دلخواه ثبت‌شده (فقط آن‌هایی که دارند)."""
    data = overrides(language_id)
    out = {}
    for source in sources:
        value = data.get(key(source))
        if value:
            out[normalize(source)] = value
    return out
