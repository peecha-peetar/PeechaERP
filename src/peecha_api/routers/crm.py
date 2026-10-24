"""API CRM (R281) — لایهٔ نازک روی services/crm؛ دسترسی‌ها همان RBAC (فرم‌های crm_*).

نوشتن‌های موبایل با Idempotency-Key تکرارناپذیرند. خطای اعتبارسنجی 400 است؛ برای ثبت فعالیت از موبایل، نبود
تنظیمات به خطا تبدیل نمی‌شود (قاعدهٔ صف آفلاین).
"""

from __future__ import annotations

import datetime
import decimal

from fastapi import APIRouter, Depends, HTTPException, status

from peecha.services.crm import activities as act_service
from peecha.services.crm import analytics
from peecha.services.crm import automation as auto_service
from peecha.services.crm import communication as comm_service
from peecha.services.crm import campaigns as camp_service
from peecha.services.crm import loyalty as loyalty_service
from peecha.services.crm import customer360 as c360
from peecha.services.crm import leads as lead_service
from peecha.services.crm import opportunities as opp_service
from peecha.services.crm import opportunity_sales as opp_sales
from peecha.services.crm import pipelines as pl_service
from peecha.services.crm import reports as report_service
from peecha.services.crm import segments as seg_service
from peecha.services.crm import tasks as task_service
from peecha.services.crm import tickets as ticket_service
from peecha_api.deps import AuthContext, get_current_context, get_idempotency_key
from peecha_api.idempotency import IdempotentReplay, run_idempotent
from peecha_api.permissions import require_permission
from peecha_api.schemas import (
    CrmActivityCompleteRequest, CrmActivityRequest, CrmAssignRequest, CrmAutomationRuleRequest, CrmMessageRequest,
    CrmPreviewRequest, CrmTemplateRequest, CrmCampaignLaunchRequest, CrmCampaignMembersRequest,
    CrmCampaignRequest, CrmLoyaltyAdjustRequest, CrmMemberStatusRequest, CrmReferralRequest, CrmLeadConvertRequest, CrmLeadRequest,
    CrmLeadStatusRequest, CrmOpportunityLine, CrmOpportunityRequest, CrmSegmentRequest, CrmSlaPolicyRequest, CrmStageMoveRequest,
    CrmTicketRateRequest, CrmTicketRequest, CrmTicketTextRequest,
)

router = APIRouter(prefix="/crm", tags=["crm"])

F_360, F_TASKS, F_LEADS, F_PIPE, F_ACT, F_ASSIGN = (
    "crm_customer360", "crm_tasks", "crm_leads", "crm_pipeline", "crm_activities", "crm_assign")


def _json(value):
    if isinstance(value, decimal.Decimal):
        return str(value)
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json(v) for v in value]
    return value


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


def _idem(key, endpoint, ctx, compute, serialize):
    try:
        return run_idempotent(key, endpoint, ctx.user_id, ctx.company_id, status.HTTP_200_OK, compute, serialize)
    except IdempotentReplay as replay:
        return replay.body
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


def _row(obj) -> dict:
    data = {k: _json(v) for k, v in obj.__dict__.items()}
    for prop in ("weighted_amount", "days_in_stage", "sla_overdue", "is_open"):
        if hasattr(type(obj), prop):
            data[prop] = _json(getattr(obj, prop))
    return data


# --- مرجع‌ها -----------------------------------------------------------------------------------------
@router.get("/lead-sources")
def lead_sources(ctx: AuthContext = Depends(require_permission(F_LEADS, "VIEW"))) -> list[dict]:
    return [{"source_id": s.source_id, "code": s.code, "name": s.name} for s in pl_service.list_lead_sources(ctx.company_id)]


@router.get("/pipelines")
def pipelines(ctx: AuthContext = Depends(require_permission(F_PIPE, "VIEW"))) -> list[dict]:
    return [{"pipeline_id": p.pipeline_id, "code": p.code, "name": p.name, "is_default": p.is_default,
             "stages": [{"stage_id": s.stage_id, "code": s.code, "name": s.name, "probability_percent": str(s.probability_percent),
                         "stage_type": s.stage_type, "sla_hours": s.sla_hours, "required_fields": s.required_fields}
                        for s in pl_service.list_stages(ctx.company_id, p.pipeline_id)]}
            for p in pl_service.list_pipelines(ctx.company_id)]


@router.get("/pipelines/{pipeline_id}/kanban")
def kanban(pipeline_id: int, mine: bool = False, ctx: AuthContext = Depends(require_permission(F_PIPE, "VIEW"))) -> dict:
    cols = _call(opp_service.kanban, ctx.company_id, pipeline_id, ctx.user_id if mine else None)
    return {"columns": [{"stage_id": c.stage_id, "code": c.code, "name": c.name, "stage_type": c.stage_type,
                         "total": str(c.total), "weighted": str(c.weighted), "cards": [_row(o) for o in c.cards]} for c in cols],
            "summary": _json(opp_service.pipeline_summary(ctx.company_id, pipeline_id, ctx.user_id if mine else None))}


# --- سرنخ --------------------------------------------------------------------------------------------
def _valid_campaign(company_id: int, campaign_id: int | None) -> int | None:
    """کمپین نامعتبر سرنخ موبایل را رد نمی‌کند (صف آفلاین)، فقط نسبت‌دادن انجام نمی‌شود."""
    if not campaign_id:
        return None
    try:
        return camp_service.get_campaign(company_id, campaign_id).campaign_id
    except ValueError:
        return None


def _lead_fields(p: CrmLeadRequest) -> lead_service.LeadFields:
    return lead_service.LeadFields(**{k: getattr(p, k) for k in lead_service.LeadFields.__dataclass_fields__})


@router.get("/leads")
def list_leads(status_code: str | None = None, open_only: bool = False, mine: bool = False, band: str | None = None,
               q: str | None = None, limit: int = 100, offset: int = 0,
               ctx: AuthContext = Depends(require_permission(F_LEADS, "VIEW"))) -> list[dict]:
    rows = lead_service.list_leads(ctx.company_id, status=status_code, open_only=open_only, band=band, search=q,
                                   owner_user_id=ctx.user_id if mine else None, limit=min(limit, 500), offset=offset)
    return [_row(r) for r in rows]


@router.post("/leads")
def create_lead(payload: CrmLeadRequest, ctx: AuthContext = Depends(require_permission(F_LEADS, "CREATE")),
                idempotency_key: str | None = Depends(get_idempotency_key)) -> dict:
    return _idem(idempotency_key, "POST /crm/leads", ctx,
                 lambda: lead_service.create_lead(ctx.company_id, ctx.user_id, _lead_fields(payload), payload.allow_duplicate,
                                                  campaign_id=_valid_campaign(ctx.company_id, payload.campaign_id)),
                 lambda lead_id: {"lead_id": lead_id})


@router.get("/leads/{lead_id}")
def get_lead(lead_id: int, ctx: AuthContext = Depends(require_permission(F_LEADS, "VIEW"))) -> dict:
    row = _row(_call(lead_service.get_lead, ctx.company_id, lead_id))
    row["score_breakdown"] = lead_service.score_breakdown(ctx.company_id, lead_id)
    row["activities"] = [_row(a) for a in act_service.list_activities(ctx.company_id, lead_id=lead_id, limit=50)]
    return row


@router.put("/leads/{lead_id}")
def update_lead(lead_id: int, payload: CrmLeadRequest, ctx: AuthContext = Depends(require_permission(F_LEADS, "EDIT"))) -> dict:
    _call(lead_service.update_lead, ctx.company_id, ctx.user_id, lead_id, _lead_fields(payload))
    return {"lead_id": lead_id}


@router.delete("/leads/{lead_id}")
def delete_lead(lead_id: int, ctx: AuthContext = Depends(require_permission(F_LEADS, "DELETE"))) -> dict:
    _call(lead_service.delete_lead, ctx.company_id, ctx.user_id, lead_id)
    return {"lead_id": lead_id}


@router.post("/leads/{lead_id}/status")
def lead_status(lead_id: int, payload: CrmLeadStatusRequest, ctx: AuthContext = Depends(require_permission(F_LEADS, "EDIT"))) -> dict:
    _call(lead_service.set_lead_status, ctx.company_id, ctx.user_id, lead_id, payload.status_code, payload.reason)
    return {"lead_id": lead_id}


@router.post("/leads/{lead_id}/assign")
def assign_lead(lead_id: int, payload: CrmAssignRequest, ctx: AuthContext = Depends(require_permission(F_ASSIGN, "EDIT"))) -> dict:
    _call(lead_service.assign_lead, ctx.company_id, ctx.user_id, lead_id, payload.owner_user_id)
    return {"lead_id": lead_id}


@router.post("/leads/{lead_id}/convert")
def convert_lead(lead_id: int, payload: CrmLeadConvertRequest, ctx: AuthContext = Depends(require_permission(F_LEADS, "EDIT")),
                 idempotency_key: str | None = Depends(get_idempotency_key)) -> dict:
    return _idem(idempotency_key, f"POST /crm/leads/{lead_id}/convert", ctx,
                 lambda: lead_service.convert_lead(ctx.company_id, ctx.user_id, lead_id, existing_customer_id=payload.existing_customer_id,
                                                   create_opportunity=payload.create_opportunity,
                                                   opportunity_title=payload.opportunity_title,
                                                   opportunity_amount=payload.opportunity_amount),
                 lambda res: {"customer_detail_account_id": res[0], "opportunity_id": res[1]})


# --- فرصت --------------------------------------------------------------------------------------------
def _opp_fields(p: CrmOpportunityRequest) -> opp_service.OpportunityFields:
    return opp_service.OpportunityFields(**{k: getattr(p, k) for k in opp_service.OpportunityFields.__dataclass_fields__})


@router.get("/opportunities")
def list_opportunities(status_code: str | None = None, customer_id: int | None = None, pipeline_id: int | None = None,
                       mine: bool = False, q: str | None = None, limit: int = 200, offset: int = 0,
                       ctx: AuthContext = Depends(require_permission(F_PIPE, "VIEW"))) -> list[dict]:
    rows = opp_service.list_opportunities(ctx.company_id, status=status_code, customer_detail_account_id=customer_id,
                                          pipeline_id=pipeline_id, owner_user_id=ctx.user_id if mine else None, search=q,
                                          limit=min(limit, 1000), offset=offset)
    return [_row(o) for o in rows]


@router.post("/opportunities")
def create_opportunity(payload: CrmOpportunityRequest, ctx: AuthContext = Depends(require_permission(F_PIPE, "CREATE")),
                       idempotency_key: str | None = Depends(get_idempotency_key)) -> dict:
    return _idem(idempotency_key, "POST /crm/opportunities", ctx,
                 lambda: opp_service.create_opportunity(ctx.company_id, ctx.user_id, _opp_fields(payload)),
                 lambda oid: {"opportunity_id": oid})


@router.get("/opportunities/{opportunity_id}")
def get_opportunity(opportunity_id: int, ctx: AuthContext = Depends(require_permission(F_PIPE, "VIEW"))) -> dict:
    row = _row(_call(opp_service.get_opportunity, ctx.company_id, opportunity_id))
    row["lines"] = [{"line_id": ln.line_id, "item_id": ln.item_id, "description": ln.description, "quantity": str(ln.quantity),
                     "unit_price": str(ln.unit_price), "discount_amount": str(ln.discount_amount)}
                    for ln in opp_service.list_lines(ctx.company_id, opportunity_id)]
    row["activities"] = [_row(a) for a in act_service.list_activities(ctx.company_id, opportunity_id=opportunity_id, limit=50)]
    return row


@router.put("/opportunities/{opportunity_id}")
def update_opportunity(opportunity_id: int, payload: CrmOpportunityRequest,
                       ctx: AuthContext = Depends(require_permission(F_PIPE, "EDIT"))) -> dict:
    _call(opp_service.update_opportunity, ctx.company_id, ctx.user_id, opportunity_id, _opp_fields(payload))
    return {"opportunity_id": opportunity_id}


@router.put("/opportunities/{opportunity_id}/lines")
def set_lines(opportunity_id: int, lines: list[CrmOpportunityLine],
              ctx: AuthContext = Depends(require_permission(F_PIPE, "EDIT"))) -> dict:
    amount = _call(opp_service.set_lines, ctx.company_id, ctx.user_id, opportunity_id,
                   [opp_service.LineFields(ln.item_id, ln.quantity, ln.unit_price, ln.discount_amount, ln.description) for ln in lines])
    return {"opportunity_id": opportunity_id, "amount": str(amount)}


@router.post("/opportunities/{opportunity_id}/stage")
def move_stage(opportunity_id: int, payload: CrmStageMoveRequest,
               ctx: AuthContext = Depends(require_permission(F_PIPE, "EDIT"))) -> dict:
    _call(opp_service.move_stage, ctx.company_id, ctx.user_id, opportunity_id, payload.stage_id, payload.lost_reason)
    return _row(opp_service.get_opportunity(ctx.company_id, opportunity_id))


@router.post("/opportunities/{opportunity_id}/documents")
def create_sales_document(opportunity_id: int, payload: dict, ctx: AuthContext = Depends(require_permission(F_PIPE, "EDIT")),
                          idempotency_key: str | None = Depends(get_idempotency_key)) -> dict:
    """R282: پیش‌فاکتور یا سفارش فروش از فرصت — با همان سرویس اسناد فروش."""
    doc_type = payload.get("document_type_code", "SALES_PROFORMA")
    return _idem(idempotency_key, f"POST /crm/opportunities/{opportunity_id}/documents", ctx,
                 lambda: opp_sales.create_sales_document(ctx.company_id, ctx.user_id, opportunity_id, doc_type),
                 lambda doc_id: {"document_id": doc_id, "document_type_code": doc_type})


@router.get("/opportunities/{opportunity_id}/sales-chain")
def sales_chain(opportunity_id: int, ctx: AuthContext = Depends(require_permission(F_PIPE, "VIEW"))) -> list[dict]:
    return _json(_call(opp_sales.sales_chain, ctx.company_id, opportunity_id))


@router.delete("/opportunities/{opportunity_id}")
def delete_opportunity(opportunity_id: int, ctx: AuthContext = Depends(require_permission(F_PIPE, "DELETE"))) -> dict:
    _call(opp_service.delete_opportunity, ctx.company_id, ctx.user_id, opportunity_id)
    return {"opportunity_id": opportunity_id}


# --- فعالیت و کارها -----------------------------------------------------------------------------------
def _act_fields(p: CrmActivityRequest) -> act_service.ActivityFields:
    return act_service.ActivityFields(**{k: getattr(p, k) for k in act_service.ActivityFields.__dataclass_fields__
                                         if hasattr(p, k)})


@router.get("/activities")
def list_activities(customer_id: int | None = None, lead_id: int | None = None, opportunity_id: int | None = None,
                    mine: bool = False, open_only: bool = False, limit: int = 100, offset: int = 0,
                    ctx: AuthContext = Depends(require_permission(F_ACT, "VIEW"))) -> list[dict]:
    rows = act_service.list_activities(ctx.company_id, customer_detail_account_id=customer_id, lead_id=lead_id,
                                       opportunity_id=opportunity_id, assigned_to_user_id=ctx.user_id if mine else None,
                                       open_only=open_only, limit=min(limit, 500), offset=offset)
    return [_row(a) for a in rows]


@router.post("/activities")
def create_activity(payload: CrmActivityRequest, ctx: AuthContext = Depends(require_permission(F_ACT, "CREATE")),
                    idempotency_key: str | None = Depends(get_idempotency_key)) -> dict:
    return _idem(idempotency_key, "POST /crm/activities", ctx,
                 lambda: act_service.create_activity(ctx.company_id, ctx.user_id, _act_fields(payload)),
                 lambda aid: {"activity_id": aid})


@router.put("/activities/{activity_id}")
def update_activity(activity_id: int, payload: CrmActivityRequest, ctx: AuthContext = Depends(require_permission(F_ACT, "EDIT"))) -> dict:
    _call(act_service.update_activity, ctx.company_id, ctx.user_id, activity_id, _act_fields(payload))
    return {"activity_id": activity_id}


@router.post("/activities/{activity_id}/complete")
def complete_activity(activity_id: int, payload: CrmActivityCompleteRequest,
                      ctx: AuthContext = Depends(require_permission(F_ACT, "EDIT")),
                      idempotency_key: str | None = Depends(get_idempotency_key)) -> dict:
    return _idem(idempotency_key, f"POST /crm/activities/{activity_id}/complete", ctx,
                 lambda: act_service.complete_activity(ctx.company_id, ctx.user_id, activity_id, payload.result_text,
                                                       payload.status_code, payload.follow_up_date, payload.follow_up_subject),
                 lambda follow: {"activity_id": activity_id, "follow_up_activity_id": follow})


@router.delete("/activities/{activity_id}")
def delete_activity(activity_id: int, ctx: AuthContext = Depends(require_permission(F_ACT, "DELETE"))) -> dict:
    _call(act_service.delete_activity, ctx.company_id, ctx.user_id, activity_id)
    return {"activity_id": activity_id}


@router.get("/tasks")
def tasks(bucket: str | None = None, ctx: AuthContext = Depends(require_permission(F_TASKS, "VIEW"))) -> dict:
    tc = task_service.task_center(ctx.company_id, ctx.user_id)
    buckets = {k: [_row(a) for a in rows] for k, rows in tc.buckets.items() if bucket in (None, k)}
    return {"buckets": buckets, "counts": {k: len(v) for k, v in tc.buckets.items()},
            "planned_visits": _json(tc.planned_visits), "pending_orders": _json(tc.pending_orders),
            "due_collections": _json(tc.due_collections), "open_tickets": _json(tc.open_tickets)}


# --- Customer 360 -----------------------------------------------------------------------------------
@router.post("/customers/{customer_id}/orders")
def customer_order(customer_id: int, ctx: AuthContext = Depends(require_permission("commercial_document_sales_order", "CREATE")),
                   idempotency_key: str | None = Depends(get_idempotency_key)) -> dict:
    """R282: سفارش فروش پیش‌نویس برای مشتری (ردیف‌ها با همان API سفارش فروش اضافه می‌شوند)."""
    return _idem(idempotency_key, f"POST /crm/customers/{customer_id}/orders", ctx,
                 lambda: opp_sales.create_customer_document(ctx.company_id, ctx.user_id, customer_id),
                 lambda doc_id: {"document_id": doc_id})


@router.get("/customers/{customer_id}/360")
def customer_360(customer_id: int, ctx: AuthContext = Depends(require_permission(F_360, "VIEW"))) -> dict:
    return _json(_call(c360.customer_360, ctx.company_id, customer_id))


@router.get("/customers/{customer_id}/timeline")
def customer_timeline(customer_id: int, kinds: str | None = None, date_from: datetime.date | None = None,
                      date_to: datetime.date | None = None, q: str | None = None, limit: int = 50, offset: int = 0,
                      ctx: AuthContext = Depends(require_permission(F_360, "VIEW"))) -> list[dict]:
    events = _call(c360.timeline, ctx.company_id, customer_id, kinds=kinds.split(",") if kinds else None, date_from=date_from,
                   date_to=date_to, search=q, limit=min(limit, 200), offset=offset)
    return [_json(e.__dict__) for e in events]


# --- تحلیل مشتری و سگمنت (R283) ---------------------------------------------------------------------
F_ANALYTICS = "crm_analytics"


@router.post("/analytics/refresh")
def analytics_refresh(ctx: AuthContext = Depends(require_permission(F_ANALYTICS, "EDIT"))) -> dict:
    n = analytics.refresh_scores(ctx.company_id)
    seg_service.refresh_counts(ctx.company_id)
    return {"customers": n}


@router.get("/analytics/scores")
def analytics_scores(rfm_segment: str | None = None, health_band: str | None = None, churn_band: str | None = None,
                     segment_id: int | None = None, order: str = "churn", limit: int = 200, offset: int = 0,
                     ctx: AuthContext = Depends(require_permission(F_ANALYTICS, "VIEW"))) -> list[dict]:
    if order not in ("churn", "health", "clv", "monetary"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="ترتیب نامعتبر است.")
    analytics.ensure_fresh(ctx.company_id)
    ids = _call(seg_service.members, ctx.company_id, segment_id) if segment_id else None
    return _json(analytics.list_scores(ctx.company_id, rfm_segment_code=rfm_segment, health_band=health_band, churn_band=churn_band,
                                       customer_ids=ids, order=order, limit=min(limit, 1000), offset=offset))


@router.get("/analytics/summary")
def analytics_summary(ctx: AuthContext = Depends(require_permission(F_ANALYTICS, "VIEW"))) -> dict:
    analytics.ensure_fresh(ctx.company_id)
    return _json({"rfm": analytics.rfm_matrix(ctx.company_id), "bands": analytics.band_counts(ctx.company_id)})


@router.get("/segments/fields")
def segment_fields(ctx: AuthContext = Depends(require_permission(F_ANALYTICS, "VIEW"))) -> dict:
    return {"fields": {k: {"label": f.label, "kind": f.kind, "choices": f.choices} for k, f in seg_service.FIELDS.items()},
            "operators": seg_service.OPERATORS}


def _segment(s) -> dict:
    return _json({"segment_id": s.segment_id, "code": s.code, "name": s.name, "description": s.description, "rule": s.rule,
                  "is_system": s.is_system, "is_active": s.is_active, "member_count": s.member_count, "refreshed_at": s.refreshed_at})


@router.get("/segments")
def segments_list(ctx: AuthContext = Depends(require_permission(F_ANALYTICS, "VIEW"))) -> list[dict]:
    return [_segment(s) for s in seg_service.list_segments(ctx.company_id)]


@router.post("/segments/preview")
def segments_preview(body: CrmSegmentRequest, ctx: AuthContext = Depends(require_permission(F_ANALYTICS, "VIEW"))) -> dict:
    return {"count": _call(seg_service.count, ctx.company_id, body.rule)}


@router.post("/segments")
def segments_create(body: CrmSegmentRequest, ctx: AuthContext = Depends(require_permission(F_ANALYTICS, "CREATE"))) -> dict:
    sid = _call(seg_service.save_segment, ctx.company_id, ctx.user_id, code=body.code, name=body.name, rule=body.rule,
                description=body.description, is_active=body.is_active)
    return {"segment_id": sid}


@router.put("/segments/{segment_id}")
def segments_update(segment_id: int, body: CrmSegmentRequest,
                    ctx: AuthContext = Depends(require_permission(F_ANALYTICS, "EDIT"))) -> dict:
    _call(seg_service.save_segment, ctx.company_id, ctx.user_id, segment_id=segment_id, code=body.code, name=body.name,
          rule=body.rule, description=body.description, is_active=body.is_active)
    return {"segment_id": segment_id}


@router.delete("/segments/{segment_id}")
def segments_delete(segment_id: int, ctx: AuthContext = Depends(require_permission(F_ANALYTICS, "DELETE"))) -> dict:
    _call(seg_service.delete_segment, ctx.company_id, ctx.user_id, segment_id)
    return {"ok": True}


@router.get("/segments/{segment_id}/members")
def segments_members(segment_id: int, ctx: AuthContext = Depends(require_permission(F_ANALYTICS, "VIEW"))) -> list[dict]:
    analytics.ensure_fresh(ctx.company_id)
    ids = _call(seg_service.members, ctx.company_id, segment_id)
    return _json(analytics.list_scores(ctx.company_id, customer_ids=ids, order="monetary"))



# --- کمپین و باشگاه مشتریان (R284) -------------------------------------------------------------------
F_CAMP = "crm_campaigns"


def _camp_fields(p: CrmCampaignRequest) -> camp_service.CampaignFields:
    return camp_service.CampaignFields(**{k: getattr(p, k) for k in camp_service.CampaignFields.__dataclass_fields__})


@router.get("/campaigns")
def campaigns_list(status_code: str | None = None, q: str | None = None,
                   ctx: AuthContext = Depends(require_permission(F_CAMP, "VIEW"))) -> list[dict]:
    return [_json(r.__dict__) for r in camp_service.list_campaigns(ctx.company_id, status_code, q)]


@router.post("/campaigns")
def campaigns_create(body: CrmCampaignRequest, ctx: AuthContext = Depends(require_permission(F_CAMP, "CREATE"))) -> dict:
    return {"campaign_id": _call(camp_service.create_campaign, ctx.company_id, ctx.user_id, _camp_fields(body))}


@router.get("/campaigns/{campaign_id}")
def campaigns_get(campaign_id: int, ctx: AuthContext = Depends(require_permission(F_CAMP, "VIEW"))) -> dict:
    camp_service.sync_delivery(ctx.company_id)
    return _json({**_call(camp_service.get_campaign, ctx.company_id, campaign_id).__dict__,
                  "analytics": camp_service.campaign_analytics(ctx.company_id, campaign_id)})


@router.put("/campaigns/{campaign_id}")
def campaigns_update(campaign_id: int, body: CrmCampaignRequest, ctx: AuthContext = Depends(require_permission(F_CAMP, "EDIT"))) -> dict:
    _call(camp_service.update_campaign, ctx.company_id, ctx.user_id, campaign_id, _camp_fields(body))
    return {"campaign_id": campaign_id}


@router.delete("/campaigns/{campaign_id}")
def campaigns_delete(campaign_id: int, ctx: AuthContext = Depends(require_permission(F_CAMP, "DELETE"))) -> dict:
    _call(camp_service.delete_campaign, ctx.company_id, ctx.user_id, campaign_id)
    return {"ok": True}


@router.get("/campaigns/{campaign_id}/members")
def campaigns_members(campaign_id: int, ctx: AuthContext = Depends(require_permission(F_CAMP, "VIEW"))) -> list[dict]:
    return _json(_call(camp_service.list_members, ctx.company_id, campaign_id))


@router.post("/campaigns/{campaign_id}/members")
def campaigns_add_members(campaign_id: int, body: CrmCampaignMembersRequest,
                          ctx: AuthContext = Depends(require_permission(F_CAMP, "EDIT"))) -> dict:
    added = 0
    if body.from_segment:
        added += _call(camp_service.build_members, ctx.company_id, ctx.user_id, campaign_id)
    if body.customer_ids:
        added += _call(camp_service.add_customers, ctx.company_id, ctx.user_id, campaign_id, body.customer_ids)
    if body.lead_ids:
        added += _call(camp_service.add_leads, ctx.company_id, ctx.user_id, campaign_id, body.lead_ids)
    return {"added": added}


@router.post("/campaigns/members/{member_id}/status")
def campaigns_member_status(member_id: int, body: CrmMemberStatusRequest,
                            ctx: AuthContext = Depends(require_permission(F_CAMP, "EDIT"))) -> dict:
    _call(camp_service.set_member_status, ctx.company_id, ctx.user_id, member_id, body.status_code, body.note)
    return {"ok": True}


@router.post("/campaigns/{campaign_id}/launch")
def campaigns_launch(campaign_id: int, body: CrmCampaignLaunchRequest,
                     ctx: AuthContext = Depends(require_permission(F_CAMP, "EDIT"))) -> dict:
    return _call(camp_service.launch, ctx.company_id, ctx.user_id, campaign_id, body.scheduled_at)


@router.post("/campaigns/{campaign_id}/complete")
def campaigns_complete(campaign_id: int, ctx: AuthContext = Depends(require_permission(F_CAMP, "EDIT"))) -> dict:
    _call(camp_service.set_status, ctx.company_id, ctx.user_id, campaign_id, "COMPLETED")
    return {"ok": True}


@router.post("/campaigns/{campaign_id}/cancel")
def campaigns_cancel(campaign_id: int, ctx: AuthContext = Depends(require_permission(F_CAMP, "EDIT"))) -> dict:
    _call(camp_service.set_status, ctx.company_id, ctx.user_id, campaign_id, "CANCELLED")
    return {"ok": True}


@router.get("/customers/{customer_id}/loyalty")
def customer_loyalty(customer_id: int, ctx: AuthContext = Depends(require_permission(F_360, "VIEW"))) -> dict:
    _call(c360.identity, ctx.company_id, customer_id)
    return _json(loyalty_service.summary(ctx.company_id, customer_id))


@router.post("/customers/{customer_id}/loyalty/adjust")
def customer_loyalty_adjust(customer_id: int, body: CrmLoyaltyAdjustRequest,
                            ctx: AuthContext = Depends(require_permission(F_CAMP, "EDIT"))) -> dict:
    return {"points": _call(loyalty_service.adjust_points, ctx.company_id, ctx.user_id, customer_id, body.points, body.reason)}


@router.post("/customers/{customer_id}/loyalty/referral")
def customer_loyalty_referral(customer_id: int, body: CrmReferralRequest,
                              ctx: AuthContext = Depends(require_permission(F_CAMP, "EDIT"))) -> dict:
    return {"points": _call(loyalty_service.award_referral, ctx.company_id, ctx.user_id, customer_id, body.referred_customer_id)}


@router.get("/settings/marketing")
def marketing_settings(ctx: AuthContext = Depends(require_permission("crm_settings", "VIEW"))) -> dict:
    from peecha.db.base import new_session
    with new_session() as session:
        scoring = lead_service.scoring_config(session, ctx.company_id)
    return {"loyalty": loyalty_service.get_rules(ctx.company_id),
            "lead_scoring": {"factor_max": scoring["factor_max"], "source_points": scoring["source_points"],
                             "bands": dict(scoring["bands"])}}


@router.put("/settings/marketing")
def marketing_settings_save(body: dict, ctx: AuthContext = Depends(require_permission("crm_settings", "EDIT"))) -> dict:
    if "loyalty" in body:
        _call(lambda: loyalty_service.save_rules(ctx.company_id, ctx.user_id, **body["loyalty"]))
    if "lead_scoring" in body:
        ls = body["lead_scoring"]
        _call(lambda: lead_service.save_scoring_config(ctx.company_id, ctx.user_id, factor_max=ls.get("factor_max"),
                                                       source_points=ls.get("source_points"), bands=ls.get("bands")))
    return marketing_settings(ctx)



# --- تیکت، شکایت و SLA (R285) -------------------------------------------------------------------------
F_TICKETS = "crm_tickets"


def _ticket(r: ticket_service.TicketRow) -> dict:
    return _json({**r.__dict__, "sla_state": r.sla_state()})


def _ticket_fields(p: CrmTicketRequest) -> ticket_service.TicketFields:
    return ticket_service.TicketFields(**{k: getattr(p, k) for k in ticket_service.TicketFields.__dataclass_fields__})


@router.get("/tickets")
def tickets_list(status_code: str | None = None, open_only: bool = False, ticket_type: str | None = None, priority: str | None = None,
                 mine: bool = False, customer_id: int | None = None, breached: bool = False, q: str | None = None, limit: int = 100,
                 offset: int = 0, ctx: AuthContext = Depends(require_permission(F_TICKETS, "VIEW"))) -> list[dict]:
    rows = ticket_service.list_tickets(ctx.company_id, status=status_code, open_only=open_only, ticket_type=ticket_type,
                                       priority=priority, assignee_user_id=ctx.user_id if mine else None, customer_id=customer_id,
                                       breached_only=breached, search=q, limit=min(limit, 500), offset=offset)
    return [_ticket(r) for r in rows]


@router.get("/tickets/stats")
def tickets_stats(date_from: datetime.date | None = None, date_to: datetime.date | None = None,
                  ctx: AuthContext = Depends(require_permission(F_TICKETS, "VIEW"))) -> dict:
    ticket_service.check_sla(ctx.company_id)
    return _json(ticket_service.stats(ctx.company_id, date_from, date_to))


@router.post("/tickets")
def tickets_create(payload: CrmTicketRequest, ctx: AuthContext = Depends(require_permission(F_TICKETS, "CREATE")),
                   idempotency_key: str | None = Depends(get_idempotency_key)) -> dict:
    return _idem(idempotency_key, "POST /crm/tickets", ctx,
                 lambda: ticket_service.create_ticket(ctx.company_id, ctx.user_id, _ticket_fields(payload)),
                 lambda tid: {"ticket_id": tid})


@router.get("/tickets/{ticket_id}")
def tickets_get(ticket_id: int, ctx: AuthContext = Depends(require_permission(F_TICKETS, "VIEW"))) -> dict:
    row = _call(ticket_service.get_ticket, ctx.company_id, ticket_id)
    return {**_ticket(row), "conversation": [_row(a) for a in ticket_service.conversation(ctx.company_id, ticket_id)]}


@router.put("/tickets/{ticket_id}")
def tickets_update(ticket_id: int, payload: CrmTicketRequest, ctx: AuthContext = Depends(require_permission(F_TICKETS, "EDIT"))) -> dict:
    _call(ticket_service.update_ticket, ctx.company_id, ctx.user_id, ticket_id, _ticket_fields(payload))
    return {"ticket_id": ticket_id}


@router.post("/tickets/{ticket_id}/assign")
def tickets_assign(ticket_id: int, body: CrmAssignRequest, ctx: AuthContext = Depends(require_permission(F_ASSIGN, "EDIT"))) -> dict:
    _call(ticket_service.assign_ticket, ctx.company_id, ctx.user_id, ticket_id, body.owner_user_id)
    return {"ok": True}


@router.post("/tickets/{ticket_id}/reply")
def tickets_reply(ticket_id: int, body: CrmTicketTextRequest, ctx: AuthContext = Depends(require_permission(F_TICKETS, "EDIT")),
                  idempotency_key: str | None = Depends(get_idempotency_key)) -> dict:
    return _idem(idempotency_key, f"POST /crm/tickets/{ticket_id}/reply", ctx,
                 lambda: ticket_service.add_reply(ctx.company_id, ctx.user_id, ticket_id, body.text, body.kind),
                 lambda aid: {"activity_id": aid})


@router.post("/tickets/{ticket_id}/resolve")
def tickets_resolve(ticket_id: int, body: CrmTicketTextRequest, ctx: AuthContext = Depends(require_permission(F_TICKETS, "EDIT"))) -> dict:
    _call(ticket_service.resolve_ticket, ctx.company_id, ctx.user_id, ticket_id, body.text)
    return {"ok": True}


@router.post("/tickets/{ticket_id}/close")
def tickets_close(ticket_id: int, ctx: AuthContext = Depends(require_permission(F_TICKETS, "EDIT"))) -> dict:
    _call(ticket_service.close_ticket, ctx.company_id, ctx.user_id, ticket_id)
    return {"ok": True}


@router.post("/tickets/{ticket_id}/reopen")
def tickets_reopen(ticket_id: int, body: CrmTicketTextRequest, ctx: AuthContext = Depends(require_permission(F_TICKETS, "EDIT"))) -> dict:
    _call(ticket_service.reopen_ticket, ctx.company_id, ctx.user_id, ticket_id, body.text or None)
    return {"ok": True}


@router.post("/tickets/{ticket_id}/rate")
def tickets_rate(ticket_id: int, body: CrmTicketRateRequest, ctx: AuthContext = Depends(require_permission(F_TICKETS, "VIEW"))) -> dict:
    _call(ticket_service.rate_ticket, ctx.company_id, ctx.user_id, ticket_id, body.score, body.comment)
    return {"ok": True}


@router.get("/sla-policies")
def sla_list(ctx: AuthContext = Depends(require_permission(F_TICKETS, "VIEW"))) -> list[dict]:
    return [_json({k: getattr(p, k) for k in ("sla_policy_id", "name", "ticket_type", "priority_code", "first_response_hours",
                                               "resolution_hours", "escalate_to_user_id", "is_active")})
            for p in ticket_service.list_policies(ctx.company_id)]


@router.post("/sla-policies")
def sla_create(body: CrmSlaPolicyRequest, ctx: AuthContext = Depends(require_permission("crm_settings", "EDIT"))) -> dict:
    return {"sla_policy_id": _call(lambda: ticket_service.save_policy(ctx.company_id, ctx.user_id, **body.model_dump()))}


@router.put("/sla-policies/{policy_id}")
def sla_update(policy_id: int, body: CrmSlaPolicyRequest, ctx: AuthContext = Depends(require_permission("crm_settings", "EDIT"))) -> dict:
    _call(lambda: ticket_service.save_policy(ctx.company_id, ctx.user_id, sla_policy_id=policy_id, **body.model_dump()))
    return {"sla_policy_id": policy_id}


@router.delete("/sla-policies/{policy_id}")
def sla_delete(policy_id: int, ctx: AuthContext = Depends(require_permission("crm_settings", "EDIT"))) -> dict:
    _call(ticket_service.delete_policy, ctx.company_id, ctx.user_id, policy_id)
    return {"ok": True}



# --- اتوماسیون و مرکز ارتباطات (R287) ------------------------------------------------------------------
F_AUTO = "crm_automation"


def _rule(r) -> dict:
    return _json({"rule_id": r.rule_id, "name": r.name, "trigger_code": r.trigger_code,
                  "trigger_label": auto_service.TRIGGERS[r.trigger_code][0], "conditions": r.conditions, "action_code": r.action_code,
                  "action_label": auto_service.ACTIONS[r.action_code][0], "action_params": r.action_params,
                  "cooldown_days": r.cooldown_days, "is_active": r.is_active, "last_run_at": r.last_run_at, "run_count": r.run_count})


@router.get("/automation/catalog")
def automation_catalog(ctx: AuthContext = Depends(require_permission(F_AUTO, "VIEW"))) -> dict:
    spec = lambda params: [{"key": p.key, "label": p.label, "kind": p.kind, "default": p.default} for p in params]
    return {"triggers": {k: {"label": v[0], "entity": v[1], "params": spec(v[2])} for k, v in auto_service.TRIGGERS.items()},
            "actions": {k: {"label": v[0], "params": spec(v[1])} for k, v in auto_service.ACTIONS.items()},
            "channels": comm_service.CHANNELS, "template_fields": comm_service.TEMPLATE_FIELDS}


@router.get("/automation/rules")
def automation_rules(ctx: AuthContext = Depends(require_permission(F_AUTO, "VIEW"))) -> list[dict]:
    return [_rule(r) for r in auto_service.list_rules(ctx.company_id)]


@router.post("/automation/rules")
def automation_create(body: CrmAutomationRuleRequest, ctx: AuthContext = Depends(require_permission(F_AUTO, "CREATE"))) -> dict:
    return {"rule_id": _call(lambda: auto_service.save_rule(ctx.company_id, ctx.user_id, **body.model_dump()))}


@router.put("/automation/rules/{rule_id}")
def automation_update(rule_id: int, body: CrmAutomationRuleRequest, ctx: AuthContext = Depends(require_permission(F_AUTO, "EDIT"))) -> dict:
    _call(lambda: auto_service.save_rule(ctx.company_id, ctx.user_id, rule_id=rule_id, **body.model_dump()))
    return {"rule_id": rule_id}


@router.delete("/automation/rules/{rule_id}")
def automation_delete(rule_id: int, ctx: AuthContext = Depends(require_permission(F_AUTO, "DELETE"))) -> dict:
    _call(auto_service.delete_rule, ctx.company_id, ctx.user_id, rule_id)
    return {"ok": True}


@router.post("/automation/rules/{rule_id}/run")
def automation_run_one(rule_id: int, ctx: AuthContext = Depends(require_permission(F_AUTO, "EDIT"))) -> dict:
    return {"processed": _call(auto_service.run_rule, ctx.company_id, rule_id, ctx.user_id)}


@router.post("/automation/run")
def automation_run(ctx: AuthContext = Depends(require_permission(F_AUTO, "EDIT"))) -> dict:
    return {"rules": {str(k): v for k, v in auto_service.run_all(ctx.company_id, ctx.user_id).items()}}


@router.post("/automation/preview")
def automation_preview(body: CrmPreviewRequest, ctx: AuthContext = Depends(require_permission(F_AUTO, "VIEW"))) -> dict:
    return {"count": _call(auto_service.preview, ctx.company_id, body.trigger_code, body.conditions)}


@router.get("/automation/log")
def automation_log(rule_id: int | None = None, ctx: AuthContext = Depends(require_permission(F_AUTO, "VIEW"))) -> list[dict]:
    return _json(auto_service.list_log(ctx.company_id, rule_id))


@router.get("/messages")
def messages_list(customer_id: int | None = None, channel: str | None = None, status_code: str | None = None,
                  ctx: AuthContext = Depends(require_permission(F_360, "VIEW"))) -> list[dict]:
    return [_json(m.__dict__) for m in comm_service.list_messages(ctx.company_id, customer_id=customer_id, channel=channel,
                                                                  status=status_code)]


@router.post("/messages")
def messages_send(body: CrmMessageRequest, ctx: AuthContext = Depends(require_permission(F_ACT, "CREATE")),
                  idempotency_key: str | None = Depends(get_idempotency_key)) -> dict:
    if body.channel == "INTERNAL":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="اعلان داخلی از این مسیر فرستاده نمی‌شود.")
    mid = _idem(idempotency_key, "POST /crm/messages", ctx,
                lambda: comm_service.send_message(ctx.company_id, ctx.user_id, body.channel, body.body, customer_id=body.customer_id,
                                                  lead_id=body.lead_id, subject=body.subject, template_id=body.template_id),
                lambda m: {"message_id": m})
    row = next(m for m in comm_service.list_messages(ctx.company_id, limit=50) if m.message_id == mid["message_id"])
    return {**mid, "status_code": row.status_code, "error_message": row.error_message}


@router.post("/messages/{message_id}/retry")
def messages_retry(message_id: int, ctx: AuthContext = Depends(require_permission(F_ACT, "CREATE"))) -> dict:
    return {"message_id": _call(comm_service.retry_message, ctx.company_id, ctx.user_id, message_id)}


@router.get("/message-templates")
def templates_list(ctx: AuthContext = Depends(require_permission(F_360, "VIEW"))) -> list[dict]:
    return [_json({k: getattr(t, k) for k in ("template_id", "code", "name", "channel", "subject", "body", "is_active")})
            for t in comm_service.list_templates(ctx.company_id)]


@router.post("/message-templates")
def templates_create(body: CrmTemplateRequest, ctx: AuthContext = Depends(require_permission(F_AUTO, "CREATE"))) -> dict:
    return {"template_id": _call(lambda: comm_service.save_template(ctx.company_id, ctx.user_id, **body.model_dump()))}


@router.put("/message-templates/{template_id}")
def templates_update(template_id: int, body: CrmTemplateRequest, ctx: AuthContext = Depends(require_permission(F_AUTO, "EDIT"))) -> dict:
    _call(lambda: comm_service.save_template(ctx.company_id, ctx.user_id, template_id=template_id, **body.model_dump()))
    return {"template_id": template_id}


@router.delete("/message-templates/{template_id}")
def templates_delete(template_id: int, ctx: AuthContext = Depends(require_permission(F_AUTO, "DELETE"))) -> dict:
    _call(comm_service.delete_template, ctx.company_id, ctx.user_id, template_id)
    return {"ok": True}


# --- داشبورد، پیش‌بینی، گزارش‌ها، جستجو و تقویم (R288) -------------------------------------------------
F_DASH = "crm_dashboard"


def _period(date_from: datetime.date | None, date_to: datetime.date | None) -> tuple[datetime.date, datetime.date]:
    date_to = date_to or datetime.date.today()
    return date_from or date_to.replace(day=1), date_to


@router.get("/dashboard")
def crm_dashboard(date_from: datetime.date | None = None, date_to: datetime.date | None = None, mine: bool = False,
                  ctx: AuthContext = Depends(require_permission(F_DASH, "VIEW"))) -> dict:
    f, t = _period(date_from, date_to)
    return _json({**report_service.dashboard(ctx.company_id, f, t, ctx.user_id if mine else None), "date_from": f, "date_to": t})


@router.get("/forecast")
def crm_forecast(months: int = 3, ctx: AuthContext = Depends(require_permission(F_DASH, "VIEW"))) -> list[dict]:
    return _json(report_service.forecast(ctx.company_id, max(1, min(months, 12))))


@router.get("/performance")
def crm_performance(date_from: datetime.date | None = None, date_to: datetime.date | None = None,
                    ctx: AuthContext = Depends(require_permission(F_DASH, "VIEW"))) -> list[dict]:
    f, t = _period(date_from, date_to)
    return _json(report_service.performance(ctx.company_id, f, t))


@router.get("/search")
def crm_search(q: str, ctx: AuthContext = Depends(require_permission(F_360, "VIEW"))) -> list[dict]:
    return _json(report_service.search(ctx.company_id, q))


@router.get("/calendar")
def crm_calendar(date_from: datetime.date, date_to: datetime.date, all_users: bool = False,
                 ctx: AuthContext = Depends(require_permission(F_TASKS, "VIEW"))) -> list[dict]:
    if (date_to - date_from).days > 92 or date_to < date_from:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="بازهٔ تقویم حداکثر سه ماه است.")
    return _json(report_service.calendar(ctx.company_id, None if all_users else ctx.user_id, date_from, date_to))


@router.get("/reports")
def crm_reports(ctx: AuthContext = Depends(require_permission(F_DASH, "VIEW"))) -> list[dict]:
    return [{"code": r.code, "title": r.title, "group": r.group, "hint": r.hint, "date_mode": r.date_mode,
             "options": [{"key": k, "label": lbl, "choices": [{"value": v, "label": vl} for v, vl in ch]} for k, lbl, ch in r.options]}
            for r in report_service.CRM_REPORTS]


@router.get("/reports/{code}")
def crm_report_run(code: str, date_from: datetime.date | None = None, date_to: datetime.date | None = None, option: str | None = None,
                   ctx: AuthContext = Depends(get_current_context)) -> dict:
    """option: «کلید=مقدار» با ویرگول. دسترسی همان فرم گزارش در منو (warehouse_report_crm_*)."""
    from peecha.services import roles as roles_service
    from peecha.services.purchase_reports import PurchaseFilters

    rep = next((r for r in report_service.CRM_REPORTS if r.code == code.upper()), None)
    if rep is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="گزارش یافت نشد.")
    if not roles_service.user_has_permission(ctx.user_id, ctx.company_id, f"warehouse_report_{rep.code.lower()}", "VIEW"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="دسترسی به این گزارش وجود ندارد.")
    f, t = _period(date_from, date_to)
    opts = dict(p.split("=", 1) for p in (option or "").split(",") if "=" in p)
    res = rep.func(ctx.company_id, PurchaseFilters(f, t, side="INVENTORY", options=opts))
    return _json({"code": rep.code, "title": rep.title, "columns": [{"title": h, "kind": k} for h, k in res.columns], "rows": res.rows,
                  "footer": res.footer(), "note": res.note})
