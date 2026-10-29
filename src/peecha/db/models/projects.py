"""R363: مدیریت پروژه — پروژه روی تفصیلی «پروژه»، فعالیت‌ها (درختی) و پیوند فعالیت‌ها."""

from __future__ import annotations

import datetime
import decimal

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from peecha.db.base import Base

_PRJ = {"schema": "prj"}


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = _PRJ

    project_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    project_detail_account_id: Mapped[int] = mapped_column(ForeignKey("acc.detail_accounts.detail_account_id"), unique=True)
    customer_detail_account_id: Mapped[int | None] = mapped_column(ForeignKey("acc.detail_accounts.detail_account_id"))
    manager_employee_id: Mapped[int | None] = mapped_column(ForeignKey("hr.employees.employee_id", ondelete="SET NULL"))
    status_code: Mapped[str] = mapped_column(String(20), default="PLANNING")
    start_date: Mapped[datetime.date] = mapped_column(Date)
    target_end_date: Mapped[datetime.date | None] = mapped_column(Date)
    contract_amount: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=0)
    description: Mapped[str | None] = mapped_column(String(1000))
    baseline_set_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc))


class ProjectTask(Base):
    """فعالیت یا فاز (فعالیتی که زیرمجموعه دارد فاز است و تاریخ و پیشرفتش از زیرمجموعه‌ها می‌آید)؛ مدت صفر = نقطهٔ عطف."""

    __tablename__ = "tasks"
    __table_args__ = _PRJ

    task_id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("prj.projects.project_id", ondelete="CASCADE"))
    parent_task_id: Mapped[int | None] = mapped_column(ForeignKey("prj.tasks.task_id", ondelete="CASCADE"))
    sort_order: Mapped[int] = mapped_column(default=0)
    name: Mapped[str] = mapped_column(String(200))
    duration_days: Mapped[int] = mapped_column(default=1)
    start_no_earlier: Mapped[datetime.date | None] = mapped_column(Date)
    responsible_employee_id: Mapped[int | None] = mapped_column(ForeignKey("hr.employees.employee_id", ondelete="SET NULL"))
    planned_hours: Mapped[decimal.Decimal] = mapped_column(Numeric(10, 2), default=0)
    planned_cost: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=0)
    percent_complete: Mapped[decimal.Decimal] = mapped_column(Numeric(5, 2), default=0)
    actual_start: Mapped[datetime.date | None] = mapped_column(Date)
    actual_finish: Mapped[datetime.date | None] = mapped_column(Date)
    baseline_start: Mapped[datetime.date | None] = mapped_column(Date)
    baseline_finish: Mapped[datetime.date | None] = mapped_column(Date)
    baseline_cost: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 2))
    notes: Mapped[str | None] = mapped_column(String(1000))


class TaskLink(Base):
    """پیوند دو فعالیت: FS پایان به شروع، SS شروع به شروع، FF پایان به پایان؛ lag_days به روز کاری (منفی = هم‌پوشانی)."""

    __tablename__ = "task_links"
    __table_args__ = _PRJ

    link_id: Mapped[int] = mapped_column(primary_key=True)
    predecessor_task_id: Mapped[int] = mapped_column(ForeignKey("prj.tasks.task_id", ondelete="CASCADE"))
    successor_task_id: Mapped[int] = mapped_column(ForeignKey("prj.tasks.task_id", ondelete="CASCADE"))
    link_type: Mapped[str] = mapped_column(String(2), default="FS")
    lag_days: Mapped[int] = mapped_column(default=0)


class LaborRate(Base):
    """R364: نرخ ساعتی هزینهٔ کارکرد از تاریخ؛ employee_id خالی = نرخ پیش‌فرض همهٔ کارکنان."""

    __tablename__ = "labor_rates"
    __table_args__ = _PRJ

    rate_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    employee_id: Mapped[int | None] = mapped_column(ForeignKey("hr.employees.employee_id", ondelete="CASCADE"))
    valid_from: Mapped[datetime.date] = mapped_column(Date)
    hourly_cost: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2))


class TimesheetEntry(Base):
    """R364: کارکرد یک کارمند روی پروژه (و فعالیت) در یک روز؛ نرخ ساعتی هنگام تایید ثابت می‌شود."""

    __tablename__ = "timesheet_entries"
    __table_args__ = _PRJ

    entry_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    project_id: Mapped[int] = mapped_column(ForeignKey("prj.projects.project_id"))
    task_id: Mapped[int | None] = mapped_column(ForeignKey("prj.tasks.task_id"))
    employee_id: Mapped[int] = mapped_column(ForeignKey("hr.employees.employee_id"))
    work_date: Mapped[datetime.date] = mapped_column(Date)
    hours: Mapped[decimal.Decimal] = mapped_column(Numeric(5, 2))
    description: Mapped[str | None] = mapped_column(String(500))
    status_code: Mapped[str] = mapped_column(String(20), default="DRAFT")
    hourly_cost: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 2))
    decision_note: Mapped[str | None] = mapped_column(String(500))
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc))
    decided_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    decided_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
