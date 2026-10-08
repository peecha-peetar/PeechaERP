"""کار و تایید انسانی موتور گردش کار.

گره «تایید» و «کار» یک کار (wf.tasks) با گیرندگان مشخص می‌سازد و فرایند منتظر می‌ماند. شیوه‌های تایید: یک نفر،
اولین تصمیم، همه، درصدی و ترتیبی. تفکیک وظایف (درخواست‌کننده درخواست خودش را تایید نمی‌کند)، تفویض اختیار، واگذاری،
ارجاع دوباره، یادداشت و برگشت برای اصلاح. هر تصمیم ثبت تغییرناپذیر دارد؛ row_version جلوی تصمیم هم‌زمان را می‌گیرد و
تصمیم تکراری از موبایل (همان client_ref) بی‌اثر است.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass

from sqlalchemy import or_, select, update

from peecha.db.base import new_session
from peecha.db.models.workflow import (
    WfDefinition, WfDelegation, WfException, WfInstance, WfTask, WfTaskAssignee, WfTaskDecision, WfTimer,
)
from peecha.services import roles as roles_service
from peecha.services.workflow import conditions, definitions, notify, registry, routing, runtime, scheduler
from peecha.services.workflow.common import (
    PRIORITIES, WorkflowError, audit, display, now, plain, render, settings, user_names,
)

KINDS = {"APPROVAL": "تایید", "TASK": "کار"}
TASK_STATUS = {"OPEN": "در انتظار", "APPROVED": "تاییدشده", "REJECTED": "ردشده", "CHANGES": "برگشت برای اصلاح",
               "DONE": "انجام‌شده", "CANCELLED": "لغوشده", "EXPIRED": "مهلت تمام شد"}
MODES = {"SINGLE": "یک نفر", "ANY": "اولین تصمیم کافی است", "ALL": "همه باید تایید کنند",
         "PERCENT": "درصدی از گیرندگان", "SEQUENTIAL": "به ترتیب، یکی پس از دیگری"}
DECISIONS = {"APPROVE": "تایید", "REJECT": "رد", "CHANGES": "برگشت برای اصلاح", "DONE": "انجام شد", "COMMENT": "یادداشت",
             "DELEGATE": "واگذاری", "REASSIGN": "ارجاع دوباره", "CANCEL": "لغو"}
SEAT_STATUS = {"QUEUED": "در نوبت", "ACTIVE": "منتظر تصمیم", "DECIDED": "تصمیم گرفت", "SKIPPED": "نیازی نشد",
               "DELEGATED": "واگذار کرد", "CANCELLED": "لغو شد"}
FIELD_KINDS = {"text": "متن", "number": "عدد", "date": "تاریخ", "bool": "بله/خیر", "choice": "انتخاب از فهرست"}
_OUTCOME = {"APPROVED": "approved", "REJECTED": "rejected", "CHANGES": "changes", "DONE": "done", "EXPIRED": "timeout"}
_LIVE = ("ACTIVE", "QUEUED")


# --- ساخت کار از گرهٔ فرایند --------------------------------------------------------------------------------
def _requester(run: runtime.Run, ctx: dict) -> int | None:
    field = run.adapter.submitter_field if run.adapter else None
    value = conditions.get_path(ctx, field) if field else None
    try:
        return int(value) if value else run.instance.started_by_user_id
    except (TypeError, ValueError):
        return run.instance.started_by_user_id


def due_at(node: dict, start: datetime.datetime | None = None) -> datetime.datetime | None:
    """موعد کار؛ R293 آن را با تقویم کاری (روز تعطیل/ساعت کاری) جایگزین می‌کند."""
    hours = float(node.get("due_hours") or 0) + 24 * float(node.get("due_days") or 0)
    return (start or now()) + datetime.timedelta(hours=hours) if hours > 0 else None


DUE_CALCULATOR = due_at  # نقطهٔ جایگزینی (company_id, node, start) در R293


def _active_delegation(session, company_id: int, user_id: int, definition_id: int | None, entity_type: str | None,
                       on: datetime.date) -> WfDelegation | None:
    rows = session.scalars(select(WfDelegation).where(
        WfDelegation.company_id == company_id, WfDelegation.from_user_id == user_id, WfDelegation.is_active.is_(True),
        WfDelegation.starts_on <= on, WfDelegation.ends_on >= on,
        or_(WfDelegation.definition_id.is_(None), WfDelegation.definition_id == definition_id),
        or_(WfDelegation.entity_type.is_(None), WfDelegation.entity_type == entity_type)))
    # تفویض مخصوص یک فرایند/نوع سند بر تفویض عمومی مقدم است
    return min(rows, key=lambda d: (d.definition_id is None, d.entity_type is None, -d.delegation_id), default=None)


def _with_delegations(session, company_id: int, users: list[int], definition_id: int | None, entity_type: str | None,
                      excluded: set[int]) -> list[tuple[int, int | None, int | None]]:
    """[(کاربر نهایی، کاربر اصلی اگر تفویض شد، شناسهٔ تفویض)]"""
    members = set(routing.company_users(session, company_id))
    today = datetime.date.today()
    out, seen = [], set()
    for uid in users:
        target, delegation_id = uid, None
        for _hop in range(3):
            d = _active_delegation(session, company_id, target, definition_id, entity_type, today)
            if d is None or d.to_user_id in excluded or d.to_user_id not in members or d.to_user_id == uid:
                break
            target, delegation_id = d.to_user_id, d.delegation_id
        if target in seen:
            continue
        seen.add(target)
        out.append((target, uid if target != uid else None, delegation_id))
    return out


def _previous_approvers(session, instance_id: int) -> set[int]:
    return set(session.scalars(select(WfTaskDecision.user_id).join(WfTask, WfTask.task_id == WfTaskDecision.task_id).where(
        WfTask.instance_id == instance_id, WfTaskDecision.decision == "APPROVE")))


def _notify_seats(session, task: WfTask, user_ids) -> None:
    if not user_ids:
        return
    if task.kind == "APPROVAL":
        notify.later(session, task.company_id, user_ids, "WF_APPROVAL_REQUIRED", f"نیاز به تایید شما: {task.title}",
                     task.instructions or "", "WfTask", task.task_id)
    else:
        notify.later(session, task.company_id, user_ids, "WF_TASK_ASSIGNED", f"کار تازه: {task.title}",
                     task.instructions or "", "WfTask", task.task_id)


def _human_node(run: runtime.Run) -> runtime.NodeResult:
    session, inst, node = run.session, run.instance, run.node
    visit = int(run.token.get("visit", 1))
    existing = session.scalar(select(WfTask).where(WfTask.instance_id == inst.instance_id, WfTask.node_id == node["id"],
                                                   WfTask.visit == visit))
    if existing is not None:  # اجرای دوباره پس از قطعی: همان کار قبلی
        return runtime.NodeResult("WAIT", detail={"task_id": existing.task_id}, token_patch={"task_id": existing.task_id})
    kind = node["type"]
    ctx = run.refresh_context()
    requester = _requester(run, ctx)
    allow_self = bool(settings(inst.company_id).get("allow_self_approval"))
    specs = (node.get("approvers") if kind == "APPROVAL" else node.get("assignees")) or []
    resolve = lambda s: routing.resolve(inst.company_id, s, context=ctx, starter=inst.started_by_user_id,  # noqa: E731
                                        entity_type=inst.entity_type, entity_id=inst.entity_id)
    excluded: set[int] = set()
    if kind == "APPROVAL" and requester and not allow_self:
        excluded.add(requester)
    if kind == "APPROVAL" and node.get("distinct_approvers"):
        excluded |= _previous_approvers(session, inst.instance_id)
    users = [u for u in resolve(specs) if u not in excluded]
    if not users and node.get("fallback"):
        users = [u for u in resolve(node["fallback"]) if u not in excluded]
    raw_mode = (node.get("mode") or "ANY").upper()
    mode = raw_mode if kind == "APPROVAL" else ("ALL" if raw_mode == "ALL" else "ANY")
    whens = {e.get("when") for e in definitions.outgoing(run.graph, node["id"])}
    labels = run.labels()
    title = render(node.get("title") or "", {**ctx, "عنوان": inst.title}, labels).strip() or \
        f"{node.get('label') or KINDS[kind]} — {inst.title or ''}".strip(" —")
    task = WfTask(company_id=inst.company_id, instance_id=inst.instance_id, node_id=node["id"], token_id=run.token["id"],
                  visit=visit, kind=kind, title=title[:300],
                  instructions=(render(node.get("instructions") or "", {**ctx, "عنوان": inst.title}, labels) or None),
                  entity_type=inst.entity_type, entity_id=inst.entity_id, mode=mode,
                  required_percent=int(node.get("percent") or 0) or None if mode == "PERCENT" else None,
                  options={"allow_changes": "changes" in whens, "allow_delegate": bool(node.get("allow_delegate", True)),
                           "require_comment_on_reject": bool(node.get("require_comment_on_reject", True)),
                           "definition_id": inst.definition_id},
                  form_fields=plain(list(node.get("fields") or [])), priority_code=node.get("priority") or "NORMAL",
                  requested_by_user_id=requester, due_at=DUE_CALCULATOR(node))
    session.add(task)
    session.flush()
    seats = _with_delegations(session, inst.company_id, users, inst.definition_id, inst.entity_type, excluded)
    active = []
    for i, (uid, original, delegation_id) in enumerate(seats):
        state = "QUEUED" if mode == "SEQUENTIAL" and i > 0 else "ACTIVE"
        session.add(WfTaskAssignee(task_id=task.task_id, user_id=uid, seq=i + 1, status_code=state, original_user_id=original,
                                   delegation_id=delegation_id, activated_at=now() if state == "ACTIVE" else None))
        if state == "ACTIVE":
            active.append(uid)
    session.flush()
    if not seats:
        runtime._raise_exception(
            session, inst, node, f"برای «{node.get('label') or KINDS[kind]}» کسی پیدا نشد",
            "هیچ کاربر فعالی با تنظیمات این مرحله منطبق نیست (یا تنها گزینه خود درخواست‌کننده است). "
            "کار را از «مرکز تایید» به فرد مناسب ارجاع دهید.", None)
    _notify_seats(session, task, active)
    if node.get("timeout_hours") and "timeout" in whens:
        session.add(WfTimer(company_id=inst.company_id, kind="WAIT", instance_id=inst.instance_id, node_id=node["id"],
                            task_id=task.task_id, payload={"token_id": run.token["id"], "when": "timeout"},
                            due_at=now() + datetime.timedelta(hours=float(node["timeout_hours"]))))
    return runtime.NodeResult("WAIT", detail={"task_id": task.task_id, "assignees": [s[0] for s in seats]},
                              token_patch={"task_id": task.task_id})


runtime.register_node("APPROVAL", _human_node)
runtime.register_node("TASK", _human_node)


def _close_open_tasks(session, instance_id: int, *, token_id: str | None = None, status: str = "CANCELLED") -> None:
    q = select(WfTask).where(WfTask.instance_id == instance_id, WfTask.status_code == "OPEN")
    if token_id:
        q = q.where(WfTask.token_id == token_id)
    for task in session.scalars(q.with_for_update()):
        task.status_code, task.closed_at, task.resumed_at = status, now(), now()
        task.row_version += 1
        session.execute(update(WfTaskAssignee).where(WfTaskAssignee.task_id == task.task_id,
                                                     WfTaskAssignee.status_code.in_(_LIVE)).values(status_code="CANCELLED"))


def _on_leave(session, inst: WfInstance, token: dict, when: str | None) -> None:
    if not token.get("task_id"):
        return
    _close_open_tasks(session, inst.instance_id, token_id=token["id"], status="EXPIRED" if when == "timeout" else "CANCELLED")
    if when != "timeout":  # زمان‌سنج مهلت دیگر لازم نیست
        session.execute(update(WfTimer).where(WfTimer.instance_id == inst.instance_id, WfTimer.status_code == "PENDING",
                                              WfTimer.task_id == token["task_id"]).values(status_code="CANCELLED"))


runtime.on_leave(_on_leave)
runtime.on_close(lambda session, inst, status: _close_open_tasks(session, inst.instance_id))


# --- تصمیم --------------------------------------------------------------------------------------------------
@dataclass
class DecisionResult:
    task_id: int
    status_code: str
    closed: bool
    message: str


def _lock(session, company_id: int, task_id: int) -> WfTask:
    task = session.scalar(select(WfTask).where(WfTask.task_id == task_id).with_for_update())
    if task is None or task.company_id != company_id:
        raise WorkflowError("کار نامعتبر است.")
    return task


def _require_open(task: WfTask, row_version: int | None = None) -> None:
    if task.status_code != "OPEN":
        raise WorkflowError(f"این کار قبلاً بسته شده است (وضعیت: {TASK_STATUS.get(task.status_code, task.status_code)}).")
    if row_version is not None and int(row_version) != task.row_version:
        raise WorkflowError("این کار هم‌زمان توسط کاربر دیگری تغییر کرده است؛ فهرست را تازه کنید و دوباره تصمیم بگیرید.")


def _seat(session, task: WfTask, user_id: int) -> WfTaskAssignee:
    rows = list(session.scalars(select(WfTaskAssignee).where(WfTaskAssignee.task_id == task.task_id,
                                                             WfTaskAssignee.user_id == user_id)))
    seat = next((r for r in rows if r.status_code == "ACTIVE"), None)
    if seat is not None:
        return seat
    if any(r.status_code == "QUEUED" for r in rows):
        raise WorkflowError("هنوز نوبت تصمیم شما نرسیده است.")
    if any(r.status_code == "DECIDED" for r in rows):
        raise WorkflowError("شما قبلاً برای این کار تصمیم گرفته‌اید.")
    raise WorkflowError("این کار به شما ارجاع نشده است.")


def _check_sod(task: WfTask, user_id: int) -> None:
    if task.kind == "APPROVAL" and task.requested_by_user_id == user_id and \
            not settings(task.company_id).get("allow_self_approval"):
        raise WorkflowError("تفکیک وظایف: درخواست‌کننده نمی‌تواند درخواست خودش را تایید کند.")


def allowed_decisions(task: WfTask) -> list[str]:
    if task.kind == "TASK":
        return ["DONE"]
    return ["APPROVE", "REJECT"] + (["CHANGES"] if (task.options or {}).get("allow_changes") else [])


def _validate_form(fields: list[dict], data: dict) -> dict:
    out = {}
    for f in fields or []:
        key, label = f.get("key"), f.get("label") or f.get("key")
        value = (data or {}).get(key)
        if value in (None, "", []):
            if f.get("required"):
                raise WorkflowError(f"«{label}» را وارد کنید.")
            continue
        kind = f.get("kind") or "text"
        if kind == "number":
            value = conditions._number(value)
            if value is None:
                raise WorkflowError(f"«{label}» باید عدد باشد.")
        elif kind == "date":
            value = conditions._date(value, datetime.date.today())
            if value is None:
                raise WorkflowError(f"«{label}» تاریخ معتبر نیست.")
        elif kind == "bool":
            value = value is True or str(value).strip().lower() in ("1", "true", "بله", "yes")
        elif kind == "choice" and f.get("choices") and value not in f["choices"]:
            raise WorkflowError(f"مقدار «{label}» از گزینه‌های مجاز نیست.")
        out[key] = value
    return out


def _aggregate(session, task: WfTask, decision: str) -> tuple[str | None, list[int]]:
    """وضعیت پایانی کار پس از این تصمیم (یا None اگر هنوز باز است) و گیرندگانی که تازه نوبتشان شد."""
    rows = list(session.scalars(select(WfTaskAssignee).where(
        WfTaskAssignee.task_id == task.task_id, WfTaskAssignee.status_code.notin_(("DELEGATED", "CANCELLED")))
        .order_by(WfTaskAssignee.seq, WfTaskAssignee.assignee_id)))
    live = [r for r in rows if r.status_code in _LIVE]
    if decision == "CHANGES":
        return "CHANGES", []
    if decision == "DONE":
        return (None if task.mode == "ALL" and live else "DONE"), []
    if task.mode in ("SINGLE", "ANY"):
        return ("APPROVED" if decision == "APPROVE" else "REJECTED"), []
    if decision == "REJECT" and task.mode in ("ALL", "SEQUENTIAL"):
        return "REJECTED", []
    if task.mode == "ALL":
        return (None if live else "APPROVED"), []
    if task.mode == "SEQUENTIAL":
        nxt = next((r for r in rows if r.status_code == "QUEUED"), None)
        if nxt is None:
            return "APPROVED", []
        nxt.status_code, nxt.activated_at = "ACTIVE", now()
        return None, [nxt.user_id]
    total = len(rows) or 1
    need = task.required_percent or 100
    approvals = sum(1 for r in rows if r.decision == "APPROVE")
    rejects = sum(1 for r in rows if r.decision == "REJECT")
    if approvals * 100 >= need * total:
        return "APPROVED", []
    if (total - rejects) * 100 < need * total:
        return "REJECTED", []
    return None, []


def decide(company_id: int, task_id: int, user_id: int, decision: str, comment: str = "", *, data: dict | None = None,
           row_version: int | None = None, client_ref: str | None = None, channel: str = "DESKTOP") -> DecisionResult:
    decision = (decision or "").upper()
    comment = (comment or "").strip()
    if decision not in ("APPROVE", "REJECT", "CHANGES", "DONE"):
        raise WorkflowError("تصمیم نامعتبر است.")
    with new_session() as session:
        task = _lock(session, company_id, task_id)
        if client_ref and session.scalar(select(WfTaskDecision.decision_id).where(
                WfTaskDecision.task_id == task_id, WfTaskDecision.client_ref == client_ref)):
            return DecisionResult(task_id, task.status_code, task.status_code != "OPEN", "این تصمیم قبلاً ثبت شده بود.")
        _require_open(task, row_version)
        if decision not in allowed_decisions(task):
            raise WorkflowError("این تصمیم برای این مرحله مجاز نیست.")
        seat = _seat(session, task, user_id)
        _check_sod(task, user_id)
        if decision in ("REJECT", "CHANGES") and (task.options or {}).get("require_comment_on_reject", True) and not comment:
            raise WorkflowError("لطفاً علت رد یا موارد اصلاحی را بنویسید.")
        values = _validate_form(task.form_fields or [], data or {}) if decision == "DONE" else {}
        session.add(WfTaskDecision(task_id=task_id, user_id=user_id, on_behalf_of_user_id=seat.original_user_id,
                                   decision=decision, comment=comment or None, data=plain(values), client_ref=client_ref,
                                   channel=(channel or "DESKTOP")[:10]))
        seat.status_code, seat.decision, seat.decided_at = "DECIDED", decision, now()
        session.flush()
        closing, activated = _aggregate(session, task, decision)
        task.row_version += 1
        if closing:
            task.status_code, task.closed_at, task.closed_by_user_id = closing, now(), user_id
            if values:
                task.result = plain(values)
            session.execute(update(WfTaskAssignee).where(WfTaskAssignee.task_id == task_id,
                                                         WfTaskAssignee.status_code.in_(_LIVE)).values(status_code="SKIPPED"))
        audit(session, company_id, user_id, "Task", task_id,
              {"APPROVE": "APPROVE", "REJECT": "REJECT", "CHANGES": "REJECT", "DONE": "COMPLETE"}[decision],
              {"decision": decision, "comment": comment, "result": closing, "on_behalf_of": seat.original_user_id,
               "channel": channel})
        _notify_seats(session, task, activated)
        if closing in ("REJECTED", "CHANGES") and task.requested_by_user_id:
            verb = "رد شد" if closing == "REJECTED" else "برای اصلاح برگشت داده شد"
            notify.later(session, company_id, [task.requested_by_user_id], "WF_MESSAGE", f"«{task.title}» {verb}", comment,
                         "WfTask", task_id)
        status = task.status_code
        session.commit()
    if closing:
        resume_task(company_id, task_id)
    message = {"APPROVED": "تایید نهایی شد.", "REJECTED": "رد شد.", "CHANGES": "برای اصلاح برگشت داده شد.",
               "DONE": "انجام شد."}.get(closing or "", "تصمیم شما ثبت شد؛ کار منتظر تصمیم بقیه است.")
    return DecisionResult(task_id, status, bool(closing), message)


def resume_task(company_id: int, task_id: int) -> bool:
    """فرایند پس از بسته‌شدن کار از مسیر همان نتیجه ادامه می‌یابد (تکرارپذیر: دوباره ادامه نمی‌دهد)."""
    with new_session() as session:
        task = session.get(WfTask, task_id)
        if task is None or task.resumed_at or task.instance_id is None or task.status_code not in _OUTCOME:
            return False
        last = session.scalar(select(WfTaskDecision).where(WfTaskDecision.task_id == task_id,
                                                           WfTaskDecision.decision.in_(("APPROVE", "REJECT", "CHANGES", "DONE")))
                              .order_by(WfTaskDecision.decision_id.desc()))
        args = dict(token_id=task.token_id, when=_OUTCOME[task.status_code], actor_user_id=task.closed_by_user_id,
                    detail={"task_id": task_id, "comment": last.comment if last else None},
                    vars_patch={task.node_id: task.result} if task.result else None)
        instance_id = task.instance_id
    ok = runtime.resume(company_id, instance_id, **args)
    with new_session() as session:
        session.execute(update(WfTask).where(WfTask.task_id == task_id, WfTask.resumed_at.is_(None)).values(resumed_at=now()))
        session.commit()
    return ok


def resume_closed(company_id: int | None = None) -> int:
    """کارهای بسته‌شده‌ای که ادامهٔ فرایندشان (مثلاً با قطعی برنامه) انجام نشده بود."""
    with new_session() as session:
        q = select(WfTask.company_id, WfTask.task_id).where(WfTask.resumed_at.is_(None), WfTask.instance_id.isnot(None),
                                                           WfTask.status_code.in_(tuple(_OUTCOME)))
        if company_id is not None:
            q = q.where(WfTask.company_id == company_id)
        rows = list(session.execute(q))
    return sum(1 for cid, tid in rows if resume_task(cid, tid))


scheduler.register_tick("tasks", resume_closed)


# --- واگذاری، ارجاع، یادداشت، پس‌گرفتن -------------------------------------------------------------------------
def _is_manager(user_id: int, company_id: int) -> bool:
    return roles_service.is_manager(user_id, company_id)


def _check_target(session, task: WfTask, to_user_id: int) -> None:
    if to_user_id not in set(routing.company_users(session, task.company_id)):
        raise WorkflowError("کاربر انتخاب‌شده در این شرکت فعال نیست.")
    if task.kind == "APPROVAL" and to_user_id == task.requested_by_user_id and \
            not settings(task.company_id).get("allow_self_approval"):
        raise WorkflowError("تفکیک وظایف: کار تایید را نمی‌توان به خود درخواست‌کننده سپرد.")


def delegate_task(company_id: int, task_id: int, user_id: int, to_user_id: int, comment: str = "") -> None:
    """گیرنده سهم خودش از این کار را به همکار دیگری می‌سپارد."""
    with new_session() as session:
        task = _lock(session, company_id, task_id)
        _require_open(task)
        if not (task.options or {}).get("allow_delegate", True):
            raise WorkflowError("واگذاری این کار در تعریف فرایند مجاز نیست.")
        seat = _seat(session, task, user_id)
        if to_user_id == user_id:
            raise WorkflowError("کار را نمی‌توان به خودتان واگذار کرد.")
        _check_target(session, task, to_user_id)
        if session.scalar(select(WfTaskAssignee.assignee_id).where(WfTaskAssignee.task_id == task_id,
                                                                   WfTaskAssignee.user_id == to_user_id)):
            raise WorkflowError("این همکار خودش از گیرندگان همین کار است.")
        seat.status_code = "DELEGATED"
        session.add(WfTaskAssignee(task_id=task_id, user_id=to_user_id, seq=seat.seq, status_code="ACTIVE",
                                   original_user_id=seat.original_user_id or user_id, activated_at=now()))
        session.add(WfTaskDecision(task_id=task_id, user_id=user_id, decision="DELEGATE", comment=(comment or "").strip() or None,
                                   data={"to_user_id": to_user_id}))
        task.row_version += 1
        audit(session, company_id, user_id, "Task", task_id, "DELEGATE", {"to": to_user_id, "comment": comment})
        notify.later(session, company_id, [to_user_id], "WF_DELEGATION", f"کاری به شما واگذار شد: {task.title}",
                     comment or "", "WfTask", task_id)
        session.commit()


def reassign_task(company_id: int, task_id: int, by_user_id: int, to_user_ids: list[int], note: str = "") -> None:
    """مدیر، گیرندگان کار را عوض می‌کند (مثلاً وقتی کسی پیدا نشده یا فرد مسئول در دسترس نیست)."""
    targets = [int(u) for u in dict.fromkeys(to_user_ids or []) if u]
    if not targets:
        raise WorkflowError("دست‌کم یک نفر را انتخاب کنید.")
    if not _is_manager(by_user_id, company_id):
        raise WorkflowError("فقط مدیر می‌تواند کار را دوباره ارجاع دهد.")
    with new_session() as session:
        task = _lock(session, company_id, task_id)
        _require_open(task)
        for uid in targets:
            _check_target(session, task, uid)
        session.execute(update(WfTaskAssignee).where(WfTaskAssignee.task_id == task_id,
                                                     WfTaskAssignee.status_code.in_(_LIVE)).values(status_code="CANCELLED"))
        existing = {a.user_id: a for a in session.scalars(select(WfTaskAssignee).where(WfTaskAssignee.task_id == task_id))}
        base = max((a.seq for a in existing.values()), default=0)
        for i, uid in enumerate(targets):
            state = "QUEUED" if task.mode == "SEQUENTIAL" and i > 0 else "ACTIVE"
            row = existing.get(uid)
            if row is not None:
                row.status_code, row.decision, row.decided_at, row.seq = state, None, None, base + i + 1
                row.activated_at = now() if state == "ACTIVE" else None
            else:
                session.add(WfTaskAssignee(task_id=task_id, user_id=uid, seq=base + i + 1, status_code=state,
                                           activated_at=now() if state == "ACTIVE" else None))
        session.add(WfTaskDecision(task_id=task_id, user_id=by_user_id, decision="REASSIGN", comment=(note or "").strip() or None,
                                   data={"to": targets}))
        task.row_version += 1
        session.execute(update(WfException).where(
            WfException.instance_id == task.instance_id, WfException.node_id == task.node_id,
            WfException.status_code.in_(("OPEN", "ESCALATED"))).values(
            status_code="RESOLVED", resolution_note="کار دوباره ارجاع شد", resolved_by_user_id=by_user_id, resolved_at=now()))
        audit(session, company_id, by_user_id, "Task", task_id, "UPDATE", {"reassigned_to": targets, "note": note})
        _notify_seats(session, task, targets[:1] if task.mode == "SEQUENTIAL" else targets)
        session.commit()


def add_comment(company_id: int, task_id: int, user_id: int, text: str) -> None:
    text = (text or "").strip()
    if not text:
        raise WorkflowError("متن یادداشت خالی است.")
    with new_session() as session:
        task = _lock(session, company_id, task_id)
        seats = {a.user_id: a.status_code for a in session.scalars(select(WfTaskAssignee).where(WfTaskAssignee.task_id == task_id))}
        if user_id not in seats and user_id != task.requested_by_user_id and not _is_manager(user_id, company_id):
            raise WorkflowError("فقط گیرندگان کار، درخواست‌کننده یا مدیر می‌توانند یادداشت بگذارند.")
        session.add(WfTaskDecision(task_id=task_id, user_id=user_id, decision="COMMENT", comment=text[:2000]))
        audit(session, company_id, user_id, "Task", task_id, "COMMENT", {"comment": text[:500]})
        others = {u for u, st in seats.items() if st in _LIVE} | {task.requested_by_user_id}
        notify.later(session, company_id, [u for u in others if u and u != user_id], "WF_MESSAGE",
                     f"یادداشت تازه روی «{task.title}»", text[:500], "WfTask", task_id)
        session.commit()


def withdraw_request(company_id: int, instance_id: int, user_id: int, reason: str = "") -> None:
    """درخواست‌کننده (یا مدیر) درخواست در جریان را پس می‌گیرد؛ کارهای باز لغو می‌شوند."""
    with new_session() as session:
        inst = session.get(WfInstance, instance_id)
        if inst is None or inst.company_id != company_id:
            raise WorkflowError("فرایند نامعتبر است.")
        starter = inst.started_by_user_id
    if user_id != starter and not _is_manager(user_id, company_id):
        raise WorkflowError("فقط درخواست‌کننده یا مدیر می‌تواند درخواست را پس بگیرد.")
    runtime.cancel_instance(company_id, instance_id, user_id, reason or "درخواست پس گرفته شد.")


# --- تفویض اختیار ----------------------------------------------------------------------------------------------
@dataclass
class DelegationRow:
    delegation_id: int
    from_user_id: int
    from_name: str
    to_user_id: int
    to_name: str
    starts_on: datetime.date
    ends_on: datetime.date
    scope: str
    reason: str
    is_active: bool
    is_current: bool


def create_delegation(company_id: int, by_user_id: int, from_user_id: int, to_user_id: int, starts_on: datetime.date,
                      ends_on: datetime.date, *, definition_id: int | None = None, entity_type: str | None = None,
                      reason: str = "", move_open_tasks: bool = True) -> int:
    if by_user_id != from_user_id and not _is_manager(by_user_id, company_id):
        raise WorkflowError("فقط خود کاربر یا مدیر می‌تواند تفویض اختیار ثبت کند.")
    if from_user_id == to_user_id:
        raise WorkflowError("کاربر نمی‌تواند به خودش تفویض کند.")
    if not starts_on or not ends_on or ends_on < starts_on:
        raise WorkflowError("تاریخ پایان تفویض نباید پیش از تاریخ شروع باشد.")
    with new_session() as session:
        members = set(routing.company_users(session, company_id))
        if to_user_id not in members or from_user_id not in members:
            raise WorkflowError("هر دو کاربر باید در این شرکت فعال باشند.")
        if session.scalar(select(WfDelegation.delegation_id).where(
                WfDelegation.company_id == company_id, WfDelegation.is_active.is_(True),
                WfDelegation.from_user_id == to_user_id, WfDelegation.to_user_id == from_user_id,
                WfDelegation.starts_on <= ends_on, WfDelegation.ends_on >= starts_on)):
            raise WorkflowError("تفویض دوطرفه در یک بازهٔ زمانی مجاز نیست (کار بین دو نفر دست‌به‌دست می‌شود).")
        d = WfDelegation(company_id=company_id, from_user_id=from_user_id, to_user_id=to_user_id, starts_on=starts_on,
                         ends_on=ends_on, definition_id=definition_id, entity_type=entity_type, reason=(reason or "").strip() or None,
                         created_by_user_id=by_user_id)
        session.add(d)
        session.flush()
        audit(session, company_id, by_user_id, "Delegation", d.delegation_id, "DELEGATE",
              {"from": from_user_id, "to": to_user_id, "starts_on": starts_on, "ends_on": ends_on})
        moved = []
        today = datetime.date.today()
        if move_open_tasks and starts_on <= today <= ends_on:
            q = select(WfTaskAssignee, WfTask).join(WfTask, WfTask.task_id == WfTaskAssignee.task_id).where(
                WfTask.company_id == company_id, WfTask.status_code == "OPEN", WfTaskAssignee.user_id == from_user_id,
                WfTaskAssignee.status_code.in_(_LIVE))
            for seat, task in session.execute(q):
                if definition_id and (task.options or {}).get("definition_id") != definition_id:
                    continue
                if entity_type and task.entity_type != entity_type:
                    continue
                if task.kind == "APPROVAL" and task.requested_by_user_id == to_user_id:
                    continue
                if session.scalar(select(WfTaskAssignee.assignee_id).where(WfTaskAssignee.task_id == task.task_id,
                                                                           WfTaskAssignee.user_id == to_user_id)):
                    continue
                state = seat.status_code
                seat.status_code = "DELEGATED"
                session.add(WfTaskAssignee(task_id=task.task_id, user_id=to_user_id, seq=seat.seq, status_code=state,
                                           original_user_id=seat.original_user_id or from_user_id,
                                           delegation_id=d.delegation_id, activated_at=seat.activated_at))
                session.add(WfTaskDecision(task_id=task.task_id, user_id=by_user_id, decision="DELEGATE",
                                           comment=d.reason, data={"to_user_id": to_user_id, "delegation_id": d.delegation_id}))
                task.row_version += 1
                if state == "ACTIVE":
                    moved.append(task.task_id)
        if moved:
            notify.later(session, company_id, [to_user_id], "WF_DELEGATION", "کارهایی به شما تفویض شد",
                         f"{len(moved)} کار باز به شما سپرده شد.", "WfDelegation", d.delegation_id)
        session.commit()
        return d.delegation_id


def end_delegation(company_id: int, delegation_id: int, by_user_id: int) -> None:
    with new_session() as session:
        d = session.get(WfDelegation, delegation_id)
        if d is None or d.company_id != company_id:
            raise WorkflowError("تفویض نامعتبر است.")
        if by_user_id != d.from_user_id and not _is_manager(by_user_id, company_id):
            raise WorkflowError("فقط خود کاربر یا مدیر می‌تواند تفویض را پایان دهد.")
        d.is_active = False
        audit(session, company_id, by_user_id, "Delegation", delegation_id, "UPDATE", {"is_active": False})
        session.commit()


def list_delegations(company_id: int, user_id: int | None = None, include_inactive: bool = False) -> list[DelegationRow]:
    today = datetime.date.today()
    with new_session() as session:
        q = select(WfDelegation).where(WfDelegation.company_id == company_id)
        if user_id:
            q = q.where(or_(WfDelegation.from_user_id == user_id, WfDelegation.to_user_id == user_id))
        if not include_inactive:
            q = q.where(WfDelegation.is_active.is_(True), WfDelegation.ends_on >= today)
        rows = list(session.scalars(q.order_by(WfDelegation.starts_on.desc())))
        names = user_names(session, {r.from_user_id for r in rows} | {r.to_user_id for r in rows})
        defs = {d.definition_id: d.name for d in session.scalars(select(WfDefinition).where(
            WfDefinition.definition_id.in_({r.definition_id for r in rows if r.definition_id})))} if rows else {}
        out = []
        for r in rows:
            adapter = registry.get_adapter(r.entity_type)
            scope = defs.get(r.definition_id) or (adapter.label if adapter else None) or "همهٔ کارها"
            out.append(DelegationRow(r.delegation_id, r.from_user_id, names.get(r.from_user_id, ""), r.to_user_id,
                                     names.get(r.to_user_id, ""), r.starts_on, r.ends_on, scope, r.reason or "", r.is_active,
                                     r.is_active and r.starts_on <= today <= r.ends_on))
        return out


# --- خواندن برای کارتابل و جزئیات -------------------------------------------------------------------------------
@dataclass
class TaskRow:
    task_id: int
    kind: str
    kind_label: str
    title: str
    instructions: str
    instance_id: int | None
    definition_name: str
    entity_type: str | None
    entity_label: str
    entity_id: int | None
    requested_by_user_id: int | None
    requested_by: str
    created_at: datetime.datetime
    due_at: datetime.datetime | None
    is_overdue: bool
    status_code: str
    status_label: str
    priority_code: str
    priority_label: str
    mode_label: str
    my_state: str
    on_behalf_of: str
    row_version: int
    open_nav: str | None


def _rows(session, tasks: list[WfTask], user_id: int | None = None) -> list[TaskRow]:
    if not tasks:
        return []
    ids = [t.task_id for t in tasks]
    seats = {}
    if user_id:
        for a in session.scalars(select(WfTaskAssignee).where(WfTaskAssignee.task_id.in_(ids), WfTaskAssignee.user_id == user_id)):
            if a.task_id not in seats or a.status_code == "ACTIVE":
                seats[a.task_id] = a
    inst_defs = dict(session.execute(select(WfInstance.instance_id, WfDefinition.name).join(
        WfDefinition, WfDefinition.definition_id == WfInstance.definition_id).where(
        WfInstance.instance_id.in_({t.instance_id for t in tasks if t.instance_id}))).all())
    names = user_names(session, {t.requested_by_user_id for t in tasks} | {s.original_user_id for s in seats.values()})
    t_now = now()
    out = []
    for t in tasks:
        adapter = registry.get_adapter(t.entity_type)
        seat = seats.get(t.task_id)
        out.append(TaskRow(
            t.task_id, t.kind, KINDS.get(t.kind, t.kind), t.title, t.instructions or "", t.instance_id,
            inst_defs.get(t.instance_id, ""), t.entity_type, adapter.label if adapter else "", t.entity_id,
            t.requested_by_user_id, names.get(t.requested_by_user_id, "سیستم"), t.created_at, t.due_at,
            bool(t.due_at and t.status_code == "OPEN" and t.due_at < t_now), t.status_code,
            TASK_STATUS.get(t.status_code, t.status_code), t.priority_code, PRIORITIES.get(t.priority_code, t.priority_code),
            MODES.get(t.mode, t.mode) if t.kind == "APPROVAL" else "", seat.status_code if seat else "",
            names.get(seat.original_user_id, "") if seat and seat.original_user_id else "", t.row_version,
            adapter.open_nav if adapter else None))
    return out


def list_my_tasks(company_id: int, user_id: int, *, kind: str | None = None, include_queued: bool = False) -> list[TaskRow]:
    states = ("ACTIVE", "QUEUED") if include_queued else ("ACTIVE",)
    with new_session() as session:
        q = select(WfTask).join(WfTaskAssignee, WfTaskAssignee.task_id == WfTask.task_id).where(
            WfTask.company_id == company_id, WfTask.status_code == "OPEN", WfTaskAssignee.user_id == user_id,
            WfTaskAssignee.status_code.in_(states))
        if kind:
            q = q.where(WfTask.kind == kind)
        tasks = list(dict.fromkeys(session.scalars(q.order_by(WfTask.due_at.asc().nulls_last(), WfTask.task_id))))
        return _rows(session, tasks, user_id)


def list_tasks(company_id: int, *, status: str | None = None, instance_id: int | None = None,
               entity_type: str | None = None, entity_id: int | None = None, requested_by: int | None = None,
               limit: int = 500) -> list[TaskRow]:
    with new_session() as session:
        q = select(WfTask).where(WfTask.company_id == company_id)
        if status:
            q = q.where(WfTask.status_code == status)
        if instance_id:
            q = q.where(WfTask.instance_id == instance_id)
        if entity_type:
            q = q.where(WfTask.entity_type == entity_type)
        if entity_id:
            q = q.where(WfTask.entity_id == entity_id)
        if requested_by:
            q = q.where(WfTask.requested_by_user_id == requested_by)
        return _rows(session, list(session.scalars(q.order_by(WfTask.task_id.desc()).limit(limit))))


@dataclass
class TaskDetail:
    row: TaskRow
    context: list[tuple[str, str]]
    assignees: list[tuple[str, str, str]]  # نام، وضعیت، توضیح (تفویض)
    history: list[tuple[datetime.datetime, str, str, str]]  # زمان، کاربر، تصمیم، توضیح
    decisions: list[tuple[str, str]]  # تصمیم‌های مجاز برای همین کاربر
    form_fields: list[dict]
    path: list[tuple[str, str]]


def context_rows(company_id: int, entity_type: str | None, entity_id: int | None) -> list[tuple[str, str]]:
    """اطلاعات کلیدی سند برای تصمیم سریع (بدون بازکردن فرم)."""
    adapter = registry.get_adapter(entity_type)
    if adapter is None or not entity_id:
        return []
    if adapter.approval_context is not None:
        try:
            return list(adapter.approval_context(company_id, int(entity_id)))
        except Exception:  # noqa: BLE001
            pass
    ctx = runtime.load_context(company_id, entity_type, entity_id)
    return [(f.label, display(ctx.get(f.key))) for f in adapter.fields if f.key in ctx][:12]


def task_detail(company_id: int, task_id: int, user_id: int | None = None) -> TaskDetail:
    with new_session() as session:
        task = session.get(WfTask, task_id)
        if task is None or task.company_id != company_id:
            raise WorkflowError("کار نامعتبر است.")
        row = _rows(session, [task], user_id)[0]
        seats = list(session.scalars(select(WfTaskAssignee).where(WfTaskAssignee.task_id == task_id)
                                     .order_by(WfTaskAssignee.seq, WfTaskAssignee.assignee_id)))
        decisions = list(session.scalars(select(WfTaskDecision).where(WfTaskDecision.task_id == task_id)
                                         .order_by(WfTaskDecision.decision_id)))
        names = user_names(session, {s.user_id for s in seats} | {s.original_user_id for s in seats} |
                           {d.user_id for d in decisions} | {d.on_behalf_of_user_id for d in decisions})
        assignees = [(names.get(s.user_id, ""), SEAT_STATUS.get(s.status_code, s.status_code) +
                      (f" ({DECISIONS.get(s.decision, '')})" if s.decision else ""),
                      f"به جای {names.get(s.original_user_id, '')}" if s.original_user_id else "") for s in seats]
        history = []
        for d in decisions:
            actor = names.get(d.user_id, "سیستم") + (f" (به جای {names.get(d.on_behalf_of_user_id, '')})"
                                                     if d.on_behalf_of_user_id else "")
            note = d.comment or ""
            if d.decision == "DELEGATE" and (d.data or {}).get("to_user_id"):
                note = f"به {user_names(session, [d.data['to_user_id']]).get(d.data['to_user_id'], '')}" + (f" — {note}" if note else "")
            history.append((d.created_at, actor, DECISIONS.get(d.decision, d.decision), note))
        mine = []
        if user_id and task.status_code == "OPEN" and any(s.user_id == user_id and s.status_code == "ACTIVE" for s in seats):
            mine = [(code, DECISIONS[code]) for code in allowed_decisions(task)]
        fields, instance_id = list(task.form_fields or []), task.instance_id
    path = runtime.status_path(company_id, instance_id) if instance_id else []
    return TaskDetail(row, context_rows(company_id, row.entity_type, row.entity_id), assignees, history, mine, fields, path)


def _timeline(session, inst: WfInstance) -> list:
    tasks = {t.task_id: t for t in session.scalars(select(WfTask).where(WfTask.instance_id == inst.instance_id))}
    if not tasks:
        return []
    decisions = list(session.scalars(select(WfTaskDecision).where(WfTaskDecision.task_id.in_(tasks))
                                     .order_by(WfTaskDecision.decision_id)))
    names = user_names(session, {d.user_id for d in decisions} | {d.on_behalf_of_user_id for d in decisions})
    rows = []
    for d in decisions:
        actor = names.get(d.user_id, "سیستم") + (f" (به جای {names.get(d.on_behalf_of_user_id, '')})"
                                                 if d.on_behalf_of_user_id else "")
        rows.append(runtime.TimelineRow(d.created_at, "DECISION", f"{DECISIONS.get(d.decision, d.decision)}: {tasks[d.task_id].title}",
                                        d.comment or "", actor, d.decision))
    return rows


runtime.TIMELINE_PROVIDERS.append(_timeline)
