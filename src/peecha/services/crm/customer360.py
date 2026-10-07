"""Customer 360: نمای واحد مشتری فقط از دادهٔ موجود ERP.

هویت از تفصیلی و پروفایل مشتری، مالی از حسابداری/خزانه/تسویه، فروش از اسناد تجاری، ارتباطات از فعالیت‌ها،
یادداشت‌ها، تماس‌ها، ویزیت‌ها و تیکت‌ها. هیچ مانده یا آماری ذخیره نمی‌شود؛ هر بخش با یک پرس‌وجوی تجمیعی خوانده
می‌شود تا صفحه سریع بماند. تایم‌لاین صفحه‌بندی دارد.
"""

from __future__ import annotations

import datetime
import decimal
from dataclasses import dataclass

from sqlalchemy import case, func, or_, select

from peecha.db.base import new_session
from peecha.db.models.accounting import (
    CustomerDetail, DetailAccount, JournalEntry, JournalEntryLine, JournalEntryLineDetail, JournalEntryStatus, JournalEntryType,
)
from peecha.db.models.commercial import (
    CommercialDocument, CommercialDocumentLine, CustomerActivity, CustomerCallLog, CustomerGroup, CustomerProfile,
    CustomerSalesNote, CustomerVisit, InvoiceSettlement, PartyAddress, PartyContact, ServiceTicket, VisitPlan,
)
from peecha.db.models.crm import Opportunity
from peecha.db.models.inventory import Item
from peecha.services import commercial_credit as credit_service
from peecha.services import commercial_settlements as settlements_service
from peecha.services import treasury as treasury_service
from peecha.services.crm import common as c

ZERO = decimal.Decimal(0)
CUSTOMER_TYPES = {"INDIVIDUAL": "شخص", "COMPANY": "شرکت", "STORE": "فروشگاه", "ORGANIZATION": "سازمان",
                  "WHOLESALER": "عمده‌فروش", "RETAILER": "خرده‌فروش", "AGENT": "نماینده", "ONLINE": "مشتری آنلاین"}
PERSON_TYPES = {"NATURAL": "حقیقی", "LEGAL": "حقوقی"}
PROFILE_STATUS = {"DRAFT": "پیش‌نویس", "PENDING_APPROVAL": "در انتظار تایید", "ACTIVE": "فعال", "SUSPENDED": "معلق",
                  "BLACKLISTED": "لیست سیاه", "INACTIVE": "غیرفعال"}
PRIORITY = {"LOW": "کم", "NORMAL": "عادی", "HIGH": "بالا", "VIP": "ویژه (VIP)"}
ONBOARDING = {"WALK_IN": "مراجعهٔ حضوری", "ONLINE": "آنلاین", "REFERRAL": "معرفی", "IMPORTED": "انتقال اطلاعات",
              "AGENT": "ویزیتور"}
DOC_LABELS = {"SALES_PROFORMA": "پیش‌فاکتور", "SALES_ORDER": "سفارش", "SALES_INVOICE": "فاکتور", "SALES_RETURN": "برگشت از فروش"}

# نوع رویدادهای تایم‌لاین → (برچسب، نماد)
TIMELINE_TYPES = {
    "CALL": ("تماس", "📞"), "MEETING": ("جلسه", "📅"), "VISIT": ("بازدید", "🚚"), "ORDER": ("سفارش", "🛒"),
    "PROFORMA": ("پیش‌فاکتور", "📝"), "INVOICE": ("فاکتور", "🧾"), "RETURN": ("برگشت از فروش", "↩️"),
    "PAYMENT": ("دریافت", "💰"), "NOTE": ("یادداشت", "💬"), "COMPLAINT": ("شکایت", "⚠️"), "TICKET": ("درخواست پشتیبانی", "🛠"),
    "TASK": ("وظیفه", "✅"), "FOLLOW_UP": ("پیگیری", "🔁"), "EMAIL": ("ایمیل", "✉️"), "MESSAGE": ("پیام", "💬"),
    "REMINDER": ("یادآور", "⏰"), "OPPORTUNITY": ("فرصت فروش", "🎯"),
}
_ACTIVITY_TO_TIMELINE = {"CALL": "CALL", "MEETING": "MEETING", "VISIT": "VISIT", "NOTE": "NOTE", "COMPLAINT": "COMPLAINT",
                         "TASK": "TASK", "FOLLOW_UP": "FOLLOW_UP", "EMAIL": "EMAIL", "MESSAGE": "MESSAGE",
                         "REMINDER": "REMINDER", "OPPORTUNITY": "OPPORTUNITY"}
_DOC_TO_TIMELINE = {"SALES_ORDER": "ORDER", "SALES_PROFORMA": "PROFORMA", "SALES_INVOICE": "INVOICE", "SALES_RETURN": "RETURN"}


def _check(session, company_id: int, customer_id: int) -> DetailAccount:
    da = session.get(DetailAccount, customer_id)
    if da is None or da.company_id != company_id:
        raise ValueError("مشتری نامعتبر است.")
    return da


# --- هویت ---------------------------------------------------------------------------------------------
def identity(company_id: int, customer_id: int) -> dict:
    with new_session() as session:
        da = _check(session, company_id, customer_id)
        det = session.get(CustomerDetail, customer_id)
        prof = session.get(CustomerProfile, customer_id)
        addr = session.scalar(select(PartyAddress).where(PartyAddress.party_detail_account_id == customer_id)
                              .order_by(PartyAddress.is_default.desc(), PartyAddress.address_id).limit(1))
        contact = session.scalar(select(PartyContact).where(PartyContact.party_detail_account_id == customer_id)
                                 .order_by(PartyContact.is_primary.desc(), PartyContact.contact_id).limit(1))
        refs = {x for x in ((prof.default_sales_rep_detail_account_id, prof.distribution_route_detail_account_id) if prof else ()) if x}
        names = dict(session.execute(select(DetailAccount.detail_account_id, DetailAccount.name).where(
            DetailAccount.detail_account_id.in_(refs or {-1}))).all())
        group = session.get(CustomerGroup, prof.customer_group_id) if prof and prof.customer_group_id else None
        visitor_ids = session.scalars(select(VisitPlan.assigned_visitor_user_id).where(
            VisitPlan.customer_detail_account_id == customer_id, VisitPlan.is_active.is_(True)).distinct()).all()
        visitors = c.user_names(session, visitor_ids)
        return {
            "customer_detail_account_id": customer_id, "code": da.code, "name": da.name, "is_active": da.is_active,
            "customer_type": CUSTOMER_TYPES.get(det.customer_type_code, det.customer_type_code or "") if det else "",
            "person_type": PERSON_TYPES.get(det.person_type_code, "") if det else "",
            "economic_code": det.economic_code if det else None, "national_id": det.national_id if det else None,
            "phone": det.phone if det else None, "mobile": det.mobile if det else None,
            "email": contact.email if contact else None, "contact_name": contact.full_name if contact else None,
            "address": (addr.line1 if addr else None) or (det.address if det else None),
            "city": addr.city if addr else None, "province": addr.province if addr else None,
            "region": det.geographic_region if det else None, "customer_class": det.customer_class if det else None,
            "gps": ((addr.gps_latitude, addr.gps_longitude) if addr and addr.gps_latitude is not None
                    else (prof.gps_latitude, prof.gps_longitude) if prof and prof.gps_latitude is not None else None),
            "onboarding_source": ONBOARDING.get(prof.onboarding_source_code, "") if prof else "",
            "sales_rep": names.get(prof.default_sales_rep_detail_account_id, "") if prof else "",
            "route": names.get(prof.distribution_route_detail_account_id, "") if prof else "",
            "visitors": "، ".join(visitors.values()),
            "group": group.name if group else "", "priority_code": prof.priority_code if prof else None,
            "level": PRIORITY.get(prof.priority_code, "") if prof else "",
            "status_code": prof.status_code if prof else None, "status": PROFILE_STATUS.get(prof.status_code, "") if prof else "",
            "credit_limit": prof.credit_limit_amount if prof else ZERO, "payment_term_days": prof.payment_term_days if prof else 0,
            "notes": det.notes if det else None,
        }


# --- مالی (فقط خواندن از حسابداری/خزانه/تسویه) ------------------------------------------------------------
def financial(company_id: int, customer_id: int, today: datetime.date | None = None) -> dict:
    today = today or datetime.date.today()
    with new_session() as session:
        _check(session, company_id, customer_id)
        base = (select(func.coalesce(func.sum(JournalEntryLine.debit_amount_base), 0),
                       func.coalesce(func.sum(JournalEntryLine.credit_amount_base), 0))
                .join(JournalEntryLineDetail, JournalEntryLineDetail.line_id == JournalEntryLine.line_id)
                .join(JournalEntry, JournalEntry.journal_entry_id == JournalEntryLine.journal_entry_id)
                .join(JournalEntryStatus, JournalEntryStatus.status_id == JournalEntry.status_id)
                .where(JournalEntry.company_id == company_id, JournalEntryLineDetail.detail_account_id == customer_id,
                       JournalEntryStatus.code != "DRAFT"))
        debit, credit = (decimal.Decimal(x) for x in session.execute(base).one())
        last_payment = session.execute(
            select(JournalEntry.document_date, JournalEntryLine.credit_amount_base)
            .join(JournalEntryLine, JournalEntryLine.journal_entry_id == JournalEntry.journal_entry_id)
            .join(JournalEntryLineDetail, JournalEntryLineDetail.line_id == JournalEntryLine.line_id)
            .join(JournalEntryType, JournalEntryType.entry_type_id == JournalEntry.entry_type_id)
            .join(JournalEntryStatus, JournalEntryStatus.status_id == JournalEntry.status_id)
            .where(JournalEntry.company_id == company_id, JournalEntryLineDetail.detail_account_id == customer_id,
                   JournalEntryType.code == "RECEIPT", JournalEntryLine.credit_amount_base > 0, JournalEntryStatus.code != "DRAFT")
            .order_by(JournalEntry.document_date.desc(), JournalEntry.journal_entry_id.desc()).limit(1)).first()
        prof = session.get(CustomerProfile, customer_id)
    balance, nature = treasury_service.get_counterparty_balance(company_id, customer_id)
    exposure = credit_service.compute_customer_exposure(company_id, customer_id)
    unsettled = settlements_service.list_unsettled_invoices_bulk(company_id, counterparty_ids=[customer_id])
    overdue = [u for u in unsettled if u.due_date and u.due_date < today]
    upcoming = sorted((u for u in unsettled if u.due_date and u.due_date >= today), key=lambda u: u.due_date)
    limit = decimal.Decimal(prof.credit_limit_amount or 0) if prof else ZERO
    if limit and exposure > limit:
        credit_state = "OVER_LIMIT"
    elif overdue:
        credit_state = "OVERDUE"
    elif limit and exposure > limit * decimal.Decimal("0.8"):
        credit_state = "NEAR_LIMIT"
    else:
        credit_state = "OK"
    return {
        "debit_total": debit, "credit_total": credit, "balance": balance, "balance_nature": nature,
        "credit_limit": limit, "exposure": exposure, "available_credit": max(ZERO, limit - exposure) if limit else None,
        "open_invoice_count": len(unsettled), "open_amount": sum((u.remaining_amount for u in unsettled), ZERO),
        "overdue_count": len(overdue), "overdue_amount": sum((u.remaining_amount for u in overdue), ZERO),
        "max_days_overdue": max(((today - u.due_date).days for u in overdue), default=0),
        "next_due_date": upcoming[0].due_date if upcoming else None,
        "next_due_amount": upcoming[0].remaining_amount if upcoming else ZERO,
        "last_payment_date": last_payment[0] if last_payment else None,
        "last_payment_amount": decimal.Decimal(last_payment[1]) if last_payment else None,
        "payment_term_days": prof.payment_term_days if prof else 0,
        "credit_state": credit_state,
        "credit_state_label": {"OK": "عادی", "NEAR_LIMIT": "نزدیک سقف اعتبار", "OVERDUE": "بدهی معوق",
                               "OVER_LIMIT": "عبور از سقف اعتبار"}[credit_state],
    }


# --- فروش ---------------------------------------------------------------------------------------------
def sales(company_id: int, customer_id: int, today: datetime.date | None = None, top_n: int = 5) -> dict:
    today = today or datetime.date.today()
    month_start, year_start = today.replace(day=1), today.replace(month=1, day=1)
    last_year_start = year_start.replace(year=year_start.year - 1)
    with new_session() as session:
        _check(session, company_id, customer_id)
        inv = (CommercialDocument.company_id == company_id, CommercialDocument.counterparty_detail_account_id == customer_id,
               CommercialDocument.document_type_code == "SALES_INVOICE", CommercialDocument.status_code == "POSTED")
        amt = CommercialDocument.total_amount
        d = CommercialDocument.document_date
        row = session.execute(select(
            func.count(), func.coalesce(func.sum(amt), 0), func.min(d), func.max(d),
            func.coalesce(func.sum(case((d >= month_start, amt), else_=0)), 0),
            func.coalesce(func.sum(case((d >= year_start, amt), else_=0)), 0),
            func.coalesce(func.sum(case(((d >= last_year_start) & (d < year_start), amt), else_=0)), 0),
        ).where(*inv)).one()
        count, total, first, last, this_month, this_year, last_year = row
        dates = list(session.scalars(select(d).where(*inv).distinct().order_by(d)))
        returns = session.scalar(select(func.coalesce(func.sum(amt), 0)).where(
            CommercialDocument.company_id == company_id, CommercialDocument.counterparty_detail_account_id == customer_id,
            CommercialDocument.document_type_code == "SALES_RETURN", CommercialDocument.status_code == "POSTED"))
        orders = session.scalar(select(func.count()).where(
            CommercialDocument.company_id == company_id, CommercialDocument.counterparty_detail_account_id == customer_id,
            CommercialDocument.document_type_code == "SALES_ORDER", CommercialDocument.status_code != "CANCELLED"))
        item_da = DetailAccount.__table__.alias("item_da")
        top = session.execute(
            select(CommercialDocumentLine.item_id, item_da.c.name, func.count(func.distinct(CommercialDocument.document_id)),
                   func.sum(CommercialDocumentLine.quantity_base), func.sum(CommercialDocumentLine.line_total))
            .join(CommercialDocument, CommercialDocument.document_id == CommercialDocumentLine.document_id)
            .join(Item, Item.item_id == CommercialDocumentLine.item_id)
            .join(item_da, item_da.c.detail_account_id == Item.item_detail_account_id).where(*inv)
            .group_by(CommercialDocumentLine.item_id, item_da.c.name)
            .order_by(func.count(func.distinct(CommercialDocument.document_id)).desc(), func.sum(CommercialDocumentLine.line_total).desc())
            .limit(top_n)).all()
        bought = select(CommercialDocumentLine.item_id).join(
            CommercialDocument, CommercialDocument.document_id == CommercialDocumentLine.document_id).where(*inv)
        # پرفروش‌ترین کالاهای شرکت در ۹۰ روز اخیر که این مشتری هرگز نخریده (فرصت فروش مکمل)
        not_bought = session.execute(
            select(CommercialDocumentLine.item_id, item_da.c.name, func.sum(CommercialDocumentLine.line_total))
            .join(CommercialDocument, CommercialDocument.document_id == CommercialDocumentLine.document_id)
            .join(Item, Item.item_id == CommercialDocumentLine.item_id)
            .join(item_da, item_da.c.detail_account_id == Item.item_detail_account_id)
            .where(CommercialDocument.company_id == company_id, CommercialDocument.document_type_code == "SALES_INVOICE",
                   CommercialDocument.status_code == "POSTED", CommercialDocument.document_date >= today - datetime.timedelta(days=90),
                   CommercialDocumentLine.item_id.not_in(bought))
            .group_by(CommercialDocumentLine.item_id, item_da.c.name)
            .order_by(func.sum(CommercialDocumentLine.line_total).desc()).limit(top_n)).all()
    gaps = [(b - a).days for a, b in zip(dates, dates[1:])]
    avg_gap = (sum(gaps) / len(gaps)) if gaps else None
    total = decimal.Decimal(total)
    return {
        "invoice_count": count, "order_count": orders or 0, "total_sales": total, "returns": decimal.Decimal(returns or 0),
        "net_sales": total - decimal.Decimal(returns or 0),
        "avg_invoice": (total / count).quantize(decimal.Decimal("0.01")) if count else ZERO,
        "first_purchase": first, "last_purchase": last,
        "days_since_last": (today - last).days if last else None,
        "sales_this_month": decimal.Decimal(this_month), "sales_this_year": decimal.Decimal(this_year),
        "sales_last_year": decimal.Decimal(last_year),
        "avg_days_between": round(avg_gap, 1) if avg_gap is not None else None,
        "purchase_days": len(dates),
        "top_items": [{"item_id": i, "name": n, "times": t, "quantity": q, "amount": a} for i, n, t, q, a in top],
        "not_bought_items": [{"item_id": i, "name": n} for i, n, _a in not_bought],
    }


# --- اقدام‌های هوشمند (قاعده‌محور؛ فاز ۴ موتور کامل‌تر را جایگزین می‌کند) -------------------------------
def smart_actions(ident: dict, fin: dict, sal: dict, open_tickets: int = 0) -> list[dict]:
    out = []
    days, gap = sal.get("days_since_last"), sal.get("avg_days_between")
    if days is not None and gap and days > gap * 1.4 and days >= 14:
        out.append({"code": "FOLLOW_UP_SALES", "severity": "warning", "action": "FOLLOW_UP",
                    "text": f"این مشتری معمولاً هر {round(gap)} روز خرید می‌کند و اکنون {days} روز گذشته است.",
                    "suggestion": "پیگیری فروش"})
    elif days is not None and days >= 60:
        out.append({"code": "INACTIVE", "severity": "warning", "action": "CALL",
                    "text": f"این مشتری {days} روز است خرید نکرده.", "suggestion": "تماس پیگیری"})
    if fin.get("overdue_amount"):
        out.append({"code": "COLLECTION", "severity": "danger", "action": "FOLLOW_UP",
                    "text": f"{fin['overdue_count']} فاکتور معوق دارد (بیشترین تأخیر {fin['max_days_overdue']} روز).",
                    "suggestion": "پیگیری وصول"})
    if fin.get("credit_state") == "OVER_LIMIT":
        out.append({"code": "CREDIT", "severity": "danger", "action": "TASK", "text": "از سقف اعتبار عبور کرده است.",
                    "suggestion": "بررسی اعتبار پیش از فروش نسیه"})
    if ident.get("priority_code") == "VIP":
        out.append({"code": "VIP", "severity": "info", "action": "TASK", "text": "مشتری ویژه (VIP) است.",
                    "suggestion": "خدمت با اولویت"})
    if open_tickets:
        out.append({"code": "TICKETS", "severity": "warning", "action": "TASK", "text": f"{open_tickets} درخواست پشتیبانی باز دارد.",
                    "suggestion": "پیگیری درخواست‌ها"})
    if not sal.get("invoice_count"):
        out.append({"code": "FIRST_SALE", "severity": "info", "action": "CALL", "text": "هنوز خریدی ثبت نکرده است.",
                    "suggestion": "معرفی محصولات و اولین سفارش"})
    return out


def summary_text(ident: dict, fin: dict, sal: dict) -> str:
    """خلاصهٔ متنی مشتری (قاعده‌محور؛ جای اتصال خلاصه‌ساز هوشمند در آینده)."""
    parts = [f"{ident['name']}"]
    if sal["invoice_count"]:
        parts.append(f"تاکنون {sal['invoice_count']} فاکتور به مبلغ کل {sal['total_sales']:,.0f} داشته")
        if sal["days_since_last"] is not None:
            parts.append(f"آخرین خرید {sal['days_since_last']} روز پیش بوده")
        if sal["avg_days_between"]:
            parts.append(f"به‌طور میانگین هر {round(sal['avg_days_between'])} روز خرید می‌کند")
    else:
        parts.append("هنوز خریدی نداشته")
    if fin["overdue_count"]:
        parts.append(f"{fin['overdue_count']} فاکتور معوق به مبلغ {fin['overdue_amount']:,.0f} دارد")
    elif fin["balance"]:
        parts.append(f"ماندهٔ حساب {fin['balance']:,.0f} ({fin['balance_nature']}) است")
    return "؛ ".join(parts) + "."


def customer_360(company_id: int, customer_id: int, today: datetime.date | None = None) -> dict:
    ident = identity(company_id, customer_id)
    fin = financial(company_id, customer_id, today)
    sal = sales(company_id, customer_id, today)
    with new_session() as session:
        open_acts = session.scalar(select(func.count()).where(
            CustomerActivity.company_id == company_id, CustomerActivity.customer_detail_account_id == customer_id,
            CustomerActivity.status_code.in_(c.ACTIVITY_OPEN_STATUSES)))
        overdue_acts = session.scalar(select(func.count()).where(
            CustomerActivity.company_id == company_id, CustomerActivity.customer_detail_account_id == customer_id,
            CustomerActivity.status_code.in_(c.ACTIVITY_OPEN_STATUSES), CustomerActivity.due_date < (today or datetime.date.today())))
        opps = session.execute(select(func.count(), func.coalesce(func.sum(Opportunity.amount), 0)).where(
            Opportunity.company_id == company_id, Opportunity.customer_detail_account_id == customer_id,
            Opportunity.status_code == "OPEN")).one()
        tickets = session.scalar(select(func.count()).where(
            ServiceTicket.customer_detail_account_id == customer_id, ServiceTicket.status_code.not_in(("CLOSED", "RESOLVED", "CANCELLED"))))
        last_visit = session.scalar(select(func.max(CustomerVisit.checked_in_at)).where(
            CustomerVisit.company_id == company_id, CustomerVisit.customer_detail_account_id == customer_id))
    return {"identity": ident, "financial": fin, "sales": sal,
            "counts": {"open_activities": open_acts, "overdue_activities": overdue_acts, "open_opportunities": opps[0],
                       "open_opportunity_value": decimal.Decimal(opps[1]), "open_tickets": tickets, "last_visit": last_visit},
            "smart_actions": smart_actions(ident, fin, sal, tickets), "summary": summary_text(ident, fin, sal),
            "analytics": analytics_block(company_id, customer_id)}


def analytics_block(company_id: int, customer_id: int) -> dict | None:
    """امتیازهای کش‌شدهٔ تحلیل (RFM، سلامت، ریزش، CLV) و سگمنت‌های فعلی مشتری؛ بدون کش ← None."""
    from peecha.services.crm import analytics, insights, segments
    sc = analytics.get_score(company_id, customer_id)
    if sc is None:
        return None
    return {"health_score": sc.health_score, "health_band": sc.health_band, "health_label": insights.HEALTH_BANDS[sc.health_band][0],
            "churn_risk": sc.churn_risk, "churn_band": sc.churn_band, "churn_label": insights.CHURN_BANDS[sc.churn_band],
            "rfm": f"{sc.r_score or '-'}{sc.f_score or '-'}{sc.m_score or '-'}", "rfm_segment": sc.rfm_segment,
            "rfm_label": analytics.RFM_SEGMENTS.get(sc.rfm_segment or "", ""), "clv_historical": sc.clv_historical,
            "clv_predicted": sc.clv_predicted, "next_best_action": sc.next_best_action, "factors": sc.factors,
            "computed_at": sc.computed_at, "segments": [s.name for s in segments.segments_of_customer(company_id, customer_id)]}


# --- تایم‌لاین ---------------------------------------------------------------------------------------
@dataclass
class TimelineEvent:
    at: datetime.datetime
    kind: str
    label: str
    icon: str
    title: str
    detail: str
    amount: decimal.Decimal | None
    status: str
    ref_type: str
    ref_id: int


def _dt(value) -> datetime.datetime:
    if isinstance(value, datetime.datetime):
        return value.replace(tzinfo=None) if value.tzinfo is None else value.astimezone().replace(tzinfo=None)
    return datetime.datetime.combine(value, datetime.time(12, 0))


def timeline(company_id: int, customer_id: int, *, kinds: list[str] | None = None, date_from: datetime.date | None = None,
             date_to: datetime.date | None = None, search: str | None = None, limit: int = 50, offset: int = 0) -> list[TimelineEvent]:
    """رویدادهای همهٔ منابع، جدیدترین اول. هر منبع با سقف (offset+limit) خوانده و سپس ادغام می‌شود."""
    want = set(kinds or TIMELINE_TYPES)
    cap = offset + limit
    lo = datetime.datetime.combine(date_from, datetime.time.min) if date_from else None
    hi = datetime.datetime.combine(date_to, datetime.time.max) if date_to else None
    like = f"%{search.strip()}%" if search else None
    events: list[TimelineEvent] = []

    def add(at, kind, title, detail="", amount=None, status="", ref_type="", ref_id=0):
        label, icon = TIMELINE_TYPES[kind]
        events.append(TimelineEvent(_dt(at), kind, label, icon, title, detail or "", amount, status, ref_type, ref_id))

    with new_session() as session:
        _check(session, company_id, customer_id)
        act_kinds = [k for k, v in _ACTIVITY_TO_TIMELINE.items() if v in want]
        if act_kinds:
            when = func.coalesce(CustomerActivity.start_at, CustomerActivity.resolved_at, CustomerActivity.created_at)
            q = select(CustomerActivity).where(CustomerActivity.company_id == company_id,
                                               CustomerActivity.customer_detail_account_id == customer_id,
                                               CustomerActivity.activity_type_code.in_(act_kinds))
            if lo:
                q = q.where(when >= lo)
            if hi:
                q = q.where(when <= hi)
            if like:
                q = q.where(or_(CustomerActivity.subject.ilike(like), CustomerActivity.description.ilike(like),
                                CustomerActivity.result_text.ilike(like)))
            for a in session.scalars(q.order_by(when.desc()).limit(cap)):
                add(a.start_at or a.resolved_at or a.created_at, _ACTIVITY_TO_TIMELINE[a.activity_type_code], a.subject,
                    a.result_text or a.description or "", a.estimated_value, c.ACTIVITY_STATUS.get(a.status_code, a.status_code),
                    "activity", a.activity_id)
        if "NOTE" in want:
            q = select(CustomerSalesNote).where(CustomerSalesNote.company_id == company_id,
                                                CustomerSalesNote.customer_detail_account_id == customer_id)
            q = q.where(CustomerSalesNote.created_at >= lo) if lo else q
            q = q.where(CustomerSalesNote.created_at <= hi) if hi else q
            q = q.where(CustomerSalesNote.note_text.ilike(like)) if like else q
            for n in session.scalars(q.order_by(CustomerSalesNote.created_at.desc()).limit(cap)):
                add(n.created_at, "NOTE", n.note_text[:120], n.note_text, ref_type="sales_note", ref_id=n.note_id)
        if "CALL" in want:
            q = select(CustomerCallLog).where(CustomerCallLog.company_id == company_id,
                                              CustomerCallLog.customer_detail_account_id == customer_id)
            q = q.where(CustomerCallLog.started_at >= lo) if lo else q
            q = q.where(CustomerCallLog.started_at <= hi) if hi else q
            q = q.where(CustomerCallLog.note.ilike(like)) if like else q
            for cl in session.scalars(q.order_by(CustomerCallLog.started_at.desc()).limit(cap)):
                add(cl.started_at, "CALL", f"تماس با {cl.phone_number}", cl.note or "", status="موفق" if cl.was_successful else "ناموفق",
                    ref_type="call_log", ref_id=cl.call_log_id)
        if "VISIT" in want and not like:
            q = select(CustomerVisit).where(CustomerVisit.company_id == company_id,
                                            CustomerVisit.customer_detail_account_id == customer_id)
            q = q.where(CustomerVisit.checked_in_at >= lo) if lo else q
            q = q.where(CustomerVisit.checked_in_at <= hi) if hi else q
            users = {}
            visits = list(session.scalars(q.order_by(CustomerVisit.checked_in_at.desc()).limit(cap)))
            users = c.user_names(session, [v.visitor_user_id for v in visits])
            for v in visits:
                dur = int((v.checked_out_at - v.checked_in_at).total_seconds() // 60) if v.checked_out_at else None
                add(v.checked_in_at, "VISIT", f"ویزیت {users.get(v.visitor_user_id, '')}".strip(),
                    "، ".join(x for x in (f"{dur} دقیقه" if dur is not None else "", "خارج از محدوده" if v.is_outside_geofence else "",
                                          v.notes or "") if x), status=v.status_code, ref_type="visit", ref_id=v.customer_visit_id)
        doc_types = [t for t, k in _DOC_TO_TIMELINE.items() if k in want]
        if doc_types:
            q = select(CommercialDocument).where(CommercialDocument.company_id == company_id,
                                                 CommercialDocument.counterparty_detail_account_id == customer_id,
                                                 CommercialDocument.document_type_code.in_(doc_types))
            q = q.where(CommercialDocument.document_date >= date_from) if date_from else q
            q = q.where(CommercialDocument.document_date <= date_to) if date_to else q
            q = q.where(or_(CommercialDocument.description.ilike(like), CommercialDocument.reference_no.ilike(like))) if like else q
            for doc in session.scalars(q.order_by(CommercialDocument.document_date.desc(), CommercialDocument.document_id.desc()).limit(cap)):
                add(doc.created_at if doc.document_date == doc.created_at.date() else doc.document_date,
                    _DOC_TO_TIMELINE[doc.document_type_code], f"{DOC_LABELS[doc.document_type_code]} شمارهٔ {doc.document_no}",
                    doc.description or "", doc.total_amount, doc.status_code, "document", doc.document_id)
        if "PAYMENT" in want and not like:
            q = (select(JournalEntry.journal_entry_id, JournalEntry.document_date, JournalEntry.description,
                        func.sum(JournalEntryLine.credit_amount_base))
                 .join(JournalEntryLine, JournalEntryLine.journal_entry_id == JournalEntry.journal_entry_id)
                 .join(JournalEntryLineDetail, JournalEntryLineDetail.line_id == JournalEntryLine.line_id)
                 .join(JournalEntryType, JournalEntryType.entry_type_id == JournalEntry.entry_type_id)
                 .join(JournalEntryStatus, JournalEntryStatus.status_id == JournalEntry.status_id)
                 .where(JournalEntry.company_id == company_id, JournalEntryLineDetail.detail_account_id == customer_id,
                        JournalEntryType.code == "RECEIPT", JournalEntryLine.credit_amount_base > 0, JournalEntryStatus.code != "DRAFT"))
            q = q.where(JournalEntry.document_date >= date_from) if date_from else q
            q = q.where(JournalEntry.document_date <= date_to) if date_to else q
            for jid, ddate, desc, amount in session.execute(q.group_by(JournalEntry.journal_entry_id, JournalEntry.document_date,
                                                                       JournalEntry.description)
                                                             .order_by(JournalEntry.document_date.desc()).limit(cap)):
                add(ddate, "PAYMENT", "دریافت وجه", desc or "", decimal.Decimal(amount), "", "journal_entry", jid)
            q = (select(InvoiceSettlement).join(CommercialDocument, CommercialDocument.document_id == InvoiceSettlement.invoice_document_id)
                 .where(InvoiceSettlement.company_id == company_id, CommercialDocument.counterparty_detail_account_id == customer_id,
                        InvoiceSettlement.journal_entry_id.is_(None)))
            q = q.where(InvoiceSettlement.settlement_date >= date_from) if date_from else q
            q = q.where(InvoiceSettlement.settlement_date <= date_to) if date_to else q
            for st in session.scalars(q.order_by(InvoiceSettlement.settlement_date.desc()).limit(cap)):
                add(st.settlement_date, "PAYMENT", "تسویهٔ فاکتور", st.description or "", st.amount, "", "settlement", st.settlement_id)
        if "TICKET" in want:
            q = select(ServiceTicket).where(ServiceTicket.customer_detail_account_id == customer_id)
            q = q.where(ServiceTicket.opened_at >= lo) if lo else q
            q = q.where(ServiceTicket.opened_at <= hi) if hi else q
            q = q.where(or_(ServiceTicket.subject.ilike(like), ServiceTicket.description.ilike(like))) if like else q
            for t in session.scalars(q.order_by(ServiceTicket.opened_at.desc()).limit(cap)):
                add(t.opened_at, "TICKET", t.subject, t.description or "", status=t.status_code, ref_type="ticket", ref_id=t.ticket_id)
        if "OPPORTUNITY" in want:
            q = select(Opportunity).where(Opportunity.company_id == company_id, Opportunity.customer_detail_account_id == customer_id)
            q = q.where(Opportunity.created_at >= lo) if lo else q
            q = q.where(Opportunity.created_at <= hi) if hi else q
            q = q.where(Opportunity.title.ilike(like)) if like else q
            for o in session.scalars(q.order_by(Opportunity.created_at.desc()).limit(cap)):
                add(o.created_at, "OPPORTUNITY", o.title, o.description or "", o.amount, c.OPP_STATUS[o.status_code],
                    "opportunity", o.opportunity_id)
    events.sort(key=lambda e: e.at, reverse=True)
    return events[offset:offset + limit]


# --- انتخاب مشتری -----------------------------------------------------------------------------------
def search_customers(company_id: int, text: str = "", limit: int = 30) -> list[dict]:
    with new_session() as session:
        q = (select(DetailAccount.detail_account_id, DetailAccount.code, DetailAccount.name, CustomerDetail.mobile, CustomerDetail.phone)
             .join(CustomerProfile, CustomerProfile.customer_detail_account_id == DetailAccount.detail_account_id)
             .outerjoin(CustomerDetail, CustomerDetail.detail_account_id == DetailAccount.detail_account_id)
             .where(DetailAccount.company_id == company_id))
        if text.strip():
            like = f"%{text.strip()}%"
            q = q.where(or_(DetailAccount.name.ilike(like), DetailAccount.code.ilike(like), CustomerDetail.mobile.ilike(like),
                            CustomerDetail.phone.ilike(like), CustomerDetail.national_id.ilike(like)))
        return [{"customer_detail_account_id": i, "code": code, "name": name, "mobile": m, "phone": p}
                for i, code, name, m, p in session.execute(q.order_by(DetailAccount.name).limit(limit))]
