"""سرویسِ مکان — انبارها و مکان‌هایِ انبار (inv.warehouses/bin_locations)."""

from __future__ import annotations

import decimal
from dataclasses import dataclass

from sqlalchemy import func, select

from peecha.db.base import new_session
from peecha.db.models.inventory import BinLocation, StockDocument, StockLedger, Warehouse

DEFAULT_BIN_CODE = "GENERAL"
DEFAULT_BIN_NAME = "مکانِ پیش‌فرض"

WAREHOUSE_TYPE_CODES = ("GENERAL", "PROJECT", "PRODUCTION_LINE", "QUARANTINE", "TRANSIT")


@dataclass
class WarehouseRow:
    warehouse_id: int
    code: str
    name: str
    warehouse_type_code: str
    project_detail_account_id: int | None
    allow_negative_stock: bool
    is_temperature_controlled: bool
    min_temp_c: decimal.Decimal | None
    max_temp_c: decimal.Decimal | None
    address: str | None
    is_default: bool
    is_active: bool


def list_warehouses(company_id: int, active_only: bool = False) -> list[WarehouseRow]:
    with new_session() as session:
        query = select(Warehouse).where(Warehouse.company_id == company_id)
        if active_only:
            query = query.where(Warehouse.is_active)
        rows = session.scalars(query.order_by(Warehouse.code)).all()
        return [
            WarehouseRow(
                r.warehouse_id, r.code, r.name, r.warehouse_type_code, r.project_detail_account_id,
                r.allow_negative_stock, r.is_temperature_controlled, r.min_temp_c, r.max_temp_c,
                r.address, r.is_default, r.is_active,
            )
            for r in rows
        ]


def get_default_warehouse(company_id: int) -> WarehouseRow | None:
    rows = list_warehouses(company_id, active_only=True)
    for r in rows:
        if r.is_default:
            return r
    return rows[0] if rows else None


def _validate_warehouse(
    warehouse_type_code: str, project_detail_account_id: int | None,
    is_temperature_controlled: bool, min_temp_c: decimal.Decimal | None, max_temp_c: decimal.Decimal | None,
) -> None:
    if warehouse_type_code not in WAREHOUSE_TYPE_CODES:
        raise ValueError("نوعِ انبار نامعتبر است.")
    if warehouse_type_code == "PROJECT" and project_detail_account_id is None:
        raise ValueError("برایِ انبارِ پروژه‌ای، انتخابِ پروژه (تفصیلی) الزامی است.")
    if is_temperature_controlled and min_temp_c is not None and max_temp_c is not None and min_temp_c > max_temp_c:
        raise ValueError("دمایِ حداقل نمی‌تواند بیشتر از دمایِ حداکثر باشد.")


def create_warehouse(
    company_id: int, code: str, name: str, warehouse_type_code: str = "GENERAL",
    project_detail_account_id: int | None = None, allow_negative_stock: bool = False,
    is_temperature_controlled: bool = False, min_temp_c: decimal.Decimal | None = None,
    max_temp_c: decimal.Decimal | None = None, address: str | None = None, is_default: bool = False,
) -> int:
    _validate_warehouse(warehouse_type_code, project_detail_account_id, is_temperature_controlled, min_temp_c, max_temp_c)
    with new_session() as session:
        if is_default:
            session.query(Warehouse).filter(Warehouse.company_id == company_id).update({"is_default": False})
        warehouse = Warehouse(
            company_id=company_id, code=code.strip(), name=name.strip(), warehouse_type_code=warehouse_type_code,
            project_detail_account_id=project_detail_account_id, allow_negative_stock=allow_negative_stock,
            is_temperature_controlled=is_temperature_controlled, min_temp_c=min_temp_c, max_temp_c=max_temp_c,
            address=(address or None), is_default=is_default,
        )
        session.add(warehouse)
        session.flush()
        warehouse_id = warehouse.warehouse_id
        session.add(BinLocation(warehouse_id=warehouse_id, code=DEFAULT_BIN_CODE, name=DEFAULT_BIN_NAME))
        session.commit()
        return warehouse_id


def update_warehouse(
    warehouse_id: int, company_id: int, code: str, name: str, is_active: bool, warehouse_type_code: str = "GENERAL",
    project_detail_account_id: int | None = None, allow_negative_stock: bool = False,
    is_temperature_controlled: bool = False, min_temp_c: decimal.Decimal | None = None,
    max_temp_c: decimal.Decimal | None = None, address: str | None = None, is_default: bool = False,
) -> None:
    _validate_warehouse(warehouse_type_code, project_detail_account_id, is_temperature_controlled, min_temp_c, max_temp_c)
    with new_session() as session:
        warehouse = session.get(Warehouse, warehouse_id)
        if warehouse is None or warehouse.company_id != company_id:
            raise ValueError("انبار نامعتبر است.")
        if is_default and not warehouse.is_default:
            session.query(Warehouse).filter(Warehouse.company_id == company_id).update({"is_default": False})
        warehouse.code, warehouse.name, warehouse.is_active = code.strip(), name.strip(), is_active
        warehouse.warehouse_type_code = warehouse_type_code
        warehouse.project_detail_account_id = project_detail_account_id
        warehouse.allow_negative_stock = allow_negative_stock
        warehouse.is_temperature_controlled = is_temperature_controlled
        warehouse.min_temp_c, warehouse.max_temp_c = min_temp_c, max_temp_c
        warehouse.address = address or None
        warehouse.is_default = is_default
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
