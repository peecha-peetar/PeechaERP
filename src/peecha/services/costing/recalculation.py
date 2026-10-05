"""بازمحاسبهٔ بهایِ تمام‌شده -- R260.

دفترِ انبار تغییرناپذیر است؛ پس بازمحاسبه حرکت‌ها را به ترتیبِ زمانی دوباره «بازپخش» می‌کند و فقط اختلاف را
با یک سندِ حسابداریِ اصلاحی (تاریخِ ثبت) + لاگِ تاریخ‌دارِ اصلاحِ بها ثبت می‌کند. لایه‌ها، تخصیص‌ها و میانگینِ مانده
به مقدارِ جدید به‌روز می‌شوند و مبلغِ قبلی/جدیدِ هر ردیف در inv.cost_recalculation_lines می‌ماند.

پشتیبانی: FIFO/LIFO/HIFO/LOFO (از تاریخِ شروع، با تخصیص‌هایِ ثبت‌شده) و میانگینِ متحرک (کلِ تاریخچه، به تفکیکِ مکان).
شناساییِ ویژه، استاندارد و NIFO به ترتیبِ زمانی وابسته نیستند و بازمحاسبه نمی‌شوند.
"""

from __future__ import annotations

import datetime
import decimal
from collections import defaultdict
from dataclasses import dataclass, field
from types import SimpleNamespace

from sqlalchemy import func, select

from peecha.db.base import new_session
from peecha.db.models.inventory import (
    CostAdjustmentLog, CostAllocation, CostLayer, CostRecalculationLine, CostRecalculationRun, Item, StockBalance,
    StockDocument, StockDocumentLine, StockLedger,
)
from peecha.services.costing import engine as costing_engine
from peecha.services.costing import strategies

_ZERO = decimal.Decimal(0)
_Q2 = decimal.Decimal("0.01")
_Q6 = decimal.Decimal("0.000001")
RECALC_TAG = "RECALC"
NOT_RECALCULATED = {
    "SPECIFIC": "شناساییِ ویژه به ترتیبِ زمانی وابسته نیست",
    "STANDARD": "بهایِ استاندارد از جدولِ بهایِ استاندارد می‌آید",
    "NIFO": "NIFO بهایِ جایگزینیِ روزِ خروج است",
}
# حسابِ طرفِ مقابلِ موجودی برایِ اختلافِ هر نوع سند (TRANSFER/امانی بی‌اثرِ حسابداری)
_EXPENSE_ROLE = {"ISSUE": "COGS", "ADJUSTMENT": "INVENTORY_ADJUSTMENT_LOSS", "RETURN_IN": "COGS"}
_NO_JE_TYPES = {"TRANSFER", "CONSIGNMENT_IN", "CONSIGN_RETURN"}


def _money(value: decimal.Decimal) -> decimal.Decimal:
    return value.quantize(_Q2, rounding=decimal.ROUND_HALF_UP)


def _q6(value: decimal.Decimal) -> decimal.Decimal:
    return value.quantize(_Q6, rounding=decimal.ROUND_HALF_UP)


@dataclass
class LineDelta:
    stock_line_id: int
    item_id: int
    warehouse_id: int
    bin_location_id: int | None
    direction: str
    doc_type: str
    document_id: int
    document_no: int
    movement_date: datetime.date
    quantity: decimal.Decimal
    old_amount: decimal.Decimal
    new_amount: decimal.Decimal

    @property
    def delta(self) -> decimal.Decimal:
        return self.new_amount - self.old_amount


@dataclass
class ItemResult:
    item_id: int
    method: str
    ok: bool
    message: str = ""
    lines: list[LineDelta] = field(default_factory=list)
    # برایِ اعمال: لایه → (مانده، بها)، ردیف → [(لایه، مقدار، بها، وضعیت)]، (انبار، مکان) → میانگین
    layer_updates: dict = field(default_factory=dict)
    allocation_updates: dict = field(default_factory=dict)
    balance_updates: dict = field(default_factory=dict)

    @property
    def changed(self) -> list[LineDelta]:
        return [ln for ln in self.lines if abs(ln.delta) >= _Q2]


def _prior_deltas(session, item_id: int) -> dict[tuple[int, str, int], decimal.Decimal]:
    """(ردیف، جهت، انبار) → جمعِ اصلاحاتِ بازمحاسبه‌هایِ قبلی (مبلغِ جاریِ ردیف = دفترِ انبار + این)."""
    rows = session.execute(
        select(CostRecalculationLine.stock_document_line_id, CostRecalculationLine.movement_direction,
               CostRecalculationLine.warehouse_id, func.sum(CostRecalculationLine.delta_amount))
        .where(CostRecalculationLine.item_id == item_id)
        .group_by(CostRecalculationLine.stock_document_line_id, CostRecalculationLine.movement_direction,
                  CostRecalculationLine.warehouse_id)).all()
    return {(ln, d, w): decimal.Decimal(v or 0) for ln, d, w, v in rows}


def _line_info(session, line_ids: set[int]) -> dict[int, SimpleNamespace]:
    if not line_ids:
        return {}
    rows = session.execute(
        select(StockDocumentLine.line_id, StockDocumentLine.source_line_id, StockDocument.document_type_code,
               StockDocument.stock_document_id, StockDocument.document_no)
        .join(StockDocument, StockDocument.stock_document_id == StockDocumentLine.stock_document_id)
        .where(StockDocumentLine.line_id.in_(line_ids))).all()
    return {r[0]: SimpleNamespace(source_line_id=r[1], doc_type=r[2], document_id=r[3], document_no=r[4]) for r in rows}


def _ledger_groups(session, item_id: int, date_from: datetime.date | None = None) -> list[SimpleNamespace]:
    """ردیف‌هایِ دفترِ انبار، گروه‌شده به (ردیفِ سند، جهت، انبار، مکان) به ترتیبِ زمانی."""
    q = (select(StockLedger).where(StockLedger.item_id == item_id)
         .order_by(StockLedger.movement_date, StockLedger.ledger_id))
    if date_from is not None:
        q = q.where(StockLedger.movement_date >= date_from)
    groups: dict[tuple, SimpleNamespace] = {}
    for r in session.scalars(q):
        key = (r.stock_document_line_id, r.movement_direction, r.warehouse_id, r.bin_location_id)
        g = groups.get(key)
        if g is None:
            g = groups[key] = SimpleNamespace(
                line_id=r.stock_document_line_id, direction=r.movement_direction, warehouse_id=r.warehouse_id,
                bin_id=r.bin_location_id, date=r.movement_date, seq=r.ledger_id, quantity=_ZERO, amount=_ZERO, ledger_ids=[])
        g.quantity += r.quantity_base
        g.amount += _money((r.unit_cost or _ZERO) * r.quantity_base)
        g.ledger_ids.append(r.ledger_id)
    return sorted(groups.values(), key=lambda g: (g.date, g.seq))


def _foreign_adjustments(session, item_id: int, date_from: datetime.date | None) -> bool:
    q = select(func.count()).select_from(CostAdjustmentLog).where(
        CostAdjustmentLog.item_id == item_id, func.coalesce(CostAdjustmentLog.costing_method, "") != RECALC_TAG)
    if date_from is not None:
        q = q.where(CostAdjustmentLog.adjusted_on >= date_from)
    return bool(session.scalar(q))


# --- روش‌هایِ لایه‌ای ------------------------------------------------------------------------
def _replay_layers(session, item: Item, method: str, date_from: datetime.date, lock: bool) -> ItemResult:
    res = ItemResult(item.item_id, method, ok=False)
    if _foreign_adjustments(session, item.item_id, date_from):
        res.message = "در بازه اصلاحِ بهایِ خرید ثبت شده است -- بازمحاسبه از تاریخی پس از آن ممکن است"
        return res
    q = (select(CostLayer, StockLedger.movement_date, StockLedger.ledger_id)
         .join(StockLedger, StockLedger.ledger_id == CostLayer.stock_ledger_id)
         .where(CostLayer.item_id == item.item_id).order_by(CostLayer.cost_layer_id))
    if lock:
        q = q.with_for_update(of=CostLayer)
    layer_rows = session.execute(q).all()
    allocs = list(session.scalars(select(CostAllocation).where(
        CostAllocation.item_id == item.item_id, CostAllocation.movement_date >= date_from)
        .order_by(CostAllocation.allocation_id)))
    if any(a.costing_method_code != method for a in allocs):
        res.message = "روشِ ارزش‌گذاریِ کالا در این بازه تغییر کرده است -- تاریخِ شروع را پس از تغییرِ روش بگذارید"
        return res
    out_groups = [g for g in _ledger_groups(session, item.item_id, date_from) if g.direction == "OUT"]
    allocs_by_key: dict[tuple[int, int], list[CostAllocation]] = defaultdict(list)
    for a in allocs:
        allocs_by_key[(a.stock_document_line_id, a.warehouse_id)].append(a)
    for g in out_groups:
        own = allocs_by_key.get((g.line_id, g.warehouse_id), [])
        if sum((a.quantity_base for a in own), _ZERO) != g.quantity:
            res.message = "خروجِ بدونِ تخصیصِ کامل در بازه (حرکتِ پیش از R257 یا برگشتی) -- تاریخِ شروع را جلوتر بگذارید"
            return res
    consumed_in_window: dict[int, decimal.Decimal] = defaultdict(lambda: _ZERO)
    for a in allocs:
        if a.cost_layer_id is not None:
            consumed_in_window[a.cost_layer_id] += a.quantity_base
    sims: list[SimpleNamespace] = []
    for layer, mdate, ledger_id in layer_rows:
        start = layer.remaining_quantity + consumed_in_window[layer.cost_layer_id]
        in_window = layer.source_type_code != "OPENING_BALANCE" and mdate >= date_from
        if start > layer.original_quantity or (in_window and start != layer.original_quantity):
            res.message = "لایه‌ها با تخصیص‌ها هم‌خوان نیستند -- بازمحاسبه برایِ این کالا ممکن نیست"
            return res
        sims.append(SimpleNamespace(
            layer=layer, cost_layer_id=layer.cost_layer_id, warehouse_id=layer.warehouse_id, unit_cost=layer.unit_cost,
            remaining_quantity=start, receipt_date=layer.receipt_date or mdate, available=not in_window,
            seq=(mdate, ledger_id), source_line_id=layer.source_line_id, source_type=layer.source_type_code,
            old_cost=layer.unit_cost))
    infos = _line_info(session, {g.line_id for g in out_groups} | {s.source_line_id for s in sims if s.source_line_id})
    prior = _prior_deltas(session, item.item_id)
    strategy = strategies.get_strategy(method)
    events = [((g.date, g.seq, 0), "O", g) for g in out_groups]
    events += [((s.seq[0], s.seq[1], 1), "L", s) for s in sims if not s.available]
    events.sort(key=lambda e: e[0])
    new_out: dict[int, tuple[decimal.Decimal, decimal.Decimal]] = {}  # ردیف → (مبلغِ قبلی، مبلغِ جدید)
    picks_by_line: dict[int, list] = {}
    transfer_done: set[int] = set()

    for _seq, kind, obj in events:
        if kind == "L":
            s = obj
            src = infos.get(s.source_line_id)
            if s.source_type == "TRANSFER" and s.source_line_id in picks_by_line and s.source_line_id not in transfer_done:
                transfer_done.add(s.source_line_id)
                dest = sorted((x for x in sims if x.source_type == "TRANSFER" and x.source_line_id == s.source_line_id),
                              key=lambda x: x.seq)
                pool = [[q, c] for _l, q, c, _st in picks_by_line[s.source_line_id]]
                for d in dest:
                    need, value = d.layer.original_quantity, _ZERO
                    while need > 0 and pool:
                        take = min(need, pool[0][0])
                        value += take * pool[0][1]
                        need -= take
                        pool[0][0] -= take
                        if pool[0][0] <= 0:
                            pool.pop(0)
                    if need == 0 and d.layer.original_quantity:
                        d.unit_cost = _q6(value / d.layer.original_quantity)
            elif s.source_type == "RETURN_IN" and src is not None and src.source_line_id in new_out:
                old_amt, new_amt = new_out[src.source_line_id]
                sold = next((g.quantity for g in out_groups if g.line_id == src.source_line_id), _ZERO)
                if sold:
                    s.unit_cost = _q6(s.old_cost + (new_amt - old_amt) / sold)
            s.available = True
            continue
        g = obj
        info = infos[g.line_id]
        own_allocs = allocs_by_key[(g.line_id, g.warehouse_id)]
        cands = [s for s in sims if s.warehouse_id == g.warehouse_id and s.available and s.remaining_quantity > 0]
        picks: list = []
        remaining = g.quantity
        if info.doc_type == "RETURN_OUT" and info.source_line_id is not None:
            own = [s for s in cands if s.source_line_id == info.source_line_id]
            got, remaining = strategies.Fifo().pick(own, remaining)
            picks += got
            for p in got:
                p.layer.remaining_quantity -= p.quantity
            cands = [s for s in cands if s.remaining_quantity > 0]
        got, remaining = strategy.pick(cands, remaining)
        for p in got:
            p.layer.remaining_quantity -= p.quantity
        picks += got
        if remaining > 0:  # سندِ عقب‌دار: موجودی در لحظهٔ ثبت واقعاً بود -- از لایه‌هایِ بعدی
            later = sorted((s for s in sims if s.warehouse_id == g.warehouse_id and not s.available and s.remaining_quantity > 0),
                           key=lambda s: s.seq)
            for s in later:
                if remaining <= 0:
                    break
                take = min(s.remaining_quantity, remaining)
                s.remaining_quantity -= take
                remaining -= take
                picks.append(strategies.Pick(s, take))
        rows = [(p.layer, p.quantity, p.layer.unit_cost, "CALCULATED") for p in picks]
        if remaining > 0:
            short = [a for a in own_allocs if a.cost_layer_id is None]
            cost = (short[0].unit_cost if short else (rows[-1][2] if rows else _ZERO))
            status = "PENDING" if any(a.costing_status_code == "PENDING" for a in own_allocs) else "CALCULATED"
            rows.append((None, remaining, cost, status))
        picks_by_line[g.line_id] = rows
        old = g.amount + prior.get((g.line_id, "OUT", g.warehouse_id), _ZERO)
        new = sum((_money(q * c) for _l, q, c, _st in rows), _ZERO)
        new_out[g.line_id] = (old, new)
        res.lines.append(LineDelta(g.line_id, item.item_id, g.warehouse_id, g.bin_id, "OUT", info.doc_type, info.document_id,
                                   info.document_no, g.date, g.quantity, old, new))
        res.allocation_updates[(g.line_id, g.warehouse_id)] = rows

    # لایه‌هایِ مشتق‌شده (انتقال/برگشت از فروش) که بهایشان عوض شد → اختلافِ ورودِ همان ردیف
    in_delta: dict[tuple[int, int], list] = {}
    for s in sims:
        res.layer_updates[s.cost_layer_id] = (s.remaining_quantity, s.unit_cost)
        if s.unit_cost != s.old_cost:
            key = (s.source_line_id, s.warehouse_id)
            acc = in_delta.setdefault(key, [_ZERO, _ZERO, _ZERO, s])
            acc[0] += s.layer.original_quantity
            acc[1] += _money(s.layer.original_quantity * s.old_cost)
            acc[2] += _money(s.layer.original_quantity * s.unit_cost)
    if in_delta:
        infos.update(_line_info(session, {k[0] for k in in_delta} - set(infos)))
    for (line_id, wh), (qty, old, new, s) in in_delta.items():
        info = infos[line_id]
        res.lines.append(LineDelta(line_id, item.item_id, wh, None, "IN", info.doc_type, info.document_id, info.document_no,
                                   s.seq[0], qty, old, new))
    actual = defaultdict(lambda: _ZERO)
    for layer, _d, _l in layer_rows:
        actual[layer.warehouse_id] += layer.remaining_quantity
    simulated = defaultdict(lambda: _ZERO)
    for s in sims:
        simulated[s.warehouse_id] += s.remaining_quantity
    on_hand = dict(session.execute(select(StockBalance.warehouse_id, func.sum(StockBalance.quantity_on_hand))
                                   .where(StockBalance.item_id == item.item_id).group_by(StockBalance.warehouse_id)).all())
    # موجودیِ منفیِ گذشته: لایهٔ رسیدِ بعدی کامل ساخته شده بود؛ بازپخش آن را با کمبود تسویه می‌کند و با ماندهٔ واقعی برابر می‌شود
    matches_balance = all(simulated.get(w, _ZERO) == max(decimal.Decimal(q or 0), _ZERO) for w, q in on_hand.items())
    if dict(actual) != dict(simulated) and not matches_balance:
        res.message = "ماندهٔ بازپخش با ماندهٔ واقعیِ لایه‌ها یکی نشد -- بازمحاسبه برایِ این کالا ممکن نیست"
        res.lines.clear()
        return res
    res.ok = True
    return res


# --- میانگینِ متحرک -------------------------------------------------------------------------
def _replay_average(session, item: Item, date_from: datetime.date) -> ItemResult:
    res = ItemResult(item.item_id, "WEIGHTED_AVERAGE", ok=False)
    if _foreign_adjustments(session, item.item_id, None):
        res.message = "اصلاحِ بهایِ خرید برایِ این کالا ثبت شده است -- بازمحاسبهٔ میانگین ممکن نیست"
        return res
    groups = _ledger_groups(session, item.item_id)
    allocs = session.execute(
        select(CostAllocation.stock_document_line_id, CostAllocation.warehouse_id, CostAllocation.costing_method_code,
               CostAllocation.costing_status_code).where(CostAllocation.item_id == item.item_id)).all()
    if any(m != "WEIGHTED_AVERAGE" for _l, _w, m, _s in allocs):
        res.message = "روشِ ارزش‌گذاریِ کالا قبلاً تغییر کرده است -- بازمحاسبهٔ میانگین ممکن نیست"
        return res
    alloc_keys = {(ln, w) for ln, w, _m, _s in allocs}
    pending_keys = {(ln, w) for ln, w, _m, st in allocs if st == "PENDING"}
    infos = _line_info(session, {g.line_id for g in groups})
    prior = _prior_deltas(session, item.item_id)
    state: dict[tuple[int, int], list] = defaultdict(lambda: [_ZERO, _ZERO])  # (انبار، مکان) → [مقدار، میانگین]
    new_out_unit: dict[int, tuple[decimal.Decimal, decimal.Decimal]] = {}  # ردیف → (بهایِ واحدِ قبلی، جدید)
    for g in groups:
        info = infos[g.line_id]
        st = state[(g.warehouse_id, g.bin_id)]
        qty, avg = st
        old = g.amount + prior.get((g.line_id, g.direction, g.warehouse_id), _ZERO)
        if g.direction == "IN":
            cost = old / g.quantity if g.quantity else _ZERO
            if info.doc_type == "TRANSFER" and g.line_id in new_out_unit:
                cost = new_out_unit[g.line_id][1]
            elif info.doc_type == "RETURN_IN" and info.source_line_id in new_out_unit:
                o, n = new_out_unit[info.source_line_id]
                cost = cost + (n - o)
            if qty < 0:
                avg = cost
            else:
                denom = qty + g.quantity
                avg = ((qty * avg) + (g.quantity * cost)) / denom if denom != 0 else cost
            st[0], st[1] = qty + g.quantity, _q6(avg)
            new = _money(cost * g.quantity)
        elif (g.line_id, g.warehouse_id) in alloc_keys:
            cost = avg if avg else (_ZERO if qty >= g.quantity else (old / g.quantity if g.quantity else _ZERO))
            st[0] = qty - g.quantity
            new = _money(cost * g.quantity)
            new_out_unit[g.line_id] = ((old / g.quantity) if g.quantity else _ZERO, cost)
            res.allocation_updates[(g.line_id, g.warehouse_id)] = [
                (None, g.quantity, cost, "PENDING" if (g.line_id, g.warehouse_id) in pending_keys and qty < g.quantity
                 else "CALCULATED")]
        else:
            # خروجِ بدونِ تخصیص (پیش از R257 یا برگشتیِ رسید): با همان بهایِ ثبت‌شده -- فرمولِ معکوسِ میانگین
            remaining = qty - g.quantity
            if remaining > 0:
                st[1] = _q6(((qty * avg) - old) / remaining)
            st[0] = remaining
            new = old
        if g.date >= date_from or new != old:
            res.lines.append(LineDelta(g.line_id, item.item_id, g.warehouse_id, g.bin_id, g.direction, info.doc_type,
                                       info.document_id, info.document_no, g.date, g.quantity, old, new))
    res.balance_updates = {k: v[1] for k, v in state.items()}
    res.ok = True
    return res


def _candidate_items(session, company_id: int, item_id: int | None, warehouse_id: int | None,
                     date_from: datetime.date) -> list[Item]:
    q = select(StockLedger.item_id).where(StockLedger.company_id == company_id, StockLedger.movement_date >= date_from)
    if item_id is not None:
        q = q.where(StockLedger.item_id == item_id)
    if warehouse_id is not None:
        q = q.where(StockLedger.warehouse_id == warehouse_id)
    ids = set(session.scalars(q.distinct()))
    flagged = select(CostAllocation.item_id).where(
        CostAllocation.company_id == company_id, CostAllocation.costing_status_code.in_(("RECALCULATION_REQUIRED", "PENDING")))
    if item_id is not None:
        flagged = flagged.where(CostAllocation.item_id == item_id)
    if warehouse_id is not None:
        flagged = flagged.where(CostAllocation.warehouse_id == warehouse_id)
    ids |= set(session.scalars(flagged.distinct()))
    return list(session.scalars(select(Item).where(Item.item_id.in_(ids or {-1})).order_by(Item.item_id)))


def _compute(session, company_id: int, item_id: int | None, warehouse_id: int | None, date_from: datetime.date,
             lock: bool) -> list[ItemResult]:
    default_method = costing_engine.company_settings(session, company_id).method
    out = []
    for item in _candidate_items(session, company_id, item_id, warehouse_id, date_from):
        method = costing_engine.effective_method(item, default_method)
        if lock:
            for (wid,) in session.execute(select(StockLedger.warehouse_id).where(StockLedger.item_id == item.item_id).distinct()):
                costing_engine.lock_item_warehouse(session, item.item_id, wid)
        if method in NOT_RECALCULATED:
            out.append(ItemResult(item.item_id, method, ok=False, message=NOT_RECALCULATED[method]))
        elif strategies.is_layer_method(method):
            out.append(_replay_layers(session, item, method, date_from, lock))
        else:
            out.append(_replay_average(session, item, date_from))
    return out


def preview(company_id: int, item_id: int | None = None, warehouse_id: int | None = None,
            date_from: datetime.date | None = None) -> list[ItemResult]:
    """پیش‌نمایش (بدونِ تغییر): اختلافِ هر ردیف و کالاهایی که بازمحاسبه نمی‌شوند با علت."""
    with new_session() as session:
        return _compute(session, company_id, item_id, warehouse_id, date_from or datetime.date(1900, 1, 1), lock=False)


def _je_lines(session, company_id: int, results: list[ItemResult], description: str):
    from peecha.db.models.accounting import DetailAccount
    from peecha.db.models.inventory import InventoryAccountMapping
    from peecha.services import detail_dimensions as dimensions_service
    from peecha.services import inventory_engine
    from peecha.services import journal_entries as je_service

    amounts: dict[tuple[str, int | None], decimal.Decimal] = defaultdict(lambda: _ZERO)  # (نقش، تفصیلیِ کالا) → بدهکار(+)
    for r in results:
        item = session.get(Item, r.item_id)
        detail = item.item_detail_account_id
        for ln in r.changed:
            if ln.doc_type in _NO_JE_TYPES:
                continue
            if ln.direction == "OUT":
                role = _EXPENSE_ROLE.get(ln.doc_type)
                if role is None:  # برگشت به تامین‌کننده و سایر: مغایرتِ بها
                    role = "INVENTORY_COST_VARIANCE" if inventory_engine.get_account_mapping(
                        company_id, "INVENTORY_COST_VARIANCE") is not None else "INVENTORY_ADJUSTMENT_LOSS"
                amounts[(role, detail)] += ln.delta
                amounts[("INVENTORY_ASSET", detail)] -= ln.delta
            else:
                amounts[("INVENTORY_ASSET", detail)] += ln.delta
                amounts[(_EXPENSE_ROLE.get(ln.doc_type, "INVENTORY_ADJUSTMENT_GAIN"), detail)] -= ln.delta
    item_dim = dimensions_service.get_specialized_dimension_type_id(company_id, dimensions_service.INVENTORY_ITEM_CODE)
    lines = []
    for (role, detail), amount in amounts.items():
        if amount == 0:
            continue
        account_id = inventory_engine._resolve_role_account(session, company_id, role)
        details = {}
        mapping = session.get(InventoryAccountMapping, (company_id, role))
        if mapping is not None and mapping.detail_account_id is not None:
            fixed = session.get(DetailAccount, mapping.detail_account_id)
            if fixed is not None:
                details[fixed.dimension_type_id] = fixed.detail_account_id
        if detail is not None and any(r.dimension_type_id == item_dim
                                      for r in dimensions_service.get_required_dimensions_for_account(account_id)):
            details[item_dim] = detail
        lines.append(je_service.LineInput(account_id=account_id, description=description,
                                          debit=amount if amount > 0 else _ZERO, credit=-amount if amount < 0 else _ZERO,
                                          details=details))
    return lines


def recalculate(company_id: int, user_id: int | None, *, item_id: int | None = None, warehouse_id: int | None = None,
                date_from: datetime.date | None = None, posting_date: datetime.date | None = None,
                reason: str | None = None) -> CostRecalculationRun | None:
    """اعمالِ بازمحاسبه: سندِ حسابداریِ اصلاحی (تاریخِ ثبت)، لاگِ اصلاحِ بها، به‌روزرسانیِ لایه/تخصیص/مانده، Audit.
    None یعنی اختلافی نبود (فقط وضعیتِ «نیازمندِ بازمحاسبه» پاک می‌شود)."""
    from peecha.services import audit as audit_service
    from peecha.services import journal_entries as je_service

    date_from = date_from or datetime.date(1900, 1, 1)
    posting_date = posting_date or datetime.date.today()
    with new_session() as session:
        results = [r for r in _compute(session, company_id, item_id, warehouse_id, date_from, lock=True) if r.ok]
        changed = [ln for r in results for ln in r.changed]
        description = f"بازمحاسبهٔ بهایِ تمام‌شده{(' -- ' + reason) if reason else ''}"
        je_lines = _je_lines(session, company_id, results, description) if changed else []
        journal_entry_id = None
        if je_lines:
            # سندِ حسابداری در تراکنشِ خودش؛ اگر رد شود، هیچ تغییری در بها اعمال نمی‌شود
            journal_entry_id = je_service.create_journal_entry(
                company_id, user_id, posting_date, description, je_lines, entry_type_code="INVENTORY").journal_entry_id
        run = None
        if changed:
            run = CostRecalculationRun(
                company_id=company_id, item_id=item_id, warehouse_id=warehouse_id, date_from=date_from,
                posting_date=posting_date, reason=reason, items_count=len({ln.item_id for ln in changed}),
                lines_count=len(changed), total_delta=sum((ln.delta for ln in changed if ln.direction == "OUT"), _ZERO),
                journal_entry_id=journal_entry_id, created_by_user_id=user_id)
            session.add(run)
            session.flush()
        for r in results:
            _apply(session, company_id, r, run, posting_date)
        if run is not None:
            audit_service.log_activity(
                session, company_id=company_id, user_id=user_id, entity_type="CostRecalculation", entity_id=run.run_id,
                action="CREATE", changes={"item_id": item_id, "warehouse_id": warehouse_id, "date_from": date_from.isoformat(),
                                          "lines": len(changed), "total_delta": str(run.total_delta), "reason": reason,
                                          "journal_entry_id": journal_entry_id})
        session.commit()
        if run is not None:
            session.refresh(run)
            session.expunge(run)
        return run


def _apply(session, company_id: int, r: ItemResult, run: CostRecalculationRun | None, posting_date: datetime.date) -> None:
    changed = r.changed
    for ln in changed:
        session.add(CostRecalculationLine(
            run_id=run.run_id, stock_document_line_id=ln.stock_line_id, item_id=ln.item_id, warehouse_id=ln.warehouse_id,
            bin_location_id=ln.bin_location_id, movement_direction=ln.direction, costing_method_code=r.method,
            quantity_base=ln.quantity, old_amount=ln.old_amount, new_amount=ln.new_amount))
        sign = -1 if ln.direction == "OUT" else 1
        session.add(CostAdjustmentLog(
            company_id=company_id, item_id=ln.item_id, warehouse_id=ln.warehouse_id, adjusted_on=posting_date,
            costing_method=RECALC_TAG, unit_cost_delta=_q6(ln.delta / ln.quantity) if ln.quantity else _ZERO,
            quantity_remaining=_ZERO, quantity_consumed=ln.quantity if ln.direction == "OUT" else _ZERO,
            inventory_value_delta=sign * ln.delta, variance_value_delta=ln.delta if ln.direction == "OUT" else _ZERO))
    note = f"بازمحاسبه #{run.run_id}" if run is not None else None
    for layer_id, (remaining, cost) in r.layer_updates.items():
        layer = session.get(CostLayer, layer_id)
        layer.remaining_quantity, layer.unit_cost = remaining, cost
        layer.status_code = "CONSUMED" if remaining == 0 else "OPEN"
    for (line_id, wh), rows in r.allocation_updates.items():
        existing = list(session.scalars(select(CostAllocation).where(
            CostAllocation.stock_document_line_id == line_id, CostAllocation.warehouse_id == wh)
            .order_by(CostAllocation.allocation_id)))
        template = existing[0]
        # تخصیص دادهٔ مشتقِ موتورِ بهاست؛ سابقهٔ مبلغِ قبلی در cost_recalculation_lines می‌ماند
        for extra in existing[len(rows):]:
            session.delete(extra)
        for i, (sim, qty, cost, status) in enumerate(rows):
            a = existing[i] if i < len(existing) else CostAllocation(
                company_id=company_id, stock_document_line_id=line_id, item_id=r.item_id, warehouse_id=wh,
                costing_method_code=r.method, movement_date=template.movement_date)
            a.cost_layer_id = sim.cost_layer_id if sim is not None else None
            a.quantity_base, a.unit_cost, a.costing_status_code = qty, cost, status
            if note and line_id in {ln.stock_line_id for ln in changed}:
                a.note = note
            elif a.note and a.note.startswith("سندِ عقب‌دار"):
                a.note = None
            if a not in existing:
                session.add(a)
    if strategies.is_layer_method(r.method):
        for wid in {s for s in session.scalars(select(CostLayer.warehouse_id).where(CostLayer.item_id == r.item_id).distinct())}:
            costing_engine.sync_balance_average(session, r.item_id, wid)
    else:
        for (wid, bin_id), avg in r.balance_updates.items():
            for bal in session.scalars(select(StockBalance).where(
                    StockBalance.item_id == r.item_id, StockBalance.warehouse_id == wid, StockBalance.bin_location_id == bin_id,
                    StockBalance.batch_id.is_(None))):
                bal.average_unit_cost = avg


def flagged_count(company_id: int) -> int:
    with new_session() as session:
        return session.scalar(select(func.count()).select_from(CostAllocation).where(
            CostAllocation.company_id == company_id, CostAllocation.costing_status_code == "RECALCULATION_REQUIRED")) or 0


def list_runs(company_id: int, limit: int = 50) -> list[CostRecalculationRun]:
    with new_session() as session:
        rows = list(session.scalars(select(CostRecalculationRun).where(CostRecalculationRun.company_id == company_id)
                                    .order_by(CostRecalculationRun.run_id.desc()).limit(limit)))
        for row in rows:
            session.expunge(row)
        return rows
