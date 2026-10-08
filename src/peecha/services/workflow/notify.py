"""ارسال اعلان گردش کار از همان سرویس اعلان مرکزی پیچا (sec.notifications).

کانال‌های بیشتر (پیامک، ایمیل، Push) و ترجیحات کاربر در R293 اضافه می‌شوند؛ این تابع نقطهٔ واحد ارسال است.
"""

from __future__ import annotations

from typing import Callable

from sqlalchemy import event as sa_event
from sqlalchemy.orm import Session

from peecha.services import notifications as notifications_service

TYPES = {
    "WF_APPROVAL_REQUIRED": "نیاز به تایید", "WF_TASK_ASSIGNED": "کار تازه", "WF_TASK_DUE": "نزدیک شدن موعد",
    "WF_SLA_WARNING": "هشدار مهلت", "WF_SLA_BREACHED": "گذشتن از مهلت", "WF_COMPLETED": "پایان فرایند",
    "WF_FAILED": "شکست فرایند", "WF_EXCEPTION": "مورد نیازمند بررسی", "WF_ESCALATION": "ارجاع به سطح بالاتر",
    "WF_MESSAGE": "پیام فرایند", "WF_DELEGATION": "تفویض اختیار",
}
_CHANNEL_SENDERS: list[Callable[..., None]] = []


def register_channel(sender: Callable[..., None]) -> None:
    """کانال اضافه (پیامک/ایمیل/Push) -- sender(company_id, user_id, type_code, title, body, entity_type, entity_id)."""
    _CHANNEL_SENDERS.append(sender)


def send(company_id: int, user_ids, type_code: str, title: str, body: str = "", entity_type: str | None = "WfInstance",
         entity_id: int | None = None) -> int:
    sent = 0
    for uid in sorted({u for u in user_ids if u}):
        notifications_service.create_notification(company_id, uid, type_code, title[:200], body or "", entity_type,
                                                  entity_id)
        for sender in _CHANNEL_SENDERS:
            try:
                sender(company_id, uid, type_code, title, body, entity_type, entity_id)
            except Exception:  # noqa: BLE001 -- خطای یک کانال بیرونی نباید اعلان درون‌برنامه را خراب کند
                pass
        sent += 1
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
