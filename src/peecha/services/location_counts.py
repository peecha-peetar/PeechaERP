"""شمارشِ دوره‌ایِ محل‌محور -- R250.

از همان جدول‌هایِ انبارگردانی (inv.cycle_count_sessions با scope_type_code = 'BY_BIN' و inv.cycle_count_lines
که bin_location_id دارد) استفاده می‌کند؛ موجودیِ دفتری از inv.stock_balance به تفکیکِ محل گرفته می‌شود و اختلاف
با سندِ اصلاحِ عادیِ انبار (ADJUSTMENT) رویِ همان محل ثبت می‌شود.
R251: کالایِ بچ‌دار به تفکیکِ بچ در هر محل شمرده می‌شود (از ستونِ محلِ inv.lot_movements).
R252: کالایِ سریال‌دار با اسکنِ سریال‌ها شمرده می‌شود: سریالِ گم‌شده کسری، سریالِ موجود در محلِ دیگرِ همین انبار
با سندِ انتقال به این محل، و سریالِ بیرون از موجودی مازاد ثبت می‌شود.
"""

from __future__ import annotations

import datetime
import decimal
from types import SimpleNamespace

from sqlalchemy import func, select

from peecha.db.base import new_session
from peecha.db.models.inventory import (
    Batch, CycleCountLine, CycleCountSession, Item, SerialNumber, StockBalance, Warehouse,
)
from peecha.services import warehouse_locations as wl

_ZERO = decimal.Decimal(0)
SCOPE = "BY_BIN"


def _has_cost(session, item_id: int) -> bool:
    """R252: مازاد فقط وقتی ثبت می‌شود که کالا بهایی دارد (همان شرطِ موتورِ انبار برایِ افزایشِ بی‌بها)."""
    from peecha.services.inventory_engine import _last_known_unit_cost

    if session.scalar(select(func.count()).select_from(StockBalance).where(
            StockBalance.item_id == item_id, StockBalance.quantity_on_hand > 0, StockBalance.average_unit_cost > 0)):
        return True
    return _last_known_unit_cost(session, item_id) is not None


def _label(session, item) -> str:
    from peecha.services import lot_tracking

    return lot_tracking._item_name(session, item)


_NO_COST = "کالایِ «{}» هنوز هیچ بهایِ ثبت‌شده‌ای ندارد؛ مازادِ آن در شمارش ثبت نمی‌شود. ابتدا رسیدِ با بها ثبت کنید."


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
            if not qty:
                continue
            rest = qty
            if track_batch and not track_serial:
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
            serial=bool(item.track_serial) if item else False,
            expiry_date=batches[ln.batch_id].expiry_date if ln.batch_id in batches else None,
            expected=ln.expected_quantity_base, counted=ln.counted_quantity_base,
            variance=(ln.counted_quantity_base - ln.expected_quantity_base) if ln.counted_quantity_base is not None else None,
            counted_at=ln.counted_at, blind=blind))
    return sorted(out, key=lambda r: (r.location_code, r.item_code, r.batch_no or ""))


def record_location_count(company_id: int, session_id: int, location_id: int, item_id: int, counted: decimal.Decimal,
                          user_id: int | None = None, batch_no: str | None = None, _serial_call: bool = False) -> int:
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
        if item.track_serial and not _serial_call:
            raise ValueError("کالایِ سریال‌دار با اسکنِ سریال‌ها شمرده می‌شود.")
        batch_id = None
        if item.track_batch and batch_no and not item.track_serial:
            batch_id = session.scalar(select(Batch.batch_id).where(Batch.item_id == item_id, Batch.batch_no == batch_no.strip()))
            if batch_id is None:
                raise ValueError(f"بچِ «{batch_no}» برایِ این کالا تعریف نشده است.")
        elif item.track_batch and not item.track_serial and not session.scalar(select(func.count()).select_from(CycleCountLine).where(
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
        if counted > line.expected_quantity_base and not item.track_serial and not _has_cost(session, item_id):
            raise ValueError(_NO_COST.format(_label(session, item)))
        line.counted_quantity_base, line.counted_quantity = counted, counted
        line.counted_uom_id, line.conversion_factor = item.base_uom_id, decimal.Decimal(1)
        line.counted_by_user_id, line.counted_at = user_id, datetime.datetime.now()
        session.flush()
        line_id = line.line_id
        session.commit()
        return line_id


def expected_serials(company_id: int, location_id: int, item_id: int) -> list[str]:
    with new_session() as session:
        return sorted(session.scalars(select(SerialNumber.serial_no).where(
            SerialNumber.company_id == company_id, SerialNumber.item_id == item_id, SerialNumber.status_code == "IN_STOCK",
            SerialNumber.current_bin_location_id == location_id)))


def record_serial_count(company_id: int, session_id: int, location_id: int, item_id: int, serial_nos: list[str],
                        user_id: int | None = None) -> int:
    """R252: سریال‌هایِ اسکن‌شده در یک محل (جایگزینِ اسکنِ قبلی)."""
    from peecha.services import lot_tracking

    serials = sorted({(x or "").strip() for x in serial_nos if (x or "").strip()})
    with new_session() as session:
        item = session.get(Item, item_id)
        if item is None or item.company_id != company_id or not item.track_serial:
            raise ValueError("این کالا سریال‌دار نیست.")
        known = {sn.serial_no: sn for sn in session.scalars(select(SerialNumber).where(
            SerialNumber.item_id == item_id, SerialNumber.serial_no.in_(serials or ["-"])))}
        batch_nos = {b.batch_id: b for b in session.scalars(select(Batch).where(
            Batch.batch_id.in_({sn.batch_id for sn in known.values() if sn.batch_id} or {-1})))}
        unknown = [x for x in serials if x not in known]
        if unknown and not _has_cost(session, item_id):
            raise ValueError(_NO_COST.format(_label(session, item)))
        if unknown and item.track_batch:
            raise ValueError(f"سریالِ ناشناختهٔ کالایِ بچ‌دار ({unknown[0]}) را با انبارگردانیِ عادی و شمارهٔ بچ ثبت کنید.")
    line_id = record_location_count(company_id, session_id, location_id, item_id, decimal.Decimal(len(serials)), user_id,
                                    _serial_call=True)
    entries = []
    for x in serials:
        b = batch_nos.get(known[x].batch_id) if x in known else None
        entries.append(lot_tracking.TrackingEntry(decimal.Decimal(1), serial_no=x, batch_no=b.batch_no if b else None,
                                                  expiry_date=b.expiry_date if b else None))
    lot_tracking.set_line_tracking(company_id, entries, cycle_count_line_id=line_id)
    return line_id


def mark_location_empty(company_id: int, session_id: int, location_id: int, user_id: int | None = None) -> int:
    """«محل خالی است»: همهٔ ردیف‌هایِ شمرده‌نشدهٔ این محل صفر ثبت می‌شوند."""
    n = 0
    for ln in count_lines(company_id, session_id):
        if ln.location_id == location_id and ln.counted is None:
            if ln.serial:
                record_serial_count(company_id, session_id, location_id, ln.item_id, [], user_id)
            else:
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
    gains = [ln for ln in lines if not ln.serial and ln.variance is not None and ln.variance > 0]
    losses = [ln for ln in lines if not ln.serial and ln.variance is not None and ln.variance < 0]
    reason = stock_count._reason_code(company_id) if lines else None
    doc_ids = _finalize_serials(company_id, user_id, warehouse_id, code, [ln for ln in lines if ln.serial and ln.counted is not None],
                                base_uom, reason)
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


def _finalize_serials(company_id: int, user_id: int, warehouse_id: int, code: str, lines: list, base_uom: dict,
                      reason: int | None) -> list[int]:
    """سریال‌ها: گم‌شده → کسری؛ موجود در محلِ دیگرِ همین انبار → انتقال به این محل؛ بیرون از موجودی → مازاد."""
    from peecha.services import inventory_documents as inv_documents_service
    from peecha.services import lot_tracking

    TE = lot_tracking.TrackingEntry
    losses, gains, moves = [], [], {}
    counted_by_line = {ln.line_id: {e.serial_no for e in lot_tracking.get_line_tracking(cycle_count_line_id=ln.line_id)}
                       for ln in lines}
    seen_anywhere: dict[int, set] = {}
    for ln in lines:  # سریالِ اسکن‌شده در محلِ دیگرِ همین شمارش گم‌شده نیست (جابه‌جا شده است)
        seen_anywhere.setdefault(ln.item_id, set()).update(counted_by_line[ln.line_id])
    with new_session() as session:
        for ln in lines:
            counted = counted_by_line[ln.line_id]
            expected = set(expected_serials(company_id, ln.location_id, ln.item_id))
            for x in sorted(expected - seen_anywhere[ln.item_id]):
                losses.append((ln, x))
            for x in sorted(counted - expected):
                sn = session.scalar(select(SerialNumber).where(SerialNumber.item_id == ln.item_id, SerialNumber.serial_no == x))
                if sn is not None and sn.status_code == "IN_STOCK" and sn.current_warehouse_id == warehouse_id \
                        and sn.current_bin_location_id is not None:
                    moves.setdefault((sn.current_bin_location_id, ln.location_id), []).append((ln, x))
                else:
                    gains.append((ln, x))
    doc_ids = []

    def post(doc_type, header, rows, src_bin=None, dst_bin=None):
        header.reference_no, header.description = code, f"سریال‌هایِ شمارشِ محلِ {code}"
        doc_id = inv_documents_service.create_stock_document(company_id, user_id, doc_type, datetime.date.today(), header)
        by_item: dict[tuple, list] = {}
        for ln, x in rows:
            by_item.setdefault((ln.item_id, ln.location_id), []).append(x)
        for (item_id, bin_id), serials in by_item.items():
            q = decimal.Decimal(len(serials))
            line_id = inv_documents_service.add_line(doc_id, company_id, inv_documents_service.LineFields(
                item_id=item_id, uom_id=base_uom[item_id], quantity=q, quantity_base=q, conversion_factor=decimal.Decimal(1),
                reason_code_id=reason if doc_type == "ADJUSTMENT" else None, bin_location_id=src_bin or bin_id,
                destination_bin_location_id=dst_bin, description="سریال: " + "، ".join(serials[:20])))
            with new_session() as session:
                batches = {sn.serial_no: session.get(Batch, sn.batch_id) if sn.batch_id else None for sn in session.scalars(
                    select(SerialNumber).where(SerialNumber.item_id == item_id, SerialNumber.serial_no.in_(serials)))}
            lot_tracking.set_line_tracking(company_id, [TE(decimal.Decimal(1), serial_no=x, batch_no=batches[x].batch_no if batches.get(x) else None,
                                                           expiry_date=batches[x].expiry_date if batches.get(x) else None)
                                                        for x in serials], stock_line_id=line_id)
        inv_documents_service.confirm_stock_document(doc_id, company_id)
        inv_documents_service.post_stock_document(doc_id, company_id, user_id)
        doc_ids.append(doc_id)

    if losses:
        post("ADJUSTMENT", inv_documents_service.DocumentHeaderFields(source_warehouse_id=warehouse_id), losses)
    for (src, dst), rows in moves.items():
        post("TRANSFER", inv_documents_service.DocumentHeaderFields(source_warehouse_id=warehouse_id, destination_warehouse_id=warehouse_id),
             rows, src_bin=src, dst_bin=dst)
    if gains:
        post("ADJUSTMENT", inv_documents_service.DocumentHeaderFields(destination_warehouse_id=warehouse_id), gains)
    return doc_ids


def cancel_location_count(company_id: int, session_id: int) -> None:
    with new_session() as session:
        s = _session(session, company_id, session_id)
        if s.status_code != "COUNTING":
            raise ValueError("فقط شمارشِ باز لغو می‌شود.")
        s.status_code = "CANCELLED"
        session.commit()
