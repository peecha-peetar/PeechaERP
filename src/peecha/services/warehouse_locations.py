"""مدیریتِ محلِ انبار و نقشهٔ تعاملی -- R248 (لایهٔ WMS رویِ همان inv.bin_locations).

- سلسله‌مراتب: انبار ← AREA (منطقه/Zone) ← AISLE (راهرو) ← RACK (قفسه) ← SHELF (طبقه/Level) ← BIN.
  سطح همان ستونِ موجودِ bin_type_code است؛ کدِ کاملِ محل (location_code) مثلِ WH01-Z01-A03-R02-L04-B07 یکتاست.
- موجودی هرگز این‌جا نگه داشته نمی‌شود: محتوا، اشغال و محلِ کالا از inv.stock_balance (همان موجودیِ سیستم) خوانده می‌شود.
- جابه‌جاییِ کالا بینِ محل‌ها فقط با سندِ انتقالِ عادیِ سیستم (inventory_documents) انجام می‌شود.
- تاریخچه: حرکات از inv.stock_ledger و تغییرِ مشخصات از audit.activity_log موجود.
"""

from __future__ import annotations

import datetime
import decimal
import math
from collections import defaultdict
from dataclasses import dataclass, fields as dc_fields
from types import SimpleNamespace

from sqlalchemy import func, or_, select

from peecha.db.base import new_session
from peecha.db.models.inventory import (
    BinLocation, Item, ItemStorageProfile, SerialNumber, StockBalance, StockDocument, StockDocumentLine, StockLedger, Warehouse, WarehouseTask,
)
from peecha.services import audit as audit_service

_ZERO = decimal.Decimal(0)
FORM_CODE = "warehouse_map"  # کدِ فرمِ دسترسی (همان screenِ nav_catalog)
QR_PREFIX = "PEECHA-LOC"

LEVELS = ("AREA", "AISLE", "RACK", "SHELF", "BIN")
LEVEL_LABELS = {"AREA": "منطقه (Zone)", "AISLE": "راهرو", "RACK": "قفسه", "SHELF": "طبقه", "BIN": "محل (Bin)"}
LEVEL_PREFIX = {"AREA": "Z", "AISLE": "A", "RACK": "R", "SHELF": "L", "BIN": "B"}
_ALLOWED_PARENTS = {"AREA": (None,), "AISLE": ("AREA",), "RACK": ("AISLE", "AREA"), "SHELF": ("RACK",), "BIN": ("SHELF", "RACK")}
LOCATION_TYPES = {
    "RECEIVING": "دریافت", "QC": "کنترلِ کیفیت", "QUARANTINE": "قرنطینه", "BULK": "انبارشِ حجیم", "RESERVE": "ذخیره",
    "PICK_FACE": "جبههٔ برداشت", "PICKING": "برداشت", "STAGING": "آماده‌سازی", "SHIPPING": "ارسال", "RETURNS": "مرجوعی",
    "DAMAGED": "آسیب‌دیده", "HIGH_VALUE": "کالایِ گران‌بها", "COLD": "سردخانه", "FREEZER": "فریزر", "TRANSIT": "ترانزیت",
}
STATUSES = {"ACTIVE": "فعال", "INACTIVE": "غیرفعال", "BLOCKED": "مسدود", "FULL": "پر", "RESERVED": "رزرو",
            "QUARANTINE": "قرنطینه", "MAINTENANCE": "در حالِ تعمیر"}
DIRECTIONS = {"NS": "شمال–جنوب", "EW": "شرق–غرب"}
_OPERABLE = ("ACTIVE",)
_DEFAULT_SIZE = {"AREA": (400, 300), "AISLE": (60, 260), "RACK": (40, 200), "SHELF": (40, 200), "BIN": (40, 40)}


@dataclass
class LocationFields:
    name: str | None = None
    location_type_code: str | None = None
    description: str | None = None
    status_code: str = "ACTIVE"
    level_number: int | None = None
    direction: str | None = None
    width_m: decimal.Decimal | None = None
    length_m: decimal.Decimal | None = None
    height_m: decimal.Decimal | None = None
    max_weight_kg: decimal.Decimal | None = None
    max_volume_m3: decimal.Decimal | None = None
    temperature_min_c: decimal.Decimal | None = None
    temperature_max_c: decimal.Decimal | None = None
    is_pickable: bool = True
    allow_putaway: bool = True
    allow_replenishment: bool = True
    is_damaged: bool = False
    allows_hazardous: bool = False
    barcode: str | None = None
    map_x: decimal.Decimal | None = None
    map_y: decimal.Decimal | None = None
    map_z: decimal.Decimal | None = None
    map_width: decimal.Decimal | None = None
    map_height: decimal.Decimal | None = None
    map_rotation: decimal.Decimal | None = None


_FIELD_NAMES = tuple(f.name for f in dc_fields(LocationFields))


def _warehouse(session, company_id: int, warehouse_id: int) -> Warehouse:
    wh = session.get(Warehouse, warehouse_id)
    if wh is None or wh.company_id != company_id:
        raise ValueError("انبار نامعتبر است.")
    return wh


def _location(session, company_id: int, location_id: int) -> BinLocation:
    loc = session.get(BinLocation, location_id)
    if loc is None:
        raise ValueError("محل نامعتبر است.")
    _warehouse(session, company_id, loc.warehouse_id)
    return loc


def display_code(loc, warehouse_code: str) -> str:
    """کدِ کامل؛ محل‌هایِ قدیمی (بدونِ location_code) = کدِ انبار + کدِ محل."""
    return loc.location_code or f"{warehouse_code}-{loc.code}"


def _validate(fields: LocationFields) -> None:
    for name in ("width_m", "length_m", "height_m", "max_weight_kg", "max_volume_m3"):
        value = getattr(fields, name)
        if value is not None and value < 0:
            raise ValueError("ابعاد و ظرفیت نمی‌توانند منفی باشند.")
    if fields.status_code not in STATUSES:
        raise ValueError("وضعیتِ محل نامعتبر است.")
    if fields.location_type_code is not None and fields.location_type_code not in LOCATION_TYPES:
        raise ValueError("نوعِ محل نامعتبر است.")
    if (fields.temperature_min_c is not None and fields.temperature_max_c is not None
            and fields.temperature_min_c > fields.temperature_max_c):
        raise ValueError("دمایِ حداقل نمی‌تواند بیشتر از دمایِ حداکثر باشد.")


def _changes(row, fields: LocationFields) -> dict:
    out = {}
    for name in _FIELD_NAMES:
        old, new = getattr(row, name), getattr(fields, name)
        if (old if old is not None else None) != new and not (old is None and new in (None, "")):
            out[name] = [None if old is None else str(old), None if new is None else str(new)]
    return out


_U = 20  # مقیاسِ نقشه: هر متر = ۲۰ واحد
_GAP = 10


def _container(parent, wh) -> tuple[float, float, float, float] | None:
    """مستطیلِ والد (یا خودِ انبار) برایِ چیدنِ محلِ تازه درونِ آن."""
    if parent is not None and parent.map_x is not None and parent.map_width is not None:
        if parent.width_m and parent.length_m:
            return float(parent.map_x), float(parent.map_y or 0), float(parent.width_m) * _U, float(parent.length_m) * _U
        return float(parent.map_x), float(parent.map_y or 0), float(parent.map_width), float(parent.map_height or parent.map_width)
    if parent is None and wh.width_m and wh.length_m:
        return 0.0, 0.0, float(wh.width_m) * _U, float(wh.length_m) * _U
    return None


def _place_new(row, level: str, parent, wh, siblings: list[tuple[float, float, float, float]]) -> None:
    """R252: اندازه از ابعادِ واقعی (متر)؛ وگرنه اندازهٔ پیش‌فرض که داخلِ والد/انبار جا شود؛ چیدن کنارِ هم‌سطح‌ها
    با شکستنِ ردیف وقتی از عرضِ والد بیرون می‌زند. ابعادِ متری هم از اندازهٔ نقشه پر می‌شود تا همیشه هم‌خوان باشند."""
    box = _container(parent, wh)
    g = _GAP if box is None else min(_GAP, max(2.0, min(box[2], box[3]) * 0.04))
    off = g if parent is None or box is None else max(2 * g, min(box[3] * 0.15, 1.5 * _U))  # جایِ برچسبِ والد
    if row.width_m and row.length_m:
        width, height = float(row.width_m) * _U, float(row.length_m) * _U
    else:
        width, height = (float(v) for v in _DEFAULT_SIZE[level])
        if box is not None:
            _bx, _by, bw, bh = box
            if level == "AREA":
                width, height = min(width, max(_U / 2, bw / 2 - 1.5 * g)), min(height, max(_U / 2, bh - 2 * g))
            elif level == "AISLE":
                width, height = min(width, max(_U / 2, bw / 6)), max(_U / 2, bh - off - g)
            elif parent is not None and parent.bin_type_code == "AISLE":
                width, height = min(width, max(_U / 2, bw - 2 * g)), max(_U / 2, min(height, bh - off - g))
            else:
                width, height = min(width, max(_U / 2, bw / 6)), max(_U / 2, min(height, bh - off - g))
    if row.map_width is None:
        row.map_width, row.map_height = decimal.Decimal(str(round(width, 2))), decimal.Decimal(str(round(height, 2)))
    if not (row.width_m and row.length_m):
        row.width_m = decimal.Decimal(str(round(width / _U, 3)))
        row.length_m = decimal.Decimal(str(round(height / _U, 3)))
    if row.map_x is None:
        bx, by, bw, bh = box if box is not None else (0.0, 0.0, 1e9, 1e9)
        top = by + off
        x, y = bx + g, top
        if siblings:  # کنارِ آخرین هم‌سطح؛ اگر جا نشد، ردیفِ بعد
            row_top = max(sy for _sx, sy, _sw, _sh in siblings)
            same_row = [(sx, sy, sw, sh) for sx, sy, sw, sh in siblings if abs(sy - row_top) < 1]
            x = max(sx + sw for sx, _sy, sw, _sh in same_row) + g
            y = row_top
            if x + width > bx + bw and box is not None:
                x, y = bx + g, max(sy + sh for _sx, sy, _sw, sh in siblings) + g
        row.map_x = decimal.Decimal(str(round(x, 2)))
        row.map_y = decimal.Decimal(str(round(y, 2)))


def create_location(company_id: int, warehouse_id: int, level: str, segment: str, parent_id: int | None = None,
                    fields: LocationFields | None = None, user_id: int | None = None) -> int:
    """محلِ تازه در سلسله‌مراتب؛ کدِ کامل = کدِ والد (یا انبار) + «-» + کدِ بخش و در انبار یکتاست."""
    fields = fields or LocationFields()
    if level not in LEVELS:
        raise ValueError("سطحِ محل نامعتبر است.")
    segment = (segment or "").strip().upper()
    if not segment or "-" in segment or " " in segment:
        raise ValueError("کدِ بخش الزامی است و نباید «-» یا فاصله داشته باشد.")
    _validate(fields)
    with new_session() as session:
        wh = _warehouse(session, company_id, warehouse_id)
        parent = None
        if parent_id is not None:
            parent = session.get(BinLocation, parent_id)
            if parent is None or parent.warehouse_id != warehouse_id:
                raise ValueError("محلِ والد باید در همین انبار باشد.")
        parent_level = parent.bin_type_code if parent is not None else None
        if parent_level not in _ALLOWED_PARENTS[level]:
            allowed = "، ".join(LEVEL_LABELS[p] if p else "خودِ انبار" for p in _ALLOWED_PARENTS[level])
            raise ValueError(f"{LEVEL_LABELS[level]} فقط زیرِ {allowed} تعریف می‌شود.")
        prefix = display_code(parent, wh.code) if parent is not None else wh.code
        full = f"{prefix}-{segment}"
        short = full[len(wh.code) + 1:]
        if len(short) > 30:
            raise ValueError("کدِ محل (بدونِ کدِ انبار) حداکثر ۳۰ نویسه است؛ کدهایِ بخش را کوتاه‌تر کنید.")
        if session.scalar(select(BinLocation.bin_location_id).where(
                BinLocation.warehouse_id == warehouse_id,
                or_(BinLocation.location_code == full, BinLocation.code == short))):
            raise ValueError(f"محلِ «{full}» قبلاً تعریف شده است.")
        siblings = session.scalar(select(func.count()).select_from(BinLocation).where(
            BinLocation.warehouse_id == warehouse_id, BinLocation.bin_type_code == level,
            BinLocation.parent_bin_location_id.is_(None) if parent is None else BinLocation.parent_bin_location_id == parent.bin_location_id))
        row = BinLocation(warehouse_id=warehouse_id, parent_bin_location_id=parent_id, code=short, location_code=full,
                          bin_type_code=level)
        for name in _FIELD_NAMES:
            setattr(row, name, getattr(fields, name))
        row.is_active = fields.status_code != "INACTIVE"
        if level in ("AREA", "AISLE", "RACK"):
            placed = [(float(b.map_x), float(b.map_y or 0),
                       float(b.width_m) * _U if b.width_m and b.length_m else float(b.map_width or 0),
                       float(b.length_m) * _U if b.width_m and b.length_m else float(b.map_height or 0))
                      for b in session.scalars(select(BinLocation).where(  # عناصرِ نقشهٔ همین والد
                          BinLocation.warehouse_id == warehouse_id, BinLocation.bin_type_code.in_(("AREA", "AISLE", "RACK")),
                          BinLocation.map_x.is_not(None),
                          BinLocation.parent_bin_location_id.is_(None) if parent is None
                          else BinLocation.parent_bin_location_id == parent.bin_location_id))]
            _place_new(row, level, parent, wh, placed)
        if level == "SHELF" and row.level_number is None:
            row.level_number = (siblings or 0) + 1
        session.add(row)
        session.flush()
        audit_service.log_activity(session, company_id=company_id, user_id=user_id, entity_type="BinLocation",
                                   entity_id=row.bin_location_id, action="CREATE", changes={"location_code": full, "level": level})
        session.commit()
        return row.bin_location_id


def update_location(company_id: int, location_id: int, fields: LocationFields, user_id: int | None = None) -> None:
    _validate(fields)
    with new_session() as session:
        row = _location(session, company_id, location_id)
        changes = _changes(row, fields)
        for name in _FIELD_NAMES:
            setattr(row, name, getattr(fields, name))
        row.is_active = fields.status_code != "INACTIVE"
        if changes:
            audit_service.log_activity(session, company_id=company_id, user_id=user_id, entity_type="BinLocation",
                                       entity_id=location_id, action="UPDATE", changes=changes)
        session.commit()


def get_fields(company_id: int, location_id: int) -> LocationFields:
    with new_session() as session:
        row = _location(session, company_id, location_id)
        return LocationFields(**{name: getattr(row, name) for name in _FIELD_NAMES})


def set_status(company_id: int, location_id: int, status_code: str, user_id: int | None = None) -> None:
    f = get_fields(company_id, location_id)
    f.status_code = status_code
    update_location(company_id, location_id, f, user_id)


def save_geometry(company_id: int, location_id: int, x, y, width=None, height=None, rotation=None, user_id: int | None = None) -> None:
    """ذخیرهٔ جابه‌جایی/تغییرِ اندازه/چرخشِ عنصرِ نقشه."""
    q = lambda v: decimal.Decimal(str(round(float(v), 2))) if v is not None else None  # noqa: E731
    if (width is not None and float(width) <= 0) or (height is not None and float(height) <= 0):
        raise ValueError("اندازهٔ عنصرِ نقشه باید مثبت باشد.")
    f = get_fields(company_id, location_id)
    f.map_x, f.map_y = q(x), q(y)
    if width is not None:
        f.map_width = q(width)
        f.width_m = decimal.Decimal(str(round(float(width) / _U, 3)))  # R252: ابعادِ متری هم‌گام با نقشه
    if height is not None:
        f.map_height = q(height)
        f.length_m = decimal.Decimal(str(round(float(height) / _U, 3)))
    if rotation is not None:
        f.map_rotation = q(float(rotation) % 360)
    update_location(company_id, location_id, f, user_id)


def delete_location(company_id: int, location_id: int, user_id: int | None = None) -> str:
    """حذفِ محل همراهِ همهٔ زیرمحل‌ها اگر هیچ‌کدام سابقه (موجودی، حرکت، سند، وظیفه، شمارش) نداشته باشند؛
    وگرنه کلِ زیرشاخه غیرفعال می‌شود. خروجی: DELETED | DEACTIVATED."""
    from peecha.db.models.inventory import CycleCountLine, LocationReplenishmentRule, LotMovement, StockReservation

    with new_session() as session:
        row = _location(session, company_id, location_id)
        warehouse_id = row.warehouse_id
    nodes = tree(company_id, warehouse_id)
    subtree = descendants(nodes, location_id)
    ids = list(subtree)
    with new_session() as session:
        used = any(session.scalar(select(func.count()).select_from(model).where(cond)) for model, cond in (
            (StockLedger, StockLedger.bin_location_id.in_(ids)),
            (StockBalance, StockBalance.bin_location_id.in_(ids)),
            (StockDocumentLine, or_(StockDocumentLine.bin_location_id.in_(ids), StockDocumentLine.destination_bin_location_id.in_(ids))),
            (WarehouseTask, or_(WarehouseTask.from_bin_location_id.in_(ids), WarehouseTask.to_bin_location_id.in_(ids))),
            (CycleCountLine, CycleCountLine.bin_location_id.in_(ids)),
            (LotMovement, LotMovement.bin_location_id.in_(ids)),
            (StockReservation, StockReservation.bin_location_id.in_(ids)),
            (SerialNumber, SerialNumber.current_bin_location_id.in_(ids)),
        ))
        rows = list(session.scalars(select(BinLocation).where(BinLocation.bin_location_id.in_(ids))))
        if used:
            for r in rows:
                if r.status_code != "INACTIVE" or r.is_active:
                    audit_service.log_activity(session, company_id=company_id, user_id=user_id, entity_type="BinLocation",
                                               entity_id=r.bin_location_id, action="UPDATE",
                                               changes={"status_code": [r.status_code, "INACTIVE"]})
                r.status_code, r.is_active = "INACTIVE", False
            session.commit()
            return "DEACTIVATED"
        for rule in session.scalars(select(LocationReplenishmentRule).where(LocationReplenishmentRule.bin_location_id.in_(ids))):
            session.delete(rule)
        for w in session.scalars(select(Warehouse).where(Warehouse.default_bin_location_id.in_(ids))):
            w.default_bin_location_id = None  # R253: پیش‌فرضِ حذف‌شده به رفتارِ قبلی برمی‌گردد
        depth = {n.location_id: len(ancestors({m.location_id: m for m in nodes}, n.location_id)) for n in nodes if n.location_id in subtree}
        for r in sorted(rows, key=lambda r: -depth.get(r.bin_location_id, 0)):  # فرزندان اول
            audit_service.log_activity(session, company_id=company_id, user_id=user_id, entity_type="BinLocation",
                                       entity_id=r.bin_location_id, action="DELETE", changes={"location_code": r.location_code or r.code})
            session.delete(r)
            session.flush()
        session.commit()
        return "DELETED"


def save_warehouse_dimensions(company_id: int, warehouse_id: int, width_m=None, length_m=None, height_m=None,
                              max_weight_kg=None, description: str | None = None) -> None:
    for v in (width_m, length_m, height_m, max_weight_kg):
        if v is not None and decimal.Decimal(v) < 0:
            raise ValueError("ابعاد/ظرفیتِ انبار نمی‌تواند منفی باشد.")
    with new_session() as session:
        wh = _warehouse(session, company_id, warehouse_id)
        wh.width_m, wh.length_m, wh.height_m = width_m, length_m, height_m
        if max_weight_kg is not None:
            wh.capacity_weight_kg = max_weight_kg
        if width_m and length_m and height_m and wh.capacity_volume_m3 is None:
            wh.capacity_volume_m3 = decimal.Decimal(width_m) * decimal.Decimal(length_m) * decimal.Decimal(height_m)
        wh.description = description or None
        session.commit()


# =====================================================================
# درخت، هندسه و اشغال
# =====================================================================
def tree(company_id: int, warehouse_id: int, active_only: bool = False) -> list[SimpleNamespace]:
    """همهٔ محل‌هایِ انبار با کدِ کامل، سطح و والد (یک کوئری)."""
    with new_session() as session:
        wh = _warehouse(session, company_id, warehouse_id)
        rows = list(session.scalars(select(BinLocation).where(BinLocation.warehouse_id == warehouse_id)
                                    .order_by(BinLocation.code)))
    out = []
    for r in rows:
        if active_only and not r.is_active:
            continue
        node = SimpleNamespace(**{name: getattr(r, name) for name in _FIELD_NAMES})
        node.location_id, node.parent_id, node.code, node.level = r.bin_location_id, r.parent_bin_location_id, r.code, r.bin_type_code
        node.full_code, node.warehouse_id, node.is_active = display_code(r, wh.code), warehouse_id, r.is_active
        out.append(node)
    return out


def descendants(nodes: list, location_id: int) -> set[int]:
    children = defaultdict(list)
    for n in nodes:
        children[n.parent_id].append(n.location_id)
    out, stack = set(), [location_id]
    while stack:
        current = stack.pop()
        if current in out:
            continue
        out.add(current)
        stack.extend(children.get(current, []))
    return out


def ancestors(nodes_by_id: dict, location_id: int) -> list:
    chain, current = [], nodes_by_id.get(location_id)
    while current is not None:
        chain.append(current)
        current = nodes_by_id.get(current.parent_id)
    return list(reversed(chain))


def geometry(company_id: int, warehouse_id: int, nodes: list | None = None) -> dict[int, tuple[float, float, float, float, float]]:
    """(x, y, w, h, rotation) هر محل رویِ نقشه. Zone/Aisle/Rack مختصاتِ ذخیره‌شده دارند؛ طبقه هم‌اندازهٔ قفسه
    است و Binهایِ بی‌مختصات به‌صورتِ سلول‌هایِ مساویِ طولِ قفسه/طبقه چیده می‌شوند."""
    nodes = nodes if nodes is not None else tree(company_id, warehouse_id)
    by_id = {n.location_id: n for n in nodes}
    children = defaultdict(list)
    for n in nodes:
        children[n.parent_id].append(n)
    out: dict[int, tuple] = {}

    def own(n):
        if n.map_x is not None and n.map_width is not None:
            w, h = float(n.map_width), float(n.map_height or n.map_width)
            if n.level in ("AREA", "AISLE", "RACK") and n.width_m and n.length_m:  # R252: ابعادِ واقعی (متر) مقدم است
                w, h = float(n.width_m) * _U, float(n.length_m) * _U
            return float(n.map_x), float(n.map_y or 0), w, h, float(n.map_rotation or 0)
        return None

    def place(n, parent_rect):
        rect = own(n)
        if rect is None and parent_rect is not None:
            rect = parent_rect
        if rect is not None:
            out[n.location_id] = rect
        kids = sorted(children.get(n.location_id, []), key=lambda k: k.code)
        if n.level in ("RACK", "SHELF") and rect is not None:
            bins = [k for k in kids if k.level == "BIN" and own(k) is None]
            x, y, w, h, rot = rect
            vertical = h >= w
            for i, b in enumerate(bins):
                cell = (h / len(bins)) if vertical else (w / len(bins))
                out[b.location_id] = (x, y + i * cell, w, cell, rot) if vertical else (x + i * cell, y, cell, h, rot)
            for k in kids:
                if k.level != "BIN" or own(k) is not None:
                    place(k, rect if k.level == "SHELF" else None)
            return
        for k in kids:
            place(k, None)

    for n in nodes:
        if n.parent_id is None or n.parent_id not in by_id:
            place(n, None)
    return out


def _stock_by_bin(company_id: int, warehouse_id: int | None = None) -> list[tuple]:
    with new_session() as session:
        q = (select(StockBalance.bin_location_id, StockBalance.item_id, func.sum(StockBalance.quantity_on_hand),
                    func.sum(StockBalance.quantity_reserved), func.sum(StockBalance.total_value))
             .where(StockBalance.company_id == company_id))
        if warehouse_id is not None:
            q = q.where(StockBalance.warehouse_id == warehouse_id)
        return session.execute(q.group_by(StockBalance.bin_location_id, StockBalance.item_id)).all()


def _item_dims(company_id: int) -> dict[int, tuple]:
    with new_session() as session:
        return {i: (w, v) for i, w, v in session.execute(
            select(Item.item_id, Item.weight_kg, Item.volume_m3).where(Item.company_id == company_id)).all()}


def capacity_of(node) -> tuple[decimal.Decimal | None, decimal.Decimal | None]:
    volume = node.max_volume_m3
    if volume is None and node.width_m and node.length_m and node.height_m:
        volume = (node.width_m * node.length_m * node.height_m).quantize(decimal.Decimal("0.001"))
    return node.max_weight_kg, volume


def occupancy(company_id: int, warehouse_id: int, nodes: list | None = None) -> dict[int, SimpleNamespace]:
    """اشغالِ هر محل (با زیرمحل‌ها): مقدار، وزن، حجم، ارزش و درصد = بیشترینِ (وزن/ظرفیتِ وزنی، حجم/ظرفیتِ حجمی)."""
    nodes = nodes if nodes is not None else tree(company_id, warehouse_id)
    dims = _item_dims(company_id)
    own: dict[int, list] = defaultdict(lambda: [_ZERO, _ZERO, _ZERO, _ZERO, set()])
    for bin_id, item_id, qty, _reserved, value in _stock_by_bin(company_id, warehouse_id):
        if not qty:
            continue
        w, v = dims.get(item_id, (None, None))
        o = own[bin_id]
        o[0] += qty
        o[1] += qty * (w or _ZERO)
        o[2] += qty * (v or _ZERO)
        o[3] += value or _ZERO
        o[4].add(item_id)
    children = defaultdict(list)
    for n in nodes:
        children[n.parent_id].append(n)
    result: dict[int, SimpleNamespace] = {}

    def total(n):
        qty, weight, volume, value, items = own[n.location_id][:4] + [set(own[n.location_id][4])]
        cap_w, cap_v = capacity_of(n)
        child_cap_w, child_cap_v = _ZERO, _ZERO
        child_caps_known_w = child_caps_known_v = bool(children.get(n.location_id))
        for k in children.get(n.location_id, []):
            r = total(k)
            qty, weight, volume, value = qty + r.quantity, weight + r.weight, volume + r.volume, value + r.value
            items |= r.items
            child_cap_w += r.max_weight or _ZERO
            child_cap_v += r.max_volume or _ZERO
            child_caps_known_w &= r.max_weight is not None
            child_caps_known_v &= r.max_volume is not None
        cap_w = cap_w if cap_w is not None else (child_cap_w if child_caps_known_w else None)
        cap_v = cap_v if cap_v is not None else (child_cap_v if child_caps_known_v else None)
        pct = [x * 100 / c for x, c in ((weight, cap_w), (volume, cap_v)) if c]
        r = SimpleNamespace(quantity=qty, weight=weight.quantize(decimal.Decimal("0.001")), volume=volume.quantize(decimal.Decimal("0.001")),
                            value=value, items=items, max_weight=cap_w, max_volume=cap_v,
                            percent=max(pct).quantize(decimal.Decimal("0.1")) if pct else None)
        result[n.location_id] = r
        return r

    for n in nodes:
        if n.location_id not in result:
            total(n)
    return result


def is_operable(node) -> bool:
    return node.is_active and node.status_code in _OPERABLE and not node.is_damaged


# =====================================================================
# محتوا، محلِ کالا، جستجو و QR
# =====================================================================
def contents(company_id: int, location_id: int) -> list[SimpleNamespace]:
    """کالاهایِ این محل و زیرمحل‌هایش از موجودیِ سیستم + سریال‌هایِ همین محل و بچ/انقضایِ کالا در همان انبار."""
    from peecha.services import inventory_catalog as catalog_service

    with new_session() as session:
        loc = _location(session, company_id, location_id)
        warehouse_id = loc.warehouse_id
    nodes = tree(company_id, warehouse_id)
    bins = descendants(nodes, location_id)
    by_id = {n.location_id: n for n in nodes}
    items = {i.item_id: i for i in catalog_service.list_items(company_id)}
    rows = [r for r in _stock_by_bin(company_id, warehouse_id) if r[0] in bins and r[2]]
    lots = bin_batches(company_id, warehouse_id) if rows else {}
    with new_session() as session:
        serials = defaultdict(list)
        for s in session.scalars(select(SerialNumber).where(SerialNumber.current_bin_location_id.in_(bins or {-1}),
                                                            SerialNumber.status_code == "IN_STOCK")):
            serials[(s.current_bin_location_id, s.item_id)].append(s.serial_no)
    out = []
    for bin_id, item_id, qty, reserved, value in sorted(rows, key=lambda r: (by_id[r[0]].full_code if r[0] in by_id else "", r[1])):
        # R252: رزروِ وظایف از این نسخه در همان ستونِ رزروِ مانده است
        item = items.get(item_id)
        item_lots = lots.get((bin_id, item_id), [])
        out.append(SimpleNamespace(
            location_id=bin_id, location_code=by_id[bin_id].full_code if bin_id in by_id else "", item_id=item_id,
            item_code=item.code if item else "", item_name=item.name if item else "", sku=(item.sku or "") if item else "",
            unit=item.base_uom_code if item else "", quantity=qty, reserved=reserved or _ZERO, value=value or _ZERO,
            batches="، ".join(lt.batch_no for lt in item_lots[:5]), batch_rows=item_lots,
            expiry=next((lt.expiry_date for lt in item_lots if lt.expiry_date), None),
            serials="، ".join(serials.get((bin_id, item_id), [])[:10])))
    return out


def product_locations(company_id: int, item_id: int) -> list[SimpleNamespace]:
    """همهٔ محل‌هایِ یک کالا (چند انبار/چند محل) با مقدار -- از موجودیِ سیستم."""
    from peecha.services import inventory_locations as locations_service

    rows = [r for r in _stock_by_bin(company_id) if r[1] == item_id and r[2]]
    with new_session() as session:
        bin_wh = dict(session.execute(select(BinLocation.bin_location_id, BinLocation.warehouse_id)
                                      .where(BinLocation.bin_location_id.in_([r[0] for r in rows] or [-1]))).all())
    warehouses = {w.warehouse_id: w for w in locations_service.list_warehouses(company_id)}
    cache: dict[int, dict] = {}
    out = []
    for bin_id, _item, qty, reserved, value in rows:
        wid = bin_wh.get(bin_id)
        if wid not in cache:
            cache[wid] = {n.location_id: n for n in tree(company_id, wid)}
        chain = ancestors(cache[wid], bin_id)
        part = {n.level: n.code.split("-")[-1] for n in chain if n.level}
        out.append(SimpleNamespace(
            warehouse_id=wid, warehouse=warehouses[wid].name if wid in warehouses else "", location_id=bin_id,
            location_code=chain[-1].full_code if chain else "", zone=part.get("AREA", ""), aisle=part.get("AISLE", ""),
            rack=part.get("RACK", ""), level=part.get("SHELF", ""), bin=part.get("BIN", chain[-1].code if chain else ""),
            quantity=qty, reserved=reserved or _ZERO, value=value or _ZERO))
    return sorted(out, key=lambda r: (r.warehouse, r.location_code))


def qr_payload(location_id: int, location_code: str) -> str:
    return f"{QR_PREFIX}:{location_id}:{location_code}"


def decode_qr(company_id: int, payload: str) -> int:
    """متنِ QR → شناسهٔ محل (کدِ ثبت‌شده باید با کدِ فعلیِ محل بخواند)."""
    parts = (payload or "").strip().split(":", 2)
    if len(parts) != 3 or parts[0] != QR_PREFIX or not parts[1].isdigit():
        raise ValueError("QR محلِ انبار نیست.")
    location_id = int(parts[1])
    with new_session() as session:
        loc = _location(session, company_id, location_id)
        wh = session.get(Warehouse, loc.warehouse_id)
        if display_code(loc, wh.code) != parts[2]:
            raise ValueError("QR با کدِ فعلیِ محل نمی‌خواند (کدِ محل تغییر کرده است).")
    return location_id


def qr_matrix(payload: str) -> list[list[int]]:
    import segno

    return [list(row) for row in segno.make(payload, error="m", micro=False).matrix_iter(scale=1, border=0)]


def barcode_bits(code: str) -> str:
    """الگویِ میله‌هایِ Code128 (برایِ چاپِ برچسب با QPainter)."""
    import barcode

    return barcode.get_barcode_class("code128")(code).build()[0]


def search(company_id: int, text: str, warehouse_id: int | None = None) -> SimpleNamespace:
    """QR/کدِ محل/بارکدِ محل → همان محل؛ وگرنه کد/نام/بارکد/SKUِ کالا → همهٔ محل‌هایِ آن کالا."""
    from peecha import numerals
    from peecha.services import inventory_catalog as catalog_service

    text = numerals.to_ascii_digits((text or "").strip())
    if not text:
        return SimpleNamespace(kind="NONE", location_ids=[], item_ids=[])
    if text.startswith(QR_PREFIX + ":"):
        return SimpleNamespace(kind="LOCATION", location_ids=[decode_qr(company_id, text)], item_ids=[])
    upper = text.upper()
    with new_session() as session:
        q = (select(BinLocation.bin_location_id, BinLocation.location_code, BinLocation.code, BinLocation.barcode, Warehouse.code)
             .join(Warehouse, Warehouse.warehouse_id == BinLocation.warehouse_id).where(Warehouse.company_id == company_id))
        if warehouse_id is not None:
            q = q.where(BinLocation.warehouse_id == warehouse_id)
        matches = [lid for lid, full, code, bc, wcode in session.execute(q).all()
                   if upper in ((full or "").upper(), f"{wcode}-{code}".upper(), (bc or "").upper())]
    if matches:
        return SimpleNamespace(kind="LOCATION", location_ids=matches, item_ids=[])
    lowered = text.lower()
    item_ids = [i.item_id for i in catalog_service.list_items(company_id)
                if lowered in (i.code or "").lower() or lowered in (i.name or "").lower()
                or lowered == (i.barcode or "").lower() or lowered == (i.sku or "").lower()]
    if not item_ids:
        from peecha.services import unit_conversion as uc

        hit = uc.resolve_barcode(company_id, text, with_price=False)  # بارکدِ واحدهایِ کالا (همان سرویسِ فروش)
        item_ids = [hit.item_id] if hit else []
    locations = []
    for item_id in item_ids:
        locations += [r.location_id for r in product_locations(company_id, item_id)
                      if warehouse_id is None or r.warehouse_id == warehouse_id]
    return SimpleNamespace(kind="PRODUCT" if item_ids else "NONE", location_ids=sorted(set(locations)), item_ids=item_ids)


# =====================================================================
# پیشنهادِ جانمایی، مسیرِ برداشت، Heatmap و تاریخچه
# =====================================================================
def _leaf_nodes(nodes: list) -> list:
    parents = {n.parent_id for n in nodes}
    return [n for n in nodes if n.location_id not in parents and n.level in ("BIN", "SHELF", "RACK", None)]


def putaway_suggestions(company_id: int, warehouse_id: int, item_id: int, quantity: decimal.Decimal, limit: int = 5) -> list:
    """بهترین محل‌ها برایِ جانمایی: فقط محلِ فعال/مجاز با ظرفیتِ کافی؛ امتیاز با تجمیعِ همان کالا، تطبیقِ نوعِ محل
    با کلاسِ ABC (A → جبههٔ برداشت، C → حجیم/ذخیره)، و ظرفیتِ باقی‌مانده."""
    from peecha.services import purchase_reports as base
    from peecha.services import warehouse_reports as wr

    quantity = decimal.Decimal(quantity)
    nodes = tree(company_id, warehouse_id)
    by_id = {n.location_id: n for n in nodes}
    occ = occupancy(company_id, warehouse_id, nodes)
    weight, volume = _item_dims(company_id).get(item_id, (None, None))
    need_w, need_v = quantity * (weight or _ZERO), quantity * (volume or _ZERO)
    today = datetime.date.today()
    f = base.PurchaseFilters(today - datetime.timedelta(days=365), today, warehouse_id=warehouse_id, side="INVENTORY")
    cls = next((row[-1] for row in wr.abc_classes(company_id, f) if row[0] == item_id), "C")
    profile = get_storage_profile(company_id, item_id)
    out = []
    for n in _leaf_nodes(nodes):
        if not is_operable(n) or not n.allow_putaway:
            continue
        if compatibility_issues(company_id, item_id, n.location_id, by_id, profile):
            continue
        o = occ.get(n.location_id)
        reasons, score = [], 0
        if o and o.max_weight is not None and o.weight + need_w > o.max_weight:
            continue
        if o and o.max_volume is not None and o.volume + need_v > o.max_volume:
            continue
        if o and (o.max_weight is not None or o.max_volume is not None):
            score += 20
            reasons.append("ظرفیتِ کافی (وزن/حجم)")
        else:
            score += 5
            reasons.append("ظرفیت تعریف نشده")
        if o and item_id in o.items:
            score += 40
            reasons.append("همین کالا در این محل است (تجمیع)")
        elif o and o.items:
            score -= 10
            reasons.append("محل کالایِ دیگر دارد")
        types = {a.location_type_code for a in ancestors(by_id, n.location_id) if a.location_type_code}
        if cls == "A" and types & {"PICK_FACE", "PICKING"}:
            score += 25
            reasons.append("نزدیکِ جبههٔ برداشت -- مناسبِ کالایِ A")
        if cls in ("B", "C") and types & {"BULK", "RESERVE"}:
            score += 15
            reasons.append(f"منطقهٔ ذخیره/حجیم -- مناسبِ کالایِ {cls}")
        if types & {"QUARANTINE", "DAMAGED", "RETURNS", "RECEIVING", "SHIPPING", "STAGING"}:
            score -= 30
            reasons.append("منطقهٔ عملیاتی/قرنطینه")
        if o and o.percent is not None:
            score += int((100 - min(o.percent, 100)) / 10)
        if profile.is_fragile and n.level_number is not None and n.level_number <= 1:
            score += 10
            reasons.append("طبقهٔ پایین -- مناسبِ کالایِ شکستنی")
        if profile.temperature_max_c is not None or profile.hazard_class_code:
            reasons.append("با شرایطِ نگهداریِ کالا سازگار است")
        out.append(SimpleNamespace(location_id=n.location_id, location_code=n.full_code, score=score, abc_class=cls,
                                   reasons=reasons, occupancy=o.percent if o else None))
    out.sort(key=lambda s: (-s.score, s.location_code))
    return out[:limit]


def picking_path(company_id: int, warehouse_id: int, location_ids: list[int]) -> SimpleNamespace:
    """مسیرِ پیشنهادی (نزدیک‌ترین همسایه) از منطقهٔ دریافت/ابتدایِ انبار تا منطقهٔ ارسال، رویِ مراکزِ نقشه."""
    nodes = tree(company_id, warehouse_id)
    geo = geometry(company_id, warehouse_id, nodes)
    center = lambda lid: (geo[lid][0] + geo[lid][2] / 2, geo[lid][1] + geo[lid][3] / 2)  # noqa: E731
    zone_of_type = lambda types: next((n.location_id for n in nodes if n.location_type_code in types and n.location_id in geo), None)  # noqa: E731
    start_zone, end_zone = zone_of_type({"PICKING", "STAGING", "RECEIVING"}), zone_of_type({"SHIPPING"})
    current = center(start_zone) if start_zone else (0.0, 0.0)
    pending = [lid for lid in dict.fromkeys(location_ids) if lid in geo]
    order, distance = [], 0.0
    while pending:
        nxt = min(pending, key=lambda lid: math.dist(current, center(lid)))
        distance += math.dist(current, center(nxt))
        current = center(nxt)
        order.append(nxt)
        pending.remove(nxt)
    if end_zone:
        distance += math.dist(current, center(end_zone))
    by_id = {n.location_id: n for n in nodes}
    return SimpleNamespace(order=order, codes=[by_id[i].full_code for i in order], distance=round(distance, 1),
                           start=start_zone, end=end_zone)


HEATMAP_MODES = {"NORMAL": "عادی", "OCCUPANCY": "اشغال", "PICK_FREQ": "تواترِ برداشت", "VALUE": "ارزشِ موجودی", "ABC": "ABC",
                 "EXPIRY": "ریسکِ انقضا", "CONGESTION": "ازدحام", "TEMPERATURE": "دما"}


def heatmap(company_id: int, warehouse_id: int, mode: str, nodes: list | None = None) -> dict[int, object]:
    """مقدارِ هر محل (برگ‌ها و والدها) برایِ حالتِ نقشه."""
    nodes = nodes if nodes is not None else tree(company_id, warehouse_id)
    if mode == "OCCUPANCY":
        return {k: v.percent for k, v in occupancy(company_id, warehouse_id, nodes).items()}
    if mode == "VALUE":
        return {k: v.value for k, v in occupancy(company_id, warehouse_id, nodes).items()}
    if mode == "TEMPERATURE":
        by_id = {n.location_id: n for n in nodes}
        out = {}
        for n in nodes:
            t = next((a.temperature_min_c for a in reversed(ancestors(by_id, n.location_id)) if a.temperature_min_c is not None), None)
            out[n.location_id] = t
        return out
    since = datetime.date.today() - datetime.timedelta(days=90 if mode == "PICK_FREQ" else 7)
    if mode in ("PICK_FREQ", "CONGESTION"):
        with new_session() as session:
            q = (select(StockLedger.bin_location_id, func.count())
                 .join(StockDocumentLine, StockDocumentLine.line_id == StockLedger.stock_document_line_id)
                 .join(StockDocument, StockDocument.stock_document_id == StockDocumentLine.stock_document_id)
                 .where(StockLedger.warehouse_id == warehouse_id, StockLedger.movement_date >= since))
            if mode == "PICK_FREQ":
                q = q.where(StockLedger.movement_direction == "OUT", StockDocument.document_type_code == "ISSUE")
            counts = dict(session.execute(q.group_by(StockLedger.bin_location_id)).all())
            if mode == "PICK_FREQ":
                for (bin_id, n) in session.execute(select(WarehouseTask.from_bin_location_id, func.count()).where(
                        WarehouseTask.warehouse_id == warehouse_id, WarehouseTask.task_type_code == "PICK",
                        WarehouseTask.status_code == "DONE").group_by(WarehouseTask.from_bin_location_id)).all():
                    counts[bin_id] = counts.get(bin_id, 0) + n
            else:
                for (bin_id, n) in session.execute(select(WarehouseTask.from_bin_location_id, func.count()).where(
                        WarehouseTask.warehouse_id == warehouse_id,
                        WarehouseTask.status_code.in_(("OPEN", "IN_PROGRESS"))).group_by(WarehouseTask.from_bin_location_id)).all():
                    counts[bin_id] = counts.get(bin_id, 0) + n
        return _roll_up(nodes, counts)
    if mode == "ABC":
        from peecha.services import purchase_reports as base
        from peecha.services import warehouse_reports as wr

        today = datetime.date.today()
        f = base.PurchaseFilters(today - datetime.timedelta(days=365), today, warehouse_id=warehouse_id, side="INVENTORY")
        classes = {row[0]: row[-1] for row in wr.abc_classes(company_id, f)}
        best: dict[int, str] = {}
        for bin_id, item_id, qty, _r, _v in _stock_by_bin(company_id, warehouse_id):
            if qty and item_id in classes:
                best[bin_id] = min(best.get(bin_id, "C"), classes[item_id])
        return best
    if mode == "EXPIRY":
        days: dict[int, int] = {}
        for (bin_id, _item), lots in bin_batches(company_id, warehouse_id).items():
            for lt in lots:
                if lt.expiry_date:
                    left = (lt.expiry_date - datetime.date.today()).days
                    days[bin_id] = min(days.get(bin_id, left), left)
        return days
    return {}


def _roll_up(nodes: list, values: dict[int, int]) -> dict[int, int]:
    out = dict(values)
    by_id = {n.location_id: n for n in nodes}
    for lid, v in values.items():
        current = by_id.get(lid)
        while current is not None and current.parent_id is not None:
            out[current.parent_id] = out.get(current.parent_id, 0) + v
            current = by_id.get(current.parent_id)
    return out


def history(company_id: int, location_id: int, limit: int = 200) -> list[SimpleNamespace]:
    """ورود/خروج/انتقال از دفترِ انبار + تغییرِ مشخصات/وضعیت/ظرفیت از audit.activity_log."""
    from peecha.db.models.audit import ActivityLog
    from peecha.services import inventory_catalog as catalog_service

    with new_session() as session:
        loc = _location(session, company_id, location_id)
        warehouse_id = loc.warehouse_id
    bins = descendants(tree(company_id, warehouse_id), location_id)
    items = {i.item_id: f"{i.code} — {i.name or ''}" for i in catalog_service.list_items(company_id)}
    with new_session() as session:
        moves = session.execute(
            select(StockLedger.movement_date, StockLedger.created_at, StockLedger.movement_direction, StockLedger.quantity_base,
                   StockLedger.item_id, StockDocument.document_type_code, StockDocument.document_no, StockDocument.stock_document_id)
            .join(StockDocumentLine, StockDocumentLine.line_id == StockLedger.stock_document_line_id)
            .join(StockDocument, StockDocument.stock_document_id == StockDocumentLine.stock_document_id)
            .where(StockLedger.bin_location_id.in_(bins)).order_by(StockLedger.ledger_id.desc()).limit(limit)).all()
        audits = list(session.scalars(select(ActivityLog).where(ActivityLog.entity_type == "BinLocation",
                                                                 ActivityLog.entity_id.in_(bins))
                                      .order_by(ActivityLog.log_id.desc()).limit(limit)))
    out = [SimpleNamespace(at=created or datetime.datetime.combine(d, datetime.time()), kind="ورود" if direction == "IN" else "خروج",
                           detail=f"{doc_type} {doc_no}", item=items.get(item_id, ""), quantity=qty, stock_document_id=doc_id,
                           doc_type=doc_type)
           for d, created, direction, qty, item_id, doc_type, doc_no, doc_id in moves]
    labels = {"CREATE": "ایجاد", "UPDATE": "تغییرِ مشخصات", "DELETE": "حذف"}
    for a in audits:
        detail = "، ".join(f"{k}: {v[0]} ← {v[1]}" if isinstance(v, list) else f"{k}: {v}" for k, v in (a.changes or {}).items())
        out.append(SimpleNamespace(at=a.created_at, kind=labels.get(a.action, a.action), detail=detail, item="", quantity=None,
                                   stock_document_id=None, doc_type=None))
    return sorted(out, key=lambda h: h.at, reverse=True)[:limit]


# =====================================================================
# انتقال بینِ محل‌ها (با سندِ انتقالِ عادیِ سیستم)
# =====================================================================
def transfer(company_id: int, user_id: int, item_id: int, from_location_id: int, to_location_id: int,
             quantity: decimal.Decimal, allow_over_capacity: bool = False) -> int:
    """اعتبارسنجیِ محلِ مقصد (فعال، مجاز برایِ جانمایی، ظرفیت) و ثبتِ سندِ انتقالِ عادی؛ خروجی = شناسهٔ سند."""
    from peecha.services import inventory_documents as inv_documents_service

    quantity = decimal.Decimal(quantity)
    if quantity <= 0:
        raise ValueError("مقدارِ انتقال باید مثبت باشد.")
    with new_session() as session:
        src = _location(session, company_id, from_location_id)
        dst = _location(session, company_id, to_location_id)
        base_uom = session.scalar(select(Item.base_uom_id).where(Item.item_id == item_id, Item.company_id == company_id))
        if base_uom is None:
            raise ValueError("کالا نامعتبر است.")
        available = session.scalar(select(func.coalesce(func.sum(StockBalance.quantity_on_hand), 0)).where(
            StockBalance.bin_location_id == from_location_id, StockBalance.item_id == item_id)) or _ZERO
        src_wh, dst_wh = src.warehouse_id, dst.warehouse_id
    dst_node = next(n for n in tree(company_id, dst_wh) if n.location_id == to_location_id)
    if not is_operable(dst_node) or not dst_node.allow_putaway:
        raise ValueError(f"محلِ مقصد «{dst_node.full_code}» برایِ ورودِ کالا فعال/مجاز نیست ({STATUSES.get(dst_node.status_code)}).")
    from peecha.services import warehouse_operations as ops

    held = ops.reserved_by_bin(company_id, src_wh).get((from_location_id, item_id), _ZERO)
    if quantity > available - held:
        raise ValueError("مقدارِ انتقال بیش از موجودیِ آزادِ محلِ مبدا است"
                         + (f" ({held} عدد برایِ وظایفِ انبار رزرو شده است)." if held else "."))
    issues = compatibility_issues(company_id, item_id, to_location_id)
    if issues:
        raise ValueError(f"کالا با محلِ «{dst_node.full_code}» سازگار نیست: " + "؛ ".join(issues))
    if not allow_over_capacity:
        o = occupancy(company_id, dst_wh).get(to_location_id)
        weight, volume = _item_dims(company_id).get(item_id, (None, None))
        if o and ((o.max_weight is not None and o.weight + quantity * (weight or _ZERO) > o.max_weight)
                  or (o.max_volume is not None and o.volume + quantity * (volume or _ZERO) > o.max_volume)):
            raise ValueError("ظرفیتِ محلِ مقصد کافی نیست (برایِ ادامه، عبور از ظرفیت را تایید کنید).")
    doc_id = inv_documents_service.create_stock_document(
        company_id, user_id, "TRANSFER", datetime.date.today(),
        inv_documents_service.DocumentHeaderFields(source_warehouse_id=src_wh, destination_warehouse_id=dst_wh,
                                                   description="انتقالِ محل از نقشهٔ انبار"))
    inv_documents_service.add_line(doc_id, company_id, inv_documents_service.LineFields(
        item_id=item_id, uom_id=base_uom, quantity=quantity, quantity_base=quantity, conversion_factor=decimal.Decimal(1),
        bin_location_id=from_location_id, destination_bin_location_id=to_location_id))
    inv_documents_service.confirm_stock_document(doc_id, company_id)
    inv_documents_service.post_stock_document(doc_id, company_id, user_id)
    return doc_id


def can(user_id: int | None, company_id: int, action: str) -> bool:
    """دسترسی از همان سیستمِ نقش‌ها (sec.role_form_permissions) با فرمِ «warehouse_map»."""
    from peecha.services import roles as roles_service

    return user_id is not None and roles_service.user_has_permission(user_id, company_id, FORM_CODE, action)



# =====================================================================
# R249: سازگاریِ کالا با محل و بررسیِ محل‌هایِ سندِ انبار
# =====================================================================
HAZARD_CLASSES = {
    "EXPLOSIVE": "منفجره (۱)", "GAS": "گاز (۲)", "FLAMMABLE_LIQUID": "مایعِ آتش‌گیر (۳)", "FLAMMABLE_SOLID": "جامدِ آتش‌گیر (۴)",
    "OXIDIZER": "اکسیدکننده (۵)", "TOXIC": "سمی (۶)", "RADIOACTIVE": "پرتوزا (۷)", "CORROSIVE": "خورنده (۸)", "MISC": "سایر (۹)",
}
AMBIENT_RANGE = (decimal.Decimal(15), decimal.Decimal(25))  # محلِ بی‌دمایِ تعریف‌شده = دمایِ محیط
NO_ENTRY_STATUSES = ("INACTIVE", "BLOCKED", "MAINTENANCE", "FULL")
NO_EXIT_STATUSES = ("BLOCKED", "MAINTENANCE")


@dataclass
class StorageProfile:
    temperature_min_c: decimal.Decimal | None = None
    temperature_max_c: decimal.Decimal | None = None
    hazard_class_code: str | None = None
    is_fragile: bool = False
    required_location_type_code: str | None = None
    notes: str | None = None

    def is_empty(self) -> bool:
        return (self.temperature_min_c is None and self.temperature_max_c is None and not self.hazard_class_code
                and not self.is_fragile and not self.required_location_type_code and not self.notes)


_PROFILE_FIELDS = tuple(f.name for f in dc_fields(StorageProfile))


def get_storage_profile(company_id: int, item_id: int) -> StorageProfile:
    with new_session() as session:
        row = session.get(ItemStorageProfile, item_id)
        if row is None or row.company_id != company_id:
            return StorageProfile()
        return StorageProfile(**{name: getattr(row, name) for name in _PROFILE_FIELDS})


def save_storage_profile(company_id: int, item_id: int, profile: StorageProfile, user_id: int | None = None) -> None:
    """ذخیرهٔ شرایطِ نگهداریِ کالا؛ پروفایلِ خالی حذف می‌شود."""
    if (profile.temperature_min_c is not None and profile.temperature_max_c is not None
            and profile.temperature_min_c > profile.temperature_max_c):
        raise ValueError("دمایِ حداقلِ نگهداری نمی‌تواند بیشتر از دمایِ حداکثر باشد.")
    if profile.hazard_class_code and profile.hazard_class_code not in HAZARD_CLASSES:
        raise ValueError("کلاسِ خطر نامعتبر است.")
    if profile.required_location_type_code and profile.required_location_type_code not in LOCATION_TYPES:
        raise ValueError("نوعِ محلِ الزامی نامعتبر است.")
    with new_session() as session:
        item = session.get(Item, item_id)
        if item is None or item.company_id != company_id:
            raise ValueError("کالا نامعتبر است.")
        row = session.get(ItemStorageProfile, item_id)
        old = {name: getattr(row, name) for name in _PROFILE_FIELDS} if row is not None else {}
        if profile.is_empty():
            if row is not None:
                session.delete(row)
        else:
            if row is None:
                row = ItemStorageProfile(item_id=item_id, company_id=company_id)
                session.add(row)
            for name in _PROFILE_FIELDS:
                setattr(row, name, getattr(profile, name))
            row.updated_at = datetime.datetime.now()
        changes = {name: [None if old.get(name) is None else str(old.get(name)),
                          None if getattr(profile, name) is None else str(getattr(profile, name))]
                   for name in _PROFILE_FIELDS if old.get(name) != getattr(profile, name)
                   and not (old.get(name) is None and getattr(profile, name) in (None, "", False))}
        if changes:
            audit_service.log_activity(session, company_id=company_id, user_id=user_id, entity_type="ItemStorageProfile",
                                       entity_id=item_id, action="UPDATE", changes=changes)
        session.commit()


def location_temperature(by_id: dict, location_id: int) -> tuple | None:
    """بازهٔ دمایِ نزدیک‌ترین محل (خودش یا والدها) که دما دارد."""
    for n in reversed(ancestors(by_id, location_id)):
        if n.temperature_min_c is not None or n.temperature_max_c is not None:
            return n.temperature_min_c, n.temperature_max_c
    return None


def compatibility_issues(company_id: int, item_id: int, location_id: int, by_id: dict | None = None,
                         profile: StorageProfile | None = None) -> list[str]:
    """ناسازگاری‌هایِ کالا با محل (دما، کالایِ خطرناک، نوعِ محلِ الزامی)؛ فهرستِ خالی = سازگار."""
    profile = profile if profile is not None else get_storage_profile(company_id, item_id)
    if profile.is_empty():
        return []
    if by_id is None:
        with new_session() as session:
            warehouse_id = _location(session, company_id, location_id).warehouse_id
        by_id = {n.location_id: n for n in tree(company_id, warehouse_id)}
    chain = ancestors(by_id, location_id)
    issues = []
    if profile.temperature_min_c is not None or profile.temperature_max_c is not None:
        loc_range = location_temperature(by_id, location_id)
        loc_min, loc_max = loc_range if loc_range else AMBIENT_RANGE
        loc_min = loc_min if loc_min is not None else loc_max
        loc_max = loc_max if loc_max is not None else loc_min
        if (profile.temperature_min_c is not None and loc_min is not None and loc_min < profile.temperature_min_c) or \
                (profile.temperature_max_c is not None and loc_max is not None and loc_max > profile.temperature_max_c):
            where = "محیط (بی‌دمایِ تعریف‌شده)" if loc_range is None else f"{loc_min} تا {loc_max}"
            need = f"{profile.temperature_min_c if profile.temperature_min_c is not None else '…'} تا " \
                   f"{profile.temperature_max_c if profile.temperature_max_c is not None else '…'}"
            issues.append(f"دمایِ محل {where} است ولی کالا {need} درجه نیاز دارد")
    if profile.hazard_class_code and not any(n.allows_hazardous for n in chain):
        issues.append(f"کالایِ خطرناک ({HAZARD_CLASSES.get(profile.hazard_class_code)}) فقط در محلِ مجاز برایِ کالایِ خطرناک")
    if profile.required_location_type_code and not any(n.location_type_code == profile.required_location_type_code for n in chain):
        issues.append(f"کالا فقط در محلِ «{LOCATION_TYPES[profile.required_location_type_code]}» نگهداری می‌شود")
    return issues


def _document_moves(doc, ln) -> list[tuple[str, int]]:
    """(جهت، محل) ردیفِ سند با همان قاعدهٔ موتورِ انبار؛ ردیفِ بی‌محل (محلِ پیش‌فرض) بررسی نمی‌شود."""
    t = doc.document_type_code
    moves = []
    if t == "TRANSFER":
        moves = [("OUT", ln.bin_location_id), ("IN", ln.destination_bin_location_id)]
    elif t == "ADJUSTMENT":
        moves = [("OUT" if doc.source_warehouse_id is not None else "IN", ln.bin_location_id)]
    elif t in ("RECEIPT", "RETURN_IN", "CONSIGNMENT_IN"):
        moves = [("IN", ln.bin_location_id)]
    else:
        moves = [("OUT", ln.bin_location_id)]
    return [(d, b) for d, b in moves if b is not None]


def check_document_locations(company_id: int, stock_document_id: int) -> SimpleNamespace:
    """پیش از تایید/ثبتِ سندِ انبار: خطا = ورود به محلِ غیرفعال/مسدود/در تعمیر/پر یا خروج از محلِ مسدود/در تعمیر؛
    هشدار = محلِ بدونِ اجازهٔ جانمایی/آسیب‌دیده، ناسازگاریِ کالا و عبور از ظرفیت."""
    errors, warnings = [], []
    with new_session() as session:
        doc = session.get(StockDocument, stock_document_id)
        if doc is None or doc.company_id != company_id:
            raise ValueError("سند نامعتبر است.")
        lines = list(session.scalars(select(StockDocumentLine).where(StockDocumentLine.stock_document_id == stock_document_id)
                                     .order_by(StockDocumentLine.line_no)))
        moves = [(ln, d, b) for ln in lines for d, b in _document_moves(doc, ln)]
        wh_of = dict(session.execute(select(BinLocation.bin_location_id, BinLocation.warehouse_id).where(
            BinLocation.bin_location_id.in_({b for _l, _d, b in moves} or {-1}))).all())
    trees: dict[int, dict] = {}
    occ_cache: dict[int, dict] = {}
    dims = _item_dims(company_id) if moves else {}
    incoming: dict[int, list] = defaultdict(lambda: [_ZERO, _ZERO])
    for ln, direction, bin_id in moves:
        wid = wh_of.get(bin_id)
        if wid is None:
            continue
        if wid not in trees:
            trees[wid] = {n.location_id: n for n in tree(company_id, wid)}
        node = trees[wid].get(bin_id)
        label = f"ردیفِ {ln.line_no}: محلِ «{node.full_code}»"
        if direction == "OUT" and node.status_code in NO_EXIT_STATUSES:
            errors.append(f"{label} {STATUSES[node.status_code]} است و خروجِ کالا از آن مجاز نیست.")
        if direction != "IN":
            continue
        if node.status_code in NO_ENTRY_STATUSES or not node.is_active:
            errors.append(f"{label} {STATUSES.get(node.status_code, 'غیرفعال')} است و ورودِ کالا به آن مجاز نیست.")
            continue
        if not node.allow_putaway or node.is_damaged:
            warnings.append(f"{label} برایِ جانمایی مجاز نیست یا آسیب‌دیده است.")
        for issue in compatibility_issues(company_id, ln.item_id, bin_id, trees[wid]):
            warnings.append(f"{label}: {issue}.")
        w, v = dims.get(ln.item_id, (None, None))
        incoming[bin_id][0] += ln.quantity_base * (w or _ZERO)
        incoming[bin_id][1] += ln.quantity_base * (v or _ZERO)
    for bin_id, (w_in, v_in) in incoming.items():
        wid = wh_of[bin_id]
        if wid not in occ_cache:
            occ_cache[wid] = occupancy(company_id, wid, list(trees[wid].values()))
        o = occ_cache[wid].get(bin_id)
        if o and ((o.max_weight is not None and o.weight + w_in > o.max_weight)
                  or (o.max_volume is not None and o.volume + v_in > o.max_volume)):
            warnings.append(f"ظرفیتِ محلِ «{trees[wid][bin_id].full_code}» با این سند پر می‌شود (عبور از ظرفیت).")
    return SimpleNamespace(errors=errors, warnings=warnings)


# =====================================================================
# R249: هندسهٔ سه‌بعدی (از همان مختصاتِ نقشه + ارتفاع/Z)
# =====================================================================
UNITS_PER_M = 20  # مقیاسِ نقشه: هر متر = ۲۰ واحد
_DEFAULT_HEIGHT_M = {"AREA": decimal.Decimal("0.05"), "AISLE": decimal.Decimal("0.02"), "RACK": decimal.Decimal("2.5"),
                     "SHELF": None, "BIN": None}


def scene_3d(company_id: int, warehouse_id: int, nodes: list | None = None) -> list[SimpleNamespace]:
    """جعبه‌هایِ سه‌بعدیِ محل‌ها (x, y, z, w, d, h به واحدِ نقشه). منطقه/راهرو کف‌اند؛ قفسه به ارتفاعِ خودش
    (یا ۲٫۵ متر)؛ طبقه‌ها ارتفاعِ قفسه را به ترتیبِ شمارهٔ طبقه تقسیم می‌کنند و Bin ارتفاعِ طبقه‌اش را می‌گیرد."""
    nodes = nodes if nodes is not None else tree(company_id, warehouse_id)
    geo = geometry(company_id, warehouse_id, nodes)
    by_id = {n.location_id: n for n in nodes}
    children = defaultdict(list)
    for n in nodes:
        children[n.parent_id].append(n)

    def footprint(lid):
        x, y, w, h, rot = geo[lid]
        if round(rot) % 180 == 90:  # چرخشِ ۹۰ درجه: ابعادِ کف جابه‌جا
            cx, cy = x + w / 2, y + h / 2
            return cx - h / 2, cy - w / 2, h, w
        return x, y, w, h

    out: dict[int, SimpleNamespace] = {}

    def add(n, z, height):
        if n.location_id not in geo:
            return
        x, y, w, d = footprint(n.location_id)
        out[n.location_id] = SimpleNamespace(location_id=n.location_id, level=n.level, code=n.full_code, x=x, y=y, z=z,
                                             w=w, d=d, h=height, status=n.status_code, active=n.is_active)

    for n in nodes:
        if n.level not in ("AREA", "AISLE", "RACK") and n.parent_id in by_id:
            continue
        base = float(n.map_z or 0) * UNITS_PER_M
        if n.level == "RACK" or n.level in ("SHELF", "BIN", None):
            height_m = n.height_m or _DEFAULT_HEIGHT_M["RACK"]
            rack_h = float(height_m) * UNITS_PER_M
            add(n, base, rack_h)
            shelves = sorted((k for k in children.get(n.location_id, []) if k.level == "SHELF"),
                             key=lambda k: (k.level_number or 0, k.code))
            slab = rack_h / len(shelves) if shelves else rack_h
            for i, shelf in enumerate(shelves):
                z = base + i * slab
                add(shelf, z, slab)
                for b in children.get(shelf.location_id, []):
                    add(b, z, slab)
            for b in (k for k in children.get(n.location_id, []) if k.level == "BIN"):
                add(b, base, rack_h)
        else:
            add(n, base, float(_DEFAULT_HEIGHT_M[n.level]) * UNITS_PER_M)
    return list(out.values())



# =====================================================================
# R251: بچ به تفکیکِ محل (از ستونِ محلِ inv.lot_movements)
# =====================================================================
def bin_batches(company_id: int, warehouse_id: int, item_id: int | None = None) -> dict[tuple[int, int], list[SimpleNamespace]]:
    """(محل، کالا) → بچ‌هایِ موجود در همان محل به ترتیبِ انقضا (FEFO)."""
    from peecha.db.models.inventory import Batch, LotMovement

    with new_session() as session:
        q = (select(LotMovement.bin_location_id, LotMovement.item_id, Batch.batch_id, Batch.batch_no, Batch.expiry_date,
                    func.sum(LotMovement.quantity_base))
             .join(Batch, Batch.batch_id == LotMovement.batch_id)
             .where(LotMovement.company_id == company_id, LotMovement.warehouse_id == warehouse_id,
                    LotMovement.bin_location_id.is_not(None))
             .group_by(LotMovement.bin_location_id, LotMovement.item_id, Batch.batch_id, Batch.batch_no, Batch.expiry_date))
        if item_id is not None:
            q = q.where(LotMovement.item_id == item_id)
        out: dict[tuple[int, int], list[SimpleNamespace]] = defaultdict(list)
        for bin_id, iid, batch_id, batch_no, expiry, qty in session.execute(q).all():
            if qty and qty > 0:
                out[(bin_id, iid)].append(SimpleNamespace(batch_id=batch_id, batch_no=batch_no, expiry_date=expiry, quantity=qty))
    for lots in out.values():
        lots.sort(key=lambda lt: (lt.expiry_date or datetime.date.max, lt.batch_no))
    return dict(out)


# =====================================================================
# R252: انتخابِ خودکارِ محلِ خروج در سندِ انبار
# =====================================================================
_OUT_TYPES = ("ISSUE", "RETURN_OUT", "CONSIGN_RETURN", "TRANSFER")


def assign_outbound_bins(company_id: int, stock_document_id: int) -> list[tuple[int, str]]:
    """ردیفِ خروجیِ بی‌محل در انبارِ دارایِ نقشه: اگر محلِ پیش‌فرض موجودیِ کافی ندارد، یک محل که کلِ مقدار را دارد
    انتخاب می‌شود (اول محلِ بچ/سریالِ تعیین‌شده، سپس زودانقضاترین بچ، سپس جبههٔ برداشت و بیشترین موجودی).
    ردیف تقسیم نمی‌شود؛ اگر هیچ محلی کلِ مقدار را نداشته باشد رفتارِ قبلی (محلِ پیش‌فرض) می‌ماند.
    خروجی: [(شمارهٔ ردیف، کدِ محلِ انتخاب‌شده)]."""
    from peecha.services import inventory_locations as locations_service
    from peecha.services import lot_tracking

    assigned: list[tuple[int, str]] = []
    with new_session() as session:
        doc = session.get(StockDocument, stock_document_id)
        if doc is None or doc.company_id != company_id or doc.status_code not in ("DRAFT", "CONFIRMED"):
            return assigned
        t = doc.document_type_code
        if t not in _OUT_TYPES and not (t == "ADJUSTMENT" and doc.source_warehouse_id):
            return assigned
        warehouse_id = doc.source_warehouse_id
        if warehouse_id is None or not session.scalar(select(func.count()).select_from(BinLocation).where(
                BinLocation.warehouse_id == warehouse_id, BinLocation.location_code.is_not(None))):
            return assigned
        lines = [ln for ln in session.scalars(select(StockDocumentLine).where(
            StockDocumentLine.stock_document_id == stock_document_id).order_by(StockDocumentLine.line_no)) if ln.bin_location_id is None]
        if not lines:
            return assigned
        default = locations_service.get_default_bin_location(warehouse_id)
        default_id = default.bin_location_id if default else None
        stock = defaultdict(dict)
        for b, i, q in session.execute(select(StockBalance.bin_location_id, StockBalance.item_id, func.sum(StockBalance.quantity_on_hand))
                                       .where(StockBalance.warehouse_id == warehouse_id)
                                       .group_by(StockBalance.bin_location_id, StockBalance.item_id)).all():
            stock[i][b] = (q or _ZERO) - _ZERO
    nodes = {n.location_id: n for n in tree(company_id, warehouse_id)}
    batches = bin_batches(company_id, warehouse_id)
    with new_session() as session:
        for ln in lines:
            item_stock = stock.get(ln.item_id, {})
            if default_id is not None and item_stock.get(default_id, _ZERO) >= ln.quantity_base:
                continue
            candidates = [b for b, q in item_stock.items() if b != default_id and q >= ln.quantity_base and b in nodes
                          and nodes[b].status_code not in NO_EXIT_STATUSES and b != ln.destination_bin_location_id]
            if not candidates:
                continue
            entries = lot_tracking.get_line_tracking(stock_line_id=ln.line_id)
            wanted_batches = {e.batch_no for e in entries if e.batch_no}
            wanted_serials = {e.serial_no for e in entries if e.serial_no}
            if wanted_serials:
                serial_bins = {s.current_bin_location_id for s in session.scalars(select(SerialNumber).where(
                    SerialNumber.item_id == ln.item_id, SerialNumber.serial_no.in_(wanted_serials)))}
                candidates = [b for b in candidates if b in serial_bins] or candidates
            if wanted_batches:
                candidates = [b for b in candidates if wanted_batches & {x.batch_no for x in batches.get((b, ln.item_id), [])}] or candidates

            def rank(b):
                lots = batches.get((b, ln.item_id), [])
                expiry = min((x.expiry_date for x in lots if x.expiry_date), default=datetime.date.max)
                types = {a.location_type_code for a in ancestors(nodes, b)}
                return expiry, not (types & {"PICK_FACE", "PICKING"}), -item_stock[b], nodes[b].full_code

            chosen = min(candidates, key=rank)
            row = session.get(StockDocumentLine, ln.line_id)
            row.bin_location_id = chosen
            item_stock[chosen] -= ln.quantity_base
            assigned.append((ln.line_no, nodes[chosen].full_code))
        session.commit()
    return assigned
