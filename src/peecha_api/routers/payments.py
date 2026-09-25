"""وصول/دریافتِ وجه از موبایل (Collection، R134) -- رویِ همان
services/treasury.create_treasury_voucher موجود سوار می‌شود (بدونِ
بازنویسیِ منطقِ حسابداریِ چندروشی/چندارزی)؛ فقط طرفِ‌حسابِ مشتری از
رویِ شناسهٔ تفصیلی resolve می‌شود (treasury.resolve_counterparty_for_detail_account)
چون کلاینتِ موبایل کدِ معینِ نگاشته‌شده را نمی‌داند. جهت همیشه RECEIPT
است -- ویزیتور/راننده فقط از مشتری وصول می‌کند، نه پرداخت به او."""

from __future__ import annotations

import datetime
import decimal

from fastapi import APIRouter, Depends, HTTPException, status

from peecha.services import field_sales as field_sales_service
from peecha.services import roles as roles_service
from peecha.services import treasury as treasury_service
from peecha_api import audit_log
from peecha_api.deps import AuthContext, get_idempotency_key
from peecha_api.idempotency import IdempotentReplay, run_idempotent
from peecha_api.permissions import FORM_TREASURY_RECEIPT, require_permission
from peecha_api.schemas import PaymentCreateRequest

router = APIRouter(prefix="/payments", tags=["payments"])

_ALLOWED_METHODS = ("CASH", "BANK", "CHECK")


@router.post("")
def create_payment(
    payload: PaymentCreateRequest,
    ctx: AuthContext = Depends(require_permission(FORM_TREASURY_RECEIPT, "CREATE")),
    idempotency_key: str | None = Depends(get_idempotency_key),
) -> dict:
    if not payload.method_lines:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="حداقل یک ردیفِ روشِ وصول لازم است.")
    # طبقِ درخواستِ صریحِ کاربر («فقط مشتریانِ خودش»): مدیر از این محدودیت معاف است.
    if not roles_service.is_manager(ctx.user_id, ctx.company_id) and not field_sales_service.is_customer_assigned_to_user(
        ctx.company_id, payload.customer_detail_account_id, ctx.user_id
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="این مشتری به شما اختصاص داده نشده است.")
    for line in payload.method_lines:
        if line.method not in _ALLOWED_METHODS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="روشِ وصول برایِ اپِ موبایل فقط نقد/بانک/چک می‌تواند باشد.",
            )

    try:
        return run_idempotent(
            idempotency_key, "POST /payments", ctx.user_id, ctx.company_id,
            status.HTTP_200_OK, lambda: _create_payment(payload, ctx),
            lambda result: {"journal_entry_id": result.journal_entry_id, "temporary_no": result.temporary_no},
        )
    except IdempotentReplay as replay:
        return replay.body
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


def _create_payment(payload: PaymentCreateRequest, ctx: AuthContext):
    account_id, counterparty_details = treasury_service.resolve_counterparty_for_detail_account(
        ctx.company_id, "RECEIPT", payload.customer_detail_account_id
    )
    method_lines = [
        treasury_service.MethodLine(
            method=line.method,
            amount=line.amount,
            description=line.description,
            detail_account_id=line.detail_account_id,
            check_no=line.check_no,
            check_bank_name=line.check_bank_name,
            check_due_date=line.check_due_date,
            check_party_name=line.check_party_name,
        )
        for line in payload.method_lines
    ]
    description = payload.description or "وصولِ میدانی از اپِ موبایل"
    if payload.customer_visit_id is not None:
        # طبقِ محدودیتِ شناخته‌شده: سندِ خزانه‌داری فیلدِ ساختاریافته‌یِ
        # customer_visit_id ندارد (یک مهاجرتِ جداگانه‌یِ آینده لازم دارد)
        # -- فعلاً فقط در توضیحاتِ سند ثبت می‌شود تا ردِ بازدید گم نشود.
        description = f"{description} — بازدید #{payload.customer_visit_id}"
    result = treasury_service.create_treasury_voucher(
        ctx.company_id, ctx.user_id, "RECEIPT", account_id, counterparty_details,
        payload.document_date or datetime.date.today(), description, method_lines,
    )
    total_amount = sum((line.amount for line in payload.method_lines), decimal.Decimal(0))
    audit_log.record(
        ctx.company_id, ctx.user_id, "JournalEntry", result.journal_entry_id, "CREATE",
        {"source": "mobile_collection", "customer_detail_account_id": payload.customer_detail_account_id, "amount": str(total_amount)},
    )
    return result
