"""ثبتِ مشتریِ جدید از موبایل (پذیرشِ مشتری/Customer Acquisition، R134) --
رویِ همان services/commercial_partners.py موجود سوار می‌شود که از قبل
گردشِ کارِ تاییدِ اعتباری (PENDING_APPROVAL -> ACTIVE) را پیاده کرده --
هیچ وضعیت/جدولِ تازه‌ای برایِ همین منظور ساخته نمی‌شود. ویزیتور همیشه
fast_track=False می‌فرستد (مشتریِ ثبت‌شده از میدان تا تاییدِ مدیر
PENDING_APPROVAL می‌ماند)؛ تاییدِ نهایی فقط برایِ کاربرانی که در ERP
نقشِ مدیریتی دارند (roles_service.is_manager) مجاز است."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from peecha.services import commercial_partners as partners_service
from peecha.services import roles as roles_service
from peecha_api.deps import AuthContext, get_current_context, get_idempotency_key
from peecha_api.idempotency import IdempotentReplay, run_idempotent
from peecha_api.schemas import CustomerCreateRequest

router = APIRouter(prefix="/customers", tags=["customers"])


@router.post("")
def create_customer(
    payload: CustomerCreateRequest,
    ctx: AuthContext = Depends(get_current_context),
    idempotency_key: str | None = Depends(get_idempotency_key),
) -> dict:
    try:
        return run_idempotent(
            idempotency_key, "POST /customers", ctx.user_id, ctx.company_id,
            status.HTTP_200_OK, lambda: _create_customer(payload, ctx),
            lambda detail_account_id: {"detail_account_id": detail_account_id, "status_code": "PENDING_APPROVAL"},
        )
    except IdempotentReplay as replay:
        return replay.body
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


def _create_customer(payload: CustomerCreateRequest, ctx: AuthContext) -> int:
    fields = partners_service.CustomerProfileFields(
        customer_group_id=payload.customer_group_id,
        default_price_list_id=payload.default_price_list_id,
        payment_term_days=payload.payment_term_days,
        credit_limit_amount=payload.credit_limit_amount,
        default_channel_code=payload.default_channel_code,
        distribution_route_detail_account_id=payload.distribution_route_detail_account_id,
        gps_latitude=payload.gps_latitude,
        gps_longitude=payload.gps_longitude,
        onboarding_source_code="AGENT",  # طبقِ CHECKِ دیتابیس: مشتریِ ثبت‌شده توسطِ ویزیتورِ میدانی
    )
    extra_fields = {}
    if payload.phone:
        extra_fields["phone"] = payload.phone
    if payload.address:
        extra_fields["address"] = payload.address
    return partners_service.create_customer(
        ctx.company_id, payload.code, payload.name, fields=fields,
        fast_track=False, submitted_by_user_id=ctx.user_id, **extra_fields,
    )


@router.post("/{detail_account_id}/approve")
def approve_customer(
    detail_account_id: int,
    ctx: AuthContext = Depends(get_current_context),
) -> dict:
    if not roles_service.is_manager(ctx.user_id, ctx.company_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="فقط مدیر می‌تواند مشتریِ جدید را تایید کند.")
    try:
        partners_service.approve_customer(detail_account_id, ctx.user_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {"detail_account_id": detail_account_id, "status_code": "ACTIVE"}
