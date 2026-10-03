"""نقطهٔ اتصالِ موبایل به زیرساختِ Smart Sales (Phase 9) -- رویِ همان
services/smart_sales.py؛ همیشه enabled=false برمی‌گرداند تا مدلِ واقعی
وصل شود (طبقِ درخواستِ صریح: پیاده‌سازیِ واقعیِ AI در این فاز نیست)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from peecha.services import smart_sales as smart_sales_service
from peecha_api.deps import AuthContext, get_current_context

router = APIRouter(prefix="/ai", tags=["ai"])


@router.get("/reorder-suggestions/{customer_detail_account_id}")
def reorder_suggestions(customer_detail_account_id: int, ctx: AuthContext = Depends(get_current_context)) -> dict:
    if not smart_sales_service.is_smart_sales_enabled():
        return {"enabled": False, "suggestions": []}
    provider = smart_sales_service.get_smart_sales_provider()
    suggestions = provider.suggest_reorder_items(ctx.company_id, customer_detail_account_id)
    return {
        "enabled": True,
        "suggestions": [{"item_id": s.item_id, "reason": s.reason, "confidence": s.confidence} for s in suggestions],
    }
