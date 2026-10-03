"""طبقِ نبودِ محدودیتِ نرخِ درخواست (rate limiting) در APIِ موبایل --
شکافِ امنیتیِ شناخته‌شده (حدسِ brute-forceِ رمزِ عبور رویِ /auth/login).

پیاده‌سازیِ حداقلی و بدونِ وابستگیِ تازه: شمارندهٔ پنجرهٔ‌ثابتِ
درون‌حافظه‌ای، کلیدشده با (IPِ کلاینت + نامِ‌کاربری) -- برایِ استقرارِ
تک‌فرآیندی (uvicorn بدونِ چند worker، همان الگویِ فعلیِ این سرویس) کافی
است. اگر بعداً به چند فرآیند/نمونه رفت (چند worker یا چند container
پشتِ یک load balancer)، این شمارنده باید به یک فروشگاهِ مشترک (مثلِ
Redis) منتقل شود -- چون هر فرآیند حافظهٔ خودش را جدا می‌شمارد."""

from __future__ import annotations

import time

from fastapi import HTTPException, Request, status

_WINDOW_SECONDS = 60.0
_MAX_ATTEMPTS_PER_KEY = 5
_SWEEP_EVERY_N_CALLS = 500

_attempts: dict[str, list[float]] = {}
_calls_since_sweep = 0


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _sweep(now: float) -> None:
    """پاک‌سازیِ فرصت‌طلبانه‌یِ کلیدهایِ خالی/منقضی -- تا حافظه با گذرِ
    زمان و تعدادِ زیادِ IPها/نامِ‌کاربری‌هایِ متفاوت نامحدود رشد نکند."""
    window_start = now - _WINDOW_SECONDS
    stale_keys = [k for k, v in _attempts.items() if not any(t >= window_start for t in v)]
    for k in stale_keys:
        del _attempts[k]


def enforce_login_rate_limit(request: Request, username: str) -> None:
    """۵ تلاشِ ورودِ ناموفق/موفق در هر ۶۰ ثانیه برایِ هر جفتِ (IP، نامِ‌کاربری)
    -- شمارشِ هر تلاش (نه فقط شکست‌خورده‌ها) تا حدسِ سریعِ رمزِ عبور روی
    یک نامِ‌کاربریِ مشخص هم مسدود شود، نه فقط تلاشِ پیاپیِ ناموفق."""
    global _calls_since_sweep
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
            detail="تعدادِ تلاش‌هایِ ورود بیش‌ازحد است -- کمی صبر کنید و دوباره تلاش کنید.",
        )
    attempts.append(now)
    _attempts[key] = attempts
