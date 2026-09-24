"""موجودیِ کالا به‌تفکیکِ انبار -- رویِ همان
services/inventory_engine.get_item_stock_by_warehouse موجود (بدونِ
منطقِ تازه‌یِ محاسبه‌یِ موجودی)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from peecha.services import inventory_engine as engine_service
from peecha.services import inventory_locations as locations_service
from peecha_api.deps import AuthContext, get_current_context

router = APIRouter(prefix="/inventory", tags=["inventory"])


@router.get("/warehouses")
def list_warehouses(ctx: AuthContext = Depends(get_current_context)) -> list[dict]:
    """طبقِ باگِ واقعیِ کشف‌شده (R198، هم‌الگو با R196): اپِ موبایل قبلاً
    warehouse_id=1 را هاردکد می‌فرستاد که در بسیاری از شرکت‌ها اصلاً
    وجود ندارد (شکستِ کلیدِ خارجیِ commercial_documents_warehouse_id_fkey).
    این اندپوینت انبارهایِ واقعیِ همین شرکت را برمی‌گرداند تا موبایل
    یکی را (ترجیحاً انبارِ پیش‌فرض) انتخاب کند."""
    warehouses = locations_service.list_warehouses(ctx.company_id, active_only=True)
    return [
        {"warehouse_id": w.warehouse_id, "code": w.code, "name": w.name, "is_default": w.fields.is_default}
        for w in warehouses
    ]


@router.get("/{item_id}")
def get_item_stock(item_id: int, ctx: AuthContext = Depends(get_current_context)) -> list[dict]:
    rows = engine_service.get_item_stock_by_warehouse(ctx.company_id, item_id)
    return [
        {"warehouse_id": r.warehouse_id, "warehouse_name": r.warehouse_name, "quantity_on_hand": str(r.quantity_on_hand)}
        for r in rows
    ]
