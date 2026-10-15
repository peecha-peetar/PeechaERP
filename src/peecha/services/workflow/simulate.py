"""آزمون و اجرای آزمایشی (Test / Dry Run): نشان می‌دهد «چه اتفاقی می‌افتاد» بدون هیچ تغییری در دادهٔ عملیاتی.

دادهٔ آزمایشی (مثلاً مبلغ = ۷۵۰ میلیون) یا یک سند واقعی (فقط خواندن) ورودی است؛ تاییدها طبق «تصمیم‌های فرضی»
پیش می‌روند و اقدام‌ها فقط توصیف می‌شوند.
"""

from __future__ import annotations

from dataclasses import dataclass

from peecha.db.base import new_session
from peecha.services.workflow import conditions, definitions, registry, routing, runtime
from peecha.services.workflow.common import NODE_TYPES, OUTCOMES, user_names


@dataclass
class TraceRow:
    node_id: str
    node_type: str
    title: str
    result: str
    ok: bool


def simulate(company_id: int, graph: dict, entity_type: str | None, *, context: dict | None = None,
             entity_id: int | None = None, decisions: dict[str, str] | None = None, starter: int | None = None,
             max_steps: int = 200) -> list[TraceRow]:
    """decisions: {شناسهٔ گره تایید/کار: approved|rejected|changes|done}؛ پیش‌فرض «تایید شد»."""
    adapter = registry.get_adapter(entity_type)
    labels = adapter.labels() if adapter else {}
    ctx = dict(context or {})
    if entity_id and adapter:
        ctx = {**runtime.load_context(company_id, entity_type, entity_id), **ctx}
    decisions = decisions or {}
    trace: list[TraceRow] = []
    trigger = graph.get("trigger") or {}
    if trigger.get("condition"):
        ok = conditions.evaluate(trigger["condition"], ctx)
        trace.append(TraceRow("start", "START", "شرط شروع", conditions.describe(trigger["condition"], labels), ok))
        if not ok:
            trace.append(TraceRow("start", "END", "پایان", "فرایند برای این داده شروع نمی‌شود.", False))
            return trace
    else:
        trace.append(TraceRow("start", "START", "شروع", "فرایند شروع می‌شود.", True))
    queue = [definitions.START]
    joins: dict[str, int] = {}
    steps = 0
    while queue and steps < max_steps:
        steps += 1
        nid = queue.pop(0)
        node = runtime._node(graph, nid)
        if node is None:
            trace.append(TraceRow(nid, "?", "مرحلهٔ ناموجود", "مسیر به مرحله‌ای ناموجود می‌رسد.", False))
            break
        ntype, title = node.get("type"), node.get("label") or NODE_TYPES.get(node.get("type"), "")
        when = None
        if ntype == "CONDITION":
            ok = conditions.evaluate(node.get("rule"), ctx)
            when = "yes" if ok else "no"
            trace.append(TraceRow(nid, ntype, title, f"{conditions.describe(node.get('rule'), labels)} ← {'بله' if ok else 'خیر'}", True))
        elif ntype in ("APPROVAL", "TASK"):
            specs = node.get("approvers") or node.get("assignees") or []
            users = routing.resolve(company_id, specs, context=ctx, starter=starter, entity_type=entity_type, entity_id=entity_id)
            with new_session() as session:
                names = user_names(session, users)
                roles = routing.role_names(session, [s.get("role_id") for s in specs])
            who = "، ".join(names.get(u, str(u)) for u in users) or "، ".join(routing.describe_spec(s, roles) for s in specs)
            when = decisions.get(nid) or ("approved" if ntype == "APPROVAL" else "done")
            verdict = definitions.EDGE_LABELS.get(when, when)
            trace.append(TraceRow(nid, ntype, title, f"ارسال به: {who or '—'} ← {verdict} (فرضی)", bool(users)))
        elif ntype == "ACTION":
            spec = registry.find_action(entity_type, node.get("action") or "")
            trace.append(TraceRow(nid, ntype, title, f"اجرا می‌شد: {spec.label if spec else node.get('action')} (بدون تغییر واقعی)",
                                  spec is not None))
        elif ntype == "NOTIFY":
            users = routing.resolve(company_id, node.get("to") or [], context=ctx, starter=starter, entity_type=entity_type,
                                    entity_id=entity_id)
            trace.append(TraceRow(nid, ntype, title, f"اعلان به {len(users)} نفر: {node.get('title', '')}", True))
        elif ntype == "WAIT":
            trace.append(TraceRow(nid, ntype, title, "منتظر می‌ماند (در آزمون بلافاصله ادامه می‌یابد)", True))
        elif ntype == "JOIN":
            joins[nid] = joins.get(nid, 0) + 1
            if joins[nid] < len(definitions.incoming(graph, nid)):
                continue
            trace.append(TraceRow(nid, ntype, title, "همهٔ شاخه‌ها رسیدند", True))
        elif ntype == "END":
            trace.append(TraceRow(nid, ntype, title, f"پایان با نتیجهٔ «{OUTCOMES.get(node.get('outcome') or 'DONE')}»", True))
            continue
        elif ntype == "START":
            pass
        else:
            trace.append(TraceRow(nid, ntype or "?", title, "", True))
        edges = runtime._next_edges(graph, node, when)
        if not edges:
            trace.append(TraceRow(nid, ntype, title, "مسیر بعدی تعریف نشده است.", False))
            break
        queue += [e["to"] for e in edges]
    if steps >= max_steps:
        trace.append(TraceRow("", "END", "توقف", "تعداد مراحل از حد مجاز گذشت (احتمال حلقهٔ بی‌پایان).", False))
    return trace
