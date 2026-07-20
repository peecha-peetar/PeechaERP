"""مترجمِ زنده — طبق درخواستِ صریح، از LibreTranslate (متن‌باز/رایگان)
استفاده می‌شود، نه یک سرویسِ تجاری‌ای که نیاز به کلید/حسابِ پولی دارد و
ممکن است از ایران در دسترس نباشد.

این ماژول فقط با فراخوانیِ صریحِ کاربر از دکمه‌ی «ترجمه با سرویسِ آنلاین»
در صفحه‌ی «ترجمه‌ها» صدا زده می‌شود — نه خودکار/پس‌زمینه (طبق همان درخواست:
«هر موقع که ما دستور دادیم»). چون این محیطِ توسعه دسترسیِ آزاد به اینترنت
ندارد (پراکسیِ محیط فقط چند دامنه‌ی مشخص را اجازه می‌دهد)، این پیاده‌سازی
طبق مستنداتِ رسمیِ LibreTranslate نوشته شده اما از همین‌جا قابل‌تستِ زنده
نبود — روی دستگاهِ کاربر (با اینترنتِ واقعی) باید تایید شود."""

from __future__ import annotations

from dataclasses import dataclass, field

import requests

DEFAULT_BASE_URL = "https://libretranslate.com"
SOURCE_LANGUAGE_CODE = "fa"
_TIMEOUT_SECONDS = 20


class TranslationServiceError(Exception):
    """سرویسِ ترجمه اصلاً در دسترس نبود (نه یک شکستِ تک‌رشته‌ای)."""


@dataclass
class TranslationBatchResult:
    translated: dict[str, str] = field(default_factory=dict)
    failed_texts: list[str] = field(default_factory=list)


def target_language_code(language_code: str) -> str:
    """کدِ زبانِ داخلیِ ما (مثلاً en-US) را به کدِ دوحرفیِ ISO موردِ
    انتظارِ LibreTranslate (مثلاً en) تبدیل می‌کند."""
    return language_code.split("-")[0].lower()


def translate_texts(
    texts: list[str],
    target_code: str,
    *,
    base_url: str = DEFAULT_BASE_URL,
    api_key: str | None = None,
) -> TranslationBatchResult:
    """هر متنِ فارسیِ texts را جداگانه به سرویس می‌فرستد. اگر همان اولین
    درخواست با خطای اتصال/شبکه مواجه شود (یعنی خودِ سرویس در دسترس نیست،
    نه یک مشکلِ تک‌موردی)، بلافاصله TranslationServiceError raise می‌شود؛
    بعد از آن، شکستِ تک‌تکِ رشته‌ها فقط در failed_texts ثبت می‌شود و ادامه
    می‌یابد (طبق اصلِ best-effort برای عملیاتِ دسته‌ای)."""
    if target_code == SOURCE_LANGUAGE_CODE:
        return TranslationBatchResult(translated={t: t for t in texts})

    url = base_url.rstrip("/") + "/translate"
    result = TranslationBatchResult()
    session = requests.Session()

    for index, text in enumerate(texts):
        if not text.strip():
            continue
        payload = {"q": text, "source": SOURCE_LANGUAGE_CODE, "target": target_code, "format": "text"}
        if api_key:
            payload["api_key"] = api_key
        try:
            response = session.post(url, json=payload, timeout=_TIMEOUT_SECONDS)
            response.raise_for_status()
            data = response.json()
            translated = data.get("translatedText")
            if translated:
                result.translated[text] = translated
            else:
                result.failed_texts.append(text)
        except (requests.RequestException, ValueError) as exc:
            if index == 0:
                raise TranslationServiceError(f"اتصال به سرویسِ ترجمه ناموفق بود: {_describe_error(exc)}") from exc
            result.failed_texts.append(text)

    return result


def _describe_error(exc: Exception) -> str:
    """پیامِ خامِ requests («400 Client Error: Bad Request for url: ...»)
    دلیلِ واقعی را نشان نمی‌دهد؛ LibreTranslate معمولاً دلیل را در بدنه‌ی
    JSON پاسخ می‌گذارد (مثلاً «کلیدِ API لازم است» یا «زبانِ مبدأ/مقصد
    پشتیبانی نمی‌شود») — این را هم اضافه می‌کنیم تا کاربر بداند دقیقاً
    باید چه چیزی را اصلاح کند (مثلاً گرفتنِ کلیدِ API یا تغییرِ آدرسِ سرویس)."""
    response = getattr(exc, "response", None)
    if response is None:
        return str(exc)
    try:
        body = response.json()
        detail = body.get("error") or body.get("message") or body
    except ValueError:
        detail = response.text
    return f"{exc} — پاسخِ سرویس: {detail}"
