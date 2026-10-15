"""مشترک افتتاحیه (R314): برچسب‌ها، دسترسی، ردپا، تنظیمات، حساب واسط و تبدیل ورودی کاربر.

حساب واسط افتتاحیه در نگاشت حساب‌های انبار (کلید OPENING_CLEARING) نگه داشته می‌شود تا سند موجودی افتتاحیه
با role_overrides همان موتور انبار طرف بستانکار را به آن ببرد.
"""

from __future__ import annotations

import datetime
import decimal
import re

from sqlalchemy import select

from peecha import numerals
from peecha.db.base import new_session
from peecha.db.models.opening import OpeningEvent, OpeningSettings

ZERO = decimal.Decimal(0)
_Q2 = decimal.Decimal("0.01")
CLEARING_KEY = "OPENING_CLEARING"
OPN_SELF_APPROVAL = "OPN_SELF_APPROVAL"

# ترتیب ثبت قطعی: زیرسیستم‌ها پیش از سند دفتر کل (سند دفتر کل حساب‌های کنترل را به حساب واسط می‌برد)
MODULE_LABELS = {
    "GL": "تراز افتتاحیهٔ دفتر کل", "INVENTORY": "موجودی کالا", "RECEIVABLES": "اسناد باز دریافتنی",
    "PAYABLES": "اسناد باز پرداختنی", "CHEQUES": "چک‌های باز", "FIXED_ASSETS": "دارایی‌های ثابت", "WIP": "کالای در جریان ساخت",
}
POST_ORDER = ("INVENTORY", "RECEIVABLES", "PAYABLES", "CHEQUES", "FIXED_ASSETS", "WIP", "GL")
RUN_STATUS_LABELS = {"DRAFT": "پیش‌نویس", "IN_PROGRESS": "در حال ورود اطلاعات", "POSTING": "در حال ثبت قطعی",
                     "POSTED": "ثبت قطعی شد، منتظر تطبیق و قفل", "LOCKED": "قفل‌شده", "CANCELLED": "لغوشده"}
MODULE_STATUS_LABELS = {"NOT_STARTED": "شروع‌نشده", "ENTERING": "در حال ورود", "HAS_ERRORS": "دارای خطا",
                        "READY": "آمادهٔ بررسی", "APPROVED": "تأییدشده", "POSTING": "در حال ثبت", "POSTED": "ثبت قطعی",
                        "LOCKED": "قفل‌شده"}
MODULE_PROGRESS = {"NOT_STARTED": 0, "ENTERING": 25, "HAS_ERRORS": 25, "READY": 60, "APPROVED": 80, "POSTING": 90, "POSTED": 100,
                   "LOCKED": 100}
ROW_STATUS_LABELS = {"VALID": "معتبر", "INVALID": "دارای خطا", "POSTED": "ثبت‌شده", "FAILED": "ثبت ناموفق", "REVERSED": "برگشت‌خورده"}
KIND_LABELS = {"ORIGINAL": "افتتاحیهٔ اصلی", "CORRECTION": "افتتاحیهٔ اصلاحی"}
EVENT_LABELS = {"CREATE": "ایجاد فرایند", "UPDATE": "ویرایش فرایند", "MODULES": "تغییر ماژول‌ها", "PEOPLE": "تعیین مسئول",
                "IMPORT": "بارگذاری فایل", "FORM": "ورود دستی", "DELETE_ROW": "حذف ردیف", "REVALIDATE": "اعتبارسنجی دوباره",
                "SUBMIT": "ارسال برای بررسی", "APPROVE": "تأیید", "REJECT": "رد", "RESET": "بازگشت به ورود اطلاعات",
                "POST": "ثبت قطعی", "POST_FAIL": "خطای ثبت", "DIFFERENCE": "ثبت اختلاف با مجوز", "LOCK": "قفل نهایی",
                "CANCEL": "لغو فرایند", "CORRECTION": "افتتاحیهٔ اصلاحی", "REVERSE": "برگشت ثبت", "SETTINGS": "تغییر تنظیمات"}
POLICY_LABELS = {"BLOCK": "قفل نهایی فقط بدون اختلاف", "APPROVAL": "ادامه با اختلاف فقط با مجوز ویژه و دلیل"}

# فرم‌های دسترسی؛ مدیر کل سیستم همیشه مجاز است
FORM_SETUP, FORM_ENTER, FORM_APPROVE, FORM_POST = "opn_setup", "opn_enter", "opn_approve", "opn_post"
FORM_CORRECT, FORM_SETTINGS, FORM_DIFFERENCE = "opn_correct", "opn_settings", "opn_difference"
FORM_LABELS = {FORM_SETUP: "تعریف فرایند افتتاحیه و مسئولان", FORM_ENTER: "ورود و بارگذاری اطلاعات افتتاحیه",
               FORM_APPROVE: "بررسی و تأیید اطلاعات افتتاحیه", FORM_POST: "ثبت قطعی و قفل افتتاحیه",
               FORM_CORRECT: "افتتاحیهٔ اصلاحی (برگشت و ثبت دوباره)", FORM_SETTINGS: "تنظیمات افتتاحیه و حساب واسط",
               FORM_DIFFERENCE: "مجوز قفل افتتاحیه با اختلاف"}
ENTITY_RUN, ENTITY_SETTINGS = "OPENING_RUN", "OPENING_SETTINGS"


def money(value) -> decimal.Decimal:
    return decimal.Decimal(value or 0).quantize(_Q2, rounding=decimal.ROUND_HALF_UP)


def dec(value) -> decimal.Decimal:
    if value is None or value == "":
        return ZERO
    return value if isinstance(value, decimal.Decimal) else decimal.Decimal(str(value))


def now() -> datetime.datetime:
    return datetime.datetime.now().astimezone()


def is_on(company_id: int, code: str, session=None) -> bool:
    from peecha.db.models.inventory import CompanyFeature

    def read(s):
        row = s.get(CompanyFeature, (company_id, code))
        return bool(row is not None and row.is_enabled)
    if session is not None:
        return read(session)
    with new_session() as s:
        return read(s)


def require(company_id: int, user_id: int | None, form_code: str, action: str = "EDIT") -> None:
    from peecha.services import roles as roles_service

    if user_id is None or not roles_service.user_has_permission(user_id, company_id, form_code, action):
        raise ValueError(f"دسترسی «{FORM_LABELS[form_code]}» را ندارید.")


def can(company_id: int, user_id: int | None, form_code: str, action: str = "EDIT") -> bool:
    try:
        require(company_id, user_id, form_code, action)
    except ValueError:
        return False
    return True


def is_super_admin(user_id: int | None) -> bool:
    from peecha.db.models.security import User

    if user_id is None:
        return False
    with new_session() as session:
        u = session.get(User, user_id)
        return bool(u and u.is_super_admin)


def audit(session, company_id: int, user_id: int | None, entity_id: int, operation: str, changes: dict | None = None,
          entity_type: str = ENTITY_RUN) -> None:
    from peecha.services import audit as audit_service

    action = operation if operation in ("CREATE", "DELETE", "APPROVE", "REJECT", "CANCEL") else "UPDATE"
    clean = {k: v if isinstance(v, (list, dict, int, bool)) or v is None else str(v) for k, v in (changes or {}).items()}
    audit_service.log_activity(session, company_id=company_id, user_id=user_id, entity_type=entity_type, entity_id=entity_id,
                               action=action, changes={"operation": operation, **clean})


def event(session, run_id: int, code: str, user_id: int | None, module_code: str | None = None, comment: str | None = None,
          details: dict | None = None) -> None:
    session.add(OpeningEvent(run_id=run_id, module_code=module_code, event_code=code, user_id=user_id, comment=comment or None,
                             details=jsonable(details) if details else None))


def jsonable(value):
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    if isinstance(value, decimal.Decimal):
        return str(value)
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    return value


def user_names(session, user_ids) -> dict[int, str]:
    from peecha.db.models.security import User

    ids = {u for u in user_ids if u}
    if not ids:
        return {}
    return {u.user_id: (u.full_name or u.username) for u in session.scalars(select(User).where(User.user_id.in_(ids)))}


# --- تنظیمات و حساب واسط ------------------------------------------------------------------------------------
def settings(company_id: int, session=None) -> OpeningSettings:
    def read(s):
        return s.get(OpeningSettings, company_id) or OpeningSettings(company_id=company_id, difference_policy="BLOCK")
    if session is not None:
        return read(session)
    with new_session() as s:
        row = read(s)
        s.expunge_all()
        return row


def clearing_account_id(company_id: int) -> int | None:
    from peecha.services import inventory_engine as engine

    return engine.get_account_mapping(company_id, CLEARING_KEY)


def save_settings(company_id: int, user_id: int, clearing_account: int | None, difference_policy: str,
                  difference_account: int | None) -> None:
    from peecha.db.models.accounting import ChartOfAccount
    from peecha.services import inventory_engine as engine

    if difference_policy not in POLICY_LABELS:
        raise ValueError("سیاست اختلاف نامعتبر است.")
    require(company_id, user_id, FORM_SETTINGS)
    with new_session() as session:
        for account_id, label in ((clearing_account, "حساب واسط افتتاحیه"), (difference_account, "حساب اختلاف افتتاحیه")):
            if account_id is None:
                continue
            acc = session.get(ChartOfAccount, account_id)
            if acc is None or acc.company_id != company_id or not acc.is_postable or not acc.is_active:
                raise ValueError(f"«{label}» باید حساب معین فعال همین شرکت باشد.")
        if clearing_account is not None and clearing_account == difference_account:
            raise ValueError("حساب اختلاف نباید همان حساب واسط باشد.")
        if difference_policy == "APPROVAL" and difference_account is None:
            raise ValueError("برای ادامه با اختلاف، «حساب اختلاف افتتاحیه» را مشخص کنید.")
        row = session.get(OpeningSettings, company_id)
        before = None if row is None else {"policy": row.difference_policy, "difference_account": row.difference_account_id}
        if row is None:
            row = OpeningSettings(company_id=company_id)
            session.add(row)
        row.difference_policy, row.difference_account_id = difference_policy, difference_account
        row.updated_by_user_id, row.updated_at = user_id, now()
        session.flush()
        audit(session, company_id, user_id, company_id, "SETTINGS",
              {"before": before, "after": {"policy": difference_policy, "difference_account": difference_account,
                                           "clearing": clearing_account}}, entity_type=ENTITY_SETTINGS)
        session.commit()
    if clearing_account is not None:
        engine.set_account_mapping(company_id, CLEARING_KEY, clearing_account)


def set_toggle(company_id: int, user_id: int, code: str, on: bool) -> None:
    from peecha.services import inventory_engine as engine

    if code != OPN_SELF_APPROVAL:
        raise ValueError("کلید نامعتبر است.")
    require(company_id, user_id, FORM_SETTINGS)
    engine.set_feature_enabled(company_id, code, on)
    with new_session() as session:
        audit(session, company_id, user_id, company_id, "TOGGLE", {"code": code, "on": on}, entity_type=ENTITY_SETTINGS)
        session.commit()


# --- تبدیل ورودی (فایل یا فرم) ------------------------------------------------------------------------------
_SEPARATORS = re.compile(r"[,٬،\s]")


def text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return numerals.to_ascii_digits(str(value)).strip()


def parse_decimal(value) -> decimal.Decimal | None:
    """None یعنی خالی؛ ValueError یعنی عدد نامعتبر. جداکنندهٔ هزارگان و رقم فارسی پذیرفته می‌شود."""
    if isinstance(value, (int, decimal.Decimal)):
        return decimal.Decimal(value)
    if isinstance(value, float):
        return decimal.Decimal(str(value))
    raw = _SEPARATORS.sub("", text(value)).replace("٫", ".").replace("/", ".") if value is not None else ""
    if not raw:
        return None
    try:
        return decimal.Decimal(raw)
    except decimal.InvalidOperation as exc:
        raise ValueError("عدد نامعتبر است") from exc


def parse_date(value) -> datetime.date | None:
    """تاریخ شمسی (۱۴۰۳/۰۱/۱۵) یا میلادی (2024-04-03) یا مقدار تاریخ اکسل."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    raw = text(value).replace("-", "/").replace(".", "/")
    if not raw:
        return None
    parts = raw.split("/")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        raise ValueError("تاریخ نامعتبر است (مثال: ۱۴۰۳/۰۱/۱۵)")
    y, m, d = (int(p) for p in parts)
    try:
        if y < 1700:
            return numerals.parse_jalali_date(f"{y:04d}/{m:02d}/{d:02d}")
        return datetime.date(y, m, d)
    except Exception as exc:  # noqa: BLE001
        raise ValueError("تاریخ نامعتبر است (مثال: ۱۴۰۳/۰۱/۱۵)") from exc


def fmt_date(value: datetime.date | None) -> str:
    return numerals.format_jalali_date(value) if value else ""
