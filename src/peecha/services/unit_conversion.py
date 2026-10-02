"""سرویسِ مرکزیِ واحدِ اندازه‌گیری، واحدهایِ کالا، تبدیلِ واحد و بارکدِ هر
واحد (R225). همه‌یِ لایه‌ها (دسکتاپ، API موبایل، فروشِ حضوری، اسنادِ
تجاری/انبار) فقط از همین‌جا تبدیل و بارکد را می‌خوانند تا منطق تکرار نشود.

اصل‌ها:
- موجودی همیشه به واحدِ پایهٔ کالا نگه‌داری می‌شود (inventory_engine دست‌نخورده)؛
  ردیفِ سند واحد/مقدارِ انتخابیِ کاربر + ضریبِ همان لحظه (snapshot) را نگه می‌دارد.
- واحدهایِ هر کالا در inv.item_uom_conversions‌اند (ردیفِ پایه با is_base_unit).
- محاسبات با Decimal.
"""

from __future__ import annotations

import decimal
import re
from dataclasses import dataclass, field

from sqlalchemy import func, select

from peecha.db.base import new_session
from peecha.db.models.inventory import Item, ItemUnitBarcode, ItemUomConversion, Uom

_ONE = decimal.Decimal(1)

UOM_TYPE_LABELS = {
    "COUNT": "شمارشی", "WEIGHT": "وزن", "LENGTH": "طول", "AREA": "مساحت", "VOLUME": "حجم",
    "TIME": "زمان", "PACKAGING": "بسته‌بندی", "OTHER": "سایر",
}
BARCODE_TYPE_LABELS = {
    "EAN13": "EAN-13", "EAN8": "EAN-8", "UPCA": "UPC-A", "CODE128": "Code128", "CODE39": "Code39",
    "GS1": "GS1", "INTERNAL": "داخلی", "CUSTOM": "سفارشی",
}
_PURPOSES = ("PURCHASE", "SALES", "INVENTORY")


@dataclass
class ItemUnit:
    item_unit_id: int
    item_id: int
    uom_id: int
    code: str
    name: str
    symbol: str | None
    uom_type_code: str
    factor: decimal.Decimal
    is_base: bool
    is_purchase_unit: bool
    is_sales_unit: bool
    is_inventory_unit: bool
    is_default_purchase: bool
    is_default_sales: bool
    decimal_places: int
    allow_decimal: bool
    min_quantity: decimal.Decimal | None
    max_quantity: decimal.Decimal | None
    weight_kg: decimal.Decimal | None
    volume_m3: decimal.Decimal | None
    is_active: bool
    sort_order: int
    barcodes: list[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        return self.name or self.code


# ---------------------------------------------------------------------
# واحدهایِ کالا
# ---------------------------------------------------------------------
def ensure_base_unit(session, item: Item) -> ItemUomConversion:
    """ردیفِ واحدِ پایه را (اگر هنوز نیست، مثلاً کالایِ تازه) می‌سازد و با
    base_uom_idِ فعلیِ کالا همگام می‌کند."""
    rows = session.scalars(select(ItemUomConversion).where(ItemUomConversion.item_id == item.item_id)).all()
    base_row = next((r for r in rows if r.is_base_unit), None)
    if base_row is not None and base_row.uom_id == item.base_uom_id:
        return base_row
    if base_row is not None:
        base_row.is_base_unit = False
        base_row.is_inventory_unit = False
        session.flush()
    target = next((r for r in rows if r.uom_id == item.base_uom_id), None)
    has_purchase_default = any(r.is_purchase_default for r in rows if r is not target)
    has_sales_default = any(r.is_sales_default for r in rows if r is not target)
    if target is None:
        target = ItemUomConversion(item_id=item.item_id, uom_id=item.base_uom_id, conversion_factor=_ONE)
        session.add(target)
    target.conversion_factor = _ONE
    target.is_base_unit = True
    target.is_inventory_unit = True
    target.is_active = True
    target.sort_order = 0
    if not has_purchase_default:
        target.is_purchase_default = True
    if not has_sales_default:
        target.is_sales_default = True
    session.flush()
    return target


def _to_item_unit(row: ItemUomConversion, uom: Uom, barcodes: list[str]) -> ItemUnit:
    dp = row.decimal_places if row.decimal_places is not None else uom.decimal_places
    return ItemUnit(
        item_unit_id=row.conversion_id, item_id=row.item_id, uom_id=row.uom_id, code=uom.code, name=uom.name,
        symbol=uom.symbol, uom_type_code=uom.uom_type_code, factor=row.conversion_factor, is_base=row.is_base_unit,
        is_purchase_unit=row.is_purchase_unit, is_sales_unit=row.is_sales_unit, is_inventory_unit=row.is_inventory_unit,
        is_default_purchase=row.is_purchase_default, is_default_sales=row.is_sales_default,
        decimal_places=dp, allow_decimal=uom.allow_decimal and dp > 0,
        min_quantity=row.min_quantity, max_quantity=row.max_quantity, weight_kg=row.weight_kg, volume_m3=row.volume_m3,
        is_active=row.is_active and uom.is_active, sort_order=row.sort_order, barcodes=barcodes,
    )


def get_item_units(item_id: int, purpose: str | None = None, active_only: bool = True) -> list[ItemUnit]:
    """واحدهایِ کالا، اول واحدِ پایه. purpose=PURCHASE/SALES/INVENTORY فقط
    واحدهایِ مجاز برایِ همان نوعِ سند را برمی‌گرداند (واحدِ پایه همیشه مجاز است)."""
    with new_session() as session:
        item = session.get(Item, item_id)
        if item is None:
            return []
        ensure_base_unit(session, item)
        session.commit()
        rows = session.scalars(
            select(ItemUomConversion).where(ItemUomConversion.item_id == item_id)
            .order_by(ItemUomConversion.is_base_unit.desc(), ItemUomConversion.sort_order, ItemUomConversion.conversion_factor)
        ).all()
        uoms = {u.uom_id: u for u in session.scalars(select(Uom).where(Uom.uom_id.in_([r.uom_id for r in rows])))}
        barcodes: dict[int, list[str]] = {}
        for b in session.scalars(
            select(ItemUnitBarcode).where(ItemUnitBarcode.item_id == item_id, ItemUnitBarcode.is_active.is_(True))
            .order_by(ItemUnitBarcode.is_primary.desc(), ItemUnitBarcode.barcode_id)
        ):
            barcodes.setdefault(b.item_unit_id, []).append(b.barcode)
        result = []
        for r in rows:
            uom = uoms.get(r.uom_id)
            if uom is None:
                continue
            unit = _to_item_unit(r, uom, barcodes.get(r.conversion_id, []))
            if active_only and not unit.is_active and not unit.is_base:
                continue
            if purpose == "PURCHASE" and not (unit.is_purchase_unit or unit.is_base):
                continue
            if purpose == "SALES" and not (unit.is_sales_unit or unit.is_base):
                continue
            if purpose == "INVENTORY" and not (unit.is_inventory_unit or unit.is_base):
                continue
            result.append(unit)
        return result


def get_item_unit(item_id: int, uom_id: int, active_only: bool = False) -> ItemUnit | None:
    return next((u for u in get_item_units(item_id, active_only=active_only) if u.uom_id == uom_id), None)


def get_default_unit(item_id: int, purpose: str) -> ItemUnit | None:
    units = get_item_units(item_id, purpose=purpose)
    if purpose == "PURCHASE":
        chosen = next((u for u in units if u.is_default_purchase), None)
    elif purpose == "SALES":
        chosen = next((u for u in units if u.is_default_sales), None)
    else:
        chosen = None
    return chosen or next((u for u in units if u.is_base), None)


def purpose_for_document_type(document_type_code: str | None) -> str | None:
    code = document_type_code or ""
    if code.startswith("PURCHASE") or code == "CONSIGNMENT_IN":
        return "PURCHASE"
    if code.startswith("SALES") or code == "CONSIGNMENT_OUT":
        return "SALES"
    return None


def get_factor(item_id: int, uom_id: int, require_active: bool = False) -> decimal.Decimal:
    """ضریبِ تبدیلِ یک واحد به واحدِ پایهٔ کالا (پایه = ۱)."""
    with new_session() as session:
        item = session.get(Item, item_id)
        if item is None:
            raise ValueError("کالا نامعتبر است.")
        if uom_id == item.base_uom_id:
            return _ONE
        row = session.scalar(
            select(ItemUomConversion).where(ItemUomConversion.item_id == item_id, ItemUomConversion.uom_id == uom_id)
        )
        if row is None:
            raise ValueError("برایِ این واحد، تبدیل به واحدِ پایه‌یِ کالا در فرمِ کالا تعریف نشده است.")
        if require_active and not row.is_active:
            raise ValueError("این واحد برایِ این کالا غیرفعال است و در سندِ تازه قابلِ‌استفاده نیست.")
        return row.conversion_factor


def convert_to_base(item_id: int, quantity: decimal.Decimal, uom_id: int) -> tuple[decimal.Decimal, decimal.Decimal]:
    """(مقدارِ پایه، ضریب) -- مثلاً ۳ کارتنِ ۲۴تایی -> (۷۲، ۲۴)."""
    factor = get_factor(item_id, uom_id)
    return decimal.Decimal(quantity) * factor, factor


def convert_from_base(item_id: int, base_quantity: decimal.Decimal, uom_id: int) -> decimal.Decimal:
    return decimal.Decimal(base_quantity) / get_factor(item_id, uom_id)


def validate_quantity(
    item_id: int, uom_id: int, quantity: decimal.Decimal, purpose: str | None = None, check_min_max: bool = True,
    require_active: bool = True,
) -> ItemUnit:
    """اعتبارسنجیِ مقدار بر اساسِ واحد: فعال‌بودن، مجاز برایِ نوعِ سند،
    تعدادِ اعشار، حداقل/حداکثرِ هر واحد. واحدِ تعریف‌شده را برمی‌گرداند."""
    unit = get_item_unit(item_id, uom_id)
    if unit is None:
        raise ValueError("این واحد برایِ این کالا تعریف نشده است -- واحد را از «واحدها و بسته‌بندیِ» فرمِ کالا اضافه کنید.")
    if require_active and not unit.is_active and not unit.is_base:
        raise ValueError(f"واحدِ «{unit.label}» برایِ این کالا غیرفعال است و در سندِ تازه قابلِ‌استفاده نیست.")
    if purpose == "PURCHASE" and not (unit.is_purchase_unit or unit.is_base):
        raise ValueError(f"واحدِ «{unit.label}» برایِ خرید مجاز نیست.")
    if purpose == "SALES" and not (unit.is_sales_unit or unit.is_base):
        raise ValueError(f"واحدِ «{unit.label}» برایِ فروش مجاز نیست.")
    quantity = decimal.Decimal(quantity)
    if quantity <= 0:
        raise ValueError("مقدار باید بزرگ‌تر از صفر باشد.")
    exponent = -quantity.normalize().as_tuple().exponent
    if exponent > 0 and (not unit.allow_decimal or exponent > unit.decimal_places):
        if not unit.allow_decimal:
            raise ValueError(f"واحدِ «{unit.label}» اعشار نمی‌پذیرد -- مقدار باید عددِ صحیح باشد.")
        raise ValueError(f"واحدِ «{unit.label}» حداکثر {unit.decimal_places} رقمِ اعشار می‌پذیرد.")
    if check_min_max:
        if unit.min_quantity is not None and quantity < unit.min_quantity:
            raise ValueError(f"حداقلِ مقدار برایِ واحدِ «{unit.label}» {unit.min_quantity.normalize()} است.")
        if unit.max_quantity is not None and quantity > unit.max_quantity:
            raise ValueError(f"حداکثرِ مقدار برایِ واحدِ «{unit.label}» {unit.max_quantity.normalize()} است.")
    return unit


def set_item_unit(
    item_id: int, uom_id: int, conversion_factor: decimal.Decimal, *,
    is_purchase_unit: bool = True, is_sales_unit: bool = True, is_inventory_unit: bool = False,
    is_default_purchase: bool = False, is_default_sales: bool = False,
    decimal_places: int | None = None, min_quantity: decimal.Decimal | None = None,
    max_quantity: decimal.Decimal | None = None, weight_kg: decimal.Decimal | None = None,
    volume_m3: decimal.Decimal | None = None, is_active: bool = True, sort_order: int | None = None,
) -> int:
    """تعریف/ویرایشِ یک واحدِ کالا. تغییرِ ضریب فقط رویِ اسنادِ *تازه* اثر
    دارد -- ردیف‌هایِ ثبت‌شده ضریبِ لحظه‌یِ ثبتِ خودشان را دارند."""
    conversion_factor = decimal.Decimal(conversion_factor)
    if conversion_factor <= 0:
        raise ValueError("ضریبِ تبدیل باید بزرگ‌تر از صفر باشد.")
    if min_quantity is not None and max_quantity is not None and min_quantity > max_quantity:
        raise ValueError("حداقلِ مقدار نمی‌تواند از حداکثر بیشتر باشد.")
    if decimal_places is not None and not (0 <= decimal_places <= 6):
        raise ValueError("تعدادِ اعشار باید بینِ ۰ تا ۶ باشد.")
    with new_session() as session:
        item = session.get(Item, item_id)
        if item is None:
            raise ValueError("کالا نامعتبر است.")
        uom = session.get(Uom, uom_id)
        if uom is None or (uom.company_id is not None and uom.company_id != item.company_id):
            raise ValueError("واحد نامعتبر است.")
        ensure_base_unit(session, item)
        row = session.scalar(
            select(ItemUomConversion).where(ItemUomConversion.item_id == item_id, ItemUomConversion.uom_id == uom_id)
        )
        is_base = uom_id == item.base_uom_id
        if is_base and conversion_factor != _ONE:
            raise ValueError("ضریبِ واحدِ پایه همیشه ۱ است.")
        if is_base and not is_active:
            raise ValueError("واحدِ پایهٔ کالا قابلِ‌غیرفعال‌شدن نیست.")
        if row is None:
            row = ItemUomConversion(item_id=item_id, uom_id=uom_id, conversion_factor=conversion_factor)
            session.add(row)
            if sort_order is None:
                sort_order = (session.scalar(
                    select(func.max(ItemUomConversion.sort_order)).where(ItemUomConversion.item_id == item_id)
                ) or 0) + 1
        row.conversion_factor = conversion_factor
        row.is_purchase_unit = is_purchase_unit
        row.is_sales_unit = is_sales_unit
        row.is_inventory_unit = is_inventory_unit or is_base
        row.decimal_places = decimal_places
        row.min_quantity = min_quantity
        row.max_quantity = max_quantity
        row.weight_kg = weight_kg
        row.volume_m3 = volume_m3
        row.is_active = is_active
        if sort_order is not None:
            row.sort_order = sort_order
        row.updated_at = func.now()
        others = session.scalars(
            select(ItemUomConversion).where(ItemUomConversion.item_id == item_id, ItemUomConversion.uom_id != uom_id)
        ).all()
        if is_default_purchase:
            for o in others:
                o.is_purchase_default = False
        if is_default_sales:
            for o in others:
                o.is_sales_default = False
        row.is_purchase_default = is_default_purchase
        row.is_sales_default = is_default_sales
        session.flush()
        # همیشه یک پیش‌فرضِ خرید/فروش وجود داشته باشد (اگر نبود، واحدِ پایه).
        all_rows = others + [row]
        base_row = next(r for r in all_rows if r.is_base_unit)
        if not any(r.is_purchase_default for r in all_rows):
            base_row.is_purchase_default = True
        if not any(r.is_sales_default for r in all_rows):
            base_row.is_sales_default = True
        session.commit()
        return row.conversion_id


def _unit_is_used(session, item_id: int, uom_id: int) -> bool:
    from peecha.db.models.commercial import CommercialDocumentLine, PriceListItem
    from peecha.db.models.inventory import StockDocumentLine

    for model in (CommercialDocumentLine, StockDocumentLine, PriceListItem):
        if session.scalar(select(func.count()).select_from(model).where(model.item_id == item_id, model.uom_id == uom_id)):
            return True
    return False


def remove_item_unit(item_unit_id: int, item_id: int) -> str:
    """واحدِ استفاده‌شده در اسناد/قیمت‌ها فقط غیرفعال می‌شود (حذفِ سخت نه)؛
    واحدِ هرگز-استفاده‌نشده حذف می‌شود. خروجی: DEACTIVATED یا DELETED."""
    with new_session() as session:
        row = session.get(ItemUomConversion, item_unit_id)
        if row is None or row.item_id != item_id:
            raise ValueError("واحدِ کالا نامعتبر است.")
        if row.is_base_unit:
            raise ValueError("واحدِ پایهٔ کالا قابلِ‌حذف نیست.")
        has_barcodes = session.scalar(
            select(func.count()).select_from(ItemUnitBarcode).where(ItemUnitBarcode.item_unit_id == item_unit_id)
        )
        if _unit_is_used(session, item_id, row.uom_id) or has_barcodes:
            row.is_active = False
            row.is_purchase_default = False
            row.is_sales_default = False
            for b in session.scalars(select(ItemUnitBarcode).where(ItemUnitBarcode.item_unit_id == item_unit_id)):
                b.is_active = False
            outcome = "DEACTIVATED"
        else:
            session.delete(row)
            outcome = "DELETED"
        session.flush()
        item = session.get(Item, item_id)
        base_row = ensure_base_unit(session, item)
        rows = session.scalars(select(ItemUomConversion).where(ItemUomConversion.item_id == item_id)).all()
        if not any(r.is_purchase_default for r in rows):
            base_row.is_purchase_default = True
        if not any(r.is_sales_default for r in rows):
            base_row.is_sales_default = True
        session.commit()
        return outcome


def item_has_history(item_id: int) -> bool:
    from peecha.db.models.commercial import CommercialDocumentLine
    from peecha.db.models.inventory import StockDocumentLine

    with new_session() as session:
        return bool(
            session.scalar(select(func.count()).select_from(StockDocumentLine).where(StockDocumentLine.item_id == item_id))
            or session.scalar(select(func.count()).select_from(CommercialDocumentLine).where(CommercialDocumentLine.item_id == item_id))
        )


# ---------------------------------------------------------------------
# قیمتِ هر واحد
# ---------------------------------------------------------------------
def get_price_for_unit(
    company_id: int, item_id: int, uom_id: int, price_list_id: int | None = None,
    quantity: decimal.Decimal = _ONE,
) -> decimal.Decimal | None:
    """قیمتِ مستقلِ همان واحد در فهرستِ قیمت اولویت دارد؛ وگرنه قیمتِ واحدِ
    پایه × ضریب. بدونِ price_list_id، اولین فهرستِ قیمتِ فروشِ شرکت."""
    from peecha.db.models.commercial import PriceList
    from peecha.services import commercial_pricing as pricing_service

    with new_session() as session:
        if price_list_id is None:
            price_list_id = session.scalar(
                select(PriceList.price_list_id).where(
                    PriceList.company_id == company_id, PriceList.price_list_type_code == "SALES",
                ).order_by(PriceList.price_list_id)
            )
        if price_list_id is None:
            return None
        direct = pricing_service._lookup_tiered_price(session, price_list_id, item_id, uom_id, quantity)
        if direct is not None:
            return direct
        item = session.get(Item, item_id)
        if item is None or item.base_uom_id == uom_id:
            return None
    try:
        factor = get_factor(item_id, uom_id)
    except ValueError:
        return None
    with new_session() as session:
        per_base = pricing_service._lookup_tiered_price(session, price_list_id, item_id, item.base_uom_id, quantity * factor)
    return per_base * factor if per_base is not None else None


# ---------------------------------------------------------------------
# بارکد
# ---------------------------------------------------------------------
_PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def normalize_barcode(barcode: str | None) -> str:
    """Trim + حذفِ فاصله/کاراکترهایِ کنترلی + تبدیلِ ارقامِ فارسی/عربی + حروفِ بزرگ."""
    text = (barcode or "").translate(_PERSIAN_DIGITS)
    text = re.sub(r"[\s‌‏‎]+", "", text)
    return text.upper()


def _gtin_checksum_ok(digits: str) -> bool:
    body, check = digits[:-1], int(digits[-1])
    total = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body)))
    return (10 - total % 10) % 10 == check


def detect_barcode_type(barcode: str) -> str:
    if re.fullmatch(r"\d{13}", barcode) and _gtin_checksum_ok(barcode):
        return "EAN13"
    if re.fullmatch(r"\d{8}", barcode) and _gtin_checksum_ok(barcode):
        return "EAN8"
    if re.fullmatch(r"\d{12}", barcode) and _gtin_checksum_ok(barcode):
        return "UPCA"
    return "INTERNAL"


def validate_barcode_format(barcode: str, barcode_type: str) -> None:
    if not barcode:
        raise ValueError("بارکد خالی است.")
    if len(barcode) > 100:
        raise ValueError("بارکد بیش از حد طولانی است.")
    if barcode_type not in BARCODE_TYPE_LABELS:
        raise ValueError("نوعِ بارکد نامعتبر است.")
    fixed = {"EAN13": 13, "EAN8": 8, "UPCA": 12}
    if barcode_type in fixed:
        n = fixed[barcode_type]
        if not re.fullmatch(rf"\d{{{n}}}", barcode):
            raise ValueError(f"بارکدِ {BARCODE_TYPE_LABELS[barcode_type]} باید دقیقاً {n} رقم باشد.")
        if not _gtin_checksum_ok(barcode):
            raise ValueError(f"رقمِ کنترلیِ بارکدِ {BARCODE_TYPE_LABELS[barcode_type]} نادرست است.")
    elif barcode_type == "CODE39" and not re.fullmatch(r"[0-9A-Z\-. $/+%]+", barcode):
        raise ValueError("بارکدِ Code39 فقط ارقام، حروفِ بزرگِ لاتین و - . $ / + % را می‌پذیرد.")
    elif barcode_type == "GS1" and not re.fullmatch(r"[0-9A-Z()\-./]+", barcode):
        raise ValueError("بارکدِ GS1 کاراکترِ نامعتبر دارد.")


@dataclass
class BarcodeRow:
    barcode_id: int
    item_id: int
    item_code: str
    item_name: str
    item_unit_id: int
    uom_id: int
    unit_name: str
    factor: decimal.Decimal
    barcode: str
    barcode_type: str
    is_primary: bool
    is_active: bool
    description: str | None


def _item_labels(session, item_ids: list[int]) -> dict[int, tuple[str, str]]:
    from peecha.db.models.accounting import DetailAccount

    rows = session.execute(
        select(Item.item_id, DetailAccount.code, DetailAccount.name)
        .join(DetailAccount, DetailAccount.detail_account_id == Item.item_detail_account_id)
        .where(Item.item_id.in_(item_ids))
    ).all()
    return {r[0]: (r[1], r[2]) for r in rows}


def _find_active_barcode(session, company_id: int, barcode: str, exclude_barcode_id: int | None = None):
    stmt = select(ItemUnitBarcode).where(
        ItemUnitBarcode.company_id == company_id, ItemUnitBarcode.barcode == barcode, ItemUnitBarcode.is_active.is_(True),
    )
    if exclude_barcode_id is not None:
        stmt = stmt.where(ItemUnitBarcode.barcode_id != exclude_barcode_id)
    return session.scalar(stmt)


def _duplicate_message(session, existing: ItemUnitBarcode) -> str:
    labels = _item_labels(session, [existing.item_id])
    code, name = labels.get(existing.item_id, ("", ""))
    unit_row = session.get(ItemUomConversion, existing.item_unit_id)
    uom = session.get(Uom, unit_row.uom_id) if unit_row else None
    return f"این بارکد قبلاً برایِ کالایِ «{code} — {name}» با واحدِ «{uom.name if uom else ''}» ثبت شده است."


def _check_legacy_duplicate(session, company_id: int, barcode: str, item_id: int) -> None:
    """بارکدهایِ قدیمیِ inv.items.barcode که (به‌علتِ تکرار) به جدولِ تازه منتقل نشده‌اند هم چک می‌شوند."""
    other = session.scalar(
        select(Item).where(Item.company_id == company_id, func.btrim(Item.barcode) == barcode, Item.item_id != item_id)
    )
    if other is not None:
        code, name = _item_labels(session, [other.item_id]).get(other.item_id, ("", ""))
        raise ValueError(f"این بارکد قبلاً برایِ کالایِ «{code} — {name}» ثبت شده است.")


def _sync_item_barcode(session, item_id: int) -> None:
    """سازگاری: inv.items.barcode همیشه = بارکدِ اصلیِ واحدِ پایه (اگر باشد)."""
    item = session.get(Item, item_id)
    base_row = ensure_base_unit(session, item)
    primary = session.scalar(
        select(ItemUnitBarcode).where(
            ItemUnitBarcode.item_unit_id == base_row.conversion_id, ItemUnitBarcode.is_active.is_(True),
        ).order_by(ItemUnitBarcode.is_primary.desc(), ItemUnitBarcode.barcode_id)
    )
    if primary is not None:
        item.barcode = primary.barcode
    elif item.barcode and session.scalar(
        select(func.count()).select_from(ItemUnitBarcode).where(
            ItemUnitBarcode.item_id == item_id, ItemUnitBarcode.barcode == normalize_barcode(item.barcode),
        )
    ):
        # فقط اگر همان بارکد در جدولِ تازه غیرفعال شده؛ بارکدِ قدیمیِ منتقل‌نشده دست‌نخورده می‌ماند.
        item.barcode = None


def add_barcode(
    company_id: int, item_id: int, uom_id: int, barcode: str, barcode_type: str | None = None,
    is_primary: bool = False, description: str | None = None,
) -> int:
    barcode = normalize_barcode(barcode)
    barcode_type = barcode_type or detect_barcode_type(barcode)
    validate_barcode_format(barcode, barcode_type)
    with new_session() as session:
        item = session.get(Item, item_id)
        if item is None or item.company_id != company_id:
            raise ValueError("کالا نامعتبر است.")
        ensure_base_unit(session, item)
        unit_row = session.scalar(
            select(ItemUomConversion).where(ItemUomConversion.item_id == item_id, ItemUomConversion.uom_id == uom_id)
        )
        if unit_row is None:
            raise ValueError("این واحد برایِ این کالا تعریف نشده است.")
        if not unit_row.is_active:
            raise ValueError("برایِ واحدِ غیرفعال نمی‌توان بارکدِ فعال ثبت کرد.")
        existing = _find_active_barcode(session, company_id, barcode)
        if existing is not None:
            if existing.item_id == item_id and existing.item_unit_id == unit_row.conversion_id:
                raise ValueError("این بارکد قبلاً برایِ همین کالا و واحد ثبت شده است.")
            raise ValueError(_duplicate_message(session, existing))
        _check_legacy_duplicate(session, company_id, barcode, item_id)
        has_primary = session.scalar(
            select(func.count()).select_from(ItemUnitBarcode).where(
                ItemUnitBarcode.item_unit_id == unit_row.conversion_id, ItemUnitBarcode.is_active.is_(True),
                ItemUnitBarcode.is_primary.is_(True),
            )
        )
        if is_primary or not has_primary:
            for b in session.scalars(select(ItemUnitBarcode).where(ItemUnitBarcode.item_unit_id == unit_row.conversion_id)):
                b.is_primary = False
            is_primary = True
        row = ItemUnitBarcode(
            company_id=company_id, item_id=item_id, item_unit_id=unit_row.conversion_id, barcode=barcode,
            barcode_type=barcode_type, is_primary=is_primary, description=(description or None),
        )
        session.add(row)
        session.flush()
        _sync_item_barcode(session, item_id)
        session.commit()
        return row.barcode_id


def update_barcode(
    barcode_id: int, company_id: int, barcode: str, barcode_type: str, is_primary: bool, is_active: bool,
    description: str | None = None,
) -> None:
    barcode = normalize_barcode(barcode)
    validate_barcode_format(barcode, barcode_type)
    with new_session() as session:
        row = session.get(ItemUnitBarcode, barcode_id)
        if row is None or row.company_id != company_id:
            raise ValueError("بارکد نامعتبر است.")
        if is_active:
            existing = _find_active_barcode(session, company_id, barcode, exclude_barcode_id=barcode_id)
            if existing is not None:
                raise ValueError(_duplicate_message(session, existing))
            _check_legacy_duplicate(session, company_id, barcode, row.item_id)
        row.barcode = barcode
        row.barcode_type = barcode_type
        row.is_active = is_active
        row.description = description or None
        row.updated_at = func.now()
        if is_primary and is_active:
            for b in session.scalars(select(ItemUnitBarcode).where(ItemUnitBarcode.item_unit_id == row.item_unit_id)):
                b.is_primary = b.barcode_id == barcode_id
        elif not is_active:
            row.is_primary = False
        session.flush()
        _sync_item_barcode(session, row.item_id)
        session.commit()


def set_primary_barcode(barcode_id: int, company_id: int) -> None:
    with new_session() as session:
        row = session.get(ItemUnitBarcode, barcode_id)
        if row is None or row.company_id != company_id or not row.is_active:
            raise ValueError("فقط بارکدِ فعال می‌تواند اصلی باشد.")
        for b in session.scalars(select(ItemUnitBarcode).where(ItemUnitBarcode.item_unit_id == row.item_unit_id)):
            b.is_primary = b.barcode_id == barcode_id
        session.flush()
        _sync_item_barcode(session, row.item_id)
        session.commit()


def deactivate_barcode(barcode_id: int, company_id: int) -> None:
    """بارکد هرگز حذفِ سخت نمی‌شود (ممکن است رویِ برچسب‌هایِ چاپ‌شده/سوابق باشد)."""
    with new_session() as session:
        row = session.get(ItemUnitBarcode, barcode_id)
        if row is None or row.company_id != company_id:
            raise ValueError("بارکد نامعتبر است.")
        row.is_active = False
        was_primary = row.is_primary
        row.is_primary = False
        session.flush()
        if was_primary:
            nxt = session.scalar(
                select(ItemUnitBarcode).where(
                    ItemUnitBarcode.item_unit_id == row.item_unit_id, ItemUnitBarcode.is_active.is_(True),
                ).order_by(ItemUnitBarcode.barcode_id)
            )
            if nxt is not None:
                nxt.is_primary = True
        _sync_item_barcode(session, row.item_id)
        session.commit()


def set_item_base_barcode(company_id: int, item_id: int, barcode: str | None) -> None:
    """سازگاری با فیلدِ قدیمیِ «بارکد» در فرمِ کالا: بارکدِ اصلیِ واحدِ پایه را تنظیم می‌کند."""
    barcode = normalize_barcode(barcode)
    with new_session() as session:
        item = session.get(Item, item_id)
        base_row = ensure_base_unit(session, item)
        base_uom_id = base_row.uom_id
        current = session.scalar(
            select(ItemUnitBarcode).where(
                ItemUnitBarcode.item_unit_id == base_row.conversion_id, ItemUnitBarcode.is_active.is_(True),
                ItemUnitBarcode.is_primary.is_(True),
            )
        )
        current_id = current.barcode_id if current is not None else None
        current_code = current.barcode if current is not None else None
        existing = _find_active_barcode(session, company_id, barcode) if barcode else None
        existing_same_item_id = existing.barcode_id if existing is not None and existing.item_id == item_id else None
        session.commit()
    if current_code == barcode:
        return
    if not barcode:
        if current_id is not None:
            deactivate_barcode(current_id, company_id)
        return
    if existing_same_item_id is not None:
        set_primary_barcode(existing_same_item_id, company_id)
        return
    add_barcode(company_id, item_id, base_uom_id, barcode, is_primary=True)


def list_barcodes(
    company_id: int, item_id: int | None = None, search: str | None = None, include_inactive: bool = True,
) -> list[BarcodeRow]:
    with new_session() as session:
        stmt = (
            select(ItemUnitBarcode, ItemUomConversion, Uom)
            .join(ItemUomConversion, ItemUomConversion.conversion_id == ItemUnitBarcode.item_unit_id)
            .join(Uom, Uom.uom_id == ItemUomConversion.uom_id)
            .where(ItemUnitBarcode.company_id == company_id)
        )
        if item_id is not None:
            stmt = stmt.where(ItemUnitBarcode.item_id == item_id)
        if not include_inactive:
            stmt = stmt.where(ItemUnitBarcode.is_active.is_(True))
        if search:
            stmt = stmt.where(ItemUnitBarcode.barcode.ilike(f"%{normalize_barcode(search)}%"))
        rows = session.execute(stmt.order_by(ItemUnitBarcode.item_id, ItemUomConversion.sort_order, ItemUnitBarcode.barcode_id)).all()
        labels = _item_labels(session, list({r[0].item_id for r in rows}))
        return [
            BarcodeRow(
                b.barcode_id, b.item_id, labels.get(b.item_id, ("", ""))[0], labels.get(b.item_id, ("", ""))[1],
                u.conversion_id, u.uom_id, m.name, u.conversion_factor, b.barcode, b.barcode_type, b.is_primary,
                b.is_active, b.description,
            )
            for b, u, m in rows
        ]


def find_duplicate_barcodes(company_id: int) -> list[tuple[str, list[int]]]:
    """Barcode Manager: بارکدهایِ تکرارشده بینِ کالاها (شاملِ بارکدهایِ قدیمیِ inv.items)."""
    with new_session() as session:
        seen: dict[str, set[int]] = {}
        for b in session.scalars(
            select(ItemUnitBarcode).where(ItemUnitBarcode.company_id == company_id, ItemUnitBarcode.is_active.is_(True))
        ):
            seen.setdefault(b.barcode, set()).add(b.item_id)
        for item in session.scalars(select(Item).where(Item.company_id == company_id, Item.barcode.is_not(None))):
            code = normalize_barcode(item.barcode)
            if code:
                seen.setdefault(code, set()).add(item.item_id)
        return sorted((code, sorted(ids)) for code, ids in seen.items() if len(ids) > 1)


@dataclass
class BarcodeMatch:
    item_id: int
    item_code: str
    item_name: str
    uom_id: int
    unit_name: str
    factor: decimal.Decimal
    barcode: str
    item_unit_id: int | None
    default_price: decimal.Decimal | None = None


def resolve_barcode(
    company_id: int, barcode: str, price_list_id: int | None = None, with_price: bool = True,
) -> BarcodeMatch | None:
    """بارکد -> کالا + واحد + ضریب (+ قیمتِ پیش‌فرضِ همان واحد).
    اولویت: بارکدِ فعالِ واحد؛ سپس بارکدِ قدیمیِ inv.items.barcode (واحدِ پایه)."""
    code = normalize_barcode(barcode)
    if not code:
        return None
    with new_session() as session:
        row = _find_active_barcode(session, company_id, code)
        if row is not None:
            unit_row = session.get(ItemUomConversion, row.item_unit_id)
            if unit_row is None or not unit_row.is_active:
                return None
            uom = session.get(Uom, unit_row.uom_id)
            item_id, uom_id, factor, item_unit_id = row.item_id, unit_row.uom_id, unit_row.conversion_factor, unit_row.conversion_id
            unit_name = uom.name if uom else ""
        else:
            item = session.scalar(
                select(Item).where(Item.company_id == company_id, func.upper(func.btrim(Item.barcode)) == code)
            )
            if item is None:
                return None
            uom = session.get(Uom, item.base_uom_id)
            item_id, uom_id, factor, item_unit_id = item.item_id, item.base_uom_id, _ONE, None
            unit_name = uom.name if uom else ""
        item_code, item_name = _item_labels(session, [item_id]).get(item_id, ("", ""))
    price = get_price_for_unit(company_id, item_id, uom_id, price_list_id) if with_price else None
    return BarcodeMatch(item_id, item_code, item_name, uom_id, unit_name, factor, code, item_unit_id, price)


def assert_barcode_available(company_id: int, barcode: str | None, item_id: int | None = None) -> None:
    """پیش از ساخت/ویرایشِ کالا: بارکدِ تکراری (فعال، متعلق به کالایِ دیگر) رد می‌شود."""
    code = normalize_barcode(barcode)
    if not code:
        return
    with new_session() as session:
        existing = _find_active_barcode(session, company_id, code)
        if existing is not None and existing.item_id != item_id:
            raise ValueError(_duplicate_message(session, existing))
        other = session.scalar(
            select(Item).where(Item.company_id == company_id, func.upper(func.btrim(Item.barcode)) == code)
            .where(Item.item_id != (item_id or 0))
        )
        if other is not None:
            item_code, name = _item_labels(session, [other.item_id]).get(other.item_id, ("", ""))
            raise ValueError(f"این بارکد قبلاً برایِ کالایِ «{item_code} — {name}» ثبت شده است.")


def get_units_for_items(
    company_id: int, item_ids: list[int], purpose: str | None = "SALES", price_list_id: int | None = None,
) -> dict[int, list[dict]]:
    """نسخهٔ گروهیِ get_item_units برایِ کاتالوگِ موبایل/POS (بدونِ یک کوئری به‌ازایِ هر کالا):
    واحدهایِ فعالِ مجاز + بارکدها + قیمتِ هر واحد (قیمتِ مستقلِ واحد، وگرنه پایه × ضریب)."""
    from peecha.db.models.commercial import PriceList, PriceListItem

    if not item_ids:
        return {}
    with new_session() as session:
        items = {i.item_id: i for i in session.scalars(select(Item).where(Item.item_id.in_(item_ids)))}
        rows = session.scalars(
            select(ItemUomConversion).where(ItemUomConversion.item_id.in_(item_ids))
            .order_by(ItemUomConversion.item_id, ItemUomConversion.is_base_unit.desc(), ItemUomConversion.sort_order)
        ).all()
        uoms = {u.uom_id: u for u in session.scalars(select(Uom))}
        barcodes: dict[int, list[str]] = {}
        for b in session.scalars(
            select(ItemUnitBarcode).where(ItemUnitBarcode.item_id.in_(item_ids), ItemUnitBarcode.is_active.is_(True))
            .order_by(ItemUnitBarcode.is_primary.desc(), ItemUnitBarcode.barcode_id)
        ):
            barcodes.setdefault(b.item_unit_id, []).append(b.barcode)
        if price_list_id is None:
            price_list_id = session.scalar(
                select(PriceList.price_list_id).where(
                    PriceList.company_id == company_id, PriceList.price_list_type_code == "SALES",
                ).order_by(PriceList.price_list_id)
            )
        prices: dict[tuple[int, int], decimal.Decimal] = {}
        if price_list_id is not None:
            for p in session.scalars(
                select(PriceListItem).where(PriceListItem.price_list_id == price_list_id, PriceListItem.item_id.in_(item_ids))
                .order_by(PriceListItem.min_quantity)
            ):
                prices.setdefault((p.item_id, p.uom_id), p.unit_price)
    by_item: dict[int, list[ItemUnit]] = {}
    seen_base: set[int] = set()
    for r in rows:
        uom = uoms.get(r.uom_id)
        item = items.get(r.item_id)
        if uom is None or item is None:
            continue
        unit = _to_item_unit(r, uom, barcodes.get(r.conversion_id, []))
        unit.is_base = r.uom_id == item.base_uom_id
        if unit.is_base:
            seen_base.add(r.item_id)
        by_item.setdefault(r.item_id, []).append(unit)
    for item_id, item in items.items():
        if item_id not in seen_base and item.base_uom_id in uoms:
            uom = uoms[item.base_uom_id]
            by_item.setdefault(item_id, []).insert(0, ItemUnit(
                0, item_id, uom.uom_id, uom.code, uom.name, uom.symbol, uom.uom_type_code, _ONE, True, True, True, True,
                True, True, uom.decimal_places, uom.allow_decimal and uom.decimal_places > 0, None, None, None, None,
                True, 0, [item.barcode] if item.barcode else [],
            ))
    result: dict[int, list[dict]] = {}
    for item_id, units in by_item.items():
        item = items[item_id]
        base_price = prices.get((item_id, item.base_uom_id))
        out = []
        for u in units:
            if not u.is_base and not u.is_active:
                continue
            if purpose == "SALES" and not (u.is_sales_unit or u.is_base):
                continue
            if purpose == "PURCHASE" and not (u.is_purchase_unit or u.is_base):
                continue
            price = prices.get((item_id, u.uom_id))
            if price is None and base_price is not None:
                price = base_price * u.factor
            out.append({
                "uom_id": u.uom_id, "item_unit_id": u.item_unit_id or None, "code": u.code, "name": u.name,
                "symbol": u.symbol, "factor": format(u.factor.normalize(), "f"), "is_base": u.is_base,
                "is_default_sales": u.is_default_sales, "is_default_purchase": u.is_default_purchase,
                "decimal_places": u.decimal_places, "allow_decimal": u.allow_decimal,
                "min_quantity": str(u.min_quantity) if u.min_quantity is not None else None,
                "max_quantity": str(u.max_quantity) if u.max_quantity is not None else None,
                "price": str(price) if price is not None else None, "barcodes": u.barcodes,
            })
        result[item_id] = out
    return result
