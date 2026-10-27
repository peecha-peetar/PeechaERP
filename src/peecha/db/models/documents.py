"""مدل ضمائم سند.

معادل db/schema/005_attachments.sql
"""

from __future__ import annotations

import datetime

from sqlalchemy import BigInteger, Date, ForeignKey, Integer, LargeBinary, SmallInteger, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from peecha.db.base import Base


class Attachment(Base):
    __tablename__ = "attachments"
    __table_args__ = {"schema": "doc"}

    attachment_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    form_id: Mapped[int] = mapped_column(ForeignKey("sec.forms.form_id"))
    source_record_id: Mapped[int]  # ارجاع نرم، مثل wf.cartable_items
    file_name: Mapped[str] = mapped_column(String(260))
    file_extension: Mapped[str] = mapped_column(String(20))
    file_size_bytes: Mapped[int]
    storage_key: Mapped[str] = mapped_column(String(500))
    content_sha256: Mapped[bytes | None]
    uploaded_by_user_id: Mapped[int] = mapped_column(ForeignKey("sec.users.user_id"))
    uploaded_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())
    is_deleted: Mapped[bool] = mapped_column(default=False)
    deleted_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    deleted_at: Mapped[datetime.datetime | None]
    # طبقِ درخواستِ صریح («یکعکس بعنوان عکس اصلی نمایش داده بشه»): از میانِ
    # چند عکسِ فعالِ یک رکورد (source_record_id)، دقیقاً یکی می‌تواند
    # عکسِ اصلی باشد -- برایِ بندانگشتیِ کنارِ نام و پیش‌فرضِ زومِ اول.
    is_primary: Mapped[bool] = mapped_column(default=False)
    # R265: نوعِ مدرک (فاکتور/گارانتی/قرارداد/دفترچه/گواهی/تصویر/فنی) -- اختیاری، برایِ مدارکِ دارایی
    document_type_code: Mapped[str | None] = mapped_column(String(20))


# --- R343: مدیریت اسناد (DMS) -------------------------------------------------------------------
_DOC = {"schema": "doc"}


class DmsSettings(Base):
    __tablename__ = "dms_settings"
    __table_args__ = _DOC

    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"), primary_key=True)
    storage_mode: Mapped[str] = mapped_column(String(4), default="DB")
    storage_root: Mapped[str | None] = mapped_column(String(500))
    max_file_mb: Mapped[int] = mapped_column(default=25)
    mobile_base_url: Mapped[str | None] = mapped_column(String(300))
    capture_minutes: Mapped[int] = mapped_column(default=10)
    capture_max_photos: Mapped[int] = mapped_column(default=10)
    expiry_reminder_days: Mapped[int] = mapped_column(default=30)
    keep_gps: Mapped[bool] = mapped_column(default=False)
    text_extraction: Mapped[bool] = mapped_column(default=True)
    image_ocr: Mapped[bool] = mapped_column(default=False)
    updated_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())


class DmsCategory(Base):
    __tablename__ = "categories"
    __table_args__ = _DOC

    category_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    parent_category_id: Mapped[int | None] = mapped_column(ForeignKey("doc.categories.category_id"))
    name: Mapped[str] = mapped_column(String(150))
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())


class DmsTag(Base):
    __tablename__ = "tags"
    __table_args__ = _DOC

    tag_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    name: Mapped[str] = mapped_column(String(80))


class DmsFile(Base):
    __tablename__ = "files"
    __table_args__ = _DOC

    file_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    storage_mode: Mapped[str] = mapped_column(String(4))
    storage_key: Mapped[str | None] = mapped_column(String(300))
    content: Mapped[bytes | None] = mapped_column(LargeBinary, deferred=True)
    thumbnail: Mapped[bytes | None] = mapped_column(LargeBinary, deferred=True)
    sha256: Mapped[bytes] = mapped_column(LargeBinary)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    mime_type: Mapped[str] = mapped_column(String(100))
    extension: Mapped[str] = mapped_column(String(10))
    original_name: Mapped[str] = mapped_column(String(260))
    width: Mapped[int | None]
    height: Mapped[int | None]
    text_status: Mapped[str] = mapped_column(String(8), default="NONE")
    text_content: Mapped[str | None] = mapped_column(Text, deferred=True)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("sec.users.user_id"))
    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())


class DmsDocument(Base):
    __tablename__ = "documents"
    __table_args__ = _DOC

    document_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    branch_id: Mapped[int | None] = mapped_column(ForeignKey("comm.branches.branch_id"))
    document_no: Mapped[str] = mapped_column(String(30))
    title: Mapped[str] = mapped_column(String(300))
    document_type_code: Mapped[str] = mapped_column(String(20))
    category_id: Mapped[int | None] = mapped_column(ForeignKey("doc.categories.category_id"))
    confidentiality_code: Mapped[str] = mapped_column(String(12), default="INTERNAL")
    status_code: Mapped[str] = mapped_column(String(14), default="DRAFT")
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("sec.users.user_id"))
    responsible_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    issue_date: Mapped[datetime.date | None] = mapped_column(Date)
    valid_from: Mapped[datetime.date | None] = mapped_column(Date)
    expiry_date: Mapped[datetime.date | None] = mapped_column(Date)
    description: Mapped[str | None] = mapped_column(Text)
    current_version_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("doc.document_versions.version_id"))
    approved_version_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("doc.document_versions.version_id"))
    archived_from_status: Mapped[str | None] = mapped_column(String(14))
    is_deleted: Mapped[bool] = mapped_column(default=False)
    deleted_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    deleted_at: Mapped[datetime.datetime | None]
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("sec.users.user_id"))
    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())
    updated_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    updated_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())
    row_version: Mapped[int] = mapped_column(default=1)


class DmsVersion(Base):
    __tablename__ = "document_versions"
    __table_args__ = _DOC

    version_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    document_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("doc.documents.document_id"))
    version_no: Mapped[int]
    change_reason: Mapped[str | None] = mapped_column(String(500))
    source_code: Mapped[str] = mapped_column(String(10), default="DESKTOP")
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("sec.users.user_id"))
    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())


class DmsVersionFile(Base):
    __tablename__ = "version_files"
    __table_args__ = _DOC

    version_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("doc.document_versions.version_id"), primary_key=True)
    position: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    file_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("doc.files.file_id"))


class DmsDocumentTag(Base):
    __tablename__ = "document_tags"
    __table_args__ = _DOC

    document_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("doc.documents.document_id"), primary_key=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey("doc.tags.tag_id"), primary_key=True)


class DmsLink(Base):
    __tablename__ = "document_links"
    __table_args__ = _DOC

    link_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    document_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("doc.documents.document_id"))
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    entity_type: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[int] = mapped_column(BigInteger)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("sec.users.user_id"))
    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())
    removed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    removed_at: Mapped[datetime.datetime | None]


class DmsEvent(Base):
    __tablename__ = "document_events"
    __table_args__ = _DOC

    event_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    document_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("doc.documents.document_id"))
    event_code: Mapped[str] = mapped_column(String(30))
    from_status: Mapped[str | None] = mapped_column(String(14))
    to_status: Mapped[str | None] = mapped_column(String(14))
    version_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("doc.document_versions.version_id"))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    note: Mapped[str | None] = mapped_column(String(1000))
    details: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())


class DmsReminder(Base):
    __tablename__ = "document_reminders"
    __table_args__ = _DOC

    reminder_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    document_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("doc.documents.document_id"))
    reminder_kind: Mapped[str] = mapped_column(String(14))
    expiry_date: Mapped[datetime.date] = mapped_column(Date)
    notified_user_ids: Mapped[list[int]] = mapped_column(ARRAY(Integer), default=list)
    result_code: Mapped[str] = mapped_column(String(10), default="SENT")
    sent_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())


class DmsCaptureRequest(Base):
    __tablename__ = "capture_requests"
    __table_args__ = _DOC

    request_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    branch_id: Mapped[int | None] = mapped_column(ForeignKey("comm.branches.branch_id"))
    token_hash: Mapped[bytes] = mapped_column(LargeBinary)
    requested_by_user_id: Mapped[int] = mapped_column(ForeignKey("sec.users.user_id"))
    target_entity_type: Mapped[str | None] = mapped_column(String(40))
    target_entity_id: Mapped[int | None] = mapped_column(BigInteger)
    target_document_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("doc.documents.document_id"))
    document_type_code: Mapped[str] = mapped_column(String(20), default="IMAGE")
    category_id: Mapped[int | None] = mapped_column(ForeignKey("doc.categories.category_id"))
    title: Mapped[str | None] = mapped_column(String(300))
    max_photos: Mapped[int] = mapped_column(default=10)
    status_code: Mapped[str] = mapped_column(String(10), default="PENDING")
    attempt_count: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())
    expires_at: Mapped[datetime.datetime]
    opened_at: Mapped[datetime.datetime | None]
    consumed_at: Mapped[datetime.datetime | None]
    completed_at: Mapped[datetime.datetime | None]
    cancelled_at: Mapped[datetime.datetime | None]
    cancelled_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    result_document_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("doc.documents.document_id"))
    result_version_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("doc.document_versions.version_id"))
    upload_key: Mapped[str | None] = mapped_column(String(80))
    failure_reason: Mapped[str | None] = mapped_column(String(300))
