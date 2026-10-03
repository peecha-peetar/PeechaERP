"""لایه‌یِ ارتباطِ خامِ HTTP با Gemini APIِ گوگل (generateContent) -- طبقِ
درخواستِ صریح («تولیدِ محتوایِ خودکار با هوش مصنوعی»). دقیقاً هم‌الگو با
wc_client.py/telegram_client.py -- فقط پارامتر می‌گیرد و پاسخِ خام
برمی‌گرداند؛ تصمیم/متنِ خواسته‌شده در commercial_social.py ساخته
می‌شود."""

from __future__ import annotations

import requests

from peecha.integrations.ecommerce import retry

_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"
_DEFAULT_MODEL = "gemini-2.0-flash"
_DEFAULT_TIMEOUT = 30


class AIContentError(RuntimeError):
    """خطایِ ارتباط با Gemini -- پیامِ HTTP/شبکه به فارسی ترجمه می‌شود."""


def generate_text(api_key: str, prompt: str, model: str = _DEFAULT_MODEL) -> str:
    url = f"{_BASE_URL}/{model}:generateContent?key={api_key}"
    resp = retry.call_with_retry(
        requests.post, url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=_DEFAULT_TIMEOUT,
    )
    try:
        data = resp.json()
    except ValueError:
        data = None
    if resp.status_code >= 400:
        message = (data or {}).get("error", {}).get("message") if isinstance(data, dict) else None
        raise AIContentError(f"تولیدِ محتوا -- خطایِ Gemini (HTTP {resp.status_code}): {message or resp.text[:300]}")
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise AIContentError("پاسخِ Gemini فاقدِ متنِ تولیدشده بود.") from exc
