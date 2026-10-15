"""مشترک بودجه‌ریزی (R313): برچسب‌ها، دسترسی، ردپا، تنظیمات سیاست و کلیدهای روشن/خاموش.

مبلغ‌ها همیشه به ارز پایهٔ شرکت است؛ مبلغ سند با نرخ خود سند تبدیل می‌شود (همان قاعدهٔ گزارش‌های R245).
"""

from __future__ import annotations

import datetime
import decimal

from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.budgeting import BudgetSettings
from peecha.services import stock_controls

ZERO = decimal.Decimal(0)
_Q2 = decimal.Decimal("0.01")

PERIOD_TYPE_LABELS = {"YEAR": "سالانه", "QUARTER": "فصلی", "MONTH": "ماهانه"}
BASIS_LABELS = {"PURCHASE": "خرید و تعهد", "ACCOUNT": "حساب دفتر کل (فقط پایش)"}
KIND_LABELS = {"ORIGINAL": "نسخهٔ اولیه", "AMENDMENT": "اصلاحیه", "SUPPLEMENT": "بودجهٔ تکمیلی"}
VERSION_STATUS_LABELS = {"DRAFT": "پیش‌نویس", "SUBMITTED": "ارسال‌شده، منتظر بررسی", "REVIEWED": "بررسی‌شده، منتظر تأیید",
                         "APPROVED": "تأییدشده، منتظر انتشار", "PUBLISHED": "مصوب و منتشرشده", "SUPERSEDED": "جایگزین‌شده",
                         "REJECTED": "ردشده", "CANCELLED": "لغوشده"}
OPEN_VERSION = ("DRAFT", "SUBMITTED", "REVIEWED", "APPROVED", "REJECTED")
EDITABLE_VERSION = ("DRAFT", "SUBMITTED", "REVIEWED")
ACTION_LABELS = {"CREATE": "ایجاد", "SUBMIT": "ارسال برای بررسی", "REVIEW": "بررسی و تأیید مسئول بودجه",
                 "APPROVE": "تأیید مدیر مجاز", "PUBLISH": "انتشار نسخهٔ مصوب", "REJECT": "رد", "REOPEN": "بازگشت به پیش‌نویس",
                 "CANCEL": "لغو", "ADJUST": "اصلاح مبلغ مصوب"}
POLICY_LABELS = {"WARN": "فقط هشدار", "APPROVAL": "نیاز به تأیید سطح بالاتر", "BLOCK": "جلوگیری تا اصلاح یا مجوز استثنا"}
UNBUDGETED_LABELS = {"ALLOW": "مجاز", "WARN": "هشدار", "BLOCK": "جلوگیری تا مجوز استثنا"}
CONTROL_LEVEL_LABELS = {"ANNUAL": "کل دورهٔ بودجه", "CUMULATIVE": "تجمعی تا پایان همان دوره"}
CONSUMPTION_LABELS = {"PRE": "پیش‌تعهد (درخواست خرید)", "COMMIT": "تعهد", "ACTUAL": "هزینهٔ واقعی"}
SOURCE_LABELS = {"PURCHASE_REQUEST": "درخواست خرید", "PURCHASE_ORDER": "سفارش خرید", "PURCHASE_INVOICE": "فاکتور خرید",
                 "PURCHASE_RETURN": "برگشت از خرید", "JOURNAL_ENTRY": "سند حسابداری"}
EVENT_LABELS = {"CONFIRM": "تایید سند", "APPROVE": "تصویب سند", "POST": "ثبت نهایی", "CANCEL": "لغو", "REVERT": "بازگشت به پیش‌نویس",
                "DELETE": "حذف سند", "DIMENSION": "تغییر مرکز هزینه/پروژه", "CORRECTION": "اصلاح فاکتور", "CLOSE": "بستن تعهد",
                "REOPEN": "بازگشایی تعهد", "VERSION": "انتشار نسخهٔ بودجه", "RESYNC": "تطبیق دوباره با اسناد",
                "INVOICE": "فاکتور سفارش", "ORDER": "سفارش از درخواست"}
EXCEPTION_LEVEL_LABELS = {"APPROVAL": "تجاوز از بودجه (تأیید سطح بالاتر)", "BLOCK": "تجاوز از بودجهٔ مسدود",
                          "CLOSED": "مصرف در دورهٔ بسته", "UNBUDGETED": "خرید خارج از بودجه"}
EXCEPTION_STATUS_LABELS = {"PENDING": "منتظر تصمیم", "APPROVED": "تأییدشده", "REJECTED": "ردشده", "USED": "مصرف‌شده",
                           "CANCELLED": "لغوشده"}
OUTCOME_LABELS = {"OK": "در محدوده", "NEAR": "نزدیک به سقف", "WARN": "عبور با هشدار", "NEEDS_APPROVAL": "منتظر مجوز",
                  "BLOCKED": "متوقف شد", "EXCEPTION_USED": "با مجوز استثنا", "UNBUDGETED": "خارج از بودجه", "ERROR": "خطای کنترل"}

# فرم‌های دسترسی (nav_catalog._EMBEDDED_HUB_SUB_FORMS)؛ مدیر کل سیستم همیشه مجاز است
FORM_PREPARE, FORM_REVIEW, FORM_APPROVE, FORM_PUBLISH = "bud_prepare", "bud_review", "bud_approve", "bud_publish"
FORM_PERIOD, FORM_SETTINGS, FORM_EXCEPTION, FORM_OVERRIDE = "bud_period", "bud_settings", "bud_exception", "bud_override"
FORM_COMMITMENT = "bud_commitment"
FORM_LABELS = {FORM_PREPARE: "تهیه و ارسال بودجه", FORM_REVIEW: "بررسی بودجه (مسئول بودجه)", FORM_APPROVE: "تأیید بودجه (مدیر مجاز)",
               FORM_PUBLISH: "انتشار نسخهٔ مصوب بودجه", FORM_PERIOD: "بستن و بازگشایی دورهٔ بودجه",
               FORM_SETTINGS: "سیاست کنترل بودجه", FORM_EXCEPTION: "تأیید مجوز تجاوز از بودجه",
               FORM_OVERRIDE: "مجوز استثنای ویژه (بودجهٔ مسدود، دورهٔ بسته، خارج از بودجه)",
               FORM_COMMITMENT: "بستن و بازگشایی تعهد سفارش"}
ENTITY_BUDGET, ENTITY_VERSION, ENTITY_EXCEPTION, ENTITY_SETTINGS = "BUDGET", "BUDGET_VERSION", "BUDGET_EXCEPTION", "BUDGET_SETTINGS"


def money(value) -> decimal.Decimal:
    return decimal.Decimal(value or 0).quantize(_Q2, rounding=decimal.ROUND_HALF_UP)


def dec(value) -> decimal.Decimal:
    if value is None or value == "":
        return ZERO
    return value if isinstance(value, decimal.Decimal) else decimal.Decimal(str(value))


def now() -> datetime.datetime:
    return datetime.datetime.now().astimezone()


def is_on(company_id: int, code: str, session=None) -> bool:
    return stock_controls.is_on(company_id, code, session)


def require(company_id: int, user_id: int | None, form_code: str, action: str = "EDIT") -> None:
    """دسترسی بودجه همیشه اعمال می‌شود (ماژول تازه است و رفتار قبلی ندارد)."""
    from peecha.services import roles as roles_service

    if user_id is None or not roles_service.user_has_permission(user_id, company_id, form_code, action):
        raise ValueError(f"دسترسی «{FORM_LABELS[form_code]}» را ندارید.")


def can(company_id: int, user_id: int | None, form_code: str, action: str = "EDIT") -> bool:
    try:
        require(company_id, user_id, form_code, action)
    except ValueError:
        return False
    return True


def audit(session, company_id: int, user_id: int | None, entity_type: str, entity_id: int, operation: str,
          changes: dict | None = None) -> None:
    from peecha.services import audit as audit_service

    action = operation if operation in ("CREATE", "DELETE", "APPROVE", "REJECT", "CANCEL") else "UPDATE"
    clean = {k: v if isinstance(v, (list, dict, int, bool)) or v is None else str(v) for k, v in (changes or {}).items()}
    audit_service.log_activity(session, company_id=company_id, user_id=user_id, entity_type=entity_type, entity_id=entity_id,
                               action=action, changes={"operation": operation, **clean})


def user_names(session, user_ids) -> dict[int, str]:
    from peecha.db.models.security import User

    ids = {u for u in user_ids if u}
    if not ids:
        return {}
    return {u.user_id: (u.full_name or u.username) for u in session.scalars(select(User).where(User.user_id.in_(ids)))}


# --- سیاست کنترل ---------------------------------------------------------------------------------------------
def settings(company_id: int, session=None) -> BudgetSettings:
    def read(s):
        row = s.get(BudgetSettings, company_id)
        return row or BudgetSettings(company_id=company_id, policy_code="WARN", warn_percent=decimal.Decimal(90),
                                     control_level="ANNUAL", unbudgeted_policy="ALLOW")
    if session is not None:
        return read(session)
    with new_session() as s:
        row = read(s)
        s.expunge_all()
        return row


def save_settings(company_id: int, user_id: int, policy_code: str, warn_percent, control_level: str,
                  unbudgeted_policy: str) -> None:
    if policy_code not in POLICY_LABELS or control_level not in CONTROL_LEVEL_LABELS or unbudgeted_policy not in UNBUDGETED_LABELS:
        raise ValueError("سیاست کنترل نامعتبر است.")
    warn = dec(warn_percent)
    if not (0 < warn <= 100):
        raise ValueError("درصد هشدار باید بین ۰ و ۱۰۰ باشد.")
    require(company_id, user_id, FORM_SETTINGS)
    with new_session() as session:
        row = session.get(BudgetSettings, company_id)
        before = None if row is None else {"policy": row.policy_code, "warn": str(row.warn_percent), "level": row.control_level,
                                            "unbudgeted": row.unbudgeted_policy}
        if row is None:
            row = BudgetSettings(company_id=company_id)
            session.add(row)
        row.policy_code, row.warn_percent, row.control_level, row.unbudgeted_policy = policy_code, warn, control_level, unbudgeted_policy
        row.updated_by_user_id, row.updated_at = user_id, now()
        session.flush()
        audit(session, company_id, user_id, ENTITY_SETTINGS, company_id, "POLICY_CHANGE",
              {"before": before, "after": {"policy": policy_code, "warn": str(warn), "level": control_level,
                                           "unbudgeted": unbudgeted_policy}})
        session.commit()


def set_toggle(company_id: int, user_id: int, code: str, on: bool) -> None:
    """کلیدهای روشن/خاموش بودجه با دسترسی «سیاست کنترل» و ثبت رویداد تغییر سیاست."""
    from peecha.services import inventory_engine as engine

    if code not in stock_controls.BUD_ALL:
        raise ValueError("کلید نامعتبر است.")
    require(company_id, user_id, FORM_SETTINGS)
    engine.set_feature_enabled(company_id, code, on)
    with new_session() as session:
        audit(session, company_id, user_id, ENTITY_SETTINGS, company_id, "TOGGLE", {"code": code, "on": on})
        session.commit()
