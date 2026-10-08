"""ساخت فرایند بدون کدنویسی: ویزارد ← گراف، توضیح فارسی گراف، چیدمان خودکار و مقایسهٔ نسخه‌ها.

ویزارد فقط «گراف» تولید می‌کند (همان قالبی که طراح گرافیکی ویرایش می‌کند)؛ هیچ منطق اجرایی جدایی ندارد.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field

from peecha.services.workflow import conditions, definitions, registry, routing
from peecha.services.workflow.common import NODE_TYPES, OUTCOMES, WorkflowError

TRIGGER_LABELS = {"EVENT": "با رخ دادن یک رویداد", "MANUAL": "دستی (دکمهٔ «ارسال برای تایید» در سند)",
                  "SCHEDULE": "زمان‌بندی‌شده", "SCAN": "بررسی دوره‌ای"}
EVERY_LABELS = {"DAY": "هر روز", "WEEK": "هر هفته", "HOUR": "هر ساعت"}
MODE_LABELS = {"SINGLE": "یک نفر", "ANY": "اولین تصمیم کافی است", "ALL": "همه باید تایید کنند",
               "PERCENT": "درصدی از گیرندگان", "SEQUENTIAL": "به ترتیب، یکی پس از دیگری"}


@dataclass
class ApprovalLevel:
    label: str
    approvers: list[dict]
    mode: str = "ANY"
    percent: int | None = None
    sla_policy_id: int | None = None
    only_if: dict | None = None  # فقط وقتی این شرط برقرار است (مثلاً مبلغ بیش از ۵۰۰ میلیون)
    allow_changes: bool = False
    instructions: str = ""
    fallback: list[dict] | None = None  # اگر کسی پیدا نشد (مثلاً مدیر مستقیم تعریف نشده)


@dataclass
class WizardSpec:
    name: str
    code: str
    entity_type: str | None
    description: str = ""
    trigger: dict = field(default_factory=lambda: {"type": "MANUAL"})
    start_condition: dict | None = None
    levels: list[ApprovalLevel] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)  # کد اقدام‌ها پس از تایید نهایی (به ترتیب)
    notify_on_approve: bool = True
    notify_on_reject: bool = True
    notify_extra: list[dict] = field(default_factory=list)  # گیرندگان بیشتر خبر پایان
    reject_actions: list[str] = field(default_factory=list)  # اقدام‌ها پس از رد (مثلاً «رد درخواست» در خود سند)


def build_graph(spec: WizardSpec) -> dict:
    """گراف خطی: [شرط؟ ← تایید]... ← اقدام‌ها ← اعلان ← پایان؛ رد ← اعلان ← پایان «رد»؛ اصلاح ← کار درخواست‌کننده ← همان تایید."""
    if not spec.levels and not spec.actions:
        raise WorkflowError("دست‌کم یک مرحلهٔ تایید یا یک اقدام لازم است.")
    trigger = copy.deepcopy(spec.trigger or {"type": "MANUAL"})
    if spec.start_condition:
        trigger["condition"] = copy.deepcopy(spec.start_condition)
    nodes: list[dict] = []
    edges: list[dict] = []
    tail: list[tuple[str, str | None]] = [(definitions.START, None)]  # (گره، برچسب مسیر) منتظر اتصال به گرهٔ بعد

    def attach(target: str) -> None:
        for src, when in tail:
            edges.append({"from": src, "to": target, **({"when": when} if when else {})})
        tail.clear()

    reject_needed = False
    reject_target = "rja1" if spec.reject_actions else ("rej_note" if spec.notify_on_reject else "end_no")
    for i, level in enumerate(spec.levels, start=1):
        if not level.approvers:
            raise WorkflowError(f"برای مرحلهٔ «{level.label or i}» تاییدکننده تعیین نشده است.")
        ap = f"ap{i}"
        if level.only_if:
            cond = f"c{i}"
            nodes.append({"id": cond, "type": "CONDITION", "label": f"نیاز به «{level.label}»؟", "rule": copy.deepcopy(level.only_if)})
            attach(cond)
            edges.append({"from": cond, "to": ap, "when": "yes"})
            skip = [(cond, "no")]
        else:
            attach(ap)
            skip = []
        node = {"id": ap, "type": "APPROVAL", "label": level.label or f"تایید مرحلهٔ {i}", "approvers": copy.deepcopy(level.approvers),
                "mode": level.mode or "ANY"}
        if level.mode == "PERCENT":
            node["percent"] = int(level.percent or 50)
        if level.sla_policy_id:
            node["sla_policy_id"] = int(level.sla_policy_id)
        if level.instructions:
            node["instructions"] = level.instructions
        if level.fallback:
            node["fallback"] = copy.deepcopy(level.fallback)
        nodes.append(node)
        edges.append({"from": ap, "to": reject_target, "when": "rejected"})
        reject_needed = True
        if level.allow_changes:
            fix = f"fix{i}"
            nodes.append({"id": fix, "type": "TASK", "label": f"اصلاح برای «{level.label}»", "assignees": [{"kind": "STARTER"}],
                          "instructions": "موارد خواسته‌شده را در سند اصلاح کنید و دوباره بفرستید.",
                          "fields": [{"key": "note", "label": "توضیح اصلاحات", "kind": "text", "required": True}]})
            edges.append({"from": ap, "to": fix, "when": "changes"})
            edges.append({"from": fix, "to": ap, "when": "done"})
        tail[:] = [(ap, "approved")] + skip
    for j, code in enumerate(spec.actions, start=1):
        action = registry.find_action(spec.entity_type, code)
        if action is None:
            raise WorkflowError(f"اقدام «{code}» شناخته نشده است.")
        aid = f"act{j}"
        nodes.append({"id": aid, "type": "ACTION", "label": action.label, "action": code, "retry": {"max": 3, "backoff_minutes": 5}})
        attach(aid)
        tail[:] = [(aid, None)]
    if spec.notify_on_approve or spec.notify_extra:
        to = ([{"kind": "STARTER"}] if spec.notify_on_approve else []) + copy.deepcopy(spec.notify_extra)
        nodes.append({"id": "ok_note", "type": "NOTIFY", "label": "خبر تایید", "to": to, "title": "«{عنوان}» تایید شد"})
        attach("ok_note")
        tail[:] = [("ok_note", None)]
    nodes.append({"id": "end_ok", "type": "END", "label": "تایید نهایی", "outcome": "APPROVED" if spec.levels else "DONE"})
    attach("end_ok")
    if reject_needed:
        after_reject = "rej_note" if spec.notify_on_reject else "end_no"
        for k, code in enumerate(spec.reject_actions, start=1):
            action = registry.find_action(spec.entity_type, code)
            if action is None:
                raise WorkflowError(f"اقدام «{code}» شناخته نشده است.")
            nodes.append({"id": f"rja{k}", "type": "ACTION", "label": action.label, "action": code,
                          "retry": {"max": 3, "backoff_minutes": 5}})
            edges.append({"from": f"rja{k}", "to": f"rja{k + 1}" if k < len(spec.reject_actions) else after_reject})
        if spec.notify_on_reject:
            nodes.append({"id": "rej_note", "type": "NOTIFY", "label": "خبر رد", "to": [{"kind": "STARTER"}],
                          "title": "«{عنوان}» رد شد"})
            edges.append({"from": "rej_note", "to": "end_no"})
        nodes.append({"id": "end_no", "type": "END", "label": "رد", "outcome": "REJECTED"})
    return auto_layout({"trigger": trigger, "nodes": nodes, "edges": edges,
                        "settings": {"allow_self_approval": False, "max_steps": 200}})


def auto_layout(graph: dict, dx: int = 230, dy: int = 120) -> dict:
    """لایه‌بندی از بالا به پایین بر اساس فاصله از «شروع» (یال برگشتی نادیده)."""
    g = copy.deepcopy(graph)
    ids = [definitions.START] + [n["id"] for n in g.get("nodes", [])]
    depth = {definitions.START: 0}
    queue = [definitions.START]
    while queue:
        nid = queue.pop(0)
        for e in definitions.outgoing(g, nid):
            if e["to"] not in depth:
                depth[e["to"]] = depth[nid] + 1
                queue.append(e["to"])
    max_depth = max(depth.values(), default=0)
    for nid in ids:
        depth.setdefault(nid, max_depth + 1)
    columns: dict[int, int] = {}
    for n in g.get("nodes", []):
        level = depth[n["id"]]
        col = columns.get(level, 0)
        columns[level] = col + 1
        n["pos"] = [col * dx, level * dy]
    g.setdefault("layout", {})["start"] = [0, 0]
    return g


def _approvers_text(company_id: int | None, specs: list[dict]) -> str:
    if not specs:
        return "—"
    if company_id is None:
        return "، ".join(routing.KINDS.get(s.get("kind"), str(s.get("kind"))) for s in specs)
    from peecha.db.base import new_session
    from peecha.services.workflow.common import user_names

    with new_session() as session:
        roles = routing.role_names(session, [s.get("role_id") for s in specs])
        users = user_names(session, [s.get("user_id") for s in specs])
    return "، ".join(routing.describe_spec(s, roles, users) for s in specs)


def trigger_text(trigger: dict, entity_type: str | None) -> str:
    ttype = (trigger or {}).get("type") or "MANUAL"
    if ttype == "EVENT":
        events = dict(registry.event_choices(entity_type))
        names = "، ".join(events.get(e, e) for e in trigger.get("events") or []) or "—"
        return f"با رویداد: {names}"
    if ttype == "SCHEDULE":
        return f"زمان‌بندی‌شده: {EVERY_LABELS.get(trigger.get('every') or 'DAY', '')} ساعت {trigger.get('at') or '۰۰:۰۰'}"
    if ttype == "SCAN":
        scan = registry.scans().get(trigger.get("scan") or "")
        return f"بررسی دوره‌ای: {scan.label if scan else trigger.get('scan')}"
    return TRIGGER_LABELS["MANUAL"]


def describe_graph(graph: dict, entity_type: str | None, company_id: int | None = None) -> list[str]:
    """خلاصهٔ فارسی خوانا برای بازبینی پیش از انتشار."""
    adapter = registry.get_adapter(entity_type)
    labels = adapter.labels() if adapter else {}
    trigger = graph.get("trigger") or {}
    lines = [f"شروع: {trigger_text(trigger, entity_type)}"]
    if trigger.get("condition"):
        lines.append(f"شرط شروع: {conditions.describe(trigger['condition'], labels)}")
    for n in graph.get("nodes", []):
        t, label = n.get("type"), n.get("label") or NODE_TYPES.get(n.get("type"), "")
        if t == "APPROVAL":
            extra = f" — {MODE_LABELS.get(n.get('mode') or 'ANY', '')}"
            if n.get("mode") == "PERCENT":
                extra += f" ({n.get('percent')}٪)"
            lines.append(f"تایید «{label}»: {_approvers_text(company_id, n.get('approvers') or [])}{extra}")
        elif t == "TASK":
            lines.append(f"کار «{label}»: {_approvers_text(company_id, n.get('assignees') or [])}")
        elif t == "CONDITION":
            lines.append(f"شرط «{label}»: {conditions.describe(n.get('rule'), labels)}")
        elif t == "ACTION":
            spec = registry.find_action(entity_type, n.get("action") or "")
            lines.append(f"اقدام خودکار: {spec.label if spec else n.get('action')}")
        elif t == "NOTIFY":
            lines.append(f"اعلان به {_approvers_text(company_id, n.get('to') or [])}: {n.get('title') or ''}")
        elif t == "WAIT":
            lines.append(f"انتظار «{label}»")
        elif t == "END":
            lines.append(f"پایان «{label}» با نتیجهٔ {OUTCOMES.get(n.get('outcome') or 'DONE', '')}")
    return lines


def diff_graphs(old: dict, new: dict) -> list[str]:
    """تفاوت دو نسخه به زبان ساده (برای پیش از انتشار و تاریخچهٔ نسخه‌ها)."""
    a = definitions.nodes_by_id(old or {})
    b = definitions.nodes_by_id(new or {})
    out = []
    for nid in b.keys() - a.keys():
        out.append(f"مرحلهٔ تازه: «{b[nid].get('label') or NODE_TYPES.get(b[nid].get('type'), nid)}»")
    for nid in a.keys() - b.keys():
        out.append(f"مرحلهٔ حذف‌شده: «{a[nid].get('label') or NODE_TYPES.get(a[nid].get('type'), nid)}»")
    for nid in a.keys() & b.keys():
        x = {k: v for k, v in a[nid].items() if k != "pos"}
        y = {k: v for k, v in b[nid].items() if k != "pos"}
        if x != y:
            out.append(f"تغییر در «{b[nid].get('label') or nid}»")
    ea = {(e["from"], e["to"], e.get("when")) for e in (old or {}).get("edges", [])}
    eb = {(e["from"], e["to"], e.get("when")) for e in (new or {}).get("edges", [])}
    if ea != eb:
        out.append(f"مسیرها تغییر کرده‌اند ({len(eb - ea)} مسیر تازه، {len(ea - eb)} مسیر حذف‌شده)")
    if (old or {}).get("trigger") != (new or {}).get("trigger"):
        out.append("شرایط شروع تغییر کرده است")
    return out or ["تفاوتی نیست"]


# --- ویرایش گراف (برای طراح گرافیکی) ----------------------------------------------------------------------
NEW_NODE_DEFAULTS = {
    "CONDITION": {"label": "شرط تازه", "rule": {}},
    "APPROVAL": {"label": "تایید تازه", "approvers": [], "mode": "ANY"},
    "TASK": {"label": "کار تازه", "assignees": [], "fields": []},
    "ACTION": {"label": "اقدام خودکار", "action": ""},
    "NOTIFY": {"label": "اعلان", "to": [{"kind": "STARTER"}], "title": "{عنوان}"},
    "WAIT": {"label": "انتظار", "hours": 24},
    "PARALLEL": {"label": "انشعاب هم‌زمان"},
    "JOIN": {"label": "پیوستن شاخه‌ها"},
    "END": {"label": "پایان", "outcome": "DONE"},
}


def new_node_id(graph: dict, node_type: str) -> str:
    prefix = {"CONDITION": "c", "APPROVAL": "ap", "TASK": "t", "ACTION": "act", "NOTIFY": "n", "WAIT": "w",
              "PARALLEL": "p", "JOIN": "j", "END": "e"}.get(node_type, "x")
    existing = set(definitions.nodes_by_id(graph))
    i = 1
    while f"{prefix}{i}" in existing:
        i += 1
    return f"{prefix}{i}"


def add_node(graph: dict, node_type: str, pos: tuple[float, float] | None = None) -> str:
    if node_type not in NEW_NODE_DEFAULTS:
        raise WorkflowError("نوع مرحله نامعتبر است.")
    nid = new_node_id(graph, node_type)
    node = {"id": nid, "type": node_type, **copy.deepcopy(NEW_NODE_DEFAULTS[node_type])}
    if pos is not None:
        node["pos"] = [float(pos[0]), float(pos[1])]
    graph.setdefault("nodes", []).append(node)
    return nid


def remove_node(graph: dict, node_id: str) -> None:
    if node_id == definitions.START:
        raise WorkflowError("گرهٔ شروع حذف نمی‌شود.")
    graph["nodes"] = [n for n in graph.get("nodes", []) if n["id"] != node_id]
    graph["edges"] = [e for e in graph.get("edges", []) if node_id not in (e["from"], e["to"])]


def connect(graph: dict, src: str, dst: str, when: str | None = None) -> None:
    if src == dst:
        raise WorkflowError("مرحله نمی‌تواند به خودش وصل شود.")
    nodes = definitions.nodes_by_id(graph)
    if src != definitions.START and src not in nodes or dst not in nodes:
        raise WorkflowError("مرحلهٔ مبدأ یا مقصد پیدا نشد.")
    if nodes.get(src, {}).get("type") == "END":
        raise WorkflowError("از مرحلهٔ پایان نمی‌توان ادامه داد.")
    allowed = definitions.NODE_EDGE_LABELS.get(nodes.get(src, {}).get("type"))
    if allowed and when not in allowed and not (None in allowed and not when):
        raise WorkflowError("برای این مرحله، نتیجهٔ مسیر را انتخاب کنید.")
    edge = {"from": src, "to": dst, **({"when": when} if when else {})}
    if any(e["from"] == src and e.get("when") == (when or None) and nodes.get(src, {}).get("type") != "PARALLEL"
           for e in graph.get("edges", [])):
        graph["edges"] = [e for e in graph["edges"] if not (e["from"] == src and e.get("when") == (when or None))]
    graph.setdefault("edges", []).append(edge)


def edge_choices(graph: dict, src: str) -> list[tuple[str | None, str]]:
    """نتیجه‌های مجاز مسیر خروجی از یک مرحله."""
    t = (definitions.nodes_by_id(graph).get(src) or {}).get("type")
    allowed = definitions.NODE_EDGE_LABELS.get(t)
    if allowed:
        return list(allowed.items())
    return [(None, definitions.EDGE_LABELS[None])]
