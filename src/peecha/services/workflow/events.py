"""Event Bus درون‌فرایندی و ماندگار (Transactional Outbox روی PostgreSQL).

سرویس‌ها رویداد را با publish(session, ...) در همان تراکنش عملیات اصلی ثبت می‌کنند؛ پس از commit همان
فرایند (یا تیک دوره‌ای پس از ری‌استارت) آن را پردازش می‌کند. RabbitMQ/Kafka لازم نیست.
"""

from __future__ import annotations

import datetime
import threading
from contextlib import contextmanager

from sqlalchemy import event as sa_event
from sqlalchemy import or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from peecha.db.base import new_session
from peecha.db.models.workflow import WfDefinition, WfDefinitionTrigger, WfEvent, WfInstance
from peecha.services.workflow import conditions, registry
from peecha.services.workflow.common import RUNNABLE_STATUSES, friendly_error, now, plain, settings

AUTO_DISPATCH = True  # پردازش بلافاصله پس از commit در همین فرایند (تست‌ها و دسکتاپ)
_STATE = threading.local()


def _depth() -> int:
    return getattr(_STATE, "depth", 0)


@contextmanager
def engine_busy():
    """وقتی موتور در حال اجراست، رویدادهای تازه فقط صف می‌شوند و پس از پایان بیرونی‌ترین اجرا پردازش می‌شوند
    (جلوگیری از بازگشت تودرتو و قفل متقابل روی همان نمونه)."""
    _STATE.depth = _depth() + 1
    try:
        yield
    finally:
        _STATE.depth = _depth() - 1
        if _STATE.depth == 0:
            pending = getattr(_STATE, "pending", set())
            _STATE.pending = set()
            if AUTO_DISPATCH:
                for cid in pending:
                    try:
                        dispatch_pending(cid)
                    except Exception:  # noqa: BLE001 -- پردازش پس‌زمینه نباید عملیات کاربر را خراب کند
                        pass


@sa_event.listens_for(Session, "after_commit")
def _after_commit(session) -> None:
    companies = session.info.pop("wf_companies", None)
    if not companies or not AUTO_DISPATCH:
        return
    if _depth() > 0:
        _STATE.pending = getattr(_STATE, "pending", set()) | set(companies)
        return
    for cid in companies:
        try:
            dispatch_pending(cid)
        except Exception:  # noqa: BLE001
            pass


@sa_event.listens_for(Session, "after_rollback")
def _after_rollback(session) -> None:
    session.info.pop("wf_companies", None)


def publish(session, company_id: int, event_type: str, entity_type: str | None = None, entity_id: int | None = None,
            payload: dict | None = None, *, actor_user_id: int | None = None, dedupe_key: str | None = None,
            causation_instance_id: int | None = None, depth: int = 0) -> int | None:
    """ثبت رویداد در همان تراکنش؛ رویداد تکراری (همان dedupe_key) نادیده گرفته می‌شود."""
    stmt = insert(WfEvent).values(company_id=company_id, event_type=event_type, entity_type=entity_type,
                                  entity_id=entity_id, payload=plain(payload or {}), dedupe_key=dedupe_key,
                                  actor_user_id=actor_user_id, causation_instance_id=causation_instance_id, depth=depth)
    if dedupe_key:
        stmt = stmt.on_conflict_do_nothing(index_elements=["company_id", "dedupe_key"],
                                           index_where=WfEvent.dedupe_key.isnot(None))
    event_id = session.execute(stmt.returning(WfEvent.event_id)).scalar()
    if event_id is not None:
        session.info.setdefault("wf_companies", set()).add(company_id)
    return event_id


def emit(company_id: int, event_type: str, entity_type: str | None = None, entity_id: int | None = None,
         payload: dict | None = None, **kwargs) -> int | None:
    """رویداد با session جدا (برای جاهایی که عملیات اصلی قبلاً commit شده)."""
    with new_session() as session:
        event_id = publish(session, company_id, event_type, entity_type, entity_id, payload, **kwargs)
        session.commit()
        return event_id


def has_listeners(company_id: int, event_type: str) -> bool:
    with new_session() as session:
        return session.scalar(select(WfDefinitionTrigger.trigger_id).where(
            WfDefinitionTrigger.company_id == company_id, WfDefinitionTrigger.event_type == event_type,
            WfDefinitionTrigger.is_active.is_(True)).limit(1)) is not None


def _claim(company_id: int | None, limit: int) -> list[int]:
    with new_session() as session:
        t = now()
        q = select(WfEvent.event_id).where(WfEvent.status_code == "PENDING",
                                           or_(WfEvent.locked_until.is_(None), WfEvent.locked_until < t))
        if company_id is not None:
            q = q.where(WfEvent.company_id == company_id)
        ids = list(session.scalars(q.order_by(WfEvent.event_id).limit(limit).with_for_update(skip_locked=True)))
        if ids:
            session.execute(update(WfEvent).where(WfEvent.event_id.in_(ids))
                            .values(locked_until=t + datetime.timedelta(minutes=2)))
        session.commit()
        return ids


def dispatch_pending(company_id: int | None = None, limit: int = 100) -> int:
    """همهٔ رویدادهای در صف را پردازش می‌کند (امن برای چند اجراکنندهٔ هم‌زمان)."""
    total = 0
    with engine_busy():
        for _ in range(20):
            ids = _claim(company_id, limit)
            if not ids:
                break
            for event_id in ids:
                process_event(event_id)
                total += 1
    return total


def process_event(event_id: int) -> None:
    from peecha.services.workflow import runtime

    with new_session() as session:
        ev = session.get(WfEvent, event_id)
        if ev is None or ev.status_code != "PENDING":
            return
        company_id = ev.company_id
        data = dict(event_type=ev.event_type, entity_type=ev.entity_type, entity_id=ev.entity_id,
                    payload=dict(ev.payload or {}), depth=ev.depth, causation=ev.causation_instance_id,
                    actor=ev.actor_user_id)
        q = select(WfDefinitionTrigger).join(WfDefinition, WfDefinition.definition_id == WfDefinitionTrigger.definition_id).where(
            WfDefinitionTrigger.company_id == company_id, WfDefinitionTrigger.event_type == ev.event_type,
            WfDefinitionTrigger.is_active.is_(True), WfDefinition.status_code.in_(RUNNABLE_STATUSES),
            WfDefinitionTrigger.version_id == WfDefinition.active_version_id)
        triggers = [(t.definition_id, t.version_id, t.entity_type) for t in session.scalars(q)]
        # همهٔ فرایندهای زنجیرهٔ علّی (الف ← ب ← ...)؛ هیچ‌کدام نباید دوباره روی همان سند شروع شوند
        ancestry: set[tuple] = set()
        cause, hops = ev.causation_instance_id, 0
        while cause and hops < 20:
            src = session.get(WfInstance, cause)
            if src is None:
                break
            ancestry.add((src.definition_id, src.entity_type, src.entity_id))
            parent = session.get(WfEvent, src.trigger_event_id) if src.trigger_event_id else None
            cause, hops = (parent.causation_instance_id if parent else None), hops + 1
    started, skipped, error = 0, [], None
    try:
        max_depth = int(settings(company_id).get("max_event_depth") or 5)
        context_cache: dict | None = None
        only_def = data["payload"].get("definition_id") if data["event_type"].startswith("SCAN:") else None
        for definition_id, version_id, trig_entity in triggers:
            if only_def and int(only_def) != definition_id:
                continue
            if trig_entity and data["entity_type"] and trig_entity != data["entity_type"]:
                continue
            if data["depth"] > max_depth:
                skipped.append("زنجیرهٔ رویدادها بیش از حد مجاز تودرتو شد (محافظت از اجرای بی‌پایان).")
                continue
            if (definition_id, data["entity_type"], data["entity_id"]) in ancestry:
                skipped.append("فرایند نمی‌تواند خودش را دوباره روی همان سند شروع کند.")
                continue
            if context_cache is None:
                context_cache = runtime.load_context(company_id, data["entity_type"], data["entity_id"])
                context_cache["event"] = data["payload"]
            with new_session() as session:
                v = session.get(registry_version_model(), version_id)
                trigger = (v.graph or {}).get("trigger") or {}
            if not conditions.evaluate(trigger.get("condition"), context_cache):
                continue
            if runtime.start_instance(company_id, definition_id, data["entity_type"], data["entity_id"],
                                      started_by=data["actor"], context=dict(context_cache),
                                      correlation_key=f"ev:{event_id}:{definition_id}", trigger_event_id=event_id,
                                      depth=data["depth"]):
                started += 1
        runtime.resume_waiting_for_event(company_id, data["event_type"], data["entity_type"], data["entity_id"])
    except Exception as exc:  # noqa: BLE001
        error = friendly_error(exc)[1]
    with new_session() as session:
        ev = session.get(WfEvent, event_id)
        ev.attempts += 1
        ev.locked_until = None
        if error and ev.attempts < 5:
            ev.last_error = error
        else:
            ev.status_code = "FAILED" if error else ("SKIPPED" if skipped and not started else "DONE")
            ev.last_error = error or ("؛ ".join(skipped) or None)
            ev.processed_at = now()
        session.commit()


def registry_version_model():
    from peecha.db.models.workflow import WfDefinitionVersion

    return WfDefinitionVersion


def recent_events(company_id: int, limit: int = 200) -> list[WfEvent]:
    with new_session() as session:
        rows = list(session.scalars(select(WfEvent).where(WfEvent.company_id == company_id)
                                    .order_by(WfEvent.event_id.desc()).limit(limit)))
        session.expunge_all()
        return rows
