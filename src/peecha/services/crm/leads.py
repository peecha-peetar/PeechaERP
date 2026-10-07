"""سرنخ (Lead): ثبت، امتیازدهی، واگذاری، تبدیل به مشتری/فرصت.

تبدیل به مشتری فقط از همان commercial_partners.create_customer انجام می‌شود (همان کدگذاری، پروفایل و اعتبارسنجی)؛
CRM مشتری موازی نمی‌سازد.
"""

from __future__ import annotations

import datetime
import decimal
from dataclasses import dataclass

from sqlalchemy import func, or_, select

from peecha.db.base import new_session
from peecha.db.models.accounting import CustomerDetail, DetailAccount
from peecha.db.models.commercial import CustomerActivity
from peecha.db.models.crm import Lead, LeadSource, Opportunity
from peecha.services import commercial_partners as partners_service
from peecha.services.crm import common as c


@dataclass
class LeadFields:
    full_name: str
    company_name: str | None = None
    mobile: str | None = None
    phone: str | None = None
    email: str | None = None
    source_id: int | None = None
    interested_item_id: int | None = None
    interested_text: str | None = None
    estimated_value: decimal.Decimal | None = None
    owner_user_id: int | None = None
    city: str | None = None
    province: str | None = None
    industry: str | None = None
    notes: str | None = None
    next_action: str | None = None
    next_action_date: datetime.date | None = None


@dataclass
class LeadRow:
    lead_id: int
    lead_no: int
    full_name: str
    company_name: str | None
    mobile: str | None
    phone: str | None
    email: str | None
    source_id: int | None
    source_name: str
    status_code: str
    status_label: str
    score: int
    score_band: str
    band_label: str
    estimated_value: decimal.Decimal | None
    owner_user_id: int | None
    owner_name: str
    next_action: str | None
    next_action_date: datetime.date | None
    last_activity_at: datetime.datetime | None
    created_at: datetime.datetime
    converted_customer_detail_account_id: int | None
    converted_opportunity_id: int | None
    interested_item_id: int | None
    interested_text: str | None
    city: str | None
    province: str | None
    industry: str | None
    notes: str | None


# --- امتیازدهی ----------------------------------------------------------------------------------------
# وزن پیش‌فرض عامل‌ها (جمع حداکثر ۱۰۰)؛ قواعد قابل تنظیم شرکت در فاز بازاریابی روی همین تابع اعمال می‌شوند.
SOURCE_POINTS = {"REFERRAL": 15, "EXHIBITION": 12, "VISITOR": 12, "PHONE": 10, "WEBSITE": 8, "MOBILE_APP": 8,
                 "STORE": 10, "WHATSAPP": 7, "TELEGRAM": 6, "INSTAGRAM": 6, "ADVERTISING": 5, "OTHER": 3}
BAND_THRESHOLDS = (("VERY_HOT", 75), ("HOT", 55), ("WARM", 30), ("COLD", 0))


def score_band(score: int) -> str:
    return next(band for band, floor in BAND_THRESHOLDS if score >= floor)


def compute_lead_score(session, lead: Lead) -> tuple[int, dict[str, int]]:
    """امتیاز ۰ تا ۱۰۰ و سهم هر عامل (تعامل، پاسخ‌گویی، علاقه به محصول، ارزش، سابقهٔ خرید، صنعت/مکان، منبع، فعالیت اخیر)."""
    counts = dict(session.execute(select(CustomerActivity.status_code, func.count()).where(
        CustomerActivity.lead_id == lead.lead_id).group_by(CustomerActivity.status_code)).all())
    total = sum(counts.values())
    done = counts.get("DONE", 0) + counts.get("RESOLVED", 0)
    parts = {
        "engagement": min(20, total * 4),
        "responsiveness": min(10, done * 5),
        "interest": 10 if (lead.interested_item_id or lead.interested_text) else 0,
        "value": 0,
        "history": 0,
        "profile": (4 if lead.industry else 0) + (3 if lead.city or lead.province else 0) + (3 if lead.email else 0),
        "source": 0,
        "recency": 0,
    }
    value = decimal.Decimal(lead.estimated_value or 0)
    parts["value"] = 20 if value >= 1_000_000_000 else 15 if value >= 200_000_000 else 10 if value >= 50_000_000 else 5 if value > 0 else 0
    if lead.mobile and session.scalar(select(CustomerDetail.detail_account_id).join(
            DetailAccount, DetailAccount.detail_account_id == CustomerDetail.detail_account_id).where(
            DetailAccount.company_id == lead.company_id, CustomerDetail.mobile == lead.mobile).limit(1)):
        parts["history"] = 10
    if lead.source_id:
        code = session.scalar(select(LeadSource.code).where(LeadSource.source_id == lead.source_id))
        parts["source"] = SOURCE_POINTS.get(code, 5)
    if lead.last_activity_at:
        days = (c.now() - lead.last_activity_at).days
        parts["recency"] = 10 if days <= 3 else 6 if days <= 14 else 2 if days <= 45 else 0
    return min(100, sum(parts.values())), parts


def _rescore(session, lead: Lead) -> None:
    lead.score, _parts = compute_lead_score(session, lead)
    lead.score_band = score_band(lead.score)


def rescore_lead(company_id: int, lead_id: int) -> int:
    with new_session() as session:
        lead = _get(session, company_id, lead_id)
        _rescore(session, lead)
        session.commit()
        return lead.score


def score_breakdown(company_id: int, lead_id: int) -> dict[str, int]:
    with new_session() as session:
        return compute_lead_score(session, _get(session, company_id, lead_id))[1]


# --- ثبت و ویرایش -------------------------------------------------------------------------------------
def _clean(f: LeadFields) -> None:
    if not (f.full_name or "").strip():
        raise ValueError("نام سرنخ الزامی است.")
    for k, v in f.__dict__.items():
        if isinstance(v, str):
            setattr(f, k, v.strip() or None)
    if f.estimated_value is not None and decimal.Decimal(f.estimated_value) < 0:
        raise ValueError("ارزش احتمالی نمی‌تواند منفی باشد.")
    if not (f.mobile or f.phone or f.email):
        raise ValueError("دست‌کم یکی از موبایل، تلفن یا ایمیل لازم است.")


def find_duplicates(company_id: int, mobile: str | None = None, email: str | None = None,
                    exclude_lead_id: int | None = None) -> list[str]:
    """سرنخ باز یا مشتری موجود با همین موبایل/ایمیل — برای هشدار پیش از ثبت."""
    out = []
    with new_session() as session:
        conds = [Lead.mobile == mobile] if mobile else []
        conds += [Lead.email == email] if email else []
        if conds:
            for no, name in session.execute(select(Lead.lead_no, Lead.full_name).where(
                    Lead.company_id == company_id, Lead.status_code.in_(c.LEAD_OPEN_STATUSES), or_(*conds),
                    Lead.lead_id != (exclude_lead_id or -1))):
                out.append(f"سرنخ {no}: {name}")
        if mobile:
            for code, name in session.execute(select(DetailAccount.code, DetailAccount.name).join(
                    CustomerDetail, CustomerDetail.detail_account_id == DetailAccount.detail_account_id).where(
                    DetailAccount.company_id == company_id, CustomerDetail.mobile == mobile)):
                out.append(f"مشتری {code}: {name}")
    return out


def create_lead(company_id: int, user_id: int, f: LeadFields, allow_duplicate: bool = False) -> int:
    _clean(f)
    if not allow_duplicate:
        dups = [d for d in find_duplicates(company_id, f.mobile, f.email) if d.startswith("سرنخ")]
        if dups:
            raise ValueError("سرنخ باز دیگری با همین مشخصات هست: " + "، ".join(dups))
    with new_session() as session:
        if f.source_id and session.get(LeadSource, f.source_id) is None:
            raise ValueError("منبع سرنخ نامعتبر است.")
        lead = Lead(company_id=company_id, lead_no=c.next_number(session, Lead, company_id, Lead.lead_no),
                    created_by_user_id=user_id, status_code="NEW", **f.__dict__)
        lead.owner_user_id = lead.owner_user_id or user_id
        session.add(lead)
        session.flush()
        _rescore(session, lead)
        c.audit(session, company_id, user_id, "Lead", lead.lead_id, "CREATE",
                {"no": lead.lead_no, "name": lead.full_name, "owner": lead.owner_user_id, "source": f.source_id})
        session.commit()
        lead_id, owner = lead.lead_id, lead.owner_user_id
    if owner != user_id:
        c.notify(company_id, owner, "CRM_LEAD_ASSIGNED", "سرنخ تازه به شما واگذار شد", f.full_name, "CrmLead", lead_id)
    return lead_id


def _get(session, company_id: int, lead_id: int) -> Lead:
    lead = session.get(Lead, lead_id)
    if lead is None or lead.company_id != company_id:
        raise ValueError("سرنخ نامعتبر است.")
    return lead


def update_lead(company_id: int, user_id: int, lead_id: int, f: LeadFields) -> None:
    _clean(f)
    with new_session() as session:
        lead = _get(session, company_id, lead_id)
        if lead.status_code == "CONVERTED":
            raise ValueError("سرنخ تبدیل‌شده قابل ویرایش نیست — اطلاعات را در پروندهٔ مشتری اصلاح کنید.")
        changes = {k: [getattr(lead, k), v] for k, v in f.__dict__.items() if getattr(lead, k) != v}
        old_owner = lead.owner_user_id
        for k, v in f.__dict__.items():
            setattr(lead, k, v)
        lead.owner_user_id = lead.owner_user_id or old_owner
        lead.updated_at = c.now()
        _rescore(session, lead)
        if changes:
            c.audit(session, company_id, user_id, "Lead", lead_id, "UPDATE", changes)
        session.commit()
        new_owner = lead.owner_user_id
    if new_owner != old_owner and new_owner != user_id:
        c.notify(company_id, new_owner, "CRM_LEAD_ASSIGNED", "سرنخ به شما واگذار شد", f.full_name, "CrmLead", lead_id)


def assign_lead(company_id: int, user_id: int, lead_id: int, owner_user_id: int) -> None:
    with new_session() as session:
        lead = _get(session, company_id, lead_id)
        old = lead.owner_user_id
        lead.owner_user_id, lead.updated_at = owner_user_id, c.now()
        c.audit(session, company_id, user_id, "Lead", lead_id, "ASSIGN", {"owner": [old, owner_user_id]})
        session.commit()
        name = lead.full_name
    if owner_user_id != user_id:
        c.notify(company_id, owner_user_id, "CRM_LEAD_ASSIGNED", "سرنخ به شما واگذار شد", name, "CrmLead", lead_id)


def set_lead_status(company_id: int, user_id: int, lead_id: int, status_code: str, reason: str | None = None) -> None:
    if status_code not in c.LEAD_STATUS or status_code == "CONVERTED":
        raise ValueError("وضعیت سرنخ نامعتبر است (تبدیل فقط از «تبدیل به مشتری/فرصت» انجام می‌شود).")
    if status_code in ("LOST", "UNQUALIFIED") and not (reason or "").strip():
        raise ValueError("دلیل از دست رفتن/فاقد شرایط بودن را بنویسید.")
    with new_session() as session:
        lead = _get(session, company_id, lead_id)
        if lead.status_code == "CONVERTED":
            raise ValueError("سرنخ تبدیل‌شده قابل تغییر وضعیت نیست.")
        old = lead.status_code
        lead.status_code, lead.updated_at = status_code, c.now()
        lead.lost_reason = (reason or "").strip() or lead.lost_reason
        c.audit(session, company_id, user_id, "Lead", lead_id, "STATUS", {"status": [old, status_code], "reason": reason})
        session.commit()


def delete_lead(company_id: int, user_id: int, lead_id: int) -> None:
    with new_session() as session:
        lead = _get(session, company_id, lead_id)
        if lead.status_code == "CONVERTED":
            raise ValueError("سرنخ تبدیل‌شده قابل حذف نیست.")
        if session.scalar(select(Opportunity.opportunity_id).where(Opportunity.lead_id == lead_id).limit(1)):
            raise ValueError("برای این سرنخ فرصت فروش ثبت شده — ابتدا فرصت را حذف کنید یا سرنخ را «از دست رفته» کنید.")
        session.query(CustomerActivity).filter(CustomerActivity.lead_id == lead_id,
                                               CustomerActivity.customer_detail_account_id.is_(None)).delete()
        session.query(CustomerActivity).filter(CustomerActivity.lead_id == lead_id).update({"lead_id": None})
        c.audit(session, company_id, user_id, "Lead", lead_id, "DELETE", {"no": lead.lead_no, "name": lead.full_name})
        session.delete(lead)
        session.commit()


# --- تبدیل ---------------------------------------------------------------------------------------------
_ONBOARDING = {"REFERRAL": "REFERRAL", "STORE": "WALK_IN", "VISITOR": "AGENT", "WEBSITE": "ONLINE", "MOBILE_APP": "ONLINE",
               "INSTAGRAM": "ONLINE", "WHATSAPP": "ONLINE", "TELEGRAM": "ONLINE"}


def convert_lead(company_id: int, user_id: int, lead_id: int, *, existing_customer_id: int | None = None,
                 customer_code: str | None = None, customer_group_id: int | None = None, create_opportunity: bool = True,
                 opportunity_title: str | None = None, opportunity_amount: decimal.Decimal | None = None,
                 fast_track: bool = True) -> tuple[int, int | None]:
    """سرنخ ← مشتری (تازه از همان سرویس مشتری، یا مشتری موجود) و در صورت خواست ← فرصت فروش. (مشتری، فرصت)."""
    from peecha.services.crm import opportunities as opp_service

    with new_session() as session:
        lead = _get(session, company_id, lead_id)
        if lead.status_code == "CONVERTED":
            raise ValueError("این سرنخ قبلاً تبدیل شده است.")
        snapshot = {k: getattr(lead, k) for k in ("full_name", "company_name", "mobile", "phone", "email", "notes",
                                                  "source_id", "estimated_value", "owner_user_id", "interested_text")}
        source_code = session.scalar(select(LeadSource.code).where(LeadSource.source_id == lead.source_id)) if lead.source_id else None
        if existing_customer_id:
            da = session.get(DetailAccount, existing_customer_id)
            if da is None or da.company_id != company_id:
                raise ValueError("مشتری انتخاب‌شده نامعتبر است.")
    customer_id = existing_customer_id
    if customer_id is None:
        name = snapshot["company_name"] or snapshot["full_name"]
        extra = {k: snapshot[k] for k in ("mobile", "phone") if snapshot[k]}
        if snapshot["notes"]:
            extra["notes"] = snapshot["notes"][:500]
        customer_id = partners_service.create_customer(
            company_id, (customer_code or "").strip() or partners_service.suggest_customer_code(company_id), name,
            partners_service.CustomerProfileFields(customer_group_id=customer_group_id,
                                                   onboarding_source_code=_ONBOARDING.get(source_code)),
            fast_track=fast_track, submitted_by_user_id=user_id, **extra)
        if snapshot["company_name"] or snapshot["email"]:
            partners_service.add_party_contact(customer_id, snapshot["full_name"], phone=snapshot["mobile"] or snapshot["phone"],
                                               email=snapshot["email"], is_primary=True)
    opportunity_id = None
    if create_opportunity:
        opportunity_id = opp_service.create_opportunity(company_id, user_id, opp_service.OpportunityFields(
            title=opportunity_title or f"فرصت فروش — {snapshot['company_name'] or snapshot['full_name']}",
            customer_detail_account_id=customer_id, lead_id=lead_id,
            amount=opportunity_amount if opportunity_amount is not None else (snapshot["estimated_value"] or decimal.Decimal(0)),
            owner_user_id=snapshot["owner_user_id"], source_id=snapshot["source_id"], description=snapshot["interested_text"]))
    with new_session() as session:
        lead = _get(session, company_id, lead_id)
        lead.status_code, lead.converted_at, lead.updated_at = "CONVERTED", c.now(), c.now()
        lead.converted_customer_detail_account_id, lead.converted_opportunity_id = customer_id, opportunity_id
        session.query(CustomerActivity).filter(CustomerActivity.lead_id == lead_id,
                                               CustomerActivity.customer_detail_account_id.is_(None)).update(
            {"customer_detail_account_id": customer_id})
        c.audit(session, company_id, user_id, "Lead", lead_id, "CONVERT",
                {"customer": customer_id, "new_customer": existing_customer_id is None, "opportunity": opportunity_id})
        session.commit()
    return customer_id, opportunity_id


# --- فهرست --------------------------------------------------------------------------------------------
def list_leads(company_id: int, *, status: str | None = None, open_only: bool = False, owner_user_id: int | None = None,
               source_id: int | None = None, band: str | None = None, search: str | None = None,
               lead_ids: list[int] | None = None, limit: int = 500, offset: int = 0) -> list[LeadRow]:
    with new_session() as session:
        q = select(Lead).where(Lead.company_id == company_id)
        if status:
            q = q.where(Lead.status_code == status)
        if open_only:
            q = q.where(Lead.status_code.in_(c.LEAD_OPEN_STATUSES))
        if owner_user_id:
            q = q.where(Lead.owner_user_id == owner_user_id)
        if source_id:
            q = q.where(Lead.source_id == source_id)
        if band:
            q = q.where(Lead.score_band == band)
        if lead_ids:
            q = q.where(Lead.lead_id.in_(lead_ids))
        if search:
            like = f"%{search.strip()}%"
            q = q.where(or_(Lead.full_name.ilike(like), Lead.company_name.ilike(like), Lead.mobile.ilike(like),
                            Lead.phone.ilike(like), Lead.email.ilike(like)))
        rows = list(session.scalars(q.order_by(Lead.created_at.desc()).limit(limit).offset(offset)))
        sources = dict(session.execute(select(LeadSource.source_id, LeadSource.name)).all())
        users = c.user_names(session, [r.owner_user_id for r in rows])
        return [LeadRow(
            lead_id=r.lead_id, lead_no=r.lead_no, full_name=r.full_name, company_name=r.company_name, mobile=r.mobile,
            phone=r.phone, email=r.email, source_id=r.source_id, source_name=sources.get(r.source_id, ""),
            status_code=r.status_code, status_label=c.LEAD_STATUS[r.status_code], score=r.score, score_band=r.score_band,
            band_label=c.SCORE_BANDS[r.score_band], estimated_value=r.estimated_value, owner_user_id=r.owner_user_id,
            owner_name=users.get(r.owner_user_id, ""), next_action=r.next_action, next_action_date=r.next_action_date,
            last_activity_at=r.last_activity_at, created_at=r.created_at,
            converted_customer_detail_account_id=r.converted_customer_detail_account_id,
            converted_opportunity_id=r.converted_opportunity_id, interested_item_id=r.interested_item_id,
            interested_text=r.interested_text, city=r.city, province=r.province, industry=r.industry, notes=r.notes)
            for r in rows]


def get_lead(company_id: int, lead_id: int) -> LeadRow:
    rows = list_leads(company_id, lead_ids=[lead_id])
    if not rows:
        raise ValueError("سرنخ نامعتبر است.")
    return rows[0]
