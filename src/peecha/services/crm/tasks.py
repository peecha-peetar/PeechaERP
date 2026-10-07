"""مرکز کارها: فعالیت‌های باز کاربر در سبدهای «معوق / امروز / فردا / این هفته / بعداً» به‌علاوهٔ صف‌های واقعی ERP
برای امروز (ویزیت‌های برنامه‌ریزی‌شده، سفارش‌های فروش منتظر، وصول‌های سررسیدشده) — همه از جدول‌های موجود."""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field

from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.accounting import DetailAccount
from peecha.db.models.commercial import CommercialDocument, VisitPlan
from peecha.services import commercial_settlements as settlements_service
from peecha.services import field_sales as field_sales_service
from peecha.services.crm import activities as act_service

BUCKETS = (("overdue", "معوق"), ("today", "امروز"), ("tomorrow", "فردا"), ("week", "این هفته"), ("later", "بعداً"),
           ("no_date", "بدون تاریخ"))
_OPEN_ORDER_STATUSES = ("DRAFT", "CONFIRMED", "APPROVED")


@dataclass
class TaskCenter:
    buckets: dict[str, list[act_service.ActivityRow]]
    planned_visits: list[dict] = field(default_factory=list)
    pending_orders: list[dict] = field(default_factory=list)
    due_collections: list[dict] = field(default_factory=list)

    def count(self, bucket: str) -> int:
        return len(self.buckets.get(bucket, []))

    def today_by_type(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for a in self.buckets.get("today", []):
            out[a.activity_type_code] = out.get(a.activity_type_code, 0) + 1
        return out


def bucket_of(due: datetime.date | None, today: datetime.date) -> str:
    if due is None:
        return "no_date"
    if due < today:
        return "overdue"
    if due == today:
        return "today"
    if due == today + datetime.timedelta(days=1):
        return "tomorrow"
    if due <= today + datetime.timedelta(days=7):
        return "week"
    return "later"


def _user_customers(session, company_id: int, user_id: int) -> list[int]:
    """مشتریانی که برنامهٔ ویزیت فعالشان به این کاربر واگذار شده (همان قاعدهٔ is_customer_assigned_to_user)."""
    return list(session.scalars(select(VisitPlan.customer_detail_account_id).where(
        VisitPlan.company_id == company_id, VisitPlan.assigned_visitor_user_id == user_id, VisitPlan.is_active.is_(True)).distinct()))


def task_center(company_id: int, user_id: int | None = None, today: datetime.date | None = None,
                include_erp_queues: bool = True) -> TaskCenter:
    """user_id=None یعنی همهٔ کاربران (نمای مدیر)."""
    today = today or datetime.date.today()
    rows = act_service.list_activities(company_id, assigned_to_user_id=user_id, open_only=True, limit=2000)
    buckets: dict[str, list] = {key: [] for key, _label in BUCKETS}
    for r in rows:
        buckets[bucket_of(r.due_date, today)].append(r)
    for key in buckets:
        buckets[key].sort(key=lambda a: (a.due_date or datetime.date.max, a.priority_code != "CRITICAL",
                                         a.priority_code != "HIGH", a.activity_id))
    tc = TaskCenter(buckets=buckets)
    if not include_erp_queues:
        return tc
    weekday = today.weekday()  # هم‌الگو با VisitPlan.visit_day_of_week
    plans = field_sales_service.list_visit_plans(company_id, visitor_user_id=user_id, visit_day_of_week=weekday, active_only=True)
    done = {v.customer_detail_account_id for v in field_sales_service.list_customer_visits(
        company_id, visitor_user_id=user_id, date_from=today, date_to=today)}
    with new_session() as session:
        names = dict(session.execute(select(DetailAccount.detail_account_id, DetailAccount.name).where(
            DetailAccount.detail_account_id.in_({p.customer_detail_account_id for p in plans} or {-1}))).all())
        tc.planned_visits = [{"customer_detail_account_id": p.customer_detail_account_id,
                              "customer_name": names.get(p.customer_detail_account_id, ""), "sequence": p.sequence_order,
                              "visited": p.customer_detail_account_id in done} for p in plans]
        scope = _user_customers(session, company_id, user_id) if user_id else None
        q = select(CommercialDocument.document_id, CommercialDocument.document_no, CommercialDocument.status_code,
                   CommercialDocument.document_date, CommercialDocument.total_amount, DetailAccount.name,
                   CommercialDocument.counterparty_detail_account_id).join(
            DetailAccount, DetailAccount.detail_account_id == CommercialDocument.counterparty_detail_account_id).where(
            CommercialDocument.company_id == company_id, CommercialDocument.document_type_code == "SALES_ORDER",
            CommercialDocument.status_code.in_(_OPEN_ORDER_STATUSES))
        if user_id:
            q = q.where((CommercialDocument.created_by_user_id == user_id)
                        | CommercialDocument.counterparty_detail_account_id.in_(scope or [-1]))
        tc.pending_orders = [{"document_id": d, "document_no": no, "status_code": st, "document_date": dt, "total_amount": amt,
                              "customer_name": name, "customer_detail_account_id": cid}
                             for d, no, st, dt, amt, name, cid in session.execute(q.order_by(CommercialDocument.document_date).limit(200))]
    unsettled = settlements_service.list_unsettled_invoices_bulk(company_id, counterparty_ids=scope if user_id else None,
                                                                 due_on_or_before=today)
    with new_session() as session:
        names = dict(session.execute(select(DetailAccount.detail_account_id, DetailAccount.name).where(
            DetailAccount.detail_account_id.in_({u.counterparty_detail_account_id for u in unsettled} or {-1}))).all())
    tc.due_collections = [{"document_id": u.document_id, "due_date": u.due_date, "remaining_amount": u.remaining_amount,
                           "customer_detail_account_id": u.counterparty_detail_account_id,
                           "customer_name": names.get(u.counterparty_detail_account_id, ""),
                           "days_overdue": (today - u.due_date).days if u.due_date else 0} for u in unsettled]
    return tc
