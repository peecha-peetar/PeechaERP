"""سرویسِ ویژگی/متغیرِ کالا — طبقِ درخواستِ صریح: امکانِ تعریفِ ویژگی
(سایز، وزن، مدل و ...)، تعریفِ مقادیرِ هر ویژگی، تولیدِ خودکارِ ترکیبِ
متغیرها برایِ یک کالا، و بارکدِ مجزا برایِ کالایِ اصلی + بارکدِ ترکیبی
برایِ هر متغیر.

جدول‌هایِ inv.item_attributes / inv.item_attribute_values /
inv.item_variant_values و ستونِ inv.items.variant_parent_item_id از
معماریِ اولیه (۰۵۷_inventory_catalog.sql) از پیش موجودند؛ این سرویس اولین
لایه‌یِ واقعیِ استفاده از آن‌هاست."""

from __future__ import annotations

import itertools
from dataclasses import dataclass

from sqlalchemy import delete, func, select

from peecha import ean13
from peecha.db.base import new_session
from peecha.db.models.inventory import Item, ItemAttribute, ItemAttributeValue, ItemVariantValue
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import inventory_catalog as catalog_service


@dataclass
class ItemAttributeRow:
    attribute_id: int
    code: str
    name: str
    is_active: bool


def list_item_attributes(company_id: int, active_only: bool = False) -> list[ItemAttributeRow]:
    with new_session() as session:
        query = select(ItemAttribute).where(ItemAttribute.company_id == company_id)
        if active_only:
            query = query.where(ItemAttribute.is_active)
        rows = session.scalars(query.order_by(ItemAttribute.name)).all()
        return [ItemAttributeRow(r.attribute_id, r.code, r.name, r.is_active) for r in rows]


def create_item_attribute(company_id: int, code: str, name: str) -> int:
    code = code.strip()
    name = name.strip()
    if not code or not name:
        raise ValueError("کد و نامِ ویژگی نمی‌توانند خالی باشند.")
    with new_session() as session:
        if session.scalar(
            select(ItemAttribute).where(ItemAttribute.company_id == company_id, ItemAttribute.code == code)
        ):
            raise ValueError(f"ویژگی‌ای با کدِ «{code}» از قبل وجود دارد.")
        attribute = ItemAttribute(company_id=company_id, code=code, name=name)
        session.add(attribute)
        session.commit()
        return attribute.attribute_id


def update_item_attribute(attribute_id: int, company_id: int, code: str, name: str, is_active: bool) -> None:
    code = code.strip()
    name = name.strip()
    if not code or not name:
        raise ValueError("کد و نامِ ویژگی نمی‌توانند خالی باشند.")
    with new_session() as session:
        attribute = session.get(ItemAttribute, attribute_id)
        if attribute is None or attribute.company_id != company_id:
            raise ValueError("ویژگی نامعتبر است.")
        duplicate = session.scalar(
            select(ItemAttribute).where(
                ItemAttribute.company_id == company_id, ItemAttribute.code == code,
                ItemAttribute.attribute_id != attribute_id,
            )
        )
        if duplicate:
            raise ValueError(f"ویژگی‌ای با کدِ «{code}» از قبل وجود دارد.")
        attribute.code = code
        attribute.name = name
        attribute.is_active = is_active
        session.commit()


def delete_item_attribute(attribute_id: int, company_id: int) -> None:
    with new_session() as session:
        attribute = session.get(ItemAttribute, attribute_id)
        if attribute is None or attribute.company_id != company_id:
            raise ValueError("ویژگی نامعتبر است.")
        if session.scalar(select(ItemVariantValue).where(ItemVariantValue.attribute_id == attribute_id)):
            raise ValueError("این ویژگی برایِ ساختِ متغیرهایی استفاده شده و قابلِ‌حذف نیست.")
        session.execute(delete(ItemAttributeValue).where(ItemAttributeValue.attribute_id == attribute_id))
        session.delete(attribute)
        session.commit()


@dataclass
class ItemAttributeValueRow:
    value_id: int
    attribute_id: int
    code: str
    value: str
    display_order: int


def list_item_attribute_values(attribute_id: int) -> list[ItemAttributeValueRow]:
    with new_session() as session:
        rows = session.scalars(
            select(ItemAttributeValue)
            .where(ItemAttributeValue.attribute_id == attribute_id)
            .order_by(ItemAttributeValue.display_order, ItemAttributeValue.value)
        ).all()
        return [ItemAttributeValueRow(r.value_id, r.attribute_id, r.code, r.value, r.display_order) for r in rows]


def add_item_attribute_value(attribute_id: int, code: str, value: str, display_order: int = 0) -> int:
    code = code.strip()
    value = value.strip()
    if not code or not value:
        raise ValueError("کد و مقدار نمی‌توانند خالی باشند.")
    with new_session() as session:
        if session.get(ItemAttribute, attribute_id) is None:
            raise ValueError("ویژگی نامعتبر است.")
        if session.scalar(
            select(ItemAttributeValue).where(
                ItemAttributeValue.attribute_id == attribute_id, ItemAttributeValue.code == code
            )
        ):
            raise ValueError(f"مقداری با کدِ «{code}» از قبل برایِ این ویژگی وجود دارد.")
        row = ItemAttributeValue(attribute_id=attribute_id, code=code, value=value, display_order=display_order)
        session.add(row)
        session.commit()
        return row.value_id


def update_item_attribute_value(value_id: int, code: str, value: str, display_order: int) -> None:
    code = code.strip()
    value = value.strip()
    if not code or not value:
        raise ValueError("کد و مقدار نمی‌توانند خالی باشند.")
    with new_session() as session:
        row = session.get(ItemAttributeValue, value_id)
        if row is None:
            raise ValueError("مقدار نامعتبر است.")
        duplicate = session.scalar(
            select(ItemAttributeValue).where(
                ItemAttributeValue.attribute_id == row.attribute_id, ItemAttributeValue.code == code,
                ItemAttributeValue.value_id != value_id,
            )
        )
        if duplicate:
            raise ValueError(f"مقداری با کدِ «{code}» از قبل برایِ این ویژگی وجود دارد.")
        row.code = code
        row.value = value
        row.display_order = display_order
        session.commit()


def delete_item_attribute_value(value_id: int) -> None:
    with new_session() as session:
        row = session.get(ItemAttributeValue, value_id)
        if row is None:
            raise ValueError("مقدار نامعتبر است.")
        if session.scalar(select(ItemVariantValue).where(ItemVariantValue.value_id == value_id)):
            raise ValueError("این مقدار برایِ ساختِ متغیرهایی استفاده شده و قابلِ‌حذف نیست.")
        session.delete(row)
        session.commit()


@dataclass
class ItemVariantRow:
    variant_item_id: int
    item_detail_account_id: int
    code: str
    name: str | None
    barcode: str | None
    attribute_labels: str


def list_item_variants(company_id: int, parent_item_id: int) -> list[ItemVariantRow]:
    rows_by_id = {r.item_id: r for r in catalog_service.list_items(company_id)}
    with new_session() as session:
        variant_ids = session.scalars(
            select(Item.item_id).where(Item.variant_parent_item_id == parent_item_id)
        ).all()
        result: list[ItemVariantRow] = []
        for variant_item_id in variant_ids:
            item_row = rows_by_id.get(variant_item_id)
            if item_row is None:
                continue
            links = session.scalars(
                select(ItemVariantValue).where(ItemVariantValue.item_id == variant_item_id)
            ).all()
            labels = []
            for link in links:
                attribute = session.get(ItemAttribute, link.attribute_id)
                value = session.get(ItemAttributeValue, link.value_id)
                if attribute is not None and value is not None:
                    labels.append(f"{attribute.name}: {value.value}")
            result.append(
                ItemVariantRow(
                    variant_item_id=variant_item_id, item_detail_account_id=item_row.item_detail_account_id,
                    code=item_row.code, name=item_row.name,
                    barcode=item_row.barcode, attribute_labels="، ".join(labels),
                )
            )
        result.sort(key=lambda r: r.code)
        return result


def ensure_item_barcode(company_id: int, item_id: int) -> str:
    """اگر بارکدِ کالا (غیرِ متغیر) از قبل خالی باشد، یک بارکدِ مجزایِ
    خودکار (EAN-13 معتبر) برایِ آن می‌سازد -- طبقِ درخواستِ صریح («برایِ
    کالایِ اصلی بارکدِ مجزا»)."""
    with new_session() as session:
        item = session.get(Item, item_id)
        if item is None or item.company_id != company_id:
            raise ValueError("کالا نامعتبر است.")
        if item.barcode:
            return item.barcode
        if item.variant_parent_item_id is not None:
            raise ValueError("بارکدِ متغیرها خودکار و بر اساسِ کالایِ اصلی تولید می‌شود؛ اینجا قابلِ‌ساخت نیست.")
        barcode = ean13.generate_main_barcode(item_id)
        item.barcode = barcode
        session.commit()
        return barcode


def set_variant_notes(company_id: int, item_id: int, notes: str | None) -> None:
    """طبقِ درخواستِ صریح («برایِ هر متغیر توضیحاتِ مجزا»): تغییرِ سریعِ
    توضیحاتِ یک کالا/متغیر بدونِ نیاز به فرمِ کاملِ update_item."""
    with new_session() as session:
        item = session.get(Item, item_id)
        if item is None or item.company_id != company_id:
            raise ValueError("کالا نامعتبر است.")
        item.notes = notes
        session.commit()


def _sync_parent_transactability(company_id: int, parent_item_id: int) -> None:
    """طبقِ تصمیمِ صریح («کالایِ اصلی بعدِ داشتنِ متغیر، غیرِقابلِ‌فروش/
    غیرِموجودی‌محور شود»): به‌محضِ داشتنِ حداقل یک متغیر، خودِ کالایِ
    اصلی دیگر مستقیماً قابلِ‌فروش/خرید/موجودی‌محور نیست -- فقط خودِ
    متغیرهایش معامله می‌شوند (کالایِ اصلی صرفاً یک قالب/گروه می‌ماند).
    اگر آخرین متغیر هم حذف شود، این مقادیر خودکار به حالتِ فعال
    برمی‌گردند."""
    with new_session() as session:
        parent = session.get(Item, parent_item_id)
        if parent is None or parent.company_id != company_id:
            return
        has_variants = (
            session.scalar(
                select(func.count()).select_from(Item).where(Item.variant_parent_item_id == parent_item_id)
            )
            or 0
        ) > 0
        if has_variants and (parent.is_sellable or parent.is_purchasable or parent.is_stock_tracked):
            parent.is_sellable = False
            parent.is_purchasable = False
            parent.is_stock_tracked = False
            session.commit()
        elif not has_variants and not (parent.is_sellable or parent.is_purchasable or parent.is_stock_tracked):
            parent.is_sellable = True
            parent.is_purchasable = True
            parent.is_stock_tracked = True
            session.commit()


def delete_item_variant(company_id: int, parent_item_id: int, variant_item_id: int) -> None:
    catalog_service.delete_item(variant_item_id, company_id)
    _sync_parent_transactability(company_id, parent_item_id)


def generate_item_variants(
    company_id: int, parent_item_id: int, attribute_value_ids: dict[int, list[int]],
) -> list[int]:
    """طبقِ درخواستِ صریح («برایِ کدِ کالا انواعِ ویژگی تولید کرد»): از رویِ
    ترکیبِ دکارتیِ مقادیرِ انتخاب‌شده برایِ هر ویژگی، به‌ازایِ هر ترکیب یک
    کالایِ «متغیر» تازه (هم‌سطح و هم‌گروهِ کالایِ اصلی) می‌سازد و آن را با
    variant_parent_item_id به کالایِ اصلی وصل می‌کند. ترکیب‌هایی که قبلاً
    برایِ همین کالا ساخته شده باشند، دوباره ساخته نمی‌شوند (idempotent).
    هر متغیرِ تازه یک «بارکدِ ترکیبی» (EAN-13، ترکیبِ شناسهٔ کالایِ اصلی +
    شمارهٔ ترتیبیِ متغیر) خودکار می‌گیرد."""
    attribute_value_ids = {aid: list(vals) for aid, vals in attribute_value_ids.items() if vals}
    if not attribute_value_ids:
        raise ValueError("حداقل یک ویژگی با حداقل یک مقدارِ انتخاب‌شده لازم است.")

    parent = catalog_service.get_item(parent_item_id)
    if parent is None or parent.company_id != company_id:
        raise ValueError("کالایِ اصلی نامعتبر است.")
    if parent.variant_parent_item_id is not None:
        raise ValueError("خودِ یک متغیر نمی‌تواند والدِ متغیرهایِ دیگر باشد.")

    dimension_type_id = dimensions_service.get_specialized_dimension_type_id(
        company_id, catalog_service.ITEM_DIMENSION_CODE
    )
    detail_rows = {
        r.detail_account_id: r for r in dimensions_service.list_detail_accounts(company_id, dimension_type_id)
    }
    parent_detail = detail_rows.get(parent.item_detail_account_id)
    if parent_detail is None:
        raise ValueError("تفصیلیِ کالایِ اصلی یافت نشد.")

    attribute_ids_sorted = sorted(attribute_value_ids.keys())
    with new_session() as session:
        values_by_id: dict[int, ItemAttributeValue] = {}
        for attribute_id in attribute_ids_sorted:
            for value_row in session.scalars(
                select(ItemAttributeValue).where(ItemAttributeValue.attribute_id == attribute_id)
            ):
                values_by_id[value_row.value_id] = value_row

        existing_variants = session.scalars(
            select(Item).where(Item.variant_parent_item_id == parent_item_id)
        ).all()
        existing_combo_keys: set[tuple] = set()
        for variant_item in existing_variants:
            links = session.scalars(
                select(ItemVariantValue).where(ItemVariantValue.item_id == variant_item.item_id)
            ).all()
            existing_combo_keys.add(tuple(sorted((link.attribute_id, link.value_id) for link in links)))
        # طبقِ رفعِ باگِ واقعیِ کشف‌شده‌یِ حینِ تست: شمارهٔ ترتیبیِ بارکدِ
        # متغیرِ بعدی نباید صرفاً از رویِ *تعدادِ* متغیرهایِ موجود حساب شود --
        # اگر یک متغیر حذف شده باشد، تعداد کمتر از بزرگ‌ترین شماره‌یِ
        # واقعاً استفاده‌شده می‌شود و شمارهٔ تازه با یک متغیرِ باقی‌مانده
        # برخورد (تکراری) می‌کند. به‌جایش بزرگ‌ترین شمارهٔ واقعاً
        # استفاده‌شده (از رویِ ۳ رقمِ آخرِ بارکدهایِ موجود) پایه قرار
        # می‌گیرد.
        barcode_prefix = f"{ean13.INTERNAL_USE_PREFIX}{parent_item_id:07d}"
        used_sequences = [
            int(v.barcode[9:12]) for v in existing_variants
            if v.barcode and len(v.barcode) == 13 and v.barcode.startswith(barcode_prefix)
        ]
        variant_sequence = max(used_sequences, default=0)

    value_lists = [attribute_value_ids[aid] for aid in attribute_ids_sorted]
    created_ids: list[int] = []
    for combo in itertools.product(*value_lists):
        combo_key = tuple(sorted(zip(attribute_ids_sorted, combo)))
        if combo_key in existing_combo_keys:
            continue
        variant_sequence += 1
        value_labels = [values_by_id[value_id].value for value_id in combo if value_id in values_by_id]
        variant_name = f"{parent_detail.name} ({' / '.join(value_labels)})" if parent_detail.name else None
        variant_code = dimensions_service.suggest_next_code(
            company_id, dimension_type_id, parent_detail.level_no, parent_detail.person_group_id or 0
        )
        variant_fields = catalog_service.ItemFields(
            item_kind_code=parent.item_kind_code, base_uom_id=parent.base_uom_id,
            brand_id=parent.brand_id, manufacturer_id=parent.manufacturer_id,
            variant_parent_item_id=parent_item_id, costing_method_code=parent.costing_method_code,
            is_sellable=parent.is_sellable, is_purchasable=parent.is_purchasable,
            is_stock_tracked=parent.is_stock_tracked, track_serial=parent.track_serial,
            track_batch=parent.track_batch, track_expiry=parent.track_expiry,
        )
        variant_item_id = catalog_service.create_item(
            company_id, variant_code, variant_name or parent_detail.code, variant_fields,
            parent_detail_account_id=parent_detail.parent_detail_account_id,
        )
        with new_session() as session:
            for attribute_id, value_id in zip(attribute_ids_sorted, combo):
                session.add(ItemVariantValue(item_id=variant_item_id, attribute_id=attribute_id, value_id=value_id))
            item_row = session.get(Item, variant_item_id)
            item_row.barcode = ean13.generate_variant_barcode(parent_item_id, variant_sequence)
            session.commit()
        existing_combo_keys.add(combo_key)
        created_ids.append(variant_item_id)
    if created_ids:
        _sync_parent_transactability(company_id, parent_item_id)
    return created_ids
