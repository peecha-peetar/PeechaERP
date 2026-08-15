"""سرویسِ مکان — انبارها و مکان‌هایِ انبار (inv.warehouses/bin_locations)."""

from __future__ import annotations

import decimal
from dataclasses import dataclass, field

from sqlalchemy import func, select

from peecha.db.base import new_session
from peecha.db.models.inventory import BinLocation, StockDocument, StockLedger, Warehouse, WarehouseUserAccess

DEFAULT_BIN_CODE = "GENERAL"
DEFAULT_BIN_NAME = "مکانِ پیش‌فرض"

WAREHOUSE_TYPE_CODES = (
    "GENERAL", "PROJECT", "PRODUCTION_LINE", "QUARANTINE", "TRANSIT",
    "CENTRAL", "BRANCH", "STORE", "RAW_MATERIAL", "FINISHED_GOODS",
    "SEMI_FINISHED", "SCRAP", "CONSIGNMENT", "VEHICLE", "RETURNED",
)

WITHDRAWAL_POLICY_CODES = ("FIFO", "LIFO", "FEFO", "MANUAL")
ACCESS_LEVEL_CODES = ("PUBLIC", "RESTRICTED")

BIN_TYPE_LABELS: dict[str, str] = {
    "AREA": "سالن",
    "AISLE": "راهرو",
    "RACK": "قفسه",
    "SHELF": "طبقه",
    "BIN": "باکس",
}


@dataclass
class WarehouseFields:
    warehouse_type_code: str = "GENERAL"
    project_detail_account_id: int | None = None
    allow_negative_stock: bool = False
    is_temperature_controlled: bool = False
    min_temp_c: decimal.Decimal | None = None
    max_temp_c: decimal.Decimal | None = None
    address: str | None = None
    is_default: bool = False
    # پایه
    english_name: str | None = None
    org_unit_id: int | None = None
    cost_center_detail_account_id: int | None = None
    # مکانی
    country: str | None = None
    province: str | None = None
    city: str | None = None
    postal_code: str | None = None
    phone: str | None = None
    gps_coordinates: str | None = None
    manager_user_id: int | None = None
    # عملیاتی
    allow_purchase: bool = True
    allow_sale: bool = True
    allow_production: bool = False
    allow_transfer: bool = True
    allow_cycle_count: bool = True
    allow_reservation: bool = True
    allow_direct_sale: bool = False
    requires_receipt_approval: bool = False
    requires_issue_approval: bool = False
    # کنترلِ موجودی (اطلاعاتی)
    costing_method_id: int | None = None
    default_min_qty: decimal.Decimal | None = None
    default_max_qty: decimal.Decimal | None = None
    default_reorder_point_qty: decimal.Decimal | None = None
    withdrawal_policy_code: str | None = None
    # کیفیت
    requires_qc: bool = False
    requires_quarantine: bool = False
    default_quarantine_warehouse_id: int | None = None
    # امنیت
    access_level_code: str = "PUBLIC"
    # تجهیزات
    has_barcode_equipment: bool = False
    has_qr_equipment: bool = False
    has_rfid_equipment: bool = False
    has_pda_equipment: bool = False
    has_scanner_equipment: bool = False
    has_scale_equipment: bool = False
    # فروشگاه/POS
    pos_enabled: bool = False
    pos_pick_priority: int | None = None
    # تولید (خودارجاع)
    raw_material_warehouse_id: int | None = None
    production_line_warehouse_id: int | None = None
    finished_goods_warehouse_id: int | None = None
    scrap_warehouse_id: int | None = None
    # مالی
    profit_center_detail_account_id: int | None = None
    # توضیحات
    notes: str | None = None


@dataclass
class WarehouseRow:
    warehouse_id: int
    company_id: int
    code: str
    name: str
    is_active: bool
    fields: WarehouseFields = field(default_factory=WarehouseFields)


_FIELD_NAMES = tuple(WarehouseFields.__dataclass_fields__.keys())


def _row_from_model(r: Warehouse) -> WarehouseRow:
    kwargs = {name: getattr(r, name) for name in _FIELD_NAMES}
    return WarehouseRow(r.warehouse_id, r.company_id, r.code, r.name, r.is_active, WarehouseFields(**kwargs))


def list_warehouses(company_id: int, active_only: bool = False) -> list[WarehouseRow]:
    with new_session() as session:
        query = select(Warehouse).where(Warehouse.company_id == company_id)
        if active_only:
            query = query.where(Warehouse.is_active)
        rows = session.scalars(query.order_by(Warehouse.code)).all()
        return [_row_from_model(r) for r in rows]


def get_warehouse(warehouse_id: int, company_id: int) -> WarehouseRow | None:
    with new_session() as session:
        row = session.get(Warehouse, warehouse_id)
        if row is None or row.company_id != company_id:
            return None
        return _row_from_model(row)


def get_default_warehouse(company_id: int) -> WarehouseRow | None:
    rows = list_warehouses(company_id, active_only=True)
    for r in rows:
        if r.is_default:
            return r
    return rows[0] if rows else None


def _validate_warehouse(fields: WarehouseFields) -> None:
    if fields.warehouse_type_code not in WAREHOUSE_TYPE_CODES:
        raise ValueError("نوعِ انبار نامعتبر است.")
    if fields.warehouse_type_code == "PROJECT" and fields.project_detail_account_id is None:
        raise ValueError("برایِ انبارِ پروژه‌ای، انتخابِ پروژه (تفصیلی) الزامی است.")
    if (
        fields.is_temperature_controlled
        and fields.min_temp_c is not None
        and fields.max_temp_c is not None
        and fields.min_temp_c > fields.max_temp_c
    ):
        raise ValueError("دمایِ حداقل نمی‌تواند بیشتر از دمایِ حداکثر باشد.")
    if fields.withdrawal_policy_code is not None and fields.withdrawal_policy_code not in WITHDRAWAL_POLICY_CODES:
        raise ValueError("سیاستِ برداشت نامعتبر است.")
    if fields.access_level_code not in ACCESS_LEVEL_CODES:
        raise ValueError("سطحِ دسترسی نامعتبر است.")
    if (
        fields.default_min_qty is not None
        and fields.default_max_qty is not None
        and fields.default_min_qty > fields.default_max_qty
    ):
        raise ValueError("حداقلِ موجودی نمی‌تواند بیشتر از حداکثر باشد.")
    if fields.default_reorder_point_qty is not None:
        if fields.default_min_qty is not None and fields.default_reorder_point_qty < fields.default_min_qty:
            raise ValueError("نقطهٔ‌سفارش نمی‌تواند کمتر از حداقلِ موجودی باشد.")
        if fields.default_max_qty is not None and fields.default_reorder_point_qty > fields.default_max_qty:
            raise ValueError("نقطهٔ‌سفارش نمی‌تواند بیشتر از حداکثرِ موجودی باشد.")


def create_warehouse(company_id: int, code: str, name: str, fields: WarehouseFields) -> int:
    _validate_warehouse(fields)
    with new_session() as session:
        if fields.is_default:
            session.query(Warehouse).filter(Warehouse.company_id == company_id).update({"is_default": False})
        warehouse = Warehouse(
            company_id=company_id, code=code.strip(), name=name.strip(),
            **{name: getattr(fields, name) for name in _FIELD_NAMES if name != "address"},
            address=(fields.address or None),
        )
        session.add(warehouse)
        session.flush()
        warehouse_id = warehouse.warehouse_id
        session.add(BinLocation(warehouse_id=warehouse_id, code=DEFAULT_BIN_CODE, name=DEFAULT_BIN_NAME))
        session.commit()
        return warehouse_id


def update_warehouse(warehouse_id: int, company_id: int, code: str, name: str, is_active: bool, fields: WarehouseFields) -> None:
    _validate_warehouse(fields)
    with new_session() as session:
        warehouse = session.get(Warehouse, warehouse_id)
        if warehouse is None or warehouse.company_id != company_id:
            raise ValueError("انبار نامعتبر است.")
        if fields.is_default and not warehouse.is_default:
            session.query(Warehouse).filter(Warehouse.company_id == company_id).update({"is_default": False})
        warehouse.code, warehouse.name, warehouse.is_active = code.strip(), name.strip(), is_active
        for attr_name in _FIELD_NAMES:
            if attr_name == "address":
                continue
            setattr(warehouse, attr_name, getattr(fields, attr_name))
        warehouse.address = fields.address or None
        session.commit()


def delete_warehouse(warehouse_id: int, company_id: int) -> None:
    with new_session() as session:
        warehouse = session.get(Warehouse, warehouse_id)
        if warehouse is None or warehouse.company_id != company_id:
            raise ValueError("انبار نامعتبر است.")
        has_movement = session.scalar(
            select(func.count()).select_from(StockLedger).where(StockLedger.warehouse_id == warehouse_id)
        )
        has_document = session.scalar(
            select(func.count()).select_from(StockDocument).where(
                (StockDocument.source_warehouse_id == warehouse_id)
                | (StockDocument.destination_warehouse_id == warehouse_id)
            )
        )
        if has_movement or has_document:
            raise ValueError("این انبار سابقهٔ سند/حرکت دارد و قابلِ‌حذف نیست.")
        session.query(BinLocation).filter(BinLocation.warehouse_id == warehouse_id).delete()
        session.query(WarehouseUserAccess).filter(WarehouseUserAccess.warehouse_id == warehouse_id).delete()
        session.delete(warehouse)
        session.commit()


# ---------------------------------------------------------------------
# مکانِ انبار
# ---------------------------------------------------------------------
@dataclass
class BinLocationRow:
    bin_location_id: int
    warehouse_id: int
    parent_bin_location_id: int | None
    code: str
    name: str | None
    bin_type_code: str | None
    barcode: str | None
    is_pickable: bool
    is_active: bool


def list_bin_locations(warehouse_id: int, active_only: bool = False) -> list[BinLocationRow]:
    with new_session() as session:
        query = select(BinLocation).where(BinLocation.warehouse_id == warehouse_id)
        if active_only:
            query = query.where(BinLocation.is_active)
        rows = session.scalars(query.order_by(BinLocation.code)).all()
        return [
            BinLocationRow(
                r.bin_location_id, r.warehouse_id, r.parent_bin_location_id, r.code, r.name,
                r.bin_type_code, r.barcode, r.is_pickable, r.is_active,
            )
            for r in rows
        ]


def get_default_bin_location(warehouse_id: int) -> BinLocationRow | None:
    with new_session() as session:
        row = session.scalar(
            select(BinLocation).where(BinLocation.warehouse_id == warehouse_id, BinLocation.code == DEFAULT_BIN_CODE)
        )
        if row is None:
            row = session.scalar(
                select(BinLocation).where(BinLocation.warehouse_id == warehouse_id).order_by(BinLocation.bin_location_id)
            )
        if row is None:
            return None
        return BinLocationRow(
            row.bin_location_id, row.warehouse_id, row.parent_bin_location_id, row.code, row.name,
            row.bin_type_code, row.barcode, row.is_pickable, row.is_active,
        )


def create_bin_location(
    warehouse_id: int, code: str, name: str | None = None, parent_bin_location_id: int | None = None,
    bin_type_code: str | None = None, barcode: str | None = None, is_pickable: bool = True,
) -> int:
    with new_session() as session:
        if parent_bin_location_id is not None:
            parent = session.get(BinLocation, parent_bin_location_id)
            if parent is None or parent.warehouse_id != warehouse_id:
                raise ValueError("مکانِ والد نامعتبر است.")
        bin_location = BinLocation(
            warehouse_id=warehouse_id, code=code.strip(), name=(name or None),
            parent_bin_location_id=parent_bin_location_id, bin_type_code=bin_type_code,
            barcode=(barcode or None), is_pickable=is_pickable,
        )
        session.add(bin_location)
        session.commit()
        return bin_location.bin_location_id


def update_bin_location(
    bin_location_id: int, warehouse_id: int, code: str, is_active: bool, name: str | None = None,
    bin_type_code: str | None = None, barcode: str | None = None, is_pickable: bool = True,
) -> None:
    with new_session() as session:
        bin_location = session.get(BinLocation, bin_location_id)
        if bin_location is None or bin_location.warehouse_id != warehouse_id:
            raise ValueError("مکانِ انبار نامعتبر است.")
        bin_location.code, bin_location.is_active = code.strip(), is_active
        bin_location.name = name or None
        bin_location.bin_type_code = bin_type_code
        bin_location.barcode = barcode or None
        bin_location.is_pickable = is_pickable
        session.commit()


def delete_bin_location(bin_location_id: int, warehouse_id: int) -> None:
    with new_session() as session:
        bin_location = session.get(BinLocation, bin_location_id)
        if bin_location is None or bin_location.warehouse_id != warehouse_id:
            raise ValueError("مکانِ انبار نامعتبر است.")
        if bin_location.code == DEFAULT_BIN_CODE:
            raise ValueError("مکانِ پیش‌فرضِ انبار قابلِ‌حذف نیست.")
        has_movement = session.scalar(
            select(func.count()).select_from(StockLedger).where(StockLedger.bin_location_id == bin_location_id)
        )
        if has_movement:
            raise ValueError("این مکان سابقهٔ حرکتِ انبار دارد و قابلِ‌حذف نیست.")
        session.delete(bin_location)
        session.commit()


# ---------------------------------------------------------------------
# کاربرانِ مجازِ انبار (inv.warehouse_user_access) — فقط CRUDِ تعریفی این
# دور؛ هنوز به هیچ سندی وصل نیست (هم‌دامنه با نگاشتِ حسابِ سطحِ‌انبار).
# ---------------------------------------------------------------------
@dataclass
class WarehouseUserAccessRow:
    warehouse_id: int
    user_id: int
    can_view_balance: bool
    can_post_receipt: bool
    can_post_issue: bool
    can_adjust: bool


def list_warehouse_user_access(warehouse_id: int) -> list[WarehouseUserAccessRow]:
    with new_session() as session:
        rows = session.scalars(
            select(WarehouseUserAccess).where(WarehouseUserAccess.warehouse_id == warehouse_id)
        ).all()
        return [
            WarehouseUserAccessRow(
                r.warehouse_id, r.user_id, r.can_view_balance, r.can_post_receipt, r.can_post_issue, r.can_adjust
            )
            for r in rows
        ]


def set_warehouse_user_access(
    warehouse_id: int, user_id: int, can_view_balance: bool = True, can_post_receipt: bool = True,
    can_post_issue: bool = True, can_adjust: bool = True,
) -> None:
    with new_session() as session:
        row = session.get(WarehouseUserAccess, (warehouse_id, user_id))
        if row is None:
            session.add(
                WarehouseUserAccess(
                    warehouse_id=warehouse_id, user_id=user_id, can_view_balance=can_view_balance,
                    can_post_receipt=can_post_receipt, can_post_issue=can_post_issue, can_adjust=can_adjust,
                )
            )
        else:
            row.can_view_balance = can_view_balance
            row.can_post_receipt = can_post_receipt
            row.can_post_issue = can_post_issue
            row.can_adjust = can_adjust
        session.commit()


def remove_warehouse_user_access(warehouse_id: int, user_id: int) -> None:
    with new_session() as session:
        row = session.get(WarehouseUserAccess, (warehouse_id, user_id))
        if row is not None:
            session.delete(row)
            session.commit()
