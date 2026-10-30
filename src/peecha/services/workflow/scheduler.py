"""زمان‌بند موتور: زمان‌سنج‌ها، بررسی‌های دوره‌ای، فرایندهای زمان‌بندی‌شده و رویدادهای در صف.

اجراکننده‌ها: تیک دسکتاپ (هر دقیقه)، فرمان مستقل سرور (worker.py) یا API. چند اجراکنندهٔ هم‌زمان امن‌اند
(FOR UPDATE SKIP LOCKED + کلید یکتای هر دوره).
"""

from __future__ import annotations

import datetime
from typing import Callable

from sqlalchemy import or_, select, update
from sqlalchemy.orm.attributes import flag_modified

from peecha.db.base import new_session
from peecha.db.models.workflow import WfDefinition, WfDefinitionTrigger, WfTimer

# پیش از import زمان‌اجرا تعریف می‌شوند تا ماژول‌هایی که هنگام import ثبت‌نام می‌کنند (tasks) در import دوری هم کار کنند
TIMER_HANDLERS: dict[str, Callable[[WfTimer], None]] = {}
TICK_HOOKS: dict[str, Callable[[int | None], int]] = {}  # کارهای دوره‌ای ماژول‌های موتور (مثلاً ادامهٔ کارهای بسته‌شده)


def register_tick(name: str, func: Callable[[int | None], int]) -> None:
    TICK_HOOKS[name] = func


def register_timer(kind: str, handler: Callable[[WfTimer], None]) -> None:
    TIMER_HANDLERS[kind] = handler


from peecha.services.workflow import events, registry, runtime  # noqa: E402
from peecha.services.workflow.common import RUNNABLE_STATUSES, friendly_error, now  # noqa: E402


def _wait_timer(timer: WfTimer) -> None:
    runtime.resume(timer.company_id, timer.instance_id, token_id=timer.payload.get("token_id"),
                   when=timer.payload.get("when"), detail={"timer": timer.timer_id})


def _retry_timer(timer: WfTimer) -> None:
    runtime.retry_token(timer.company_id, timer.instance_id, timer.payload.get("token_id"))


register_timer("WAIT", _wait_timer)
register_timer("RETRY", _retry_timer)


def fire_due_timers(company_id: int | None = None, at: datetime.datetime | None = None, limit: int = 100) -> int:
    t = at or now()
    with new_session() as session:
        q = select(WfTimer.timer_id).where(WfTimer.status_code == "PENDING", WfTimer.due_at <= t,
                                           or_(WfTimer.locked_until.is_(None), WfTimer.locked_until < now()))
        if company_id is not None:
            q = q.where(WfTimer.company_id == company_id)
        ids = list(session.scalars(q.order_by(WfTimer.due_at).limit(limit).with_for_update(skip_locked=True)))
        if ids:
            session.execute(update(WfTimer).where(WfTimer.timer_id.in_(ids))
                            .values(locked_until=now() + datetime.timedelta(minutes=5)))
        session.commit()
    fired = 0
    for timer_id in ids:
        with new_session() as session:
            timer = session.get(WfTimer, timer_id)
            if timer is None or timer.status_code != "PENDING":
                continue
            session.expunge(timer)
        error = None
        try:
            handler = TIMER_HANDLERS.get(timer.kind)
            if handler is not None:
                handler(timer)
        except Exception as exc:  # noqa: BLE001
            error = friendly_error(exc)[1]
        with new_session() as session:
            row = session.get(WfTimer, timer_id)
            row.attempts += 1
            row.locked_until = None
            if error and row.attempts < 5:
                row.payload = {**(row.payload or {}), "last_error": error}
                flag_modified(row, "payload")
            elif row.status_code == "PENDING":
                row.status_code, row.fired_at = ("FAILED" if error else "DONE"), now()
            session.commit()
        fired += 1
    return fired


def _period_key(every: str, at: datetime.datetime) -> str:
    local = at.astimezone()
    if every == "HOUR":
        return local.strftime("%Y%m%d%H")
    if every == "WEEK":
        year, week, _ = local.isocalendar()
        return f"{year}W{week:02d}"
    return local.strftime("%Y%m%d")


def _due(config: dict, at: datetime.datetime) -> bool:
    local = at.astimezone()
    hh, mm = (int(x) for x in (config.get("at") or "00:00").split(":")[:2])
    if config.get("every") == "HOUR":
        return local.minute >= mm
    if config.get("every") == "WEEK" and config.get("weekday") is not None and local.weekday() != int(config["weekday"]):
        return False
    return (local.hour, local.minute) >= (hh, mm)


def _runnable_triggers(session, company_id: int | None, trigger_type: str):
    q = select(WfDefinitionTrigger).join(WfDefinition, WfDefinition.definition_id == WfDefinitionTrigger.definition_id).where(
        WfDefinitionTrigger.trigger_type == trigger_type, WfDefinitionTrigger.is_active.is_(True),
        WfDefinition.status_code.in_(RUNNABLE_STATUSES), WfDefinitionTrigger.version_id == WfDefinition.active_version_id)
    if company_id is not None:
        q = q.where(WfDefinitionTrigger.company_id == company_id)
    return list(session.scalars(q))


def run_schedules(company_id: int | None = None, at: datetime.datetime | None = None) -> int:
    t = at or now()
    with new_session() as session:
        triggers = [(tr.company_id, tr.definition_id, dict(tr.config or {})) for tr in _runnable_triggers(session, company_id, "SCHEDULE")]
    started = 0
    for cid, definition_id, config in triggers:
        if not _due(config, t):
            continue
        key = f"sch:{definition_id}:{_period_key(config.get('every') or 'DAY', t)}"
        try:
            started += bool(runtime.start_instance(cid, definition_id, None, None, correlation_key=key))
        except Exception:  # noqa: BLE001 -- یک فرایند ناقص نباید بقیه را متوقف کند
            pass
    return started


def run_scans(company_id: int | None = None, at: datetime.datetime | None = None, force: bool = False) -> int:
    """بررسی‌های دوره‌ای: موجودیت‌های منطبق ← رویداد یکتا در هر دوره ← شروع فرایند همان تعریف."""
    t = at or now()
    published = 0
    with new_session() as session:
        claims = []
        for tr in _runnable_triggers(session, company_id, "SCAN"):
            config = dict(tr.config or {})
            last = config.get("last_run_at")
            every = int(config.get("every_minutes") or 60)
            if not force and last and datetime.datetime.fromisoformat(last) > t - datetime.timedelta(minutes=every):
                continue
            config["last_run_at"] = t.isoformat()
            tr.config = config
            flag_modified(tr, "config")
            claims.append((tr.company_id, tr.definition_id, config))
        session.commit()
    for cid, definition_id, config in claims:
        scan = registry.scans().get(config.get("scan") or "")
        if scan is None:
            continue
        try:
            ids = scan.func(cid, config.get("params") or {})
        except Exception:  # noqa: BLE001
            continue
        period = _period_key("DAY" if scan.period == "DAY" else scan.period, t)
        with new_session() as session:
            for entity_id in ids:
                published += events.publish(session, cid, f"SCAN:{scan.code}", scan.entity_type, entity_id,
                                            {"definition_id": definition_id, "scan": scan.code},
                                            dedupe_key=f"scan:{definition_id}:{entity_id}:{period}") is not None
            session.commit()
    return published


def run_due(company_id: int | None = None, at: datetime.datetime | None = None) -> dict:
    """یک دور کامل زمان‌بند (برای تیک دسکتاپ/سرور)."""
    counts = {"recovered": runtime.recover_stuck(company_id)}
    counts["timers"] = fire_due_timers(company_id, at)
    counts["schedules"] = run_schedules(company_id, at)
    counts["scans"] = run_scans(company_id, at)
    counts["events"] = events.dispatch_pending(company_id)
    for name, func in TICK_HOOKS.items():
        try:
            counts[name] = func(company_id)
        except Exception:  # noqa: BLE001
            counts[name] = 0
    return counts


def tick(company_id: int | None) -> dict:
    """تیک بی‌صدای دسکتاپ: هیچ خطایی نباید برنامه را متوقف کند."""
    try:
        return run_due(company_id)
    except Exception:  # noqa: BLE001
        return {}
