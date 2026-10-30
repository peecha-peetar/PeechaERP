"""R367: جذب و استخدام (و در نسخه‌های بعد ارزیابی عملکرد و آموزش) روی پرونده‌های پرسنلی hr."""

from __future__ import annotations

import datetime
import decimal

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from peecha.db.base import Base

_HR = {"schema": "hr"}


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


class JobOpening(Base):
    __tablename__ = "job_openings"
    __table_args__ = _HR

    opening_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    code: Mapped[str] = mapped_column(String(30))
    title: Mapped[str] = mapped_column(String(200))
    position_id: Mapped[int] = mapped_column(ForeignKey("hr.positions.position_id"))
    headcount: Mapped[int] = mapped_column(default=1)
    status_code: Mapped[str] = mapped_column(String(20), default="OPEN")
    opened_on: Mapped[datetime.date] = mapped_column(Date)
    close_by: Mapped[datetime.date | None] = mapped_column(Date)
    salary_min: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 2))
    salary_max: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 2))
    hiring_manager_employee_id: Mapped[int | None] = mapped_column(ForeignKey("hr.employees.employee_id", ondelete="SET NULL"))
    description: Mapped[str | None] = mapped_column(String(2000))
    requirements: Mapped[str | None] = mapped_column(String(2000))
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Candidate(Base):
    __tablename__ = "candidates"
    __table_args__ = _HR

    candidate_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    first_name: Mapped[str] = mapped_column(String(100))
    last_name: Mapped[str] = mapped_column(String(100))
    national_id: Mapped[str | None] = mapped_column(String(20))
    mobile: Mapped[str | None] = mapped_column(String(30))
    email: Mapped[str | None] = mapped_column(String(150))
    education: Mapped[str | None] = mapped_column(String(200))
    experience_years: Mapped[decimal.Decimal | None] = mapped_column(Numeric(4, 1))
    source_code: Mapped[str] = mapped_column(String(20), default="OTHER")
    notes: Mapped[str | None] = mapped_column(String(1000))
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=_now)


class JobApplication(Base):
    __tablename__ = "job_applications"
    __table_args__ = _HR

    application_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    opening_id: Mapped[int] = mapped_column(ForeignKey("hr.job_openings.opening_id"))
    candidate_id: Mapped[int] = mapped_column(ForeignKey("hr.candidates.candidate_id"))
    stage_code: Mapped[str] = mapped_column(String(20), default="APPLIED")
    applied_on: Mapped[datetime.date] = mapped_column(Date)
    offer_salary: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 2))
    offer_start_date: Mapped[datetime.date | None] = mapped_column(Date)
    decision_note: Mapped[str | None] = mapped_column(String(500))
    employee_id: Mapped[int | None] = mapped_column(ForeignKey("hr.employees.employee_id"))
    hired_on: Mapped[datetime.date | None] = mapped_column(Date)


class ApplicationEvent(Base):
    __tablename__ = "application_events"
    __table_args__ = _HR

    event_id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("hr.job_applications.application_id", ondelete="CASCADE"))
    from_stage: Mapped[str | None] = mapped_column(String(20))
    to_stage: Mapped[str] = mapped_column(String(20))
    note: Mapped[str | None] = mapped_column(String(500))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Interview(Base):
    __tablename__ = "interviews"
    __table_args__ = _HR

    interview_id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("hr.job_applications.application_id", ondelete="CASCADE"))
    scheduled_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True))
    interviewer_employee_id: Mapped[int | None] = mapped_column(ForeignKey("hr.employees.employee_id", ondelete="SET NULL"))
    mode_code: Mapped[str] = mapped_column(String(20), default="IN_PERSON")
    status_code: Mapped[str] = mapped_column(String(20), default="SCHEDULED")
    score: Mapped[int | None] = mapped_column(SmallInteger)
    recommendation_code: Mapped[str | None] = mapped_column(String(20))
    notes: Mapped[str | None] = mapped_column(String(1000))
