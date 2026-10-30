"""طبق نبود محدودیت نرخ درخواست (rate limiting) در API موبایل --
شکاف امنیتی شناخته‌شده (حدس brute-force رمز عبور روی /auth/login).

R378: شمارنده در جدول sec.rate_limit_hits پایگاه داده است تا با چند worker یا چند سرور API هم سقف واقعی
اعمال شود (پنجرهٔ لغزان؛ هر کلید با قفل سبک تراکنشی شمرده می‌شود). اگر پایگاه داده در دسترس نباشد، همان شمارندهٔ
درون‌حافظه‌ای قبلی به‌کار می‌رود."""

from __future__ import annotations

import time

from fastapi import HTTPException, Request, status
from sqlalchemy import text

_WINDOW_SECONDS = 60.0
_MAX_ATTEMPTS_PER_KEY = 5
_SWEEP_EVERY_N_CALLS = 500

_attempts: dict[str, list[float]] = {}
_buckets: dict[str, list[float]] = {}
_calls_since_sweep = 0


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _sweep(now: float) -> None:
    """پاک‌سازی فرصت‌طلبانهٔ کلیدهای خالی/منقضی — تا حافظه با گذر
    زمان و تعداد زیاد IPها/نام‌کاربری‌های متفاوت نامحدود رشد نکند."""
    window_start = now - _WINDOW_SECONDS
    stale_keys = [k for k, v in _attempts.items() if not any(t >= window_start for t in v)]
    for k in stale_keys:
        del _attempts[k]


_db_calls = 0


def _db_allow(key: str, max_calls: int, window_seconds: float) -> bool | None:
    """True: مجاز و ثبت شد؛ False: سقف پر است؛ None: پایگاه داده در دسترس نیست (شمارندهٔ حافظه به‌کار می‌رود)."""
    global _db_calls
    from peecha.db.base import get_engine

    try:
        with get_engine().begin() as conn:
            conn.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": key})
            count = conn.execute(text("SELECT count(*) FROM sec.rate_limit_hits WHERE bucket_key = :k "
                                      "AND hit_at > clock_timestamp() - make_interval(secs => :w)"),
                                 {"k": key, "w": float(window_seconds)}).scalar()
            if count >= max_calls:
                return False
            conn.execute(text("INSERT INTO sec.rate_limit_hits (bucket_key) VALUES (:k)"), {"k": key})
            _db_calls += 1
            if _db_calls % _SWEEP_EVERY_N_CALLS == 0:
                conn.execute(text("DELETE FROM sec.rate_limit_hits WHERE hit_at < clock_timestamp() - interval '1 day'"))
        return True
    except Exception:  # noqa: BLE001 -- نبود جدول یا اتصال نباید ورود را از کار بیندازد
        return None


def reset() -> None:
    """پاک کردن همهٔ شمارنده‌ها (آزمون‌ها و راه‌اندازی دوباره)."""
    from peecha.db.base import get_engine

    _attempts.clear()
    _buckets.clear()
    try:
        with get_engine().begin() as conn:
            conn.execute(text("DELETE FROM sec.rate_limit_hits"))
    except Exception:  # noqa: BLE001
        pass


def enforce_login_rate_limit(request: Request, username: str) -> None:
    """۵ تلاش ورود ناموفق/موفق در هر ۶۰ ثانیه برای هر جفت (IP، نام‌کاربری)
    -- شمارش هر تلاش (نه فقط شکست‌خورده‌ها) تا حدس سریع رمز عبور روی
    یک نام‌کاربری مشخص هم مسدود شود، نه فقط تلاش پیاپی ناموفق."""
    global _calls_since_sweep
    allowed = _db_allow(f"login:{_client_ip(request)}:{username.strip().lower()}"[:250], _MAX_ATTEMPTS_PER_KEY, _WINDOW_SECONDS)
    if allowed is False:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="تعداد تلاش‌های ورود بیش‌ازحد است — کمی صبر کنید و دوباره تلاش کنید.",
        )
    if allowed:
        return
    now = time.monotonic()
    _calls_since_sweep += 1
    if _calls_since_sweep >= _SWEEP_EVERY_N_CALLS:
        _calls_since_sweep = 0
        _sweep(now)

    key = f"{_client_ip(request)}:{username.strip().lower()}"
    window_start = now - _WINDOW_SECONDS
    attempts = [t for t in _attempts.get(key, []) if t >= window_start]
    if len(attempts) >= _MAX_ATTEMPTS_PER_KEY:
        _attempts[key] = attempts
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="تعداد تلاش‌های ورود بیش‌ازحد است — کمی صبر کنید و دوباره تلاش کنید.",
        )
    attempts.append(now)
    _attempts[key] = attempts


def enforce_rate_limit(request: Request, bucket: str, key: str, max_calls: int, window_seconds: float = 60.0) -> None:
    """R343: همان شمارندهٔ پنجرهٔ ثابت برای مسیرهای دیگر (مثل درخواست عکس‌برداری)، کلیدشده با IP و کلید مسیر."""
    full_key = f"{bucket}:{_client_ip(request)}:{key}"
    allowed = _db_allow(full_key[:250], max_calls, window_seconds)
    if allowed is False:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                            detail="تعداد درخواست‌ها بیش‌ازحد است — کمی صبر کنید و دوباره تلاش کنید.")
    if allowed:
        return
    now = time.monotonic()
    calls = [t for t in _buckets.get(full_key, []) if t >= now - window_seconds]
    if len(calls) >= max_calls:
        _buckets[full_key] = calls
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                            detail="تعداد درخواست‌ها بیش‌ازحد است — کمی صبر کنید و دوباره تلاش کنید.")
    calls.append(now)
    _buckets[full_key] = calls
    if len(_buckets) > 10_000:
        for stale in [k for k, v in _buckets.items() if not v or v[-1] < now - window_seconds]:
            del _buckets[stale]
