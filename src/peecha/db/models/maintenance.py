"""مدل‌های نگهداری و تعمیرات (schema mnt) — R312. معادل db/schema/222_maintenance.sql.

تجهیز همان دارایی ثابت (fa.assets) است؛ این‌جا فقط دادهٔ نگهداری.
"""

from __future__ import annotations

import datetime
import decimal
from typing import Any

from sqlalchemy import BigInteger, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from peecha.db.base import Base

_MNT = {"schema": "mnt"}


class EquipmentProfile(Base):
    __tablename__ = "equipment_profiles"
    __table_args__ = _MNT

    profile_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    asset_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("fa.assets.asset_id"), unique=True)
    criticality_code: Mapped[str] = mapped_column(String(10), default="MEDIUM")
    technical_specs: Mapped[list[Any] | None] = mapped_column(JSONB)
    meter_unit: Mapped[str | None] = mapped_column(String(30))
    responsible_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    default_technician_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    service_supplier_detail_account_id: Mapped[int | None] = mapped_column(ForeignKey("acc.detail_accounts.detail_account_id"))
    safety_notes: Mapped[str | None] = mapped_column(String(1000))
    notes: Mapped[str | None] = mapped_column(String(1000))
    updated_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    updated_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")


class FailureCode(Base):
    __tablename__ = "failure_codes"
    __table_args__ = _MNT

    failure_code_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    kind_code: Mapped[str] = mapped_column(String(10))
    code: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(150))
    is_active: Mapped[bool] = mapped_column(default=True)


class WorkRequest(Base):
    __tablename__ = "work_requests"
    __table_args__ = _MNT

    request_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    request_no: Mapped[int]
    asset_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("fa.assets.asset_id"))
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(String(2000))
    failure_at: Mapped[datetime.datetime | None]
    reported_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")
    reported_by_user_id: Mapped[int] = mapped_column(ForeignKey("sec.users.user_id"))
    machine_stopped: Mapped[bool] = mapped_column(default=False)
    severity_code: Mapped[str] = mapped_column(String(10), default="MEDIUM")
    probable_cause: Mapped[str | None] = mapped_column(String(500))
    suggested_work_type: Mapped[str | None] = mapped_column(String(15))
    priority_code: Mapped[str | None] = mapped_column(String(10))
    status_code: Mapped[str] = mapped_column(String(15), default="NEW")
    evaluated_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    evaluated_at: Mapped[datetime.datetime | None]
    approved_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    approved_at: Mapped[datetime.datetime | None]
    decision_note: Mapped[str | None] = mapped_column(String(500))
    assigned_to_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    source_code: Mapped[str] = mapped_column(String(10), default="DESKTOP")
    idempotency_key: Mapped[str | None] = mapped_column(String(80))


class PmPlan(Base):
    __tablename__ = "pm_plans"
    __table_args__ = _MNT

    plan_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    code: Mapped[str] = mapped_column(String(30))
    asset_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("fa.assets.asset_id"))
    title: Mapped[str] = mapped_column(String(200))
    work_type_code: Mapped[str] = mapped_column(String(15), default="PREVENTIVE")
    trigger_code: Mapped[str] = mapped_column(String(10), default="CALENDAR")
    interval_days: Mapped[int | None]
    meter_interval: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 4))
    lead_days: Mapped[int] = mapped_column(default=0)
    start_date: Mapped[datetime.date]
    next_due_date: Mapped[datetime.date | None]
    last_completed_date: Mapped[datetime.date | None]
    meter_at_last: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 4), default=0)
    estimated_hours: Mapped[decimal.Decimal | None] = mapped_column(Numeric(10, 2))
    safety_instructions: Mapped[str | None] = mapped_column(String(2000))
    required_skills: Mapped[str | None] = mapped_column(String(500))
    requires_shutdown: Mapped[bool] = mapped_column(default=False)
    responsible_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    is_active: Mapped[bool] = mapped_column(default=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    created_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")


class PmPlanTask(Base):
    __tablename__ = "pm_plan_tasks"
    __table_args__ = _MNT

    plan_task_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    plan_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("mnt.pm_plans.plan_id", ondelete="CASCADE"))
    seq: Mapped[int]
    description: Mapped[str] = mapped_column(String(500))
    result_type: Mapped[str] = mapped_column(String(10), default="CHECK")
    min_value: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 4))
    max_value: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 4))
    uom_label: Mapped[str | None] = mapped_column(String(30))
    is_mandatory: Mapped[bool] = mapped_column(default=True)
    is_safety: Mapped[bool] = mapped_column(default=False)


class PmPlanPart(Base):
    __tablename__ = "pm_plan_parts"
    __table_args__ = _MNT

    plan_part_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    plan_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("mnt.pm_plans.plan_id", ondelete="CASCADE"))
    item_id: Mapped[int] = mapped_column(ForeignKey("inv.items.item_id"))
    warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("inv.warehouses.warehouse_id"))
    quantity: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 6))


class WorkOrder(Base):
    __tablename__ = "work_orders"
    __table_args__ = _MNT

    work_order_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    wo_no: Mapped[int]
    asset_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("fa.assets.asset_id"))
    request_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("mnt.work_requests.request_id"))
    pm_plan_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("mnt.pm_plans.plan_id"))
    pm_due_date: Mapped[datetime.date | None]
    work_type_code: Mapped[str] = mapped_column(String(15))
    priority_code: Mapped[str] = mapped_column(String(10), default="NORMAL")
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(String(2000))
    status_code: Mapped[str] = mapped_column(String(15), default="OPEN")
    hold_reason: Mapped[str | None] = mapped_column(String(500))
    responsible_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    planned_start: Mapped[datetime.datetime | None]
    planned_end: Mapped[datetime.datetime | None]
    estimated_hours: Mapped[decimal.Decimal | None] = mapped_column(Numeric(10, 2))
    actual_start: Mapped[datetime.datetime | None]
    actual_end: Mapped[datetime.datetime | None]
    requires_shutdown: Mapped[bool] = mapped_column(default=False)
    safety_instructions: Mapped[str | None] = mapped_column(String(2000))
    required_skills: Mapped[str | None] = mapped_column(String(500))
    problem_code_id: Mapped[int | None] = mapped_column(ForeignKey("mnt.failure_codes.failure_code_id"))
    cause_code_id: Mapped[int | None] = mapped_column(ForeignKey("mnt.failure_codes.failure_code_id"))
    remedy_code_id: Mapped[int | None] = mapped_column(ForeignKey("mnt.failure_codes.failure_code_id"))
    root_cause_note: Mapped[str | None] = mapped_column(String(1000))
    completion_note: Mapped[str | None] = mapped_column(String(1000))
    completed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    completed_at: Mapped[datetime.datetime | None]
    verification_result: Mapped[str | None] = mapped_column(String(5))
    verification_note: Mapped[str | None] = mapped_column(String(1000))
    verified_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    verified_at: Mapped[datetime.datetime | None]
    closed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    closed_at: Mapped[datetime.datetime | None]
    reopened_count: Mapped[int] = mapped_column(default=0)
    capital_candidate: Mapped[bool] = mapped_column(default=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(80))
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    created_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")


class WorkOrderTechnician(Base):
    __tablename__ = "work_order_technicians"
    __table_args__ = _MNT

    work_order_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("mnt.work_orders.work_order_id", ondelete="CASCADE"),
                                               primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("sec.users.user_id"), primary_key=True)
    is_lead: Mapped[bool] = mapped_column(default=False)
    assigned_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    assigned_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")


class WorkOrderTask(Base):
    __tablename__ = "work_order_tasks"
    __table_args__ = _MNT

    task_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    work_order_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("mnt.work_orders.work_order_id", ondelete="CASCADE"))
    seq: Mapped[int]
    description: Mapped[str] = mapped_column(String(500))
    result_type: Mapped[str] = mapped_column(String(10), default="CHECK")
    min_value: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 4))
    max_value: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 4))
    uom_label: Mapped[str | None] = mapped_column(String(30))
    is_mandatory: Mapped[bool] = mapped_column(default=True)
    is_safety: Mapped[bool] = mapped_column(default=False)
    is_done: Mapped[bool] = mapped_column(default=False)
    value_numeric: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 4))
    value_text: Mapped[str | None] = mapped_column(String(500))
    is_ok: Mapped[bool | None]
    done_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    done_at: Mapped[datetime.datetime | None]


class WorkOrderLabor(Base):
    __tablename__ = "work_order_labor"
    __table_args__ = _MNT

    labor_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    work_order_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("mnt.work_orders.work_order_id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("sec.users.user_id"))
    employee_id: Mapped[int | None] = mapped_column(ForeignKey("hr.employees.employee_id"))
    work_date: Mapped[datetime.date]
    hours: Mapped[decimal.Decimal] = mapped_column(Numeric(10, 2))
    hourly_rate: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=0)
    amount: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=0)
    note: Mapped[str | None] = mapped_column(String(300))
    idempotency_key: Mapped[str | None] = mapped_column(String(80))
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    created_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")


class WorkOrderPart(Base):
    __tablename__ = "work_order_parts"
    __table_args__ = _MNT

    part_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    work_order_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("mnt.work_orders.work_order_id"))
    item_id: Mapped[int] = mapped_column(ForeignKey("inv.items.item_id"))
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("inv.warehouses.warehouse_id"))
    planned_qty: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 6))
    issued_qty: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 6), default=0)
    returned_qty: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 6), default=0)
    issued_amount: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=0)
    returned_amount: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=0)
    purchase_request_id: Mapped[int | None] = mapped_column(BigInteger)
    purchase_request_line_id: Mapped[int | None] = mapped_column(BigInteger)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))


class WorkOrderPartMove(Base):
    __tablename__ = "work_order_part_moves"
    __table_args__ = _MNT

    move_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    part_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("mnt.work_order_parts.part_id"))
    direction_code: Mapped[str] = mapped_column(String(6))
    quantity: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 6))
    amount: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=0)
    stock_document_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("inv.stock_documents.stock_document_id"))
    idempotency_key: Mapped[str | None] = mapped_column(String(80))
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    created_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")


class WorkOrderCost(Base):
    __tablename__ = "work_order_costs"
    __table_args__ = _MNT

    cost_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    work_order_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("mnt.work_orders.work_order_id"))
    cost_type_code: Mapped[str] = mapped_column(String(10))
    description: Mapped[str] = mapped_column(String(300))
    supplier_detail_account_id: Mapped[int | None] = mapped_column(ForeignKey("acc.detail_accounts.detail_account_id"))
    amount: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2))
    accounting_code: Mapped[str] = mapped_column(String(12), default="PENDING")
    commercial_document_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("comm.commercial_documents.document_id"))
    asset_event_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("fa.asset_events.event_id"))
    status_code: Mapped[str] = mapped_column(String(12), default="DRAFT")
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    created_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")
    posted_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    posted_at: Mapped[datetime.datetime | None]


class DowntimeEvent(Base):
    __tablename__ = "downtime_events"
    __table_args__ = _MNT

    downtime_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    asset_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("fa.assets.asset_id"))
    downtime_type_code: Mapped[str] = mapped_column(String(10), default="BREAKDOWN")
    down_from: Mapped[datetime.datetime]
    reported_at: Mapped[datetime.datetime | None]
    available_at: Mapped[datetime.datetime | None]
    request_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("mnt.work_requests.request_id"))
    work_order_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("mnt.work_orders.work_order_id"))
    previous_asset_status: Mapped[str | None] = mapped_column(String(20))
    note: Mapped[str | None] = mapped_column(String(500))
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    released_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))


class PlannedDowntime(Base):
    __tablename__ = "planned_downtime"
    __table_args__ = _MNT

    window_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    asset_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("fa.assets.asset_id"))
    work_order_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("mnt.work_orders.work_order_id"))
    start_at: Mapped[datetime.datetime]
    end_at: Mapped[datetime.datetime]
    status_code: Mapped[str] = mapped_column(String(10), default="PROPOSED")
    reason: Mapped[str | None] = mapped_column(String(300))
    requested_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    approved_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    approved_at: Mapped[datetime.datetime | None]


class CapacityRestriction(Base):
    __tablename__ = "capacity_restrictions"
    __table_args__ = _MNT

    restriction_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    asset_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("fa.assets.asset_id"))
    capacity_percent: Mapped[decimal.Decimal] = mapped_column(Numeric(5, 2))
    start_date: Mapped[datetime.date]
    end_date: Mapped[datetime.date | None]
    status_code: Mapped[str] = mapped_column(String(10), default="PROPOSED")
    reason: Mapped[str] = mapped_column(String(300))
    work_order_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("mnt.work_orders.work_order_id"))
    requested_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    approved_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    approved_at: Mapped[datetime.datetime | None]


class PmPostponement(Base):
    __tablename__ = "pm_postponements"
    __table_args__ = _MNT

    postponement_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    plan_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("mnt.pm_plans.plan_id"))
    work_order_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("mnt.work_orders.work_order_id"))
    old_due_date: Mapped[datetime.date]
    new_due_date: Mapped[datetime.date]
    reason: Mapped[str] = mapped_column(String(300))
    status_code: Mapped[str] = mapped_column(String(10), default="PENDING")
    requested_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    decided_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    decided_at: Mapped[datetime.datetime | None]


class CalibrationInstrument(Base):
    """R382: ابزار اندازه‌گیری با دورهٔ کالیبراسیون."""

    __tablename__ = "calibration_instruments"
    __table_args__ = {"schema": "mnt"}

    instrument_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    code: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(200))
    asset_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("fa.assets.asset_id"))
    serial_no: Mapped[str | None] = mapped_column(String(100))
    location_text: Mapped[str | None] = mapped_column(String(200))
    measure_range: Mapped[str | None] = mapped_column(String(100))
    tolerance: Mapped[str | None] = mapped_column(String(100))
    interval_days: Mapped[int]
    lead_days: Mapped[int] = mapped_column(default=14)
    method_code: Mapped[str] = mapped_column(String(10), default="EXTERNAL")
    lab_detail_account_id: Mapped[int | None] = mapped_column(ForeignKey("acc.detail_accounts.detail_account_id"))
    responsible_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    status_code: Mapped[str] = mapped_column(String(15), default="ACTIVE")
    next_due_date: Mapped[datetime.date]
    last_calibrated_on: Mapped[datetime.date | None]
    notes: Mapped[str | None] = mapped_column(String(1000))
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    created_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")


class CalibrationRecord(Base):
    """R382: نتیجهٔ یک کالیبراسیون."""

    __tablename__ = "calibration_records"
    __table_args__ = {"schema": "mnt"}

    record_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    instrument_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("mnt.calibration_instruments.instrument_id", ondelete="CASCADE"))
    record_no: Mapped[int]
    calibrated_on: Mapped[datetime.date]
    result_code: Mapped[str] = mapped_column(String(10))
    performed_by: Mapped[str | None] = mapped_column(String(200))
    certificate_no: Mapped[str | None] = mapped_column(String(100))
    as_found: Mapped[str | None] = mapped_column(String(500))
    as_left: Mapped[str | None] = mapped_column(String(500))
    cost_amount: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=0)
    next_due_date: Mapped[datetime.date | None]
    ncr_id: Mapped[int | None] = mapped_column(ForeignKey("qms.nonconformances.ncr_id", ondelete="SET NULL"))
    notes: Mapped[str | None] = mapped_column(String(1000))
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    created_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")
