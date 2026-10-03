"""فهرستِ بدهکاران و وصولِ امروزِ خودِ کاربر (Phase 5، تکمیل) -- رویِ
همان field_sales.list_visit_plans (برایِ دانستنِ کدام مشتری‌ها به این
کاربر تخصیص دارند) + treasury.get_counterparty_balances_bulk/
list_vouchers_for_user_on_date موجود.

طبقِ رفعِ گزارشِ گمراه‌کننده‌یِ کاربر («همه‌یِ بدهکاران overdue نشان داده
می‌شوند»): Agingِ واقعی حالا رویِ همان
commercial_settlements.list_unsettled_invoices سوار است -- هر فاکتورِ
تسویه‌نشده due_dateِ واقعی‌اش (از rooی payment_term_days طرفِ‌حساب) را
دارد؛ اگر قدیمی‌ترین سررسیدِ بازِ مشتری گذشته باشد، «عقب‌افتاده» است."""

from __future__ import annotations

import datetime

from fastapi import APIRouter, Depends

from peecha.services import commercial_settlements as settlements_service
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

    today = datetime.date.today()
    earliest_due_by_customer: dict[int, datetime.date] = {}
    for status in settlements_service.list_unsettled_invoices(ctx.company_id, "SALES_INVOICE"):
        if status.counterparty_detail_account_id is None or status.due_date is None:
            continue
        current = earliest_due_by_customer.get(status.counterparty_detail_account_id)
        if current is None or status.due_date < current:
            earliest_due_by_customer[status.counterparty_detail_account_id] = status.due_date

    debtors = []
    for customer_id in customer_ids:
        balance = balances.get(customer_id)
        customer = customers_by_id.get(customer_id)
        if balance is None or customer is None:
            continue
        amount, nature = balance
        if nature != "بدهکار" or amount <= 0:
            continue
        earliest_due_date = earliest_due_by_customer.get(customer_id)
        debtors.append(
            {
                "detail_account_id": customer_id,
                "code": customer["code"],
                "name": customer["name"],
                "balance_amount": str(amount),
                # None یعنی «هیچ فاکتورِ سررسیددارِ بازی نیست» (مثلاً
                # فاکتور بدونِ مهلتِ پرداخت یا اصلاً فاکتورِ باز ندارد) --
                # نه «عقب‌افتاده» و نه «در مهلت»، صرفاً نامشخص.
                "earliest_due_date": earliest_due_date.isoformat() if earliest_due_date else None,
                "is_overdue": earliest_due_date is not None and earliest_due_date < today,
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
