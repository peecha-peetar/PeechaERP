"""سرویسِ عنوانِ فیلدهای فرم‌ها به‌تفکیکِ زبان.

طبق درخواستِ صریح: فقط برای «عنوان فیلدها» (نه کلِ متنِ رابط کاربری)، با
یک ساختارِ قابل‌مدیریت که بتوان برایش زبانِ تازه هم بدون ترجمه اضافه کرد و
بعداً عنوان را برای همان زبان عوض کرد.

به‌جای یک ستونِ جداگانه در دیتابیس برای هر زبان (که با هر زبانِ تازه نیاز
به ALTER TABLE دارد و دقیقاً با «کاربر بتواند بدون ترجمه زبان اضافه کند»
در تضاد است)، از همان جدولِ عمومیِ core.translations استفاده می‌شود
(entity_type='FormField')، دقیقاً به همان الگویی که chart_of_accounts.py
برای نامِ حساب‌ها استفاده می‌کند؛ در نتیجه افزودنِ زبانِ جدید هیچ تغییرِ
اسکیمایی نمی‌خواهد. کاتالوگِ خودِ فیلدها هم در sec.form_fields (که قبلاً
برای دسترسیِ سطحِ فیلد در طراحیِ دیتابیس بود) نگه داشته می‌شود.

«حالتِ پیش‌فرض» یعنی: اگر برای زبانی هنوز عنوانی ثبت نشده، همان متنِ
پیش‌فرضِ فارسی (که از قبل در کدِ برنامه بود) نمایش داده می‌شود، تا وقتی
کاربر خودش آن را برای آن زبان عوض کند.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.core import Translation
from peecha.db.models.security import Form, FormField
from peecha.services.roles import ensure_catalog as ensure_forms_catalog

_ENTITY_TYPE = "FormField"
_PROPERTY_NAME = "Label"

# (کدِ فرم، [(کدِ فیلد، عنوانِ پیش‌فرضِ فارسی), ...]) — دقیقاً همان متن‌هایی
# که همین الان به‌صورت هاردکد در KVِ هر صفحه بود؛ همان‌ها هم seed می‌شوند و
# هم fallback نهایی‌اند وقتی برای یک زبان هنوز عنوانی ثبت نشده.
_FORM_FIELDS: dict[str, list[tuple[str, str]]] = {
    "chart_of_accounts": [
        ("segment_code", "کد حساب (فقط بخش این سطح)"),
        ("name", "نام حساب"),
    ],
    "journal_entry": [
        ("description", "شرح سند"),
        ("date", "تاریخ سند"),
        ("line_account", "حساب"),
        ("line_description", "شرح ردیف"),
        ("line_debit", "بدهکار"),
        ("line_credit", "بستانکار"),
    ],
    "languages": [
        ("code", "کد زبان"),
        ("native_name", "نام زبان"),
        ("sort_order", "ترتیبِ نمایش"),
    ],
    "companies": [
        ("code", "کد شرکت"),
        ("legal_name", "نام حقوقی"),
        ("display_name", "نام نمایشی"),
        ("economic_code", "کد اقتصادی"),
        ("registration_no", "شماره ثبت"),
        ("national_id", "شناسه ملی"),
        ("fy_start_day", "روزِ شروعِ سال مالی"),
        ("fy_start_month", "ماهِ شروعِ سال مالی"),
    ],
    "fiscal_years": [
        ("on_date", "تاریخ"),
    ],
    "users": [
        ("username", "نام‌کاربری"),
        ("full_name", "نام کامل"),
        ("email", "ایمیل"),
        ("password", "رمز عبور"),
    ],
    "roles": [
        ("code", "کدِ نقش"),
    ],
}


def ensure_catalog() -> None:
    ensure_forms_catalog()
    with new_session() as session:
        forms_by_code = {f.code: f.form_id for f in session.scalars(select(Form))}
        existing = {(ff.form_id, ff.code) for ff in session.scalars(select(FormField))}
        for form_code, fields in _FORM_FIELDS.items():
            form_id = forms_by_code.get(form_code)
            if form_id is None:
                continue
            for sort_order, (field_code, _default_label) in enumerate(fields):
                if (form_id, field_code) not in existing:
                    session.add(FormField(form_id=form_id, code=field_code, sort_order=sort_order))
        session.commit()


@dataclass
class FieldLabelRow:
    field_id: int
    code: str
    default_label: str
    label: str | None  # None یعنی برای این زبان override ندارد (همان پیش‌فرض نمایش داده می‌شود)


def list_fields(form_code: str, language_id: int | None) -> list[FieldLabelRow]:
    ensure_catalog()
    defaults = dict(_FORM_FIELDS.get(form_code, []))
    with new_session() as session:
        form = session.scalar(select(Form).where(Form.code == form_code))
        if form is None:
            return []
        fields = session.scalars(
            select(FormField).where(FormField.form_id == form.form_id).order_by(FormField.sort_order)
        ).all()
        overrides: dict[int, str] = {}
        if language_id is not None and fields:
            rows = session.execute(
                select(Translation.entity_id, Translation.value).where(
                    Translation.entity_type == _ENTITY_TYPE,
                    Translation.property_name == _PROPERTY_NAME,
                    Translation.language_id == language_id,
                    Translation.entity_id.in_([f.field_id for f in fields]),
                )
            ).all()
            overrides = dict(rows)
        return [
            FieldLabelRow(
                field_id=f.field_id,
                code=f.code,
                default_label=defaults.get(f.code, f.code),
                label=overrides.get(f.field_id),
            )
            for f in fields
        ]


def set_label(field_id: int, language_id: int, label: str | None) -> None:
    """label خالی/None یعنی بازگشت به عنوانِ پیش‌فرض (حذفِ override)."""
    with new_session() as session:
        existing = session.scalar(
            select(Translation).where(
                Translation.entity_type == _ENTITY_TYPE,
                Translation.entity_id == field_id,
                Translation.property_name == _PROPERTY_NAME,
                Translation.language_id == language_id,
            )
        )
        clean_label = (label or "").strip()
        if not clean_label:
            if existing is not None:
                session.delete(existing)
                session.commit()
            return
        if existing is None:
            session.add(
                Translation(
                    entity_type=_ENTITY_TYPE,
                    entity_id=field_id,
                    property_name=_PROPERTY_NAME,
                    language_id=language_id,
                    value=clean_label,
                )
            )
        else:
            existing.value = clean_label
        session.commit()


def get_labels_map(form_code: str, language_id: int | None) -> dict[str, str]:
    """برای استفاده‌ی زمانِ اجرا در خودِ صفحات: کدِ فیلد → عنوانِ مؤثر
    (override یا پیش‌فرض)."""
    rows = list_fields(form_code, language_id)
    return {row.code: (row.label or row.default_label) for row in rows}
