"""داشبوردِ تولید -- R270: شاخص‌ها، هشدارها و نمودارها از همان سرویس‌هایِ تولید (بدونِ محاسبهٔ موازی)."""

from __future__ import annotations

import datetime
import decimal
from collections import defaultdict
from types import SimpleNamespace

from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.production import ProductionOrder
from peecha.services.production import common as c
from peecha.services.purchase_dashboard import Kpi

ZERO = c.ZERO
_HUNDRED = decimal.Decimal(100)
OPEN = ("RELEASED", "IN_PROGRESS", "ON_HOLD")
CHART_TITLES = (
    ("by_period", "تولید به تفکیکِ دوره", "PRD_BY_PERIOD", {}),
    ("elements", "عناصرِ بهایِ تمام‌شده", "PRD_COST", {}),
    ("top_products", "محصولاتِ پرتولید", "PRD_BY_PRODUCT", {}),
    ("variance", "انحرافِ بهایِ دستورها", "PRD_STD_VS_ACTUAL", {}),
)
ALERT_LABELS = {"SHORTAGE": "کمبودِ مواد", "LATE": "تولیدِ عقب‌افتاده", "OVER_COST": "هزینه بالاتر از استاندارد",
                "ABNORMAL_SCRAP": "ضایعاتِ غیرعادی"}
ALERT_LEVEL = {"SHORTAGE": "RED", "LATE": "YELLOW", "OVER_COST": "ORANGE", "ABNORMAL_SCRAP": "RED"}


def alerts(company_id: int, cost_tolerance_percent: decimal.Decimal = decimal.Decimal(5)) -> list[SimpleNamespace]:
    from peecha.services.production.costing import order_costs
    from peecha.services.production.orders import availability, normal_scrap_percent

    out = []
    today = datetime.date.today()
    with new_session() as session:
        orders = list(session.scalars(select(ProductionOrder).where(
            ProductionOrder.company_id == company_id,
            ProductionOrder.status_code.in_(("DRAFT", "PLANNED") + OPEN + ("COMPLETED",)))))
        costs = {o.order_id: order_costs(session, o) for o in orders if o.status_code in OPEN + ("COMPLETED",)}
        scrap_limits = {o.order_id: normal_scrap_percent(session, o) for o in orders}
    for o in orders:
        if o.status_code in ("DRAFT", "PLANNED") + OPEN:
            short = [a for a in availability(company_id, o.order_id) if a.status != "GREEN" and not a.is_optional]
            if short:
                out.append(SimpleNamespace(kind="SHORTAGE", order_id=o.order_id, order_code=o.order_code,
                                           text=f"{o.order_code}: کمبودِ {len(short)} ماده"))
            if o.due_date < today:
                out.append(SimpleNamespace(kind="LATE", order_id=o.order_id, order_code=o.order_code,
                                           text=f"{o.order_code}: {(today - o.due_date).days} روز تأخیر"))
        k = costs.get(o.order_id)
        if k is not None and k.produced and k.standard_total and k.variance * _HUNDRED > k.standard_total * cost_tolerance_percent:
            out.append(SimpleNamespace(kind="OVER_COST", order_id=o.order_id, order_code=o.order_code,
                                       text=f"{o.order_code}: {(k.variance * _HUNDRED / k.standard_total).quantize(decimal.Decimal('0.1'))}٪ بالاتر از استاندارد"))
        total = decimal.Decimal(o.produced_qty) + decimal.Decimal(o.scrapped_qty)
        if o.scrapped_qty and total and decimal.Decimal(o.scrapped_qty) * _HUNDRED / total > scrap_limits[o.order_id]:
            out.append(SimpleNamespace(kind="ABNORMAL_SCRAP", order_id=o.order_id, order_code=o.order_code,
                                       text=f"{o.order_code}: ضایعاتِ {(decimal.Decimal(o.scrapped_qty) * _HUNDRED / total).quantize(decimal.Decimal('0.1'))}٪"))
    return out


def dashboard(company_id: int, date_from: datetime.date, date_to: datetime.date):
    from peecha.services.production import reports as pr
    from peecha.services.production.costing import order_costs
    from peecha.services.purchase_reports import PurchaseFilters

    f = PurchaseFilters(date_from, date_to, side="INVENTORY")
    today = datetime.date.today()
    with new_session() as session:
        orders = pr._orders(session, company_id, f)
        produced = pr._production_rows(session, company_id, f)
        costed = [(o, order_costs(session, o)) for o in orders if o.status_code not in ("DRAFT", "PLANNED")]
    qty = sum((q for _o, _t, q, _a in produced), ZERO)
    value = sum((a for _o, _t, _q, a in produced), ZERO)
    actual = sum((k.total - k.co_product_amount for _o, k in costed if k.produced), ZERO)
    standard = sum((k.standard_total for _o, k in costed if k.produced), ZERO)
    good = sum((decimal.Decimal(o.produced_qty) for o in orders), ZERO)
    scrap = sum((decimal.Decimal(o.scrapped_qty) for o in orders), ZERO)
    eff = pr.efficiency(company_id, f)
    mat_eff = [r[3] for r in eff.rows if r[3] is not None]
    lab_eff = [r[4] for r in eff.rows if r[4] is not None]
    al = alerts(company_id)
    n_short = len({a.order_id for a in al if a.kind == "SHORTAGE"})
    kpis = [
        Kpi("ORDERS", "دستورهایِ تولید", len(orders), "INT", "PRD_ORDERS", "دستورهایِ فعال/برنامه‌شده در بازه", {"status": "ALL"}),
        Kpi("IN_PROGRESS", "در حالِ تولید", sum(1 for o in orders if o.status_code in OPEN), "INT", "PRD_ORDERS",
            "صادرشده/در حالِ تولید/متوقف", {"status": "OPEN"}),
        Kpi("COMPLETED", "تکمیل‌شده", sum(1 for o in orders if o.status_code in ("COMPLETED", "CLOSED")), "INT", "PRD_ORDERS",
            "تکمیل/بسته", {"status": "COMPLETED"}),
        Kpi("DELAYED", "عقب‌افتاده", sum(1 for o in orders if o.due_date < today and o.status_code not in ("COMPLETED", "CLOSED")),
            "INT", "PRD_EFFICIENCY", "تاریخِ پایان گذشته و تکمیل‌نشده"),
        Kpi("SHORTAGE", "کمبودِ مواد", n_short, "INT", "PRD_MATERIAL_REQUIREMENT", "دستورهایِ دارایِ کمبود"),
        Kpi("QTY", "مقدارِ تولید", qty, "INT", "PRD_BY_PRODUCT", "Σ رسیدِ محصولِ اصلی"),
        Kpi("VALUE", "ارزشِ تولید", value, "MONEY", "PRD_BY_PRODUCT", "Σ بهایِ رسیدِ محصول"),
        Kpi("ACTUAL", "بهایِ واقعی", actual, "MONEY", "PRD_COST", "مواد + دستمزد + ماشین + سربار − جانبی"),
        Kpi("STANDARD", "بهایِ استاندارد", standard, "MONEY", "PRD_STD_VS_ACTUAL", "استانداردِ واحد × تولید"),
        Kpi("VARIANCE", "انحرافِ بها", actual - standard, "MONEY", "PRD_COST_VARIANCE", "واقعی − استاندارد"),
        Kpi("SCRAP", "ضایعات٪", (scrap * _HUNDRED / (good + scrap)).quantize(decimal.Decimal("0.1")) if good + scrap else ZERO,
            "PERCENT", "PRD_SCRAP_ANALYSIS", "ضایعات ÷ (سالم + ضایعات)"),
        Kpi("MAT_EFF", "کاراییِ مواد٪", (sum(mat_eff) / len(mat_eff)).quantize(decimal.Decimal("0.1")) if mat_eff else ZERO,
            "PERCENT", "PRD_EFFICIENCY", "مصرفِ استاندارد ÷ واقعی"),
        Kpi("LAB_EFF", "کاراییِ دستمزد٪", (sum(lab_eff) / len(lab_eff)).quantize(decimal.Decimal("0.1")) if lab_eff else ZERO,
            "PERCENT", "PRD_EFFICIENCY", "ساعتِ استاندارد ÷ واقعی"),
    ]
    by_period, by_product = defaultdict(lambda: ZERO), defaultdict(lambda: ZERO)
    from peecha.services.fixed_assets.common import period_of

    for o, t, q, _a in produced:
        by_period[period_of(t.txn_date)[0]] += q
        by_product[o.item_id] += q
    with new_session() as session:
        labels = c.item_labels(session, list(by_product))
    top = sorted(by_product.items(), key=lambda kv: -kv[1])[:10]
    elements = {"مواد": sum((k.material for _o, k in costed), ZERO), "دستمزد": sum((k.labor for _o, k in costed), ZERO),
                "ماشین": sum((k.machine for _o, k in costed), ZERO), "سربار": sum((k.overhead for _o, k in costed), ZERO)}
    var_rows = sorted([(o.order_code, k.variance) for o, k in costed if k.produced], key=lambda x: -abs(x[1]))[:10]
    charts = {
        "by_period": {"kind": "bar", "labels": sorted(by_period), "series": {"تولید": [by_period[p] for p in sorted(by_period)]}},
        "elements": {"kind": "donut", "labels": list(elements), "series": {"تعداد": list(elements.values())}},
        "top_products": {"kind": "bar", "labels": [labels.get(i, "") for i, _ in top], "series": {"تولید": [v for _, v in top]}},
        "variance": {"kind": "bar", "labels": [x[0] for x in var_rows], "series": {"انحراف": [x[1] for x in var_rows]}},
    }
    counts = defaultdict(int)
    for a in al:
        counts[a.kind] += 1
    alert_rows = [(ALERT_LABELS[k], n) for k, n in counts.items()]
    return kpis, charts, alert_rows, al
