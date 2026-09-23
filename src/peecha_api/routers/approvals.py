"""صندوقِ تاییدِ موبایل -- تجمیعِ دو موتورِ تاییدِ ازپیش‌موجود، بدونِ ساختِ
موتورِ سومی: (۱) services/cartable.py (تاییدِ چندمرحله‌ایِ عمومیِ اسناد،
اگر برایِ فرمی در تنظیمات فعال شده باشد) و (۲) پذیرشِ مشتری
(commercial_partners، PENDING_APPROVAL). فقط GL_DIM/EDIT مشتریانِ
درانتظار را می‌بیند؛ کارتابل خودش طبقِ current_approver_user_id/role
فیلتر می‌شود (list_my_tasks)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from peecha.services import cartable as cartable_service
from peecha.services import commercial_partners as partners_service
from peecha.services import roles as roles_service
from peecha_api import audit_log
from peecha_api.deps import AuthContext, get_current_context
from peecha_api.permissions import FORM_CUSTOMER_MANAGEMENT

router = APIRouter(prefix="/approvals", tags=["approvals"])


class DecisionRequest(BaseModel):
    comment: str = ""


@router.get("")
def list_approvals(ctx: AuthContext = Depends(get_current_context)) -> dict:
    tasks = cartable_service.list_my_tasks(ctx.user_id, ctx.company_id)
    pending_customers = []
    if roles_service.user_has_permission(ctx.user_id, ctx.company_id, FORM_CUSTOMER_MANAGEMENT, "EDIT"):
        pending_customers = [
            {
                "customer_detail_account_id": p.customer_detail_account_id,
                "submitted_by_user_id": p.submitted_by_user_id,
                "submitted_at": p.submitted_at.isoformat() if p.submitted_at else None,
            }
            for p in partners_service.list_customer_profiles(ctx.company_id, status_code="PENDING_APPROVAL")
        ]
    return {
        "cartable_tasks": [
            {
                "cartable_item_id": t.cartable_item_id, "form_code": t.form_code, "form_label": t.form_label,
                "description": t.description, "submitted_by_name": t.submitted_by_name,
                "submitted_at": t.submitted_at.isoformat() if t.submitted_at else None,
                "current_step_no": t.current_step_no, "total_steps": t.total_steps,
            }
            for t in tasks
        ],
        "pending_customers": pending_customers,
    }


@router.post("/cartable/{cartable_item_id}/approve")
def approve_cartable_item(
    cartable_item_id: int, payload: DecisionRequest, ctx: AuthContext = Depends(get_current_context)
) -> dict:
    try:
        cartable_service.approve_item(cartable_item_id, ctx.user_id, payload.comment)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    audit_log.record(ctx.company_id, ctx.user_id, "CartableItem", cartable_item_id, "APPROVE", {"source": "mobile"})
    return {"cartable_item_id": cartable_item_id, "decision": "APPROVED"}


@router.post("/cartable/{cartable_item_id}/reject")
def reject_cartable_item(
    cartable_item_id: int, payload: DecisionRequest, ctx: AuthContext = Depends(get_current_context)
) -> dict:
    try:
        cartable_service.reject_item(cartable_item_id, ctx.user_id, payload.comment)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    audit_log.record(ctx.company_id, ctx.user_id, "CartableItem", cartable_item_id, "REJECT", {"source": "mobile"})
    return {"cartable_item_id": cartable_item_id, "decision": "REJECTED"}
