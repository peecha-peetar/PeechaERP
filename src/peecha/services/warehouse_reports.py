"""گزارش‌ها و تحلیل انبار — R246 (فقط خواندنی).

همان موتور گزارش خرید/فروش/حسابداری (ReportDef/ReportResult و صفحهٔ عمومی) با side="INVENTORY".
منابع: inv.stock_balance (ماندهٔ جاری و ارزش آن — همان مبنای حسابداری و داشبورد)، inv.stock_ledger
(گردش و ماندهٔ تاریخی)، کاردکس موجود inventory_engine.list_item_ledger، سیاست سفارش و مصرف از
purchase_reports_ext، بچ/سریال/امانی از lot_tracking و انبارگردانی از inv.cycle_count_*.
هیچ سند، مانده یا بهایی نوشته یا اصلاح نمی‌شود.

تعریف‌ها (قرارداد گزارش، نه منطق عملیاتی):
- قرنطینه = موجودی انبارهای نوع QUARANTINE؛ مسدود = انبارهای نوع SCRAP یا انبار غیرفعال؛
  امانی = موجودی امانی تامین‌کننده طبق lot_movements (همان «پیگیری امانی»).
- رزرو = inv.stock_balance.quantity_reserved و inv.stock_reservations؛ آزاد = موجودی − رزرو.
- مصرف/فروش = خروج اسناد ISSUE (همان مبنای گزارش‌های نقطهٔ سفارش و راکد).
"""

from __future__ import annotations

import datetime
import decimal
import statistics
from collections import defaultdict
from types import SimpleNamespace

import jdatetime
from sqlalchemy import case, func, select

from peecha.db.base import new_session
from peecha.db.models.commercial import CommercialDocument
from peecha.db.models.inventory import (
    BinLocation, Brand, CycleCountLine, CycleCountSession, ItemCategory, ItemUomConversion, SerialMovement, SerialNumber,
    StockBalance, StockDocument, StockDocumentLine, StockLedger, StockReservation, Warehouse,
)
from peecha.db.models.security import User
from peecha.services import purchase_reports as base
from peecha.services.purchase_reports import DATE, DAYS, INT, MONEY, PERCENT, QTY, TEXT, ReportDef, ReportResult

_ZERO = decimal.Decimal(0)
_Q2 = decimal.Decimal("0.01")
_EPOCH = datetime.date(1900, 1, 1)
STOCK_REF = "STOCK:"  # ref = (stock_document_id, "STOCK:<نوع>") برایِ بازکردنِ سندِ انبار

DOC_TYPE_TITLES = {
    "RECEIPT": "رسید", "ISSUE": "حواله", "TRANSFER": "انتقال", "RETURN_IN": "برگشت از فروش",
    "RETURN_OUT": "برگشت به تامین‌کننده", "ADJUSTMENT": "اصلاح موجودی", "CONSIGNMENT_IN": "امانی ورودی",
    "CONSIGN_RETURN": "برگشت امانی",
}
STATUS_TITLES = {"DRAFT": "پیش‌نویس", "CONFIRMED": "تاییدشده", "POSTED": "ثبت نهایی", "CANCELLED": "لغوشده"}
# دسته‌هایِ کارتکس (ترتیبِ فرمولِ «اول دوره + ... = پایانِ دوره»)
MOVE_CATEGORIES = (
    ("RECEIPT", "رسید خرید/ورود", 1), ("PURCHASE_RETURN", "برگشت به تامین‌کننده", -1),
    ("PRODUCTION_RECEIPT", "رسید تولید", 1), ("CUSTOMER_RETURN", "برگشت از فروش", 1), ("SALE", "فروش", -1),
    ("ISSUE", "حواله/مصرف", -1), ("PRODUCTION_CONSUMPTION", "مصرف تولید", -1), ("TRANSFER_OUT", "انتقال خروجی", -1),
    ("TRANSFER_IN", "انتقال ورودی", 1), ("ADJUST_IN", "اصلاح موجودی (افزایش)", 1), ("ADJUST_OUT", "اصلاح موجودی (کاهش)", -1),
    ("CONSIGN_IN", "امانی ورودی", 1), ("CONSIGN_OUT", "برگشت امانی", -1), ("OTHER_IN", "سایر ورودی", 1),
    ("OTHER_OUT", "سایر خروجی", -1), ("COST_ADJUST", "اصلاح بهای خرید (تعدیل ارزش)", 1),
)
CATEGORY_TITLES = {code: title for code, title, _s in MOVE_CATEGORIES}
_QUARANTINE_TYPES = ("QUARANTINE",)
_BLOCKED_TYPES = ("SCRAP",)


def category_of(doc_type: str, direction: str, commercial_type: str | None) -> str:
    """دستهٔ کاردکس از نوع سند انبار و (در صورت وجود) نوع سند بازرگانی مبدا."""
    if doc_type == "RECEIPT":
        return "RECEIPT" if direction == "IN" else "OTHER_OUT"
    if doc_type == "RETURN_OUT":
        return "PURCHASE_RETURN"
    if doc_type == "RETURN_IN":
        return "CUSTOMER_RETURN"
    if doc_type == "ISSUE":
        if direction == "IN":
            return "OTHER_IN"
        return "SALE" if (commercial_type or "").startswith("SALES") else "ISSUE"
    if doc_type == "TRANSFER":
        return "TRANSFER_IN" if direction == "IN" else "TRANSFER_OUT"
    if doc_type == "ADJUSTMENT":
        return "ADJUST_IN" if direction == "IN" else "ADJUST_OUT"
    if doc_type == "CONSIGNMENT_IN":
        return "CONSIGN_IN" if direction == "IN" else "CONSIGN_OUT"
    if doc_type == "CONSIGN_RETURN":
        return "CONSIGN_OUT" if direction == "OUT" else "CONSIGN_IN"
    return "OTHER_IN" if direction == "IN" else "OTHER_OUT"


# ---------------------------------------------------------------------
# داده‌هایِ پایه (هر کدام یک کوئریِ تجمیعی -- بدونِ N+1)
# ---------------------------------------------------------------------
def _meta(company_id: int) -> SimpleNamespace:
    ctx = base._ctx(company_id)
    with new_session() as session:
        whs = {w.warehouse_id: SimpleNamespace(
            warehouse_id=w.warehouse_id, code=w.code, name=w.name, type=w.warehouse_type_code, branch_id=w.branch_id,
            is_active=w.is_active, manager_user_id=w.manager_user_id,
            cap_weight=w.capacity_weight_kg if w.capacity_weight_kg is not None else w.vehicle_capacity_weight_kg,
            cap_volume=w.capacity_volume_m3 if w.capacity_volume_m3 is not None else w.vehicle_capacity_volume_m3,
            allow_negative=w.allow_negative_stock)
            for w in session.scalars(select(Warehouse).where(Warehouse.company_id == company_id))}
        categories = {c.category_id: f"{c.code} — {c.name}" for c in session.scalars(
            select(ItemCategory).where(ItemCategory.company_id == company_id))}
        brands = {b.brand_id: f"{b.code} — {b.name}" for b in session.scalars(select(Brand).where(Brand.company_id == company_id))}
        users = dict(session.execute(select(User.user_id, User.full_name)).all())
        try:
            from peecha.db.models.commercial import Branch

            branches = {b.branch_id: f"{b.code} — {b.name}" for b in session.scalars(
                select(Branch).where(Branch.company_id == company_id))}
        except ImportError:  # pragma: no cover
            branches = {}
    return SimpleNamespace(ctx=ctx, items=ctx.items, whs=whs, categories=categories, brands=brands, users=users,
                           branches=branches)


def _wh_label(m, wid) -> str:
    w = m.whs.get(wid)
    return f"{w.code} — {w.name}" if w else ""


def _item_ok(m, f, item_id: int, stock_only: bool = False) -> bool:
    item = m.items.get(item_id)
    if item is None:
        return False
    if stock_only and (not item.is_stock_tracked or item.item_kind_code == "SERVICE" or item.has_variants):
        return False
    if f.item_id is not None and item_id != f.item_id:
        return False
    if f.category_id is not None and item.category_id != f.category_id:
        return False
    return f.brand_id is None or item.brand_id == f.brand_id


def _wh_ok(m, f, wid: int | None) -> bool:
    if f.warehouse_id is not None and wid != f.warehouse_id:
        return False
    if f.branch_id is not None:
        w = m.whs.get(wid)
        return w is not None and w.branch_id == f.branch_id
    return True


def _cat(m, item_id) -> str:
    item = m.items.get(item_id)
    return m.categories.get(item.category_id, "— بدون گروه —") if item else ""


def _brand(m, item_id) -> str:
    item = m.items.get(item_id)
    return m.brands.get(item.brand_id, "— بدون برند —") if item else ""


def _balances(company_id: int) -> dict[tuple[int, int], list]:
    """[موجودی، رزرو، ارزش] به ازای (کالا، انبار) از ماندهٔ جاری."""
    with new_session() as session:
        rows = session.execute(
            select(StockBalance.item_id, StockBalance.warehouse_id, func.sum(StockBalance.quantity_on_hand),
                   func.sum(StockBalance.quantity_reserved), func.sum(StockBalance.total_value))
            .where(StockBalance.company_id == company_id).group_by(StockBalance.item_id, StockBalance.warehouse_id)).all()
    return {(i, w): [q or _ZERO, r or _ZERO, v or _ZERO] for i, w, q, r, v in rows}


def _ledger_position(company_id: int, as_of: datetime.date) -> dict[tuple[int, int], list]:
    """[موجودی، رزرو=۰، ارزش] تا پایان یک تاریخ، از دفتر انبار (برای تاریخ‌های گذشته)."""
    sign = case((StockLedger.movement_direction == "IN", 1), else_=-1)
    with new_session() as session:
        rows = session.execute(
            select(StockLedger.item_id, StockLedger.warehouse_id, func.sum(sign * StockLedger.quantity_base),
                   func.sum(sign * StockLedger.quantity_base * func.coalesce(StockLedger.unit_cost, 0)))
            .where(StockLedger.company_id == company_id, StockLedger.movement_date <= as_of)
            .group_by(StockLedger.item_id, StockLedger.warehouse_id)).all()
    out = {(i, w): [q or _ZERO, _ZERO, (v or _ZERO).quantize(_Q2)] for i, w, q, v in rows}
    for (i, w), delta in cost_adjustments(company_id, as_of).items():  # R247
        out.setdefault((i, w), [_ZERO, _ZERO, _ZERO])[2] += delta
    return out


def cost_adjustments(company_id: int, as_of: datetime.date, since: datetime.date | None = None) -> dict[tuple, decimal.Decimal]:
    """R247: جمع اصلاح بهای ثبت‌شده در inv.cost_adjustment_log به ازای (کالا، انبار) تا یک تاریخ."""
    from peecha.db.models.inventory import CostAdjustmentLog

    with new_session() as session:
        q = (select(CostAdjustmentLog.item_id, CostAdjustmentLog.warehouse_id, func.sum(CostAdjustmentLog.inventory_value_delta))
             .where(CostAdjustmentLog.company_id == company_id, CostAdjustmentLog.adjusted_on <= as_of))
        if since is not None:
            q = q.where(CostAdjustmentLog.adjusted_on >= since)
        rows = session.execute(q.group_by(CostAdjustmentLog.item_id, CostAdjustmentLog.warehouse_id)).all()
    return {(i, w): v or _ZERO for i, w, v in rows}


def position(company_id: int, f, m=None) -> tuple[dict[tuple[int, int], list], bool]:
    """موجودی (کالا، انبار) در تاریخ گزارش: امروز/آینده از ماندهٔ جاری، گذشته از دفتر انبار."""
    m = m or _meta(company_id)
    live = f.date_to >= datetime.date.today()
    data = _balances(company_id) if live else _ledger_position(company_id, f.date_to)
    return {k: v for k, v in data.items() if _item_ok(m, f, k[0]) and _wh_ok(m, f, k[1])}, live


def _position_note(live: bool) -> str:
    return ("ماندهٔ جاری (inv.stock_balance) — همان مبنای حسابداری." if live else
            "ماندهٔ تاریخی از دفتر انبار + اصلاح بهای ثبت‌شده تا همان تاریخ (از R247)؛ رزرو در آن دیده نمی‌شود.")


def movements(company_id: int, date_from: datetime.date, date_to: datetime.date, *, item_ids=None,
              direction: str | None = None) -> list[SimpleNamespace]:
    """حرکات دفتر انبار با سند، نوع سند و نوع سند بازرگانی مبدا (یک کوئری)."""
    with new_session() as session:
        q = (select(StockLedger.ledger_id, StockLedger.movement_date, StockLedger.item_id, StockLedger.warehouse_id,
                    StockLedger.bin_location_id, StockLedger.movement_direction, StockLedger.quantity_base,
                    StockLedger.unit_cost, StockDocument.stock_document_id, StockDocument.document_type_code,
                    StockDocument.document_no, StockDocument.counterparty_detail_account_id, StockDocument.created_by_user_id,
                    CommercialDocument.document_type_code)
             .join(StockDocumentLine, StockDocumentLine.line_id == StockLedger.stock_document_line_id)
             .join(StockDocument, StockDocument.stock_document_id == StockDocumentLine.stock_document_id)
             .outerjoin(CommercialDocument, CommercialDocument.stock_document_id == StockDocument.stock_document_id)
             .where(StockLedger.company_id == company_id, StockLedger.movement_date.between(date_from, date_to)))
        if item_ids is not None:
            q = q.where(StockLedger.item_id.in_(list(item_ids)))
        if direction is not None:
            q = q.where(StockLedger.movement_direction == direction)
        rows = session.execute(q.order_by(StockLedger.movement_date, StockLedger.ledger_id)).all()
    out = []
    for (lid, when, item, wh, bin_id, direct, qty, cost, doc_id, doc_type, doc_no, party, user, comm_type) in rows:
        out.append(SimpleNamespace(
            ledger_id=lid, date=when, item_id=item, warehouse_id=wh, bin_id=bin_id, direction=direct, qty=qty,
            unit_cost=cost or _ZERO, value=(qty * (cost or _ZERO)).quantize(_Q2), doc_id=doc_id, doc_type=doc_type,
            doc_no=doc_no, party=party, user_id=user, comm_type=comm_type,
            category=category_of(doc_type, direct, comm_type)))
    return out


def _consumption(company_id: int, m, f, date_from, date_to) -> list[SimpleNamespace]:
    """خروج مصرف/فروش (اسناد ISSUE) — همان مبنای گزارش‌های نقطهٔ سفارش و راکد موجود."""
    return [mv for mv in movements(company_id, date_from, date_to, direction="OUT")
            if mv.doc_type == "ISSUE" and _item_ok(m, f, mv.item_id) and _wh_ok(m, f, mv.warehouse_id)]


def _ref(doc_id: int, doc_type: str) -> tuple[int, str]:
    return (doc_id, f"{STOCK_REF}{doc_type}")


def _consignment(company_id: int) -> dict[tuple[int, int], decimal.Decimal]:
    from peecha.services import lot_tracking

    out: dict[tuple[int, int], decimal.Decimal] = defaultdict(lambda: _ZERO)
    for r in lot_tracking.list_lot_balances(company_id, consignment_only=True):
        out[(r.item_id, r.warehouse_id)] += r.quantity
    return out


def _period_key(value: datetime.date, period: str) -> str:
    j = jdatetime.date.fromgregorian(date=value)
    if period == "YEAR":
        return f"{j.year}"
    if period == "MONTH":
        return f"{j.year}/{j.month:02d}"
    if period == "WEEK":
        start = value - datetime.timedelta(days=(value.weekday() + 2) % 7)  # هفتهٔ شنبه‌تا‌جمعه
        js = jdatetime.date.fromgregorian(date=start)
        return f"{js.year}/{js.month:02d}/{js.day:02d}"
    return f"{j.year}/{j.month:02d}/{j.day:02d}"


def _pct(part, whole):
    return (decimal.Decimal(part) * 100 / whole).quantize(decimal.Decimal("0.1")) if whole else None


def _avg(value, qty):
    return (value / qty).quantize(_Q2) if qty else None


def _opt(f, key: str, default: str) -> str:
    return str(f.options.get(key) or default)


# ---------------------------------------------------------------------
# ۳) موجودی
# ---------------------------------------------------------------------
_STATUS_OPTION = ("state", "وضعیت موجودی", (("NONZERO", "دارای موجودی (غیر صفر)"), ("ALL", "همه"),
                                             ("POSITIVE", "مثبت"), ("NEGATIVE", "منفی"), ("RESERVED", "دارای رزرو")))


def stock_on_hand(company_id: int, f) -> ReportResult:
    m = _meta(company_id)
    pos, live = position(company_id, f, m)
    consign = _consignment(company_id) if live else {}
    state = _opt(f, "state", "NONZERO")
    r = ReportResult([("کد کالا", TEXT), ("نام کالا", TEXT), ("گروه", TEXT), ("برند", TEXT), ("انبار", TEXT), ("واحد اصلی", TEXT),
                      ("موجودی", QTY), ("رزرو", QTY), ("آزاد", QTY), ("قرنطینه", QTY), ("مسدود", QTY), ("امانی", QTY),
                      ("میانگین بها", MONEY), ("ارزش موجودی", MONEY)], no_total={12}, note=_position_note(live))
    for (item_id, wid), (qty, reserved, value) in sorted(pos.items(), key=lambda kv: (m.ctx.item_label(kv[0][0]), _wh_label(m, kv[0][1]))):
        if (state == "NONZERO" and qty == 0) or (state == "POSITIVE" and qty <= 0) or (state == "NEGATIVE" and qty >= 0) \
                or (state == "RESERVED" and reserved <= 0):
            continue
        item, w = m.items[item_id], m.whs.get(wid)
        quarantine = qty if w and w.type in _QUARANTINE_TYPES else _ZERO
        blocked = qty if w and (w.type in _BLOCKED_TYPES or not w.is_active) else _ZERO
        r.add([item.code, item.name or "", _cat(m, item_id), _brand(m, item_id), _wh_label(m, wid), m.ctx.base_uom(item_id),
               qty, reserved, qty - reserved, quarantine, blocked, consign.get((item_id, wid), _ZERO), _avg(value, qty), value])
    return r


def _hierarchy(company_id: int, f, levels: tuple[str, ...]) -> ReportResult:
    m = _meta(company_id)
    pos, live = position(company_id, f, m)
    labels = {"WAREHOUSE": ("انبار", lambda i, w: _wh_label(m, w)), "CATEGORY": ("گروه کالا", lambda i, w: _cat(m, i)),
              "BRAND": ("برند", lambda i, w: _brand(m, i)), "BRANCH": ("شعبه", lambda i, w: m.branches.get(
                  getattr(m.whs.get(w), "branch_id", None), "— بدون شعبه —"))}
    agg: dict[tuple, list] = defaultdict(lambda: [_ZERO, _ZERO])
    for (item_id, wid), (qty, _r, value) in pos.items():
        if qty == 0 and value == 0:
            continue
        key = tuple(labels[lv][1](item_id, wid) for lv in levels) + (m.ctx.item_label(item_id),)
        agg[key][0] += qty
        agg[key][1] += value
    total = sum((v[1] for v in agg.values()), _ZERO)
    r = ReportResult([(labels[lv][0], TEXT) for lv in levels] + [("کالا", TEXT), ("واحد", TEXT), ("موجودی", QTY),
                                                                 ("میانگین بها", MONEY), ("ارزش", MONEY), ("سهم از ارزش", PERCENT)],
                     no_total={len(levels) + 3, len(levels) + 5}, note=_position_note(live))
    item_by_label = {m.ctx.item_label(i): i for i in m.items}
    for key in sorted(agg):
        qty, value = agg[key]
        r.add(list(key) + [m.ctx.base_uom(item_by_label.get(key[-1])), qty, _avg(value, qty), value, _pct(value, total)])
    return r


def stock_by_warehouse(company_id: int, f) -> ReportResult:
    return _hierarchy(company_id, f, ("WAREHOUSE", "CATEGORY"))


def stock_by_category(company_id: int, f) -> ReportResult:
    return _hierarchy(company_id, f, ("CATEGORY",))


def stock_by_brand(company_id: int, f) -> ReportResult:
    return _hierarchy(company_id, f, ("BRAND",))


def _last_movement(company_id: int) -> dict[int, datetime.date]:
    with new_session() as session:
        return dict(session.execute(select(StockLedger.item_id, func.max(StockLedger.movement_date))
                                    .where(StockLedger.company_id == company_id).group_by(StockLedger.item_id)).all())


def zero_stock(company_id: int, f) -> ReportResult:
    m = _meta(company_id)
    pos, live = position(company_id, f, m)
    totals: dict[int, decimal.Decimal] = defaultdict(lambda: _ZERO)
    for (item_id, _w), (qty, _r, _v) in pos.items():
        totals[item_id] += qty
    last = _last_movement(company_id)
    r = ReportResult([("کالا", TEXT), ("گروه", TEXT), ("برند", TEXT), ("واحد", TEXT), ("آخرین گردش", DATE),
                      ("روز از آخرین گردش", DAYS), ("وضعیت", TEXT)], no_total={5}, note=_position_note(live))
    for item_id in sorted(m.items, key=m.ctx.item_label):
        if not _item_ok(m, f, item_id, stock_only=True) or totals.get(item_id, _ZERO) != 0:
            continue
        when = last.get(item_id)
        r.add([m.ctx.item_label(item_id), _cat(m, item_id), _brand(m, item_id), m.ctx.base_uom(item_id), when,
               (f.date_to - when).days if when else None, "تمام‌شده" if when else "هرگز موجودی نداشته"])
    return r


def negative_stock(company_id: int, f) -> ReportResult:
    """با ریزنمایی به سندی که مانده را منفی کرد: آخرین حرکتی که ماندهٔ رواگرد را از ≥۰ به <۰ برد."""
    m = _meta(company_id)
    pos, live = position(company_id, f, m)
    negatives = {k: v for k, v in pos.items() if v[0] < 0}
    r = ReportResult([("کالا", TEXT), ("انبار", TEXT), ("موجودی", QTY), ("ارزش", MONEY), ("تاریخ منفی‌شدن", DATE),
                      ("سند ایجادکننده", TEXT), ("انبار اجازهٔ منفی دارد", TEXT)], note=_position_note(live))
    causes: dict[tuple, SimpleNamespace] = {}
    if negatives:
        running: dict[tuple, decimal.Decimal] = defaultdict(lambda: _ZERO)
        for mv in movements(company_id, _EPOCH, f.date_to, item_ids={k[0] for k in negatives}):
            key = (mv.item_id, mv.warehouse_id)
            if key not in negatives:
                continue
            before = running[key]
            running[key] += mv.qty if mv.direction == "IN" else -mv.qty
            if before >= 0 > running[key]:
                causes[key] = mv
    for key, (qty, _r, value) in sorted(negatives.items(), key=lambda kv: m.ctx.item_label(kv[0][0])):
        mv = causes.get(key)
        w = m.whs.get(key[1])
        r.add([m.ctx.item_label(key[0]), _wh_label(m, key[1]), qty, value, mv.date if mv else None,
               f"{DOC_TYPE_TITLES.get(mv.doc_type, mv.doc_type)} {mv.doc_no}" if mv else "",
               "بله" if w and w.allow_negative else "خیر"], _ref(mv.doc_id, mv.doc_type) if mv else None)
    if not r.rows:
        r.note += " موجودی منفی وجود ندارد."
    return r


def _open_sales_commitments(company_id: int, m, f) -> list[tuple]:
    """(سند، ردیف، ماندهٔ تحویل‌نشده) سفارش‌های فروش باز — همان فرمول «تقاضای باز» در گزارش‌های خرید."""
    from peecha.services.purchase_reports_ext import _OPEN_ORDER_STATUSES

    pairs = base._lines(company_id, ("SALES_ORDER",), _OPEN_ORDER_STATUSES, None, m.ctx, dated=False)
    billed = base._invoiced_base_by_source_line(company_id, "SALES_INVOICE", [ln.line_id for _d, ln in pairs])
    out = []
    for doc, ln in pairs:
        remaining = ln.quantity_base - billed.get(ln.line_id, _ZERO)
        wid = ln.warehouse_id or doc.warehouse_id
        if remaining > 0 and _item_ok(m, f, ln.item_id) and _wh_ok(m, f, wid):
            out.append((doc, ln, remaining, wid))
    return out


def reserved_stock(company_id: int, f) -> ReportResult:
    m = _meta(company_id)
    bal = _balances(company_id)
    with new_session() as session:
        reservations = list(session.scalars(select(StockReservation).where(
            StockReservation.company_id == company_id, StockReservation.status_code == "ACTIVE")))
    r = ReportResult([("کالا", TEXT), ("انبار", TEXT), ("موجودی کل", QTY), ("رزرو", QTY), ("آزاد", QTY), ("منبع رزرو", TEXT),
                      ("شمارهٔ سند", TEXT), ("نوع", TEXT)], no_total={2, 4})
    for res in reservations:
        if not (_item_ok(m, f, res.item_id) and _wh_ok(m, f, res.warehouse_id)):
            continue
        qty, reserved, _v = bal.get((res.item_id, res.warehouse_id), [_ZERO, _ZERO, _ZERO])
        r.add([m.ctx.item_label(res.item_id), _wh_label(m, res.warehouse_id), qty, res.remaining_quantity_base, qty - reserved,
               res.source_type_code, str(res.source_record_id), "رزرو قطعی"])
    if _opt(f, "soft", "YES") == "YES":
        for doc, ln, remaining, wid in _open_sales_commitments(company_id, m, f):
            qty, reserved, _v = bal.get((ln.item_id, wid), [_ZERO, _ZERO, _ZERO])
            r.add([m.ctx.item_label(ln.item_id), _wh_label(m, wid), qty, remaining, qty - reserved, "سفارش فروش باز",
                   str(doc.document_no), "تعهد سفارش (غیر قطعی)"], (doc.document_id, doc.document_type_code))
    r.note = ("رزرو قطعی از inv.stock_reservations و ستون رزرو مانده؛ «تعهد سفارش» ماندهٔ فاکتورنشدهٔ سفارش‌های فروش باز است "
              "و موجودی را قفل نمی‌کند.")
    return r


def free_stock(company_id: int, f) -> ReportResult:
    m = _meta(company_id)
    bal = {k: v for k, v in _balances(company_id).items() if _item_ok(m, f, k[0]) and _wh_ok(m, f, k[1])}
    commit: dict[tuple, decimal.Decimal] = defaultdict(lambda: _ZERO)
    for _doc, ln, remaining, wid in _open_sales_commitments(company_id, m, f):
        commit[(ln.item_id, wid)] += remaining
    r = ReportResult([("کالا", TEXT), ("انبار", TEXT), ("موجودی", QTY), ("رزرو", QTY), ("قرنطینه/مسدود", QTY),
                      ("قابل‌استفاده/فروش", QTY), ("تعهد سفارش فروش", QTY), ("آزاد پس از تعهد", QTY)])
    for key in sorted(set(bal) | set(commit), key=lambda k: (m.ctx.item_label(k[0]), _wh_label(m, k[1]))):
        qty, reserved, _v = bal.get(key, [_ZERO, _ZERO, _ZERO])
        if qty == 0 and not commit.get(key):
            continue
        w = m.whs.get(key[1])
        held = qty if w and (w.type in _QUARANTINE_TYPES + _BLOCKED_TYPES or not w.is_active) else _ZERO
        usable = qty - reserved - held
        r.add([m.ctx.item_label(key[0]), _wh_label(m, key[1]), qty, reserved, held, usable, commit.get(key, _ZERO),
               usable - commit.get(key, _ZERO)])
    return r


def quarantine_stock(company_id: int, f) -> ReportResult:
    m = _meta(company_id)
    pos, live = position(company_id, f, m)
    held = {k: v for k, v in pos.items() if v[0] and (w := m.whs.get(k[1])) and (w.type in _QUARANTINE_TYPES + _BLOCKED_TYPES or not w.is_active)}
    last_in: dict[tuple, SimpleNamespace] = {}
    if held:
        for mv in movements(company_id, _EPOCH, f.date_to, item_ids={k[0] for k in held}, direction="IN"):
            if (mv.item_id, mv.warehouse_id) in held:
                last_in[(mv.item_id, mv.warehouse_id)] = mv
    r = ReportResult([("کالا", TEXT), ("انبار", TEXT), ("مقدار", QTY), ("ارزش", MONEY), ("دلیل", TEXT), ("وضعیت", TEXT),
                      ("تاریخ ورود", DATE), ("روز در قرنطینه", DAYS), ("سند ورود", TEXT)], no_total={7}, note=_position_note(live))
    for key, (qty, _r, value) in sorted(held.items(), key=lambda kv: m.ctx.item_label(kv[0][0])):
        w, mv = m.whs[key[1]], last_in.get(key)
        reason = "انبار قرنطینه" if w.type in _QUARANTINE_TYPES else ("انبار ضایعات" if w.type in _BLOCKED_TYPES else "انبار غیرفعال")
        r.add([m.ctx.item_label(key[0]), _wh_label(m, key[1]), qty, value, reason,
               "قرنطینه" if w.type in _QUARANTINE_TYPES else "مسدود", mv.date if mv else None,
               (f.date_to - mv.date).days if mv else None, f"{DOC_TYPE_TITLES.get(mv.doc_type, mv.doc_type)} {mv.doc_no}" if mv else ""],
              _ref(mv.doc_id, mv.doc_type) if mv else None)
    if not r.rows:
        r.note += " کالایی در انبار قرنطینه/ضایعات/غیرفعال نیست."
    return r


# ---------------------------------------------------------------------
# ۴) کارتکس و گردش
# ---------------------------------------------------------------------
def stock_card(company_id: int, f) -> ReportResult:
    """کاردکس کالا روی همان inventory_engine.list_item_ledger (مانده و بهای نمایشی کاردکس موجود)."""
    from peecha.services import inventory_engine as engine_service

    if f.item_id is None:
        raise ValueError("برای کاردکس ابتدا «کالا» را انتخاب کنید.")
    m = _meta(company_id)
    basis = _opt(f, "basis", "KARDEX")
    if basis == "LEDGER":
        opening_qty, opening_value, rows = _ledger_card_rows(company_id, m, f)
    else:
        rows = engine_service.list_item_ledger(company_id, f.item_id, f.warehouse_id, f.date_from, f.date_to)
        before = engine_service.list_item_ledger(company_id, f.item_id, f.warehouse_id, None, f.date_from - datetime.timedelta(days=1))
        opening_qty = before[-1].running_balance if before else _ZERO
        opening_value = before[-1].running_value_balance if before else _ZERO
    # نگاشتِ ردیف به سند (نوع، شماره، تاریخ) و نوعِ سندِ بازرگانیِ مبدا -- یک کوئری
    with new_session() as session:
        docs = session.execute(
            select(StockDocument.stock_document_id, StockDocument.document_type_code, StockDocument.document_no,
                   StockDocument.document_date, StockDocument.description, CommercialDocument.document_type_code)
            .outerjoin(CommercialDocument, CommercialDocument.stock_document_id == StockDocument.stock_document_id)
            .where(StockDocument.company_id == company_id, StockDocument.document_date.between(f.date_from, f.date_to))).all()
    doc_map = {(t, n, d): (sid, desc, ct) for sid, t, n, d, desc, ct in docs}
    unit = m.ctx.base_uom(f.item_id)
    totals: dict[str, list] = defaultdict(lambda: [_ZERO, _ZERO])
    detail = []
    for row in rows:
        sid, desc, comm_type = doc_map.get((row.document_type_code, row.document_no, row.movement_date), (None, "", None))
        direction = "IN" if row.quantity_in or getattr(row, "category", None) == "COST_ADJUST" else "OUT"
        cat = getattr(row, "category", None) or category_of(row.document_type_code, direction, comm_type)
        desc = getattr(row, "description", None) or desc
        qty = row.quantity_in or row.quantity_out
        value = row.value_in or row.value_out
        totals[cat][0] += qty
        totals[cat][1] += value
        detail.append(([row.movement_date, str(row.document_no or ""), DOC_TYPE_TITLES.get(row.document_type_code, row.document_type_code or ""),
                        CATEGORY_TITLES[cat], desc or "", row.quantity_in, row.quantity_out, row.running_balance, unit, row.unit_cost,
                        value, row.running_value_balance, row.warehouse_name,
                        m.ctx.names.get(row.counterparty_detail_account_id, "") if row.counterparty_detail_account_id else ""],
                       (sid, f"{STOCK_REF}{row.document_type_code}") if sid else None))
    closing_qty = rows[-1].running_balance if rows else opening_qty
    closing_value = rows[-1].running_value_balance if rows else opening_value
    note = (f"کالا: {m.ctx.item_label(f.item_id)} -- اول دوره {base_fmt(opening_qty)} {unit}، پایان دوره {base_fmt(closing_qty)} {unit}. "
            + ("ارزش بر مبنای دفتر انبار و اصلاح بهای ثبت‌شده — همان مبنای حسابداری و گزارش ارزش موجودی."
               if basis == "LEDGER" else
               "بها و ارزش همان کاردکس سیستم است (بهای واحد رسید با سهم مالیات ردیف برای نمایش)؛ "
               "برای مبنای حسابداری «مبنای ارزش» را «دفتر انبار» کنید."))
    if _opt(f, "view", "DETAIL") == "SUMMARY":
        r = ReportResult([("شرح", TEXT), ("علامت", TEXT), ("مقدار", QTY), ("ارزش", MONEY)], no_total={2, 3}, note=note)
        r.add(["موجودی اول دوره", "", opening_qty, opening_value])
        for code, title, sign in MOVE_CATEGORIES:
            qty, value = totals.get(code, [_ZERO, _ZERO])
            if qty or code in ("RECEIPT", "PURCHASE_RETURN", "PRODUCTION_RECEIPT", "CUSTOMER_RETURN", "SALE", "ISSUE",
                               "PRODUCTION_CONSUMPTION", "TRANSFER_OUT", "TRANSFER_IN"):
                r.add([title, "+" if sign > 0 else "−", qty, value])
        r.add(["موجودی پایان دوره", "=", closing_qty, closing_value])
        return r
    r = ReportResult([("تاریخ", DATE), ("شمارهٔ سند", TEXT), ("نوع سند", TEXT), ("نوع گردش", TEXT), ("شرح", TEXT), ("ورود", QTY),
                      ("خروج", QTY), ("موجودی", QTY), ("واحد", TEXT), ("بهای واحد", MONEY), ("ارزش حرکت", MONEY),
                      ("ماندهٔ ارزش", MONEY), ("انبار", TEXT), ("طرف حساب", TEXT)], no_total={7, 9, 10, 11}, note=note)
    r.add([f.date_from, "", "", "ماندهٔ اول دوره", "", None, None, opening_qty, unit, None, None, opening_value, "", ""])
    for cells, ref in detail:
        r.add(cells, ref)
    return r


def _ledger_card_rows(company_id: int, m, f):
    """R247: کاردکس بر مبنای دفتر انبار (بهای ثبت‌شدهٔ هر حرکت، بدون مالیات) + ردیف‌های اصلاح بها."""
    from peecha.db.models.inventory import CostAdjustmentLog

    moves = [mv for mv in movements(company_id, _EPOCH, f.date_to, item_ids={f.item_id})
             if f.warehouse_id is None or mv.warehouse_id == f.warehouse_id]
    with new_session() as session:
        q = select(CostAdjustmentLog).where(CostAdjustmentLog.company_id == company_id, CostAdjustmentLog.item_id == f.item_id,
                                            CostAdjustmentLog.adjusted_on <= f.date_to)
        if f.warehouse_id is not None:
            q = q.where(CostAdjustmentLog.warehouse_id == f.warehouse_id)
        logs = list(session.scalars(q))
    events = [(mv.date, 0, mv.ledger_id, mv) for mv in moves] + [(lg.adjusted_on, 1, lg.log_id, lg) for lg in logs]
    qty_b, value_b = _ZERO, _ZERO
    opening = None
    rows = []
    for when, kind, _id, ev in sorted(events, key=lambda e: e[:3]):
        if when >= f.date_from and opening is None:
            opening = (qty_b, value_b)
        if kind == 0:
            signed = ev.qty if ev.direction == "IN" else -ev.qty
            qty_b += signed
            value_b += ev.value if ev.direction == "IN" else -ev.value
            row = SimpleNamespace(movement_date=ev.date, document_type_code=ev.doc_type, document_no=ev.doc_no,
                                  quantity_in=ev.qty if ev.direction == "IN" else _ZERO,
                                  quantity_out=ev.qty if ev.direction == "OUT" else _ZERO, unit_cost=ev.unit_cost,
                                  value_in=ev.value if ev.direction == "IN" else _ZERO,
                                  value_out=ev.value if ev.direction == "OUT" else _ZERO,
                                  running_balance=qty_b, running_value_balance=value_b, warehouse_name=m.whs[ev.warehouse_id].name,
                                  counterparty_detail_account_id=ev.party)
        else:
            value_b += ev.inventory_value_delta
            row = SimpleNamespace(movement_date=ev.adjusted_on, document_type_code=None, document_no=None, quantity_in=_ZERO,
                                  quantity_out=_ZERO, unit_cost=ev.unit_cost_delta, value_in=ev.inventory_value_delta, value_out=_ZERO,
                                  running_balance=qty_b, running_value_balance=value_b, warehouse_name=m.whs[ev.warehouse_id].name,
                                  counterparty_detail_account_id=None, category="COST_ADJUST",
                                  description=f"اصلاح بهای واحد {base_fmt(ev.unit_cost_delta)}")
        if when >= f.date_from:
            rows.append(row)
    if opening is None:
        opening = (qty_b, value_b)
    return opening[0], opening[1], rows


def base_fmt(value) -> str:
    from peecha import numerals

    return numerals.format_money(decimal.Decimal(value), 2, None)


_PERIOD_OPTION = ("period", "دوره", (("MONTH", "ماهانه"), ("DAY", "روزانه"), ("WEEK", "هفتگی"), ("YEAR", "سالانه")))
_DOC_TYPE_OPTION = ("doc_type", "نوع سند", (("ALL", "همه"),) + tuple(DOC_TYPE_TITLES.items()))


def item_movement(company_id: int, f) -> ReportResult:
    m = _meta(company_id)
    period, by, doc_type = _opt(f, "period", "MONTH"), _opt(f, "by", "TOTAL"), _opt(f, "doc_type", "ALL")
    agg: dict[tuple, list] = defaultdict(lambda: [_ZERO, _ZERO, _ZERO, _ZERO, set()])
    for mv in movements(company_id, f.date_from, f.date_to):
        if not (_item_ok(m, f, mv.item_id) and _wh_ok(m, f, mv.warehouse_id)) or (doc_type != "ALL" and mv.doc_type != doc_type):
            continue
        key = (_period_key(mv.date, period),) + ((m.ctx.item_label(mv.item_id),) if by == "ITEM" else
                                                 (_wh_label(m, mv.warehouse_id),) if by == "WAREHOUSE" else ())
        a = agg[key]
        if mv.direction == "IN":
            a[0] += mv.qty
            a[2] += mv.value
        else:
            a[1] += mv.qty
            a[3] += mv.value
        a[4].add(mv.doc_id)
    extra = [("کالا", TEXT)] if by == "ITEM" else [("انبار", TEXT)] if by == "WAREHOUSE" else []
    r = ReportResult([("دوره", TEXT)] + extra + [("مقدار ورود", QTY), ("مقدار خروج", QTY), ("خالص مقدار", QTY),
                                                ("ارزش ورود", MONEY), ("ارزش خروج", MONEY), ("تعداد سند", INT)])
    for key in sorted(agg):
        qin, qout, vin, vout, docs = agg[key]
        r.add(list(key) + [qin, qout, qin - qout, vin, vout, len(docs)])
    return r


def movement_by_type(company_id: int, f) -> ReportResult:
    m = _meta(company_id)
    agg: dict[str, list] = defaultdict(lambda: [_ZERO, _ZERO, set(), set()])
    for mv in movements(company_id, f.date_from, f.date_to):
        if _item_ok(m, f, mv.item_id) and _wh_ok(m, f, mv.warehouse_id):
            a = agg[mv.category]
            a[0] += mv.qty
            a[1] += mv.value
            a[2].add(mv.doc_id)
            a[3].add(mv.item_id)
    r = ReportResult([("نوع گردش", TEXT), ("جهت", TEXT), ("مقدار", QTY), ("ارزش", MONEY), ("تعداد سند", INT), ("تعداد کالا", INT)],
                     no_total={2, 3, 5})
    for code, title, sign in MOVE_CATEGORIES:
        if code in agg:
            qty, value, docs, items = agg[code]
            r.add([title, "ورود" if sign > 0 else "خروج", qty, value, len(docs), len(items)])
    r.note = "مقدار و ارزش ورود و خروج با هم جمع نمی‌شوند؛ برای تراز از کاردکس یا گردش کالا استفاده کنید."
    return r


# ---------------------------------------------------------------------
# ۶) ارزش
# ---------------------------------------------------------------------
_VALUE_BY = ("by", "به تفکیک", (("WAREHOUSE", "انبار"), ("ITEM", "کالا"), ("CATEGORY", "گروه کالا"), ("BRAND", "برند"),
                                ("BRANCH", "شعبه")))


def valuation(company_id: int, f) -> ReportResult:
    m = _meta(company_id)
    pos, live = position(company_id, f, m)
    by = _opt(f, "by", "WAREHOUSE")
    label = {"WAREHOUSE": lambda i, w: _wh_label(m, w), "ITEM": lambda i, w: m.ctx.item_label(i), "CATEGORY": lambda i, w: _cat(m, i),
             "BRAND": lambda i, w: _brand(m, i),
             "BRANCH": lambda i, w: m.branches.get(getattr(m.whs.get(w), "branch_id", None), "— بدون شعبه —")}[by]
    agg: dict[str, list] = defaultdict(lambda: [_ZERO, _ZERO, set()])
    for (item_id, wid), (qty, _r, value) in pos.items():
        if qty == 0 and value == 0:
            continue
        a = agg[label(item_id, wid)]
        a[0] += qty
        a[1] += value
        a[2].add(item_id)
    total = sum((a[1] for a in agg.values()), _ZERO)
    r = ReportResult([(dict(_VALUE_BY[2])[by], TEXT), ("تعداد کالا", INT), ("مقدار", QTY), ("ارزش", MONEY), ("سهم", PERCENT)],
                     no_total={1, 2} if by != "ITEM" else {1}, note=_position_note(live))
    for key, (qty, value, items) in sorted(agg.items(), key=lambda kv: -kv[1][1]):
        r.add([key, len(items), qty, value, _pct(value, total)])
    return r


def value_trend(company_id: int, f) -> ReportResult:
    """ارزش و مقدار موجودی در پایان هر ماه (دفتر انبار)."""
    m = _meta(company_id)
    sign = case((StockLedger.movement_direction == "IN", 1), else_=-1)
    with new_session() as session:
        rows = session.execute(
            select(StockLedger.movement_date, StockLedger.item_id, StockLedger.warehouse_id, func.sum(sign * StockLedger.quantity_base),
                   func.sum(sign * StockLedger.quantity_base * func.coalesce(StockLedger.unit_cost, 0)))
            .where(StockLedger.company_id == company_id, StockLedger.movement_date <= f.date_to)
            .group_by(StockLedger.movement_date, StockLedger.item_id, StockLedger.warehouse_id)).all()
        from peecha.db.models.inventory import CostAdjustmentLog

        rows = list(rows) + [(d, i, w, _ZERO, v) for d, i, w, v in session.execute(  # R247: اصلاحِ بهایِ تاریخ‌دار
            select(CostAdjustmentLog.adjusted_on, CostAdjustmentLog.item_id, CostAdjustmentLog.warehouse_id,
                   CostAdjustmentLog.inventory_value_delta)
            .where(CostAdjustmentLog.company_id == company_id, CostAdjustmentLog.adjusted_on <= f.date_to)).all()]
    qty_b, value_b = _ZERO, _ZERO
    months: dict[str, list] = {}
    for when, item_id, wid, qty, value in sorted(rows, key=lambda r: r[0]):
        if not (_item_ok(m, f, item_id) and _wh_ok(m, f, wid)):
            continue
        qty_b += qty or _ZERO
        value_b += value or _ZERO
        if when >= f.date_from:
            months[_period_key(when, "MONTH")] = [qty_b, value_b.quantize(_Q2)]
        else:
            months["_before"] = [qty_b, value_b.quantize(_Q2)]
    r = ReportResult([("ماه", TEXT), ("موجودی پایان ماه", QTY), ("ارزش پایان ماه", MONEY), ("تغییر ارزش", MONEY)], no_total={1, 2})
    prev = months.pop("_before", [_ZERO, _ZERO])[1]
    for key in sorted(months):
        qty, value = months[key]
        r.add([key, qty, value, value - prev])
        prev = value
    r.note = "از دفتر انبار (بهای ثبت‌شدهٔ هر حرکت) + اصلاح بهای تاریخ‌دار؛ ماه بدون حرکت نمایش داده نمی‌شود."
    return r


# ---------------------------------------------------------------------
# ۷ تا ۱۴) تحلیل
# ---------------------------------------------------------------------
_AGING_BUCKETS = ((30, "۰–۳۰"), (60, "۳۱–۶۰"), (90, "۶۱–۹۰"), (180, "۹۱–۱۸۰"), (365, "۱۸۱–۳۶۵"), (None, "+۳۶۵"))


def stock_aging(company_id: int, f) -> ReportResult:
    """سن موجودی: موجودی فعلی به جدیدترین ورودها نسبت داده می‌شود (فرض «اول‌وارده اول‌صادره» برای سن)."""
    m = _meta(company_id)
    pos, live = position(company_id, f, m)
    pos = {k: v for k, v in pos.items() if v[0] > 0}
    ins: dict[tuple, list] = defaultdict(list)
    if pos:
        for mv in movements(company_id, _EPOCH, f.date_to, item_ids={k[0] for k in pos}, direction="IN"):
            ins[(mv.item_id, mv.warehouse_id)].append(mv)
    total_value = sum((v[2] for v in pos.values()), _ZERO)
    r = ReportResult([("کالا", TEXT), ("انبار", TEXT), ("مقدار", QTY), ("ارزش", MONEY), ("درصد از ارزش کل", PERCENT)]
                     + [(f"{label} روز", QTY) for _d, label in _AGING_BUCKETS] + [("میانگین سن (روز)", DAYS)],
                     no_total={4, 11}, note="مقدار هر بازه به واحد اصلی؛ " + _position_note(live))
    for key, (qty, _r, value) in sorted(pos.items(), key=lambda kv: -kv[1][2]):
        buckets = [_ZERO] * len(_AGING_BUCKETS)
        left, weighted = qty, _ZERO
        for mv in reversed(ins.get(key, [])):
            if left <= 0:
                break
            take = min(left, mv.qty)
            age = (f.date_to - mv.date).days
            idx = next(i for i, (limit, _l) in enumerate(_AGING_BUCKETS) if limit is None or age <= limit)
            buckets[idx] += take
            weighted += take * age
            left -= take
        if left > 0:  # ورودِ قبل از دفتر (افتتاحیه/مهاجرت): قدیمی‌ترین بازه
            buckets[-1] += left
        r.add([m.ctx.item_label(key[0]), _wh_label(m, key[1]), qty, value, _pct(value, total_value)] + buckets
              + [int(weighted / (qty - left)) if qty - left > 0 else None])
    return r


_SLOW_DAYS = ("days", "روز بدون خروج", (("90", "۹۰"), ("30", "۳۰"), ("60", "۶۰"), ("180", "۱۸۰"), ("365", "۳۶۵")))
_SLOW_COUNT = ("max_count", "حداکثر دفعات خروج", (("2", "۲"), ("0", "۰"), ("1", "۱"), ("5", "۵"), ("10", "۱۰")))
_SLOW_QTY = ("max_ratio", "حداکثر خروج نسبت به موجودی", (("25", "۲۵٪"), ("10", "۱۰٪"), ("50", "۵۰٪"), ("100", "۱۰۰٪")))


def _out_stats(company_id: int, m, f, date_from, date_to):
    count: dict[tuple, int] = defaultdict(int)
    qty: dict[tuple, decimal.Decimal] = defaultdict(lambda: _ZERO)
    for mv in _consumption(company_id, m, f, date_from, date_to):
        count[(mv.item_id, mv.warehouse_id)] += 1
        qty[(mv.item_id, mv.warehouse_id)] += mv.qty
    return count, qty


def _last_out(company_id: int) -> dict[tuple, datetime.date]:
    with new_session() as session:
        rows = session.execute(
            select(StockLedger.item_id, StockLedger.warehouse_id, func.max(StockLedger.movement_date))
            .join(StockDocumentLine, StockDocumentLine.line_id == StockLedger.stock_document_line_id)
            .join(StockDocument, StockDocument.stock_document_id == StockDocumentLine.stock_document_id)
            .where(StockLedger.company_id == company_id, StockLedger.movement_direction == "OUT",
                   StockDocument.document_type_code == "ISSUE")
            .group_by(StockLedger.item_id, StockLedger.warehouse_id)).all()
    return {(i, w): d for i, w, d in rows}


def slow_moving(company_id: int, f) -> ReportResult:
    """کم‌گردش: موجودی > ۰ و در N روز اخیر یا بدون خروج، یا خروج کمتر از حد دفعات/نسبت."""
    m = _meta(company_id)
    days, max_count, max_ratio = int(_opt(f, "days", "90")), int(_opt(f, "max_count", "2")), int(_opt(f, "max_ratio", "25"))
    since = f.date_to - datetime.timedelta(days=days)
    pos, live = position(company_id, f, m)
    count, qty_out = _out_stats(company_id, m, f, since, f.date_to)
    last = _last_out(company_id)
    r = ReportResult([("کالا", TEXT), ("انبار", TEXT), ("موجودی", QTY), ("ارزش", MONEY), ("آخرین خروج", DATE),
                      ("روز بدون خروج", DAYS), (f"دفعات خروج ({days} روز)", INT), (f"مقدار خروج ({days} روز)", QTY),
                      ("نسبت خروج به موجودی", PERCENT)], no_total={5, 8}, note=_position_note(live))
    for key, (qty, _r, value) in sorted(pos.items(), key=lambda kv: -kv[1][2]):
        if qty <= 0:
            continue
        ratio = _pct(qty_out.get(key, _ZERO), qty)
        if count.get(key, 0) > max_count and (ratio or 0) > max_ratio:
            continue
        when = last.get(key)
        r.add([m.ctx.item_label(key[0]), _wh_label(m, key[1]), qty, value, when, (f.date_to - when).days if when else None,
               count.get(key, 0), qty_out.get(key, _ZERO), ratio])
    return r


def dead_stock(company_id: int, f) -> ReportResult:
    """راکد: موجودی > ۰ و هیچ خروجی (از هر نوع سند خروجی) در بازه."""
    m = _meta(company_id)
    pos, live = position(company_id, f, m)
    moved = {(mv.item_id, mv.warehouse_id) for mv in movements(company_id, f.date_from, f.date_to, direction="OUT")}
    last = _last_out(company_id)
    lm = _last_movement(company_id)
    r = ReportResult([("کالا", TEXT), ("انبار", TEXT), ("موجودی", QTY), ("ارزش", MONEY), ("آخرین خروج", DATE),
                      ("آخرین گردش", DATE), ("روز راکد", DAYS)], no_total={6}, note=_position_note(live))
    for key, (qty, _r, value) in sorted(pos.items(), key=lambda kv: -kv[1][2]):
        if qty <= 0 or key in moved:
            continue
        when = last.get(key)
        r.add([m.ctx.item_label(key[0]), _wh_label(m, key[1]), qty, value, when, lm.get(key[0]),
               (f.date_to - when).days if when else (f.date_to - f.date_from).days])
    return r


def _policy_map(company_id: int) -> dict[tuple, SimpleNamespace]:
    from peecha.services.purchase_reports_ext import _policies

    return {(p.item_id, p.warehouse_id): p for p in _policies(company_id)}


_HORIZON = ("horizon", "افق تقاضا", (("90", "۹۰ روز"), ("30", "۳۰ روز"), ("60", "۶۰ روز"), ("180", "۱۸۰ روز")))
_THRESHOLD = ("threshold", "آستانه", (("20", "۲۰٪"), ("0", "۰٪"), ("10", "۱۰٪"), ("50", "۵۰٪")))


def overstock(company_id: int, f) -> ReportResult:
    """مازاد: اگر سیاست سفارش حداکثر دارد همان قاعدهٔ سیستم (موجودی > حداکثر)؛ وگرنه
    موجودی > ذخیرهٔ اطمینان (حداقل) + تقاضای افق × (۱ + آستانه)، تقاضا از میانگین مصرف بازه."""
    m = _meta(company_id)
    horizon, threshold = int(_opt(f, "horizon", "90")), decimal.Decimal(_opt(f, "threshold", "20"))
    days = max((f.date_to - f.date_from).days + 1, 1)
    pos, live = position(company_id, f, m)
    _count, used = _out_stats(company_id, m, f, f.date_from, f.date_to)
    policies = _policy_map(company_id)
    r = ReportResult([("کالا", TEXT), ("انبار", TEXT), ("موجودی", QTY), ("حد مجاز", QTY), ("مازاد", QTY), ("ارزش مازاد", MONEY),
                      ("مبنا", TEXT), ("مصرف روزانه", QTY)], no_total={3, 7}, note=_position_note(live))
    for key, (qty, _r, value) in sorted(pos.items(), key=lambda kv: m.ctx.item_label(kv[0][0])):
        if qty <= 0:
            continue
        p = policies.get(key) or policies.get((key[0], None))
        daily = used.get(key, _ZERO) / days
        if p is None and daily == 0:  # بدونِ سیاست و بدونِ تقاضا: در گزارشِ راکد/کم‌گردش دیده می‌شود
            continue
        if p is not None and p.max_qty is not None:
            limit, basis = p.max_qty, "حداکثر سیاست سفارش"
        else:
            safety = (p.min_qty or _ZERO) if p else _ZERO
            limit = (safety + daily * horizon * (1 + threshold / 100)).quantize(_Q2)
            basis = f"ذخیرهٔ اطمینان + تقاضای {horizon} روز + {threshold}٪"
        if qty > limit:
            excess = qty - limit
            r.add([m.ctx.item_label(key[0]), _wh_label(m, key[1]), qty, limit, excess, (excess * value / qty).quantize(_Q2),
                   basis, daily.quantize(_Q2)])
    return r


def stock_coverage(company_id: int, f) -> ReportResult:
    """پوشش (روز) = موجودی آزاد ÷ میانگین مصرف روزانهٔ بازه (خروج ISSUE)."""
    m = _meta(company_id)
    days = max((f.date_to - f.date_from).days + 1, 1)
    bal = {k: v for k, v in _balances(company_id).items() if _item_ok(m, f, k[0]) and _wh_ok(m, f, k[1])}
    _count, used = _out_stats(company_id, m, f, f.date_from, f.date_to)
    r = ReportResult([("کالا", TEXT), ("انبار", TEXT), ("موجودی آزاد", QTY), ("مصرف بازه", QTY), ("میانگین مصرف روزانه", QTY),
                      ("پوشش (روز)", DAYS), ("تاریخ اتمام تقریبی", DATE)], no_total={4, 5})
    for key in sorted(set(bal) | set(used), key=lambda k: (m.ctx.item_label(k[0]), _wh_label(m, k[1]))):
        qty, reserved, _v = bal.get(key, [_ZERO, _ZERO, _ZERO])
        free = qty - reserved
        if free <= 0 and not used.get(key):
            continue
        daily = (used.get(key, _ZERO) / days).quantize(decimal.Decimal("0.0001"))
        cover = int(free / daily) if daily > 0 and free > 0 else (0 if free <= 0 else None)
        r.add([m.ctx.item_label(key[0]), _wh_label(m, key[1]), free, used.get(key, _ZERO), daily, cover,
               f.date_to + datetime.timedelta(days=cover) if cover is not None else None])
    r.note = f"میانگین بر مبنای {days} روز بازه؛ پوشش خالی یعنی در بازه مصرفی نبوده است."
    return r


def reorder_report(company_id: int, f) -> ReportResult:
    """نقطهٔ سفارش برای هر سیاست کالا×انبار (یا پیش‌فرض انبار): آزاد ≤ نقطهٔ سفارش.
    مقدار پیشنهادی = (حداکثر، وگرنه نقطهٔ سفارش + مقدار سفارش) − آزاد — همان قاعدهٔ «پیشنهاد خرید»."""
    m = _meta(company_id)
    days = max((f.date_to - f.date_from).days + 1, 1)
    bal = _balances(company_id)
    _count, used = _out_stats(company_id, m, f, f.date_from, f.date_to)
    view = _opt(f, "view", "DUE")
    r = ReportResult([("کالا", TEXT), ("انبار", TEXT), ("موجودی", QTY), ("رزرو", QTY), ("آزاد", QTY), ("نقطهٔ سفارش", QTY),
                      ("ذخیرهٔ اطمینان", QTY), ("میانگین تقاضای روزانه", QTY), ("مقدار پیشنهادی", QTY), ("وضعیت", TEXT)],
                     no_total={5, 6, 7})
    for (item_id, wid), p in sorted(_policy_map(company_id).items(), key=lambda kv: m.ctx.item_label(kv[0][0])):
        if not _item_ok(m, f, item_id) or (wid is not None and not _wh_ok(m, f, wid)) or (wid is None and f.warehouse_id is not None):
            continue
        keys = [(item_id, wid)] if wid is not None else [k for k in bal if k[0] == item_id]
        qty = sum((bal.get(k, [_ZERO])[0] for k in keys), _ZERO)
        reserved = sum((bal.get(k, [_ZERO, _ZERO])[1] for k in keys), _ZERO)
        demand = sum((used.get(k, _ZERO) for k in keys), _ZERO) if wid is not None else \
            sum((v for k, v in used.items() if k[0] == item_id), _ZERO)
        free = qty - reserved
        rop = p.reorder_point_qty if p.reorder_point_qty is not None else p.min_qty
        due = rop is not None and free <= rop
        if view == "DUE" and not due:
            continue
        target = p.max_qty if p.max_qty is not None else (rop or _ZERO) + (p.reorder_qty or _ZERO)
        suggested = max(target - free, _ZERO) if due else _ZERO
        r.add([m.ctx.item_label(item_id), _wh_label(m, wid) if wid else "همهٔ انبارها", qty, reserved, free, rop, p.min_qty,
               (demand / days).quantize(_Q2), suggested, "رسیده به نقطهٔ سفارش" if due else "عادی"])
    return r


_ABC_BASIS = ("basis", "مبنا", (("VALUE", "ارزش مصرف"), ("QTY", "مقدار فروش/مصرف"), ("FREQ", "دفعات گردش")))
_ABC_CUTS = ("cuts", "مرز A/B", (("80-95", "۸۰٪ / ۹۵٪"), ("70-90", "۷۰٪ / ۹۰٪"), ("60-85", "۶۰٪ / ۸۵٪")))


def abc_classes(company_id: int, f, m=None) -> list[tuple]:
    """[(کالا، مقدار، ارزش، دفعات، شاخص، درصد تجمعی، کلاس)] -- مرتب بر اساس شاخص."""
    m = m or _meta(company_id)
    basis, (cut_a, cut_b) = _opt(f, "basis", "VALUE"), map(int, _opt(f, "cuts", "80-95").split("-"))
    stats: dict[int, list] = defaultdict(lambda: [_ZERO, _ZERO, 0])
    for mv in _consumption(company_id, m, f, f.date_from, f.date_to):
        s = stats[mv.item_id]
        s[0] += mv.qty
        s[1] += mv.value
        s[2] += 1
    metric = {"VALUE": lambda s: s[1], "QTY": lambda s: s[0], "FREQ": lambda s: decimal.Decimal(s[2])}[basis]
    total = sum((metric(s) for s in stats.values()), _ZERO)
    out, running = [], _ZERO
    for item_id, s in sorted(stats.items(), key=lambda kv: -metric(kv[1])):
        running += metric(s)
        share = _pct(running, total) or _ZERO
        prev = _pct(running - metric(s), total) or _ZERO
        cls = "A" if prev < cut_a else "B" if prev < cut_b else "C"
        out.append((item_id, s[0], s[1], s[2], metric(s), share, cls))
    return out


def abc_analysis(company_id: int, f) -> ReportResult:
    m = _meta(company_id)
    rows = abc_classes(company_id, f, m)
    total_value = sum((x[2] for x in rows), _ZERO)
    r = ReportResult([("کالا", TEXT), ("مقدار مصرف", QTY), ("ارزش مصرف", MONEY), ("دفعات گردش", INT), ("سهم از ارزش", PERCENT),
                      ("درصد تجمعی شاخص", PERCENT), ("کلاس", TEXT)], no_total={4, 5})
    for item_id, qty, value, freq, _metric, cum, cls in rows:
        r.add([m.ctx.item_label(item_id), qty, value, freq, _pct(value, total_value), cum, cls])
    r.note = "مصرف = خروج اسناد حواله/فروش در بازه؛ کالاهای بدون مصرف در فهرست نیستند."
    return r


def xyz_classes(company_id: int, f, m=None) -> dict[int, tuple]:
    """XYZ بر اساس ضریب تغییرات مصرف ماهانه: X ≤ ۰٫۵، Y ≤ ۱، Z > ۱ (ماه‌های بی‌مصرف صفر حساب می‌شوند)."""
    m = m or _meta(company_id)
    months = []
    d = f.date_from
    while d <= f.date_to:
        key = _period_key(d, "MONTH")
        if key not in months:
            months.append(key)
        d += datetime.timedelta(days=1)
    usage: dict[int, dict[str, decimal.Decimal]] = defaultdict(lambda: defaultdict(lambda: _ZERO))
    for mv in _consumption(company_id, m, f, f.date_from, f.date_to):
        usage[mv.item_id][_period_key(mv.date, "MONTH")] += mv.qty
    out = {}
    for item_id, by_month in usage.items():
        series = [float(by_month.get(k, 0)) for k in months]
        mean = statistics.fmean(series) if series else 0
        cv = (statistics.pstdev(series) / mean) if mean else None
        cls = "X" if cv is not None and cv <= 0.5 else "Y" if cv is not None and cv <= 1 else "Z"
        out[item_id] = (round(cv, 2) if cv is not None else None, cls)
    return out


def abc_xyz(company_id: int, f) -> ReportResult:
    m = _meta(company_id)
    abc = abc_classes(company_id, f, m)
    xyz = xyz_classes(company_id, f, m)
    if _opt(f, "view", "MATRIX") == "DETAIL":
        r = ReportResult([("کالا", TEXT), ("ABC", TEXT), ("XYZ", TEXT), ("ضریب تغییرات", TEXT), ("ارزش مصرف", MONEY),
                          ("مقدار مصرف", QTY), ("خانهٔ ماتریس", TEXT)])
        for item_id, qty, value, _fq, _mt, _cum, cls in abc:
            cv, x = xyz.get(item_id, (None, "Z"))
            r.add([m.ctx.item_label(item_id), cls, x, str(cv) if cv is not None else "—", value, qty, cls + x])
        return r
    cells: dict[str, list] = defaultdict(lambda: [0, _ZERO])
    for item_id, _qty, value, _fq, _mt, _cum, cls in abc:
        c = cells[cls + xyz.get(item_id, (None, "Z"))[1]]
        c[0] += 1
        c[1] += value
    r = ReportResult([("ABC", TEXT), ("X (پایدار) — تعداد", INT), ("X — ارزش", MONEY), ("Y (نوسانی) — تعداد", INT), ("Y — ارزش", MONEY),
                      ("Z (نامنظم) — تعداد", INT), ("Z — ارزش", MONEY)])
    for cls in "ABC":
        r.add([cls] + [v for x in "XYZ" for v in cells.get(cls + x, [0, _ZERO])])
    r.note = "ABC بر مبنای گزینهٔ «مبنا»؛ XYZ: ضریب تغییرات مصرف ماهانه X ≤ ۰٫۵ < Y ≤ ۱ < Z."
    return r


# ---------------------------------------------------------------------
# ۱۵ تا ۱۷ و ۲۸) شمارش، مغایرت و دقت
# ---------------------------------------------------------------------
def _count_lines(company_id: int, f, m) -> list[SimpleNamespace]:
    bal = _balances(company_id)
    with new_session() as session:
        rows = session.execute(
            select(CycleCountLine, CycleCountSession)
            .join(CycleCountSession, CycleCountSession.session_id == CycleCountLine.session_id)
            .where(CycleCountSession.company_id == company_id)).all()
    out = []
    for ln, s in rows:
        when = (ln.counted_at or s.snapshot_at or s.created_at)
        when_d = when.date() if when else None
        if not (_item_ok(m, f, ln.item_id) and _wh_ok(m, f, s.warehouse_id)):
            continue
        if when_d is not None and not (f.date_from <= when_d <= f.date_to):
            continue
        qty, _r, value = bal.get((ln.item_id, s.warehouse_id), [_ZERO, _ZERO, _ZERO])
        avg_cost = (value / qty) if qty else _ZERO
        out.append(SimpleNamespace(line=ln, session=s, date=when_d, avg_cost=avg_cost,
                                   variance=ln.variance_quantity_base if ln.counted_quantity_base is not None else None))
    return out


def inventory_variance(company_id: int, f) -> ReportResult:
    m = _meta(company_id)
    r = ReportResult([("تاریخ", DATE), ("انبار", TEXT), ("شمارش", TEXT), ("کالا", TEXT), ("موجودی سیستم", QTY), ("شمارش‌شده", QTY),
                      ("اختلاف مقدار", QTY), ("اختلاف ارزش", MONEY), ("درصد اختلاف", PERCENT), ("علت/توضیح", TEXT),
                      ("شمارشگر", TEXT), ("وضعیت", TEXT)], no_total={8})
    only_diff = _opt(f, "view", "DIFF") == "DIFF"
    for c in sorted(_count_lines(company_id, f, m), key=lambda c: (c.date or _EPOCH, c.session.session_id)):
        if c.variance is None or (only_diff and not c.variance):
            continue
        ln, s = c.line, c.session
        r.add([c.date, _wh_label(m, s.warehouse_id), s.session_code, m.ctx.item_label(ln.item_id), ln.expected_quantity_base,
               ln.counted_quantity_base, c.variance, (c.variance * c.avg_cost).quantize(_Q2),
               _pct(c.variance, abs(ln.expected_quantity_base)) if ln.expected_quantity_base else None, ln.notes or "",
               m.users.get(ln.counted_by_user_id, ""), "ثبت‌شده" if s.status_code == "POSTED" else "در حال شمارش"],
              _ref(s.resulting_stock_document_id, "ADJUSTMENT") if s.resulting_stock_document_id else None)
    r.note = "ارزش اختلاف با میانگین بهای فعلی کالا در همان انبار برآورد شده است."
    return r


def stock_counts(company_id: int, f) -> ReportResult:
    m = _meta(company_id)
    view = _opt(f, "view", "ALL")
    by_session: dict[int, list] = defaultdict(list)
    sessions = {}
    with new_session() as session:
        for s in session.scalars(select(CycleCountSession).where(CycleCountSession.company_id == company_id)):
            sessions[s.session_id] = s
        for ln in session.scalars(select(CycleCountLine).where(CycleCountLine.session_id.in_(list(sessions) or [-1]))):
            by_session[ln.session_id].append(ln)
    r = ReportResult([("شمارش", TEXT), ("انبار", TEXT), ("تاریخ", DATE), ("وضعیت", TEXT), ("ردیف‌ها", INT), ("شمارش‌شده", INT),
                      ("دارای اختلاف", INT), ("دقت", PERCENT), ("تاییدکننده", TEXT), ("سند اصلاحی", TEXT)], no_total={7})
    for sid, s in sorted(sessions.items()):
        if not _wh_ok(m, f, s.warehouse_id):
            continue
        when = (s.snapshot_at or s.created_at).date()
        if not (f.date_from <= when <= f.date_to):
            continue
        lines = by_session.get(sid, [])
        counted = [ln for ln in lines if ln.counted_quantity_base is not None]
        diff = [ln for ln in counted if ln.variance_quantity_base]
        state = "تکمیل و تایید‌شده" if s.status_code == "POSTED" else (
            "شمارش‌شده، تاییدنشده" if lines and len(counted) == len(lines) else "باز")
        code = {"تکمیل و تایید‌شده": "DONE", "شمارش‌شده، تاییدنشده": "UNAPPROVED", "باز": "OPEN"}[state]
        if view != "ALL" and view != code:
            continue
        r.add([s.session_code, _wh_label(m, s.warehouse_id), when, state, len(lines), len(counted), len(diff),
               _pct(len(counted) - len(diff), len(counted)), m.users.get(s.approved_by_user_id, ""),
               str(s.resulting_stock_document_id or "")],
              _ref(s.resulting_stock_document_id, "ADJUSTMENT") if s.resulting_stock_document_id else None)
    return r


def counter_performance(company_id: int, f) -> ReportResult:
    m = _meta(company_id)
    agg: dict[int | None, list] = defaultdict(lambda: [0, 0, _ZERO, _ZERO, []])
    for c in _count_lines(company_id, f, m):
        if c.variance is None:
            continue
        a = agg[c.line.counted_by_user_id]
        a[0] += 1
        a[1] += 1 if not c.variance else 0
        a[2] += abs(c.variance)
        a[3] += abs(c.variance * c.avg_cost)
        if c.line.counted_at and c.session.snapshot_at:
            a[4].append((c.line.counted_at - c.session.snapshot_at).total_seconds() / 3600)
    r = ReportResult([("شمارشگر", TEXT), ("ردیف شمرده", INT), ("ردیف بدون اختلاف", INT), ("دقت", PERCENT),
                      ("قدر مطلق اختلاف", QTY), ("ارزش اختلاف", MONEY), ("میانگین زمان تا شمارش (ساعت)", QTY)], no_total={3, 6})
    for uid, (n, ok, qty, value, hours) in sorted(agg.items(), key=lambda kv: -kv[1][0]):
        r.add([m.users.get(uid, "— نامشخص —"), n, ok, _pct(ok, n), qty, value.quantize(_Q2),
               decimal.Decimal(str(round(statistics.fmean(hours), 2))) if hours else None])
    return r


def cycle_count(company_id: int, f) -> ReportResult:
    m = _meta(company_id)
    agg: dict[tuple, list] = defaultdict(lambda: [0, None, _ZERO, 0, set()])
    for c in _count_lines(company_id, f, m):
        if c.variance is None:
            continue
        a = agg[(c.line.item_id, c.session.warehouse_id)]
        a[0] += 1
        a[1] = c.date if a[1] is None or (c.date and c.date > a[1]) else a[1]
        a[2] += abs(c.variance)
        a[3] += 1 if not c.variance else 0
        a[4].add(c.session.session_code)
    r = ReportResult([("کالا", TEXT), ("انبار", TEXT), ("دفعات شمارش", INT), ("آخرین شمارش", DATE), ("روز از آخرین شمارش", DAYS),
                      ("مجموع اختلاف‌های قبلی", QTY), ("دقت", PERCENT), ("برنامه‌های شمارش", TEXT)], no_total={4, 6})
    for key, (n, last, diff, ok, codes) in sorted(agg.items(), key=lambda kv: m.ctx.item_label(kv[0][0])):
        r.add([m.ctx.item_label(key[0]), _wh_label(m, key[1]), n, last, (f.date_to - last).days if last else None, diff,
               _pct(ok, n), "، ".join(sorted(codes))])
    r.note = "برنامهٔ شمارش دوره‌ای جدا در سیستم تعریف نمی‌شود؛ هر جلسهٔ انبارگردانی یک برنامه حساب شده است."
    return r


_ACC_BY = ("by", "به تفکیک", (("WAREHOUSE", "انبار"), ("USER", "اپراتور"), ("CATEGORY", "گروه کالا"), ("MONTH", "ماه")))


def inventory_accuracy(company_id: int, f) -> ReportResult:
    """دقت موجودی = ردیف‌های شمارش بدون اختلاف ÷ ردیف‌های شمارش‌شده."""
    m = _meta(company_id)
    by = _opt(f, "by", "WAREHOUSE")
    agg: dict[str, list] = defaultdict(lambda: [0, 0, _ZERO])
    for c in _count_lines(company_id, f, m):
        if c.variance is None:
            continue
        key = {"WAREHOUSE": _wh_label(m, c.session.warehouse_id), "USER": m.users.get(c.line.counted_by_user_id, "— نامشخص —"),
               "CATEGORY": _cat(m, c.line.item_id), "MONTH": _period_key(c.date, "MONTH") if c.date else "—"}[by]
        a = agg[key]
        a[0] += 1
        a[1] += 1 if not c.variance else 0
        a[2] += abs(c.variance * c.avg_cost)
    r = ReportResult([(dict(_ACC_BY[2])[by], TEXT), ("ردیف شمرده", INT), ("ردیف دقیق", INT), ("دقت موجودی", PERCENT),
                      ("ارزش اختلاف", MONEY)], no_total={3})
    for key in sorted(agg):
        n, ok, value = agg[key]
        r.add([key, n, ok, _pct(ok, n), value.quantize(_Q2)])
    total_n, total_ok = sum(a[0] for a in agg.values()), sum(a[1] for a in agg.values())
    r.note = f"دقت کل: {_pct(total_ok, total_n) if total_n else '—'}٪"
    return r


# ---------------------------------------------------------------------
# ۱۸ تا ۲۰) بچ، انقضا، سریال، امانی
# ---------------------------------------------------------------------
def _lots(company_id: int, f, m, **kw):
    from peecha.services import lot_tracking

    return [r for r in lot_tracking.list_lot_balances(company_id, item_id=f.item_id, warehouse_id=f.warehouse_id, **kw)
            if _item_ok(m, f, r.item_id) and _wh_ok(m, f, r.warehouse_id)]


def _expiry_state(expiry: datetime.date | None, as_of: datetime.date) -> str:
    if expiry is None:
        return "بدون تاریخ انقضا"
    left = (expiry - as_of).days
    if left < 0:
        return "منقضی‌شده"
    for limit in (7, 30, 60, 90):
        if left <= limit:
            return f"کمتر از {limit} روز"
    return "معتبر"


def batch_stock(company_id: int, f) -> ReportResult:
    m = _meta(company_id)
    r = ReportResult([("کالا", TEXT), ("بچ/لات", TEXT), ("تاریخ تولید", DATE), ("تاریخ انقضا", DATE), ("مقدار", QTY), ("انبار", TEXT),
                      ("محل", TEXT), ("تامین‌کننده", TEXT), ("امانی", TEXT), ("وضعیت", TEXT)])
    for row in _lots(company_id, f, m):
        if not row.batch_no:
            continue
        r.add([row.item_label, row.batch_no, row.manufacture_date, row.expiry_date, row.quantity, row.warehouse_label, "",
               row.supplier_name or "", "بله" if row.is_consignment else "خیر", _expiry_state(row.expiry_date, f.date_to)])
    r.note = "محل نگهداری برای بچ در سیستم ثبت نمی‌شود (فقط برای سریال)."
    return r


_EXPIRY_VIEW = ("window", "بازه", (("90", "تا ۹۰ روز"), ("EXPIRED", "منقضی‌شده"), ("7", "کمتر از ۷ روز"), ("30", "کمتر از ۳۰ روز"),
                                  ("60", "کمتر از ۶۰ روز")))


def expiry_report(company_id: int, f) -> ReportResult:
    m = _meta(company_id)
    window = _opt(f, "window", "90")
    bal = _balances(company_id)
    r = ReportResult([("کالا", TEXT), ("بچ/لات", TEXT), ("انبار", TEXT), ("تاریخ انقضا", DATE), ("روز مانده", DAYS), ("مقدار", QTY),
                      ("ارزش تقریبی", MONEY), ("وضعیت", TEXT)], no_total={4})
    for row in _lots(company_id, f, m):
        if row.expiry_date is None:
            continue
        left = (row.expiry_date - f.date_to).days
        if (window == "EXPIRED" and left >= 0) or (window != "EXPIRED" and (left < 0 or left > int(window))):
            continue
        qty, _r, value = bal.get((row.item_id, row.warehouse_id), [_ZERO, _ZERO, _ZERO])
        r.add([row.item_label, row.batch_no or row.serial_no or "", row.warehouse_label, row.expiry_date, left, row.quantity,
               (row.quantity * value / qty).quantize(_Q2) if qty else None, _expiry_state(row.expiry_date, f.date_to)])
    return r


def serial_report(company_id: int, f) -> ReportResult:
    m = _meta(company_id)
    with new_session() as session:
        serials = list(session.scalars(select(SerialNumber).where(SerialNumber.company_id == company_id)))
        moves: dict[int, list] = defaultdict(list)
        for mv in session.scalars(select(SerialMovement).where(SerialMovement.serial_id.in_([s.serial_id for s in serials] or [-1]))
                                  .order_by(SerialMovement.moved_at)):
            moves[mv.serial_id].append(mv)
        wanted = {mv.stock_document_line_id for ms in moves.values() for mv in ms} | {s.source_line_id for s in serials if s.source_line_id}
        line_doc = dict(session.execute(select(StockDocumentLine.line_id, StockDocumentLine.stock_document_id)
                                        .where(StockDocumentLine.line_id.in_(wanted or {-1}))).all())
        docs = {d.stock_document_id: d for d in session.scalars(select(StockDocument).where(
            StockDocument.stock_document_id.in_(set(line_doc.values()) or {-1})))} if serials else {}
        bins = dict(session.execute(select(BinLocation.bin_location_id, BinLocation.code)).all())
    status = _opt(f, "status", "ALL")
    labels = {"IN_STOCK": "در انبار", "SOLD": "فروخته‌شده", "ISSUED": "خارج‌شده", "RETURNED": "برگشتی", "SCRAPPED": "ضایعات"}
    r = ReportResult([("سریال", TEXT), ("کالا", TEXT), ("وضعیت", TEXT), ("انبار", TEXT), ("محل", TEXT), ("تاریخ ورود", DATE),
                      ("تاریخ خروج", DATE), ("سند مرتبط", TEXT), ("گارانتی تا", DATE)])
    for s in sorted(serials, key=lambda s: (m.ctx.item_label(s.item_id), s.serial_no)):
        if not _item_ok(m, f, s.item_id) or (f.warehouse_id is not None and s.current_warehouse_id != f.warehouse_id):
            continue
        if status != "ALL" and (s.status_code == "IN_STOCK") != (status == "IN_STOCK"):
            continue
        history = moves.get(s.serial_id, [])
        first_in = next((mv.moved_at.date() for mv in history if mv.to_warehouse_id), s.created_at.date() if s.created_at else None)
        last_out = next((mv.moved_at.date() for mv in reversed(history) if mv.from_warehouse_id and not mv.to_warehouse_id), None)
        doc = docs.get(line_doc.get(history[-1].stock_document_line_id)) if history else docs.get(line_doc.get(s.source_line_id))
        r.add([s.serial_no, m.ctx.item_label(s.item_id), labels.get(s.status_code, s.status_code), _wh_label(m, s.current_warehouse_id),
               bins.get(s.current_bin_location_id, ""), first_in, last_out if s.status_code != "IN_STOCK" else None,
               f"{DOC_TYPE_TITLES.get(doc.document_type_code, doc.document_type_code)} {doc.document_no}" if doc else "",
               s.warranty_expiry_date], _ref(doc.stock_document_id, doc.document_type_code) if doc else None)
    return r


def consignment_stock(company_id: int, f) -> ReportResult:
    m = _meta(company_id)
    r = ReportResult([("تامین‌کننده", TEXT), ("کالا", TEXT), ("انبار", TEXT), ("بچ/سریال", TEXT), ("مقدار", QTY)])
    for row in _lots(company_id, f, m, consignment_only=True):
        r.add([row.supplier_name or "", row.item_label, row.warehouse_label, row.batch_no or row.serial_no or "", row.quantity])
    r.note = "موجودی امانی تامین‌کنندگان که هنوز تسویه/برگشت نشده (همان دادهٔ «پیگیری امانی»)."
    return r


# ---------------------------------------------------------------------
# ۲۱ تا ۲۷) اسنادِ انبار، رسید/حواله/انتقال، بهره‌وری، ظرفیت، جایگزینی
# ---------------------------------------------------------------------
def _stock_docs(company_id: int, types: tuple[str, ...], f, m):
    with new_session() as session:
        docs = list(session.scalars(select(StockDocument).where(
            StockDocument.company_id == company_id, StockDocument.document_type_code.in_(types),
            StockDocument.document_date.between(f.date_from, f.date_to)).order_by(StockDocument.document_date)))
        stats = {sid: (n, q) for sid, n, q in session.execute(
            select(StockDocumentLine.stock_document_id, func.count(), func.sum(StockDocumentLine.quantity_base))
            .where(StockDocumentLine.stock_document_id.in_([d.stock_document_id for d in docs] or [-1]))
            .group_by(StockDocumentLine.stock_document_id)).all()}
        origin = dict(session.execute(select(CommercialDocument.stock_document_id, CommercialDocument.document_type_code)
                                      .where(CommercialDocument.stock_document_id.in_([d.stock_document_id for d in docs] or [-1]))).all())
    out = []
    for d in docs:
        wids = {d.source_warehouse_id, d.destination_warehouse_id} - {None}
        if (f.warehouse_id is not None or f.branch_id is not None) and not any(_wh_ok(m, f, w) for w in wids):
            continue
        n, q = stats.get(d.stock_document_id, (0, _ZERO))
        hours = (d.posted_at - d.created_at).total_seconds() / 3600 if d.posted_at and d.created_at else None
        out.append(SimpleNamespace(doc=d, lines=n, qty=q or _ZERO, hours=hours, origin=origin.get(d.stock_document_id)))
    return out


def _hours(value) -> decimal.Decimal | None:
    return decimal.Decimal(str(round(value, 2))) if value is not None else None


_ORIGIN_TITLES = {"PURCHASE_INVOICE": "فاکتور خرید", "PURCHASE_ORDER": "سفارش خرید", "PURCHASE_RETURN": "برگشت از خرید",
                  "SALES_INVOICE": "فاکتور فروش", "SALES_ORDER": "سفارش فروش", "SALES_RETURN": "برگشت از فروش",
                  "CONSIGNMENT_IN": "امانی ورودی", "CONSIGNMENT_OUT": "امانی خروجی"}
_DOC_VIEW = ("view", "نمایش", (("ALL", "همه"), ("OPEN", "باز (ثبت‌نشده)"), ("TODAY", "امروز"), ("POSTED", "ثبت‌شده")))


def _doc_rows(company_id: int, f, types: tuple[str, ...], title_extra: tuple = ()) -> ReportResult:
    m = _meta(company_id)
    view = _opt(f, "view", "ALL")
    r = ReportResult([("تاریخ", DATE), ("نوع", TEXT), ("شماره", TEXT), ("وضعیت", TEXT), ("انبار مبدا", TEXT), ("انبار مقصد", TEXT),
                      ("طرف حساب", TEXT), ("ردیف", INT), ("مقدار (پایه)", QTY), ("زمان ثبت تا تایید (ساعت)", QTY),
                      ("سند بازرگانی", TEXT), ("کاربر", TEXT)], no_total={9})
    today = datetime.date.today()
    for s in _stock_docs(company_id, types, f, m):
        d = s.doc
        if (view == "OPEN" and d.status_code in ("POSTED", "CANCELLED")) or (view == "TODAY" and d.document_date != today) \
                or (view == "POSTED" and d.status_code != "POSTED") or (view == "PENDING" and d.status_code in ("POSTED", "CANCELLED")):
            continue
        r.add([d.document_date, DOC_TYPE_TITLES.get(d.document_type_code, d.document_type_code), str(d.document_no),
               STATUS_TITLES.get(d.status_code, d.status_code), _wh_label(m, d.source_warehouse_id), _wh_label(m, d.destination_warehouse_id),
               m.ctx.names.get(d.counterparty_detail_account_id, "") if d.counterparty_detail_account_id else "", s.lines, s.qty,
               _hours(s.hours), _ORIGIN_TITLES.get(s.origin, s.origin or ""), m.users.get(d.created_by_user_id, "")], _ref(d.stock_document_id, d.document_type_code))
    return r


def receiving(company_id: int, f) -> ReportResult:
    r = _doc_rows(company_id, f, ("RECEIPT", "RETURN_IN", "CONSIGNMENT_IN"))
    if _opt(f, "view", "ALL") in ("ALL", "OPEN"):
        pending = base.run_report(company_id, "PENDING_RECEIPTS", base.PurchaseFilters(_EPOCH, datetime.date.today(),
                                                                                       item_id=f.item_id, category_id=f.category_id,
                                                                                       warehouse_id=f.warehouse_id))
        for row, ref in zip(pending.rows, pending.refs):
            title, no, when, party, wh, lines, qty, _days = row
            r.add([when, title, str(no), "منتظر تایید انبار", "", wh, party, lines, qty, None, title, ""], ref)
    r.note = "رسیدهای انبار + سفارش‌های خرید/امانی که منتظر تایید رسید انباردارند."
    return r


def issues(company_id: int, f) -> ReportResult:
    r = _doc_rows(company_id, f, ("ISSUE", "RETURN_OUT", "CONSIGN_RETURN"))
    if _opt(f, "view", "ALL") in ("ALL", "OPEN"):
        pending = base.run_report(company_id, "PENDING_ISSUES", base.PurchaseFilters(_EPOCH, datetime.date.today(),
                                                                                     item_id=f.item_id, category_id=f.category_id,
                                                                                     warehouse_id=f.warehouse_id, side="SALES"))
        for row, ref in zip(pending.rows, pending.refs):
            title, no, when, party, wh, lines, qty, _days = row
            r.add([when, title, str(no), "منتظر حوالهٔ انبار", wh, "", party, lines, qty, None, title, ""], ref)
    return r


def transfers(company_id: int, f) -> ReportResult:
    """انتقال‌ها؛ «در مسیر» = موجودی انبارهای نوع ترانزیت (انتقال دومرحله‌ای در سیستم جدا ثبت نمی‌شود)."""
    view = _opt(f, "view", "ALL")
    if view == "IN_TRANSIT":
        m = _meta(company_id)
        pos, live = position(company_id, f, m)
        r = ReportResult([("کالا", TEXT), ("انبار ترانزیت", TEXT), ("مقدار", QTY), ("ارزش", MONEY)], note=_position_note(live))
        for (item_id, wid), (qty, _r, value) in sorted(pos.items(), key=lambda kv: m.ctx.item_label(kv[0][0])):
            if qty and getattr(m.whs.get(wid), "type", None) == "TRANSIT":
                r.add([m.ctx.item_label(item_id), _wh_label(m, wid), qty, value])
        return r
    r = _doc_rows(company_id, dataclass_replace(f, view="PENDING" if view == "PENDING" else view), ("TRANSFER",))
    r.note = "انتقال ناقص/برگشتی در سیستم مفهوم جدا ندارد؛ برگشت انتقال با سند انتقال معکوس ثبت می‌شود."
    return r


def dataclass_replace(f, **options):
    import dataclasses

    return dataclasses.replace(f, options={**f.options, **options})


def productivity(company_id: int, f) -> ReportResult:
    """بهره‌وری: میانگین زمان ایجاد تا ثبت نهایی و ردیف در ساعت، به تفکیک نوع سند و کاربر."""
    m = _meta(company_id)
    agg: dict[tuple, list] = defaultdict(lambda: [0, 0, []])
    for s in _stock_docs(company_id, tuple(DOC_TYPE_TITLES), f, m):
        if s.doc.status_code != "POSTED":
            continue
        a = agg[(DOC_TYPE_TITLES.get(s.doc.document_type_code, s.doc.document_type_code),
                 m.users.get(s.doc.posted_by_user_id or s.doc.created_by_user_id, ""))]
        a[0] += 1
        a[1] += s.lines
        if s.hours is not None:
            a[2].append(s.hours)
    r = ReportResult([("نوع سند", TEXT), ("کاربر", TEXT), ("تعداد سند", INT), ("تعداد ردیف", INT), ("میانگین زمان (ساعت)", QTY),
                      ("ردیف در ساعت", QTY)], no_total={4, 5})
    for key in sorted(agg):
        n, lines, hours = agg[key]
        total_hours = sum(hours)
        # سندِ خودکار (صادرشده از فاکتور) در کسری از ثانیه ثبت می‌شود؛ نرخِ ساعتی برایِ آن معنا ندارد
        r.add(list(key) + [n, lines, _hours(statistics.fmean(hours)) if hours else None,
                           _hours(lines / total_hours) if total_hours >= 0.25 else None])
    r.note = ("زمان دریافت/حواله = فاصلهٔ ایجاد تا ثبت نهایی سند. زمان جانمایی/برداشت/بسته‌بندی/ارسال در سیستم ثبت نمی‌شود.")
    return r


def capacity(company_id: int, f) -> ReportResult:
    """اشغال = Σ موجودی × وزن/حجم کالا؛ ظرفیت فقط برای انبارهای خودرو در سیستم تعریف می‌شود."""
    m = _meta(company_id)
    bal = _balances(company_id)
    with new_session() as session:
        from peecha.db.models.inventory import Item

        dims = {i: (w, v) for i, w, v in session.execute(select(Item.item_id, Item.weight_kg, Item.volume_m3)
                                                       .where(Item.company_id == company_id)).all()}
    used: dict[int, list] = defaultdict(lambda: [_ZERO, _ZERO, 0, 0])
    for (item_id, wid), (qty, _r, _v) in bal.items():
        if qty <= 0:
            continue
        w, v = dims.get(item_id, (None, None))
        u = used[wid]
        u[0] += qty * (w or _ZERO)
        u[1] += qty * (v or _ZERO)
        u[2] += 1
        u[3] += 1 if (w is None and v is None) else 0
    r = ReportResult([("انبار", TEXT), ("ظرفیت وزنی (کیلوگرم)", QTY), ("اشغال وزنی", QTY), ("آزاد وزنی", QTY), ("درصد وزنی", PERCENT),
                      ("ظرفیت حجمی (مترمکعب)", QTY), ("اشغال حجمی", QTY), ("آزاد حجمی", QTY), ("درصد حجمی", PERCENT),
                      ("کالای بدون وزن/حجم", INT)], no_total={4, 8})
    for wid, w in sorted(m.whs.items(), key=lambda kv: kv[1].code):
        if not _wh_ok(m, f, wid):
            continue
        weight, volume, _n, missing = used.get(wid, [_ZERO, _ZERO, 0, 0])
        r.add([_wh_label(m, wid), w.cap_weight, weight.quantize(_Q2), (w.cap_weight - weight).quantize(_Q2) if w.cap_weight else None,
               _pct(weight, w.cap_weight) if w.cap_weight else None, w.cap_volume, volume.quantize(_Q2),
               (w.cap_volume - volume).quantize(_Q2) if w.cap_volume else None, _pct(volume, w.cap_volume) if w.cap_volume else None,
               missing])
    r.note = "ظرفیت از فرم انبار (ظرفیت وزنی/حجمی انبار، یا ظرفیت خودرو)؛ انبار بدون ظرفیت فقط اشغال را نشان می‌دهد."
    return r


def replenishment(company_id: int, f) -> ReportResult:
    """پیشنهاد جایگزینی بین انبارها (فقط پیشنهاد): انبار زیر نقطهٔ سفارش/حداقل از انبار دارای مازاد آزاد."""
    m = _meta(company_id)
    bal = _balances(company_id)
    policies = _policy_map(company_id)
    needs, surplus = [], defaultdict(list)
    for (item_id, wid), p in policies.items():
        if wid is None or not _item_ok(m, f, item_id):
            continue
        qty, reserved, _v = bal.get((item_id, wid), [_ZERO, _ZERO, _ZERO])
        free = qty - reserved
        trigger = p.reorder_point_qty if p.reorder_point_qty is not None else p.min_qty
        target = p.max_qty if p.max_qty is not None else (trigger or _ZERO) + (p.reorder_qty or _ZERO)
        if trigger is not None and free <= trigger and _wh_ok(m, f, wid):
            needs.append((item_id, wid, max(target - free, _ZERO), free))
    for (item_id, wid), (qty, reserved, _v) in bal.items():
        p = policies.get((item_id, wid))
        keep = (p.max_qty if p and p.max_qty is not None else (p.reorder_point_qty if p and p.reorder_point_qty is not None else _ZERO))
        spare = qty - reserved - keep
        w = m.whs.get(wid)
        if spare > 0 and w and w.is_active and w.type not in _QUARANTINE_TYPES + _BLOCKED_TYPES + ("VEHICLE", "TRANSIT"):
            surplus[item_id].append([wid, spare])
    r = ReportResult([("کالا", TEXT), ("انبار مبدا", TEXT), ("انبار مقصد", TEXT), ("آزاد مقصد", QTY), ("نیاز", QTY),
                      ("مقدار پیشنهادی", QTY), ("وضعیت", TEXT)])
    for item_id, wid, need, free in sorted(needs, key=lambda x: m.ctx.item_label(x[0])):
        sources = [s for s in surplus.get(item_id, []) if s[0] != wid]
        if not sources or need <= 0:
            r.add([m.ctx.item_label(item_id), "", _wh_label(m, wid), free, need, _ZERO, "منبع داخلی ندارد — خرید لازم است"])
            continue
        for s in sorted(sources, key=lambda s: -s[1]):
            if need <= 0:
                break
            take = min(need, s[1])
            s[1] -= take
            need -= take
            r.add([m.ctx.item_label(item_id), _wh_label(m, s[0]), _wh_label(m, wid), free, take + need, take, "پیشنهاد"])
    r.note = "سند انتقالی ساخته نمی‌شود؛ زمان اجرا پس از ثبت انتقال در گزارش انتقال‌ها دیده می‌شود."
    return r


def bin_stock(company_id: int, f) -> ReportResult:
    m = _meta(company_id)
    with new_session() as session:
        bins = {b.bin_location_id: b for b in session.scalars(
            select(BinLocation).join(Warehouse, Warehouse.warehouse_id == BinLocation.warehouse_id)
            .where(Warehouse.company_id == company_id))}
        rows = session.execute(select(StockBalance.item_id, StockBalance.warehouse_id, StockBalance.bin_location_id,
                                      func.sum(StockBalance.quantity_on_hand), func.sum(StockBalance.total_value))
                               .where(StockBalance.company_id == company_id)
                               .group_by(StockBalance.item_id, StockBalance.warehouse_id, StockBalance.bin_location_id)).all()
    r = ReportResult([("انبار", TEXT), ("محل", TEXT), ("نوع محل", TEXT), ("کالا", TEXT), ("موجودی", QTY), ("ارزش", MONEY)])
    for item_id, wid, bin_id, qty, value in sorted(rows, key=lambda x: (_wh_label(m, x[1]), getattr(bins.get(x[2]), "code", ""))):
        if not qty or not (_item_ok(m, f, item_id) and _wh_ok(m, f, wid)):
            continue
        b = bins.get(bin_id)
        r.add([_wh_label(m, wid), f"{b.code} — {b.name or ''}" if b else "", (b.bin_type_code or "") if b else "",
               m.ctx.item_label(item_id), qty, value])
    return r


# ---------------------------------------------------------------------
# R252: محل‌محور -- بچ به تفکیکِ محل، موج‌ها، شمارشِ محل، تأمینِ مجدد
# ---------------------------------------------------------------------
def _location_codes(company_id: int) -> dict[int, str]:
    from peecha.services import warehouse_locations as wl

    with new_session() as session:
        rows = session.execute(select(BinLocation, Warehouse.code).join(Warehouse, Warehouse.warehouse_id == BinLocation.warehouse_id)
                               .where(Warehouse.company_id == company_id)).all()
    return {b.bin_location_id: wl.display_code(b, wcode) for b, wcode in rows}


def bin_batch_stock(company_id: int, f) -> ReportResult:
    from peecha.services import inventory_locations as locations_service
    from peecha.services import warehouse_locations as wl

    m, codes = _meta(company_id), _location_codes(company_id)
    as_of = f.date_to
    r = ReportResult([("انبار", TEXT), ("محل", TEXT), ("کالا", TEXT), ("بچ", TEXT), ("انقضا", DATE), ("روز مانده", INT), ("موجودی", QTY)],
                     no_total={5})
    for w in locations_service.list_warehouses(company_id):
        if not _wh_ok(m, f, w.warehouse_id):
            continue
        for (bin_id, item_id), lots in sorted(wl.bin_batches(company_id, w.warehouse_id).items(), key=lambda kv: codes.get(kv[0][0], "")):
            if not _item_ok(m, f, item_id):
                continue
            for lt in lots:
                r.add([_wh_label(m, w.warehouse_id), codes.get(bin_id, ""), m.ctx.item_label(item_id), lt.batch_no, lt.expiry_date,
                       (lt.expiry_date - as_of).days if lt.expiry_date else None, lt.quantity])
    r.note = "بچ به تفکیک محل از حرکات بچ (ستون محل، R251)؛ حرکات بدون محل در این گزارش نیستند."
    return r


def waves_report(company_id: int, f) -> ReportResult:
    from peecha.services import warehouse_operations as ops

    m, codes = _meta(company_id), _location_codes(company_id)
    status = {"OPEN": "باز", "DONE": "انجام‌شده", "CANCELLED": "لغوشده"}
    r = ReportResult([("موج", TEXT), ("انبار", TEXT), ("وضعیت", TEXT), ("مسیر (متر)", QTY), ("وظایف", INT), ("انجام‌شده", INT),
                      ("محل‌های مسیر", TEXT), ("ایجاد", DATE), ("زمان انجام (دقیقه)", QTY), ("سازنده", TEXT)], no_total={3, 8})
    for w in ops.list_waves(company_id):
        if not _wh_ok(m, f, w.warehouse_id) or not (f.date_from <= w.created_at.date() <= f.date_to):
            continue
        tasks = ops.wave_tasks(company_id, w.wave_id)
        stops = list(dict.fromkeys(codes.get(t.from_bin_location_id, "") for t in tasks if t.from_bin_location_id))
        r.add([w.wave_code, _wh_label(m, w.warehouse_id), status.get(w.status_code, w.status_code),
               decimal.Decimal(str(round(float(w.path_distance or 0) / 20, 1))), len(tasks), sum(1 for t in tasks if t.status_code == "DONE"),
               " ← ".join(stops[:12]), w.created_at.date(), _minutes(w.created_at, w.completed_at), m.users.get(w.created_by_user_id, "")])
    return r


def location_counts_report(company_id: int, f) -> ReportResult:
    from peecha.services import location_counts as lc

    m = _meta(company_id)
    r = ReportResult([("شمارش", TEXT), ("انبار", TEXT), ("وضعیت", TEXT), ("محل", TEXT), ("کالا", TEXT), ("بچ", TEXT), ("دفتری", QTY),
                      ("شمارش", QTY), ("اختلاف", QTY), ("زمان شمارش", DATE)], no_total={6, 7})
    status = {"COUNTING": "در حال شمارش", "POSTED": "نهایی‌شده", "CANCELLED": "لغوشده"}
    for s in lc.list_location_counts(company_id):
        if not _wh_ok(m, f, s.warehouse_id) or not (f.date_from <= s.created_at.date() <= f.date_to):
            continue
        for ln in lc.count_lines(company_id, s.session_id):
            if not _item_ok(m, f, ln.item_id):
                continue
            if _opt(f, "view", "ALL") == "DIFF" and not ln.variance:
                continue
            r.add([s.session_code, _wh_label(m, s.warehouse_id), status.get(s.status_code, s.status_code), ln.location_code,
                   m.ctx.item_label(ln.item_id), ln.batch_no or "", ln.expected, ln.counted, ln.variance,
                   ln.counted_at.date() if ln.counted_at else None],
                  _ref(s.resulting_stock_document_id, "ADJUSTMENT") if s.resulting_stock_document_id else None)
    return r


def replenishment_tasks(company_id: int, f) -> ReportResult:
    from peecha.services import warehouse_operations as ops
    from peecha.services.warehouse_operations import TASK_STATUSES

    m, codes = _meta(company_id), _location_codes(company_id)
    rules = {r_.rule_id: r_ for r_ in ops.list_rules(company_id)}
    r = ReportResult([("وظیفه", INT), ("انبار", TEXT), ("کالا", TEXT), ("از محل", TEXT), ("به محل", TEXT), ("حداقل/حداکثر", TEXT),
                      ("مقدار", QTY), ("انجام‌شده", QTY), ("وضعیت", TEXT), ("ایجاد", DATE), ("زمان انجام (دقیقه)", QTY)], no_total={0, 10})
    for t in _tasks(company_id, f, m, "REPLENISH"):
        rule = rules.get(t.replenishment_rule_id)
        r.add([t.task_id, _wh_label(m, t.warehouse_id), m.ctx.item_label(t.item_id), codes.get(t.from_bin_location_id, ""),
               codes.get(t.to_bin_location_id, ""), f"{rule.min_quantity.normalize()} / {rule.max_quantity.normalize()}" if rule else "",
               t.quantity_base, t.done_quantity_base, TASK_STATUSES[t.status_code], t.created_at.date(),
               _minutes(t.started_at or t.created_at, t.completed_at)],
              _ref(t.resulting_stock_document_id, "TRANSFER") if t.resulting_stock_document_id else None)
    for need in ops.replenishment_needs(company_id):
        if not (_item_ok(m, f, need.item_id) and _wh_ok(m, f, need.warehouse_id)):
            continue
        r.add([None, _wh_label(m, need.warehouse_id), m.ctx.item_label(need.item_id), "، ".join(x.location_code for x in need.sources[:3]),
               need.location_code, f"{need.rule.min_quantity.normalize()} / {need.rule.max_quantity.normalize()}", need.need, None,
               "نیاز بی‌وظیفه", None, None])
    return r


# ---------------------------------------------------------------------
# ۲۹) اطلاعاتِ پایه
# ---------------------------------------------------------------------
_WH_TYPES = {"GENERAL": "عمومی", "PROJECT": "پروژه", "PRODUCTION_LINE": "خط تولید", "QUARANTINE": "قرنطینه", "TRANSIT": "ترانزیت",
             "RAW_MATERIAL": "مواد اولیه", "FINISHED_GOODS": "محصول نهایی", "SEMI_FINISHED": "نیمه‌ساخته", "SCRAP": "ضایعات",
             "CONSIGNMENT": "امانی", "VEHICLE": "خودرو", "RETURNED": "مرجوعی"}


def md_warehouses(company_id: int, f) -> ReportResult:
    m = _meta(company_id)
    bal = _balances(company_id)
    with new_session() as session:
        bins = dict(session.execute(select(BinLocation.warehouse_id, func.count()).group_by(BinLocation.warehouse_id)).all())
    agg: dict[int, list] = defaultdict(lambda: [0, _ZERO])
    for (item_id, wid), (qty, _r, value) in bal.items():
        if qty:
            agg[wid][0] += 1
            agg[wid][1] += value
    r = ReportResult([("کد", TEXT), ("نام", TEXT), ("نوع", TEXT), ("شعبه", TEXT), ("مسئول", TEXT), ("فعال", TEXT), ("موجودی منفی مجاز", TEXT),
                      ("تعداد محل", INT), ("تعداد کالای دارای موجودی", INT), ("ارزش موجودی", MONEY)])
    for wid, w in sorted(m.whs.items(), key=lambda kv: kv[1].code):
        if not _wh_ok(m, f, wid):
            continue
        n, value = agg.get(wid, [0, _ZERO])
        r.add([w.code, w.name, _WH_TYPES.get(w.type, w.type), m.branches.get(w.branch_id, ""), m.users.get(w.manager_user_id, ""),
               "بله" if w.is_active else "خیر", "بله" if w.allow_negative else "خیر", bins.get(wid, 0), n, value])
    return r


def md_units(company_id: int, f) -> ReportResult:
    m = _meta(company_id)
    with new_session() as session:
        convs = list(session.scalars(select(ItemUomConversion).where(
            ItemUomConversion.item_id.in_([i for i in m.items if _item_ok(m, f, i)] or [-1]))))
    r = ReportResult([("کالا", TEXT), ("واحد اصلی", TEXT), ("واحد", TEXT), ("ضریب به واحد اصلی", QTY), ("پیش‌فرض خرید", TEXT),
                      ("پیش‌فرض فروش", TEXT), ("واحد انبار", TEXT), ("حداقل", QTY), ("حداکثر", QTY), ("فعال", TEXT)], no_total={3, 7, 8})
    yes = lambda b: "بله" if b else ""  # noqa: E731
    for c in sorted(convs, key=lambda c: (m.ctx.item_label(c.item_id), c.sort_order)):
        r.add([m.ctx.item_label(c.item_id), m.ctx.base_uom(c.item_id), m.ctx.uom_names.get(c.uom_id, ""), c.conversion_factor,
               yes(c.is_purchase_default), yes(c.is_sales_default), yes(c.is_inventory_unit), c.min_quantity, c.max_quantity,
               "بله" if c.is_active else "خیر"])
    return r


def md_tracked_items(company_id: int, f) -> ReportResult:
    m = _meta(company_id)
    kind = _opt(f, "kind", "ANY")
    r = ReportResult([("کالا", TEXT), ("گروه", TEXT), ("سریال", TEXT), ("بچ/لات", TEXT), ("انقضا", TEXT), ("عمر مفید (روز)", INT),
                      ("کنترل کیفیت", TEXT)], no_total={5})
    with new_session() as session:
        from peecha.db.models.inventory import Item

        shelf = dict(session.execute(select(Item.item_id, Item.shelf_life_days).where(Item.company_id == company_id)).all())
    for item_id, item in sorted(m.items.items(), key=lambda kv: m.ctx.item_label(kv[0])):
        if not _item_ok(m, f, item_id):
            continue
        flags = {"SERIAL": item.track_serial, "BATCH": item.track_batch, "EXPIRY": item.track_expiry}
        if (kind == "ANY" and not any(flags.values())) or (kind in flags and not flags[kind]):
            continue
        yes = lambda b: "✓" if b else ""  # noqa: E731
        r.add([m.ctx.item_label(item_id), _cat(m, item_id), yes(item.track_serial), yes(item.track_batch), yes(item.track_expiry),
               shelf.get(item_id), yes(item.requires_qc)])
    return r


def md_min_max(company_id: int, f) -> ReportResult:
    m = _meta(company_id)
    bal = _balances(company_id)
    r = ReportResult([("کالا", TEXT), ("انبار", TEXT), ("حداقل", QTY), ("نقطهٔ سفارش", QTY), ("حداکثر", QTY), ("مقدار سفارش", QTY),
                      ("زمان تحویل (روز)", INT), ("منبع", TEXT), ("موجودی فعلی", QTY)], no_total={2, 3, 4, 5, 6})
    for (item_id, wid), p in sorted(_policy_map(company_id).items(), key=lambda kv: m.ctx.item_label(kv[0][0])):
        if not _item_ok(m, f, item_id) or (wid is not None and not _wh_ok(m, f, wid)):
            continue
        qty = bal.get((item_id, wid), [_ZERO])[0] if wid else sum((v[0] for k, v in bal.items() if k[0] == item_id), _ZERO)
        r.add([m.ctx.item_label(item_id), _wh_label(m, wid) if wid else "همهٔ انبارها", p.min_qty, p.reorder_point_qty, p.max_qty,
               p.reorder_qty, p.lead_time_days, p.source, qty])
    return r


# ---------------------------------------------------------------------
# R247: WMS سبک (جانمایی/برداشت) و برنامهٔ شمارش
# ---------------------------------------------------------------------
def _tasks(company_id: int, f, m, task_type: str) -> list:
    from peecha.services import warehouse_operations as ops

    out = []
    for t in ops.list_tasks(company_id, task_type):
        if not (_item_ok(m, f, t.item_id) and _wh_ok(m, f, t.warehouse_id)):
            continue
        if not (f.date_from <= t.created_at.date() <= f.date_to):
            continue
        out.append(t)
    return out


def _minutes(start, end) -> decimal.Decimal | None:
    return decimal.Decimal(str(round((end - start).total_seconds() / 60, 1))) if start and end else None


def _task_source(t) -> tuple[str, tuple | None]:
    if t.source_stock_document_id:
        return f"سند انبار {t.source_stock_document_id}", None
    if t.source_commercial_document_id:
        return f"سند فروش {t.source_commercial_document_id}", None
    return "", None


def _bins(company_id: int) -> dict[int, str]:
    with new_session() as session:
        return {b: f"{c} — {n or ''}" for b, c, n in session.execute(
            select(BinLocation.bin_location_id, BinLocation.code, BinLocation.name)
            .join(Warehouse, Warehouse.warehouse_id == BinLocation.warehouse_id).where(Warehouse.company_id == company_id)).all()}


_TASK_VIEW = ("view", "نمایش", (("ALL", "همه"), ("OPEN", "در انتظار"), ("IN_PROGRESS", "در حال انجام"), ("DONE", "انجام‌شده")))


def putaway_report(company_id: int, f) -> ReportResult:
    from peecha.services.warehouse_operations import TASK_STATUSES

    m, bins, view = _meta(company_id), _bins(company_id), _opt(f, "view", "ALL")
    r = ReportResult([("وظیفه", INT), ("انبار", TEXT), ("منبع", TEXT), ("کالا", TEXT), ("مقدار", QTY), ("از محل", TEXT), ("به محل", TEXT),
                      ("وضعیت", TEXT), ("ایجاد", DATE), ("زمان انتظار تا شروع (دقیقه)", QTY), ("زمان جانمایی (دقیقه)", QTY),
                      ("اپراتور", TEXT)], no_total={0, 9, 10})
    for t in _tasks(company_id, f, m, "PUTAWAY"):
        if view != "ALL" and t.status_code != view:
            continue
        r.add([t.task_id, _wh_label(m, t.warehouse_id), _task_source(t)[0], m.ctx.item_label(t.item_id), t.quantity_base,
               bins.get(t.from_bin_location_id, ""), bins.get(t.to_bin_location_id, ""), TASK_STATUSES[t.status_code], t.created_at.date(),
               _minutes(t.created_at, t.started_at), _minutes(t.started_at, t.completed_at),
               m.users.get(t.completed_by_user_id or t.assigned_user_id, "")],
              _ref(t.resulting_stock_document_id, "TRANSFER") if t.resulting_stock_document_id
              else (_ref(t.source_stock_document_id, "RECEIPT") if t.source_stock_document_id else None))
    return r


_PICK_VIEW = ("view", "نمایش", (("ALL", "همه"), ("OPEN", "آمادهٔ برداشت"), ("IN_PROGRESS", "در حال برداشت"), ("DONE", "برداشته‌شده"),
                                 ("PARTIAL", "برداشت ناقص")))


def picking_report(company_id: int, f) -> ReportResult:
    from peecha.services.warehouse_operations import TASK_STATUSES

    m, bins, view = _meta(company_id), _bins(company_id), _opt(f, "view", "ALL")
    r = ReportResult([("وظیفه", INT), ("انبار", TEXT), ("منبع", TEXT), ("کالا", TEXT), ("مقدار درخواستی", QTY), ("برداشته‌شده", QTY),
                      ("دقت برداشت", PERCENT), ("از محل", TEXT), ("وضعیت", TEXT), ("ایجاد", DATE), ("زمان برداشت (دقیقه)", QTY),
                      ("برداشت‌کننده", TEXT)], no_total={0, 6, 10})
    for t in _tasks(company_id, f, m, "PICK"):
        partial = t.status_code == "DONE" and (t.done_quantity_base or _ZERO) != t.quantity_base
        if view == "PARTIAL" and not partial or (view not in ("ALL", "PARTIAL") and t.status_code != view):
            continue
        accuracy = (100 - abs(t.done_quantity_base - t.quantity_base) * 100 / t.quantity_base).quantize(decimal.Decimal("0.1"))             if t.status_code == "DONE" and t.quantity_base else None
        r.add([t.task_id, _wh_label(m, t.warehouse_id), _task_source(t)[0], m.ctx.item_label(t.item_id), t.quantity_base,
               t.done_quantity_base, accuracy, bins.get(t.from_bin_location_id, ""),
               "برداشت ناقص" if partial else TASK_STATUSES[t.status_code], t.created_at.date(), _minutes(t.started_at, t.completed_at),
               m.users.get(t.completed_by_user_id or t.assigned_user_id, "")],
              (t.source_commercial_document_id, "SALES_ORDER") if t.source_commercial_document_id
              else (_ref(t.source_stock_document_id, "ISSUE") if t.source_stock_document_id else None))
    return r


def wms_performance(company_id: int, f) -> ReportResult:
    """عملکرد اپراتور: وظایف انجام‌شده، میانگین زمان، ردیف در ساعت و دقت برداشت."""
    from peecha.services.warehouse_operations import TASK_TYPES

    m = _meta(company_id)
    agg: dict[tuple, list] = defaultdict(lambda: [0, [], 0, 0])
    for task_type in TASK_TYPES:
        for t in _tasks(company_id, f, m, task_type):
            if t.status_code != "DONE":
                continue
            a = agg[(TASK_TYPES[task_type], m.users.get(t.completed_by_user_id, "— نامشخص —"))]
            a[0] += 1
            minutes = _minutes(t.started_at, t.completed_at)
            if minutes is not None:
                a[1].append(minutes)
            if task_type == "PICK":
                a[2] += 1
                a[3] += 1 if t.done_quantity_base == t.quantity_base else 0
    r = ReportResult([("نوع", TEXT), ("اپراتور", TEXT), ("وظایف انجام‌شده", INT), ("میانگین زمان (دقیقه)", QTY),
                      ("ردیف در ساعت", QTY), ("دقت برداشت", PERCENT)], no_total={3, 4, 5})
    for key in sorted(agg):
        n, minutes, picks, exact = agg[key]
        total = sum(minutes, _ZERO)
        r.add(list(key) + [n, (total / len(minutes)).quantize(decimal.Decimal("0.1")) if minutes else None,
                           (decimal.Decimal(n) * 60 / total).quantize(decimal.Decimal("0.1")) if total >= 1 else None,
                           _pct(exact, picks) if picks else None])
    r.note = "زمان هر وظیفه از «شروع» تا «تکمیل» در صفحهٔ وظایف انبار؛ بسته‌بندی و ارسال جدا ثبت نمی‌شوند."
    return r


def unlocated_stock(company_id: int, f) -> ReportResult:
    """دریافت‌شده ولی جانمایی‌نشده: موجودی محل پیش‌فرض در انبارهایی که محل دیگری هم دارند + وظایف جانمایی باز."""
    from peecha.services import warehouse_operations as ops

    m = _meta(company_id)
    with new_session() as session:
        bins = session.execute(select(BinLocation.bin_location_id, BinLocation.warehouse_id, BinLocation.code)
                               .join(Warehouse, Warehouse.warehouse_id == BinLocation.warehouse_id)
                               .where(Warehouse.company_id == company_id)).all()
        rows = session.execute(select(StockBalance.item_id, StockBalance.warehouse_id, StockBalance.bin_location_id,
                                      func.sum(StockBalance.quantity_on_hand))
                               .where(StockBalance.company_id == company_id)
                               .group_by(StockBalance.item_id, StockBalance.warehouse_id, StockBalance.bin_location_id)).all()
    from peecha.services.inventory_locations import get_default_bin_location

    per_wh: dict[int, int] = defaultdict(int)
    for _bin_id, wid, _code in bins:
        per_wh[wid] += 1
    default_bins = {d.bin_location_id for d in (get_default_bin_location(w) for w in per_wh) if d}  # R253: پیش‌فرضِ انتخابی
    open_tasks: dict[tuple, decimal.Decimal] = defaultdict(lambda: _ZERO)
    for t in ops.list_tasks(company_id, "PUTAWAY"):
        if t.status_code in ("OPEN", "IN_PROGRESS"):
            open_tasks[(t.item_id, t.warehouse_id)] += t.quantity_base
    r = ReportResult([("کالا", TEXT), ("انبار", TEXT), ("موجودی در محل دریافت (پیش‌فرض)", QTY), ("وظیفهٔ جانمایی باز", QTY)])
    keys = {(i, w): q for i, w, b, q in rows if b in default_bins and q and per_wh[w] > 1}
    for key in sorted(set(keys) | set(open_tasks), key=lambda k: (m.ctx.item_label(k[0]), _wh_label(m, k[1]))):
        if _item_ok(m, f, key[0]) and _wh_ok(m, f, key[1]):
            r.add([m.ctx.item_label(key[0]), _wh_label(m, key[1]), keys.get(key, _ZERO), open_tasks.get(key, _ZERO)])
    r.note = "انبار تک‌محلی (فقط محل پیش‌فرض) جانمایی لازم ندارد و در این فهرست نیست."
    return r


def cycle_count_due(company_id: int, f) -> ReportResult:
    from peecha.services import warehouse_operations as ops

    m = _meta(company_id)
    r = ReportResult([("برنامه", TEXT), ("انبار", TEXT), ("کالا", TEXT), ("تواتر (روز)", INT), ("آخرین شمارش", DATE),
                      ("سررسید", DATE), ("روز تاخیر", DAYS), ("وضعیت", TEXT)], no_total={3, 6})
    for d in sorted(ops.due_counts(company_id, f.date_to, f.warehouse_id), key=lambda d: (d.due_date or _EPOCH, d.plan.code)):
        if not (_item_ok(m, f, d.item_id) and _wh_ok(m, f, d.warehouse_id)):
            continue
        r.add([f"{d.plan.code} — {d.plan.name}", _wh_label(m, d.warehouse_id), m.ctx.item_label(d.item_id), d.plan.frequency_days,
               d.last_count, d.due_date, d.overdue_days, "هرگز شمرده نشده" if d.last_count is None else "سررسید شده"])
    r.note = "اقلام برنامه‌های فعال شمارش دوره‌ای که شمارش بعدی‌شان رسیده است؛ شمارش با «انبارگردانی» انجام می‌شود."
    return r


# ---------------------------------------------------------------------
# فهرست
# ---------------------------------------------------------------------
_ST, _CD, _VL, _AN, _CT, _LT, _OP, _MD = ("موجودی", "کاردکس و گردش", "ارزش موجودی", "تحلیل موجودی", "شمارش و مغایرت",
                                           "بچ، انقضا و سریال", "عملیات انبار", "اطلاعات پایه")
_IF = ("item", "category", "brand", "warehouse", "branch")
_IFNW = ("item", "category", "brand")

WAREHOUSE_REPORTS: list[ReportDef] = [
    ReportDef("STOCK_ON_HAND", "موجودی لحظه‌ای", stock_on_hand, _IF,
              "موجودی، رزرو، آزاد، قرنطینه، مسدود، امانی، میانگین بها و ارزش هر کالا در هر انبار تا تاریخ گزارش.", "as_of", _ST,
              options=(_STATUS_OPTION,)),
    ReportDef("STOCK_BY_WAREHOUSE", "موجودی به تفکیک انبار", stock_by_warehouse, _IF,
              "انبار ← گروه کالا ← کالا؛ با «گروه‌بندی» جمع هر انبار/گروه را ببینید.", "as_of", _ST, default_group="انبار"),
    ReportDef("STOCK_BY_CATEGORY", "موجودی به تفکیک گروه کالا", stock_by_category, _IF, "گروه ← کالا.", "as_of", _ST,
              default_group="گروه کالا"),
    ReportDef("STOCK_BY_BRAND", "موجودی به تفکیک برند", stock_by_brand, _IF, "برند ← کالا.", "as_of", _ST, default_group="برند"),
    ReportDef("ZERO_STOCK", "کالاهای بدون موجودی", zero_stock, _IF, "کالاهای انبارداری که موجودی کلشان صفر است.", "as_of", _ST),
    ReportDef("NEGATIVE_STOCK", "موجودی منفی", negative_stock, _IF,
              "کالا×انبارهای منفی، با سندی که مانده را منفی کرد (دابل‌کلیک).", "as_of", _ST),
    ReportDef("RESERVED_STOCK", "موجودی رزروشده", reserved_stock, _IF, "رزروهای قطعی و تعهد سفارش‌های فروش باز.", "none", _ST,
              options=(("soft", "تعهد سفارش فروش", (("YES", "نمایش"), ("NO", "عدم نمایش"))),)),
    ReportDef("FREE_STOCK", "موجودی آزاد", free_stock, _IF,
              "موجودی قابل‌استفاده/فروش = موجودی − رزرو − قرنطینه/مسدود؛ و آزاد پس از تعهد سفارش‌ها.", "none", _ST),
    ReportDef("QUARANTINE_STOCK", "موجودی قرنطینه و مسدود", quarantine_stock, _IF,
              "موجودی انبارهای قرنطینه، ضایعات و غیرفعال با دلیل و سند ورود.", "as_of", _ST),
    ReportDef("CONSIGNMENT_STOCK", "موجودی امانی", consignment_stock, _IF, "موجودی امانی تامین‌کنندگان.", "none", _ST),
    ReportDef("STOCK_CARD", "کاردکس کالا", stock_card, ("item", "warehouse"),
              "اول دوره + رسید − برگشت خرید + تولید + برگشت فروش − فروش − حواله − مصرف تولید ± انتقال = پایان دوره.", group=_CD,
              options=(("view", "نمایش", (("DETAIL", "ریز حرکات"), ("SUMMARY", "خلاصهٔ فرمولی"))),
                       ("basis", "مبنای ارزش", (("KARDEX", "کاردکس سیستم (با سهم مالیات)"),
                                                 ("LEDGER", "دفتر انبار (مبنای حسابداری)"))))),
    ReportDef("ITEM_MOVEMENT", "گردش کالا (روزانه/هفتگی/ماهانه/سالانه)", item_movement, _IF,
              "ورود و خروج مقداری و ریالی در هر دوره.", group=_CD,
              options=(_PERIOD_OPTION, ("by", "تفکیک", (("TOTAL", "کل"), ("ITEM", "کالا"), ("WAREHOUSE", "انبار"))), _DOC_TYPE_OPTION)),
    ReportDef("MOVEMENT_BY_TYPE", "گردش به تفکیک نوع", movement_by_type, _IF,
              "رسید، فروش، حواله، انتقال، برگشت، اصلاح و امانی در بازه.", group=_CD),
    ReportDef("VALUATION", "ارزش موجودی", valuation, _IF,
              "ارزش موجودی به تفکیک انبار/کالا/گروه/برند/شعبه تا تاریخ — با همان بهای ثبت‌شدهٔ سیستم.", "as_of", _VL,
              options=(_VALUE_BY,)),
    ReportDef("VALUE_TREND", "روند ارزش موجودی", value_trend, _IF, "مقدار و ارزش موجودی در پایان هر ماه.", group=_VL),
    ReportDef("STOCK_AGING", "سن موجودی", stock_aging, _IF,
              "موجودی فعلی در بازه‌های ۰–۳۰ تا +۳۶۵ روز بر اساس تاریخ ورود.", "as_of", _AN),
    ReportDef("SLOW_MOVING", "کالاهای کم‌گردش", slow_moving, _IF,
              "موجودی > ۰ با خروج کم در N روز اخیر (دفعات و نسبت خروج به موجودی قابل تنظیم).", "as_of", _AN,
              options=(_SLOW_DAYS, _SLOW_COUNT, _SLOW_QTY)),
    ReportDef("DEAD_STOCK", "کالاهای راکد", dead_stock, _IF, "موجودی > ۰ و هیچ خروجی در بازه.", group=_AN),
    ReportDef("OVERSTOCK", "کالاهای مازاد", overstock, _IF,
              "موجودی بیش از حداکثر سیاست سفارش، یا ذخیرهٔ اطمینان + تقاضا + آستانه.", group=_AN, options=(_HORIZON, _THRESHOLD)),
    ReportDef("STOCK_COVERAGE", "پوشش موجودی (روز)", stock_coverage, _IF,
              "موجودی آزاد ÷ میانگین مصرف روزانهٔ بازه.", group=_AN),
    ReportDef("REORDER", "کالاهای رسیده به نقطهٔ سفارش", reorder_report, _IF,
              "سیاست سفارش هر کالا×انبار با موجودی، رزرو، آزاد، تقاضا و مقدار پیشنهادی.", group=_AN,
              options=(("view", "نمایش", (("DUE", "فقط رسیده به نقطهٔ سفارش"), ("ALL", "همه"))),)),
    ReportDef("ABC", "تحلیل ABC موجودی", abc_analysis, _IF, "طبقه‌بندی کالاها بر اساس ارزش/مقدار/دفعات مصرف.", group=_AN,
              options=(_ABC_BASIS, _ABC_CUTS)),
    ReportDef("ABC_XYZ", "ماتریس ABC–XYZ", abc_xyz, _IF, "اهمیت (ABC) در برابر ثبات تقاضا (XYZ).", group=_AN,
              options=(("view", "نمایش", (("MATRIX", "ماتریس"), ("DETAIL", "ریز کالاها"))), _ABC_BASIS, _ABC_CUTS)),
    ReportDef("VARIANCE", "مغایرت موجودی", inventory_variance, _IF,
              "موجودی سیستم در برابر شمارش، اختلاف مقدار/ارزش/درصد، علت، شمارشگر و تاریخ.", group=_CT,
              options=(("view", "نمایش", (("DIFF", "فقط دارای اختلاف"), ("ALL", "همهٔ ردیف‌های شمرده"))),)),
    ReportDef("STOCK_COUNTS", "گزارش انبارگردانی‌ها", stock_counts, ("warehouse", "branch"),
              "شمارش‌های باز، تکمیل‌شده و تاییدنشده با دقت هر شمارش.", group=_CT,
              options=(("view", "نمایش", (("ALL", "همه"), ("OPEN", "باز"), ("UNAPPROVED", "شمارش‌شده، تاییدنشده"),
                                          ("DONE", "تکمیل‌شده"))),)),
    ReportDef("COUNTER_PERFORMANCE", "عملکرد شمارشگران", counter_performance, _IF, "ردیف، دقت و اختلاف هر شمارشگر.", group=_CT),
    ReportDef("CYCLE_COUNT", "شمارش دوره‌ای", cycle_count, _IF,
              "دفعات شمارش هر کالا×انبار، آخرین شمارش، اختلاف‌های قبلی و دقت.", group=_CT),
    ReportDef("CYCLE_COUNT_DUE", "شمارش‌های سررسیدشده", cycle_count_due, _IF,
              "اقلام برنامه‌های شمارش دوره‌ای که باید شمرده شوند.", "as_of", _CT),
    ReportDef("ACCURACY", "دقت موجودی", inventory_accuracy, _IF,
              "درصد ردیف‌های شمارش بدون اختلاف به تفکیک انبار/اپراتور/گروه/ماه.", group=_CT, options=(_ACC_BY,)),
    ReportDef("BATCH_STOCK", "موجودی بچ/لات", batch_stock, _IF, "موجودی هر بچ با تاریخ تولید/انقضا، انبار و وضعیت.", "as_of", _LT),
    ReportDef("EXPIRY", "انقضای کالا", expiry_report, _IF, "منقضی‌شده و کمتر از ۷/۳۰/۶۰/۹۰ روز.", "as_of", _LT,
              options=(_EXPIRY_VIEW,)),
    ReportDef("SERIALS", "شماره‌سریال‌ها", serial_report, _IFNW + ("warehouse",),
              "وضعیت، انبار، محل، تاریخ ورود/خروج و سند مرتبط هر سریال.", "none", _LT,
              options=(("status", "وضعیت", (("ALL", "همه"), ("IN_STOCK", "در انبار"), ("OUT", "خارج‌شده"))),)),
    ReportDef("RECEIVING", "رسیدها", receiving, _IF,
              "رسیدهای امروز/باز/ثبت‌شده و سفارش‌های منتظر تایید رسید، با زمان دریافت.", group=_OP, options=(_DOC_VIEW,)),
    ReportDef("ISSUES", "حواله‌ها", issues, _IF, "حواله‌ها و سفارش‌های فروش منتظر حوالهٔ انبار.", group=_OP, options=(_DOC_VIEW,)),
    ReportDef("TRANSFERS", "انتقال‌های بین انبار", transfers, ("warehouse", "branch"),
              "انتقال‌های انجام‌شده، در انتظار و موجودی در مسیر (انبارهای ترانزیت)، با زمان انتقال.", group=_OP,
              options=(("view", "نمایش", (("ALL", "همه"), ("POSTED", "انجام‌شده"), ("PENDING", "در انتظار"),
                                          ("IN_TRANSIT", "در مسیر"))),)),
    ReportDef("REPLENISHMENT", "پیشنهاد تامین مجدد", replenishment, _IF,
              "انبارهای زیر نقطهٔ سفارش و انبار مبدای دارای مازاد.", "none", _OP),
    ReportDef("PRODUCTIVITY", "بهره‌وری انبار", productivity, ("warehouse", "branch"),
              "تعداد سند و ردیف، میانگین زمان و ردیف در ساعت به تفکیک نوع سند و کاربر.", group=_OP),
    ReportDef("CAPACITY", "ظرفیت انبار", capacity, ("warehouse", "branch"), "ظرفیت وزنی/حجمی، اشغال، آزاد و درصد استفاده.", "none", _OP),
    ReportDef("BIN_STOCK", "موجودی به تفکیک محل نگهداری", bin_stock, _IF, "موجودی هر خانهٔ قفسه در هر انبار.", "none", _OP),
    ReportDef("PUTAWAY", "جانمایی", putaway_report, _IF,
              "وظایف جانمایی با محل مبدا/مقصد، زمان انتظار، زمان جانمایی و اپراتور.", group=_OP, options=(_TASK_VIEW,)),
    ReportDef("UNLOCATED_STOCK", "دریافت‌شده ولی جانمایی‌نشده", unlocated_stock, _IF,
              "موجودی ماندهٔ محل دریافت و وظایف جانمایی باز.", "none", _OP),
    ReportDef("PICKING", "برداشت", picking_report, _IF,
              "آمادهٔ برداشت، برداشته‌شده، در انتظار، ناقص؛ دقت و زمان برداشت.", group=_OP, options=(_PICK_VIEW,)),
    ReportDef("WMS_PERFORMANCE", "عملکرد اپراتورهای انبار", wms_performance, ("warehouse", "branch"),
              "وظایف انجام‌شده، میانگین زمان، ردیف در ساعت و دقت برداشت هر اپراتور.", group=_OP),
    ReportDef("BIN_BATCH_STOCK", "بچ به تفکیک محل", bin_batch_stock, _IF,
              "بچ/لات و انقضای موجود در هر خانهٔ قفسه — برای برداشت FEFO از محل درست.", "as_of", _OP),
    ReportDef("WAVES", "موج‌های برداشت", waves_report, ("warehouse", "branch"),
              "موج‌ها با طول مسیر، محل‌های مسیر به ترتیب، پیشرفت و زمان انجام.", group=_OP),
    ReportDef("LOCATION_COUNTS", "شمارش‌های محل", location_counts_report, _IF,
              "ردیف‌های شمارش محل‌محور با دفتری، شمارش و اختلاف.", group=_OP,
              options=(("view", "نمایش", (("ALL", "همه"), ("DIFF", "فقط دارای اختلاف"))),)),
    ReportDef("REPLENISH_TASKS", "تامین مجدد محل‌های برداشت", replenishment_tasks, _IF,
              "وظایف تامین مجدد و نیازهای بی‌وظیفه با قاعدهٔ حداقل/حداکثر.", group=_OP),
    ReportDef("MD_WAREHOUSES", "فهرست انبارها", md_warehouses, ("warehouse", "branch"),
              "نوع، شعبه، مسئول، محل‌ها، تعداد و ارزش کالاهای هر انبار.", "none", _MD),
    ReportDef("MD_UNITS", "واحدها و تبدیل واحد کالاها", md_units, _IFNW, "واحدهای فرعی هر کالا و ضریب تبدیل.", "none", _MD),
    ReportDef("MD_TRACKED", "کالاهای دارای سریال/بچ/انقضا", md_tracked_items, _IFNW, "کالاهای ردیابی‌شده.", "none", _MD,
              options=(("kind", "نوع", (("ANY", "هر کدام"), ("SERIAL", "سریال"), ("BATCH", "بچ/لات"), ("EXPIRY", "انقضا"))),)),
    ReportDef("MD_MIN_MAX", "کالاهای دارای حداقل/حداکثر موجودی", md_min_max, _IF,
              "سیاست سفارش کالا یا پیش‌فرض انبار با موجودی فعلی.", "none", _MD),
]
# R259: گزارش‌هایِ بهایِ تمام‌شده (ماژولِ costing) در همین موتور/صفحه
from peecha.services.costing.reports import COSTING_REPORTS  # noqa: E402

WAREHOUSE_REPORTS += COSTING_REPORTS
# R264: گزارش‌هایِ دارایی‌هایِ ثابت هم رویِ همین موتور/صفحه (بدونِ موتورِ گزارشِ جدید)
from peecha.services.fixed_assets.reports import FA_REPORTS  # noqa: E402

WAREHOUSE_REPORTS += FA_REPORTS
# R270: گزارش‌هایِ تولید
from peecha.services.production.reports import PRODUCTION_REPORTS  # noqa: E402

WAREHOUSE_REPORTS += PRODUCTION_REPORTS
# R288: گزارش‌های CRM
from peecha.services.crm.reports import CRM_REPORTS  # noqa: E402

WAREHOUSE_REPORTS += CRM_REPORTS
# R296: گزارش‌های گردش کار و تایید
from peecha.services.workflow.monitor import WF_REPORTS  # noqa: E402

WAREHOUSE_REPORTS += WF_REPORTS
WAREHOUSE_REPORTS_BY_CODE = {r.code: r for r in WAREHOUSE_REPORTS}
