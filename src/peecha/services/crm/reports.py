"""داشبورد، پیش‌بینی فروش، عملکرد فروشنده، جستجوی سراسری، تقویم و ۱۶ گزارش CRM (فاز ۹، R288).

گزارش‌ها ReportDef همان موتور و صفحهٔ عمومی گزارش‌اند (اجرای پس‌زمینه، صفحه‌بندی، گروه‌بندی، خروجی و چاپ).
دابل‌کلیک ردیف مشتری (مرجع «CRM_CUSTOMER») پروندهٔ ۳۶۰ را باز می‌کند. همهٔ اعداد از جدول‌های موجود ERP/CRM خوانده می‌شود.
"""

from __future__ import annotations

import datetime
import decimal
from collections import defaultdict

from sqlalchemy import func, or_, select

from peecha.db.base import new_session
from peecha.db.models.accounting import DetailAccount
from peecha.db.models.commercial import CommercialDocument, CustomerActivity, ServiceTicket, VisitPlan
from peecha.db.models.crm import Campaign, CustomerScore, Lead, LeadSource, Opportunity, PipelineStage
from peecha.services.crm import analytics
from peecha.services.crm import common as c
from peecha.services.purchase_reports import DATE, INT, MONEY, PERCENT, TEXT, ReportDef, ReportResult, _jalali_month

ZERO = decimal.Decimal(0)
_HUNDRED = decimal.Decimal(100)


def _pct(a, b) -> decimal.Decimal | None:
    return (decimal.Decimal(a) * _HUNDRED / decimal.Decimal(b)).quantize(decimal.Decimal("0.1")) if b else None


def _span(date_from: datetime.date, date_to: datetime.date):
    return (datetime.datetime.combine(date_from, datetime.time.min).astimezone(),
            datetime.datetime.combine(date_to + datetime.timedelta(days=1), datetime.time.min).astimezone())


def _cust(cid):
    return (cid, "CRM_CUSTOMER") if cid else None


def c_doc_title(code: str) -> str:
    from peecha.services import commercial_documents as documents_service

    return documents_service._DOC_TYPE_TITLES.get(code, code)


def _net():
    return CommercialDocument.subtotal_amount - CommercialDocument.discount_amount


# =====================================================================================================
# داشبورد
# =====================================================================================================
def dashboard(company_id: int, date_from: datetime.date, date_to: datetime.date, owner_user_id: int | None = None) -> dict:
    t0, t1 = _span(date_from, date_to)
    today = datetime.date.today()
    with new_session() as session:
        lq = [Lead.company_id == company_id]
        oq = [Opportunity.company_id == company_id]
        aq = [CustomerActivity.company_id == company_id]
        if owner_user_id:
            lq.append(Lead.owner_user_id == owner_user_id)
            oq.append(Opportunity.owner_user_id == owner_user_id)
            aq.append(or_(CustomerActivity.assigned_to_user_id == owner_user_id,
                          CustomerActivity.assigned_to_user_id.is_(None) & (CustomerActivity.created_by_user_id == owner_user_id)))
        new_leads = session.scalar(select(func.count()).where(*lq, Lead.created_at >= t0, Lead.created_at < t1))
        converted = session.scalar(select(func.count()).where(*lq, Lead.converted_at >= t0, Lead.converted_at < t1))
        open_cnt, open_amt, weighted = session.execute(select(
            func.count(), func.coalesce(func.sum(Opportunity.amount), 0),
            func.coalesce(func.sum(Opportunity.amount * Opportunity.probability_percent / 100), 0)).where(
            *oq, Opportunity.status_code == "OPEN")).one()
        closed = dict((s, (n, decimal.Decimal(a))) for s, n, a in session.execute(select(
            Opportunity.status_code, func.count(), func.coalesce(func.sum(Opportunity.amount), 0)).where(
            *oq, Opportunity.status_code.in_(("WON", "LOST")), Opportunity.closed_at >= t0, Opportunity.closed_at < t1)
            .group_by(Opportunity.status_code)))
        cycle = session.scalar(select(func.avg(func.extract("epoch", Opportunity.closed_at - Opportunity.created_at) / 86400)).where(
            *oq, Opportunity.status_code == "WON", Opportunity.closed_at >= t0, Opportunity.closed_at < t1))
        done = session.scalar(select(func.count()).where(*aq, CustomerActivity.status_code.in_(("DONE", "RESOLVED")),
                                                         CustomerActivity.resolved_at >= t0, CustomerActivity.resolved_at < t1))
        overdue = session.scalar(select(func.count()).where(*aq, CustomerActivity.status_code.in_(c.ACTIVITY_OPEN_STATUSES),
                                                            CustomerActivity.due_date < today))
        tickets_open, breached = session.execute(select(
            func.count().filter(ServiceTicket.status_code.in_(("OPEN", "IN_PROGRESS"))),
            func.count().filter(ServiceTicket.sla_breached.is_(True) & ServiceTicket.status_code.in_(("OPEN", "IN_PROGRESS")))).where(
            ServiceTicket.company_id == company_id)).one()
        csat = session.scalar(select(func.avg(ServiceTicket.satisfaction_score)).where(
            ServiceTicket.company_id == company_id, ServiceTicket.resolved_at >= t0, ServiceTicket.resolved_at < t1))
        sales, buyers = session.execute(select(func.coalesce(func.sum(_net()), 0),
                                               func.count(func.distinct(CommercialDocument.counterparty_detail_account_id))).where(
            CommercialDocument.company_id == company_id, CommercialDocument.document_type_code == "SALES_INVOICE",
            CommercialDocument.status_code == "POSTED", CommercialDocument.document_date.between(date_from, date_to))).one()
        bands = dict(session.execute(select(CustomerScore.churn_band, func.count()).where(
            CustomerScore.company_id == company_id).group_by(CustomerScore.churn_band)).all())
        active_campaigns = session.scalar(select(func.count()).where(Campaign.company_id == company_id,
                                                                     Campaign.status_code.in_(("ACTIVE", "SCHEDULED"))))
    won_n, won_amt = closed.get("WON", (0, ZERO))
    lost_n, lost_amt = closed.get("LOST", (0, ZERO))
    return {
        "new_leads": new_leads, "converted_leads": converted, "lead_conversion": _pct(converted, new_leads),
        "open_opportunities": open_cnt, "pipeline_amount": decimal.Decimal(open_amt), "weighted_pipeline": decimal.Decimal(weighted).quantize(decimal.Decimal("0.01")),
        "won": won_n, "won_amount": won_amt, "lost": lost_n, "lost_amount": lost_amt, "win_rate": _pct(won_n, won_n + lost_n),
        "avg_deal": (won_amt / won_n).quantize(decimal.Decimal("0.01")) if won_n else None,
        "avg_cycle_days": decimal.Decimal(str(round(float(cycle), 1))) if cycle is not None else None,
        "activities_done": done, "overdue_activities": overdue, "open_tickets": tickets_open, "breached_tickets": breached,
        "csat": decimal.Decimal(str(round(float(csat), 1))) if csat is not None else None,
        "sales": decimal.Decimal(sales), "buyers": buyers, "high_churn": bands.get("HIGH", 0), "active_campaigns": active_campaigns,
    }


def forecast(company_id: int, months: int = 3, today: datetime.date | None = None) -> list[dict]:
    """پیش‌بینی ماه‌های آینده: فرصت‌های باز با تاریخ بستن (کل، وزنی با احتمال مرحله، قطعی ≥۸۰٪) + روند فروش جاری
    (میانگین فروش خالص ماهانهٔ ۶ ماه گذشته). فرصت‌های باز گذشته از تاریخ بستن در ماه جاری حساب می‌شوند."""
    today = today or datetime.date.today()
    first = today.replace(day=1)
    with new_session() as session:
        base = session.scalar(select(func.coalesce(func.sum(_net()), 0)).where(
            CommercialDocument.company_id == company_id, CommercialDocument.document_type_code == "SALES_INVOICE",
            CommercialDocument.status_code == "POSTED", CommercialDocument.document_date >= first - datetime.timedelta(days=182),
            CommercialDocument.document_date < first))
        opps = session.execute(select(Opportunity.expected_close_date, Opportunity.amount, Opportunity.probability_percent).where(
            Opportunity.company_id == company_id, Opportunity.status_code == "OPEN")).all()
    run_rate = (decimal.Decimal(base) / 6).quantize(decimal.Decimal("0.01"))
    out = []
    starts = []
    m = first
    for _ in range(months):
        starts.append(m)
        m = (m + datetime.timedelta(days=32)).replace(day=1)
    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else m
        rows = [(a, p) for d, a, p in opps if d is not None and (d < end) and (d >= start or (i == 0 and d < start))]
        undated = [(a, p) for d, a, p in opps if d is None] if i == len(starts) - 1 else []
        weighted = sum((a * p / _HUNDRED for a, p in rows), ZERO).quantize(decimal.Decimal("0.01"))
        out.append({"month": _jalali_month(start), "start": start, "opportunities": len(rows), "pipeline": sum((a for a, _p in rows), ZERO),
                    "weighted": weighted, "commit": sum((a for a, p in rows if p >= 80), ZERO), "run_rate": run_rate,
                    "forecast": run_rate + weighted, "undated_pipeline": sum((a for a, _p in undated), ZERO)})
    return out


def performance(company_id: int, date_from: datetime.date, date_to: datetime.date) -> list[dict]:
    """عملکرد هر کاربر فروش: سرنخ، تبدیل، فرصت برنده/بازنده، مبلغ برنده، فعالیت انجام‌شده و عقب‌افتاده، تیکت حل‌شده، فاکتور ثبت‌شده."""
    t0, t1 = _span(date_from, date_to)
    today = datetime.date.today()
    stats: dict[int, dict] = defaultdict(lambda: defaultdict(lambda: 0))
    with new_session() as session:
        for uid, n, conv in session.execute(select(Lead.owner_user_id, func.count(), func.count(Lead.converted_at)).where(
                Lead.company_id == company_id, Lead.created_at >= t0, Lead.created_at < t1).group_by(Lead.owner_user_id)):
            stats[uid]["leads"], stats[uid]["converted"] = n, conv
        for uid, st, n, amt in session.execute(select(Opportunity.owner_user_id, Opportunity.status_code, func.count(),
                                                      func.coalesce(func.sum(Opportunity.amount), 0)).where(
                Opportunity.company_id == company_id, Opportunity.status_code.in_(("WON", "LOST")), Opportunity.closed_at >= t0,
                Opportunity.closed_at < t1).group_by(Opportunity.owner_user_id, Opportunity.status_code)):
            stats[uid][st.lower()] = n
            if st == "WON":
                stats[uid]["won_amount"] = decimal.Decimal(amt)
        for uid, n in session.execute(select(Opportunity.owner_user_id, func.count()).where(
                Opportunity.company_id == company_id, Opportunity.status_code == "OPEN").group_by(Opportunity.owner_user_id)):
            stats[uid]["open_opps"] = n
        owner = func.coalesce(CustomerActivity.assigned_to_user_id, CustomerActivity.created_by_user_id)
        for uid, n in session.execute(select(owner, func.count()).where(
                CustomerActivity.company_id == company_id, CustomerActivity.status_code.in_(("DONE", "RESOLVED")),
                CustomerActivity.resolved_at >= t0, CustomerActivity.resolved_at < t1).group_by(owner)):
            stats[uid]["activities"] = n
        for uid, n in session.execute(select(owner, func.count()).where(
                CustomerActivity.company_id == company_id, CustomerActivity.status_code.in_(c.ACTIVITY_OPEN_STATUSES),
                CustomerActivity.due_date < today).group_by(owner)):
            stats[uid]["overdue"] = n
        for uid, n in session.execute(select(ServiceTicket.assigned_to_user_id, func.count()).where(
                ServiceTicket.company_id == company_id, ServiceTicket.resolved_at >= t0, ServiceTicket.resolved_at < t1)
                .group_by(ServiceTicket.assigned_to_user_id)):
            stats[uid]["tickets"] = n
        for uid, n, amt in session.execute(select(CommercialDocument.created_by_user_id, func.count(), func.coalesce(func.sum(_net()), 0)).where(
                CommercialDocument.company_id == company_id, CommercialDocument.document_type_code == "SALES_INVOICE",
                CommercialDocument.status_code == "POSTED", CommercialDocument.document_date.between(date_from, date_to))
                .group_by(CommercialDocument.created_by_user_id)):
            stats[uid]["invoices"], stats[uid]["sales"] = n, decimal.Decimal(amt)
        names = c.user_names(session, {u for u in stats if u})
    out = []
    for uid, s in stats.items():
        if uid is None:
            continue
        out.append({"user_id": uid, "name": names.get(uid, str(uid)), "leads": s["leads"], "converted": s["converted"],
                    "lead_conversion": _pct(s["converted"], s["leads"]), "won": s["won"], "lost": s["lost"],
                    "won_amount": s["won_amount"] or ZERO, "win_rate": _pct(s["won"], s["won"] + s["lost"]), "open_opps": s["open_opps"],
                    "activities": s["activities"], "overdue": s["overdue"], "tickets": s["tickets"], "invoices": s["invoices"],
                    "sales": s["sales"] or ZERO})
    return sorted(out, key=lambda x: (-(x["sales"] + x["won_amount"]), x["name"]))


# =====================================================================================================
# جستجو و تقویم
# =====================================================================================================
def search(company_id: int, text: str, limit: int = 10) -> list[dict]:
    """جستجوی سراسری CRM: مشتری، سرنخ، فرصت، تیکت، کمپین و سند فروش (شماره)."""
    from peecha.services.crm.customer360 import search_customers

    q = (text or "").strip()
    if len(q) < 2 and not q.isdigit():
        return []
    like = f"%{q}%"
    out = [{"kind": "CUSTOMER", "kind_label": "مشتری", "id": r["customer_detail_account_id"], "title": r["name"],
            "subtitle": " — ".join(x for x in (r["code"], r["mobile"] or r["phone"]) if x), "customer_id": r["customer_detail_account_id"]}
           for r in search_customers(company_id, q, limit)]
    with new_session() as session:
        for x in session.scalars(select(Lead).where(Lead.company_id == company_id, or_(
                Lead.full_name.ilike(like), Lead.company_name.ilike(like), Lead.mobile.ilike(like), Lead.email.ilike(like))).limit(limit)):
            out.append({"kind": "LEAD", "kind_label": "سرنخ", "id": x.lead_id, "title": x.full_name,
                        "subtitle": f"{x.lead_no} — {c.LEAD_STATUS.get(x.status_code, x.status_code)}",
                        "customer_id": x.converted_customer_detail_account_id})
        num = int(q) if q.isdigit() else -1
        for x in session.scalars(select(Opportunity).where(Opportunity.company_id == company_id, or_(
                Opportunity.title.ilike(like), Opportunity.opportunity_no == num)).limit(limit)):
            out.append({"kind": "OPPORTUNITY", "kind_label": "فرصت", "id": x.opportunity_id, "title": x.title,
                        "subtitle": f"{x.opportunity_no} — {c.OPP_STATUS.get(x.status_code, x.status_code)}",
                        "customer_id": x.customer_detail_account_id})
        for x in session.scalars(select(ServiceTicket).where(ServiceTicket.company_id == company_id, or_(
                ServiceTicket.subject.ilike(like), ServiceTicket.ticket_no == num)).limit(limit)):
            out.append({"kind": "TICKET", "kind_label": "تیکت", "id": x.ticket_id, "title": x.subject, "subtitle": f"{x.ticket_no or ''}",
                        "customer_id": x.customer_detail_account_id})
        for x in session.scalars(select(Campaign).where(Campaign.company_id == company_id, Campaign.name.ilike(like)).limit(limit)):
            out.append({"kind": "CAMPAIGN", "kind_label": "کمپین", "id": x.campaign_id, "title": x.name, "subtitle": str(x.campaign_no),
                        "customer_id": None})
        for d, name in session.execute(select(CommercialDocument, DetailAccount.name).join(
                DetailAccount, DetailAccount.detail_account_id == CommercialDocument.counterparty_detail_account_id).where(
                CommercialDocument.company_id == company_id, CommercialDocument.document_type_code.like("SALES_%"),
                CommercialDocument.document_no == num).limit(limit)):
            out.append({"kind": "DOCUMENT", "kind_label": "سند فروش", "id": d.document_id, "title": f"{c_doc_title(d.document_type_code)} {d.document_no}",
                        "subtitle": name, "customer_id": d.counterparty_detail_account_id, "document_type_code": d.document_type_code})
    return out


def calendar(company_id: int, user_id: int | None, date_from: datetime.date, date_to: datetime.date) -> list[dict]:
    """رویدادهای بازه برای کاربر (None = همه): فعالیت‌ها، ویزیت برنامه‌ریزی‌شده، بستن مورد انتظار فرصت، موعد تیکت، کمپین."""
    events: list[dict] = []
    with new_session() as session:
        q = select(CustomerActivity, DetailAccount.name).outerjoin(
            DetailAccount, DetailAccount.detail_account_id == CustomerActivity.customer_detail_account_id).where(
            CustomerActivity.company_id == company_id, CustomerActivity.due_date.between(date_from, date_to))
        if user_id:
            q = q.where(or_(CustomerActivity.assigned_to_user_id == user_id,
                            CustomerActivity.assigned_to_user_id.is_(None) & (CustomerActivity.created_by_user_id == user_id)))
        for a, name in session.execute(q):
            events.append({"date": a.due_date, "kind": "ACTIVITY", "kind_label": c.ACTIVITY_TYPES.get(a.activity_type_code, ""),
                           "title": a.subject, "party": name or "", "id": a.activity_id, "customer_id": a.customer_detail_account_id,
                           "done": a.status_code not in c.ACTIVITY_OPEN_STATUSES})
        vq = select(VisitPlan, DetailAccount.name).join(DetailAccount, DetailAccount.detail_account_id == VisitPlan.customer_detail_account_id).where(
            VisitPlan.company_id == company_id, VisitPlan.is_active.is_(True))
        if user_id:
            vq = vq.where(VisitPlan.assigned_visitor_user_id == user_id)
        plans = session.execute(vq).all()
        day = date_from
        while day <= date_to and (date_to - date_from).days <= 92:
            for p, name in plans:
                if p.visit_day_of_week == day.weekday():
                    events.append({"date": day, "kind": "VISIT", "kind_label": "ویزیت", "title": f"ویزیت {name}", "party": name,
                                   "id": p.visit_plan_id, "customer_id": p.customer_detail_account_id, "done": False})
            day += datetime.timedelta(days=1)
        oq = select(Opportunity).where(Opportunity.company_id == company_id, Opportunity.status_code == "OPEN",
                                       Opportunity.expected_close_date.between(date_from, date_to))
        if user_id:
            oq = oq.where(Opportunity.owner_user_id == user_id)
        for o in session.scalars(oq):
            events.append({"date": o.expected_close_date, "kind": "OPPORTUNITY", "kind_label": "بستن فرصت", "title": o.title, "party": "",
                           "id": o.opportunity_id, "customer_id": o.customer_detail_account_id, "done": False})
        t0, t1 = _span(date_from, date_to)
        tq = select(ServiceTicket).where(ServiceTicket.company_id == company_id, ServiceTicket.status_code.in_(("OPEN", "IN_PROGRESS")),
                                         ServiceTicket.resolution_due_at >= t0, ServiceTicket.resolution_due_at < t1)
        if user_id:
            tq = tq.where(ServiceTicket.assigned_to_user_id == user_id)
        for t in session.scalars(tq):
            events.append({"date": t.resolution_due_at.astimezone().date(), "kind": "TICKET", "kind_label": "موعد تیکت", "title": t.subject,
                           "party": "", "id": t.ticket_id, "customer_id": t.customer_detail_account_id, "done": False})
        for cp in session.scalars(select(Campaign).where(Campaign.company_id == company_id, or_(
                Campaign.start_date.between(date_from, date_to), Campaign.end_date.between(date_from, date_to)))):
            for d, label in ((cp.start_date, "شروع کمپین"), (cp.end_date, "پایان کمپین")):
                if d and date_from <= d <= date_to:
                    events.append({"date": d, "kind": "CAMPAIGN", "kind_label": label, "title": cp.name, "party": "", "id": cp.campaign_id,
                                   "customer_id": None, "done": cp.status_code in ("COMPLETED", "CANCELLED")})
    order = {"ACTIVITY": 0, "VISIT": 1, "TICKET": 2, "OPPORTUNITY": 3, "CAMPAIGN": 4}
    return sorted(events, key=lambda e: (e["date"], order[e["kind"]], e["title"]))


# =====================================================================================================
# ۱۶ گزارش (روی موتور عمومی گزارش)
# =====================================================================================================
_G_SALES, _G_CUST, _G_SERV, _G_MKT = "فروش و قیف", "تحلیل مشتری", "خدمات مشتری", "بازاریابی و فعالیت"


def lead_sources(company_id: int, f) -> ReportResult:
    t0, t1 = _span(f.date_from, f.date_to)
    r = ReportResult([("منبع", TEXT), ("سرنخ", INT), ("تبدیل‌شده", INT), ("نرخ تبدیل", PERCENT), ("ارزش احتمالی", MONEY),
                      ("فرصت برنده", INT), ("مبلغ برنده", MONEY)])
    with new_session() as session:
        names = dict(session.execute(select(LeadSource.source_id, LeadSource.name)).all())
        leads = session.execute(select(Lead.source_id, func.count(), func.count(Lead.converted_at), func.coalesce(func.sum(Lead.estimated_value), 0))
                                .where(Lead.company_id == company_id, Lead.created_at >= t0, Lead.created_at < t1).group_by(Lead.source_id)).all()
        won = dict((s, (n, a)) for s, n, a in session.execute(select(Opportunity.source_id, func.count(), func.coalesce(func.sum(Opportunity.amount), 0))
                                                              .where(Opportunity.company_id == company_id, Opportunity.status_code == "WON",
                                                                     Opportunity.closed_at >= t0, Opportunity.closed_at < t1).group_by(Opportunity.source_id)))
    for sid, n, conv, val in sorted(leads, key=lambda x: -x[1]):
        w = won.get(sid, (0, 0))
        r.add([names.get(sid, "بدون منبع"), n, conv, _pct(conv, n), decimal.Decimal(val), w[0], decimal.Decimal(w[1])])
    return r


def lead_funnel(company_id: int, f) -> ReportResult:
    t0, t1 = _span(f.date_from, f.date_to)
    r = ReportResult([("وضعیت", TEXT), ("تعداد", INT), ("سهم", PERCENT), ("ارزش احتمالی", MONEY), ("میانگین امتیاز", INT)], no_total={2, 4})
    with new_session() as session:
        rows = dict((s, (n, v, sc)) for s, n, v, sc in session.execute(select(
            Lead.status_code, func.count(), func.coalesce(func.sum(Lead.estimated_value), 0), func.avg(Lead.score)).where(
            Lead.company_id == company_id, Lead.created_at >= t0, Lead.created_at < t1).group_by(Lead.status_code)))
    total = sum(n for n, _v, _s in rows.values())
    for code, label in c.LEAD_STATUS.items():
        n, v, sc = rows.get(code, (0, 0, None))
        r.add([label, n, _pct(n, total), decimal.Decimal(v), int(round(float(sc))) if sc is not None else None])
    return r


def pipeline_by_stage(company_id: int, f) -> ReportResult:
    r = ReportResult([("قیف", TEXT), ("مرحله", TEXT), ("احتمال", PERCENT), ("تعداد فرصت", INT), ("مبلغ", MONEY), ("مبلغ وزنی", MONEY),
                      ("میانگین روز در مرحله", INT)], no_total={2, 6})
    from peecha.db.models.crm import Pipeline

    now = c.now()
    with new_session() as session:
        stages = session.execute(select(PipelineStage, Pipeline.name).join(Pipeline, Pipeline.pipeline_id == PipelineStage.pipeline_id)
                                 .where(Pipeline.company_id == company_id, PipelineStage.stage_type == "OPEN")
                                 .order_by(Pipeline.pipeline_id, PipelineStage.sort_order)).all()
        opps = defaultdict(list)
        for o in session.scalars(select(Opportunity).where(Opportunity.company_id == company_id, Opportunity.status_code == "OPEN")):
            opps[o.stage_id].append(o)
    for st, pname in stages:
        rows = opps.get(st.stage_id, [])
        amt = sum((o.amount for o in rows), ZERO)
        r.add([pname, st.name, st.probability_percent, len(rows), amt,
               sum((o.amount * o.probability_percent / _HUNDRED for o in rows), ZERO).quantize(decimal.Decimal("0.01")),
               round(sum((now - o.stage_entered_at).days for o in rows) / len(rows)) if rows else None])
    return r


def won_lost(company_id: int, f) -> ReportResult:
    t0, t1 = _span(f.date_from, f.date_to)
    r = ReportResult([("نتیجه", TEXT), ("علت/عنوان", TEXT), ("تعداد", INT), ("مبلغ", MONEY), ("میانگین چرخهٔ فروش (روز)", INT)], no_total={4})
    with new_session() as session:
        rows = session.scalars(select(Opportunity).where(Opportunity.company_id == company_id, Opportunity.status_code.in_(("WON", "LOST")),
                                                         Opportunity.closed_at >= t0, Opportunity.closed_at < t1)).all()
    groups: dict[tuple, list] = defaultdict(list)
    for o in rows:
        groups[(o.status_code, (o.lost_reason or "نامشخص") if o.status_code == "LOST" else "برنده")].append(o)
    for (st, reason), items in sorted(groups.items(), key=lambda x: (x[0][0] != "WON", -len(x[1]))):
        r.add([c.OPP_STATUS[st], reason, len(items), sum((o.amount for o in items), ZERO),
               round(sum((o.closed_at - o.created_at).days for o in items) / len(items))])
    return r


def salesperson_performance(company_id: int, f) -> ReportResult:
    r = ReportResult([("کاربر", TEXT), ("سرنخ", INT), ("تبدیل", INT), ("نرخ تبدیل", PERCENT), ("فرصت باز", INT), ("برنده", INT),
                      ("بازنده", INT), ("نرخ موفقیت", PERCENT), ("مبلغ برنده", MONEY), ("فعالیت انجام‌شده", INT), ("عقب‌افتاده", INT),
                      ("تیکت حل‌شده", INT), ("فاکتور", INT), ("فروش خالص", MONEY)])
    for p in performance(company_id, f.date_from, f.date_to):
        r.add([p["name"], p["leads"], p["converted"], p["lead_conversion"], p["open_opps"], p["won"], p["lost"], p["win_rate"],
               p["won_amount"], p["activities"], p["overdue"], p["tickets"], p["invoices"], p["sales"]])
    return r


def activity_report(company_id: int, f) -> ReportResult:
    r = ReportResult([("کاربر", TEXT), ("نوع", TEXT), ("کل", INT), ("انجام‌شده", INT), ("باز", INT), ("عقب‌افتاده", INT)])
    today = datetime.date.today()
    owner = func.coalesce(CustomerActivity.assigned_to_user_id, CustomerActivity.created_by_user_id)
    with new_session() as session:
        rows = session.execute(select(owner, CustomerActivity.activity_type_code, func.count(),
                                      func.count().filter(CustomerActivity.status_code.in_(("DONE", "RESOLVED"))),
                                      func.count().filter(CustomerActivity.status_code.in_(c.ACTIVITY_OPEN_STATUSES)),
                                      func.count().filter(CustomerActivity.status_code.in_(c.ACTIVITY_OPEN_STATUSES) & (CustomerActivity.due_date < today)))
                               .where(CustomerActivity.company_id == company_id, CustomerActivity.due_date.between(f.date_from, f.date_to))
                               .group_by(owner, CustomerActivity.activity_type_code)).all()
        names = c.user_names(session, {x[0] for x in rows})
    for uid, typ, n, done, open_, late in sorted(rows, key=lambda x: (names.get(x[0], ""), x[1])):
        r.add([names.get(uid, ""), c.ACTIVITY_TYPES.get(typ, typ), n, done, open_, late])
    return r


def overdue_followups(company_id: int, f) -> ReportResult:
    r = ReportResult([("مسئول", TEXT), ("نوع", TEXT), ("موضوع", TEXT), ("مشتری/سرنخ", TEXT), ("موعد", DATE), ("روز تأخیر", INT),
                      ("اولویت", TEXT)], no_total={5})
    today = f.date_to if f.date_to < datetime.date.today() else datetime.date.today()
    with new_session() as session:
        rows = session.execute(select(CustomerActivity, DetailAccount.name, Lead.full_name).outerjoin(
            DetailAccount, DetailAccount.detail_account_id == CustomerActivity.customer_detail_account_id).outerjoin(
            Lead, Lead.lead_id == CustomerActivity.lead_id).where(
            CustomerActivity.company_id == company_id, CustomerActivity.status_code.in_(c.ACTIVITY_OPEN_STATUSES),
            CustomerActivity.due_date < today).order_by(CustomerActivity.due_date)).all()
        names = c.user_names(session, {a.assigned_to_user_id or a.created_by_user_id for a, _n, _l in rows})
    for a, cname, lname in rows:
        r.add([names.get(a.assigned_to_user_id or a.created_by_user_id, ""), c.ACTIVITY_TYPES.get(a.activity_type_code, ""), a.subject,
               cname or lname or "", a.due_date, (today - a.due_date).days, c.PRIORITIES.get(a.priority_code, "")],
              _cust(a.customer_detail_account_id))
    return r


def rfm_report(company_id: int, f) -> ReportResult:
    analytics.ensure_fresh(company_id)
    r = ReportResult([("گروه رفتار خرید", TEXT), ("تعداد مشتری", INT), ("خرید ۱۲ ماه", MONEY), ("سهم مبلغ", PERCENT)])
    m = analytics.rfm_matrix(company_id)
    total = sum((x["monetary"] for x in m), ZERO)
    for x in m:
        r.add([x["label"], x["count"], x["monetary"], _pct(x["monetary"], total)])
    return r


def _scores_report(company_id: int, rows: list[dict], extra) -> ReportResult:
    r = ReportResult([("کد", TEXT), ("مشتری", TEXT), ("گروه رفتار خرید", TEXT), ("سلامت", INT), ("احتمال ریزش", PERCENT), ("روز از آخرین خرید", INT),
                      ("خرید ۱۲ ماه", MONEY), ("ارزش طول عمر", MONEY), ("ارزش پیش‌بینی", MONEY), ("بدهی معوق", MONEY), ("اقدام پیشنهادی", TEXT)],
                     no_total={3, 4, 5})
    for x in rows:
        if extra(x):
            r.add([x["code"], x["name"], x["rfm_label"], x["health_score"], x["churn_risk"], x["recency_days"], x["monetary_365"],
                   x["clv_historical"], x["clv_predicted"], x["overdue_amount"], x["next_best_action"] or ""], _cust(x["customer_detail_account_id"]))
    return r


def churn_report(company_id: int, f) -> ReportResult:
    analytics.ensure_fresh(company_id)
    band = str(f.options.get("band") or "HIGH")
    return _scores_report(company_id, analytics.list_scores(company_id, order="churn"),
                          lambda x: band == "ALL" or x["churn_band"] == band or (band == "MEDIUM_UP" and x["churn_band"] != "LOW"))


def clv_report(company_id: int, f) -> ReportResult:
    analytics.ensure_fresh(company_id)
    return _scores_report(company_id, analytics.list_scores(company_id, order="clv"), lambda x: x["invoice_count_total"] > 0)


def inactive_customers(company_id: int, f) -> ReportResult:
    analytics.ensure_fresh(company_id)
    days = int(f.options.get("days") or 60)
    return _scores_report(company_id, sorted(analytics.list_scores(company_id), key=lambda x: -(x["recency_days"] or 0)),
                          lambda x: x["recency_days"] is not None and x["recency_days"] >= days)


def campaign_report(company_id: int, f) -> ReportResult:
    from peecha.services.crm import campaigns as camp_service

    r = ReportResult([("کمپین", TEXT), ("نوع", TEXT), ("وضعیت", TEXT), ("مخاطب", INT), ("پاسخ", INT), ("نرخ پاسخ", PERCENT), ("سرنخ", INT),
                      ("سرنخ تبدیل‌شده", INT), ("خریدار", INT), ("فروش", MONEY), ("هزینه", MONEY), ("هزینه هر سرنخ", MONEY), ("بازگشت سرمایه", PERCENT)],
                     no_total={11})
    for cp in camp_service.list_campaigns(company_id):
        if cp.start_date and cp.start_date > f.date_to:
            continue
        if cp.end_date and cp.end_date < f.date_from:
            continue
        a = camp_service.campaign_analytics(company_id, cp.campaign_id)
        r.add([cp.name, cp.type_label, cp.status_label, a["members"], a["responded"], a["response_rate"], a["leads"], a["leads_converted"],
               a["buyers"], a["revenue"], a["cost"], a["cost_per_lead"], a["roi_percent"]])
    return r


def tickets_sla(company_id: int, f) -> ReportResult:
    from peecha.services.crm import tickets as ticket_service

    t0, t1 = _span(f.date_from, f.date_to)
    r = ReportResult([("نوع", TEXT), ("کل", INT), ("باز", INT), ("نقض تعهد زمانی", INT), ("پایبندی به تعهد زمانی", PERCENT),
                      ("میانگین اولین پاسخ (ساعت)", TEXT), ("میانگین حل (ساعت)", TEXT), ("رضایت (از ۵)", TEXT)])
    hours = lambda a, b: func.avg(func.extract("epoch", a - b) / 3600)
    with new_session() as session:
        rows = session.execute(select(ServiceTicket.ticket_type, func.count(),
                                      func.count().filter(ServiceTicket.status_code.in_(("OPEN", "IN_PROGRESS"))),
                                      func.count().filter(ServiceTicket.sla_breached.is_(True)),
                                      hours(ServiceTicket.first_responded_at, ServiceTicket.opened_at),
                                      hours(ServiceTicket.resolved_at, ServiceTicket.opened_at), func.avg(ServiceTicket.satisfaction_score))
                               .where(ServiceTicket.company_id == company_id, ServiceTicket.opened_at >= t0, ServiceTicket.opened_at < t1)
                               .group_by(ServiceTicket.ticket_type)).all()
    fmt = lambda v: f"{float(v):.1f}" if v is not None else ""
    for typ, n, open_, br, resp, res, cs in rows:
        r.add([ticket_service.TYPES.get(typ, typ), n, open_, br, _pct(n - br, n), fmt(resp), fmt(res), fmt(cs)])
    return r


def complaints(company_id: int, f) -> ReportResult:
    t0, t1 = _span(f.date_from, f.date_to)
    r = ReportResult([("مشتری", TEXT), ("دسته", TEXT), ("تعداد شکایت", INT), ("باز", INT), ("نقض تعهد زمانی", INT), ("آخرین شکایت", DATE)])
    with new_session() as session:
        rows = session.execute(select(ServiceTicket.customer_detail_account_id, DetailAccount.name, ServiceTicket.category, func.count(),
                                      func.count().filter(ServiceTicket.status_code.in_(("OPEN", "IN_PROGRESS"))),
                                      func.count().filter(ServiceTicket.sla_breached.is_(True)), func.max(ServiceTicket.opened_at))
                               .join(DetailAccount, DetailAccount.detail_account_id == ServiceTicket.customer_detail_account_id)
                               .where(ServiceTicket.company_id == company_id, ServiceTicket.ticket_type == "COMPLAINT",
                                      ServiceTicket.opened_at >= t0, ServiceTicket.opened_at < t1)
                               .group_by(ServiceTicket.customer_detail_account_id, DetailAccount.name, ServiceTicket.category)).all()
    for cid, name, cat, n, open_, br, last in sorted(rows, key=lambda x: -x[3]):
        r.add([name, cat or "بدون دسته", n, open_, br, last.astimezone().date()], _cust(cid))
    return r


def satisfaction(company_id: int, f) -> ReportResult:
    from peecha.services.crm import tickets as ticket_service

    t0, t1 = _span(f.date_from, f.date_to)
    r = ReportResult([("شماره", INT), ("مشتری", TEXT), ("نوع", TEXT), ("موضوع", TEXT), ("حل‌شده در", DATE), ("امتیاز", INT), ("نظر مشتری", TEXT)],
                     no_total={0, 5})
    with new_session() as session:
        rows = session.execute(select(ServiceTicket, DetailAccount.name).join(
            DetailAccount, DetailAccount.detail_account_id == ServiceTicket.customer_detail_account_id).where(
            ServiceTicket.company_id == company_id, ServiceTicket.satisfaction_score.is_not(None), ServiceTicket.resolved_at >= t0,
            ServiceTicket.resolved_at < t1).order_by(ServiceTicket.satisfaction_score, ServiceTicket.resolved_at.desc())).all()
    for t, name in rows:
        r.add([t.ticket_no, name, ticket_service.TYPES.get(t.ticket_type, t.ticket_type), t.subject, t.resolved_at.astimezone().date(),
               t.satisfaction_score, t.satisfaction_comment or ""], _cust(t.customer_detail_account_id))
    if rows:
        r.note = f"میانگین رضایت: {sum(t.satisfaction_score for t, _n in rows) / len(rows):.1f} از ۵ ({len(rows)} پاسخ)"
    return r


def forecast_report(company_id: int, f) -> ReportResult:
    months = int(f.options.get("months") or 3)
    r = ReportResult([("ماه", TEXT), ("فرصت باز", INT), ("مبلغ فرصت‌ها", MONEY), ("وزنی (احتمال مرحله)", MONEY), ("قطعی (≥۸۰٪)", MONEY),
                      ("روند فروش ماهانه", MONEY), ("پیش‌بینی فروش", MONEY)], no_total={5})
    rows = forecast(company_id, months)
    for x in rows:
        r.add([x["month"], x["opportunities"], x["pipeline"], x["weighted"], x["commit"], x["run_rate"], x["forecast"]])
    if rows and rows[-1]["undated_pipeline"]:
        r.note = f"فرصت‌های بدون تاریخ بستن (در پیش‌بینی نیست): {rows[-1]['undated_pipeline']:,.0f}"
    return r


_NO = ()
_CHURN_OPT = (("band", "سطح احتمال ریزش", (("HIGH", "زیاد"), ("MEDIUM_UP", "متوسط و زیاد"), ("ALL", "همه"))),)
_DAYS_OPT = (("days", "روز بدون خرید", (("60", "۶۰ روز"), ("30", "۳۰ روز"), ("90", "۹۰ روز"), ("180", "۱۸۰ روز"))),)
_MONTHS_OPT = (("months", "تعداد ماه", (("3", "۳ ماه"), ("6", "۶ ماه"), ("12", "۱۲ ماه"))),)

CRM_REPORTS: list[ReportDef] = [
    ReportDef("CRM_LEAD_SOURCES", "عملکرد منابع سرنخ", lead_sources, _NO, "سرنخ، تبدیل و فروش برندهٔ هر منبع.", "range", _G_SALES),
    ReportDef("CRM_LEAD_FUNNEL", "قیف سرنخ", lead_funnel, _NO, "سرنخ‌های بازه به تفکیک وضعیت.", "range", _G_SALES),
    ReportDef("CRM_PIPELINE", "قیف فروش به تفکیک مرحله", pipeline_by_stage, _NO, "فرصت‌های باز هر مرحله با مبلغ وزنی.", "none", _G_SALES),
    ReportDef("CRM_WON_LOST", "تحلیل برد و باخت", won_lost, _NO, "فرصت‌های بسته‌شده و علت باخت.", "range", _G_SALES),
    ReportDef("CRM_PERFORMANCE", "عملکرد فروشندگان", salesperson_performance, _NO, "سرنخ، فرصت، فعالیت، تیکت و فروش هر کاربر.",
              "range", _G_SALES),
    ReportDef("CRM_FORECAST", "پیش‌بینی فروش", forecast_report, _NO, "فرصت‌های وزنی ماه‌های آینده + روند فروش جاری.", "none", _G_SALES,
              options=_MONTHS_OPT),
    ReportDef("CRM_RFM", "تحلیل رفتار خرید مشتریان", rfm_report, _NO, "تعداد و خرید هر گروه رفتار خرید (تازگی، تکرار و مبلغ خرید).", "none", _G_CUST),
    ReportDef("CRM_CHURN", "مشتریان در معرض ریزش", churn_report, _NO, "احتمال ریزش، سلامت و اقدام پیشنهادی.", "none", _G_CUST,
              options=_CHURN_OPT),
    ReportDef("CRM_CLV", "ارزش طول عمر مشتریان", clv_report, _NO, "ارزش تاکنون و پیش‌بینی‌شدهٔ هر مشتری.", "none", _G_CUST),
    ReportDef("CRM_INACTIVE", "مشتریان غیرفعال", inactive_customers, _NO, "مشتریانی که مدتی خرید نکرده‌اند.", "none", _G_CUST,
              options=_DAYS_OPT),
    ReportDef("CRM_TICKETS_SLA", "تیکت‌ها و پایبندی به تعهد زمانی", tickets_sla, _NO, "تیکت‌های بازه به تفکیک نوع، نقض تعهد زمانی و زمان‌ها.", "range", _G_SERV),
    ReportDef("CRM_COMPLAINTS", "شکایت‌های مشتریان", complaints, _NO, "شکایت‌ها به تفکیک مشتری و دسته.", "range", _G_SERV),
    ReportDef("CRM_SATISFACTION", "رضایت مشتری", satisfaction, _NO, "امتیاز و نظر مشتری پس از حل تیکت.", "range", _G_SERV),
    ReportDef("CRM_CAMPAIGNS", "عملکرد کمپین‌ها", campaign_report, _NO, "پاسخ، سرنخ، فروش و بازگشت سرمایهٔ هر کمپین.", "range", _G_MKT),
    ReportDef("CRM_ACTIVITIES", "فعالیت‌ها به تفکیک کاربر", activity_report, _NO, "تماس، جلسه، پیگیری و ... هر کاربر.", "range", _G_MKT),
    ReportDef("CRM_OVERDUE", "پیگیری‌های عقب‌افتاده", overdue_followups, _NO, "کارهای باز گذشته از موعد.", "as_of", _G_MKT),
]
CRM_REPORT_MENU = [
    ("CRM_SALES", _G_SALES, [(r.code, r.title) for r in CRM_REPORTS if r.group == _G_SALES]),
    ("CRM_CUST", _G_CUST, [(r.code, r.title) for r in CRM_REPORTS if r.group == _G_CUST]),
    ("CRM_SERV", _G_SERV, [(r.code, r.title) for r in CRM_REPORTS if r.group == _G_SERV]),
    ("CRM_MKT", _G_MKT, [(r.code, r.title) for r in CRM_REPORTS if r.group == _G_MKT]),
]
