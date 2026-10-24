"""R319: ارسال پیام با ربات رسمی پیام‌رسان‌ها (تلگرام، بله، ایتا، روبیکا).

تلگرام و بله همان Bot API استاندارد را دارند (telegram_client). ایتا («ایتایار»: <base>/<token>/sendMessage) و روبیکا
(Bot API نسخهٔ ۳: <base>/<token>/sendMessage) هم الگوی «توکن در مسیر + chat_id/text» دارند؛ نشانی پایهٔ هر پیام‌رسان در
تنظیمات قابل تغییر است تا اگر سرویس نشانی‌اش را عوض کرد، بدون تغییر برنامه درست شود."""

from __future__ import annotations

import requests

from peecha.integrations.ecommerce import retry
from peecha.integrations.social import telegram_client

DEFAULT_BASE_URLS = {
    "TELEGRAM": "https://api.telegram.org",
    "BALE": "https://tapi.bale.ir",
    "EITAA": "https://eitaayar.ir/api",
    "RUBIKA": "https://botapi.rubika.ir/v3",
}
_TIMEOUT = 30


class MessengerError(RuntimeError):
    """خطای ربات پیام‌رسان با پیام فارسی."""


def _url(platform: str, base_url: str | None, token: str, method: str) -> str:
    base = (base_url or DEFAULT_BASE_URLS[platform]).rstrip("/")
    if platform in ("TELEGRAM", "BALE"):
        return f"{base}/bot{token}/{method}"
    return f"{base}/{token}/{method}"


def _check_response(resp, label: str) -> dict:
    try:
        data = resp.json()
    except ValueError:
        data = None
    failed = resp.status_code >= 400 or (isinstance(data, dict) and (
        data.get("ok") is False or str(data.get("status", "OK")).upper() not in ("OK", "TRUE")))
    if failed:
        detail = (data or {}).get("description") or (data or {}).get("status_det") if isinstance(data, dict) else None
        raise MessengerError(f"{label} — پاسخ ربات (HTTP {resp.status_code}): {detail or resp.text[:300]}")
    return data if isinstance(data, dict) else {}


def send_message(platform: str, token: str, chat_id: str, text: str, base_url: str | None = None) -> dict:
    if platform not in DEFAULT_BASE_URLS:
        raise MessengerError("پیام‌رسان نامعتبر است.")
    if not token:
        raise MessengerError("توکن ربات تنظیم نشده است.")
    if platform in ("TELEGRAM", "BALE") and not base_url:
        return telegram_client.send_message(platform, token, chat_id, text)
    url = _url(platform, base_url, token, "sendMessage")
    if platform == "EITAA":
        resp = retry.call_with_retry(requests.post, url, data={"chat_id": chat_id, "text": text}, timeout=_TIMEOUT)
    else:
        resp = retry.call_with_retry(requests.post, url, json={"chat_id": chat_id, "text": text}, timeout=_TIMEOUT)
    return _check_response(resp, "ارسال پیام")


def check_connection(platform: str, token: str, base_url: str | None = None) -> tuple[bool, str]:
    if not token:
        return False, "توکن ربات تنظیم نشده است."
    try:
        method = requests.get if platform in ("TELEGRAM", "BALE", "EITAA") else requests.post
        resp = retry.call_with_retry(method, _url(platform, base_url, token, "getMe"), timeout=_TIMEOUT)
        _check_response(resp, "بررسی ربات")
    except Exception as exc:  # noqa: BLE001 -- خطاهای شبکه متنوع‌اند
        return False, f"اتصال به ربات برقرار نشد: {exc}"
    return True, "اتصال به ربات برقرار است."
