"""مرکزِ رسانه -- طبقِ ادامه‌یِ اولویتِ بخشِ محتوا/بازاریابی: یک کتابخانه‌یِ
عکس/فایلِ مشترکِ شرکت (نه متصل به یک سندِ خاص) برایِ استفاده‌یِ دوباره
در مقالات/پست‌ها/محصولات. معماری هم‌الگو با گالریِ عکسِ حسابِ تفصیلی
(detail_dimensions.py) است: از همان جدولِ عمومیِ doc.attachments استفاده
می‌شود -- فقط source_record_id این‌جا company_id است (یعنی «رکورد»
همان کتابخانه‌یِ سراسریِ شرکت است، نه یک حسابِ خاص) -- پس نیازی به
جدولِ تازه نیست."""

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
from peecha.services.detail_dimensions import is_image_extension

_FORM_CODE = "media_center"
_MEDIA_DIR = SETTINGS_DIR / "media_center"


def _get_form_id(session) -> int:
    roles_service.ensure_catalog()
    form = session.scalar(select(Form).where(Form.code == _FORM_CODE))
    if form is None:
        raise ValueError("فرمِ «مرکزِ رسانه» هنوز در فهرستِ فرم‌ها ثبت نشده است.")
    return form.form_id


def upload_media(company_id: int, user_id: int, file_path: str) -> int:
    source = Path(file_path)
    if not source.is_file():
        raise ValueError("فایل یافت نشد.")
    try:
        _MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ValueError(f"پوشهٔ مرکزِ رسانه («{_MEDIA_DIR}») در دسترس نیست: {exc}") from exc
    content = source.read_bytes()
    digest = hashlib.sha256(content).digest()
    extension = source.suffix.lstrip(".")
    storage_name = f"{uuid.uuid4().hex}.{extension}" if extension else uuid.uuid4().hex
    destination = _MEDIA_DIR / storage_name
    shutil.copyfile(source, destination)
    with new_session() as session:
        form_id = _get_form_id(session)
        new_row = Attachment(
            company_id=company_id, form_id=form_id, source_record_id=company_id,
            file_name=source.name, file_extension=extension, file_size_bytes=len(content),
            storage_key=str(destination), content_sha256=digest, uploaded_by_user_id=user_id,
        )
        session.add(new_row)
        session.commit()
        return new_row.attachment_id


def list_media(company_id: int) -> list[Attachment]:
    with new_session() as session:
        form_id = _get_form_id(session)
        rows = session.scalars(
            select(Attachment)
            .where(
                Attachment.company_id == company_id, Attachment.form_id == form_id,
                Attachment.source_record_id == company_id, Attachment.is_deleted.is_(False),
            )
            .order_by(Attachment.uploaded_at.desc())
        ).all()
        session.expunge_all()
        return list(rows)


def delete_media(attachment_id: int, company_id: int, user_id: int) -> None:
    with new_session() as session:
        row = session.get(Attachment, attachment_id)
        if row is None or row.company_id != company_id or row.is_deleted:
            raise ValueError("فایل یافت نشد.")
        row.is_deleted = True
        row.deleted_by_user_id = user_id
        row.deleted_at = datetime.datetime.now()
        session.commit()
