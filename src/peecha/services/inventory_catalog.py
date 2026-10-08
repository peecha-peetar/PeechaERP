"""سرویس کاتالوگ انبار — واحد/برند/تولیدکننده و «کالا».

طبق سند معماری: کالا موجودیت تازه‌ای نیست، تفصیلی سطح‌آخر گروه سیستمی
INVENTORY_ITEM است (acc.detail_accounts)؛ inv.items یک جدول اقماری
یک‌به‌یک است — دقیقاً هم‌الگو با hr.employees نسبت به تفصیلی گروه
PERSONNEL. منطق پل‌زدن این‌جاست (نه در detail_dimensions.py که عمداً
بی‌اطلاع از inv.* می‌ماند)."""

from __future__ import annotations

import datetime
import decimal
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import delete, func, select

from peecha.db.base import new_session
from peecha.db.models.commercial import PriceListItem
from peecha.db.models.core import Company
from peecha.db.models.inventory import (
    Brand,
    CostingMethod,
    Item,
    ItemCategory,
    ItemUomConversion,
    ItemVariant,
    Manufacturer,
    RelatedItem,
    StockDocumentLine,
    Uom,
    Warehouse,
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
    "default_tax_percent",
    "warranty_months", "seo_title", "seo_url_slug", "seo_meta_description", "seo_meta_keywords",
    "website_category", "website_tags", "pos_shortcut_key", "pos_button_color", "pos_requires_weight",
    "pos_requires_serial", "pos_menu_group_id", "ecommerce_stock_mode",
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
    decimal_places: int = 2
    symbol: str | None = None
    base_uom_id: int | None = None
    conversion_factor: decimal.Decimal = decimal.Decimal(1)
    allow_decimal: bool = True
    is_system: bool = False
    description: str | None = None


# طبقِ گزارشِ صریح: واحدِ شمارشی (COUNT) و بسته‌بندی پیش‌فرض عددِ صحیح است،
# بقیه‌یِ انواع دو رقمِ اعشار — هنگامِ ساختِ واحدِ تازه (بدونِ مقدارِ صریح).
_DEFAULT_DECIMAL_PLACES_BY_UOM_TYPE = {"COUNT": 0, "PACKAGING": 0}
UOM_TYPE_CODES = ("COUNT", "WEIGHT", "LENGTH", "AREA", "VOLUME", "TIME", "PACKAGING", "OTHER")


def list_uoms(company_id: int, active_only: bool = False) -> list[UomRow]:
    with new_session() as session:
        query = select(Uom).where((Uom.company_id == company_id) | (Uom.company_id.is_(None)))
        if active_only:
            query = query.where(Uom.is_active)
        rows = session.scalars(query.order_by(Uom.code)).all()
        return [
            UomRow(
                r.uom_id, r.code, r.name, r.uom_type_code, r.is_active, r.company_id is None, r.decimal_places,
                r.symbol, r.base_uom_id, r.conversion_factor, r.allow_decimal, r.is_system, r.description,
            )
            for r in rows
        ]


def _validate_uom_master(
    session, company_id: int, uom_type_code: str, decimal_places: int, base_uom_id: int | None,
    conversion_factor: decimal.Decimal, self_uom_id: int | None = None,
) -> None:
    if uom_type_code not in UOM_TYPE_CODES:
        raise ValueError("نوع واحد نامعتبر است.")
    if not (0 <= decimal_places <= 6):
        raise ValueError("تعداد اعشار باید بین ۰ تا ۶ باشد.")
    if conversion_factor is None or decimal.Decimal(conversion_factor) <= 0:
        raise ValueError("ضریب تبدیل باید بزرگ‌تر از صفر باشد.")
    if base_uom_id is not None:
        if base_uom_id == self_uom_id:
            raise ValueError("واحد نمی‌تواند واحد پایهٔ خودش باشد.")
        base = session.get(Uom, base_uom_id)
        if base is None or (base.company_id is not None and base.company_id != company_id):
            raise ValueError("واحد پایه نامعتبر است.")
        if base.uom_type_code != uom_type_code and uom_type_code != "PACKAGING":
            raise ValueError("واحد پایه باید هم‌نوع با همین واحد باشد (مثلاً کیلوگرم ← گرم).")


def create_uom(
    company_id: int, code: str, name: str, uom_type_code: str, decimal_places: int | None = None, *,
    symbol: str | None = None, base_uom_id: int | None = None, conversion_factor: decimal.Decimal = decimal.Decimal(1),
    allow_decimal: bool | None = None, description: str | None = None,
) -> int:
    if decimal_places is None:
        decimal_places = _DEFAULT_DECIMAL_PLACES_BY_UOM_TYPE.get(uom_type_code, 2)
    if not code.strip() or not name.strip():
        raise ValueError("کد و نام واحد الزامی است.")
    with new_session() as session:
        _validate_uom_master(session, company_id, uom_type_code, decimal_places, base_uom_id, conversion_factor)
        if allow_decimal is None:
            allow_decimal = decimal_places > 0
        uom = Uom(
            company_id=company_id, code=code.strip(), name=name.strip(), uom_type_code=uom_type_code,
            decimal_places=decimal_places if allow_decimal else 0, symbol=(symbol or None), base_uom_id=base_uom_id,
            conversion_factor=decimal.Decimal(conversion_factor), allow_decimal=allow_decimal,
            description=(description or None),
        )
        session.add(uom)
        session.commit()
        from peecha import decimals

        decimals.invalidate()
        return uom.uom_id


def update_uom(
    uom_id: int, company_id: int, code: str, name: str, uom_type_code: str, is_active: bool, decimal_places: int, *,
    symbol: str | None = None, base_uom_id: int | None = None, conversion_factor: decimal.Decimal | None = None,
    allow_decimal: bool | None = None, description: str | None = None,
) -> None:
    with new_session() as session:
        uom = session.get(Uom, uom_id)
        if uom is None or uom.company_id != company_id:
            raise ValueError("واحد اندازه‌گیری نامعتبر است (فقط واحدهای اختصاصی همین شرکت قابل‌ویرایش‌اند).")
        factor = decimal.Decimal(conversion_factor) if conversion_factor is not None else uom.conversion_factor
        _validate_uom_master(session, company_id, uom_type_code, decimal_places, base_uom_id, factor, uom_id)
        if allow_decimal is None:
            allow_decimal = decimal_places > 0
        uom.code = code.strip()
        uom.name = name.strip()
        uom.uom_type_code = uom_type_code
        uom.is_active = is_active
        uom.decimal_places = decimal_places if allow_decimal else 0
        uom.allow_decimal = allow_decimal
        uom.symbol = symbol or None
        uom.base_uom_id = base_uom_id
        uom.conversion_factor = factor
        uom.description = description or None
        uom.updated_at = func.now()
        session.commit()
        from peecha import decimals

        decimals.invalidate()


def _uom_in_use(session, uom_id: int) -> bool:
    from peecha.db.models.commercial import CommercialDocumentLine, PriceListItem
    from peecha.db.models.inventory import StockDocumentLine

    if session.scalar(select(func.count()).select_from(Item).where(Item.base_uom_id == uom_id)):
        return True
    for model in (ItemUomConversion, CommercialDocumentLine, StockDocumentLine, PriceListItem):
        if session.scalar(select(func.count()).select_from(model).where(model.uom_id == uom_id)):
            return True
    return False


def delete_uom(uom_id: int, company_id: int) -> str:
    """طبق سیستم واحد (R225): واحد استفاده‌شده هرگز حذف سخت نمی‌شود --
    فقط غیرفعال (برای سند تازه قابل‌انتخاب نیست؛ اسناد قبلی دست‌نخورده).
    خروجی: DELETED یا DEACTIVATED."""
    with new_session() as session:
        uom = session.get(Uom, uom_id)
        if uom is None or uom.company_id != company_id:
            raise ValueError("واحد اندازه‌گیری نامعتبر است.")
        if _uom_in_use(session, uom_id):
            uom.is_active = False
            session.commit()
            return "DEACTIVATED"
        session.delete(uom)
        session.commit()
        return "DELETED"


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
            raise ValueError("این برند به کالایی وصل است و قابل‌حذف نیست.")
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
            raise ValueError("این تولیدکننده به کالایی وصل است و قابل‌حذف نیست.")
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
        from peecha.services.costing.engine import NOT_YET_AVAILABLE

        return [CostingMethodRow(r.costing_method_id, r.code) for r in rows if r.code not in NOT_YET_AVAILABLE]


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
    # طبقِ رفعِ باگِ واقعی («کالای اصلی که متغیر داره اصلا نباید در هیچ
    # مرحله انتخاب و مقدار بگیره»): خودِ کالای اصلی/الگو -- که یک یا چند
    # متغیرِ زیرمجموعه دارد -- هیچ‌وقت قابلِ‌فروش/انتقال/موجودی‌گیریِ
    # مستقیم نیست؛ فقط متغیرهایش تراکنش‌پذیرند.
    has_variants: bool = False
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
    default_tax_percent: decimal.Decimal | None = None
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
    pos_menu_group_id: int | None = None
    ecommerce_stock_mode: str = "DATABASE"


def _item_dimension_type_id(company_id: int) -> int:
    return dimensions_service.get_specialized_dimension_type_id(company_id, ITEM_DIMENSION_CODE)


def list_items(company_id: int, active_only: bool = False, transactable_only: bool = False) -> list[ItemRow]:
    """طبق رفع باگ واقعی («کالای اصلی که متغیر داره اصلا نباید در هیچ
    مرحله انتخاب و مقدار بگیره»): پارامتر transactable_only را برای
    هر جایی که کاربر می‌خواهد یک کالا را روی یک سند/تراکنش انتخاب کند
    (فروش، خرید، بارگیری خودرو، سند انبار، POS، همگام‌سازی موبایل...)
    True بدهید — کالاهای اصلی/الگو (has_variants=True) حذف می‌شوند،
    چون خود آن‌ها موجودی/فروش ندارند و فقط متغیرهایشان معنا دارند.
    برای صفحات مدیریت کاتالوگ (فهرست کالاها/متغیرها) این پارامتر
    نباید ست شود — کالای اصلی هم باید در آن‌جا قابل‌دیدن/ویرایش باشد."""
    dimension_type_id = _item_dimension_type_id(company_id)
    detail_rows = {
        r.detail_account_id: r for r in dimensions_service.list_detail_accounts(company_id, dimension_type_id)
    }
    with new_session() as session:
        items = session.scalars(select(Item).where(Item.company_id == company_id)).all()
        uom_codes = {u.uom_id: u.code for u in session.scalars(select(Uom))}
        # طبقِ درخواستِ صریح («متغیرها دیگر بعنوانِ تفصیلی معرفی نشوند، در
        # یک جدولِ مستقل با کدبندیِ متفاوت ذخیره شوند»): کدِ نمایشیِ یک
        # متغیر دیگر همان کدِ تفصیلیِ فنیِ زیرینش نیست -- از inv.item_
        # variants می‌آید. برایِ کالاهایِ عادی/اصلی (که در این جدول ردیفی
        # ندارند) دقیقاً مثلِ قبل از رویِ خودِ تفصیلی خوانده می‌شود.
        variant_codes = {v.item_id: v.variant_code for v in session.scalars(select(ItemVariant))}
        parent_ids = {it.variant_parent_item_id for it in items if it.variant_parent_item_id is not None}
        result: list[ItemRow] = []
        for it in items:
            detail = detail_rows.get(it.item_detail_account_id)
            if detail is None:
                continue
            if active_only and not detail.is_active:
                continue
            has_variants = it.item_id in parent_ids
            if transactable_only and has_variants:
                continue
            result.append(
                ItemRow(
                    item_id=it.item_id,
                    item_detail_account_id=it.item_detail_account_id,
                    code=variant_codes.get(it.item_id, detail.code),
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
                    has_variants=has_variants,
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
    """برای پل ادغام با detail_dimensions.py: از روی تفصیلی سطح‌آخر
    گروه INVENTORY_ITEM، ردیف کامل کالا (اگر موجود باشد) را برمی‌گرداند —
    گره‌های میانی گروه‌بندی (که ردیف inv.items ندارند) None می‌گیرند."""
    return next(
        (r for r in list_items(company_id) if r.item_detail_account_id == item_detail_account_id), None
    )


def resolve_default_tax_percent(company_id: int, item_id: int, warehouse_id: int | None = None) -> decimal.Decimal:
    """طبق درخواست صریح کاربر («سیاست محاسبهٔ مالیات: اگر روی تنظیمات
    شرکت بود برای همه لحاظ کند، اگر شرکت تنظیم نداشت روی انبار، و اگر
    انبار نداشت روی کالا نگاه کند»): اولویت — اول تنظیمات کلی شرکت
    (Company.default_tax_percent)، اگر خالی بود انبار (Warehouse.
    default_tax_percent)، اگر آن هم خالی بود خود کالا (Item.
    default_tax_percent)، در نهایت صفر."""
    with new_session() as session:
        company = session.get(Company, company_id)
        if company is not None and company.default_tax_percent is not None:
            return company.default_tax_percent
        if warehouse_id is not None:
            warehouse = session.get(Warehouse, warehouse_id)
            if warehouse is not None and warehouse.default_tax_percent is not None:
                return warehouse.default_tax_percent
        item = session.get(Item, item_id)
        if item is not None and item.default_tax_percent is not None:
            return item.default_tax_percent
        return decimal.Decimal(0)


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
    default_tax_percent: decimal.Decimal | None = None
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
    pos_menu_group_id: int | None = None
    ecommerce_stock_mode: str = "DATABASE"


def _validate_item_fields(fields: ItemFields) -> None:
    if fields.item_kind_code not in _ITEM_KIND_CODES:
        raise ValueError("نوع کالا نامعتبر است.")
    if fields.item_kind_code == "SERVICE" and fields.is_stock_tracked:
        raise ValueError("خدمت نمی‌تواند موجودی‌محور باشد.")
    if fields.track_expiry and not fields.track_batch:
        raise ValueError("ردیابی انقضا نیازمند فعال‌بودن ردیابی بچ است.")
    if fields.ecommerce_stock_mode not in ("DATABASE", "ALWAYS_IN_STOCK", "OUT_OF_STOCK"):
        raise ValueError("حالت موجودی فروش اینترنتی نامعتبر است.")


def create_item(
    company_id: int, code: str, name: str, fields: ItemFields, parent_detail_account_id: int | None = None
) -> int:
    """ساخت کالا: اول تفصیلی سطح‌آخر گروه INVENTORY_ITEM ساخته می‌شود،
    سپس ردیف اقماری inv.items با همان item_detail_account_id — دقیقاً
    هم‌الگو با hr.create_personnel_detail_account نسبت به hr.employees.

    این تابع فقط برای رکوردهای واقعاً سطح‌آخر صدا زده می‌شود؛ گره‌های
    میانی گروه‌بندی کالا (سطوح ۱ تا max_level-1) مستقیماً با
    dimensions_service.create_detail_account در detail_dimensions.py
    ساخته می‌شوند و به این تابع نیازی ندارند."""
    _validate_item_fields(fields)
    from peecha.services import unit_conversion as uc

    uc.assert_barcode_available(company_id, fields.barcode)
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
        session.flush()
        uc.ensure_base_unit(session, item)
        session.commit()
        item_id = item.item_id
    if fields.barcode:
        uc.set_item_base_barcode(company_id, item_id, fields.barcode)
    return item_id


def bulk_set_brand_category(company_id: int, item_ids: list[int], *, set_brand: bool = False, brand_id: int | None = None, set_category: bool = False, category_id: int | None = None) -> int:
    """طبق درخواست صریح (پورت «Category & Brand Studio» PeechaSync): تخصیص
    گروهی دسته/برند به چند کالا در یک اقدام — به‌جای بازکردن تک‌تک
    فرم کالا. set_brand/set_category جدا از خود برند/دسته است تا کاربر
    بتواند فقط یکی از این دو را تغییر دهد و «بدون برند»/«بدون دسته»
    (یعنی None) هم یک انتخاب معتبر باشد."""
    if not set_brand and not set_category:
        return 0
    with new_session() as session:
        items = session.scalars(
            select(Item).where(Item.company_id == company_id, Item.item_id.in_(item_ids))
        ).all()
        for item in items:
            if set_brand:
                item.brand_id = brand_id
            if set_category:
                item.category_id = category_id
        session.commit()
        return len(items)


def update_item(
    item_id: int, company_id: int, code: str, name: str, is_active: bool, lifecycle_status_code: str, fields: ItemFields
) -> None:
    _validate_item_fields(fields)
    if lifecycle_status_code not in ("DRAFT", "ACTIVE", "DISCONTINUED"):
        raise ValueError("وضعیت چرخهٔ‌عمر نامعتبر است.")

    from peecha.services import inventory_engine as engine_service
    from peecha.services import unit_conversion as uc

    uc.assert_barcode_available(company_id, fields.barcode, item_id)
    with new_session() as session:
        item = session.get(Item, item_id)
        if item is None or item.company_id != company_id:
            raise ValueError("کالا نامعتبر است.")
        # طبقِ سیستمِ واحد (R225): تغییرِ واحدِ پایهٔ کالایی که سند/تراکنش دارد
        # مجاز نیست -- مقدارِ پایهٔ همهٔ اسنادِ قبلی بی‌معنا می‌شد.
        if item.base_uom_id != fields.base_uom_id and uc.item_has_history(item_id):
            raise ValueError(
                "این کالا سابقهٔ سند/تراکنش دارد؛ تغییر واحد پایه فقط از طریق مهاجرت تخصصی داده ممکن است -- "
                "به‌جایش واحد تازه را در «واحدها و بسته‌بندی» با ضریب تبدیل اضافه کنید."
            )

        # طبقِ مرحلهٔ ۸ (۱۰۸): واحدِ پایه/روشِ قیمت‌گذاری فقط با موجودیِ صفر
        # در همهٔ انبارها قابلِ‌تغییر است — نه صرفِ نبودِ سابقهٔ حرکت.
        has_open_balance = (
            (item.base_uom_id != fields.base_uom_id or item.costing_method_code != fields.costing_method_code)
            and engine_service.get_item_total_on_hand(item_id) != 0
        )
        if has_open_balance and item.base_uom_id != fields.base_uom_id:
            raise ValueError("این کالا در انباری موجودی دارد؛ واحد پایه فقط با موجودی صفر قابل‌تغییر است.")
        if has_open_balance and item.costing_method_code != fields.costing_method_code:
            raise ValueError("این کالا در انباری موجودی دارد؛ روش قیمت‌گذاری فقط با موجودی صفر قابل‌تغییر است.")

        # طبقِ رفعِ باگِ واقعیِ کشف‌شده («ویرایشِ متغیرها کرش می‌کند» +
        # «متغیرها ویژگیِ کالایِ اصلی را نمی‌گیرند»): variant_parent_item_id
        # هرگز نباید از رویِ فرم بازنویسی شود -- خودِ فرمِ عمومیِ کالا
        # (collect_fields) اصلاً این فیلد را نمی‌شناسد و همیشه None
        # می‌فرستد، پس نوشتنِ کورکورانه‌یِ آن این‌جا هر بار که یک متغیر
        # (حتیّ بدونِ تغییرِ واقعی) از طریقِ همین فرمِ عمومی ذخیره شود، آن
        # را از کالایِ اصلی‌اش یتیم می‌کرد -- این پیوند فقط توسطِ
        # item_variants.generate_item_variants (در create_item) تعیین
        # می‌شود و بعد از آن دیگر از این مسیر تغییر نمی‌کند.
        item.item_kind_code = fields.item_kind_code
        item.base_uom_id = fields.base_uom_id
        item.brand_id = fields.brand_id
        item.manufacturer_id = fields.manufacturer_id
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

        # طبقِ درخواستِ صریح («وقتی کالایِ اصلی موجودی‌محور باشه باید
        # واریانت‌ها هم همون ویژگی‌هایِ کالایِ اصلی را بگیرد» + «متغیرها
        # همه از کالایِ اصلی ارث ببرند»): این همگام‌سازی فقط یک‌بارِ
        # هنگامِ تولیدِ اولیه‌یِ متغیرها کافی نیست -- هر بار که خودِ کالایِ
        # اصلی (نه یک متغیر) ذخیره می‌شود، این فیلدهایِ ساختاری/ردیابی به
        # همه‌یِ متغیرهایِ موجودش هم اعمال می‌شود. فیلدهایِ
        # is_sellable/is_purchasable/is_stock_tracked عمداً این‌جا نیستند:
        # کالایِ اصلیِ دارایِ متغیر خودش همیشه غیرِقابلِ‌معامله می‌شود
        # (طبقِ _sync_parent_transactability در item_variants.py) پس مقدارِ
        # فعلیِ آن فیلدها رویِ خودِ فرم معنایِ «الگو» ندارد و نباید به
        # متغیرهایی که از قبل درست تنظیم شده‌اند سرایت کند.
        if item.variant_parent_item_id is None:
            variants = session.scalars(select(Item).where(Item.variant_parent_item_id == item_id)).all()
            for variant in variants:
                variant.item_kind_code = fields.item_kind_code
                variant.base_uom_id = fields.base_uom_id
                variant.brand_id = fields.brand_id
                variant.manufacturer_id = fields.manufacturer_id
                variant.costing_method_code = fields.costing_method_code
                variant.track_serial = fields.track_serial
                variant.track_batch = fields.track_batch
                variant.track_expiry = fields.track_expiry
                # طبقِ رفعِ باگِ واقعیِ گزارش‌شده («درصدِ مالیاتِ کالایِ مادر
                # برایِ متغیرها محاسبه نمی‌شود»): default_tax_percent هم باید
                # مثلِ فیلدهایِ ساختاریِ بالا، هر بار ویرایشِ کالایِ اصلی، به
                # همه‌یِ متغیرهایش سرایت کند -- وگرنه تغییرِ بعدیِ مالیات رویِ
                # کالایِ مادر، برایِ متغیرهایِ ازپیش‌ساخته‌شده اثر نمی‌کند.
                variant.default_tax_percent = fields.default_tax_percent
                variant.updated_at = datetime.datetime.now(datetime.timezone.utc)
                uc.ensure_base_unit(session, variant)

        uc.ensure_base_unit(session, item)
        session.commit()

    uc.set_item_base_barcode(company_id, item_id, fields.barcode)
    dimensions_service.update_detail_account(detail_account_id, company_id, code, is_active, name)


# R301: جدول‌هایی که فقط تعریفِ خودِ کالا هستند و همراهش پاک می‌شوند (فرزند پیش از والد).
# هر جدولِ دیگری که به کالا اشاره کند «استفاده» است و جلوی حذف را می‌گیرد.
_OWNED_DELETES = (
    "DELETE FROM inv.bom_lines WHERE bom_id IN (SELECT bom_id FROM inv.bom_headers WHERE finished_item_id = :i)",
    "DELETE FROM prd.bom_outputs WHERE bom_id IN (SELECT bom_id FROM inv.bom_headers WHERE finished_item_id = :i)",
    "DELETE FROM prd.standard_cost_cards WHERE item_id = :i"
    " OR bom_id IN (SELECT bom_id FROM inv.bom_headers WHERE finished_item_id = :i)"
    " OR routing_id IN (SELECT routing_id FROM prd.routings WHERE item_id = :i)",
    "DELETE FROM inv.bom_headers WHERE finished_item_id = :i",
    "DELETE FROM prd.routing_operations WHERE routing_id IN (SELECT routing_id FROM prd.routings WHERE item_id = :i)",
    "DELETE FROM prd.routings WHERE item_id = :i",
    "DELETE FROM prd.item_production_profiles WHERE item_id = :i",
    "DELETE FROM inv.asset_depreciation_entries WHERE item_id = :i",
    "DELETE FROM inv.asset_details WHERE item_id = :i",
    "DELETE FROM inv.item_unit_barcodes WHERE item_id = :i",
    "DELETE FROM inv.item_uom_conversions WHERE item_id = :i",
    "DELETE FROM inv.item_variant_values WHERE item_id = :i",
    "DELETE FROM inv.item_variants WHERE item_id = :i OR parent_item_id = :i",
    "DELETE FROM inv.item_suppliers WHERE item_id = :i",
    "DELETE FROM inv.item_supplier_codes WHERE item_id = :i",
    "DELETE FROM inv.item_media WHERE item_id = :i",
    "DELETE FROM inv.item_storage_profiles WHERE item_id = :i",
    "DELETE FROM inv.related_items WHERE item_id = :i OR related_item_id = :i",
    "DELETE FROM inv.standard_costs WHERE item_id = :i",
    "DELETE FROM inv.replacement_costs WHERE item_id = :i",
    "DELETE FROM inv.reorder_policies WHERE item_id = :i",
    "DELETE FROM inv.reorder_suggestion_acknowledgements WHERE item_id = :i",
    "DELETE FROM inv.cycle_count_plans WHERE item_id = :i",
    "DELETE FROM comm.price_list_item_price_history WHERE item_id = :i",
    "DELETE FROM comm.price_list_items WHERE item_id = :i",
    "DELETE FROM comm.bundle_components WHERE bundle_id IN (SELECT bundle_id FROM comm.bundle_definitions WHERE bundle_item_id = :i)",
    "DELETE FROM comm.bundle_definitions WHERE bundle_item_id = :i",
    "DELETE FROM comm.marketplace_item_mappings WHERE item_id = :i",
)
_OWNED_TABLES = {
    "inv.bom_headers.finished_item_id", "prd.standard_cost_cards.item_id", "prd.routings.item_id",
    "prd.item_production_profiles.item_id", "inv.asset_details.item_id", "inv.asset_depreciation_entries.item_id",
    "inv.item_unit_barcodes.item_id", "inv.item_uom_conversions.item_id", "inv.item_variant_values.item_id",
    "inv.item_variants.item_id", "inv.item_variants.parent_item_id", "inv.item_suppliers.item_id",
    "inv.item_supplier_codes.item_id", "inv.item_media.item_id", "inv.item_storage_profiles.item_id",
    "inv.related_items.item_id", "inv.related_items.related_item_id", "inv.standard_costs.item_id",
    "inv.replacement_costs.item_id", "inv.reorder_policies.item_id", "inv.reorder_suggestion_acknowledgements.item_id",
    "inv.cycle_count_plans.item_id", "comm.price_list_item_price_history.item_id", "comm.price_list_items.item_id",
    "comm.bundle_definitions.bundle_item_id", "comm.marketplace_item_mappings.item_id",
}
# نام فارسی جاهایی که کالا در آن‌ها «استفاده» شده (برای پیام حذف)
USAGE_LABELS = {
    "comm.commercial_document_lines": "ردیف اسناد خرید و فروش", "inv.stock_document_lines": "ردیف اسناد انبار",
    "inv.stock_ledger": "گردش انبار (کاردکس)", "inv.stock_balance": "موجودی انبار",
    "comm.purchase_request_lines": "درخواست خرید", "comm.rfq_lines": "استعلام قیمت",
    "comm.commercial_contracts": "قراردادهای خرید و فروش", "comm.promotion_rules": "قواعد تخفیف و جایزه",
    "comm.vendor_rebate_agreements": "قراردادهای تخفیف حجمی", "comm.service_tickets": "تیکت‌های خدمات",
    "comm.service_ticket_parts_used": "قطعات مصرفی تیکت‌های خدمات", "comm.warranties": "گارانتی‌ها",
    "comm.bundle_components": "جزء بستهٔ کالای دیگر", "comm.marketplace_inventory_push_log": "سابقهٔ ارسال به فروشگاه اینترنتی",
    "crm.leads": "سرنخ‌های فروش", "crm.opportunity_lines": "فرصت‌های فروش", "fa.assets": "دارایی‌های ثابت",
    "inv.batches": "بچ‌ها", "inv.bom_lines": "فرمول ساخت (مواد اولیهٔ کالای دیگر)", "inv.cost_adjustment_log": "اصلاح بها",
    "inv.cost_allocations": "تخصیص بها", "inv.cost_layers": "لایه‌های بهای تمام‌شده",
    "inv.cost_recalculation_lines": "محاسبهٔ دوبارهٔ بها", "inv.cost_recalculation_runs": "محاسبهٔ دوبارهٔ بها",
    "inv.cycle_count_lines": "انبارگردانی", "inv.items": "متغیرهای این کالا", "inv.location_replenishment_rules": "قواعد تأمین محل انبار",
    "inv.lot_movements": "گردش بچ", "inv.serial_numbers": "سریال‌ها", "inv.stock_reservations": "رزرو موجودی",
    "inv.vehicle_loading_lines": "بارگیری خودرو", "inv.vehicle_settlement_lines": "تسویهٔ خودرو",
    "inv.warehouse_tasks": "وظایف انبار (جانمایی و برداشت)", "prd.bom_outputs": "محصول جانبی فرمول تولید",
    "prd.mrp_lines": "برنامه‌ریزی مواد", "prd.order_materials": "مواد دستور تولید", "prd.order_outputs": "محصول دستور تولید",
    "prd.order_transactions": "گردش تولید", "prd.production_orders": "دستور تولید", "prd.production_plan_lines": "برنامهٔ تولید",
}


def _item_references(session) -> list[tuple[str, str]]:
    """(جدول، ستون) همهٔ کلیدهای خارجی تک‌ستونی که به inv.items اشاره می‌کنند -- از خود پایگاه داده."""
    from sqlalchemy import text

    return [(t, c) for t, c in session.execute(text(
        "SELECT c.conrelid::regclass::text, a.attname FROM pg_constraint c "
        "JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1] "
        "WHERE c.contype = 'f' AND c.confrelid = 'inv.items'::regclass AND array_length(c.conkey, 1) = 1"))]


def _usage(session, item_id: int, *, ignore_variants: bool = False) -> list[tuple[str, int]]:
    from sqlalchemy import text

    totals: dict[str, int] = {}
    for table, column in _item_references(session):
        if f"{table}.{column}" in _OWNED_TABLES or (ignore_variants and table == "inv.items"):
            continue
        n = session.scalar(text(f'SELECT count(*) FROM {table} WHERE "{column}" = :i'), {"i": item_id}) or 0
        if n:
            label = USAGE_LABELS.get(table, table)
            totals[label] = totals.get(label, 0) + n
    return sorted(totals.items(), key=lambda x: -x[1])


def item_usage(company_id: int, item_id: int) -> list[tuple[str, int]]:
    """جاهایی که این کالا در آن‌ها استفاده شده: [(نام فارسی بخش، تعداد ردیف)] -- خالی یعنی قابل‌حذف است."""
    with new_session() as session:
        item = session.get(Item, item_id)
        if item is None or item.company_id != company_id:
            raise ValueError("کالا نامعتبر است.")
        return _usage(session, item_id)


def _usage_message(name: str, usage: list[tuple[str, int]]) -> str:
    from peecha import numerals

    lines = "\n".join(f"• {label}: {numerals.to_persian_digits(str(n))} مورد" for label, n in usage)
    return (f"«{name}» در این بخش‌ها استفاده شده و قابل‌حذف نیست:\n{lines}\n"
            "به‌جای حذف می‌توانید وضعیت آن را «متوقف‌شده» کنید.")


def variant_ids(company_id: int, item_id: int) -> list[int]:
    with new_session() as session:
        return list(session.scalars(select(Item.item_id).where(Item.company_id == company_id,
                                                               Item.variant_parent_item_id == item_id)))


def delete_item(item_id: int, company_id: int, *, with_variants: bool = False) -> None:
    """حذف کالا (R301).

    ۱) اگر کالا متغیر دارد: فقط با with_variants=True و همراه همهٔ متغیرهایش حذف می‌شود.
    ۲) اگر خودش یا یکی از متغیرهایش جایی «استفاده» شده باشد (سند، گردش، تولید، فرمول ساخت کالای دیگر و ...)،
       پیام دقیق می‌دهد که در کدام بخش‌ها و چند مورد -- از روی همهٔ کلیدهای خارجی واقعی پایگاه داده.
    ۳) وگرنه تعریف‌های خود کالا (واحد و بارکد، فرمول ساخت و مسیر تولید خودش، تامین‌کننده‌ها، قیمت‌ها، عکس‌ها،
       سیاست سفارش، ...) و حساب تفصیلی‌اش هم پاک می‌شوند."""
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    with new_session() as session:
        item = session.get(Item, item_id)
        if item is None or item.company_id != company_id:
            raise ValueError("کالا نامعتبر است.")
        children = list(session.scalars(select(Item).where(Item.variant_parent_item_id == item_id)))
        if children and not with_variants:
            raise ValueError(f"این کالا {len(children)} متغیر دارد؛ با حذف آن، همهٔ متغیرهایش هم حذف می‌شوند.")
        for victim in [*children, item]:
            usage = _usage(session, victim.item_id, ignore_variants=victim is item)
            if usage:
                prefix = "متغیر " if victim is not item else ""
                raise ValueError(_usage_message(prefix + _display_name(session, victim), usage))
        detail_ids = []
        try:
            for victim in [*children, item]:
                for sql in _OWNED_DELETES:
                    session.execute(text(sql), {"i": victim.item_id})
                detail_ids.append(victim.item_detail_account_id)
                session.delete(victim)
                session.flush()
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            table = getattr(getattr(exc.orig, "diag", None), "table_name", None)
            schema = getattr(getattr(exc.orig, "diag", None), "schema_name", None)
            where = USAGE_LABELS.get(f"{schema}.{table}", f"{schema}.{table}") if table else "بخش دیگری از برنامه"
            raise ValueError(f"این کالا در «{where}» استفاده شده و قابل‌حذف نیست.") from exc
    for detail_account_id in detail_ids:
        dimensions_service.delete_detail_account(detail_account_id, company_id)


def _display_name(session, item: Item) -> str:
    from peecha.db.models.accounting import DetailAccount

    account = session.get(DetailAccount, item.item_detail_account_id)
    return f"{account.code} — {account.name}" if account is not None else f"کالای {item.item_id}"


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


# سازگاری با کدِ پیش از R225 -- همه به services/unit_conversion.py واگذار می‌شوند.
def list_item_uom_conversions(item_id: int) -> list[UomConversionRow]:
    """فقط واحدهای غیرپایهٔ فعال (همان معنای قبلی)."""
    from peecha.services import unit_conversion as uc

    return [
        UomConversionRow(u.item_unit_id, u.uom_id, u.code, u.factor, u.is_default_purchase, u.is_default_sales)
        for u in uc.get_item_units(item_id) if not u.is_base
    ]


def set_item_uom_conversion(
    item_id: int, uom_id: int, conversion_factor: decimal.Decimal,
    is_purchase_default: bool = False, is_sales_default: bool = False,
) -> None:
    from peecha.services import unit_conversion as uc

    uc.set_item_unit(
        item_id, uom_id, conversion_factor, is_default_purchase=is_purchase_default, is_default_sales=is_sales_default,
    )


def delete_item_uom_conversion(conversion_id: int, item_id: int) -> None:
    from peecha.services import unit_conversion as uc

    uc.remove_item_unit(conversion_id, item_id)


@dataclass
class ItemUomOption:
    uom_id: int
    code: str
    name: str
    factor: decimal.Decimal
    is_base: bool
    is_purchase_default: bool
    is_sales_default: bool
    decimal_places: int


def list_item_uom_options(item_id: int, purpose: str | None = None) -> list[ItemUomOption]:
    """واحدهای قابل‌انتخاب در سند تازه (فعال، مجاز برای purpose)، اول واحد پایه."""
    from peecha.services import unit_conversion as uc

    return [
        ItemUomOption(u.uom_id, u.code, u.name, u.factor, u.is_base, u.is_default_purchase, u.is_default_sales, u.decimal_places)
        for u in uc.get_item_units(item_id, purpose=purpose)
    ]


def get_uom_factor(item_id: int, uom_id: int) -> decimal.Decimal:
    """ضریب تبدیل یک واحد به واحد پایهٔ کالا (پایه = ۱)."""
    from peecha.services import unit_conversion as uc

    return uc.get_factor(item_id, uom_id)


# ---------------------------------------------------------------------
# کالاهایِ جایگزین/مکمل
# ---------------------------------------------------------------------
def list_related_items(item_id: int) -> list[tuple[int, str]]:
    with new_session() as session:
        rows = session.scalars(select(RelatedItem).where(RelatedItem.item_id == item_id)).all()
        return [(r.related_item_id, r.relation_type_code) for r in rows]


def add_related_item(item_id: int, related_item_id: int, relation_type_code: str) -> None:
    if relation_type_code not in ("SUBSTITUTE", "COMPLEMENTARY"):
        raise ValueError("نوع ارتباط نامعتبر است.")
    if item_id == related_item_id:
        raise ValueError("یک کالا نمی‌تواند جایگزین/مکمل خودش باشد.")
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
            raise ValueError("این کد قبلاً برای دسته‌بندی دیگری استفاده شده است.")
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
            raise ValueError("این دسته زیرگروه دارد و قابل‌حذف نیست.")
        if session.scalar(select(func.count()).select_from(Item).where(Item.category_id == category_id)):
            raise ValueError("این دسته به کالایی وصل است و قابل‌حذف نیست.")
        session.delete(category)
        session.commit()
