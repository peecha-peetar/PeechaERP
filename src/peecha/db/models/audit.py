"""مدل‌های schema حسابرسی (audit) — ردِ تغییرناپذیرِ رویدادهای کسب‌وکاری.

معادل db/schema/006_audit_log.sql. جدولِ *_history در sec (مثلِ
sec.role_form_permissions_history) تاریخچه‌ی خودکارِ سطحِ ردیف است؛ این
جدول یک ردِ عمومیِ سطحِ اپلیکیشن است (کدام کاربر، کدام موجودیت، چه
عملیاتی) و در دیتابیس با تریگر از UPDATE/DELETE محافظت می‌شود، پس اینجا
هم — مثلِ جدول‌های history — هیچ‌وقت از طریق ORM ویرایش/حذف نمی‌شود."""

from __future__ import annotations

import datetime
from typing import Any

from sqlalchemy import BigInteger, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from peecha.db.base import Base


class ActivityLog(Base):
    __tablename__ = "activity_log"
    __table_args__ = {"schema": "audit"}

    log_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("core.companies.company_id"))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    entity_type: Mapped[str] = mapped_column(String(50))
    entity_id: Mapped[int]
    action: Mapped[str] = mapped_column(String(10))  # CREATE, UPDATE, DELETE
    changes: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())
