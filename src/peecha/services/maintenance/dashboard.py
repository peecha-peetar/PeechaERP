"""داشبورد نگهداری (R312) — همان شاخص‌های reliability، صف کار و هشدارها؛ بدون محاسبهٔ موازی."""

from __future__ import annotations

import datetime
import decimal
from collections import defaultdict
from types import SimpleNamespace

from sqlalchemy import func, select

from peecha.db.base import new_session
from peecha.db.models.maintenance import (
    CapacityRestriction, PlannedDowntime, PmPlan, PmPostponement, WorkOrder, WorkOrderCost, WorkRequest,
)
from peecha.services.purchase_dashboard import Kpi
from peecha.services.maintenance import common as c

CHART_TITLES = (
    ("by_status", "دستورهای کار باز به تفکیک وضعیت", "MNT_WORK_ORDERS", {}),
    ("downtime", "تجهیزات با بیشترین ساعت توقف", "MNT_DOWNTIME", {}),
    ("causes", "پرتکرارترین علل خرابی", "MNT_FAILURES", {}),
    ("cost", "پرهزینه‌ترین تجهیزات", "MNT_COST", {}),
)
ALERT_LABELS = {"DOWN": "ماشین متوقف", "PM_OVERDUE": "نگهداری پیشگیرانهٔ عقب‌افتاده", "URGENT": "درخواست فوری بررسی‌نشده",
                "APPROVAL": "منتظر تأیید", "NO_DATA": "دادهٔ کارکرد ثبت نشده"}
ALERT_LEVEL = {"DOWN": "RED", "PM_OVERDUE": "ORANGE", "URGENT": "RED", "APPROVAL": "YELLOW", "NO_DATA": "YELLOW"}


def alerts(company_id: int) -> list[SimpleNamespace]:
    from peecha.services.maintenance import availability, pm, requests

    out = []
    for d in availability.list_downtimes(company_id, open_only=True):
        out.append(SimpleNamespace(kind="DOWN", ref=("EQUIPMENT", d.asset_id),
                                   text=f"{d.asset_label}: {d.type_label} از {d.hours} ساعت پیش"))
    for r in requests.queue(company_id, statuses=("NEW",)):
        if r.severity_code in ("HIGH", "CRITICAL") or r.machine_down_now:
            out.append(SimpleNamespace(kind="URGENT", ref=("REQUEST", r.request_id), text=f"درخواست {r.request_no}: {r.title}"))
    for p in pm.list_plans(company_id, include_inactive=False):
        if p.due.state == "OVERDUE":
            out.append(SimpleNamespace(kind="PM_OVERDUE", ref=("PM", p.plan_id),
                                       text=f"{p.code} — {p.title} ({p.asset_label}): سررسید گذشته"))
        elif p.due.state == "NO_DATA":
            out.append(SimpleNamespace(kind="NO_DATA", ref=("PM", p.plan_id), text=f"{p.code} — {p.title}: کارکردی ثبت نشده"))
    with new_session() as session:
        windows = session.scalar(select(func.count()).where(PlannedDowntime.company_id == company_id,
                                                            PlannedDowntime.status_code == "PROPOSED"))
        limits = session.scalar(select(func.count()).where(CapacityRestriction.company_id == company_id,
                                                           CapacityRestriction.status_code == "PROPOSED"))
        posts = session.scalar(select(func.count()).select_from(PmPostponement).join(
            PmPlan, PmPlan.plan_id == PmPostponement.plan_id).where(PmPlan.company_id == company_id,
                                                                    PmPostponement.status_code == "PENDING"))
    if windows or limits or posts:
        out.append(SimpleNamespace(kind="APPROVAL", ref=("AVAILABILITY", None),
                                   text=f"توقف برنامه‌ریزی‌شده {windows}، ظرفیت محدود {limits}، تعویق {posts}"))
    return out


def dashboard(company_id: int, date_from: datetime.date, date_to: datetime.date):
    from peecha.services.maintenance import reliability as rel

    k = rel.compute(company_id, rel.Filters(date_from=date_from, date_to=date_to))
    b = k.by_code
    with new_session() as session:
        by_status = dict(session.execute(select(WorkOrder.status_code, func.count()).where(
            WorkOrder.company_id == company_id, WorkOrder.status_code.in_(c.OPEN_WO)).group_by(WorkOrder.status_code)).all())
        new_req = session.scalar(select(func.count()).where(WorkRequest.company_id == company_id,
                                                            WorkRequest.status_code.in_(("NEW", "UNDER_REVIEW")))) or 0
        pending_cost = session.scalar(select(func.count()).select_from(WorkOrderCost).join(
            WorkOrder, WorkOrder.work_order_id == WorkOrderCost.work_order_id).where(
            WorkOrder.company_id == company_id, WorkOrderCost.status_code.in_(("DRAFT", "PENDING_APPROVAL")),
            WorkOrderCost.accounting_code != "NONE")) or 0
    from peecha.services.maintenance import availability

    down_now = len({d.asset_id for d in availability.list_downtimes(company_id, open_only=True)})
    awaiting_test = by_status.get("COMPLETED", 0)

    def v(code):
        return b[code].value

    kpis = [
        Kpi("DOWN_NOW", "ماشین متوقف اکنون", down_now, "INT", "MNT_DOWNTIME", "تجهیزات با توقف باز (بدون آماده‌به‌کاری)"),
        Kpi("NEW_REQUESTS", "درخواست بررسی‌نشده", new_req, "INT", "MNT_REQUESTS", "درخواست جدید یا در حال بررسی",
            {"status": "NEW"}),
        Kpi("OPEN_WO", "دستور کار باز", v("OPEN_WO"), "INT", "MNT_WORK_ORDERS", b["OPEN_WO"].definition),
        Kpi("AWAITING_TEST", "منتظر آزمون و تأیید", awaiting_test, "INT", "MNT_WORK_ORDERS", "انجام‌شده توسط تکنسین و آزمون‌نشده",
            {"status": "COMPLETED"}),
        Kpi("MTTR", "میانگین زمان تعمیر (ساعت)", v("MTTR"), "HOURS", "MNT_RELIABILITY", b["MTTR"].definition),
        Kpi("MTBF", "میانگین زمان بین خرابی‌ها (ساعت)", v("MTBF"), "HOURS", "MNT_RELIABILITY", b["MTBF"].definition),
        Kpi("AVAILABILITY", "دسترس‌پذیری٪", v("AVAILABILITY"), "PERCENT", "MNT_RELIABILITY", b["AVAILABILITY"].definition),
        Kpi("DOWNTIME", "ساعت توقف", v("DOWNTIME"), "HOURS", "MNT_DOWNTIME", b["DOWNTIME"].definition),
        Kpi("PM_SHARE", "سهم پیشگیرانه٪", v("PM_SHARE"), "PERCENT", "MNT_WORK_ORDERS", b["PM_SHARE"].definition),
        Kpi("PM_COMPLIANCE", "انجام به‌موقع پیشگیرانه٪", v("PM_COMPLIANCE"), "PERCENT", "MNT_PM_COMPLIANCE",
            b["PM_COMPLIANCE"].definition),
        Kpi("ON_TIME", "انجام به‌موقع دستور کار٪", v("ON_TIME"), "PERCENT", "MNT_WORK_ORDERS", b["ON_TIME"].definition),
        Kpi("FAILURE_RATE", "نرخ خرابی در ۱۰۰۰ ساعت", v("FAILURE_RATE"), "HOURS", "MNT_RELIABILITY", b["FAILURE_RATE"].definition),
        Kpi("COST", "هزینهٔ نگهداری", v("COST"), "MONEY", "MNT_COST", b["COST"].definition),
        Kpi("PENDING_COST", "هزینهٔ تعیین‌تکلیف‌نشده", pending_cost, "INT", "MNT_WORK_ORDERS",
            "ردیف هزینهٔ ثبت‌نشده در حسابداری یا منتظر تأیید مالی"),
        Kpi("BACKLOG", "کار معوق (ساعت تخمینی)", v("BACKLOG_HOURS"), "HOURS", "MNT_WORK_ORDERS", b["BACKLOG_HOURS"].definition),
    ]
    down_by: dict[str, decimal.Decimal] = defaultdict(decimal.Decimal)
    from peecha.services.maintenance.reliability import _bounds

    lo, hi = _bounds(rel.Filters(date_from=date_from, date_to=date_to))
    for d in availability.list_downtimes(company_id, date_from=date_from, date_to=date_to):
        end = min(c.aware(d.available_at) or c.now(), hi)
        start = max(c.aware(d.down_from), lo)
        if end > start:
            down_by[d.asset_label] += decimal.Decimal((end - start).total_seconds()) / 3600
    top_down = sorted(down_by.items(), key=lambda kv: -kv[1])[:8]
    charts = {
        "by_status": {"kind": "donut", "labels": [c.WO_STATUS_LABELS[s] for s in c.OPEN_WO],
                      "series": {"تعداد": [by_status.get(s, 0) for s in c.OPEN_WO]}},
        "downtime": {"kind": "bar", "labels": [a for a, _h in top_down],
                     "series": {"ساعت توقف": [h.quantize(decimal.Decimal("0.1")) for _a, h in top_down]}},
        "causes": {"kind": "bar", "labels": [lb for lb, _n in k.top_causes[:8]], "series": {"تعداد": [n for _lb, n in k.top_causes[:8]]}},
        "cost": {"kind": "bar", "labels": [lb for lb, _v, _n in k.costliest[:8]],
                 "series": {"هزینه": [v_ for _lb, v_, _n in k.costliest[:8]]}},
    }
    return kpis, charts, alerts(company_id)
