"""سرویسِ ترجمه‌ی برچسب‌هایِ ناوبری (ساید‌بار/ریبون/زیرفرم‌هایِ تنظیمات) به
زبان‌هایِ غیرِپیش‌فرض.

طبقِ حسابرسیِ صریح: `session.current_language` در کلِ برنامه هیچ‌جا
مقداردهی نمی‌شد (سوییچرِ «زبانِ فعال» در هدر فقط ظاهراً پر می‌شد، بدونِ
signalِ متصل) و صفحه‌ی «ترجمه‌ها» زیرِ تنظیماتِ سیستم یک PlaceholderScreen
خالی بود — یعنی سوییچِ زبان در عمل هیچ اثری روی برنامه نداشت. این سرویس
رویِ همان جدولِ عمومیِ core.translations کار می‌کند (که طبقِ کامنتِ خودِ
schema از ابتدا برایِ entity_type='menu' طراحی شده بود، بدونِ نیاز به
migration تازه).

پیشنهادِ خودکار (LibreTranslate) عمداً این‌جا نیست: کلاینتش موقعِ حذفِ
معماریِ Kivy پاک شد و به یک سرویسِ بیرونیِ در‌دسترس نیاز دارد که در این
محیط تاییدنشده است؛ ترجمه فعلاً دستی است — اگر بعداً لازم شد، جداگانه
اضافه می‌شود."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.core import Translation
from peecha.nav_catalog import NAV_ITEMS, SETTINGS_SUB_FORMS

_ENTITY_TYPE = "menu"
_SETTINGS_PREFIX = "SETTINGS_SUB::"


@dataclass
class TranslatableLabel:
    code: str
    source_label: str


def _flatten_nav(items: list[dict]) -> list[TranslatableLabel]:
    result: list[TranslatableLabel] = []
    for item in items:
        result.append(TranslatableLabel(code=item["code"], source_label=item["label"]))
        children = item.get("children")
        if children:
            result.extend(_flatten_nav(children))
    return result


def list_translatable_labels() -> list[TranslatableLabel]:
    labels = _flatten_nav(NAV_ITEMS)
    labels += [
        TranslatableLabel(code=f"{_SETTINGS_PREFIX}{code}", source_label=label)
        for code, label in SETTINGS_SUB_FORMS
    ]
    return labels


def list_translations_for_language(language_id: int) -> dict[str, str]:
    """code -> ترجمه‌یِ موجود، فقط برایِ کدهایی که ترجمه دارند."""
    with new_session() as session:
        rows = session.execute(
            select(Translation.property_name, Translation.value).where(
                Translation.entity_type == _ENTITY_TYPE,
                Translation.language_id == language_id,
            )
        ).all()
        return {code: value for code, value in rows}


def set_translation(code: str, language_id: int, value: str) -> None:
    value = value.strip()
    with new_session() as session:
        existing = session.scalar(
            select(Translation).where(
                Translation.entity_type == _ENTITY_TYPE,
                Translation.entity_id == 0,
                Translation.property_name == code,
                Translation.language_id == language_id,
            )
        )
        if not value:
            if existing is not None:
                session.delete(existing)
                session.commit()
            return
        if existing is not None:
            existing.value = value
        else:
            session.add(
                Translation(
                    entity_type=_ENTITY_TYPE, entity_id=0, property_name=code,
                    language_id=language_id, value=value,
                )
            )
        session.commit()


def translate_label(code: str, source_label: str, language_id: int | None) -> str:
    """برچسبِ ترجمه‌شده برایِ language_id اگر موجود باشد، وگرنه همان متنِ
    فارسیِ اصلی — تابعِ مرکزی که shell_window.py هنگامِ رندرِ ساید‌بار/ریبون
    صدا می‌زند. language_id=None (یا زبانِ پیش‌فرض) یعنی همیشه فارسی."""
    if language_id is None:
        return source_label
    translations = list_translations_for_language(language_id)
    return translations.get(code, source_label)
