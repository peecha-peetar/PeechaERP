"""خلاصه‌یِ صفحه‌یِ خانه‌یِ اپِ موبایل («امروز: N ویزیت، N سفارش، مبلغِ
فروش، مبلغِ وصول، ویزیتِ بعدی») -- رویِ همان services/field_sales.py،
commercial_documents.py، treasury.py موجود؛ بدونِ محاسبه‌یِ تازه‌ای که
از قبل نبوده، فقط تجمیعِ همان توابع برایِ یک درخواستِ تکی."""

from __future__ import annotations

import datetime

from fastapi import APIRouter, Depends

from peecha.services import commercial_documents as documents_service
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import field_sales as field_sales_service
from peecha.services import treasury as treasury_service
from peecha_api.deps import AuthContext, get_current_context

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

_ORDER_TYPE_CODES = ("SALES_ORDER", "SALES_INVOICE")
# طبقِ رفعِ باگِ واقعی («در پخشِ سرد سفارش ثبت کردم ولی در پخشِ گرم نشون
# میده -- این دو تا کاملاً مجزا باید باشه»): هر حالت فقط سندِ خودش --
# پخشِ گرم = فاکتورِ آنی رویِ کانالِ VAN_SALES، پخشِ سرد = سفارش رویِ
# کانالِ PRE_SALES. بدونِ mode (نسخه‌هایِ قدیمیِ اپ) رفتارِ قبلی حفظ می‌شود.
_DOC_TYPES_BY_MODE = {"VAN_SALES": ("SALES_INVOICE",), "PRE_SALES": ("SALES_ORDER",)}


@router.get("/today")
def today_summary(mode: str | None = None, ctx: AuthContext = Depends(get_current_context)) -> dict:
    today = datetime.date.today()
    channel_type_code = mode if mode in _DOC_TYPES_BY_MODE else None

    visits_today = field_sales_service.list_customer_visits(
        ctx.company_id, visitor_user_id=ctx.user_id, date_from=today, date_to=today,
    )
    completed_count = sum(1 for v in visits_today if v.status_code == "COMPLETED")

    order_summary = documents_service.summarize_documents_for_user_on_date(
        ctx.company_id, ctx.user_id, today, _DOC_TYPES_BY_MODE.get(channel_type_code, _ORDER_TYPE_CODES),
        channel_type_code=channel_type_code,
    )
    collection_amount = treasury_service.sum_voucher_amount_for_user_on_date(
        ctx.company_id, ctx.user_id, today, "RECEIPT",
    )

    weekday = today.weekday()  # پایتون: دوشنبه=0 ... یکشنبه=6؛ هم‌الگو با VisitPlan.visit_day_of_week
    plans_today = field_sales_service.list_visit_plans(
        ctx.company_id, visitor_user_id=ctx.user_id, visit_day_of_week=weekday, active_only=True,
    )
    # visits_today از checked_in_at نزولی مرتب است (list_customer_visits) --
    # پس اولین موردِ هر مشتری، تازه‌ترین ویزیتِ همان مشتری در امروز است.
    latest_visit_by_customer: dict[int, str] = {}
    for v in visits_today:
        latest_visit_by_customer.setdefault(v.customer_detail_account_id, v.status_code)

    customers_by_id = {c["detail_account_id"]: c for c in dimensions_service.list_customers(ctx.company_id)}
    today_route = []
    next_visit = None
    for plan in plans_today:
        customer = customers_by_id.get(plan.customer_detail_account_id)
        if customer is None:
            continue
        visit_status = latest_visit_by_customer.get(plan.customer_detail_account_id)
        state = {"COMPLETED": "DONE", "IN_PROGRESS": "CURRENT", "SKIPPED": "SKIPPED"}.get(visit_status, "UPCOMING")
        entry = {
            "visit_plan_id": plan.visit_plan_id,
            "customer_detail_account_id": customer["detail_account_id"],
            "customer_name": customer["name"],
            "state": state,
        }
        today_route.append(entry)
        if next_visit is None and state == "UPCOMING":
            next_visit = {
                "customer_detail_account_id": customer["detail_account_id"],
                "customer_name": customer["name"],
                "visit_plan_id": plan.visit_plan_id,
            }

    return {
        "visit_count": len(visits_today),
        "visit_completed_count": completed_count,
        "order_count": order_summary.document_count,
        "sales_amount": str(order_summary.total_amount),
        "collection_amount": str(collection_amount),
        "next_visit": next_visit,
        "today_route": today_route,
    }
