"""پایش و تحلیل گردش کار (R296): وضعیت اجراها، ریز اجرا، گلوگاه‌ها، پایبندی به مهلت، عملکرد تاییدکنندگان و خطاها.

فقط خواندن است؛ گزارش‌ها روی همان موتور گزارش برنامه (ReportDef/ReportResult) ساخته می‌شوند تا جستجو، گروه‌بندی،
چاپ و خروجی اکسل مثل بقیهٔ گزارش‌ها کار کند.
"""

from __future__ import annotations

import datetime
import decimal
from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import func, select

from peecha.db.base import new_session
from peecha.db.models.workflow import (
    WfActionExecution, WfDefinition, WfException, WfInstance, WfInstanceStep, WfTask, WfTaskDecision,
)
from peecha.services.purchase_reports import DATE, INT, PERCENT, QTY, TEXT, ReportDef, ReportResult
from peecha.services.workflow import registry
from peecha.services.workflow.common import INSTANCE_STATUS, NODE_TYPES, OUTCOMES, now, user_names

HOURS = QTY  # ساعت با یک رقم اعشار (ستون‌ها در جمع کل نمی‌آیند)
Q1 = decimal.Decimal("0.1")
STATUS_FILTERS = {"RUNNING": "در جریان", "WAITING": "منتظر اقدام", "COMPLETED": "پایان‌یافته", "FAILED": "ناموفق",
                  "CANCELLED": "لغوشده", "ESCALATED": "ارجاع‌شده به سطح بالاتر", "EXCEPTION": "نیازمند بررسی"}
_DECISIONS = {"APPROVE": "تایید", "REJECT": "رد", "CHANGES": "برگشت برای اصلاح", "DONE": "انجام"}
_TASK_DONE = ("APPROVED", "REJECTED", "CHANGES", "DONE")


def _span(date_from: datetime.date | None, date_to: datetime.date | None):
    start = datetime.datetime.combine(date_from, datetime.time.min).astimezone() if date_from else None
    end = datetime.datetime.combine(date_to + datetime.timedelta(days=1), datetime.time.min).astimezone() if date_to else None
    return start, end


def _hours(a: datetime.datetime | None, b: datetime.datetime | None) -> decimal.Decimal | None:
    if not a or not b:
        return None
    return (decimal.Decimal((b - a).total_seconds()) / 3600).quantize(Q1)


def _avg(values) -> decimal.Decimal | None:
    values = [v for v in values if v is not None]
    return (sum(values, decimal.Decimal(0)) / len(values)).quantize(Q1) if values else None


def _pct(part: int, whole: int) -> decimal.Decimal | None:
    return (decimal.Decimal(part) * 100 / whole).quantize(Q1) if whole else None


def _definitions(session, company_id: int) -> dict[int, str]:
    return {d.definition_id: d.name for d in session.scalars(select(WfDefinition).where(WfDefinition.company_id == company_id))}


def _entity_label(entity_type: str | None) -> str:
    adapter = registry.get_adapter(entity_type) if entity_type else None
    return adapter.label if adapter else ("عمومی" if not entity_type else entity_type)


# --- خلاصهٔ بالای صفحهٔ پایش --------------------------------------------------------------------------------
@dataclass
class Overview:
    running: int
    waiting: int
    completed: int
    failed: int
    cancelled: int
    escalated: int
    open_exceptions: int
    overdue_tasks: int
    avg_hours: decimal.Decimal | None
    approval_rate: decimal.Decimal | None
    on_time_rate: decimal.Decimal | None


def overview(company_id: int, date_from: datetime.date | None = None, date_to: datetime.date | None = None,
             definition_id: int | None = None) -> Overview:
    start, end = _span(date_from, date_to)
    with new_session() as session:
        q = select(WfInstance).where(WfInstance.company_id == company_id)
        if definition_id:
            q = q.where(WfInstance.definition_id == definition_id)
        rows = list(session.scalars(q))
        in_range = [r for r in rows if (start is None or r.started_at >= start) and (end is None or r.started_at < end)]
        by = defaultdict(int)
        for r in rows:
            if r.status_code in ("RUNNING", "WAITING"):
                by[r.status_code] += 1
        for r in in_range:
            if r.status_code in ("COMPLETED", "FAILED", "CANCELLED"):
                by[r.status_code] += 1
        ids = {r.instance_id for r in rows}
        tq = select(WfTask).where(WfTask.company_id == company_id)
        if definition_id:
            tq = tq.where(WfTask.instance_id.in_(ids or {-1}))
        task_rows = list(session.scalars(tq))
        escalated = len({t.instance_id for t in task_rows if (t.escalation_level or 0) > 0 and t.status_code == "OPEN"})
        t = now()
        overdue = sum(1 for x in task_rows if x.status_code == "OPEN" and x.due_at and x.due_at < t)
        closed = [x for x in task_rows if x.closed_at and x.due_at and (start is None or x.closed_at >= start)
                  and (end is None or x.closed_at < end)]
        on_time = sum(1 for x in closed if x.closed_at <= x.due_at)
        exq = select(func.count()).select_from(WfException).where(WfException.company_id == company_id,
                                                                  WfException.status_code == "OPEN")
        if definition_id:
            exq = exq.where(WfException.instance_id.in_(ids or {-1}))
        open_ex = session.scalar(exq) or 0
    done = [r for r in in_range if r.status_code == "COMPLETED"]
    decided = [r for r in done if r.outcome_code in ("APPROVED", "REJECTED")]
    return Overview(by["RUNNING"], by["WAITING"], by["COMPLETED"], by["FAILED"], by["CANCELLED"], escalated, open_ex, overdue,
                    _avg(_hours(r.started_at, r.ended_at) for r in done),
                    _pct(sum(1 for r in decided if r.outcome_code == "APPROVED"), len(decided)), _pct(on_time, len(closed)))


# --- فهرست اجراها --------------------------------------------------------------------------------------------
@dataclass
class RunRow:
    instance_id: int
    definition_id: int
    definition_name: str
    entity_type: str | None
    entity_label: str
    entity_id: int | None
    title: str
    status_code: str
    status_label: str
    outcome_label: str
    started_by: str
    started_at: datetime.datetime
    ended_at: datetime.datetime | None
    hours: decimal.Decimal | None
    waiting_on: str
    escalated: bool
    open_exception: bool
    last_error: str


def runs(company_id: int, *, status: str | None = None, definition_id: int | None = None, entity_type: str | None = None,
         date_from: datetime.date | None = None, date_to: datetime.date | None = None, search: str = "",
         limit: int = 500) -> list[RunRow]:
    start, end = _span(date_from, date_to)
    with new_session() as session:
        q = select(WfInstance).where(WfInstance.company_id == company_id)
        if status in ("RUNNING", "WAITING", "COMPLETED", "FAILED", "CANCELLED"):
            q = q.where(WfInstance.status_code == status)
        if definition_id:
            q = q.where(WfInstance.definition_id == definition_id)
        if entity_type:
            q = q.where(WfInstance.entity_type == entity_type)
        if start is not None:
            q = q.where(WfInstance.started_at >= start)
        if end is not None:
            q = q.where(WfInstance.started_at < end)
        rows = list(session.scalars(q.order_by(WfInstance.instance_id.desc()).limit(limit * 3 if search or status else limit)))
        ids = [r.instance_id for r in rows] or [-1]
        escalated = set(session.scalars(select(WfTask.instance_id).where(WfTask.instance_id.in_(ids), WfTask.status_code == "OPEN",
                                                                         WfTask.escalation_level > 0)))
        excepted = set(session.scalars(select(WfException.instance_id).where(WfException.instance_id.in_(ids),
                                                                             WfException.status_code == "OPEN")))
        names = _definitions(session, company_id)
        users = user_names(session, {r.started_by_user_id for r in rows})
        from peecha.services.workflow import runtime

        waiting = {}
        for r in rows:
            graph = runtime._graph(session, r.version_id)
            waiting[r.instance_id] = "، ".join(filter(None, ((runtime._node(graph, t["node"]) or {}).get("label") or ""
                                                            for t in r.tokens or [])))
    out = []
    for r in rows:
        if status == "ESCALATED" and r.instance_id not in escalated:
            continue
        if status == "EXCEPTION" and r.instance_id not in excepted:
            continue
        row = RunRow(r.instance_id, r.definition_id, names.get(r.definition_id, ""), r.entity_type, _entity_label(r.entity_type),
                     r.entity_id, r.title or "", r.status_code, INSTANCE_STATUS.get(r.status_code, r.status_code),
                     OUTCOMES.get(r.outcome_code or "", ""), users.get(r.started_by_user_id, "سیستم"), r.started_at, r.ended_at,
                     _hours(r.started_at, r.ended_at or now()), waiting.get(r.instance_id, ""), r.instance_id in escalated,
                     r.instance_id in excepted, r.last_error or "")
        if search and search not in f"{row.title} {row.definition_name} {row.started_by} {row.entity_label}":
            continue
        out.append(row)
        if len(out) >= limit:
            break
    return out


# --- ریز اجرا ------------------------------------------------------------------------------------------------
@dataclass
class LogRow:
    at: datetime.datetime | None
    step: str
    kind: str
    status: str
    hours: decimal.Decimal | None
    actor: str
    detail: str


_STEP_STATUS = {"DONE": "انجام شد", "RUNNING": "در حال اجرا", "WAITING": "منتظر", "FAILED": "ناموفق", "SKIPPED": "رد شد",
                "CANCELLED": "لغو شد"}
_ACTION_STATUS = {"DONE": "انجام شد", "PENDING": "در انتظار تلاش دوباره", "FAILED": "ناموفق"}


def execution_log(company_id: int, instance_id: int) -> list[LogRow]:
    """گام‌های اجرا با مدت هر گام، اجرای اقدام‌ها (با تعداد تلاش) و تصمیم‌ها، به ترتیب زمان."""
    with new_session() as session:
        inst = session.get(WfInstance, instance_id)
        if inst is None or inst.company_id != company_id:
            return []
        steps = list(session.scalars(select(WfInstanceStep).where(WfInstanceStep.instance_id == instance_id)
                                     .order_by(WfInstanceStep.step_id)))
        actions = list(session.scalars(select(WfActionExecution).where(WfActionExecution.instance_id == instance_id)))
        task_ids = list(session.scalars(select(WfTask.task_id).where(WfTask.instance_id == instance_id)))
        decisions = list(session.scalars(select(WfTaskDecision).where(WfTaskDecision.task_id.in_(task_ids or [-1]))))
        names = user_names(session, {s.actor_user_id for s in steps} | {d.user_id for d in decisions})
    rows = []
    for s in steps:
        if s.node_type == "START":
            continue
        detail = s.error or (OUTCOMES.get(s.outcome or "", "") if s.outcome else "")
        if s.attempt and s.attempt > 1:
            detail = f"{detail} (تلاش {s.attempt})".strip()
        rows.append(LogRow(s.started_at, s.label or NODE_TYPES.get(s.node_type, ""), NODE_TYPES.get(s.node_type, s.node_type),
                           _STEP_STATUS.get(s.status_code, s.status_code), _hours(s.started_at, s.ended_at),
                           names.get(s.actor_user_id, ""), detail))
    for a in actions:
        spec = registry.find_action(inst.entity_type, a.action_code)
        rows.append(LogRow(a.updated_at or a.created_at, spec.label if spec else a.action_code, "اجرای اقدام",
                           _ACTION_STATUS.get(a.status_code, a.status_code), None, "",
                           f"{a.attempts} بار تلاش" + (f" — {a.last_error[:120]}" if a.last_error else "")))
    for d in decisions:
        label = _DECISIONS.get(d.decision)
        if label:
            rows.append(LogRow(d.created_at, "تصمیم", "تصمیم", label, None, names.get(d.user_id, ""), d.comment or ""))
    return sorted(rows, key=lambda r: r.at or datetime.datetime.min.replace(tzinfo=datetime.timezone.utc))


# --- گزارش‌ها روی موتور گزارش برنامه ------------------------------------------------------------------------
def _instances(session, company_id: int, start, end):
    q = select(WfInstance).where(WfInstance.company_id == company_id)
    if start is not None:
        q = q.where(WfInstance.started_at >= start)
    if end is not None:
        q = q.where(WfInstance.started_at < end)
    return list(session.scalars(q))


def _wf_ref(instance_id: int):
    return (instance_id, "WF_INSTANCE")


def report_runs(company_id: int, f) -> ReportResult:
    r = ReportResult([("فرایند", TEXT), ("سند", TEXT), ("عنوان", TEXT), ("شروع‌کننده", TEXT), ("وضعیت", TEXT), ("نتیجه", TEXT),
                      ("شروع", DATE), ("پایان", DATE), ("مدت (ساعت)", HOURS), ("منتظر", TEXT)], no_total={8})
    status = f.options.get("status") if getattr(f, "options", None) else None
    for row in runs(company_id, status=None if status in (None, "ALL") else status, date_from=f.date_from, date_to=f.date_to,
                    limit=5000):
        r.add([row.definition_name, row.entity_label, row.title, row.started_by, row.status_label, row.outcome_label,
               row.started_at.date(), row.ended_at.date() if row.ended_at else None, row.hours, row.waiting_on],
              _wf_ref(row.instance_id))
    return r


def report_process_summary(company_id: int, f) -> ReportResult:
    r = ReportResult([("فرایند", TEXT), ("نوع سند", TEXT), ("شروع‌شده", INT), ("در جریان", INT), ("تاییدشده", INT), ("ردشده", INT),
                      ("ناموفق", INT), ("لغوشده", INT), ("درصد تایید", PERCENT), ("میانگین مدت (ساعت)", HOURS),
                      ("بیشترین مدت (ساعت)", HOURS)], no_total={8, 9, 10})
    start, end = _span(f.date_from, f.date_to)
    with new_session() as session:
        names = _definitions(session, company_id)
        defs = {d.definition_id: d for d in session.scalars(select(WfDefinition).where(WfDefinition.company_id == company_id))}
        groups = defaultdict(list)
        for i in _instances(session, company_id, start, end):
            groups[i.definition_id].append(i)
    for did, rows in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        done = [i for i in rows if i.status_code == "COMPLETED"]
        approved = sum(1 for i in done if i.outcome_code == "APPROVED")
        rejected = sum(1 for i in done if i.outcome_code == "REJECTED")
        durations = [_hours(i.started_at, i.ended_at) for i in done]
        r.add([names.get(did, ""), _entity_label(defs[did].entity_type) if did in defs else "", len(rows),
               sum(1 for i in rows if i.status_code in ("RUNNING", "WAITING")), approved, rejected,
               sum(1 for i in rows if i.status_code == "FAILED"), sum(1 for i in rows if i.status_code == "CANCELLED"),
               _pct(approved, approved + rejected), _avg(durations), max((d for d in durations if d is not None), default=None)])
    return r


def _tasks(session, company_id: int, start, end):
    q = select(WfTask).where(WfTask.company_id == company_id)
    if start is not None:
        q = q.where(WfTask.created_at >= start)
    if end is not None:
        q = q.where(WfTask.created_at < end)
    return list(session.scalars(q))


def bottleneck_rows(company_id: int, date_from=None, date_to=None) -> list[dict]:
    """هر مرحلهٔ انسانی هر فرایند: تعداد، باز، میانگین و بیشترین انتظار، گذشته از مهلت و ارجاع‌شده (کندترین بالا)."""
    start, end = _span(date_from, date_to)
    t = now()
    with new_session() as session:
        tasks = _tasks(session, company_id, start, end)
        inst_def = dict(session.execute(select(WfInstance.instance_id, WfInstance.definition_id).where(
            WfInstance.instance_id.in_({x.instance_id for x in tasks} or {-1}))).all())
        names = _definitions(session, company_id)
    groups = defaultdict(list)
    for x in tasks:
        groups[(inst_def.get(x.instance_id), x.node_id)].append(x)
    out = []
    for (did, node), rows in groups.items():
        waits = [_hours(x.created_at, x.closed_at or t) for x in rows]
        out.append({"definition": names.get(did, ""), "step": rows[0].title.split(" — ")[0], "node_id": node, "tasks": len(rows),
                    "open": sum(1 for x in rows if x.status_code == "OPEN"), "avg_hours": _avg(waits),
                    "max_hours": max((w for w in waits if w is not None), default=None),
                    "overdue": sum(1 for x in rows if x.due_at and (x.closed_at or t) > x.due_at),
                    "escalated": sum(1 for x in rows if (x.escalation_level or 0) > 0),
                    "rejected": sum(1 for x in rows if x.status_code == "REJECTED")})
    return sorted(out, key=lambda d: -(d["avg_hours"] or 0))


def report_bottlenecks(company_id: int, f) -> ReportResult:
    r = ReportResult([("فرایند", TEXT), ("مرحله", TEXT), ("تعداد کار", INT), ("باز", INT), ("میانگین انتظار (ساعت)", HOURS),
                      ("بیشترین انتظار (ساعت)", HOURS), ("گذشته از مهلت", INT), ("ارجاع‌شده", INT), ("ردشده", INT)],
                     no_total={4, 5})
    for d in bottleneck_rows(company_id, f.date_from, f.date_to):
        r.add([d["definition"], d["step"], d["tasks"], d["open"], d["avg_hours"], d["max_hours"], d["overdue"], d["escalated"],
               d["rejected"]])
    if r.rows:
        r.note = f"کندترین مرحله: «{r.rows[0][1]}» در «{r.rows[0][0]}»"
    return r


def report_sla(company_id: int, f) -> ReportResult:
    r = ReportResult([("فرایند", TEXT), ("مرحله", TEXT), ("کار دارای مهلت", INT), ("به‌موقع", INT), ("با تاخیر", INT),
                      ("هنوز باز و گذشته از مهلت", INT), ("درصد به‌موقع", PERCENT), ("ارجاع‌شده", INT)], no_total={6})
    start, end = _span(f.date_from, f.date_to)
    t = now()
    with new_session() as session:
        tasks = [x for x in _tasks(session, company_id, start, end) if x.due_at]
        inst_def = dict(session.execute(select(WfInstance.instance_id, WfInstance.definition_id).where(
            WfInstance.instance_id.in_({x.instance_id for x in tasks} or {-1}))).all())
        names = _definitions(session, company_id)
    groups = defaultdict(list)
    for x in tasks:
        groups[(inst_def.get(x.instance_id), x.node_id)].append(x)
    for (did, _node), rows in sorted(groups.items(), key=lambda kv: names.get(kv[0][0], "")):
        closed = [x for x in rows if x.closed_at]
        on_time = sum(1 for x in closed if x.closed_at <= x.due_at)
        r.add([names.get(did, ""), rows[0].title.split(" — ")[0], len(rows), on_time, len(closed) - on_time,
               sum(1 for x in rows if not x.closed_at and x.due_at < t), _pct(on_time, len(closed)),
               sum(1 for x in rows if (x.escalation_level or 0) > 0)])
    return r


def report_approvers(company_id: int, f) -> ReportResult:
    r = ReportResult([("کاربر", TEXT), ("تصمیم‌ها", INT), ("تایید", INT), ("رد", INT), ("برگشت برای اصلاح", INT),
                      ("میانگین پاسخ (ساعت)", HOURS), ("کار باز", INT), ("باز و گذشته از مهلت", INT)], no_total={5})
    start, end = _span(f.date_from, f.date_to)
    t = now()
    with new_session() as session:
        tasks = {x.task_id: x for x in session.scalars(select(WfTask).where(WfTask.company_id == company_id))}
        dq = select(WfTaskDecision).where(WfTaskDecision.task_id.in_(list(tasks) or [-1]),
                                          WfTaskDecision.decision.in_(tuple(_DECISIONS)))
        if start is not None:
            dq = dq.where(WfTaskDecision.created_at >= start)
        if end is not None:
            dq = dq.where(WfTaskDecision.created_at < end)
        decisions = list(session.scalars(dq))
        from peecha.db.models.workflow import WfTaskAssignee

        open_seats = list(session.execute(select(WfTaskAssignee.user_id, WfTaskAssignee.task_id).where(
            WfTaskAssignee.task_id.in_([k for k, v in tasks.items() if v.status_code == "OPEN"] or [-1]),
            WfTaskAssignee.status_code == "ACTIVE")))
        names = user_names(session, {d.user_id for d in decisions} | {u for u, _t in open_seats})
    stats = defaultdict(lambda: {"n": 0, "APPROVE": 0, "REJECT": 0, "CHANGES": 0, "resp": [], "open": 0, "late": 0})
    for d in decisions:
        s = stats[d.user_id]
        s["n"] += 1
        s[d.decision] = s.get(d.decision, 0) + 1
        task = tasks.get(d.task_id)
        if task is not None:
            s["resp"].append(_hours(task.created_at, d.created_at))
    for user_id, task_id in open_seats:
        s = stats[user_id]
        s["open"] += 1
        due = tasks[task_id].due_at
        s["late"] += 1 if due and due < t else 0
    for user_id, s in sorted(stats.items(), key=lambda kv: -kv[1]["n"]):
        r.add([names.get(user_id, "—"), s["n"], s["APPROVE"], s["REJECT"], s["CHANGES"], _avg(s["resp"]), s["open"], s["late"]])
    return r


def report_failures(company_id: int, f) -> ReportResult:
    r = ReportResult([("فرایند", TEXT), ("اقدام", TEXT), ("اجرا", INT), ("موفق", INT), ("ناموفق", INT), ("با تلاش دوباره", INT),
                      ("درصد موفقیت", PERCENT), ("آخرین خطا", TEXT)], no_total={6})
    start, end = _span(f.date_from, f.date_to)
    with new_session() as session:
        q = select(WfActionExecution, WfInstance).join(WfInstance, WfInstance.instance_id == WfActionExecution.instance_id).where(
            WfActionExecution.company_id == company_id)
        if start is not None:
            q = q.where(WfActionExecution.created_at >= start)
        if end is not None:
            q = q.where(WfActionExecution.created_at < end)
        rows = list(session.execute(q))
        names = _definitions(session, company_id)
    groups = defaultdict(list)
    for a, inst in rows:
        groups[(inst.definition_id, inst.entity_type, a.action_code)].append(a)
    for (did, et, code), items in sorted(groups.items(), key=lambda kv: -sum(1 for a in kv[1] if a.status_code == "FAILED")):
        spec = registry.find_action(et, code)
        ok = sum(1 for a in items if a.status_code == "DONE")
        failed = [a for a in items if a.status_code == "FAILED"]
        last = max(failed, key=lambda a: a.updated_at or a.created_at, default=None)
        r.add([names.get(did, ""), spec.label if spec else code, len(items), ok, len(failed), sum(1 for a in items if a.attempts > 1),
               _pct(ok, len(items)), (last.last_error or "")[:200] if last else ""])
    return r


def report_exceptions(company_id: int, f) -> ReportResult:
    r = ReportResult([("فرایند", TEXT), ("عنوان", TEXT), ("دلیل", TEXT), ("وضعیت", TEXT), ("ثبت", DATE), ("رسیدگی", DATE),
                      ("رسیدگی‌کننده", TEXT)])
    start, end = _span(f.date_from, f.date_to)
    labels = {"OPEN": "باز", "RESOLVED": "حل‌شده", "IGNORED": "نادیده گرفته‌شده"}
    with new_session() as session:
        q = select(WfException, WfInstance.definition_id).join(WfInstance, WfInstance.instance_id == WfException.instance_id).where(
            WfException.company_id == company_id)
        if start is not None:
            q = q.where(WfException.created_at >= start)
        if end is not None:
            q = q.where(WfException.created_at < end)
        rows = list(session.execute(q.order_by(WfException.exception_id.desc())))
        names = _definitions(session, company_id)
        users = user_names(session, {e.resolved_by_user_id for e, _d in rows})
    for e, did in rows:
        r.add([names.get(did, ""), e.title or "", e.reason or "", labels.get(e.status_code, e.status_code), e.created_at.date(),
               e.resolved_at.date() if e.resolved_at else None, users.get(e.resolved_by_user_id, "")], _wf_ref(e.instance_id))
    return r


def report_escalations(company_id: int, f) -> ReportResult:
    r = ReportResult([("فرایند", TEXT), ("کار", TEXT), ("سطح ارجاع", INT), ("مهلت", DATE), ("وضعیت", TEXT), ("بسته شدن", DATE)],
                     no_total={2})
    start, end = _span(f.date_from, f.date_to)
    labels = {"OPEN": "باز", "APPROVED": "تاییدشده", "REJECTED": "ردشده", "CHANGES": "برگشت برای اصلاح", "DONE": "انجام‌شده",
              "CANCELLED": "لغوشده"}
    with new_session() as session:
        tasks = [x for x in _tasks(session, company_id, start, end) if (x.escalation_level or 0) > 0]
        inst_def = dict(session.execute(select(WfInstance.instance_id, WfInstance.definition_id).where(
            WfInstance.instance_id.in_({x.instance_id for x in tasks} or {-1}))).all())
        names = _definitions(session, company_id)
    for x in sorted(tasks, key=lambda x: -(x.escalation_level or 0)):
        r.add([names.get(inst_def.get(x.instance_id), ""), x.title, x.escalation_level, x.due_at.date() if x.due_at else None,
               labels.get(x.status_code, x.status_code), x.closed_at.date() if x.closed_at else None], _wf_ref(x.instance_id))
    return r


_G = "گردش کار و تایید"
_STATUS_OPT = (("status", "وضعیت", (("ALL", "همه"), ("RUNNING", "در جریان"), ("WAITING", "منتظر اقدام"),
                                     ("COMPLETED", "پایان‌یافته"), ("FAILED", "ناموفق"), ("CANCELLED", "لغوشده"),
                                     ("ESCALATED", "ارجاع‌شده"), ("EXCEPTION", "نیازمند بررسی"))),)
WF_REPORTS: list[ReportDef] = [
    ReportDef("WF_RUNS", "اجرای فرایندها", report_runs, (), "هر اجرای فرایند با وضعیت، نتیجه و مدت.", "range", _G, options=_STATUS_OPT),
    ReportDef("WF_SUMMARY", "خلاصهٔ فرایندها", report_process_summary, (), "شروع، تایید، رد و میانگین مدت هر فرایند.", "range", _G),
    ReportDef("WF_BOTTLENECKS", "گلوگاه‌ها (مراحل کند)", report_bottlenecks, (), "مراحلی که بیشترین انتظار را دارند.", "range", _G),
    ReportDef("WF_SLA", "پایبندی به مهلت", report_sla, (), "کارهای به‌موقع و با تاخیر در هر مرحله.", "range", _G),
    ReportDef("WF_APPROVERS", "عملکرد تاییدکنندگان", report_approvers, (), "تصمیم‌ها، زمان پاسخ و کارهای باز هر کاربر.", "range", _G),
    ReportDef("WF_FAILURES", "خطاهای اقدام‌ها", report_failures, (), "اقدام‌های خودکار ناموفق و تلاش‌های دوباره.", "range", _G),
    ReportDef("WF_EXCEPTIONS", "موارد نیازمند بررسی", report_exceptions, (), "خطاهایی که به رسیدگی انسانی نیاز داشتند.", "range", _G),
    ReportDef("WF_ESCALATIONS", "ارجاع‌ها به سطح بالاتر", report_escalations, (), "کارهایی که از مهلت گذشتند و ارجاع شدند.",
              "range", _G),
]
WF_REPORT_MENU = [("WF_REP", _G, [(r.code, r.title) for r in WF_REPORTS])]
