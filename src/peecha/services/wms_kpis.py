"""شاخص‌های عملیات انبار (WMS) — R251.

فقط خواندنی: از وظایف انبار، موج‌ها، رزروها، شمارش‌های محل و همان اشغال محل (موجودی سیستم) محاسبه می‌شود.
"""

from __future__ import annotations

import datetime
import decimal
from collections import defaultdict
from types import SimpleNamespace

from sqlalchemy import and_, or_, select

from peecha.db.base import new_session
from peecha.db.models.inventory import CycleCountLine, CycleCountSession, PickWave, WarehouseTask
from peecha.services import warehouse_locations as wl
from peecha.services import warehouse_operations as ops

_ZERO = decimal.Decimal(0)


def _naive(value: datetime.datetime) -> datetime.datetime:
    return value.astimezone().replace(tzinfo=None) if value.tzinfo is not None else value


def _hours(start, end) -> float | None:
    if start is None or end is None:
        return None
    return max((_naive(end) - _naive(start)).total_seconds(), 0) / 3600


def dashboard(company_id: int, date_from: datetime.date, date_to: datetime.date, warehouse_id: int | None = None) -> SimpleNamespace:
    """kpis: [(کد، عنوان، مقدار، واحد)]، operators: بهره‌وری هر اپراتور، by_type: وظایف به تفکیک نوع."""
    start = datetime.datetime.combine(date_from, datetime.time.min)
    end = datetime.datetime.combine(date_to, datetime.time.max)
    with new_session() as session:
        # R308: فقط وظایف انجام‌شدهٔ همین بازه و وظایف باز (نه همهٔ تاریخچه)
        q = select(WarehouseTask).where(WarehouseTask.company_id == company_id, WarehouseTask.created_at <= end, or_(
            and_(WarehouseTask.status_code == "DONE", WarehouseTask.completed_at.between(start, end)),
            WarehouseTask.status_code.in_(("OPEN", "IN_PROGRESS"))))
        if warehouse_id is not None:
            q = q.where(WarehouseTask.warehouse_id == warehouse_id)
        tasks = list(session.scalars(q))
        wq = select(PickWave).where(PickWave.company_id == company_id, PickWave.created_at.between(start, end))
        if warehouse_id is not None:
            wq = wq.where(PickWave.warehouse_id == warehouse_id)
        waves = list(session.scalars(wq))
        cq = (select(CycleCountLine).join(CycleCountSession, CycleCountSession.session_id == CycleCountLine.session_id)
              .where(CycleCountSession.company_id == company_id, CycleCountSession.scope_type_code == "BY_BIN",
                     CycleCountLine.counted_at.between(start, end)))
        if warehouse_id is not None:
            cq = cq.where(CycleCountSession.warehouse_id == warehouse_id)
        counted = list(session.scalars(cq))
    done = [t for t in tasks if t.status_code == "DONE" and t.completed_at and start <= t.completed_at <= end]
    open_tasks = [t for t in tasks if t.status_code in ("OPEN", "IN_PROGRESS")]
    by_type = {}
    for code, label in ops.TASK_TYPES.items():
        d = [t for t in done if t.task_type_code == code]
        durations = [h for h in (_hours(t.started_at, t.completed_at) for t in d) if h is not None]
        by_type[code] = SimpleNamespace(label=label, done=len(d), open=sum(1 for t in open_tasks if t.task_type_code == code),
                                        avg_minutes=round(sum(durations) / len(durations) * 60, 1) if durations else None)
    picks = [t for t in done if t.task_type_code == "PICK"]
    exact = sum(1 for t in picks if t.done_quantity_base == t.quantity_base)
    operators = defaultdict(lambda: SimpleNamespace(tasks=0, hours=0.0, picks=0, exact=0))
    for t in done:
        o = operators[t.completed_by_user_id]
        o.tasks += 1
        o.hours += _hours(t.started_at, t.completed_at) or 0
        if t.task_type_code == "PICK":
            o.picks += 1
            o.exact += t.done_quantity_base == t.quantity_base
    # استفاده از محل‌ها: محل‌هایِ برگِ فعال (Bin/طبقه/قفسهٔ بی‌فرزند) در انبارهایِ دارایِ نقشه
    from peecha.services import inventory_locations as locations_service

    leaves = occupied = full = 0
    occ_values = []
    for w in locations_service.list_warehouses(company_id):
        if warehouse_id is not None and w.warehouse_id != warehouse_id:
            continue
        nodes = [n for n in wl.tree(company_id, w.warehouse_id) if n.level is not None]
        if not nodes:
            continue
        occ = wl.occupancy(company_id, w.warehouse_id, nodes)
        parents = {n.parent_id for n in nodes}
        for n in nodes:
            if n.location_id in parents or not n.is_active:
                continue
            leaves += 1
            o = occ.get(n.location_id)
            if o and o.quantity:
                occupied += 1
            if o and o.percent is not None:
                occ_values.append(float(o.percent))
                full += o.percent >= 90
    counted_lines = [c for c in counted if c.counted_quantity_base is not None]
    accurate = sum(1 for c in counted_lines if c.counted_quantity_base == c.expected_quantity_base)
    reserved = ops.reserved_by_bin(company_id, warehouse_id)
    needs = ops.replenishment_needs(company_id, warehouse_id)
    pct = lambda a, b: round(a * 100 / b, 1) if b else None  # noqa: E731
    kpis = [
        ("TASKS_DONE", "وظایف انجام‌شده", len(done), "وظیفه"),
        ("TASKS_OPEN", "وظایف باز", len(open_tasks), "وظیفه"),
        ("PICK_ACCURACY", "دقت جمع‌آوری", pct(exact, len(picks)), "٪"),
        ("LOCATION_USE", "محل‌های دارای کالا", pct(occupied, leaves), "٪"),
        ("AVG_OCCUPANCY", "میانگین اشغال محل‌ها", round(sum(occ_values) / len(occ_values), 1) if occ_values else None, "٪"),
        ("FULL_LOCATIONS", "محل‌های پر (≥۹۰٪)", full, "محل"),
        ("WAVES", "جمع‌آوری‌های گروهی", len(waves), "گروه"),
        ("WAVE_DISTANCE", "میانگین مسیر هر جمع‌آوری گروهی",
         round(sum(float(w.path_distance or 0) for w in waves) / len(waves) / wl.UNITS_PER_M, 1) if waves else None, "متر"),
        ("REPLENISH_NEEDS", "محل‌های زیر حداقل", len(needs), "محل"),
        ("RESERVED", "رزرو فعال وظایف", sum(reserved.values(), _ZERO), "واحد"),
        ("COUNT_LINES", "ردیف‌های شمرده‌شده", len(counted_lines), "ردیف"),
        ("COUNT_ACCURACY", "دقت موجودی (شمارش محل)", pct(accurate, len(counted_lines)), "٪"),
    ]
    extra = None
    from peecha.services import stock_controls

    if stock_controls.is_on(company_id, stock_controls.ADVANCED_KPIS):
        extra = _advanced(company_id, start, end, warehouse_id, done, picks)
        kpis += extra.kpis
    return SimpleNamespace(kpis=kpis, by_type=by_type, operators=dict(operators),
                           short_reasons=extra.short_reasons if extra else [])


def _advanced(company_id: int, start: datetime.datetime, end: datetime.datetime, warehouse_id: int | None, done: list,
              picks: list) -> SimpleNamespace:
    """R308 (کلید «شاخص‌های تکمیلی»): فقط از داده‌های ثبت‌شده — ردپای عملیات، وظایف، رسیدها، بازرسی کیفیت و بچ‌ها."""
    from peecha.db.models.audit import ActivityLog
    from peecha.db.models.inventory import QcInspection, StockDocument, StockDocumentLine
    from peecha.services import expiry_watch, quality_control

    pct = lambda a, b: round(a * 100 / b, 1) if b else None  # noqa: E731
    done_ids = [t.task_id for t in done]
    with new_session() as session:
        scanned = set(session.scalars(select(ActivityLog.entity_id).where(
            ActivityLog.entity_type == "WarehouseTask", ActivityLog.action == "COMPLETE",
            ActivityLog.entity_id.in_(done_ids or [-1]), ActivityLog.changes["scanned"].astext == "True")))
        putaways = [t for t in done if t.task_type_code == "PUTAWAY" and t.source_stock_document_id]
        posted = dict(session.execute(select(StockDocument.stock_document_id, StockDocument.posted_at).where(
            StockDocument.stock_document_id.in_({t.source_stock_document_id for t in putaways} or {-1}))).all())
        iq = (select(QcInspection, StockDocumentLine.quantity_base, StockDocument.posted_at)
              .join(StockDocumentLine, StockDocumentLine.line_id == QcInspection.stock_document_line_id)
              .join(StockDocument, StockDocument.stock_document_id == StockDocumentLine.stock_document_id)
              .where(QcInspection.company_id == company_id, QcInspection.status_code == "APPROVED",
                     QcInspection.inspected_at.between(start, end)))
        if warehouse_id is not None:
            iq = iq.where(StockDocument.destination_warehouse_id == warehouse_id)
        inspections = session.execute(iq).all()
    short = [t for t in picks if t.done_quantity_base is not None and t.done_quantity_base < t.quantity_base]
    reasons: dict[str, int] = defaultdict(int)
    for t in short:
        note = (t.notes or "").split("کسری برداشت:", 1)
        reasons[note[1].strip() if len(note) == 2 and note[1].strip() else "بی‌علت"] += 1
    dock = [_hours(posted.get(t.source_stock_document_id), t.completed_at) for t in putaways]
    dock = [h for h in dock if h is not None]
    # R311: مقدار تصمیم‌گرفته (پذیرفته + ردشده)؛ «در انتظار» هنوز بازرسی نهایی نشده
    inspected = sum((decimal.Decimal(i.accepted_quantity if i.accepted_quantity is not None
                                     else decimal.Decimal(q) - decimal.Decimal(i.rejected_quantity or 0))
                     + decimal.Decimal(i.rejected_quantity or 0) for i, q, _p in inspections), _ZERO)
    rejected = sum((decimal.Decimal(i.rejected_quantity or 0) for i, _q, _p in inspections), _ZERO)
    waits = [h for h in (_hours(p, i.inspected_at) for i, _q, p in inspections) if h is not None]
    pending_qc = quality_control.pending_by_warehouse(company_id)
    lots = expiry_watch.near_expiry(company_id, warehouse_id)
    kpis = [
        ("SCAN_RATE", "وظایف تاییدشده با اسکن", pct(len(scanned), len(done)), "٪"),
        ("SHORT_PICKS", "جمع‌آوری‌های کسری‌دار", len(short), "جمع‌آوری"),
        ("SHORT_RATE", "سهم جمع‌آوری کسری‌دار", pct(len(short), len(picks)), "٪"),
        ("DOCK_TO_STOCK", "میانگین رسید تا چیدن در قفسه", round(sum(dock) / len(dock), 1) if dock else None, "ساعت"),
        ("QC_INSPECTED", "بازرسی‌های کیفیت", len(inspections), "ردیف"),
        ("QC_REJECT_RATE", "سهم مقدار ردشده در کنترل کیفیت", pct(rejected, inspected), "٪"),
        ("QC_WAIT", "میانگین انتظار تا کنترل کیفیت", round(sum(waits) / len(waits), 1) if waits else None, "ساعت"),
        ("QC_PENDING", "ردیف‌های منتظر کنترل کیفیت",
         pending_qc.get(warehouse_id, 0) if warehouse_id is not None else sum(pending_qc.values()), "ردیف"),
        ("EXPIRED_LOTS", "بچ‌های منقضی در انبار", sum(1 for r in lots if r.expired), "بچ"),
        ("NEAR_EXPIRY_LOTS", "بچ‌های نزدیک به انقضا", sum(1 for r in lots if not r.expired), "بچ"),
    ]
    return SimpleNamespace(kpis=kpis, short_reasons=sorted(reasons.items(), key=lambda kv: (-kv[1], kv[0])))
