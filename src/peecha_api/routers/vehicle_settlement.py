"""تسویهٔ پایانِ روزِ خودرو -- طبقِ درخواستِ صریحِ کاربر («تسویه آخر روز
باید بصورت انتخابی به یک نفر از ۳ تا نقش واگذار بشه و تسویه را باید به
تاییدِ انبار و حسابداری برسونه»). این اندپوینت‌ها فقط برایِ ثبتِ سمتِ
موبایل‌اند -- تاییدِ انبار/حسابداری همچنان از دسکتاپ انجام می‌شود
(هم‌الگو با تاییدِ انبار/توزینِ پخشِ سرد)."""

from __future__ import annotations

import datetime
import decimal

from fastapi import APIRouter, Depends, HTTPException, status

from peecha.services import inventory_catalog as catalog_service
from peecha.services import vehicle_settlement as settlement_service
from peecha_api.deps import AuthContext, get_current_context
from peecha_api.schemas import VehicleSettlementSubmitRequest

router = APIRouter(prefix="/vehicle-settlement", tags=["vehicle-settlement"])


def _resolve_vehicle_or_403(ctx: AuthContext) -> int:
    vehicle_warehouse_id = settlement_service.get_settlement_vehicle_for_user(ctx.user_id, ctx.company_id)
    if vehicle_warehouse_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="شما مسئولِ ثبتِ تسویهٔ پایانِ روزِ هیچ خودرویی نیستید.",
        )
    return vehicle_warehouse_id


@router.get("/today-summary")
def today_summary(ctx: AuthContext = Depends(get_current_context)) -> dict:
    vehicle_warehouse_id = _resolve_vehicle_or_403(ctx)
    today = datetime.date.today()
    # طبقِ درخواستِ صریحِ کاربر («چند بار پخشِ گرم و تسویه در یک روز»):
    # اگر امروز قبلاً تسویه شده، پیش‌نمایش هم فقط بعدِ آن را نشان می‌دهد --
    # هم‌الگو با submit_settlement، وگرنه پیش‌نمایش با مبلغِ واقعیِ ثبت‌شده فرق می‌کند.
    window_start = settlement_service.get_open_window_start(vehicle_warehouse_id, ctx.company_id, today)
    lines = settlement_service.compute_today_summary(vehicle_warehouse_id, ctx.company_id, today, after=window_start)
    items_by_id = {i.item_id: i for i in catalog_service.list_items(ctx.company_id)}
    invoiced_amount = settlement_service.compute_invoiced_amount(vehicle_warehouse_id, ctx.company_id, today, after=window_start)
    return {
        "invoiced_amount": str(invoiced_amount),
        "lines": [
            {
                "item_id": l.item_id, "item_name": items_by_id[l.item_id].name if l.item_id in items_by_id else None,
                "uom_id": l.uom_id, "loaded_quantity": str(l.loaded_quantity), "sold_quantity": str(l.sold_quantity),
            }
            for l in lines
        ],
    }


@router.post("")
def submit(payload: VehicleSettlementSubmitRequest, ctx: AuthContext = Depends(get_current_context)) -> dict:
    vehicle_warehouse_id = _resolve_vehicle_or_403(ctx)
    today = datetime.date.today()
    window_start = settlement_service.get_open_window_start(vehicle_warehouse_id, ctx.company_id, today)
    summary_by_item = {
        (l.item_id, l.uom_id): l
        for l in settlement_service.compute_today_summary(vehicle_warehouse_id, ctx.company_id, today, after=window_start)
    }
    lines = []
    for line in payload.lines:
        summary = summary_by_item.get((line.item_id, line.uom_id))
        lines.append(
            settlement_service.SettlementLineInput(
                item_id=line.item_id, uom_id=line.uom_id,
                loaded_quantity=summary.loaded_quantity if summary else decimal.Decimal(0),
                sold_quantity=summary.sold_quantity if summary else decimal.Decimal(0),
                returned_quantity=line.returned_quantity,
            )
        )
    try:
        vehicle_settlement_id = settlement_service.submit_settlement(
            vehicle_warehouse_id, ctx.company_id, ctx.user_id, today, lines, payload.declared_cash_amount,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {"vehicle_settlement_id": vehicle_settlement_id}
