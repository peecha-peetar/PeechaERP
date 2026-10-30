"""R367: جذب و استخدام؛ R368: ارزیابی عملکرد؛ R369: آموزش — روی پرونده‌های پرسنلی hr."""

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


# --- R368: ارزیابی عملکرد ---------------------------------------------------------------------------------------------
class AppraisalTemplate(Base):
    __tablename__ = "appraisal_templates"
    __table_args__ = _HR

    template_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    code: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(default=True)


class AppraisalCriterion(Base):
    __tablename__ = "appraisal_criteria"
    __table_args__ = _HR

    criterion_id: Mapped[int] = mapped_column(primary_key=True)
    template_id: Mapped[int] = mapped_column(ForeignKey("hr.appraisal_templates.template_id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(String(500))
    weight: Mapped[decimal.Decimal] = mapped_column(Numeric(5, 2))
    sort_order: Mapped[int] = mapped_column(default=0)


class AppraisalCycle(Base):
    __tablename__ = "appraisal_cycles"
    __table_args__ = _HR

    cycle_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    title: Mapped[str] = mapped_column(String(200))
    template_id: Mapped[int] = mapped_column(ForeignKey("hr.appraisal_templates.template_id"))
    period_from: Mapped[datetime.date] = mapped_column(Date)
    period_to: Mapped[datetime.date] = mapped_column(Date)
    self_assessment: Mapped[bool] = mapped_column(default=True)
    status_code: Mapped[str] = mapped_column(String(20), default="DRAFT")


class Appraisal(Base):
    __tablename__ = "appraisals"
    __table_args__ = _HR

    appraisal_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    cycle_id: Mapped[int] = mapped_column(ForeignKey("hr.appraisal_cycles.cycle_id", ondelete="CASCADE"))
    employee_id: Mapped[int] = mapped_column(ForeignKey("hr.employees.employee_id"))
    reviewer_employee_id: Mapped[int | None] = mapped_column(ForeignKey("hr.employees.employee_id", ondelete="SET NULL"))
    status_code: Mapped[str] = mapped_column(String(20), default="PENDING_SELF")
    self_comment: Mapped[str | None] = mapped_column(String(1000))
    manager_comment: Mapped[str | None] = mapped_column(String(1000))
    strengths: Mapped[str | None] = mapped_column(String(1000))
    improvements: Mapped[str | None] = mapped_column(String(1000))
    goals: Mapped[str | None] = mapped_column(String(1000))
    overall_score: Mapped[decimal.Decimal | None] = mapped_column(Numeric(4, 2))
    finalized_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    finalized_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))


class AppraisalScore(Base):
    __tablename__ = "appraisal_scores"
    __table_args__ = _HR

    appraisal_id: Mapped[int] = mapped_column(ForeignKey("hr.appraisals.appraisal_id", ondelete="CASCADE"), primary_key=True)
    criterion_id: Mapped[int] = mapped_column(ForeignKey("hr.appraisal_criteria.criterion_id"), primary_key=True)
    self_score: Mapped[int | None] = mapped_column(SmallInteger)
    manager_score: Mapped[int | None] = mapped_column(SmallInteger)
    comment: Mapped[str | None] = mapped_column(String(500))


# --- R369: آموزش -------------------------------------------------------------------------------------------------------
class TrainingCourse(Base):
    __tablename__ = "training_courses"
    __table_args__ = _HR

    course_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    code: Mapped[str] = mapped_column(String(30))
    title: Mapped[str] = mapped_column(String(200))
    category_code: Mapped[str] = mapped_column(String(20), default="OTHER")
    hours: Mapped[decimal.Decimal] = mapped_column(Numeric(6, 1))
    validity_months: Mapped[int | None] = mapped_column()
    provider: Mapped[str | None] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(default=True)


class PositionTraining(Base):
    """دورهٔ الزامی هر پست سازمانی."""

    __tablename__ = "position_trainings"
    __table_args__ = _HR

    position_id: Mapped[int] = mapped_column(ForeignKey("hr.positions.position_id", ondelete="CASCADE"), primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("hr.training_courses.course_id", ondelete="CASCADE"), primary_key=True)


class TrainingSession(Base):
    __tablename__ = "training_sessions"
    __table_args__ = _HR

    session_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    course_id: Mapped[int] = mapped_column(ForeignKey("hr.training_courses.course_id"))
    start_date: Mapped[datetime.date] = mapped_column(Date)
    end_date: Mapped[datetime.date] = mapped_column(Date)
    trainer: Mapped[str | None] = mapped_column(String(200))
    location: Mapped[str | None] = mapped_column(String(200))
    capacity: Mapped[int | None] = mapped_column()
    cost: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=0)
    status_code: Mapped[str] = mapped_column(String(20), default="PLANNED")


class TrainingEnrollment(Base):
    __tablename__ = "training_enrollments"
    __table_args__ = _HR

    enrollment_id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("hr.training_sessions.session_id", ondelete="CASCADE"))
    employee_id: Mapped[int] = mapped_column(ForeignKey("hr.employees.employee_id"))
    status_code: Mapped[str] = mapped_column(String(20), default="ENROLLED")
    score: Mapped[decimal.Decimal | None] = mapped_column(Numeric(5, 2))
    certificate_no: Mapped[str | None] = mapped_column(String(50))
    completed_on: Mapped[datetime.date | None] = mapped_column(Date)
    expires_on: Mapped[datetime.date | None] = mapped_column(Date)
