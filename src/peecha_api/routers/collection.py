"""فهرستِ بدهکاران و وصولِ امروزِ خودِ کاربر (Phase 5، تکمیل) -- رویِ
همان field_sales.list_visit_plans (برایِ دانستنِ کدام مشتری‌ها به این
کاربر تخصیص دارند) + treasury.get_counterparty_balances_bulk/
list_vouchers_for_user_on_date موجود.

محدودیتِ شناخته‌شده: «وصولِ عقب‌افتاده» (overdue، بر اساسِ سررسیدِ هر
فاکتور) پیاده نشده -- نیازمندِ گزارشِ Agingِ واقعی (کدام فاکتورِ خاص
هنوز باز است) که موضوعِ جداگانه‌ای از ماندهٔ کلیِ حساب است."""

from __future__ import annotations

import datetime

from fastapi import APIRouter, Depends

from peecha.services import detail_dimensions as dimensions_service
from peecha.services import field_sales as field_sales_service
from peecha.services import treasury as treasury_service
from peecha_api.deps import AuthContext, get_current_context

router = APIRouter(prefix="/collection", tags=["collection"])


@router.get("/debtors")
def list_debtors(ctx: AuthContext = Depends(get_current_context)) -> list[dict]:
    plans = field_sales_service.list_visit_plans(ctx.company_id, visitor_user_id=ctx.user_id, active_only=True)
    customer_ids = list({p.customer_detail_account_id for p in plans})
    if not customer_ids:
        return []

    balances = treasury_service.get_counterparty_balances_bulk(ctx.company_id, customer_ids)
    customers_by_id = {c["detail_account_id"]: c for c in dimensions_service.list_customers(ctx.company_id)}

    debtors = []
    for customer_id in customer_ids:
        balance = balances.get(customer_id)
        customer = customers_by_id.get(customer_id)
        if balance is None or customer is None:
            continue
        amount, nature = balance
        if nature != "بدهکار" or amount <= 0:
            continue
        debtors.append(
            {
                "detail_account_id": customer_id,
                "code": customer["code"],
                "name": customer["name"],
                "balance_amount": str(amount),
            }
        )
    debtors.sort(key=lambda d: float(d["balance_amount"]), reverse=True)
    return debtors


@router.get("/today")
def list_today_collections(ctx: AuthContext = Depends(get_current_context)) -> list[dict]:
    rows = treasury_service.list_vouchers_for_user_on_date(ctx.company_id, ctx.user_id, datetime.date.today(), "RECEIPT")
    customers_by_id = {c["detail_account_id"]: c for c in dimensions_service.list_customers(ctx.company_id)}
    return [
        {
            "journal_entry_id": r.journal_entry_id,
            "customer_name": customers_by_id.get(r.counterparty_detail_account_id, {}).get("name") if r.counterparty_detail_account_id else None,
            "amount": str(r.amount),
            "description": r.description,
        }
        for r in rows
    ]
