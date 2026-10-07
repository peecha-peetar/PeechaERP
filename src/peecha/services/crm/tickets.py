"""تیکت، شکایت و SLA (فاز ۶، R285).

تیکت همان comm.service_tickets خدمات پس از فروش است: تیکت خدماتی/گارانتی با commercial_aftersales.open_ticket
(همان قاعدهٔ هزینه‌بردار بودن) ساخته می‌شود و تغییر وضعیت با advance_ticket_status (همان قاعدهٔ بستن تیکت
هزینه‌بردار). CRM فقط نوع، اولویت، SLA، پاسخ، ارجاع و رضایت را اضافه می‌کند. گفت‌وگوی تیکت فعالیت CRM با ticket_id است.
"""

from __future__ import annotations

import datetime
import decimal
from dataclasses import dataclass

from sqlalchemy import func, or_, select

from peecha.db.base import new_session
from peecha.db.models.accounting import DetailAccount
from peecha.db.models.commercial import CommercialDocument, CustomerActivity, ServiceTicket
from peecha.db.models.crm import SlaPolicy
from peecha.services import commercial_aftersales as aftersales_service
from peecha.services.crm import activities as act_service
from peecha.services.crm import common as c

TYPES = {"COMPLAINT": "شکایت", "REQUEST": "درخواست", "INQUIRY": "استعلام", "SUPPORT": "پشتیبانی", "SERVICE": "خدمات/تعمیر",
         "RETURN": "مرجوعی", "SUGGESTION": "پیشنهاد"}
STATUS = {"OPEN": "باز", "IN_PROGRESS": "در حال رسیدگی", "RESOLVED": "حل‌شده", "CLOSED": "بسته"}
CHANNELS = {"PHONE": "تلفن", "MOBILE_APP": "اپ موبایل", "EMAIL": "ایمیل", "WEB": "وب‌سایت", "STORE": "فروشگاه",
            "VISIT": "ویزیت", "SOCIAL": "شبکهٔ اجتماعی", "OTHER": "سایر"}
OPEN_STATUSES = ("OPEN", "IN_PROGRESS")
DEFAULT_POLICIES = (("بحرانی", "CRITICAL", 1, 8), ("بالا", "HIGH", 4, 24), ("عادی", "NORMAL", 8, 48), ("کم", "LOW", 24, 96))


@dataclass
class TicketFields:
    customer_detail_account_id: int
    subject: str
    ticket_type: str = "COMPLAINT"
    priority_code: str = "NORMAL"
    channel_code: str | None = None
    category: str | None = None
    description: str | None = None
    assigned_to_user_id: int | None = None
    related_document_id: int | None = None
    item_id: int | None = None
    warranty_id: int | None = None


# --- سیاست‌های SLA --------------------------------------------------------------------------------------
def ensure_default_policies(company_id: int) -> None:
    with new_session() as session:
        if session.scalar(select(func.count()).where(SlaPolicy.company_id == company_id)):
            return
        for name, prio, first, resolve in DEFAULT_POLICIES:
            session.add(SlaPolicy(company_id=company_id, name=f"SLA {name}", priority_code=prio,
                                  first_response_hours=decimal.Decimal(first), resolution_hours=decimal.Decimal(resolve)))
        session.commit()


def list_policies(company_id: int, active_only: bool = False) -> list[SlaPolicy]:
    ensure_default_policies(company_id)
    with new_session() as session:
        q = select(SlaPolicy).where(SlaPolicy.company_id == company_id)
        if active_only:
            q = q.where(SlaPolicy.is_active.is_(True))
        rows = list(session.scalars(q.order_by(SlaPolicy.resolution_hours, SlaPolicy.sla_policy_id)))
        session.expunge_all()
        return rows


def save_policy(company_id: int, user_id: int | None, *, sla_policy_id: int | None = None, name: str, first_response_hours,
                resolution_hours, ticket_type: str | None = None, priority_code: str | None = None,
                escalate_to_user_id: int | None = None, is_active: bool = True) -> int:
    if not (name or "").strip():
        raise ValueError("نام SLA الزامی است.")
    first, resolve = decimal.Decimal(first_response_hours or 0), decimal.Decimal(resolution_hours or 0)
    if first <= 0 or resolve <= 0:
        raise ValueError("زمان پاسخ و حل باید بیشتر از صفر باشد.")
    if resolve < first:
        raise ValueError("زمان حل نمی‌تواند کمتر از زمان اولین پاسخ باشد.")
    if ticket_type and ticket_type not in TYPES:
        raise ValueError("نوع تیکت نامعتبر است.")
    if priority_code and priority_code not in c.PRIORITIES:
        raise ValueError("اولویت نامعتبر است.")
    with new_session() as session:
        if sla_policy_id:
            pol = session.get(SlaPolicy, sla_policy_id)
            if pol is None or pol.company_id != company_id:
                raise ValueError("SLA نامعتبر است.")
        else:
            pol = SlaPolicy(company_id=company_id)
            session.add(pol)
        pol.name, pol.first_response_hours, pol.resolution_hours = name.strip(), first, resolve
        pol.ticket_type, pol.priority_code, pol.escalate_to_user_id, pol.is_active = ticket_type, priority_code, escalate_to_user_id, is_active
        session.flush()
        c.audit(session, company_id, user_id, "SlaPolicy", pol.sla_policy_id, "UPDATE" if sla_policy_id else "CREATE",
                {"name": pol.name, "first": first, "resolve": resolve, "type": ticket_type, "priority": priority_code})
        session.commit()
        return pol.sla_policy_id


def delete_policy(company_id: int, user_id: int | None, sla_policy_id: int) -> None:
    with new_session() as session:
        pol = session.get(SlaPolicy, sla_policy_id)
        if pol is None or pol.company_id != company_id:
            raise ValueError("SLA نامعتبر است.")
        c.audit(session, company_id, user_id, "SlaPolicy", sla_policy_id, "DELETE", {"name": pol.name})
        session.delete(pol)
        session.commit()


def match_policy(session, company_id: int, ticket_type: str, priority_code: str) -> SlaPolicy | None:
    """دقیق‌ترین سیاست فعال: نوع و اولویت ← فقط نوع ← فقط اولویت ← عمومی."""
    pols = list(session.scalars(select(SlaPolicy).where(SlaPolicy.company_id == company_id, SlaPolicy.is_active.is_(True))))

    def rank(p):
        if p.ticket_type not in (None, ticket_type) or p.priority_code not in (None, priority_code):
            return None
        return (p.ticket_type is not None) * 2 + (p.priority_code is not None)

    ranked = [(rank(p), -p.sla_policy_id, p) for p in pols if rank(p) is not None]
    return max(ranked, key=lambda x: (x[0], x[1]))[2] if ranked else None


def _apply_sla(session, company_id: int, t: ServiceTicket) -> None:
    pol = match_policy(session, company_id, t.ticket_type, t.priority_code)
    t.sla_policy_id = pol.sla_policy_id if pol else None
    start = t.opened_at or c.now()
    if pol:
        t.first_response_due_at = start + datetime.timedelta(hours=float(pol.first_response_hours))
        t.resolution_due_at = start + datetime.timedelta(hours=float(pol.resolution_hours))
    else:
        t.first_response_due_at = t.resolution_due_at = None


# --- تیکت ----------------------------------------------------------------------------------------------
def _validate(session, company_id: int, f: TicketFields) -> None:
    if not (f.subject or "").strip():
        raise ValueError("موضوع تیکت الزامی است.")
    if f.ticket_type not in TYPES:
        raise ValueError("نوع تیکت نامعتبر است.")
    if f.priority_code not in c.PRIORITIES:
        raise ValueError("اولویت نامعتبر است.")
    if f.channel_code and f.channel_code not in CHANNELS:
        raise ValueError("کانال دریافت نامعتبر است.")
    da = session.get(DetailAccount, f.customer_detail_account_id)
    if da is None or da.company_id != company_id:
        raise ValueError("مشتری نامعتبر است.")
    if f.related_document_id:
        doc = session.get(CommercialDocument, f.related_document_id)
        if doc is None or doc.company_id != company_id or doc.counterparty_detail_account_id != f.customer_detail_account_id:
            raise ValueError("سند مرتبط متعلق به این مشتری نیست.")


def create_ticket(company_id: int, user_id: int, f: TicketFields) -> int:
    ensure_default_policies(company_id)
    with new_session() as session:
        _validate(session, company_id, f)
    if f.ticket_type == "SERVICE":
        ticket_id = aftersales_service.open_ticket(f.customer_detail_account_id, f.subject.strip(), warranty_id=f.warranty_id,
                                                   item_id=f.item_id, description=f.description,
                                                   assigned_to_user_id=f.assigned_to_user_id)
    else:
        with new_session() as session:
            t = ServiceTicket(customer_detail_account_id=f.customer_detail_account_id, subject=f.subject.strip(), item_id=f.item_id,
                              description=f.description, is_billable=False, assigned_to_user_id=f.assigned_to_user_id)
            session.add(t)
            session.commit()
            ticket_id = t.ticket_id
    with new_session() as session:
        t = session.get(ServiceTicket, ticket_id)
        t.company_id, t.created_by_user_id, t.updated_at = company_id, user_id, c.now()
        t.ticket_no = (session.scalar(select(func.max(ServiceTicket.ticket_no)).where(ServiceTicket.company_id == company_id)) or 0) + 1
        t.ticket_type, t.priority_code, t.channel_code = f.ticket_type, f.priority_code, f.channel_code
        t.category, t.related_document_id = (f.category or "").strip() or None, f.related_document_id
        _apply_sla(session, company_id, t)
        c.audit(session, company_id, user_id, "Ticket", ticket_id, "CREATE",
                {"no": t.ticket_no, "type": t.ticket_type, "priority": t.priority_code, "customer": t.customer_detail_account_id})
        session.commit()
        no, assignee = t.ticket_no, t.assigned_to_user_id
    if assignee and assignee != user_id:
        c.notify(company_id, assignee, "CRM_TICKET_ASSIGNED", f"تیکت {no} به شما ارجاع شد", f.subject, "CrmTicket", ticket_id)
    return ticket_id


def _get(session, company_id: int, ticket_id: int) -> ServiceTicket:
    t = session.get(ServiceTicket, ticket_id)
    if t is None:
        raise ValueError("تیکت نامعتبر است.")
    da = session.get(DetailAccount, t.customer_detail_account_id)
    if (t.company_id or da.company_id) != company_id:
        raise ValueError("تیکت نامعتبر است.")
    if t.company_id is None:  # تیکت خدماتی قدیمی: اولین بار وارد CRM می‌شود
        t.company_id = company_id
        t.ticket_no = (session.scalar(select(func.max(ServiceTicket.ticket_no)).where(ServiceTicket.company_id == company_id)) or 0) + 1
    return t


def update_ticket(company_id: int, user_id: int, ticket_id: int, f: TicketFields) -> None:
    with new_session() as session:
        t = _get(session, company_id, ticket_id)
        if t.status_code == "CLOSED":
            raise ValueError("تیکت بسته قابل ویرایش نیست.")
        _validate(session, company_id, f)
        if f.customer_detail_account_id != t.customer_detail_account_id:
            raise ValueError("مشتری تیکت قابل تغییر نیست.")
        if (f.ticket_type == "SERVICE") != (t.ticket_type == "SERVICE"):
            raise ValueError("تیکت خدماتی به نوع دیگر (یا برعکس) تبدیل نمی‌شود.")
        before = {k: getattr(t, k) for k in ("subject", "ticket_type", "priority_code", "channel_code", "category", "description",
                                             "assigned_to_user_id", "related_document_id")}
        resla = f.ticket_type != t.ticket_type or f.priority_code != t.priority_code
        t.subject = f.subject.strip()
        for k in before:
            if k != "subject":
                setattr(t, k, getattr(f, k))
        if resla:
            _apply_sla(session, company_id, t)
        t.updated_at = c.now()
        c.audit(session, company_id, user_id, "Ticket", ticket_id, "UPDATE",
                {k: [before[k], getattr(t, k)] for k in before if before[k] != getattr(t, k)})
        session.commit()
        new_assignee = t.assigned_to_user_id if t.assigned_to_user_id != before["assigned_to_user_id"] else None
        no = t.ticket_no
    if new_assignee and new_assignee != user_id:
        c.notify(company_id, new_assignee, "CRM_TICKET_ASSIGNED", f"تیکت {no} به شما ارجاع شد", f.subject, "CrmTicket", ticket_id)


def assign_ticket(company_id: int, user_id: int, ticket_id: int, assignee_user_id: int | None) -> None:
    with new_session() as session:
        t = _get(session, company_id, ticket_id)
        old, t.assigned_to_user_id, t.updated_at = t.assigned_to_user_id, assignee_user_id, c.now()
        c.audit(session, company_id, user_id, "Ticket", ticket_id, "ASSIGN", {"assignee": [old, assignee_user_id]})
        session.commit()
        no, subject = t.ticket_no, t.subject
    if assignee_user_id and assignee_user_id != user_id:
        c.notify(company_id, assignee_user_id, "CRM_TICKET_ASSIGNED", f"تیکت {no} به شما ارجاع شد", subject, "CrmTicket", ticket_id)


def _advance(ticket_id: int, status_code: str) -> None:
    aftersales_service.advance_ticket_status(ticket_id, status_code)


def add_reply(company_id: int, user_id: int, ticket_id: int, text: str, kind: str = "NOTE") -> int:
    """پاسخ/پیگیری تیکت (فعالیت CRM با ticket_id). اولین پاسخ زمان پاسخ SLA را ثبت می‌کند."""
    if not (text or "").strip():
        raise ValueError("متن پاسخ خالی است.")
    if kind not in ("NOTE", "CALL", "EMAIL", "MESSAGE", "VISIT"):
        raise ValueError("نوع پاسخ نامعتبر است.")
    with new_session() as session:
        t = _get(session, company_id, ticket_id)
        if t.status_code == "CLOSED":
            raise ValueError("تیکت بسته است؛ ابتدا آن را باز کنید.")
        customer, subject, status = t.customer_detail_account_id, t.subject, t.status_code
        if t.first_responded_at is None:
            t.first_responded_at = c.now()
        t.updated_at = c.now()
        session.commit()
    if status == "OPEN":
        _advance(ticket_id, "IN_PROGRESS")
    aid = act_service.create_activity(company_id, user_id, act_service.ActivityFields(
        kind, f"پاسخ تیکت: {subject}"[:200], description=text.strip(), customer_detail_account_id=customer, ticket_id=ticket_id,
        due_date=datetime.date.today()))
    if kind != "NOTE":  # پاسخ انجام‌شده است، نه کار باز
        act_service.complete_activity(company_id, user_id, aid, text.strip())
    return aid


def resolve_ticket(company_id: int, user_id: int, ticket_id: int, resolution_text: str) -> None:
    if not (resolution_text or "").strip():
        raise ValueError("شرح راه‌حل الزامی است.")
    with new_session() as session:
        t = _get(session, company_id, ticket_id)
        if t.status_code not in OPEN_STATUSES:
            raise ValueError("فقط تیکت باز حل می‌شود.")
        session.commit()
    _advance(ticket_id, "RESOLVED")
    with new_session() as session:
        t = _get(session, company_id, ticket_id)
        now = c.now()
        t.resolved_at, t.resolution_text, t.updated_at = now, resolution_text.strip(), now
        t.first_responded_at = t.first_responded_at or now
        if t.resolution_due_at and now > t.resolution_due_at:
            t.sla_breached = True
        c.audit(session, company_id, user_id, "Ticket", ticket_id, "RESOLVE", {"breached": t.sla_breached})
        session.commit()


def close_ticket(company_id: int, user_id: int, ticket_id: int) -> None:
    with new_session() as session:
        t = _get(session, company_id, ticket_id)
        if t.status_code == "CLOSED":
            raise ValueError("تیکت قبلاً بسته شده است.")
        session.commit()
    _advance(ticket_id, "CLOSED")
    with new_session() as session:
        t = _get(session, company_id, ticket_id)
        t.resolved_at, t.updated_at = t.resolved_at or c.now(), c.now()
        c.audit(session, company_id, user_id, "Ticket", ticket_id, "CLOSE", {})
        session.commit()


def reopen_ticket(company_id: int, user_id: int, ticket_id: int, reason: str | None = None) -> None:
    with new_session() as session:
        t = _get(session, company_id, ticket_id)
        if t.status_code in OPEN_STATUSES:
            raise ValueError("تیکت باز است.")
        now = c.now()
        t.status_code, t.closed_at, t.resolved_at, t.updated_at = "OPEN", None, None, now
        t.sla_breached, t.escalation_level = False, 0
        pol = match_policy(session, company_id, t.ticket_type, t.priority_code)
        t.sla_policy_id = pol.sla_policy_id if pol else None
        # موعد حل از لحظهٔ بازشدن دوباره؛ اولین پاسخ قبلاً داده شده است
        t.resolution_due_at = now + datetime.timedelta(hours=float(pol.resolution_hours)) if pol else None
        c.audit(session, company_id, user_id, "Ticket", ticket_id, "REOPEN", {"reason": reason})
        session.commit()


def rate_ticket(company_id: int, user_id: int | None, ticket_id: int, score: int, comment: str | None = None) -> None:
    """رضایت مشتری (۱ تا ۵) پس از حل تیکت."""
    if not 1 <= int(score) <= 5:
        raise ValueError("امتیاز رضایت باید بین ۱ تا ۵ باشد.")
    with new_session() as session:
        t = _get(session, company_id, ticket_id)
        if t.status_code not in ("RESOLVED", "CLOSED"):
            raise ValueError("رضایت پس از حل تیکت ثبت می‌شود.")
        t.satisfaction_score, t.satisfaction_comment, t.updated_at = int(score), (comment or "").strip() or None, c.now()
        c.audit(session, company_id, user_id, "Ticket", ticket_id, "RATE", {"score": int(score)})
        session.commit()


def check_sla(company_id: int, now: datetime.datetime | None = None) -> list[int]:
    """تیکت‌های باز گذشته از موعد پاسخ یا حل: علامت نقض، یک سطح ارجاع بالاتر و اعلان به مسئول/ارجاع‌گیرنده.
    هر تیکت در هر سطح فقط یک بار ارجاع می‌شود. برمی‌گرداند: شناسهٔ تیکت‌های تازه ارجاع‌شده."""
    now = now or c.now()
    notes = []
    with new_session() as session:
        rows = list(session.scalars(select(ServiceTicket).where(
            ServiceTicket.company_id == company_id, ServiceTicket.status_code.in_(OPEN_STATUSES),
            or_(ServiceTicket.resolution_due_at < now,
                (ServiceTicket.first_responded_at.is_(None)) & (ServiceTicket.first_response_due_at < now)))))
        for t in rows:
            level = 2 if t.resolution_due_at and now > t.resolution_due_at else 1
            t.sla_breached = True
            if t.escalation_level >= level:
                continue
            t.escalation_level, t.escalated_at = level, now
            pol = session.get(SlaPolicy, t.sla_policy_id) if t.sla_policy_id else None
            targets = {u for u in (t.assigned_to_user_id, pol.escalate_to_user_id if pol else None, t.created_by_user_id) if u}
            what = "موعد حل" if level == 2 else "موعد اولین پاسخ"
            notes.append((t.ticket_id, t.ticket_no, t.subject, what, targets))
            c.audit(session, company_id, None, "Ticket", t.ticket_id, "ESCALATE", {"level": level})
        session.commit()
    for tid, no, subject, what, targets in notes:
        for u in targets:
            c.notify(company_id, u, "CRM_TICKET_SLA", f"نقض SLA تیکت {no}: {what} گذشته است", subject, "CrmTicket", tid)
    return [n[0] for n in notes]


# --- فهرست ---------------------------------------------------------------------------------------------
@dataclass
class TicketRow:
    ticket_id: int
    ticket_no: int | None
    customer_detail_account_id: int
    customer_name: str
    subject: str
    description: str | None
    ticket_type: str
    type_label: str
    priority_code: str
    priority_label: str
    status_code: str
    status_label: str
    channel_code: str | None
    category: str | None
    assigned_to_user_id: int | None
    assignee_name: str
    opened_at: datetime.datetime
    first_response_due_at: datetime.datetime | None
    resolution_due_at: datetime.datetime | None
    first_responded_at: datetime.datetime | None
    resolved_at: datetime.datetime | None
    sla_breached: bool
    escalation_level: int
    related_document_id: int | None
    resolution_text: str | None
    satisfaction_score: int | None
    satisfaction_comment: str | None
    is_billable: bool

    @property
    def is_open(self) -> bool:
        return self.status_code in OPEN_STATUSES

    def sla_state(self, now: datetime.datetime | None = None) -> str:
        """OK | AT_RISK (کمتر از ۲۰٪ زمان مانده) | BREACHED | NONE"""
        if self.sla_breached:
            return "BREACHED"
        if not self.is_open or not self.resolution_due_at:
            return "NONE" if not self.resolution_due_at else "OK"
        now = now or c.now()
        if now > self.resolution_due_at:
            return "BREACHED"
        total = (self.resolution_due_at - self.opened_at).total_seconds() or 1
        return "AT_RISK" if (self.resolution_due_at - now).total_seconds() / total < 0.2 else "OK"


def list_tickets(company_id: int, *, status: str | None = None, open_only: bool = False, ticket_type: str | None = None,
                 priority: str | None = None, assignee_user_id: int | None = None, customer_id: int | None = None,
                 breached_only: bool = False, search: str | None = None, limit: int = 500, offset: int = 0) -> list[TicketRow]:
    with new_session() as session:
        q = select(ServiceTicket, DetailAccount.name).join(
            DetailAccount, DetailAccount.detail_account_id == ServiceTicket.customer_detail_account_id).where(
            DetailAccount.company_id == company_id)
        if status:
            q = q.where(ServiceTicket.status_code == status)
        if open_only:
            q = q.where(ServiceTicket.status_code.in_(OPEN_STATUSES))
        if ticket_type:
            q = q.where(ServiceTicket.ticket_type == ticket_type)
        if priority:
            q = q.where(ServiceTicket.priority_code == priority)
        if assignee_user_id:
            q = q.where(ServiceTicket.assigned_to_user_id == assignee_user_id)
        if customer_id:
            q = q.where(ServiceTicket.customer_detail_account_id == customer_id)
        if breached_only:
            q = q.where(ServiceTicket.sla_breached.is_(True))
        if search:
            like = f"%{search}%"
            q = q.where(or_(ServiceTicket.subject.ilike(like), DetailAccount.name.ilike(like), ServiceTicket.category.ilike(like)))
        rows = session.execute(q.order_by(ServiceTicket.status_code.in_(OPEN_STATUSES).desc(),
                                          ServiceTicket.resolution_due_at.asc().nulls_last(), ServiceTicket.ticket_id.desc())
                               .limit(limit).offset(offset)).all()
        names = c.user_names(session, {t.assigned_to_user_id for t, _n in rows})
        return [TicketRow(
            t.ticket_id, t.ticket_no, t.customer_detail_account_id, name, t.subject, t.description, t.ticket_type,
            TYPES.get(t.ticket_type, t.ticket_type), t.priority_code, c.PRIORITIES.get(t.priority_code, t.priority_code), t.status_code,
            STATUS.get(t.status_code, t.status_code), t.channel_code, t.category, t.assigned_to_user_id,
            names.get(t.assigned_to_user_id, ""), t.opened_at, t.first_response_due_at, t.resolution_due_at, t.first_responded_at,
            t.resolved_at, t.sla_breached, t.escalation_level, t.related_document_id, t.resolution_text, t.satisfaction_score,
            t.satisfaction_comment, t.is_billable) for t, name in rows]


def get_ticket(company_id: int, ticket_id: int) -> TicketRow:
    with new_session() as session:
        t = _get(session, company_id, ticket_id)
        session.commit()
        customer = t.customer_detail_account_id
    row = next((r for r in list_tickets(company_id, customer_id=customer) if r.ticket_id == ticket_id), None)
    if row is None:
        raise ValueError("تیکت نامعتبر است.")
    return row


def conversation(company_id: int, ticket_id: int) -> list[act_service.ActivityRow]:
    get_ticket(company_id, ticket_id)
    with new_session() as session:
        ids = list(session.scalars(select(CustomerActivity.activity_id).where(CustomerActivity.ticket_id == ticket_id)
                                   .order_by(CustomerActivity.created_at)))
    return [act_service.get_activity(company_id, i) for i in ids]


def stats(company_id: int, date_from: datetime.date | None = None, date_to: datetime.date | None = None) -> dict:
    """تعداد باز، نقض SLA، میانگین زمان پاسخ و حل (ساعت)، رضایت میانگین (CSAT)، تفکیک نوع."""
    with new_session() as session:
        base = [ServiceTicket.company_id == company_id]
        if date_from:
            base.append(ServiceTicket.opened_at >= datetime.datetime.combine(date_from, datetime.time.min))
        if date_to:
            base.append(ServiceTicket.opened_at < datetime.datetime.combine(date_to + datetime.timedelta(days=1), datetime.time.min))
        hours = lambda a, b: func.avg(func.extract("epoch", a - b) / 3600)
        total, open_, breached, resp_h, res_h, csat, rated = session.execute(select(
            func.count(), func.count().filter(ServiceTicket.status_code.in_(OPEN_STATUSES)),
            func.count().filter(ServiceTicket.sla_breached.is_(True)),
            hours(ServiceTicket.first_responded_at, ServiceTicket.opened_at),
            hours(ServiceTicket.resolved_at, ServiceTicket.opened_at), func.avg(ServiceTicket.satisfaction_score),
            func.count(ServiceTicket.satisfaction_score)).where(*base)).one()
        by_type = dict(session.execute(select(ServiceTicket.ticket_type, func.count()).where(*base)
                                       .group_by(ServiceTicket.ticket_type)).all())
    q = lambda v: decimal.Decimal(str(round(float(v), 1))) if v is not None else None
    return {"total": total, "open": open_, "breached": breached,
            "sla_compliance": q(100 * (total - breached) / total) if total else None,
            "avg_first_response_hours": q(resp_h), "avg_resolution_hours": q(res_h), "csat": q(csat), "rated": rated,
            "by_type": {k: by_type.get(k, 0) for k in TYPES}}
