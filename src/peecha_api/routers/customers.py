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

import base64
import os
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError

from peecha.config import SETTINGS_DIR
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
from peecha_api.schemas import CustomerCreateRequest, CustomerRejectRequest, PartyAddressRequest

_TEMP_UPLOAD_DIR = SETTINGS_DIR / "mobile_uploads_tmp"

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


@router.get("/duplicate-check")
def duplicate_check(
    name: str | None = None, mobile: str | None = None, phone: str | None = None,
    ctx: AuthContext = Depends(require_permission(FORM_CUSTOMER_MANAGEMENT, "CREATE")),
) -> list[dict]:
    """طبقِ بازبینیِ ساختارِ «تعریفِ مشتری» (R216، بخشِ ۱۶): پیش از ثبتِ
    نهاییِ فرمِ «مشتریِ جدید»یِ موبایل صدا زده می‌شود -- فقط وقتی آنلاین
    است (خودِ اقدامِ ثبت هم‌چنان آفلاین کار می‌کند، این فقط یک هشدارِ
    اختیاریِ پیش از ارسال است)."""
    matches = partners_service.find_duplicate_customers(ctx.company_id, name=name, mobile=mobile, phone=phone)
    return [
        {
            "detail_account_id": m["detail_account_id"], "code": m["code"], "name": m["name"],
            "mobile": m.get("mobile"), "phone": m.get("phone"), "address": m.get("address"),
            "match_reasons": m["match_reasons"],
        }
        for m in matches
    ]


@router.get("/new-form-options")
def new_customer_form_options(ctx: AuthContext = Depends(require_permission(FORM_CUSTOMER_MANAGEMENT, "CREATE"))) -> dict:
    """طبقِ درخواستِ صریحِ کاربر («Customer Acquisition»): گزینه‌هایِ
    لازم برایِ فرمِ «مشتریِ جدید»یِ موبایل -- کدِ پیشنهادی (هم‌الگو با
    suggest_next_codeِ دسکتاپ) و نوعِ مشتری (customer group). مسیر/کانال
    از همان GET /routes و GET /pricing/channels گرفته می‌شود (تکراری
    ساخته نشد)."""
    dimension_type_id = dimensions_service.get_person_dimension_type_id(ctx.company_id)
    person_group_id = dimensions_service.get_person_group_id(ctx.company_id, dimensions_service.CUSTOMER_GROUP_CODE)
    suggested_code = dimensions_service.suggest_next_code(ctx.company_id, dimension_type_id, level_no=1, person_group_id=person_group_id)
    return {
        "suggested_code": suggested_code,
        "groups": [{"group_id": g.group_id, "code": g.code, "name": g.name} for g in partners_service.list_customer_groups(ctx.company_id)],
    }


@router.get("/{detail_account_id}")
def get_customer_detail(
    detail_account_id: int, mode: str | None = None, ctx: AuthContext = Depends(get_current_context),
) -> dict:
    customers_by_id = {c["detail_account_id"]: c for c in dimensions_service.list_customers(ctx.company_id)}
    customer = customers_by_id.get(detail_account_id)
    if customer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="مشتری یافت نشد.")

    profile = partners_service.get_customer_profile(detail_account_id)
    balance_amount, balance_nature = treasury_service.get_counterparty_balance(ctx.company_id, detail_account_id)
    purchase_summary = documents_service.summarize_customer_purchases(ctx.company_id, detail_account_id)
    items_by_id = {it.item_id: it for it in catalog_service.list_items(ctx.company_id)}

    # طبقِ رفعِ باگِ واقعی («پخشِ سرد و گرم کاملاً مجزا باشند»): با mode
    # فقط سندِ همان حالت (گرم = فاکتورِ کانالِ VAN_SALES، سرد = سفارشِ
    # کانالِ PRE_SALES)؛ بدونِ mode رفتارِ قبلی.
    if mode == "VAN_SALES":
        mode_documents = documents_service.list_documents(
            ctx.company_id, "SALES_INVOICE", counterparty_detail_account_id=detail_account_id, limit=10, channel_type_code="VAN_SALES",
        )
    elif mode == "PRE_SALES":
        mode_documents = documents_service.list_documents(
            ctx.company_id, "SALES_ORDER", counterparty_detail_account_id=detail_account_id, limit=10, channel_type_code="PRE_SALES",
        )
    else:
        mode_documents = (
            documents_service.list_documents(ctx.company_id, "SALES_ORDER", counterparty_detail_account_id=detail_account_id, limit=10)
            + documents_service.list_documents(ctx.company_id, "SALES_INVOICE", counterparty_detail_account_id=detail_account_id, limit=10)
        )
    recent_documents = sorted(
        mode_documents,
        key=lambda d: (d.document_date, d.document_id),
        reverse=True,
    )[:10]

    return {
        "detail_account_id": detail_account_id,
        "code": customer["code"],
        "name": customer["name"],
        "phone": customer.get("phone"),
        "mobile": customer.get("mobile"),
        "address": customer.get("address"),
        "notes": customer.get("notes"),
        "customer_type_code": customer.get("customer_type_code"),
        "customer_class": customer.get("customer_class"),
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
            lambda result: {"detail_account_id": result[0], "code": result[1], "status_code": "PENDING_APPROVAL"},
        )
    except IdempotentReplay as replay:
        return replay.body
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


def _save_temp_upload(photo_base64: str) -> str:
    _TEMP_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    destination = _TEMP_UPLOAD_DIR / f"{uuid.uuid4().hex}.jpg"
    destination.write_bytes(base64.b64decode(photo_base64))
    return str(destination)


def _create_customer(payload: CustomerCreateRequest, ctx: AuthContext) -> tuple[int, str]:
    # طبقِ درخواستِ صریحِ کاربر («Customer Acquisition باید آفلاین هم کار
    # کند»): اگر ویزیتورِ آفلاین کدی نفرستاده، همین‌جا (فقط لحظه‌یِ
    # همگام‌سازیِ واقعی -- نه در گوشی) کدِ بعدی پیشنهاد/اختصاص می‌شود.
    code = (payload.code or "").strip()
    if not code:
        dimension_type_id = dimensions_service.get_person_dimension_type_id(ctx.company_id)
        person_group_id = dimensions_service.get_person_group_id(ctx.company_id, dimensions_service.CUSTOMER_GROUP_CODE)
        code = dimensions_service.suggest_next_code(ctx.company_id, dimension_type_id, level_no=1, person_group_id=person_group_id)
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
    if payload.mobile:
        extra_fields["mobile"] = payload.mobile
    if payload.address:
        extra_fields["address"] = payload.address
    if payload.notes:
        extra_fields["notes"] = payload.notes
    if payload.customer_type_code:
        extra_fields["customer_type_code"] = payload.customer_type_code
    if payload.customer_class:
        extra_fields["customer_class"] = payload.customer_class
    try:
        detail_account_id = partners_service.create_customer(
            ctx.company_id, code, payload.name, fields=fields,
            fast_track=False, submitted_by_user_id=ctx.user_id, **extra_fields,
        )
    except IntegrityError as exc:
        # طبقِ باگِ واقعیِ کشف‌شده (R199 -- همین الگو): تصادفِ کدِ پیشنهادی
        # با یک ثبتِ هم‌زمانِ دیگر (مثلاً دو ویزیتورِ آفلاین که هردو
        # هنگامِ آفلاین‌بودن یک کد را پیشنهادی گرفته‌اند) نباید ۵۰۰ی خام
        # بدهد -- ویزیتور دوباره تلاش می‌کند (صفِ آفلاین همین اقدام را
        # نگه می‌دارد، کدِ کاملاً هرزمان دوباره محاسبه می‌شود).
        raise ValueError("این کدِ مشتری از قبل استفاده شده است -- دوباره تلاش کنید.") from exc
    # طبقِ درخواستِ صریحِ کاربر («عکسِ فروشگاه»): همان مکانیزمِ عکسِ
    # حساب‌هایِ تفصیلی (تبِ «عکس‌ها و فایل‌ها»یِ دسکتاپ) -- نه یک سیستمِ
    # موازیِ تازه.
    if payload.photo_base64:
        temp_path = _save_temp_upload(payload.photo_base64)
        try:
            attachment_id = dimensions_service.attach_detail_account_file(ctx.company_id, detail_account_id, ctx.user_id, temp_path)
            dimensions_service.set_primary_detail_account_photo(attachment_id, ctx.company_id)
        finally:
            os.unlink(temp_path)
    audit_log.record(
        ctx.company_id, ctx.user_id, "CustomerProfile", detail_account_id, "CREATE",
        {"source": "mobile", "code": code, "name": payload.name},
    )
    notifications_service.notify_managers(
        ctx.company_id, "CUSTOMER_APPROVAL_NEEDED", f"مشتریِ جدید «{payload.name}» نیازِ تاییدِ اعتباری دارد",
        entity_type="CustomerProfile", entity_id=detail_account_id,
    )
    return detail_account_id, code


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


@router.post("/{detail_account_id}/reject")
def reject_customer(
    detail_account_id: int,
    payload: CustomerRejectRequest,
    ctx: AuthContext = Depends(require_permission(FORM_CUSTOMER_MANAGEMENT, "EDIT")),
) -> dict:
    try:
        partners_service.reject_customer(detail_account_id, ctx.user_id, payload.reason)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    # طبقِ محدودیتِ دیتابیس (ck_activity_log_action): action فقط یکی از
    # CREATE/UPDATE/DELETE/APPROVE/REVERSE می‌تواند باشد -- «رد» همان
    # تغییرِ وضعیت (UPDATE) است، با جزئیاتِ دلیل در changes.
    audit_log.record(
        ctx.company_id, ctx.user_id, "CustomerProfile", detail_account_id, "UPDATE",
        {"source": "mobile", "action": "reject", "reason": payload.reason},
    )
    return {"detail_account_id": detail_account_id, "status_code": "INACTIVE"}


def _ensure_customer_in_company(detail_account_id: int, company_id: int) -> None:
    customers_by_id = {c["detail_account_id"]: c for c in dimensions_service.list_customers(company_id)}
    if detail_account_id not in customers_by_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="مشتری یافت نشد.")


def _address_to_dict(a) -> dict:
    return {
        "address_id": a.address_id, "address_type_code": a.address_type_code, "line1": a.line1, "city": a.city,
        "province": a.province, "postal_code": a.postal_code, "is_default": a.is_default,
        "gps_latitude": str(a.gps_latitude) if a.gps_latitude is not None else None,
        "gps_longitude": str(a.gps_longitude) if a.gps_longitude is not None else None,
        "geofence_radius_meters": a.geofence_radius_meters,
    }


@router.get("/{detail_account_id}/addresses")
def list_customer_addresses(detail_account_id: int, ctx: AuthContext = Depends(get_current_context)) -> list[dict]:
    """طبقِ بازبینیِ ساختارِ «تعریفِ مشتری» (R216، بخشِ ۲ -- چندآدرسیِ
    واقعی + GeoFence): برخلافِ فیلدِ تکیِ address/gps_latitude رویِ خودِ
    مشتری (که هم‌چنان برایِ سازگاریِ عقب‌رو باقی می‌ماند)، این‌جا آدرسِ
    چندگانه با نوع (دفتر/فروشگاه/انبار/تحویل/صورتحساب/مرجوعی) و
    GPS/شعاعِ GeoFendِ مستقلِ هر آدرس برمی‌گردد."""
    _ensure_customer_in_company(detail_account_id, ctx.company_id)
    return [_address_to_dict(a) for a in partners_service.list_party_addresses(detail_account_id)]


@router.post("/{detail_account_id}/addresses")
def create_customer_address(
    detail_account_id: int, payload: PartyAddressRequest,
    ctx: AuthContext = Depends(require_permission(FORM_CUSTOMER_MANAGEMENT, "EDIT")),
) -> dict:
    _ensure_customer_in_company(detail_account_id, ctx.company_id)
    try:
        address_id = partners_service.add_party_address(
            detail_account_id, payload.address_type_code, payload.line1, city=payload.city,
            province=payload.province, postal_code=payload.postal_code, is_default=payload.is_default,
            gps_latitude=payload.gps_latitude, gps_longitude=payload.gps_longitude,
            geofence_radius_meters=payload.geofence_radius_meters,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    audit_log.record(
        ctx.company_id, ctx.user_id, "PartyAddress", address_id, "CREATE",
        {"source": "mobile", "customer_detail_account_id": detail_account_id, "address_type_code": payload.address_type_code},
    )
    return {"address_id": address_id}


@router.put("/{detail_account_id}/addresses/{address_id}")
def update_customer_address(
    detail_account_id: int, address_id: int, payload: PartyAddressRequest,
    ctx: AuthContext = Depends(require_permission(FORM_CUSTOMER_MANAGEMENT, "EDIT")),
) -> dict:
    _ensure_customer_in_company(detail_account_id, ctx.company_id)
    try:
        partners_service.update_party_address(
            address_id, detail_account_id, payload.address_type_code, payload.line1, city=payload.city,
            province=payload.province, postal_code=payload.postal_code, is_default=payload.is_default,
            gps_latitude=payload.gps_latitude, gps_longitude=payload.gps_longitude,
            geofence_radius_meters=payload.geofence_radius_meters,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    audit_log.record(
        ctx.company_id, ctx.user_id, "PartyAddress", address_id, "UPDATE",
        {"source": "mobile", "customer_detail_account_id": detail_account_id},
    )
    return {"address_id": address_id}


@router.delete("/{detail_account_id}/addresses/{address_id}")
def delete_customer_address(
    detail_account_id: int, address_id: int,
    ctx: AuthContext = Depends(require_permission(FORM_CUSTOMER_MANAGEMENT, "EDIT")),
) -> dict:
    _ensure_customer_in_company(detail_account_id, ctx.company_id)
    try:
        partners_service.delete_party_address(address_id, detail_account_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    audit_log.record(
        ctx.company_id, ctx.user_id, "PartyAddress", address_id, "DELETE",
        {"source": "mobile", "customer_detail_account_id": detail_account_id},
    )
    return {"address_id": address_id}
