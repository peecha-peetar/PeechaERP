"""تحلیل مشتری (فاز ۴، R283): RFM، امتیاز سلامت، ریسک ریزش، ارزش طول عمر (CLV) و اقدام پیشنهادی.

همهٔ ورودی‌ها از دادهٔ واقعی ERP با پرس‌وجوی تجمیعی خوانده می‌شوند (فاکتور ثبت‌شده، برگشت از فروش، بهای تمام‌شده
از compute_customer_profit، معوقات از تسویه، شکایت و تعامل از فعالیت‌ها). نتیجه در crm.customer_scores کش می‌شود تا
فهرست‌ها، سگمنت‌ها و داشبورد سریع بمانند؛ refresh_scores هر زمان کش را از نو می‌سازد.
"""

from __future__ import annotations

import datetime
import decimal
from dataclasses import dataclass

from sqlalchemy import case, func, select

from peecha.db.base import new_session
from peecha.db.models.accounting import DetailAccount
from peecha.db.models.commercial import CommercialDocument, CustomerActivity, CustomerProfile, ServiceTicket
from peecha.db.models.crm import CrmSettings, CustomerScore
from peecha.services import commercial_documents as documents_service
from peecha.services import commercial_settlements as settlements_service
from peecha.services.crm import common as c
from peecha.services.crm import insights

ZERO = decimal.Decimal(0)
RFM_SEGMENTS = {"CHAMPIONS": "قهرمانان", "LOYAL": "وفادار", "POTENTIAL": "وفادار بالقوه", "NEW": "مشتری تازه",
                "PROMISING": "امیدوارکننده", "NEED_ATTENTION": "نیازمند توجه", "AT_RISK": "در معرض ریزش",
                "HIBERNATING": "خواب‌رفته", "LOST": "از دست رفته", "NO_PURCHASE": "بدون خرید"}
DEFAULT_OPTIONS = {"clv_horizon_months": 24, "rfm_window_days": 365, "dormant_days": 90, "inactivity_days": 60}


def settings(company_id: int) -> dict:
    with new_session() as session:
        row = session.get(CrmSettings, company_id)
        return {**DEFAULT_OPTIONS, **(row.options if row else {})}


def save_settings(company_id: int, user_id: int | None, **options) -> dict:
    unknown = set(options) - set(DEFAULT_OPTIONS)
    if unknown:
        raise ValueError("تنظیم نامعتبر: " + "، ".join(sorted(unknown)))
    with new_session() as session:
        row = session.get(CrmSettings, company_id) or CrmSettings(company_id=company_id, options={})
        row.options = {**(row.options or {}), **options}
        row.updated_at = c.now()
        session.add(row)
        c.audit(session, company_id, user_id, "Settings", company_id, "UPDATE", options)
        session.commit()
    return settings(company_id)


def _quintile(values: list[float]) -> list[float]:
    """مرزهای پنج‌گانه (۲۰، ۴۰، ۶۰، ۸۰ درصد)."""
    if not values:
        return []
    ordered = sorted(values)
    return [ordered[min(len(ordered) - 1, int(len(ordered) * q / 5))] for q in (1, 2, 3, 4)]


def _score(value: float, bounds: list[float], reverse: bool = False) -> int:
    s = 1 + sum(1 for b in bounds if value > b) if not reverse else 5 - sum(1 for b in bounds if value > b)
    return max(1, min(5, s))


def rfm_segment(r: int | None, f: int | None, m: int | None) -> str:
    if r is None:
        return "NO_PURCHASE"
    if r >= 4 and f >= 4 and m >= 4:
        return "CHAMPIONS"
    if f >= 4 and r >= 3:
        return "LOYAL"
    if r >= 4 and f == 1:
        return "NEW"
    if r >= 4 and f in (2, 3):
        return "POTENTIAL"
    if r == 3 and f <= 2:
        return "PROMISING" if m >= 3 else "NEED_ATTENTION"
    if r <= 2 and f >= 3:
        return "AT_RISK"
    if r == 2:
        return "HIBERNATING"
    return "LOST" if r == 1 else "NEED_ATTENTION"


@dataclass
class _Agg:
    count_total: int = 0
    first: datetime.date | None = None
    last: datetime.date | None = None
    freq_365: int = 0
    mon_365: decimal.Decimal = ZERO
    sales_90: decimal.Decimal = ZERO
    freq_prev_90: int = 0
    amount_prev_90: decimal.Decimal = ZERO


def compute_scores(company_id: int, today: datetime.date | None = None) -> list[dict]:
    """امتیاز همهٔ مشتریان شرکت (پروفایل‌دار) بدون ذخیره؛ refresh_scores آن را ذخیره می‌کند."""
    today = today or datetime.date.today()
    opts = settings(company_id)
    d365, d90, d180 = (today - datetime.timedelta(days=n) for n in (opts["rfm_window_days"], 90, 180))
    with new_session() as session:
        customers = dict(session.execute(select(CustomerProfile.customer_detail_account_id, CustomerProfile.priority_code).where(
            CustomerProfile.company_id == company_id)).all())
        d, amt = CommercialDocument.document_date, CommercialDocument.total_amount
        inv_filter = (CommercialDocument.company_id == company_id, CommercialDocument.document_type_code == "SALES_INVOICE",
                      CommercialDocument.status_code == "POSTED")
        agg: dict[int, _Agg] = {}
        for cid, n, first, last, f365, m365, s90, fp90, ap90 in session.execute(select(
                CommercialDocument.counterparty_detail_account_id, func.count(), func.min(d), func.max(d),
                func.count(case((d >= d365, 1))), func.coalesce(func.sum(case((d >= d365, amt), else_=0)), 0),
                func.coalesce(func.sum(case((d >= d90, amt), else_=0)), 0),
                func.count(case(((d >= d180) & (d < d90), 1))),
                func.coalesce(func.sum(case(((d >= d180) & (d < d90), amt), else_=0)), 0),
        ).where(*inv_filter).group_by(CommercialDocument.counterparty_detail_account_id)):
            agg[cid] = _Agg(n, first, last, f365, decimal.Decimal(m365), decimal.Decimal(s90), fp90, decimal.Decimal(ap90))
        gaps: dict[int, list[datetime.date]] = {}
        for cid, dd in session.execute(select(CommercialDocument.counterparty_detail_account_id, d).where(*inv_filter)
                                       .distinct().order_by(CommercialDocument.counterparty_detail_account_id, d)):
            gaps.setdefault(cid, []).append(dd)
        # برگشت از فروش به مبلغ خالص (بدون مالیات)، هم‌پایهٔ net_revenue در compute_customer_profit
        net = CommercialDocument.subtotal_amount - CommercialDocument.discount_amount
        returns = dict(session.execute(select(CommercialDocument.counterparty_detail_account_id, func.coalesce(func.sum(net), 0)).where(
            CommercialDocument.company_id == company_id, CommercialDocument.document_type_code == "SALES_RETURN",
            CommercialDocument.status_code == "POSTED").group_by(CommercialDocument.counterparty_detail_account_id)).all())
        complaints: dict[int, int] = dict(session.execute(select(CustomerActivity.customer_detail_account_id, func.count()).where(
            CustomerActivity.company_id == company_id, CustomerActivity.activity_type_code == "COMPLAINT",
            CustomerActivity.status_code.in_(c.ACTIVITY_OPEN_STATUSES)).group_by(CustomerActivity.customer_detail_account_id)).all())
        for cid, n in session.execute(select(ServiceTicket.customer_detail_account_id, func.count()).join(
                DetailAccount, DetailAccount.detail_account_id == ServiceTicket.customer_detail_account_id).where(
                DetailAccount.company_id == company_id, ServiceTicket.status_code.not_in(("RESOLVED", "CLOSED", "CANCELLED")))
                .group_by(ServiceTicket.customer_detail_account_id)):
            complaints[cid] = complaints.get(cid, 0) + n
        activities = dict(session.execute(select(CustomerActivity.customer_detail_account_id, func.count()).where(
            CustomerActivity.company_id == company_id, CustomerActivity.created_at >= datetime.datetime.combine(d90, datetime.time.min))
            .group_by(CustomerActivity.customer_detail_account_id)).all())
    first_ever = min((a.first for a in agg.values() if a.first), default=today)
    profit = {r.counterparty_detail_account_id: r for r in documents_service.compute_customer_profit(company_id, first_ever, today)}
    overdue: dict[int, tuple[decimal.Decimal, int]] = {}
    for u in settlements_service.list_unsettled_invoices_bulk(company_id, due_on_or_before=today - datetime.timedelta(days=1)):
        amount, days = overdue.get(u.counterparty_detail_account_id, (ZERO, 0))
        overdue[u.counterparty_detail_account_id] = (amount + u.remaining_amount, max(days, (today - u.due_date).days if u.due_date else 0))
    buyers = {cid: a for cid, a in agg.items() if a.freq_365}
    r_bounds = _quintile([float((today - a.last).days) for a in buyers.values()])
    f_bounds = _quintile([float(a.freq_365) for a in buyers.values()])
    m_bounds = _quintile([float(a.mon_365) for a in buyers.values()])
    provider = insights.get_provider()
    horizon = decimal.Decimal(opts["clv_horizon_months"])
    out = []
    for cid, priority in customers.items():
        a = agg.get(cid, _Agg())
        recency = (today - a.last).days if a.last else None
        dates = gaps.get(cid, [])
        gap_list = [(y - x).days for x, y in zip(dates, dates[1:])]
        avg_gap = sum(gap_list) / len(gap_list) if gap_list else None
        r = f = m = None
        if cid in buyers:
            r, f, m = _score(float(recency), r_bounds, reverse=True), _score(float(a.freq_365), f_bounds), _score(float(a.mon_365), m_bounds)
        elif a.last:
            r, f, m = 1, 1, 1
        od_amount, od_days = overdue.get(cid, (ZERO, 0))
        sig = insights.CustomerSignals(
            recency_days=recency, avg_gap_days=avg_gap, frequency_365=a.freq_365, monetary_365=float(a.mon_365), r_score=r,
            f_score=f, m_score=m, freq_recent_90=sum(1 for x in dates if x >= d90), freq_prev_90=a.freq_prev_90,
            amount_recent_90=float(a.sales_90), amount_prev_90=float(a.amount_prev_90), overdue_amount=float(od_amount),
            max_days_overdue=od_days, open_complaints=complaints.get(cid, 0), activities_90d=activities.get(cid, 0),
            priority_code=priority, has_purchases=bool(a.count_total))
        health, churn = provider.health(sig), provider.churn(sig)
        actions = provider.next_best_actions(sig)
        p = profit.get(cid)
        clv_hist = ((p.gross_profit if p else ZERO) - decimal.Decimal(returns.get(cid, 0))).quantize(decimal.Decimal("0.01"))
        months = max(1, ((today - a.first).days // 30) + 1) if a.first else 1
        monthly = clv_hist / months
        clv_pred = max(ZERO, monthly * horizon * (1 - decimal.Decimal(churn.score) / 100)).quantize(decimal.Decimal("0.01"))
        out.append({
            "customer_detail_account_id": cid, "recency_days": recency, "frequency_365": a.freq_365, "monetary_365": a.mon_365,
            "sales_90d": a.sales_90, "invoice_count_total": a.count_total, "first_purchase": a.first, "last_purchase": a.last,
            "avg_gap_days": decimal.Decimal(str(round(avg_gap, 1))) if avg_gap is not None else None, "r_score": r, "f_score": f,
            "m_score": m, "rfm_segment": rfm_segment(r, f, m), "health_score": health.score, "health_band": health.band,
            "churn_risk": churn.score, "churn_band": churn.band, "clv_historical": clv_hist, "clv_predicted": clv_pred,
            "overdue_amount": od_amount, "open_complaints": complaints.get(cid, 0), "activities_90d": activities.get(cid, 0),
            "factors": {"health": health.factors, "churn": churn.factors}, "next_best_action": actions[0]["suggestion"] if actions else None,
            "actions": actions})
    return out


def refresh_scores(company_id: int, today: datetime.date | None = None) -> int:
    rows = compute_scores(company_id, today)
    cols = {k for k in CustomerScore.__table__.columns.keys()}
    with new_session() as session:
        session.query(CustomerScore).filter(CustomerScore.company_id == company_id).delete()
        for r in rows:
            session.add(CustomerScore(company_id=company_id, computed_at=c.now(), **{k: v for k, v in r.items() if k in cols}))
        session.commit()
    return len(rows)


def ensure_fresh(company_id: int, max_age_hours: int = 12) -> None:
    """اگر کش قدیمی یا خالی است، دوباره ساخته می‌شود (فراخوانی سبک در بازکردن صفحه‌ها)."""
    with new_session() as session:
        newest = session.scalar(select(func.min(CustomerScore.computed_at)).where(CustomerScore.company_id == company_id))
        have = session.scalar(select(func.count()).where(CustomerScore.company_id == company_id))
        customers = session.scalar(select(func.count()).where(CustomerProfile.company_id == company_id))
    if not have or have != customers or newest is None or c.now() - newest > datetime.timedelta(hours=max_age_hours):
        refresh_scores(company_id)


def get_score(company_id: int, customer_id: int) -> CustomerScore | None:
    with new_session() as session:
        row = session.get(CustomerScore, customer_id)
        if row is None or row.company_id != company_id:
            return None
        session.expunge(row)
        return row


def list_scores(company_id: int, *, rfm_segment_code: str | None = None, health_band: str | None = None,
                churn_band: str | None = None, customer_ids: list[int] | None = None, order: str = "churn",
                limit: int = 1000, offset: int = 0) -> list[dict]:
    with new_session() as session:
        q = select(CustomerScore, DetailAccount.code, DetailAccount.name).join(
            DetailAccount, DetailAccount.detail_account_id == CustomerScore.customer_detail_account_id).where(
            CustomerScore.company_id == company_id)
        if rfm_segment_code:
            q = q.where(CustomerScore.rfm_segment == rfm_segment_code)
        if health_band:
            q = q.where(CustomerScore.health_band == health_band)
        if churn_band:
            q = q.where(CustomerScore.churn_band == churn_band)
        if customer_ids is not None:
            q = q.where(CustomerScore.customer_detail_account_id.in_(customer_ids or [-1]))
        sort = {"churn": CustomerScore.churn_risk.desc(), "health": CustomerScore.health_score.asc(),
                "clv": CustomerScore.clv_historical.desc(), "monetary": CustomerScore.monetary_365.desc()}[order]
        rows = session.execute(q.order_by(sort, DetailAccount.name).limit(limit).offset(offset)).all()
        return [{**{k: getattr(s, k) for k in CustomerScore.__table__.columns.keys()}, "code": code, "name": name,
                 "rfm_label": RFM_SEGMENTS.get(s.rfm_segment or "", ""), "health_label": insights.HEALTH_BANDS[s.health_band][0],
                 "health_icon": insights.HEALTH_BANDS[s.health_band][1], "churn_label": insights.CHURN_BANDS[s.churn_band]}
                for s, code, name in rows]


def rfm_matrix(company_id: int) -> list[dict]:
    with new_session() as session:
        rows = session.execute(select(CustomerScore.rfm_segment, func.count(), func.coalesce(func.sum(CustomerScore.monetary_365), 0))
                               .where(CustomerScore.company_id == company_id).group_by(CustomerScore.rfm_segment)).all()
    by = {seg: (n, decimal.Decimal(m)) for seg, n, m in rows}
    return [{"code": code, "label": label, "count": by.get(code, (0, ZERO))[0], "monetary": by.get(code, (0, ZERO))[1]}
            for code, label in RFM_SEGMENTS.items()]


def band_counts(company_id: int) -> dict:
    with new_session() as session:
        health = dict(session.execute(select(CustomerScore.health_band, func.count()).where(
            CustomerScore.company_id == company_id).group_by(CustomerScore.health_band)).all())
        churn = dict(session.execute(select(CustomerScore.churn_band, func.count()).where(
            CustomerScore.company_id == company_id).group_by(CustomerScore.churn_band)).all())
    return {"health": health, "churn": churn}
