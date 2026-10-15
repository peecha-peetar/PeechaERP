"""مشترک کیفیت: برچسب‌ها، کلیدها، دسترسی و تنظیمات."""

from __future__ import annotations

from peecha.db.base import new_session
from peecha.db.models.quality import QmsSettings
from peecha.services import stock_controls

STAGE_LABELS = {"RECEIPT": "رسید خرید", "SALES_RETURN": "مرجوعی فروش", "IN_PROCESS": "حین تولید", "FINAL": "محصول نهایی"}
STATUS_LABELS = {"RECORDED": "منتظر تأیید", "APPROVED": "تأییدشده", "CANCELLED": "لغوشده"}
RESULT_LABELS = {"PENDING": "در انتظار تصمیم", "APPROVED": "پذیرفته", "PARTIAL": "پذیرش بخشی", "REJECTED": "مردود"}
DISPOSITION_LABELS = {"ACCEPT": "پذیرش", "REJECT": "رد", "PARTIAL": "پذیرش بخشی", "PENDING": "در انتظار تصمیم",
                      "REWORK": "دوباره‌کاری", "CONCESSION": "مصرف مشروط"}
DATA_TYPE_LABELS = {"NUMERIC": "عددی", "PASS_FAIL": "قبول/رد", "OPTION": "گزینه‌ای", "TEXT": "متنی"}
SAMPLING_LABELS = {"FULL": "بازرسی کامل", "FIXED": "تعداد ثابت نمونه", "PERCENT": "درصد از محموله"}
PLAN_STATUS_LABELS = {"DRAFT": "پیش‌نویس", "ACTIVE": "فعال", "SUPERSEDED": "نسخهٔ قبلی", "INACTIVE": "غیرفعال"}
SEVERITY_LABELS = {"MINOR": "جزئی", "MAJOR": "عمده", "CRITICAL": "بحرانی"}
NCR_STATUS_LABELS = {"OPEN": "باز", "INVESTIGATING": "در حال بررسی", "ACTION": "در حال اقدام", "CLOSED": "بسته‌شده",
                     "CANCELLED": "لغوشده"}
NCR_SOURCE_LABELS = {"RECEIPT": "رسید خرید", "SALES_RETURN": "مرجوعی مشتری", "IN_PROCESS": "حین تولید", "FINAL": "محصول نهایی",
                     "INTERNAL": "داخلی", "SUPPLIER": "تامین‌کننده", "CUSTOMER": "شکایت مشتری"}
NCR_DISPOSITION_LABELS = {"USE_AS_IS": "مصرف به همین شکل", "REWORK": "دوباره‌کاری", "SCRAP": "ضایعات",
                          "RETURN_TO_SUPPLIER": "برگشت به تامین‌کننده", "REPLACE": "جایگزینی", "NONE": "بدون اقدام روی کالا"}
CAUSE_LABELS = {"MATERIAL": "مواد", "METHOD": "روش", "MACHINE": "ماشین", "MAN": "نیروی انسانی", "MEASUREMENT": "اندازه‌گیری",
                "ENVIRONMENT": "محیط", "SUPPLIER": "تامین‌کننده", "OTHER": "سایر"}
ROOT_CAUSE_METHOD_LABELS = {"FIVE_WHY": "پنج چرا", "FISHBONE": "استخوان ماهی (۶ عامل)", "OTHER": "سایر"}
CAPA_TYPE_LABELS = {"CORRECTIVE": "اصلاحی", "PREVENTIVE": "پیشگیرانه"}
CAPA_STATUS_LABELS = {"OPEN": "باز", "DONE": "انجام‌شده", "VERIFIED": "اثربخش", "INEFFECTIVE": "بی‌اثر", "CANCELLED": "لغوشده"}

# فرم‌های دسترسی کیفیت (nav_catalog) و اقدام لازم برای هرکدام
FORM_INSPECT, FORM_APPROVE, FORM_RELEASE, FORM_MANAGE, FORM_NCR = "qc_inspect", "qc_approve", "qc_release", "qc_manage", "qc_ncr"
_FORM_LABELS = {FORM_INSPECT: "ثبت نتیجهٔ بازرسی", FORM_APPROVE: "تأیید نهایی کیفیت", FORM_RELEASE: "آزادسازی موجودی قرنطینه",
                FORM_MANAGE: "مدیریت طرح‌ها و تنظیمات کیفیت", FORM_NCR: "رسیدگی به عدم‌انطباق و اقدام‌ها"}


def is_on(company_id: int, code: str, session=None) -> bool:
    return stock_controls.is_on(company_id, code, session)


def require(company_id: int, user_id: int | None, form_code: str, action: str = "EDIT", session=None) -> None:
    """با کلید «اعمال دسترسی‌های جداگانهٔ کیفیت» فقط نقش دارای مجوز همان بخش (مدیر کل همیشه مجاز)."""
    if not is_on(company_id, stock_controls.QC_ROLE_PERMISSIONS, session):
        return
    from peecha.services import roles as roles_service

    if user_id is None or not roles_service.user_has_permission(user_id, company_id, form_code, action):
        raise ValueError(f"دسترسی «{_FORM_LABELS[form_code]}» را ندارید.")


def can(company_id: int, user_id: int | None, form_code: str, action: str = "EDIT") -> bool:
    try:
        require(company_id, user_id, form_code, action)
    except ValueError:
        return False
    return True


_DEFAULTS = {"score_window_days": 365, "score_min_samples": 3, "weight_reject": 40, "weight_return": 25, "weight_ncr": 20,
             "weight_delay": 15, "weight_trend": 0, "target_handling_days": 2, "auto_ncr_on_reject": True}


def settings(company_id: int, session=None) -> QmsSettings:
    """تنظیمات کیفیت شرکت (بدون ردیف = پیش‌فرض‌ها، بدون نوشتن)."""
    def _load(s):
        row = s.get(QmsSettings, company_id)
        if row is None:
            row = QmsSettings(company_id=company_id, **_DEFAULTS)
        return row

    if session is not None:
        return _load(session)
    with new_session() as s:
        row = _load(s)
        if row in s:
            s.expunge(row)
        return row


def save_settings(company_id: int, user_id: int, **values) -> None:
    import datetime
    import decimal

    from peecha.services import audit as audit_service

    with new_session() as session:
        require(company_id, user_id, FORM_MANAGE, session=session)
        row = session.get(QmsSettings, company_id)
        if row is None:
            row = QmsSettings(company_id=company_id, **_DEFAULTS)
            session.add(row)
        allowed = {"score_window_days", "score_min_samples", "weight_reject", "weight_return", "weight_ncr", "weight_delay",
                   "weight_trend", "target_handling_days", "auto_ncr_on_reject"}
        unknown = set(values) - allowed
        if unknown:
            raise ValueError(f"تنظیم ناشناخته: {', '.join(sorted(unknown))}")
        before = {k: str(getattr(row, k)) for k in values}
        for k, v in values.items():
            if k.startswith("weight_") or k == "target_handling_days":
                v = decimal.Decimal(v)
                if v < 0:
                    raise ValueError("وزن یا هدف منفی نمی‌تواند باشد.")
            setattr(row, k, v)
        weights = [decimal.Decimal(getattr(row, k) if getattr(row, k) is not None else 0)
                   for k in ("weight_reject", "weight_return", "weight_ncr", "weight_delay", "weight_trend")]
        if sum(weights) <= 0:
            raise ValueError("دست‌کم یک شاخص باید وزن داشته باشد.")
        if (row.score_window_days or 0) <= 0 or (row.score_min_samples or 0) < 1:
            raise ValueError("بازهٔ محاسبه و حداقل تعداد نمونه باید مثبت باشد.")
        row.updated_by_user_id, row.updated_at = user_id, datetime.datetime.now(datetime.timezone.utc)
        session.flush()
        audit_service.log_activity(session, company_id=company_id, user_id=user_id, entity_type="QmsSettings", entity_id=company_id,
                                   action="UPDATE", changes={k: [before[k], str(v)] for k, v in values.items()})
        session.commit()
