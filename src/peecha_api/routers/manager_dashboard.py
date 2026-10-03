"""داشبوردِ مدیریتِ فروش (Phase 7) -- فقط برایِ کاربرانِ مدیر
(roles_service.is_manager، همان قاعده‌یِ توابعِ مدیریتیِ دیگرِ این API).
رویِ همان توابعِ تجمیعیِ سرویس‌هایِ موجود (field_sales/commercial_documents/
treasury/commercial_partners) -- بدونِ منطقِ حسابداری/گزارش‌گیریِ تازه.

طبقِ R189: فیلترِ منطقه/مسیر (route_detail_account_id) اضافه شد -- هر
سه منبع (ویزیت/سفارش/وصول) با joinِ CustomerProfile.distribution_route_detail_account_id
فیلتر می‌شوند (پیاده‌سازیِ واقعی در field_sales/commercial_documents/treasury)."""

from __future__ import annotations

import datetime

from fastapi import APIRouter, Depends, HTTPException, status

from peecha.services import commercial_documents as documents_service
from peecha.services import commercial_partners as partners_service
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import field_sales as field_sales_service
from peecha.services import roles as roles_service
from peecha.services import treasury as treasury_service
from peecha.services import users as users_service
from peecha_api.deps import AuthContext, get_current_context

router = APIRouter(prefix="/manager/dashboard", tags=["manager"])

_ORDER_TYPE_CODES = ("SALES_ORDER", "SALES_INVOICE")


def _require_manager(ctx: AuthContext) -> None:
    if not roles_service.is_manager(ctx.user_id, ctx.company_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="این گزارش فقط برایِ مدیر در دسترس است.")


@router.get("/routes")
def list_routes(ctx: AuthContext = Depends(get_current_context)) -> list[dict]:
    """فهرستِ مسیرهایِ توزیعِ تعریف‌شده -- برایِ پرکردنِ فیلترِ منطقه/مسیرِ
    داشبورد در اپِ موبایل."""
    _require_manager(ctx)
    dimension_type_id = dimensions_service.get_specialized_dimension_type_id(
        ctx.company_id, dimensions_service.DISTRIBUTION_ROUTE_CODE,
    )
    routes = dimensions_service.list_leaf_detail_accounts(ctx.company_id, dimension_type_id)
    return [{"detail_account_id": r.detail_account_id, "code": r.code, "name": r.name} for r in routes]


@router.get("")
def get_dashboard(
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
    visitor_user_id: int | None = None,
    route_detail_account_id: int | None = None,
    ctx: AuthContext = Depends(get_current_context),
) -> dict:
    _require_manager(ctx)
    today = datetime.date.today()
    date_from = date_from or today
    date_to = date_to or today
    if date_from > date_to:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="date_from نمی‌تواند بعدِ date_to باشد.")

    visits = field_sales_service.list_customer_visits(
        ctx.company_id, visitor_user_id=visitor_user_id, date_from=date_from, date_to=date_to,
        route_detail_account_id=route_detail_account_id,
    )
    completed_visits = sum(1 for v in visits if v.status_code == "COMPLETED")

    order_summary = documents_service.summarize_documents_for_company(
        ctx.company_id, date_from, date_to, _ORDER_TYPE_CODES, created_by_user_id=visitor_user_id,
        route_detail_account_id=route_detail_account_id,
    )
    collection_amount = treasury_service.sum_voucher_amount_for_company(
        ctx.company_id, date_from, date_to, "RECEIPT", created_by_user_id=visitor_user_id,
        route_detail_account_id=route_detail_account_id,
    )
    average_order_value = (
        order_summary.total_amount / order_summary.document_count if order_summary.document_count else 0
    )
    collection_rate = (
        collection_amount / order_summary.total_amount if order_summary.total_amount else 0
    )
    conversion_rate = (order_summary.document_count / completed_visits) if completed_visits else 0

    new_customer_count = partners_service.count_new_customers(ctx.company_id, date_from, date_to)
    customers_without_purchase_count = partners_service.count_customers_without_purchase(ctx.company_id)

    by_visitor = []
    if visitor_user_id is None:
        visitor_ids = set(documents_service.list_document_creators(ctx.company_id, date_from, date_to, _ORDER_TYPE_CODES))
        visitor_ids.update({v.visitor_user_id for v in visits})
        names_by_id = {u.user_id: u.full_name for u in users_service.list_users()}
        for uid in sorted(visitor_ids):
            user_visits = [v for v in visits if v.visitor_user_id == uid]
            user_order_summary = documents_service.summarize_documents_for_company(
                ctx.company_id, date_from, date_to, _ORDER_TYPE_CODES, created_by_user_id=uid,
                route_detail_account_id=route_detail_account_id,
            )
            user_collection = treasury_service.sum_voucher_amount_for_company(
                ctx.company_id, date_from, date_to, "RECEIPT", created_by_user_id=uid,
                route_detail_account_id=route_detail_account_id,
            )
            by_visitor.append(
                {
                    "user_id": uid,
                    "full_name": names_by_id.get(uid, f"کاربرِ #{uid}"),
                    "visit_count": len(user_visits),
                    "visit_completed_count": sum(1 for v in user_visits if v.status_code == "COMPLETED"),
                    "order_count": user_order_summary.document_count,
                    "sales_amount": str(user_order_summary.total_amount),
                    "collection_amount": str(user_collection),
                }
            )

    return {
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "sales_amount": str(order_summary.total_amount),
        "order_count": order_summary.document_count,
        "average_order_value": str(average_order_value),
        "collection_amount": str(collection_amount),
        "collection_rate": str(collection_rate),
        "visit_count": len(visits),
        "visit_completed_count": completed_visits,
        "visit_to_order_conversion": str(conversion_rate),
        "new_customer_count": new_customer_count,
        "customers_without_purchase_count": customers_without_purchase_count,
        "by_visitor": by_visitor,
    }
