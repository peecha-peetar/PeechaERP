"""مرکز ارتباطات CRM (فاز ۸، R287).

هر کانال (پیامک، ایمیل، واتس‌اپ، تلگرام، اعلان داخلی) پشت یک Provider است. پیامک از همان درگاه پیامک موجود
(sms_gateway) فرستاده می‌شود و اعلان داخلی از سرویس اعلان‌ها؛ برای ایمیل و پیام‌رسان‌ها فقط نقطهٔ اتصال هست
(register_provider) تا بدون تغییر بقیهٔ کد وصل شوند. هر پیام در crm.messages و به‌صورت فعالیت در تایم‌لاین مشتری ثبت می‌شود.
"""

from __future__ import annotations

import datetime
import string
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.accounting import CustomerDetail, DetailAccount
from peecha.db.models.core import Company
from peecha.db.models.crm import Lead, Message, MessageTemplate
from peecha.services import sms_gateway as sms_gateway_service
from peecha.services.crm import activities as act_service
from peecha.services.crm import common as c

CHANNELS = {"SMS": "پیامک", "EMAIL": "ایمیل", "WHATSAPP": "واتس‌اپ", "TELEGRAM": "تلگرام", "INTERNAL": "اعلان داخلی"}
STATUS = {"QUEUED": "در صف", "SENT": "ارسال‌شده", "FAILED": "ناموفق"}
_ACTIVITY_TYPE = {"SMS": "MESSAGE", "WHATSAPP": "MESSAGE", "TELEGRAM": "MESSAGE", "EMAIL": "EMAIL", "INTERNAL": "NOTE"}
TEMPLATE_FIELDS = {"name": "نام مشتری/سرنخ", "company": "نام شرکت شما", "balance": "ماندهٔ حساب", "overdue": "بدهی معوق",
                   "days": "روزهای بدون خرید", "amount": "مبلغ", "subject": "موضوع"}
# R289: جای‌نگهدار فارسی هم‌ارز هر فیلد ({نام} همان {name})؛ متن‌های قدیمی انگلیسی هم کار می‌کنند.
PERSIAN_FIELDS = {"نام": "name", "شرکت": "company", "مانده": "balance", "معوق": "overdue", "روز": "days", "مبلغ": "amount",
                  "موضوع": "subject"}


def fields_hint() -> str:
    return "، ".join(f"{{{fa}}} {TEMPLATE_FIELDS[en]}" for fa, en in PERSIAN_FIELDS.items())


@dataclass
class SendResult:
    ok: bool
    info: str = ""


class Provider(Protocol):
    code: str

    def send(self, company_id: int, recipient: str, subject: str | None, body: str) -> SendResult: ...


class SmsProvider:
    code = "SMS_GATEWAY"

    def send(self, company_id: int, recipient: str, subject: str | None, body: str) -> SendResult:
        gateway = sms_gateway_service.get_sms_gateway(company_id)
        if gateway is None or not gateway.is_active:
            return SendResult(False, "درگاه پیامک تنظیم نشده یا غیرفعال است.")
        res = sms_gateway_service.send_sms(gateway.request_template, gateway.http_method, recipient, body)
        return SendResult(res.success, "" if res.success else res.message)


class NotConfiguredProvider:
    def __init__(self, channel: str) -> None:
        self.code, self.channel = f"{channel}_NONE", channel

    def send(self, company_id: int, recipient: str, subject: str | None, body: str) -> SendResult:
        return SendResult(False, f"سرویس {CHANNELS[self.channel]} هنوز وصل نشده است.")


_providers: dict[str, Provider] = {"SMS": SmsProvider(), "EMAIL": NotConfiguredProvider("EMAIL"),
                                   "WHATSAPP": NotConfiguredProvider("WHATSAPP"), "TELEGRAM": NotConfiguredProvider("TELEGRAM")}


def register_provider(channel: str, provider: Provider | None) -> None:
    """اتصال سرویس ایمیل/واتس‌اپ/تلگرام (یا جایگزینی پیامک)؛ None یعنی بازگشت به حالت پیش‌فرض."""
    if channel not in CHANNELS or channel == "INTERNAL":
        raise ValueError("کانال نامعتبر است.")
    _providers[channel] = provider or (SmsProvider() if channel == "SMS" else NotConfiguredProvider(channel))


def get_provider(channel: str) -> Provider:
    return _providers[channel]


# --- الگوها --------------------------------------------------------------------------------------------
class _SafeDict(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def render(text: str, values: dict) -> str:
    """جای‌گذاری {نام} / {name} و ... ؛ فیلد ناشناخته دست‌نخورده می‌ماند (خطا نمی‌دهد)."""
    known = {k: v for k, v in values.items() if v is not None}
    known.update({fa: known[en] for fa, en in PERSIAN_FIELDS.items() if en in known and fa not in known})
    return string.Formatter().vformat(text or "", (), _SafeDict(known))


def list_templates(company_id: int, active_only: bool = False) -> list[MessageTemplate]:
    with new_session() as session:
        q = select(MessageTemplate).where(MessageTemplate.company_id == company_id)
        if active_only:
            q = q.where(MessageTemplate.is_active.is_(True))
        rows = list(session.scalars(q.order_by(MessageTemplate.name)))
        session.expunge_all()
        return rows


def save_template(company_id: int, user_id: int | None, *, template_id: int | None = None, code: str, name: str, channel: str,
                  body: str, subject: str | None = None, is_active: bool = True) -> int:
    code, name, body = (code or "").strip().upper(), (name or "").strip(), (body or "").strip()
    if not code or not name or not body:
        raise ValueError("کد، نام و متن الگو الزامی است.")
    if channel not in CHANNELS:
        raise ValueError("کانال نامعتبر است.")
    with new_session() as session:
        dup = session.scalar(select(MessageTemplate.template_id).where(MessageTemplate.company_id == company_id,
                                                                       MessageTemplate.code == code))
        if dup and dup != template_id:
            raise ValueError("کد الگو تکراری است.")
        if template_id:
            t = session.get(MessageTemplate, template_id)
            if t is None or t.company_id != company_id:
                raise ValueError("الگو نامعتبر است.")
        else:
            t = MessageTemplate(company_id=company_id)
            session.add(t)
        t.code, t.name, t.channel, t.body, t.subject, t.is_active = code, name, channel, body, (subject or "").strip() or None, is_active
        session.flush()
        c.audit(session, company_id, user_id, "MessageTemplate", t.template_id, "UPDATE" if template_id else "CREATE", {"code": code})
        session.commit()
        return t.template_id


def delete_template(company_id: int, user_id: int | None, template_id: int) -> None:
    with new_session() as session:
        t = session.get(MessageTemplate, template_id)
        if t is None or t.company_id != company_id:
            raise ValueError("الگو نامعتبر است.")
        c.audit(session, company_id, user_id, "MessageTemplate", template_id, "DELETE", {"code": t.code})
        session.delete(t)
        session.commit()


# --- ارسال ---------------------------------------------------------------------------------------------
def _recipient(session, company_id: int, channel: str, customer_id: int | None, lead_id: int | None) -> tuple[str | None, str]:
    """(نشانی گیرنده در این کانال، نام). ایمیل از مخاطب اصلی/سرنخ؛ پیامک و پیام‌رسان از موبایل."""
    if customer_id:
        da = session.get(DetailAccount, customer_id)
        if da is None or da.company_id != company_id:
            raise ValueError("مشتری نامعتبر است.")
        det = session.get(CustomerDetail, customer_id)
        if channel == "EMAIL":
            from peecha.db.models.commercial import PartyContact

            email = session.scalar(select(PartyContact.email).where(PartyContact.party_detail_account_id == customer_id,
                                                                   PartyContact.email.is_not(None))
                                   .order_by(PartyContact.is_primary.desc()).limit(1))
            return email, da.name
        return (det.mobile or det.phone) if det else None, da.name
    if lead_id:
        lead = session.get(Lead, lead_id)
        if lead is None or lead.company_id != company_id:
            raise ValueError("سرنخ نامعتبر است.")
        return (lead.email if channel == "EMAIL" else lead.mobile or lead.phone), lead.full_name
    raise ValueError("گیرنده (مشتری یا سرنخ) مشخص نشده است.")


def send_message(company_id: int, user_id: int | None, channel: str, body: str, *, customer_id: int | None = None,
                 lead_id: int | None = None, subject: str | None = None, template_id: int | None = None,
                 values: dict | None = None, campaign_id: int | None = None, rule_id: int | None = None,
                 notify_user_id: int | None = None) -> int:
    """ارسال پیام به مشتری/سرنخ (یا اعلان داخلی به کاربر). شکست ارسال خطا نمی‌دهد: پیام با وضعیت «ناموفق» ثبت
    می‌شود تا در دفتر پیام‌ها دیده و دوباره فرستاده شود. برمی‌گرداند: شناسهٔ پیام."""
    if channel not in CHANNELS:
        raise ValueError("کانال نامعتبر است.")
    with new_session() as session:
        if template_id:
            tpl = session.get(MessageTemplate, template_id)
            if tpl is None or tpl.company_id != company_id:
                raise ValueError("الگو نامعتبر است.")
            body, subject = body or tpl.body, subject or tpl.subject
        if not (body or "").strip():
            raise ValueError("متن پیام خالی است.")
        if channel == "INTERNAL":
            recipient, name = None, ""
            if not notify_user_id:
                raise ValueError("کاربر گیرندهٔ اعلان مشخص نشده است.")
            if customer_id:
                name = session.get(DetailAccount, customer_id).name
        else:
            recipient, name = _recipient(session, company_id, channel, customer_id, lead_id)
        company = session.get(Company, company_id)
        text = render(body.strip(), {"name": name, "company": company.display_name if company else "", **(values or {})})
        subj = render(subject, {"name": name, **(values or {})}) if subject else None
        msg = Message(company_id=company_id, channel=channel, customer_detail_account_id=customer_id, lead_id=lead_id,
                      recipient=recipient, subject=subj, body=text[:2000], template_id=template_id, campaign_id=campaign_id,
                      rule_id=rule_id, created_by_user_id=user_id, status_code="QUEUED")
        session.add(msg)
        session.commit()
        message_id = msg.message_id
    if channel == "INTERNAL":
        c.notify(company_id, notify_user_id, "CRM_MESSAGE", subj or "پیام ارتباط با مشتری", text, "CrmCustomer" if customer_id else "CrmMessage",
                 customer_id or message_id)
        result = SendResult(True)
        provider_code = "NOTIFICATION"
    elif not recipient:
        result, provider_code = SendResult(False, f"گیرنده برای {CHANNELS[channel]} نشانی ثبت‌شده ندارد."), None
    else:
        provider = get_provider(channel)
        provider_code = provider.code
        try:
            result = provider.send(company_id, recipient, subj, text)
        except Exception as exc:  # noqa: BLE001 -- خطای سرویس بیرونی نباید ثبت پیام را از بین ببرد
            result = SendResult(False, str(exc)[:500])
    activity_id = None
    if customer_id or lead_id:
        activity_id = act_service.create_activity(company_id, user_id or _company_admin(company_id), act_service.ActivityFields(
            _ACTIVITY_TYPE[channel], (subj or f"{CHANNELS[channel]}: {text[:60]}")[:200], customer_detail_account_id=customer_id,
            lead_id=lead_id, description=text, due_date=datetime.date.today()))
        if _ACTIVITY_TYPE[channel] != "NOTE":
            act_service.complete_activity(company_id, user_id or _company_admin(company_id), activity_id,
                                          "ارسال شد" if result.ok else f"ارسال نشد: {result.info}")
    with new_session() as session:
        msg = session.get(Message, message_id)
        msg.status_code, msg.error_message, msg.provider_code = ("SENT" if result.ok else "FAILED"), (result.info or None), provider_code
        msg.sent_at = c.now() if result.ok else None
        msg.activity_id = activity_id
        session.commit()
    return message_id


def _company_admin(company_id: int) -> int:
    """فعالیت‌های خودکار (اتوماسیون بدون کاربر) به نام اولین کاربر شرکت ثبت می‌شوند."""
    users = c.list_company_users(company_id)
    if not users:
        raise ValueError("شرکت کاربری ندارد.")
    return users[0][0]


def retry_message(company_id: int, user_id: int | None, message_id: int) -> int:
    with new_session() as session:
        m = session.get(Message, message_id)
        if m is None or m.company_id != company_id:
            raise ValueError("پیام نامعتبر است.")
        if m.status_code != "FAILED":
            raise ValueError("فقط پیام ناموفق دوباره فرستاده می‌شود.")
        args = (m.channel, m.body, m.customer_detail_account_id, m.lead_id, m.subject, m.campaign_id, m.rule_id)
    channel, body, customer, lead, subject, campaign, rule = args
    return send_message(company_id, user_id, channel, body, customer_id=customer, lead_id=lead, subject=subject,
                        campaign_id=campaign, rule_id=rule)


@dataclass
class MessageRow:
    message_id: int
    channel: str
    channel_label: str
    customer_detail_account_id: int | None
    lead_id: int | None
    party_name: str
    recipient: str | None
    subject: str | None
    body: str
    status_code: str
    status_label: str
    error_message: str | None
    created_at: datetime.datetime
    sent_at: datetime.datetime | None
    rule_id: int | None
    campaign_id: int | None


def list_messages(company_id: int, *, customer_id: int | None = None, channel: str | None = None, status: str | None = None,
                  limit: int = 300, offset: int = 0) -> list[MessageRow]:
    with new_session() as session:
        q = (select(Message, DetailAccount.name, Lead.full_name)
             .outerjoin(DetailAccount, DetailAccount.detail_account_id == Message.customer_detail_account_id)
             .outerjoin(Lead, Lead.lead_id == Message.lead_id).where(Message.company_id == company_id))
        if customer_id:
            q = q.where(Message.customer_detail_account_id == customer_id)
        if channel:
            q = q.where(Message.channel == channel)
        if status:
            q = q.where(Message.status_code == status)
        rows = session.execute(q.order_by(Message.message_id.desc()).limit(limit).offset(offset)).all()
        return [MessageRow(m.message_id, m.channel, CHANNELS.get(m.channel, m.channel), m.customer_detail_account_id, m.lead_id,
                           cname or lname or "", m.recipient, m.subject, m.body, m.status_code, STATUS[m.status_code], m.error_message,
                           m.created_at, m.sent_at, m.rule_id, m.campaign_id) for m, cname, lname in rows]
