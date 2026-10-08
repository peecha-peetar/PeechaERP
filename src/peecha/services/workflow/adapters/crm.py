"""ارتباط با مشتری: واگذاری سرنخ، تایید فرصت فروش، تایید مشتری تازه و پیگیری مشتریان غیرفعال."""

from __future__ import annotations

import decimal

from sqlalchemy import func, select

from peecha.db.base import new_session
from peecha.db.models.commercial import CustomerProfile
from peecha.db.models.crm import Lead, Opportunity
from peecha.services.workflow import model_events, registry, routing
from peecha.services.workflow.adapters._common import ZERO, detail_name, jdate, money, user_name
from peecha.services.workflow.common import WorkflowError
from peecha.services.workflow.model_events import Watch
from peecha.services.workflow.registry import ActionContext, ActionSpec, EntityAdapter, FieldSpec, ParamSpec, ScanSpec

LEAD_STATUS = {"NEW": "جدید", "CONTACTED": "تماس گرفته‌شده", "QUALIFIED": "واجد شرایط", "UNQUALIFIED": "فاقد شرایط",
               "CONVERTED": "تبدیل‌شده", "LOST": "از دست رفته"}


# --- سرنخ -------------------------------------------------------------------------------------------------
def lead_context(company_id: int, lead_id: int) -> dict:
    with new_session() as session:
        x = session.get(Lead, lead_id)
        if x is None or x.company_id != company_id:
            raise WorkflowError("سرنخ پیدا نشد.")
        return {"lead_id": x.lead_id, "lead_no": x.lead_no, "full_name": x.full_name, "company_name": x.company_name or "",
                "mobile": x.mobile or "", "source_id": x.source_id, "campaign_id": x.campaign_id,
                "estimated_value": decimal.Decimal(x.estimated_value or 0), "owner_user_id": x.owner_user_id,
                "owner_name": user_name(session, x.owner_user_id), "status": x.status_code, "score": x.score,
                "score_band": x.score_band, "city": x.city or "", "province": x.province or "", "industry": x.industry or "",
                "created_by": x.created_by_user_id}


def _least_loaded(company_id: int, candidates: list[int]) -> int:
    with new_session() as session:
        load = dict(session.execute(select(Lead.owner_user_id, func.count()).where(
            Lead.company_id == company_id, Lead.owner_user_id.in_(candidates),
            Lead.status_code.in_(("NEW", "CONTACTED", "QUALIFIED"))).group_by(Lead.owner_user_id)).all())
    return min(candidates, key=lambda u: (load.get(u, 0), u))


def _assign(ctx: ActionContext) -> dict:
    """واگذاری به کم‌کارترین فرد گروه (نوبتی و منصفانه) یا به فرد مشخص -- با همان سرویس واگذاری سرنخ."""
    from peecha.services.crm import leads

    owner = ctx.params.get("user_id")
    if not owner:
        specs = [{"kind": "ROLE", "role_id": int(ctx.params["role_id"])}] if ctx.params.get("role_id") else \
            [{"kind": "PERMISSION", "form_code": "crm_leads", "action": "EDIT"}]
        candidates = routing.resolve(ctx.company_id, specs, context=ctx.context)
        if not candidates:
            raise WorkflowError("کسی برای واگذاری سرنخ پیدا نشد؛ گروه کارشناسان فروش را در تنظیمات اقدام مشخص کنید.")
        owner = _least_loaded(ctx.company_id, candidates)
    leads.assign_lead(ctx.company_id, ctx.user_id or int(owner), int(ctx.entity_id), int(owner))
    return {"owner_user_id": int(owner), "variables": {"assigned_to": int(owner)}}


registry.register_adapter(EntityAdapter(
    "LEAD", "سرنخ فروش", "CRM", lead_context,
    fields=(FieldSpec("estimated_value", "ارزش تخمینی", "money"), FieldSpec("score", "امتیاز", "number"),
            FieldSpec("score_band", "گرمی سرنخ", "choice", {"COLD": "سرد", "WARM": "گرم", "HOT": "داغ", "VERY_HOT": "بسیار داغ"}),
            FieldSpec("source_id", "منبع", "number"), FieldSpec("campaign_id", "کمپین", "number"),
            FieldSpec("city", "شهر", "text"), FieldSpec("province", "استان", "text"), FieldSpec("industry", "صنعت", "text"),
            FieldSpec("owner_user_id", "مسئول", "user"), FieldSpec("created_by", "ثبت‌کننده", "user"),
            FieldSpec("status", "وضعیت", "choice", LEAD_STATUS)),
    events={"LEAD_CREATED": "ثبت سرنخ تازه", "LEAD_QUALIFIED": "واجد شرایط شدن سرنخ", "LEAD_CONVERTED": "تبدیل سرنخ",
            "LEAD_LOST": "از دست رفتن سرنخ"},
    actions={"assign": ActionSpec(
        "assign", "واگذاری سرنخ (نوبتی بین کارشناسان)", _assign,
        params=(ParamSpec("role_id", "گروه کارشناسان", "role"), ParamSpec("user_id", "یا فرد مشخص", "user")))},
    title=lambda c: f"سرنخ {c.get('full_name')}", owner=lambda cid, eid: lead_context(cid, eid)["owner_user_id"],
    approval_context=lambda cid, eid: (lambda c: [
        ("نام", c["full_name"]), ("شرکت", c["company_name"] or "—"), ("ارزش تخمینی", money(c["estimated_value"])),
        ("امتیاز", str(c["score"])), ("مسئول", c["owner_name"] or "—")])(lead_context(cid, eid)),
    open_nav="CRM_LEADS", submitter_field="created_by", form_code="crm_leads"))

model_events.watch(Watch(Lead, lambda x: "LEAD", actor=lambda x: x.created_by_user_id))


# --- فرصت فروش ---------------------------------------------------------------------------------------------
def opp_context(company_id: int, opportunity_id: int) -> dict:
    with new_session() as session:
        o = session.get(Opportunity, opportunity_id)
        if o is None or o.company_id != company_id:
            raise WorkflowError("فرصت فروش پیدا نشد.")
        return {"opportunity_id": o.opportunity_id, "opportunity_no": o.opportunity_no, "title": o.title,
                "customer_id": o.customer_detail_account_id, "customer_name": detail_name(session, o.customer_detail_account_id),
                "amount": decimal.Decimal(o.amount or 0), "probability": decimal.Decimal(o.probability_percent or 0),
                "expected_close_date": o.expected_close_date, "owner_user_id": o.owner_user_id,
                "owner_name": user_name(session, o.owner_user_id), "status": o.status_code, "stage_id": o.stage_id,
                "created_by": o.created_by_user_id}


registry.register_adapter(EntityAdapter(
    "OPPORTUNITY", "فرصت فروش", "CRM", opp_context,
    fields=(FieldSpec("amount", "مبلغ", "money"), FieldSpec("probability", "احتمال موفقیت", "number"),
            FieldSpec("customer_id", "مشتری", "number"), FieldSpec("owner_user_id", "مسئول", "user"),
            FieldSpec("expected_close_date", "تاریخ پیش‌بینی بستن", "date"),
            FieldSpec("status", "وضعیت", "choice", {"OPEN": "باز", "WON": "برنده", "LOST": "بازنده"})),
    events={"OPPORTUNITY_CREATED": "ثبت فرصت فروش", "OPPORTUNITY_WON": "برنده شدن فرصت", "OPPORTUNITY_LOST": "از دست رفتن فرصت"},
    title=lambda c: f"فرصت فروش «{c.get('title')}» — {money(c.get('amount'))}",
    owner=lambda cid, eid: opp_context(cid, eid)["owner_user_id"],
    approval_context=lambda cid, eid: (lambda c: [
        ("عنوان", c["title"]), ("مشتری", c["customer_name"] or "—"), ("مبلغ", money(c["amount"])),
        ("احتمال موفقیت", f"{c['probability']}٪"), ("پیش‌بینی بستن", jdate(c["expected_close_date"])),
        ("مسئول", c["owner_name"] or "—")])(opp_context(cid, eid)),
    open_nav="CRM_PIPELINE", open_method="select", submitter_field="owner_user_id", form_code="crm_pipeline"))

model_events.watch(Watch(Opportunity, lambda o: "OPPORTUNITY", actor=lambda o: o.created_by_user_id))


# --- مشتری تازه (تایید اعتبار و فعال‌سازی) ------------------------------------------------------------------
CUSTOMER_STATUS = {"DRAFT": "پیش‌نویس", "PENDING_APPROVAL": "در انتظار تایید", "ACTIVE": "فعال", "INACTIVE": "غیرفعال",
                   "ON_HOLD": "متوقف", "BLOCKED": "مسدود"}


def customer_context(company_id: int, customer_id: int) -> dict:
    with new_session() as session:
        p = session.get(CustomerProfile, customer_id)
        if p is None or p.company_id != company_id:
            raise WorkflowError("مشتری پیدا نشد.")
        return {"customer_id": customer_id, "customer_name": detail_name(session, customer_id), "status": p.status_code,
                "credit_limit": decimal.Decimal(p.credit_limit_amount or 0), "payment_term_days": p.payment_term_days,
                "customer_group_id": p.customer_group_id, "channel_code": p.default_channel_code or "",
                "onboarding_source": p.onboarding_source_code or "", "submitted_by": p.submitted_by_user_id,
                "submitted_by_name": user_name(session, p.submitted_by_user_id)}


def _cust_approve(ctx: ActionContext) -> dict:
    from peecha.services import commercial_partners

    commercial_partners.approve_customer(int(ctx.entity_id), ctx.user_id)
    return {"status": "ACTIVE"}


def _cust_reject(ctx: ActionContext) -> dict:
    from peecha.services import commercial_partners

    reason = (ctx.params.get("reason") or ctx.context.get("last_comment") or "رد در گردش کار تایید").strip()
    commercial_partners.reject_customer(int(ctx.entity_id), ctx.user_id, reason)
    return {"status": "INACTIVE"}


def _cust_status(*statuses: str):
    def check(company_id: int, customer_id: int) -> bool:
        return customer_context(company_id, customer_id)["status"] in statuses
    return check


registry.register_adapter(EntityAdapter(
    "CUSTOMER", "مشتری تازه", "CRM", customer_context,
    fields=(FieldSpec("credit_limit", "سقف اعتبار", "money"), FieldSpec("payment_term_days", "مهلت پرداخت (روز)", "number"),
            FieldSpec("customer_group_id", "گروه مشتری", "number"), FieldSpec("channel_code", "کانال فروش", "text"),
            FieldSpec("onboarding_source", "منشأ ثبت", "choice", {"MOBILE": "موبایل", "DESKTOP": "دسکتاپ"}),
            FieldSpec("submitted_by", "ثبت‌کننده", "user")),
    events={"CUSTOMER_CREATED": "ثبت مشتری تازه", "CUSTOMER_PENDING_APPROVAL": "ارسال مشتری برای تایید",
            "CUSTOMER_ACTIVE": "فعال شدن مشتری"},
    actions={"approve": ActionSpec("approve", "تایید و فعال‌سازی مشتری", _cust_approve, risk="HIGH", is_done=_cust_status("ACTIVE")),
             "reject": ActionSpec("reject", "رد مشتری", _cust_reject, is_done=_cust_status("INACTIVE"),
                                  params=(ParamSpec("reason", "دلیل رد"),))},
    title=lambda c: f"مشتری تازه: {c.get('customer_name')}", owner=lambda cid, eid: customer_context(cid, eid)["submitted_by"],
    approval_context=lambda cid, eid: (lambda c: [
        ("مشتری", c["customer_name"]), ("سقف اعتبار", money(c["credit_limit"])), ("مهلت پرداخت", f"{c['payment_term_days']} روز"),
        ("ثبت‌کننده", c["submitted_by_name"] or "—")])(customer_context(cid, eid)),
    open_nav="CRM_CUSTOMER360", open_method="load_customer", submitter_field="submitted_by", gate_statuses=("ACTIVE",),
    gate_label="تا تایید فرایند، مشتری فعال نمی‌شود", form_code="detail_dimensions"))

model_events.watch(Watch(CustomerProfile, lambda p: "CUSTOMER", actor=lambda p: p.submitted_by_user_id,
                         # فقط تایید مشتری تازه؛ رفع توقف یا فعال‌سازی دوباره مثل قبل آزاد است
                         gate_exempt=lambda p, old: old != "PENDING_APPROVAL"))


def _inactive_customers(company_id: int, params: dict) -> list[int]:
    from peecha.services.crm import analytics

    days = int(params.get("days") or 60)
    analytics.ensure_fresh(company_id)
    return [s["customer_detail_account_id"] for s in analytics.list_scores(company_id)
            if s.get("recency_days") is not None and s["recency_days"] >= days]


registry.register_scan(ScanSpec("CUSTOMER_INACTIVE", "مشتریان بدون خرید اخیر", "CUSTOMER", _inactive_customers,
                                params=(ParamSpec("days", "روز بدون خرید", "int", 60),), period="WEEK"))
