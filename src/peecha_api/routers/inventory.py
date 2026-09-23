"""موجودیِ کالا به‌تفکیکِ انبار -- رویِ همان
services/inventory_engine.get_item_stock_by_warehouse موجود (بدونِ
منطقِ تازه‌یِ محاسبه‌یِ موجودی)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from peecha.services import inventory_engine as engine_service
from peecha_api.deps import AuthContext, get_current_context

router = APIRouter(prefix="/inventory", tags=["inventory"])


@router.get("/{item_id}")
def get_item_stock(item_id: int, ctx: AuthContext = Depends(get_current_context)) -> list[dict]:
    rows = engine_service.get_item_stock_by_warehouse(ctx.company_id, item_id)
    return [
        {"warehouse_id": r.warehouse_id, "warehouse_name": r.warehouse_name, "quantity_on_hand": str(r.quantity_on_hand)}
        for r in rows
    ]
