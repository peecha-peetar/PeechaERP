"""فعالیت‌های CRM روی جدول واحد comm.customer_activities (تماس، جلسه، بازدید، پیگیری، ایمیل، پیام، وظیفه، یادآور،
یادداشت، شکایت). فعالیت به مشتری یا سرنخ وصل است و می‌تواند به فرصت، تیکت یا ویزیت موجود ارجاع دهد."""

from __future__ import annotations

import datetime
import decimal
from dataclasses import dataclass, field

from sqlalchemy import func, or_, select

from peecha.db.base import new_session
from peecha.db.models.accounting import DetailAccount
from peecha.db.models.commercial import CustomerActivity
from peecha.db.models.crm import Lead, Opportunity
from peecha.services.crm import common as c

_CLOSE_STATUSES = {"COMPLAINT": ("RESOLVED", "CANCELLED"), "OPPORTUNITY": ("WON", "LOST", "CANCELLED")}


@dataclass
class ActivityFields:
    activity_type_code: str
    subject: str
    customer_detail_account_id: int | None = None
    lead_id: int | None = None
    opportunity_id: int | None = None
    ticket_id: int | None = None
    customer_visit_id: int | None = None
    description: str | None = None
    due_date: datetime.date | None = None
    start_at: datetime.datetime | None = None
    duration_minutes: int | None = None
    priority_code: str = "NORMAL"
    assigned_to_user_id: int | None = None
    estimated_value: decimal.Decimal | None = None
    next_action: str | None = None
    next_action_date: datetime.date | None = None


@dataclass
class ActivityRow:
    activity_id: int
    activity_type_code: str
    type_label: str
    subject: str
    description: str | None
    status_code: str
    status_label: str
    priority_code: str
    due_date: datetime.date | None
    start_at: datetime.datetime | None
    duration_minutes: int | None
    customer_detail_account_id: int | None
    customer_name: str
    lead_id: int | None
    lead_name: str
    opportunity_id: int | None
    assigned_to_user_id: int | None
    assigned_name: str
    result_text: str | None
    next_action: str | None
    next_action_date: datetime.date | None
    created_at: datetime.datetime
    resolved_at: datetime.datetime | None
    extra: dict = field(default_factory=dict)

    @property
    def is_open(self) -> bool:
        return self.status_code in c.ACTIVITY_OPEN_STATUSES

    def is_overdue(self, today: datetime.date | None = None) -> bool:
        return self.is_open and self.due_date is not None and self.due_date < (today or datetime.date.today())


def _check_party(session, company_id: int, f: ActivityFields) -> None:
    if f.opportunity_id:
        opp = session.get(Opportunity, f.opportunity_id)
        if opp is None or opp.company_id != company_id:
            raise ValueError("فرصت فروش نامعتبر است.")
        f.customer_detail_account_id = f.customer_detail_account_id or opp.customer_detail_account_id
        f.lead_id = f.lead_id or (opp.lead_id if not f.customer_detail_account_id else None)
    if f.lead_id:
        lead = session.get(Lead, f.lead_id)
        if lead is None or lead.company_id != company_id:
            raise ValueError("سرنخ نامعتبر است.")
        f.customer_detail_account_id = f.customer_detail_account_id or lead.converted_customer_detail_account_id
    if f.customer_detail_account_id:
        da = session.get(DetailAccount, f.customer_detail_account_id)
        if da is None or da.company_id != company_id:
            raise ValueError("مشتری نامعتبر است.")
    if not f.customer_detail_account_id and not f.lead_id:
        raise ValueError("فعالیت باید به یک مشتری یا سرنخ مربوط باشد.")


def _validate(f: ActivityFields) -> None:
    if f.activity_type_code not in c.ACTIVITY_TYPES or f.activity_type_code == "OPPORTUNITY":
        raise ValueError("نوع فعالیت نامعتبر است.")
    if not (f.subject or "").strip():
        raise ValueError("موضوع فعالیت الزامی است.")
    if f.priority_code not in c.PRIORITIES:
        raise ValueError("اولویت نامعتبر است.")
    if f.duration_minutes is not None and f.duration_minutes < 0:
        raise ValueError("مدت فعالیت نمی‌تواند منفی باشد.")
    if f.start_at is not None and f.due_date is None:
        f.due_date = f.start_at.date()


def _touch_lead(session, lead_id: int | None) -> None:
    if lead_id:
        lead = session.get(Lead, lead_id)
        if lead is not None:
            lead.last_activity_at = c.now()
            if lead.status_code == "NEW":
                lead.status_code = "CONTACTED"


def create_activity(company_id: int, user_id: int, f: ActivityFields, session=None) -> int:
    """session اختیاری: سرویس‌های دیگر CRM (مرحلهٔ قیف، اتوماسیون) فعالیت را در همان تراکنش خودشان می‌سازند."""
    _validate(f)
    own = session is None
    session = session or new_session()
    try:
        _check_party(session, company_id, f)
        row = CustomerActivity(company_id=company_id, created_by_user_id=user_id, status_code="OPEN",
                               **{k: (v.strip() if isinstance(v, str) else v) for k, v in f.__dict__.items()})
        if f.activity_type_code == "NOTE":
            row.status_code, row.resolved_at, row.resolved_by_user_id = "DONE", c.now(), user_id
        session.add(row)
        session.flush()
        _touch_lead(session, f.lead_id)
        c.audit(session, company_id, user_id, "Activity", row.activity_id, "CREATE",
                {"type": f.activity_type_code, "customer": f.customer_detail_account_id, "lead": f.lead_id,
                 "opportunity": f.opportunity_id, "assigned": f.assigned_to_user_id})
        if own:
            session.commit()
        activity_id = row.activity_id
    finally:
        if own:
            session.close()
    if f.assigned_to_user_id and f.assigned_to_user_id != user_id:
        c.notify(company_id, f.assigned_to_user_id, "CRM_TASK_ASSIGNED", "فعالیت تازه به شما واگذار شد",
                 f"{c.ACTIVITY_TYPES[f.activity_type_code]}: {f.subject}", "CrmActivity", activity_id)
    return activity_id


def _get(session, company_id: int, activity_id: int) -> CustomerActivity:
    row = session.get(CustomerActivity, activity_id)
    if row is None or row.company_id != company_id:
        raise ValueError("فعالیت نامعتبر است.")
    return row


def update_activity(company_id: int, user_id: int, activity_id: int, f: ActivityFields) -> None:
    _validate(f)
    with new_session() as session:
        row = _get(session, company_id, activity_id)
        _check_party(session, company_id, f)
        changes = {}
        for k, v in f.__dict__.items():
            v = v.strip() if isinstance(v, str) else v
            if getattr(row, k) != v:
                changes[k] = [getattr(row, k), v]
                setattr(row, k, v)
        row.updated_at = c.now()
        if changes:
            c.audit(session, company_id, user_id, "Activity", activity_id, "UPDATE", changes)
        session.commit()
    if "assigned_to_user_id" in changes and f.assigned_to_user_id and f.assigned_to_user_id != user_id:
        c.notify(company_id, f.assigned_to_user_id, "CRM_TASK_ASSIGNED", "فعالیت به شما واگذار شد", f.subject,
                 "CrmActivity", activity_id)


def complete_activity(company_id: int, user_id: int, activity_id: int, result_text: str | None = None,
                      status_code: str | None = None, follow_up_date: datetime.date | None = None,
                      follow_up_subject: str | None = None) -> int | None:
    """بستن فعالیت با نتیجه؛ اگر تاریخ پیگیری داده شود، فعالیت «پیگیری» بعدی خودکار ساخته می‌شود (شناسهٔ آن برمی‌گردد)."""
    with new_session() as session:
        row = _get(session, company_id, activity_id)
        if row.status_code not in c.ACTIVITY_OPEN_STATUSES:
            raise ValueError("این فعالیت قبلاً بسته شده است.")
        allowed = _CLOSE_STATUSES.get(row.activity_type_code, ("DONE", "CANCELLED"))
        status_code = status_code or allowed[0]
        if status_code not in allowed:
            raise ValueError("وضعیت نامعتبر برای بستن این نوع فعالیت.")
        row.status_code, row.resolved_at, row.resolved_by_user_id = status_code, c.now(), user_id
        row.result_text = (result_text or "").strip() or row.result_text
        if follow_up_date:
            row.next_action, row.next_action_date = follow_up_subject or row.next_action, follow_up_date
        _touch_lead(session, row.lead_id)
        c.audit(session, company_id, user_id, "Activity", activity_id, "COMPLETE", {"status": status_code, "result": result_text})
        party = (row.customer_detail_account_id, row.lead_id, row.opportunity_id, row.assigned_to_user_id, row.subject)
        session.commit()
    if not follow_up_date:
        return None
    return create_activity(company_id, user_id, ActivityFields(
        "FOLLOW_UP", follow_up_subject or f"پیگیری: {party[4]}", customer_detail_account_id=party[0], lead_id=party[1],
        opportunity_id=party[2], due_date=follow_up_date, assigned_to_user_id=party[3] or user_id))


def reopen_activity(company_id: int, user_id: int, activity_id: int) -> None:
    with new_session() as session:
        row = _get(session, company_id, activity_id)
        row.status_code, row.resolved_at, row.resolved_by_user_id = "OPEN", None, None
        c.audit(session, company_id, user_id, "Activity", activity_id, "REOPEN")
        session.commit()


def delete_activity(company_id: int, user_id: int, activity_id: int) -> None:
    with new_session() as session:
        row = _get(session, company_id, activity_id)
        c.audit(session, company_id, user_id, "Activity", activity_id, "DELETE",
                {"type": row.activity_type_code, "subject": row.subject, "customer": row.customer_detail_account_id})
        session.delete(row)
        session.commit()


def get_activity(company_id: int, activity_id: int) -> ActivityRow:
    rows = list_activities(company_id, activity_ids=[activity_id])
    if not rows:
        raise ValueError("فعالیت نامعتبر است.")
    return rows[0]


def list_activities(company_id: int, *, customer_detail_account_id: int | None = None, lead_id: int | None = None,
                    opportunity_id: int | None = None, assigned_to_user_id: int | None = None, open_only: bool = False,
                    types: list[str] | None = None, due_from: datetime.date | None = None,
                    due_to: datetime.date | None = None, overdue_only: bool = False, search: str | None = None,
                    activity_ids: list[int] | None = None, limit: int = 200, offset: int = 0) -> list[ActivityRow]:
    with new_session() as session:
        q = select(CustomerActivity).where(CustomerActivity.company_id == company_id)
        if customer_detail_account_id:
            q = q.where(CustomerActivity.customer_detail_account_id == customer_detail_account_id)
        if lead_id:
            q = q.where(CustomerActivity.lead_id == lead_id)
        if opportunity_id:
            q = q.where(CustomerActivity.opportunity_id == opportunity_id)
        if assigned_to_user_id:
            q = q.where(or_(CustomerActivity.assigned_to_user_id == assigned_to_user_id,
                            (CustomerActivity.assigned_to_user_id.is_(None)) & (CustomerActivity.created_by_user_id == assigned_to_user_id)))
        if open_only or overdue_only:
            q = q.where(CustomerActivity.status_code.in_(c.ACTIVITY_OPEN_STATUSES))
        if overdue_only:
            q = q.where(CustomerActivity.due_date < datetime.date.today())
        if types:
            q = q.where(CustomerActivity.activity_type_code.in_(types))
        if due_from:
            q = q.where(CustomerActivity.due_date >= due_from)
        if due_to:
            q = q.where(CustomerActivity.due_date <= due_to)
        if search:
            q = q.where(or_(CustomerActivity.subject.ilike(f"%{search}%"), CustomerActivity.description.ilike(f"%{search}%")))
        if activity_ids:
            q = q.where(CustomerActivity.activity_id.in_(activity_ids))
        q = q.order_by(func.coalesce(CustomerActivity.due_date, func.date(CustomerActivity.created_at)).desc(),
                       CustomerActivity.activity_id.desc()).limit(limit).offset(offset)
        rows = list(session.scalars(q))
        names = dict(session.execute(select(DetailAccount.detail_account_id, DetailAccount.name).where(
            DetailAccount.detail_account_id.in_({r.customer_detail_account_id for r in rows if r.customer_detail_account_id} or {-1}))).all())
        leads = dict(session.execute(select(Lead.lead_id, Lead.full_name).where(
            Lead.lead_id.in_({r.lead_id for r in rows if r.lead_id} or {-1}))).all())
        users = c.user_names(session, [r.assigned_to_user_id for r in rows])
        return [ActivityRow(
            activity_id=r.activity_id, activity_type_code=r.activity_type_code,
            type_label=c.ACTIVITY_TYPES.get(r.activity_type_code, r.activity_type_code), subject=r.subject,
            description=r.description, status_code=r.status_code, status_label=c.ACTIVITY_STATUS.get(r.status_code, r.status_code),
            priority_code=r.priority_code or "NORMAL", due_date=r.due_date, start_at=r.start_at, duration_minutes=r.duration_minutes,
            customer_detail_account_id=r.customer_detail_account_id, customer_name=names.get(r.customer_detail_account_id, ""),
            lead_id=r.lead_id, lead_name=leads.get(r.lead_id, ""), opportunity_id=r.opportunity_id,
            assigned_to_user_id=r.assigned_to_user_id, assigned_name=users.get(r.assigned_to_user_id, ""),
            result_text=r.result_text, next_action=r.next_action, next_action_date=r.next_action_date,
            created_at=r.created_at, resolved_at=r.resolved_at) for r in rows]
