"""تولید: صدور دستور تولید پس از تایید، کمبود مواد و تکمیل تولید."""

from __future__ import annotations

import decimal

from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.production import ProductionOrder
from peecha.services.workflow import model_events, registry
from peecha.services.workflow.adapters._common import ZERO, item_code_name, jdate, user_name
from peecha.services.workflow.common import WorkflowError, display
from peecha.services.workflow.model_events import Watch
from peecha.services.workflow.registry import ActionContext, ActionSpec, EntityAdapter, FieldSpec, ScanSpec


def order_context(company_id: int, order_id: int) -> dict:
    from peecha.services.production import orders

    with new_session() as session:
        o = session.get(ProductionOrder, order_id)
        if o is None or o.company_id != company_id:
            raise WorkflowError("دستور تولید پیدا نشد.")
        out = {"order_id": o.order_id, "order_code": o.order_code, "item_id": o.item_id,
               "item_name": item_code_name(session, o.item_id)[1],
               "planned_qty": decimal.Decimal(o.planned_qty), "produced_qty": decimal.Decimal(o.produced_qty or 0),
               "start_date": o.start_date, "due_date": o.due_date, "status": o.status_code, "priority": o.priority,
               "branch_id": o.branch_id, "work_center_id": o.work_center_id, "responsible": o.responsible_user_id,
               "responsible_name": user_name(session, o.responsible_user_id), "created_by": o.created_by_user_id,
               "planned_cost": (decimal.Decimal(o.planned_unit_cost or 0) * decimal.Decimal(o.planned_qty)).quantize(decimal.Decimal("0.01"))}
    try:
        rows = [a for a in orders.availability(company_id, order_id) if a.status != "GREEN" and not a.is_optional]
    except Exception:  # noqa: BLE001 -- دستور بدون فهرست مواد: کمبودی گزارش نمی‌شود
        rows = []
    out["shortage_count"] = len(rows)
    out["has_shortage"] = bool(rows)
    out["shortage_text"] = "، ".join(f"{a.item_label} ({display(a.shortage)})" for a in rows[:8])
    return out


def _release(ctx: ActionContext) -> dict:
    from peecha.services.production import orders

    with new_session() as session:
        status = session.get(ProductionOrder, ctx.entity_id).status_code
    if status == "DRAFT":
        orders.plan_order(ctx.company_id, ctx.user_id, int(ctx.entity_id))
    shortages = orders.release_order(ctx.company_id, ctx.user_id, int(ctx.entity_id))
    return {"shortages": len(shortages)}


def _plan(ctx: ActionContext) -> dict:
    from peecha.services.production import orders

    orders.plan_order(ctx.company_id, ctx.user_id, int(ctx.entity_id))
    return {"status": "PLANNED"}


def _status_in(*statuses: str):
    def check(company_id: int, order_id: int) -> bool:
        with new_session() as session:
            o = session.get(ProductionOrder, order_id)
            return o is not None and o.status_code in statuses
    return check


_STATUS = {"DRAFT": "پیش‌نویس", "PLANNED": "برنامه‌ریزی‌شده", "RELEASED": "صادرشده", "IN_PROGRESS": "در حال تولید",
           "ON_HOLD": "متوقف", "COMPLETED": "تکمیل‌شده", "CLOSED": "بسته‌شده", "CANCELLED": "لغوشده"}

registry.register_adapter(EntityAdapter(
    "PRODUCTION_ORDER", "دستور تولید", "PRODUCTION", order_context,
    fields=(FieldSpec("planned_qty", "مقدار برنامه", "number"), FieldSpec("planned_cost", "بهای برنامه", "money"),
            FieldSpec("has_shortage", "کمبود مواد دارد", "bool"), FieldSpec("shortage_count", "تعداد اقلام کمبود", "number"),
            FieldSpec("priority", "اولویت", "number"), FieldSpec("branch_id", "شعبه", "number"),
            FieldSpec("work_center_id", "مرکز کاری", "number"), FieldSpec("responsible", "مسئول", "user"),
            FieldSpec("created_by", "ثبت‌کننده", "user"), FieldSpec("due_date", "موعد", "date"),
            FieldSpec("status", "وضعیت", "choice", _STATUS)),
    events={f"PRODUCTION_ORDER_{k}": f"{v} — دستور تولید" for k, v in
            {"CREATED": "ثبت", "PLANNED": "برنامه‌ریزی", "RELEASED": "صدور", "IN_PROGRESS": "شروع تولید",
             "COMPLETED": "تکمیل", "CLOSED": "بستن", "CANCELLED": "لغو"}.items()},
    actions={"release": ActionSpec("release", "صدور دستور تولید", _release, risk="HIGH",
                                   is_done=_status_in("RELEASED", "IN_PROGRESS", "COMPLETED", "CLOSED")),
             "plan": ActionSpec("plan", "برنامه‌ریزی دستور", _plan, is_done=_status_in("PLANNED", "RELEASED", "IN_PROGRESS",
                                                                                           "COMPLETED", "CLOSED"))},
    title=lambda c: f"دستور تولید {c.get('order_code')} — {c.get('item_name') or ''}".strip(" —"),
    owner=lambda cid, eid: order_context(cid, eid)["responsible"] or order_context(cid, eid)["created_by"],
    approval_context=lambda cid, eid: (lambda c: [
        ("کالا", c["item_name"]), ("مقدار", display(c["planned_qty"])), ("شروع", jdate(c["start_date"])),
        ("موعد", jdate(c["due_date"])), ("بهای برنامه", display(c["planned_cost"])),
        ("کمبود مواد", c["shortage_text"] or "ندارد")])(order_context(cid, eid)),
    open_nav="PRD_ORDERS", open_method="open_order", submitter_field="created_by", gate_statuses=("RELEASED",),
    gate_label="تا تایید فرایند، دستور تولید صادر نمی‌شود", form_code="prd_orders"))

model_events.watch(Watch(ProductionOrder, lambda o: "PRODUCTION_ORDER", actor=lambda o: o.created_by_user_id))


def _shortages(company_id: int, params: dict) -> list[int]:
    from peecha.services.production import orders

    with new_session() as session:
        ids = list(session.scalars(select(ProductionOrder.order_id).where(
            ProductionOrder.company_id == company_id, ProductionOrder.status_code.in_(("PLANNED", "RELEASED", "IN_PROGRESS")))))
    out = []
    for oid in ids:
        try:
            if any(a.status != "GREEN" and not a.is_optional for a in orders.availability(company_id, oid)):
                out.append(oid)
        except Exception:  # noqa: BLE001
            continue
    return out


registry.register_scan(ScanSpec("MATERIAL_SHORTAGE", "دستورهای تولید دارای کمبود مواد", "PRODUCTION_ORDER", _shortages))
