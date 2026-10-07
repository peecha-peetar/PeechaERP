"""کمپین بازاریابی CRM (فاز ۵، R284).

مخاطبان از سگمنت پویا (فاز ۴) یا سرنخ‌ها ساخته می‌شوند. ارسال پیامکی با همان comm.sms_campaigns و تیک ارسال
موجود (sms_marketing.run_due_campaigns و sms_gateway) انجام می‌شود؛ کمپین تماس/بازدید برای هر مخاطب فعالیت CRM
می‌سازد تا در مرکز کارها دیده شود. درآمد کمپین از فاکتورهای ثبت‌شدهٔ همان مشتریان در بازهٔ کمپین خوانده می‌شود.
"""

from __future__ import annotations

import datetime
import decimal
from dataclasses import dataclass

from sqlalchemy import func, select

from peecha.db.base import new_session
from peecha.db.models.accounting import CustomerDetail, DetailAccount
from peecha.db.models.commercial import CommercialDocument, SmsCampaign, SmsCampaignRecipient
from peecha.db.models.crm import Campaign, CampaignMember, Lead, Opportunity, Segment
from peecha.services.crm import activities as act_service
from peecha.services.crm import common as c
from peecha.services.crm import segments as seg_service

ZERO = decimal.Decimal(0)
TYPES = {"SMS": "پیامک", "EMAIL": "ایمیل", "WHATSAPP": "واتس‌اپ", "TELEGRAM": "تلگرام", "CALL": "تماس تلفنی",
         "VISIT": "بازدید حضوری", "EVENT": "رویداد/نمایشگاه", "ADVERTISING": "تبلیغات", "SOCIAL": "شبکهٔ اجتماعی", "OTHER": "سایر"}
STATUS = {"DRAFT": "پیش‌نویس", "SCHEDULED": "زمان‌بندی‌شده", "ACTIVE": "در حال اجرا", "COMPLETED": "پایان‌یافته",
          "CANCELLED": "لغوشده"}
MEMBER_STATUS = {"TARGETED": "هدف", "SENT": "ارسال‌شده", "FAILED": "ناموفق", "RESPONDED": "پاسخ داده", "CONVERTED": "تبدیل‌شده",
                 "OPTED_OUT": "انصراف"}
_TASK_TYPES = {"CALL": "CALL", "VISIT": "VISIT"}


@dataclass
class CampaignFields:
    name: str
    campaign_type: str = "SMS"
    segment_id: int | None = None
    lead_source_id: int | None = None
    start_date: datetime.date | None = None
    end_date: datetime.date | None = None
    attribution_days: int = 30
    budget_amount: decimal.Decimal | None = None
    actual_cost: decimal.Decimal = ZERO
    expected_revenue: decimal.Decimal | None = None
    message_text: str | None = None
    owner_user_id: int | None = None
    description: str | None = None


def _get(session, company_id: int, campaign_id: int) -> Campaign:
    camp = session.get(Campaign, campaign_id)
    if camp is None or camp.company_id != company_id:
        raise ValueError("کمپین نامعتبر است.")
    return camp


def _apply(session, company_id: int, camp: Campaign, f: CampaignFields) -> None:
    if not (f.name or "").strip():
        raise ValueError("نام کمپین الزامی است.")
    if f.campaign_type not in TYPES:
        raise ValueError("نوع کمپین نامعتبر است.")
    if f.start_date and f.end_date and f.end_date < f.start_date:
        raise ValueError("تاریخ پایان کمپین پیش از تاریخ شروع است.")
    for v, label in ((f.budget_amount, "بودجه"), (f.actual_cost, "هزینهٔ واقعی")):
        if v is not None and decimal.Decimal(v) < 0:
            raise ValueError(f"{label} نمی‌تواند منفی باشد.")
    if int(f.attribution_days or 0) < 0:
        raise ValueError("بازهٔ نسبت‌دهی نمی‌تواند منفی باشد.")
    if f.segment_id:
        seg = session.get(Segment, f.segment_id)
        if seg is None or seg.company_id != company_id:
            raise ValueError("سگمنت نامعتبر است.")
    for k, v in f.__dict__.items():
        setattr(camp, k, (v.strip() or None) if isinstance(v, str) else v)
    camp.name = f.name.strip()
    camp.actual_cost = f.actual_cost or ZERO
    camp.attribution_days = int(f.attribution_days or 0)
    camp.updated_at = c.now()


def create_campaign(company_id: int, user_id: int, f: CampaignFields) -> int:
    with new_session() as session:
        camp = Campaign(company_id=company_id, created_by_user_id=user_id, status_code="DRAFT",
                        campaign_no=c.next_number(session, Campaign, company_id, Campaign.campaign_no))
        _apply(session, company_id, camp, f)
        camp.owner_user_id = camp.owner_user_id or user_id
        session.add(camp)
        session.flush()
        c.audit(session, company_id, user_id, "Campaign", camp.campaign_id, "CREATE",
                {"no": camp.campaign_no, "name": camp.name, "type": camp.campaign_type, "segment": camp.segment_id})
        session.commit()
        return camp.campaign_id


def update_campaign(company_id: int, user_id: int, campaign_id: int, f: CampaignFields) -> None:
    with new_session() as session:
        camp = _get(session, company_id, campaign_id)
        if camp.status_code in ("COMPLETED", "CANCELLED"):
            raise ValueError("کمپین بسته‌شده قابل ویرایش نیست.")
        if camp.status_code != "DRAFT" and (f.campaign_type != camp.campaign_type or f.segment_id != camp.segment_id):
            raise ValueError("پس از اجرا، نوع و سگمنت کمپین تغییر نمی‌کند؛ فقط تاریخ، هزینه و توضیحات.")
        before = {k: getattr(camp, k) for k in f.__dict__}
        _apply(session, company_id, camp, f)
        c.audit(session, company_id, user_id, "Campaign", campaign_id, "UPDATE",
                {k: [before[k], getattr(camp, k)] for k in before if before[k] != getattr(camp, k)})
        session.commit()


def delete_campaign(company_id: int, user_id: int, campaign_id: int) -> None:
    with new_session() as session:
        camp = _get(session, company_id, campaign_id)
        if camp.status_code != "DRAFT":
            raise ValueError("فقط کمپین پیش‌نویس حذف می‌شود؛ کمپین اجراشده را لغو کنید.")
        c.audit(session, company_id, user_id, "Campaign", campaign_id, "DELETE", {"name": camp.name})
        session.delete(camp)
        session.commit()


def set_status(company_id: int, user_id: int, campaign_id: int, status_code: str) -> None:
    """پایان یا لغو کمپین. پیامک‌های ارسال‌نشدهٔ کمپین لغوشده از صف ارسال بیرون می‌روند."""
    if status_code not in ("COMPLETED", "CANCELLED"):
        raise ValueError("وضعیت نامعتبر است.")
    with new_session() as session:
        camp = _get(session, company_id, campaign_id)
        if camp.status_code in ("COMPLETED", "CANCELLED"):
            raise ValueError("کمپین قبلاً بسته شده است.")
        if status_code == "CANCELLED" and camp.sms_campaign_id:
            sms = session.get(SmsCampaign, camp.sms_campaign_id)
            if sms is not None and sms.status_code == "PENDING":
                # صف پیامک موجود فقط PENDING/SENT/FAILED دارد؛ FAILED یعنی دیگر ارسال نمی‌شود
                sms.status_code = "FAILED"
                session.query(SmsCampaignRecipient).filter(SmsCampaignRecipient.campaign_id == sms.campaign_id,
                                                           SmsCampaignRecipient.status_code == "PENDING").update(
                    {"status_code": "FAILED", "error_message": "کمپین لغو شد"})
        old = camp.status_code
        camp.status_code, camp.updated_at = status_code, c.now()
        if status_code == "COMPLETED" and not camp.end_date:
            camp.end_date = datetime.date.today()
        c.audit(session, company_id, user_id, "Campaign", campaign_id, status_code, {"status": [old, status_code]})
        session.commit()


# --- مخاطبان ------------------------------------------------------------------------------------------
def _contacts(session, customer_ids: list[int]) -> dict[int, str | None]:
    rows = session.execute(select(CustomerDetail.detail_account_id, CustomerDetail.mobile, CustomerDetail.phone).where(
        CustomerDetail.detail_account_id.in_(customer_ids or [-1]))).all()
    return {cid: (mobile or phone) for cid, mobile, phone in rows}


def build_members(company_id: int, user_id: int, campaign_id: int) -> int:
    """مخاطبان هدف را از سگمنت کمپین (روی دادهٔ امروز) می‌سازد؛ مخاطبانی که پاسخ داده یا تبدیل شده‌اند حفظ می‌شوند."""
    with new_session() as session:
        camp = _get(session, company_id, campaign_id)
        if camp.status_code != "DRAFT":
            raise ValueError("مخاطبان فقط پیش از اجرای کمپین ساخته می‌شوند.")
        if not camp.segment_id:
            raise ValueError("برای کمپین سگمنت انتخاب نشده است.")
        segment_id = camp.segment_id
    ids = seg_service.members(company_id, segment_id)
    return _add_customers(company_id, user_id, campaign_id, ids, replace_targeted=True)


def add_customers(company_id: int, user_id: int, campaign_id: int, customer_ids: list[int]) -> int:
    return _add_customers(company_id, user_id, campaign_id, customer_ids, replace_targeted=False)


def _add_customers(company_id: int, user_id: int, campaign_id: int, customer_ids: list[int], replace_targeted: bool) -> int:
    with new_session() as session:
        camp = _get(session, company_id, campaign_id)
        if camp.status_code in ("COMPLETED", "CANCELLED"):
            raise ValueError("کمپین بسته شده است.")
        valid = set(session.scalars(select(DetailAccount.detail_account_id).where(
            DetailAccount.company_id == company_id, DetailAccount.detail_account_id.in_(customer_ids or [-1]))))
        if replace_targeted:
            session.query(CampaignMember).filter(CampaignMember.campaign_id == campaign_id, CampaignMember.status_code == "TARGETED",
                                                 CampaignMember.customer_detail_account_id.is_not(None)).delete()
        existing = set(session.scalars(select(CampaignMember.customer_detail_account_id).where(
            CampaignMember.campaign_id == campaign_id, CampaignMember.customer_detail_account_id.is_not(None))))
        contacts = _contacts(session, list(valid))
        added = 0
        for cid in customer_ids:
            if cid in valid and cid not in existing:
                session.add(CampaignMember(campaign_id=campaign_id, customer_detail_account_id=cid, contact=contacts.get(cid)))
                existing.add(cid)
                added += 1
        c.audit(session, company_id, user_id, "Campaign", campaign_id, "MEMBERS", {"added": added, "rebuild": replace_targeted})
        session.commit()
        return added


def add_leads(company_id: int, user_id: int, campaign_id: int, lead_ids: list[int]) -> int:
    with new_session() as session:
        camp = _get(session, company_id, campaign_id)
        if camp.status_code in ("COMPLETED", "CANCELLED"):
            raise ValueError("کمپین بسته شده است.")
        existing = set(session.scalars(select(CampaignMember.lead_id).where(CampaignMember.campaign_id == campaign_id,
                                                                            CampaignMember.lead_id.is_not(None))))
        added = 0
        for lead in session.scalars(select(Lead).where(Lead.company_id == company_id, Lead.lead_id.in_(lead_ids or [-1]))):
            if lead.lead_id in existing:
                continue
            session.add(CampaignMember(campaign_id=campaign_id, lead_id=lead.lead_id, contact=lead.mobile or lead.email or lead.phone,
                                       customer_detail_account_id=lead.converted_customer_detail_account_id))
            lead.campaign_id = lead.campaign_id or campaign_id
            added += 1
        session.commit()
        return added


def remove_member(company_id: int, user_id: int, member_id: int) -> None:
    with new_session() as session:
        m = session.get(CampaignMember, member_id)
        if m is None:
            raise ValueError("مخاطب نامعتبر است.")
        camp = _get(session, company_id, m.campaign_id)
        if m.status_code != "TARGETED" or camp.status_code != "DRAFT":
            raise ValueError("فقط مخاطب هدف کمپین اجرانشده حذف می‌شود.")
        session.delete(m)
        session.commit()


def set_member_status(company_id: int, user_id: int, member_id: int, status_code: str, note: str | None = None) -> None:
    if status_code not in ("RESPONDED", "CONVERTED", "OPTED_OUT"):
        raise ValueError("وضعیت مخاطب نامعتبر است.")
    with new_session() as session:
        m = session.get(CampaignMember, member_id)
        if m is None:
            raise ValueError("مخاطب نامعتبر است.")
        _get(session, company_id, m.campaign_id)
        m.status_code, m.note = status_code, (note or m.note)
        if status_code in ("RESPONDED", "CONVERTED") and not m.responded_at:
            m.responded_at = c.now()
        if status_code == "CONVERTED":
            m.converted_at = c.now()
        session.commit()


# --- اجرا ---------------------------------------------------------------------------------------------
def launch(company_id: int, user_id: int, campaign_id: int, scheduled_at: datetime.datetime | None = None) -> dict:
    """پیامک ← صف ارسال موجود؛ تماس/بازدید ← فعالیت برای مسئول کمپین؛ سایر انواع فقط فعال می‌شوند."""
    with new_session() as session:
        camp = _get(session, company_id, campaign_id)
        if camp.status_code != "DRAFT":
            raise ValueError("این کمپین قبلاً اجرا شده است.")
        members = list(session.scalars(select(CampaignMember).where(CampaignMember.campaign_id == campaign_id)))
        if not members:
            raise ValueError("کمپین مخاطبی ندارد.")
        result = {"sms_recipients": 0, "activities": 0}
        when = scheduled_at or c.now()
        if camp.campaign_type == "SMS":
            if not (camp.message_text or "").strip():
                raise ValueError("متن پیامک کمپین خالی است.")
            targets = [m for m in members if m.customer_detail_account_id and m.contact and m.status_code != "OPTED_OUT"]
            if not targets:
                raise ValueError("هیچ مخاطبی شمارهٔ تماس ندارد.")
            sms = SmsCampaign(company_id=company_id, name=f"CRM-{camp.campaign_no}: {camp.name}"[:150],
                              message_text=camp.message_text[:500], scheduled_at=when, created_by_user_id=user_id)
            session.add(sms)
            session.flush()
            for m in targets:
                session.add(SmsCampaignRecipient(campaign_id=sms.campaign_id, customer_detail_account_id=m.customer_detail_account_id,
                                                 phone_number=m.contact))
            for m in members:
                if m not in targets and m.status_code == "TARGETED" and m.customer_detail_account_id and not m.contact:
                    m.status_code, m.note = "FAILED", "شمارهٔ تماس ندارد"
            camp.sms_campaign_id = sms.campaign_id
            result["sms_recipients"] = len(targets)
        camp.status_code = "SCHEDULED" if scheduled_at and scheduled_at > c.now() else "ACTIVE"
        camp.scheduled_at, camp.start_date = when, camp.start_date or when.date()
        camp.updated_at = c.now()
        task_type = _TASK_TYPES.get(camp.campaign_type)
        task_targets = [(m.customer_detail_account_id, m.lead_id) for m in members if m.status_code == "TARGETED"]
        owner, name, no = camp.owner_user_id or user_id, camp.name, camp.campaign_no
        c.audit(session, company_id, user_id, "Campaign", campaign_id, "LAUNCH", {"members": len(members), **result})
        session.commit()
    if task_type:
        for customer_id, lead_id in task_targets:
            act_service.create_activity(company_id, user_id, act_service.ActivityFields(
                task_type, f"کمپین {no}: {name}", customer_detail_account_id=customer_id,
                lead_id=None if customer_id else lead_id, due_date=when.date(), assigned_to_user_id=owner))
            result["activities"] += 1
    return result


def sync_delivery(company_id: int) -> int:
    """وضعیت ارسال پیامک مخاطبان را از صف پیامک موجود برمی‌دارد. برمی‌گرداند: تعداد مخاطبان به‌روزشده."""
    changed = 0
    with new_session() as session:
        camps = list(session.scalars(select(Campaign).where(
            Campaign.company_id == company_id, Campaign.sms_campaign_id.is_not(None), Campaign.status_code.in_(("SCHEDULED", "ACTIVE")))))
        for camp in camps:
            sms = session.get(SmsCampaign, camp.sms_campaign_id)
            status = dict(session.execute(select(SmsCampaignRecipient.customer_detail_account_id, SmsCampaignRecipient.status_code).where(
                SmsCampaignRecipient.campaign_id == camp.sms_campaign_id)).all())
            for m in session.scalars(select(CampaignMember).where(CampaignMember.campaign_id == camp.campaign_id,
                                                                  CampaignMember.status_code == "TARGETED")):
                new = status.get(m.customer_detail_account_id)
                if new in ("SENT", "FAILED"):
                    m.status_code = new
                    changed += 1
            if camp.status_code == "SCHEDULED" and sms is not None and sms.status_code != "PENDING":
                camp.status_code = "ACTIVE"
        session.commit()
    return changed


# --- فهرست و تحلیل -------------------------------------------------------------------------------------
@dataclass
class CampaignRow:
    campaign_id: int
    campaign_no: int
    name: str
    campaign_type: str
    type_label: str
    status_code: str
    status_label: str
    segment_id: int | None
    segment_name: str
    lead_source_id: int | None
    start_date: datetime.date | None
    end_date: datetime.date | None
    attribution_days: int
    budget_amount: decimal.Decimal | None
    actual_cost: decimal.Decimal
    expected_revenue: decimal.Decimal | None
    message_text: str | None
    owner_user_id: int | None
    owner_name: str
    description: str | None
    member_count: int
    created_at: datetime.datetime


def list_campaigns(company_id: int, status: str | None = None, search: str | None = None) -> list[CampaignRow]:
    with new_session() as session:
        q = select(Campaign).where(Campaign.company_id == company_id)
        if status:
            q = q.where(Campaign.status_code == status)
        if search:
            q = q.where(Campaign.name.ilike(f"%{search}%"))
        camps = list(session.scalars(q.order_by(Campaign.campaign_no.desc())))
        counts = dict(session.execute(select(CampaignMember.campaign_id, func.count()).where(
            CampaignMember.campaign_id.in_([x.campaign_id for x in camps] or [-1])).group_by(CampaignMember.campaign_id)).all())
        segs = dict(session.execute(select(Segment.segment_id, Segment.name).where(Segment.company_id == company_id)).all())
        names = c.user_names(session, {x.owner_user_id for x in camps})
        return [CampaignRow(
            x.campaign_id, x.campaign_no, x.name, x.campaign_type, TYPES[x.campaign_type], x.status_code, STATUS[x.status_code],
            x.segment_id, segs.get(x.segment_id, ""), x.lead_source_id, x.start_date, x.end_date, x.attribution_days,
            x.budget_amount, x.actual_cost, x.expected_revenue, x.message_text, x.owner_user_id, names.get(x.owner_user_id, ""),
            x.description, counts.get(x.campaign_id, 0), x.created_at) for x in camps]


def get_campaign(company_id: int, campaign_id: int) -> CampaignRow:
    row = next((r for r in list_campaigns(company_id) if r.campaign_id == campaign_id), None)
    if row is None:
        raise ValueError("کمپین نامعتبر است.")
    return row


def list_members(company_id: int, campaign_id: int) -> list[dict]:
    with new_session() as session:
        _get(session, company_id, campaign_id)
        rows = session.execute(select(CampaignMember, DetailAccount.name, Lead.full_name).outerjoin(
            DetailAccount, DetailAccount.detail_account_id == CampaignMember.customer_detail_account_id).outerjoin(
            Lead, Lead.lead_id == CampaignMember.lead_id).where(CampaignMember.campaign_id == campaign_id)
            .order_by(CampaignMember.member_id)).all()
        return [{"member_id": m.member_id, "customer_detail_account_id": m.customer_detail_account_id, "lead_id": m.lead_id,
                 "name": cname or lname or "", "contact": m.contact, "status_code": m.status_code,
                 "status_label": MEMBER_STATUS[m.status_code], "responded_at": m.responded_at, "converted_at": m.converted_at,
                 "note": m.note} for m, cname, lname in rows]


def campaign_analytics(company_id: int, campaign_id: int, today: datetime.date | None = None) -> dict:
    """نرخ پاسخ و تبدیل، سرنخ‌ها و فرصت‌های نسبت‌داده‌شده، فروش مخاطبان در بازهٔ کمپین، هزینه به ازای سرنخ و ROI."""
    today = today or datetime.date.today()
    with new_session() as session:
        camp = _get(session, company_id, campaign_id)
        by_status = dict(session.execute(select(CampaignMember.status_code, func.count()).where(
            CampaignMember.campaign_id == campaign_id).group_by(CampaignMember.status_code)).all())
        customers = set(session.scalars(select(CampaignMember.customer_detail_account_id).where(
            CampaignMember.campaign_id == campaign_id, CampaignMember.customer_detail_account_id.is_not(None))))
        leads = session.execute(select(Lead.status_code, Lead.converted_customer_detail_account_id).where(
            Lead.campaign_id == campaign_id)).all()
        customers |= {cust for _s, cust in leads if cust}
        opps = session.execute(select(Opportunity.status_code, func.count(), func.coalesce(func.sum(Opportunity.amount), 0)).where(
            Opportunity.campaign_id == campaign_id).group_by(Opportunity.status_code)).all()
        start = camp.start_date or camp.created_at.date()
        end = min(today, (camp.end_date or today) + datetime.timedelta(days=camp.attribution_days))
        net = CommercialDocument.subtotal_amount - CommercialDocument.discount_amount
        buyers, invoices, revenue = session.execute(select(
            func.count(func.distinct(CommercialDocument.counterparty_detail_account_id)), func.count(),
            func.coalesce(func.sum(net), 0)).where(
            CommercialDocument.company_id == company_id, CommercialDocument.document_type_code == "SALES_INVOICE",
            CommercialDocument.status_code == "POSTED", CommercialDocument.counterparty_detail_account_id.in_(list(customers) or [-1]),
            CommercialDocument.document_date >= start, CommercialDocument.document_date <= end)).one()
        cost = camp.actual_cost or ZERO
    members = sum(by_status.values())
    reached = sum(by_status.get(k, 0) for k in ("SENT", "RESPONDED", "CONVERTED"))
    responded = by_status.get("RESPONDED", 0) + by_status.get("CONVERTED", 0)
    opp = {s: (n, decimal.Decimal(a)) for s, n, a in opps}
    revenue = decimal.Decimal(revenue)
    pct = lambda a, b: (decimal.Decimal(a) * 100 / b).quantize(decimal.Decimal("0.1")) if b else None
    return {
        "members": members, "by_status": {k: by_status.get(k, 0) for k in MEMBER_STATUS}, "reached": reached,
        "responded": responded, "response_rate": pct(responded, members),
        "leads": len(leads), "leads_converted": sum(1 for s, _c in leads if s == "CONVERTED"),
        "opportunities": sum(n for n, _a in opp.values()), "opportunities_won": opp.get("WON", (0, ZERO))[0],
        "won_amount": opp.get("WON", (0, ZERO))[1], "pipeline_amount": opp.get("OPEN", (0, ZERO))[1],
        "buyers": buyers, "invoices": invoices, "revenue": revenue, "conversion_rate": pct(buyers, len(customers)),
        "cost": cost, "budget": camp.budget_amount, "cost_per_lead": (cost / len(leads)).quantize(decimal.Decimal("0.01")) if leads else None,
        "roi_percent": pct(revenue - cost, cost) if cost else None, "window": (start, end),
    }
