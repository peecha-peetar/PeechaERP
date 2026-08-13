"""سرویسِ کاتالوگِ انبار — واحد/برند/تولیدکننده و «کالا».

طبقِ سندِ معماری: کالا موجودیتِ تازه‌ای نیست، تفصیلیِ سطحِ‌آخرِ گروهِ سیستمیِ
INVENTORY_ITEM است (acc.detail_accounts)؛ inv.items یک جدولِ اقماریِ
یک‌به‌یک است — دقیقاً هم‌الگو با hr.employees نسبت به تفصیلیِ گروهِ
PERSONNEL. منطقِ پل‌زدن این‌جاست (نه در detail_dimensions.py که عمداً
بی‌اطلاع از inv.* می‌ماند)."""

from __future__ import annotations

import datetime
import decimal
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import delete, func, select

from peecha.db.base import new_session
from peecha.db.models.inventory import (
    AssetDepreciationEntry,
    AssetDetail,
    Batch,
    BomHeader,
    BomLine,
    Brand,
    CostingMethod,
    CostLayer,
    CycleCountLine,
    Item,
    ItemCategory,
    ItemMedia,
    ItemSupplier,
    ItemUomConversion,
    ItemVariantValue,
    Manufacturer,
    ReorderPolicy,
    ReorderSuggestionAcknowledgement,
    RelatedItem,
    SerialNumber,
    StandardCost,
    StockDocumentLine,
    StockReservation,
    Uom,
)
from peecha.services import detail_dimensions as dimensions_service

ITEM_DIMENSION_CODE = "INVENTORY_ITEM"

_ITEM_KIND_CODES = (
    "GOOD", "SERVICE", "RAW_MATERIAL", "SEMI_FINISHED", "FINISHED_GOOD", "ASSET", "BUNDLE", "KIT",
)

_EXTENDED_ITEM_FIELD_KEYS = (
    "category_id", "default_warehouse_id", "barcode", "qr_code_data", "sku", "latin_name", "short_name",
    "country_of_origin", "length_cm", "width_cm", "height_cm", "package_type_code", "freight_class_code",
    "requires_qc", "qc_standard", "qc_test_spec", "qc_inspection_interval_days", "purchase_lead_time_days",
    "purchase_min_order_qty", "purchase_package_qty", "max_discount_percent", "sales_commission_percent",
    "warranty_months", "seo_title", "seo_url_slug", "seo_meta_description", "seo_meta_keywords",
    "website_category", "website_tags", "pos_shortcut_key", "pos_button_color", "pos_requires_weight",
    "pos_requires_serial",
)


def _extended_item_kwargs(fields: "ItemFields") -> dict[str, Any]:
    return {key: getattr(fields, key) for key in _EXTENDED_ITEM_FIELD_KEYS}


# ---------------------------------------------------------------------
# واحدِ اندازه‌گیری
# ---------------------------------------------------------------------
@dataclass
class UomRow:
    uom_id: int
    code: str
    name: str
    uom_type_code: str
    is_active: bool
    is_global: bool


def list_uoms(company_id: int, active_only: bool = False) -> list[UomRow]:
    with new_session() as session:
        query = select(Uom).where((Uom.company_id == company_id) | (Uom.company_id.is_(None)))
        if active_only:
            query = query.where(Uom.is_active)
        rows = session.scalars(query.order_by(Uom.code)).all()
        return [
            UomRow(r.uom_id, r.code, r.name, r.uom_type_code, r.is_active, r.company_id is None) for r in rows
        ]


def create_uom(company_id: int, code: str, name: str, uom_type_code: str) -> int:
    with new_session() as session:
        uom = Uom(company_id=company_id, code=code.strip(), name=name.strip(), uom_type_code=uom_type_code)
        session.add(uom)
        session.commit()
        return uom.uom_id


def update_uom(uom_id: int, company_id: int, code: str, name: str, uom_type_code: str, is_active: bool) -> None:
    with new_session() as session:
        uom = session.get(Uom, uom_id)
        if uom is None or uom.company_id != company_id:
            raise ValueError("واحدِ اندازه‌گیری نامعتبر است (فقط واحدهایِ اختصاصیِ همین شرکت قابلِ‌ویرایش‌اند).")
        uom.code = code.strip()
        uom.name = name.strip()
        uom.uom_type_code = uom_type_code
        uom.is_active = is_active
        session.commit()


def delete_uom(uom_id: int, company_id: int) -> None:
    with new_session() as session:
        uom = session.get(Uom, uom_id)
        if uom is None or uom.company_id != company_id:
            raise ValueError("واحدِ اندازه‌گیری نامعتبر است.")
        in_use = session.scalar(
            select(func.count()).select_from(Item).where(Item.base_uom_id == uom_id)
        ) or session.scalar(
            select(func.count()).select_from(ItemUomConversion).where(ItemUomConversion.uom_id == uom_id)
        )
        if in_use:
            raise ValueError("این واحد در تعریفِ کالاها استفاده شده و قابلِ‌حذف نیست.")
        session.delete(uom)
        session.commit()


# ---------------------------------------------------------------------
# برند / تولیدکننده
# ---------------------------------------------------------------------
@dataclass
class BrandRow:
    brand_id: int
    code: str
    name: str
    is_active: bool


def list_brands(company_id: int, active_only: bool = False) -> list[BrandRow]:
    with new_session() as session:
        query = select(Brand).where(Brand.company_id == company_id)
        if active_only:
            query = query.where(Brand.is_active)
        rows = session.scalars(query.order_by(Brand.code)).all()
        return [BrandRow(r.brand_id, r.code, r.name, r.is_active) for r in rows]


def create_brand(company_id: int, code: str, name: str) -> int:
    with new_session() as session:
        brand = Brand(company_id=company_id, code=code.strip(), name=name.strip())
        session.add(brand)
        session.commit()
        return brand.brand_id


def update_brand(brand_id: int, company_id: int, code: str, name: str, is_active: bool) -> None:
    with new_session() as session:
        brand = session.get(Brand, brand_id)
        if brand is None or brand.company_id != company_id:
            raise ValueError("برند نامعتبر است.")
        brand.code, brand.name, brand.is_active = code.strip(), name.strip(), is_active
        session.commit()


def delete_brand(brand_id: int, company_id: int) -> None:
    with new_session() as session:
        brand = session.get(Brand, brand_id)
        if brand is None or brand.company_id != company_id:
            raise ValueError("برند نامعتبر است.")
        if session.scalar(select(func.count()).select_from(Item).where(Item.brand_id == brand_id)):
            raise ValueError("این برند به کالایی وصل است و قابلِ‌حذف نیست.")
        session.delete(brand)
        session.commit()


@dataclass
class ManufacturerRow:
    manufacturer_id: int
    code: str
    name: str
    country_name: str | None
    is_active: bool


def list_manufacturers(company_id: int, active_only: bool = False) -> list[ManufacturerRow]:
    with new_session() as session:
        query = select(Manufacturer).where(Manufacturer.company_id == company_id)
        if active_only:
            query = query.where(Manufacturer.is_active)
        rows = session.scalars(query.order_by(Manufacturer.code)).all()
        return [ManufacturerRow(r.manufacturer_id, r.code, r.name, r.country_name, r.is_active) for r in rows]


def create_manufacturer(company_id: int, code: str, name: str, country_name: str | None = None) -> int:
    with new_session() as session:
        manufacturer = Manufacturer(
            company_id=company_id, code=code.strip(), name=name.strip(), country_name=(country_name or None)
        )
        session.add(manufacturer)
        session.commit()
        return manufacturer.manufacturer_id


def update_manufacturer(
    manufacturer_id: int, company_id: int, code: str, name: str, is_active: bool, country_name: str | None = None
) -> None:
    with new_session() as session:
        manufacturer = session.get(Manufacturer, manufacturer_id)
        if manufacturer is None or manufacturer.company_id != company_id:
            raise ValueError("تولیدکننده نامعتبر است.")
        manufacturer.code, manufacturer.name = code.strip(), name.strip()
        manufacturer.country_name, manufacturer.is_active = (country_name or None), is_active
        session.commit()


def delete_manufacturer(manufacturer_id: int, company_id: int) -> None:
    with new_session() as session:
        manufacturer = session.get(Manufacturer, manufacturer_id)
        if manufacturer is None or manufacturer.company_id != company_id:
            raise ValueError("تولیدکننده نامعتبر است.")
        if session.scalar(select(func.count()).select_from(Item).where(Item.manufacturer_id == manufacturer_id)):
            raise ValueError("این تولیدکننده به کالایی وصل است و قابلِ‌حذف نیست.")
        session.delete(manufacturer)
        session.commit()


# ---------------------------------------------------------------------
# روش‌هایِ قیمت‌گذاری (Lookup ثابتِ سیستمی)
# ---------------------------------------------------------------------
@dataclass
class CostingMethodRow:
    costing_method_id: int
    code: str


def list_costing_methods() -> list[CostingMethodRow]:
    with new_session() as session:
        rows = session.scalars(select(CostingMethod).order_by(CostingMethod.costing_method_id)).all()
        return [CostingMethodRow(r.costing_method_id, r.code) for r in rows]


# ---------------------------------------------------------------------
# کالا/خدمت — پل به تفصیلیِ گروهِ INVENTORY_ITEM
# ---------------------------------------------------------------------
@dataclass
class ItemRow:
    item_id: int
    item_detail_account_id: int
    code: str
    name: str | None
    is_active: bool
    item_kind_code: str
    base_uom_id: int
    base_uom_code: str = ""
    brand_id: int | None = None
    manufacturer_id: int | None = None
    variant_parent_item_id: int | None = None
    costing_method_code: str | None = None
    lifecycle_status_code: str = "ACTIVE"
    is_sellable: bool = True
    is_purchasable: bool = True
    is_stock_tracked: bool = True
    track_serial: bool = False
    track_batch: bool = False
    track_expiry: bool = False
    notes: str | None = None
    category_id: int | None = None
    default_warehouse_id: int | None = None
    barcode: str | None = None
    qr_code_data: str | None = None
    sku: str | None = None
    latin_name: str | None = None
    short_name: str | None = None
    country_of_origin: str | None = None
    length_cm: decimal.Decimal | None = None
    width_cm: decimal.Decimal | None = None
    height_cm: decimal.Decimal | None = None
    package_type_code: str | None = None
    freight_class_code: str | None = None
    requires_qc: bool = False
    qc_standard: str | None = None
    qc_test_spec: str | None = None
    qc_inspection_interval_days: int | None = None
    purchase_lead_time_days: int | None = None
    purchase_min_order_qty: decimal.Decimal | None = None
    purchase_package_qty: decimal.Decimal | None = None
    max_discount_percent: decimal.Decimal | None = None
    sales_commission_percent: decimal.Decimal | None = None
    warranty_months: int | None = None
    seo_title: str | None = None
    seo_url_slug: str | None = None
    seo_meta_description: str | None = None
    seo_meta_keywords: str | None = None
    website_category: str | None = None
    website_tags: str | None = None
    pos_shortcut_key: str | None = None
    pos_button_color: str | None = None
    pos_requires_weight: bool = False
    pos_requires_serial: bool = False


def _item_dimension_type_id(company_id: int) -> int:
    return dimensions_service.get_specialized_dimension_type_id(company_id, ITEM_DIMENSION_CODE)


def list_items(company_id: int, active_only: bool = False) -> list[ItemRow]:
    dimension_type_id = _item_dimension_type_id(company_id)
    detail_rows = {
        r.detail_account_id: r for r in dimensions_service.list_detail_accounts(company_id, dimension_type_id)
    }
    with new_session() as session:
        items = session.scalars(select(Item).where(Item.company_id == company_id)).all()
        uom_codes = {u.uom_id: u.code for u in session.scalars(select(Uom))}
        result: list[ItemRow] = []
        for it in items:
            detail = detail_rows.get(it.item_detail_account_id)
            if detail is None:
                continue
            if active_only and not detail.is_active:
                continue
            result.append(
                ItemRow(
                    item_id=it.item_id,
                    item_detail_account_id=it.item_detail_account_id,
                    code=detail.code,
                    name=detail.name,
                    is_active=detail.is_active,
                    item_kind_code=it.item_kind_code,
                    base_uom_id=it.base_uom_id,
                    base_uom_code=uom_codes.get(it.base_uom_id, ""),
                    brand_id=it.brand_id,
                    manufacturer_id=it.manufacturer_id,
                    variant_parent_item_id=it.variant_parent_item_id,
                    costing_method_code=it.costing_method_code,
                    lifecycle_status_code=it.lifecycle_status_code,
                    is_sellable=it.is_sellable,
                    is_purchasable=it.is_purchasable,
                    is_stock_tracked=it.is_stock_tracked,
                    track_serial=it.track_serial,
                    track_batch=it.track_batch,
                    track_expiry=it.track_expiry,
                    notes=it.notes,
                    **{key: getattr(it, key) for key in _EXTENDED_ITEM_FIELD_KEYS},
                )
            )
        result.sort(key=lambda r: r.code)
        return result


def get_item(item_id: int) -> Item | None:
    with new_session() as session:
        item = session.get(Item, item_id)
        if item is not None:
            session.expunge(item)
        return item


def get_item_by_detail_account_id(item_detail_account_id: int) -> Item | None:
    with new_session() as session:
        item = session.scalar(select(Item).where(Item.item_detail_account_id == item_detail_account_id))
        if item is not None:
            session.expunge(item)
        return item


def get_item_row_by_detail_account_id(company_id: int, item_detail_account_id: int) -> ItemRow | None:
    """برایِ پلِ ادغام با detail_dimensions.py: از رویِ تفصیلیِ سطحِ‌آخرِ
    گروهِ INVENTORY_ITEM، ردیفِ کاملِ کالا (اگر موجود باشد) را برمی‌گرداند —
    گره‌هایِ میانیِ گروه‌بندی (که ردیفِ inv.items ندارند) None می‌گیرند."""
    return next(
        (r for r in list_items(company_id) if r.item_detail_account_id == item_detail_account_id), None
    )


@dataclass
class ItemFields:
    item_kind_code: str
    base_uom_id: int
    brand_id: int | None = None
    manufacturer_id: int | None = None
    variant_parent_item_id: int | None = None
    costing_method_code: str | None = None
    is_sellable: bool = True
    is_purchasable: bool = True
    is_stock_tracked: bool = True
    track_serial: bool = False
    track_batch: bool = False
    track_expiry: bool = False
    shelf_life_days: int | None = None
    weight_kg: decimal.Decimal | None = None
    volume_m3: decimal.Decimal | None = None
    notes: str | None = None
    extra_fields: dict[str, Any] = field(default_factory=dict)
    category_id: int | None = None
    default_warehouse_id: int | None = None
    barcode: str | None = None
    qr_code_data: str | None = None
    sku: str | None = None
    latin_name: str | None = None
    short_name: str | None = None
    country_of_origin: str | None = None
    length_cm: decimal.Decimal | None = None
    width_cm: decimal.Decimal | None = None
    height_cm: decimal.Decimal | None = None
    package_type_code: str | None = None
    freight_class_code: str | None = None
    requires_qc: bool = False
    qc_standard: str | None = None
    qc_test_spec: str | None = None
    qc_inspection_interval_days: int | None = None
    purchase_lead_time_days: int | None = None
    purchase_min_order_qty: decimal.Decimal | None = None
    purchase_package_qty: decimal.Decimal | None = None
    max_discount_percent: decimal.Decimal | None = None
    sales_commission_percent: decimal.Decimal | None = None
    warranty_months: int | None = None
    seo_title: str | None = None
    seo_url_slug: str | None = None
    seo_meta_description: str | None = None
    seo_meta_keywords: str | None = None
    website_category: str | None = None
    website_tags: str | None = None
    pos_shortcut_key: str | None = None
    pos_button_color: str | None = None
    pos_requires_weight: bool = False
    pos_requires_serial: bool = False


def _validate_item_fields(fields: ItemFields) -> None:
    if fields.item_kind_code not in _ITEM_KIND_CODES:
        raise ValueError("نوعِ کالا نامعتبر است.")
    if fields.item_kind_code == "SERVICE" and fields.is_stock_tracked:
        raise ValueError("خدمت نمی‌تواند موجودی‌محور باشد.")
    if fields.track_expiry and not fields.track_batch:
        raise ValueError("ردیابیِ انقضا نیازمندِ فعال‌بودنِ ردیابیِ بچ است.")


def create_item(
    company_id: int, code: str, name: str, fields: ItemFields, parent_detail_account_id: int | None = None
) -> int:
    """ساختِ کالا: اول تفصیلیِ سطحِ‌آخرِ گروهِ INVENTORY_ITEM ساخته می‌شود،
    سپس ردیفِ اقماریِ inv.items با همان item_detail_account_id — دقیقاً
    هم‌الگو با hr.create_personnel_detail_account نسبت به hr.employees.

    این تابع فقط برایِ رکوردهایِ واقعاً سطحِ‌آخر صدا زده می‌شود؛ گره‌هایِ
    میانیِ گروه‌بندیِ کالا (سطوحِ ۱ تا max_level-1) مستقیماً با
    dimensions_service.create_detail_account در detail_dimensions.py
    ساخته می‌شوند و به این تابع نیازی ندارند."""
    _validate_item_fields(fields)
    dimension_type_id = _item_dimension_type_id(company_id)
    detail_account = dimensions_service.create_detail_account(
        company_id, dimension_type_id, code, name, parent_detail_account_id=parent_detail_account_id
    )
    with new_session() as session:
        item = Item(
            company_id=company_id,
            item_detail_account_id=detail_account.detail_account_id,
            item_kind_code=fields.item_kind_code,
            base_uom_id=fields.base_uom_id,
            brand_id=fields.brand_id,
            manufacturer_id=fields.manufacturer_id,
            variant_parent_item_id=fields.variant_parent_item_id,
            costing_method_code=fields.costing_method_code,
            is_sellable=fields.is_sellable,
            is_purchasable=fields.is_purchasable,
            is_stock_tracked=fields.is_stock_tracked,
            track_serial=fields.track_serial,
            track_batch=fields.track_batch,
            track_expiry=fields.track_expiry,
            shelf_life_days=fields.shelf_life_days,
            weight_kg=fields.weight_kg,
            volume_m3=fields.volume_m3,
            notes=fields.notes,
            extra_fields=dict(fields.extra_fields),
            **_extended_item_kwargs(fields),
        )
        session.add(item)
        session.commit()
        return item.item_id


def update_item(
    item_id: int, company_id: int, code: str, name: str, is_active: bool, lifecycle_status_code: str, fields: ItemFields
) -> None:
    _validate_item_fields(fields)
    if lifecycle_status_code not in ("DRAFT", "ACTIVE", "DISCONTINUED"):
        raise ValueError("وضعیتِ چرخهٔ‌عمر نامعتبر است.")

    from peecha.services import inventory_engine as engine_service

    with new_session() as session:
        item = session.get(Item, item_id)
        if item is None or item.company_id != company_id:
            raise ValueError("کالا نامعتبر است.")

        # طبقِ مرحلهٔ ۸ (۱۰۸): واحدِ پایه/روشِ قیمت‌گذاری فقط با موجودیِ صفر
        # در همهٔ انبارها قابلِ‌تغییر است — نه صرفِ نبودِ سابقهٔ حرکت.
        has_open_balance = (
            (item.base_uom_id != fields.base_uom_id or item.costing_method_code != fields.costing_method_code)
            and engine_service.get_item_total_on_hand(item_id) != 0
        )
        if has_open_balance and item.base_uom_id != fields.base_uom_id:
            raise ValueError("این کالا در انباری موجودی دارد؛ واحدِ پایه فقط با موجودیِ صفر قابلِ‌تغییر است.")
        if has_open_balance and item.costing_method_code != fields.costing_method_code:
            raise ValueError("این کالا در انباری موجودی دارد؛ روشِ قیمت‌گذاری فقط با موجودیِ صفر قابلِ‌تغییر است.")

        item.item_kind_code = fields.item_kind_code
        item.base_uom_id = fields.base_uom_id
        item.brand_id = fields.brand_id
        item.manufacturer_id = fields.manufacturer_id
        item.variant_parent_item_id = fields.variant_parent_item_id
        item.costing_method_code = fields.costing_method_code
        item.lifecycle_status_code = lifecycle_status_code
        item.is_sellable = fields.is_sellable
        item.is_purchasable = fields.is_purchasable
        item.is_stock_tracked = fields.is_stock_tracked
        item.track_serial = fields.track_serial
        item.track_batch = fields.track_batch
        item.track_expiry = fields.track_expiry
        item.shelf_life_days = fields.shelf_life_days
        item.weight_kg = fields.weight_kg
        item.volume_m3 = fields.volume_m3
        item.notes = fields.notes
        item.extra_fields = dict(fields.extra_fields)
        for key, value in _extended_item_kwargs(fields).items():
            setattr(item, key, value)
        item.updated_at = datetime.datetime.now(datetime.timezone.utc)
        detail_account_id = item.item_detail_account_id
        session.commit()

    dimensions_service.update_detail_account(detail_account_id, company_id, code, is_active, name)


def _item_has_stock_movements(session, item_id: int) -> bool:
    from peecha.db.models.inventory import StockLedger

    return bool(session.scalar(select(func.count()).select_from(StockLedger).where(StockLedger.item_id == item_id)))


def delete_item(item_id: int, company_id: int) -> None:
    """طبقِ رفعِ باگِ کشف‌شده: پیش‌تر این تابع فقط سابقهٔ حرکتِ انبار را چک
    می‌کرد و مستقیماً ردیفِ inv.items را حذف می‌کرد — اگر کالا زیرجدول‌هایِ
    تعریفیِ خودش را داشت (asset_details/bom_headers/item_suppliers/...)،
    حذف با نقضِ کلیدِ خارجی شکست می‌خورد. حالا:
    ۱) اگر کالا در جایی که واقعاً «استفاده» محسوب می‌شود (جزءِ فهرستِ
       موادِ اولیهٔ کالایِ دیگر، والدِ تنوعِ کالاهایِ دیگر، رزرو/بچ/سریال/
       لایهٔ‌بها/انبارگردانیِ فعال) نقش داشته باشد، حذف رد می‌شود.
    ۲) در غیرِ این صورت، زیرجدول‌هایِ تعریفیِ خودِ همین کالا (که فقط با
       همین کالا معنا دارند، نه سابقهٔ عملیاتیِ مستقل) پیش از حذفِ خودِ
       کالا پاک می‌شوند."""
    with new_session() as session:
        item = session.get(Item, item_id)
        if item is None or item.company_id != company_id:
            raise ValueError("کالا نامعتبر است.")
        if _item_has_stock_movements(session, item_id):
            raise ValueError("این کالا سابقهٔ حرکتِ انبار دارد و قابلِ‌حذف نیست — به‌جایِ حذف، وضعیتِ آن را «متوقف‌شده» کنید.")
        if session.scalar(
            select(func.count()).select_from(StockDocumentLine).where(StockDocumentLine.item_id == item_id)
        ):
            raise ValueError("این کالا در سندی استفاده شده و قابلِ‌حذف نیست.")
        if session.scalar(select(func.count()).select_from(BomLine).where(BomLine.component_item_id == item_id)):
            raise ValueError("این کالا به‌عنوانِ جزءِ فهرستِ موادِ اولیهٔ کالایِ دیگری استفاده شده و قابلِ‌حذف نیست.")
        if session.scalar(select(func.count()).select_from(Item).where(Item.variant_parent_item_id == item_id)):
            raise ValueError("این کالا والدِ یک یا چند تنوعِ کالاست و قابلِ‌حذف نیست.")
        if session.scalar(select(func.count()).select_from(StockReservation).where(StockReservation.item_id == item_id)):
            raise ValueError("این کالا رزروِ موجودی دارد و قابلِ‌حذف نیست.")
        if session.scalar(select(func.count()).select_from(Batch).where(Batch.item_id == item_id)):
            raise ValueError("این کالا سابقهٔ بچ دارد و قابلِ‌حذف نیست.")
        if session.scalar(select(func.count()).select_from(SerialNumber).where(SerialNumber.item_id == item_id)):
            raise ValueError("این کالا سابقهٔ سریال دارد و قابلِ‌حذف نیست.")
        if session.scalar(select(func.count()).select_from(CostLayer).where(CostLayer.item_id == item_id)):
            raise ValueError("این کالا سابقهٔ لایهٔ بهایِ تمام‌شده دارد و قابلِ‌حذف نیست.")
        if session.scalar(select(func.count()).select_from(CycleCountLine).where(CycleCountLine.item_id == item_id)):
            raise ValueError("این کالا در انبارگردانی استفاده شده و قابلِ‌حذف نیست.")

        bom_ids = session.scalars(select(BomHeader.bom_id).where(BomHeader.finished_item_id == item_id)).all()
        if bom_ids:
            session.execute(delete(BomLine).where(BomLine.bom_id.in_(bom_ids)))
            session.execute(delete(BomHeader).where(BomHeader.bom_id.in_(bom_ids)))
        session.execute(delete(AssetDepreciationEntry).where(AssetDepreciationEntry.item_id == item_id))
        session.execute(delete(AssetDetail).where(AssetDetail.item_id == item_id))
        session.execute(delete(ItemUomConversion).where(ItemUomConversion.item_id == item_id))
        session.execute(delete(ItemVariantValue).where(ItemVariantValue.item_id == item_id))
        session.execute(delete(ItemSupplier).where(ItemSupplier.item_id == item_id))
        session.execute(delete(ItemMedia).where(ItemMedia.item_id == item_id))
        session.execute(
            delete(RelatedItem).where((RelatedItem.item_id == item_id) | (RelatedItem.related_item_id == item_id))
        )
        session.execute(delete(StandardCost).where(StandardCost.item_id == item_id))
        session.execute(delete(ReorderPolicy).where(ReorderPolicy.item_id == item_id))
        session.execute(delete(ReorderSuggestionAcknowledgement).where(ReorderSuggestionAcknowledgement.item_id == item_id))

        detail_account_id = item.item_detail_account_id
        session.delete(item)
        session.commit()
    dimensions_service.delete_detail_account(detail_account_id, company_id)


# ---------------------------------------------------------------------
# تبدیلِ واحد
# ---------------------------------------------------------------------
@dataclass
class UomConversionRow:
    conversion_id: int
    uom_id: int
    uom_code: str
    conversion_factor: decimal.Decimal
    is_purchase_default: bool
    is_sales_default: bool


def list_item_uom_conversions(item_id: int) -> list[UomConversionRow]:
    with new_session() as session:
        rows = session.scalars(
            select(ItemUomConversion).where(ItemUomConversion.item_id == item_id)
        ).all()
        uom_codes = {u.uom_id: u.code for u in session.scalars(select(Uom))}
        return [
            UomConversionRow(
                r.conversion_id, r.uom_id, uom_codes.get(r.uom_id, ""), r.conversion_factor,
                r.is_purchase_default, r.is_sales_default,
            )
            for r in rows
        ]


def set_item_uom_conversion(
    item_id: int, uom_id: int, conversion_factor: decimal.Decimal,
    is_purchase_default: bool = False, is_sales_default: bool = False,
) -> None:
    if conversion_factor <= 0:
        raise ValueError("ضریبِ تبدیل باید بزرگ‌تر از صفر باشد.")
    with new_session() as session:
        existing = session.scalar(
            select(ItemUomConversion).where(
                ItemUomConversion.item_id == item_id, ItemUomConversion.uom_id == uom_id
            )
        )
        if existing is not None:
            existing.conversion_factor = conversion_factor
            existing.is_purchase_default = is_purchase_default
            existing.is_sales_default = is_sales_default
        else:
            session.add(
                ItemUomConversion(
                    item_id=item_id, uom_id=uom_id, conversion_factor=conversion_factor,
                    is_purchase_default=is_purchase_default, is_sales_default=is_sales_default,
                )
            )
        session.commit()


def delete_item_uom_conversion(conversion_id: int, item_id: int) -> None:
    with new_session() as session:
        row = session.get(ItemUomConversion, conversion_id)
        if row is None or row.item_id != item_id:
            raise ValueError("ردیفِ تبدیلِ واحد نامعتبر است.")
        session.delete(row)
        session.commit()


# ---------------------------------------------------------------------
# کالاهایِ جایگزین/مکمل
# ---------------------------------------------------------------------
def list_related_items(item_id: int) -> list[tuple[int, str]]:
    with new_session() as session:
        rows = session.scalars(select(RelatedItem).where(RelatedItem.item_id == item_id)).all()
        return [(r.related_item_id, r.relation_type_code) for r in rows]


def add_related_item(item_id: int, related_item_id: int, relation_type_code: str) -> None:
    if relation_type_code not in ("SUBSTITUTE", "COMPLEMENTARY"):
        raise ValueError("نوعِ ارتباط نامعتبر است.")
    if item_id == related_item_id:
        raise ValueError("یک کالا نمی‌تواند جایگزین/مکملِ خودش باشد.")
    with new_session() as session:
        session.add(RelatedItem(item_id=item_id, related_item_id=related_item_id, relation_type_code=relation_type_code))
        session.commit()


def remove_related_item(related_item_link_id: int) -> None:
    with new_session() as session:
        row = session.get(RelatedItem, related_item_link_id)
        if row is not None:
            session.delete(row)
            session.commit()


# ---------------------------------------------------------------------
# دسته‌بندیِ کالا — بخشِ ۱ (گروه/زیرگروه)
# ---------------------------------------------------------------------
@dataclass
class ItemCategoryRow:
    category_id: int
    parent_category_id: int | None
    code: str
    name: str
    is_active: bool


def list_categories(company_id: int, active_only: bool = False) -> list[ItemCategoryRow]:
    with new_session() as session:
        query = select(ItemCategory).where(ItemCategory.company_id == company_id)
        if active_only:
            query = query.where(ItemCategory.is_active)
        rows = session.scalars(query.order_by(ItemCategory.code)).all()
        return [
            ItemCategoryRow(r.category_id, r.parent_category_id, r.code, r.name, r.is_active) for r in rows
        ]


def create_category(company_id: int, code: str, name: str, parent_category_id: int | None = None) -> int:
    with new_session() as session:
        if session.scalar(
            select(func.count()).select_from(ItemCategory).where(
                ItemCategory.company_id == company_id, ItemCategory.code == code.strip()
            )
        ):
            raise ValueError("این کد قبلاً برایِ دسته‌بندیِ دیگری استفاده شده است.")
        category = ItemCategory(
            company_id=company_id, parent_category_id=parent_category_id, code=code.strip(), name=name.strip()
        )
        session.add(category)
        session.commit()
        return category.category_id


def update_category(category_id: int, company_id: int, name: str, is_active: bool) -> None:
    with new_session() as session:
        category = session.get(ItemCategory, category_id)
        if category is None or category.company_id != company_id:
            raise ValueError("دسته‌بندی نامعتبر است.")
        category.name = name.strip()
        category.is_active = is_active
        session.commit()


def delete_category(category_id: int, company_id: int) -> None:
    with new_session() as session:
        category = session.get(ItemCategory, category_id)
        if category is None or category.company_id != company_id:
            raise ValueError("دسته‌بندی نامعتبر است.")
        if session.scalar(
            select(func.count()).select_from(ItemCategory).where(ItemCategory.parent_category_id == category_id)
        ):
            raise ValueError("این دسته زیرگروه دارد و قابلِ‌حذف نیست.")
        if session.scalar(select(func.count()).select_from(Item).where(Item.category_id == category_id)):
            raise ValueError("این دسته به کالایی وصل است و قابلِ‌حذف نیست.")
        session.delete(category)
        session.commit()
