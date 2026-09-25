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
from peecha.services import commercial_pricing as pricing_service
from peecha.services import commercial_settlements as settlements_service
from peecha.services import currencies as currencies_service
from peecha.services import inventory_locations as locations_service
from peecha.services import roles as roles_service
from peecha_api import audit_log
from peecha_api.deps import AuthContext, get_current_context, get_idempotency_key
from peecha_api.idempotency import IdempotentReplay, run_idempotent
from peecha_api.permissions import FORM_COLD_DISTRIBUTION, FORM_HOT_DISTRIBUTION
from peecha_api.schemas import OrderCreateRequest

router = APIRouter(prefix="/orders", tags=["orders"])

# طبقِ nav_catalog.py: پخشِ سرد (سفارش‌گیریِ SALES_ORDER) و پخشِ گرم
# (فاکتورِ آنیِ SALES_INVOICE) دو فرمِ RBACِ جداگانه‌یِ از قبل تعریف‌شده
# دارند -- هرکدام طبقِ نوعِ سندِ درخواستی چک می‌شوند.
_FORM_BY_TYPE = {"SALES_ORDER": FORM_COLD_DISTRIBUTION, "SALES_INVOICE": FORM_HOT_DISTRIBUTION}


@router.post("")
def create_order(
    payload: OrderCreateRequest,
    ctx: AuthContext = Depends(get_current_context),
    idempotency_key: str | None = Depends(get_idempotency_key),
) -> dict:
    if payload.document_type_code not in _FORM_BY_TYPE:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="نوعِ سند برایِ اپِ موبایل فقط سفارش یا فاکتورِ فروش می‌تواند باشد.")
    if not payload.lines:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="حداقل یک ردیف لازم است.")
    form_code = _FORM_BY_TYPE[payload.document_type_code]
    if not roles_service.user_has_permission(ctx.user_id, ctx.company_id, form_code, "CREATE"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"دسترسیِ ثبتِ {form_code} وجود ندارد.")

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
    # طبقِ باگِ واقعیِ کشف‌شده رویِ گوشیِ فیزیکیِ کاربر (R196، R198): مقادیرِ
    # warehouse_id/channel_code/currency_id که برایِ این شرکتِ خاص معتبر
    # نباشند، بدونِ این چک مستقیم به یک ForeignKeyViolationِ خامِ
    # SQLAlchemy می‌رسیدند (خطایِ ۵۰۰ِ بی‌پیام) -- که در SyncEngineِ
    # موبایل (فقط ۴xx حذف‌شدنی از صف است) کلِ صفِ آفلاین را برایِ همیشه
    # قفل می‌کرد، چون این اقدام هیچ‌وقت با تلاشِ دوباره موفق نمی‌شود.
    if locations_service.get_warehouse(payload.warehouse_id, ctx.company_id) is None:
        raise ValueError("انبارِ انتخاب‌شده برایِ این شرکت معتبر نیست.")
    if not any(ch.channel_code == payload.channel_code for ch in pricing_service.list_channels(ctx.company_id)):
        raise ValueError("کانالِ فروشِ انتخاب‌شده برایِ این شرکت معتبر نیست.")
    if not any(c.currency_id == payload.currency_id for c in currencies_service.list_all_currencies()):
        raise ValueError("ارزِ انتخاب‌شده معتبر نیست.")

    document_id = documents_service.create_document(
        ctx.company_id, ctx.user_id, payload.document_type_code, datetime.date.today(),
        documents_service.DocumentHeaderFields(
            counterparty_detail_account_id=payload.counterparty_detail_account_id,
            currency_id=payload.currency_id, warehouse_id=payload.warehouse_id, channel_code=payload.channel_code,
            cost_center_detail_account_id=payload.cost_center_detail_account_id,
            project_detail_account_id=payload.project_detail_account_id,
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
        # طبقِ درخواستِ صریحِ کاربر («نوعِ تسویه در پخشِ گرم باید همانندِ
        # انواعِ تسویه در دسکتاپ باشد»): ویزیتور روشِ واقعیِ دریافت (نقد/
        # بانکی/چک/... -- هرچه مدیر برایِ موبایل فعال کرده باشد) و مبلغِ
        # هر روش را انتخاب می‌کند؛ مانده‌یِ پوشش‌داده‌نشده خودکار نسیه
        # می‌شود (save_settlement_plan). None یعنی موبایلِ آپدیت‌نشده
        # (سازگاریِ عقب‌رو با رفتارِ قبلی: ۱۰۰٪ نقدی).
        if payload.settlement_lines is None:
            settlements_service.auto_approve_full_cash_settlement_plan(document_id, ctx.company_id, ctx.user_id)
        else:
            enabled_codes = settlements_service.list_enabled_mobile_settlement_method_codes(ctx.company_id)
            for line in payload.settlement_lines:
                if line.method_code not in enabled_codes:
                    raise ValueError(f"روشِ تسویهٔ «{line.method_code}» برایِ موبایل فعال نیست.")
            settlement_lines = [(line.method_code, line.amount, None) for line in payload.settlement_lines]
            settlements_service.auto_approve_settlement_plan(document_id, ctx.company_id, ctx.user_id, settlement_lines)
        documents_service.post_document(document_id, ctx.company_id, ctx.user_id)
    audit_log.record(
        ctx.company_id, ctx.user_id, "CommercialDocument", document_id, "CREATE",
        {"source": "mobile", "document_type_code": payload.document_type_code, "line_count": len(line_ids)},
    )
    return document_id, line_ids
