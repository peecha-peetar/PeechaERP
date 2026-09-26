"""لایه‌یِ ارتباطِ خامِ HTTP با WP REST APIِ وردپرس (Application Password
+ Basic Auth) -- طبقِ ادامه‌یِ اولویتِ بخشِ محتوا («سینکِ CMS»). دقیقاً
هم‌الگو با wc_client.py/telegram_client.py: فقط پارامتر می‌گیرد و پاسخِ
خام برمی‌گرداند."""

from __future__ import annotations

import requests

from peecha.integrations.ecommerce import retry

_DEFAULT_TIMEOUT = 30


class CmsAPIError(RuntimeError):
    """خطایِ ارتباط با وردپرس -- پیامِ HTTP/شبکه به فارسی ترجمه می‌شود."""


def _api_base(site_url: str) -> str:
    return f"{site_url.rstrip('/')}/wp-json/wp/v2"


def _raise_for_status(resp, label: str) -> dict:
    try:
        data = resp.json()
    except ValueError:
        data = None
    if resp.status_code >= 400:
        message = (data or {}).get("message") if isinstance(data, dict) else None
        raise CmsAPIError(f"{label} -- خطایِ وردپرس (HTTP {resp.status_code}): {message or resp.text[:300]}")
    return data if isinstance(data, dict) else {}


def check_connection(site_url: str, username: str, app_password: str) -> tuple[bool, str]:
    try:
        resp = retry.call_with_retry(
            requests.get, f"{_api_base(site_url)}/users/me",
            auth=(username, app_password), timeout=_DEFAULT_TIMEOUT,
        )
    except Exception as exc:  # noqa: BLE001 -- خطاهایِ requests/شبکه متنوع‌اند
        return False, f"اتصال به وردپرس برقرار نشد: {exc}"
    if resp.status_code >= 400:
        return False, f"وردپرس با خطایِ HTTP {resp.status_code} پاسخ داد -- آدرسِ سایت/نامِ‌کاربری/رمزِ‌کاره را بررسی کنید."
    return True, "اتصال به وردپرس برقرار است."


def create_post(site_url: str, username: str, app_password: str, title: str, content: str, status: str = "publish") -> dict:
    resp = retry.call_with_retry(
        requests.post, f"{_api_base(site_url)}/posts",
        auth=(username, app_password), json={"title": title, "content": content, "status": status},
        timeout=_DEFAULT_TIMEOUT,
    )
    return _raise_for_status(resp, "ایجادِ مقاله")


def update_post(site_url: str, username: str, app_password: str, post_id: str, title: str, content: str, status: str = "publish") -> dict:
    resp = retry.call_with_retry(
        requests.post, f"{_api_base(site_url)}/posts/{post_id}",
        auth=(username, app_password), json={"title": title, "content": content, "status": status},
        timeout=_DEFAULT_TIMEOUT,
    )
    return _raise_for_status(resp, "به‌روزرسانیِ مقاله")
