"""R363: زمان‌بندی پروژه به روش مسیر بحرانی روی روزهای کاری شرکت.

- روز کاری: روزی از هفته که در تقویم کاری شرکت ساعت کاری دارد و در فهرست تعطیلات نیست (همان تقویم گردش کار).
- هر فعالیت در «شاخص روز کاری» زمان‌بندی می‌شود: شروع = es، پایان انحصاری = ef = es + مدت.
- پیوند FS: شروع جانشین ≥ پایان پیش‌نیاز + تأخیر؛ SS: شروع ≥ شروع پیش‌نیاز + تأخیر؛ FF: پایان ≥ پایان پیش‌نیاز + تأخیر.
- «شروع نه زودتر از» و شروع پروژه حد پایین شروع‌اند؛ شروع واقعی و پایان واقعی (اگر ثبت شده) جای برنامه را می‌گیرند.
- شناوری کل = دیرترین شروع − زودترین شروع؛ فعالیت با شناوری صفر (یا منفی) بحرانی است.
- فاز (فعالیتی که زیرمجموعه دارد) تاریخ، هزینه، ساعت و پیشرفتش را از زیرمجموعه‌ها می‌گیرد؛ وزن پیشرفت هر فعالیت مدت آن است.
"""

from __future__ import annotations

import bisect
import datetime
import decimal
from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.hr import Employee
from peecha.db.models.projects import Project, ProjectTask, TaskLink

ZERO = decimal.Decimal(0)
HUNDRED = decimal.Decimal(100)
TASK_STATES = {"DONE": "پایان‌یافته", "RUNNING": "در حال انجام", "LATE": "عقب‌افتاده", "WAITING": "شروع‌نشده"}
LINK_LABELS = {"FS": "", "SS": "SS", "FF": "FF"}


class WorkCalendar:
    """تبدیل تاریخ به شاخص روز کاری (و برعکس) از یک تاریخ پایه."""

    def __init__(self, company_id: int, base: datetime.date) -> None:
        from peecha.services.workflow import calendar as wf_calendar

        self.company_id = company_id
        self.base = base
        self.weekdays = set(wf_calendar.work_hours(company_id)) or {5, 6, 0, 1, 2, 3}
        self._holidays: set[datetime.date] = set()
        self._loaded_to = base - datetime.timedelta(days=1)
        self.days: list[datetime.date] = []
        self._extend(base + datetime.timedelta(days=400))

    def _extend(self, until: datetime.date) -> None:
        from peecha.services.workflow import calendar as wf_calendar

        if until <= self._loaded_to:
            return
        until = max(until, self._loaded_to + datetime.timedelta(days=365))
        self._holidays |= wf_calendar.holiday_dates(self.company_id, self._loaded_to + datetime.timedelta(days=1), until)
        d = self._loaded_to + datetime.timedelta(days=1)
        while d <= until:
            if d.weekday() in self.weekdays and d not in self._holidays:
                self.days.append(d)
            d += datetime.timedelta(days=1)
        self._loaded_to = until

    def is_working(self, d: datetime.date) -> bool:
        self._extend(d)
        return d.weekday() in self.weekdays and d not in self._holidays

    def index(self, d: datetime.date) -> int:
        """شاخص نخستین روز کاری که ≥ d است (تاریخ پیش از پایه شاخص منفی تقریبی می‌گیرد)."""
        if d < self.base:
            return -sum(1 for k in range((self.base - d).days) if self.is_working(d + datetime.timedelta(days=k)))
        self._extend(d + datetime.timedelta(days=30))
        return bisect.bisect_left(self.days, d)

    def date(self, idx: int) -> datetime.date:
        if idx < 0:
            d, left = self.base, -idx
            while left:
                d -= datetime.timedelta(days=1)
                if self.is_working(d):
                    left -= 1
            return d
        while idx >= len(self.days):
            self._extend(self._loaded_to + datetime.timedelta(days=365))
        return self.days[idx]

    def working_days(self, start: datetime.date, finish: datetime.date) -> int:
        return max(0, self.index(finish + datetime.timedelta(days=1)) - self.index(start))


@dataclass
class ScheduledTask:
    task_id: int
    parent_task_id: int | None
    wbs: str
    level: int
    name: str
    is_summary: bool
    duration: int
    start: datetime.date
    finish: datetime.date
    es: int
    ef: int
    total_float: int
    critical: bool
    percent: decimal.Decimal
    planned_hours: decimal.Decimal
    planned_cost: decimal.Decimal
    responsible_employee_id: int | None
    responsible: str
    actual_start: datetime.date | None
    actual_finish: datetime.date | None
    start_no_earlier: datetime.date | None
    baseline_start: datetime.date | None
    baseline_finish: datetime.date | None
    baseline_cost: decimal.Decimal | None
    predecessors: str
    state_code: str
    notes: str

    @property
    def is_milestone(self) -> bool:
        return not self.is_summary and self.duration == 0

    @property
    def state_label(self) -> str:
        return TASK_STATES[self.state_code]


@dataclass
class Schedule:
    project_id: int
    start: datetime.date
    finish: datetime.date
    tasks: list[ScheduledTask] = field(default_factory=list)
    percent: decimal.Decimal = ZERO
    planned_percent: decimal.Decimal = ZERO
    planned_cost: decimal.Decimal = ZERO
    baseline_finish: datetime.date | None = None
    critical_count: int = 0
    late_count: int = 0
    calendar: WorkCalendar | None = None

    @property
    def schedule_variance(self) -> decimal.Decimal:
        return self.percent - self.planned_percent

    def by_id(self) -> dict[int, ScheduledTask]:
        return {t.task_id: t for t in self.tasks}


@dataclass
class _Agg:
    es: int
    ef: int
    total_float: int
    weight: decimal.Decimal
    earned: decimal.Decimal
    plain: decimal.Decimal
    leaves: int
    hours: decimal.Decimal
    cost: decimal.Decimal
    baseline_cost: decimal.Decimal | None
    baseline_start: datetime.date | None
    baseline_finish: datetime.date | None


def _children(tasks: list[ProjectTask]) -> dict[int | None, list[ProjectTask]]:
    out: dict[int | None, list[ProjectTask]] = defaultdict(list)
    for t in tasks:
        out[t.parent_task_id].append(t)
    for rows in out.values():
        rows.sort(key=lambda t: (t.sort_order, t.task_id))
    return out


def _topological(leaf_ids: list[int], links: list[TaskLink]) -> list[int]:
    preds = defaultdict(set)
    succs = defaultdict(set)
    for ln in links:
        preds[ln.successor_task_id].add(ln.predecessor_task_id)
        succs[ln.predecessor_task_id].add(ln.successor_task_id)
    pending = {t: len(preds[t]) for t in leaf_ids}
    ready = [t for t in leaf_ids if pending[t] == 0]
    out = []
    while ready:
        t = ready.pop(0)
        out.append(t)
        for s in sorted(succs[t]):
            pending[s] -= 1
            if pending[s] == 0:
                ready.append(s)
    if len(out) != len(leaf_ids):
        raise ValueError("پیوند فعالیت‌ها حلقه دارد؛ زمان‌بندی ممکن نیست.")
    return out


def compute(company_id: int, project_id: int, as_of: datetime.date | None = None) -> Schedule:
    as_of = as_of or datetime.date.today()
    with new_session() as session:
        project = session.get(Project, project_id)
        if project is None or project.company_id != company_id:
            raise ValueError("پروژه نامعتبر است.")
        tasks = list(session.scalars(select(ProjectTask).where(ProjectTask.project_id == project_id)))
        ids = [t.task_id for t in tasks]
        links = list(session.scalars(select(TaskLink).where(TaskLink.successor_task_id.in_(ids or [0]))))
        names = {e.employee_id: f"{e.first_name} {e.last_name}".strip() for e in session.scalars(
            select(Employee).where(Employee.employee_id.in_({t.responsible_employee_id for t in tasks if t.responsible_employee_id} or {0})))}
        session.expunge_all()
    floor = [project.start_date] + [d for t in tasks for d in (t.actual_start, t.start_no_earlier, t.baseline_start) if d]
    cal = WorkCalendar(company_id, min(floor))
    kids = _children(tasks)
    by_id = {t.task_id: t for t in tasks}
    leaves = [t.task_id for t in tasks if not kids.get(t.task_id)]
    order = _topological(leaves, links)
    preds_of, succs_of = defaultdict(list), defaultdict(list)
    for ln in links:
        preds_of[ln.successor_task_id].append(ln)
        succs_of[ln.predecessor_task_id].append(ln)
    start_idx = cal.index(project.start_date)
    es: dict[int, int] = {}
    ef: dict[int, int] = {}
    for tid in order:
        t = by_id[tid]
        e = start_idx
        if t.start_no_earlier:
            e = max(e, cal.index(t.start_no_earlier))
        for ln in preds_of[tid]:
            lag = ln.lag_days
            if ln.link_type == "SS":
                e = max(e, es[ln.predecessor_task_id] + lag)
            elif ln.link_type == "FF":
                e = max(e, ef[ln.predecessor_task_id] + lag - t.duration_days)
            else:
                e = max(e, ef[ln.predecessor_task_id] + lag)
        e = max(e, start_idx)
        if t.actual_start:
            e = cal.index(t.actual_start)
        f = e + t.duration_days
        if t.actual_finish:
            f = max(e + 1, cal.index(t.actual_finish) + 1)
        es[tid], ef[tid] = e, f
    end = max(ef.values(), default=start_idx)
    ls: dict[int, int] = {}
    lf: dict[int, int] = {}
    for tid in reversed(order):
        length = ef[tid] - es[tid]
        late = end
        for ln in succs_of[tid]:
            s, lag = ln.successor_task_id, ln.lag_days
            if ln.link_type == "SS":
                late = min(late, ls[s] - lag + length)
            elif ln.link_type == "FF":
                late = min(late, lf[s] - lag)
            else:
                late = min(late, ls[s] - lag)
        lf[tid], ls[tid] = late, late - length

    today_idx = cal.index(as_of + datetime.timedelta(days=1)) - 1  # آخرین روز کاری تا امروز

    def pred_label(tid: int, wbs: dict[int, str]) -> str:
        parts = []
        for ln in sorted(preds_of[tid], key=lambda x: wbs.get(x.predecessor_task_id, "")):
            lag = f"+{ln.lag_days}" if ln.lag_days > 0 else (str(ln.lag_days) if ln.lag_days < 0 else "")
            parts.append(f"{wbs.get(ln.predecessor_task_id, '?')}{LINK_LABELS[ln.link_type]}{lag}")
        return "، ".join(parts)

    wbs: dict[int, str] = {}
    flat: list[tuple[ProjectTask, int]] = []

    def walk(parent: int | None, prefix: str, level: int) -> None:
        for n, t in enumerate(kids.get(parent, []), start=1):
            code = f"{prefix}{n}"
            wbs[t.task_id] = code
            flat.append((t, level))
            walk(t.task_id, code + ".", level + 1)

    walk(None, "", 0)

    agg: dict[int, _Agg] = {}

    def roll(tid: int) -> _Agg:
        if tid not in agg:
            t = by_id[tid]
            if not kids.get(tid):
                weight = decimal.Decimal(t.duration_days)
                agg[tid] = _Agg(es[tid], ef[tid], ls[tid] - es[tid], weight, weight * t.percent_complete, t.percent_complete, 1,
                                t.planned_hours, t.planned_cost, t.baseline_cost, t.baseline_start, t.baseline_finish)
            else:
                parts = [roll(c.task_id) for c in kids[tid]]
                count = sum(p.leaves for p in parts)
                bs, bf = [p.baseline_start for p in parts if p.baseline_start], [p.baseline_finish for p in parts if p.baseline_finish]
                costs = [p.baseline_cost for p in parts if p.baseline_cost is not None]
                agg[tid] = _Agg(min(p.es for p in parts), max(p.ef for p in parts), min(p.total_float for p in parts),
                                sum((p.weight for p in parts), ZERO), sum((p.earned for p in parts), ZERO),
                                sum((p.plain * p.leaves for p in parts), ZERO) / count if count else ZERO, count,
                                sum((p.hours for p in parts), ZERO), sum((p.cost for p in parts), ZERO),
                                sum(costs, ZERO) if costs else None, min(bs) if bs else None, max(bf) if bf else None)
        return agg[tid]

    out = []
    for t, level in flat:
        a = roll(t.task_id)
        summary = bool(kids.get(t.task_id))
        percent = ((a.earned / a.weight) if a.weight else a.plain).quantize(decimal.Decimal("0.01"))
        if summary or a.ef - a.es >= 1:
            start, finish = cal.date(a.es), cal.date(a.ef - 1)
        else:  # نقطهٔ عطف روز پایان پیش‌نیازش دیده می‌شود
            start = finish = cal.date(a.es - 1) if preds_of[t.task_id] and a.es > start_idx else cal.date(a.es)
        started = bool(t.actual_start) or percent > 0
        if percent >= HUNDRED:
            state = "DONE"
        elif finish < as_of or (not started and start < as_of):
            state = "LATE"
        elif started:
            state = "RUNNING"
        else:
            state = "WAITING"
        out.append(ScheduledTask(
            t.task_id, t.parent_task_id, wbs[t.task_id], level, t.name, summary, a.ef - a.es if summary else t.duration_days,
            start, finish, a.es, a.ef, a.total_float, a.total_float <= 0, percent, a.hours, a.cost,
            None if summary else t.responsible_employee_id, "" if summary else names.get(t.responsible_employee_id, ""),
            t.actual_start, t.actual_finish, t.start_no_earlier, a.baseline_start, a.baseline_finish, a.baseline_cost,
            pred_label(t.task_id, wbs), state, t.notes or ""))

    sched = Schedule(project_id, cal.date(min(es.values(), default=start_idx)),
                     cal.date(max(end - 1, min(es.values(), default=start_idx))), out, calendar=cal)
    leaf_rows = [r for r in out if not r.is_summary]
    weight = sum((decimal.Decimal(r.duration) for r in leaf_rows), ZERO)
    if weight:
        sched.percent = (sum((decimal.Decimal(r.duration) * r.percent for r in leaf_rows), ZERO) / weight).quantize(decimal.Decimal("0.01"))
        planned = ZERO
        for r in leaf_rows:
            if r.duration <= 0:
                continue
            if r.baseline_start and r.baseline_finish:
                b0, blen = cal.index(r.baseline_start), max(cal.working_days(r.baseline_start, r.baseline_finish), 1)
            else:
                b0, blen = r.es, r.duration
            done = min(max(today_idx + 1 - b0, 0), blen)
            planned += decimal.Decimal(r.duration) * decimal.Decimal(done) / decimal.Decimal(blen) * HUNDRED
        sched.planned_percent = (planned / weight).quantize(decimal.Decimal("0.01"))
    elif leaf_rows:
        sched.percent = (sum((r.percent for r in leaf_rows), ZERO) / len(leaf_rows)).quantize(decimal.Decimal("0.01"))
    sched.planned_cost = sum((r.planned_cost for r in leaf_rows), ZERO)
    finishes = [r.baseline_finish for r in leaf_rows if r.baseline_finish]
    sched.baseline_finish = max(finishes) if finishes else None
    sched.critical_count = sum(1 for r in leaf_rows if r.critical)
    sched.late_count = sum(1 for r in leaf_rows if r.state_code == "LATE")
    return sched
