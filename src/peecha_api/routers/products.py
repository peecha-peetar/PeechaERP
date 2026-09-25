"""فهرست/جستجویِ کالا برایِ سفارش‌گیریِ موبایل -- رویِ همان
services/inventory_catalog.py موجود (بدونِ منطقِ تازه‌یِ کاتالوگ).
sync/pull هم فهرستِ کالا می‌دهد ولی بدونِ جستجو/فیلتر -- این‌جا برایِ
جستجویِ سریع در حینِ سفارش‌گیری (بارکد/کد/نام) است."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from peecha.services import inventory_catalog as catalog_service
from peecha_api.deps import AuthContext, get_current_context

router = APIRouter(prefix="/products", tags=["products"])


@router.get("")
def list_products(q: str | None = None, ctx: AuthContext = Depends(get_current_context)) -> list[dict]:
    items = catalog_service.list_items(ctx.company_id, active_only=True, transactable_only=True)
    if q:
        needle = q.strip().lower()
        items = [
            it for it in items
            if needle in (it.code or "").lower()
            or needle in (it.name or "").lower()
            or needle in (it.barcode or "").lower()
        ]
    return [
        {
            "item_id": it.item_id, "code": it.code, "name": it.name, "barcode": it.barcode,
            "base_uom_id": it.base_uom_id, "base_uom_code": it.base_uom_code,
            "is_sellable": it.is_sellable, "default_tax_percent": str(it.default_tax_percent) if it.default_tax_percent is not None else None,
        }
        for it in items
    ]
