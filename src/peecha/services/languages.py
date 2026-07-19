"""سرویس مدیریت زبان‌ها (core.languages) — تعریفِ صریح زبان به‌جای
هاردکد بودنِ «فارسی» در bootstrap؛ فقط یک زبان می‌تواند is_default باشد
(طبق ایندکس یکتای دیتابیس)، پس ست‌کردنِ پیش‌فرضِ جدید باید بقیه را خاموش کند."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select

from peecha.db.base import new_session
from peecha.db.models.core import Company, Language


@dataclass
class LanguageRow:
    language_id: int
    code: str
    native_name: str
    is_rtl: bool
    is_default: bool
    is_active: bool
    sort_order: int


def list_languages() -> list[LanguageRow]:
    with new_session() as session:
        rows = session.scalars(select(Language).order_by(Language.sort_order, Language.language_id)).all()
        return [
            LanguageRow(
                language_id=r.language_id,
                code=r.code,
                native_name=r.native_name,
                is_rtl=r.is_rtl,
                is_default=r.is_default,
                is_active=r.is_active,
                sort_order=r.sort_order,
            )
            for r in rows
        ]


def create_language(code: str, native_name: str, is_rtl: bool, is_default: bool, sort_order: int = 0) -> Language:
    with new_session() as session:
        if session.scalar(select(func.count()).select_from(Language).where(Language.code == code)):
            raise ValueError("این کدِ زبان قبلاً تعریف شده است.")
        if is_default:
            session.execute(Language.__table__.update().values(is_default=False))
        language = Language(
            code=code, native_name=native_name, is_rtl=is_rtl, is_default=is_default,
            is_active=True, sort_order=sort_order,
        )
        session.add(language)
        session.commit()
        session.refresh(language)
        session.expunge(language)
        return language


def update_language(
    language_id: int, native_name: str, is_rtl: bool, is_default: bool, is_active: bool, sort_order: int = 0
) -> Language:
    with new_session() as session:
        language = session.get(Language, language_id)
        if language is None:
            raise ValueError("زبان نامعتبر است.")
        if is_default and not language.is_default:
            session.execute(Language.__table__.update().values(is_default=False))
        elif not is_default and language.is_default:
            raise ValueError("باید همیشه یک زبانِ پیش‌فرض وجود داشته باشد.")
        language.native_name = native_name
        language.is_rtl = is_rtl
        language.is_default = is_default
        language.is_active = is_active
        language.sort_order = sort_order
        session.commit()
        session.refresh(language)
        session.expunge(language)
        return language


def delete_language(language_id: int) -> None:
    with new_session() as session:
        language = session.get(Language, language_id)
        if language is None:
            raise ValueError("زبان نامعتبر است.")
        if language.is_default:
            raise ValueError("زبانِ پیش‌فرض قابل حذف نیست.")
        in_use = session.scalar(
            select(func.count()).select_from(Company).where(Company.default_language_id == language_id)
        )
        if in_use:
            raise ValueError("این زبان به‌عنوان زبانِ پیش‌فرضِ یک یا چند شرکت استفاده شده؛ قابل حذف نیست.")
        session.delete(language)
        session.commit()
