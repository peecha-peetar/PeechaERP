"""تعریف داده‌محور فرایند: چرخهٔ عمر، نسخهٔ تغییرناپذیر، اعتبارسنجی پیش از انتشار.

گراف هر نسخه:
    {"trigger": {"type": "EVENT"|"MANUAL"|"SCHEDULE"|"SCAN", "events": [...], "condition": قاعده, ...},
     "nodes": [{"id", "type", "label", ...تنظیمات گره}],
     "edges": [{"from", "to", "when"}],      # when: None|yes|no|approved|rejected|changes|done|timeout|failed
     "settings": {"allow_self_approval": False, "max_steps": 200}}
گره «start» ضمنی است. نسخهٔ منتشرشده هرگز ویرایش نمی‌شود؛ ویرایش یعنی نسخهٔ تازه و نمونه‌های در حال اجرا با نسخهٔ
خودشان ادامه می‌دهند.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass

from sqlalchemy import delete, func, select

from peecha.db.base import new_session
from peecha.db.models.security import Role, User
from peecha.db.models.workflow import WfDefinition, WfDefinitionTrigger, WfDefinitionVersion, WfInstance
from peecha.services.workflow import conditions, registry
from peecha.services.workflow.common import (
    DEFINITION_STATUS, NODE_TYPES, OPEN_INSTANCE_STATUSES, RUNNABLE_STATUSES, WorkflowError, audit, now,
)

START = "start"
NODE_EDGE_LABELS = {
    "CONDITION": {"yes": "بله", "no": "خیر"},
    "APPROVAL": {"approved": "تایید شد", "rejected": "رد شد", "changes": "نیاز به اصلاح", "timeout": "پایان مهلت"},
    "TASK": {"done": "انجام شد", "timeout": "پایان مهلت"},
    "WAIT": {None: "پس از انتظار", "timeout": "پایان مهلت"},
    "ACTION": {None: "پس از اجرا", "failed": "در صورت شکست"},
}
EDGE_LABELS = {None: "ادامه", "yes": "بله", "no": "خیر", "approved": "تایید شد", "rejected": "رد شد",
               "changes": "نیاز به اصلاح", "done": "انجام شد", "timeout": "پایان مهلت", "failed": "در صورت شکست"}
TRANSITIONS = {
    "DRAFT": {"TESTING", "PUBLISHED", "ARCHIVED"},
    "TESTING": {"DRAFT", "PUBLISHED", "ARCHIVED"},
    "PUBLISHED": {"ACTIVE", "PAUSED", "ARCHIVED"},
    "ACTIVE": {"PAUSED", "ARCHIVED"},
    "PAUSED": {"ACTIVE", "ARCHIVED"},
    "ARCHIVED": {"DRAFT"},
}
_HUMAN_OR_WAIT = {"APPROVAL", "TASK", "WAIT"}


@dataclass
class Issue:
    level: str  # error | warning
    message: str
    node_id: str | None = None


def empty_graph(trigger_type: str = "MANUAL") -> dict:
    return {"trigger": {"type": trigger_type, "events": []}, "nodes": [{"id": "end", "type": "END", "label": "پایان",
                                                                         "outcome": "DONE"}],
            "edges": [{"from": START, "to": "end"}], "settings": {"allow_self_approval": False, "max_steps": 200}}


def checksum(graph: dict) -> str:
    return hashlib.sha256(json.dumps(graph, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def nodes_by_id(graph: dict) -> dict[str, dict]:
    return {n["id"]: n for n in graph.get("nodes") or []}


def outgoing(graph: dict, node_id: str) -> list[dict]:
    return [e for e in graph.get("edges") or [] if e.get("from") == node_id]


def incoming(graph: dict, node_id: str) -> list[dict]:
    return [e for e in graph.get("edges") or [] if e.get("to") == node_id]


# --- اعتبارسنجی -----------------------------------------------------------------------------------------
def _node_name(node: dict) -> str:
    return node.get("label") or NODE_TYPES.get(node.get("type"), node.get("id"))


def _reachable(graph: dict) -> set[str]:
    seen, stack = set(), [START]
    while stack:
        nid = stack.pop()
        if nid in seen:
            continue
        seen.add(nid)
        stack += [e["to"] for e in outgoing(graph, nid)]
    return seen


def _cycles_without_pause(graph: dict) -> list[list[str]]:
    """حلقه‌ای که هیچ گره انسانی/انتظار ندارد = تکرار بی‌پایان."""
    nodes = nodes_by_id(graph)
    bad: list[list[str]] = []
    state: dict[str, int] = {}
    path: list[str] = []

    def visit(nid: str) -> None:
        state[nid] = 1
        path.append(nid)
        for e in outgoing(graph, nid):
            nxt = e["to"]
            if state.get(nxt) == 1:
                cycle = path[path.index(nxt):]
                if not any(nodes.get(c, {}).get("type") in _HUMAN_OR_WAIT for c in cycle):
                    bad.append(cycle)
            elif state.get(nxt) is None:
                visit(nxt)
        path.pop()
        state[nid] = 2

    visit(START)
    return bad


def _paths_have_approval_before(graph: dict, target: str) -> bool:
    """آیا در همهٔ مسیرهای start ← target یک گره تایید (با خروجی approved) وجود دارد؟"""
    nodes = nodes_by_id(graph)

    def dfs(nid: str, seen: frozenset) -> bool:
        if nid == target:
            return False  # به هدف رسیدیم بی‌آنکه تاییدی دیده شود
        node = nodes.get(nid, {})
        for e in outgoing(graph, nid):
            if e["to"] in seen:
                continue
            if node.get("type") == "APPROVAL" and e.get("when") == "approved":
                continue  # این شاخه پس از تایید است
            if not dfs(e["to"], seen | {e["to"]}):
                return False
        return True

    return dfs(START, frozenset({START}))


def validate_graph(company_id: int, graph: dict, entity_type: str | None) -> list[Issue]:
    issues: list[Issue] = []
    adapter = registry.get_adapter(entity_type)
    fields = adapter.field_map() if adapter else {}
    trigger = graph.get("trigger") or {}
    ttype = trigger.get("type")
    if ttype not in ("EVENT", "MANUAL", "SCHEDULE", "SCAN"):
        issues.append(Issue("error", "نحوهٔ شروع فرایند مشخص نشده است."))
    elif ttype == "EVENT" and not trigger.get("events"):
        issues.append(Issue("error", "رویداد شروع فرایند انتخاب نشده است."))
    elif ttype == "EVENT" and adapter is not None:
        known = dict(registry.event_choices(entity_type))
        for ev in trigger.get("events") or []:
            if ev not in known:
                issues.append(Issue("error", f"رویداد «{ev}» برای «{adapter.label}» تعریف نشده است."))
    elif ttype == "SCAN":
        scan = registry.scans().get(trigger.get("scan") or "")
        if scan is None:
            issues.append(Issue("error", "نوع بررسی دوره‌ای انتخاب نشده است."))
    elif ttype == "SCHEDULE" and trigger.get("every") not in ("HOUR", "DAY", "WEEK"):
        issues.append(Issue("error", "دورهٔ زمان‌بندی (ساعتی، روزانه یا هفتگی) انتخاب نشده است."))
    if ttype in ("EVENT", "MANUAL", "SCAN") and entity_type and adapter is None:
        issues.append(Issue("error", f"نوع سند «{entity_type}» برای گردش کار تعریف نشده است."))
    for msg in conditions.validate(trigger.get("condition"), fields if adapter else None):
        issues.append(Issue("error", f"شرط شروع: {msg}"))

    nodes = nodes_by_id(graph)
    if len(nodes) != len(graph.get("nodes") or []):
        issues.append(Issue("error", "شناسهٔ تکراری در مراحل فرایند وجود دارد."))
    if START in nodes:
        issues.append(Issue("error", "شناسهٔ «start» رزرو شده است."))
    for e in graph.get("edges") or []:
        if e.get("from") != START and e.get("from") not in nodes:
            issues.append(Issue("error", "اتصالی از مرحلهٔ ناموجود وجود دارد."))
        if e.get("to") not in nodes:
            issues.append(Issue("error", "اتصالی به مرحلهٔ ناموجود وجود دارد."))
    if not outgoing(graph, START):
        issues.append(Issue("error", "فرایند پس از شروع به هیچ مرحله‌ای وصل نیست."))
    if not any(n.get("type") == "END" for n in nodes.values()):
        issues.append(Issue("error", "فرایند مرحلهٔ پایان ندارد."))
    if not any(n.get("type") in ("APPROVAL", "TASK", "ACTION", "NOTIFY") for n in nodes.values()):
        issues.append(Issue("error", "فرایند هیچ کاری انجام نمی‌دهد (تایید، کار، اقدام یا اعلان ندارد)."))

    reachable = _reachable(graph)
    role_ids, user_ids = set(), set()
    for nid, node in nodes.items():
        ntype, name = node.get("type"), _node_name(node)
        if ntype not in NODE_TYPES or ntype == "START":
            issues.append(Issue("error", f"نوع مرحلهٔ «{name}» شناخته نشده است.", nid))
            continue
        if nid not in reachable:
            issues.append(Issue("error", f"مرحلهٔ «{name}» از شروع فرایند قابل دسترسی نیست.", nid))
        outs = outgoing(graph, nid)
        whens = {e.get("when") for e in outs}
        if ntype != "END" and not outs:
            issues.append(Issue("error", f"مرحلهٔ «{name}» به مرحلهٔ بعدی وصل نیست.", nid))
        if ntype == "END" and outs:
            issues.append(Issue("error", f"مرحلهٔ پایان «{name}» نباید ادامه داشته باشد.", nid))
        if ntype == "CONDITION":
            if not {"yes", "no"} <= whens:
                issues.append(Issue("error", f"شرط «{name}» باید هر دو مسیر «بله» و «خیر» را داشته باشد.", nid))
            if not node.get("rule"):
                issues.append(Issue("error", f"شرط «{name}» تعریف نشده است.", nid))
            for msg in conditions.validate(node.get("rule"), fields if adapter else None):
                issues.append(Issue("error", f"شرط «{name}»: {msg}", nid))
        elif ntype == "APPROVAL":
            if not node.get("approvers"):
                issues.append(Issue("error", f"برای «{name}» تاییدکننده‌ای تعیین نشده است.", nid))
            if not {"approved", "rejected"} <= whens:
                issues.append(Issue("error", f"«{name}» باید هر دو مسیر «تایید شد» و «رد شد» را داشته باشد.", nid))
            if node.get("mode") == "PERCENT" and not 0 < int(node.get("percent") or 0) <= 100:
                issues.append(Issue("error", f"درصد لازم برای «{name}» باید بین ۱ تا ۱۰۰ باشد.", nid))
            if (node.get("mode") or "ANY") not in ("SINGLE", "ANY", "ALL", "PERCENT", "SEQUENTIAL"):
                issues.append(Issue("error", f"شیوهٔ تایید «{name}» نامعتبر است.", nid))
            for a in node.get("approvers") or []:
                if a.get("kind") == "ROLE":
                    role_ids.add(a.get("role_id"))
                if a.get("kind") == "USER":
                    user_ids.add(a.get("user_id"))
                if a.get("kind") == "RESOLVER" and a.get("code") not in registry.resolvers():
                    issues.append(Issue("error", f"مسیریاب «{a.get('code')}» برای «{name}» شناخته نشده است.", nid))
        elif ntype == "TASK":
            if not node.get("assignees"):
                issues.append(Issue("error", f"برای کار «{name}» مسئولی تعیین نشده است.", nid))
            if "done" not in whens and None not in whens:
                issues.append(Issue("error", f"کار «{name}» مسیر «انجام شد» ندارد.", nid))
            keys = [f.get("key") for f in node.get("fields") or []]
            if any(not k or not (f.get("label") or "").strip() for k, f in zip(keys, node.get("fields") or [])):
                issues.append(Issue("error", f"هر خانهٔ فرم کار «{name}» باید کلید و عنوان داشته باشد.", nid))
            if len(keys) != len(set(keys)):
                issues.append(Issue("error", f"کلید تکراری در فرم کار «{name}».", nid))
            for a in node.get("assignees") or []:
                if a.get("kind") == "ROLE":
                    role_ids.add(a.get("role_id"))
                if a.get("kind") == "USER":
                    user_ids.add(a.get("user_id"))
        elif ntype == "ACTION":
            spec = registry.find_action(entity_type, node.get("action") or "")
            if spec is None:
                issues.append(Issue("error", f"اقدام «{name}» شناخته نشده است.", nid))
            elif spec.risk == "HIGH" and not _paths_have_approval_before(graph, nid):
                issues.append(Issue("error", f"اقدام حساس «{name}» بدون تایید انسانی قبلی مجاز نیست.", nid))
            if spec is not None and node.get("action") == "emit_event" and \
                    (node.get("params") or {}).get("event") in set(trigger.get("events") or []):
                issues.append(Issue("error", f"«{name}» همان رویداد شروع این فرایند را منتشر می‌کند (وابستگی دوری).", nid))
        elif ntype == "NOTIFY":
            if not node.get("to"):
                issues.append(Issue("error", f"گیرندهٔ اعلان «{name}» تعیین نشده است.", nid))
            if not (node.get("title") or "").strip():
                issues.append(Issue("error", f"عنوان اعلان «{name}» خالی است.", nid))
            for a in node.get("to") or []:
                if a.get("kind") == "ROLE":
                    role_ids.add(a.get("role_id"))
                if a.get("kind") == "USER":
                    user_ids.add(a.get("user_id"))
        elif ntype == "WAIT":
            if not any(node.get(k) for k in ("hours", "minutes", "days", "until_field", "until_event")):
                issues.append(Issue("error", f"مدت یا شرط پایان انتظار «{name}» تعیین نشده است.", nid))
        elif ntype == "PARALLEL" and len(outs) < 2:
            issues.append(Issue("error", f"انشعاب «{name}» حداقل دو شاخه لازم دارد.", nid))
        elif ntype == "JOIN" and len(incoming(graph, nid)) < 2:
            issues.append(Issue("warning", f"«{name}» فقط یک شاخهٔ ورودی دارد.", nid))
        elif ntype == "END" and node.get("outcome", "DONE") not in ("APPROVED", "REJECTED", "DONE", "CANCELLED"):
            issues.append(Issue("error", f"نتیجهٔ پایان «{name}» نامعتبر است.", nid))

    for cycle in _cycles_without_pause(graph):
        names = " ← ".join(_node_name(nodes[c]) for c in cycle if c in nodes)
        issues.append(Issue("error", f"حلقهٔ بی‌پایان: {names}"))

    with new_session() as session:
        role_ids.discard(None)
        user_ids.discard(None)
        if role_ids:
            found = set(session.scalars(select(Role.role_id).where(Role.role_id.in_(role_ids), Role.company_id == company_id)))
            for rid in role_ids - found:
                issues.append(Issue("error", f"نقش شمارهٔ {rid} در این شرکت وجود ندارد."))
        if user_ids:
            found = set(session.scalars(select(User.user_id).where(User.user_id.in_(user_ids), User.is_active.is_(True))))
            for uid in user_ids - found:
                issues.append(Issue("error", f"کاربر شمارهٔ {uid} وجود ندارد یا غیرفعال است."))
    return issues


def errors(issues: list[Issue]) -> list[Issue]:
    return [i for i in issues if i.level == "error"]


# --- خواندن ---------------------------------------------------------------------------------------------
@dataclass
class DefinitionRow:
    definition_id: int
    code: str
    name: str
    description: str | None
    module_code: str | None
    entity_type: str | None
    category: str | None
    template_code: str | None
    status_code: str
    status_label: str
    active_version_id: int | None
    active_version_no: int | None
    latest_version_id: int
    latest_version_no: int
    has_draft: bool
    trigger_type: str | None
    running: int
    updated_at: object


def _row(session, d: WfDefinition) -> DefinitionRow:
    versions = list(session.scalars(select(WfDefinitionVersion).where(WfDefinitionVersion.definition_id == d.definition_id)
                                    .order_by(WfDefinitionVersion.version_no)))
    latest = versions[-1]
    active = next((v for v in versions if v.version_id == d.active_version_id), None)
    running = session.scalar(select(func.count()).select_from(WfInstance).where(
        WfInstance.definition_id == d.definition_id, WfInstance.status_code.in_(OPEN_INSTANCE_STATUSES)))
    graph = (active or latest).graph or {}
    return DefinitionRow(d.definition_id, d.code, d.name, d.description, d.module_code, d.entity_type, d.category,
                         d.template_code, d.status_code, DEFINITION_STATUS.get(d.status_code, d.status_code),
                         d.active_version_id, active.version_no if active else None, latest.version_id, latest.version_no,
                         latest.status_code == "DRAFT", (graph.get("trigger") or {}).get("type"), running or 0, d.updated_at)


def list_definitions(company_id: int, include_archived: bool = True, entity_type: str | None = None) -> list[DefinitionRow]:
    with new_session() as session:
        q = select(WfDefinition).where(WfDefinition.company_id == company_id)
        if not include_archived:
            q = q.where(WfDefinition.status_code != "ARCHIVED")
        if entity_type:
            q = q.where(WfDefinition.entity_type == entity_type)
        return [_row(session, d) for d in session.scalars(q.order_by(WfDefinition.name))]


def get_definition(company_id: int, definition_id: int) -> DefinitionRow:
    with new_session() as session:
        d = session.get(WfDefinition, definition_id)
        if d is None or d.company_id != company_id:
            raise WorkflowError("فرایند نامعتبر است.")
        return _row(session, d)


def get_graph(company_id: int, definition_id: int, version_id: int | None = None) -> dict:
    """گراف نسخهٔ خواسته‌شده؛ پیش‌فرض آخرین نسخه (پیش‌نویس جاری برای ویرایش)."""
    with new_session() as session:
        d = session.get(WfDefinition, definition_id)
        if d is None or d.company_id != company_id:
            raise WorkflowError("فرایند نامعتبر است.")
        q = select(WfDefinitionVersion).where(WfDefinitionVersion.definition_id == definition_id)
        v = session.scalar(q.where(WfDefinitionVersion.version_id == version_id)) if version_id else \
            session.scalar(q.order_by(WfDefinitionVersion.version_no.desc()))
        return copy.deepcopy(v.graph or {})


def list_versions(company_id: int, definition_id: int) -> list[WfDefinitionVersion]:
    with new_session() as session:
        d = session.get(WfDefinition, definition_id)
        if d is None or d.company_id != company_id:
            raise WorkflowError("فرایند نامعتبر است.")
        rows = list(session.scalars(select(WfDefinitionVersion).where(WfDefinitionVersion.definition_id == definition_id)
                                    .order_by(WfDefinitionVersion.version_no.desc())))
        session.expunge_all()
        return rows


# --- نوشتن ----------------------------------------------------------------------------------------------
def create_definition(company_id: int, user_id: int | None, *, code: str, name: str, entity_type: str | None = None,
                      module_code: str | None = None, description: str | None = None, category: str | None = None,
                      graph: dict | None = None, template_code: str | None = None) -> int:
    code, name = (code or "").strip().upper(), (name or "").strip()
    if not code or not name:
        raise WorkflowError("کد و نام فرایند الزامی است.")
    adapter = registry.get_adapter(entity_type) if entity_type else None
    if entity_type and adapter is None:
        raise WorkflowError(f"نوع سند «{entity_type}» برای گردش کار تعریف نشده است.")
    with new_session() as session:
        if session.scalar(select(WfDefinition.definition_id).where(WfDefinition.company_id == company_id,
                                                                   WfDefinition.code == code)):
            raise WorkflowError("کد فرایند تکراری است.")
        d = WfDefinition(company_id=company_id, code=code, name=name, description=description,
                         module_code=module_code or (adapter.module_code if adapter else None), entity_type=entity_type,
                         category=category, template_code=template_code, status_code="DRAFT",
                         created_by_user_id=user_id)
        session.add(d)
        session.flush()
        g = copy.deepcopy(graph) if graph else empty_graph()
        session.add(WfDefinitionVersion(definition_id=d.definition_id, version_no=1, graph=g, checksum=checksum(g),
                                        created_by_user_id=user_id))
        audit(session, company_id, user_id, "Definition", d.definition_id, "CREATE", {"code": code, "name": name})
        session.commit()
        return d.definition_id


def update_info(company_id: int, user_id: int | None, definition_id: int, *, name: str, description: str | None = None,
                category: str | None = None) -> None:
    with new_session() as session:
        d = _get(session, company_id, definition_id, lock=True)
        if not (name or "").strip():
            raise WorkflowError("نام فرایند الزامی است.")
        d.name, d.description, d.category, d.updated_at = name.strip(), description, category, now()
        audit(session, company_id, user_id, "Definition", definition_id, "UPDATE", {"name": name})
        session.commit()


def _get(session, company_id: int, definition_id: int, lock: bool = False) -> WfDefinition:
    q = select(WfDefinition).where(WfDefinition.definition_id == definition_id)
    d = session.scalar(q.with_for_update() if lock else q)
    if d is None or d.company_id != company_id:
        raise WorkflowError("فرایند نامعتبر است.")
    return d


def save_draft(company_id: int, user_id: int | None, definition_id: int, graph: dict, notes: str | None = None) -> int:
    """گراف در پیش‌نویس ذخیره می‌شود؛ اگر آخرین نسخه منتشر شده باشد، نسخهٔ تازه ساخته می‌شود."""
    with new_session() as session:
        d = _get(session, company_id, definition_id, lock=True)
        if d.status_code == "ARCHIVED":
            raise WorkflowError("فرایند بایگانی‌شده قابل ویرایش نیست؛ ابتدا آن را از بایگانی خارج کنید.")
        latest = session.scalar(select(WfDefinitionVersion).where(WfDefinitionVersion.definition_id == definition_id)
                                .order_by(WfDefinitionVersion.version_no.desc()))
        g = copy.deepcopy(graph)
        if latest.status_code != "DRAFT":
            latest = WfDefinitionVersion(definition_id=definition_id, version_no=latest.version_no + 1, created_by_user_id=user_id)
            session.add(latest)
        latest.graph, latest.checksum, latest.notes = g, checksum(g), notes
        d.updated_at = now()
        if d.status_code == "TESTING":
            d.status_code = "DRAFT"
        session.flush()
        audit(session, company_id, user_id, "Definition", definition_id, "UPDATE", {"version_no": latest.version_no})
        session.commit()
        return latest.version_id


def _sync_triggers(session, d: WfDefinition) -> None:
    session.execute(delete(WfDefinitionTrigger).where(WfDefinitionTrigger.definition_id == d.definition_id))
    if d.active_version_id is None:
        return
    v = session.get(WfDefinitionVersion, d.active_version_id)
    trigger = (v.graph or {}).get("trigger") or {}
    active = d.status_code in RUNNABLE_STATUSES
    ttype = trigger.get("type") or "MANUAL"
    gate = {"gate": True} if trigger.get("gate") else {}
    if ttype == "EVENT":
        for ev in trigger.get("events") or []:
            session.add(WfDefinitionTrigger(company_id=d.company_id, definition_id=d.definition_id, version_id=v.version_id,
                                            trigger_type="EVENT", event_type=ev, entity_type=d.entity_type,
                                            config=gate, is_active=active))
    elif ttype == "SCAN":
        session.add(WfDefinitionTrigger(company_id=d.company_id, definition_id=d.definition_id, version_id=v.version_id,
                                        trigger_type="SCAN", event_type=f"SCAN:{trigger.get('scan')}",
                                        entity_type=d.entity_type, config={k: trigger.get(k) for k in ("scan", "params", "every_minutes")},
                                        is_active=active))
    else:
        session.add(WfDefinitionTrigger(company_id=d.company_id, definition_id=d.definition_id, version_id=v.version_id,
                                        trigger_type=ttype, event_type=None, entity_type=d.entity_type,
                                        config={**{k: trigger.get(k) for k in ("every", "at", "weekday")}, **gate},
                                        is_active=active))


def set_status(company_id: int, user_id: int | None, definition_id: int, status_code: str) -> None:
    """چرخهٔ عمر: پیش‌نویس ← آزمون ← انتشار ← فعال ↔ توقف ← بایگانی."""
    if status_code == "PUBLISHED":
        publish(company_id, user_id, definition_id)
        return
    with new_session() as session:
        d = _get(session, company_id, definition_id, lock=True)
        if status_code not in TRANSITIONS.get(d.status_code, set()):
            raise WorkflowError(f"تغییر وضعیت از «{DEFINITION_STATUS[d.status_code]}» به «{DEFINITION_STATUS.get(status_code, status_code)}» مجاز نیست.")
        if status_code == "TESTING":
            latest = session.scalar(select(WfDefinitionVersion).where(WfDefinitionVersion.definition_id == definition_id)
                                    .order_by(WfDefinitionVersion.version_no.desc()))
            problems = errors(validate_graph(company_id, latest.graph or {}, d.entity_type))
            if problems:
                raise WorkflowError("پیش از آزمون این ایرادها را رفع کنید:\n" + "\n".join(f"• {p.message}" for p in problems))
        if status_code == "ACTIVE" and d.active_version_id is None:
            raise WorkflowError("فرایند هنوز منتشر نشده است.")
        d.status_code, d.updated_at = status_code, now()
        _sync_triggers(session, d)
        audit(session, company_id, user_id, "Definition", definition_id, "UPDATE", {"status": status_code})
        session.commit()
    if status_code in RUNNABLE_STATUSES:
        _after_runnable(company_id, user_id, definition_id)


# R300: کارهای پس از اجرایی شدن فرایند (مثل خاموش کردن کارتابل قبلی همان سند تا دو مسیر تایید هم‌زمان نباشد)
RUNNABLE_HOOKS: list = []


def _after_runnable(company_id: int, user_id: int | None, definition_id: int) -> None:
    for hook in RUNNABLE_HOOKS:
        hook(company_id, user_id, definition_id)


def publish(company_id: int, user_id: int | None, definition_id: int) -> int:
    """آخرین پیش‌نویس منتشر می‌شود (پس از اعتبارسنجی)؛ نسخهٔ قبلی برای نمونه‌های در حال اجرا باقی می‌ماند."""
    with new_session() as session:
        d = _get(session, company_id, definition_id, lock=True)
        if d.status_code == "ARCHIVED":
            raise WorkflowError("فرایند بایگانی‌شده قابل انتشار نیست.")
        latest = session.scalar(select(WfDefinitionVersion).where(WfDefinitionVersion.definition_id == definition_id)
                                .order_by(WfDefinitionVersion.version_no.desc()))
        if latest.status_code != "DRAFT":
            raise WorkflowError("تغییر تازه‌ای برای انتشار وجود ندارد.")
        problems = errors(validate_graph(company_id, latest.graph or {}, d.entity_type))
        if problems:
            raise WorkflowError("پیش از انتشار این ایرادها را رفع کنید:\n" + "\n".join(f"• {p.message}" for p in problems))
        for old in session.scalars(select(WfDefinitionVersion).where(WfDefinitionVersion.definition_id == definition_id,
                                                                     WfDefinitionVersion.status_code == "PUBLISHED")):
            old.status_code = "SUPERSEDED"
        latest.status_code, latest.published_by_user_id, latest.published_at = "PUBLISHED", user_id, now()
        latest.checksum = checksum(latest.graph or {})
        d.active_version_id = latest.version_id
        if d.status_code in ("DRAFT", "TESTING"):
            d.status_code = "PUBLISHED"
        d.updated_at = now()
        session.flush()
        _sync_triggers(session, d)
        audit(session, company_id, user_id, "Definition", definition_id, "PUBLISH", {"version_no": latest.version_no})
        runnable = d.status_code in RUNNABLE_STATUSES
        session.commit()
        version_id = latest.version_id
    if runnable:
        _after_runnable(company_id, user_id, definition_id)
    return version_id


def delete_definition(company_id: int, user_id: int | None, definition_id: int) -> None:
    with new_session() as session:
        d = _get(session, company_id, definition_id, lock=True)
        if session.scalar(select(func.count()).select_from(WfInstance).where(WfInstance.definition_id == definition_id)):
            raise WorkflowError("این فرایند سابقهٔ اجرا دارد و حذف نمی‌شود؛ می‌توانید آن را بایگانی کنید.")
        d.active_version_id = None
        session.flush()
        session.delete(d)
        audit(session, company_id, user_id, "Definition", definition_id, "DELETE", {"code": d.code})
        session.commit()


def duplicate(company_id: int, user_id: int | None, definition_id: int, code: str, name: str) -> int:
    src = get_definition(company_id, definition_id)
    return create_definition(company_id, user_id, code=code, name=name, entity_type=src.entity_type,
                             module_code=src.module_code, description=src.description, category=src.category,
                             graph=get_graph(company_id, definition_id))


def runnable_version(session, definition_id: int) -> WfDefinitionVersion | None:
    d = session.get(WfDefinition, definition_id)
    if d is None or d.status_code not in RUNNABLE_STATUSES or d.active_version_id is None:
        return None
    return session.get(WfDefinitionVersion, d.active_version_id)


def manual_definitions(company_id: int, entity_type: str) -> list[DefinitionRow]:
    """فرایندهای قابل «ارسال برای تایید» دستی از داخل سند."""
    return [d for d in list_definitions(company_id, include_archived=False, entity_type=entity_type)
            if d.status_code in RUNNABLE_STATUSES and d.trigger_type == "MANUAL"]
