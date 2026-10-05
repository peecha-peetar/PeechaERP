"""مدل‌هایِ دارایی‌هایِ ثابت (schema fa) -- R262. معادلِ db/schema/195_fixed_assets.sql."""

from __future__ import annotations

import datetime
import decimal
from typing import Any

from sqlalchemy import BigInteger, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from peecha.db.base import Base

_FA = {"schema": "fa"}


class AssetSettings(Base):
    __tablename__ = "asset_settings"
    __table_args__ = _FA

    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"), primary_key=True)
    depreciation_start_rule: Mapped[str] = mapped_column(String(20), default="IN_SERVICE")
    depreciation_frequency: Mapped[str] = mapped_column(String(10), default="MONTHLY")
    improvement_capitalize_min: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=0)
    require_cost_center: Mapped[bool] = mapped_column(default=False)
    large_improvement_approval_min: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 2))
    updated_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")


class AssetBook(Base):
    __tablename__ = "asset_books"
    __table_args__ = _FA

    book_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    code: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(100))
    is_primary: Mapped[bool] = mapped_column(default=False)
    posts_to_gl: Mapped[bool] = mapped_column(default=True)
    is_active: Mapped[bool] = mapped_column(default=True)


class AssetCategory(Base):
    __tablename__ = "asset_categories"
    __table_args__ = _FA

    category_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    code: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(150))
    default_method: Mapped[str] = mapped_column(String(25), default="STRAIGHT_LINE")
    default_life_months: Mapped[int | None]
    default_residual_percent: Mapped[decimal.Decimal] = mapped_column(Numeric(7, 4), default=0)
    default_declining_rate: Mapped[decimal.Decimal | None] = mapped_column(Numeric(9, 6))
    cost_center_required: Mapped[bool] = mapped_column(default=False)
    default_cost_center_detail_account_id: Mapped[int | None] = mapped_column(ForeignKey("acc.detail_accounts.detail_account_id"))
    asset_account_id: Mapped[int | None] = mapped_column(ForeignKey("acc.chart_of_accounts.account_id"))
    accumulated_depreciation_account_id: Mapped[int | None] = mapped_column(ForeignKey("acc.chart_of_accounts.account_id"))
    depreciation_expense_account_id: Mapped[int | None] = mapped_column(ForeignKey("acc.chart_of_accounts.account_id"))
    disposal_gain_account_id: Mapped[int | None] = mapped_column(ForeignKey("acc.chart_of_accounts.account_id"))
    disposal_loss_account_id: Mapped[int | None] = mapped_column(ForeignKey("acc.chart_of_accounts.account_id"))
    impairment_account_id: Mapped[int | None] = mapped_column(ForeignKey("acc.chart_of_accounts.account_id"))
    revaluation_account_id: Mapped[int | None] = mapped_column(ForeignKey("acc.chart_of_accounts.account_id"))
    cip_account_id: Mapped[int | None] = mapped_column(ForeignKey("acc.chart_of_accounts.account_id"))
    maintenance_expense_account_id: Mapped[int | None] = mapped_column(ForeignKey("acc.chart_of_accounts.account_id"))
    is_active: Mapped[bool] = mapped_column(default=True)


class AssetGroup(Base):
    __tablename__ = "asset_groups"
    __table_args__ = _FA

    group_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    code: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(150))
    is_active: Mapped[bool] = mapped_column(default=True)


class AssetLocation(Base):
    __tablename__ = "asset_locations"
    __table_args__ = _FA

    location_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    parent_location_id: Mapped[int | None] = mapped_column(ForeignKey("fa.asset_locations.location_id"))
    code: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(150))
    location_type: Mapped[str] = mapped_column(String(15), default="ROOM")
    branch_id: Mapped[int | None] = mapped_column(ForeignKey("comm.branches.branch_id"))
    is_active: Mapped[bool] = mapped_column(default=True)


class Asset(Base):
    __tablename__ = "assets"
    __table_args__ = _FA

    asset_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    asset_code: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(200))
    category_id: Mapped[int] = mapped_column(ForeignKey("fa.asset_categories.category_id"))
    group_id: Mapped[int | None] = mapped_column(ForeignKey("fa.asset_groups.group_id"))
    asset_type_code: Mapped[str] = mapped_column(String(20), default="EQUIPMENT")
    description: Mapped[str | None] = mapped_column(Text)
    brand: Mapped[str | None] = mapped_column(String(100))
    model: Mapped[str | None] = mapped_column(String(100))
    serial_no: Mapped[str | None] = mapped_column(String(100))
    part_no: Mapped[str | None] = mapped_column(String(100))
    barcode: Mapped[str | None] = mapped_column(String(100))
    parent_asset_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("fa.assets.asset_id"))
    status_code: Mapped[str] = mapped_column(String(20), default="DRAFT")
    source_code: Mapped[str] = mapped_column(String(20), default="MANUAL")
    acquisition_date: Mapped[datetime.date | None]
    capitalization_date: Mapped[datetime.date | None]
    in_service_date: Mapped[datetime.date | None]
    depreciation_start_date: Mapped[datetime.date | None]
    purchase_price: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=0)
    residual_value: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=0)
    useful_life: Mapped[decimal.Decimal | None] = mapped_column(Numeric(14, 2))
    useful_life_unit: Mapped[str] = mapped_column(String(10), default="MONTH")
    depreciation_method: Mapped[str] = mapped_column(String(25), default="STRAIGHT_LINE")
    declining_rate: Mapped[decimal.Decimal | None] = mapped_column(Numeric(9, 6))
    gross_cost: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=0)
    accumulated_depreciation: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=0)
    accumulated_impairment: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=0)
    revaluation_surplus: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=0)
    units_consumed: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 4), default=0)
    branch_id: Mapped[int | None] = mapped_column(ForeignKey("comm.branches.branch_id"))
    department_id: Mapped[int | None] = mapped_column(ForeignKey("hr.organizational_units.org_unit_id"))
    cost_center_detail_account_id: Mapped[int | None] = mapped_column(ForeignKey("acc.detail_accounts.detail_account_id"))
    project_detail_account_id: Mapped[int | None] = mapped_column(ForeignKey("acc.detail_accounts.detail_account_id"))
    location_id: Mapped[int | None] = mapped_column(ForeignKey("fa.asset_locations.location_id"))
    custodian_employee_id: Mapped[int | None] = mapped_column(ForeignKey("hr.employees.employee_id"))
    supplier_detail_account_id: Mapped[int | None] = mapped_column(ForeignKey("acc.detail_accounts.detail_account_id"))
    invoice_document_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("comm.commercial_documents.document_id"))
    invoice_reference: Mapped[str | None] = mapped_column(String(100))
    source_stock_line_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("inv.stock_document_lines.line_id"))
    capitalization_stock_document_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("inv.stock_documents.stock_document_id"))
    legacy_item_id: Mapped[int | None] = mapped_column(ForeignKey("inv.items.item_id"))
    currency_id: Mapped[int | None] = mapped_column(ForeignKey("core.currencies.currency_id"))
    exchange_rate: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 6))
    purchase_price_fc: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 2))
    is_production_machine: Mapped[bool] = mapped_column(default=False)
    work_center_code: Mapped[str | None] = mapped_column(String(40))
    production_line: Mapped[str | None] = mapped_column(String(100))
    machine_rate: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 2))
    capacity_per_hour: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 4))
    standard_hours: Mapped[decimal.Decimal | None] = mapped_column(Numeric(14, 2))
    notes: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    created_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")
    updated_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")

    @property
    def book_value(self) -> decimal.Decimal:
        return self.gross_cost - self.accumulated_depreciation - self.accumulated_impairment


class AssetBookSetting(Base):
    __tablename__ = "asset_book_settings"
    __table_args__ = _FA

    asset_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("fa.assets.asset_id"), primary_key=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("fa.asset_books.book_id"), primary_key=True)
    depreciation_method: Mapped[str] = mapped_column(String(25))
    useful_life: Mapped[decimal.Decimal | None] = mapped_column(Numeric(14, 2))
    residual_value: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=0)
    declining_rate: Mapped[decimal.Decimal | None] = mapped_column(Numeric(9, 6))


class AssetCostItem(Base):
    __tablename__ = "asset_cost_items"
    __table_args__ = _FA

    cost_item_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    asset_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("fa.assets.asset_id"))
    cost_type: Mapped[str] = mapped_column(String(20))
    amount: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2))
    offset_account_id: Mapped[int | None] = mapped_column(ForeignKey("acc.chart_of_accounts.account_id"))
    offset_detail_account_id: Mapped[int | None] = mapped_column(ForeignKey("acc.detail_accounts.detail_account_id"))
    reference: Mapped[str | None] = mapped_column(String(100))
    journal_entry_id: Mapped[int | None] = mapped_column(ForeignKey("acc.journal_entries.journal_entry_id"))
    created_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")


class AssetTransaction(Base):
    __tablename__ = "asset_transactions"
    __table_args__ = _FA

    txn_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    asset_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("fa.assets.asset_id"))
    book_id: Mapped[int] = mapped_column(ForeignKey("fa.asset_books.book_id"))
    txn_type: Mapped[str] = mapped_column(String(20))
    txn_date: Mapped[datetime.date]
    cost_delta: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=0)
    depreciation_delta: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=0)
    impairment_delta: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=0)
    revaluation_delta: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=0)
    units: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 4))
    description: Mapped[str | None] = mapped_column(String(300))
    reference: Mapped[str | None] = mapped_column(String(100))
    journal_entry_id: Mapped[int | None] = mapped_column(ForeignKey("acc.journal_entries.journal_entry_id"))
    source_type: Mapped[str | None] = mapped_column(String(20))
    source_id: Mapped[int | None] = mapped_column(BigInteger)
    reversed_txn_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("fa.asset_transactions.txn_id"))
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    created_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")


class DepreciationRun(Base):
    __tablename__ = "depreciation_runs"
    __table_args__ = _FA

    run_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    book_id: Mapped[int] = mapped_column(ForeignKey("fa.asset_books.book_id"))
    period_code: Mapped[str] = mapped_column(String(10))
    period_start: Mapped[datetime.date]
    period_end: Mapped[datetime.date]
    posting_date: Mapped[datetime.date]
    status_code: Mapped[str] = mapped_column(String(12), default="CALCULATED")
    asset_count: Mapped[int] = mapped_column(default=0)
    total_amount: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=0)
    journal_entry_id: Mapped[int | None] = mapped_column(ForeignKey("acc.journal_entries.journal_entry_id"))
    reversal_journal_entry_id: Mapped[int | None] = mapped_column(ForeignKey("acc.journal_entries.journal_entry_id"))
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    reviewed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    approved_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    posted_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    created_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")
    posted_at: Mapped[datetime.datetime | None]


class DepreciationLine(Base):
    __tablename__ = "depreciation_lines"
    __table_args__ = _FA

    depreciation_line_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    run_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("fa.depreciation_runs.run_id"))
    asset_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("fa.assets.asset_id"))
    method: Mapped[str] = mapped_column(String(25))
    opening_book_value: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2))
    amount: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2))
    closing_book_value: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2))
    units: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 4))
    cost_center_detail_account_id: Mapped[int | None] = mapped_column(ForeignKey("acc.detail_accounts.detail_account_id"))
    expense_account_id: Mapped[int | None] = mapped_column(ForeignKey("acc.chart_of_accounts.account_id"))
    accumulated_account_id: Mapped[int | None] = mapped_column(ForeignKey("acc.chart_of_accounts.account_id"))
    txn_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("fa.asset_transactions.txn_id"))


class AssetUsage(Base):
    __tablename__ = "asset_usage"
    __table_args__ = _FA

    usage_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    asset_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("fa.assets.asset_id"))
    usage_date: Mapped[datetime.date]
    units: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 4))
    source_code: Mapped[str] = mapped_column(String(15), default="MANUAL")
    production_order_ref: Mapped[str | None] = mapped_column(String(60))
    note: Mapped[str | None] = mapped_column(String(300))
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    created_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")


class MachineCostAllocation(Base):
    __tablename__ = "machine_cost_allocations"
    __table_args__ = _FA

    allocation_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    asset_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("fa.assets.asset_id"))
    period_code: Mapped[str] = mapped_column(String(10))
    production_order_ref: Mapped[str] = mapped_column(String(60))
    hours: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 4))
    rate_per_hour: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 6))
    amount: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2))
    cost_center_detail_account_id: Mapped[int | None] = mapped_column(ForeignKey("acc.detail_accounts.detail_account_id"))
    created_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")


class AssetEvent(Base):
    __tablename__ = "asset_events"
    __table_args__ = _FA

    event_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    asset_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("fa.assets.asset_id"))
    event_type: Mapped[str] = mapped_column(String(20))
    event_date: Mapped[datetime.date]
    status_code: Mapped[str] = mapped_column(String(20), default="POSTED")
    amount: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 2))
    proceeds: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 2))
    previous_book_value: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 2))
    new_value: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 2))
    gain_loss: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 2))
    reason: Mapped[str | None] = mapped_column(String(300))
    condition_note: Mapped[str | None] = mapped_column(String(300))
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    offset_account_id: Mapped[int | None] = mapped_column(ForeignKey("acc.chart_of_accounts.account_id"))
    counterparty_detail_account_id: Mapped[int | None] = mapped_column(ForeignKey("acc.detail_accounts.detail_account_id"))
    journal_entry_id: Mapped[int | None] = mapped_column(ForeignKey("acc.journal_entries.journal_entry_id"))
    idempotency_key: Mapped[str | None] = mapped_column(String(80))
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    approved_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    created_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")
    posted_at: Mapped[datetime.datetime | None]


class CipProject(Base):
    __tablename__ = "cip_projects"
    __table_args__ = _FA

    cip_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    code: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(200))
    category_id: Mapped[int] = mapped_column(ForeignKey("fa.asset_categories.category_id"))
    start_date: Mapped[datetime.date]
    status_code: Mapped[str] = mapped_column(String(12), default="OPEN")
    cost_center_detail_account_id: Mapped[int | None] = mapped_column(ForeignKey("acc.detail_accounts.detail_account_id"))
    project_detail_account_id: Mapped[int | None] = mapped_column(ForeignKey("acc.detail_accounts.detail_account_id"))
    capitalized_asset_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("fa.assets.asset_id"))
    capitalized_at: Mapped[datetime.date | None]
    journal_entry_id: Mapped[int | None] = mapped_column(ForeignKey("acc.journal_entries.journal_entry_id"))
    notes: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    created_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")


class CipCost(Base):
    __tablename__ = "cip_costs"
    __table_args__ = _FA

    cip_cost_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    cip_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("fa.cip_projects.cip_id"))
    cost_date: Mapped[datetime.date]
    cost_type: Mapped[str] = mapped_column(String(20))
    amount: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2))
    description: Mapped[str | None] = mapped_column(String(300))
    offset_account_id: Mapped[int | None] = mapped_column(ForeignKey("acc.chart_of_accounts.account_id"))
    offset_detail_account_id: Mapped[int | None] = mapped_column(ForeignKey("acc.detail_accounts.detail_account_id"))
    stock_document_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("inv.stock_documents.stock_document_id"))
    journal_entry_id: Mapped[int | None] = mapped_column(ForeignKey("acc.journal_entries.journal_entry_id"))
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    created_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")


class PhysicalCount(Base):
    __tablename__ = "physical_counts"
    __table_args__ = _FA

    count_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    code: Mapped[str] = mapped_column(String(40))
    count_date: Mapped[datetime.date]
    location_id: Mapped[int | None] = mapped_column(ForeignKey("fa.asset_locations.location_id"))
    status_code: Mapped[str] = mapped_column(String(10), default="OPEN")
    notes: Mapped[str | None] = mapped_column(String(300))
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    created_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")
    closed_at: Mapped[datetime.datetime | None]


class PhysicalCountItem(Base):
    __tablename__ = "physical_count_items"
    __table_args__ = _FA

    count_item_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    count_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("fa.physical_counts.count_id"))
    asset_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("fa.assets.asset_id"))
    expected_location_id: Mapped[int | None] = mapped_column(ForeignKey("fa.asset_locations.location_id"))
    expected_custodian_employee_id: Mapped[int | None] = mapped_column(ForeignKey("hr.employees.employee_id"))
    found_location_id: Mapped[int | None] = mapped_column(ForeignKey("fa.asset_locations.location_id"))
    found_custodian_employee_id: Mapped[int | None] = mapped_column(ForeignKey("hr.employees.employee_id"))
    result_code: Mapped[str] = mapped_column(String(20), default="PENDING")
    scan_method: Mapped[str | None] = mapped_column(String(10))
    is_damaged: Mapped[bool] = mapped_column(default=False)
    scanned_at: Mapped[datetime.datetime | None]
    note: Mapped[str | None] = mapped_column(String(300))


class AssetWarranty(Base):
    __tablename__ = "asset_warranties"
    __table_args__ = _FA

    warranty_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    asset_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("fa.assets.asset_id"))
    warranty_type: Mapped[str | None] = mapped_column(String(60))
    supplier_detail_account_id: Mapped[int | None] = mapped_column(ForeignKey("acc.detail_accounts.detail_account_id"))
    contract_no: Mapped[str | None] = mapped_column(String(60))
    start_date: Mapped[datetime.date]
    end_date: Mapped[datetime.date]
    note: Mapped[str | None] = mapped_column(String(300))


class AssetInsurance(Base):
    __tablename__ = "asset_insurances"
    __table_args__ = _FA

    insurance_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    asset_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("fa.assets.asset_id"))
    insurer_name: Mapped[str] = mapped_column(String(150))
    policy_no: Mapped[str | None] = mapped_column(String(60))
    start_date: Mapped[datetime.date]
    end_date: Mapped[datetime.date]
    premium: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 2))
    coverage: Mapped[str | None] = mapped_column(String(300))
    insured_value: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 2))
