"""انبار: اصلاح موجودی، انتقال بین انبارها، انبارگردانی و سفارش مجدد کالای زیر نقطهٔ سفارش.

انتقال و انبارگردانی چندمرحله‌ای‌اند (چند سند پشت سر هم)، پس دروازه‌شان فقط پیش‌بررسی فرم است تا هیچ ثبتی
نیمه‌کاره نماند؛ انتقال‌های خودکار (بارگیری خودرو، تسویهٔ خودرو، امانی) هیچ‌وقت متوقف نمی‌شوند.
"""

from __future__ import annotations

import datetime
import decimal

from sqlalchemy import func, select

from peecha.db.base import new_session
from peecha.db.models.inventory import (
    CycleCountSession, Item, ReorderPolicy, StockBalance, StockDocument, StockDocumentLine, Warehouse,
)
from peecha.services.workflow import model_events, registry
from peecha.services.workflow.adapters._common import ZERO, item_code_name, jdate, user_name
from peecha.services.workflow.common import WorkflowError, display
from peecha.services.workflow.model_events import Watch
from peecha.services.workflow.registry import ActionContext, ActionSpec, EntityAdapter, FieldSpec, ParamSpec, ScanSpec

STOCK_STATUS = {"DRAFT": "پیش‌نویس", "CONFIRMED": "تاییدشده", "POSTED": "ثبت نهایی", "REVERSED": "برگشت‌خورده"}
STOCK_KINDS = {"ADJUSTMENT": ("STOCK_ADJUSTMENT", "اصلاح موجودی", "INV_ADJUSTMENT"),
               "TRANSFER": ("STOCK_TRANSFER", "انتقال بین انبارها", "INV_TRANSFER")}


def _wh_name(session, warehouse_id: int | None) -> str:
    row = session.get(Warehouse, warehouse_id) if warehouse_id else None
    return row.name if row else ""


# --- اسناد انبار -------------------------------------------------------------------------------------------
def stock_context(company_id: int, stock_document_id: int) -> dict:
    with new_session() as session:
        d = session.get(StockDocument, stock_document_id)
        if d is None or d.company_id != company_id:
            raise WorkflowError("سند انبار پیدا نشد.")
        qty, value, lines = session.execute(
            select(func.coalesce(func.sum(func.abs(StockDocumentLine.quantity_base)), 0),
                   func.coalesce(func.sum(func.abs(StockDocumentLine.quantity_base) * func.coalesce(StockDocumentLine.unit_cost, 0)), 0),
                   func.count()).where(StockDocumentLine.stock_document_id == stock_document_id)).one()
        return {"stock_document_id": d.stock_document_id, "document_no": d.document_no, "document_type": d.document_type_code,
                "document_date": d.document_date, "status": d.status_code, "source_warehouse_id": d.source_warehouse_id,
                "destination_warehouse_id": d.destination_warehouse_id, "source_warehouse": _wh_name(session, d.source_warehouse_id),
                "destination_warehouse": _wh_name(session, d.destination_warehouse_id),
                "total_quantity": decimal.Decimal(qty or 0), "total_value": decimal.Decimal(value or 0).quantize(decimal.Decimal("0.01")),
                "line_count": int(lines), "created_by": d.created_by_user_id,
                "created_by_name": user_name(session, d.created_by_user_id), "description": d.description or ""}


def _stock_post(ctx: ActionContext) -> dict:
    from peecha.services import inventory_documents

    with new_session() as session:
        status = session.get(StockDocument, ctx.entity_id).status_code
    if status == "DRAFT":
        inventory_documents.confirm_stock_document(int(ctx.entity_id), ctx.company_id)
    result = inventory_documents.post_stock_document(int(ctx.entity_id), ctx.company_id, ctx.user_id)
    return {"journal_entry_id": getattr(result, "journal_entry_id", None)}


def _stock_posted(company_id: int, stock_document_id: int) -> bool:
    with new_session() as session:
        d = session.get(StockDocument, stock_document_id)
        return d is not None and d.status_code in ("POSTED", "REVERSED")


def _stock_card(company_id: int, stock_document_id: int) -> list[tuple[str, str]]:
    c = stock_context(company_id, stock_document_id)
    rows = [("تاریخ", jdate(c["document_date"])), ("تعداد ردیف", str(c["line_count"])), ("جمع مقدار", display(c["total_quantity"])),
            ("ارزش تقریبی", display(c["total_value"])), ("ثبت‌کننده", c["created_by_name"] or "—")]
    if c["source_warehouse"]:
        rows.insert(0, ("انبار مبدأ", c["source_warehouse"]))
    if c["destination_warehouse"]:
        rows.insert(1, ("انبار مقصد", c["destination_warehouse"]))
    return rows


STOCK_FIELDS = (FieldSpec("total_quantity", "جمع مقدار", "number"), FieldSpec("total_value", "ارزش تقریبی", "money"),
                FieldSpec("source_warehouse_id", "انبار مبدأ", "number"), FieldSpec("destination_warehouse_id", "انبار مقصد", "number"),
                FieldSpec("line_count", "تعداد ردیف", "number"), FieldSpec("created_by", "ثبت‌کننده", "user"),
                FieldSpec("status", "وضعیت", "choice", STOCK_STATUS))

for _code, (_et, _label, _nav) in STOCK_KINDS.items():
    registry.register_adapter(EntityAdapter(
        _et, _label, "INVENTORY", stock_context, fields=STOCK_FIELDS,
        events={f"{_et}_CREATED": f"ثبت «{_label}»", f"{_et}_CONFIRMED": f"تایید «{_label}»",
                f"{_et}_POSTED": f"ثبت نهایی «{_label}»"},
        actions={"post": ActionSpec("post", "ثبت نهایی سند انبار", _stock_post, risk="HIGH", is_done=_stock_posted)},
        title=lambda c, _l=_label: f"{_l} شمارهٔ {c.get('document_no')}",
        owner=lambda cid, eid: stock_context(cid, eid)["created_by"], approval_context=_stock_card, open_nav=_nav,
        submitter_field="created_by",
        # اصلاح موجودی یک‌مرحله‌ای است (دروازهٔ سرویس)؛ انتقال فقط پیش‌بررسی فرم
        gate_statuses=("POSTED",) if _code == "ADJUSTMENT" else (),
        form_gate_statuses=() if _code == "ADJUSTMENT" else ("POSTED",),
        gate_label="تا تایید فرایند، سند ثبت نهایی نمی‌شود", form_code=f"inventory_document_{_code.lower()}"))


def _stock_entity(d: StockDocument) -> str | None:
    kind = STOCK_KINDS.get(d.document_type_code)
    if kind is None or (d.document_type_code == "ADJUSTMENT" and d.cycle_count_session_id):
        return None  # اختلاف انبارگردانی با فرایند خود انبارگردانی کنترل می‌شود
    return kind[0]


model_events.watch(Watch(StockDocument, _stock_entity, actor=lambda d: d.created_by_user_id))


# --- انبارگردانی --------------------------------------------------------------------------------------------
COUNT_STATUS = {"PLANNED": "برنامه‌ریزی‌شده", "COUNTING": "در حال شمارش", "POSTED": "ثبت نهایی", "CANCELLED": "لغوشده"}


def count_context(company_id: int, session_id: int) -> dict:
    from peecha.services import stock_count

    try:
        s = stock_count.get_count_session(session_id, company_id)
    except ValueError as exc:
        raise WorkflowError(str(exc)) from exc
    counted = [ln for ln in s.lines if ln.counted_quantity_base is not None]
    diffs = [ln for ln in counted if ln.variance_quantity_base]
    with new_session() as session:
        row = session.get(CycleCountSession, session_id)
        creator = row.created_by_user_id
        warehouse = _wh_name(session, s.warehouse_id)
    return {"session_id": s.session_id, "session_code": s.session_code, "warehouse_id": s.warehouse_id, "warehouse": warehouse,
            "status": s.status_code, "line_count": len(s.lines), "counted_lines": len(counted), "difference_lines": len(diffs),
            "difference_quantity": sum((abs(ln.variance_quantity_base) for ln in diffs), ZERO), "created_by": creator}


def _count_finalize(ctx: ActionContext) -> dict:
    from peecha.services import stock_count

    return {"stock_document_ids": stock_count.finalize_count_session(int(ctx.entity_id), ctx.company_id, ctx.user_id)}


def _count_posted(company_id: int, session_id: int) -> bool:
    with new_session() as session:
        row = session.get(CycleCountSession, session_id)
        return row is not None and row.status_code == "POSTED"


registry.register_adapter(EntityAdapter(
    "INVENTORY_COUNT", "انبارگردانی", "INVENTORY", count_context,
    fields=(FieldSpec("difference_lines", "ردیف‌های دارای اختلاف", "number"),
            FieldSpec("difference_quantity", "جمع اختلاف", "number"), FieldSpec("warehouse_id", "انبار", "number"),
            FieldSpec("line_count", "تعداد ردیف", "number"), FieldSpec("created_by", "ثبت‌کننده", "user")),
    events={"INVENTORY_COUNT_CREATED": "شروع انبارگردانی", "INVENTORY_COUNT_COUNTING": "شروع شمارش",
            "INVENTORY_COUNT_POSTED": "ثبت نهایی انبارگردانی"},
    actions={"finalize": ActionSpec("finalize", "ثبت نهایی انبارگردانی (اصلاح اختلاف‌ها)", _count_finalize, risk="HIGH",
                                    is_done=_count_posted)},
    title=lambda c: f"انبارگردانی {c.get('session_code')} — {c.get('warehouse') or ''}".strip(" —"),
    owner=lambda cid, eid: count_context(cid, eid)["created_by"],
    approval_context=lambda cid, eid: (lambda c: [
        ("انبار", c["warehouse"]), ("ردیف‌های شمرده‌شده", f"{c['counted_lines']} از {c['line_count']}"),
        ("ردیف‌های دارای اختلاف", str(c["difference_lines"])), ("جمع اختلاف", display(c["difference_quantity"]))])(
        count_context(cid, eid)),
    open_nav="INV_STOCK_COUNT", open_method="open_session", submitter_field="created_by", form_gate_statuses=("POSTED",),
    gate_label="تا تایید فرایند، انبارگردانی ثبت نهایی نمی‌شود", form_code="stock_count"))

model_events.watch(Watch(CycleCountSession, lambda s: "INVENTORY_COUNT", actor=lambda s: s.created_by_user_id))


# --- سفارش مجدد (کالای زیر نقطهٔ سفارش) --------------------------------------------------------------------
def _free_qty(session, item_id: int, warehouse_id: int | None) -> tuple[decimal.Decimal, decimal.Decimal]:
    q = select(func.coalesce(func.sum(StockBalance.quantity_on_hand), 0),
               func.coalesce(func.sum(StockBalance.quantity_reserved), 0)).where(StockBalance.item_id == item_id)
    if warehouse_id is not None:
        q = q.where(StockBalance.warehouse_id == warehouse_id)
    on_hand, reserved = session.execute(q).one()
    return decimal.Decimal(on_hand or 0), decimal.Decimal(reserved or 0)


def reorder_context(company_id: int, policy_id: int) -> dict:
    """همان قاعدهٔ «پیشنهاد خرید» گزارش نقطهٔ سفارش: آزاد ≤ نقطهٔ سفارش؛ پیشنهاد = (حداکثر، وگرنه نقطه + مقدار سفارش) − آزاد."""
    with new_session() as session:
        p = session.get(ReorderPolicy, policy_id)
        if p is None or p.company_id != company_id:
            raise WorkflowError("سیاست سفارش کالا پیدا نشد.")
        item = session.get(Item, p.item_id)
        code, name = item_code_name(session, p.item_id)
        on_hand, reserved = _free_qty(session, p.item_id, p.warehouse_id)
        free = on_hand - reserved
        rop = p.reorder_point_qty if p.reorder_point_qty is not None else p.min_qty
        target = p.max_qty if p.max_qty is not None else (rop or ZERO) + (p.reorder_qty or ZERO)
        due = rop is not None and free <= rop
        return {"policy_id": p.policy_id, "item_id": p.item_id, "item_code": code,
                "item_name": name, "base_uom_id": item.base_uom_id if item else None,
                "warehouse_id": p.warehouse_id, "warehouse": _wh_name(session, p.warehouse_id) or "همهٔ انبارها",
                "on_hand": on_hand, "reserved": reserved, "free": free, "reorder_point": rop, "max_qty": p.max_qty,
                "below_point": due, "suggested_qty": max(target - free, ZERO) if due else ZERO}


def _below_min(company_id: int, params: dict) -> list[int]:
    with new_session() as session:
        ids = list(session.scalars(select(ReorderPolicy.policy_id).where(ReorderPolicy.company_id == company_id,
                                                                        ReorderPolicy.is_active.is_(True))))
    out = []
    for pid in ids:
        try:
            if reorder_context(company_id, pid)["below_point"]:
                out.append(pid)
        except WorkflowError:
            continue
    return out


def _open_request_for(session, company_id: int, item_id: int) -> int | None:
    from peecha.db.models.commercial import PurchaseRequest, PurchaseRequestLine

    return session.scalar(select(PurchaseRequest.request_id).join(
        PurchaseRequestLine, PurchaseRequestLine.request_id == PurchaseRequest.request_id).where(
        PurchaseRequest.company_id == company_id, PurchaseRequestLine.item_id == item_id,
        PurchaseRequest.status_code.in_(("DRAFT", "SUBMITTED", "APPROVED"))).limit(1))


def _create_purchase_request(ctx: ActionContext) -> dict:
    """درخواست خرید با همان سرویس درخواست خرید؛ اگر برای این کالا درخواست بازی هست، تکراری ساخته نمی‌شود."""
    from peecha.services import purchase_requests as pr

    c = reorder_context(ctx.company_id, int(ctx.entity_id))
    with new_session() as session:
        existing = _open_request_for(session, ctx.company_id, c["item_id"])
    if existing:
        return {"request_id": existing, "already_open": True}
    qty = c["suggested_qty"]
    if qty <= 0:
        return {"skipped": True}
    request_id = pr.create_request(ctx.company_id, ctx.user_id, pr.RequestFields(
        request_date=datetime.date.today(), warehouse_id=c["warehouse_id"],
        priority_code=ctx.params.get("priority") or "NORMAL",
        description=f"درخواست خودکار: موجودی «{c['item_name']}» به نقطهٔ سفارش رسید"))
    pr.add_line(request_id, ctx.company_id, c["item_id"], c["base_uom_id"], qty)
    if str(ctx.params.get("submit", "true")).lower() in ("1", "true", "yes"):
        pr.submit_request(request_id, ctx.company_id)
    return {"request_id": request_id, "quantity": str(qty)}


registry.register_adapter(EntityAdapter(
    "REORDER_POLICY", "سفارش مجدد کالا", "INVENTORY", reorder_context,
    fields=(FieldSpec("free", "موجودی آزاد", "number"), FieldSpec("reorder_point", "نقطهٔ سفارش", "number"),
            FieldSpec("suggested_qty", "مقدار پیشنهادی", "number"), FieldSpec("warehouse_id", "انبار", "number"),
            FieldSpec("item_id", "کالا", "number")),
    actions={"create_purchase_request": ActionSpec(
        "create_purchase_request", "ساخت درخواست خرید", _create_purchase_request,
        params=(ParamSpec("submit", "ارسال خودکار درخواست", "choice", "true", {"true": "بله", "false": "خیر"}),
                ParamSpec("priority", "اولویت", "choice", "NORMAL", {"NORMAL": "عادی", "HIGH": "زیاد", "URGENT": "فوری"})))},
    title=lambda c: f"رسیدن «{c.get('item_name')}» به نقطهٔ سفارش — {c.get('warehouse')}",
    approval_context=lambda cid, eid: (lambda c: [
        ("کالا", f"{c['item_code']} — {c['item_name']}"), ("انبار", c["warehouse"]), ("موجودی آزاد", display(c["free"])),
        ("نقطهٔ سفارش", display(c["reorder_point"])), ("مقدار پیشنهادی", display(c["suggested_qty"]))])(reorder_context(cid, eid))))

registry.register_scan(ScanSpec("STOCK_BELOW_MIN", "کالاهای رسیده به نقطهٔ سفارش", "REORDER_POLICY", _below_min))
