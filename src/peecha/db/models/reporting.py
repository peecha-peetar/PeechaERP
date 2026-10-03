"""رجیستریِ گزارش‌هایِ حرفه‌ایِ قابلِ‌تخصیص -- معادلِ
098_report_template_registry.sql."""

from __future__ import annotations

import datetime

from sqlalchemy import Boolean, ForeignKey, String
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
