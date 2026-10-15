"""تعهد زمانی کارها: موعد با ساعت کاری، یادآوری پیش از موعد، اعلام گذشتن از مهلت و ارجاع خودکار به سطح بالاتر.

هر مرحلهٔ تایید/کار می‌تواند یک «سیاست تعهد زمانی» (wf.sla_policies) یا تنظیم درجا داشته باشد:
    {"sla_policy_id": 3}  یا  {"due_hours": 8, "warn_before_hours": 2, "escalate_after_hours": 4,
                               "escalate_to": [{"kind": "ROLE", "role_id": 5}], "business_hours": true}
اگر مقصد ارجاع تعیین نشده باشد، مدیر مستقیم گیرندگان (و در نبودش مدیران شرکت) گیرندهٔ ارجاع است.
"""

from __future__ import annotations

import datetime
import decimal
from dataclasses import dataclass

from sqlalchemy import select, update

from peecha import numerals
from peecha.db.base import new_session
from peecha.db.models.workflow import WfInstance, WfSlaPolicy, WfTask, WfTaskAssignee, WfTaskDecision, WfTimer
from peecha.services.workflow import calendar, notify, routing, runtime, scheduler, tasks
from peecha.services.workflow.common import PRIORITIES, WorkflowError, audit, now, plain, settings, user_names

SLA_STATUS = {**tasks.SLA_STATUS, "NONE": "بدون مهلت"}
_SLA_TIMERS = ("REMINDER", "SLA", "ESCALATION")


@dataclass
class _Rule:
    policy_id: int | None
    due: float
    warn: float | None
    escalate_after: float | None
    escalate_to: list
    repeat: float | None
    max_escalations: int
    business: bool


def _num(v) -> float | None:
    if v in (None, ""):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _rule(session, node: dict) -> _Rule | None:
    pid = node.get("sla_policy_id")
    if pid:
        p = session.get(WfSlaPolicy, int(pid))
        if p is not None and p.is_active:
            return _Rule(p.policy_id, float(p.due_hours), _num(p.warn_before_hours), _num(p.escalate_after_hours),
                         list(p.escalate_to or []), _num(p.repeat_every_hours), int(p.max_escalations or 0), bool(p.business_hours))
    due = _num(node.get("due_hours"))
    if not due or due <= 0:
        return None
    return _Rule(None, due, _num(node.get("warn_before_hours")), _num(node.get("escalate_after_hours")),
                 list(node.get("escalate_to") or []), _num(node.get("repeat_every_hours")),
                 int(node.get("max_escalations") or 2), bool(node.get("business_hours", True)))


def _add(company_id: int, start: datetime.datetime, hours: float, business: bool) -> datetime.datetime:
    return calendar.add_business_hours(company_id, start, hours) if business else start + datetime.timedelta(hours=hours)


def _timer(session, task: WfTask, kind: str, due: datetime.datetime, **payload) -> None:
    session.add(WfTimer(company_id=task.company_id, kind=kind, instance_id=task.instance_id, task_id=task.task_id,
                        node_id=(task.node_id or "")[:40] or None, payload={"task_id": task.task_id, **plain(payload)},
                        due_at=due))


def _on_created(session, task: WfTask, node: dict) -> None:
    rule = _rule(session, node)
    if rule is None:
        return
    start = now()
    task.sla_policy_id = rule.policy_id
    task.due_at = _add(task.company_id, start, rule.due, rule.business)
    task.sla_status = "ON_TRACK"
    if rule.warn and 0 < rule.warn < rule.due:
        task.warn_at = _add(task.company_id, start, rule.due - rule.warn, rule.business)
        _timer(session, task, "REMINDER", task.warn_at)
    _timer(session, task, "SLA", task.due_at)
    if rule.escalate_after is not None:
        task.escalate_at = _add(task.company_id, task.due_at, rule.escalate_after, rule.business) \
            if rule.escalate_after > 0 else task.due_at
        _timer(session, task, "ESCALATION", task.escalate_at, level=1)


def _on_closed(session, task: WfTask) -> None:
    if task.sla_status in ("ON_TRACK", "AT_RISK"):
        task.sla_status = "MET"
    session.execute(update(WfTimer).where(WfTimer.task_id == task.task_id, WfTimer.status_code == "PENDING",
                                          WfTimer.kind.in_(_SLA_TIMERS)).values(status_code="CANCELLED"))


tasks.TASK_CREATED_HOOKS.append(_on_created)
tasks.TASK_CLOSED_HOOKS.append(_on_closed)


def _active_users(session, task_id: int) -> list[int]:
    return list(session.scalars(select(WfTaskAssignee.user_id).where(WfTaskAssignee.task_id == task_id,
                                                                     WfTaskAssignee.status_code == "ACTIVE")))


def _due_text(at: datetime.datetime | None) -> str:
    return numerals.format_jalali_datetime(at) if at else ""


def _reminder(timer: WfTimer) -> None:
    with new_session() as session:
        task = session.scalar(select(WfTask).where(WfTask.task_id == timer.payload.get("task_id")).with_for_update())
        if task is None or task.status_code != "OPEN":
            return
        if task.sla_status == "ON_TRACK":
            task.sla_status = "AT_RISK"
        notify.later(session, task.company_id, _active_users(session, task.task_id), "WF_TASK_DUE",
                     f"یادآوری: موعد «{task.title}» نزدیک است", f"موعد: {_due_text(task.due_at)}", "WfTask", task.task_id)
        session.commit()


def _breach(timer: WfTimer) -> None:
    with new_session() as session:
        task = session.scalar(select(WfTask).where(WfTask.task_id == timer.payload.get("task_id")).with_for_update())
        if task is None or task.status_code != "OPEN":
            return
        task.sla_status = "BREACHED"
        if task.priority_code in ("LOW", "NORMAL"):
            task.priority_code = "HIGH"
        task.row_version += 1
        notify.later(session, task.company_id, _active_users(session, task.task_id), "WF_SLA_BREACHED",
                     f"مهلت «{task.title}» گذشت", f"موعد بود: {_due_text(task.due_at)}", "WfTask", task.task_id)
        session.commit()


def _escalation_targets(session, task: WfTask, specs: list) -> list[int]:
    if specs:
        inst = session.get(WfInstance, task.instance_id) if task.instance_id else None
        ctx = (inst.context or {}) if inst else {}
        return routing.resolve(task.company_id, specs, context=ctx, starter=inst.started_by_user_id if inst else None,
                               entity_type=task.entity_type, entity_id=task.entity_id)
    out = []
    for uid in _active_users(session, task.task_id):
        manager = routing._unit_manager(session, routing._employee_unit(session, task.company_id, uid), exclude=uid)
        if manager and manager not in out:
            out.append(manager)
    return out or routing.resolve(task.company_id, [{"kind": "MANAGERS"}])


def _escalate(timer: WfTimer) -> None:
    level = int(timer.payload.get("level") or 1)
    with new_session() as session:
        task = session.scalar(select(WfTask).where(WfTask.task_id == timer.payload.get("task_id")).with_for_update())
        if task is None or task.status_code != "OPEN":
            return
        node = {}
        if task.instance_id:
            inst = session.get(WfInstance, task.instance_id)
            node = runtime._node(runtime._graph(session, inst.version_id), task.node_id) or {}
        rule = _rule(session, node) or _Rule(None, 0, None, 0, [], None, 1, True)
        allow_self = bool(settings(task.company_id).get("allow_self_approval"))
        seats = {a.user_id: a for a in session.scalars(select(WfTaskAssignee).where(WfTaskAssignee.task_id == task.task_id))}
        added = []
        for uid in _escalation_targets(session, task, rule.escalate_to):
            if task.kind == "APPROVAL" and uid == task.requested_by_user_id and not allow_self:
                continue
            seat = seats.get(uid)
            if seat is not None and seat.status_code == "ACTIVE":
                continue
            if seat is not None:
                seat.status_code, seat.decision, seat.decided_at, seat.activated_at = "ACTIVE", None, None, now()
            else:
                session.add(WfTaskAssignee(task_id=task.task_id, user_id=uid, seq=max([a.seq for a in seats.values()] or [0]) + 1,
                                           status_code="ACTIVE", activated_at=now()))
            added.append(uid)
        current = _active_users(session, task.task_id)
        task.escalation_level = level
        task.sla_status = "BREACHED"
        task.priority_code = "CRITICAL" if level >= 2 else "HIGH"
        task.row_version += 1
        session.add(WfTaskDecision(task_id=task.task_id, user_id=None, decision="ESCALATE",
                                   comment=f"ارجاع خودکار سطح {numerals.to_persian_digits(str(level))} به‌خاطر گذشتن از مهلت",
                                   data={"to": added, "level": level}))
        audit(session, task.company_id, None, "Task", task.task_id, "ESCALATE", {"to": added, "level": level})
        names = user_names(session, added)
        notify.later(session, task.company_id, added, "WF_ESCALATION", f"ارجاع به شما: {task.title}",
                     "این کار از مهلتش گذشته و برای پیگیری به شما ارجاع شد.", "WfTask", task.task_id)
        others = [u for u in current if u not in added]
        if others and added:
            notify.later(session, task.company_id, others, "WF_SLA_BREACHED", f"«{task.title}» به سطح بالاتر ارجاع شد",
                         "ارجاع به: " + "، ".join(names.get(u, "") for u in added), "WfTask", task.task_id)
        if rule.repeat and level < max(rule.max_escalations, 1):
            _timer(session, task, "ESCALATION", _add(task.company_id, now(), rule.repeat, rule.business), level=level + 1)
        session.commit()


scheduler.register_timer("REMINDER", _reminder)
scheduler.register_timer("SLA", _breach)
scheduler.register_timer("ESCALATION", _escalate)


def remind_now(company_id: int, task_id: int, by_user_id: int, note: str = "") -> int:
    """درخواست‌کننده یا مدیر یادآوری دستی می‌فرستد."""
    from peecha.services import roles as roles_service

    with new_session() as session:
        task = session.get(WfTask, task_id)
        if task is None or task.company_id != company_id:
            raise WorkflowError("کار نامعتبر است.")
        if task.status_code != "OPEN":
            raise WorkflowError("این کار دیگر باز نیست.")
        if by_user_id != task.requested_by_user_id and not roles_service.is_manager(by_user_id, company_id):
            raise WorkflowError("فقط درخواست‌کننده یا مدیر می‌تواند یادآوری بفرستد.")
        targets = _active_users(session, task_id)
        notify.later(session, company_id, targets, "WF_TASK_DUE", f"یادآوری: «{task.title}» منتظر شماست",
                     (note or "").strip() or (f"موعد: {_due_text(task.due_at)}" if task.due_at else ""), "WfTask", task_id)
        session.add(WfTaskDecision(task_id=task_id, user_id=by_user_id, decision="COMMENT",
                                   comment=("یادآوری: " + (note or "").strip()).strip(" :")[:2000]))
        session.commit()
        return len(targets)


# --- سیاست‌های تعهد زمانی ------------------------------------------------------------------------------------------
@dataclass
class PolicyRow:
    policy_id: int
    code: str
    name: str
    due_hours: decimal.Decimal
    warn_before_hours: decimal.Decimal | None
    escalate_after_hours: decimal.Decimal | None
    escalate_to: list
    escalate_to_text: str
    repeat_every_hours: decimal.Decimal | None
    max_escalations: int
    business_hours: bool
    is_active: bool


def list_policies(company_id: int, active_only: bool = False) -> list[PolicyRow]:
    with new_session() as session:
        q = select(WfSlaPolicy).where(WfSlaPolicy.company_id == company_id)
        if active_only:
            q = q.where(WfSlaPolicy.is_active.is_(True))
        rows = list(session.scalars(q.order_by(WfSlaPolicy.due_hours, WfSlaPolicy.code)))
        roles = routing.role_names(session, [s.get("role_id") for r in rows for s in (r.escalate_to or [])])
        users = user_names(session, [s.get("user_id") for r in rows for s in (r.escalate_to or [])])
        return [PolicyRow(r.policy_id, r.code, r.name, r.due_hours, r.warn_before_hours, r.escalate_after_hours,
                          list(r.escalate_to or []),
                          "، ".join(routing.describe_spec(s, roles, users) for s in r.escalate_to or []) or "مدیر مستقیم گیرنده",
                          r.repeat_every_hours, r.max_escalations, r.business_hours, r.is_active) for r in rows]


def save_policy(company_id: int, user_id: int | None, policy_id: int | None, *, code: str, name: str, due_hours,
                warn_before_hours=None, escalate_after_hours=None, escalate_to: list | None = None, repeat_every_hours=None,
                max_escalations: int = 2, business_hours: bool = True, is_active: bool = True) -> int:
    code, name = (code or "").strip().upper(), (name or "").strip()
    if not code or not name:
        raise WorkflowError("کد و نام سیاست الزامی است.")
    due = _num(due_hours)
    if not due or due <= 0:
        raise WorkflowError("مهلت انجام باید بیشتر از صفر ساعت باشد.")
    warn = _num(warn_before_hours)
    if warn is not None and not 0 < warn < due:
        raise WorkflowError("یادآوری باید بین صفر و کل مهلت باشد.")
    esc = _num(escalate_after_hours)
    if esc is not None and esc < 0:
        raise WorkflowError("زمان ارجاع نمی‌تواند منفی باشد.")
    rep = _num(repeat_every_hours)
    if rep is not None and rep <= 0:
        raise WorkflowError("فاصلهٔ تکرار ارجاع باید بیشتر از صفر باشد.")
    with new_session() as session:
        dup = session.scalar(select(WfSlaPolicy.policy_id).where(WfSlaPolicy.company_id == company_id, WfSlaPolicy.code == code))
        if dup and dup != policy_id:
            raise WorkflowError("این کد قبلاً استفاده شده است.")
        row = session.get(WfSlaPolicy, policy_id) if policy_id else WfSlaPolicy(company_id=company_id)
        if row is None or row.company_id != company_id:
            raise WorkflowError("سیاست نامعتبر است.")
        D = lambda v: decimal.Decimal(str(v)) if v is not None else None  # noqa: E731
        row.code, row.name, row.due_hours, row.warn_before_hours = code, name[:150], D(due), D(warn)
        row.escalate_after_hours, row.escalate_to, row.repeat_every_hours = D(esc), plain(list(escalate_to or [])), D(rep)
        row.max_escalations, row.business_hours, row.is_active = max(int(max_escalations or 1), 1), bool(business_hours), bool(is_active)
        session.add(row)
        session.flush()
        audit(session, company_id, user_id, "SlaPolicy", row.policy_id, "UPDATE" if policy_id else "CREATE",
              {"code": code, "due_hours": due, "warn": warn, "escalate_after": esc})
        session.commit()
        return row.policy_id


def delete_policy(company_id: int, user_id: int | None, policy_id: int) -> str:
    """سیاست استفاده‌شده غیرفعال می‌شود (کارهای گذشته معنایشان را از دست ندهند)؛ بقیه حذف."""
    with new_session() as session:
        row = session.get(WfSlaPolicy, policy_id)
        if row is None or row.company_id != company_id:
            raise WorkflowError("سیاست نامعتبر است.")
        used = session.scalar(select(WfTask.task_id).where(WfTask.sla_policy_id == policy_id).limit(1))
        if used:
            row.is_active = False
            result = "DEACTIVATED"
        else:
            session.delete(row)
            result = "DELETED"
        audit(session, company_id, user_id, "SlaPolicy", policy_id, "DELETE", {"result": result})
        session.commit()
        return result


def sla_label(status: str) -> str:
    return SLA_STATUS.get(status, status)


def priority_label(code: str) -> str:
    return PRIORITIES.get(code, code)


scheduler.register_tick("deliveries", notify.deliver_pending)
