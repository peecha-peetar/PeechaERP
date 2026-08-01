"""سرویس مدیریت کاربران (sec.users) + دسترسیِ کاربر به شرکت‌ها
(sec.user_companies). کاربر خودش شرکتی ندارد؛ فقط از طریق این جدولِ
واسط به یک یا چند شرکت دسترسی می‌گیرد (چندشرکتی)."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.core import Company, Language
from peecha.db.models.security import User, UserCompany
from peecha.services.auth import hash_password


@dataclass
class UserRow:
    user_id: int
    username: str
    full_name: str
    email: str | None
    default_language_id: int | None
    is_super_admin: bool
    is_active: bool
    company_ids: list[int]
    default_company_id: int | None


def list_users() -> list[UserRow]:
    with new_session() as session:
        users = session.scalars(select(User).order_by(User.username)).all()
        links = session.scalars(select(UserCompany)).all()
        by_user: dict[int, list[UserCompany]] = {}
        for link in links:
            by_user.setdefault(link.user_id, []).append(link)

        rows = []
        for u in users:
            user_links = by_user.get(u.user_id, [])
            default_link = next((l for l in user_links if l.is_default), None)
            rows.append(
                UserRow(
                    user_id=u.user_id,
                    username=u.username,
                    full_name=u.full_name,
                    email=u.email,
                    default_language_id=u.default_language_id,
                    is_super_admin=u.is_super_admin,
                    is_active=u.is_active,
                    company_ids=[l.company_id for l in user_links],
                    default_company_id=default_link.company_id if default_link else None,
                )
            )
        return rows


def grant_company_access(user_id: int, company_id: int) -> None:
    """طبقِ حسابرسیِ صریح: ساختنِ شرکتِ تازه از صفحه‌ی «شرکت‌ها» به‌خودی‌خود
    هیچ دسترسی‌ای به هیچ کاربری نمی‌داد — یعنی شرکتِ تازه در سوییچرِ هدرِ
    همان کاربرِ سازنده هم دیده نمی‌شد، مگر جداگانه از صفحه‌ی «کاربران»
    دسترسی داده می‌شد. این تابع برایِ همان لحظه‌ی ساختِ شرکت صدا زده
    می‌شود تا کاربرِ سازنده بلافاصله دسترسی داشته باشد؛ اگر این اولین
    شرکتِ کاربر باشد، به‌طورِ خودکار پیش‌فرض هم می‌شود."""
    with new_session() as session:
        existing_links = session.scalars(
            select(UserCompany).where(UserCompany.user_id == user_id)
        ).all()
        if any(link.company_id == company_id for link in existing_links):
            return
        make_default = not existing_links
        session.add(UserCompany(user_id=user_id, company_id=company_id, is_default=make_default))
        session.commit()


def create_user(
    username: str,
    full_name: str,
    password: str,
    email: str | None,
    default_language_id: int | None,
    is_super_admin: bool,
    company_ids: list[int],
    default_company_id: int | None,
) -> User:
    with new_session() as session:
        if session.scalar(select(User).where(User.username == username)):
            raise ValueError("این نام‌کاربری قبلاً استفاده شده است.")
        password_hash, password_salt = hash_password(password)
        user = User(
            username=username,
            full_name=full_name,
            password_hash=password_hash,
            password_salt=password_salt,
            email=email or None,
            default_language_id=default_language_id,
            is_super_admin=is_super_admin,
            is_active=True,
            must_change_password=True,
        )
        session.add(user)
        session.flush()

        for company_id in company_ids:
            session.add(
                UserCompany(
                    user_id=user.user_id,
                    company_id=company_id,
                    is_default=(company_id == default_company_id),
                )
            )
        session.commit()
        session.refresh(user)
        session.expunge(user)
        return user


def update_user(
    user_id: int,
    full_name: str,
    email: str | None,
    default_language_id: int | None,
    is_super_admin: bool,
    is_active: bool,
    company_ids: list[int],
    default_company_id: int | None,
    new_password: str | None = None,
) -> User:
    with new_session() as session:
        user = session.get(User, user_id)
        if user is None:
            raise ValueError("کاربر نامعتبر است.")
        user.full_name = full_name
        user.email = email or None
        user.default_language_id = default_language_id
        user.is_super_admin = is_super_admin
        user.is_active = is_active
        if new_password:
            password_hash, password_salt = hash_password(new_password)
            user.password_hash = password_hash
            user.password_salt = password_salt
            user.must_change_password = True

        session.execute(UserCompany.__table__.delete().where(UserCompany.user_id == user_id))
        for company_id in company_ids:
            session.add(
                UserCompany(
                    user_id=user_id,
                    company_id=company_id,
                    is_default=(company_id == default_company_id),
                )
            )
        session.commit()
        session.refresh(user)
        session.expunge(user)
        return user


def list_companies_for_picker() -> list[tuple[int, str]]:
    with new_session() as session:
        rows = session.execute(select(Company.company_id, Company.display_name).order_by(Company.code)).all()
        return [(cid, name) for cid, name in rows]


def list_languages_for_picker() -> list[tuple[int, str]]:
    with new_session() as session:
        rows = session.execute(select(Language.language_id, Language.native_name).order_by(Language.sort_order)).all()
        return [(lid, name) for lid, name in rows]
