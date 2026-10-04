"""محلِ انبار برایِ اپِ موبایل -- R248 (اسکنِ کالا/محل، محتوا، پیشنهادِ جانمایی، تاییدِ جانمایی/برداشت، انتقال).

نازک: همهٔ منطق در services/warehouse_locations و services/warehouse_operations است؛ دسترسی با همان RBACِ موجود
(فرمِ «warehouse_map»). موجودی همان inv.stock_balance است و جابه‌جایی فقط با سندِ انتقالِ عادیِ سیستم.
"""

from __future__ import annotations

import decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from peecha.services import warehouse_locations as wl
from peecha.services import warehouse_operations as ops
from peecha_api.deps import AuthContext
from peecha_api.permissions import require_permission

router = APIRouter(prefix="/locations", tags=["locations"])
_VIEW = Depends(require_permission(wl.FORM_CODE, "VIEW"))
_EDIT = Depends(require_permission(wl.FORM_CODE, "EDIT"))


def _bad_request(exc: ValueError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


def _node_dict(n, occ=None, geo=None) -> dict:
    o = (occ or {}).get(n.location_id)
    g = (geo or {}).get(n.location_id)
    return {
        "location_id": n.location_id, "parent_id": n.parent_id, "code": n.full_code, "level": n.level,
        "name": n.name, "location_type": n.location_type_code, "status": n.status_code,
        "picking_allowed": n.is_pickable, "putaway_allowed": n.allow_putaway, "replenishment_allowed": n.allow_replenishment,
        "damaged": n.is_damaged,
        "occupancy_percent": str(o.percent) if o and o.percent is not None else None,
        "quantity": str(o.quantity) if o else "0",
        "map": {"x": g[0], "y": g[1], "width": g[2], "height": g[3], "rotation": g[4],
                "z": float(n.map_z) if n.map_z is not None else None} if g else None,
        "qr": wl.qr_payload(n.location_id, n.full_code),
    }


def _detail(company_id: int, location_id: int) -> dict:
    from peecha.db.base import new_session
    from peecha.db.models.inventory import BinLocation

    with new_session() as session:
        row = session.get(BinLocation, location_id)
        warehouse_id = row.warehouse_id if row else None
    if warehouse_id is None:
        raise ValueError("محل نامعتبر است.")
    nodes = wl.tree(company_id, warehouse_id)
    node = next(n for n in nodes if n.location_id == location_id)
    out = _node_dict(node, wl.occupancy(company_id, warehouse_id, nodes))
    out["warehouse_id"] = warehouse_id
    out["contents"] = [{
        "location_code": c.location_code, "item_id": c.item_id, "item_code": c.item_code, "item_name": c.item_name, "sku": c.sku,
        "quantity": str(c.quantity), "unit": c.unit, "batches": c.batches, "serials": c.serials,
        "expiry": c.expiry.isoformat() if c.expiry else None,
    } for c in wl.contents(company_id, location_id)]
    return out


@router.get("/warehouses/{warehouse_id}/map")
def warehouse_map(warehouse_id: int, ctx: AuthContext = _VIEW) -> list[dict]:
    """همهٔ محل‌هایِ انبار با مختصاتِ نقشه و اشغال (برایِ نقشهٔ موبایل/نمایِ سه‌بعدیِ آینده)."""
    try:
        nodes = wl.tree(ctx.company_id, warehouse_id)
    except ValueError as exc:
        raise _bad_request(exc) from exc
    occ, geo = wl.occupancy(ctx.company_id, warehouse_id, nodes), wl.geometry(ctx.company_id, warehouse_id, nodes)
    return [_node_dict(n, occ, geo) for n in nodes]


@router.get("/search")
def search(q: str, ctx: AuthContext = _VIEW) -> dict:
    """کد/نام/بارکدِ کالا، کد/بارکدِ محل یا متنِ QR."""
    try:
        result = wl.search(ctx.company_id, q)
    except ValueError as exc:
        raise _bad_request(exc) from exc
    return {"kind": result.kind, "item_ids": result.item_ids,
            "locations": [_detail(ctx.company_id, lid) for lid in result.location_ids[:50]]}


@router.get("/scan")
def scan(payload: str, ctx: AuthContext = _VIEW) -> dict:
    """اسکنِ QRِ محل → جزئیات و محتوا."""
    try:
        return _detail(ctx.company_id, wl.decode_qr(ctx.company_id, payload))
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.get("/items/{item_id}")
def item_locations(item_id: int, ctx: AuthContext = _VIEW) -> list[dict]:
    return [{"warehouse_id": r.warehouse_id, "warehouse": r.warehouse, "location_id": r.location_id, "location_code": r.location_code,
             "zone": r.zone, "aisle": r.aisle, "rack": r.rack, "level": r.level, "bin": r.bin, "quantity": str(r.quantity)}
            for r in wl.product_locations(ctx.company_id, item_id)]


@router.get("/putaway-suggestions")
def putaway_suggestions(warehouse_id: int, item_id: int, quantity: decimal.Decimal, ctx: AuthContext = _VIEW) -> list[dict]:
    try:
        rows = wl.putaway_suggestions(ctx.company_id, warehouse_id, item_id, quantity)
    except ValueError as exc:
        raise _bad_request(exc) from exc
    return [{"location_id": s.location_id, "location_code": s.location_code, "score": s.score, "abc_class": s.abc_class,
             "reasons": s.reasons} for s in rows]


@router.get("/{location_id}")
def location_detail(location_id: int, ctx: AuthContext = _VIEW) -> dict:
    try:
        return _detail(ctx.company_id, location_id)
    except ValueError as exc:
        raise _bad_request(exc) from exc


class TransferRequest(BaseModel):
    item_id: int
    from_location_id: int
    to_location_id: int
    quantity: decimal.Decimal
    allow_over_capacity: bool = False


@router.post("/transfer")
def transfer(body: TransferRequest, ctx: AuthContext = _EDIT) -> dict:
    try:
        doc_id = wl.transfer(ctx.company_id, ctx.user_id, body.item_id, body.from_location_id, body.to_location_id,
                             body.quantity, body.allow_over_capacity)
    except ValueError as exc:
        raise _bad_request(exc) from exc
    return {"stock_document_id": doc_id}


class PutawayConfirm(BaseModel):
    to_location_id: int


@router.post("/tasks/{task_id}/putaway")
def confirm_putaway(task_id: int, body: PutawayConfirm, ctx: AuthContext = _EDIT) -> dict:
    try:
        doc_id = ops.complete_putaway(task_id, ctx.company_id, ctx.user_id, body.to_location_id)
    except ValueError as exc:
        raise _bad_request(exc) from exc
    return {"task_id": task_id, "stock_document_id": doc_id}


class PickConfirm(BaseModel):
    quantity: decimal.Decimal


@router.post("/tasks/{task_id}/pick")
def confirm_pick(task_id: int, body: PickConfirm, ctx: AuthContext = _EDIT) -> dict:
    try:
        ops.complete_pick(task_id, ctx.company_id, ctx.user_id, body.quantity)
    except ValueError as exc:
        raise _bad_request(exc) from exc
    return {"task_id": task_id, "status": "DONE"}
