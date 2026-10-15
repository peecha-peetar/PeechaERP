"""مدیریت «مورد نیازمند بررسی» (Exception): مالک، اولویت، علت، تلاش دوباره، حل، نادیده گرفتن، ارجاع."""

from __future__ import annotations

import copy
import datetime
from dataclasses import dataclass

from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.workflow import WfException, WfInstance, WfInstanceStep
from peecha.services.workflow import actions, notify, routing, runtime
from peecha.services.workflow.common import EXCEPTION_STATUS, PRIORITIES, WorkflowError, audit, now, user_names


@dataclass
class ExceptionRow:
    exception_id: int
    instance_id: int | None
    instance_title: str
    node_id: str | None
    title: str
    reason: str
    technical_detail: str | None
    priority_code: str
    priority_label: str
    owner: str
    owner_user_id: int | None
    status_code: str
    status_label: str
    created_at: datetime.datetime
    resolution_note: str | None


def list_exceptions(company_id: int, *, open_only: bool = True, owner_user_id: int | None = None,
                    instance_id: int | None = None) -> list[ExceptionRow]:
    with new_session() as session:
        q = select(WfException).where(WfException.company_id == company_id)
        if open_only:
            q = q.where(WfException.status_code.in_(("OPEN", "RETRYING", "ESCALATED")))
        if owner_user_id:
            q = q.where(WfException.owner_user_id == owner_user_id)
        if instance_id:
            q = q.where(WfException.instance_id == instance_id)
        rows = list(session.scalars(q.order_by(WfException.exception_id.desc())))
        names = user_names(session, {r.owner_user_id for r in rows})
        titles = {i.instance_id: i.title for i in session.scalars(select(WfInstance).where(
            WfInstance.instance_id.in_({r.instance_id for r in rows if r.instance_id})))} if rows else {}
        return [ExceptionRow(r.exception_id, r.instance_id, titles.get(r.instance_id, "") or "", r.node_id, r.title, r.reason,
                             r.technical_detail, r.priority_code, PRIORITIES.get(r.priority_code, r.priority_code),
                             names.get(r.owner_user_id, "—"), r.owner_user_id, r.status_code,
                             EXCEPTION_STATUS.get(r.status_code, r.status_code), r.created_at, r.resolution_note) for r in rows]


def _load(session, company_id: int, exception_id: int) -> WfException:
    ex = session.scalar(select(WfException).where(WfException.exception_id == exception_id).with_for_update())
    if ex is None or ex.company_id != company_id:
        raise WorkflowError("مورد نامعتبر است.")
    if ex.status_code in ("RESOLVED", "IGNORED"):
        raise WorkflowError("این مورد قبلاً بسته شده است.")
    return ex


def _token(session, ex: WfException) -> tuple[WfInstance | None, dict | None]:
    inst = session.get(WfInstance, ex.instance_id) if ex.instance_id else None
    if inst is None:
        return None, None
    token = next((t for t in inst.tokens or [] if t.get("exception_id") == ex.exception_id), None)
    return inst, (copy.deepcopy(token) if token else None)


def retry(company_id: int, exception_id: int, user_id: int | None, note: str = "") -> bool:
    """همان اقدام دوباره اجرا می‌شود (کلید یکتا ثابت است؛ اقدام انجام‌شده تکرار نمی‌شود)."""
    with new_session() as session:
        ex = _load(session, company_id, exception_id)
        inst, token = _token(session, ex)
        if token is None:
            raise WorkflowError("این مورد به مرحلهٔ فعالی از فرایند وصل نیست.")
        execution_id = ex.execution_id
        ex.status_code, ex.resolution_note, ex.resolved_by_user_id, ex.resolved_at = "RESOLVED", note or "تلاش دوباره", user_id, now()
        audit(session, company_id, user_id, "Exception", exception_id, "RETRY", {"note": note})
        session.commit()
        instance_id = inst.instance_id
    if execution_id:
        actions.reset_execution(execution_id)
    return runtime.retry_token(company_id, instance_id, token["id"])


def resolve(company_id: int, exception_id: int, user_id: int | None, note: str) -> bool:
    """کار به‌صورت دستی انجام شده و فرایند از همان مسیر عادی ادامه می‌یابد."""
    if not (note or "").strip():
        raise WorkflowError("توضیح حل مورد الزامی است.")
    with new_session() as session:
        ex = _load(session, company_id, exception_id)
        inst, token = _token(session, ex)
        instance_id = inst.instance_id if inst is not None else None
        execution_id = ex.execution_id
        ex.status_code, ex.resolution_note, ex.resolved_by_user_id, ex.resolved_at = "RESOLVED", note, user_id, now()
        audit(session, company_id, user_id, "Exception", exception_id, "RESOLVE", {"note": note})
        session.commit()
    if execution_id:
        actions.mark_done_manually(execution_id, user_id, note)
    if instance_id is None or token is None:
        return True
    return runtime.resume(company_id, instance_id, token_id=token["id"], actor_user_id=user_id,
                          detail={"manual": note}, states=("EXCEPTION",))


def ignore(company_id: int, exception_id: int, user_id: int | None, note: str) -> bool:
    """از اقدام صرف‌نظر می‌شود؛ اگر مسیر «در صورت شکست» تعریف شده باشد همان، وگرنه مسیر عادی."""
    if not (note or "").strip():
        raise WorkflowError("علت نادیده گرفتن الزامی است.")
    with new_session() as session:
        ex = _load(session, company_id, exception_id)
        inst, token = _token(session, ex)
        instance_id, version_id = (inst.instance_id, inst.version_id) if inst is not None else (None, None)
        ex.status_code, ex.resolution_note, ex.resolved_by_user_id, ex.resolved_at = "IGNORED", note, user_id, now()
        audit(session, company_id, user_id, "Exception", exception_id, "RESOLVE", {"ignored": True, "note": note})
        session.commit()
    if instance_id is None or token is None:
        return True
    from peecha.services.workflow import definitions

    with new_session() as session:
        graph = runtime._graph(session, version_id)
    has_failed = any(e.get("when") == "failed" for e in definitions.outgoing(graph, token["node"]))
    return runtime.resume(company_id, instance_id, token_id=token["id"], when="failed" if has_failed else None,
                          actor_user_id=user_id, detail={"ignored": note}, states=("EXCEPTION",))


def escalate(company_id: int, exception_id: int, user_id: int | None, note: str = "", to_user_id: int | None = None) -> None:
    with new_session() as session:
        ex = _load(session, company_id, exception_id)
        ex.status_code, ex.priority_code = "ESCALATED", "CRITICAL"
        if to_user_id:
            ex.owner_user_id = to_user_id
        ex.resolution_note = note or None
        audit(session, company_id, user_id, "Exception", exception_id, "ESCALATE", {"to": to_user_id, "note": note})
        title = f"ارجاع فوری: {ex.title}"
        reason = ex.reason
        session.commit()
    targets = [to_user_id] if to_user_id else routing.resolve(company_id, [{"kind": "MANAGERS"}])
    notify.send(company_id, targets, "WF_ESCALATION", title, reason, "WfException", exception_id)


def failed_step_detail(company_id: int, exception_id: int) -> WfInstanceStep | None:
    with new_session() as session:
        ex = session.get(WfException, exception_id)
        if ex is None or ex.company_id != company_id or not ex.instance_id:
            return None
        step = session.scalar(select(WfInstanceStep).where(WfInstanceStep.instance_id == ex.instance_id,
                                                           WfInstanceStep.node_id == ex.node_id)
                              .order_by(WfInstanceStep.step_id.desc()))
        if step is not None:
            session.expunge(step)
        return step
