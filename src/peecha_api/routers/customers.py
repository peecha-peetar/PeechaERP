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

from peecha.services import commercial_documents as documents_service
from peecha.services import commercial_partners as partners_service
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import inventory_catalog as catalog_service
from peecha.services import notifications as notifications_service
from peecha.services import treasury as treasury_service
from peecha_api import audit_log
from peecha_api.deps import AuthContext, get_current_context, get_idempotency_key
from peecha_api.idempotency import IdempotentReplay, run_idempotent
from peecha_api.permissions import FORM_CUSTOMER_MANAGEMENT, require_permission
from peecha_api.schemas import CustomerCreateRequest

router = APIRouter(prefix="/customers", tags=["customers"])


@router.get("")
def list_customers(q: str | None = None, ctx: AuthContext = Depends(get_current_context)) -> list[dict]:
    """طبقِ اصلِ «Search مشتری سریع باشد» (UI-2): فهرستِ کاملِ مشتریانِ
    شرکت (نه فقط مشتریانِ برنامه‌ریزی‌شده‌یِ /sync/pull) با جستجویِ
    کد/نام -- برایِ تبِ «مشتریان» که باید همه را ببیند، نه فقط مسیرِ
    امروز."""
    customers = dimensions_service.list_customers(ctx.company_id)
    if q:
        needle = q.strip().lower()
        customers = [c for c in customers if needle in (c["code"] or "").lower() or needle in (c["name"] or "").lower()]
    return [
        {"detail_account_id": c["detail_account_id"], "code": c["code"], "name": c["name"], "phone": c.get("phone")}
        for c in customers
    ]


@router.get("/{detail_account_id}")
def get_customer_detail(detail_account_id: int, ctx: AuthContext = Depends(get_current_context)) -> dict:
    customers_by_id = {c["detail_account_id"]: c for c in dimensions_service.list_customers(ctx.company_id)}
    customer = customers_by_id.get(detail_account_id)
    if customer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="مشتری یافت نشد.")

    profile = partners_service.get_customer_profile(detail_account_id)
    balance_amount, balance_nature = treasury_service.get_counterparty_balance(ctx.company_id, detail_account_id)
    purchase_summary = documents_service.summarize_customer_purchases(ctx.company_id, detail_account_id)
    items_by_id = {it.item_id: it for it in catalog_service.list_items(ctx.company_id)}

    recent_documents = sorted(
        (
            documents_service.list_documents(ctx.company_id, "SALES_ORDER", counterparty_detail_account_id=detail_account_id, limit=10)
            + documents_service.list_documents(ctx.company_id, "SALES_INVOICE", counterparty_detail_account_id=detail_account_id, limit=10)
        ),
        key=lambda d: (d.document_date, d.document_id),
        reverse=True,
    )[:10]

    return {
        "detail_account_id": detail_account_id,
        "code": customer["code"],
        "name": customer["name"],
        "phone": customer.get("phone"),
        "address": customer.get("address"),
        "status_code": profile.status_code if profile else None,
        "customer_group_id": profile.customer_group_id if profile else None,
        "credit_limit_amount": str(profile.credit_limit_amount) if profile else None,
        "payment_term_days": profile.payment_term_days if profile else None,
        "gps_latitude": str(profile.gps_latitude) if profile and profile.gps_latitude is not None else None,
        "gps_longitude": str(profile.gps_longitude) if profile and profile.gps_longitude is not None else None,
        "balance_amount": str(balance_amount),
        "balance_nature": balance_nature,
        "last_purchase_date": purchase_summary.last_purchase_date.isoformat() if purchase_summary.last_purchase_date else None,
        "top_products": [
            {
                "item_id": p.item_id,
                "item_name": items_by_id[p.item_id].name if p.item_id in items_by_id else None,
                "total_quantity": str(p.total_quantity),
                "total_amount": str(p.total_amount),
            }
            for p in purchase_summary.top_products
        ],
        "recent_documents": [
            {
                "document_id": d.document_id,
                "document_type_code": d.document_type_code,
                "document_no": d.document_no,
                "document_date": d.document_date.isoformat(),
                "status_code": d.status_code,
                "total_amount": str(d.total_amount),
            }
            for d in recent_documents
        ],
    }


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
