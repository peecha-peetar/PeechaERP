"""مدل‌های هستهٔ منابع انسانی (hr.*).

معادل db/schema/043_hr_core.sql
"""

from __future__ import annotations

import datetime
import decimal

from typing import Any

from sqlalchemy import Boolean, Date, ForeignKey, Numeric, SmallInteger, String, Time, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from peecha.db.base import Base


class LookupType(Base):
    __tablename__ = "lookup_types"
    __table_args__ = {"schema": "hr"}

    lookup_type_id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)


class LookupValue(Base):
    __tablename__ = "lookup_values"
    __table_args__ = {"schema": "hr"}

    lookup_value_id: Mapped[int] = mapped_column(primary_key=True)
    lookup_type_id: Mapped[int] = mapped_column(ForeignKey("hr.lookup_types.lookup_type_id"))
    company_id: Mapped[int | None] = mapped_column(ForeignKey("core.companies.company_id"))
    code: Mapped[str] = mapped_column(String(50))
    name: Mapped[str] = mapped_column(String(200))
    display_order: Mapped[int] = mapped_column(SmallInteger, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class OrganizationalUnit(Base):
    __tablename__ = "organizational_units"
    __table_args__ = {"schema": "hr"}

    org_unit_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    code: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(200))
    parent_org_unit_id: Mapped[int | None] = mapped_column(ForeignKey("hr.organizational_units.org_unit_id"))
    cost_center_detail_account_id: Mapped[int | None] = mapped_column(ForeignKey("acc.detail_accounts.detail_account_id"))
    manager_employee_id: Mapped[int | None] = mapped_column(ForeignKey("hr.employees.employee_id"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    parent: Mapped[OrganizationalUnit | None] = relationship(remote_side="OrganizationalUnit.org_unit_id")


class JobGrade(Base):
    __tablename__ = "job_grades"
    __table_args__ = {"schema": "hr"}

    job_grade_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    code: Mapped[str] = mapped_column(String(30))
    title: Mapped[str] = mapped_column(String(200))
    grade_level: Mapped[int] = mapped_column(SmallInteger, default=0)
    min_base_salary: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 2))
    max_base_salary: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 2))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Position(Base):
    __tablename__ = "positions"
    __table_args__ = {"schema": "hr"}

    position_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    code: Mapped[str] = mapped_column(String(30))
    title: Mapped[str] = mapped_column(String(200))
    org_unit_id: Mapped[int] = mapped_column(ForeignKey("hr.organizational_units.org_unit_id"))
    job_grade_id: Mapped[int | None] = mapped_column(ForeignKey("hr.job_grades.job_grade_id"))
    capacity: Mapped[int] = mapped_column(SmallInteger, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Employee(Base):
    __tablename__ = "employees"
    __table_args__ = {"schema": "hr"}

    employee_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    personnel_detail_account_id: Mapped[int] = mapped_column(ForeignKey("acc.detail_accounts.detail_account_id"), unique=True)
    employee_code: Mapped[str] = mapped_column(String(30))
    first_name: Mapped[str] = mapped_column(String(100))
    last_name: Mapped[str] = mapped_column(String(100))
    national_id: Mapped[str | None] = mapped_column(String(20))
    date_of_birth: Mapped[datetime.date | None] = mapped_column(Date)
    gender_lookup_id: Mapped[int | None] = mapped_column(ForeignKey("hr.lookup_values.lookup_value_id"))
    marital_status_lookup_id: Mapped[int | None] = mapped_column(ForeignKey("hr.lookup_values.lookup_value_id"))
    education_degree_lookup_id: Mapped[int | None] = mapped_column(ForeignKey("hr.lookup_values.lookup_value_id"))
    military_service_lookup_id: Mapped[int | None] = mapped_column(ForeignKey("hr.lookup_values.lookup_value_id"))
    social_security_no: Mapped[str | None] = mapped_column(String(30))
    bank_account_no: Mapped[str | None] = mapped_column(String(40))
    bank_iban: Mapped[str | None] = mapped_column(String(34))
    phone: Mapped[str | None] = mapped_column(String(30))
    mobile: Mapped[str | None] = mapped_column(String(30))
    address: Mapped[str | None] = mapped_column(String(400))
    hire_date: Mapped[datetime.date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")
    notes: Mapped[str | None] = mapped_column(String(1000))


class EmploymentContract(Base):
    __tablename__ = "employment_contracts"
    __table_args__ = {"schema": "hr"}

    contract_id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("hr.employees.employee_id"))
    employment_type_lookup_id: Mapped[int | None] = mapped_column(ForeignKey("hr.lookup_values.lookup_value_id"))
    org_unit_id: Mapped[int] = mapped_column(ForeignKey("hr.organizational_units.org_unit_id"))
    position_id: Mapped[int] = mapped_column(ForeignKey("hr.positions.position_id"))
    start_date: Mapped[datetime.date] = mapped_column(Date)
    end_date: Mapped[datetime.date | None] = mapped_column(Date)
    base_salary: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2))
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")
    end_reason_lookup_id: Mapped[int | None] = mapped_column(ForeignKey("hr.lookup_values.lookup_value_id"))


class Termination(Base):
    __tablename__ = "terminations"
    __table_args__ = {"schema": "hr"}

    termination_id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("hr.employees.employee_id"))
    contract_id: Mapped[int] = mapped_column(ForeignKey("hr.employment_contracts.contract_id"))
    termination_date: Mapped[datetime.date] = mapped_column(Date)
    termination_type_lookup_id: Mapped[int | None] = mapped_column(ForeignKey("hr.lookup_values.lookup_value_id"))
    reason: Mapped[str | None] = mapped_column(String(1000))
    settlement_status: Mapped[str] = mapped_column(String(20), default="PENDING")
    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())


class AttendanceRecord(Base):
    __tablename__ = "attendance_records"
    __table_args__ = {"schema": "hr"}

    attendance_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    employee_id: Mapped[int] = mapped_column(ForeignKey("hr.employees.employee_id"))
    work_date: Mapped[datetime.date] = mapped_column(Date)
    clock_in: Mapped[datetime.time | None] = mapped_column(Time)
    clock_out: Mapped[datetime.time | None] = mapped_column(Time)
    worked_hours: Mapped[decimal.Decimal | None] = mapped_column(Numeric(6, 2))
    status: Mapped[str] = mapped_column(String(20), default="PENDING_APPROVAL")
    source: Mapped[str] = mapped_column(String(20), default="MANUAL")
    notes: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())


class AttendanceImportTemplate(Base):
    __tablename__ = "attendance_import_templates"
    __table_args__ = {"schema": "hr"}

    template_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    name: Mapped[str] = mapped_column(String(150))
    has_header_row: Mapped[bool] = mapped_column(Boolean, default=True)
    date_format: Mapped[str] = mapped_column(String(30), default="%Y-%m-%d")
    time_format: Mapped[str] = mapped_column(String(30), default="%H:%M")
    column_mapping: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
