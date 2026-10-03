"""تعیینِ قیمتِ معتبر برایِ یک ردیفِ سفارش از موبایل -- طبقِ محدودیتِ
شناخته‌شده‌یِ R131/R132 (که /sync/pull قیمت برنمی‌گرداند)، این‌جا دقیقاً
همان زنجیره‌یِ پنج‌گامیِ services/commercial_pricing.resolve_price
(قرارداد→فهرستِ قیمتِ پلکانی→تخفیف) صدا زده می‌شود -- بدونِ بازنویسیِ
منطق. فقط وقتی موبایل آنلاین است قابلِ‌استفاده است؛ در حالتِ آفلاین
همچنان ورودیِ دستیِ قیمت (طبقِ طراحیِ R132) به‌عنوانِ Fallback باقی
می‌ماند."""

from __future__ import annotations

import datetime
import decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status

from peecha.services import commercial_partners as partners_service
from peecha.services import commercial_pricing as pricing_service
from peecha.services import commercial_settlements as settlements_service
from peecha.services import inventory_catalog as catalog_service
from peecha.services import treasury as treasury_service
from peecha_api.deps import AuthContext, get_current_context
from peecha_api.schemas import PriceResolveResponse

router = APIRouter(prefix="/pricing", tags=["pricing"])


@router.get("/resolve", response_model=PriceResolveResponse)
def resolve_price(
    counterparty_detail_account_id: int = Query(...),
    item_id: int = Query(...),
    uom_id: int = Query(...),
    quantity: decimal.Decimal = Query(...),
    document_type_code: str = Query("SALES_INVOICE"),
    # طبقِ باگِ واقعیِ کشف‌شده (R210): بدونِ این، پیش‌نمایشِ مالیاتِ موبایل
    # همیشه رویِ اولویتِ «کالا» می‌ماند و اگر شرکت انبار را override کرده
    # باشد نادیده گرفته می‌شود -- دقیقاً هم‌الگو با resolve_default_tax_percentِ
    # دسکتاپ.
    warehouse_id: int | None = Query(None),
    # طبقِ درخواستِ صریحِ کاربر («تعریف بشه کدام قیمت برایِ کالاهایِ پخشِ
    # گرم و سرد و حتی تخفیف‌ها/پروموشن‌ها قابلِ‌انتخاب باشه»): اگر همین
    # کانال در تنظیماتِ بازرگانی فهرستِ قیمت/قاعدهٔ تخفیفِ پیش‌فرضِ خودش
    # را داشته باشد، به‌جایِ فهرستِ قیمتِ پیش‌فرضِ خودِ مشتری اعمال می‌شود.
    channel_code: str | None = Query(None),
    ctx: AuthContext = Depends(get_current_context),
) -> PriceResolveResponse:
    profile = partners_service.get_customer_profile(counterparty_detail_account_id)
    price_list_id = profile.default_price_list_id if profile is not None else None
    discount_rule_id = None
    if channel_code is not None:
        channel = pricing_service.get_channel(ctx.company_id, channel_code)
        if channel is not None:
            if channel.default_price_list_id is not None:
                price_list_id = channel.default_price_list_id
            discount_rule_id = channel.default_discount_rule_id

    try:
        resolved = pricing_service.resolve_price(
            ctx.company_id, counterparty_detail_account_id, item_id, uom_id, quantity,
            price_list_id, document_type_code, datetime.date.today(), discount_rule_id=discount_rule_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    tax_percent = catalog_service.resolve_default_tax_percent(ctx.company_id, item_id, warehouse_id)
    return PriceResolveResponse(
        unit_price=resolved.unit_price, source=resolved.source, discount_amount=resolved.discount_amount,
        tax_percent=tax_percent,
    )


@router.get("/channels")
def list_channels(
    channel_type_code: str | None = Query(None),
    ctx: AuthContext = Depends(get_current_context),
) -> list[dict]:
    """طبقِ باگِ واقعیِ کشف‌شده (R196): اپِ موبایل قبلاً مقدارِ channel_type_code
    («VAN_SALES») را به‌جایِ یک channel_codeِ واقعی مستقیم به سرور
    می‌فرستاد -- چون comm.channels.channel_code یک ستونِ جداست (مثلِ
    «VAN-1»)، نه همان کدِ نوع، این باعثِ شکستِ محدودیتِ کلیدِ خارجی
    می‌شد و سند اصلاً ساخته نمی‌شد. این اندپوینت کدهایِ واقعیِ کانالِ
    تعریف‌شده در همین شرکت را برمی‌گرداند تا موبایل یکی را انتخاب کند."""
    channels = pricing_service.list_channels(ctx.company_id)
    if channel_type_code is not None:
        channels = [c for c in channels if c.channel_type_code == channel_type_code]
    return [
        {
            "channel_code": c.channel_code, "name": c.name, "channel_type_code": c.channel_type_code,
            # طبقِ درخواستِ صریح («در تنظیماتِ موبایل مرکزِ هزینه/پروژه
            # تعیین شود»): پیش‌فرضِ ثابتِ همین کانال -- اگر تنظیم شده
            # باشد، اپِ موبایل بدونِ نمایشِ هیچ انتخاب‌گری، همین‌ها را در
            # هر سفارش می‌فرستد.
            "default_cost_center_detail_account_id": c.default_cost_center_detail_account_id,
            "default_project_detail_account_id": c.default_project_detail_account_id,
        }
        for c in channels
    ]


@router.get("/settlement-methods")
def list_settlement_methods(ctx: AuthContext = Depends(get_current_context)) -> list[dict]:
    """طبقِ درخواستِ صریحِ کاربر («نوعِ تسویه در پخشِ گرم باید همانندِ
    انواعِ تسویه در دسکتاپ باشد -- فقط جایی باشد که برخی را برایِ
    موبایل خاموش کنیم»): فقط روش‌هایِ فعال‌شده‌یِ موبایل برمی‌گردد."""
    result = []
    for m in settlements_service.list_mobile_settlement_methods(ctx.company_id):
        if not m.is_enabled:
            continue
        # طبقِ درخواستِ صریح («دقیقاً همون فیلدهایی که دسکتاپ داره»): ستونِ
        # «تفصیلی» (کدام صندوق/حسابِ بانکی) + پیش‌فرضِ همان روش.
        requires_detail, options = settlements_service.mobile_method_detail_options(ctx.company_id, m.method_code)
        default = settlements_service.get_pos_settlement_method_default(ctx.company_id, m.method_code)
        result.append({
            "method_code": m.method_code,
            "label": m.label,
            "requires_detail": requires_detail,
            "detail_options": [
                {"detail_account_id": o.detail_account_id, "code": o.code, "name": o.name or o.code} for o in options
            ],
            "default_detail_account_id": default.detail_account_id if default is not None else None,
        })
    return result


@router.get("/banks")
def list_banks(ctx: AuthContext = Depends(get_current_context)) -> list[dict]:
    """فهرستِ بانک‌ها برایِ فیلدِ «بانک» در ثبتِ چکِ دریافتی -- همان
    فهرستِ دسکتاپ (تنظیماتِ خزانه‌داری)."""
    return [{"bank_id": b.bank_id, "name": b.name} for b in treasury_service.list_banks(ctx.company_id, active_only=True)]
