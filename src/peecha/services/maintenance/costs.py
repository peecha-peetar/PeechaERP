"""هزینه‌های دستور کار (R312): خدمات پیمانکار و سایر هزینه‌ها، و خلاصهٔ هزینه.

منبع ثبت مالی هر نوع هزینه یکی است تا ثبت دوباره پیش نیاید:
- قطعه: سند انبار (parts.py)؛ این‌جا فقط خوانده می‌شود.
- نیروی کار داخلی: اطلاعاتی (حقوق در حقوق‌ودستمزد هزینه شده است).
- خدمات و سایر: یا به فاکتور خرید ثبت‌شده وصل می‌شود (بدون ثبت تازه، جمع اتصال‌ها حداکثر مبلغ فاکتور)، یا با همان
  fixed_assets.approval.request("IMPROVE") ثبت می‌شود (سیاست سرمایه‌ای‌کردن، تأیید مالی و کلید یکتایی موجود)،
  یا با علت «بدون ثبت مالی» علامت می‌خورد (مثلاً زیر پوشش ضمانت).
"""

from __future__ import annotations

import datetime
import decimal
from types import SimpleNamespace

from sqlalchemy import func, select

from peecha.db.base import new_session
from peecha.db.models.commercial import CommercialDocument
from peecha.db.models.fixed_assets import AssetEvent
from peecha.db.models.maintenance import WorkOrder, WorkOrderCost, WorkOrderLabor
from peecha.services.maintenance import common as c
from peecha.services.maintenance import work_orders as wos

_ACTIVE_WO = ("OPEN", "PLANNED", "ASSIGNED", "IN_PROGRESS", "ON_HOLD", "COMPLETED", "VERIFIED")


def _key(cost_id: int) -> str:
    return f"MNT-COST-{cost_id}"


def _lock_cost(session, company_id: int, cost_id: int) -> tuple[WorkOrderCost, WorkOrder]:
    cost = session.scalar(select(WorkOrderCost).where(WorkOrderCost.cost_id == cost_id).with_for_update())
    wo = session.get(WorkOrder, cost.work_order_id) if cost is not None else None
    if cost is None or wo is None or wo.company_id != company_id:
        raise ValueError("ردیف هزینه نامعتبر است.")
    return cost, wo


def add_cost(company_id: int, user_id: int, work_order_id: int, cost_type_code: str, description: str, amount,
             supplier_detail_account_id: int | None = None) -> int:
    if cost_type_code not in c.COST_TYPE_LABELS:
        raise ValueError("نوع هزینه نامعتبر است.")
    if not (description or "").strip():
        raise ValueError("شرح هزینه الزامی است.")
    amount = c.money(amount)
    if amount <= 0:
        raise ValueError("مبلغ باید مثبت باشد.")
    with new_session() as session:
        c.require(company_id, user_id, c.FORM_EXECUTE, session=session)
        wo = wos.lock(session, company_id, work_order_id)
        if wo.status_code not in _ACTIVE_WO:
            raise ValueError("دستور کار بسته یا لغوشده هزینهٔ جدید نمی‌پذیرد.")
        row = WorkOrderCost(work_order_id=work_order_id, cost_type_code=cost_type_code, description=description.strip()[:300],
                            supplier_detail_account_id=supplier_detail_account_id, amount=amount, accounting_code="PENDING",
                            status_code="DRAFT", created_by_user_id=user_id)
        session.add(row)
        session.flush()
        c.audit(session, company_id, user_id, wos.ENTITY, work_order_id, "COST_ADD",
                {"cost_id": row.cost_id, "type": cost_type_code, "amount": str(amount)})
        session.commit()
        return row.cost_id


def link_invoice(company_id: int, user_id: int, cost_id: int, commercial_document_id: int) -> None:
    """اتصال به فاکتور خرید ثبت‌شده — هزینه همان‌جا ثبت شده و این‌جا دوباره ثبت نمی‌شود."""
    with new_session() as session:
        c.require(company_id, user_id, c.FORM_COST, session=session)
        cost, wo = _lock_cost(session, company_id, cost_id)
        if cost.status_code != "DRAFT":
            raise ValueError(f"این هزینه در وضعیت «{c.COST_STATUS_LABELS[cost.status_code]}» است.")
        doc = session.scalar(select(CommercialDocument).where(CommercialDocument.document_id == commercial_document_id)
                             .with_for_update())
        if doc is None or doc.company_id != company_id or doc.document_type_code != "PURCHASE_INVOICE":
            raise ValueError("فقط به فاکتور خرید همین شرکت می‌توان وصل کرد.")
        if doc.status_code != "POSTED":
            raise ValueError("فاکتور خرید هنوز ثبت نهایی نشده است.")
        if cost.supplier_detail_account_id and doc.counterparty_detail_account_id != cost.supplier_detail_account_id:
            raise ValueError("تامین‌کنندهٔ فاکتور با تامین‌کنندهٔ این هزینه یکی نیست.")
        used = c.dec(session.scalar(select(func.coalesce(func.sum(WorkOrderCost.amount), 0)).where(
            WorkOrderCost.commercial_document_id == commercial_document_id, WorkOrderCost.status_code == "LINKED")))
        total = c.dec(doc.total_amount)
        if used + c.dec(cost.amount) > total:
            raise ValueError(f"جمع هزینه‌های متصل به این فاکتور از مبلغ فاکتور بیشتر می‌شود (باقی‌مانده {c.money(total - used)}).")
        cost.commercial_document_id, cost.accounting_code, cost.status_code = commercial_document_id, "INVOICE", "LINKED"
        cost.posted_by_user_id, cost.posted_at = user_id, c.now()
        cost.supplier_detail_account_id = cost.supplier_detail_account_id or doc.counterparty_detail_account_id
        session.flush()
        c.audit(session, company_id, user_id, wos.ENTITY, wo.work_order_id, "COST_LINK",
                {"cost_id": cost_id, "commercial_document_id": commercial_document_id, "amount": str(cost.amount)})
        session.commit()


def post(company_id: int, user_id: int, cost_id: int, offset_account_id: int, offset_detail_account_id: int | None = None,
         capital: bool | None = None, date: datetime.date | None = None) -> str:
    """ثبت مالی از مسیر دارایی (هزینهٔ تعمیر یا افزایش سرمایه‌ای طبق سیاست/انتخاب مالی). خروجی = وضعیت تازه.

    کلید یکتایی MNT-COST-<شناسه> تضمین می‌کند تکرار این اقدام سند دوم نمی‌سازد.
    """
    from peecha.services.fixed_assets import approval

    date = date or datetime.date.today()
    with new_session() as session:
        c.require(company_id, user_id, c.FORM_COST, session=session)
        cost, wo = _lock_cost(session, company_id, cost_id)
        if cost.status_code != "DRAFT":
            raise ValueError(f"این هزینه در وضعیت «{c.COST_STATUS_LABELS[cost.status_code]}» است.")
        if cost.accounting_code == "NONE":
            raise ValueError("این هزینه «بدون ثبت مالی» علامت خورده است.")
        asset_id, amount, desc, wo_no = wo.asset_id, c.dec(cost.amount), cost.description, wo.wo_no
    result = approval.request(company_id, user_id, "IMPROVE", asset_id, approval_amount=amount, date=date, amount=amount,
                              offset_account_id=offset_account_id, offset_detail_account_id=offset_detail_account_id,
                              description=f"دستور کار نگهداری {wo_no}: {desc}", capital=capital, idempotency_key=_key(cost_id))
    with new_session() as session:
        cost, wo = _lock_cost(session, company_id, cost_id)
        if result.status_code == "PENDING_APPROVAL":
            cost.status_code, cost.asset_event_id = "PENDING_APPROVAL", result.event_id
            cost.accounting_code = "CAPITALIZE" if capital else ("EXPENSE" if capital is False else "PENDING")
        else:
            _mark_posted(cost, result, user_id)
        session.flush()
        c.audit(session, company_id, user_id, wos.ENTITY, wo.work_order_id, "COST_POST",
                {"cost_id": cost_id, "asset_event_id": result.event_id, "status": cost.status_code,
                 "accounting": cost.accounting_code})
        session.commit()
        return cost.status_code


def _mark_posted(cost: WorkOrderCost, ev: AssetEvent, user_id: int | None) -> None:
    cost.status_code, cost.asset_event_id = "POSTED", ev.event_id
    cost.accounting_code = "CAPITALIZE" if ev.event_type == "IMPROVEMENT" else "EXPENSE"
    cost.posted_by_user_id, cost.posted_at = user_id, c.now()


def refresh_pending(session, work_order_id: int) -> None:
    """هزینهٔ منتظر تأیید مالی: پس از تأیید = ثبت‌شده؛ پس از رد = دوباره «ثبت‌نشده» (قابل ثبت دوباره)."""
    for cost in session.scalars(select(WorkOrderCost).where(WorkOrderCost.work_order_id == work_order_id,
                                                            WorkOrderCost.status_code == "PENDING_APPROVAL").with_for_update()):
        done = session.scalar(select(AssetEvent).where(AssetEvent.idempotency_key == _key(cost.cost_id)))
        if done is not None and done.status_code == "POSTED":
            _mark_posted(cost, done, done.created_by_user_id)
            continue
        pending = session.get(AssetEvent, cost.asset_event_id) if cost.asset_event_id else None
        if pending is None or pending.status_code in ("REJECTED", "CANCELLED"):
            cost.status_code, cost.asset_event_id, cost.accounting_code = "DRAFT", None, "PENDING"


def mark_none(company_id: int, user_id: int, cost_id: int, reason: str) -> None:
    """هزینه‌ای که ثبت مالی ندارد (مثلاً زیر پوشش ضمانت یا فقط برای سابقه)."""
    if not (reason or "").strip():
        raise ValueError("علت بدون ثبت مالی بودن را بنویسید.")
    with new_session() as session:
        c.require(company_id, user_id, c.FORM_COST, session=session)
        cost, wo = _lock_cost(session, company_id, cost_id)
        if cost.status_code != "DRAFT":
            raise ValueError(f"این هزینه در وضعیت «{c.COST_STATUS_LABELS[cost.status_code]}» است.")
        cost.accounting_code = "NONE"
        session.flush()
        c.audit(session, company_id, user_id, wos.ENTITY, wo.work_order_id, "COST_NONE", {"cost_id": cost_id, "reason": reason})
        session.commit()


def cancel_cost(company_id: int, user_id: int, cost_id: int, reason: str) -> None:
    if not (reason or "").strip():
        raise ValueError("علت لغو را بنویسید.")
    with new_session() as session:
        c.require(company_id, user_id, c.FORM_EXECUTE, session=session)
        cost, wo = _lock_cost(session, company_id, cost_id)
        if cost.status_code != "DRAFT":
            raise ValueError("فقط هزینهٔ ثبت‌نشده در حسابداری لغو می‌شود.")
        cost.status_code = "CANCELLED"
        session.flush()
        c.audit(session, company_id, user_id, wos.ENTITY, wo.work_order_id, "COST_CANCEL", {"cost_id": cost_id, "reason": reason})
        session.commit()


def list_costs(company_id: int, work_order_id: int) -> list[SimpleNamespace]:
    from peecha.db.models.accounting import DetailAccount

    with new_session() as session:
        wo = session.get(WorkOrder, work_order_id)
        if wo is None or wo.company_id != company_id:
            raise ValueError("دستور کار نامعتبر است.")
        rows = list(session.scalars(select(WorkOrderCost).where(WorkOrderCost.work_order_id == work_order_id)
                                    .order_by(WorkOrderCost.cost_id)))
        sup = {d.detail_account_id: d.name for d in session.scalars(select(DetailAccount).where(
            DetailAccount.detail_account_id.in_([r.supplier_detail_account_id for r in rows if r.supplier_detail_account_id] or [-1])))}
        inv_no = dict(session.execute(select(CommercialDocument.document_id, CommercialDocument.document_no).where(
            CommercialDocument.document_id.in_([r.commercial_document_id for r in rows if r.commercial_document_id] or [-1]))).all())
        return [SimpleNamespace(cost_id=r.cost_id, cost_type_code=r.cost_type_code, type_label=c.COST_TYPE_LABELS[r.cost_type_code],
                                description=r.description, supplier_name=sup.get(r.supplier_detail_account_id, ""),
                                supplier_detail_account_id=r.supplier_detail_account_id, amount=r.amount,
                                accounting_code=r.accounting_code, accounting_label=c.ACCOUNTING_LABELS[r.accounting_code],
                                status_code=r.status_code, status_label=c.COST_STATUS_LABELS[r.status_code],
                                invoice_no=inv_no.get(r.commercial_document_id), asset_event_id=r.asset_event_id)
                for r in rows]


def summary_in_session(session, work_order_ids) -> dict[int, SimpleNamespace]:
    """هزینهٔ هر دستور کار: قطعه (خالص سند انبار) + نیروی کار (اطلاعاتی) + خدمات + سایر (بدون ردیف لغوشده)."""
    from peecha.services.maintenance import parts

    ids = list(work_order_ids)
    out = {wid: SimpleNamespace(parts=c.ZERO, labor=c.ZERO, services=c.ZERO, other=c.ZERO, total=c.ZERO, hours=c.ZERO)
           for wid in ids}
    if not ids:
        return out
    for wid, amount in parts.issued_total(session, ids).items():
        out[wid].parts = c.money(amount)
    for wid, hours, amount in session.execute(select(WorkOrderLabor.work_order_id, func.sum(WorkOrderLabor.hours),
                                                     func.sum(WorkOrderLabor.amount))
                                              .where(WorkOrderLabor.work_order_id.in_(ids)).group_by(WorkOrderLabor.work_order_id)):
        out[wid].labor, out[wid].hours = c.money(amount), c.dec(hours)
    for wid, kind, amount in session.execute(select(WorkOrderCost.work_order_id, WorkOrderCost.cost_type_code,
                                                    func.sum(WorkOrderCost.amount))
                                             .where(WorkOrderCost.work_order_id.in_(ids), WorkOrderCost.status_code != "CANCELLED")
                                             .group_by(WorkOrderCost.work_order_id, WorkOrderCost.cost_type_code)):
        if kind == "SERVICE":
            out[wid].services = c.money(amount)
        else:
            out[wid].other = c.money(amount)
    for s in out.values():
        s.total = s.parts + s.labor + s.services + s.other
    return out


def summary(company_id: int, work_order_id: int) -> SimpleNamespace:
    with new_session() as session:
        wo = session.get(WorkOrder, work_order_id)
        if wo is None or wo.company_id != company_id:
            raise ValueError("دستور کار نامعتبر است.")
        return summary_in_session(session, [work_order_id])[work_order_id]
