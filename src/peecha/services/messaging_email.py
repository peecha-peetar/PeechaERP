"""R380: ارسال ایمیل با سرور SMTP شرکت — برای پیام و کمپین ایمیلی مرکز ارتباطات، اعلان‌های کانال «ایمیل» و آزمون تنظیمات.

- مشخصات سرور (نشانی، درگاه، امنیت بدون/STARTTLS/SSL، نام کاربری، رمز، فرستنده) در همان جدول تنظیم پیام‌رسان‌ها با کانال
  EMAIL و همان رمزنگاری توکن ربات‌ها نگه داشته می‌شود؛ رمز هرگز به فرم برگردانده نمی‌شود.
- متن فارسی با UTF-8 و نسخهٔ HTML راست‌به‌چپ فرستاده می‌شود؛ پیوست اختیاری است.
- ناموفق بودن ارسال خطا نمی‌دهد: نتیجه برمی‌گردد و در دفتر پیام‌ها یا وضعیت اعلان ثبت می‌شود.
"""

from __future__ import annotations

import datetime
import html
import re
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.crm import MessengerSetting

CHANNEL = "EMAIL"
SECURITY = {"STARTTLS": "STARTTLS (معمولاً درگاه ۵۸۷)", "SSL": "SSL (معمولاً درگاه ۴۶۵)", "NONE": "بدون رمزنگاری (فقط شبکهٔ داخلی)"}
TIMEOUT_SECONDS = 20
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass
class EmailSettings:
    host: str = ""
    port: int = 587
    security: str = "STARTTLS"
    username: str = ""
    from_address: str = ""
    from_name: str = ""
    is_active: bool = False
    has_password: bool = False
    last_error: str | None = None


def valid_address(address: str) -> bool:
    return bool(_EMAIL_RE.match((address or "").strip()))


def _row(session, company_id: int) -> MessengerSetting | None:
    return session.scalar(select(MessengerSetting).where(MessengerSetting.company_id == company_id, MessengerSetting.channel == CHANNEL))


def _secret(row: MessengerSetting | None) -> dict:
    from peecha.services import ecommerce_credentials

    return ecommerce_credentials.decrypt_credentials(row.secret_encrypted) if row is not None and row.secret_encrypted else {}


def get_settings(company_id: int) -> EmailSettings:
    with new_session() as session:
        row = _row(session, company_id)
        data = _secret(row)
    return EmailSettings(data.get("host", ""), int(data.get("port") or 587), data.get("security") or "STARTTLS", data.get("username", ""),
                         data.get("from_address", ""), data.get("from_name", ""), bool(row and row.is_active), bool(data.get("password")),
                         row.last_error if row else None)


def save_settings(company_id: int, user_id: int | None, *, host: str, port: int, security: str, username: str = "",
                  password: str | None = None, from_address: str, from_name: str = "", is_active: bool = True) -> None:
    """password خالی یا None یعنی همان رمز قبلی بماند."""
    from peecha.services import ecommerce_credentials
    from peecha.services.crm import common as c

    host, from_address = (host or "").strip(), (from_address or "").strip()
    if security not in SECURITY:
        raise ValueError("نوع امنیت اتصال نامعتبر است.")
    if not host:
        raise ValueError("نشانی سرور ایمیل را وارد کنید.")
    if not 1 <= int(port) <= 65535:
        raise ValueError("درگاه سرور ایمیل نامعتبر است.")
    if not valid_address(from_address):
        raise ValueError("نشانی ایمیل فرستنده نامعتبر است.")
    with new_session() as session:
        row = _row(session, company_id)
        if row is None:
            row = MessengerSetting(company_id=company_id, channel=CHANNEL)
            session.add(row)
        old = _secret(row)
        data = {"host": host, "port": int(port), "security": security, "username": (username or "").strip(),
                "password": password if password else old.get("password", ""), "from_address": from_address,
                "from_name": (from_name or "").strip()}
        row.secret_encrypted = ecommerce_credentials.encrypt_credentials(data)
        row.is_active, row.base_url, row.http_method = bool(is_active), None, "POST"
        row.updated_by_user_id, row.updated_at = user_id, datetime.datetime.now().astimezone()
        session.flush()
        c.audit(session, company_id, user_id, "MessengerSetting", row.setting_id, "UPDATE",
                {"channel": CHANNEL, "is_active": row.is_active, "host": host, "password_changed": bool(password)})
        session.commit()


def _record(company_id: int, error: str | None) -> None:
    with new_session() as session:
        row = _row(session, company_id)
        if row is not None:
            row.last_error = (error or None) and error[:500]
            row.last_checked_at = datetime.datetime.now().astimezone()
            session.commit()


def _html(body: str) -> str:
    paragraphs = "".join(f"<p>{html.escape(p).replace(chr(10), '<br>')}</p>" for p in (body or "").split("\n\n"))
    return (f'<html><body dir="rtl" style="font-family: Tahoma, Vazirmatn, sans-serif; text-align: right; line-height: 1.8">'
            f"{paragraphs}</body></html>")


def send_email(company_id: int, to: str, subject: str, body: str, attachments: tuple = ()) -> tuple[bool, str]:
    """(موفق؟، پیام). attachments: [(نام فایل، بایت‌ها، نوع mime مثل application/pdf)]."""
    with new_session() as session:
        row = _row(session, company_id)
        data = _secret(row)
        active = bool(row and row.is_active)
    if not active or not data.get("host"):
        return False, "سرور ایمیل تنظیم نشده یا خاموش است."
    to = (to or "").strip()
    if not valid_address(to):
        return False, "نشانی ایمیل گیرنده نامعتبر است."
    msg = EmailMessage()
    msg["Subject"] = subject or "پیام"
    msg["From"] = formataddr((data.get("from_name") or "", data["from_address"]))
    msg["To"] = to
    msg["Message-ID"] = make_msgid(domain=data["from_address"].split("@")[-1])
    msg.set_content(body or "")
    msg.add_alternative(_html(body), subtype="html")
    for name, content, mime in attachments:
        maintype, _sep, subtype = (mime or "application/octet-stream").partition("/")
        msg.add_attachment(content, maintype=maintype, subtype=subtype or "octet-stream", filename=name)
    try:
        if data.get("security") == "SSL":
            server = smtplib.SMTP_SSL(data["host"], int(data["port"]), timeout=TIMEOUT_SECONDS, context=ssl.create_default_context())
        else:
            server = smtplib.SMTP(data["host"], int(data["port"]), timeout=TIMEOUT_SECONDS)
        with server:
            if data.get("security") == "STARTTLS":
                server.starttls(context=ssl.create_default_context())
            if data.get("username"):
                server.login(data["username"], data.get("password", ""))
            server.send_message(msg)
    except (smtplib.SMTPException, OSError) as exc:
        error = f"ارسال ایمیل انجام نشد: {exc}"
        _record(company_id, error)
        return False, error
    _record(company_id, None)
    return True, "ایمیل فرستاده شد."


def test_settings(company_id: int, to: str) -> tuple[bool, str]:
    return send_email(company_id, to, "آزمون ایمیل پیچا", "این ایمیل برای آزمودن تنظیمات سرور ایمیل فرستاده شده است.")


class EmailProvider:
    """ارائه‌دهندهٔ کانال EMAIL مرکز ارتباطات (پیام تکی و کمپین)."""

    code = "SMTP"

    def send(self, company_id: int, recipient: str, subject: str | None, body: str):
        from peecha.services.crm.communication import SendResult

        ok, message = send_email(company_id, recipient, subject or "", body)
        return SendResult(ok, "" if ok else message)


def notify_user(company_id: int, user_id: int, title: str, body: str) -> str:
    """فرستندهٔ کانال «ایمیل» مرکز اعلان: SENT، FAILED، NO_ADDRESS یا NOT_CONFIGURED."""
    from peecha.db.models.security import User

    with new_session() as session:
        user = session.get(User, user_id)
        address = (user.email or "").strip() if user else ""
    if not valid_address(address):
        return "NO_ADDRESS"
    settings = get_settings(company_id)
    if not settings.is_active or not settings.host:
        return "NOT_CONFIGURED"
    ok, _message = send_email(company_id, address, title, body or title)
    return "SENT" if ok else "FAILED"
