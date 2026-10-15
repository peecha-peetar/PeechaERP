"""داشبورد کیفیت — شاخص‌ها، هشدارها و نمودارها از همان بازرسی‌ها، عدم‌انطباق‌ها و موجودی قرنطینه (بدون محاسبهٔ موازی)."""

from __future__ import annotations

import datetime
import decimal
from collections import defaultdict
from types import SimpleNamespace

from sqlalchemy import func, select

from peecha.db.base import new_session
from peecha.db.models.inventory import QcInspection, StockDocument, StockDocumentLine
from peecha.db.models.quality import CapaAction, Nonconformance
from peecha.services.purchase_dashboard import Kpi
from peecha.services.qms import common as c

_ZERO = decimal.Decimal(0)
_HUNDRED = decimal.Decimal(100)
_Q1 = decimal.Decimal("0.1")
CHART_TITLES = (
    ("by_period", "پذیرفته و مردود به تفکیک ماه", "QC_INSPECTION_LOG", {"status": "APPROVED"}),
    ("ncr_trend", "روند عدم‌انطباق", "QC_NCR", {}),
    ("by_severity", "عدم‌انطباق باز به تفکیک شدت", "QC_NCR", {"status": "OPEN"}),
    ("suppliers", "تامین‌کنندگان با بیشترین مردودی", "QC_SUPPLIER_CARD", {}),
)
ALERT_LABELS = {"CAPA_OVERDUE": "اقدام اصلاحی عقب‌افتاده", "CRITICAL_NCR": "عدم‌انطباق بحرانی باز", "OLD_HOLD": "رسید منتظر بازرسی",
                "OLD_QUARANTINE": "کالای مانده در قرنطینه", "AWAITING": "نتیجهٔ منتظر تأیید"}
ALERT_LEVEL = {"CAPA_OVERDUE": "RED", "CRITICAL_NCR": "RED", "OLD_HOLD": "YELLOW", "OLD_QUARANTINE": "ORANGE", "AWAITING": "YELLOW"}


def _pct(part, whole):
    return (decimal.Decimal(part) * _HUNDRED / decimal.Decimal(whole)).quantize(_Q1) if whole else None


def _day_range(date_from: datetime.date, date_to: datetime.date):
    return (datetime.datetime.combine(date_from, datetime.time.min),
            datetime.datetime.combine(date_to + datetime.timedelta(days=1), datetime.time.min))


def alerts(company_id: int, quarantine_days: int = 30) -> list[SimpleNamespace]:
    from peecha.services import quality_control as qc
    from peecha.services.qms import ncr

    st = c.settings(company_id)
    today = datetime.date.today()
    out = []
    for a in ncr.list_actions(company_id, open_only=True):
        if a.overdue_days > 0:
            out.append(SimpleNamespace(kind="CAPA_OVERDUE", ref=("NCR", a.ncr_id),
                                       text=f"پرونده {a.ncr_no}: «{a.description}» {a.overdue_days} روز از مهلت گذشته"))
    for n in ncr.list_ncrs(company_id):
        if n.severity_code == "CRITICAL" and n.status_code not in ("CLOSED", "CANCELLED"):
            out.append(SimpleNamespace(kind="CRITICAL_NCR", ref=("NCR", n.ncr_id), text=f"پرونده {n.ncr_no}: {n.title}"))
    for r in qc.list_pending(company_id):
        waited = (today - r.document_date).days if r.document_date else 0
        if waited > int(decimal.Decimal(st.target_handling_days)):
            out.append(SimpleNamespace(kind="OLD_HOLD", ref=("LINE", r.line_id),
                                       text=f"رسید {r.document_no} — {r.item_name}: {waited} روز منتظر بازرسی"))
    for r in qc.quarantine_stock(company_id):
        if r.age_days is not None and r.age_days > quarantine_days and r.warehouse_type == "QUARANTINE":
            out.append(SimpleNamespace(kind="OLD_QUARANTINE", ref=("WH", r.warehouse_id),
                                       text=f"{r.item_label} در «{r.warehouse_name}»: {r.age_days} روز بدون تعیین تکلیف"))
    with new_session() as session:
        waiting = session.scalar(select(func.count()).select_from(QcInspection).where(
            QcInspection.company_id == company_id, QcInspection.status_code == "RECORDED"))
    if waiting:
        out.append(SimpleNamespace(kind="AWAITING", ref=("QUEUE", None), text=f"{waiting} نتیجهٔ بازرسی منتظر تأیید نهایی"))
    return out


def dashboard(company_id: int, date_from: datetime.date, date_to: datetime.date):
    from peecha.services import quality_control as qc
    from peecha.services.fixed_assets.common import period_of
    from peecha.services.qms import scoring

    start, end = _day_range(date_from, date_to)
    with new_session() as session:
        rows = session.execute(select(QcInspection).where(
            QcInspection.company_id == company_id, QcInspection.status_code == "APPROVED",
            QcInspection.approved_at >= start, QcInspection.approved_at < end)).scalars().all()
        awaiting = session.scalar(select(func.count()).select_from(QcInspection).where(
            QcInspection.company_id == company_id, QcInspection.status_code == "RECORDED")) or 0
        receipt_delays = [
            (q.approved_at - posted).total_seconds() / 86400
            for q, posted in session.execute(
                select(QcInspection, StockDocument.posted_at)
                .join(StockDocumentLine, StockDocumentLine.line_id == QcInspection.stock_document_line_id)
                .join(StockDocument, StockDocument.stock_document_id == StockDocumentLine.stock_document_id)
                .where(QcInspection.company_id == company_id, QcInspection.status_code == "APPROVED",
                       QcInspection.stage_code.in_(("RECEIPT", "SALES_RETURN")),
                       QcInspection.approved_at >= start, QcInspection.approved_at < end)).all()
            if posted and q.approved_at]
        ncr_rows = session.execute(select(Nonconformance).where(
            Nonconformance.company_id == company_id, Nonconformance.status_code != "CANCELLED",
            Nonconformance.detected_at >= start, Nonconformance.detected_at < end)).scalars().all()
        open_ncr = session.execute(select(Nonconformance.severity_code, func.count()).where(
            Nonconformance.company_id == company_id, Nonconformance.status_code.not_in(("CLOSED", "CANCELLED")))
            .group_by(Nonconformance.severity_code)).all()
        overdue = session.scalar(select(func.count()).select_from(CapaAction).where(
            CapaAction.company_id == company_id, CapaAction.status_code.in_(("OPEN", "DONE")),
            CapaAction.due_date < datetime.date.today())) or 0
    accepted = sum((decimal.Decimal(q.accepted_quantity or 0) for q in rows), _ZERO)
    rejected = sum((decimal.Decimal(q.rejected_quantity or 0) for q in rows), _ZERO)
    rework = sum((decimal.Decimal(q.pending_quantity or 0) for q in rows if q.disposition_code == "REWORK"), _ZERO)
    concession = sum(1 for q in rows if q.disposition_code == "CONCESSION")
    pending_holds = len(qc.list_pending(company_id))
    quarantine = qc.quarantine_stock(company_id)
    q_value = sum((r.value for r in quarantine if r.warehouse_type == "QUARANTINE"), _ZERO)
    ncr_cost = sum((decimal.Decimal(n.cost_amount or 0) for n in ncr_rows), _ZERO)
    open_by_sev = dict(open_ncr)
    delay = decimal.Decimal(str(round(sum(receipt_delays) / len(receipt_delays), 1))) if receipt_delays else None
    kpis = [
        Kpi("WAITING", "منتظر بازرسی", pending_holds, "INT", "QC_INSPECTION_LOG",
            "ردیف‌های رسید، مرجوعی و تولید نگه‌داشته‌شده تا ثبت نتیجه", {"status": "RECORDED"}),
        Kpi("AWAITING", "منتظر تأیید نهایی", awaiting, "INT", "QC_INSPECTION_LOG", "نتیجهٔ ثبت‌شده و تأییدنشده",
            {"status": "RECORDED"}),
        Kpi("INSPECTIONS", "بازرسی تأییدشده", len(rows), "INT", "QC_INSPECTION_LOG", "تعداد بازرسی تأییدشده در بازه",
            {"status": "APPROVED"}),
        Kpi("ACCEPT_RATE", "نرخ قبولی٪", _pct(accepted, accepted + rejected), "PERCENT", "QC_ITEM_CARD",
            "پذیرفته ÷ (پذیرفته + مردود)"),
        Kpi("REJECT_RATE", "نرخ مردودی٪", _pct(rejected, accepted + rejected), "PERCENT", "QC_ITEM_CARD",
            "مردود ÷ (پذیرفته + مردود)"),
        Kpi("REWORK", "مقدار دوباره‌کاری", rework, "INT", "QC_PRODUCTION", "جمع مقدار ارجاع‌شده به دوباره‌کاری"),
        Kpi("CONCESSION", "مصرف مشروط", concession, "INT", "QC_INSPECTION_LOG", "بازرسی‌های با تصمیم مصرف مشروط",
            {"status": "APPROVED"}),
        Kpi("NCR_OPEN", "عدم‌انطباق باز", sum(open_by_sev.values()), "INT", "QC_NCR", "پرونده‌های باز، در بررسی و در اقدام",
            {"status": "ALL"}),
        Kpi("NCR_CRITICAL", "عدم‌انطباق بحرانی باز", open_by_sev.get("CRITICAL", 0), "INT", "QC_NCR", "شدت بحرانی و بسته‌نشده",
            {"severity": "CRITICAL"}),
        Kpi("CAPA_OVERDUE", "اقدام عقب‌افتاده", overdue, "INT", "QC_CAPA", "اقدام باز یا منتظر بررسی که مهلتش گذشته"),
        Kpi("QUARANTINE", "ارزش موجودی قرنطینه", q_value, "MONEY", "QC_QUARANTINE", "ارزش موجودی انبارهای قرنطینه"),
        Kpi("NCR_COST", "هزینهٔ عدم‌انطباق", ncr_cost, "MONEY", "QC_NCR", "جمع هزینهٔ برآوردی پرونده‌های بازه"),
        Kpi("DELAY", "میانگین زمان رسیدگی (روز)", delay, "DAYS", "QC_SUPPLIER_CARD", "از ثبت رسید تا تأیید بازرسی"),
    ]
    acc_by, rej_by, ncr_by = defaultdict(lambda: _ZERO), defaultdict(lambda: _ZERO), defaultdict(int)
    for q in rows:
        p = period_of(q.approved_at.date())[0]
        acc_by[p] += decimal.Decimal(q.accepted_quantity or 0)
        rej_by[p] += decimal.Decimal(q.rejected_quantity or 0)
    for n in ncr_rows:
        ncr_by[period_of(n.detected_at.date())[0]] += 1
    periods = sorted(set(acc_by) | set(rej_by))
    worst = sorted([s for s in scoring.supplier_scores(company_id, as_of=date_to) if s.reject_rate],
                   key=lambda s: -s.reject_rate)[:8]
    charts = {
        "by_period": {"kind": "bar", "labels": periods,
                      "series": {"پذیرفته": [acc_by[p] for p in periods], "مردود": [rej_by[p] for p in periods]}},
        "ncr_trend": {"kind": "bar", "labels": sorted(ncr_by), "series": {"عدم‌انطباق": [ncr_by[p] for p in sorted(ncr_by)]}},
        "by_severity": {"kind": "donut", "labels": [c.SEVERITY_LABELS[k] for k in c.SEVERITY_LABELS],
                        "series": {"تعداد": [open_by_sev.get(k, 0) for k in c.SEVERITY_LABELS]}},
        "suppliers": {"kind": "bar", "labels": [s.supplier_label for s in worst],
                      "series": {"نرخ مردودی٪": [s.reject_rate for s in worst]}},
    }
    return kpis, charts, alerts(company_id)
