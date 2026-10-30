"""R311 — سیستم مدیریت کیفیت: طرح کیفیت نسخه‌دار، نتایج پارامترها، عدم‌انطباق، اقدام اصلاحی/پیشگیرانه و تنظیمات.

خود رکورد بازرسی همان inv.qc_inspections (مدل QcInspection در inventory.py) است.
"""

from __future__ import annotations

import datetime
import decimal
from typing import Any

from sqlalchemy import BigInteger, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from peecha.db.base import Base

_QMS = {"schema": "qms"}


class InspectionPlan(Base):
    __tablename__ = "inspection_plans"
    __table_args__ = _QMS

    plan_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    code: Mapped[str] = mapped_column(String(30))
    version_no: Mapped[int] = mapped_column(default=1)
    name: Mapped[str] = mapped_column(String(150))
    stage_code: Mapped[str] = mapped_column(String(20))
    item_id: Mapped[int | None] = mapped_column(ForeignKey("inv.items.item_id"))
    category_id: Mapped[int | None] = mapped_column(ForeignKey("inv.item_categories.category_id"))
    supplier_detail_account_id: Mapped[int | None] = mapped_column(ForeignKey("acc.detail_accounts.detail_account_id"))
    work_center_id: Mapped[int | None] = mapped_column(ForeignKey("prd.work_centers.work_center_id"))
    operation_id: Mapped[int | None] = mapped_column(ForeignKey("prd.operations.operation_id"))
    document_type_code: Mapped[str | None] = mapped_column(String(20))
    sampling_method: Mapped[str] = mapped_column(String(10), default="FULL")
    sample_size: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 6))
    sample_percent: Mapped[decimal.Decimal | None] = mapped_column(Numeric(7, 3))
    acceptance_number: Mapped[int] = mapped_column(default=0)
    is_mandatory: Mapped[bool] = mapped_column(default=True)
    valid_from: Mapped[datetime.date | None]
    valid_to: Mapped[datetime.date | None]
    status_code: Mapped[str] = mapped_column(String(12), default="DRAFT")
    previous_plan_id: Mapped[int | None] = mapped_column(ForeignKey("qms.inspection_plans.plan_id"))
    notes: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("sec.users.user_id"))
    created_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")
    activated_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    activated_at: Mapped[datetime.datetime | None]


class PlanParameter(Base):
    __tablename__ = "plan_parameters"
    __table_args__ = _QMS

    parameter_id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("qms.inspection_plans.plan_id", ondelete="CASCADE"))
    seq: Mapped[int]
    name: Mapped[str] = mapped_column(String(150))
    data_type: Mapped[str] = mapped_column(String(10))
    uom_label: Mapped[str | None] = mapped_column(String(30))
    min_value: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 6))
    max_value: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 6))
    target_value: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 6))
    options: Mapped[list[Any] | None] = mapped_column(JSONB)
    test_method: Mapped[str | None] = mapped_column(String(300))
    is_mandatory: Mapped[bool] = mapped_column(default=True)


class InspectionResult(Base):
    __tablename__ = "inspection_results"
    __table_args__ = _QMS

    result_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    qc_inspection_id: Mapped[int] = mapped_column(ForeignKey("inv.qc_inspections.qc_inspection_id", ondelete="CASCADE"))
    parameter_id: Mapped[int | None] = mapped_column(ForeignKey("qms.plan_parameters.parameter_id"))
    sample_no: Mapped[int] = mapped_column(default=1)
    parameter_name: Mapped[str] = mapped_column(String(150))
    data_type: Mapped[str] = mapped_column(String(10))
    uom_label: Mapped[str | None] = mapped_column(String(30))
    min_value: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 6))
    max_value: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 6))
    target_value: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 6))
    options: Mapped[list[Any] | None] = mapped_column(JSONB)
    is_mandatory: Mapped[bool] = mapped_column(default=True)
    value_numeric: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 6))
    value_text: Mapped[str | None] = mapped_column(String(500))
    value_bool: Mapped[bool | None]
    is_conforming: Mapped[bool | None]
    recorded_by_user_id: Mapped[int] = mapped_column(ForeignKey("sec.users.user_id"))
    recorded_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")


class Nonconformance(Base):
    __tablename__ = "nonconformances"
    __table_args__ = _QMS

    ncr_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    ncr_no: Mapped[int]
    source_code: Mapped[str] = mapped_column(String(20))
    qc_inspection_id: Mapped[int | None] = mapped_column(ForeignKey("inv.qc_inspections.qc_inspection_id"))
    item_id: Mapped[int | None] = mapped_column(ForeignKey("inv.items.item_id"))
    supplier_detail_account_id: Mapped[int | None] = mapped_column(ForeignKey("acc.detail_accounts.detail_account_id"))
    customer_detail_account_id: Mapped[int | None] = mapped_column(ForeignKey("acc.detail_accounts.detail_account_id"))
    production_order_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("prd.production_orders.order_id"))
    stock_document_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("inv.stock_documents.stock_document_id"))
    quantity: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 6), default=0)
    severity_code: Mapped[str] = mapped_column(String(10), default="MINOR")
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    cause_code: Mapped[str | None] = mapped_column(String(20))
    root_cause_method: Mapped[str | None] = mapped_column(String(12))
    root_cause_details: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    root_cause: Mapped[str | None] = mapped_column(Text)
    responsible_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    cost_amount: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=0)
    disposition_code: Mapped[str | None] = mapped_column(String(20))
    status_code: Mapped[str] = mapped_column(String(15), default="OPEN")
    detected_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")
    due_date: Mapped[datetime.date | None]
    closed_at: Mapped[datetime.datetime | None]
    closed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("sec.users.user_id"))
    created_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")


class CapaAction(Base):
    __tablename__ = "capa_actions"
    __table_args__ = _QMS

    action_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    ncr_id: Mapped[int] = mapped_column(ForeignKey("qms.nonconformances.ncr_id"))
    action_type: Mapped[str] = mapped_column(String(12))
    description: Mapped[str] = mapped_column(Text)
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    due_date: Mapped[datetime.date | None]
    status_code: Mapped[str] = mapped_column(String(12), default="OPEN")
    evidence: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime.datetime | None]
    completed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    verified_at: Mapped[datetime.datetime | None]
    verified_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    effectiveness_note: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("sec.users.user_id"))
    created_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")


class QmsSettings(Base):
    __tablename__ = "settings"
    __table_args__ = _QMS

    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"), primary_key=True)
    score_window_days: Mapped[int] = mapped_column(default=365)
    score_min_samples: Mapped[int] = mapped_column(default=3)
    weight_reject: Mapped[decimal.Decimal] = mapped_column(Numeric(6, 2), default=40)
    weight_return: Mapped[decimal.Decimal] = mapped_column(Numeric(6, 2), default=25)
    weight_ncr: Mapped[decimal.Decimal] = mapped_column(Numeric(6, 2), default=20)
    weight_delay: Mapped[decimal.Decimal] = mapped_column(Numeric(6, 2), default=15)
    weight_trend: Mapped[decimal.Decimal] = mapped_column(Numeric(6, 2), default=0)
    target_handling_days: Mapped[decimal.Decimal] = mapped_column(Numeric(6, 2), default=2)
    auto_ncr_on_reject: Mapped[bool] = mapped_column(default=True)
    updated_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    updated_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")


class Certificate(Base):
    """R362: گواهی آنالیز؛ snapshot نتایج و مشخصات هنگام صدور است و با تغییر بعدی بازرسی عوض نمی‌شود."""

    __tablename__ = "certificates"
    __table_args__ = _QMS

    certificate_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    certificate_no: Mapped[int]
    qc_inspection_id: Mapped[int] = mapped_column(ForeignKey("inv.qc_inspections.qc_inspection_id"))
    item_id: Mapped[int] = mapped_column(ForeignKey("inv.items.item_id"))
    batch_no: Mapped[str | None] = mapped_column(String(50))
    customer_detail_account_id: Mapped[int | None] = mapped_column(ForeignKey("acc.detail_accounts.detail_account_id"))
    sales_document_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("comm.commercial_documents.document_id"))
    issue_date: Mapped[datetime.date]
    status_code: Mapped[str] = mapped_column(String(10), default="ISSUED")
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)
    notes: Mapped[str | None] = mapped_column(String(500))
    issued_by_user_id: Mapped[int] = mapped_column(ForeignKey("sec.users.user_id"))
    issued_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")
    revoked_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    revoked_at: Mapped[datetime.datetime | None]
    revoke_reason: Mapped[str | None] = mapped_column(String(500))
