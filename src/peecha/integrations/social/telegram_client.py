"""لایه‌یِ ارتباطِ خامِ HTTP با Bot APIِ تلگرام/بله.

طبقِ مستنداتِ tapi.bale.ai: بله دقیقاً همان Bot APIِ استانداردِ تلگرام را
با آدرسِ پایه‌یِ متفاوت پیاده می‌کند (getMe/sendMessage با همان ساختارِ
درخواست/پاسخ) -- پس یک کلاینتِ مشترک با base_url به‌ازایِ پلتفرم کافی
است، دقیقاً هم‌الگو با wc_client.py/presta_client.py."""

from __future__ import annotations

import requests

from peecha.integrations.ecommerce import retry

_TELEGRAM_BASE_URL = "https://api.telegram.org"
_BALE_BASE_URL = "https://tapi.bale.ir"
_DEFAULT_TIMEOUT = 30


class SocialAPIError(RuntimeError):
    """خطایِ ارتباط با بات -- پیامِ HTTP/شبکه به فارسی ترجمه می‌شود."""


def base_url_for_platform(platform_code: str) -> str:
    return _BALE_BASE_URL if platform_code == "BALE" else _TELEGRAM_BASE_URL


def _raise_for_status(resp, label: str) -> dict:
    try:
        data = resp.json()
    except ValueError:
        data = None
    if resp.status_code >= 400 or (isinstance(data, dict) and data.get("ok") is False):
        message = (data or {}).get("description") if isinstance(data, dict) else None
        raise SocialAPIError(f"{label} -- خطایِ بات (HTTP {resp.status_code}): {message or resp.text[:300]}")
    return data if isinstance(data, dict) else {}


def check_connection(platform_code: str, bot_token: str) -> tuple[bool, str]:
    try:
        resp = retry.call_with_retry(
            requests.get, f"{base_url_for_platform(platform_code)}/bot{bot_token}/getMe", timeout=_DEFAULT_TIMEOUT,
        )
    except Exception as exc:  # noqa: BLE001 -- خطاهایِ requests/شبکه متنوع‌اند
        return False, f"اتصال به بات برقرار نشد: {exc}"
    if resp.status_code >= 400:
        return False, f"بات با خطایِ HTTP {resp.status_code} پاسخ داد -- توکن را بررسی کنید."
    return True, "اتصال به بات برقرار است."


def send_message(platform_code: str, bot_token: str, chat_id: str, text: str) -> dict:
    resp = retry.call_with_retry(
        requests.post, f"{base_url_for_platform(platform_code)}/bot{bot_token}/sendMessage",
        json={"chat_id": chat_id, "text": text}, timeout=_DEFAULT_TIMEOUT,
    )
    return _raise_for_status(resp, "ارسالِ پیام")
