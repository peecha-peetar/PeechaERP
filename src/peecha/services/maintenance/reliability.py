"""شاخص‌های قابلیت اطمینان (R312) — تعریف دقیق هر شاخص در DEFINITIONS؛ مخرج صفر = «داده ناکافی» (نه صفر).

دوره = [از تاریخ، تا تاریخ] شامل هر دو روز؛ زمان‌ها ساعت تقویمی (۲۴ ساعته) است چون تقویم کاری برای تجهیز تعریف نشده.
منبع زمان‌ها: mnt.downtime_events (شروع توقف تا آماده‌به‌کاری)؛ منبع دستورها: mnt.work_orders؛ هزینه: costs.summary_in_session.
"""

from __future__ import annotations

import datetime
import decimal
from collections import Counter, defaultdict
from dataclasses import dataclass
from types import SimpleNamespace

from sqlalchemy import or_, select

from peecha.db.base import new_session
from peecha.db.models.fixed_assets import Asset
from peecha.db.models.maintenance import DowntimeEvent, FailureCode, WorkOrder
from peecha.services.fixed_assets.common import CLOSED_STATUSES
from peecha.services.maintenance import common as c

INSUFFICIENT = "داده ناکافی"
_H = decimal.Decimal(3600)
_Q = decimal.Decimal("0.01")

DEFINITIONS = {
    "MTTR": ("میانگین زمان تعمیر (ساعت)",
             "جمع مدت توقف‌های «خرابی» که در دوره شروع و آماده‌به‌کاری‌شان ثبت شده ÷ تعداد همان توقف‌ها. "
             "مدت = از شروع توقف تا ثبت آماده‌به‌کاری (شامل انتظار قطعه و آزمون).", "توقف‌ها"),
    "MTBF": ("میانگین زمان بین خرابی‌ها (ساعت)",
             "ساعت کارکرد تجهیزات در دوره ÷ تعداد توقف‌های «خرابی» که در دوره شروع شده‌اند. ساعت کارکرد = ساعت تقویمی "
             "از تاریخ بهره‌برداری (یا شروع دوره) تا پایان دوره (یا اکنون) منهای ساعت توقف.", "دارایی + توقف‌ها"),
    "FAILURE_RATE": ("نرخ خرابی (در هر ۱۰۰۰ ساعت کارکرد)", "تعداد خرابی‌های شروع‌شده در دوره × ۱۰۰۰ ÷ ساعت کارکرد.",
                     "دارایی + توقف‌ها"),
    "DOWNTIME": ("ساعت توقف", "جمع هم‌پوشانی همهٔ توقف‌ها (خرابی، برنامه‌ریزی‌شده، سایر) با دوره؛ توقف باز تا اکنون.",
                 "توقف‌ها"),
    "AVAILABILITY": ("دسترس‌پذیری (درصد)", "ساعت کارکرد ÷ (ساعت کارکرد + ساعت توقف) × ۱۰۰.", "دارایی + توقف‌ها"),
    "PM_SHARE": ("سهم نگهداری پیشگیرانه (درصد)",
                 "دستورهای کار پیشگیرانه/بازرسی/اساسی/پیش‌بینانهٔ بسته‌شده در دوره ÷ همهٔ دستورهای بسته‌شده در دوره × ۱۰۰.",
                 "دستورهای کار"),
    "PM_COMPLIANCE": ("انجام به‌موقع نگهداری پیشگیرانه (درصد)",
                      "دستورهای پیشگیرانه‌ای که سررسیدشان در دوره و تا امروز بوده و تا همان سررسید انجام شده‌اند ÷ همهٔ "
                      "دستورهای پیشگیرانهٔ سررسیدشده در دوره (بدون لغوشده) × ۱۰۰.", "دستورهای کار"),
    "ON_TIME": ("انجام به‌موقع دستورهای کار (درصد)",
                "دستورهای بسته‌شده در دوره که پایان واقعی‌شان تا پایان برنامه‌ریزی‌شده بوده ÷ دستورهای بسته‌شدهٔ دوره که "
                "پایان برنامه‌ریزی‌شده دارند × ۱۰۰.", "دستورهای کار"),
    "COST": ("هزینهٔ نگهداری", "جمع هزینهٔ دستورهای کار ایجادشده در دوره (بدون لغوشده): قطعه (خالص سند انبار) + نیروی کار "
                               "(اطلاعاتی) + خدمات + سایر.", "دستورهای کار، اسناد انبار"),
    "OPEN_WO": ("دستورهای کار باز", "دستورهای کار در هر وضعیتی جز بسته‌شده و لغوشده (اکنون).", "دستورهای کار"),
    "BACKLOG_HOURS": ("کار معوق (ساعت تخمینی)", "جمع زمان تخمینی دستورهای باز.", "دستورهای کار"),
}


@dataclass
class Filters:
    date_from: datetime.date
    date_to: datetime.date
    location_id: int | None = None      # کارخانه/ناحیه/خط (با زیرشاخه‌ها)
    line: str | None = None
    asset_id: int | None = None
    work_type_code: str | None = None
    responsible_user_id: int | None = None


def _kpi(code: str, value, numerator=None, denominator=None, unit: str = "") -> SimpleNamespace:
    label, definition, source = DEFINITIONS[code]
    insufficient = value is None
    return SimpleNamespace(code=code, label=label, value=value, display=INSUFFICIENT if insufficient else value,
                           numerator=numerator, denominator=denominator, unit=unit, definition=definition, source=source,
                           insufficient=insufficient)


def _bounds(f: Filters) -> tuple[datetime.datetime, datetime.datetime]:
    lo = datetime.datetime.combine(f.date_from, datetime.time()).astimezone()
    hi = datetime.datetime.combine(f.date_to + datetime.timedelta(days=1), datetime.time()).astimezone()
    now = c.now()
    return lo, (min(hi, now) if lo < now else hi)   # آینده هنوز کارکرد/توقفی ندارد


def _hours(a, b) -> decimal.Decimal:
    if b <= a:
        return decimal.Decimal(0)
    return decimal.Decimal((b - a).total_seconds()) / _H


def _assets(session, company_id: int, f: Filters) -> list[Asset]:
    from peecha.services.maintenance import equipment

    rows = equipment.list_equipment(company_id, location_id=f.location_id, line=f.line, include_closed=False)
    ids = [r.asset_id for r in rows if not f.asset_id or r.asset_id == f.asset_id]
    return list(session.scalars(select(Asset).where(Asset.asset_id.in_(ids or [-1]))))


def _wo_filter(q, f: Filters):
    if f.work_type_code:
        q = q.where(WorkOrder.work_type_code == f.work_type_code)
    if f.responsible_user_id:
        q = q.where(WorkOrder.responsible_user_id == f.responsible_user_id)
    return q


def compute(company_id: int, f: Filters) -> SimpleNamespace:
    """همهٔ شاخص‌ها + علل پرتکرار + پرهزینه‌ترین تجهیزات برای یک دوره و فیلتر."""
    from peecha.services.maintenance import costs

    if f.date_to < f.date_from:
        raise ValueError("پایان دوره نمی‌تواند پیش از شروع آن باشد.")
    lo, hi = _bounds(f)
    with new_session() as session:
        assets = {a.asset_id: a for a in _assets(session, company_id, f)}
        ids = list(assets) or [-1]
        wo_filtered = bool(f.work_type_code or f.responsible_user_id)
        allowed_wo = None
        if wo_filtered:
            allowed_wo = set(session.scalars(_wo_filter(select(WorkOrder.work_order_id).where(
                WorkOrder.company_id == company_id, WorkOrder.asset_id.in_(ids)), f)))
        downs = [d for d in session.scalars(select(DowntimeEvent).where(
            DowntimeEvent.company_id == company_id, DowntimeEvent.asset_id.in_(ids), DowntimeEvent.down_from < hi,
            or_(DowntimeEvent.available_at.is_(None), DowntimeEvent.available_at > lo)))
            if allowed_wo is None or d.work_order_id in allowed_wo]
        now = c.now()
        down_hours: dict[int, decimal.Decimal] = defaultdict(decimal.Decimal)
        for d in downs:
            down_hours[d.asset_id] += _hours(max(c.aware(d.down_from), lo), min(c.aware(d.available_at) or now, hi))
        breakdowns = [d for d in downs if d.downtime_type_code == "BREAKDOWN" and lo <= c.aware(d.down_from) < hi]
        repaired = [d for d in breakdowns if d.available_at is not None]
        repair_hours = sum((_hours(c.aware(d.down_from), c.aware(d.available_at)) for d in repaired), decimal.Decimal(0))
        operating = decimal.Decimal(0)
        for a in assets.values():
            if a.in_service_date is None or a.status_code in CLOSED_STATUSES:
                continue
            start = max(lo, datetime.datetime.combine(a.in_service_date, datetime.time()).astimezone())
            operating += max(decimal.Decimal(0), _hours(start, hi) - down_hours.get(a.asset_id, decimal.Decimal(0)))
        total_down = sum(down_hours.values(), decimal.Decimal(0))

        wq = _wo_filter(select(WorkOrder).where(WorkOrder.company_id == company_id, WorkOrder.asset_id.in_(ids)), f)
        wos_all = list(session.scalars(wq))
        closed = [w for w in wos_all if w.status_code == "CLOSED" and w.closed_at and lo <= c.aware(w.closed_at) < hi]
        pm_closed = [w for w in closed if w.work_type_code in c.PM_TYPES]
        today = datetime.date.today()
        pm_due = [w for w in wos_all if w.pm_plan_id and w.pm_due_date and f.date_from <= w.pm_due_date <= min(f.date_to, today)
                  and w.status_code != "CANCELLED"]
        pm_on_time = [w for w in pm_due if w.actual_end and c.aware(w.actual_end).date() <= w.pm_due_date
                      and w.status_code in ("COMPLETED", "VERIFIED", "CLOSED")]
        planned = [w for w in closed if w.planned_end and w.actual_end]
        on_time = [w for w in planned if c.aware(w.actual_end) <= c.aware(w.planned_end)]
        created = [w for w in wos_all if w.status_code != "CANCELLED" and lo <= c.aware(w.created_at) < hi]
        cost_of = costs.summary_in_session(session, [w.work_order_id for w in created])
        total_cost = sum((s.total for s in cost_of.values()), decimal.Decimal(0))
        open_wo = [w for w in wos_all if w.status_code in c.OPEN_WO]
        backlog = sum((c.dec(w.estimated_hours) for w in open_wo), decimal.Decimal(0))

        by_asset_cost: dict[int, decimal.Decimal] = defaultdict(decimal.Decimal)
        for w in created:
            by_asset_cost[w.asset_id] += cost_of[w.work_order_id].total
        failures_by_asset = Counter(d.asset_id for d in breakdowns)
        cause = Counter(w.cause_code_id for w in closed if w.work_type_code not in c.PM_TYPES)
        problem = Counter(w.problem_code_id for w in closed if w.work_type_code not in c.PM_TYPES)
        code_ids = {k for k in list(cause) + list(problem) if k}
        code_label = {fc.failure_code_id: f"{fc.code} — {fc.name}" for fc in session.scalars(
            select(FailureCode).where(FailureCode.failure_code_id.in_(code_ids or {-1})))}

    def pct(n, d):
        return (decimal.Decimal(n) * 100 / decimal.Decimal(d)).quantize(_Q) if d else None

    n_fail = len(breakdowns)
    kpis = [
        _kpi("MTTR", (repair_hours / len(repaired)).quantize(_Q) if repaired else None, repair_hours.quantize(_Q), len(repaired), "ساعت"),
        _kpi("MTBF", (operating / n_fail).quantize(_Q) if n_fail and operating > 0 else None, operating.quantize(_Q), n_fail, "ساعت"),
        _kpi("FAILURE_RATE", (decimal.Decimal(n_fail) * 1000 / operating).quantize(_Q) if operating > 0 else None, n_fail,
             operating.quantize(_Q), "در ۱۰۰۰ ساعت"),
        _kpi("DOWNTIME", total_down.quantize(_Q) if assets else None, None, None, "ساعت"),
        _kpi("AVAILABILITY", pct(operating, operating + total_down) if operating + total_down > 0 else None,
             operating.quantize(_Q), (operating + total_down).quantize(_Q), "درصد"),
        _kpi("PM_SHARE", pct(len(pm_closed), len(closed)), len(pm_closed), len(closed), "درصد"),
        _kpi("PM_COMPLIANCE", pct(len(pm_on_time), len(pm_due)), len(pm_on_time), len(pm_due), "درصد"),
        _kpi("ON_TIME", pct(len(on_time), len(planned)), len(on_time), len(planned), "درصد"),
        _kpi("COST", c.money(total_cost) if created else None, None, len(created), "ریال"),
        _kpi("OPEN_WO", len(open_wo), None, None, "دستور"),
        _kpi("BACKLOG_HOURS", backlog.quantize(_Q), None, None, "ساعت"),
    ]
    costliest = sorted(((assets[a].asset_code + " — " + assets[a].name, v, failures_by_asset.get(a, 0))
                        for a, v in by_asset_cost.items() if v > 0 and a in assets), key=lambda x: -x[1])[:10]
    return SimpleNamespace(
        kpis=kpis, by_code={k.code: k for k in kpis}, filters=f,
        top_causes=[(code_label.get(k, "علت ثبت نشده"), n) for k, n in cause.most_common(10)],
        top_problems=[(code_label.get(k, "نشانه ثبت نشده"), n) for k, n in problem.most_common(10)],
        costliest=costliest, failures_by_asset=sorted(((assets[a].asset_code + " — " + assets[a].name, n)
                                                       for a, n in failures_by_asset.items() if a in assets), key=lambda x: -x[1])[:10],
        breakdowns=n_fail, assets=len(assets))


def asset_summary(company_id: int, asset_id: int, days: int = 365) -> SimpleNamespace:
    """خلاصهٔ یک‌سالهٔ کارت تجهیز."""
    today = datetime.date.today()
    r = compute(company_id, Filters(date_from=today - datetime.timedelta(days=days - 1), date_to=today, asset_id=asset_id))
    return SimpleNamespace(mttr=r.by_code["MTTR"], mtbf=r.by_code["MTBF"], downtime=r.by_code["DOWNTIME"],
                           availability=r.by_code["AVAILABILITY"], cost=r.by_code["COST"], breakdowns=r.breakdowns)
