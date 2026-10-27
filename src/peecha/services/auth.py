"""احراز هویت: هش/بررسی رمز عبور و ساخت اولین کاربر مدیر.

هش با PBKDF2-HMAC-SHA256 (کتابخانهٔ استاندارد پایتون، بدون وابستگی اضافه)؛
اگر بعداً خواستیم به bcrypt/argon2 مهاجرت کنیم، چون فقط از این دو تابع صدا
زده می‌شود، تغییرش محدود به همین فایل خواهد بود.
"""

from __future__ import annotations

import datetime
import hashlib
import hmac
import math
import os
import re

from sqlalchemy import func, select

from peecha import numerals
from peecha.db.base import new_session
from peecha.db.models.security import User, UserCompany

_PBKDF2_ITERATIONS = 260_000
# R344: سیاست رمز و قفل موقت پس از ورود ناموفق مکرر (دسکتاپ و موبایل هر دو از authenticate می‌گذرند)
MIN_PASSWORD_LENGTH = 8
MAX_FAILED_LOGINS = 5
LOCK_MINUTES = 15


class AccountLockedError(ValueError):
    """حساب موقتاً قفل است؛ متن خطا برای نمایش به کاربر است."""


def check_password_strength(password: str) -> None:
    password = password or ""
    if len(password) < MIN_PASSWORD_LENGTH or not re.search(r"[^\W\d_]", password) or not re.search(r"\d", password):
        raise ValueError("رمز عبور باید دست‌کم ۸ نویسه و شامل حرف و عدد باشد.")


def hash_password(password: str) -> tuple[bytes, bytes]:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    return digest, salt


def verify_password(password: str, password_hash: bytes, salt: bytes) -> bool:
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    return hmac.compare_digest(candidate, password_hash)


def has_any_user() -> bool:
    with new_session() as session:
        count = session.scalar(select(func.count()).select_from(User))
    return bool(count)


def _login_event(session, user: User, action: str, changes: dict | None = None) -> None:
    from peecha.services.audit import log_activity

    company_id = session.scalar(select(UserCompany.company_id).where(UserCompany.user_id == user.user_id)
                                .order_by(UserCompany.is_default.desc()).limit(1))
    log_activity(session, company_id=company_id, user_id=user.user_id, entity_type="User", entity_id=user.user_id,
                 action=action, changes=changes)


def authenticate(username: str, password: str) -> User | None:
    """در صورت درست‌بودن نام‌کاربری/رمز و فعال‌بودن کاربر، همان User را
    برمی‌گرداند؛ وگرنه None (بدون افشای این‌که مشکل از نام‌کاربری بود یا رمز).
    پس از MAX_FAILED_LOGINS ورود ناموفق پیاپی، حساب LOCK_MINUTES دقیقه قفل می‌شود و AccountLockedError می‌دهد."""
    with new_session() as session:
        user = session.scalar(select(User).where(User.username == username).with_for_update())
        if user is None or not user.is_active:
            return None
        now = datetime.datetime.now(datetime.timezone.utc)
        if user.locked_until is not None and user.locked_until > now:
            minutes = max(1, math.ceil((user.locked_until - now).total_seconds() / 60))
            raise AccountLockedError(f"به‌دلیل چند ورود ناموفق، این حساب تا {numerals.to_persian_digits(str(minutes))} دقیقهٔ دیگر قفل است.")
        if not verify_password(password, bytes(user.password_hash), bytes(user.password_salt)):
            user.failed_login_count = (user.failed_login_count or 0) + 1
            if user.failed_login_count >= MAX_FAILED_LOGINS:
                user.failed_login_count, user.locked_until = 0, now + datetime.timedelta(minutes=LOCK_MINUTES)
                _login_event(session, user, "LOCK", {"minutes": LOCK_MINUTES})
            else:
                _login_event(session, user, "LOGIN_FAIL", {"attempt": user.failed_login_count})
            session.commit()
            return None
        user.failed_login_count, user.locked_until = 0, None
        _login_event(session, user, "LOGIN")
        session.commit()
        session.refresh(user)
        session.expunge(user)
        return user


def change_password(user_id: int, new_password: str, current_password: str | None = None) -> None:
    """تغییر رمز خود کاربر (و تغییر اجباری پس از ورود اول). اگر current_password داده شود، اول بررسی می‌شود."""
    check_password_strength(new_password)
    with new_session() as session:
        user = session.get(User, user_id)
        if user is None:
            raise ValueError("کاربر نامعتبر است.")
        if current_password is not None and not verify_password(current_password, bytes(user.password_hash),
                                                                bytes(user.password_salt)):
            raise ValueError("رمز فعلی نادرست است.")
        if verify_password(new_password, bytes(user.password_hash), bytes(user.password_salt)):
            raise ValueError("رمز جدید باید با رمز فعلی فرق داشته باشد.")
        user.password_hash, user.password_salt = hash_password(new_password)
        user.must_change_password = False
        user.password_changed_at = datetime.datetime.now(datetime.timezone.utc)
        session.commit()


def create_super_admin_user(username: str, full_name: str, password: str) -> User:
    """فقط برای بوت‌استرپ اولیه (وقتی هیچ کاربری در دیتابیس نیست) استفاده می‌شود."""
    password_hash, password_salt = hash_password(password)
    with new_session() as session:
        user = User(
            username=username,
            full_name=full_name,
            password_hash=password_hash,
            password_salt=password_salt,
            is_super_admin=True,
            is_active=True,
            must_change_password=False,
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        session.expunge(user)
        return user
