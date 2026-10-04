"""داشبوردِ انبار -- R246.

مثلِ داشبوردِ خرید، هر شاخص و نمودار از خروجیِ همان گزارش‌هایِ services/warehouse_reports
(و دو گزارشِ موجودِ خرید/فروش) ساخته می‌شود و کدِ گزارشِ مبدا را برایِ Drill-down دارد؛
پس عددِ داشبورد همیشه با گزارشِ مربوط یکی است و منطقِ محاسبهٔ جدیدی ندارد.
"""

from __future__ import annotations

import datetime
import decimal
from collections import defaultdict

from peecha.services import inventory_catalog as catalog_service
from peecha.services import purchase_reports as reports
from peecha.services.purchase_dashboard import Kpi, column

_ZERO = decimal.Decimal(0)
_EPOCH = datetime.date(1900, 1, 1)
SIDE = "INVENTORY"


def run(company_id: int, code: str, date_from: datetime.date, date_to: datetime.date, **options) -> reports.ReportResult:
    """همان قاعدهٔ صفحهٔ گزارش برایِ تاریخ (as_of = تا تاریخ، none = تا امروز)."""
    mode = reports.report_def(code, SIDE).date_mode
    if mode == "none":
        date_from, date_to = _EPOCH, datetime.date.today()
    elif mode == "as_of":
        date_from = _EPOCH
    return reports.run_report(company_id, code, reports.PurchaseFilters(date_from, date_to, side=SIDE, options=options))


def _sum(result: reports.ReportResult, header: str) -> decimal.Decimal:
    i = column(result, header)
    return sum((decimal.Decimal(r[i]) for r in result.rows if r[i] not in (None, "")), _ZERO)


def _value_of(result: reports.ReportResult, qty_header: str) -> decimal.Decimal:
    """ارزشِ بخشی از موجودی = ارزشِ ردیف × (مقدارِ آن بخش ÷ موجودیِ ردیف)."""
    qi, ti, vi = column(result, qty_header), column(result, "موجودی"), column(result, "ارزشِ موجودی")
    return sum(((decimal.Decimal(r[vi]) * decimal.Decimal(r[qi]) / decimal.Decimal(r[ti])).quantize(decimal.Decimal("0.01"))
                for r in result.rows if r[qi] and r[ti]), _ZERO)


class _Cache:
    """هر گزارش با هر گزینه فقط یک بار در هر به‌روزرسانی اجرا می‌شود."""

    def __init__(self, company_id, date_from, date_to):
        self.args = (company_id, date_from, date_to)
        self.data = {}

    def __call__(self, code: str, **options) -> reports.ReportResult:
        key = (code, tuple(sorted(options.items())))
        if key not in self.data:
            self.data[key] = run(self.args[0], code, self.args[1], self.args[2], **options)
        return self.data[key]


def kpis(company_id: int, date_from: datetime.date, date_to: datetime.date, cache: _Cache | None = None) -> list[Kpi]:
    c = cache or _Cache(company_id, date_from, date_to)
    on_hand = c("STOCK_ON_HAND", state="ALL")
    positive_items = {r[0] for r in on_hand.rows if r[column(on_hand, "موجودی")] > 0}
    skus = [i for i in catalog_service.list_items(company_id, transactable_only=True)
            if i.is_stock_tracked and i.item_kind_code != "SERVICE"]
    fast = c("ABC", basis="FREQ")
    out = [
        Kpi("VALUE", "ارزشِ کلِ موجودی", _sum(c("VALUATION", by="WAREHOUSE"), "ارزش"), "MONEY", "VALUATION", "Σ ارزشِ ماندهٔ کالاها"),
        Kpi("SKU", "تعدادِ SKU", len(skus), "INT", "MD_TRACKED", "کالاهایِ انبارداریِ قابلِ معامله", {"kind": "ANY"}),
        Kpi("IN_STOCK", "کالاهایِ موجود", len(positive_items), "INT", "STOCK_ON_HAND", "کالاهایِ با موجودیِ مثبت", {"state": "POSITIVE"}),
        Kpi("ZERO", "کالاهایِ بدونِ موجودی", len(c("ZERO_STOCK").rows), "INT", "ZERO_STOCK", "موجودیِ کل = صفر"),
        Kpi("NEGATIVE", "موجودیِ منفی", len(c("NEGATIVE_STOCK").rows), "INT", "NEGATIVE_STOCK", "ردیف‌هایِ کالا×انبارِ منفی"),
        Kpi("RESERVED", "ارزشِ موجودیِ رزرو", _value_of(on_hand, "رزرو"), "MONEY", "RESERVED_STOCK", "ارزش × سهمِ رزرو از موجودی"),
        Kpi("FREE", "ارزشِ موجودیِ آزاد", _value_of(on_hand, "آزاد"), "MONEY", "FREE_STOCK", "ارزش × سهمِ آزاد از موجودی"),
        Kpi("QUARANTINE", "ارزشِ موجودیِ قرنطینه", _value_of(on_hand, "قرنطینه"), "MONEY", "QUARANTINE_STOCK", "موجودیِ انبارهایِ قرنطینه"),
        Kpi("BLOCKED", "ارزشِ موجودیِ مسدود", _value_of(on_hand, "مسدود"), "MONEY", "QUARANTINE_STOCK", "انبارهایِ ضایعات/غیرفعال"),
        Kpi("CONSIGNMENT", "اقلامِ امانی", len(c("CONSIGNMENT_STOCK").rows), "INT", "CONSIGNMENT_STOCK", "ردیف‌هایِ امانیِ تسویه‌نشده"),
        Kpi("LOW", "کالاهایِ کم‌موجودی", sum(1 for r in c("REORDER", view="ALL").rows
                                              if r[6] is not None and r[4] < r[6]), "INT", "REORDER", "آزاد < حداقل (ذخیرهٔ اطمینان)",
            {"view": "ALL"}),
        Kpi("ROP", "زیرِ نقطهٔ سفارش", len(c("REORDER").rows), "INT", "REORDER", "آزاد ≤ نقطهٔ سفارش"),
        Kpi("OVER", "کالاهایِ مازاد", len(c("OVERSTOCK").rows), "INT", "OVERSTOCK", "بیش از حداکثر/تقاضا"),
        Kpi("DEAD", "کالاهایِ راکد", len(c("DEAD_STOCK").rows), "INT", "DEAD_STOCK", "بدونِ خروج در بازه"),
        Kpi("SLOW", "کالاهایِ کندگردش", len(c("SLOW_MOVING").rows), "INT", "SLOW_MOVING", "خروجِ کم در ۹۰ روز"),
        Kpi("FAST", "کالاهایِ تندگردش", sum(1 for r in fast.rows if r[-1] == "A"), "INT", "ABC", "کلاسِ A بر مبنایِ دفعاتِ گردش",
            {"basis": "FREQ"}),
        Kpi("NEAR_EXPIRY", "نزدیکِ انقضا (۳۰ روز)", len(c("EXPIRY", window="30").rows), "INT", "EXPIRY", "انقضا ≤ ۳۰ روز",
            {"window": "30"}),
        Kpi("EXPIRED", "منقضی‌شده", len(c("EXPIRY", window="EXPIRED").rows), "INT", "EXPIRY", "تاریخِ انقضا گذشته",
            {"window": "EXPIRED"}),
        Kpi("OPEN_RECEIPTS", "رسیدهایِ باز", len(c("RECEIVING", view="OPEN").rows), "INT", "RECEIVING", "ثبت‌نشده یا منتظرِ تاییدِ انبار",
            {"view": "OPEN"}),
        Kpi("OPEN_ISSUES", "حواله‌هایِ باز", len(c("ISSUES", view="OPEN").rows), "INT", "ISSUES", "ثبت‌نشده یا منتظرِ حواله",
            {"view": "OPEN"}),
        Kpi("TRANSFERS", "انتقال‌هایِ در انتظار", len(c("TRANSFERS", view="PENDING").rows), "INT", "TRANSFERS", "انتقالِ ثبت‌نشده",
            {"view": "PENDING"}),
        Kpi("COUNTS", "شمارش‌هایِ باز", len(c("STOCK_COUNTS", view="OPEN").rows) + len(c("STOCK_COUNTS", view="UNAPPROVED").rows),
            "INT", "STOCK_COUNTS", "باز + شمارش‌شدهٔ تاییدنشده"),
        Kpi("VARIANCE", "مغایرت‌هایِ موجودی", len(c("VARIANCE").rows), "INT", "VARIANCE", "ردیف‌هایِ شمارشِ دارایِ اختلاف در بازه"),
        # R247
        Kpi("PUTAWAY", "جانمایی‌هایِ در انتظار", len(c("UNLOCATED_STOCK").rows), "INT", "UNLOCATED_STOCK",
            "کالاهایِ ماندهٔ محلِ دریافت یا با وظیفهٔ جانماییِ باز"),
        Kpi("PICKS", "برداشت‌هایِ باز", sum(1 for r in c("PICKING").rows if r[8] in ("باز", "در حالِ انجام")), "INT", "PICKING",
            "وظایفِ برداشتِ باز یا در حالِ انجام در بازه"),
        Kpi("COUNT_DUE", "شمارش‌هایِ سررسیدشده", len(c("CYCLE_COUNT_DUE").rows), "INT", "CYCLE_COUNT_DUE",
            "اقلامِ برنامهٔ شمارشِ دوره‌ای که موعدشان رسیده"),
    ]
    return out


CHART_TITLES = (
    ("value_trend", "ارزشِ موجودی در طولِ زمان", "VALUE_TREND", {}),
    ("in_out", "ورود و خروجِ کالا (ماهانه)", "ITEM_MOVEMENT", {}),
    ("by_warehouse", "تعدادِ کالا به تفکیکِ انبار", "STOCK_BY_WAREHOUSE", {}),
    ("by_category", "موجودی به تفکیکِ گروهِ کالا", "VALUATION", {"by": "CATEGORY"}),
    ("abc", "ABC موجودی (ارزشِ مصرف)", "ABC", {}),
    ("aging", "سنِ موجودی (ارزش)", "STOCK_AGING", {}),
    ("slow", "کالاهایِ کم‌گردش (ارزش)", "SLOW_MOVING", {}),
    ("dead", "کالاهایِ راکد (ارزش)", "DEAD_STOCK", {}),
    ("utilization", "استفاده از ظرفیتِ انبار", "CAPACITY", {}),
    ("variance", "مغایرتِ موجودی (ارزشِ ماهانه)", "ACCURACY", {"by": "MONTH"}),
    ("fast20", "۲۰ کالایِ تندگردش", "ABC", {"basis": "FREQ"}),
    ("slow20", "۲۰ کالایِ کندگردش", "SLOW_MOVING", {}),
    ("near_rop", "کالاهایِ نزدیک به نقطهٔ سفارش", "REORDER", {"view": "ALL"}),
    ("qty_trend", "روندِ ماهانهٔ مقدارِ موجودی", "VALUE_TREND", {}),
    ("value_by_wh", "ارزشِ موجودی به تفکیکِ انبار", "VALUATION", {"by": "WAREHOUSE"}),
)


def _short(label: str) -> str:
    return label.split(" — ")[-1] if isinstance(label, str) else str(label)


def charts(company_id: int, date_from: datetime.date, date_to: datetime.date, cache: _Cache | None = None) -> dict[str, dict]:
    """{کلید: {"labels": [...], "series": {نام: [...]}, "kind": "bar"|"donut"}}"""
    c = cache or _Cache(company_id, date_from, date_to)
    out: dict[str, dict] = {}

    def bar(key, labels, **series):
        out[key] = {"labels": [str(x) for x in labels], "series": series, "kind": "bar"}

    trend = c("VALUE_TREND")
    bar("value_trend", [r[0] for r in trend.rows], ارزش=[r[2] for r in trend.rows])
    bar("qty_trend", [r[0] for r in trend.rows], مقدار=[r[1] for r in trend.rows])
    move = c("ITEM_MOVEMENT")
    bar("in_out", [r[0] for r in move.rows], ارزشِ_ورود=[r[4] for r in move.rows], ارزشِ_خروج=[r[5] for r in move.rows])
    per_wh: dict[str, set] = defaultdict(set)
    for r in c("STOCK_BY_WAREHOUSE").rows:
        per_wh[r[0]].add(r[2])
    bar("by_warehouse", [_short(k) for k in per_wh], تعداد=[len(v) for v in per_wh.values()])
    out["by_category"] = {"labels": [_short(r[0]) for r in c("VALUATION", by="CATEGORY").rows],
                          "series": {"ارزش": [r[3] for r in c("VALUATION", by="CATEGORY").rows]}, "kind": "donut"}
    abc = c("ABC")
    classes = {k: _ZERO for k in "ABC"}
    for r in abc.rows:
        classes[r[-1]] += r[2]
    bar("abc", list(classes), ارزش=list(classes.values()))
    aging = c("STOCK_AGING")
    buckets = [h for h, _k in aging.columns[5:11]]
    values = [_ZERO] * len(buckets)
    for r in aging.rows:
        unit = (r[3] / r[2]) if r[2] else _ZERO
        for i in range(len(buckets)):
            values[i] += (r[5 + i] * unit).quantize(decimal.Decimal("0.01"))
    bar("aging", [b.replace(" روز", "") for b in buckets], ارزش=values)
    slow = sorted(c("SLOW_MOVING").rows, key=lambda r: -r[3])
    bar("slow", [_short(r[0]) for r in slow[:10]], ارزش=[r[3] for r in slow[:10]])
    slow20 = sorted(slow, key=lambda r: -(r[5] if r[5] is not None else 10 ** 6))[:20]
    bar("slow20", [_short(r[0]) for r in slow20], روزِ_بدونِ_خروج=[r[5] if r[5] is not None else 0 for r in slow20])
    dead = sorted(c("DEAD_STOCK").rows, key=lambda r: -r[3])[:10]
    bar("dead", [_short(r[0]) for r in dead], ارزش=[r[3] for r in dead])
    cap = c("CAPACITY")
    if any(r[4] is not None or r[8] is not None for r in cap.rows):
        bar("utilization", [_short(r[0]) for r in cap.rows], درصدِ_وزنی=[r[4] or 0 for r in cap.rows],
            درصدِ_حجمی=[r[8] or 0 for r in cap.rows])
    else:
        bar("utilization", [_short(r[0]) for r in cap.rows], اشغالِ_وزنی=[r[2] for r in cap.rows])
    acc = c("ACCURACY", by="MONTH")
    bar("variance", [r[0] for r in acc.rows], ارزشِ_اختلاف=[r[4] for r in acc.rows])
    fast = c("ABC", basis="FREQ").rows[:20]
    bar("fast20", [_short(r[0]) for r in fast], دفعاتِ_گردش=[r[3] for r in fast])
    rop = [r for r in c("REORDER", view="ALL").rows if r[5]]
    rop.sort(key=lambda r: (r[4] - r[5]))
    bar("near_rop", [_short(r[0]) for r in rop[:10]], آزاد=[r[4] for r in rop[:10]], نقطهٔ_سفارش=[r[5] for r in rop[:10]])
    val = c("VALUATION", by="WAREHOUSE")
    bar("value_by_wh", [_short(r[0]) for r in val.rows], ارزش=[r[3] for r in val.rows])
    return out


def dashboard(company_id: int, date_from: datetime.date, date_to: datetime.date) -> tuple[list[Kpi], dict[str, dict]]:
    cache = _Cache(company_id, date_from, date_to)
    return kpis(company_id, date_from, date_to, cache), charts(company_id, date_from, date_to, cache)
