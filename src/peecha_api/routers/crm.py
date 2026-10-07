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
from peecha.services.crm import customer360 as c360
from peecha.services.crm import leads as lead_service
from peecha.services.crm import opportunities as opp_service
from peecha.services.crm import opportunity_sales as opp_sales
from peecha.services.crm import pipelines as pl_service
from peecha.services.crm import segments as seg_service
from peecha.services.crm import tasks as task_service
from peecha_api.deps import AuthContext, get_idempotency_key
from peecha_api.idempotency import IdempotentReplay, run_idempotent
from peecha_api.permissions import require_permission
from peecha_api.schemas import (
    CrmActivityCompleteRequest, CrmActivityRequest, CrmAssignRequest, CrmLeadConvertRequest, CrmLeadRequest,
    CrmLeadStatusRequest, CrmOpportunityLine, CrmOpportunityRequest, CrmSegmentRequest, CrmStageMoveRequest,
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
                 lambda: lead_service.create_lead(ctx.company_id, ctx.user_id, _lead_fields(payload), payload.allow_duplicate),
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
            "due_collections": _json(tc.due_collections)}


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
