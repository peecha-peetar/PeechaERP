"""پیوست درخواست تعمیر و دستور کار (R312): عکس خرابی، گزارش آزمون، فاکتور پیمانکار، ...

همان پیوست عمومی (doc.attachments) با فرم «صف درخواست‌ها» یا «دستور کار» و source_record_id = شناسهٔ رکورد؛
فایل‌ها کنار مدارک دارایی ذخیره می‌شوند. جدول تازه‌ای ساخته نمی‌شود.
"""

from __future__ import annotations

import datetime
import hashlib
import uuid
from pathlib import Path

from sqlalchemy import select

from peecha.config import SETTINGS_DIR
from peecha.db.base import new_session
from peecha.db.models.documents import Attachment
from peecha.db.models.maintenance import WorkOrder, WorkRequest
from peecha.db.models.security import Form
from peecha.services import roles as roles_service
from peecha.services.maintenance import common as c

DOCUMENT_TYPES = {"IMAGE": "عکس", "REPORT": "گزارش آزمون/بازدید", "INVOICE": "فاکتور", "MANUAL": "دستورالعمل", "OTHER": "سایر"}
_DIR = SETTINGS_DIR / "maintenance"
_KINDS = {"REQUEST": (c.ATTACH_FORM_REQUEST, WorkRequest, "MntWorkRequest"),
          "WORK_ORDER": (c.ATTACH_FORM_WO, WorkOrder, "MntWorkOrder")}


def _form_id(session, form_code: str) -> int:
    roles_service.ensure_catalog()
    form_id = session.scalar(select(Form.form_id).where(Form.code == form_code))
    if form_id is None:
        raise ValueError("فرم پیوست نگهداری در فهرست فرم‌ها ثبت نشده است.")
    return form_id


def _check(session, company_id: int, kind: str, record_id: int):
    if kind not in _KINDS:
        raise ValueError("نوع رکورد نامعتبر است.")
    form_code, model, entity = _KINDS[kind]
    row = session.get(model, record_id)
    if row is None or row.company_id != company_id:
        raise ValueError("رکورد نامعتبر است.")
    return form_code, entity


def add(company_id: int, user_id: int, kind: str, record_id: int, file_path: str | None, document_type_code: str = "IMAGE",
        content: bytes | None = None, file_name: str | None = None) -> int:
    """پیوست از مسیر فایل (رومیزی) یا محتوای خام (موبایل)."""
    if document_type_code not in DOCUMENT_TYPES:
        raise ValueError("نوع پیوست نامعتبر است.")
    if content is None:
        source = Path(file_path)
        if not source.is_file():
            raise ValueError("فایل یافت نشد.")
        content, file_name = source.read_bytes(), file_name or source.name
    if not content:
        raise ValueError("فایل خالی است.")
    if len(content) > 15 * 1024 * 1024:
        raise ValueError("حجم پیوست بیش از ۱۵ مگابایت است.")
    file_name = (file_name or "پیوست").strip()[:200]
    extension = Path(file_name).suffix.lstrip(".")[:10]
    with new_session() as session:
        form_code, entity = _check(session, company_id, kind, record_id)
        _DIR.mkdir(parents=True, exist_ok=True)
        destination = _DIR / (f"{uuid.uuid4().hex}.{extension}" if extension else uuid.uuid4().hex)
        destination.write_bytes(content)
        row = Attachment(company_id=company_id, form_id=_form_id(session, form_code), source_record_id=record_id,
                         file_name=file_name, file_extension=extension or None, file_size_bytes=len(content),
                         storage_key=str(destination), content_sha256=hashlib.sha256(content).digest(),
                         uploaded_by_user_id=user_id, document_type_code=document_type_code)
        session.add(row)
        session.flush()
        c.audit(session, company_id, user_id, entity, record_id, "ATTACH", {"attachment_id": row.attachment_id,
                                                                            "file_name": file_name})
        session.commit()
        return row.attachment_id


def list_for(company_id: int, kind: str, record_id: int) -> list[Attachment]:
    with new_session() as session:
        form_code, _entity = _check(session, company_id, kind, record_id)
        rows = list(session.scalars(select(Attachment).where(
            Attachment.company_id == company_id, Attachment.form_id == _form_id(session, form_code),
            Attachment.source_record_id == record_id, Attachment.is_deleted.is_(False)).order_by(Attachment.uploaded_at)))
        session.expunge_all()
        return rows


def delete(company_id: int, user_id: int, attachment_id: int) -> None:
    with new_session() as session:
        row = session.get(Attachment, attachment_id)
        if row is None or row.company_id != company_id:
            raise ValueError("پیوست نامعتبر است.")
        row.is_deleted, row.deleted_by_user_id, row.deleted_at = True, user_id, datetime.datetime.now()
        session.commit()
