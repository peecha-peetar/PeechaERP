"""بودجه (R313): نسخهٔ بودجه و مجوز تجاوز از بودجه در موتور گردش کار.

اگر برای «نسخهٔ بودجه» فرایند فعال «با دروازه» منتشر شود، ورود نسخه به «تأییدشده» فقط از مسیر همان فرایند ممکن است؛
تأیید و رد با همان توابع سرویس بودجه انجام می‌شود و تفویض اختیار و منع خودتاییدی موتور هم اعمال می‌شود.
"""

from __future__ import annotations

from peecha.db.base import new_session
from peecha.db.models.budgeting import Budget, BudgetException, BudgetVersion
from peecha.services.workflow import model_events, registry
from peecha.services.workflow.adapters._common import jdate, money, user_name
from peecha.services.workflow.common import WorkflowError
from peecha.services.workflow.model_events import Watch
from peecha.services.workflow.registry import ActionContext, ActionSpec, EntityAdapter, FieldSpec, ParamSpec

_KIND = {"ORIGINAL": "نسخهٔ اولیه", "AMENDMENT": "اصلاحیه", "SUPPLEMENT": "بودجهٔ تکمیلی"}
_STATUS = {"DRAFT": "پیش‌نویس", "SUBMITTED": "ارسال‌شده", "REVIEWED": "بررسی‌شده", "APPROVED": "تأییدشده",
           "PUBLISHED": "منتشرشده", "SUPERSEDED": "جایگزین‌شده", "REJECTED": "ردشده", "CANCELLED": "لغوشده"}


def version_context(company_id: int, version_id: int) -> dict:
    from peecha.services.budgeting import budgets as bud

    with new_session() as session:
        v = session.get(BudgetVersion, version_id)
        b = session.get(Budget, v.budget_id) if v is not None else None
        if v is None or b is None or b.company_id != company_id:
            raise WorkflowError("نسخهٔ بودجه پیدا نشد.")
        ns = bud.get_version(company_id, version_id)
        return {"version_id": v.version_id, "budget_code": b.code, "budget_name": b.name, "version_no": v.version_no,
                "kind": v.kind_code, "kind_label": _KIND[v.kind_code], "status": v.status_code, "total": ns.total_amount,
                "change": ns.total_amount - ns.total_previous if v.based_on_version_id else ns.total_amount,
                "line_count": len(ns.lines), "prepared_by": v.prepared_by_user_id,
                "prepared_by_name": user_name(session, v.prepared_by_user_id), "valid_from": v.valid_from, "valid_to": v.valid_to}


def _review_and_approve(ctx: ActionContext) -> dict:
    from peecha.services.budgeting import approval

    version_id = int(ctx.entity_id)
    with new_session() as session:
        status = session.get(BudgetVersion, version_id).status_code
    if status == "SUBMITTED":
        approval.review(ctx.company_id, ctx.user_id, version_id, "تأیید در گردش کار")
    approval.approve(ctx.company_id, ctx.user_id, version_id, ctx.context.get("last_comment") or "تأیید در گردش کار")
    return {"status": "APPROVED"}


def _reject_version(ctx: ActionContext) -> dict:
    from peecha.services.budgeting import approval

    reason = (ctx.params.get("reason") or ctx.context.get("last_comment") or "رد در گردش کار تأیید").strip()
    approval.reject(ctx.company_id, ctx.user_id, int(ctx.entity_id), reason)
    return {"status": "REJECTED"}


def _publish_version(ctx: ActionContext) -> dict:
    from peecha.services.budgeting import approval

    approval.publish(ctx.company_id, ctx.user_id, int(ctx.entity_id), "انتشار در گردش کار")
    return {"status": "PUBLISHED"}


def _version_in(*statuses: str):
    def check(company_id: int, version_id: int) -> bool:
        with new_session() as session:
            v = session.get(BudgetVersion, version_id)
            return v is not None and v.status_code in statuses
    return check


def _version_company(conn, v) -> int | None:
    from sqlalchemy import text

    return conn.execute(text("SELECT company_id FROM bud.budgets WHERE budget_id = :b"), {"b": v.budget_id}).scalar()


registry.register_adapter(EntityAdapter(
    "BUDGET_VERSION", "نسخهٔ بودجه", "BUDGET", version_context,
    fields=(FieldSpec("total", "جمع مبلغ نسخه", "money"), FieldSpec("change", "تغییر نسبت به نسخهٔ قبل", "money"),
            FieldSpec("kind", "نوع نسخه", "choice", _KIND), FieldSpec("prepared_by", "تهیه‌کننده", "user"),
            FieldSpec("line_count", "تعداد ردیف", "number")),
    events={f"BUDGET_VERSION_{k}": f"{v} «نسخهٔ بودجه»" for k, v in _STATUS.items()} | {"BUDGET_VERSION_CREATED": "ایجاد نسخهٔ بودجه"},
    actions={"approve": ActionSpec("approve", "بررسی و تأیید نسخهٔ بودجه", _review_and_approve, risk="HIGH",
                                   is_done=_version_in("APPROVED", "PUBLISHED")),
             "reject": ActionSpec("reject", "رد نسخهٔ بودجه", _reject_version, is_done=_version_in("REJECTED"),
                                  params=(ParamSpec("reason", "دلیل رد"),)),
             "publish": ActionSpec("publish", "انتشار نسخهٔ مصوب", _publish_version, risk="HIGH", is_done=_version_in("PUBLISHED"))},
    title=lambda c: f"{c.get('kind_label')} {c.get('version_no')} — {c.get('budget_name')}",
    owner=lambda cid, eid: version_context(cid, eid)["prepared_by"],
    approval_context=lambda cid, eid: (lambda c: [
        ("بودجه", f"{c['budget_code']} — {c['budget_name']}"), ("نسخه", f"{c['kind_label']} {c['version_no']}"),
        ("جمع مبلغ", money(c["total"])), ("تغییر", money(c["change"])), ("اعتبار", f"{jdate(c['valid_from'])} تا {jdate(c['valid_to'])}"),
        ("تهیه‌کننده", c["prepared_by_name"] or "—")])(version_context(cid, eid)),
    open_nav="BUD_BUDGETS", open_method="open_version", submitter_field="prepared_by", gate_statuses=("APPROVED",),
    gate_label="تا تأیید فرایند، نسخهٔ بودجه تأیید و منتشر نمی‌شود", form_code="bud_budgets"))

model_events.watch(Watch(BudgetVersion, lambda v: "BUDGET_VERSION", company_id=_version_company,
                         actor=lambda v: v.prepared_by_user_id))


def exception_context(company_id: int, exception_id: int) -> dict:
    from peecha.services.budgeting import common as c

    with new_session() as session:
        e = session.get(BudgetException, exception_id)
        if e is None or e.company_id != company_id:
            raise WorkflowError("درخواست مجوز بودجه پیدا نشد.")
        return {"exception_id": e.exception_id, "level": e.level_code, "level_label": c.EXCEPTION_LEVEL_LABELS[e.level_code],
                "excess": e.excess_amount, "source": c.SOURCE_LABELS.get(e.source_type, e.source_type), "source_no": e.source_no,
                "reason": e.reason or "", "status": e.status_code, "requested_by": e.requested_by_user_id,
                "requested_by_name": user_name(session, e.requested_by_user_id)}


def _approve_exception(ctx: ActionContext) -> dict:
    from peecha.services.budgeting import exceptions

    exceptions.decide(ctx.company_id, ctx.user_id, int(ctx.entity_id), True, ctx.context.get("last_comment") or "تأیید در گردش کار")
    return {"status": "APPROVED"}


def _reject_exception(ctx: ActionContext) -> dict:
    from peecha.services.budgeting import exceptions

    reason = (ctx.params.get("reason") or ctx.context.get("last_comment") or "رد در گردش کار").strip()
    exceptions.decide(ctx.company_id, ctx.user_id, int(ctx.entity_id), False, reason)
    return {"status": "REJECTED"}


def _exception_in(*statuses: str):
    def check(company_id: int, exception_id: int) -> bool:
        with new_session() as session:
            e = session.get(BudgetException, exception_id)
            return e is not None and e.status_code in statuses
    return check


registry.register_adapter(EntityAdapter(
    "BUDGET_EXCEPTION", "مجوز تجاوز از بودجه", "BUDGET", exception_context,
    fields=(FieldSpec("excess", "مبلغ تجاوز", "money"),
            FieldSpec("level", "نوع مجوز", "choice", {"APPROVAL": "تجاوز (تأیید سطح بالاتر)", "BLOCK": "بودجهٔ مسدود",
                                                      "CLOSED": "دورهٔ بسته", "UNBUDGETED": "خارج از بودجه"}),
            FieldSpec("requested_by", "درخواست‌کننده", "user")),
    events={"BUDGET_EXCEPTION_CREATED": "درخواست مجوز تجاوز از بودجه"},
    actions={"approve": ActionSpec("approve", "تأیید مجوز", _approve_exception, risk="HIGH", is_done=_exception_in("APPROVED", "USED")),
             "reject": ActionSpec("reject", "رد مجوز", _reject_exception, is_done=_exception_in("REJECTED"),
                                  params=(ParamSpec("reason", "دلیل رد"),))},
    title=lambda c: f"{c.get('level_label')} — {c.get('source')} {c.get('source_no') or ''}",
    owner=lambda cid, eid: exception_context(cid, eid)["requested_by"],
    approval_context=lambda cid, eid: (lambda c: [
        ("سند", f"{c['source']} {c['source_no'] or ''}"), ("نوع", c["level_label"]), ("مبلغ تجاوز", money(c["excess"])),
        ("شرح", c["reason"] or "—"), ("درخواست‌کننده", c["requested_by_name"] or "—")])(exception_context(cid, eid)),
    open_nav="BUD_EXCEPTIONS", open_method="open_exception", submitter_field="requested_by", form_code="bud_exceptions"))

model_events.watch(Watch(BudgetException, lambda e: "BUDGET_EXCEPTION", actor=lambda e: e.requested_by_user_id))
