"""رجیستری گزارش‌های حرفه‌ای قابل‌تخصیص — معادل
098_report_template_registry.sql."""

from __future__ import annotations

import datetime
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Integer, LargeBinary, SmallInteger, String
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
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


class ReportSchedule(Base):
    """R375: زمان‌بندی اجرای خودکار یک گزارش ساخته‌شده."""

    __tablename__ = "report_schedules"
    __table_args__ = {"schema": "rpt"}

    schedule_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    report_id: Mapped[int] = mapped_column(ForeignKey("rpt.custom_reports.report_id", ondelete="CASCADE"))
    frequency_code: Mapped[str] = mapped_column(String(10))
    run_hour: Mapped[int] = mapped_column(SmallInteger, default=7)
    weekday: Mapped[int | None] = mapped_column(SmallInteger)
    month_day: Mapped[int | None] = mapped_column(SmallInteger)
    period_code: Mapped[str] = mapped_column(String(15), default="NONE")
    recipient_user_ids: Mapped[list[int]] = mapped_column(ARRAY(Integer), default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    next_run_at: Mapped[datetime.datetime]
    last_run_at: Mapped[datetime.datetime | None]
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    created_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")


class ReportRun(Base):
    __tablename__ = "report_runs"
    __table_args__ = {"schema": "rpt"}

    run_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    schedule_id: Mapped[int | None] = mapped_column(ForeignKey("rpt.report_schedules.schedule_id", ondelete="CASCADE"))
    report_id: Mapped[int] = mapped_column(ForeignKey("rpt.custom_reports.report_id", ondelete="CASCADE"))
    run_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")
    status_code: Mapped[str] = mapped_column(String(10))
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    recipient_user_ids: Mapped[list[int]] = mapped_column(ARRAY(Integer), default=list)
    file_name: Mapped[str | None] = mapped_column(String(200))
    content: Mapped[bytes | None] = mapped_column(LargeBinary)
    error_message: Mapped[str | None] = mapped_column(String(500))
