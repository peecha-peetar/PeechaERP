"""پخشِ سرد/گرم -- R129، بخشِ بارگیریِ خودرو. یک Pick Listِ صبح -- طبقِ
درخواستِ صریح («سیستم پیشنهاد بدهد چقدر کارتن نیاز داری، چقدر موجودیِ
خودرو داری، چقدر کسری داری») -- که بعدِ تاییدِ راننده، یک سندِ TRANSFERِ
واقعی از انبارِ مرکزی به انبارِ خودرو می‌سازد. منطقِ واقعیِ جابه‌جاییِ
موجودی این‌جا دوباره نوشته نمی‌شود؛ همان inventory_documents.py/
inventory_engine.py صدا زده می‌شود -- دقیقاً هم‌الگو با هر سندِ دیگرِ
انبار در این پروژه."""

from __future__ import annotations

import datetime
import decimal
from dataclasses import dataclass

from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.inventory import VehicleLoading, VehicleLoadingLine
from peecha.services import inventory_documents as inv_documents_service
from peecha.services import inventory_engine as engine_service


@dataclass
class VehicleLoadingLineFields:
    item_id: int
    uom_id: int
    planned_quantity: decimal.Decimal


@dataclass
class VehicleLoadingLineRow:
    vehicle_loading_line_id: int
    item_id: int
    uom_id: int
    planned_quantity: decimal.Decimal
    available_quantity_at_planning: decimal.Decimal | None
    shortage_quantity: decimal.Decimal


@dataclass
class VehicleLoadingRow:
    vehicle_loading_id: int
    vehicle_warehouse_id: int
    source_warehouse_id: int
    loading_date: datetime.date
    status_code: str
    stock_document_id: int | None
    driver_confirmed_by_user_id: int | None
    driver_confirmed_at: datetime.datetime | None
    lines: list[VehicleLoadingLineRow]


def create_vehicle_loading(
    company_id: int, created_by_user_id: int, vehicle_warehouse_id: int, source_warehouse_id: int,
    loading_date: datetime.date, lines: list[VehicleLoadingLineFields], notes: str | None = None,
) -> int:
    if vehicle_warehouse_id == source_warehouse_id:
        raise ValueError("انبارِ خودرو و انبارِ مبدا نمی‌توانند یکی باشند.")
    if not lines:
        raise ValueError("حداقل یک ردیف برایِ بارگیری لازم است.")
    balances_by_item = {b.item_id: b.quantity_available for b in engine_service.list_balances(company_id, warehouse_id=source_warehouse_id)}
    with new_session() as session:
        loading = VehicleLoading(
            company_id=company_id, vehicle_warehouse_id=vehicle_warehouse_id, source_warehouse_id=source_warehouse_id,
            loading_date=loading_date, notes=notes or None, created_by_user_id=created_by_user_id,
        )
        session.add(loading)
        session.flush()
        for line_fields in lines:
            if line_fields.planned_quantity <= 0:
                raise ValueError("مقدارِ برنامه‌ریزی‌شده باید بزرگ‌تر از صفر باشد.")
            session.add(
                VehicleLoadingLine(
                    vehicle_loading_id=loading.vehicle_loading_id, item_id=line_fields.item_id, uom_id=line_fields.uom_id,
                    planned_quantity=line_fields.planned_quantity,
                    available_quantity_at_planning=balances_by_item.get(line_fields.item_id, decimal.Decimal(0)),
                )
            )
        session.commit()
        return loading.vehicle_loading_id


def get_vehicle_loading(vehicle_loading_id: int, company_id: int) -> VehicleLoadingRow:
    with new_session() as session:
        loading = session.get(VehicleLoading, vehicle_loading_id)
        if loading is None or loading.company_id != company_id:
            raise ValueError("سندِ بارگیری نامعتبر است.")
        line_rows = session.scalars(
            select(VehicleLoadingLine).where(VehicleLoadingLine.vehicle_loading_id == vehicle_loading_id)
        ).all()
        lines = [
            VehicleLoadingLineRow(
                r.vehicle_loading_line_id, r.item_id, r.uom_id, r.planned_quantity, r.available_quantity_at_planning,
                shortage_quantity=max(decimal.Decimal(0), r.planned_quantity - (r.available_quantity_at_planning or decimal.Decimal(0))),
            )
            for r in line_rows
        ]
        return VehicleLoadingRow(
            loading.vehicle_loading_id, loading.vehicle_warehouse_id, loading.source_warehouse_id, loading.loading_date,
            loading.status_code, loading.stock_document_id, loading.driver_confirmed_by_user_id, loading.driver_confirmed_at,
            lines,
        )


def list_vehicle_loadings(company_id: int, vehicle_warehouse_id: int | None = None, status_code: str | None = None) -> list[VehicleLoadingRow]:
    with new_session() as session:
        stmt = select(VehicleLoading.vehicle_loading_id).where(VehicleLoading.company_id == company_id)
        if vehicle_warehouse_id is not None:
            stmt = stmt.where(VehicleLoading.vehicle_warehouse_id == vehicle_warehouse_id)
        if status_code is not None:
            stmt = stmt.where(VehicleLoading.status_code == status_code)
        stmt = stmt.order_by(VehicleLoading.loading_date.desc())
        ids = session.scalars(stmt).all()
    return [get_vehicle_loading(loading_id, company_id) for loading_id in ids]


def confirm_vehicle_loading(vehicle_loading_id: int, company_id: int, driver_user_id: int) -> int:
    """طبقِ رفعِ باگِ واقعی: بارگیری باید واقعاً موجودی را جابه‌جا کند --
    نه فقط یک برنامهٔ کاغذی بماند. سندِ TRANSFERِ واقعی از همان سرویسِ
    عمومیِ انبار ساخته/تایید/پست می‌شود تا کاردکس/موجودیِ خودرو درست
    به‌روز شود، دقیقاً هم‌الگو با هر انتقالِ دیگر."""
    with new_session() as session:
        loading = session.get(VehicleLoading, vehicle_loading_id)
        if loading is None or loading.company_id != company_id:
            raise ValueError("سندِ بارگیری نامعتبر است.")
        if loading.status_code != "DRAFT":
            raise ValueError("این بارگیری قبلاً تایید شده است.")
        source_warehouse_id, vehicle_warehouse_id, loading_date = (
            loading.source_warehouse_id, loading.vehicle_warehouse_id, loading.loading_date,
        )
        line_rows = session.scalars(
            select(VehicleLoadingLine).where(VehicleLoadingLine.vehicle_loading_id == vehicle_loading_id)
        ).all()
        lines = [(r.item_id, r.uom_id, r.planned_quantity) for r in line_rows]

    stock_document_id = inv_documents_service.create_stock_document(
        company_id, driver_user_id, "TRANSFER", loading_date,
        inv_documents_service.DocumentHeaderFields(source_warehouse_id=source_warehouse_id, destination_warehouse_id=vehicle_warehouse_id),
    )
    for item_id, uom_id, quantity in lines:
        inv_documents_service.add_line(
            stock_document_id, company_id,
            inv_documents_service.LineFields(item_id=item_id, uom_id=uom_id, quantity=quantity, quantity_base=quantity),
        )
    inv_documents_service.confirm_stock_document(stock_document_id, company_id)
    inv_documents_service.post_stock_document(stock_document_id, company_id, driver_user_id)

    with new_session() as session:
        loading = session.get(VehicleLoading, vehicle_loading_id)
        loading.status_code = "CONFIRMED"
        loading.stock_document_id = stock_document_id
        loading.driver_confirmed_by_user_id = driver_user_id
        loading.driver_confirmed_at = datetime.datetime.now()
        session.commit()
    return stock_document_id
