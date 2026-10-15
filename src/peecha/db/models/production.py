"""مدل‌های ماژول تولید (schema prd) — R266 به بعد. معادل db/schema/198..201_production_*.sql.

فهرست مواد همان inv.bom_headers / inv.bom_lines است (مدل در inventory.py)؛ این‌جا فقط جدول‌های تازه.
"""

from __future__ import annotations

import datetime
import decimal
from typing import Any

from sqlalchemy import BigInteger, ForeignKey, Numeric, SmallInteger, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from peecha.db.base import Base

_PRD = {"schema": "prd"}


# --- فاز ۱: اطلاعاتِ پایه -------------------------------------------------------------
class ProductionSettings(Base):
    __tablename__ = "production_settings"
    __table_args__ = _PRD

    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"), primary_key=True)
    default_material_warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("inv.warehouses.warehouse_id"))
    default_production_warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("inv.warehouses.warehouse_id"))
    default_fg_warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("inv.warehouses.warehouse_id"))
    default_scrap_warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("inv.warehouses.warehouse_id"))
    default_cost_center_detail_account_id: Mapped[int | None] = mapped_column(ForeignKey("acc.detail_accounts.detail_account_id"))
    auto_reservation: Mapped[bool] = mapped_column(default=True)
    auto_consumption: Mapped[bool] = mapped_column(default=False)
    allow_over_consumption: Mapped[bool] = mapped_column(default=True)
    allow_under_consumption: Mapped[bool] = mapped_column(default=True)
    auto_cost_calculation: Mapped[bool] = mapped_column(default=True)
    require_cost_closing: Mapped[bool] = mapped_column(default=False)
    allow_negative_material: Mapped[bool] = mapped_column(default=False)
    shortage_policy: Mapped[str] = mapped_column(String(10), default="WARN")
    require_cost_center: Mapped[bool] = mapped_column(default=False)
    default_overhead_basis: Mapped[str] = mapped_column(String(20), default="LABOR_HOURS")
    default_joint_cost_method: Mapped[str] = mapped_column(String(20), default="QUANTITY")
    abnormal_scrap_percent: Mapped[decimal.Decimal] = mapped_column(Numeric(7, 4), default=decimal.Decimal(5))
    order_prefix: Mapped[str] = mapped_column(String(10), default="PO")
    updated_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")


class ItemProductionProfile(Base):
    __tablename__ = "item_production_profiles"
    __table_args__ = _PRD

    item_id: Mapped[int] = mapped_column(ForeignKey("inv.items.item_id"), primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    make_or_buy: Mapped[str] = mapped_column(String(4), default="MAKE")
    production_uom_id: Mapped[int | None] = mapped_column(ForeignKey("inv.uom.uom_id"))
    consumption_uom_id: Mapped[int | None] = mapped_column(ForeignKey("inv.uom.uom_id"))
    min_lot_qty: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 6))
    max_lot_qty: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 6))
    lot_multiple_qty: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 6))
    lead_time_days: Mapped[int] = mapped_column(default=0)
    standard_scrap_percent: Mapped[decimal.Decimal] = mapped_column(Numeric(7, 4), default=decimal.Decimal(0))
    weight_per_unit: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 6))
    backflush: Mapped[bool | None]


class WorkCenter(Base):
    __tablename__ = "work_centers"
    __table_args__ = _PRD

    work_center_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    code: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(150))
    center_type: Mapped[str] = mapped_column(String(15), default="LINE")
    branch_id: Mapped[int | None] = mapped_column(ForeignKey("comm.branches.branch_id"))
    warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("inv.warehouses.warehouse_id"))
    cost_center_detail_account_id: Mapped[int | None] = mapped_column(ForeignKey("acc.detail_accounts.detail_account_id"))
    operator_count: Mapped[int] = mapped_column(default=1)
    shifts_per_day: Mapped[int] = mapped_column(default=1)
    hours_per_shift: Mapped[decimal.Decimal] = mapped_column(Numeric(6, 2), default=decimal.Decimal(8))
    working_days_per_week: Mapped[int] = mapped_column(default=6)
    hourly_capacity_qty: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 6))
    efficiency_percent: Mapped[decimal.Decimal] = mapped_column(Numeric(7, 4), default=decimal.Decimal(100))
    labor_rate: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=decimal.Decimal(0))
    machine_rate: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=decimal.Decimal(0))
    overhead_rate: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=decimal.Decimal(0))
    is_active: Mapped[bool] = mapped_column(default=True)

    @property
    def daily_hours(self) -> decimal.Decimal:
        return decimal.Decimal(self.shifts_per_day) * decimal.Decimal(self.hours_per_shift)


class WorkCenterMachine(Base):
    __tablename__ = "work_center_machines"
    __table_args__ = _PRD

    work_center_id: Mapped[int] = mapped_column(ForeignKey("prd.work_centers.work_center_id"), primary_key=True)
    asset_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("fa.assets.asset_id"), primary_key=True)


class LaborRate(Base):
    __tablename__ = "labor_rates"
    __table_args__ = _PRD

    labor_rate_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    code: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(150))
    employee_id: Mapped[int | None] = mapped_column(ForeignKey("hr.employees.employee_id"))
    hourly_rate: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2))
    overtime_multiplier: Mapped[decimal.Decimal] = mapped_column(Numeric(6, 3), default=decimal.Decimal("1.4"))
    is_active: Mapped[bool] = mapped_column(default=True)


class Operation(Base):
    __tablename__ = "operations"
    __table_args__ = _PRD

    operation_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    code: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(150))
    default_work_center_id: Mapped[int | None] = mapped_column(ForeignKey("prd.work_centers.work_center_id"))
    default_setup_minutes: Mapped[decimal.Decimal] = mapped_column(Numeric(10, 2), default=decimal.Decimal(0))
    default_run_minutes: Mapped[decimal.Decimal] = mapped_column(Numeric(12, 4), default=decimal.Decimal(0))
    is_qc: Mapped[bool] = mapped_column(default=False)
    is_active: Mapped[bool] = mapped_column(default=True)


class Routing(Base):
    __tablename__ = "routings"
    __table_args__ = _PRD

    routing_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    item_id: Mapped[int] = mapped_column(ForeignKey("inv.items.item_id"))
    version_no: Mapped[int] = mapped_column(default=1)
    name: Mapped[str | None] = mapped_column(String(150))
    status_code: Mapped[str] = mapped_column(String(10), default="ACTIVE")
    is_default: Mapped[bool] = mapped_column(default=False)
    valid_from: Mapped[datetime.date | None]
    valid_to: Mapped[datetime.date | None]
    created_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")


class RoutingOperation(Base):
    __tablename__ = "routing_operations"
    __table_args__ = _PRD

    routing_operation_id: Mapped[int] = mapped_column(primary_key=True)
    routing_id: Mapped[int] = mapped_column(ForeignKey("prd.routings.routing_id"))
    seq: Mapped[int]
    operation_id: Mapped[int | None] = mapped_column(ForeignKey("prd.operations.operation_id"))
    name: Mapped[str] = mapped_column(String(150))
    work_center_id: Mapped[int | None] = mapped_column(ForeignKey("prd.work_centers.work_center_id"))
    asset_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("fa.assets.asset_id"))
    labor_count: Mapped[decimal.Decimal] = mapped_column(Numeric(6, 2), default=decimal.Decimal(1))
    setup_minutes: Mapped[decimal.Decimal] = mapped_column(Numeric(10, 2), default=decimal.Decimal(0))
    run_minutes: Mapped[decimal.Decimal] = mapped_column(Numeric(12, 4), default=decimal.Decimal(0))
    queue_minutes: Mapped[decimal.Decimal] = mapped_column(Numeric(10, 2), default=decimal.Decimal(0))
    move_minutes: Mapped[decimal.Decimal] = mapped_column(Numeric(10, 2), default=decimal.Decimal(0))
    machine_minutes: Mapped[decimal.Decimal | None] = mapped_column(Numeric(12, 4))
    labor_rate: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 2))
    machine_rate: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 2))
    overhead_rate: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 2))
    scrap_percent: Mapped[decimal.Decimal] = mapped_column(Numeric(7, 4), default=decimal.Decimal(0))
    is_qc: Mapped[bool] = mapped_column(default=False)
    description: Mapped[str | None] = mapped_column(String(500))


class BomOutput(Base):
    __tablename__ = "bom_outputs"
    __table_args__ = _PRD

    bom_output_id: Mapped[int] = mapped_column(primary_key=True)
    bom_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("inv.bom_headers.bom_id"))
    item_id: Mapped[int] = mapped_column(ForeignKey("inv.items.item_id"))
    output_type: Mapped[str] = mapped_column(String(12))
    quantity_per: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 6))
    recovery_value_per_unit: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 6))
    sales_value_per_unit: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 6))
    weight_per_unit: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 6))
    cost_share_percent: Mapped[decimal.Decimal | None] = mapped_column(Numeric(7, 4))



# --- فاز ۲: دستورِ تولید -----------------------------------------------------------------
class ProductionOrder(Base):
    __tablename__ = "production_orders"
    __table_args__ = _PRD

    order_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    order_no: Mapped[int]
    order_code: Mapped[str] = mapped_column(String(30))
    item_id: Mapped[int] = mapped_column(ForeignKey("inv.items.item_id"))
    bom_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("inv.bom_headers.bom_id"))
    routing_id: Mapped[int | None] = mapped_column(ForeignKey("prd.routings.routing_id"))
    parent_order_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("prd.production_orders.order_id"))
    planned_qty: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 6))
    produced_qty: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 6), default=decimal.Decimal(0))
    scrapped_qty: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 6), default=decimal.Decimal(0))
    uom_id: Mapped[int] = mapped_column(ForeignKey("inv.uom.uom_id"))
    start_date: Mapped[datetime.date]
    due_date: Mapped[datetime.date]
    actual_start_date: Mapped[datetime.date | None]
    actual_end_date: Mapped[datetime.date | None]
    material_warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("inv.warehouses.warehouse_id"))
    wip_warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("inv.warehouses.warehouse_id"))
    fg_warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("inv.warehouses.warehouse_id"))
    scrap_warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("inv.warehouses.warehouse_id"))
    branch_id: Mapped[int | None] = mapped_column(ForeignKey("comm.branches.branch_id"))
    cost_center_detail_account_id: Mapped[int | None] = mapped_column(ForeignKey("acc.detail_accounts.detail_account_id"))
    project_detail_account_id: Mapped[int | None] = mapped_column(ForeignKey("acc.detail_accounts.detail_account_id"))
    work_center_id: Mapped[int | None] = mapped_column(ForeignKey("prd.work_centers.work_center_id"))
    priority: Mapped[int] = mapped_column(SmallInteger, default=3)
    responsible_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    status_code: Mapped[str] = mapped_column(String(12), default="DRAFT")
    hold_reason: Mapped[str | None] = mapped_column(String(300))
    sales_order_line_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("comm.commercial_document_lines.line_id"))
    joint_cost_method: Mapped[str | None] = mapped_column(String(20))
    standard_unit_cost: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 6))
    planned_unit_cost: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 6))
    notes: Mapped[str | None] = mapped_column(String(1000))
    idempotency_key: Mapped[str | None] = mapped_column(String(80))
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("sec.users.user_id"))
    created_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")
    released_at: Mapped[datetime.datetime | None]
    completed_at: Mapped[datetime.datetime | None]
    closed_at: Mapped[datetime.datetime | None]
    closed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    plan_line_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("prd.production_plan_lines.line_id"))

    @property
    def remaining_qty(self) -> decimal.Decimal:
        return max(decimal.Decimal(0), decimal.Decimal(self.planned_qty) - decimal.Decimal(self.produced_qty))

    @property
    def progress_percent(self) -> decimal.Decimal:
        return min(decimal.Decimal(100), decimal.Decimal(self.produced_qty) * 100 / decimal.Decimal(self.planned_qty))


class OrderMaterial(Base):
    __tablename__ = "order_materials"
    __table_args__ = _PRD

    material_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    order_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("prd.production_orders.order_id"))
    line_no: Mapped[int]
    item_id: Mapped[int] = mapped_column(ForeignKey("inv.items.item_id"))
    bom_line_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("inv.bom_lines.bom_line_id"))
    component_type: Mapped[str] = mapped_column(String(15), default="MATERIAL")
    warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("inv.warehouses.warehouse_id"))
    operation_seq: Mapped[int | None]
    quantity_type: Mapped[str] = mapped_column(String(10), default="VARIABLE")
    quantity_per_base: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 6))
    batch_size_qty: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 6), default=decimal.Decimal(1))
    scrap_percent: Mapped[decimal.Decimal] = mapped_column(Numeric(7, 4), default=decimal.Decimal(0))
    planned_qty: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 6), default=decimal.Decimal(0))
    issued_qty: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 6), default=decimal.Decimal(0))
    returned_qty: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 6), default=decimal.Decimal(0))
    reserved_qty: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 6), default=decimal.Decimal(0))
    issued_amount: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=decimal.Decimal(0))
    returned_amount: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=decimal.Decimal(0))
    standard_unit_cost: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 6))
    is_optional: Mapped[bool] = mapped_column(default=False)
    substitute_item_id: Mapped[int | None] = mapped_column(ForeignKey("inv.items.item_id"))

    @property
    def consumed_qty(self) -> decimal.Decimal:
        return decimal.Decimal(self.issued_qty) - decimal.Decimal(self.returned_qty)

    @property
    def consumed_amount(self) -> decimal.Decimal:
        return decimal.Decimal(self.issued_amount) - decimal.Decimal(self.returned_amount)


class OrderOutput(Base):
    __tablename__ = "order_outputs"
    __table_args__ = _PRD

    output_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    order_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("prd.production_orders.order_id"))
    item_id: Mapped[int] = mapped_column(ForeignKey("inv.items.item_id"))
    output_type: Mapped[str] = mapped_column(String(12))
    planned_qty: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 6), default=decimal.Decimal(0))
    produced_qty: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 6), default=decimal.Decimal(0))
    produced_amount: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=decimal.Decimal(0))
    recovery_value_per_unit: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 6))
    sales_value_per_unit: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 6))
    weight_per_unit: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 6))
    cost_share_percent: Mapped[decimal.Decimal | None] = mapped_column(Numeric(7, 4))


class OrderOperation(Base):
    __tablename__ = "order_operations"
    __table_args__ = _PRD

    order_operation_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    order_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("prd.production_orders.order_id"))
    seq: Mapped[int]
    name: Mapped[str] = mapped_column(String(150))
    work_center_id: Mapped[int | None] = mapped_column(ForeignKey("prd.work_centers.work_center_id"))
    asset_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("fa.assets.asset_id"))
    labor_rate: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=decimal.Decimal(0))
    machine_rate: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=decimal.Decimal(0))
    overhead_rate: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=decimal.Decimal(0))
    std_labor_hours: Mapped[decimal.Decimal] = mapped_column(Numeric(14, 4), default=decimal.Decimal(0))
    std_machine_hours: Mapped[decimal.Decimal] = mapped_column(Numeric(14, 4), default=decimal.Decimal(0))
    std_elapsed_hours: Mapped[decimal.Decimal] = mapped_column(Numeric(14, 4), default=decimal.Decimal(0))
    status_code: Mapped[str] = mapped_column(String(12), default="PENDING")
    completed_qty: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 6), default=decimal.Decimal(0))
    actual_labor_hours: Mapped[decimal.Decimal] = mapped_column(Numeric(14, 4), default=decimal.Decimal(0))
    actual_machine_hours: Mapped[decimal.Decimal] = mapped_column(Numeric(14, 4), default=decimal.Decimal(0))
    started_at: Mapped[datetime.datetime | None]
    finished_at: Mapped[datetime.datetime | None]


class OrderTransaction(Base):
    __tablename__ = "order_transactions"
    __table_args__ = _PRD

    txn_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    order_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("prd.production_orders.order_id"))
    txn_type: Mapped[str] = mapped_column(String(12))
    txn_date: Mapped[datetime.date]
    item_id: Mapped[int | None] = mapped_column(ForeignKey("inv.items.item_id"))
    quantity: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 6), default=decimal.Decimal(0))
    amount: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=decimal.Decimal(0))
    wip_delta: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=decimal.Decimal(0))
    material_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("prd.order_materials.material_id"))
    output_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("prd.order_outputs.output_id"))
    order_operation_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("prd.order_operations.order_operation_id"))
    stock_document_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("inv.stock_documents.stock_document_id"))
    journal_entry_id: Mapped[int | None] = mapped_column(ForeignKey("acc.journal_entries.journal_entry_id"))
    reason: Mapped[str | None] = mapped_column(String(300))
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    idempotency_key: Mapped[str | None] = mapped_column(String(80))
    reversed_txn_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("prd.order_transactions.txn_id"))
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    created_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")


# --- فاز ۳: هزینه‌یابی ---------------------------------------------------------------------
class LaborEntry(Base):
    __tablename__ = "labor_entries"
    __table_args__ = _PRD

    entry_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    order_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("prd.production_orders.order_id"))
    order_operation_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("prd.order_operations.order_operation_id"))
    employee_id: Mapped[int | None] = mapped_column(ForeignKey("hr.employees.employee_id"))
    work_center_id: Mapped[int | None] = mapped_column(ForeignKey("prd.work_centers.work_center_id"))
    work_date: Mapped[datetime.date]
    hours: Mapped[decimal.Decimal] = mapped_column(Numeric(14, 4), default=decimal.Decimal(0))
    overtime_hours: Mapped[decimal.Decimal] = mapped_column(Numeric(14, 4), default=decimal.Decimal(0))
    rate: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2))
    overtime_rate: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=decimal.Decimal(0))
    amount: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2))
    cost_center_detail_account_id: Mapped[int | None] = mapped_column(ForeignKey("acc.detail_accounts.detail_account_id"))
    is_standard: Mapped[bool] = mapped_column(default=False)
    txn_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("prd.order_transactions.txn_id"))
    notes: Mapped[str | None] = mapped_column(String(300))
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    created_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")


class MachineEntry(Base):
    __tablename__ = "machine_entries"
    __table_args__ = _PRD

    entry_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    order_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("prd.production_orders.order_id"))
    order_operation_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("prd.order_operations.order_operation_id"))
    work_center_id: Mapped[int | None] = mapped_column(ForeignKey("prd.work_centers.work_center_id"))
    asset_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("fa.assets.asset_id"))
    work_date: Mapped[datetime.date]
    hours: Mapped[decimal.Decimal] = mapped_column(Numeric(14, 4))
    rate: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 6))
    amount: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2))
    is_standard: Mapped[bool] = mapped_column(default=False)
    fa_allocation_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("fa.machine_cost_allocations.allocation_id"))
    txn_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("prd.order_transactions.txn_id"))
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    created_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")


class CostPool(Base):
    __tablename__ = "cost_pools"
    __table_args__ = _PRD

    pool_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    code: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(150))
    category: Mapped[str] = mapped_column(String(20), default="OVERHEAD")
    period_code: Mapped[str] = mapped_column(String(7))
    amount: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2))
    basis: Mapped[str] = mapped_column(String(20))
    work_center_id: Mapped[int | None] = mapped_column(ForeignKey("prd.work_centers.work_center_id"))
    allocated_amount: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=decimal.Decimal(0))
    status_code: Mapped[str] = mapped_column(String(10), default="OPEN")
    notes: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")


class CostAllocationRow(Base):
    __tablename__ = "cost_allocations"
    __table_args__ = _PRD

    allocation_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    pool_id: Mapped[int] = mapped_column(ForeignKey("prd.cost_pools.pool_id"))
    order_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("prd.production_orders.order_id"))
    basis_value: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 4), default=decimal.Decimal(0))
    amount: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2))
    txn_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("prd.order_transactions.txn_id"))
    created_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")


class StandardCostCard(Base):
    __tablename__ = "standard_cost_cards"
    __table_args__ = _PRD

    card_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    item_id: Mapped[int] = mapped_column(ForeignKey("inv.items.item_id"))
    effective_date: Mapped[datetime.date]
    bom_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("inv.bom_headers.bom_id"))
    routing_id: Mapped[int | None] = mapped_column(ForeignKey("prd.routings.routing_id"))
    material_cost: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 6), default=decimal.Decimal(0))
    labor_cost: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 6), default=decimal.Decimal(0))
    machine_cost: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 6), default=decimal.Decimal(0))
    overhead_cost: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 6), default=decimal.Decimal(0))
    byproduct_credit: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 6), default=decimal.Decimal(0))
    total_cost: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 6), default=decimal.Decimal(0))
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    created_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")


class OrderCostSummary(Base):
    __tablename__ = "order_cost_summaries"
    __table_args__ = _PRD

    order_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("prd.production_orders.order_id"), primary_key=True)
    computed_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")
    produced_qty: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 6), default=decimal.Decimal(0))
    material_std: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=decimal.Decimal(0))
    material_actual: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=decimal.Decimal(0))
    labor_std: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=decimal.Decimal(0))
    labor_actual: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=decimal.Decimal(0))
    machine_std: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=decimal.Decimal(0))
    machine_actual: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=decimal.Decimal(0))
    overhead_std: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=decimal.Decimal(0))
    overhead_actual: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=decimal.Decimal(0))
    byproduct_credit: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=decimal.Decimal(0))
    scrap_recovery: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=decimal.Decimal(0))
    total_std: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=decimal.Decimal(0))
    total_actual: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=decimal.Decimal(0))
    std_unit_cost: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 6), default=decimal.Decimal(0))
    actual_unit_cost: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 6), default=decimal.Decimal(0))


class OrderVariance(Base):
    __tablename__ = "order_variances"
    __table_args__ = _PRD

    variance_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    order_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("prd.production_orders.order_id"))
    variance_code: Mapped[str] = mapped_column(String(30))
    amount: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=decimal.Decimal(0))
    quantity: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 6))
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class CostClosing(Base):
    __tablename__ = "cost_closings"
    __table_args__ = _PRD

    closing_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    period_code: Mapped[str] = mapped_column(String(7))
    period_start: Mapped[datetime.date]
    period_end: Mapped[datetime.date]
    status_code: Mapped[str] = mapped_column(String(10), default="FINALIZED")
    orders_count: Mapped[int] = mapped_column(default=0)
    wip_balance: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=decimal.Decimal(0))
    material_total: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=decimal.Decimal(0))
    labor_total: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=decimal.Decimal(0))
    machine_total: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=decimal.Decimal(0))
    overhead_applied: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=decimal.Decimal(0))
    overhead_pools: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=decimal.Decimal(0))
    output_total: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=decimal.Decimal(0))
    variance_total: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=decimal.Decimal(0))
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    finalized_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    finalized_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")
    reopened_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    reopened_at: Mapped[datetime.datetime | None]
    reopen_reason: Mapped[str | None] = mapped_column(String(300))


# --- فاز ۴: برنامه‌ریزی ------------------------------------------------------------------------
class ProductionPlan(Base):
    __tablename__ = "production_plans"
    __table_args__ = _PRD

    plan_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    code: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(150))
    period_type: Mapped[str] = mapped_column(String(5), default="MONTH")
    start_date: Mapped[datetime.date]
    end_date: Mapped[datetime.date]
    status_code: Mapped[str] = mapped_column(String(10), default="DRAFT")
    notes: Mapped[str | None] = mapped_column(String(500))
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    created_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")


class ProductionPlanLine(Base):
    __tablename__ = "production_plan_lines"
    __table_args__ = _PRD

    line_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("prd.production_plans.plan_id"))
    item_id: Mapped[int] = mapped_column(ForeignKey("inv.items.item_id"))
    planned_date: Mapped[datetime.date]
    quantity: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 6))
    work_center_id: Mapped[int | None] = mapped_column(ForeignKey("prd.work_centers.work_center_id"))
    source_type: Mapped[str] = mapped_column(String(12), default="MANUAL")
    sales_order_line_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("comm.commercial_document_lines.line_id"))
    order_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("prd.production_orders.order_id"))
    notes: Mapped[str | None] = mapped_column(String(300))


class MrpRun(Base):
    __tablename__ = "mrp_runs"
    __table_args__ = _PRD

    run_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    run_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")
    horizon_date: Mapped[datetime.date]
    params: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    lines_count: Mapped[int] = mapped_column(default=0)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))


class MrpLine(Base):
    __tablename__ = "mrp_lines"
    __table_args__ = _PRD

    mrp_line_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("prd.mrp_runs.run_id"))
    item_id: Mapped[int] = mapped_column(ForeignKey("inv.items.item_id"))
    level: Mapped[int] = mapped_column(default=0)
    make_or_buy: Mapped[str] = mapped_column(String(4))
    gross_requirement: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 6), default=decimal.Decimal(0))
    independent_demand: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 6), default=decimal.Decimal(0))
    dependent_demand: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 6), default=decimal.Decimal(0))
    on_hand: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 6), default=decimal.Decimal(0))
    reserved: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 6), default=decimal.Decimal(0))
    available: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 6), default=decimal.Decimal(0))
    scheduled_receipts: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 6), default=decimal.Decimal(0))
    min_stock: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 6), default=decimal.Decimal(0))
    net_requirement: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 6), default=decimal.Decimal(0))
    suggested_action: Mapped[str] = mapped_column(String(10), default="NONE")
    suggested_qty: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 6), default=decimal.Decimal(0))
    need_date: Mapped[datetime.date | None]
    release_date: Mapped[datetime.date | None]
    converted_ref: Mapped[str | None] = mapped_column(String(60))
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
