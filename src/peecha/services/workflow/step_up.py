"""تشخیص کارهای حساس برای تایید دوباره با رمز در موبایل (R297).

حساس یعنی: طراح برای همان مرحله «تایید دوباره» را خواسته، یا مبلغ سند از سقف تنظیمات گردش کار
(mobile_step_up_amount) بیشتر است، یا تایید همین مرحله مستقیم به یک اقدام پرخطر (مثل تصویب سند یا دائم‌کردن
سند حسابداری) می‌رسد.
"""

from __future__ import annotations

import decimal

from peecha.db.base import new_session
from peecha.db.models.workflow import WfInstance, WfTask
from peecha.services.workflow import definitions, registry, runtime
from peecha.services.workflow.common import settings

_AMOUNT_KEYS = ("total_amount", "amount", "estimated_amount", "document_amount")


def _amount(context: dict) -> decimal.Decimal | None:
    for key in _AMOUNT_KEYS:
        value = context.get(key)
        if value not in (None, ""):
            try:
                return decimal.Decimal(str(value))
            except decimal.InvalidOperation:
                continue
    return None


def requires_step_up(company_id: int, task_id: int) -> bool:
    with new_session() as session:
        task = session.get(WfTask, task_id)
        if task is None or task.company_id != company_id or task.instance_id is None:
            return False
        inst = session.get(WfInstance, task.instance_id)
        graph = runtime._graph(session, inst.version_id)
        node = runtime._node(graph, task.node_id) or {}
        entity_type, entity_id = inst.entity_type, inst.entity_id
    if node.get("step_up"):
        return True
    threshold = settings(company_id).get("mobile_step_up_amount")
    if threshold not in (None, "", 0, "0") and entity_type and entity_id:
        try:
            amount = _amount(runtime.load_context(company_id, entity_type, entity_id))
            if amount is not None and amount >= decimal.Decimal(str(threshold)):
                return True
        except Exception:  # noqa: BLE001 -- خطای خواندن سند: احتیاط یعنی حساس
            return True
    for edge in definitions.outgoing(graph, task.node_id):
        if edge.get("when") not in ("approved", "done", None):
            continue
        nxt = runtime._node(graph, edge["to"]) or {}
        if nxt.get("type") == "ACTION":
            spec = registry.find_action(entity_type, nxt.get("action") or "")
            if spec is not None and spec.risk == "HIGH":
                return True
    return False
