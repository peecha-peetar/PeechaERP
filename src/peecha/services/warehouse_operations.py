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
    BinLocation, CycleCountLine, CycleCountPlan, CycleCountSession, LocationReplenishmentRule, PickWave, StockBalance, StockDocument,
    StockDocumentLine, StockLedger, StockReservation, WarehouseTask,
)

_ZERO = decimal.Decimal(0)
TASK_TYPES = {"PUTAWAY": "جانمایی", "PICK": "برداشت", "REPLENISH": "تأمینِ مجدد"}
_RESERVATION_SOURCE = {"PICK": "WMS_PICK_TASK", "REPLENISH": "WMS_REPLENISH_TASK"}
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
    from peecha.services.inventory_locations import get_default_bin_location

    row = get_default_bin_location(warehouse_id)
    return row.bin_location_id if row else None


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

    if task_type not in ("PUTAWAY", "PICK"):
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
                    from_bin = ln.bin_location_id or _best_pick_bin(session, warehouse_id, ln.item_id)
                task = WarehouseTask(company_id=company_id, warehouse_id=warehouse_id, task_type_code=task_type,
                                     source_stock_document_id=doc_id, source_stock_line_id=ln.line_id, item_id=ln.item_id,
                                     quantity_base=ln.quantity_base, from_bin_location_id=from_bin or _default_bin(session, warehouse_id),
                                     created_by_user_id=user_id)
                session.add(task)
                session.flush()
                _reserve(session, task)
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
                                     quantity_base=ln.quantity_base,
                                     from_bin_location_id=_best_pick_bin(session, warehouse_id, ln.item_id) or _default_bin(session, warehouse_id),
                                     created_by_user_id=user_id)
                session.add(task)
                session.flush()
                _reserve(session, task)
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
        _release(session, task, "CANCELLED")
        _close_wave_if_done(session, task.wave_id)
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
        task_line_id = task.source_stock_line_id
    from peecha.services import warehouse_locations as wl

    issues = wl.compatibility_issues(company_id, item_id, to_bin_location_id)  # R249
    if issues:
        raise ValueError("کالا با محلِ مقصد سازگار نیست: " + "؛ ".join(issues))
    with new_session() as session:
        uom_id = session.scalar(select(StockDocumentLine.uom_id).where(StockDocumentLine.line_id == task_line_id))
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
        _release(session, task, "FULFILLED", picked_quantity)
        warehouse_id, wave_id = task.warehouse_id, task.wave_id
        _close_wave_if_done(session, wave_id)
        session.commit()
    auto_replenish(company_id, user_id, warehouse_id)



# =====================================================================
# R249: رزروِ وظیفه، انتخابِ محلِ برداشت و تأمینِ مجددِ جبههٔ برداشت
# =====================================================================
def _reserve(session, task: WarehouseTask) -> None:
    """رزروِ قطعیِ مقدارِ وظیفه در همان inv.stock_reservations (ستونِ رزروِ موتورِ انبار دست نمی‌خورد)."""
    if task.task_type_code not in _RESERVATION_SOURCE or not task.quantity_base or task.quantity_base <= 0:
        return
    res = StockReservation(company_id=task.company_id, item_id=task.item_id, warehouse_id=task.warehouse_id,
                           bin_location_id=task.from_bin_location_id, quantity=task.quantity_base,
                           source_type_code=_RESERVATION_SOURCE[task.task_type_code], source_record_id=task.task_id)
    session.add(res)
    _hold(session, res, 1)


def _hold(session, res: StockReservation, sign: int) -> None:
    """R252: رزروِ فعال در ستونِ رزروِ مانده هم نگه داشته می‌شود تا «موجودیِ آزاد» (کاتالوگ/فروشگاه/بارگیری) کم شود.
    موتورِ انبار این ستون را بررسی نمی‌کند، پس ثبتِ حواله و فروش هرگز به‌خاطرِ آن رد نمی‌شود."""
    if res.bin_location_id is None:
        return
    bal = session.scalar(select(StockBalance).where(
        StockBalance.item_id == res.item_id, StockBalance.warehouse_id == res.warehouse_id,
        StockBalance.bin_location_id == res.bin_location_id, StockBalance.batch_id.is_(None)))
    if bal is not None:
        bal.quantity_reserved = max(_ZERO, (bal.quantity_reserved or _ZERO) + sign * res.quantity)


def _release(session, task: WarehouseTask, status: str, fulfilled: decimal.Decimal | None = None) -> None:
    source = _RESERVATION_SOURCE.get(task.task_type_code)
    if source is None:
        return
    for res in session.scalars(select(StockReservation).where(
            StockReservation.source_type_code == source, StockReservation.source_record_id == task.task_id,
            StockReservation.status_code == "ACTIVE")):
        res.status_code, res.released_at = status, datetime.datetime.now()
        _hold(session, res, -1)
        if fulfilled is not None:
            res.fulfilled_quantity_base = min(decimal.Decimal(fulfilled), res.quantity)


def task_reservations(company_id: int, task_id: int) -> list[StockReservation]:
    with new_session() as session:
        task = _task(session, task_id, company_id)
        source = _RESERVATION_SOURCE.get(task.task_type_code)
        return list(session.scalars(select(StockReservation).where(
            StockReservation.source_type_code == source, StockReservation.source_record_id == task_id)))


def reserved_by_bin(company_id: int, warehouse_id: int | None = None) -> dict[tuple[int, int], decimal.Decimal]:
    """(محل، کالا) → مقدارِ رزروِ فعالِ وظایفِ انبار."""
    with new_session() as session:
        q = (select(StockReservation.bin_location_id, StockReservation.item_id, func.sum(StockReservation.remaining_quantity_base))
             .where(StockReservation.company_id == company_id, StockReservation.status_code == "ACTIVE",
                    StockReservation.source_type_code.in_(tuple(_RESERVATION_SOURCE.values()))))
        if warehouse_id is not None:
            q = q.where(StockReservation.warehouse_id == warehouse_id)
        return {(b, i): q_ or _ZERO for b, i, q_ in session.execute(q.group_by(StockReservation.bin_location_id, StockReservation.item_id))}


def _best_pick_bin(session, warehouse_id: int, item_id: int) -> int | None:
    """محلِ برداشت: محلِ قابلِ‌برداشتِ دارایِ موجودی با اولویتِ جبههٔ برداشت (نوعِ خودِ محل یا والدها)، سپس بیشترین موجودی."""
    from peecha.db.models.inventory import Warehouse
    from peecha.services import warehouse_locations as wl

    rows = session.execute(
        select(StockBalance.bin_location_id, func.sum(StockBalance.quantity_on_hand))
        .where(StockBalance.warehouse_id == warehouse_id, StockBalance.item_id == item_id)
        .group_by(StockBalance.bin_location_id)).all()
    rows = [(b, q) for b, q in rows if (q or 0) > 0]
    if not rows:
        return None
    company_id = session.get(Warehouse, warehouse_id).company_id
    by_id = {n.location_id: n for n in wl.tree(company_id, warehouse_id)}
    ranked = []
    for bin_id, qty in rows:
        node = by_id.get(bin_id)
        if node is None or node.status_code in wl.NO_EXIT_STATUSES or not node.is_pickable:
            continue
        types = {a.location_type_code for a in wl.ancestors(by_id, bin_id)}
        ranked.append((not (types & {"PICK_FACE", "PICKING"}), -qty, bin_id))
    return min(ranked)[2] if ranked else None


@dataclass
class RuleFields:
    bin_location_id: int
    item_id: int
    min_quantity: decimal.Decimal
    max_quantity: decimal.Decimal
    is_active: bool = True


def list_rules(company_id: int, warehouse_id: int | None = None) -> list[LocationReplenishmentRule]:
    with new_session() as session:
        q = select(LocationReplenishmentRule).where(LocationReplenishmentRule.company_id == company_id)
        if warehouse_id is not None:
            q = q.join(BinLocation, BinLocation.bin_location_id == LocationReplenishmentRule.bin_location_id).where(
                BinLocation.warehouse_id == warehouse_id)
        return list(session.scalars(q.order_by(LocationReplenishmentRule.rule_id)))


def save_rule(company_id: int, fields: RuleFields, rule_id: int | None = None) -> int:
    from peecha.db.models.inventory import Item, Warehouse

    if fields.min_quantity is None or fields.max_quantity is None or fields.min_quantity < 0:
        raise ValueError("حداقل باید صفر یا بیشتر باشد.")
    if fields.max_quantity <= fields.min_quantity:
        raise ValueError("حداکثر باید بیشتر از حداقل باشد.")
    with new_session() as session:
        loc = session.get(BinLocation, fields.bin_location_id)
        wh = session.get(Warehouse, loc.warehouse_id) if loc else None
        if wh is None or wh.company_id != company_id:
            raise ValueError("محل نامعتبر است.")
        if not loc.allow_replenishment:
            raise ValueError("تأمینِ مجدد برایِ این محل مجاز نیست.")
        item = session.get(Item, fields.item_id)
        if item is None or item.company_id != company_id:
            raise ValueError("کالا نامعتبر است.")
        dup = session.scalar(select(LocationReplenishmentRule.rule_id).where(
            LocationReplenishmentRule.bin_location_id == fields.bin_location_id, LocationReplenishmentRule.item_id == fields.item_id))
        if dup and dup != rule_id:
            raise ValueError("برایِ این کالا در این محل قبلاً قاعده تعریف شده است.")
        if rule_id is None:
            row = LocationReplenishmentRule(company_id=company_id)
            session.add(row)
        else:
            row = session.get(LocationReplenishmentRule, rule_id)
            if row is None or row.company_id != company_id:
                raise ValueError("قاعده نامعتبر است.")
        row.bin_location_id, row.item_id = fields.bin_location_id, fields.item_id
        row.min_quantity, row.max_quantity, row.is_active = fields.min_quantity, fields.max_quantity, fields.is_active
        session.commit()
        return row.rule_id


def delete_rule(company_id: int, rule_id: int) -> None:
    with new_session() as session:
        row = session.get(LocationReplenishmentRule, rule_id)
        if row is None or row.company_id != company_id:
            raise ValueError("قاعده نامعتبر است.")
        if session.scalar(select(func.count()).select_from(WarehouseTask).where(WarehouseTask.replenishment_rule_id == rule_id)):
            row.is_active = False  # دارایِ سابقهٔ وظیفه: فقط غیرفعال
        else:
            session.delete(row)
        session.commit()


def replenishment_needs(company_id: int, warehouse_id: int | None = None) -> list[SimpleNamespace]:
    """قاعده‌هایی که موجودی + وظایفِ بازِ تأمین به حداقل یا کمتر رسیده؛ مقدار = تا حداکثر، با منابعِ پیشنهادی
    (محل‌هایِ دیگرِ همان انبار با موجودیِ آزاد، اولویتِ ذخیره/حجیم)."""
    from peecha.services import warehouse_locations as wl

    rules = [r for r in list_rules(company_id, warehouse_id) if r.is_active]
    if not rules:
        return []
    with new_session() as session:
        loc_wh = dict(session.execute(select(BinLocation.bin_location_id, BinLocation.warehouse_id).where(
            BinLocation.bin_location_id.in_([r.bin_location_id for r in rules]))).all())
        open_qty = dict(session.execute(select(WarehouseTask.replenishment_rule_id, func.sum(WarehouseTask.quantity_base)).where(
            WarehouseTask.task_type_code == "REPLENISH", WarehouseTask.status_code.in_(("OPEN", "IN_PROGRESS")),
            WarehouseTask.replenishment_rule_id.in_([r.rule_id for r in rules])).group_by(WarehouseTask.replenishment_rule_id)).all())
    trees: dict[int, list] = {}
    stock: dict[int, list] = {}
    reserved: dict[int, dict] = {}
    out = []
    for rule in rules:
        wid = loc_wh[rule.bin_location_id]
        if wid not in trees:
            trees[wid] = wl.tree(company_id, wid)
            stock[wid] = wl._stock_by_bin(company_id, wid)
            reserved[wid] = reserved_by_bin(company_id, wid)
        nodes = trees[wid]
        by_id = {n.location_id: n for n in nodes}
        target = by_id[rule.bin_location_id]
        inside = wl.descendants(nodes, rule.bin_location_id)
        on_hand = sum((q for b, i, q, _r, _v in stock[wid] if i == rule.item_id and b in inside and q), _ZERO)
        pending = open_qty.get(rule.rule_id) or _ZERO
        if on_hand + pending > rule.min_quantity or not wl.is_operable(target):
            continue
        need = rule.max_quantity - on_hand - pending
        sources = []
        for b, i, q, _r, _v in stock[wid]:
            node = by_id.get(b)
            if i != rule.item_id or b in inside or not q or node is None or node.status_code in wl.NO_EXIT_STATUSES:
                continue
            free = q - reserved[wid].get((b, i), _ZERO)
            if free <= 0:
                continue
            types = {a.location_type_code for a in wl.ancestors(by_id, b)}
            rank = 0 if types & {"RESERVE", "BULK"} else (2 if types & {"PICK_FACE", "PICKING"} else 1)
            sources.append(SimpleNamespace(location_id=b, location_code=node.full_code, free=free, rank=rank))
        sources.sort(key=lambda x: (x.rank, -x.free, x.location_code))
        out.append(SimpleNamespace(rule=rule, warehouse_id=wid, location_code=target.full_code, item_id=rule.item_id,
                                   on_hand=on_hand, pending=pending, need=need, sources=sources,
                                   available=sum((x.free for x in sources), _ZERO)))
    return out


def generate_replenishment_tasks(company_id: int, user_id: int, warehouse_id: int | None = None) -> list[int]:
    """وظیفهٔ تأمینِ مجدد برایِ هر نیاز (در صورتِ نیاز از چند منبع)؛ مقدارِ منبع رزرو می‌شود."""
    created = []
    needs = replenishment_needs(company_id, warehouse_id)
    with new_session() as session:
        for need in needs:
            left = need.need
            for src in need.sources:
                if left <= 0:
                    break
                qty = min(left, src.free)
                task = WarehouseTask(company_id=company_id, warehouse_id=need.warehouse_id, task_type_code="REPLENISH",
                                     item_id=need.item_id, quantity_base=qty, from_bin_location_id=src.location_id,
                                     to_bin_location_id=need.rule.bin_location_id, replenishment_rule_id=need.rule.rule_id,
                                     created_by_user_id=user_id)
                session.add(task)
                session.flush()
                _reserve(session, task)
                created.append(task.task_id)
                left -= qty
        session.commit()
    return created


def complete_replenishment(task_id: int, company_id: int, user_id: int, quantity: decimal.Decimal | None = None) -> int:
    """جابه‌جاییِ واقعی با سندِ انتقالِ عادی (همان مسیرِ انتقالِ نقشه با بررسیِ وضعیت/ظرفیت/سازگاری)."""
    from peecha.services import warehouse_locations as wl

    with new_session() as session:
        task = _task(session, task_id, company_id)
        if task.task_type_code != "REPLENISH" or task.status_code not in ("OPEN", "IN_PROGRESS"):
            raise ValueError("این وظیفهٔ تأمینِ مجددِ باز نیست.")
        qty = decimal.Decimal(quantity) if quantity is not None else task.quantity_base
        if qty <= 0 or qty > task.quantity_base:
            raise ValueError("مقدارِ تأمین باید مثبت و حداکثر برابرِ مقدارِ وظیفه باشد.")
        item_id, src, dst = task.item_id, task.from_bin_location_id, task.to_bin_location_id
        _release(session, task, "CANCELLED")  # تا خودِ رزروِ این وظیفه مانعِ انتقال نشود
        session.commit()
    try:
        doc_id = wl.transfer(company_id, user_id, item_id, src, dst, qty)
    except ValueError:
        with new_session() as session:
            task = _task(session, task_id, company_id)
            for res in session.scalars(select(StockReservation).where(
                    StockReservation.source_type_code == "WMS_REPLENISH_TASK", StockReservation.source_record_id == task_id)):
                res.status_code, res.released_at = "ACTIVE", None
                _hold(session, res, 1)
            session.commit()
        raise
    with new_session() as session:
        task = _task(session, task_id, company_id)
        now = datetime.datetime.now()
        task.status_code, task.completed_at, task.completed_by_user_id = "DONE", now, user_id
        task.started_at = task.started_at or now
        task.done_quantity_base, task.resulting_stock_document_id = qty, doc_id
        for res in session.scalars(select(StockReservation).where(
                StockReservation.source_type_code == "WMS_REPLENISH_TASK", StockReservation.source_record_id == task_id)):
            res.status_code, res.fulfilled_quantity_base = "FULFILLED", min(qty, res.quantity)
        session.commit()
    return doc_id



# =====================================================================
# R250: تأمینِ خودکار و برداشتِ موجی
# =====================================================================
def auto_replenish(company_id: int, user_id: int, warehouse_id: int) -> list[int]:
    """پس از هر برداشت: اگر قاعدهٔ فعالی در این انبار به حداقل رسیده، وظیفهٔ تأمین ساخته می‌شود."""
    if not any(r.is_active for r in list_rules(company_id, warehouse_id)):
        return []
    return generate_replenishment_tasks(company_id, user_id, warehouse_id)


def _close_wave_if_done(session, wave_id: int | None) -> None:
    if wave_id is None:
        return
    open_left = session.scalar(select(func.count()).select_from(WarehouseTask).where(
        WarehouseTask.wave_id == wave_id, WarehouseTask.status_code.in_(("OPEN", "IN_PROGRESS"))))
    wave = session.get(PickWave, wave_id)
    if wave is not None and not open_left and wave.status_code == "OPEN":
        wave.status_code, wave.completed_at = "DONE", datetime.datetime.now()


def create_wave(company_id: int, warehouse_id: int, user_id: int, task_ids: list[int] | None = None) -> int:
    """موج از وظایفِ برداشتِ بازِ بی‌موجِ انبار (یا وظایفِ داده‌شده)، به ترتیبِ مسیرِ نزدیک‌ترین همسایه."""
    from peecha.services import warehouse_locations as wl

    with new_session() as session:
        q = select(WarehouseTask).where(
            WarehouseTask.company_id == company_id, WarehouseTask.warehouse_id == warehouse_id, WarehouseTask.task_type_code == "PICK",
            WarehouseTask.status_code.in_(("OPEN", "IN_PROGRESS")), WarehouseTask.wave_id.is_(None))
        if task_ids is not None:
            q = q.where(WarehouseTask.task_id.in_(task_ids))
        tasks = list(session.scalars(q))
        if task_ids is not None and len(tasks) != len(set(task_ids)):
            raise ValueError("بعضی از وظایف برداشتِ بازِ بی‌موجِ همین انبار نیستند.")
        if not tasks:
            raise ValueError("وظیفهٔ برداشتِ بازی برایِ موج نیست.")
        bins = [t.from_bin_location_id for t in tasks if t.from_bin_location_id]
        path = wl.picking_path(company_id, warehouse_id, bins)
        rank = {lid: i for i, lid in enumerate(path.order)}
        count = session.scalar(select(func.count()).select_from(PickWave).where(PickWave.company_id == company_id)) or 0
        wave = PickWave(company_id=company_id, warehouse_id=warehouse_id, wave_code=f"WAVE-{count + 1:05d}",
                        path_distance=decimal.Decimal(str(path.distance)), created_by_user_id=user_id)
        session.add(wave)
        session.flush()
        ordered = sorted(tasks, key=lambda t: (rank.get(t.from_bin_location_id, len(rank)), t.task_id))
        for seq, t in enumerate(ordered, start=1):
            t.wave_id, t.wave_sequence = wave.wave_id, seq
        session.commit()
        return wave.wave_id


def list_waves(company_id: int, open_only: bool = False, warehouse_id: int | None = None) -> list[PickWave]:
    with new_session() as session:
        q = select(PickWave).where(PickWave.company_id == company_id)
        if open_only:
            q = q.where(PickWave.status_code == "OPEN")
        if warehouse_id is not None:
            q = q.where(PickWave.warehouse_id == warehouse_id)
        return list(session.scalars(q.order_by(PickWave.wave_id.desc())))


def wave_tasks(company_id: int, wave_id: int) -> list[WarehouseTask]:
    with new_session() as session:
        wave = session.get(PickWave, wave_id)
        if wave is None or wave.company_id != company_id:
            raise ValueError("موج نامعتبر است.")
        return list(session.scalars(select(WarehouseTask).where(WarehouseTask.wave_id == wave_id)
                                    .order_by(WarehouseTask.wave_sequence)))


def release_wave(company_id: int, wave_id: int) -> None:
    """لغوِ موج: وظایفِ باز از موج خارج می‌شوند (خودِ وظیفه‌ها باقی می‌مانند)."""
    with new_session() as session:
        wave = session.get(PickWave, wave_id)
        if wave is None or wave.company_id != company_id:
            raise ValueError("موج نامعتبر است.")
        if wave.status_code != "OPEN":
            raise ValueError("فقط موجِ باز لغو می‌شود.")
        for t in session.scalars(select(WarehouseTask).where(WarehouseTask.wave_id == wave_id,
                                                            WarehouseTask.status_code.in_(("OPEN", "IN_PROGRESS")))):
            t.wave_id, t.wave_sequence = None, None
        wave.status_code = "CANCELLED"
        session.commit()
