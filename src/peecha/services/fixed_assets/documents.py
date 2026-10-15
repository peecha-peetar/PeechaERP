"""مدارک دارایی (فاکتور، گارانتی، قرارداد، دفترچه، گواهی، تصویر، مدرک فنی) — R265.

از همان سیستم پیوست موجود (doc.attachments) با فرم «fa_assets» و source_record_id = شناسهٔ دارایی؛ فایل‌ها کنار
مرکز رسانه ذخیره می‌شوند (بدون جدول تازه).
"""

from __future__ import annotations

import datetime
import hashlib
import shutil
import uuid
from pathlib import Path

from sqlalchemy import select

from peecha.config import SETTINGS_DIR
from peecha.db.base import new_session
from peecha.db.models.documents import Attachment
from peecha.db.models.security import Form
from peecha.services import roles as roles_service
from peecha.services.fixed_assets import assets as fa

DOCUMENT_TYPES = {"INVOICE": "فاکتور", "WARRANTY": "گارانتی", "CONTRACT": "قرارداد", "MANUAL": "دفترچهٔ راهنما",
                  "CERTIFICATE": "گواهی", "IMAGE": "تصویر", "TECHNICAL": "مدرک فنی", "OTHER": "سایر"}
_FORM_CODE = "fa_assets"
_DIR = SETTINGS_DIR / "fixed_assets"


def _form_id(session) -> int:
    roles_service.ensure_catalog()
    form_id = session.scalar(select(Form.form_id).where(Form.code == _FORM_CODE))
    if form_id is None:
        raise ValueError("فرم «دارایی‌ها» در فهرست فرم‌ها ثبت نشده است.")
    return form_id


def add_document(company_id: int, user_id: int, asset_id: int, file_path: str, document_type_code: str = "OTHER") -> int:
    if document_type_code not in DOCUMENT_TYPES:
        raise ValueError("نوع مدرک نامعتبر است.")
    fa.get_asset(company_id, asset_id)
    source = Path(file_path)
    if not source.is_file():
        raise ValueError("فایل یافت نشد.")
    _DIR.mkdir(parents=True, exist_ok=True)
    content = source.read_bytes()
    extension = source.suffix.lstrip(".")
    destination = _DIR / (f"{uuid.uuid4().hex}.{extension}" if extension else uuid.uuid4().hex)
    shutil.copyfile(source, destination)
    with new_session() as session:
        row = Attachment(company_id=company_id, form_id=_form_id(session), source_record_id=asset_id, file_name=source.name,
                         file_extension=extension, file_size_bytes=len(content), storage_key=str(destination),
                         content_sha256=hashlib.sha256(content).digest(), uploaded_by_user_id=user_id,
                         document_type_code=document_type_code)
        session.add(row)
        session.commit()
        return row.attachment_id


def list_documents(company_id: int, asset_id: int) -> list[Attachment]:
    with new_session() as session:
        rows = list(session.scalars(select(Attachment).where(
            Attachment.company_id == company_id, Attachment.form_id == _form_id(session),
            Attachment.source_record_id == asset_id, Attachment.is_deleted.is_(False)).order_by(Attachment.uploaded_at)))
        session.expunge_all()
        return rows


def delete_document(company_id: int, user_id: int, attachment_id: int) -> None:
    with new_session() as session:
        row = session.get(Attachment, attachment_id)
        if row is None or row.company_id != company_id:
            raise ValueError("مدرک نامعتبر است.")
        row.is_deleted, row.deleted_by_user_id, row.deleted_at = True, user_id, datetime.datetime.now()
        session.commit()
