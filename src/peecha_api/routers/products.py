"""فهرست/جستجویِ کالا برایِ سفارش‌گیریِ موبایل -- رویِ همان
services/inventory_catalog.py موجود (بدونِ منطقِ تازه‌یِ کاتالوگ).
sync/pull هم فهرستِ کالا می‌دهد ولی بدونِ جستجو/فیلتر -- این‌جا برایِ
جستجویِ سریع در حینِ سفارش‌گیری (بارکد/کد/نام) است."""

from __future__ import annotations

import decimal

from fastapi import APIRouter, Depends, HTTPException, status

from peecha.services import detail_dimensions as dimensions_service
from peecha.services import inventory_catalog as catalog_service
from peecha.services import inventory_engine as engine_service
from peecha.services import inventory_locations as locations_service
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


@router.get("/catalog")
def catalog(warehouse_id: int | None = None, ctx: AuthContext = Depends(get_current_context)) -> dict:
    """طبقِ درخواستِ صریحِ کاربر («مشتری انتخاب میشه، کاتالوگِ کالا باز
    میشه که انواعِ فیلترها روش داره -- دسته‌بندی‌ها و برند -- و جستجویِ
    زنده و اسکنِ بارکد»): کلِ کاتالوگِ قابلِ‌فروش در یک درخواست (تا
    فیلتر/جستجو/بارکد همه رویِ گوشی و بدونِ رفت‌وبرگشتِ شبکه انجام
    شود) + موجودیِ انبارِ داده‌شده (در پخشِ گرم: انبارِ خودرو). کالایِ
    اصلیِ متغیردار حذف است (فقط متغیرهایش). قیمت این‌جا نیست -- هنگامِ
    افزودن به سبد با /pricing/resolve (قیمتِ همان مشتری) گرفته می‌شود."""
    if warehouse_id is not None and locations_service.get_warehouse(warehouse_id, ctx.company_id) is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="انبارِ انتخاب‌شده برایِ این شرکت معتبر نیست.")
    items = [it for it in catalog_service.list_items(ctx.company_id, active_only=True, transactable_only=True) if it.is_sellable]
    stock_by_item: dict[int, decimal.Decimal] = {}
    if warehouse_id is not None:
        for b in engine_service.list_balances(ctx.company_id, warehouse_id=warehouse_id):
            stock_by_item[b.item_id] = stock_by_item.get(b.item_id, decimal.Decimal(0)) + b.quantity_available
    used_categories = {it.category_id for it in items if it.category_id is not None}
    used_brands = {it.brand_id for it in items if it.brand_id is not None}
    # طبقِ درخواستِ صریحِ کاربر («عکسِ کالاهایِ تعریف‌شده در کاتالوگِ کالا
    # بیاد خیلی انگشتی»): همان عکسِ اصلیِ حسابِ تفصیلیِ کالا (تبِ «عکس‌ها و
    # فایل‌ها»یِ فرمِ کالایِ دسکتاپ) -- کوچک‌شده و Base64، در همین پاسخ
    # (بدونِ درخواستِ شبکه‌یِ جدا به‌ازایِ هر کالا و قابلِ‌کش‌شدنِ کاملِ آفلاین).
    item_dim_type_id = dimensions_service.get_specialized_dimension_type_id(ctx.company_id, dimensions_service.INVENTORY_ITEM_CODE)
    photo_thumbnails: dict[int, str] = {}
    if dimensions_service.get_group_photo_enabled(item_dim_type_id):
        photo_thumbnails = dimensions_service.get_photo_thumbnails_for_accounts(
            ctx.company_id, [it.item_detail_account_id for it in items]
        )
    return {
        "items": [
            {
                "item_id": it.item_id, "code": it.code, "name": it.name, "barcode": it.barcode, "sku": it.sku,
                "category_id": it.category_id, "brand_id": it.brand_id,
                "base_uom_id": it.base_uom_id, "base_uom_code": it.base_uom_code,
                "default_tax_percent": str(it.default_tax_percent) if it.default_tax_percent is not None else None,
                "stock_quantity": str(stock_by_item.get(it.item_id, decimal.Decimal(0))) if warehouse_id is not None else None,
                "photo_base64": photo_thumbnails.get(it.item_detail_account_id),
            }
            for it in items
        ],
        "categories": [
            {"category_id": c.category_id, "parent_category_id": c.parent_category_id, "name": c.name}
            for c in catalog_service.list_categories(ctx.company_id, active_only=True) if c.category_id in used_categories
        ],
        "brands": [
            {"brand_id": b.brand_id, "name": b.name}
            for b in catalog_service.list_brands(ctx.company_id, active_only=True) if b.brand_id in used_brands
        ],
    }
