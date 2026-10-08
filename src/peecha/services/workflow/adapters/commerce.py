"""فروش و خرید: اسناد بازرگانی، درخواست خرید، قفل اعتباری و فاکتورهای معوق.

اقدام‌ها فقط همان توابع سرویس موجودند (تصویب سند، آزادسازی قفل اعتباری، تصویب/رد درخواست خرید).
"""

from __future__ import annotations

import datetime
import decimal

from sqlalchemy import func, select

from peecha.db.base import new_session
from peecha.db.models.commercial import CommercialDocument, CommercialDocumentLine, CreditHold, PurchaseRequest, PurchaseRequestLine
from peecha.services.workflow import model_events, registry
from peecha.services.workflow.adapters._common import ZERO, detail_name, jdate, money, status_events, user_name
from peecha.services.workflow.common import WorkflowError
from peecha.services.workflow.model_events import Watch
from peecha.services.workflow.registry import ActionContext, ActionSpec, EntityAdapter, FieldSpec, ParamSpec, ScanSpec

DOC_TYPES = {  # نوع سند ← (برچسب، کد منو)
    "SALES_ORDER": ("سفارش فروش", "SALES_ORDER"),
    "SALES_PROFORMA": ("پیش‌فاکتور فروش", "SALES_PROFORMA"),
    "SALES_INVOICE": ("فاکتور فروش", "SALES_INVOICE"),
    "SALES_RETURN": ("برگشت از فروش", "SALES_RETURN"),
    "PURCHASE_ORDER": ("سفارش خرید", "PURCH_ORDER"),
    "PURCHASE_PROFORMA": ("پیش‌فاکتور خرید", "PURCH_PROFORMA"),
    "PURCHASE_INVOICE": ("فاکتور خرید", "PURCH_INVOICE"),
    "PURCHASE_RETURN": ("برگشت به تامین‌کننده", "PURCH_RETURN"),
}
DOC_STATUS = {"DRAFT": "پیش‌نویس", "CONFIRMED": "تاییدشده", "APPROVED": "تصویب‌شده", "POSTED": "ثبت نهایی",
              "CANCELLED": "لغوشده"}
DOC_EVENTS = {"CONFIRMED": "تایید کاربر", "APPROVED": "تصویب مدیر", "POSTED": "ثبت نهایی", "CANCELLED": "لغو"}


# --- اسناد بازرگانی -------------------------------------------------------------------------------------------
def _doc(session, company_id: int, document_id: int) -> CommercialDocument:
    doc = session.get(CommercialDocument, document_id)
    if doc is None or doc.company_id != company_id:
        raise WorkflowError("سند پیدا نشد.")
    return doc


def doc_context(company_id: int, document_id: int) -> dict:
    with new_session() as session:
        d = _doc(session, company_id, document_id)
        lines = session.scalar(select(func.count()).select_from(CommercialDocumentLine)
                               .where(CommercialDocumentLine.document_id == document_id)) or 0
        hold = session.scalar(select(CreditHold.hold_id).where(CreditHold.related_document_id == document_id,
                                                              CreditHold.released_at.is_(None)))
        subtotal = decimal.Decimal(d.subtotal_amount or 0)
        discount = decimal.Decimal(d.discount_amount or 0)
        today = datetime.date.today()
        return {
            "document_id": d.document_id, "document_no": d.document_no, "document_type": d.document_type_code,
            "document_date": d.document_date, "status": d.status_code, "counterparty_id": d.counterparty_detail_account_id,
            "counterparty_name": detail_name(session, d.counterparty_detail_account_id),
            "total_amount": decimal.Decimal(d.total_amount or 0), "subtotal_amount": subtotal, "discount_amount": discount,
            "discount_percent": (discount * 100 / subtotal).quantize(decimal.Decimal("0.01")) if subtotal else ZERO,
            "tax_amount": decimal.Decimal(d.tax_amount or 0), "warehouse_id": d.warehouse_id, "branch_id": d.branch_id,
            "org_unit_id": d.org_unit_id, "created_by": d.created_by_user_id, "due_date": d.due_date,
            "overdue_days": (today - d.due_date).days if d.due_date and d.due_date < today else 0,
            "credit_hold": hold is not None, "credit_hold_id": hold, "line_count": int(lines),
            "channel_code": d.channel_code, "description": d.description or "",
        }


def _doc_card(company_id: int, document_id: int) -> list[tuple[str, str]]:
    c = doc_context(company_id, document_id)
    rows = [("طرف حساب", c["counterparty_name"] or "—"), ("تاریخ", jdate(c["document_date"])),
            ("جمع کل", money(c["total_amount"])), ("تخفیف", f"{money(c['discount_amount'])} ({c['discount_percent']}٪)"),
            ("تعداد ردیف", str(c["line_count"])), ("وضعیت", DOC_STATUS.get(c["status"], c["status"]))]
    if c["due_date"]:
        rows.append(("سررسید", jdate(c["due_date"])))
    if c["credit_hold"]:
        rows.append(("قفل اعتباری", "باز است"))
    return rows


def _approve_doc(ctx: ActionContext) -> dict:
    from peecha.services import commercial_documents as docs

    docs.approve_document(int(ctx.entity_id), ctx.company_id, ctx.user_id)
    return {"status": "APPROVED"}


def _post_doc(ctx: ActionContext) -> dict:
    from peecha.services import commercial_documents as docs

    docs.post_document(int(ctx.entity_id), ctx.company_id, ctx.user_id)
    return {"status": "POSTED"}


def _release_hold(ctx: ActionContext) -> dict:
    from peecha.services import commercial_credit

    with new_session() as session:
        holds = list(session.scalars(select(CreditHold.hold_id).where(CreditHold.related_document_id == ctx.entity_id,
                                                                      CreditHold.released_at.is_(None))))
    for hold_id in holds:
        commercial_credit.release_credit_hold(hold_id, ctx.user_id)
    return {"released": holds}


def _doc_status_is(*statuses: str):
    def check(company_id: int, document_id: int) -> bool:
        with new_session() as session:
            return _doc(session, company_id, document_id).status_code in statuses
    return check


def _no_open_hold(company_id: int, document_id: int) -> bool:
    with new_session() as session:
        return session.scalar(select(CreditHold.hold_id).where(CreditHold.related_document_id == document_id,
                                                               CreditHold.released_at.is_(None))) is None


DOC_FIELDS = (
    FieldSpec("total_amount", "جمع کل", "money"), FieldSpec("subtotal_amount", "جمع پیش از تخفیف", "money"),
    FieldSpec("discount_amount", "مبلغ تخفیف", "money"), FieldSpec("discount_percent", "درصد تخفیف", "number"),
    FieldSpec("tax_amount", "مالیات", "money"), FieldSpec("counterparty_id", "طرف حساب", "number"),
    FieldSpec("warehouse_id", "انبار", "number"), FieldSpec("branch_id", "شعبه", "number"),
    FieldSpec("org_unit_id", "واحد سازمانی", "number"), FieldSpec("created_by", "صادرکننده", "user"),
    FieldSpec("document_date", "تاریخ سند", "date"), FieldSpec("due_date", "سررسید", "date"),
    FieldSpec("overdue_days", "روز گذشته از سررسید", "number"), FieldSpec("credit_hold", "قفل اعتباری باز", "bool"),
    FieldSpec("line_count", "تعداد ردیف", "number"), FieldSpec("status", "وضعیت", "choice", DOC_STATUS),
    FieldSpec("channel_code", "کانال فروش", "text"),
)

for _code, (_label, _nav) in DOC_TYPES.items():
    registry.register_adapter(EntityAdapter(
        _code, _label, "PURCHASE" if _code.startswith("PURCHASE") else "SALES", doc_context, fields=DOC_FIELDS,
        events={f"{_code}_{k}": v for k, v in status_events(_label, DOC_EVENTS).items()} | {f"{_code}_CREATED": f"ثبت «{_label}»"},
        actions={
            "approve": ActionSpec("approve", "تصویب سند", _approve_doc, risk="HIGH",
                                  is_done=_doc_status_is("APPROVED", "POSTED"),
                                  description="همان «تصویب مدیر» فرم سند"),
            "release_credit_hold": ActionSpec("release_credit_hold", "آزادسازی قفل اعتباری", _release_hold, risk="HIGH",
                                              is_done=_no_open_hold),
            "post": ActionSpec("post", "ثبت نهایی سند", _post_doc, risk="HIGH", is_done=_doc_status_is("POSTED")),
        },
        title=lambda c, _l=_label: f"{_l} شمارهٔ {c.get('document_no')} — {c.get('counterparty_name') or ''}".strip(" —"),
        owner=lambda cid, eid: doc_context(cid, eid)["created_by"], approval_context=_doc_card, open_nav=_nav,
        submitter_field="created_by", gate_statuses=("APPROVED",), form_gate_statuses=("POSTED",),
        gate_label="تا تایید فرایند، سند قابل تصویب و ثبت نهایی نیست",
        form_code=f"commercial_document_{_code.lower()}"))

model_events.watch(Watch(
    CommercialDocument, lambda d: d.document_type_code if d.document_type_code in DOC_TYPES else None,
    actor=lambda d: d.created_by_user_id,
    # فروش فروشگاهی (صندوق) هرگز متوقف نمی‌شود
    gate_exempt=lambda d, _old: d.pos_session_id is not None))


# --- قفل اعتباری (تایید اعتبار مشتری) -----------------------------------------------------------------------
def hold_context(company_id: int, hold_id: int) -> dict:
    from peecha.services import commercial_credit

    with new_session() as session:
        h = session.get(CreditHold, hold_id)
        if h is None:
            raise WorkflowError("قفل اعتباری پیدا نشد.")
        doc = session.get(CommercialDocument, h.related_document_id) if h.related_document_id else None
        if doc is not None and doc.company_id != company_id:
            raise WorkflowError("قفل اعتباری پیدا نشد.")
        party = h.party_detail_account_id
        out = {"hold_id": h.hold_id, "customer_id": party, "customer_name": detail_name(session, party), "reason": h.reason,
               "document_id": h.related_document_id, "document_no": doc.document_no if doc else None,
               "document_amount": decimal.Decimal(doc.total_amount or 0) if doc else ZERO,
               "released": h.released_at is not None, "held_by": h.held_by_user_id}
    try:
        out["exposure"] = decimal.Decimal(commercial_credit.compute_customer_exposure(company_id, party) or 0)
    except Exception:  # noqa: BLE001 -- نمایش اعتبار نباید اجرای فرایند را متوقف کند
        out["exposure"] = None
    return out


def _hold_release(ctx: ActionContext) -> dict:
    from peecha.services import commercial_credit

    commercial_credit.release_credit_hold(int(ctx.entity_id), ctx.user_id)
    return {"released": True}


def _hold_approve_document(ctx: ActionContext) -> dict:
    from peecha.services import commercial_documents as docs

    doc_id = ctx.context.get("document_id")
    if not doc_id:
        return {"skipped": True}
    with new_session() as session:
        if session.get(CommercialDocument, doc_id).status_code != "CONFIRMED":
            return {"skipped": True}
    docs.approve_document(int(doc_id), ctx.company_id, ctx.user_id)
    return {"document_id": doc_id}


def _hold_released(company_id: int, hold_id: int) -> bool:
    with new_session() as session:
        h = session.get(CreditHold, hold_id)
        return h is not None and h.released_at is not None


def _hold_company(conn, h: CreditHold) -> int | None:
    if not h.related_document_id:
        return None
    from sqlalchemy import text

    return conn.execute(text("SELECT company_id FROM comm.commercial_documents WHERE document_id = :d"),
                        {"d": h.related_document_id}).scalar()


registry.register_adapter(EntityAdapter(
    "CREDIT_HOLD", "قفل اعتباری مشتری", "SALES", hold_context,
    fields=(FieldSpec("document_amount", "مبلغ سند", "money"), FieldSpec("exposure", "بدهی فعلی مشتری", "money"),
            FieldSpec("customer_id", "مشتری", "number"), FieldSpec("held_by", "ثبت‌کننده", "user")),
    events={"CREDIT_HOLD_CREATED": "ایجاد قفل اعتباری (عبور از سقف اعتبار)"},
    actions={"release": ActionSpec("release", "آزادسازی قفل اعتباری", _hold_release, risk="HIGH", is_done=_hold_released),
             "approve_document": ActionSpec("approve_document", "تصویب سند مربوط", _hold_approve_document, risk="HIGH")},
    title=lambda c: f"عبور از سقف اعتبار — {c.get('customer_name') or ''}",
    approval_context=lambda cid, eid: (lambda c: [
        ("مشتری", c["customer_name"]), ("دلیل", c["reason"]), ("مبلغ سند", money(c["document_amount"])),
        ("بدهی فعلی مشتری", money(c["exposure"]) if c["exposure"] is not None else "—")])(hold_context(cid, eid)),
    submitter_field="held_by", form_code="commercial_document_sales_order"))

model_events.watch(Watch(CreditHold, lambda h: "CREDIT_HOLD" if h.related_document_id else None, status_attr=None,
                         company_id=_hold_company, actor=lambda h: h.held_by_user_id))


# --- درخواست خرید ------------------------------------------------------------------------------------------
PR_STATUS = {"DRAFT": "پیش‌نویس", "SUBMITTED": "ارسال‌شده", "APPROVED": "تصویب‌شده", "REJECTED": "ردشده",
             "CANCELLED": "لغوشده", "ORDERED": "سفارش داده‌شده"}


def pr_context(company_id: int, request_id: int) -> dict:
    with new_session() as session:
        r = session.get(PurchaseRequest, request_id)
        if r is None or r.company_id != company_id:
            raise WorkflowError("درخواست خرید پیدا نشد.")
        lines = list(session.scalars(select(PurchaseRequestLine).where(PurchaseRequestLine.request_id == request_id)))
        estimate = sum((decimal.Decimal(ln.quantity) * decimal.Decimal(ln.estimated_unit_price or 0) for ln in lines), ZERO)
        return {"request_id": r.request_id, "request_no": r.request_no, "request_date": r.request_date,
                "required_date": r.required_date, "requester": r.requester_user_id,
                "requester_name": user_name(session, r.requester_user_id), "priority": r.priority_code,
                "warehouse_id": r.warehouse_id, "branch_id": r.branch_id, "org_unit_id": r.org_unit_id,
                "estimated_amount": estimate.quantize(decimal.Decimal("0.01")), "line_count": len(lines),
                "status": r.status_code, "description": r.description or ""}


def _pr_approve(ctx: ActionContext) -> dict:
    from peecha.services import purchase_requests

    purchase_requests.approve_request(int(ctx.entity_id), ctx.company_id, ctx.user_id)
    return {"status": "APPROVED"}


def _pr_reject(ctx: ActionContext) -> dict:
    from peecha.services import purchase_requests

    reason = (ctx.params.get("reason") or ctx.context.get("last_comment") or "رد در گردش کار تایید").strip()
    purchase_requests.reject_request(int(ctx.entity_id), ctx.company_id, reason)
    return {"status": "REJECTED"}


def _pr_status_is(*statuses: str):
    def check(company_id: int, request_id: int) -> bool:
        with new_session() as session:
            r = session.get(PurchaseRequest, request_id)
            return r is not None and r.status_code in statuses
    return check


registry.register_adapter(EntityAdapter(
    "PURCHASE_REQUEST", "درخواست خرید", "PURCHASE", pr_context,
    fields=(FieldSpec("estimated_amount", "مبلغ تخمینی", "money"), FieldSpec("requester", "درخواست‌کننده", "user"),
            FieldSpec("priority", "اولویت", "choice", {"LOW": "کم", "NORMAL": "عادی", "HIGH": "زیاد", "URGENT": "فوری"}),
            FieldSpec("warehouse_id", "انبار", "number"), FieldSpec("branch_id", "شعبه", "number"),
            FieldSpec("org_unit_id", "واحد سازمانی", "number"), FieldSpec("line_count", "تعداد ردیف", "number"),
            FieldSpec("required_date", "تاریخ نیاز", "date")),
    events={"PURCHASE_REQUEST_CREATED": "ثبت درخواست خرید", "PURCHASE_REQUEST_SUBMITTED": "ارسال درخواست خرید",
            "PURCHASE_REQUEST_APPROVED": "تصویب درخواست خرید", "PURCHASE_REQUEST_REJECTED": "رد درخواست خرید"},
    actions={"approve": ActionSpec("approve", "تصویب درخواست خرید", _pr_approve, risk="HIGH",
                                   is_done=_pr_status_is("APPROVED", "ORDERED")),
             "reject": ActionSpec("reject", "رد درخواست خرید", _pr_reject, is_done=_pr_status_is("REJECTED"),
                                  params=(ParamSpec("reason", "دلیل رد"),))},
    title=lambda c: f"درخواست خرید شمارهٔ {c.get('request_no')} — {c.get('requester_name') or ''}".strip(" —"),
    owner=lambda cid, eid: pr_context(cid, eid)["requester"],
    approval_context=lambda cid, eid: (lambda c: [
        ("درخواست‌کننده", c["requester_name"]), ("تاریخ", jdate(c["request_date"])), ("تاریخ نیاز", jdate(c["required_date"])),
        ("مبلغ تخمینی", money(c["estimated_amount"])), ("تعداد ردیف", str(c["line_count"]))])(pr_context(cid, eid)),
    open_nav="PURCH_REQUESTS", submitter_field="requester", gate_statuses=("APPROVED",),
    gate_label="تا تایید فرایند، درخواست قابل تصویب نیست", form_code="purchase_requests"))

model_events.watch(Watch(PurchaseRequest, lambda r: "PURCHASE_REQUEST", actor=lambda r: r.requester_user_id))


# --- فاکتورهای معوق (بررسی دوره‌ای) ----------------------------------------------------------------------
def _overdue_invoices(company_id: int, params: dict) -> list[int]:
    from peecha.services import commercial_settlements

    days = int(params.get("min_days") or 0)
    cutoff = datetime.date.today() - datetime.timedelta(days=max(days, 1))
    minimum = decimal.Decimal(str(params.get("min_amount") or 0))
    return [r.document_id for r in commercial_settlements.list_unsettled_invoices_bulk(company_id, due_on_or_before=cutoff)
            if r.remaining_amount >= minimum]


registry.register_scan(ScanSpec(
    "OVERDUE_INVOICES", "فاکتورهای فروش معوق", "SALES_INVOICE", _overdue_invoices,
    params=(ParamSpec("min_days", "حداقل روز گذشته از سررسید", "int", 1), ParamSpec("min_amount", "حداقل مانده", "money", 0))))
