"""اجرای اقدام‌ها با دفتر یکتا (Idempotency)، تلاش دوباره (Retry) و تبدیل شکست به «مورد نیازمند بررسی».

اقدام سند (entity.*) همیشه تابع سرویس موجود پیچاست؛ اقدام‌های عمومی اینجا ثبت می‌شوند و توسعه‌دهنده با
registry.register_action اقدام تازه اضافه می‌کند (بدون Hard-code در هسته).
"""

from __future__ import annotations

import datetime
import json
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from peecha.db.base import new_session
from peecha.db.models.workflow import WfActionExecution
from peecha.services.workflow import registry
from peecha.services.workflow.common import (
    WorkflowError, audit, friendly_error, is_transient, now, plain, render, settings,
)
from peecha.services.workflow.registry import ActionContext, ActionSpec, ParamSpec


@dataclass
class ActionOutcome:
    status: str  # DONE | RETRY | FAILED
    result: dict = field(default_factory=dict)
    error: str | None = None
    technical: str | None = None
    retry_at: datetime.datetime | None = None
    attempts: int = 0
    execution_id: int | None = None


def _ledger(company_id: int, key: str, instance_id: int | None, node_id: str | None, action_code: str) -> tuple[int, str, dict, int]:
    """(execution_id, status, result, attempts) -- ردیف یکتا برای همین اجرای گره."""
    for _ in range(2):
        with new_session() as session:
            ex = session.scalar(select(WfActionExecution).where(WfActionExecution.company_id == company_id,
                                                                WfActionExecution.idempotency_key == key).with_for_update())
            if ex is None:
                ex = WfActionExecution(company_id=company_id, idempotency_key=key, instance_id=instance_id, node_id=node_id,
                                       action_code=action_code, status_code="PENDING", attempts=0, result={})
                session.add(ex)
                try:
                    session.flush()
                except IntegrityError:
                    session.rollback()
                    continue
            if ex.status_code != "DONE":
                ex.attempts += 1
                ex.updated_at = now()
            session.commit()
            return ex.execution_id, ex.status_code, dict(ex.result or {}), ex.attempts
    raise WorkflowError("ثبت اجرای اقدام ممکن نشد.")


def _finish(execution_id: int, status: str, *, result: dict | None = None, error: str | None = None,
            retry_at: datetime.datetime | None = None, company_id: int | None = None, user_id: int | None = None) -> None:
    with new_session() as session:
        ex = session.get(WfActionExecution, execution_id)
        ex.status_code, ex.updated_at, ex.next_retry_at = status, now(), retry_at
        if result is not None:
            ex.result = plain(result)
        ex.last_error = error
        if status == "DONE" and company_id:
            audit(session, company_id, user_id, "Action", execution_id, "EXECUTE",
                  {"action": ex.action_code, "instance_id": ex.instance_id, "node": ex.node_id})
        session.commit()


def execute(company_id: int, *, instance_id: int | None, node: dict, visit: int, entity_type: str | None,
            entity_id: int | None, context: dict, run_as: int | None) -> ActionOutcome:
    code = node.get("action") or ""
    spec = registry.find_action(entity_type, code)
    if spec is None:
        return ActionOutcome("FAILED", error=f"اقدام «{code}» شناخته نشده است.", technical=f"unknown action {code}")
    key = f"wf:{instance_id}:{node.get('id')}:{visit}"
    execution_id, status, result, attempts = _ledger(company_id, key, instance_id, node.get("id"), code)
    if status == "DONE":
        return ActionOutcome("DONE", result, attempts=attempts, execution_id=execution_id)
    if spec.is_done is not None and entity_id:
        try:
            if spec.is_done(company_id, int(entity_id)):
                _finish(execution_id, "DONE", result={"already_done": True}, company_id=company_id, user_id=run_as)
                return ActionOutcome("DONE", {"already_done": True}, attempts=attempts, execution_id=execution_id)
        except Exception:  # noqa: BLE001 -- بررسی حالت فقط بهینه‌سازی است؛ اجرای اصلی تصمیم نهایی را می‌گیرد
            pass
    ctx = ActionContext(company_id=company_id, user_id=run_as, entity_type=entity_type, entity_id=entity_id,
                        instance_id=instance_id, context=context, params=dict(node.get("params") or {}),
                        idempotency_key=key)
    try:
        result = spec.func(ctx) or {}
    except Exception as exc:  # noqa: BLE001
        friendly, technical = friendly_error(exc)
        retry = node.get("retry") or {}
        max_attempts = max(1, int(retry.get("max", 3)))
        if is_transient(exc) and attempts < max_attempts:
            backoff = max(1, int(retry.get("backoff_minutes", 1))) * (2 ** (attempts - 1))
            retry_at = now() + datetime.timedelta(minutes=backoff)
            _finish(execution_id, "PENDING", error=technical, retry_at=retry_at)
            return ActionOutcome("RETRY", error=friendly, technical=technical, retry_at=retry_at, attempts=attempts,
                                 execution_id=execution_id)
        _finish(execution_id, "FAILED", error=technical)
        return ActionOutcome("FAILED", error=friendly, technical=technical, attempts=attempts, execution_id=execution_id)
    _finish(execution_id, "DONE", result=result, company_id=company_id, user_id=run_as)
    return ActionOutcome("DONE", result if isinstance(result, dict) else {"result": result}, attempts=attempts,
                         execution_id=execution_id)


def reset_execution(execution_id: int) -> None:
    """برای «تلاش دوباره» دستی: اجرای ناموفق دوباره قابل اجرا می‌شود (کلید یکتا همان می‌ماند)."""
    with new_session() as session:
        ex = session.get(WfActionExecution, execution_id)
        if ex is not None and ex.status_code != "DONE":
            ex.status_code, ex.attempts, ex.next_retry_at, ex.updated_at = "PENDING", 0, None, now()
        session.commit()


def mark_done_manually(execution_id: int, user_id: int | None, note: str) -> None:
    with new_session() as session:
        ex = session.get(WfActionExecution, execution_id)
        if ex is not None:
            ex.status_code, ex.updated_at = "DONE", now()
            ex.result = {**(ex.result or {}), "manual": True, "note": note, "by": user_id}
        session.commit()


# --- اقدام‌های عمومی داخلی ------------------------------------------------------------------------------
def _emit_event(ctx: ActionContext) -> dict:
    from peecha.services.workflow import events

    event_type = (ctx.params.get("event") or "").strip()
    if not event_type:
        raise WorkflowError("نام رویداد برای انتشار مشخص نشده است.")
    with new_session() as session:
        from peecha.db.models.workflow import WfInstance

        depth = (session.get(WfInstance, ctx.instance_id).depth if ctx.instance_id else 0) + 1
        event_id = events.publish(session, ctx.company_id, event_type, ctx.entity_type, ctx.entity_id,
                                  {"source_instance_id": ctx.instance_id}, actor_user_id=ctx.user_id,
                                  causation_instance_id=ctx.instance_id, depth=depth,
                                  dedupe_key=f"chain:{ctx.idempotency_key}")
        session.commit()
    return {"event_id": event_id}


def _set_variable(ctx: ActionContext) -> dict:
    key = (ctx.params.get("key") or "").strip()
    if not key:
        raise WorkflowError("نام متغیر مشخص نشده است.")
    return {"variables": {key: ctx.params.get("value")}}


def _add_comment(ctx: ActionContext) -> dict:
    text = render(ctx.params.get("text") or "", ctx.context)
    if not text.strip():
        raise WorkflowError("متن یادداشت خالی است.")
    return {"comment": text}


def _create_followup(ctx: ActionContext) -> dict:
    """پیگیری/وظیفه در همان فعالیت‌های CRM (comm.customer_activities) -- بدون جدول کار تازه."""
    from peecha.services.crm import activities as act_service

    customer = ctx.context.get(ctx.params.get("customer_field") or "customer_id")
    due = datetime.date.today() + datetime.timedelta(days=int(ctx.params.get("due_in_days") or 0))
    assignee = ctx.params.get("assign_to")
    if assignee in (None, "", "STARTER"):
        assignee = ctx.user_id
    activity_id = act_service.create_activity(ctx.company_id, ctx.user_id, act_service.ActivityFields(
        ctx.params.get("activity_type") or "FOLLOW_UP", render(ctx.params.get("subject") or "پیگیری", ctx.context)[:200],
        customer_detail_account_id=int(customer) if customer else None, due_date=due,
        priority_code=ctx.params.get("priority") or "NORMAL", assigned_to_user_id=int(assignee) if assignee else None,
        description=render(ctx.params.get("description") or "", ctx.context) or None))
    return {"activity_id": activity_id}


def _call_api(ctx: ActionContext) -> dict:
    """فراخوانی سرویس بیرونی فقط برای نشانی‌های مجاز تنظیمات (بدون فهرست مجاز، اجرا نمی‌شود)."""
    url = (ctx.params.get("url") or "").strip()
    allow = settings(ctx.company_id).get("api_allowlist") or []
    host = urllib.parse.urlparse(url).hostname or ""
    if not url or host not in allow:
        raise WorkflowError("این نشانی در فهرست سرویس‌های مجاز گردش کار نیست (تنظیمات گردش کار).")
    body = json.dumps({"entity_type": ctx.entity_type, "entity_id": ctx.entity_id, "instance_id": ctx.instance_id,
                       "context": plain(ctx.context)}, ensure_ascii=False).encode()
    req = urllib.request.Request(url, data=body, method="POST", headers={"Content-Type": "application/json",
                                                                          "Idempotency-Key": ctx.idempotency_key})
    with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310 -- فقط میزبان‌های فهرست مجاز
        return {"status": resp.status}


registry.register_action(ActionSpec("emit_event", "انتشار رویداد برای فرایند دیگر", _emit_event,
                                    params=(ParamSpec("event", "نام رویداد"),)))
registry.register_action(ActionSpec("set_variable", "ثبت مقدار در فرایند", _set_variable,
                                    params=(ParamSpec("key", "نام"), ParamSpec("value", "مقدار"))))
registry.register_action(ActionSpec("add_comment", "افزودن یادداشت", _add_comment, params=(ParamSpec("text", "متن"),)))
registry.register_action(ActionSpec(
    "create_followup", "ثبت پیگیری یا وظیفه", _create_followup,
    params=(ParamSpec("subject", "موضوع", default="پیگیری"), ParamSpec("activity_type", "نوع", "choice", "FOLLOW_UP"),
            ParamSpec("due_in_days", "موعد (روز بعد)", "int", 0), ParamSpec("assign_to", "مسئول", "user", "STARTER"),
            ParamSpec("priority", "اولویت", "choice", "NORMAL"))))
registry.register_action(ActionSpec("call_api", "فراخوانی سرویس بیرونی مجاز", _call_api, params=(ParamSpec("url", "نشانی"),)))
