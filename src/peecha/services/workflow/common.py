"""ثابت‌ها و ابزار مشترک موتور گردش کار: برچسب‌ها، حسابرسی، خطای قابل‌فهم، تنظیمات شرکت."""

from __future__ import annotations

import datetime
import decimal
import string
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import DBAPIError, IntegrityError, OperationalError

from peecha import numerals
from peecha.db.base import new_session
from peecha.db.models.workflow import WfSettings
from peecha.services import audit as audit_service

DEFINITION_STATUS = {"DRAFT": "پیش‌نویس", "TESTING": "در حال آزمون", "PUBLISHED": "منتشرشده", "ACTIVE": "فعال",
                     "PAUSED": "متوقف", "ARCHIVED": "بایگانی‌شده"}
RUNNABLE_STATUSES = ("PUBLISHED", "ACTIVE")
VERSION_STATUS = {"DRAFT": "پیش‌نویس", "PUBLISHED": "منتشرشده", "SUPERSEDED": "نسخهٔ قبلی"}
INSTANCE_STATUS = {"RUNNING": "در حال اجرا", "WAITING": "در انتظار", "COMPLETED": "پایان‌یافته", "FAILED": "ناموفق",
                   "CANCELLED": "لغوشده", "SUSPENDED": "معلق"}
OPEN_INSTANCE_STATUSES = ("RUNNING", "WAITING", "SUSPENDED")
OUTCOMES = {"APPROVED": "تاییدشده", "REJECTED": "ردشده", "DONE": "انجام‌شده", "CANCELLED": "لغوشده"}
NODE_TYPES = {"START": "شروع", "CONDITION": "شرط", "APPROVAL": "تایید", "TASK": "کار", "ACTION": "اقدام خودکار",
              "NOTIFY": "اعلان", "WAIT": "انتظار", "PARALLEL": "انشعاب هم‌زمان", "JOIN": "پیوستن شاخه‌ها", "END": "پایان"}
PRIORITIES = {"LOW": "کم", "NORMAL": "عادی", "HIGH": "بالا", "CRITICAL": "فوری"}
EXCEPTION_STATUS = {"OPEN": "باز", "RETRYING": "در حال تلاش دوباره", "RESOLVED": "حل‌شده", "IGNORED": "نادیده گرفته شد",
                    "ESCALATED": "ارجاع به سطح بالاتر"}
STEP_STATUS = {"RUNNING": "در حال اجرا", "DONE": "انجام شد", "WAITING": "در انتظار", "FAILED": "ناموفق", "SKIPPED": "رد شد"}
TRIGGER_TYPES = {"EVENT": "با رویداد", "MANUAL": "دستی (ارسال کاربر)", "SCHEDULE": "زمان‌بندی‌شده", "SCAN": "بررسی دوره‌ای"}

# روزهای کاری به شمارهٔ روز هفتهٔ پایتون (دوشنبه=۰ ... شنبه=۵، یکشنبه=۶)؛ جمعه (۴) تعطیل، پنجشنبه نیمه‌وقت
DEFAULT_WORK_HOURS = {"5": ["08:00", "16:00"], "6": ["08:00", "16:00"], "0": ["08:00", "16:00"], "1": ["08:00", "16:00"],
                      "2": ["08:00", "16:00"], "3": ["08:00", "12:00"]}
DEFAULT_SETTINGS = {"allow_self_approval": False, "max_steps": 200, "max_event_depth": 5, "api_allowlist": [],
                    "notify_starter_on_end": True, "work_hours": DEFAULT_WORK_HOURS, "notification_defaults": {},
                    "mobile_step_up_amount": None}
_AUDIT_ACTIONS = {"CREATE", "UPDATE", "DELETE", "APPROVE", "REVERSE", "MERGE", "SUBMIT", "REJECT", "DELEGATE", "ESCALATE",
                  "EXECUTE", "PUBLISH", "CANCEL", "RETRY", "RESOLVE", "COMMENT", "START", "COMPLETE"}


class WorkflowError(ValueError):
    """خطای قابل‌نمایش به کاربر (فارسی)؛ جزئیات فنی جدا نگه داشته می‌شود."""

    def __init__(self, message: str, technical: str | None = None) -> None:
        super().__init__(message)
        self.technical = technical


def now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def friendly_error(exc: BaseException) -> tuple[str, str]:
    """(پیام فارسی قابل‌فهم، جزئیات فنی). خطای سرویس‌های پیچا (ValueError) خودش فارسی است."""
    technical = f"{type(exc).__name__}: {exc}"
    if isinstance(exc, WorkflowError):
        return str(exc), exc.technical or technical
    if isinstance(exc, ValueError):
        return str(exc) or "اطلاعات سند معتبر نیست.", technical
    if isinstance(exc, IntegrityError):
        return "ثبت انجام نشد زیرا با اطلاعات موجود (مثلاً کد تکراری یا ارجاع نامعتبر) سازگار نیست.", technical
    if isinstance(exc, (OperationalError, DBAPIError, ConnectionError, TimeoutError, OSError)):
        return "ارتباط با پایگاه‌داده یا سرویس برقرار نشد؛ دوباره تلاش می‌شود.", technical
    return "اجرای این مرحله با خطای پیش‌بینی‌نشده روبه‌رو شد؛ مدیر سیستم جزئیات فنی را می‌بیند.", technical


def is_transient(exc: BaseException) -> bool:
    """خطاهای موقتی (قطعی ارتباط/قفل) ارزش تلاش دوباره دارند؛ خطای اعتبارسنجی سرویس نه."""
    if isinstance(exc, ValueError):
        return False
    return isinstance(exc, (OperationalError, ConnectionError, TimeoutError, OSError)) or (
        isinstance(exc, DBAPIError) and getattr(exc, "connection_invalidated", False))


def audit(session, company_id: int, user_id: int | None, entity: str, entity_id: int, action: str,
          changes: dict[str, Any] | None = None) -> None:
    kind = action if action in _AUDIT_ACTIONS else "UPDATE"
    audit_service.log_activity(session, company_id=company_id, user_id=user_id, entity_type=f"Wf{entity}",
                               entity_id=int(entity_id), action=kind,
                               changes={"operation": action, **{k: plain(v) for k, v in (changes or {}).items()}})


def plain(value):
    """مقدار قابل‌ذخیره در JSON (تاریخ/عدد اعشاری به رشته)."""
    if isinstance(value, (list, tuple, set)):
        return [plain(v) for v in value]
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, decimal.Decimal):
        return str(value)
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    return value if value is None or isinstance(value, (str, int, float, bool)) else str(value)


def settings(company_id: int) -> dict:
    with new_session() as session:
        row = session.get(WfSettings, company_id)
        return {**DEFAULT_SETTINGS, **(row.options if row else {})}


def save_settings(company_id: int, user_id: int | None, **options) -> dict:
    unknown = set(options) - set(DEFAULT_SETTINGS)
    if unknown:
        raise WorkflowError("تنظیم نامعتبر: " + "، ".join(sorted(unknown)))
    with new_session() as session:
        row = session.get(WfSettings, company_id) or WfSettings(company_id=company_id, options={})
        row.options = {**(row.options or {}), **plain(options)}
        row.updated_at = now()
        session.add(row)
        audit(session, company_id, user_id, "Settings", company_id, "UPDATE", options)
        session.commit()
    return settings(company_id)


class _SafeDict(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def display(value) -> str:
    """نمایش فارسی مقدار در متن اعلان/عنوان."""
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "بله" if value else "خیر"
    if isinstance(value, (int, float, decimal.Decimal)):
        number = decimal.Decimal(str(value))
        # normalize() روی عدد صحیح نماد علمی می‌دهد (5E+8)
        number = number.quantize(1) if number == number.to_integral_value() else number.normalize()
        return numerals.format_amount(number)
    if isinstance(value, datetime.datetime):
        return numerals.format_jalali_datetime(value)
    if isinstance(value, datetime.date):
        return numerals.format_jalali_date(value)
    return str(value)


def render(text: str, context: dict, labels: dict[str, str] | None = None) -> str:
    """{کلید} یا {برچسب فارسی فیلد} با مقدار context جایگزین می‌شود؛ کلید ناشناخته دست‌نخورده می‌ماند."""
    values = {k: display(v) for k, v in (context or {}).items() if not isinstance(v, (dict, list))}
    for key, label in (labels or {}).items():
        if key in values:
            values.setdefault(label, values[key])
    return string.Formatter().vformat(text or "", (), _SafeDict(values))


def user_names(session, user_ids) -> dict[int, str]:
    from peecha.db.models.security import User

    ids = {u for u in user_ids if u}
    if not ids:
        return {}
    return {uid: (full or name) for uid, full, name in session.execute(
        select(User.user_id, User.full_name, User.username).where(User.user_id.in_(ids)))}
