"""مشترک نگهداری و تعمیرات (R312): برچسب‌ها، کلیدها، دسترسی، شماره‌گذاری و ردپا.

تجهیز همان دارایی ثابت است؛ وضعیت ماشین فقط از fixed_assets.set_status_in_session، قطعه فقط از موتور انبار و
ثبت مالی فقط از سرویس‌های موجود (دارایی/انبار/خرید). هیچ نوشتن مستقیمی در جدول‌های ماژول‌های دیگر نیست.
"""

from __future__ import annotations

import datetime
import decimal

from sqlalchemy import func, select, text

from peecha.db.models.fixed_assets import Asset
from peecha.services import stock_controls

ZERO = decimal.Decimal(0)
_Q2 = decimal.Decimal("0.01")
_Q4 = decimal.Decimal("0.0001")

WORK_TYPE_LABELS = {"EMERGENCY": "اضطراری", "CORRECTIVE": "اصلاحی", "PREVENTIVE": "پیشگیرانه", "PREDICTIVE": "پیش‌بینانه",
                    "INSPECTION": "بازرسی", "OVERHAUL": "تعمیرات اساسی"}
PRIORITY_LABELS = {"LOW": "کم", "NORMAL": "عادی", "HIGH": "زیاد", "URGENT": "فوری"}
SEVERITY_LABELS = {"LOW": "کم", "MEDIUM": "متوسط", "HIGH": "زیاد", "CRITICAL": "بحرانی"}
CRITICALITY_LABELS = {"HIGH": "حیاتی", "MEDIUM": "مهم", "LOW": "عادی"}
REQUEST_STATUS_LABELS = {"NEW": "جدید", "UNDER_REVIEW": "در حال بررسی", "APPROVED": "تأییدشده", "REJECTED": "ردشده",
                         "CONVERTED": "تبدیل به دستور کار", "CANCELLED": "لغوشده"}
WO_STATUS_LABELS = {"OPEN": "باز", "PLANNED": "برنامه‌ریزی‌شده", "ASSIGNED": "واگذارشده", "IN_PROGRESS": "در حال انجام",
                    "ON_HOLD": "متوقف موقت", "COMPLETED": "انجام‌شده، منتظر آزمون", "VERIFIED": "آزمون‌شده",
                    "CLOSED": "بسته‌شده", "CANCELLED": "لغوشده"}
SOURCE_LABELS = {"DESKTOP": "برنامهٔ رومیزی", "MOBILE": "موبایل", "QR": "اسکن برچسب", "PM": "برنامهٔ پیشگیرانه"}
TRIGGER_LABELS = {"CALENDAR": "تقویمی", "METER": "بر اساس کارکرد", "BOTH": "هرکدام زودتر"}
RESULT_TYPE_LABELS = {"CHECK": "انجام شد/نشد", "NUMERIC": "مقدار اندازه‌گیری", "TEXT": "شرح"}
DOWNTIME_TYPE_LABELS = {"BREAKDOWN": "خرابی", "PLANNED": "توقف برنامه‌ریزی‌شده", "OTHER": "سایر"}
APPROVAL_STATUS_LABELS = {"PROPOSED": "پیشنهادی", "APPROVED": "تأییدشده", "CANCELLED": "لغوشده"}
POSTPONE_STATUS_LABELS = {"PENDING": "منتظر تأیید", "APPROVED": "تأییدشده", "REJECTED": "ردشده"}
COST_TYPE_LABELS = {"SERVICE": "خدمات پیمانکار", "OTHER": "سایر هزینه‌ها"}
COST_STATUS_LABELS = {"DRAFT": "ثبت‌نشده در حسابداری", "PENDING_APPROVAL": "منتظر تأیید مالی", "POSTED": "ثبت‌شده",
                      "LINKED": "متصل به فاکتور خرید", "CANCELLED": "لغوشده"}
ACCOUNTING_LABELS = {"PENDING": "تعیین‌نشده", "INVOICE": "فاکتور خرید", "EXPENSE": "هزینهٔ تعمیر", "CAPITALIZE": "افزایش سرمایه‌ای",
                     "NONE": "بدون ثبت مالی"}
FAILURE_KIND_LABELS = {"PROBLEM": "نشانهٔ خرابی", "CAUSE": "علت", "REMEDY": "اقدام انجام‌شده"}
VERIFY_LABELS = {"PASS": "قبول", "FAIL": "مردود"}

OPEN_WO = ("OPEN", "PLANNED", "ASSIGNED", "IN_PROGRESS", "ON_HOLD", "COMPLETED", "VERIFIED")
PM_TYPES = ("PREVENTIVE", "INSPECTION", "OVERHAUL", "PREDICTIVE")

# فرم‌های دسترسی (nav_catalog._EMBEDDED_HUB_SUB_FORMS)؛ با کلید MNT_ROLE_PERMISSIONS اعمال می‌شوند
FORM_REQUEST, FORM_PLAN, FORM_EXECUTE, FORM_VERIFY = "mnt_request", "mnt_plan", "mnt_execute", "mnt_verify"
FORM_PARTS, FORM_COST, FORM_APPROVE, FORM_MANAGE = "mnt_parts", "mnt_cost", "mnt_approve", "mnt_manage"
FORM_LABELS = {FORM_REQUEST: "ثبت درخواست تعمیر", FORM_PLAN: "بررسی درخواست و برنامه‌ریزی دستور کار",
               FORM_EXECUTE: "اجرای دستور کار", FORM_VERIFY: "آزمون، تأیید و بستن دستور کار",
               FORM_PARTS: "صدور و برگشت قطعه", FORM_COST: "ثبت مالی هزینه‌های تعمیر",
               FORM_APPROVE: "تأیید توقف برنامه‌ریزی‌شده، ظرفیت محدود و تعویق", FORM_MANAGE: "تجهیزات، برنامه‌های پیشگیرانه و تنظیمات"}
# فرم پیوست‌ها (همان doc.attachments)
ATTACH_FORM_REQUEST, ATTACH_FORM_WO = "mnt_requests", "mnt_work_orders"


def money(value) -> decimal.Decimal:
    return decimal.Decimal(value or 0).quantize(_Q2, rounding=decimal.ROUND_HALF_UP)


def dec(value) -> decimal.Decimal:
    if value is None or value == "":
        return ZERO
    return value if isinstance(value, decimal.Decimal) else decimal.Decimal(str(value))


def now() -> datetime.datetime:
    return datetime.datetime.now().astimezone()


def aware(value: datetime.datetime | None) -> datetime.datetime | None:
    """ستون‌های زمانی timestamptz هستند؛ زمان بدون منطقه = وقت محلی."""
    if value is None:
        return None
    return value if value.tzinfo is not None else value.astimezone()


def is_on(company_id: int, code: str, session=None) -> bool:
    return stock_controls.is_on(company_id, code, session)


def require(company_id: int, user_id: int | None, form_code: str, action: str = "EDIT", session=None) -> None:
    """با کلید «دسترسی‌های جداگانهٔ نگهداری» فقط نقش دارای همان گام (مدیر کل همیشه مجاز)."""
    if not is_on(company_id, stock_controls.MNT_ROLE_PERMISSIONS, session):
        return
    from peecha.services import roles as roles_service

    if user_id is None or not roles_service.user_has_permission(user_id, company_id, form_code, action):
        raise ValueError(f"دسترسی «{FORM_LABELS[form_code]}» را ندارید.")


def can(company_id: int, user_id: int | None, form_code: str, action: str = "EDIT") -> bool:
    try:
        require(company_id, user_id, form_code, action)
    except ValueError:
        return False
    return True


def next_no(session, model, column, company_id: int) -> int:
    """شمارهٔ بعدی با قفل مشورتی تراکنش (دو ثبت هم‌زمان شمارهٔ تکراری نمی‌گیرند)."""
    session.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"mnt:{model.__tablename__}:{company_id}"})
    return (session.scalar(select(func.max(column)).where(model.company_id == company_id)) or 0) + 1


def asset_of(session, company_id: int, asset_id: int, lock: bool = False) -> Asset:
    q = select(Asset).where(Asset.asset_id == asset_id)
    asset = session.scalar(q.with_for_update() if lock else q)
    if asset is None or asset.company_id != company_id:
        raise ValueError("تجهیز نامعتبر است.")
    return asset


def asset_label(asset: Asset) -> str:
    return f"{asset.asset_code} — {asset.name}"


def audit(session, company_id: int, user_id: int | None, entity_type: str, entity_id: int, operation: str,
          changes: dict | None = None) -> None:
    """ردپا با همان سرویس موجود؛ نام گام در changes.operation."""
    from peecha.services import audit as audit_service

    action = operation if operation in ("CREATE", "DELETE", "APPROVE", "REJECT", "CANCEL", "START", "COMPLETE") else "UPDATE"
    clean = {k: v if isinstance(v, (list, dict, int, bool)) or v is None else str(v) for k, v in (changes or {}).items()}
    audit_service.log_activity(session, company_id=company_id, user_id=user_id, entity_type=entity_type, entity_id=entity_id,
                               action=action, changes={"operation": operation, **clean})


def user_names(session, user_ids) -> dict[int, str]:
    from peecha.db.models.security import User

    ids = {u for u in user_ids if u}
    if not ids:
        return {}
    return {u.user_id: (u.full_name or u.username) for u in session.scalars(select(User).where(User.user_id.in_(ids)))}
