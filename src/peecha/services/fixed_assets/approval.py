"""تأییدِ عملیاتِ حساسِ دارایی با موتورِ کارتابلِ موجود -- R265.

هر عملیاتِ حساس (سرمایه‌ای‌شدن، تجدیدِ ارزیابی، کاهشِ ارزش، فروش، اسقاط/واگذاری، بهسازیِ بزرگ، انتقال) فرمِ دسترسیِ
خودش را دارد. اگر برایِ آن فرم گردشِ کارِ فعالی تعریف شده باشد، یک رویدادِ «در انتظارِ تأیید» با پارامترهایِ عملیات
ساخته و به کارتابل فرستاده می‌شود؛ پس از تأیید همان عملیات اجرا می‌شود. بدونِ گردشِ کار، عملیات مستقیم اجرا می‌شود.
"""

from __future__ import annotations

import datetime
import decimal

from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.fixed_assets import AssetEvent
from peecha.services import cartable
from peecha.services.fixed_assets import assets as fa
from peecha.services.fixed_assets import common as c
from peecha.services.fixed_assets import events as fe

# عملیات ← (فرمِ دسترسی/گردشِ کار، نوعِ رویداد، برچسب)
OPERATIONS = {
    "CAPITALIZE": ("fa_capitalize", "CAPITALIZATION", "سرمایه‌ای‌شدن"),
    "REVALUE": ("fa_revalue", "REVALUATION", "تجدیدِ ارزیابی"),
    "IMPAIR": ("fa_impair", "IMPAIRMENT", "کاهشِ ارزش"),
    "SELL": ("fa_sell", "SALE", "فروشِ دارایی"),
    "SCRAP": ("fa_scrap", "SCRAP", "اسقاط"),
    "DISPOSE": ("fa_dispose", "WRITE_OFF", "واگذاری"),
    "IMPROVE": ("fa_improve", "IMPROVEMENT", "بهسازیِ بزرگ"),
    "TRANSFER": ("fa_transfer", "TRANSFER", "انتقالِ دارایی"),
}
_DATE_KEYS = ("date", "in_service_date", "depreciation_start_date")


def _encode(params: dict) -> dict:
    out = {}
    for k, v in params.items():
        if isinstance(v, datetime.date):
            out[k] = {"__date__": v.isoformat()}
        elif isinstance(v, decimal.Decimal):
            out[k] = {"__dec__": str(v)}
        else:
            out[k] = v
    return out


def _decode(params: dict) -> dict:
    out = {}
    for k, v in params.items():
        if isinstance(v, dict) and "__date__" in v:
            out[k] = datetime.date.fromisoformat(v["__date__"])
        elif isinstance(v, dict) and "__dec__" in v:
            out[k] = decimal.Decimal(v["__dec__"])
        else:
            out[k] = v
    return out


def _execute(operation: str, company_id: int, user_id: int, asset_id: int, params: dict, approved_by: int | None):
    p = dict(params)
    if operation == "CAPITALIZE":
        return fa.capitalize(company_id, user_id, asset_id, **p)
    if operation == "REVALUE":
        return fe.revalue(company_id, user_id, asset_id, approved_by_user_id=approved_by, **p)
    if operation == "IMPAIR":
        return fe.impair(company_id, user_id, asset_id, approved_by_user_id=approved_by, **p)
    if operation == "SELL":
        return fe.sell(company_id, user_id, asset_id, approved_by_user_id=approved_by, **p)
    if operation == "SCRAP":
        return fe.scrap(company_id, user_id, asset_id, approved_by_user_id=approved_by, **p)
    if operation == "DISPOSE":
        return fe.dispose(company_id, user_id, asset_id, approved_by_user_id=approved_by, **p)
    if operation == "IMPROVE":
        return fe.improve(company_id, user_id, asset_id, **p)
    if operation == "TRANSFER":
        return fa.transfer(company_id, user_id, asset_id, **p)
    raise ValueError("عملیاتِ نامعتبر.")


def needs_approval(company_id: int, operation: str, amount: decimal.Decimal | None = None) -> bool:
    form = OPERATIONS[operation][0]
    if operation == "IMPROVE":
        threshold = c.get_settings(company_id).large_improvement_approval_min
        if threshold is None or (amount or 0) < threshold:
            return False
    return cartable.has_active_workflow(company_id, form)


def request(company_id: int, user_id: int, operation: str, asset_id: int, approval_amount: decimal.Decimal | None = None,
            **params):
    """اجرایِ عملیات؛ اگر گردشِ کارِ تأیید فعال باشد، فقط درخواست ثبت می‌شود و AssetEvent در انتظار برمی‌گردد."""
    if operation not in OPERATIONS:
        raise ValueError("عملیاتِ نامعتبر.")
    form, event_type, label = OPERATIONS[operation]
    amount = approval_amount if approval_amount is not None else params.get("amount") or params.get("price")
    if not needs_approval(company_id, operation, amount):
        return _execute(operation, company_id, user_id, asset_id, params, None)
    with new_session() as session:
        asset = c.lock_asset(session, asset_id, company_id)
        c.ensure_open(asset)
        pending = session.scalar(select(AssetEvent.event_id).where(AssetEvent.asset_id == asset_id,
                                                                  AssetEvent.status_code == "PENDING_APPROVAL"))
        if pending:
            raise ValueError("برایِ این دارایی یک درخواستِ دیگر در انتظارِ تأیید است.")
        ev = AssetEvent(company_id=company_id, asset_id=asset_id, event_type=event_type,
                        event_date=params.get("date") or datetime.date.today(), status_code="PENDING_APPROVAL",
                        amount=amount, reason=params.get("reason"), created_by_user_id=user_id,
                        details={"operation": operation, "params": _encode(params)})
        session.add(ev)
        session.flush()
        c.audit(session, company_id, user_id, asset_id, "REQUEST", {"operation": operation, "event_id": ev.event_id})
        session.commit()
        event_id = ev.event_id
    item = cartable.submit_for_approval(company_id, form, event_id, "CREATE", user_id, amount=amount)
    if item is None:  # گردشِ کار برایِ این مبلغ مرحله‌ای ندارد → اجرایِ مستقیم
        return _approve(company_id, event_id, user_id)
    with new_session() as session:
        ev = session.get(AssetEvent, event_id)
        session.expunge(ev)
        return ev


def _approve(company_id: int, event_id: int, approved_by_user_id: int):
    with new_session() as session:
        ev = session.scalar(select(AssetEvent).where(AssetEvent.event_id == event_id).with_for_update())
        if ev is None or ev.company_id != company_id or ev.status_code != "PENDING_APPROVAL":
            raise ValueError("درخواستِ تأیید نامعتبر است.")
        operation, params = ev.details["operation"], _decode(ev.details["params"])
        requester, asset_id = ev.created_by_user_id, ev.asset_id
    result = _execute(operation, company_id, requester, asset_id, params, approved_by_user_id)
    with new_session() as session:
        ev = session.get(AssetEvent, event_id)
        ev.status_code, ev.approved_by_user_id, ev.posted_at = "APPROVED", approved_by_user_id, datetime.datetime.now()
        ev.details = {**ev.details, "result_event_id": getattr(result, "event_id", result)}
        c.audit(session, company_id, approved_by_user_id, asset_id, "APPROVE", {"operation": operation, "event_id": event_id})
        session.commit()
    return result


def _reject(company_id: int, event_id: int, user_id: int, reason: str) -> None:
    with new_session() as session:
        ev = session.get(AssetEvent, event_id)
        if ev is None or ev.status_code != "PENDING_APPROVAL":
            return
        ev.status_code = "REJECTED"
        ev.details = {**ev.details, "rejected_reason": reason}
        c.audit(session, company_id, user_id, ev.asset_id, "REJECT", {"event_id": event_id, "reason": reason})
        session.commit()


def _describe(company_id: int, event_id: int) -> str:
    with new_session() as session:
        ev = session.get(AssetEvent, event_id)
        if ev is None:
            return f"دارایی #{event_id}"
        asset = session.get(c.Asset, ev.asset_id)
        label = OPERATIONS.get((ev.details or {}).get("operation"), ("", "", "عملیاتِ دارایی"))[2]
        return f"{label} -- {asset.asset_code} {asset.name}"


def pending(company_id: int) -> list[AssetEvent]:
    with new_session() as session:
        rows = list(session.scalars(select(AssetEvent).where(AssetEvent.company_id == company_id,
                                                             AssetEvent.status_code == "PENDING_APPROVAL")
                                    .order_by(AssetEvent.created_at)))
        for r in rows:
            session.expunge(r)
        return rows


def register_handlers() -> None:
    for form, _type, _label in OPERATIONS.values():
        cartable.register_handler(form, on_approved=lambda cid, rid, uid: _approve(cid, rid, uid),
                                  on_rejected=lambda cid, rid, uid, reason: _reject(cid, rid, uid, reason),
                                  describe=_describe)


register_handlers()
