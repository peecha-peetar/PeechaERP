"""چک‌این/چک‌اوتِ واقعیِ ویزیتور -- روی همان services/field_sales.py
(R129). طبقِ نکتهٔ امنیتی: سرویسِ زیرین فقط company_id را چک می‌کند
(چون از دسکتاپ هم برایِ سرپرست قابلِ‌استفاده است)؛ این‌جا -- جایی که
کلاینت خودِ ویزیتور است، نه سرپرست -- اضافه‌تر چک می‌شود که آن ویزیت
واقعاً مالِ همین کاربر باشد."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from peecha.services import field_sales as field_sales_service
from peecha_api.deps import AuthContext, get_current_context, get_idempotency_key
from peecha_api.idempotency import IdempotentReplay, run_idempotent
from peecha_api.schemas import VisitCompleteRequest, VisitSkipRequest, VisitStartRequest

router = APIRouter(prefix="/visits", tags=["visits"])


def _ensure_own_visit(ctx: AuthContext, customer_visit_id: int) -> None:
    own_visits = field_sales_service.list_customer_visits(ctx.company_id, visitor_user_id=ctx.user_id)
    if not any(v.customer_visit_id == customer_visit_id for v in own_visits):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ویزیت یافت نشد.")


@router.post("/start")
def start_visit(
    payload: VisitStartRequest,
    ctx: AuthContext = Depends(get_current_context),
    idempotency_key: str | None = Depends(get_idempotency_key),
) -> dict:
    def _do() -> int:
        return field_sales_service.start_visit(
            ctx.company_id, payload.customer_detail_account_id, ctx.user_id, payload.visit_plan_id,
            payload.check_in_latitude, payload.check_in_longitude,
        )

    try:
        return run_idempotent(
            idempotency_key, "POST /visits/start", ctx.user_id, ctx.company_id,
            status.HTTP_200_OK, _do, lambda customer_visit_id: {"customer_visit_id": customer_visit_id},
        )
    except IdempotentReplay as replay:
        return replay.body


@router.post("/{customer_visit_id}/complete", status_code=status.HTTP_204_NO_CONTENT)
def complete_visit(customer_visit_id: int, payload: VisitCompleteRequest, ctx: AuthContext = Depends(get_current_context)) -> None:
    _ensure_own_visit(ctx, customer_visit_id)
    try:
        field_sales_service.complete_visit(customer_visit_id, ctx.company_id, payload.notes)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/{customer_visit_id}/skip", status_code=status.HTTP_204_NO_CONTENT)
def skip_visit(customer_visit_id: int, payload: VisitSkipRequest, ctx: AuthContext = Depends(get_current_context)) -> None:
    _ensure_own_visit(ctx, customer_visit_id)
    try:
        field_sales_service.skip_visit(customer_visit_id, ctx.company_id, payload.skip_reason)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
