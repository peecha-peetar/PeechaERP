"""ثبتِ سفارش/فاکتور از موبایل -- روی همان services/commercial_documents.py
موجود سوار می‌شود، بدونِ بازنویسیِ منطقِ قیمت‌گذاری/تخفیف/مالیات. طبقِ
تفاوتِ دو ماژول: پخشِ سرد (SALES_ORDER) فقط سفارش می‌سازد و همان‌جا
متوقف می‌شود (تبدیل به فاکتور بعداً در خودِ ERP)؛ پخشِ گرم (SALES_INVOICE
با post_immediately=True) بلافاصله تاییدوپست می‌شود چون کالا همان‌لحظه
از خودرو تحویل داده شده."""

from __future__ import annotations

import datetime

from fastapi import APIRouter, Depends, HTTPException, status

from peecha.services import commercial_documents as documents_service
from peecha.services import commercial_settlements as settlements_service
from peecha_api.deps import AuthContext, get_current_context, get_idempotency_key
from peecha_api.idempotency import IdempotentReplay, run_idempotent
from peecha_api.schemas import OrderCreateRequest

router = APIRouter(prefix="/orders", tags=["orders"])

_ALLOWED_TYPES = ("SALES_ORDER", "SALES_INVOICE")


@router.post("")
def create_order(
    payload: OrderCreateRequest,
    ctx: AuthContext = Depends(get_current_context),
    idempotency_key: str | None = Depends(get_idempotency_key),
) -> dict:
    if payload.document_type_code not in _ALLOWED_TYPES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="نوعِ سند برایِ اپِ موبایل فقط سفارش یا فاکتورِ فروش می‌تواند باشد.")
    if not payload.lines:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="حداقل یک ردیف لازم است.")

    try:
        return run_idempotent(
            idempotency_key, "POST /orders", ctx.user_id, ctx.company_id,
            status.HTTP_200_OK, lambda: _create_order(payload, ctx),
            lambda result: {"document_id": result[0], "line_ids": result[1]},
        )
    except IdempotentReplay as replay:
        return replay.body
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


def _create_order(payload: OrderCreateRequest, ctx: AuthContext) -> tuple[int, list[int]]:
    document_id = documents_service.create_document(
        ctx.company_id, ctx.user_id, payload.document_type_code, datetime.date.today(),
        documents_service.DocumentHeaderFields(
            counterparty_detail_account_id=payload.counterparty_detail_account_id,
            currency_id=payload.currency_id, warehouse_id=payload.warehouse_id, channel_code=payload.channel_code,
        ),
    )
    # line_ids دقیقاً هم‌ترتیب با payload.lines برگردانده می‌شود -- طبقِ
    # نیازِ R133: اپِ موبایل برایِ تاییدِ تحویلِ همین سفارش (پخشِ گرم) به
    # document_line_id هر ردیف نیاز دارد که فقط بعدِ همین ثبت مشخص می‌شود.
    line_ids: list[int] = []
    for line in payload.lines:
        line_ids.append(
            documents_service.add_line(
                document_id, ctx.company_id, item_id=line.item_id, uom_id=line.uom_id,
                quantity=line.quantity, quantity_base=line.quantity, unit_price=line.unit_price,
            )
        )
    documents_service.confirm_document(document_id, ctx.company_id, ctx.user_id)
    if payload.document_type_code == "SALES_INVOICE" and payload.post_immediately:
        # طبقِ محدودیتِ شناخته‌شده: ثبتِ نهاییِ فاکتورِ غیرِPOS نیازمندِ
        # نقشه‌یِ تسویه‌یِ تاییدشده است (commercial_settlements.py).
        # وصولِ واقعیِ چندروشیِ درمحل (نقد/کارت/چک/ترکیبی -- بخشِ ۸ِ
        # سندِ کاربر) هنوز به این اندپوینت وصل نشده و یک کارِ جداگانه‌یِ
        # آینده است؛ فعلاً برایِ بازنکردنِ مسیرِ ثبتِ نهایی، به‌صورتِ
        # موقت تمامِ مبلغ نقدی فرض و خودکار تاییدمی‌شود.
        settlements_service.auto_approve_full_cash_settlement_plan(document_id, ctx.company_id, ctx.user_id)
        documents_service.post_document(document_id, ctx.company_id, ctx.user_id)
    return document_id, line_ids
