"""گزارش‌هایِ بهایِ تمام‌شده -- R259 (فقط خواندنی؛ همان موتور و صفحهٔ گزارش‌هایِ انبار).

همهٔ ارقامِ بها از costing (لایه، تخصیص، بهایِ جایگزینی) و دفترِ انبار خوانده می‌شود؛ گزارش هیچ بهایی را
دوباره محاسبه نمی‌کند (منبعِ حقیقت: موتورِ بهایِ تمام‌شده).
"""

from __future__ import annotations

import datetime
import decimal
from collections import defaultdict

from sqlalchemy import func, select

from peecha.db.base import new_session
from peecha.db.models.commercial import CommercialDocument, CommercialDocumentLine
from peecha.db.models.inventory import (
    Batch, CostAllocation, CostLayer, SerialNumber, StandardCost, StockDocument, StockDocumentLine, StockLedger,
)
from peecha.services.costing import engine as costing_engine
from peecha.services.costing import replacement as costing_replacement
from peecha.services.costing import strategies, valuation
from peecha.services.purchase_reports import DATE, MONEY, PERCENT, QTY, TEXT, ReportDef, ReportResult

_ZERO = decimal.Decimal(0)
_GROUP = "بهایِ تمام‌شده"
_IF = ("item", "category", "brand", "warehouse", "branch")


def _wr():
    from peecha.services import warehouse_reports as wr

    return wr


def _ok(m, f, item_id, wid) -> bool:
    wr = _wr()
    return wr._item_ok(m, f, item_id) and wr._wh_ok(m, f, wid)


def _pct(part, whole):
    return (decimal.Decimal(part) * 100 / whole).quantize(decimal.Decimal("0.1")) if whole else None


def _doc_label(dtype, dno) -> str:
    return f"{_wr().DOC_TYPE_TITLES.get(dtype, dtype)} {dno}"


def _ref(doc_id, dtype):
    return (doc_id, _wr().STOCK_REF + dtype) if doc_id else None


# ---------------------------------------------------------------------
def cost_valuation(company_id: int, f) -> ReportResult:
    wr = _wr()
    m = wr._meta(company_id)
    by_lot = str(f.options.get("by") or "ITEM_WH") == "LOT"
    if by_lot:
        r = ReportResult([("کالا", TEXT), ("انبار", TEXT), ("بچ", TEXT), ("سریال", TEXT), ("مقدار", QTY), ("بهایِ واحد", MONEY),
                          ("ارزش", MONEY)], no_total={5}, note="ریزِ جاریِ لایه‌هایِ باز (روش‌هایِ لایه‌ای).")
        for v in sorted(valuation.lot_values(company_id), key=lambda v: (m.ctx.item_label(v.item_id), v.batch_no, v.serial_no)):
            if _ok(m, f, v.item_id, v.warehouse_id):
                r.add([m.ctx.item_label(v.item_id), wr._wh_label(m, v.warehouse_id), v.batch_no, v.serial_no, v.quantity,
                       v.unit_cost.quantize(decimal.Decimal("0.01")), v.value.quantize(decimal.Decimal("0.01"))])
        return r
    r = ReportResult([("کالا", TEXT), ("انبار", TEXT), ("مقدار", QTY), ("بهایِ واحد", MONEY), ("ارزش", MONEY), ("روش", TEXT)],
                     no_total={3}, note="ارزش تا پایانِ تاریخِ گزارش از دفترِ انبار (همان مبنایِ حسابداری).")
    methods: dict[int, str] = {}
    for (item_id, wid), (qty, value) in sorted(valuation.positions(company_id, f.date_to).items(),
                                                key=lambda kv: (m.ctx.item_label(kv[0][0]), kv[0][1])):
        if (qty == 0 and value == 0) or not _ok(m, f, item_id, wid):
            continue
        if item_id not in methods:
            methods[item_id] = valuation.effective_method(company_id, item_id)
        r.add([m.ctx.item_label(item_id), wr._wh_label(m, wid), qty, (value / qty).quantize(decimal.Decimal("0.01")) if qty else None,
               value, strategies.METHOD_LABELS.get(methods[item_id], methods[item_id])])
    return r


def cost_layers(company_id: int, f) -> ReportResult:
    wr = _wr()
    m = wr._meta(company_id)
    open_only = str(f.options.get("status") or "OPEN") == "OPEN"
    with new_session() as session:
        q = (select(CostLayer, StockDocument.document_type_code, StockDocument.document_no, StockDocument.stock_document_id)
             .outerjoin(StockDocumentLine, StockDocumentLine.line_id == CostLayer.source_line_id)
             .outerjoin(StockDocument, StockDocument.stock_document_id == StockDocumentLine.stock_document_id)
             .where(CostLayer.company_id == company_id))
        if open_only:
            q = q.where(CostLayer.remaining_quantity > 0)
        rows = session.execute(q.order_by(CostLayer.item_id, CostLayer.receipt_date, CostLayer.cost_layer_id)).all()
        batches = dict(session.execute(select(Batch.batch_id, Batch.batch_no)).all())
        serials = dict(session.execute(select(SerialNumber.serial_id, SerialNumber.serial_no).where(
            SerialNumber.serial_id.in_({row[0].serial_id for row in rows if row[0].serial_id} or {-1}))).all())
    r = ReportResult([("کالا", TEXT), ("انبار", TEXT), ("سندِ ورود", TEXT), ("تاریخِ دریافت", DATE), ("منبع", TEXT),
                      ("بچ", TEXT), ("سریال", TEXT), ("مقدارِ اولیه", QTY), ("مانده", QTY), ("بهایِ واحد", MONEY),
                      ("ارزشِ مانده", MONEY), ("وضعیت", TEXT)], no_total={9})
    src = {"OPENING_BALANCE": "لایهٔ آغازین", "LEGACY": "پیش از R257"}
    for lyr, dtype, dno, did in rows:
        if not _ok(m, f, lyr.item_id, lyr.warehouse_id):
            continue
        r.add([m.ctx.item_label(lyr.item_id), wr._wh_label(m, lyr.warehouse_id), _doc_label(dtype, dno) if dtype else "",
               lyr.receipt_date, src.get(lyr.source_type_code, wr.DOC_TYPE_TITLES.get(lyr.source_type_code, lyr.source_type_code or "")),
               batches.get(lyr.batch_id, ""), serials.get(lyr.serial_id, ""), lyr.original_quantity, lyr.remaining_quantity,
               lyr.unit_cost, (lyr.remaining_quantity * lyr.unit_cost).quantize(decimal.Decimal("0.01")),
               "باز" if lyr.remaining_quantity > 0 else "مصرف‌شده"], _ref(did, dtype))
    return r


def cost_allocation(company_id: int, f) -> ReportResult:
    wr = _wr()
    m = wr._meta(company_id)
    with new_session() as session:
        rows = session.execute(
            select(CostAllocation, StockDocument.document_type_code, StockDocument.document_no, StockDocument.stock_document_id)
            .join(StockDocumentLine, StockDocumentLine.line_id == CostAllocation.stock_document_line_id)
            .join(StockDocument, StockDocument.stock_document_id == StockDocumentLine.stock_document_id)
            .where(CostAllocation.company_id == company_id, CostAllocation.movement_date.between(f.date_from, f.date_to))
            .order_by(CostAllocation.movement_date, CostAllocation.allocation_id)).all()
        layer_ids = {a.cost_layer_id for a, *_ in rows if a.cost_layer_id}
        layer_src = {lid: (d, t, n) for lid, d, t, n in session.execute(
            select(CostLayer.cost_layer_id, CostLayer.receipt_date, StockDocument.document_type_code, StockDocument.document_no)
            .outerjoin(StockDocumentLine, StockDocumentLine.line_id == CostLayer.source_line_id)
            .outerjoin(StockDocument, StockDocument.stock_document_id == StockDocumentLine.stock_document_id)
            .where(CostLayer.cost_layer_id.in_(layer_ids or {-1}))).all()}
    r = ReportResult([("سندِ خروج", TEXT), ("تاریخ", DATE), ("کالا", TEXT), ("انبار", TEXT), ("مقدار", QTY), ("بهایِ واحد", MONEY),
                      ("بهایِ کل", MONEY), ("لایهٔ مبدأ", TEXT), ("روش", TEXT), ("وضعیت", TEXT)], no_total={5})
    for a, dtype, dno, did in rows:
        if not _ok(m, f, a.item_id, a.warehouse_id):
            continue
        if a.cost_layer_id:
            d, t, n = layer_src.get(a.cost_layer_id, (None, None, None))
            source = f"لایهٔ #{a.cost_layer_id}" + (f" -- {_doc_label(t, n)}" if t else "") + (f" ({d})" if d else "")
        else:
            source = a.note or strategies.METHOD_LABELS.get(a.costing_method_code, "")
        r.add([_doc_label(dtype, dno), a.movement_date, m.ctx.item_label(a.item_id), wr._wh_label(m, a.warehouse_id),
               a.quantity_base, a.unit_cost, (a.quantity_base * a.unit_cost).quantize(decimal.Decimal("0.01")), source,
               strategies.METHOD_LABELS.get(a.costing_method_code, a.costing_method_code),
               costing_engine.STATUS_LABELS.get(a.costing_status_code, a.costing_status_code)], _ref(did, dtype))
    return r


def cost_history(company_id: int, f) -> ReportResult:
    wr = _wr()
    m = wr._meta(company_id)
    r = ReportResult([("تاریخ", DATE), ("کالا", TEXT), ("بهایِ واحد", MONEY), ("مقدار", QTY), ("نوع", TEXT), ("منبع", TEXT),
                      ("تامین‌کننده", TEXT), ("سند", TEXT), ("انبار", TEXT), ("روش", TEXT)], no_total={2})
    for h in valuation.cost_history(company_id, f.item_id, f.date_from, f.date_to):
        if not _ok(m, f, h.item_id, h.warehouse_id):
            continue
        r.add([h.date, m.ctx.item_label(h.item_id), h.unit_cost, h.quantity, "ورود" if h.direction == "IN" else "خروج",
               wr.DOC_TYPE_TITLES.get(h.source, h.source), h.supplier, str(h.document_no or ""), wr._wh_label(m, h.warehouse_id),
               strategies.METHOD_LABELS.get(h.method, h.method)], _ref(h.document_id, h.source))
    return r


def _line_cost(session, stock_line_id: int, direction: str) -> decimal.Decimal:
    """بهایِ یک ردیفِ سندِ انبار: تخصیص‌هایِ موتور (منبعِ حقیقت)؛ برایِ اسنادِ پیش از R257 همان دفترِ انبار."""
    value = session.scalar(select(func.sum(CostAllocation.quantity_base * CostAllocation.unit_cost)).where(
        CostAllocation.stock_document_line_id == stock_line_id))
    if value is None:
        value = session.scalar(select(func.sum(StockLedger.quantity_base * StockLedger.unit_cost)).where(
            StockLedger.stock_document_line_id == stock_line_id, StockLedger.movement_direction == direction))
    return decimal.Decimal(value or 0)


def cogs(company_id: int, f) -> ReportResult:
    """فروش، بهایِ تمام‌شده (از موتورِ بها) و سودِ ناخالص به تفکیکِ کالا؛ برگشت از فروش کسر می‌شود."""
    wr = _wr()
    m = wr._meta(company_id)
    agg: dict[int, list] = defaultdict(lambda: [_ZERO, _ZERO, _ZERO])
    with new_session() as session:
        rows = session.execute(
            select(CommercialDocument.document_type_code, CommercialDocumentLine.item_id, CommercialDocumentLine.quantity,
                   CommercialDocumentLine.conversion_factor, CommercialDocumentLine.unit_price, CommercialDocumentLine.discount_amount,
                   CommercialDocumentLine.stock_document_line_id, CommercialDocumentLine.warehouse_id, CommercialDocument.warehouse_id)
            .join(CommercialDocument, CommercialDocument.document_id == CommercialDocumentLine.document_id)
            .where(CommercialDocument.company_id == company_id, CommercialDocument.status_code == "POSTED",
                   CommercialDocument.document_type_code.in_(("SALES_INVOICE", "SALES_RETURN")),
                   CommercialDocument.document_date.between(f.date_from, f.date_to))).all()
        for dtype, item_id, qty, factor, price, discount, stock_line_id, lwh, dwh in rows:
            if not _ok(m, f, item_id, lwh or dwh):
                continue
            sign = -1 if dtype == "SALES_RETURN" else 1
            a = agg[item_id]
            a[0] += sign * qty * (factor or 1)
            a[1] += sign * (qty * price - (discount or _ZERO))
            if stock_line_id:
                a[2] += sign * _line_cost(session, stock_line_id, "IN" if sign < 0 else "OUT")
    r = ReportResult([("کالا", TEXT), ("مقدارِ فروش (پایه)", QTY), ("فروش", MONEY), ("بهایِ تمام‌شده", MONEY), ("سودِ ناخالص", MONEY),
                      ("حاشیهٔ سود", PERCENT)], no_total={5}, note="بهایِ تمام‌شده از تخصیص‌هایِ موتورِ بها؛ برگشت‌ها کسر شده‌اند.")
    for item_id, (qty, revenue, cost) in sorted(agg.items(), key=lambda kv: -(kv[1][1] - kv[1][2])):
        r.add([m.ctx.item_label(item_id), qty, revenue.quantize(decimal.Decimal("0.01")), cost.quantize(decimal.Decimal("0.01")),
               (revenue - cost).quantize(decimal.Decimal("0.01")), _pct(revenue - cost, revenue)])
    return r


def replacement_report(company_id: int, f) -> ReportResult:
    wr = _wr()
    m = wr._meta(company_id)
    totals: dict[int, list] = defaultdict(lambda: [_ZERO, _ZERO])
    for (item_id, wid), (qty, value) in valuation.positions(company_id, f.date_to).items():
        if qty > 0 and _ok(m, f, item_id, wid):
            totals[item_id][0] += qty
            totals[item_id][1] += value
    with new_session() as session:
        sources = costing_engine.company_settings(session, company_id).nifo_sources
        r = ReportResult([("کالا", TEXT), ("موجودی", QTY), ("بهایِ جاری", MONEY), ("بهایِ جایگزینی", MONEY), ("منبع", TEXT),
                          ("اختلافِ واحد", MONEY), ("اختلاف٪", PERCENT), ("اثر بر ارزشِ موجودی", MONEY)], no_total={2, 3, 5, 6})
        for item_id, (qty, value) in sorted(totals.items(), key=lambda kv: m.ctx.item_label(kv[0])):
            current = value / qty
            found = costing_replacement.replacement_cost(session, company_id, item_id, f.warehouse_id, f.date_to, sources)
            if found is None:
                r.add([m.ctx.item_label(item_id), qty, current.quantize(decimal.Decimal("0.01")), None, "—", None, None, None])
                continue
            rc, src = found
            r.add([m.ctx.item_label(item_id), qty, current.quantize(decimal.Decimal("0.01")), rc,
                   costing_replacement.SOURCES.get(src, src), (rc - current).quantize(decimal.Decimal("0.01")),
                   _pct(rc - current, current), ((rc - current) * qty).quantize(decimal.Decimal("0.01"))])
    return r


def expected_cost(session, company_id: int, item_id: int, as_of: datetime.date) -> tuple[decimal.Decimal, str] | None:
    """بهایِ مرجع/مورد انتظار: بهایِ استانداردِ موجود، وگرنه بهایِ جایگزینی (سیستمِ استانداردِ تازه ساخته نمی‌شود)."""
    std = session.scalar(select(StandardCost.standard_unit_cost).where(
        StandardCost.item_id == item_id, StandardCost.effective_date <= as_of).order_by(StandardCost.effective_date.desc()).limit(1))
    if std is not None:
        return std, "بهایِ استاندارد"
    found = costing_replacement.replacement_cost(session, company_id, item_id, None, as_of,
                                                 costing_engine.company_settings(session, company_id).nifo_sources)
    return (found[0], costing_replacement.SOURCES.get(found[1], found[1])) if found else None


def cost_variance(company_id: int, f) -> ReportResult:
    wr = _wr()
    m = wr._meta(company_id)
    with new_session() as session:
        rows = session.execute(
            select(CostAllocation.item_id, func.sum(CostAllocation.quantity_base),
                   func.sum(CostAllocation.quantity_base * CostAllocation.unit_cost))
            .join(StockDocumentLine, StockDocumentLine.line_id == CostAllocation.stock_document_line_id)
            .join(StockDocument, StockDocument.stock_document_id == StockDocumentLine.stock_document_id)
            .where(CostAllocation.company_id == company_id, StockDocument.document_type_code == "ISSUE",
                   CostAllocation.movement_date.between(f.date_from, f.date_to))
            .group_by(CostAllocation.item_id)).all()
        r = ReportResult([("کالا", TEXT), ("مقدارِ خروج", QTY), ("بهایِ مورد انتظار", MONEY), ("مبنا", TEXT), ("بهایِ واقعی", MONEY),
                          ("مغایرتِ واحد", MONEY), ("مغایرت٪", PERCENT), ("مغایرتِ کل", MONEY)], no_total={2, 4, 5, 6},
                         note="مبنایِ مورد انتظار: بهایِ استاندارد (اگر تعریف شده)، وگرنه بهایِ جایگزینی.")
        for item_id, qty, value in sorted(rows, key=lambda row: m.ctx.item_label(row[0])):
            if not wr._item_ok(m, f, item_id) or not qty:
                continue
            actual = decimal.Decimal(value) / decimal.Decimal(qty)
            exp = expected_cost(session, company_id, item_id, f.date_to)
            if exp is None:
                r.add([m.ctx.item_label(item_id), qty, None, "—", actual.quantize(decimal.Decimal("0.01")), None, None, None])
                continue
            diff = actual - exp[0]
            r.add([m.ctx.item_label(item_id), qty, exp[0], exp[1], actual.quantize(decimal.Decimal("0.01")),
                   diff.quantize(decimal.Decimal("0.01")), _pct(diff, exp[0]), (diff * qty).quantize(decimal.Decimal("0.01"))])
    return r


def pending_costs(company_id: int, f) -> ReportResult:
    wr = _wr()
    m = wr._meta(company_id)
    with new_session() as session:
        rows = session.execute(
            select(CostAllocation, StockDocument.document_type_code, StockDocument.document_no, StockDocument.stock_document_id)
            .join(StockDocumentLine, StockDocumentLine.line_id == CostAllocation.stock_document_line_id)
            .join(StockDocument, StockDocument.stock_document_id == StockDocumentLine.stock_document_id)
            .where(CostAllocation.company_id == company_id, CostAllocation.costing_status_code != "CALCULATED")
            .order_by(CostAllocation.movement_date)).all()
    r = ReportResult([("سند", TEXT), ("تاریخ", DATE), ("کالا", TEXT), ("انبار", TEXT), ("مقدار", QTY), ("بهایِ موقت", MONEY),
                      ("وضعیت", TEXT), ("توضیح", TEXT)], no_total={5},
                     note="تراکنش‌هایی که بهایِ نهایی ندارند -- با «محاسبهٔ مجددِ بها» تعیین‌تکلیف می‌شوند.")
    for a, dtype, dno, did in rows:
        if _ok(m, f, a.item_id, a.warehouse_id):
            r.add([_doc_label(dtype, dno), a.movement_date, m.ctx.item_label(a.item_id), wr._wh_label(m, a.warehouse_id),
                   a.quantity_base, a.unit_cost, costing_engine.STATUS_LABELS.get(a.costing_status_code, a.costing_status_code),
                   a.note or ""], _ref(did, dtype))
    return r


COSTING_REPORTS: list[ReportDef] = [
    ReportDef("COST_VALUATION", "ارزش‌گذاریِ موجودی (بهایِ تمام‌شده)", cost_valuation, _IF,
              "کالا، انبار، مقدار، بهایِ واحد و ارزش در تاریخ (یا ریزِ بچ/سریالِ جاری).", "as_of", _GROUP,
              options=(("by", "نما", (("ITEM_WH", "کالا × انبار"), ("LOT", "بچ/سریال (جاری)"))),)),
    ReportDef("COST_LAYERS", "لایه‌هایِ هزینه", cost_layers, _IF,
              "هر لایه: سندِ ورود، مقدارِ اولیه و مانده، بهایِ واحد و ارزشِ مانده.", "none", _GROUP,
              options=(("status", "وضعیت", (("OPEN", "باز"), ("ALL", "همه"))),)),
    ReportDef("COST_ALLOCATION", "تخصیصِ بهایِ خروج", cost_allocation, _IF,
              "هر خروج: سند، مقدار، بها و لایهٔ مبدأ.", "range", _GROUP),
    ReportDef("COST_HISTORY", "تاریخچهٔ بهایِ کالا", cost_history, _IF,
              "بهایِ هر ورود و خروج با منبع، تامین‌کننده، سند، انبار و روش.", "range", _GROUP),
    ReportDef("COST_COGS", "بهایِ تمام‌شدهٔ کالایِ فروش‌رفته و سودِ ناخالص", cogs, _IF,
              "فروش، بهایِ تمام‌شده (موتورِ بها) و سودِ ناخالصِ هر کالا.", "range", _GROUP),
    ReportDef("COST_REPLACEMENT", "بهایِ جایگزینی در برابرِ بهایِ جاری", replacement_report, _IF,
              "بهایِ جاری، بهایِ جایگزینی، اختلاف و درصد.", "as_of", _GROUP),
    ReportDef("COST_VARIANCE", "مغایرتِ بها (مورد انتظار/واقعی)", cost_variance, _IF,
              "بهایِ مورد انتظار (استاندارد/جایگزینی) در برابرِ بهایِ واقعیِ خروج.", "range", _GROUP),
    ReportDef("COST_PENDING", "تراکنش‌هایِ بهایِ در انتظار", pending_costs, _IF,
              "خروج‌هایِ دارایِ بهایِ موقت (موجودیِ منفی) یا نیازمندِ محاسبهٔ مجدد.", "none", _GROUP),
]
