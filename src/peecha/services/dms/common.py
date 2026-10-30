"""R343: ثابت‌ها، برچسب‌ها، تنظیمات و قاعدهٔ دسترسی اسناد."""

from __future__ import annotations

import datetime

from sqlalchemy import select

from peecha.db.models.documents import DmsDocument, DmsEvent, DmsLink, DmsSettings
from peecha.services import roles as roles_service

FORM_DOCS = "dms_documents"
FORM_APPROVE = "dms_approve"
FORM_CONFIDENTIAL = "dms_confidential"
FORM_SETTINGS = "dms_settings"
FORM_CATEGORIES = "dms_categories"

DOCUMENT_TYPES = {
    "CONTRACT": "قرارداد", "INVOICE": "فاکتور", "RECEIPT": "رسید", "REMITTANCE": "حواله", "DELIVERY": "فرم تحویل",
    "PRODUCT_IMAGE": "تصویر کالا", "CUSTOMER_DOC": "مدارک مشتری", "FINANCIAL": "سند مالی", "PERSONNEL": "مدارک پرسنلی",
    "CERTIFICATE": "گواهی و مجوز", "IMAGE": "تصویر", "OTHER": "سایر",
}
CONFIDENTIALITY = {"PUBLIC": "عمومی", "INTERNAL": "داخلی", "CONFIDENTIAL": "محرمانه", "SECRET": "سری"}
STATUSES = {
    "DRAFT": "پیش‌نویس", "PENDING": "در انتظار بررسی", "IN_REVIEW": "در حال بررسی", "NEEDS_CHANGES": "نیازمند اصلاح",
    "REJECTED": "ردشده", "APPROVED": "تاییدشده", "OBSOLETE": "منسوخ‌شده", "ARCHIVED": "بایگانی‌شده",
}
# اقدام ← (وضعیت‌های مجاز مبدا، وضعیت مقصد، فرم دسترسی، توضیح لازم است؟)
TRANSITIONS = {
    "submit": (("DRAFT", "NEEDS_CHANGES", "REJECTED"), "PENDING", FORM_DOCS, False),
    "start_review": (("PENDING",), "IN_REVIEW", FORM_APPROVE, False),
    "request_changes": (("PENDING", "IN_REVIEW"), "NEEDS_CHANGES", FORM_APPROVE, True),
    "reject": (("PENDING", "IN_REVIEW"), "REJECTED", FORM_APPROVE, True),
    "approve": (("PENDING", "IN_REVIEW"), "APPROVED", FORM_APPROVE, False),
    "obsolete": (("APPROVED",), "OBSOLETE", FORM_APPROVE, False),
}
ACTION_LABELS = {
    "submit": "ارسال برای بررسی", "start_review": "شروع بررسی", "request_changes": "نیازمند اصلاح", "reject": "رد سند",
    "approve": "تایید سند", "obsolete": "منسوخ", "archive": "بایگانی", "restore": "بازگردانی از بایگانی",
}
EVENT_LABELS = {
    "CREATE": "ایجاد سند", "UPDATE": "ویرایش مشخصات", "VERSION": "نسخهٔ جدید", "STATUS": "تغییر وضعیت",
    "LINK": "پیوند به رکورد", "UNLINK": "حذف پیوند", "DOWNLOAD": "دریافت فایل", "DELETE": "حذف سند",
    "CAPTURE": "عکس‌برداری با موبایل", "REMINDER": "یادآوری انقضا", "DENIED": "دسترسی ردشده",
}


def escape_like(value: str) -> str:
    """متن کاربر در LIKE حرفی جست‌وجو شود، نه به‌عنوان % و _."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def can(user_id: int | None, company_id: int, form_code: str, action: str) -> bool:
    return user_id is not None and roles_service.user_has_permission(user_id, company_id, form_code, action)


def require(user_id: int | None, company_id: int, form_code: str, action: str, what: str) -> None:
    if not can(user_id, company_id, form_code, action):
        raise PermissionError(f"برای {what} دسترسی لازم را ندارید.")


def settings(session, company_id: int) -> DmsSettings:
    row = session.get(DmsSettings, company_id)
    if row is None:
        row = DmsSettings(company_id=company_id, storage_mode="DB", max_file_mb=25, capture_minutes=10, capture_max_photos=10,
                          expiry_reminder_days=30, keep_gps=False, text_extraction=True, image_ocr=False)
        session.add(row)
        session.flush()
    return row


def confidentiality_ok(user_id: int, doc: DmsDocument) -> bool:
    """اسناد محرمانه و سری فقط برای مالک، مسئول، ثبت‌کننده یا دارندهٔ دسترسی «اسناد محرمانه و سری»."""
    if doc.confidentiality_code in ("PUBLIC", "INTERNAL"):
        return True
    if user_id in (doc.owner_user_id, doc.responsible_user_id, doc.created_by_user_id):
        return True
    return can(user_id, doc.company_id, FORM_CONFIDENTIAL, "VIEW")


def can_view(session, user_id: int | None, company_id: int, doc: DmsDocument | None) -> bool:
    """دیدن سند: همان شرکت، حذف‌نشده، سطح محرمانگی، و دسترسی «مشاهده»ی اسناد یا دسترسی به رکوردی که سند به آن پیوسته است."""
    if user_id is None or doc is None or doc.company_id != company_id or doc.is_deleted:
        return False
    if not confidentiality_ok(user_id, doc):
        return False
    if can(user_id, company_id, FORM_DOCS, "VIEW"):
        return True
    from peecha.services.dms import entities

    links = session.execute(select(DmsLink.entity_type, DmsLink.entity_id).where(
        DmsLink.document_id == doc.document_id, DmsLink.is_active.is_(True))).all()
    return any(entities.can_access(user_id, company_id, entity_type) for entity_type, _entity_id in links)


def load_for(session, user_id: int | None, company_id: int, document_id: int, *, lock: bool = False) -> DmsDocument:
    """سند را فقط اگر کاربر اجازهٔ دیدنش را دارد برمی‌گرداند؛ سند شرکت دیگر یا ناموجود هم همان پیام را می‌گیرد."""
    query = select(DmsDocument).where(DmsDocument.document_id == document_id)
    doc = session.scalar(query.with_for_update() if lock else query)
    if not can_view(session, user_id, company_id, doc):
        if doc is not None and doc.company_id == company_id and not doc.is_deleted:
            _log_denied(company_id, doc.document_id, user_id)
        raise LookupError("سند پیدا نشد یا اجازهٔ دیدن آن را ندارید.")
    return doc


def log(session, company_id: int, document_id: int | None, event_code: str, user_id: int | None, *, note: str | None = None,
        from_status: str | None = None, to_status: str | None = None, version_id: int | None = None,
        details: dict | None = None) -> None:
    session.add(DmsEvent(company_id=company_id, document_id=document_id, event_code=event_code, user_id=user_id,
                         note=(note or None) and note[:1000], from_status=from_status, to_status=to_status,
                         version_id=version_id, details=details))


def _log_denied(company_id: int, document_id: int, user_id: int | None) -> None:
    """تلاش ناموفق برای دیدن سند در جلسهٔ جدا ثبت می‌شود تا با برگشت تراکنش اصلی از دست نرود."""
    from peecha.db.base import new_session

    with new_session() as session:
        log(session, company_id, document_id, "DENIED", user_id)
        session.commit()


def save_settings(company_id: int, user_id: int, values: dict) -> None:
    """تنظیمات اسناد شرکت؛ پوشهٔ ذخیره‌سازی پیش از ذخیره آزموده می‌شود."""
    import os
    from pathlib import Path

    from peecha.db.base import new_session

    require(user_id, company_id, FORM_SETTINGS, "EDIT", "تغییر تنظیمات اسناد")
    mode = values.get("storage_mode", "DB")
    if mode not in ("DB", "FS"):
        raise ValueError("محل ذخیره‌سازی معتبر نیست.")
    root = (values.get("storage_root") or "").strip() or None
    if mode == "FS":
        if not root:
            raise ValueError("برای ذخیره روی پوشه، مسیر پوشهٔ مشترک را وارد کنید.")
        folder = Path(root)
        try:
            folder.mkdir(parents=True, exist_ok=True)
            probe = folder / f".peecha-write-test-{os.getpid()}"
            probe.write_bytes(b"ok")
            probe.unlink()
        except OSError as exc:
            raise ValueError(f"در پوشهٔ «{root}» نوشتن ممکن نیست: {exc.strerror or exc}") from exc
    url = (values.get("mobile_base_url") or "").strip().rstrip("/") or None
    if url and not url.lower().startswith(("https://", "http://")):
        raise ValueError("نشانی سرور موبایل باید با https:// شروع شود (http:// فقط برای آزمایش در شبکهٔ داخلی).")
    numbers = {"max_file_mb": (1, 200), "capture_minutes": (2, 120), "capture_max_photos": (1, 30), "expiry_reminder_days": (0, 365)}
    with new_session() as session:
        row = settings(session, company_id)
        row.storage_mode, row.storage_root, row.mobile_base_url = mode, root, url
        for name, (low, high) in numbers.items():
            value = int(values.get(name, getattr(row, name)))
            if not low <= value <= high:
                raise ValueError(f"مقدار «{name}» باید بین {low} و {high} باشد.")
            setattr(row, name, value)
        for name in ("keep_gps", "text_extraction", "image_ocr"):
            setattr(row, name, bool(values.get(name, getattr(row, name))))
        row.updated_at = now()
        session.commit()
