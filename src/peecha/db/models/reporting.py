"""رجیستری گزارش‌های حرفه‌ای قابل‌تخصیص — معادل
098_report_template_registry.sql."""

from __future__ import annotations

import datetime
from typing import Any

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from peecha.db.base import Base


class ReportTemplate(Base):
    __tablename__ = "report_templates"
    __table_args__ = (
        {"schema": "rpt"},
    )

    report_template_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    form_code: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(150))
    file_name: Mapped[str] = mapped_column(String(120))
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")


class CustomReport(Base):
    """R374: گزارش ساخته‌شده در گزارش‌ساز (تعریف به JSON)."""

    __tablename__ = "custom_reports"
    __table_args__ = {"schema": "rpt"}

    report_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("sec.users.user_id"))
    name: Mapped[str] = mapped_column(String(150))
    dataset_code: Mapped[str] = mapped_column(String(40))
    definition: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    is_shared: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")
    updated_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")
