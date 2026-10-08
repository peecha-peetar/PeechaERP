"""دارایی ثابت: درخواست عملیات حساس (فروش، اسقاط، تجدید ارزیابی، ...) که منتظر تایید است.

اگر برای «درخواست عملیات دارایی» فرایند فعالی باشد، همان رویداد «در انتظار تایید» ماژول دارایی ساخته می‌شود و
تایید یا رد آن با همان توابع تایید/رد ماژول انجام می‌شود (گردش کار کارتابل قدیمی هم مثل قبل کار می‌کند).
"""

from __future__ import annotations

import decimal

from peecha.db.base import new_session
from peecha.db.models.fixed_assets import AssetEvent
from peecha.services.workflow import model_events, registry
from peecha.services.workflow.adapters._common import jdate, money, user_name
from peecha.services.workflow.common import WorkflowError
from peecha.services.workflow.model_events import Watch
from peecha.services.workflow.registry import ActionContext, ActionSpec, EntityAdapter, FieldSpec, ParamSpec

OPERATION_LABELS = {"CAPITALIZE": "سرمایه‌ای‌شدن", "REVALUE": "تجدید ارزیابی", "IMPAIR": "کاهش ارزش", "SELL": "فروش دارایی",
                    "SCRAP": "اسقاط", "DISPOSE": "واگذاری", "IMPROVE": "بهسازی بزرگ", "TRANSFER": "انتقال دارایی"}


def request_context(company_id: int, event_id: int) -> dict:
    from peecha.db.models.fixed_assets import Asset

    with new_session() as session:
        ev = session.get(AssetEvent, event_id)
        if ev is None or ev.company_id != company_id:
            raise WorkflowError("درخواست دارایی پیدا نشد.")
        asset = session.get(Asset, ev.asset_id)
        operation = (ev.details or {}).get("operation") or ""
        return {"event_id": ev.event_id, "asset_id": ev.asset_id, "asset_code": getattr(asset, "asset_code", "") or "",
                "asset_name": getattr(asset, "name", "") or "", "operation": operation,
                "operation_label": OPERATION_LABELS.get(operation, operation), "amount": decimal.Decimal(ev.amount or 0),
                "event_date": ev.event_date, "reason": ev.reason or "", "status": ev.status_code,
                "requested_by": ev.created_by_user_id, "requested_by_name": user_name(session, ev.created_by_user_id)}


def _approve(ctx: ActionContext) -> dict:
    from peecha.services.fixed_assets import approval

    result = approval._approve(ctx.company_id, int(ctx.entity_id), ctx.user_id)
    return {"result_event_id": getattr(result, "event_id", None)}


def _reject(ctx: ActionContext) -> dict:
    from peecha.services.fixed_assets import approval

    reason = (ctx.params.get("reason") or ctx.context.get("last_comment") or "رد در گردش کار تایید").strip()
    approval._reject(ctx.company_id, int(ctx.entity_id), ctx.user_id, reason)
    return {"status": "REJECTED"}


def _status_in(*statuses: str):
    def check(company_id: int, event_id: int) -> bool:
        with new_session() as session:
            ev = session.get(AssetEvent, event_id)
            return ev is not None and ev.status_code in statuses
    return check


registry.register_adapter(EntityAdapter(
    "FA_REQUEST", "درخواست عملیات دارایی", "FIXED_ASSETS", request_context,
    fields=(FieldSpec("amount", "مبلغ", "money"), FieldSpec("operation", "عملیات", "choice", OPERATION_LABELS),
            FieldSpec("requested_by", "درخواست‌کننده", "user"), FieldSpec("asset_id", "دارایی", "number")),
    events={"FA_REQUEST_CREATED": "ثبت درخواست عملیات دارایی"},
    actions={"approve": ActionSpec("approve", "اجرای عملیات تاییدشده", _approve, risk="HIGH", is_done=_status_in("APPROVED")),
             "reject": ActionSpec("reject", "رد درخواست", _reject, is_done=_status_in("REJECTED"),
                                  params=(ParamSpec("reason", "دلیل رد"),))},
    title=lambda c: f"{c.get('operation_label')} — {c.get('asset_name')}",
    owner=lambda cid, eid: request_context(cid, eid)["requested_by"],
    approval_context=lambda cid, eid: (lambda c: [
        ("دارایی", f"{c['asset_code']} — {c['asset_name']}"), ("عملیات", c["operation_label"]), ("مبلغ", money(c["amount"])),
        ("تاریخ", jdate(c["event_date"])), ("دلیل", c["reason"] or "—"), ("درخواست‌کننده", c["requested_by_name"] or "—")])(
        request_context(cid, eid)),
    submitter_field="requested_by", form_code="fa_assets"))

model_events.watch(Watch(AssetEvent, lambda ev: "FA_REQUEST" if (ev.details or {}).get("operation") else None,
                         actor=lambda ev: ev.created_by_user_id))


def engine_governs(company_id: int, operation: str, amount, asset_id: int) -> bool:
    """فرایند فعال گردش کار برای این درخواست هست؟ (برای تصمیم ماژول دارایی که درخواست بسازد یا مستقیم اجرا کند)"""
    try:
        return model_events.governed(company_id, "FA_REQUEST", {"operation": operation, "amount": amount or 0,
                                                                "asset_id": asset_id})
    except Exception:  # noqa: BLE001 -- نبود جدول‌های گردش کار رفتار ماژول را عوض نمی‌کند
        return False
