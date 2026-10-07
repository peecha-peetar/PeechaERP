"""ثابت‌ها و ابزار مشترک CRM: برچسب‌ها، Audit، اعلان، شماره‌گذاری."""

from __future__ import annotations

import datetime
from typing import Any

from sqlalchemy import func, select

from peecha.db.models.security import User
from peecha.services import audit as audit_service
from peecha.services import notifications as notifications_service

LEAD_STATUS = {"NEW": "جدید", "CONTACTED": "تماس گرفته‌شده", "QUALIFIED": "واجد شرایط", "UNQUALIFIED": "فاقد شرایط",
               "CONVERTED": "تبدیل‌شده", "LOST": "از دست رفته"}
LEAD_OPEN_STATUSES = ("NEW", "CONTACTED", "QUALIFIED")
SCORE_BANDS = {"COLD": "سرد", "WARM": "گرم", "HOT": "داغ", "VERY_HOT": "بسیار داغ"}
OPP_STATUS = {"OPEN": "باز", "WON": "برنده", "LOST": "بازنده"}
ACTIVITY_TYPES = {"CALL": "تماس", "MEETING": "جلسه", "VISIT": "بازدید", "FOLLOW_UP": "پیگیری", "EMAIL": "ایمیل",
                  "MESSAGE": "پیام", "TASK": "وظیفه", "REMINDER": "یادآور", "NOTE": "یادداشت", "COMPLAINT": "شکایت",
                  "OPPORTUNITY": "فرصت فروش (قدیمی)"}
ACTIVITY_STATUS = {"OPEN": "باز", "IN_PROGRESS": "در حال انجام", "DONE": "انجام‌شده", "RESOLVED": "حل‌شده",
                   "WON": "برنده", "LOST": "بازنده", "CANCELLED": "لغوشده"}
ACTIVITY_OPEN_STATUSES = ("OPEN", "IN_PROGRESS")
PRIORITIES = {"LOW": "کم", "NORMAL": "عادی", "HIGH": "بالا", "CRITICAL": "بحرانی"}

# قیف پیش‌فرض (قابل تغییر از تنظیمات CRM): (کد، نام، احتمال، نوع، SLA ساعت، فیلدهای الزامی، اقدام بعدی)
DEFAULT_STAGES = (
    ("NEW", "جدید", 10, "OPEN", 24, [], "تماس اولیه با مشتری"),
    ("CONTACTED", "تماس گرفته‌شده", 20, "OPEN", 72, [], "تعیین نیاز مشتری"),
    ("QUALIFIED", "واجد شرایط", 35, "OPEN", 72, ["amount"], "تحلیل نیاز"),
    ("NEEDS_ANALYSIS", "تحلیل نیاز", 50, "OPEN", 120, ["amount"], "آماده‌سازی پیشنهاد"),
    ("PROPOSAL", "ارسال پیشنهاد", 65, "OPEN", 120, ["amount", "expected_close_date"], "پیگیری پیشنهاد"),
    ("NEGOTIATION", "مذاکره", 80, "OPEN", 72, ["amount", "expected_close_date", "customer"], "نهایی‌سازی قرارداد"),
    ("WON", "برنده", 100, "WON", None, ["customer"], None),
    ("LOST", "بازنده", 0, "LOST", None, [], None),
)

# فعالیت خودکار هنگام ورود به مرحله: {"type", "subject", "due_in_days"}
DEFAULT_STAGE_ACTIVITIES = {
    "NEW": {"type": "CALL", "subject": "تماس اولیه", "due_in_days": 1},
    "PROPOSAL": {"type": "FOLLOW_UP", "subject": "پیگیری پیشنهاد ارسال‌شده", "due_in_days": 3},
    "NEGOTIATION": {"type": "TASK", "subject": "نهایی‌سازی مذاکره و قرارداد", "due_in_days": 2},
}


def audit(session, company_id: int, user_id: int | None, entity: str, entity_id: int, action: str,
          changes: dict[str, Any] | None = None) -> None:
    """اکشن‌های مجاز Audit محدودند؛ عملیات خاص CRM (تغییر مرحله، واگذاری، تبدیل...) به‌صورت UPDATE با نام عملیات ثبت می‌شوند."""
    kind = action if action in ("CREATE", "UPDATE", "DELETE", "APPROVE", "MERGE") else "UPDATE"
    audit_service.log_activity(session, company_id=company_id, user_id=user_id, entity_type=f"Crm{entity}",
                               entity_id=entity_id, action=kind,
                               changes={"operation": action, **{k: _plain(v) for k, v in (changes or {}).items()}})


def _plain(value):
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    return value if value is None or isinstance(value, (str, int, float, bool)) else str(value)


def notify(company_id: int, user_id: int | None, type_code: str, title: str, body: str = "",
           entity_type: str | None = None, entity_id: int | None = None) -> None:
    """اعلان از همان سرویس اعلان مرکزی پیچا؛ نبود گیرنده خطا نیست."""
    if user_id:
        notifications_service.create_notification(company_id, user_id, type_code, title, body, entity_type, entity_id)


def next_number(session, model, company_id: int, column) -> int:
    session.execute(select(model.company_id).where(model.company_id == company_id).with_for_update()).all()
    return (session.scalar(select(func.max(column)).where(model.company_id == company_id)) or 0) + 1


def user_names(session, user_ids) -> dict[int, str]:
    ids = {u for u in user_ids if u}
    if not ids:
        return {}
    return {uid: (full or name) for uid, full, name in session.execute(
        select(User.user_id, User.full_name, User.username).where(User.user_id.in_(ids)))}


def now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def list_company_users(company_id: int) -> list[tuple[int, str]]:
    """کاربران فعال شرکت (برای مسئول/واگذاری) — از همان sec.user_companies."""
    from peecha.db.base import new_session
    from peecha.db.models.security import UserCompany

    with new_session() as session:
        return [(uid, full or name) for uid, full, name in session.execute(
            select(User.user_id, User.full_name, User.username).join(UserCompany, UserCompany.user_id == User.user_id)
            .where(UserCompany.company_id == company_id, User.is_active.is_(True)).order_by(User.full_name))]
