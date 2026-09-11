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
    ctx: AuthContext = Depends(get_current_context),
) -> PriceResolveResponse:
    profile = partners_service.get_customer_profile(counterparty_detail_account_id)
    price_list_id = profile.default_price_list_id if profile is not None else None

    try:
        resolved = pricing_service.resolve_price(
            ctx.company_id, counterparty_detail_account_id, item_id, uom_id, quantity,
            price_list_id, document_type_code, datetime.date.today(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return PriceResolveResponse(
        unit_price=resolved.unit_price, source=resolved.source, discount_amount=resolved.discount_amount,
    )
