"""R377: ورود دومرحله‌ای با کد یک‌بارمصرف زمان‌دار (TOTP، RFC 6238) — سازگار با Google Authenticator، Microsoft Authenticator
و برنامه‌های مشابه؛ فقط با کتابخانهٔ استاندارد پایتون.

- کاربر با اسکن QR (یا ورود دستی کلید) فعال می‌کند و با یک کد درست تایید؛ هشت کد بازیابی یک‌بارمصرف فقط همان لحظه نشان داده
  و درهم‌سازی‌شده نگه داشته می‌شود.
- کد شش‌رقمی هر ۳۰ ثانیه عوض می‌شود؛ یک گام قبل و بعد هم (برای اختلاف ساعت) پذیرفته می‌شود و هیچ کدی دو بار پذیرفته نمی‌شود.
- اگر در یکی از شرکت‌های کاربر کلید «الزام ورود دومرحله‌ای» روشن باشد، کاربر بدون آن وارد نمی‌شود (در دسکتاپ همان لحظه فعالش
  می‌کند) و نمی‌تواند خاموشش کند. مدیر سیستم می‌تواند برای کاربری که گوشی‌اش را گم کرده بازنشانی کند.
- راز در جدول کاربر نگه داشته می‌شود و هر رایانه و سرور موبایل با آن کد را می‌سنجد؛ دسترسی مستقیم به پایگاه داده باید محدود باشد.
"""

from __future__ import annotations

import base64
import datetime
import hashlib
import hmac
import os
import secrets
import struct
import time
import urllib.parse
from types import SimpleNamespace

from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.security import User, UserCompany, UserMfa

ISSUER = "Peecha"
STEP_SECONDS = 30
DIGITS = 6
WINDOW = 1
RECOVERY_COUNT = 8
POLICY_FEATURE = "SECURITY_MFA_REQUIRED"


def new_secret() -> str:
    return base64.b32encode(os.urandom(20)).decode("ascii").rstrip("=")


def _key(secret: str) -> bytes:
    padded = secret.upper() + "=" * (-len(secret) % 8)
    return base64.b32decode(padded)


def step_at(when: float | None = None) -> int:
    return int((time.time() if when is None else when) // STEP_SECONDS)


def code_for_step(secret: str, step: int) -> str:
    digest = hmac.new(_key(secret), struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    number = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(number % 10 ** DIGITS).zfill(DIGITS)


def code_at(secret: str, when: float | None = None) -> str:
    return code_for_step(secret, step_at(when))


def _clean(code: str) -> str:
    from peecha import numerals

    return numerals.to_ascii_digits(code or "").replace(" ", "").replace("-", "").strip().upper()


def matching_step(secret: str, code: str, when: float | None = None, after_step: int | None = None) -> int | None:
    """گام زمانی که کد با آن می‌خواند (یا None)؛ گام‌های تا after_step (استفاده‌شده) پذیرفته نمی‌شوند."""
    code = _clean(code)
    if len(code) != DIGITS or not code.isdigit():
        return None
    now = step_at(when)
    for step in range(now - WINDOW, now + WINDOW + 1):
        if after_step is not None and step <= after_step:
            continue
        if hmac.compare_digest(code_for_step(secret, step), code):
            return step
    return None


def otpauth_uri(secret: str, username: str) -> str:
    label = urllib.parse.quote(f"{ISSUER}:{username}")
    return f"otpauth://totp/{label}?secret={secret}&issuer={ISSUER}&algorithm=SHA1&digits={DIGITS}&period={STEP_SECONDS}"


def qr_png(uri: str, scale: int = 6) -> bytes:
    import io

    import segno

    buffer = io.BytesIO()
    segno.make(uri, error="m").save(buffer, kind="png", scale=scale, border=3)
    return buffer.getvalue()


def _hash_recovery(code: str) -> str:
    return hashlib.sha256(_clean(code).encode("ascii")).hexdigest()


def _new_recovery_codes() -> list[str]:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return ["".join(secrets.choice(alphabet) for _ in range(4)) + "-" + "".join(secrets.choice(alphabet) for _ in range(4))
            for _ in range(RECOVERY_COUNT)]


# --- وضعیت و سیاست ------------------------------------------------------------------------------------------
def is_enabled(session, user_id: int) -> bool:
    row = session.get(UserMfa, user_id)
    return row is not None and row.is_enabled


def required_for(session, user_id: int) -> bool:
    from peecha.db.models.inventory import CompanyFeature

    return session.scalar(select(CompanyFeature.company_id).join(UserCompany, UserCompany.company_id == CompanyFeature.company_id)
                          .where(UserCompany.user_id == user_id, CompanyFeature.feature_code == POLICY_FEATURE,
                                 CompanyFeature.is_enabled.is_(True)).limit(1)) is not None


def status(user_id: int) -> SimpleNamespace:
    with new_session() as session:
        row = session.get(UserMfa, user_id)
        enabled = row is not None and row.is_enabled
        return SimpleNamespace(enabled=enabled, required=required_for(session, user_id),
                               recovery_left=len(row.recovery_hashes or []) if enabled else 0,
                               enabled_at=row.enabled_at if enabled else None)


def next_step(user_id: int) -> str | None:
    """پس از رمز درست: VERIFY (کد لازم است)، ENROLL (الزامی است ولی فعال نشده) یا None."""
    with new_session() as session:
        if is_enabled(session, user_id):
            return "VERIFY"
        return "ENROLL" if required_for(session, user_id) else None


def _audit(session, user_id: int, action: str, actor_id: int | None = None, changes: dict | None = None) -> None:
    from peecha.services.audit import log_activity

    company_id = session.scalar(select(UserCompany.company_id).where(UserCompany.user_id == user_id)
                                .order_by(UserCompany.is_default.desc()).limit(1))
    log_activity(session, company_id=company_id, user_id=actor_id or user_id, entity_type="User", entity_id=user_id, action=action,
                 changes=changes)


# --- فعال‌سازی و مدیریت -------------------------------------------------------------------------------------------
def start_enrollment(user_id: int) -> tuple[str, str]:
    """(راز، نشانی otpauth برای QR). تا تایید با کد درست، فعال نمی‌شود."""
    with new_session() as session:
        user = session.get(User, user_id)
        if user is None:
            raise ValueError("کاربر نامعتبر است.")
        row = session.get(UserMfa, user_id)
        if row is not None and row.is_enabled:
            raise ValueError("ورود دومرحله‌ای از قبل فعال است.")
        secret = new_secret()
        if row is None:
            row = UserMfa(user_id=user_id, secret=secret)
            session.add(row)
        row.secret, row.is_enabled, row.recovery_hashes, row.last_step = secret, False, [], None
        session.commit()
        return secret, otpauth_uri(secret, user.username)


def confirm_enrollment(user_id: int, code: str, when: float | None = None) -> list[str]:
    """با اولین کد درست فعال می‌شود؛ کدهای بازیابی (فقط همین یک بار) برگردانده می‌شوند."""
    with new_session() as session:
        row = session.get(UserMfa, user_id)
        if row is None or row.is_enabled:
            raise ValueError("اول فعال‌سازی را شروع کنید.")
        step = matching_step(row.secret, code, when)
        if step is None:
            raise ValueError("کد نادرست است؛ ساعت گوشی را بررسی کنید و کد جدید برنامه را وارد کنید.")
        codes = _new_recovery_codes()
        row.is_enabled, row.enabled_at, row.last_step = True, datetime.datetime.now(datetime.timezone.utc), step
        row.recovery_hashes = [_hash_recovery(c) for c in codes]
        _audit(session, user_id, "MFA_ON")
        session.commit()
        return codes


def check(user_id: int, code: str, when: float | None = None) -> str | None:
    """کد برنامه یا کد بازیابی را می‌سنجد و مصرف می‌کند: TOTP، RECOVERY یا None."""
    with new_session() as session:
        row = session.scalar(select(UserMfa).where(UserMfa.user_id == user_id).with_for_update())
        if row is None or not row.is_enabled:
            return None
        step = matching_step(row.secret, code, when, row.last_step)
        if step is not None:
            row.last_step = step
            session.commit()
            return "TOTP"
        digest = _hash_recovery(code)
        if len(_clean(code)) == 8 and digest in (row.recovery_hashes or []):
            row.recovery_hashes = [h for h in row.recovery_hashes if h != digest]
            _audit(session, user_id, "MFA_BACKUP", changes={"left": len(row.recovery_hashes)})
            session.commit()
            return "RECOVERY"
        return None


def regenerate_recovery(user_id: int, code: str, when: float | None = None) -> list[str]:
    if check(user_id, code, when) is None:
        raise ValueError("کد نادرست است.")
    codes = _new_recovery_codes()
    with new_session() as session:
        row = session.get(UserMfa, user_id)
        row.recovery_hashes = [_hash_recovery(c) for c in codes]
        _audit(session, user_id, "MFA_CODES")
        session.commit()
    return codes


def disable(user_id: int, code: str, when: float | None = None) -> None:
    with new_session() as session:
        if required_for(session, user_id):
            raise ValueError("در شرکت شما ورود دومرحله‌ای الزامی است و خاموش نمی‌شود.")
    if check(user_id, code, when) is None:
        raise ValueError("کد نادرست است.")
    with new_session() as session:
        session.delete(session.get(UserMfa, user_id))
        _audit(session, user_id, "MFA_OFF")
        session.commit()


def reset_by_admin(admin_user_id: int, company_id: int, user_id: int) -> None:
    """برای کاربری که گوشی و کدهای بازیابی را گم کرده؛ در ورود بعدی دوباره فعال می‌کند (اگر الزامی باشد)."""
    from peecha.services import roles

    if not roles.is_manager(admin_user_id, company_id):
        raise ValueError("بازنشانی ورود دومرحله‌ای با مدیر سیستم است.")
    with new_session() as session:
        row = session.get(UserMfa, user_id)
        if row is None:
            raise ValueError("ورود دومرحله‌ای این کاربر فعال نیست.")
        session.delete(row)
        _audit(session, user_id, "MFA_RESET", actor_id=admin_user_id)
        session.commit()
