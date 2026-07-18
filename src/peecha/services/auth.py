"""احراز هویت: هش/بررسی رمز عبور و ساخت اولین کاربر مدیر.

هش با PBKDF2-HMAC-SHA256 (کتابخانه‌ی استاندارد پایتون، بدون وابستگی اضافه)؛
اگر بعداً خواستیم به bcrypt/argon2 مهاجرت کنیم، چون فقط از این دو تابع صدا
زده می‌شود، تغییرش محدود به همین فایل خواهد بود.
"""

from __future__ import annotations

import hashlib
import hmac
import os

from sqlalchemy import func, select

from peecha.db.base import new_session
from peecha.db.models.security import User

_PBKDF2_ITERATIONS = 260_000


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


def authenticate(username: str, password: str) -> User | None:
    """در صورت درست‌بودن نام‌کاربری/رمز و فعال‌بودن کاربر، همان User را
    برمی‌گرداند؛ وگرنه None (بدون افشای این‌که مشکل از نام‌کاربری بود یا رمز)."""
    with new_session() as session:
        user = session.scalar(select(User).where(User.username == username))
        if user is None or not user.is_active:
            return None
        if not verify_password(password, bytes(user.password_hash), bytes(user.password_salt)):
            return None
        session.expunge(user)
        return user


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
