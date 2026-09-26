"""مدل ضمائم سند.

معادل db/schema/005_attachments.sql
"""

from __future__ import annotations

import datetime

from sqlalchemy import ForeignKey, String, func
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
