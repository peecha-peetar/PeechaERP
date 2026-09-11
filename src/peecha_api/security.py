"""صدور/بررسیِ توکنِ دسترسی (JWT، کوتاه‌مدت) و توکنِ رفرش (رشتهٔ
تصادفیِ مات، درازمدت، هش‌شده در دیتابیس -- دقیقاً هم‌الگو با ذخیرهٔ
رمزِ عبورِ کاربران در services/auth.py، فقط بدونِ نمکِ جداگانه چون
خودِ توکن از قبل با آنتروپیِ بالا تصادفی است)."""

from __future__ import annotations

import datetime
import hashlib
import secrets

import jwt
from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.security import DeviceToken
from peecha_api.config import ACCESS_TOKEN_MINUTES, JWT_ALGORITHM, JWT_SECRET, REFRESH_TOKEN_DAYS


def create_access_token(user_id: int, company_id: int) -> str:
    now = datetime.datetime.now(datetime.timezone.utc)
    payload = {
        "sub": str(user_id),
        "company_id": company_id,
        "iat": now,
        "exp": now + datetime.timedelta(minutes=ACCESS_TOKEN_MINUTES),
        # طبقِ رفعِ باگِ واقعی: بدونِ این، دو توکنِ صادرشده در یک ثانیه
        # (مثلاً لاگین و رفرشِ بلافاصله) کاملاً یکسان درمی‌آمدند.
        "jti": secrets.token_hex(8),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> tuple[int, int] | None:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        return None
    return int(payload["sub"]), int(payload["company_id"])


def _hash_refresh_token(token: str) -> bytes:
    return hashlib.sha256(token.encode("utf-8")).digest()


def create_device_token(user_id: int, company_id: int, device_name: str | None) -> tuple[int, str]:
    refresh_token = secrets.token_urlsafe(48)
    with new_session() as session:
        row = DeviceToken(
            user_id=user_id, company_id=company_id, device_name=device_name or None,
            refresh_token_hash=_hash_refresh_token(refresh_token),
        )
        session.add(row)
        session.commit()
        return row.device_token_id, refresh_token


def resolve_refresh_token(refresh_token: str) -> tuple[int, int, int] | None:
    """اگر معتبر/باطل‌نشده باشد، (device_token_id, user_id, company_id)
    را برمی‌گرداند و last_used_at را به‌روز می‌کند؛ وگرنه None."""
    token_hash = _hash_refresh_token(refresh_token)
    with new_session() as session:
        row = session.scalar(select(DeviceToken).where(DeviceToken.refresh_token_hash == token_hash))
        if row is None or row.revoked_at is not None:
            return None
        if datetime.datetime.now() - row.created_at.replace(tzinfo=None) > datetime.timedelta(days=REFRESH_TOKEN_DAYS):
            return None
        row.last_used_at = datetime.datetime.now()
        session.commit()
        return row.device_token_id, row.user_id, row.company_id


def revoke_device_token(device_token_id: int, company_id: int) -> None:
    with new_session() as session:
        row = session.get(DeviceToken, device_token_id)
        if row is None or row.company_id != company_id:
            raise ValueError("توکنِ دستگاه نامعتبر است.")
        row.revoked_at = datetime.datetime.now()
        session.commit()
