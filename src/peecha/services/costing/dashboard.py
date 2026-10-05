"""داشبوردِ بهایِ تمام‌شده -- R259: شاخص‌ها و نمودارها از همان سرویس‌هایِ costing (بدونِ محاسبهٔ موازی)."""

from __future__ import annotations

import datetime
import decimal
from collections import defaultdict

import jdatetime
from sqlalchemy import func, select

from peecha.db.base import new_session
from peecha.db.models.inventory import CostAllocation, StockDocument, StockDocumentLine, StockLedger
from peecha.services.costing import reports as costing_reports
from peecha.services.costing import valuation
from peecha.services.purchase_dashboard import Kpi

_ZERO = decimal.Decimal(0)
CHART_TITLES = (
    ("value_trend", "روندِ ارزشِ موجودی", "COST_VALUATION", {}),
    ("cogs_trend", "روندِ بهایِ تمام‌شدهٔ فروش", "COST_COGS", {}),
    ("cost_trend", "روندِ میانگینِ بهایِ خروج", "COST_HISTORY", {}),
    ("purchase_vs_replacement", "بهایِ آخرین خرید در برابرِ بهایِ جایگزینی", "COST_REPLACEMENT", {}),
    ("top_increase", "بیشترین افزایشِ بها (درصد)", "COST_HISTORY", {}),
)


def _month_ends(date_from: datetime.date, date_to: datetime.date) -> list[tuple[str, datetime.date, datetime.date]]:
    """(برچسبِ ماهِ شمسی، اولِ ماه، پایانِ ماه) بینِ دو تاریخ -- حداکثر ۱۲ ماهِ آخر."""
    out = []
    j = jdatetime.date.fromgregorian(date=date_to).replace(day=1)
    while len(out) < 12:
        start = j.togregorian()
        nxt = (j + jdatetime.timedelta(days=32)).replace(day=1)
        end = min(nxt.togregorian() - datetime.timedelta(days=1), date_to)
        out.append((f"{j.year}/{j.month:02d}", max(start, date_from), end))
        if start <= date_from:
            break
        j = (j - jdatetime.timedelta(days=1)).replace(day=1)
    return list(reversed(out))


def _issue_totals(company_id: int, date_from: datetime.date, date_to: datetime.date) -> tuple[decimal.Decimal, decimal.Decimal]:
    with new_session() as session:
        value, qty = session.execute(
            select(func.coalesce(func.sum(CostAllocation.quantity_base * CostAllocation.unit_cost), 0),
                   func.coalesce(func.sum(CostAllocation.quantity_base), 0))
            .join(StockDocumentLine, StockDocumentLine.line_id == CostAllocation.stock_document_line_id)
            .join(StockDocument, StockDocument.stock_document_id == StockDocumentLine.stock_document_id)
            .where(CostAllocation.company_id == company_id, StockDocument.document_type_code == "ISSUE",
                   CostAllocation.movement_date.between(date_from, date_to))).one()
    return decimal.Decimal(value), decimal.Decimal(qty)


def dashboard(company_id: int, date_from: datetime.date, date_to: datetime.date):
    from peecha.services.purchase_reports import PurchaseFilters

    f = PurchaseFilters(date_from, date_to, side="INVENTORY")
    s = valuation.summary(company_id, date_from, date_to)
    variance = costing_reports.cost_variance(company_id, f)
    replacement = costing_reports.replacement_report(company_id, f)
    total_variance = sum((r[7] or _ZERO for r in variance.rows), _ZERO)
    replacement_gap = sum((r[7] or _ZERO for r in replacement.rows), _ZERO)
    kpis = [
        Kpi("VALUE", "ارزشِ موجودی", s.inventory_value, "MONEY", "COST_VALUATION", "Σ (ورود − خروج) با بهایِ ثبت‌شده تا پایانِ بازه"),
        Kpi("COGS", "بهایِ تمام‌شدهٔ خروج‌ها", s.cogs, "MONEY", "COST_ALLOCATION", "Σ تخصیصِ بهایِ حواله‌ها در بازه"),
        Kpi("AVG", "میانگینِ بهایِ واحد", s.average_cost, "MONEY", "COST_VALUATION", "ارزشِ موجودی ÷ مقدارِ موجودی"),
        Kpi("VARIANCE", "مغایرتِ بها", total_variance, "MONEY", "COST_VARIANCE", "Σ (بهایِ واقعی − مورد انتظار) × مقدار"),
        Kpi("REPLACEMENT", "اثرِ بهایِ جایگزینی", replacement_gap, "MONEY", "COST_REPLACEMENT", "Σ (جایگزینی − جاری) × موجودی"),
        Kpi("LAYERS", "لایه‌هایِ باز", s.open_layers, "INT", "COST_LAYERS", "تعدادِ لایه‌هایِ دارایِ مانده"),
        Kpi("PENDING", "بهایِ در انتظار", s.pending, "INT", "COST_PENDING", "تخصیص‌هایِ غیرِ «محاسبه‌شده»"),
    ]
    months = _month_ends(date_from, date_to)
    labels = [m[0] for m in months]
    values, cogs_series, avg_cost = [], [], []
    for _label, start, end in months:
        values.append(sum((v[1] for v in valuation.positions(company_id, end).values()), _ZERO))
        value, qty = _issue_totals(company_id, start, end)
        cogs_series.append(value)
        avg_cost.append((value / qty) if qty else _ZERO)
    chart_data = {
        "value_trend": {"kind": "bar", "labels": labels, "series": {"ارزش": values}},
        "cogs_trend": {"kind": "bar", "labels": labels, "series": {"بهایِ تمام‌شده": cogs_series}},
        "cost_trend": {"kind": "bar", "labels": labels, "series": {"میانگینِ بهایِ خروج": avg_cost}},
    }
    top = sorted((r for r in replacement.rows if r[3] is not None), key=lambda r: -(abs(r[7] or 0)))[:8]
    chart_data["purchase_vs_replacement"] = {
        "kind": "bar", "labels": [r[0][:18] for r in top],
        "series": {"بهایِ جاری": [r[2] or 0 for r in top], "بهایِ جایگزینی": [r[3] or 0 for r in top]}}
    first_last: dict[int, list] = defaultdict(lambda: [None, None])
    with new_session() as session:
        for item_id, cost in session.execute(
                select(StockLedger.item_id, StockLedger.unit_cost)
                .join(StockDocumentLine, StockDocumentLine.line_id == StockLedger.stock_document_line_id)
                .join(StockDocument, StockDocument.stock_document_id == StockDocumentLine.stock_document_id)
                .where(StockLedger.company_id == company_id, StockLedger.movement_direction == "IN",
                       StockDocument.document_type_code == "RECEIPT", StockLedger.unit_cost > 0,
                       StockLedger.movement_date.between(date_from, date_to))
                .order_by(StockLedger.movement_date, StockLedger.ledger_id)).all():
            fl = first_last[item_id]
            fl[0] = fl[0] if fl[0] is not None else cost
            fl[1] = cost
    from peecha.services import warehouse_reports as wr

    m = wr._meta(company_id)
    increases = sorted(((m.ctx.item_label(i), (b - a) * 100 / a) for i, (a, b) in first_last.items() if a and b and b > a),
                       key=lambda t: -t[1])[:8]
    chart_data["top_increase"] = {"kind": "bar", "labels": [t[0][:18] for t in increases],
                                  "series": {"افزایش٪": [t[1].quantize(decimal.Decimal("0.1")) for t in increases]}}
    return kpis, chart_data
