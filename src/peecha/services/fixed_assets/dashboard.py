"""داشبوردِ دارایی‌هایِ ثابت -- R264: شاخص‌ها، هشدارها و نمودارها از همان سرویس‌ها (بدونِ محاسبهٔ موازی)."""

from __future__ import annotations

import datetime
import decimal
from collections import Counter, defaultdict

from sqlalchemy import func, select

from peecha.db.base import new_session
from peecha.db.models.fixed_assets import Asset, AssetCategory, DepreciationRun
from peecha.services.fixed_assets import common as c
from peecha.services.purchase_dashboard import Kpi

ZERO = c.ZERO
CHART_TITLES = (
    ("by_category", "ارزشِ دفتری به تفکیکِ طبقه", "FA_BY_CATEGORY", {}),
    ("status", "وضعیتِ دارایی‌ها", "FA_REGISTER", {"status": "ALL"}),
    ("depreciation_trend", "استهلاکِ ماهانهٔ ثبت‌شده", "FA_DEPRECIATION", {}),
    ("forecast", "پیش‌بینیِ استهلاکِ ۱۲ ماهِ آینده", "FA_FORECAST", {}),
)
ALERT_LABELS = {"WARRANTY": "انقضایِ گارانتی", "INSURANCE": "انقضایِ بیمه", "DEPRECIATION_END": "پایانِ استهلاک",
                "MISSING": "دارایی‌هایِ مفقود", "IMPAIRMENT": "کاهشِ ارزش", "APPROVAL": "در انتظارِ تأیید"}


def dashboard(company_id: int, date_from: datetime.date, date_to: datetime.date):
    from peecha.services.fixed_assets import physical as fp
    from peecha.services.fixed_assets import reports as fr
    from peecha.services.purchase_reports import PurchaseFilters

    with new_session() as session:
        assets = list(session.scalars(select(Asset).where(Asset.company_id == company_id)))
        cats = dict(session.execute(select(AssetCategory.category_id, AssetCategory.name)
                                    .where(AssetCategory.company_id == company_id)).all())
        runs = session.execute(select(DepreciationRun.period_code, func.sum(DepreciationRun.total_amount))
                               .where(DepreciationRun.company_id == company_id, DepreciationRun.status_code == "POSTED",
                                      DepreciationRun.period_end >= date_from, DepreciationRun.period_start <= date_to)
                               .group_by(DepreciationRun.period_code).order_by(DepreciationRun.period_code)).all()
    active = [a for a in assets if a.status_code not in c.CLOSED_STATUSES]
    status_count = Counter(a.status_code for a in assets)
    gross = sum((a.gross_cost for a in active), ZERO)
    accumulated = sum((a.accumulated_depreciation + a.accumulated_impairment for a in active), ZERO)
    alerts = fp.alerts(company_id, date_to)
    alert_count = Counter(a.kind for a in alerts)
    kpis = [
        Kpi("COUNT", "تعدادِ دارایی‌ها", len(active), "INT", "FA_REGISTER", "دارایی‌هایِ واگذارنشده", {"status": "ACTIVE"}),
        Kpi("GROSS", "بهایِ تمام‌شده", gross, "MONEY", "FA_BY_CATEGORY", "Σ بهایِ تمام‌شده"),
        Kpi("ACCUM", "استهلاک و کاهشِ ارزشِ انباشته", accumulated, "MONEY", "FA_BY_CATEGORY", "Σ استهلاکِ انباشته + کاهشِ ارزش"),
        Kpi("NBV", "ارزشِ دفتری", gross - accumulated, "MONEY", "FA_BY_CATEGORY", "بها − استهلاک − کاهشِ ارزش"),
        Kpi("IN_SERVICE", "در بهره‌برداری", status_count["IN_SERVICE"] + status_count["CAPITALIZED"], "INT", "FA_REGISTER",
            "دارایی‌هایِ فعال", {"status": "ACTIVE"}),
        Kpi("MAINTENANCE", "در تعمیر", status_count["UNDER_MAINTENANCE"], "INT", "FA_REGISTER", "وضعیتِ «در تعمیر»"),
        Kpi("FULLY_DEPRECIATED", "کاملاً مستهلک", status_count["FULLY_DEPRECIATED"], "INT", "FA_FULLY_DEPRECIATED",
            "ارزشِ دفتری = اسقاط"),
        Kpi("DISPOSED", "واگذارشده", sum(status_count[s] for s in ("SOLD", "SCRAPPED", "DISPOSED")), "INT", "FA_DISPOSALS",
            "فروش/اسقاط/حذف"),
    ]
    by_cat: dict[str, decimal.Decimal] = defaultdict(lambda: ZERO)
    for a in active:
        by_cat[cats.get(a.category_id, "")] += a.book_value
    top = sorted(by_cat.items(), key=lambda kv: -kv[1])[:10]
    forecast = fr.forecast_report(company_id, PurchaseFilters(date_from, date_to, side="INVENTORY", options={"months": "12"}))
    chart_data = {
        "by_category": {"kind": "bar", "labels": [t[0] for t in top], "series": {"ارزشِ دفتری": [t[1] for t in top]}},
        "status": {"kind": "donut", "labels": [c.STATUS_LABELS[s] for s in status_count],
                   "series": {"تعداد": [decimal.Decimal(n) for n in status_count.values()]}},
        "depreciation_trend": {"kind": "bar", "labels": [p for p, _ in runs], "series": {"استهلاک": [v for _, v in runs]}},
        "forecast": {"kind": "bar", "labels": [r[0] for r in forecast.rows], "series": {"استهلاک": [r[1] for r in forecast.rows]}},
    }
    alert_rows = [(ALERT_LABELS[k], n) for k, n in alert_count.items()]
    return kpis, chart_data, alert_rows, alerts
