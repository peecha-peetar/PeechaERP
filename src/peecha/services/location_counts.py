"""شمارشِ دوره‌ایِ محل‌محور -- R250.

از همان جدول‌هایِ انبارگردانی (inv.cycle_count_sessions با scope_type_code = 'BY_BIN' و inv.cycle_count_lines
که bin_location_id دارد) استفاده می‌کند؛ موجودیِ دفتری از inv.stock_balance به تفکیکِ محل گرفته می‌شود و اختلاف
با سندِ اصلاحِ عادیِ انبار (ADJUSTMENT) رویِ همان محل ثبت می‌شود.
R251: کالایِ بچ‌دار به تفکیکِ بچ در هر محل شمرده می‌شود (از ستونِ محلِ inv.lot_movements)؛ کالایِ سریال‌دار
همچنان با انبارگردانیِ عادی.
"""

from __future__ import annotations

import datetime
import decimal
from types import SimpleNamespace

from sqlalchemy import func, select

from peecha.db.base import new_session
from peecha.db.models.inventory import Batch, CycleCountLine, CycleCountSession, Item, StockBalance, Warehouse
from peecha.services import warehouse_locations as wl

_ZERO = decimal.Decimal(0)
SCOPE = "BY_BIN"


def _tracked(item) -> bool:
    """فقط سریال‌دار از شمارشِ محل بیرون است؛ بچ‌دار به تفکیکِ بچ شمرده می‌شود."""
    return bool(item.track_serial)


def _session(session, company_id: int, session_id: int) -> CycleCountSession:
    row = session.get(CycleCountSession, session_id)
    if row is None or row.company_id != company_id or row.scope_type_code != SCOPE:
        raise ValueError("شمارشِ محل نامعتبر است.")
    return row


def create_location_count(company_id: int, warehouse_id: int, location_ids: list[int], user_id: int,
                          blind: bool = True) -> int:
    """جلسهٔ شمارش برایِ محل‌ها (و همهٔ زیرمحل‌هایشان)؛ موجودیِ دفتریِ هر (محل، کالا) همین لحظه ثبت می‌شود."""
    if not location_ids:
        raise ValueError("حداقل یک محل برایِ شمارش انتخاب کنید.")
    nodes = wl.tree(company_id, warehouse_id)
    by_id = {n.location_id: n for n in nodes}
    scope: set[int] = set()
    for lid in location_ids:
        if lid not in by_id:
            raise ValueError("محل در این انبار نیست.")
        scope |= wl.descendants(nodes, lid)
    with new_session() as session:
        wh = session.get(Warehouse, warehouse_id)
        if wh is None or wh.company_id != company_id:
            raise ValueError("انبار نامعتبر است.")
        if not wh.allow_cycle_count:
            raise ValueError("انبارگردانی برایِ این انبار مجاز نشده است (تنظیماتِ انبار).")
        open_ids = set()
        for s in session.scalars(select(CycleCountSession).where(
                CycleCountSession.warehouse_id == warehouse_id, CycleCountSession.scope_type_code == SCOPE,
                CycleCountSession.status_code == "COUNTING")):
            open_ids |= set((s.scope_filter or {}).get("bins", []))
        if open_ids & scope:
            raise ValueError("بعضی از این محل‌ها در شمارشِ بازِ دیگری هستند.")
        flags = {i: (tb, ts) for i, tb, ts in session.execute(select(Item.item_id, Item.track_batch, Item.track_serial).where(
            Item.company_id == company_id))}
        count = session.scalar(select(func.count()).select_from(CycleCountSession).where(
            CycleCountSession.company_id == company_id, CycleCountSession.scope_type_code == SCOPE)) or 0
        row = CycleCountSession(
            company_id=company_id, warehouse_id=warehouse_id, session_code=f"LOC-{count + 1:05d}", scope_type_code=SCOPE,
            scope_filter={"locations": list(location_ids), "bins": sorted(scope)}, status_code="COUNTING",
            is_blind_count=blind, snapshot_at=datetime.datetime.now(), created_by_user_id=user_id)
        session.add(row)
        session.flush()
        stock = session.execute(
            select(StockBalance.bin_location_id, StockBalance.item_id, func.sum(StockBalance.quantity_on_hand))
            .where(StockBalance.warehouse_id == warehouse_id, StockBalance.bin_location_id.in_(scope))
            .group_by(StockBalance.bin_location_id, StockBalance.item_id)).all()
        batches = wl.bin_batches(company_id, warehouse_id)
        for bin_id, item_id, qty in stock:
            track_batch, track_serial = flags.get(item_id, (False, False))
            if not qty or track_serial:
                continue
            rest = qty
            if track_batch:
                for lt in batches.get((bin_id, item_id), []):
                    session.add(CycleCountLine(session_id=row.session_id, item_id=item_id, bin_location_id=bin_id,
                                               batch_id=lt.batch_id, expected_quantity_base=lt.quantity))
                    rest -= lt.quantity
            if rest > 0:
                session.add(CycleCountLine(session_id=row.session_id, item_id=item_id, bin_location_id=bin_id,
                                           expected_quantity_base=rest))
        session.commit()
        return row.session_id


def list_location_counts(company_id: int, open_only: bool = False) -> list[CycleCountSession]:
    with new_session() as session:
        q = select(CycleCountSession).where(CycleCountSession.company_id == company_id, CycleCountSession.scope_type_code == SCOPE)
        if open_only:
            q = q.where(CycleCountSession.status_code == "COUNTING")
        return list(session.scalars(q.order_by(CycleCountSession.session_id.desc())))


def count_lines(company_id: int, session_id: int) -> list[SimpleNamespace]:
    from peecha.services import inventory_catalog as catalog_service

    with new_session() as session:
        s = _session(session, company_id, session_id)
        warehouse_id, blind = s.warehouse_id, s.is_blind_count
        lines = list(session.scalars(select(CycleCountLine).where(CycleCountLine.session_id == session_id)))
    codes = {n.location_id: n.full_code for n in wl.tree(company_id, warehouse_id)}
    items = {i.item_id: i for i in catalog_service.list_items(company_id)}
    with new_session() as session:
        batches = {b.batch_id: b for b in session.scalars(select(Batch).where(
            Batch.batch_id.in_({ln.batch_id for ln in lines if ln.batch_id} or {-1})))}
    out = []
    for ln in lines:
        item = items.get(ln.item_id)
        out.append(SimpleNamespace(
            line_id=ln.line_id, location_id=ln.bin_location_id, location_code=codes.get(ln.bin_location_id, ""), item_id=ln.item_id,
            item_code=item.code if item else "", item_name=item.name if item else "", unit=item.base_uom_code if item else "",
            batch_id=ln.batch_id, batch_no=batches[ln.batch_id].batch_no if ln.batch_id in batches else None,
            expiry_date=batches[ln.batch_id].expiry_date if ln.batch_id in batches else None,
            expected=ln.expected_quantity_base, counted=ln.counted_quantity_base,
            variance=(ln.counted_quantity_base - ln.expected_quantity_base) if ln.counted_quantity_base is not None else None,
            counted_at=ln.counted_at, blind=blind))
    return sorted(out, key=lambda r: (r.location_code, r.item_code, r.batch_no or ""))


def record_location_count(company_id: int, session_id: int, location_id: int, item_id: int, counted: decimal.Decimal,
                          user_id: int | None = None, batch_no: str | None = None) -> int:
    """ثبت/جایگزینیِ شمارشِ یک کالا در یک محل (واحدِ پایه)؛ کالایِ پیدا‌شدهٔ بی‌سابقه هم ثبت می‌شود."""
    counted = decimal.Decimal(counted)
    if counted < 0:
        raise ValueError("مقدارِ شمارش‌شده نمی‌تواند منفی باشد.")
    with new_session() as session:
        s = _session(session, company_id, session_id)
        if s.status_code != "COUNTING":
            raise ValueError("این شمارش بسته شده است.")
        if location_id not in set((s.scope_filter or {}).get("bins", [])):
            raise ValueError("این محل در دامنهٔ این شمارش نیست.")
        item = session.get(Item, item_id)
        if item is None or item.company_id != company_id:
            raise ValueError("کالا نامعتبر است.")
        if _tracked(item):
            raise ValueError("کالایِ سریال‌دار را با انبارگردانیِ عادی (با ردیابی) بشمارید.")
        batch_id = None
        if item.track_batch and batch_no:
            batch_id = session.scalar(select(Batch.batch_id).where(Batch.item_id == item_id, Batch.batch_no == batch_no.strip()))
            if batch_id is None:
                raise ValueError(f"بچِ «{batch_no}» برایِ این کالا تعریف نشده است.")
        elif item.track_batch and not session.scalar(select(func.count()).select_from(CycleCountLine).where(
                CycleCountLine.session_id == session_id, CycleCountLine.item_id == item_id,
                CycleCountLine.bin_location_id == location_id, CycleCountLine.batch_id.is_(None))):
            # فقط ماندهٔ قدیمیِ بی‌بچِ همین محل (ردیفِ ازپیش‌ساخته) بدونِ شمارهٔ بچ شمرده می‌شود
            raise ValueError("این کالا بچ‌دار است؛ شمارهٔ بچ را وارد کنید.")
        line = session.scalar(select(CycleCountLine).where(
            CycleCountLine.session_id == session_id, CycleCountLine.item_id == item_id, CycleCountLine.bin_location_id == location_id,
            CycleCountLine.batch_id == batch_id if batch_id is not None else CycleCountLine.batch_id.is_(None)))
        if line is None:
            line = CycleCountLine(session_id=session_id, item_id=item_id, bin_location_id=location_id, batch_id=batch_id,
                                  expected_quantity_base=_ZERO)
            session.add(line)
        line.counted_quantity_base, line.counted_quantity = counted, counted
        line.counted_uom_id, line.conversion_factor = item.base_uom_id, decimal.Decimal(1)
        line.counted_by_user_id, line.counted_at = user_id, datetime.datetime.now()
        session.flush()
        line_id = line.line_id
        session.commit()
        return line_id


def mark_location_empty(company_id: int, session_id: int, location_id: int, user_id: int | None = None) -> int:
    """«محل خالی است»: همهٔ ردیف‌هایِ شمرده‌نشدهٔ این محل صفر ثبت می‌شوند."""
    n = 0
    for ln in count_lines(company_id, session_id):
        if ln.location_id == location_id and ln.counted is None:
            record_location_count(company_id, session_id, location_id, ln.item_id, _ZERO, user_id, ln.batch_no)
            n += 1
    return n


def finalize_location_count(company_id: int, session_id: int, user_id: int) -> list[int]:
    """اختلافِ ردیف‌هایِ شمرده‌شده با سندِ اصلاحِ انبار رویِ همان محل (مازاد و کسری جدا)."""
    from peecha.services import inventory_documents as inv_documents_service
    from peecha.services import lot_tracking
    from peecha.services import stock_count

    lines = count_lines(company_id, session_id)
    with new_session() as session:
        s = _session(session, company_id, session_id)
        if s.status_code != "COUNTING":
            raise ValueError("این شمارش قبلاً بسته شده است.")
        warehouse_id, code = s.warehouse_id, s.session_code
        base_uom = dict(session.execute(select(Item.item_id, Item.base_uom_id).where(Item.company_id == company_id)).all())
    gains = [ln for ln in lines if ln.variance is not None and ln.variance > 0]
    losses = [ln for ln in lines if ln.variance is not None and ln.variance < 0]
    reason = stock_count._reason_code(company_id) if gains or losses else None
    doc_ids = []
    for rows, header in ((gains, inv_documents_service.DocumentHeaderFields(destination_warehouse_id=warehouse_id)),
                         (losses, inv_documents_service.DocumentHeaderFields(source_warehouse_id=warehouse_id))):
        if not rows:
            continue
        header.reference_no, header.description = code, f"اختلافِ شمارشِ محلِ {code}"
        doc_id = inv_documents_service.create_stock_document(company_id, user_id, "ADJUSTMENT", datetime.date.today(), header)
        for ln in rows:
            qty = abs(ln.variance)
            line_id = inv_documents_service.add_line(doc_id, company_id, inv_documents_service.LineFields(
                item_id=ln.item_id, uom_id=base_uom[ln.item_id], quantity=qty, quantity_base=qty, conversion_factor=decimal.Decimal(1),
                reason_code_id=reason, bin_location_id=ln.location_id,
                description=f"شمارشِ محلِ {ln.location_code}: دفتری {ln.expected.normalize()}، شمارش {ln.counted.normalize()}"
                            + (f" -- بچ {ln.batch_no}" if ln.batch_no else "")))
            if ln.batch_no:
                lot_tracking.set_line_tracking(company_id, [lot_tracking.TrackingEntry(
                    qty, batch_no=ln.batch_no, expiry_date=ln.expiry_date)], stock_line_id=line_id)
        inv_documents_service.confirm_stock_document(doc_id, company_id)
        inv_documents_service.post_stock_document(doc_id, company_id, user_id)
        doc_ids.append(doc_id)
    with new_session() as session:
        s = _session(session, company_id, session_id)
        s.status_code, s.approved_by_user_id, s.approved_at = "POSTED", user_id, datetime.datetime.now()
        s.resulting_stock_document_id = doc_ids[0] if doc_ids else None
        session.commit()
    return doc_ids


def cancel_location_count(company_id: int, session_id: int) -> None:
    with new_session() as session:
        s = _session(session, company_id, session_id)
        if s.status_code != "COUNTING":
            raise ValueError("فقط شمارشِ باز لغو می‌شود.")
        s.status_code = "CANCELLED"
        session.commit()
