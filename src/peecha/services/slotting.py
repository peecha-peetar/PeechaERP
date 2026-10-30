"""R309 — پیشنهاد چیدمان (Slotting؛ کلید WMS_SLOTTING_SUGGESTIONS).

کلاس ABC هر کالا از دفعات خروج همان انبار (همان abc_classes گزارش‌های انبار، مبنای «دفعات») خوانده می‌شود:
کالای پرگردش (A) که در هیچ محل جمع‌آوری نیست → پیشنهاد محل جمع‌آوری؛ کالای کم‌گردش (C) که محل جمع‌آوری را گرفته
→ پیشنهاد محل ذخیره/حجیم. فقط پیشنهاد است؛ جابه‌جایی با سند انتقال پیش‌نویسی که کاربر ثبت می‌کند.
"""

from __future__ import annotations

import datetime
import decimal
from types import SimpleNamespace

from peecha.services import warehouse_locations as wl

_ZERO = decimal.Decimal(0)
_PICK_TYPES = {"PICK_FACE", "PICKING"}
_STORE_TYPES = {"RESERVE", "BULK"}


def suggestions(company_id: int, warehouse_id: int, days: int = 90) -> list[SimpleNamespace]:
    from peecha.services import inventory_catalog as catalog_service
    from peecha.services import purchase_reports as base
    from peecha.services import warehouse_reports as wr

    nodes = wl.tree(company_id, warehouse_id)
    if not nodes:
        return []
    by_id = {n.location_id: n for n in nodes}
    types = {n.location_id: {a.location_type_code for a in wl.ancestors(by_id, n.location_id) if a.location_type_code}
             for n in nodes}
    if not any(t & _PICK_TYPES for t in types.values()):
        return []   # انبار محل جمع‌آوری تعریف‌شده ندارد
    today = datetime.date.today()
    f = base.PurchaseFilters(today - datetime.timedelta(days=days), today, warehouse_id=warehouse_id, side="INVENTORY",
                             options={"basis": "FREQ"})
    classes = {row[0]: (row[-1], row[3]) for row in wr.abc_classes(company_id, f)}
    stock: dict[int, list] = {}
    for b, i, q, _r, _v in wl._stock_by_bin(company_id, warehouse_id):
        if q and q > 0 and b in by_id:
            stock.setdefault(i, []).append((b, decimal.Decimal(q)))
    labels = {i.item_id: f"{i.code} — {i.name or ''}" for i in catalog_service.list_items(company_id)}
    out = []
    for item_id, places in stock.items():
        cls, picks = classes.get(item_id, ("C", 0))
        in_pick = [(b, q) for b, q in places if types.get(b, set()) & _PICK_TYPES]
        if cls == "A" and not in_pick:
            source, qty = max(places, key=lambda p: p[1])
            target = next((s for s in wl.putaway_suggestions(company_id, warehouse_id, item_id, qty, limit=20)
                           if types.get(s.location_id, set()) & _PICK_TYPES), None)
            reason = "کالای پرگردش در هیچ محل جمع‌آوری نیست"
        elif cls == "C" and in_pick:
            source, qty = max(in_pick, key=lambda p: p[1])
            target = next((s for s in wl.putaway_suggestions(company_id, warehouse_id, item_id, qty, limit=20)
                           if types.get(s.location_id, set()) & _STORE_TYPES), None)
            reason = "کالای کم‌گردش محل جمع‌آوری را گرفته است"
        else:
            continue
        if target is None or target.location_id == source:
            continue
        out.append(SimpleNamespace(item_id=item_id, item_label=labels.get(item_id, ""), abc_class=cls, picks=picks,
                                   from_location_id=source, from_code=by_id[source].full_code, quantity=qty,
                                   to_location_id=target.location_id, to_code=target.location_code, reason=reason))
    return sorted(out, key=lambda s: (s.abc_class, -s.picks, s.item_label))


def create_move_draft(company_id: int, user_id: int, warehouse_id: int, suggestion: SimpleNamespace) -> int:
    """سند انتقال پیش‌نویس درون همان انبار برای یک پیشنهاد (ثبتش با کاربر)."""
    from peecha.services import inventory_documents as inv_docs

    base_uom = _base_uom(suggestion.item_id)
    doc_id = inv_docs.create_stock_document(company_id, user_id, "TRANSFER", datetime.date.today(), inv_docs.DocumentHeaderFields(
        source_warehouse_id=warehouse_id, destination_warehouse_id=warehouse_id, reference_no="SLOTTING",
        description=f"پیشنهاد چیدمان: {suggestion.reason}"))
    inv_docs.add_line(doc_id, company_id, inv_docs.LineFields(
        item_id=suggestion.item_id, uom_id=base_uom, quantity=suggestion.quantity, quantity_base=suggestion.quantity,
        conversion_factor=decimal.Decimal(1), bin_location_id=suggestion.from_location_id,
        destination_bin_location_id=suggestion.to_location_id, description=f"{suggestion.from_code} ← {suggestion.to_code}"))
    return doc_id


def _base_uom(item_id: int) -> int:
    from sqlalchemy import select

    from peecha.db.base import new_session
    from peecha.db.models.inventory import Item

    with new_session() as session:
        return session.scalar(select(Item.base_uom_id).where(Item.item_id == item_id))
