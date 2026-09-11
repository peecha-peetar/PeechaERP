"""Pull: دلتایِ داده‌یِ لازم برایِ اپِ موبایلِ همین ویزیتور -- فقط
مسیر/مشتریانِ خودش، نه کلِ دیتابیس. طبقِ طرحِ تاییدشده (نسخهٔ اول،
ساده): فعلاً «همیشه همه‌چیز» می‌کشد، نه دلتایِ واقعی بر اساسِ نسخه --
موتورِ Change-Data-Captureِ واقعی یک گامِ جداگانه‌یِ آینده است اگر
حجمِ داده مشکل‌ساز شود."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from peecha.services import detail_dimensions as dimensions_service
from peecha.services import field_sales as field_sales_service
from peecha.services import inventory_catalog as catalog_service
from peecha_api.deps import AuthContext, get_current_context

router = APIRouter(prefix="/sync", tags=["sync"])


@router.get("/pull")
def pull(ctx: AuthContext = Depends(get_current_context)) -> dict:
    visit_plans = field_sales_service.list_visit_plans(ctx.company_id, visitor_user_id=ctx.user_id, active_only=True)
    customer_ids = {p.customer_detail_account_id for p in visit_plans}
    customers_by_id = {c["detail_account_id"]: c for c in dimensions_service.list_customers(ctx.company_id)}

    items = catalog_service.list_items(ctx.company_id, active_only=True)

    return {
        "visit_plans": [
            {
                "visit_plan_id": p.visit_plan_id,
                "customer_detail_account_id": p.customer_detail_account_id,
                "visit_day_of_week": p.visit_day_of_week,
                "sequence_order": p.sequence_order,
            }
            for p in visit_plans
        ],
        "customers": [
            {
                "detail_account_id": customer_id,
                "code": customers_by_id[customer_id]["code"],
                "name": customers_by_id[customer_id]["name"],
                "gps_latitude": customers_by_id[customer_id].get("gps_latitude"),
                "gps_longitude": customers_by_id[customer_id].get("gps_longitude"),
            }
            for customer_id in customer_ids
            if customer_id in customers_by_id
        ],
        # طبقِ درخواستِ صریح: قیمت این‌جا برنمی‌گردد -- تعیینِ قیمتِ
        # واقعی وابسته به کانال/فهرستِ‌قیمتِ مشتری است (commercial_pricing.py،
        # منطقِ چندلایه‌یِ از قبل تست‌شده) و اتصالِ درستش به اپِ موبایل در
        # فازِ بعد (هم‌زمان با ثبتِ سفارشِ واقعی از موبایل) انجام می‌شود.
        "items": [
            {"item_id": it.item_id, "code": it.code, "name": it.name, "base_uom_id": it.base_uom_id, "base_uom_code": it.base_uom_code}
            for it in items
        ],
    }
