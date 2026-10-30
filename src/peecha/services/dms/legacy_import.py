"""R354: انتقال پیوست‌های قدیمی (doc.attachments) به سامانهٔ اسناد.

هر پیوست قدیمی حذف‌نشده یک سند در سامانهٔ اسناد می‌شود، با همان فایل، و به همان رکورد (دارایی، دستور کار، سند
حسابداری) پیوند می‌خورد؛ پیوستی که رکورد معادلی در سامانهٔ اسناد ندارد (درخواست تعمیر، مرکز رسانه) بدون پیوند و با
برچسب منبعش ثبت می‌شود. پیوست اصلی دست نمی‌خورد و فرم‌های قدیمی مثل قبل کار می‌کنند؛ انتقال دوباره تکراری نمی‌سازد.
فایل باید از همین کامپیوتر در دسترس باشد (مسیر ذخیره‌شدهٔ پیوست قدیمی)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.documents import Attachment, LegacyAttachmentImport
from peecha.db.models.security import Form
from peecha.services.dms import documents as dms

# کد فرم پیوست قدیمی ← (نوع رکورد در سامانهٔ اسناد یا None، برچسب منبع)
_SOURCES = {
    "fa_assets": ("fixed_asset", "دارایی ثابت"),
    "mnt_work_orders": ("work_order", "دستور کار نگهداری"),
    "mnt_requests": (None, "درخواست تعمیر"),
    "journal_entry": ("journal_entry", "سند حسابداری"),
    "order_tracking": ("journal_entry", "مدیریت سفارشات"),
    "media_center": (None, "مرکز رسانه"),
}
_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "gif", "bmp", "webp", "heic"}


@dataclass
class ImportReport:
    imported: int = 0
    missing_files: list[str] = field(default_factory=list)
    unlinked: int = 0
    rejected: list[str] = field(default_factory=list)


def _pending(session, company_id: int):
    done = select(LegacyAttachmentImport.attachment_id)
    return session.execute(select(Attachment, Form.code).join(Form, Form.form_id == Attachment.form_id).where(
        Attachment.company_id == company_id, Attachment.is_deleted.is_(False), Attachment.attachment_id.not_in(done))
        .order_by(Attachment.attachment_id)).all()


def pending_count(company_id: int) -> int:
    with new_session() as session:
        return len(_pending(session, company_id))


def _type(attachment: Attachment, entity_type: str | None) -> str:
    extension = (attachment.file_extension or Path(attachment.file_name).suffix.lstrip(".")).lower()
    if attachment.document_type_code == "INVOICE":
        return "INVOICE"
    if extension in _IMAGE_EXTENSIONS:
        return "IMAGE"
    return "FINANCIAL" if entity_type == "journal_entry" else "OTHER"


def import_all(company_id: int, user_id: int) -> ImportReport:
    """همهٔ پیوست‌های قدیمی منتقل‌نشده را به سامانهٔ اسناد می‌برد."""
    report = ImportReport()
    with new_session() as session:
        rows = [(a.attachment_id, a.file_name, a.storage_key, a.source_record_id, _type(a, _SOURCES.get(code, (None,))[0]), code)
                for a, code in _pending(session, company_id)]
    for attachment_id, file_name, storage_key, record_id, type_code, form_code in rows:
        entity_type, source_label = _SOURCES.get(form_code, (None, form_code))
        path = Path(storage_key or "")
        if not path.is_file():
            report.missing_files.append(file_name)
            continue
        fields = dms.DocumentFields(title=Path(file_name).stem[:300] or file_name, document_type_code=type_code,
                                    description=f"منتقل‌شده از پیوست قدیمی «{source_label}» (رکورد {record_id})",
                                    tags=[f"پیوست قدیمی {source_label}"])
        files = [(file_name, path.read_bytes())]
        try:
            document_id = dms.create_document(company_id, user_id, fields, files,
                                              [(entity_type, record_id)] if entity_type else [], source="DESKTOP",
                                              reason="انتقال از پیوست قدیمی")
        except (ValueError, LookupError):  # رکورد اصلی دیگر نیست: فایل بدون پیوند حفظ می‌شود
            try:
                document_id = dms.create_document(company_id, user_id, fields, files, source="DESKTOP",
                                                  reason="انتقال از پیوست قدیمی")
            except ValueError as exc:  # خود فایل پذیرفته نیست (مثلاً عکس خراب یا پسوند غیرمجاز)
                report.rejected.append(f"{file_name}: {exc}")
                continue
            entity_type = None
        if entity_type is None:
            report.unlinked += 1
        with new_session() as session:
            session.add(LegacyAttachmentImport(attachment_id=attachment_id, company_id=company_id, dms_document_id=document_id,
                                               imported_by_user_id=user_id))
            session.commit()
        report.imported += 1
    return report


def copy_entity_documents(source_company_id: int, target_company_id: int, user_id: int, entity_type: str,
                          source_id: int, target_id: int) -> int:
    """اسناد پیوسته به یک رکورد را با همان فایل‌ها در شرکت مقصد می‌سازد و به رکورد جدید پیوند می‌دهد (انتقال بین شرکت‌ها)."""
    copied = 0
    for row in dms.documents_for_entity(source_company_id, user_id, entity_type, source_id):
        doc = dms.get_document(source_company_id, user_id, row.document_id)
        current = next((v for v in doc.versions if v.is_current), None)
        files = [dms.read_file(source_company_id, user_id, f.file_id)[::2] for f in (current.files if current else [])]
        dms.create_document(target_company_id, user_id, dms.DocumentFields(
            title=doc.title, document_type_code=doc.document_type_code, confidentiality_code=doc.confidentiality_code,
            issue_date=doc.issue_date, valid_from=doc.valid_from, expiry_date=doc.expiry_date, description=doc.description,
            tags=list(doc.tags)), files, [(entity_type, target_id)], source="DESKTOP", reason="انتقال از شرکت مبدأ")
        copied += 1
    return copied
