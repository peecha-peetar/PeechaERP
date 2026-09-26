"""ارسالِ پیامک از طریقِ یک درگاهِ عمومی -- طبقِ درخواستِ صریحِ کاربر
(«یک تب برایِ بازاریابی و ارسالِ پیامکِ زمان‌بندی‌شده») و پاسخِ او به
سوالِ ارائه‌دهنده («راه‌آفتاب، تقریباً همه مثل هم‌اند»): چون APIِ دقیقِ
هیچ ارائه‌دهنده‌ای پیدا نشد، به‌جایِ سخت‌کدکردنِ یک ارائه‌دهنده، ادمین
یک الگویِ URL با {phone}/{text} (و هرگونه کلیدِ API/نامِ‌کاربری/رمزِ
لازم، مستقیماً در همان URL) در تنظیمات وارد می‌کند؛ این تابع فقط
جایگزینی می‌کند و درخواستِ HTTP می‌فرستد -- بدونِ فرضِ هیچ فرمتِ خاصی
از پاسخ (چون فرمتِ موفقیت/خطایِ هر ارائه‌دهنده متفاوت است)."""

from __future__ import annotations

import urllib.parse
from dataclasses import dataclass

import requests
from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.commercial import SmsGatewaySettings
from peecha.services import ecommerce_credentials

_DEFAULT_TIMEOUT_SECONDS = 10.0


@dataclass
class SmsGatewayInfo:
    setting_id: int
    request_template: str
    http_method: str
    is_active: bool


def get_sms_gateway(company_id: int) -> SmsGatewayInfo | None:
    with new_session() as session:
        row = session.scalar(select(SmsGatewaySettings).where(SmsGatewaySettings.company_id == company_id))
        if row is None:
            return None
        creds = ecommerce_credentials.decrypt_credentials(row.request_template_encrypted)
        return SmsGatewayInfo(
            setting_id=row.setting_id, request_template=creds.get("template", ""), http_method=row.http_method,
            is_active=row.is_active,
        )


def set_sms_gateway(company_id: int, request_template: str, http_method: str, is_active: bool) -> None:
    encrypted = ecommerce_credentials.encrypt_credentials({"template": request_template})
    with new_session() as session:
        row = session.scalar(select(SmsGatewaySettings).where(SmsGatewaySettings.company_id == company_id))
        if row is None:
            row = SmsGatewaySettings(company_id=company_id)
            session.add(row)
        row.request_template_encrypted = encrypted
        row.http_method = http_method.upper() if http_method.upper() in ("GET", "POST") else "GET"
        row.is_active = is_active
        session.commit()


@dataclass
class SmsSendResult:
    success: bool
    message: str


def send_sms(request_template: str, http_method: str, phone_number: str, text: str, timeout: float = _DEFAULT_TIMEOUT_SECONDS) -> SmsSendResult:
    if not request_template:
        return SmsSendResult(False, "درگاهِ پیامک تنظیم نشده است.")
    url = request_template.replace("{phone}", urllib.parse.quote(phone_number)).replace("{text}", urllib.parse.quote(text))
    try:
        if http_method.upper() == "POST":
            response = requests.post(url, timeout=timeout)
        else:
            response = requests.get(url, timeout=timeout)
        if response.status_code >= 400:
            return SmsSendResult(False, f"درگاهِ پیامک با کدِ {response.status_code} پاسخ داد.")
        return SmsSendResult(True, "پیامک ارسال شد.")
    except requests.RequestException as exc:
        return SmsSendResult(False, f"ارسالِ پیامک ناموفق بود: {exc}")
