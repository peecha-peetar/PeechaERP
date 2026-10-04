"""عملیاتِ انبار -- R247: برنامهٔ شمارشِ دوره‌ای و وظایفِ جانمایی/برداشت (WMS سبک).

- برنامهٔ شمارش فقط «سررسید» را حساب می‌کند؛ خودِ شمارش همان انبارگردانیِ موجود (stock_count) است.
- وظیفهٔ جانمایی زمان و اپراتور را ثبت می‌کند و جابه‌جاییِ محل را با سندِ انتقالِ معمولیِ سیستم
  (inventory_documents: انبارِ مبدا = مقصد، محلِ متفاوت) انجام می‌دهد؛ منطقِ انبار تغییری نمی‌کند.
- وظیفهٔ برداشت فقط زمان، اپراتور و مقدارِ برداشته را ثبت می‌کند؛ خروجِ واقعی همچنان با حواله است.
"""

from __future__ import annotations

import datetime
import decimal
from dataclasses import dataclass
from types import SimpleNamespace

from sqlalchemy import func, select

from peecha.db.base import new_session
from peecha.db.models.inventory import (
    BinLocation, CycleCountLine, CycleCountPlan, CycleCountSession, StockBalance, StockDocument, StockDocumentLine,
    StockLedger, WarehouseTask,
)

_ZERO = decimal.Decimal(0)
TASK_TYPES = {"PUTAWAY": "جانمایی", "PICK": "برداشت"}
TASK_STATUSES = {"OPEN": "باز", "IN_PROGRESS": "در حالِ انجام", "DONE": "انجام‌شده", "CANCELLED": "لغوشده"}
_INBOUND = ("RECEIPT", "RETURN_IN", "CONSIGNMENT_IN")
_OUTBOUND = ("ISSUE", "TRANSFER", "RETURN_OUT", "CONSIGN_RETURN")


# =====================================================================
# برنامهٔ شمارشِ دوره‌ای
# =====================================================================
@dataclass
class PlanFields:
    code: str
    name: str
    warehouse_id: int
    frequency_days: int
    item_id: int | None = None
    category_id: int | None = None
    abc_class: str | None = None
    is_active: bool = True
    notes: str | None = None


def list_plans(company_id: int, active_only: bool = False) -> list[CycleCountPlan]:
    with new_session() as session:
        rows = list(session.scalars(select(CycleCountPlan).where(CycleCountPlan.company_id == company_id).order_by(CycleCountPlan.code)))
    return [p for p in rows if p.is_active or not active_only]


def save_plan(company_id: int, fields: PlanFields, plan_id: int | None = None) -> int:
    code, name = (fields.code or "").strip().upper(), (fields.name or "").strip()
    if not code or not name:
        raise ValueError("کد و نامِ برنامهٔ شمارش الزامی است.")
    if not fields.frequency_days or fields.frequency_days <= 0:
        raise ValueError("تواترِ شمارش (روز) باید بزرگ‌تر از صفر باشد.")
    if fields.abc_class not in (None, "A", "B", "C"):
        raise ValueError("کلاسِ ABC نامعتبر است.")
    if sum(x is not None for x in (fields.item_id, fields.category_id, fields.abc_class)) > 1:
        raise ValueError("دامنهٔ برنامه فقط یکی از «کالا»، «گروه» یا «کلاسِ ABC» است (یا هیچ‌کدام = همهٔ کالاها).")
    with new_session() as session:
        clash = session.scalar(select(CycleCountPlan).where(CycleCountPlan.company_id == company_id, CycleCountPlan.code == code))
        if clash is not None and clash.plan_id != plan_id:
            raise ValueError("این کدِ برنامه قبلاً تعریف شده است.")
        row = session.get(CycleCountPlan, plan_id) if plan_id else CycleCountPlan(company_id=company_id)
        if row is None or row.company_id != company_id:
            raise ValueError("برنامهٔ شمارش نامعتبر است.")
        for name_ in ("warehouse_id", "frequency_days", "item_id", "category_id", "abc_class", "is_active"):
            setattr(row, name_, getattr(fields, name_))
        row.code, row.name, row.notes = code, name, (fields.notes or None)
        session.add(row)
        session.commit()
        return row.plan_id


def delete_plan(company_id: int, plan_id: int) -> None:
    with new_session() as session:
        row = session.get(CycleCountPlan, plan_id)
        if row is None or row.company_id != company_id:
            raise ValueError("برنامهٔ شمارش نامعتبر است.")
        session.delete(row)
        session.commit()


def last_counts(company_id: int) -> dict[tuple[int, int], datetime.date]:
    """آخرین تاریخِ شمارشِ هر (کالا، انبار) از انبارگردانی‌ها."""
    with new_session() as session:
        rows = session.execute(
            # counted_at همیشه پر نمی‌شود (record_count آن را نمی‌نویسد)؛ زمانِ جلسهٔ شمارش جایگزین است
            select(CycleCountLine.item_id, CycleCountSession.warehouse_id,
                   func.max(func.coalesce(CycleCountLine.counted_at, CycleCountSession.snapshot_at, CycleCountSession.created_at)))
            .join(CycleCountSession, CycleCountSession.session_id == CycleCountLine.session_id)
            .where(CycleCountSession.company_id == company_id, CycleCountLine.counted_quantity_base.is_not(None))
            .group_by(CycleCountLine.item_id, CycleCountSession.warehouse_id)).all()
    return {(i, w): d.date() for i, w, d in rows if d}


def due_counts(company_id: int, as_of: datetime.date | None = None, warehouse_id: int | None = None) -> list[SimpleNamespace]:
    """اقلامِ هر برنامهٔ فعال که شمارشِ بعدی‌شان رسیده: هرگز شمرده نشده یا آخرین شمارش + تواتر ≤ تاریخ."""
    from peecha.services import inventory_catalog as catalog_service
    from peecha.services import purchase_reports as base
    from peecha.services import warehouse_reports as wr

    as_of = as_of or datetime.date.today()
    plans = [p for p in list_plans(company_id, active_only=True) if warehouse_id is None or p.warehouse_id == warehouse_id]
    if not plans:
        return []
    items = {i.item_id: i for i in catalog_service.list_items(company_id, transactable_only=True)
             if i.is_stock_tracked and i.item_kind_code != "SERVICE"}
    with new_session() as session:
        stocked = {(i, w) for i, w, q in session.execute(
            select(StockBalance.item_id, StockBalance.warehouse_id, func.sum(StockBalance.quantity_on_hand))
            .where(StockBalance.company_id == company_id)
            .group_by(StockBalance.item_id, StockBalance.warehouse_id)).all() if q}
    last = last_counts(company_id)
    abc_cache: dict[int, dict[int, str]] = {}
    out = []
    for p in plans:
        if p.item_id is not None:
            scope = [p.item_id]
        elif p.category_id is not None:
            scope = [i for i, it in items.items() if it.category_id == p.category_id]
        elif p.abc_class is not None:
            if p.warehouse_id not in abc_cache:
                f = base.PurchaseFilters(as_of - datetime.timedelta(days=365), as_of, warehouse_id=p.warehouse_id, side="INVENTORY")
                abc_cache[p.warehouse_id] = {row[0]: row[-1] for row in wr.abc_classes(company_id, f)}
            scope = [i for i, cls in abc_cache[p.warehouse_id].items() if cls == p.abc_class]
        else:
            scope = list(items)
        for item_id in scope:
            if item_id not in items or ((item_id, p.warehouse_id) not in stocked and (item_id, p.warehouse_id) not in last):
                continue
            prev = last.get((item_id, p.warehouse_id))
            due = prev + datetime.timedelta(days=p.frequency_days) if prev else None
            if due is None or due <= as_of:
                out.append(SimpleNamespace(plan=p, item_id=item_id, warehouse_id=p.warehouse_id, last_count=prev, due_date=due,
                                           overdue_days=(as_of - due).days if due else None))
    return out


# =====================================================================
# وظایفِ جانمایی و برداشت
# =====================================================================
def _default_bin(session, warehouse_id: int) -> int | None:
    from peecha.services.inventory_locations import DEFAULT_BIN_CODE

    bin_id = session.scalar(select(BinLocation.bin_location_id).where(
        BinLocation.warehouse_id == warehouse_id, BinLocation.code == DEFAULT_BIN_CODE))
    return bin_id or session.scalar(select(BinLocation.bin_location_id).where(BinLocation.warehouse_id == warehouse_id)
                                    .order_by(BinLocation.bin_location_id))


def putaway_sources(company_id: int, days: int = 60) -> list[SimpleNamespace]:
    """رسیدهایِ ثبت‌شدهٔ اخیر که هنوز برایِ همهٔ ردیف‌هایشان وظیفهٔ جانمایی ندارند."""
    since = datetime.date.today() - datetime.timedelta(days=days)
    with new_session() as session:
        docs = list(session.scalars(select(StockDocument).where(
            StockDocument.company_id == company_id, StockDocument.document_type_code.in_(_INBOUND),
            StockDocument.status_code == "POSTED", StockDocument.document_date >= since).order_by(StockDocument.document_date.desc())))
        tasked = set(session.scalars(select(WarehouseTask.source_stock_line_id).where(
            WarehouseTask.company_id == company_id, WarehouseTask.task_type_code == "PUTAWAY",
            WarehouseTask.status_code != "CANCELLED", WarehouseTask.source_stock_line_id.is_not(None))))
        lines = {}
        for ln in session.scalars(select(StockDocumentLine).where(
                StockDocumentLine.stock_document_id.in_([d.stock_document_id for d in docs] or [-1]))):
            lines.setdefault(ln.stock_document_id, []).append(ln.line_id)
    return [SimpleNamespace(key=("STOCK", d.stock_document_id), doc=d, open_lines=len(set(lines.get(d.stock_document_id, [])) - tasked))
            for d in docs if set(lines.get(d.stock_document_id, [])) - tasked]


def pick_sources(company_id: int) -> list[SimpleNamespace]:
    """حواله/انتقال‌هایِ ثبت‌نشده و سفارش‌هایِ فروش/امانیِ منتظرِ حوالهٔ انبار."""
    from peecha.services import commercial_documents as documents_service

    out = []
    with new_session() as session:
        for d in session.scalars(select(StockDocument).where(
                StockDocument.company_id == company_id, StockDocument.document_type_code.in_(_OUTBOUND),
                StockDocument.status_code.in_(("DRAFT", "CONFIRMED"))).order_by(StockDocument.document_date)):
            out.append(SimpleNamespace(key=("STOCK", d.stock_document_id), doc=d, open_lines=None))
    for doc in documents_service.list_purchase_order_goods_receipt_queue(company_id):
        if doc.document_type_code in ("SALES_ORDER", "CONSIGNMENT_OUT") and doc.warehouse_approved_at is None:
            out.append(SimpleNamespace(key=("COMMERCIAL", doc.document_id), doc=doc, open_lines=None))
    return out


def generate_tasks(company_id: int, task_type: str, source: tuple[str, int], user_id: int) -> list[int]:
    """وظیفه برایِ ردیف‌هایِ یک سند (تکراری ساخته نمی‌شود)."""
    from peecha.services import commercial_documents as documents_service

    if task_type not in TASK_TYPES:
        raise ValueError("نوعِ وظیفه نامعتبر است.")
    kind, doc_id = source
    created = []
    with new_session() as session:
        existing_stock = set(session.scalars(select(WarehouseTask.source_stock_line_id).where(
            WarehouseTask.task_type_code == task_type, WarehouseTask.status_code != "CANCELLED",
            WarehouseTask.source_stock_line_id.is_not(None))))
        existing_comm = set(session.scalars(select(WarehouseTask.source_commercial_line_id).where(
            WarehouseTask.task_type_code == task_type, WarehouseTask.status_code != "CANCELLED",
            WarehouseTask.source_commercial_line_id.is_not(None))))
        if kind == "STOCK":
            doc = session.get(StockDocument, doc_id)
            if doc is None or doc.company_id != company_id:
                raise ValueError("سندِ انبار نامعتبر است.")
            if task_type == "PUTAWAY" and (doc.document_type_code not in _INBOUND or doc.status_code != "POSTED"):
                raise ValueError("جانمایی فقط برایِ رسیدِ ثبت‌شده ساخته می‌شود.")
            if task_type == "PICK" and (doc.document_type_code not in _OUTBOUND or doc.status_code not in ("DRAFT", "CONFIRMED")):
                raise ValueError("برداشت فقط برایِ حواله/انتقالِ ثبت‌نشده ساخته می‌شود.")
            warehouse_id = doc.destination_warehouse_id if task_type == "PUTAWAY" else doc.source_warehouse_id
            lines = list(session.scalars(select(StockDocumentLine).where(StockDocumentLine.stock_document_id == doc_id)
                                         .order_by(StockDocumentLine.line_no)))
            for ln in lines:
                if ln.line_id in existing_stock:
                    continue
                if task_type == "PUTAWAY":
                    from_bin = session.scalar(select(StockLedger.bin_location_id).where(
                        StockLedger.stock_document_line_id == ln.line_id, StockLedger.movement_direction == "IN"))
                else:
                    from_bin = ln.bin_location_id
                task = WarehouseTask(company_id=company_id, warehouse_id=warehouse_id, task_type_code=task_type,
                                     source_stock_document_id=doc_id, source_stock_line_id=ln.line_id, item_id=ln.item_id,
                                     quantity_base=ln.quantity_base, from_bin_location_id=from_bin or _default_bin(session, warehouse_id),
                                     created_by_user_id=user_id)
                session.add(task)
                session.flush()
                created.append(task.task_id)
        elif kind == "COMMERCIAL":
            if task_type != "PICK":
                raise ValueError("از سندِ بازرگانی فقط وظیفهٔ برداشت ساخته می‌شود.")
            doc, lines = documents_service.get_document(doc_id, company_id)
            for ln in lines:
                if ln.line_id in existing_comm or ln.item_id is None:
                    continue
                warehouse_id = ln.warehouse_id or doc.warehouse_id
                if warehouse_id is None:
                    continue
                task = WarehouseTask(company_id=company_id, warehouse_id=warehouse_id, task_type_code="PICK",
                                     source_commercial_document_id=doc_id, source_commercial_line_id=ln.line_id, item_id=ln.item_id,
                                     quantity_base=ln.quantity_base, from_bin_location_id=_default_bin(session, warehouse_id),
                                     created_by_user_id=user_id)
                session.add(task)
                session.flush()
                created.append(task.task_id)
        else:
            raise ValueError("منبعِ وظیفه نامعتبر است.")
        session.commit()
    return created


def list_tasks(company_id: int, task_type: str | None = None, status: str | None = None,
               warehouse_id: int | None = None) -> list[WarehouseTask]:
    with new_session() as session:
        q = select(WarehouseTask).where(WarehouseTask.company_id == company_id)
        if task_type:
            q = q.where(WarehouseTask.task_type_code == task_type)
        if status:
            q = q.where(WarehouseTask.status_code == status)
        if warehouse_id:
            q = q.where(WarehouseTask.warehouse_id == warehouse_id)
        return list(session.scalars(q.order_by(WarehouseTask.task_id.desc())))


def _task(session, task_id: int, company_id: int) -> WarehouseTask:
    task = session.get(WarehouseTask, task_id)
    if task is None or task.company_id != company_id:
        raise ValueError("وظیفه نامعتبر است.")
    return task


def start_task(task_id: int, company_id: int, user_id: int) -> None:
    with new_session() as session:
        task = _task(session, task_id, company_id)
        if task.status_code != "OPEN":
            raise ValueError("فقط وظیفهٔ باز شروع می‌شود.")
        task.status_code, task.started_at = "IN_PROGRESS", datetime.datetime.now()
        task.assigned_user_id = task.assigned_user_id or user_id
        session.commit()


def cancel_task(task_id: int, company_id: int) -> None:
    with new_session() as session:
        task = _task(session, task_id, company_id)
        if task.status_code == "DONE":
            raise ValueError("وظیفهٔ انجام‌شده لغو نمی‌شود.")
        task.status_code = "CANCELLED"
        session.commit()


def complete_putaway(task_id: int, company_id: int, user_id: int, to_bin_location_id: int) -> int | None:
    """جانمایی: اگر محلِ مقصد با محلِ فعلی فرق دارد، با سندِ انتقالِ عادیِ سیستم جابه‌جا می‌شود."""
    from peecha.services import inventory_documents as inv_documents_service

    with new_session() as session:
        task = _task(session, task_id, company_id)
        if task.task_type_code != "PUTAWAY" or task.status_code not in ("OPEN", "IN_PROGRESS"):
            raise ValueError("این وظیفهٔ جانماییِ باز نیست.")
        bin_ok = session.scalar(select(BinLocation.warehouse_id).where(BinLocation.bin_location_id == to_bin_location_id))
        if bin_ok != task.warehouse_id:
            raise ValueError("محلِ مقصد باید در همان انبار باشد.")
        target = session.get(BinLocation, to_bin_location_id)  # R248: فقط محلِ فعال و مجاز برایِ جانمایی
        if not target.is_active or target.status_code != "ACTIVE" or target.is_damaged or not target.allow_putaway:
            raise ValueError("محلِ مقصد فعال نیست یا ورودِ کالا به آن مجاز نیست.")
        warehouse_id, item_id, qty, from_bin = task.warehouse_id, task.item_id, task.quantity_base, task.from_bin_location_id
        uom_id = session.scalar(select(StockDocumentLine.uom_id).where(StockDocumentLine.line_id == task.source_stock_line_id))
    doc_id = None
    if to_bin_location_id != from_bin:
        from peecha.db.models.inventory import Item

        with new_session() as session:
            base_uom = session.scalar(select(Item.base_uom_id).where(Item.item_id == item_id))
        doc_id = inv_documents_service.create_stock_document(
            company_id, user_id, "TRANSFER", datetime.date.today(),
            inv_documents_service.DocumentHeaderFields(source_warehouse_id=warehouse_id, destination_warehouse_id=warehouse_id,
                                                       description=f"جانماییِ وظیفهٔ {task_id}"))
        inv_documents_service.add_line(doc_id, company_id, inv_documents_service.LineFields(
            item_id=item_id, uom_id=base_uom or uom_id, quantity=qty, quantity_base=qty, conversion_factor=decimal.Decimal(1),
            bin_location_id=from_bin, destination_bin_location_id=to_bin_location_id, description=f"جانماییِ وظیفهٔ {task_id}"))
        inv_documents_service.confirm_stock_document(doc_id, company_id)
        inv_documents_service.post_stock_document(doc_id, company_id, user_id)
    with new_session() as session:
        task = _task(session, task_id, company_id)
        now = datetime.datetime.now()
        task.status_code, task.completed_at, task.completed_by_user_id = "DONE", now, user_id
        task.started_at = task.started_at or now
        task.to_bin_location_id, task.done_quantity_base, task.resulting_stock_document_id = to_bin_location_id, qty, doc_id
        session.commit()
    return doc_id


def complete_pick(task_id: int, company_id: int, user_id: int, picked_quantity: decimal.Decimal) -> None:
    picked_quantity = decimal.Decimal(picked_quantity)
    if picked_quantity < 0:
        raise ValueError("مقدارِ برداشته نمی‌تواند منفی باشد.")
    with new_session() as session:
        task = _task(session, task_id, company_id)
        if task.task_type_code != "PICK" or task.status_code not in ("OPEN", "IN_PROGRESS"):
            raise ValueError("این وظیفهٔ برداشتِ باز نیست.")
        now = datetime.datetime.now()
        task.status_code, task.completed_at, task.completed_by_user_id = "DONE", now, user_id
        task.started_at = task.started_at or now
        task.done_quantity_base = picked_quantity
        session.commit()
