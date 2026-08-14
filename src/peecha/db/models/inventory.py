"""مدل‌هایِ ماژولِ انبار و لجستیک (Inventory & Logistics).

معادلِ db/schema/057 تا 063_inventory_*.sql — طبقِ سندِ معماریِ ۱۵مرحله‌ای:
«کالا» موجودیتِ تازه‌ای نیست، Item یک جدولِ اقماریِ یک‌به‌یکِ تفصیلیِ گروهِ
سیستمیِ INVENTORY_ITEM است (دقیقاً هم‌الگو با hr.employees نسبت به تفصیلیِ
گروهِ PERSONNEL)؛ Ledger منبعِ حقیقتِ تغییرناپذیر است و Balance همیشه از
رویِ آن بازسازی‌پذیر می‌ماند.
"""

from __future__ import annotations

import datetime
import decimal

from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    Date,
    ForeignKey,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from peecha.db.base import Base


# =======================================================================
# خوشهٔ کاتالوگ — معادلِ 057_inventory_catalog.sql
# =======================================================================
class Uom(Base):
    __tablename__ = "uom"
    __table_args__ = (UniqueConstraint("company_id", "code"), {"schema": "inv"})

    uom_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("core.companies.company_id"))
    code: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(50))
    uom_type_code: Mapped[str] = mapped_column(String(10))
    decimal_places: Mapped[int] = mapped_column(SmallInteger, default=2)
    is_active: Mapped[bool] = mapped_column(default=True)


class Brand(Base):
    __tablename__ = "brands"
    __table_args__ = (UniqueConstraint("company_id", "code"), {"schema": "inv"})

    brand_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    code: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(150))
    is_active: Mapped[bool] = mapped_column(default=True)


class Manufacturer(Base):
    __tablename__ = "manufacturers"
    __table_args__ = (UniqueConstraint("company_id", "code"), {"schema": "inv"})

    manufacturer_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    code: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(150))
    country_name: Mapped[str | None] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(default=True)


class CostingMethod(Base):
    __tablename__ = "costing_methods"
    __table_args__ = {"schema": "inv"}

    costing_method_id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    code: Mapped[str] = mapped_column(String(20))


class ItemCategory(Base):
    """دسته‌بندیِ سلسله‌مراتبیِ کالا — مستقل از تفصیلی؛ صرفاً برایِ گروه‌بندیِ
    نمایشی/گزارشی و override حساب در سطحِ دسته."""

    __tablename__ = "item_categories"
    __table_args__ = (UniqueConstraint("company_id", "code"), {"schema": "inv"})

    category_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    parent_category_id: Mapped[int | None] = mapped_column(ForeignKey("inv.item_categories.category_id"))
    code: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(150))
    is_active: Mapped[bool] = mapped_column(default=True)


class Item(Base):
    """جدولِ اقماریِ «کالا/خدمت» — یک‌به‌یک با تفصیلیِ سطحِ‌آخرِ گروهِ
    INVENTORY_ITEM؛ خودِ کد/نام/سلسله‌مراتب رویِ acc.detail_accounts است،
    نه این‌جا."""

    __tablename__ = "items"
    __table_args__ = (
        CheckConstraint(
            "item_kind_code = 'GOOD' OR is_stock_tracked = FALSE", name="ck_inv_items_service_not_tracked"
        ),
        CheckConstraint("track_expiry = FALSE OR track_batch = TRUE", name="ck_inv_items_expiry_needs_batch"),
        {"schema": "inv"},
    )

    item_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    item_detail_account_id: Mapped[int] = mapped_column(
        ForeignKey("acc.detail_accounts.detail_account_id"), unique=True
    )
    item_kind_code: Mapped[str] = mapped_column(String(20))  # GOOD|SERVICE|RAW_MATERIAL|...
    base_uom_id: Mapped[int] = mapped_column(ForeignKey("inv.uom.uom_id"))
    brand_id: Mapped[int | None] = mapped_column(ForeignKey("inv.brands.brand_id"))
    manufacturer_id: Mapped[int | None] = mapped_column(ForeignKey("inv.manufacturers.manufacturer_id"))
    variant_parent_item_id: Mapped[int | None] = mapped_column(ForeignKey("inv.items.item_id"))
    costing_method_code: Mapped[str | None] = mapped_column(ForeignKey("inv.costing_methods.code"))
    lifecycle_status_code: Mapped[str] = mapped_column(String(15), default="ACTIVE")  # DRAFT|ACTIVE|DISCONTINUED
    is_sellable: Mapped[bool] = mapped_column(default=True)
    is_purchasable: Mapped[bool] = mapped_column(default=True)
    is_stock_tracked: Mapped[bool] = mapped_column(default=True)
    track_serial: Mapped[bool] = mapped_column(default=False)
    track_batch: Mapped[bool] = mapped_column(default=False)
    track_expiry: Mapped[bool] = mapped_column(default=False)
    shelf_life_days: Mapped[int | None]
    weight_kg: Mapped[decimal.Decimal | None] = mapped_column(Numeric(12, 4))
    volume_m3: Mapped[decimal.Decimal | None] = mapped_column(Numeric(12, 6))
    primary_attachment_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("doc.attachments.attachment_id")
    )
    extra_fields: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    notes: Mapped[str | None] = mapped_column(String(1000))
    created_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")

    # --- فیلدهایِ فازِ ۱ تا ۱۵ (078_inventory_catalog_v2.sql) --------------
    category_id: Mapped[int | None] = mapped_column(ForeignKey("inv.item_categories.category_id"))
    default_warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("inv.warehouses.warehouse_id"))
    barcode: Mapped[str | None] = mapped_column(String(50))
    qr_code_data: Mapped[str | None] = mapped_column(String(200))
    sku: Mapped[str | None] = mapped_column(String(50))
    latin_name: Mapped[str | None] = mapped_column(String(200))
    short_name: Mapped[str | None] = mapped_column(String(50))
    country_of_origin: Mapped[str | None] = mapped_column(String(60))
    length_cm: Mapped[decimal.Decimal | None] = mapped_column(Numeric(10, 2))
    width_cm: Mapped[decimal.Decimal | None] = mapped_column(Numeric(10, 2))
    height_cm: Mapped[decimal.Decimal | None] = mapped_column(Numeric(10, 2))
    package_type_code: Mapped[str | None] = mapped_column(String(30))
    freight_class_code: Mapped[str | None] = mapped_column(String(30))
    requires_qc: Mapped[bool] = mapped_column(default=False)
    qc_standard: Mapped[str | None] = mapped_column(String(100))
    qc_test_spec: Mapped[str | None] = mapped_column(Text)
    qc_inspection_interval_days: Mapped[int | None]
    purchase_lead_time_days: Mapped[int | None]
    purchase_min_order_qty: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 6))
    purchase_package_qty: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 6))
    max_discount_percent: Mapped[decimal.Decimal | None] = mapped_column(Numeric(5, 2))
    sales_commission_percent: Mapped[decimal.Decimal | None] = mapped_column(Numeric(5, 2))
    warranty_months: Mapped[int | None]
    seo_title: Mapped[str | None] = mapped_column(String(200))
    seo_url_slug: Mapped[str | None] = mapped_column(String(200))
    seo_meta_description: Mapped[str | None] = mapped_column(String(500))
    seo_meta_keywords: Mapped[str | None] = mapped_column(String(300))
    website_category: Mapped[str | None] = mapped_column(String(150))
    website_tags: Mapped[str | None] = mapped_column(String(300))
    pos_shortcut_key: Mapped[str | None] = mapped_column(String(10))
    pos_button_color: Mapped[str | None] = mapped_column(String(20))
    pos_requires_weight: Mapped[bool] = mapped_column(default=False)
    pos_requires_serial: Mapped[bool] = mapped_column(default=False)
    updated_at: Mapped[datetime.datetime | None]


class ItemUomConversion(Base):
    __tablename__ = "item_uom_conversions"
    __table_args__ = (UniqueConstraint("item_id", "uom_id"), {"schema": "inv"})

    conversion_id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("inv.items.item_id"))
    uom_id: Mapped[int] = mapped_column(ForeignKey("inv.uom.uom_id"))
    conversion_factor: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 6))
    is_purchase_default: Mapped[bool] = mapped_column(default=False)
    is_sales_default: Mapped[bool] = mapped_column(default=False)


class ItemAttribute(Base):
    __tablename__ = "item_attributes"
    __table_args__ = (UniqueConstraint("company_id", "code"), {"schema": "inv"})

    attribute_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    code: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(default=True)


class ItemAttributeValue(Base):
    __tablename__ = "item_attribute_values"
    __table_args__ = (UniqueConstraint("attribute_id", "code"), {"schema": "inv"})

    value_id: Mapped[int] = mapped_column(primary_key=True)
    attribute_id: Mapped[int] = mapped_column(ForeignKey("inv.item_attributes.attribute_id"))
    code: Mapped[str] = mapped_column(String(20))
    value: Mapped[str] = mapped_column(String(100))
    display_order: Mapped[int] = mapped_column(SmallInteger, default=0)


class ItemVariantValue(Base):
    __tablename__ = "item_variant_values"
    __table_args__ = {"schema": "inv"}

    item_id: Mapped[int] = mapped_column(ForeignKey("inv.items.item_id"), primary_key=True)
    attribute_id: Mapped[int] = mapped_column(ForeignKey("inv.item_attributes.attribute_id"), primary_key=True)
    value_id: Mapped[int] = mapped_column(ForeignKey("inv.item_attribute_values.value_id"))


class RelatedItem(Base):
    __tablename__ = "related_items"
    __table_args__ = (
        UniqueConstraint("item_id", "related_item_id", "relation_type_code"),
        {"schema": "inv"},
    )

    related_item_link_id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("inv.items.item_id"))
    related_item_id: Mapped[int] = mapped_column(ForeignKey("inv.items.item_id"))
    relation_type_code: Mapped[str] = mapped_column(String(15))  # SUBSTITUTE | COMPLEMENTARY


class ItemSupplier(Base):
    __tablename__ = "item_suppliers"
    __table_args__ = (
        UniqueConstraint("item_id", "supplier_detail_account_id"),
        {"schema": "inv"},
    )

    item_supplier_id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("inv.items.item_id"))
    supplier_detail_account_id: Mapped[int] = mapped_column(ForeignKey("acc.detail_accounts.detail_account_id"))
    supplier_sku: Mapped[str | None] = mapped_column(String(50))
    lead_time_days: Mapped[int | None]
    min_order_qty: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 6))
    is_preferred: Mapped[bool] = mapped_column(default=False)


class ItemMedia(Base):
    __tablename__ = "item_media"
    __table_args__ = {"schema": "inv"}

    item_media_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("inv.items.item_id"))
    attachment_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("doc.attachments.attachment_id"))
    media_type_code: Mapped[str] = mapped_column(String(15))  # IMAGE|VIDEO|CATALOG|MANUAL|DOCUMENT
    alt_text: Mapped[str | None] = mapped_column(String(200))
    is_primary: Mapped[bool] = mapped_column(default=False)
    sort_order: Mapped[int] = mapped_column(SmallInteger, default=0)


class BomHeader(Base):
    __tablename__ = "bom_headers"
    __table_args__ = (UniqueConstraint("finished_item_id", "version_no"), {"schema": "inv"})

    bom_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    finished_item_id: Mapped[int] = mapped_column(ForeignKey("inv.items.item_id"))
    version_no: Mapped[int] = mapped_column(SmallInteger, default=1)
    batch_size_qty: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 6), default=decimal.Decimal(1))
    production_time_minutes: Mapped[int | None]
    scrap_percent: Mapped[decimal.Decimal] = mapped_column(Numeric(5, 2), default=decimal.Decimal(0))
    is_active: Mapped[bool] = mapped_column(default=True)


class BomLine(Base):
    __tablename__ = "bom_lines"
    __table_args__ = (UniqueConstraint("bom_id", "line_no"), {"schema": "inv"})

    bom_line_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    bom_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("inv.bom_headers.bom_id"))
    component_item_id: Mapped[int] = mapped_column(ForeignKey("inv.items.item_id"))
    quantity_per: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 6))
    scrap_percent: Mapped[decimal.Decimal] = mapped_column(Numeric(5, 2), default=decimal.Decimal(0))
    line_no: Mapped[int] = mapped_column(SmallInteger)


class AssetDetail(Base):
    __tablename__ = "asset_details"
    __table_args__ = {"schema": "inv"}

    item_id: Mapped[int] = mapped_column(ForeignKey("inv.items.item_id"), primary_key=True)
    asset_tag_no: Mapped[str | None] = mapped_column(String(50))
    depreciation_group_code: Mapped[str | None] = mapped_column(String(30))
    useful_life_months: Mapped[int] = mapped_column()
    depreciation_method_code: Mapped[str] = mapped_column(String(20), default="STRAIGHT_LINE")
    acquisition_date: Mapped[datetime.date] = mapped_column(Date)
    acquisition_cost: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2))
    salvage_value: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=decimal.Decimal(0))


class AssetDepreciationEntry(Base):
    __tablename__ = "asset_depreciation_entries"
    __table_args__ = (UniqueConstraint("item_id", "period_date"), {"schema": "inv"})

    depreciation_entry_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("inv.asset_details.item_id"))
    period_date: Mapped[datetime.date] = mapped_column(Date)
    depreciation_amount: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2))
    journal_entry_id: Mapped[int | None] = mapped_column(ForeignKey("acc.journal_entries.journal_entry_id"))


class CategoryAccountMapping(Base):
    __tablename__ = "category_account_mappings"
    __table_args__ = {"schema": "inv"}

    category_id: Mapped[int] = mapped_column(ForeignKey("inv.item_categories.category_id"), primary_key=True)
    mapping_key: Mapped[str] = mapped_column(String(30), primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("acc.chart_of_accounts.account_id"))


# =======================================================================
# خوشهٔ مکان — معادلِ 058_inventory_locations.sql
# =======================================================================
class Warehouse(Base):
    __tablename__ = "warehouses"
    __table_args__ = (UniqueConstraint("company_id", "code"), {"schema": "inv"})

    warehouse_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    code: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(150))
    warehouse_type_code: Mapped[str] = mapped_column(String(20), default="GENERAL")
    project_detail_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("acc.detail_accounts.detail_account_id")
    )
    allow_negative_stock: Mapped[bool] = mapped_column(default=False)
    is_temperature_controlled: Mapped[bool] = mapped_column(default=False)
    min_temp_c: Mapped[decimal.Decimal | None] = mapped_column(Numeric(5, 2))
    max_temp_c: Mapped[decimal.Decimal | None] = mapped_column(Numeric(5, 2))
    address: Mapped[str | None] = mapped_column(String(400))
    is_default: Mapped[bool] = mapped_column(default=False)
    is_active: Mapped[bool] = mapped_column(default=True)
    # --- طبقِ بازطراحیِ فرمِ انبار (079_inventory_warehouse_v2.sql) --------
    # پایه
    english_name: Mapped[str | None] = mapped_column(String(150))
    org_unit_id: Mapped[int | None] = mapped_column(ForeignKey("hr.organizational_units.org_unit_id"))
    cost_center_detail_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("acc.detail_accounts.detail_account_id")
    )
    # مکانی
    country: Mapped[str | None] = mapped_column(String(100))
    province: Mapped[str | None] = mapped_column(String(100))
    city: Mapped[str | None] = mapped_column(String(100))
    postal_code: Mapped[str | None] = mapped_column(String(20))
    phone: Mapped[str | None] = mapped_column(String(30))
    gps_coordinates: Mapped[str | None] = mapped_column(String(50))
    manager_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    # عملیاتی
    allow_purchase: Mapped[bool] = mapped_column(default=True)
    allow_sale: Mapped[bool] = mapped_column(default=True)
    allow_production: Mapped[bool] = mapped_column(default=False)
    allow_transfer: Mapped[bool] = mapped_column(default=True)
    allow_cycle_count: Mapped[bool] = mapped_column(default=True)
    allow_reservation: Mapped[bool] = mapped_column(default=True)
    allow_direct_sale: Mapped[bool] = mapped_column(default=False)
    requires_receipt_approval: Mapped[bool] = mapped_column(default=False)
    requires_issue_approval: Mapped[bool] = mapped_column(default=False)
    # کنترلِ موجودی (اطلاعاتی — به موتورِ reorder/costing وصل نیست)
    costing_method_id: Mapped[int | None] = mapped_column(
        SmallInteger, ForeignKey("inv.costing_methods.costing_method_id")
    )
    default_min_qty: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 6))
    default_max_qty: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 6))
    default_reorder_point_qty: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 6))
    withdrawal_policy_code: Mapped[str | None] = mapped_column(String(10))
    # کیفیت
    requires_qc: Mapped[bool] = mapped_column(default=False)
    requires_quarantine: Mapped[bool] = mapped_column(default=False)
    default_quarantine_warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("inv.warehouses.warehouse_id"))
    # امنیت
    access_level_code: Mapped[str] = mapped_column(String(15), default="PUBLIC")
    # تجهیزات
    has_barcode_equipment: Mapped[bool] = mapped_column(default=False)
    has_qr_equipment: Mapped[bool] = mapped_column(default=False)
    has_rfid_equipment: Mapped[bool] = mapped_column(default=False)
    has_pda_equipment: Mapped[bool] = mapped_column(default=False)
    has_scanner_equipment: Mapped[bool] = mapped_column(default=False)
    has_scale_equipment: Mapped[bool] = mapped_column(default=False)
    # فروشگاه/POS
    pos_enabled: Mapped[bool] = mapped_column(default=False)
    pos_pick_priority: Mapped[int | None] = mapped_column(SmallInteger)
    # تولید (خودارجاع)
    raw_material_warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("inv.warehouses.warehouse_id"))
    production_line_warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("inv.warehouses.warehouse_id"))
    finished_goods_warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("inv.warehouses.warehouse_id"))
    scrap_warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("inv.warehouses.warehouse_id"))
    # مالی
    profit_center_detail_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("acc.detail_accounts.detail_account_id")
    )
    # توضیحات
    notes: Mapped[str | None] = mapped_column(Text)


class BinLocation(Base):
    __tablename__ = "bin_locations"
    __table_args__ = (UniqueConstraint("warehouse_id", "code"), {"schema": "inv"})

    bin_location_id: Mapped[int] = mapped_column(primary_key=True)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("inv.warehouses.warehouse_id"))
    parent_bin_location_id: Mapped[int | None] = mapped_column(ForeignKey("inv.bin_locations.bin_location_id"))
    code: Mapped[str] = mapped_column(String(30))
    name: Mapped[str | None] = mapped_column(String(100))
    bin_type_code: Mapped[str | None] = mapped_column(String(15))
    barcode: Mapped[str | None] = mapped_column(String(100))
    is_pickable: Mapped[bool] = mapped_column(default=True)
    is_active: Mapped[bool] = mapped_column(default=True)


class WarehouseUserAccess(Base):
    """کاربرانِ مجازِ انبار — هم‌الگو با sec.user_companies (junction ساده) +
    چهار پرچمِ توانایی. فقط CRUDِ تعریفی؛ هنوز به هیچ سندی وصل نیست."""

    __tablename__ = "warehouse_user_access"
    __table_args__ = {"schema": "inv"}

    warehouse_id: Mapped[int] = mapped_column(ForeignKey("inv.warehouses.warehouse_id"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("sec.users.user_id"), primary_key=True)
    can_view_balance: Mapped[bool] = mapped_column(default=True)
    can_post_receipt: Mapped[bool] = mapped_column(default=True)
    can_post_issue: Mapped[bool] = mapped_column(default=True)
    can_adjust: Mapped[bool] = mapped_column(default=True)


class WarehouseAccountMapping(Base):
    """نگاشتِ حسابِ سطحِ‌انبار — عیناً هم‌شکلِ CategoryAccountMapping؛ override
    رویِ InventoryAccountMapping. طبقِ همان دامنه‌بندی: فقط CRUD این دور."""

    __tablename__ = "warehouse_account_mappings"
    __table_args__ = {"schema": "inv"}

    warehouse_id: Mapped[int] = mapped_column(ForeignKey("inv.warehouses.warehouse_id"), primary_key=True)
    mapping_key: Mapped[str] = mapped_column(String(30), primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("acc.chart_of_accounts.account_id"))


# =======================================================================
# موتورِ موجودی و اسنادِ عملیاتی — معادلِ 059_inventory_engine_documents.sql
# =======================================================================
class DocumentReasonCode(Base):
    __tablename__ = "document_reason_codes"
    __table_args__ = (UniqueConstraint("company_id", "applies_to", "code"), {"schema": "inv"})

    reason_code_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("core.companies.company_id"))
    applies_to: Mapped[str] = mapped_column(String(20))  # ADJUSTMENT | RETURN_IN | RETURN_OUT
    code: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(default=True)


class StockDocument(Base):
    __tablename__ = "stock_documents"
    __table_args__ = (
        UniqueConstraint("company_id", "fiscal_year_id", "document_type_code", "document_no"),
        {"schema": "inv"},
    )

    stock_document_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    fiscal_year_id: Mapped[int] = mapped_column(ForeignKey("acc.fiscal_years.fiscal_year_id"))
    document_type_code: Mapped[str] = mapped_column(String(15))
    document_no: Mapped[int]
    document_date: Mapped[datetime.date] = mapped_column(Date)
    status_code: Mapped[str] = mapped_column(String(15), default="DRAFT")
    source_warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("inv.warehouses.warehouse_id"))
    destination_warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("inv.warehouses.warehouse_id"))
    counterparty_detail_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("acc.detail_accounts.detail_account_id")
    )
    cost_center_detail_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("acc.detail_accounts.detail_account_id")
    )
    project_detail_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("acc.detail_accounts.detail_account_id")
    )
    reference_no: Mapped[str | None] = mapped_column(String(50))
    description: Mapped[str | None] = mapped_column(Text)
    journal_entry_id: Mapped[int | None] = mapped_column(ForeignKey("acc.journal_entries.journal_entry_id"))
    cycle_count_session_id: Mapped[int | None] = mapped_column(ForeignKey("inv.cycle_count_sessions.session_id"))
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("sec.users.user_id"))
    created_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")
    posted_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    posted_at: Mapped[datetime.datetime | None]


class StockDocumentLine(Base):
    __tablename__ = "stock_document_lines"
    __table_args__ = (UniqueConstraint("stock_document_id", "line_no"), {"schema": "inv"})

    line_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    stock_document_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("inv.stock_documents.stock_document_id"))
    line_no: Mapped[int] = mapped_column(SmallInteger)
    item_id: Mapped[int] = mapped_column(ForeignKey("inv.items.item_id"))
    uom_id: Mapped[int] = mapped_column(ForeignKey("inv.uom.uom_id"))
    quantity: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 6))
    quantity_base: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 6))
    bin_location_id: Mapped[int | None] = mapped_column(ForeignKey("inv.bin_locations.bin_location_id"))
    destination_bin_location_id: Mapped[int | None] = mapped_column(ForeignKey("inv.bin_locations.bin_location_id"))
    batch_id: Mapped[int | None] = mapped_column(ForeignKey("inv.batches.batch_id"))
    unit_cost: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 6))
    line_total_cost: Mapped[decimal.Decimal | None] = mapped_column(
        Numeric(18, 2), Computed("round(quantity_base * unit_cost, 2)")
    )
    quality_status_code: Mapped[str] = mapped_column(String(15), default="APPROVED")
    reason_code_id: Mapped[int | None] = mapped_column(ForeignKey("inv.document_reason_codes.reason_code_id"))
    source_line_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("inv.stock_document_lines.line_id"))
    reservation_id: Mapped[int | None] = mapped_column(ForeignKey("inv.stock_reservations.reservation_id"))
    description: Mapped[str | None] = mapped_column(String(500))


class StockLedger(Base):
    """دفترِ حرکاتِ موجودی — Append-Only (تغییرناپذیر با Trigger در دیتابیس)."""

    __tablename__ = "stock_ledger"
    __table_args__ = {"schema": "inv"}

    ledger_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    stock_document_line_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("inv.stock_document_lines.line_id"))
    item_id: Mapped[int] = mapped_column(ForeignKey("inv.items.item_id"))
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("inv.warehouses.warehouse_id"))
    bin_location_id: Mapped[int] = mapped_column(ForeignKey("inv.bin_locations.bin_location_id"))
    batch_id: Mapped[int | None] = mapped_column(ForeignKey("inv.batches.batch_id"))
    serial_id: Mapped[int | None] = mapped_column(ForeignKey("inv.serial_numbers.serial_id"))
    movement_direction: Mapped[str] = mapped_column(String(3))  # IN | OUT
    quantity_base: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 6))
    unit_cost: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 6))
    total_cost: Mapped[decimal.Decimal | None] = mapped_column(
        Numeric(18, 2), Computed("round(quantity_base * unit_cost, 2)")
    )
    movement_date: Mapped[datetime.date] = mapped_column(Date)
    created_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")


class StockBalance(Base):
    __tablename__ = "stock_balance"
    __table_args__ = {"schema": "inv"}

    stock_balance_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    item_id: Mapped[int] = mapped_column(ForeignKey("inv.items.item_id"))
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("inv.warehouses.warehouse_id"))
    bin_location_id: Mapped[int] = mapped_column(ForeignKey("inv.bin_locations.bin_location_id"))
    batch_id: Mapped[int | None] = mapped_column(ForeignKey("inv.batches.batch_id"))
    quantity_on_hand: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 6), default=0)
    quantity_reserved: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 6), default=0)
    quantity_available: Mapped[decimal.Decimal] = mapped_column(
        Numeric(18, 6), Computed("quantity_on_hand - quantity_reserved")
    )
    average_unit_cost: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 6), default=0)
    total_value: Mapped[decimal.Decimal] = mapped_column(
        Numeric(18, 2), Computed("round(quantity_on_hand * average_unit_cost, 2)")
    )
    last_movement_at: Mapped[datetime.datetime | None]


class StockReservation(Base):
    __tablename__ = "stock_reservations"
    __table_args__ = (
        CheckConstraint("fulfilled_quantity_base <= quantity", name="ck_inv_stock_reservations_fulfilled"),
        {"schema": "inv"},
    )

    reservation_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    item_id: Mapped[int] = mapped_column(ForeignKey("inv.items.item_id"))
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("inv.warehouses.warehouse_id"))
    bin_location_id: Mapped[int | None] = mapped_column(ForeignKey("inv.bin_locations.bin_location_id"))
    batch_id: Mapped[int | None] = mapped_column(ForeignKey("inv.batches.batch_id"))
    quantity: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 6))
    priority_level: Mapped[int] = mapped_column(SmallInteger, default=100)
    fulfilled_quantity_base: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 6), default=0)
    remaining_quantity_base: Mapped[decimal.Decimal] = mapped_column(
        Numeric(18, 6), Computed("quantity - fulfilled_quantity_base")
    )
    source_type_code: Mapped[str] = mapped_column(String(30))
    source_record_id: Mapped[int] = mapped_column(BigInteger)
    status_code: Mapped[str] = mapped_column(String(15), default="ACTIVE")
    expires_at: Mapped[datetime.datetime | None]
    created_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")
    released_at: Mapped[datetime.datetime | None]


# =======================================================================
# رهگیریِ کالا و کیفیت — معادلِ 060_inventory_tracking_quality.sql
# =======================================================================
class Batch(Base):
    __tablename__ = "batches"
    __table_args__ = (UniqueConstraint("item_id", "batch_no"), {"schema": "inv"})

    batch_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    item_id: Mapped[int] = mapped_column(ForeignKey("inv.items.item_id"))
    batch_no: Mapped[str] = mapped_column(String(50))
    manufacture_date: Mapped[datetime.date | None] = mapped_column(Date)
    expiry_date: Mapped[datetime.date | None] = mapped_column(Date)
    supplier_detail_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("acc.detail_accounts.detail_account_id")
    )
    qc_status_code: Mapped[str] = mapped_column(String(15), default="PENDING")
    source_line_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("inv.stock_document_lines.line_id"))
    notes: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")


class SerialNumber(Base):
    __tablename__ = "serial_numbers"
    __table_args__ = (UniqueConstraint("company_id", "item_id", "serial_no"), {"schema": "inv"})

    serial_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    item_id: Mapped[int] = mapped_column(ForeignKey("inv.items.item_id"))
    serial_no: Mapped[str] = mapped_column(String(100))
    batch_id: Mapped[int | None] = mapped_column(ForeignKey("inv.batches.batch_id"))
    current_warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("inv.warehouses.warehouse_id"))
    current_bin_location_id: Mapped[int | None] = mapped_column(ForeignKey("inv.bin_locations.bin_location_id"))
    status_code: Mapped[str] = mapped_column(String(15), default="IN_STOCK")
    warranty_expiry_date: Mapped[datetime.date | None] = mapped_column(Date)
    source_line_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("inv.stock_document_lines.line_id"))
    created_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")


class SerialMovement(Base):
    __tablename__ = "serial_movements"
    __table_args__ = {"schema": "inv"}

    serial_movement_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    serial_id: Mapped[int] = mapped_column(ForeignKey("inv.serial_numbers.serial_id"))
    stock_document_line_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("inv.stock_document_lines.line_id"))
    from_status_code: Mapped[str | None] = mapped_column(String(15))
    to_status_code: Mapped[str] = mapped_column(String(15))
    from_warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("inv.warehouses.warehouse_id"))
    to_warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("inv.warehouses.warehouse_id"))
    moved_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")


class QcInspection(Base):
    __tablename__ = "qc_inspections"
    __table_args__ = (
        CheckConstraint(
            "(stock_document_line_id IS NOT NULL)::int + (batch_id IS NOT NULL)::int = 1",
            name="ck_inv_qc_inspections_one_target",
        ),
        {"schema": "inv"},
    )

    qc_inspection_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    stock_document_line_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("inv.stock_document_lines.line_id")
    )
    batch_id: Mapped[int | None] = mapped_column(ForeignKey("inv.batches.batch_id"))
    inspected_by_user_id: Mapped[int] = mapped_column(ForeignKey("sec.users.user_id"))
    inspected_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")
    result_code: Mapped[str] = mapped_column(String(15))
    sampled_quantity: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 6))
    rejected_quantity: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 6))
    notes: Mapped[str | None] = mapped_column(Text)


# =======================================================================
# قیمت‌گذاری، برنامه‌ریزی و یکپارچگی — معادلِ 061_inventory_costing_planning_integration.sql
# =======================================================================
class CompanyCostingSettings(Base):
    __tablename__ = "company_costing_settings"
    __table_args__ = {"schema": "inv"}

    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"), primary_key=True)
    default_costing_method_id: Mapped[int] = mapped_column(
        SmallInteger, ForeignKey("inv.costing_methods.costing_method_id")
    )
    allow_item_override: Mapped[bool] = mapped_column(default=True)


class CostLayer(Base):
    __tablename__ = "cost_layers"
    __table_args__ = (
        CheckConstraint("remaining_quantity BETWEEN 0 AND original_quantity", name="ck_inv_cost_layers_remaining"),
        {"schema": "inv"},
    )

    cost_layer_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("inv.items.item_id"))
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("inv.warehouses.warehouse_id"))
    stock_ledger_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("inv.stock_ledger.ledger_id"))
    received_at: Mapped[datetime.datetime]
    original_quantity: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 6))
    remaining_quantity: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 6))
    unit_cost: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 6))


class StandardCost(Base):
    __tablename__ = "standard_costs"
    __table_args__ = {"schema": "inv"}

    item_id: Mapped[int] = mapped_column(ForeignKey("inv.items.item_id"), primary_key=True)
    effective_date: Mapped[datetime.date] = mapped_column(Date, primary_key=True)
    standard_unit_cost: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 6))


class ReorderPolicy(Base):
    __tablename__ = "reorder_policies"
    __table_args__ = (
        CheckConstraint(
            "max_qty IS NULL OR reorder_point_qty IS NULL OR max_qty > reorder_point_qty",
            name="ck_inv_reorder_policies_max_gt_point",
        ),
        {"schema": "inv"},
    )

    policy_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    item_id: Mapped[int] = mapped_column(ForeignKey("inv.items.item_id"))
    warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("inv.warehouses.warehouse_id"))
    min_qty: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 6))
    max_qty: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 6))
    reorder_point_qty: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 6))
    reorder_qty: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 6))
    lead_time_days: Mapped[int | None] = mapped_column(SmallInteger)
    is_active: Mapped[bool] = mapped_column(default=True)


class ReorderSuggestionAcknowledgement(Base):
    __tablename__ = "reorder_suggestion_acknowledgements"
    __table_args__ = {"schema": "inv"}

    ack_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    item_id: Mapped[int] = mapped_column(ForeignKey("inv.items.item_id"))
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("inv.warehouses.warehouse_id"))
    acknowledged_by_user_id: Mapped[int] = mapped_column(ForeignKey("sec.users.user_id"))
    acknowledged_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")
    snooze_until: Mapped[datetime.date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(String(500))


class InventoryAccountMapping(Base):
    __tablename__ = "account_mappings"
    __table_args__ = {"schema": "inv"}

    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"), primary_key=True)
    mapping_key: Mapped[str] = mapped_column(String(30), primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("acc.chart_of_accounts.account_id"))


class FeatureDefinition(Base):
    __tablename__ = "feature_definitions"
    __table_args__ = {"schema": "inv"}

    feature_code: Mapped[str] = mapped_column(String(50), primary_key=True)
    name: Mapped[str] = mapped_column(String(150))
    category: Mapped[str] = mapped_column(String(30))
    requires_feature_code: Mapped[str | None] = mapped_column(ForeignKey("inv.feature_definitions.feature_code"))
    description: Mapped[str | None] = mapped_column(Text)


class CompanyFeature(Base):
    __tablename__ = "company_features"
    __table_args__ = {"schema": "inv"}

    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"), primary_key=True)
    feature_code: Mapped[str] = mapped_column(ForeignKey("inv.feature_definitions.feature_code"), primary_key=True)
    is_enabled: Mapped[bool] = mapped_column(default=False)


# =======================================================================
# انبارگردانی — معادلِ 062_inventory_cycle_count.sql
# =======================================================================
class CycleCountSession(Base):
    __tablename__ = "cycle_count_sessions"
    __table_args__ = (UniqueConstraint("company_id", "session_code"), {"schema": "inv"})

    session_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("inv.warehouses.warehouse_id"))
    session_code: Mapped[str] = mapped_column(String(30))
    scope_type_code: Mapped[str] = mapped_column(String(20))
    scope_filter: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    status_code: Mapped[str] = mapped_column(String(20), default="PLANNED")
    is_blind_count: Mapped[bool] = mapped_column(default=True)
    snapshot_at: Mapped[datetime.datetime | None]
    approved_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    approved_at: Mapped[datetime.datetime | None]
    resulting_stock_document_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("inv.stock_documents.stock_document_id")
    )
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("sec.users.user_id"))
    created_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")


class CycleCountLine(Base):
    __tablename__ = "cycle_count_lines"
    __table_args__ = {"schema": "inv"}

    line_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("inv.cycle_count_sessions.session_id"))
    item_id: Mapped[int] = mapped_column(ForeignKey("inv.items.item_id"))
    bin_location_id: Mapped[int] = mapped_column(ForeignKey("inv.bin_locations.bin_location_id"))
    batch_id: Mapped[int | None] = mapped_column(ForeignKey("inv.batches.batch_id"))
    expected_quantity_base: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 6))
    counted_quantity_base: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 6))
    variance_quantity_base: Mapped[decimal.Decimal | None] = mapped_column(
        Numeric(18, 6), Computed("counted_quantity_base - expected_quantity_base")
    )
    counted_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    counted_at: Mapped[datetime.datetime | None]
    recount_requested: Mapped[bool] = mapped_column(default=False)
    notes: Mapped[str | None] = mapped_column(String(500))


# =======================================================================
# داشبورد — معادلِ 063_inventory_dashboard.sql
# =======================================================================
class DailyKpiSnapshot(Base):
    __tablename__ = "daily_kpi_snapshots"
    __table_args__ = (UniqueConstraint("company_id", "snapshot_date"), {"schema": "inv"})

    snapshot_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    snapshot_date: Mapped[datetime.date] = mapped_column(Date)
    total_inventory_value: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2))
    total_active_items: Mapped[int]
    total_warehouses: Mapped[int]
    negative_balance_count: Mapped[int]
    near_expiry_value: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=0)
    critical_reorder_count: Mapped[int] = mapped_column(default=0)
    open_reservations_value: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=0)
