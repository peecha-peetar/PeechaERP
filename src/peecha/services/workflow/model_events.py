"""رویدادهای خودکار از تغییر اسناد و «دروازهٔ تایید» — بدون یک خط تغییر در سرویس‌های کسب‌وکار.

هر ماژول با watch() می‌گوید کدام مدل، با کدام ستون وضعیت، به کدام نوع سند گردش کار تنظیم می‌شود. پس از هر flush:
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
_AFTER_GATE = ("CANCELLED", "REJECTED")


def trigger_reaches_gate(entity_type: str | None, trigger: dict | None) -> bool:
    """R329: آیا فرایند پیش از وضعیت قفل‌شده شروع می‌شود؟ فرایندی که فقط با خود «تصویب» (یا پس از آن) شروع شود هرگز
    پیش از تصویب اجرا نمی‌شود و قفلش سند را برای همیشه می‌بست."""
    trigger = trigger or {}
    if trigger.get("type") != "EVENT":
        return True
    blocked = set(all_gated(entity_type)) | set(_AFTER_GATE)
    prefix = f"{entity_type}_"
    return any(not ev.startswith(prefix) or ev[len(prefix):] not in blocked for ev in trigger.get("events") or [])


def start_event_hint(entity_type: str | None) -> str:
    """برچسب رویدادی که فرایند تایید باید با آن شروع شود (مثلاً «ارسال درخواست خرید»)."""
    from peecha.services.workflow import registry

    adapter = registry.get_adapter(entity_type)
    if adapter is None:
        return ""
    blocked = set(all_gated(entity_type)) | set(_AFTER_GATE) | {"CREATED", "DRAFT"}
    prefix = f"{entity_type}_"
    labels = [label for code, label in adapter.events.items() if code.startswith(prefix) and code[len(prefix):] not in blocked]
    return labels[0] if labels else next(iter(adapter.events.values()), "")


def unreachable_gate_text(entity_type: str | None) -> str:
    hint = start_event_hint(entity_type)
    return ("این فرایند پس از تایید شروع می‌شود، پس «قفل تایید» هرگز باز نمی‌شود؛ "
            + (f"رویداد شروع را «{hint}» بگذارید یا " if hint else "")
            + "تیک «قفل تایید» را بردارید.")


def _has_human_step(graph: dict) -> bool:
    return any(n.get("type") in ("APPROVAL", "TASK") for n in (graph or {}).get("nodes") or [])


def gate_definitions(conn, company_id: int, entity_type: str) -> list[tuple[int, int]]:
    """(تعریف، نسخه) فرایندهای فعال «با دروازه» برای این نوع سند.

    R329: فرایندی که هیچ‌وقت «تایید شد» تمام نمی‌شود، یا پس از تصویب شروع می‌شود و مرحلهٔ تایید ندارد (مثلاً فقط
    خبر)، جلوی سند را نمی‌گیرد؛ اگر مرحلهٔ تایید دارد، سند از وضعیت پیش از تصویب به آن فرستاده می‌شود (unsent_gate)."""
    out = []
    for definition_id, version_id in dict.fromkeys(tuple(r) for r in conn.execute(text(
            "SELECT t.definition_id, t.version_id FROM wf.definition_triggers t "
            "JOIN wf.definitions d ON d.definition_id = t.definition_id "
            "WHERE t.company_id = :c AND t.entity_type = :et AND t.is_active AND (t.config ->> 'gate') = 'true' "
            "AND d.status_code IN ('PUBLISHED', 'ACTIVE') AND t.version_id = d.active_version_id ORDER BY t.definition_id"),
            {"c": company_id, "et": entity_type})):
        graph = conn.execute(text("SELECT graph FROM wf.definition_versions WHERE version_id = :v"),
                             {"v": version_id}).scalar() or {}
        approves = any(n.get("type") == "END" and n.get("outcome") == "APPROVED" for n in graph.get("nodes") or [])
        if approves and (trigger_reaches_gate(entity_type, graph.get("trigger")) or _has_human_step(graph)):
            out.append((definition_id, version_id))
    return out


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
    if versions and not approved_by_workflow(conn, company_id, entity_type, entity_id):
        running = entity_id and conn.execute(text(
            "SELECT 1 FROM wf.instances WHERE company_id = :c AND entity_type = :et AND entity_id = :id "
            "AND status_code IN ('RUNNING', 'WAITING') LIMIT 1"), {"c": company_id, "et": entity_type, "id": entity_id}).first()
        if running:
            return _failed_text(conn, company_id, entity_type, entity_id) or \
                "این سند در جریان تایید است؛ پس از تایید نهایی خودکار انجام می‌شود."
        if _conditions_match(conn, company_id, entity_type, versions, context, entity_id):
            return "این سند باید تایید شود؛ اول آن را «برای تایید بفرستید»."
    return _busy_text(conn, company_id, entity_type, entity_id)


# --- R323: تا پایان گردش کار، سند دستی جلو نمی‌رود (حتی بدون «قفل تایید» در تعریف) -----------------------------
def _lock_while_running(conn, company_id: int) -> bool:
    from peecha.services.workflow.common import DEFAULT_SETTINGS

    options = conn.execute(text("SELECT options FROM wf.settings WHERE company_id = :c"), {"c": company_id}).scalar()
    return bool({**DEFAULT_SETTINGS, **(options or {})}.get("lock_while_running"))


def running_steps(conn, company_id: int, entity_type: str | None, entity_id: int | None) -> list[str] | None:
    """عنوان مراحل باز گردش کار در جریان که تایید یا کار انسانی دارد؛ None یعنی چنین گردش کاری در جریان نیست."""
    if not entity_type or not entity_id:
        return None
    rows = conn.execute(text(
        "SELECT i.instance_id, v.graph FROM wf.instances i JOIN wf.definition_versions v ON v.version_id = i.version_id "
        "WHERE i.company_id = :c AND i.entity_type = :et AND i.entity_id = :id AND i.status_code IN ('RUNNING', 'WAITING')"),
        {"c": company_id, "et": entity_type, "id": entity_id}).all()
    labels = {}
    for instance_id, graph in rows:
        nodes = (graph or {}).get("nodes") or []
        if any(n.get("type") in ("APPROVAL", "TASK") for n in nodes):
            labels[instance_id] = {n.get("id"): n.get("label") for n in nodes}
    if not labels:
        return None
    return [labels[i].get(node_id) or title for i, node_id, title in conn.execute(text(
        "SELECT instance_id, node_id, title FROM wf.tasks WHERE instance_id = ANY(:ids) AND status_code = 'OPEN' "
        "ORDER BY task_id"), {"ids": list(labels)})]


def _failed_text(conn, company_id: int, entity_type: str | None, entity_id: int | None) -> str | None:
    found = _failed_action(conn, company_id, entity_type, entity_id)
    return found[1] if found else None


def _failed_action(conn, company_id: int, entity_type: str | None, entity_id: int | None) -> tuple[int, str] | None:
    """R327: اقدام خودکار فرایند در جریان (مثلاً «تصویب درخواست خرید») شکست خورده و منتظر «اجرای دوباره» است:
    (شمارهٔ مورد بررسی، پیام)."""
    if not entity_type or not entity_id:
        return None
    for exception_id, node_id, reason, graph in conn.execute(text(
            "SELECT e.exception_id, e.node_id, e.reason, v.graph FROM wf.exceptions e JOIN wf.instances i ON i.instance_id = e.instance_id "
            "JOIN wf.definition_versions v ON v.version_id = i.version_id WHERE i.company_id = :c AND i.entity_type = :et "
            "AND i.entity_id = :id AND i.status_code IN ('RUNNING', 'WAITING') "
            "AND e.status_code IN ('OPEN', 'RETRYING', 'ESCALATED') ORDER BY e.exception_id DESC"),
            {"c": company_id, "et": entity_type, "id": entity_id}):
        node = next((n for n in (graph or {}).get("nodes") or [] if n.get("id") == node_id), None)
        if node is not None and node.get("type") == "ACTION":  # مرحلهٔ انسانی بی‌گیرنده پیام جدای خودش را دارد
            return exception_id, _failed_message(node.get("label"), reason)
    return None


def _failed_message(label: str | None, reason: str | None) -> str:
    reason = f" ({reason.strip().rstrip('.')})" if (reason or "").strip() else ""
    return f"«{label or 'اقدام خودکار'}» انجام نشد{reason}؛ مسئول فرایند آن را با «اجرای دوباره» در نوار گردش کار اجرا کند."


def failed(company_id: int, entity_type: str | None, entity_id: int | None) -> tuple[int, str] | None:
    from peecha.db.base import new_session

    if not entity_type or not entity_id:
        return None
    with new_session() as session:
        return _failed_action(session.connection(), company_id, entity_type, int(entity_id))


def unsent_gate(company_id: int, entity_type: str | None, entity_id: int | None) -> list[int]:
    """R327: فرایندهای «با دروازه» که این سند باید از آن‌ها بگذرد ولی فرایندی برایش در جریان نیست (پیش از تعریف فرایند
    ارسال شده، یا فرایند قبلی لغو/ناموفق شد)؛ «ارسال برای تایید» همین‌ها را شروع می‌کند."""
    if not entity_type or not entity_id:
        return []
    _ensure_loaded()
    if not all_gated(entity_type):
        return []
    from peecha.db.base import new_session

    with new_session() as session:
        conn = session.connection()
        versions = gate_definitions(conn, company_id, entity_type)
        if not versions or approved_by_workflow(conn, company_id, entity_type, entity_id) or conn.execute(text(
                "SELECT 1 FROM wf.instances WHERE company_id = :c AND entity_type = :et AND entity_id = :id "
                "AND status_code IN ('RUNNING', 'WAITING') LIMIT 1"),
                {"c": company_id, "et": entity_type, "id": entity_id}).first():
            return []
        from peecha.services.workflow import runtime

        try:
            status = runtime.load_context(company_id, entity_type, entity_id).get("status")
        except Exception:  # noqa: BLE001
            status = None
        if status in ("CANCELLED", "REJECTED") or status in all_gated(entity_type):
            return []
        out = []
        for d, v in versions:
            trigger = (conn.execute(text("SELECT graph FROM wf.definition_versions WHERE version_id = :v"),
                                    {"v": v}).scalar() or {}).get("trigger") or {}
            events = set(trigger.get("events") or [])
            # R328: فقط در همان وضعیتی که فرایند را شروع می‌کند (مثلاً «تاییدشده»، نه پیش‌نویس)؛ R329: فرایند تاییدی که
            # رویداد شروعش پس از تصویب است، از هر وضعیت پیش از تصویب (جز پیش‌نویس) فرستاده می‌شود
            if not trigger_reaches_gate(entity_type, trigger):
                if status in (None, "DRAFT"):
                    continue
            elif trigger.get("type") == "EVENT" and status and f"{entity_type}_{status}" not in events \
                    and f"{entity_type}_CREATED" not in events:
                continue
            if _conditions_match(conn, company_id, entity_type, [(d, v)], None, entity_id):
                out.append(d)
        return out


def _busy_text(conn, company_id: int, entity_type: str | None, entity_id: int | None) -> str | None:
    if not _lock_while_running(conn, company_id):
        return None
    steps = running_steps(conn, company_id, entity_type, entity_id)
    if steps is None:
        return None
    failure = _failed_text(conn, company_id, entity_type, entity_id)
    if failure:
        return failure
    stuck = conn.execute(text(
        "SELECT t.node_id FROM wf.tasks t JOIN wf.instances i ON i.instance_id = t.instance_id "
        "WHERE i.company_id = :c AND i.entity_type = :et AND i.entity_id = :id AND t.status_code = 'OPEN' "
        "AND NOT EXISTS (SELECT 1 FROM wf.task_assignees a WHERE a.task_id = t.task_id AND a.status_code IN ('ACTIVE', 'QUEUED')) "
        "LIMIT 1"), {"c": company_id, "et": entity_type, "id": entity_id}).first()
    if stuck:  # R325: کار بی‌گیرنده — بدون راهنما، سند بی‌صدا گیر می‌کرد
        name = f"«{steps[0]}» " if steps else ""
        return f"مرحلهٔ {name}گیرنده ندارد؛ مدیر آن را از نوار گردش کار به فرد مناسب ارجاع دهد."
    where = f" (مرحلهٔ «{'»، «'.join(steps[:3])}»)" if steps else ""
    return f"این سند در جریان تایید است{where}؛ تا پایان گردش کار این کار ممکن نیست."


def busy(company_id: int, entity_type: str | None, entity_id: int | None, user_id: int | None = None) -> str | None:
    """پیش از بردن سند به مرحلهٔ بعد (مثلاً تبدیل درخواست به سفارش یا رد دستی): None یعنی آزاد.

    R330: کسی که مرحلهٔ «انجام کار» همین سند (مثلاً «تبدیل به سفارش») منتظر اوست، همان کار را روی سند انجام می‌دهد."""
    if not entity_type or not entity_id or _acting() is not None or getattr(_STATE, "ungated", False):
        return None
    from peecha.db.base import new_session

    with new_session() as session:
        conn = session.connection()
        if user_id and conn.execute(text(
                "SELECT 1 FROM wf.tasks t JOIN wf.task_assignees a ON a.task_id = t.task_id "
                "WHERE t.company_id = :c AND t.entity_type = :et AND t.entity_id = :id AND t.status_code = 'OPEN' "
                "AND t.kind = 'TASK' AND a.user_id = :u AND a.status_code = 'ACTIVE' LIMIT 1"),
                {"c": company_id, "et": entity_type, "id": int(entity_id), "u": user_id}).first():
            return None
        return _busy_text(conn, company_id, entity_type, int(entity_id))


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
