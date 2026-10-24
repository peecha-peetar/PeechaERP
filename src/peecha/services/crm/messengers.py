"""R319: پیام‌رسان‌ها در مرکز ارتباطات و «پیام پس از فرایند».

- بله، تلگرام، ایتا و روبیکا با ربات رسمی (توکن هر ربات در تنظیمات)؛ واتس‌اپ با درگاه عمومی URL (مثل درگاه پیامک).
- شناسهٔ گفت‌وگوی هر طرف حساب در هر پیام‌رسان در crm.party_messenger_ids؛ پیامک و واتس‌اپ از موبایل.
- قاعدهٔ «پس از رویداد X، الگوی Y برای Z» یک فرایند گردش کار با یک اقدام «ارسال پیام» است؛ پس رویداد، صف، تلاش
  دوباره و پایش همان موتور گردش کار است و ارسال از همان send_message مرکز ارتباطات (ثبت در دفتر پیام‌ها و تایم‌لاین).
همه پشت کلید «MSG_AFTER_PROCESS»؛ با کلید خاموش اقدام هیچ پیامی نمی‌فرستد.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass

from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.crm import MessengerSetting, PartyMessengerId
from peecha.services.crm import communication as comm

FEATURE = "MSG_AFTER_PROCESS"
BOT_CHANNELS = ("BALE", "TELEGRAM", "EITAA", "RUBIKA")  # ترتیب نمایش؛ همان comm.BOT_CHANNELS
GATEWAY_CHANNELS = ("WHATSAPP",)
RECIPIENTS = {"COUNTERPARTY": "طرف حساب همان سند", "FIXED": "گیرندهٔ ثابت (شماره یا شناسهٔ گفت‌وگو/گروه)",
              "USER": "کاربر برنامه (اعلان داخلی)"}
RULE_CATEGORY = "MESSAGE"
RULE_FIELDS_HINT = "{نام} طرف حساب، {شماره} شمارهٔ سند، {مبلغ} مبلغ، {تاریخ} تاریخ سند، {عنوان} عنوان سند، {شرکت} نام شرکت شما"


def is_on(company_id: int) -> bool:
    from peecha.services import inventory_engine as engine

    return engine.is_feature_enabled(company_id, FEATURE)


# --- تنظیمات هر پیام‌رسان --------------------------------------------------------------------------------
@dataclass
class ChannelSetting:
    channel: str
    label: str
    kind: str  # BOT | GATEWAY
    is_active: bool = False
    has_secret: bool = False
    base_url: str = ""
    http_method: str = "GET"
    last_error: str | None = None


def _secret(row: MessengerSetting | None) -> str:
    from peecha.services import ecommerce_credentials

    if row is None:
        return ""
    return ecommerce_credentials.decrypt_credentials(row.secret_encrypted).get("secret", "")


def list_settings(company_id: int) -> list[ChannelSetting]:
    with new_session() as session:
        rows = {r.channel: r for r in session.scalars(select(MessengerSetting).where(MessengerSetting.company_id == company_id))}
        out = []
        for ch in BOT_CHANNELS + GATEWAY_CHANNELS:
            r = rows.get(ch)
            out.append(ChannelSetting(ch, comm.CHANNELS[ch], "BOT" if ch in BOT_CHANNELS else "GATEWAY",
                                      bool(r and r.is_active), bool(r and r.secret_encrypted), (r.base_url or "") if r else "",
                                      (r.http_method or "GET") if r else "GET", r.last_error if r else None))
        return out


def save_setting(company_id: int, user_id: int | None, channel: str, *, secret: str | None, is_active: bool,
                 base_url: str | None = None, http_method: str = "GET") -> None:
    """secret: توکن ربات، یا الگوی نشانی درگاه با {phone} و {text}؛ خالی یعنی همان قبلی بماند."""
    from peecha.services import ecommerce_credentials
    from peecha.services.crm import common as c

    if channel not in BOT_CHANNELS + GATEWAY_CHANNELS:
        raise ValueError("پیام‌رسان نامعتبر است.")
    secret = (secret or "").strip()
    if channel in GATEWAY_CHANNELS and secret and ("{phone}" not in secret or "{text}" not in secret):
        raise ValueError("الگوی نشانی درگاه باید {phone} و {text} داشته باشد.")
    with new_session() as session:
        row = session.scalar(select(MessengerSetting).where(MessengerSetting.company_id == company_id,
                                                           MessengerSetting.channel == channel))
        if row is None:
            row = MessengerSetting(company_id=company_id, channel=channel)
            session.add(row)
        if secret:
            row.secret_encrypted = ecommerce_credentials.encrypt_credentials({"secret": secret})
        if is_active and not (secret or row.secret_encrypted):
            raise ValueError("برای روشن‌کردن، ابتدا توکن ربات یا نشانی درگاه را وارد کنید.")
        row.is_active = bool(is_active)
        row.base_url = (base_url or "").strip() or None
        row.http_method = "POST" if (http_method or "").upper() == "POST" else "GET"
        row.updated_by_user_id, row.updated_at = user_id, datetime.datetime.now().astimezone()
        session.flush()
        c.audit(session, company_id, user_id, "MessengerSetting", row.setting_id, "UPDATE",
                {"channel": channel, "is_active": row.is_active, "secret_changed": bool(secret)})
        session.commit()


def _setting(company_id: int, channel: str) -> MessengerSetting | None:
    with new_session() as session:
        row = session.scalar(select(MessengerSetting).where(MessengerSetting.company_id == company_id,
                                                           MessengerSetting.channel == channel))
        if row is not None:
            session.expunge(row)
        return row


def _record(company_id: int, channel: str, error: str | None) -> None:
    with new_session() as session:
        row = session.scalar(select(MessengerSetting).where(MessengerSetting.company_id == company_id,
                                                           MessengerSetting.channel == channel))
        if row is not None:
            row.last_error = (error or None) and error[:500]
            row.last_checked_at = datetime.datetime.now().astimezone()
            session.commit()


def test_setting(company_id: int, channel: str) -> tuple[bool, str]:
    from peecha.integrations.social import messenger_bots

    row = _setting(company_id, channel)
    if row is None or not row.secret_encrypted:
        return False, "این پیام‌رسان هنوز تنظیم نشده است."
    if channel in GATEWAY_CHANNELS:
        return True, "درگاه عمومی با اولین ارسال آزموده می‌شود (پاسخ هر سرویس متفاوت است)."
    ok, message = messenger_bots.check_connection(channel, _secret(row), row.base_url)
    _record(company_id, channel, None if ok else message)
    return ok, message


# --- شناسهٔ گفت‌وگوی طرف حساب ------------------------------------------------------------------------------
def set_chat_id(company_id: int, party_detail_account_id: int, channel: str, chat_id: str | None) -> None:
    if channel not in BOT_CHANNELS:
        raise ValueError("شناسهٔ گفت‌وگو فقط برای بله، تلگرام، ایتا و روبیکا لازم است.")
    chat_id = (chat_id or "").strip()
    with new_session() as session:
        row = session.get(PartyMessengerId, (party_detail_account_id, channel))
        if not chat_id:
            if row is not None:
                session.delete(row)
        elif row is None:
            session.add(PartyMessengerId(party_detail_account_id=party_detail_account_id, channel=channel, chat_id=chat_id,
                                         company_id=company_id))
        else:
            row.chat_id = chat_id
        session.commit()


def chat_ids(company_id: int, party_detail_account_id: int | None = None) -> list[PartyMessengerId]:
    with new_session() as session:
        q = select(PartyMessengerId).where(PartyMessengerId.company_id == company_id)
        if party_detail_account_id is not None:
            q = q.where(PartyMessengerId.party_detail_account_id == party_detail_account_id)
        rows = list(session.scalars(q.order_by(PartyMessengerId.party_detail_account_id, PartyMessengerId.channel)))
        session.expunge_all()
        return rows


def chat_id_of(session, party_detail_account_id: int, channel: str) -> str | None:
    row = session.get(PartyMessengerId, (party_detail_account_id, channel))
    return row.chat_id if row is not None else None


# --- ارسال‌کننده‌ها (Provider مرکز ارتباطات) -----------------------------------------------------------------
class BotProvider:
    def __init__(self, channel: str) -> None:
        self.channel, self.code = channel, f"{channel}_BOT"

    def send(self, company_id: int, recipient: str, subject: str | None, body: str) -> comm.SendResult:
        from peecha.integrations.social import messenger_bots

        row = _setting(company_id, self.channel)
        if row is None or not row.is_active or not row.secret_encrypted:
            return comm.SendResult(False, f"ربات {comm.CHANNELS[self.channel]} تنظیم نشده یا خاموش است.")
        text = f"{subject}\n{body}" if subject else body
        try:
            messenger_bots.send_message(self.channel, _secret(row), recipient, text, row.base_url)
        except Exception as exc:  # noqa: BLE001 -- خطای سرویس بیرونی فقط پیام را «ناموفق» می‌کند
            _record(company_id, self.channel, str(exc))
            return comm.SendResult(False, str(exc)[:500])
        _record(company_id, self.channel, None)
        return comm.SendResult(True)


class UrlGatewayProvider:
    def __init__(self, channel: str) -> None:
        self.channel, self.code = channel, f"{channel}_GATEWAY"

    def send(self, company_id: int, recipient: str, subject: str | None, body: str) -> comm.SendResult:
        from peecha.services import sms_gateway

        row = _setting(company_id, self.channel)
        if row is None or not row.is_active or not row.secret_encrypted:
            return comm.SendResult(False, f"درگاه {comm.CHANNELS[self.channel]} تنظیم نشده یا خاموش است.")
        res = sms_gateway.send_sms(_secret(row), row.http_method or "GET", recipient, body)
        _record(company_id, self.channel, None if res.success else res.message)
        return comm.SendResult(res.success, "" if res.success else res.message)


def register_providers() -> None:
    """فقط جای «وصل‌نشده» را می‌گیرد؛ سرویسی که پیش‌تر با register_provider وصل شده دست نمی‌خورد."""
    for ch, provider in [(ch, BotProvider(ch)) for ch in BOT_CHANNELS] + [(ch, UrlGatewayProvider(ch)) for ch in GATEWAY_CHANNELS]:
        if isinstance(comm._providers.get(ch), comm.NotConfiguredProvider):
            comm.register_provider(ch, provider)


# --- قاعدهٔ «پیام پس از فرایند» (فرایند گردش کار یک‌اقدامی) ----------------------------------------------------
@dataclass
class EventChoice:
    event_type: str
    label: str
    entity_type: str


def event_choices() -> list[EventChoice]:
    from peecha.services.workflow import registry

    out = []
    for a in registry.adapters():
        for code, label in a.events.items():
            out.append(EventChoice(code, f"{a.label}: {label}", a.entity_type))
    return sorted(out, key=lambda e: e.label)


@dataclass
class RuleRow:
    definition_id: int
    name: str
    event_type: str
    event_label: str
    channel: str
    template_id: int | None
    body: str
    recipient: str
    target: str
    notify_user_id: int | None
    status_code: str
    status_label: str
    is_active: bool


def _action_node(graph: dict) -> dict:
    return next((n for n in graph.get("nodes") or [] if n.get("type") == "ACTION" and n.get("action") == "send_message"), {})


def list_rules(company_id: int) -> list[RuleRow]:
    from peecha.services.workflow import definitions

    labels = {e.event_type: e.label for e in event_choices()}
    out = []
    for d in definitions.list_definitions(company_id, include_archived=False):
        if d.category != RULE_CATEGORY:
            continue
        graph = definitions.get_graph(company_id, d.definition_id)
        events = ((graph.get("trigger") or {}).get("events") or [""])
        p = _action_node(graph).get("params") or {}
        out.append(RuleRow(d.definition_id, d.name, events[0], labels.get(events[0], events[0]), p.get("channel", "SMS"),
                           p.get("template_id"), p.get("body", ""), p.get("recipient", "COUNTERPARTY"), p.get("target", ""),
                           p.get("notify_user_id"), d.status_code, d.status_label, d.status_code in ("PUBLISHED", "ACTIVE")))
    return out


def save_rule(company_id: int, user_id: int | None, *, name: str, event_type: str, channel: str,
              template_id: int | None = None, body: str = "", recipient: str = "COUNTERPARTY", target: str = "",
              notify_user_id: int | None = None, definition_id: int | None = None) -> int:
    from peecha.services.workflow import builder, definitions
    from peecha.services.workflow.builder import WizardSpec

    name = (name or "").strip()
    choice = next((e for e in event_choices() if e.event_type == event_type), None)
    if not name:
        raise ValueError("نام قاعده الزامی است.")
    if choice is None:
        raise ValueError("رویداد را انتخاب کنید.")
    if recipient not in RECIPIENTS:
        raise ValueError("گیرنده نامعتبر است.")
    if recipient == "USER":
        channel = "INTERNAL"
        if not notify_user_id:
            raise ValueError("کاربر گیرنده را انتخاب کنید.")
    elif channel not in comm.CHANNELS or channel == "INTERNAL":
        raise ValueError("کانال ارسال نامعتبر است.")
    if recipient == "FIXED" and not (target or "").strip():
        raise ValueError("شماره یا شناسهٔ گیرندهٔ ثابت را وارد کنید.")
    if not template_id and not (body or "").strip():
        raise ValueError("یک الگو انتخاب کنید یا متن پیام را بنویسید.")
    code = f"MSG_{event_type}"[:40]
    graph = builder.build_graph(WizardSpec(name=name, code=code, entity_type=choice.entity_type,
                                           trigger={"type": "EVENT", "events": [event_type]}, actions=["send_message"],
                                           notify_on_approve=False, notify_on_reject=False))
    _action_node(graph)["params"] = {"channel": channel, "template_id": template_id, "body": (body or "").strip(),
                                     "recipient": recipient, "target": (target or "").strip(), "notify_user_id": notify_user_id}
    if definition_id is None:
        existing = {d.code for d in definitions.list_definitions(company_id)}
        n, unique = 1, code
        while unique in existing:
            n += 1
            unique = f"{code[:36]}_{n}"
        definition_id = definitions.create_definition(company_id, user_id, code=unique, name=name,
                                                      entity_type=choice.entity_type, category=RULE_CATEGORY,
                                                      description="پیام پس از فرایند")
    else:
        definitions.update_info(company_id, user_id, definition_id, name=name, description="پیام پس از فرایند",
                                category=RULE_CATEGORY)
    definitions.save_draft(company_id, user_id, definition_id, graph)
    definitions.publish(company_id, user_id, definition_id)
    return definition_id


def set_rule_active(company_id: int, user_id: int | None, definition_id: int, active: bool) -> None:
    from peecha.services.workflow import definitions

    definitions.set_status(company_id, user_id, definition_id, "ACTIVE" if active else "PAUSED")


def delete_rule(company_id: int, user_id: int | None, definition_id: int) -> None:
    """بدون سابقهٔ اجرا حذف، وگرنه بایگانی (سابقهٔ ارسال‌ها می‌ماند)."""
    from peecha.services.workflow import definitions
    from peecha.services.workflow.common import WorkflowError

    try:
        definitions.delete_definition(company_id, user_id, definition_id)
    except WorkflowError:
        definitions.set_status(company_id, user_id, definition_id, "ARCHIVED")


# --- اقدام گردش کار «ارسال پیام» ----------------------------------------------------------------------------
_PARTY_KEYS = ("counterparty_id", "customer_detail_account_id", "customer_id", "supplier_detail_account_id", "supplier_id",
               "party_detail_account_id")


def _values(ctx) -> dict:
    from peecha import numerals
    from peecha.services.workflow import registry

    c = ctx.context or {}
    values: dict = {}
    adapter = registry.get_adapter(ctx.entity_type)
    if adapter is not None:
        for f in adapter.fields:
            v = c.get(f.key)
            if v is None:
                continue
            values[f.label] = numerals.format_jalali_date(v) if isinstance(v, datetime.date) else numerals.to_persian_digits(str(v))
        values["عنوان"] = adapter.describe(c)
    number = c.get("document_no") or c.get("code") or ctx.entity_id
    values["شماره"] = numerals.to_persian_digits(str(number)) if number is not None else ""
    amount = c.get("total_amount") if c.get("total_amount") is not None else c.get("amount")
    if amount is not None:
        from peecha import decimals

        values["amount"] = decimals.format_amount(amount)
    date = c.get("document_date") or c.get("date")
    if isinstance(date, datetime.date):
        values["تاریخ"] = numerals.format_jalali_date(date)
    values["subject"] = values.get("عنوان", "")
    return values


def _party(context: dict) -> int | None:
    for key in _PARTY_KEYS:
        if context.get(key):
            return int(context[key])
    return None


def send_action(ctx) -> dict:
    p = ctx.params or {}
    if ctx.dry_run:
        return {"dry_run": True}
    if not is_on(ctx.company_id):
        return {"skipped": "پیام پس از فرایند در تنظیمات خاموش است."}
    channel, recipient = p.get("channel") or "SMS", p.get("recipient") or "COUNTERPARTY"
    template_id = int(p["template_id"]) if p.get("template_id") else None
    body, values = p.get("body") or "", _values(ctx)
    if recipient == "USER":
        message_id = comm.send_message(ctx.company_id, ctx.user_id, "INTERNAL", body, template_id=template_id, values=values,
                                       notify_user_id=int(p["notify_user_id"]), customer_id=_party(ctx.context or {}))
    elif recipient == "FIXED":
        message_id = comm.send_message(ctx.company_id, ctx.user_id, channel, body, template_id=template_id, values=values,
                                       to=p.get("target"))
    else:
        party = _party(ctx.context or {})
        if party is None:
            return {"skipped": "این سند طرف حسابی ندارد."}
        message_id = comm.send_message(ctx.company_id, ctx.user_id, channel, body, customer_id=party,
                                       template_id=template_id, values=values)
    from peecha.db.models.crm import Message

    with new_session() as session:
        msg = session.get(Message, message_id)
        return {"message_id": message_id, "status": msg.status_code if msg else None,
                "error": msg.error_message if msg else None}
