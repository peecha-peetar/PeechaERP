"""اجرای ماندگار نمونه‌های فرایند (Restart-safe).

هر گره در تراکنش جداگانه و با قفل ردیف نمونه اجرا می‌شود و پس از commit پیش می‌رود؛ هیچ حالتی فقط در
حافظه نیست. «نشانه»ها (tokens) جایگاه اجرای هر شاخه را نگه می‌دارند (برای شاخه‌های هم‌زمان). اقدام خودکار
دومرحله‌ای اجرا می‌شود: ثبت «در حال اجرا» ← اجرای سرویس بیرون از قفل ← ثبت نتیجه؛ با دفتر یکتای اقدام، اجرای
دوباره پس از قطعی هم سند تکراری نمی‌سازد.
"""

from __future__ import annotations

import copy
import datetime
from dataclasses import dataclass, field
from typing import Callable

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.attributes import flag_modified

from peecha.db.base import new_session
from peecha.db.models.workflow import (
    WfDefinition, WfDefinitionVersion, WfException, WfInstance, WfInstanceStep, WfTimer,
)
from peecha.services.workflow import actions, conditions, definitions, events, notify, registry, routing
from peecha.services.workflow.common import (
    INSTANCE_STATUS, NODE_TYPES, OUTCOMES, WorkflowError, audit, friendly_error, now, plain, render, settings,
    user_names,
)

START = definitions.START
MAX_VISITS_PER_NODE = 50
STUCK_MINUTES = 10


@dataclass
class NodeResult:
    kind: str  # NEXT | WAIT | END | FAIL | CONSUME
    when: str | None = None
    detail: dict = field(default_factory=dict)
    error: str | None = None
    technical: str | None = None
    outcome: str | None = None
    actor_user_id: int | None = None
    token_patch: dict = field(default_factory=dict)


@dataclass
class Run:
    session: object
    instance: WfInstance
    graph: dict
    node: dict
    token: dict
    adapter: registry.EntityAdapter | None
    variables: dict

    @property
    def company_id(self) -> int:
        return self.instance.company_id

    @property
    def context(self) -> dict:
        return self.instance.context or {}

    def labels(self) -> dict[str, str]:
        return self.adapter.labels() if self.adapter else {}

    def refresh_context(self) -> dict:
        inst = self.instance
        if inst.entity_type and inst.entity_id and self.adapter:
            fresh = load_context(inst.company_id, inst.entity_type, inst.entity_id)
            if "event" in (inst.context or {}):
                fresh["event"] = inst.context["event"]
            inst.context = fresh
        return self.context


NODE_HANDLERS: dict[str, Callable[[Run], NodeResult]] = {}
CLOSE_HOOKS: list[Callable] = []  # (session, instance, status) -- مثلاً لغو کارهای باز (R292)
TIMELINE_PROVIDERS: list[Callable] = []  # (session, instance) -> [TimelineRow]
LEAVE_HOOKS: list[Callable] = []  # (session, instance, token, when) -- نشانهٔ منتظر از هر راهی ادامه یافت


def register_node(node_type: str, handler: Callable[[Run], NodeResult]) -> None:
    NODE_HANDLERS[node_type] = handler


def on_close(hook: Callable) -> None:
    CLOSE_HOOKS.append(hook)


def on_leave(hook: Callable) -> None:
    LEAVE_HOOKS.append(hook)


def load_context(company_id: int, entity_type: str | None, entity_id: int | None) -> dict:
    adapter = registry.get_adapter(entity_type)
    if adapter is None or not entity_id:
        return {}
    ctx = plain(adapter.load(company_id, int(entity_id)) or {})
    ctx.setdefault("entity_type", entity_type)
    ctx.setdefault("entity_id", entity_id)
    return ctx


# --- کمک‌های داخلی -----------------------------------------------------------------------------------------
_GRAPH_CACHE: dict[int, dict] = {}


def _graph(session, version_id: int) -> dict:
    if version_id not in _GRAPH_CACHE:  # نسخهٔ منتشرشده تغییرناپذیر است
        _GRAPH_CACHE[version_id] = copy.deepcopy(session.get(WfDefinitionVersion, version_id).graph or {})
    return _GRAPH_CACHE[version_id]


def _save(inst: WfInstance, tokens: list | None = None, variables: dict | None = None) -> None:
    if tokens is not None:
        inst.tokens = copy.deepcopy(tokens)
        flag_modified(inst, "tokens")
    if variables is not None:
        inst.variables = copy.deepcopy(variables)
        flag_modified(inst, "variables")


def _node(graph: dict, node_id: str) -> dict | None:
    if node_id == START:
        return {"id": START, "type": "START", "label": "شروع فرایند"}
    return definitions.nodes_by_id(graph).get(node_id)


def _next_edges(graph: dict, node: dict, when: str | None) -> list[dict]:
    outs = definitions.outgoing(graph, node["id"])
    if node.get("type") == "PARALLEL":
        return outs
    if when is not None:
        matched = [e for e in outs if e.get("when") == when]
        if matched:
            return matched[:1]
    return [e for e in outs if e.get("when") in (None, "", "default")][:1]


def _open_step(session, inst: WfInstance, node: dict, status: str, *, outcome=None, detail=None, error=None,
               attempt: int = 1, actor=None, closed: bool = False) -> WfInstanceStep:
    step = WfInstanceStep(instance_id=inst.instance_id, node_id=node["id"], node_type=node.get("type", "START"),
                          label=(node.get("label") or NODE_TYPES.get(node.get("type"), ""))[:200], status_code=status,
                          outcome=outcome, detail=plain(detail or {}), error=error, attempt=attempt, actor_user_id=actor,
                          started_at=now())
    if closed:
        step.ended_at, step.duration_ms = step.started_at, 0
    session.add(step)
    session.flush()
    return step


def _close_step(step: WfInstanceStep | None, status: str, *, outcome=None, detail=None, error=None, actor=None) -> None:
    if step is None:
        return
    t = now()
    step.status_code, step.ended_at = status, t
    step.duration_ms = int((t - step.started_at).total_seconds() * 1000) if step.started_at else 0
    if outcome is not None:
        step.outcome = outcome
    if detail:
        step.detail = plain({**(step.detail or {}), **detail})
        flag_modified(step, "detail")
    if error is not None:
        step.error = error
    if actor is not None:
        step.actor_user_id = actor


def _advance(session, inst: WfInstance, graph: dict, node: dict, tokens: list, variables: dict, when: str | None) -> str | None:
    """نشانه‌های تازه برای مرحله(های) بعد؛ خطا اگر مسیر تعریف نشده باشد."""
    edges = _next_edges(graph, node, when)
    if not edges:
        label = definitions.EDGE_LABELS.get(when, when)
        return f"برای نتیجهٔ «{label}» در مرحلهٔ «{node.get('label') or NODE_TYPES.get(node.get('type'))}» مسیر بعدی تعریف نشده است."
    visits = variables.setdefault("visits", {})
    for e in edges:
        variables["seq"] = int(variables.get("seq", 1)) + 1
        tokens.append({"id": f"t{variables['seq']}", "node": e["to"], "state": "READY",
                       "visit": int(visits.get(e["to"], 0)) + 1, "via": when})
    return None


_END_PHRASE = {"APPROVED": "تایید شد", "REJECTED": "رد شد", "DONE": "به پایان رسید", "CANCELLED": "لغو شد"}


def _close_instance(session, inst: WfInstance, status: str, *, outcome: str | None = None, error: str | None = None,
                    actor: int | None = None) -> None:
    inst.status_code, inst.outcome_code, inst.ended_at = status, outcome, now()
    if error:
        inst.last_error = error
    _save(inst, tokens=[])
    session.execute(update(WfTimer).where(WfTimer.instance_id == inst.instance_id, WfTimer.status_code == "PENDING")
                    .values(status_code="CANCELLED"))
    for hook in CLOSE_HOOKS:
        hook(session, inst, status)
    action = {"COMPLETED": "COMPLETE", "CANCELLED": "CANCEL"}.get(status, "UPDATE")
    audit(session, inst.company_id, actor, "Instance", inst.instance_id, action,
          {"status": status, "outcome": outcome, "error": error})


def _owner_ids(session, inst: WfInstance) -> list[int]:
    d = session.get(WfDefinition, inst.definition_id)
    return [u for u in {inst.started_by_user_id, d.created_by_user_id if d else None} if u]


def _raise_exception(session, inst: WfInstance, node: dict, title: str, reason: str, technical: str | None,
                     execution_id: int | None = None) -> WfException:
    owners = _owner_ids(session, inst)
    ex = WfException(company_id=inst.company_id, instance_id=inst.instance_id, node_id=node.get("id"),
                     execution_id=execution_id, title=title[:300], reason=reason, technical_detail=technical,
                     priority_code="HIGH", owner_user_id=owners[0] if owners else None)
    session.add(ex)
    session.flush()
    notify.send(inst.company_id, owners, "WF_EXCEPTION", title, reason, "WfException", ex.exception_id)
    return ex


def _apply(session, inst: WfInstance, graph: dict, node: dict, token: dict, tokens: list, variables: dict,
           result: NodeResult, step: WfInstanceStep | None = None) -> None:
    tokens[:] = [t for t in tokens if t.get("id") != token.get("id")]
    status = {"NEXT": "DONE", "END": "DONE", "CONSUME": "DONE", "WAIT": "WAITING", "FAIL": "FAILED"}[result.kind]
    outcome = result.when or result.outcome
    if step is None:
        step = _open_step(session, inst, node, status, outcome=outcome, detail=result.detail, error=result.error,
                          attempt=int(token.get("visit", 1)), actor=result.actor_user_id, closed=status != "WAITING")
    else:
        _close_step(step, status, outcome=outcome, detail=result.detail, error=result.error, actor=result.actor_user_id) \
            if status != "WAITING" else None
    if result.actor_user_id:
        variables["last_actor"] = result.actor_user_id
    if result.kind == "NEXT":
        problem = _advance(session, inst, graph, node, tokens, variables, result.when)
        if problem:
            _close_step(step, "FAILED", error=problem)
            _fail(session, inst, node, problem, None, tokens, variables)
            return
    elif result.kind == "WAIT":
        waiting = {**token, **result.token_patch, "state": result.token_patch.get("state", "WAITING"),
                   "since": now().isoformat(), "step_id": step.step_id}
        tokens.append(waiting)
    elif result.kind == "END":
        _save(inst, variables=variables)
        _close_instance(session, inst, "COMPLETED", outcome=result.outcome or "DONE", actor=result.actor_user_id)
        if settings(inst.company_id).get("notify_starter_on_end", True) and inst.started_by_user_id:
            d = session.get(WfDefinition, inst.definition_id)
            notify.send(inst.company_id, [inst.started_by_user_id], "WF_COMPLETED",
                        f"«{inst.title or d.name}» {_END_PHRASE.get(result.outcome or 'DONE', 'به پایان رسید')}",
                        f"فرایند «{d.name}» پایان یافت.", "WfInstance", inst.instance_id)
        return
    elif result.kind == "FAIL":
        _fail(session, inst, node, result.error or "اجرای مرحله ناموفق بود.", result.technical, tokens, variables)
        return
    inst.status_code = "RUNNING" if any(t.get("state") == "READY" for t in tokens) else "WAITING"
    _save(inst, tokens=tokens, variables=variables)


def _fail(session, inst: WfInstance, node: dict, message: str, technical: str | None, tokens: list, variables: dict) -> None:
    _save(inst, tokens=tokens, variables=variables)
    title = f"فرایند «{inst.title or ''}» در مرحلهٔ «{node.get('label') or NODE_TYPES.get(node.get('type'), '')}» متوقف شد"
    _raise_exception(session, inst, node, title, message, technical)
    _close_instance(session, inst, "FAILED", error=message)


# --- شروع و اجرا -------------------------------------------------------------------------------------------
def start_instance(company_id: int, definition_id: int, entity_type: str | None = None, entity_id: int | None = None, *,
                   started_by: int | None = None, context: dict | None = None, correlation_key: str | None = None,
                   trigger_event_id: int | None = None, depth: int = 0, title: str | None = None,
                   run: bool = True) -> int | None:
    """None یعنی همین رویداد قبلاً این فرایند را شروع کرده بود (اجرای تکراری نمی‌سازد)."""
    with new_session() as session:
        d = session.get(WfDefinition, definition_id)
        if d is None or d.company_id != company_id:
            raise WorkflowError("فرایند نامعتبر است.")
        v = definitions.runnable_version(session, definition_id)
        if v is None:
            raise WorkflowError(f"فرایند «{d.name}» فعال نیست (فقط فرایند منتشرشده یا فعال اجرا می‌شود).")
        entity_type = entity_type or d.entity_type
        if context is None:
            context = load_context(company_id, entity_type, entity_id)
        adapter = registry.get_adapter(entity_type)
        if title is None:
            title = adapter.describe(context) if adapter and context else d.name
        if correlation_key and session.scalar(select(WfInstance.instance_id).where(
                WfInstance.company_id == company_id, WfInstance.correlation_key == correlation_key)):
            return None
        inst = WfInstance(company_id=company_id, definition_id=definition_id, version_id=v.version_id,
                          entity_type=entity_type, entity_id=entity_id, title=(title or d.name)[:300], status_code="RUNNING",
                          tokens=[{"id": "t1", "node": START, "state": "READY", "visit": 1}], context=plain(context),
                          variables={"visits": {}, "seq": 1}, correlation_key=correlation_key,
                          trigger_event_id=trigger_event_id, started_by_user_id=started_by, depth=depth)
        session.add(inst)
        try:
            session.flush()
        except IntegrityError:
            session.rollback()
            return None
        audit(session, company_id, started_by, "Instance", inst.instance_id, "START",
              {"definition": d.code, "version": v.version_no, "entity_type": entity_type, "entity_id": entity_id})
        session.commit()
        instance_id = inst.instance_id
    if run:
        run_instance(instance_id)
    return instance_id


def run_instance(instance_id: int, max_iterations: int = 500) -> None:
    with events.engine_busy():
        for _ in range(max_iterations):
            pending = _step_once(instance_id)
            if pending is None:
                return
            if pending == "CONTINUE":
                continue
            outcome = actions.execute(pending["company_id"], instance_id=instance_id, node=pending["node"],
                                      visit=pending["visit"], entity_type=pending["entity_type"],
                                      entity_id=pending["entity_id"], context=pending["context"], run_as=pending["run_as"])
            _complete_action(instance_id, pending["token_id"], outcome)


def _step_once(instance_id: int):
    """یک گره را اجرا می‌کند. None = کاری نمانده؛ CONTINUE = ادامه؛ dict = اقدامی که باید بیرون از قفل اجرا شود."""
    with new_session() as session:
        inst = session.scalar(select(WfInstance).where(WfInstance.instance_id == instance_id).with_for_update())
        if inst is None or inst.status_code not in ("RUNNING", "WAITING"):
            return None
        tokens = copy.deepcopy(inst.tokens or [])
        variables = copy.deepcopy(inst.variables or {})
        token = next((t for t in tokens if t.get("state") == "READY"), None)
        if token is None:
            status = "WAITING" if tokens else inst.status_code
            if inst.status_code != status:
                inst.status_code = status
                session.commit()
            return None
        graph = _graph(session, inst.version_id)
        node = _node(graph, token["node"])
        inst.status_code = "RUNNING"
        inst.step_count += 1
        max_steps = int((graph.get("settings") or {}).get("max_steps") or settings(inst.company_id).get("max_steps") or 200)
        visits = variables.setdefault("visits", {})
        visits[token["node"]] = int(visits.get(token["node"], 0)) + 1
        if node is None:
            _fail(session, inst, {"id": token["node"], "type": "END"}, "مرحلهٔ بعدی در تعریف فرایند وجود ندارد.", None,
                  [t for t in tokens if t is not token], variables)
            session.commit()
            return None
        if inst.step_count > max_steps or visits[token["node"]] > MAX_VISITS_PER_NODE:
            _fail(session, inst, node, "تعداد مراحل اجراشده از حد مجاز گذشت (محافظت از حلقهٔ بی‌پایان).", None,
                  [t for t in tokens if t is not token], variables)
            session.commit()
            return None
        adapter = registry.get_adapter(inst.entity_type)
        if node["type"] == "ACTION":
            step = _open_step(session, inst, node, "RUNNING", attempt=int(token.get("visit", 1)))
            token.update(state="RUNNING", since=now().isoformat(), step_id=step.step_id)
            _save(inst, tokens=tokens, variables=variables)
            run_as = _run_as(inst, node, variables)
            pending = {"company_id": inst.company_id, "node": node, "visit": int(token.get("visit", 1)),
                       "entity_type": inst.entity_type, "entity_id": inst.entity_id, "context": dict(inst.context or {}),
                       "run_as": run_as, "token_id": token["id"]}
            session.commit()
            return pending
        if node["type"] == "START":
            result = NodeResult("NEXT", detail={"trigger_event_id": inst.trigger_event_id})
        else:
            handler = NODE_HANDLERS.get(node["type"])
            run = Run(session, inst, graph, node, token, adapter, variables)
            if handler is None:
                result = NodeResult("FAIL", error=f"مرحلهٔ «{NODE_TYPES.get(node['type'], node['type'])}» در این نسخه فعال نیست.")
            else:
                try:
                    result = handler(run)
                except Exception as exc:  # noqa: BLE001
                    friendly, technical = friendly_error(exc)
                    result = NodeResult("FAIL", error=friendly, technical=technical)
        _apply(session, inst, graph, node, token, tokens, variables, result)
        session.commit()
        return "CONTINUE"


def _run_as(inst: WfInstance, node: dict, variables: dict) -> int | None:
    mode = (node.get("run_as") or "APPROVER").upper()
    if mode == "STARTER":
        return inst.started_by_user_id
    if mode == "USER" and node.get("run_as_user_id"):
        return int(node["run_as_user_id"])
    return variables.get("last_decider") or variables.get("last_actor") or inst.started_by_user_id


def _complete_action(instance_id: int, token_id: str, outcome: actions.ActionOutcome) -> None:
    with new_session() as session:
        inst = session.scalar(select(WfInstance).where(WfInstance.instance_id == instance_id).with_for_update())
        if inst is None or inst.status_code not in ("RUNNING", "WAITING"):
            return
        tokens = copy.deepcopy(inst.tokens or [])
        variables = copy.deepcopy(inst.variables or {})
        token = next((t for t in tokens if t.get("id") == token_id), None)
        if token is None or token.get("state") != "RUNNING":
            return
        graph = _graph(session, inst.version_id)
        node = _node(graph, token["node"])
        step = session.get(WfInstanceStep, token.get("step_id")) if token.get("step_id") else None
        detail = {"result": outcome.result, "attempts": outcome.attempts, "execution_id": outcome.execution_id}
        if outcome.status == "DONE":
            variables.update({"vars": {**variables.get("vars", {}), **(outcome.result.get("variables") or {})}})
            _apply(session, inst, graph, node, token, tokens, variables, NodeResult("NEXT", detail=detail), step)
        elif outcome.status == "RETRY":
            timer = WfTimer(company_id=inst.company_id, kind="RETRY", instance_id=inst.instance_id, node_id=node["id"],
                            payload={"token_id": token_id}, due_at=outcome.retry_at)
            session.add(timer)
            session.flush()
            if step is not None:
                step.status_code, step.error = "WAITING", outcome.error
                step.detail = plain({**(step.detail or {}), **detail, "retry_at": outcome.retry_at})
                flag_modified(step, "detail")
            token.update(state="WAITING", timer_id=timer.timer_id, retry=True)
            inst.status_code = "RUNNING" if any(t.get("state") == "READY" for t in tokens) else "WAITING"
            _save(inst, tokens=tokens, variables=variables)
        elif any(e.get("when") == "failed" for e in definitions.outgoing(graph, node["id"])):
            _apply(session, inst, graph, node, token, tokens, variables,
                   NodeResult("NEXT", when="failed", detail=detail, error=outcome.error), step)
        else:
            _close_step(step, "FAILED", detail=detail, error=outcome.error)
            title = f"اجرای «{node.get('label') or 'اقدام خودکار'}» در فرایند «{inst.title or ''}» ناموفق بود"
            ex = _raise_exception(session, inst, node, title, outcome.error or "اجرا ناموفق بود.", outcome.technical,
                                  outcome.execution_id)
            token.update(state="EXCEPTION", exception_id=ex.exception_id)
            inst.status_code = "RUNNING" if any(t.get("state") == "READY" for t in tokens) else "WAITING"
            _save(inst, tokens=tokens, variables=variables)
        session.commit()


def resume(company_id: int, instance_id: int, *, node_id: str | None = None, token_id: str | None = None,
           when: str | None = None, actor_user_id: int | None = None, detail: dict | None = None,
           states: tuple[str, ...] = ("WAITING",), run: bool = True, vars_patch: dict | None = None) -> bool:
    """ادامهٔ نشانهٔ منتظر (پس از تایید، پایان کار، زمان‌سنج یا رویداد). vars_patch: دادهٔ واردشده در کار."""
    with new_session() as session:
        inst = session.scalar(select(WfInstance).where(WfInstance.instance_id == instance_id).with_for_update())
        if inst is None or inst.company_id != company_id or inst.status_code not in ("RUNNING", "WAITING"):
            return False
        tokens = copy.deepcopy(inst.tokens or [])
        variables = copy.deepcopy(inst.variables or {})
        token = next((t for t in tokens if (token_id and t.get("id") == token_id) or
                      (not token_id and t.get("node") == node_id and t.get("state") in states)), None)
        if token is None or token.get("state") not in states:
            return False
        graph = _graph(session, inst.version_id)
        node = _node(graph, token["node"])
        step = session.get(WfInstanceStep, token.get("step_id")) if token.get("step_id") else None
        if actor_user_id:
            variables["last_decider"] = actor_user_id
        if vars_patch:
            variables["vars"] = {**variables.get("vars", {}), **plain(vars_patch)}
        for hook in LEAVE_HOOKS:
            hook(session, inst, token, when)
        _apply(session, inst, graph, node, token, tokens, variables,
               NodeResult("NEXT", when=when, detail=detail or {}, actor_user_id=actor_user_id), step)
        session.commit()
    if run:
        run_instance(instance_id)
    return True


def retry_token(company_id: int, instance_id: int, token_id: str) -> bool:
    """پس از زمان تلاش دوباره یا درخواست دستی: نشانهٔ منتظر دوباره آمادهٔ اجرا می‌شود."""
    with new_session() as session:
        inst = session.scalar(select(WfInstance).where(WfInstance.instance_id == instance_id).with_for_update())
        if inst is None or inst.company_id != company_id or inst.status_code not in ("RUNNING", "WAITING"):
            return False
        tokens = copy.deepcopy(inst.tokens or [])
        token = next((t for t in tokens if t.get("id") == token_id), None)
        if token is None or token.get("state") not in ("WAITING", "EXCEPTION", "RUNNING"):
            return False
        step = session.get(WfInstanceStep, token.get("step_id")) if token.get("step_id") else None
        _close_step(step, "FAILED", error=step.error if step else None)
        for k in ("timer_id", "retry", "exception_id", "step_id", "since"):
            token.pop(k, None)
        token["state"] = "READY"
        inst.status_code = "RUNNING"
        _save(inst, tokens=tokens)
        session.commit()
    run_instance(instance_id)
    return True


def resume_waiting_for_event(company_id: int, event_type: str, entity_type: str | None, entity_id: int | None) -> int:
    """گره «انتظار تا رویداد»: نمونه‌های منتظر همان سند با رسیدن رویداد ادامه می‌دهند."""
    if not entity_id:
        return 0
    with new_session() as session:
        rows = [(i.instance_id, [t["id"] for t in (i.tokens or []) if t.get("state") == "WAITING" and
                                 t.get("await_event") == event_type])
                for i in session.scalars(select(WfInstance).where(
                    WfInstance.company_id == company_id, WfInstance.status_code == "WAITING",
                    WfInstance.entity_type == entity_type, WfInstance.entity_id == entity_id))]
    resumed = 0
    for instance_id, token_ids in rows:
        for tid in token_ids:
            with new_session() as session:
                session.execute(update(WfTimer).where(WfTimer.instance_id == instance_id, WfTimer.status_code == "PENDING",
                                                      WfTimer.payload["token_id"].astext == tid).values(status_code="CANCELLED"))
                session.commit()
            resumed += resume(company_id, instance_id, token_id=tid, detail={"event": event_type})
    return resumed


def cancel_instance(company_id: int, instance_id: int, user_id: int | None, reason: str = "") -> None:
    with new_session() as session:
        inst = session.scalar(select(WfInstance).where(WfInstance.instance_id == instance_id).with_for_update())
        if inst is None or inst.company_id != company_id:
            raise WorkflowError("فرایند نامعتبر است.")
        if inst.status_code not in ("RUNNING", "WAITING", "SUSPENDED"):
            raise WorkflowError("این فرایند دیگر در جریان نیست.")
        _close_instance(session, inst, "CANCELLED", outcome="CANCELLED", error=reason or None, actor=user_id)
        session.commit()


def recover_stuck(company_id: int | None = None) -> int:
    """نشانه‌ای که هنگام اجرای اقدام (مثلاً با بستن ناگهانی برنامه) رها شده دوباره آماده می‌شود؛ دفتر یکتای اقدام
    مانع اجرای تکراری است."""
    limit = now() - datetime.timedelta(minutes=STUCK_MINUTES)
    with new_session() as session:
        q = select(WfInstance).where(WfInstance.status_code.in_(("RUNNING", "WAITING")))
        if company_id is not None:
            q = q.where(WfInstance.company_id == company_id)
        candidates = [i.instance_id for i in session.scalars(q) if any(
            t.get("state") == "RUNNING" and t.get("since") and datetime.datetime.fromisoformat(t["since"]) < limit
            for t in i.tokens or [])]
    fixed = 0
    for instance_id in candidates:
        with new_session() as session:
            inst = session.scalar(select(WfInstance).where(WfInstance.instance_id == instance_id).with_for_update(skip_locked=True))
            if inst is None:
                continue
            tokens = copy.deepcopy(inst.tokens or [])
            for t in tokens:
                if t.get("state") == "RUNNING" and t.get("since") and datetime.datetime.fromisoformat(t["since"]) < limit:
                    t["state"] = "READY"
                    fixed += 1
            inst.status_code = "RUNNING"
            _save(inst, tokens=tokens)
            session.commit()
        run_instance(instance_id)
    return fixed


# --- گره‌های داخلی ---------------------------------------------------------------------------------------
def _condition(run: Run) -> NodeResult:
    ctx = run.refresh_context()
    ok = conditions.evaluate(run.node.get("rule"), {**ctx, "vars": run.variables.get("vars", {})})
    return NodeResult("NEXT", when="yes" if ok else "no",
                      detail={"rule": conditions.describe(run.node.get("rule"), run.labels()),
                              "checks": conditions.explain(run.node.get("rule"), ctx, run.labels()), "result": ok})


def _notify(run: Run) -> NodeResult:
    inst = run.instance
    ctx = run.refresh_context()
    users = routing.resolve(inst.company_id, run.node.get("to") or [], context=ctx, starter=inst.started_by_user_id,
                            entity_type=inst.entity_type, entity_id=inst.entity_id)
    title = render(run.node.get("title") or "", {**ctx, "عنوان": inst.title}, run.labels())
    body = render(run.node.get("body") or "", {**ctx, "عنوان": inst.title}, run.labels())
    sent = notify.send(inst.company_id, users, run.node.get("type_code") or "WF_MESSAGE", title or inst.title, body,
                       "WfInstance", inst.instance_id)
    return NodeResult("NEXT", detail={"recipients": sent, "title": title})


def _wait(run: Run) -> NodeResult:
    node, inst = run.node, run.instance
    if node.get("until_event"):
        patch = {"await_event": node["until_event"]}
        if node.get("timeout_hours"):
            timer = WfTimer(company_id=inst.company_id, kind="WAIT", instance_id=inst.instance_id, node_id=node["id"],
                            payload={"token_id": run.token["id"], "when": "timeout"},
                            due_at=now() + datetime.timedelta(hours=float(node["timeout_hours"])))
            run.session.add(timer)
            run.session.flush()
            patch["timer_id"] = timer.timer_id
        return NodeResult("WAIT", detail={"until_event": node["until_event"]}, token_patch=patch)
    due = None
    delta = datetime.timedelta(days=float(node.get("days") or 0), hours=float(node.get("hours") or 0),
                               minutes=float(node.get("minutes") or 0))
    if delta.total_seconds() > 0:
        due = now() + delta
    elif node.get("until_field"):
        value = conditions._date(conditions.get_path(run.refresh_context(), node["until_field"]), datetime.date.today())
        if value is None:
            return NodeResult("NEXT", detail={"note": "تاریخ مورد انتظار در سند خالی است؛ بدون انتظار ادامه یافت."})
        value += datetime.timedelta(days=int(node.get("offset_days") or 0))
        due = datetime.datetime.combine(value, datetime.time(8, 0)).astimezone()
    if due is None or due <= now():
        return NodeResult("NEXT", detail={"note": "زمان انتظار گذشته بود."})
    timer = WfTimer(company_id=inst.company_id, kind="WAIT", instance_id=inst.instance_id, node_id=node["id"],
                    payload={"token_id": run.token["id"]}, due_at=due)
    run.session.add(timer)
    run.session.flush()
    return NodeResult("WAIT", detail={"until": due}, token_patch={"timer_id": timer.timer_id})


def _join(run: Run) -> NodeResult:
    joins = run.variables.setdefault("joins", {})
    nid = run.node["id"]
    joins[nid] = int(joins.get(nid, 0)) + 1
    needed = len(definitions.incoming(run.graph, nid))
    if joins[nid] >= needed:
        joins[nid] = 0
        return NodeResult("NEXT", detail={"arrived": needed})
    return NodeResult("CONSUME", detail={"arrived": joins[nid], "needed": needed})


register_node("CONDITION", _condition)
register_node("NOTIFY", _notify)
register_node("WAIT", _wait)
register_node("PARALLEL", lambda run: NodeResult("NEXT"))
register_node("JOIN", _join)
register_node("END", lambda run: NodeResult("END", outcome=run.node.get("outcome") or "DONE"))


# --- خواندن برای UI --------------------------------------------------------------------------------------
@dataclass
class InstanceRow:
    instance_id: int
    definition_id: int
    definition_name: str
    version_no: int
    entity_type: str | None
    entity_id: int | None
    title: str
    status_code: str
    status_label: str
    outcome_code: str | None
    started_by: str
    started_at: datetime.datetime
    ended_at: datetime.datetime | None
    waiting_on: str
    last_error: str | None


def _instance_rows(session, rows) -> list[InstanceRow]:
    rows = list(rows)
    defs = {d.definition_id: d for d in session.scalars(select(WfDefinition).where(
        WfDefinition.definition_id.in_({r.definition_id for r in rows})))} if rows else {}
    vers = {v.version_id: v for v in session.scalars(select(WfDefinitionVersion).where(
        WfDefinitionVersion.version_id.in_({r.version_id for r in rows})))} if rows else {}
    names = user_names(session, {r.started_by_user_id for r in rows})
    out = []
    for r in rows:
        graph = _graph(session, r.version_id)
        waiting = [(_node(graph, t["node"]) or {}).get("label") or "" for t in r.tokens or []]
        out.append(InstanceRow(r.instance_id, r.definition_id, defs[r.definition_id].name, vers[r.version_id].version_no,
                               r.entity_type, r.entity_id, r.title or "", r.status_code, INSTANCE_STATUS.get(r.status_code, r.status_code),
                               r.outcome_code, names.get(r.started_by_user_id, "سیستم"), r.started_at, r.ended_at,
                               "، ".join(w for w in waiting if w), r.last_error))
    return out


def list_instances(company_id: int, *, status: str | None = None, definition_id: int | None = None,
                   entity_type: str | None = None, entity_id: int | None = None, limit: int = 300,
                   offset: int = 0) -> list[InstanceRow]:
    with new_session() as session:
        q = select(WfInstance).where(WfInstance.company_id == company_id)
        if status:
            q = q.where(WfInstance.status_code == status)
        if definition_id:
            q = q.where(WfInstance.definition_id == definition_id)
        if entity_type:
            q = q.where(WfInstance.entity_type == entity_type)
        if entity_id:
            q = q.where(WfInstance.entity_id == entity_id)
        return _instance_rows(session, session.scalars(q.order_by(WfInstance.instance_id.desc()).limit(limit).offset(offset)))


def get_instance(company_id: int, instance_id: int) -> InstanceRow:
    with new_session() as session:
        inst = session.get(WfInstance, instance_id)
        if inst is None or inst.company_id != company_id:
            raise WorkflowError("فرایند نامعتبر است.")
        return _instance_rows(session, [inst])[0]


@dataclass
class TimelineRow:
    at: datetime.datetime
    kind: str
    title: str
    detail: str
    actor: str
    status: str


def timeline(company_id: int, instance_id: int) -> list[TimelineRow]:
    with new_session() as session:
        inst = session.get(WfInstance, instance_id)
        if inst is None or inst.company_id != company_id:
            raise WorkflowError("فرایند نامعتبر است.")
        steps = list(session.scalars(select(WfInstanceStep).where(WfInstanceStep.instance_id == instance_id)
                                     .order_by(WfInstanceStep.step_id)))
        names = user_names(session, {s.actor_user_id for s in steps} | {inst.started_by_user_id})
        rows = [TimelineRow(inst.started_at, "START", "شروع فرایند", inst.title or "", names.get(inst.started_by_user_id, "سیستم"), "DONE")]
        for s in steps:
            if s.node_type == "START":
                continue
            detail = s.error or ""
            if not detail and s.outcome:
                detail = definitions.EDGE_LABELS.get(s.outcome, OUTCOMES.get(s.outcome, s.outcome))
            if not detail and (s.detail or {}).get("rule"):
                detail = s.detail["rule"]
            rows.append(TimelineRow(s.ended_at or s.started_at, s.node_type, s.label or NODE_TYPES.get(s.node_type, ""),
                                    detail, names.get(s.actor_user_id, ""), s.status_code))
        for provider in TIMELINE_PROVIDERS:
            rows += provider(session, inst)
        if inst.ended_at:
            rows.append(TimelineRow(inst.ended_at, "END", f"پایان: {INSTANCE_STATUS.get(inst.status_code)}",
                                    OUTCOMES.get(inst.outcome_code or "", inst.last_error or ""), "", inst.status_code))
        return sorted(rows, key=lambda r: r.at)


def status_path(company_id: int, instance_id: int) -> list[tuple[str, str]]:
    """مسیر اصلی برای نوار وضعیت سند: [(برچسب، done|current|pending|failed)]."""
    with new_session() as session:
        inst = session.get(WfInstance, instance_id)
        if inst is None or inst.company_id != company_id:
            return []
        graph = _graph(session, inst.version_id)
        steps = list(session.scalars(select(WfInstanceStep).where(WfInstanceStep.instance_id == instance_id)
                                     .order_by(WfInstanceStep.step_id)))
    taken: dict[str, str | None] = {}
    done: set[str] = set()
    failed: set[str] = set()
    for s in steps:
        if s.status_code == "DONE":
            done.add(s.node_id)
            taken[s.node_id] = s.outcome
        elif s.status_code == "FAILED":
            failed.add(s.node_id)
    current = {t["node"] for t in inst.tokens or []}
    nodes = definitions.nodes_by_id(graph)
    path, nid, seen = [("ثبت و ارسال", "done")], START, set()
    while nid and nid not in seen:
        seen.add(nid)
        node = _node(graph, nid) or {}
        if nid != START and node.get("type") in ("APPROVAL", "TASK", "ACTION", "END"):
            state = "current" if nid in current else "failed" if nid in failed else "done" if nid in done else "pending"
            label = node.get("label") or NODE_TYPES.get(node.get("type"), "")
            if node.get("type") == "END":
                label = OUTCOMES.get(inst.outcome_code or node.get("outcome") or "DONE", label) if nid in done else label
            path.append((label, state))
        if node.get("type") == "END":
            break
        default = {"CONDITION": "yes", "APPROVAL": "approved", "TASK": "done"}.get(node.get("type"))
        edges = _next_edges(graph, node, taken.get(nid, default)) if nid in nodes or nid == START else []
        nid = edges[0]["to"] if edges else None
    return path


from peecha.services.workflow import tasks as _tasks  # noqa: E402,F401 -- گره‌های تایید و کار انسانی
