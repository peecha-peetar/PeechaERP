"""ثبتِ مشتریِ جدید از موبایل (پذیرشِ مشتری/Customer Acquisition، R134) --
رویِ همان services/commercial_partners.py موجود سوار می‌شود که از قبل
گردشِ کارِ تاییدِ اعتباری (PENDING_APPROVAL -> ACTIVE) را پیاده کرده --
هیچ وضعیت/جدولِ تازه‌ای برایِ همین منظور ساخته نمی‌شود. ویزیتور همیشه
fast_track=False می‌فرستد (مشتریِ ثبت‌شده از میدان تا تاییدِ مدیر
PENDING_APPROVAL می‌ماند). دسترسیِ ثبت/تاییدِ مشتری از همان فرمِ
دسکتاپیِ «تعریفِ تفصیلی» (GL_DIM) می‌آید -- برایِ این‌که یک نقش بتواند از
موبایل مشتری ثبت/تایید کند، باید در تبِ «نقش‌ها»یِ دسکتاپ اکشنِ
CREATE/EDIT رویِ فرمِ GL_DIM به آن نقش داده شده باشد (مدیرِ کلِ سیستم
همیشه مجاز است)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from peecha.services import commercial_partners as partners_service
from peecha.services import notifications as notifications_service
from peecha_api import audit_log
from peecha_api.deps import AuthContext, get_idempotency_key
from peecha_api.idempotency import IdempotentReplay, run_idempotent
from peecha_api.permissions import FORM_CUSTOMER_MANAGEMENT, require_permission
from peecha_api.schemas import CustomerCreateRequest

router = APIRouter(prefix="/customers", tags=["customers"])


@router.post("")
def create_customer(
    payload: CustomerCreateRequest,
    ctx: AuthContext = Depends(require_permission(FORM_CUSTOMER_MANAGEMENT, "CREATE")),
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
    detail_account_id = partners_service.create_customer(
        ctx.company_id, payload.code, payload.name, fields=fields,
        fast_track=False, submitted_by_user_id=ctx.user_id, **extra_fields,
    )
    audit_log.record(
        ctx.company_id, ctx.user_id, "CustomerProfile", detail_account_id, "CREATE",
        {"source": "mobile", "code": payload.code, "name": payload.name},
    )
    notifications_service.notify_managers(
        ctx.company_id, "CUSTOMER_APPROVAL_NEEDED", f"مشتریِ جدید «{payload.name}» نیازِ تاییدِ اعتباری دارد",
        entity_type="CustomerProfile", entity_id=detail_account_id,
    )
    return detail_account_id


@router.post("/{detail_account_id}/approve")
def approve_customer(
    detail_account_id: int,
    ctx: AuthContext = Depends(require_permission(FORM_CUSTOMER_MANAGEMENT, "EDIT")),
) -> dict:
    try:
        partners_service.approve_customer(detail_account_id, ctx.user_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    audit_log.record(ctx.company_id, ctx.user_id, "CustomerProfile", detail_account_id, "APPROVE", {"source": "mobile"})
    return {"detail_account_id": detail_account_id, "status_code": "ACTIVE"}
