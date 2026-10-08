"""رویدادهای خودکار از تغییر اسناد و «دروازهٔ تایید» — بدون یک خط تغییر در سرویس‌های کسب‌وکار.

هر ماژول با watch() می‌گوید کدام مدل، با کدام ستون وضعیت، به کدام نوع سند گردش کار نگاشت می‌شود. پس از هر flush:
    سند تازه ← «<نوع سند>_CREATED»؛ تغییر وضعیت ← «<نوع سند>_<وضعیت تازه>»
رویداد در همان تراکنش ثبت می‌شود (اگر عملیات برگشت بخورد رویدادی هم نمی‌ماند) و فقط وقتی کسی به آن گوش می‌دهد.

دروازهٔ تایید: اگر برای نوعی از سند فرایندی «با دروازه» فعال باشد، ورود سند به وضعیت‌های حساس (مثلاً تصویب یا ثبت
نهایی) فقط از مسیر همان فرایند ممکن است؛ تا سند از گردش کار «تاییدشده» بیرون نیامده باشد، دکمهٔ معمول تصویب
پیام روشن می‌دهد. بدون فرایند فعال با دروازه، رفتار برنامه دقیقاً مثل قبل است.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Callable

from sqlalchemy import event as sa_event, inspect, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from peecha.db.models.workflow import WfEvent
from peecha.services.workflow.common import WorkflowError, plain


@dataclass
class Watch:
    model: type
    entity_type: Callable[[Any], str | None]  # نوع سند گردش کار برای این ردیف (None یعنی نادیده)
    status_attr: str | None = "status_code"
    status_code: Callable[[Any, Any], str | None] | None = None  # (connection, مقدار خام) ← کد وضعیت (مثلاً status_id)
    company_id: Callable[[Any, Any], int | None] | None = None  # (connection, ردیف) ← شرکت؛ پیش‌فرض ستون company_id
    actor: Callable[[Any], int | None] | None = None
    created: bool = True
    entity_id: Callable[[Any], int | None] | None = None  # پیش‌فرض کلید همان ردیف
    gate_exempt: Callable[[Any, str | None], bool] | None = None  # (ردیف، وضعیت قبلی) ← آزاد؟ مثلاً فروش فروشگاهی


_WATCHES: dict[type, list[Watch]] = {}
_GATES: dict[str, tuple[str, ...]] = {}  # نوع سند ← وضعیت‌هایی که دروازه از آن‌ها محافظت می‌کند
_FORM_GATES: dict[str, tuple[str, ...]] = {}  # فقط پیش‌بررسی فرم (عملیات چندمرحله‌ای که نباید نیمه‌کاره بماند)
_STATE = threading.local()


def watch(w: Watch) -> None:
    _WATCHES.setdefault(w.model, []).append(w)


def gate_statuses(entity_type: str, statuses: tuple[str, ...], form_statuses: tuple[str, ...] = ()) -> None:
    if statuses:
        _GATES[entity_type] = tuple(statuses)
    if form_statuses:
        _FORM_GATES[entity_type] = tuple(form_statuses)


def gated(entity_type: str | None) -> tuple[str, ...]:
    return _GATES.get(entity_type or "", ())


def all_gated(entity_type: str | None) -> tuple[str, ...]:
    return gated(entity_type) + _FORM_GATES.get(entity_type or "", ())


@contextmanager
def acting(instance_id: int | None, depth: int = 0):
    """اقدام خودکار موتور در حال اجراست: دروازه باز است و رویدادهای حاصل «علت» دارند (محافظت از حلقه)."""
    previous = getattr(_STATE, "acting", None)
    _STATE.acting = (instance_id, depth)
    try:
        yield
    finally:
        _STATE.acting = previous


def _acting():
    return getattr(_STATE, "acting", None)


@contextmanager
def ungated():
    """عملیاتی که هرگز نباید با دروازه متوقف شود (مثلاً فروش واقعی موبایل که کالایش تحویل شده)."""
    previous = getattr(_STATE, "ungated", False)
    _STATE.ungated = True
    try:
        yield
    finally:
        _STATE.ungated = previous


def _ensure_loaded() -> None:
    from peecha.services.workflow import registry

    if not registry._LOADED:
        registry.ensure_loaded()


def _pk(obj) -> int | None:
    """کلید ردیف (برای ردیف تازه هم پس از INSERT در دسترس است)."""
    try:
        values = inspect(obj).mapper.primary_key_from_instance(obj)
    except Exception:  # noqa: BLE001
        return None
    return values[0] if values and values[0] is not None else None


def _company(conn, w: Watch, obj) -> int | None:
    if w.company_id is not None:
        return w.company_id(conn, obj)
    return getattr(obj, "company_id", None)


def _entity_id(w: Watch, obj) -> int | None:
    return w.entity_id(obj) if w.entity_id is not None else _pk(obj)


def _status(conn, w: Watch, value) -> str | None:
    if value is None:
        return None
    return w.status_code(conn, value) if w.status_code else str(value)


def _transitions(session, conn, include_new: bool = True):
    """(watch، ردیف، نوع سند، شرکت، وضعیت قبلی، وضعیت تازه، تازه‌ساخته؟) برای ردیف‌های تحت‌نظر."""
    out = []
    for obj in list(session.new) if include_new else []:
        for w in _WATCHES.get(type(obj), ()):
            et = w.entity_type(obj)
            if et:
                new = _status(conn, w, getattr(obj, w.status_attr, None)) if w.status_attr else None
                out.append((w, obj, et, None, new, True))
    for obj in list(session.dirty):
        for w in _WATCHES.get(type(obj), ()):
            if not w.status_attr:
                continue
            hist = inspect(obj).attrs[w.status_attr].history
            if not hist.added:
                continue
            et = w.entity_type(obj)
            if not et:
                continue
            old = _status(conn, w, hist.deleted[0]) if hist.deleted else None
            new = _status(conn, w, hist.added[0])
            if old != new:
                out.append((w, obj, et, old, new, False))
    return out


# --- دروازهٔ تایید ----------------------------------------------------------------------------------------------
def gate_definitions(conn, company_id: int, entity_type: str) -> list[tuple[int, int]]:
    """(تعریف، نسخه) فرایندهای فعال «با دروازه» برای این نوع سند."""
    return [(r[0], r[1]) for r in conn.execute(text(
        "SELECT DISTINCT t.definition_id, t.version_id FROM wf.definition_triggers t "
        "JOIN wf.definitions d ON d.definition_id = t.definition_id "
        "WHERE t.company_id = :c AND t.entity_type = :et AND t.is_active AND (t.config ->> 'gate') = 'true' "
        "AND d.status_code IN ('PUBLISHED', 'ACTIVE') AND t.version_id = d.active_version_id"),
        {"c": company_id, "et": entity_type})]


def _conditions_match(conn, company_id: int, entity_type: str, versions: list[tuple[int, int]], context: dict | None,
                      entity_id: int | None) -> bool:
    """دروازه فقط وقتی بسته است که شرط شروع یکی از همین فرایندها با سند جور باشد (مثلاً مبلغ بالای سقف)."""
    from peecha.services.workflow import conditions, runtime

    ctx = context
    for _definition_id, version_id in versions:
        graph = conn.execute(text("SELECT graph FROM wf.definition_versions WHERE version_id = :v"), {"v": version_id}).scalar()
        condition = ((graph or {}).get("trigger") or {}).get("condition")
        if not condition:
            return True
        if ctx is None:
            try:
                ctx = runtime.load_context(company_id, entity_type, entity_id)
            except Exception:  # noqa: BLE001 -- اطلاعات ناقص سند نباید کار کاربر را متوقف کند
                ctx = {}
        try:
            if conditions.evaluate(condition, ctx):
                return True
        except Exception:  # noqa: BLE001
            continue
    return False


def governed(company_id: int, entity_type: str, context: dict) -> bool:
    """آیا برای این درخواست (با این اطلاعات) فرایند فعالی هست؟ -- برای ماژول‌هایی که خودشان «درخواست» می‌سازند."""
    from peecha.db.base import new_session

    with new_session() as session:
        conn = session.connection()
        versions = [(r[0], r[1]) for r in conn.execute(text(
            "SELECT DISTINCT t.definition_id, t.version_id FROM wf.definition_triggers t "
            "JOIN wf.definitions d ON d.definition_id = t.definition_id "
            "WHERE t.company_id = :c AND t.entity_type = :et AND t.is_active AND t.trigger_type = 'EVENT' "
            "AND d.status_code IN ('PUBLISHED', 'ACTIVE') AND t.version_id = d.active_version_id"),
            {"c": company_id, "et": entity_type})]
        return bool(versions) and _conditions_match(conn, company_id, entity_type, versions, context, None)


def approved_by_workflow(conn, company_id: int, entity_type: str, entity_id: int | None) -> bool:
    if not entity_id:
        return False
    return conn.execute(text(
        "SELECT 1 FROM wf.instances WHERE company_id = :c AND entity_type = :et AND entity_id = :id "
        "AND status_code = 'COMPLETED' AND outcome_code = 'APPROVED' LIMIT 1"),
        {"c": company_id, "et": entity_type, "id": entity_id}).first() is not None


def gate_message(conn, company_id: int, entity_type: str, entity_id: int | None, context: dict | None = None) -> str | None:
    """متن دلیل بسته بودن دروازه برای همین سند (None یعنی آزاد)."""
    if not all_gated(entity_type):
        return None
    versions = gate_definitions(conn, company_id, entity_type)
    if not versions or approved_by_workflow(conn, company_id, entity_type, entity_id):
        return None
    running = entity_id and conn.execute(text(
        "SELECT 1 FROM wf.instances WHERE company_id = :c AND entity_type = :et AND entity_id = :id "
        "AND status_code IN ('RUNNING', 'WAITING') LIMIT 1"), {"c": company_id, "et": entity_type, "id": entity_id}).first()
    if running:
        return "این سند در جریان تایید است؛ پس از تایید نهایی در «مرکز تایید» خودکار انجام می‌شود."
    if not _conditions_match(conn, company_id, entity_type, versions, context, entity_id):
        return None
    return "این سند پیش از این مرحله باید تایید شود؛ ابتدا آن را «برای تایید بفرستید»."


def check(company_id: int, entity_type: str | None, entity_id: int | None, target_status: str | None = None,
          current_status: str | None = None) -> str | None:
    """پیش‌بررسی فرم‌ها پیش از اجرای عملیات چندمرحله‌ای (مثل ثبت نهایی) تا هیچ کاری نیمه‌تمام نماند.

    سندی که الان در یکی از وضعیت‌های محافظت‌شده است (مثلاً تصویب‌شده) پیش‌تر از دروازه گذشته و آزاد است."""
    if not entity_type or _acting() is not None:
        return None
    _ensure_loaded()
    statuses = all_gated(entity_type)
    if not statuses or (target_status and target_status not in statuses) or (current_status in statuses):
        return None
    from peecha.db.base import new_session

    with new_session() as session:
        return gate_message(session.connection(), company_id, entity_type, entity_id)


@sa_event.listens_for(Session, "before_flush")
def _gate(session, flush_context, instances) -> None:
    if not _WATCHES:
        _ensure_loaded()
    if not _GATES or _acting() is not None or getattr(_STATE, "ungated", False):
        return
    if not any(type(o) in _WATCHES for o in session.dirty):
        return
    conn = session.connection()
    for w, obj, et, old, new, _created in _transitions(session, conn, include_new=False):
        statuses = gated(et)
        # فقط ورود به اولین وضعیت حساس؛ سندی که پیش‌تر از دروازه گذشته (مثلاً تصویب‌شده ← ثبت نهایی) آزاد است
        if new not in statuses or old in statuses or (w.gate_exempt is not None and w.gate_exempt(obj, old)):
            continue
        cid = _company(conn, w, obj)
        message = gate_message(conn, cid, et, _entity_id(w, obj)) if cid else None
        if message:
            raise WorkflowError(message)


# --- انتشار رویداد -------------------------------------------------------------------------------------------
def _listened(session, conn, company_id: int, entity_type: str, event_type: str, entity_id: int) -> bool:
    cache = session.info.setdefault("wf_listen", {})  # در یک تراکنش (مثلاً ورود گروهی) هر پرسش یک‌بار
    key = (company_id, event_type)
    if key not in cache:
        cache[key] = conn.execute(text(
            "SELECT 1 FROM wf.definition_triggers WHERE company_id = :c AND event_type = :e AND is_active LIMIT 1"),
            {"c": company_id, "e": event_type}).first() is not None
    if cache[key]:
        return True
    waiting_key = (company_id, "*waiting*")
    if waiting_key not in cache:
        cache[waiting_key] = conn.execute(text(
            "SELECT 1 FROM wf.instances WHERE company_id = :c AND status_code = 'WAITING' LIMIT 1"), {"c": company_id}).first() is not None
    if not cache[waiting_key]:
        return False
    return conn.execute(text(
        "SELECT 1 FROM wf.instances WHERE company_id = :c AND entity_type = :et AND entity_id = :id AND status_code = 'WAITING' "
        "LIMIT 1"), {"c": company_id, "et": entity_type, "id": entity_id}).first() is not None


@sa_event.listens_for(Session, "after_flush")
def _publish(session, flush_context) -> None:
    if not _WATCHES:
        return
    if not any(type(o) in _WATCHES for o in list(session.new) + list(session.dirty)):
        return
    conn = session.connection()
    acting_ctx = _acting()
    for w, obj, et, old, new, created in _transitions(session, conn):
        entity_id = _entity_id(w, obj)
        cid = _company(conn, w, obj)
        if not entity_id or not cid:
            continue
        kinds = (["CREATED"] if created and w.created else []) + ([new] if new and (not created or new != "DRAFT") else [])
        for kind in kinds:
            event_type = f"{et}_{kind}"
            if not _listened(session, conn, cid, et, event_type, entity_id):
                continue
            stmt = insert(WfEvent).values(
                company_id=cid, event_type=event_type, entity_type=et, entity_id=entity_id,
                payload=plain({"from": old, "to": new}), actor_user_id=w.actor(obj) if w.actor else None,
                causation_instance_id=acting_ctx[0] if acting_ctx else None, depth=(acting_ctx[1] + 1) if acting_ctx else 0)
            conn.execute(stmt)
            session.info.setdefault("wf_companies", set()).add(cid)


@sa_event.listens_for(Session, "after_transaction_end")
def _forget(session, transaction) -> None:
    if transaction.parent is None:
        session.info.pop("wf_listen", None)
