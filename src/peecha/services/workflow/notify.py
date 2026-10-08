"""مرکز اعلان پیچا: یک نقطهٔ واحد ارسال، با کانال‌های داخل برنامه، پیام روی صفحهٔ رایانه، پیامک، ایمیل و اعلان گوشی.

هر اعلان یک ردیف sec.notifications است (همان که اپ موبایل و زنگولهٔ دسکتاپ می‌خوانند). کانال‌های بیرونی (پیامک،
ایمیل، گوشی) در صف می‌مانند و زمان‌بند آن‌ها را جدا از تراکنش اصلی می‌فرستد، تا کندی یا قطعی سرویس بیرونی هیچ
تاییدی را معطل نکند. ایمیل و اعلان گوشی فعلاً «رابط» دارند و با register_email_sender/register_push_sender وصل
می‌شوند.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Callable

from sqlalchemy import event as sa_event, func, or_, select, update
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from peecha.db.base import new_session
from peecha.db.models.security import Notification, NotificationPreference, User

TYPES = {
    "WF_APPROVAL_REQUIRED": "نیاز به تایید", "WF_TASK_ASSIGNED": "کار تازه", "WF_TASK_DUE": "نزدیک شدن موعد",
    "WF_SLA_WARNING": "هشدار مهلت", "WF_SLA_BREACHED": "گذشتن از مهلت", "WF_COMPLETED": "پایان فرایند",
    "WF_FAILED": "شکست فرایند", "WF_EXCEPTION": "مورد نیازمند بررسی", "WF_ESCALATION": "ارجاع به سطح بالاتر",
    "WF_MESSAGE": "پیام فرایند", "WF_DELEGATION": "تفویض اختیار",
}
OTHER_TYPES = {
    "CRM_TASK_ASSIGNED": "کار تازهٔ ارتباط با مشتری", "CRM_LEAD_ASSIGNED": "سرنخ واگذارشده",
    "CRM_OPPORTUNITY_ASSIGNED": "فرصت فروش واگذارشده", "CRM_TICKET_ASSIGNED": "تیکت واگذارشده",
    "CRM_TICKET_SLA": "مهلت تیکت", "CRM_MESSAGE": "پیام ارتباط با مشتری", "CRM_AUTOMATION": "اقدام خودکار ارتباط با مشتری",
}
CHANNELS = {"in_app": "داخل برنامه", "desktop": "پیام روی صفحه", "sms": "پیامک", "email": "ایمیل", "push": "اعلان گوشی"}
EXTERNAL = ("sms", "email", "push")
DEFAULT_CHANNELS = {"in_app": True, "desktop": True, "sms": False, "email": False, "push": False}
PRIORITY_OF = {"WF_SLA_BREACHED": "HIGH", "WF_EXCEPTION": "HIGH", "WF_ESCALATION": "CRITICAL", "WF_FAILED": "HIGH"}
DELIVERY_STATUS = {"PENDING": "در صف ارسال", "SENT": "ارسال شد", "FAILED": "ارسال نشد", "NO_ADDRESS": "نشانی/شماره ثبت نشده",
                   "NOT_CONFIGURED": "سرویس وصل نیست"}
_CHANNEL_SENDERS: list[Callable[..., None]] = []


def type_label(type_code: str) -> str:
    return TYPES.get(type_code) or OTHER_TYPES.get(type_code) or "اعلان"


def register_channel(sender: Callable[..., None]) -> None:
    """کانال اضافه (هم‌زمان) -- sender(company_id, user_id, type_code, title, body, entity_type, entity_id)."""
    _CHANNEL_SENDERS.append(sender)


# --- ترجیحات کانال ----------------------------------------------------------------------------------------------
def _company_defaults(company_id: int) -> dict:
    from peecha.services.workflow.common import settings

    return settings(company_id).get("notification_defaults") or {}


def effective_channels(company_id: int, user_id: int, type_code: str, *, _prefs: dict | None = None,
                       _defaults: dict | None = None) -> dict[str, bool]:
    """پیش‌فرض برنامه ← پیش‌فرض شرکت برای این نوع ← ترجیح عمومی کاربر ← ترجیح کاربر برای همین نوع."""
    out = dict(DEFAULT_CHANNELS)
    out.update({k: bool(v) for k, v in ((_company_defaults(company_id) if _defaults is None else _defaults)
                                        .get(type_code) or {}).items() if k in CHANNELS})
    prefs = _prefs if _prefs is not None else user_preferences(company_id, user_id)
    for key in ("*", type_code):
        if key in prefs:
            out.update(prefs[key])
    return out


def user_preferences(company_id: int, user_id: int) -> dict[str, dict[str, bool]]:
    with new_session() as session:
        rows = session.scalars(select(NotificationPreference).where(NotificationPreference.company_id == company_id,
                                                                    NotificationPreference.user_id == user_id))
        return {r.type_code: {c: bool(getattr(r, c)) for c in CHANNELS} for r in rows}


def save_preference(company_id: int, user_id: int, type_code: str, **channels: bool) -> None:
    if type_code != "*" and type_code not in TYPES and type_code not in OTHER_TYPES:
        raise ValueError("نوع اعلان نامعتبر است.")
    unknown = set(channels) - set(CHANNELS)
    if unknown:
        raise ValueError("کانال نامعتبر است.")
    with new_session() as session:
        row = session.get(NotificationPreference, (company_id, user_id, type_code))
        if row is None:
            base = effective_channels(company_id, user_id, type_code)
            row = NotificationPreference(company_id=company_id, user_id=user_id, type_code=type_code, **base)
            session.add(row)
        for key, value in channels.items():
            setattr(row, key, bool(value))
        session.commit()


def reset_preferences(company_id: int, user_id: int) -> None:
    with new_session() as session:
        session.query(NotificationPreference).filter(NotificationPreference.company_id == company_id,
                                                     NotificationPreference.user_id == user_id).delete()
        session.commit()


# --- ارسال -----------------------------------------------------------------------------------------------------
def send(company_id: int, user_ids, type_code: str, title: str, body: str = "", entity_type: str | None = "WfInstance",
         entity_id: int | None = None, *, priority: str | None = None) -> int:
    targets = sorted({int(u) for u in user_ids if u})
    if not targets:
        return 0
    defaults = _company_defaults(company_id)
    sent = 0
    with new_session() as session:
        for uid in targets:
            prefs = {r.type_code: {c: bool(getattr(r, c)) for c in CHANNELS} for r in session.scalars(
                select(NotificationPreference).where(NotificationPreference.company_id == company_id,
                                                     NotificationPreference.user_id == uid))}
            eff = effective_channels(company_id, uid, type_code, _prefs=prefs, _defaults=defaults)
            outbound = {c: "PENDING" for c in EXTERNAL if eff.get(c)}
            if not (eff["in_app"] or eff["desktop"] or outbound):
                continue
            session.add(Notification(company_id=company_id, user_id=uid, type_code=type_code, title=(title or "")[:200],
                                     body=body or None, entity_type=entity_type, entity_id=entity_id,
                                     is_read=not eff["in_app"], priority_code=priority or PRIORITY_OF.get(type_code, "NORMAL"),
                                     channels={"desktop": bool(eff["desktop"]), **outbound}))
            sent += 1
        session.commit()
    for uid in targets:
        for sender in _CHANNEL_SENDERS:
            try:
                sender(company_id, uid, type_code, title, body, entity_type, entity_id)
            except Exception:  # noqa: BLE001 -- خطای یک کانال بیرونی نباید اعلان درون‌برنامه را خراب کند
                pass
    return sent


def later(session, company_id: int, user_ids, type_code: str, title: str, body: str = "",
          entity_type: str | None = "WfInstance", entity_id: int | None = None) -> None:
    """اعلان پس از commit همین تراکنش (اگر تراکنش برگشت بخورد اعلانی هم نمی‌رود)."""
    session.info.setdefault("wf_notes", []).append((company_id, list(user_ids), type_code, title, body, entity_type, entity_id))


@sa_event.listens_for(Session, "after_commit")
def _send_later(session) -> None:
    for args in session.info.pop("wf_notes", None) or []:
        try:
            send(*args)
        except Exception:  # noqa: BLE001 -- خطای اعلان نباید تصمیم ثبت‌شده را خراب کند
            pass


@sa_event.listens_for(Session, "after_rollback")
def _drop_later(session) -> None:
    session.info.pop("wf_notes", None)


# --- کانال‌های بیرونی (در صف، با زمان‌بند) -------------------------------------------------------------------------
def user_mobile(company_id: int, user_id: int) -> str | None:
    from peecha.db.models.hr import Employee

    with new_session() as session:
        emp = session.scalar(select(Employee).where(Employee.company_id == company_id, Employee.user_id == user_id))
        return (emp.mobile or emp.phone) if emp else None


def _sms_sender(company_id: int, user_id: int, title: str, body: str) -> str:
    from peecha.services import sms_gateway

    mobile = user_mobile(company_id, user_id)
    if not mobile:
        return "NO_ADDRESS"
    gateway = sms_gateway.get_sms_gateway(company_id)
    if gateway is None or not gateway.is_active:
        return "NOT_CONFIGURED"
    res = sms_gateway.send_sms(gateway.request_template, gateway.http_method, mobile, f"{title}\n{body or ''}".strip()[:500])
    return "SENT" if res.success else "FAILED"


def _not_configured(company_id: int, user_id: int, title: str, body: str) -> str:
    return "NOT_CONFIGURED"


_EXTERNAL_SENDERS: dict[str, Callable[[int, int, str, str], str]] = {"sms": _sms_sender, "email": _not_configured,
                                                                       "push": _not_configured}


def register_email_sender(sender: Callable[[int, int, str, str], str] | None) -> None:
    """sender(company_id, user_id, title, body) -> SENT|FAILED|NO_ADDRESS؛ None یعنی «وصل نیست»."""
    _EXTERNAL_SENDERS["email"] = sender or _not_configured


def register_push_sender(sender: Callable[[int, int, str, str], str] | None) -> None:
    _EXTERNAL_SENDERS["push"] = sender or _not_configured


def register_sms_sender(sender: Callable[[int, int, str, str], str] | None) -> None:
    _EXTERNAL_SENDERS["sms"] = sender or _sms_sender


def deliver_pending(company_id: int | None = None, limit: int = 200) -> int:
    """اعلان‌های در صف کانال‌های بیرونی (دو روز اخیر) فرستاده و نتیجه‌شان ثبت می‌شود."""
    since = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=2)
    with new_session() as session:
        q = select(Notification).where(Notification.created_at >= since,
                                       or_(*[Notification.channels[c].astext == "PENDING" for c in EXTERNAL]))
        if company_id is not None:
            q = q.where(Notification.company_id == company_id)
        pending = list(session.scalars(q.order_by(Notification.notification_id).limit(limit)))
        jobs = [(n.notification_id, n.company_id, n.user_id, n.title, n.body or "",
                 [c for c in EXTERNAL if (n.channels or {}).get(c) == "PENDING"]) for n in pending]
    done = 0
    for nid, cid, uid, title, body, chans in jobs:
        results = {}
        for c in chans:
            try:
                results[c] = _EXTERNAL_SENDERS[c](cid, uid, title, body) or "FAILED"
            except Exception:  # noqa: BLE001
                results[c] = "FAILED"
        with new_session() as session:
            row = session.get(Notification, nid)
            row.channels = {**(row.channels or {}), **results}
            flag_modified(row, "channels")
            session.commit()
        done += 1
    return done


# --- مرکز اعلان (خواندن) ---------------------------------------------------------------------------------------
@dataclass
class NoteRow:
    notification_id: int
    type_code: str
    type_label: str
    title: str
    body: str
    created_at: datetime.datetime
    is_read: bool
    priority_code: str
    entity_type: str | None
    entity_id: int | None
    delivery: str


def _delivery_text(channels: dict) -> str:
    parts = [f"{CHANNELS[c]}: {DELIVERY_STATUS.get(str(channels[c]), str(channels[c]))}" for c in EXTERNAL if c in (channels or {})]
    return "، ".join(parts)


def list_notifications(company_id: int, user_id: int, *, unread_only: bool = False, type_codes: list[str] | None = None,
                       limit: int = 300) -> list[NoteRow]:
    with new_session() as session:
        q = select(Notification).where(Notification.company_id == company_id, Notification.user_id == user_id)
        if unread_only:
            q = q.where(Notification.is_read.is_(False))
        if type_codes:
            q = q.where(Notification.type_code.in_(type_codes))
        rows = session.scalars(q.order_by(Notification.notification_id.desc()).limit(limit))
        return [NoteRow(n.notification_id, n.type_code, type_label(n.type_code), n.title, n.body or "", n.created_at,
                        n.is_read, n.priority_code or "NORMAL", n.entity_type, n.entity_id, _delivery_text(n.channels or {}))
                for n in rows]


def unread_count(company_id: int, user_id: int) -> int:
    with new_session() as session:
        return int(session.scalar(select(func.count()).select_from(Notification).where(
            Notification.company_id == company_id, Notification.user_id == user_id, Notification.is_read.is_(False))) or 0)


def mark_read(company_id: int, user_id: int, notification_ids: list[int] | None = None) -> int:
    """None یعنی همه."""
    with new_session() as session:
        q = update(Notification).where(Notification.company_id == company_id, Notification.user_id == user_id,
                                       Notification.is_read.is_(False))
        if notification_ids is not None:
            q = q.where(Notification.notification_id.in_(notification_ids))
        count = session.execute(q.values(is_read=True, read_at=func.now())).rowcount
        session.commit()
        return count or 0


def desktop_popups(company_id: int, user_id: int, after_id: int) -> list[NoteRow]:
    """اعلان‌های تازه‌ای که کاربر خواسته روی صفحه هم نشان داده شوند."""
    with new_session() as session:
        rows = session.scalars(select(Notification).where(
            Notification.company_id == company_id, Notification.user_id == user_id, Notification.is_read.is_(False),
            Notification.notification_id > after_id).order_by(Notification.notification_id).limit(20))
        return [NoteRow(n.notification_id, n.type_code, type_label(n.type_code), n.title, n.body or "", n.created_at,
                        n.is_read, n.priority_code or "NORMAL", n.entity_type, n.entity_id, "")
                for n in rows if (n.channels or {}).get("desktop", True)]


def latest_id(company_id: int, user_id: int) -> int:
    with new_session() as session:
        return int(session.scalar(select(func.max(Notification.notification_id)).where(
            Notification.company_id == company_id, Notification.user_id == user_id)) or 0)


def user_email(user_id: int) -> str | None:
    with new_session() as session:
        u = session.get(User, user_id)
        return u.email if u else None
