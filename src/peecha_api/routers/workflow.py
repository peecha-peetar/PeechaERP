"""گردش کار موبایل (R297): کارتابل یکپارچه، جزئیات کار، تصمیم، یادداشت و سپردن به همکار.

نازک است و فقط همان سرویس‌های دسکتاپ را صدا می‌زند. تصمیم‌ها با Idempotency-Key تکرارناپذیرند (صف آفلاین)،
هر نوشتن در سابقه ثبت می‌شود و کار حساس تا رمز کاربر دوباره وارد نشود تایید نمی‌شود.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.security import User, UserCompany
from peecha.db.models.workflow import WfTask, WfTaskAssignee
from peecha.services import auth as auth_service, roles as roles_service
from peecha.services.workflow import inbox, registry, step_up, tasks
from peecha_api import audit_log
from peecha_api.deps import AuthContext, get_current_context, get_idempotency_key
from peecha_api.idempotency import IdempotentReplay, run_idempotent

router = APIRouter(prefix="/workflow", tags=["workflow"])
_AUDIT = {"APPROVE": "APPROVE", "REJECT": "REJECT", "CHANGES": "UPDATE", "DONE": "COMPLETE"}  # کدهای مجاز سابقه
registry.ensure_loaded()


class DecideRequest(BaseModel):
    decision: str
    comment: str = ""
    data: dict | None = None
    row_version: int | None = None
    password: str | None = Field(default=None, description="فقط برای کار حساس")


class CommentRequest(BaseModel):
    text: str


class DelegateRequest(BaseModel):
    to_user_id: int
    comment: str = ""


def _iso(value):
    return value.isoformat() if value else None


def _item(w: inbox.WorkItem) -> dict:
    return {"key": w.key, "source": w.source, "source_label": w.source_label, "kind": w.kind, "kind_label": w.kind_label,
            "ref_id": w.ref_id, "title": w.title, "subtitle": w.subtitle, "due_at": _iso(w.due_at), "is_overdue": w.is_overdue,
            "priority_code": w.priority_code, "priority_label": w.priority_label, "created_at": _iso(w.created_at),
            "can_decide": w.source == "WF", "status_note": w.status_note,
            "definition": w.extra.get("definition") if w.source == "WF" else None}


def _involved(ctx: AuthContext, task_id: int) -> bool:
    """فقط گیرندگان، درخواست‌کننده و مدیران جزئیات کار را می‌بینند."""
    with new_session() as session:
        task = session.get(WfTask, task_id)
        if task is None or task.company_id != ctx.company_id:
            return False
        if task.requested_by_user_id == ctx.user_id:
            return True
        seat = session.scalar(select(WfTaskAssignee.assignee_id).where(
            WfTaskAssignee.task_id == task_id,
            (WfTaskAssignee.user_id == ctx.user_id) | (WfTaskAssignee.original_user_id == ctx.user_id)).limit(1))
    return seat is not None or roles_service.is_manager(ctx.user_id, ctx.company_id)


def _guard(ctx: AuthContext, task_id: int) -> None:
    if not _involved(ctx, task_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="این کار پیدا نشد یا به شما مربوط نیست.")


def _idem(key, endpoint, ctx, compute, serialize):
    try:
        return run_idempotent(key, endpoint, ctx.user_id, ctx.company_id, status.HTTP_200_OK, compute, serialize)
    except IdempotentReplay as replay:
        return replay.body
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/inbox")
def my_inbox(source: str | None = None, ctx: AuthContext = Depends(get_current_context)) -> dict:
    items = inbox.my_work(ctx.company_id, ctx.user_id, sources=(source,) if source else None)
    return {"items": [_item(w) for w in items], "count": len(items), "overdue": sum(1 for w in items if w.is_overdue)}


@router.get("/tasks/{task_id}")
def task_detail(task_id: int, ctx: AuthContext = Depends(get_current_context)) -> dict:
    _guard(ctx, task_id)
    try:
        d = tasks.task_detail(ctx.company_id, task_id, ctx.user_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    r = d.row
    return {"task_id": r.task_id, "title": r.title, "kind": r.kind, "kind_label": r.kind_label, "instructions": r.instructions,
            "definition": r.definition_name, "entity_label": r.entity_label, "requested_by": r.requested_by,
            "created_at": _iso(r.created_at), "due_at": _iso(r.due_at), "is_overdue": r.is_overdue, "status_code": r.status_code,
            "status_label": r.status_label, "priority_label": r.priority_label, "sla_label": r.sla_label,
            "row_version": r.row_version, "context": [{"label": k, "value": v} for k, v in d.context],
            "history": [{"at": _iso(at), "user": who, "decision": what, "note": note} for at, who, what, note in d.history],
            "assignees": [{"name": n, "state": s, "note": x} for n, s, x in d.assignees],
            "decisions": [{"code": c, "label": label} for c, label in d.decisions], "form_fields": d.form_fields,
            "path": [{"label": label, "state": state} for label, state in d.path],
            "requires_step_up": step_up.requires_step_up(ctx.company_id, task_id)}


@router.post("/tasks/{task_id}/decide")
def decide(task_id: int, payload: DecideRequest, ctx: AuthContext = Depends(get_current_context),
           idempotency_key: str | None = Depends(get_idempotency_key)) -> dict:
    _guard(ctx, task_id)
    if payload.decision.upper() in ("APPROVE", "DONE") and step_up.requires_step_up(ctx.company_id, task_id):
        with new_session() as session:
            user = session.get(User, ctx.user_id)
            ok = user is not None and bool(payload.password) and auth_service.verify_password(
                payload.password, bytes(user.password_hash), bytes(user.password_salt))
        if not ok:
            audit_log.record(ctx.company_id, ctx.user_id, "WfTask", task_id, "UPDATE", {"source": "mobile", "step_up": "failed"})
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="این مورد حساس است؛ برای تایید، رمز خود را درست وارد کنید.")

    def compute():
        result = tasks.decide(ctx.company_id, task_id, ctx.user_id, payload.decision, payload.comment, data=payload.data,
                              row_version=payload.row_version, client_ref=idempotency_key, channel="MOBILE")
        audit_log.record(ctx.company_id, ctx.user_id, "WfTask", task_id, _AUDIT.get(payload.decision.upper(), "UPDATE"),
                         {"source": "mobile", "decision": payload.decision.upper()})
        return result

    return _idem(idempotency_key, f"POST /workflow/tasks/{task_id}/decide", ctx, compute,
                 lambda r: {"task_id": r.task_id, "status": r.status_code, "closed": r.closed, "message": r.message})


@router.post("/tasks/{task_id}/comment")
def comment(task_id: int, payload: CommentRequest, ctx: AuthContext = Depends(get_current_context),
            idempotency_key: str | None = Depends(get_idempotency_key)) -> dict:
    _guard(ctx, task_id)
    return _idem(idempotency_key, f"POST /workflow/tasks/{task_id}/comment", ctx,
                 lambda: tasks.add_comment(ctx.company_id, task_id, ctx.user_id, payload.text), lambda _r: {"task_id": task_id})


@router.post("/tasks/{task_id}/delegate")
def delegate(task_id: int, payload: DelegateRequest, ctx: AuthContext = Depends(get_current_context),
             idempotency_key: str | None = Depends(get_idempotency_key)) -> dict:
    _guard(ctx, task_id)

    def compute():
        tasks.delegate_task(ctx.company_id, task_id, ctx.user_id, payload.to_user_id, payload.comment)
        audit_log.record(ctx.company_id, ctx.user_id, "WfTask", task_id, "DELEGATE",
                         {"source": "mobile", "to_user_id": payload.to_user_id})

    return _idem(idempotency_key, f"POST /workflow/tasks/{task_id}/delegate", ctx, compute, lambda _r: {"task_id": task_id})


@router.get("/colleagues")
def colleagues(ctx: AuthContext = Depends(get_current_context)) -> list[dict]:
    """همکاران فعال همین شرکت برای سپردن کار."""
    with new_session() as session:
        rows = session.execute(select(User.user_id, User.full_name, User.username).join(
            UserCompany, UserCompany.user_id == User.user_id).where(
            UserCompany.company_id == ctx.company_id, User.is_active.is_(True), User.user_id != ctx.user_id)
            .order_by(User.full_name)).all()
    return [{"user_id": u, "name": name or username} for u, name, username in rows]
