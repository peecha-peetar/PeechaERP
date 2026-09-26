"""سخت‌گیریِ اتصال به فروشگاه (Retry/Backoff).

طبقِ گزارشِ کاربر («سخت‌گیریِ شبکه»): تا این‌جا هر خطایِ شبکه‌ایِ زودگذر
(قطعیِ لحظه‌ای، Timeout) یا کدهایِ HTTPِ موقتیِ سمتِ سرور (429/5xx) بلافاصله
کلِ عملیاتِ سینک را متوقف می‌کرد -- حتی اگر تلاشِ دوباره (چند ثانیه بعد)
موفق می‌شد. این ماژول یک تلاشِ مجددِ عمومی با فاصله‌یِ نمایی (exponential
backoff) اضافه می‌کند که هر تماسِ HTTP در این پکیج (ووکامرس/پرستاشاپ) از آن
عبور می‌کند.

خطاهایِ دائمی (400/401/403/404/422/...) بلافاصله بالا می‌روند/برگردانده
می‌شوند -- تلاشِ مجدد برایِ آن‌ها بی‌فایده است و فقط سینک را کند می‌کند."""

from __future__ import annotations

import time
from typing import Callable, TypeVar

import requests

_RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
DEFAULT_MAX_ATTEMPTS = 4
DEFAULT_BASE_DELAY_SECONDS = 1.0

T = TypeVar("T")


def call_with_retry(
    func: Callable[..., T],
    *args,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    base_delay: float = DEFAULT_BASE_DELAY_SECONDS,
    **kwargs,
) -> T:
    """``func(*args, **kwargs)`` را صدا می‌زند. اگر ``requests.RequestException``
    رخ دهد یا پاسخِ برگشتی ``status_code``یِ موقتی (429/5xx) داشته باشد، با
    تاخیرِ نماییِ ``base_delay * 2**(attempt-1)`` (۱، ۲، ۴، ... ثانیه) دوباره
    تلاش می‌کند -- حداکثر ``max_attempts`` بار. آخرین پاسخ/خطا در صورتِ
    ناموفق‌ماندنِ همه‌یِ تلاش‌ها برگردانده/دوباره بالا برده می‌شود."""
    last_exc: requests.RequestException | None = None
    resp = None
    for attempt in range(1, max_attempts + 1):
        try:
            resp = func(*args, **kwargs)
        except requests.RequestException as exc:
            last_exc = exc
            if attempt == max_attempts:
                raise
            time.sleep(base_delay * (2 ** (attempt - 1)))
            continue
        status_code = getattr(resp, "status_code", None)
        if status_code in _RETRYABLE_STATUS_CODES and attempt < max_attempts:
            time.sleep(base_delay * (2 ** (attempt - 1)))
            continue
        return resp
    if last_exc is not None:
        raise last_exc
    return resp
