"""R311 — گزارش‌های کیفیت روی همان موتور گزارش (فیلتر، گروه‌بندی، چاپ PDF و خروجی Excel استاندارد)."""

from __future__ import annotations

import datetime
import decimal
from collections import defaultdict

from sqlalchemy import func, select

from peecha.db.base import new_session
from peecha.db.models.inventory import Item, QcInspection
from peecha.db.models.quality import InspectionResult
from peecha.services.purchase_reports import DATE, INT, MONEY, PERCENT, QTY, TEXT, ReportDef, ReportResult
from peecha.services.qms import common as c

_ZERO = decimal.Decimal(0)
_G = "کیفیت"
_ALL_OPT = ("ALL", "همه")


def _pct(part, whole):
    return (decimal.Decimal(part) * 100 / decimal.Decimal(whole)).quantize(decimal.Decimal("0.1")) if whole else None


def _ref(doc_id, doc_type):
    return (doc_id, doc_type) if doc_id and doc_type else None


def _category_ok(item_id, category_id, cache: dict) -> bool:
    if category_id is None:
        return True
    if item_id not in cache:
        with new_session() as s:
            cache[item_id] = s.scalar(select(Item.category_id).where(Item.item_id == item_id))
    return cache[item_id] == category_id


def _inspections(company_id: int, f):
    from peecha.services.qms import queries

    stage = (f.options or {}).get("stage")
    status = (f.options or {}).get("status")
    rows = queries.list_inspections(company_id, status=None if status in (None, "ALL") else status,
                                    stage=None if stage in (None, "ALL") else stage, date_from=f.date_from, date_to=f.date_to,
                                    limit=100000)
    cache: dict = {}
    out = []
    for r in rows:
        if f.item_id is not None and r.item_id != f.item_id:
            continue
        if f.supplier_id is not None and r.party_id != f.supplier_id:
            continue
        if f.warehouse_id is not None and r.warehouse_id != f.warehouse_id:
            continue
        if f.work_center_id is not None and r.work_center_id != f.work_center_id:
            continue
        if f.inspector_id is not None and r.inspected_by_user_id != f.inspector_id:
            continue
        if not _category_ok(r.item_id, f.category_id, cache):
            continue
        out.append(r)
    return out


def inspection_log(company_id: int, f) -> ReportResult:
    res = ReportResult([
        ("تاریخ ثبت", DATE), ("مرحله", TEXT), ("وضعیت", TEXT), ("نتیجه", TEXT), ("تصمیم", TEXT), ("کالا", TEXT),
        ("طرف‌حساب", TEXT), ("سند منبع", TEXT), ("دستور تولید", TEXT), ("عملیات", TEXT), ("انبار", TEXT), ("طرح کیفیت", TEXT),
        ("مقدار تحت کنترل", QTY), ("پذیرفته", QTY), ("مردود", QTY), ("در انتظار", QTY), ("بازرس", TEXT), ("تأییدکننده", TEXT),
        ("توضیح", TEXT),
    ], note="هر بازرسی یک ردیف؛ نتیجهٔ تأییدشده قابل تغییر نیست و اصلاح با بازرسی مجدد انجام می‌شود.")
    for r in _inspections(company_id, f):
        res.add([r.inspected_at.date() if r.inspected_at else None, r.stage_label, r.status_label, r.result_label,
                 r.disposition_label, r.item_label, r.party_label, str(r.document_no) if r.document_no else "", r.order_code,
                 r.operation_name, r.warehouse_name, r.plan_label, r.lot, r.accepted, r.rejected, r.pending, r.inspector,
                 r.approver, r.notes], _ref(r.stock_document_id, r.document_type_code))
    return res


def parameter_results(company_id: int, f) -> ReportResult:
    rows = {r.inspection_id: r for r in _inspections(company_id, f)}
    res = ReportResult([("بازرسی", INT), ("تاریخ", DATE), ("کالا", TEXT), ("مرحله", TEXT), ("نمونه", INT), ("پارامتر", TEXT),
                        ("نوع", TEXT), ("حداقل", QTY), ("حداکثر", QTY), ("هدف", QTY), ("مقدار", TEXT), ("واحد", TEXT),
                        ("منطبق", TEXT), ("اجباری", TEXT)], no_total={0, 4, 7, 8, 9})
    with new_session() as session:
        for x in session.scalars(select(InspectionResult).where(InspectionResult.company_id == company_id,
                                                                InspectionResult.qc_inspection_id.in_(list(rows) or [-1]))
                                 .order_by(InspectionResult.qc_inspection_id, InspectionResult.sample_no, InspectionResult.result_id)):
            r = rows[x.qc_inspection_id]
            value = (x.value_numeric.normalize() if x.value_numeric is not None else
                     (("قبول" if x.value_bool else "رد") if x.value_bool is not None else (x.value_text or "")))
            res.add([x.qc_inspection_id, r.inspected_at.date() if r.inspected_at else None, r.item_label, r.stage_label,
                     x.sample_no, x.parameter_name, c.DATA_TYPE_LABELS[x.data_type], x.min_value, x.max_value, x.target_value,
                     str(value), x.uom_label or "", "" if x.is_conforming is None else ("بله" if x.is_conforming else "خیر"),
                     "بله" if x.is_mandatory else "خیر"])
    return res


def quarantine(company_id: int, f) -> ReportResult:
    from peecha.services import quality_control as qc

    res = ReportResult([("انبار", TEXT), ("نوع", TEXT), ("کالا", TEXT), ("مقدار", QTY), ("آزاد برای تصمیم", QTY), ("ارزش", MONEY),
                        ("آخرین ورود", DATE), ("روز ماندگاری", INT)], no_total={7},
                       note="کالای انبارهای قرنطینه و ضایعات؛ با کلید «قفل انبار قرنطینه» فقط از صفحهٔ کنترل کیفیت خارج می‌شود.")
    cache: dict = {}
    for r in qc.quarantine_stock(company_id, f.warehouse_id):
        if f.item_id is not None and r.item_id != f.item_id:
            continue
        if not _category_ok(r.item_id, f.category_id, cache):
            continue
        res.add([r.warehouse_name, "قرنطینه" if r.warehouse_type == "QUARANTINE" else "ضایعات", r.item_label, r.quantity, r.free,
                 r.value, r.last_in, r.age_days])
    return res


def ncr_report(company_id: int, f) -> ReportResult:
    from peecha.db.models.quality import Nonconformance
    from peecha.services.qms import ncr

    status = (f.options or {}).get("status")
    severity = (f.options or {}).get("severity")
    res = ReportResult([("شماره", INT), ("تاریخ", DATE), ("عنوان", TEXT), ("منبع", TEXT), ("شدت", TEXT), ("وضعیت", TEXT),
                        ("کالا", TEXT), ("طرف‌حساب", TEXT), ("مقدار", QTY), ("هزینهٔ برآوردی", MONEY), ("علت", TEXT),
                        ("مسئول", TEXT), ("مهلت", DATE), ("روز باز", INT), ("اقدام باز", INT)], no_total={0, 13})
    with new_session() as session:
        meta = {n.ncr_id: n for n in session.scalars(select(Nonconformance).where(Nonconformance.company_id == company_id))}
    today = datetime.date.today()
    for r in ncr.list_ncrs(company_id):
        n = meta[r.ncr_id]
        detected = r.detected_at.date() if r.detected_at else None
        if detected and not (f.date_from <= detected <= f.date_to):
            continue
        if status not in (None, "ALL") and r.status_code != status:
            continue
        if severity not in (None, "ALL") and r.severity_code != severity:
            continue
        if f.item_id is not None and n.item_id != f.item_id:
            continue
        if f.supplier_id is not None and f.supplier_id not in (n.supplier_detail_account_id, n.customer_detail_account_id):
            continue
        end = n.closed_at.date() if n.closed_at else today
        res.add([r.ncr_no, detected, r.title, r.source_label, r.severity_label, r.status_label, r.item_label, r.party_label,
                 r.quantity, r.cost_amount, r.cause_label, r.responsible, r.due_date, (end - detected).days if detected else None,
                 r.open_actions])
    return res


def capa_report(company_id: int, f) -> ReportResult:
    from peecha.services.qms import ncr

    status = (f.options or {}).get("status")
    res = ReportResult([("پرونده", INT), ("عنوان پرونده", TEXT), ("نوع اقدام", TEXT), ("شرح", TEXT), ("مسئول", TEXT), ("مهلت", DATE),
                        ("وضعیت", TEXT), ("روز تأخیر", INT), ("شواهد", TEXT)], no_total={0})
    for a in ncr.list_actions(company_id, open_only=status in (None, "OPEN")):
        if status not in (None, "ALL", "OPEN") and a.status_code != status:
            continue
        res.add([a.ncr_no, a.ncr_title, a.type_label, a.description, a.owner, a.due_date, a.status_label, a.overdue_days or None,
                 a.evidence or ""])
    return res


def supplier_card(company_id: int, f) -> ReportResult:
    from peecha.services.qms import scoring

    st = c.settings(company_id)
    res = ReportResult([("تامین‌کننده", TEXT), ("تعداد بازرسی", INT), ("مقدار بازرسی‌شده", QTY), ("نرخ مردودی", PERCENT),
                        ("مقدار خرید", QTY), ("نرخ برگشت", PERCENT), ("عدم‌انطباق", INT), ("میانگین تأخیر رسیدگی (روز)", QTY),
                        ("روند مردودی (واحد درصد)", QTY), ("امتیاز (از ۱۰۰)", QTY), ("توضیح", TEXT)], no_total={3, 5, 7, 8, 9},
                       note=scoring.formula_text(st))
    for s in scoring.supplier_scores(company_id, as_of=f.date_to, supplier_id=f.supplier_id):
        res.add([s.supplier_label, s.inspections, s.inspected_qty, s.reject_rate, s.purchased_qty, s.return_rate, s.ncr_count,
                 s.delay_days, s.trend, s.score, s.note])
    return res


def item_card(company_id: int, f) -> ReportResult:
    from peecha.db.models.quality import Nonconformance

    agg: dict[int, dict] = defaultdict(lambda: {"n": 0, "qty": _ZERO, "acc": _ZERO, "rej": _ZERO, "rework": _ZERO, "label": ""})
    for r in _inspections(company_id, f):
        if r.status_code != "APPROVED" or r.item_id is None:
            continue
        a = agg[r.item_id]
        a["n"] += 1
        a["label"] = r.item_label
        a["acc"] += r.accepted or _ZERO
        a["rej"] += r.rejected
        a["qty"] += (r.accepted or _ZERO) + r.rejected
        if r.disposition_code == "REWORK":
            a["rework"] += r.pending
    with new_session() as session:
        ncrs = dict(session.execute(select(Nonconformance.item_id, func.count()).where(
            Nonconformance.company_id == company_id, Nonconformance.status_code != "CANCELLED",
            Nonconformance.detected_at >= datetime.datetime.combine(f.date_from, datetime.time.min),
            Nonconformance.detected_at < datetime.datetime.combine(f.date_to + datetime.timedelta(days=1), datetime.time.min))
            .group_by(Nonconformance.item_id)).all())
    res = ReportResult([("کالا", TEXT), ("تعداد بازرسی", INT), ("مقدار تصمیم‌گرفته", QTY), ("پذیرفته", QTY), ("مردود", QTY),
                        ("نرخ قبولی", PERCENT), ("نرخ مردودی", PERCENT), ("دوباره‌کاری", QTY), ("عدم‌انطباق", INT)])
    for item_id, a in sorted(agg.items(), key=lambda kv: kv[1]["label"]):
        res.add([a["label"], a["n"], a["qty"], a["acc"], a["rej"], _pct(a["acc"], a["qty"]), _pct(a["rej"], a["qty"]), a["rework"],
                 ncrs.get(item_id, 0)])
    return res


def production_quality(company_id: int, f) -> ReportResult:
    res = ReportResult([("دستور تولید", TEXT), ("کالا", TEXT), ("مرحله", TEXT), ("عملیات", TEXT), ("بازرسی", INT),
                        ("پذیرفته", QTY), ("مردود", QTY), ("دوباره‌کاری/در انتظار", QTY), ("نرخ قبولی", PERCENT)], no_total={8})
    agg: dict[tuple, dict] = defaultdict(lambda: {"n": 0, "acc": _ZERO, "rej": _ZERO, "pend": _ZERO, "item": "", "op": ""})
    for r in _inspections(company_id, f):
        if r.stage_code not in ("IN_PROCESS", "FINAL") or r.status_code != "APPROVED":
            continue
        a = agg[(r.order_code, r.stage_label, r.operation_name)]
        a["n"] += 1
        a["item"], a["op"] = r.item_label, r.operation_name
        a["acc"] += r.accepted or _ZERO
        a["rej"] += r.rejected
        a["pend"] += r.pending
    for (order_code, stage, op), a in sorted(agg.items()):
        res.add([order_code, a["item"], stage, op, a["n"], a["acc"], a["rej"], a["pend"], _pct(a["acc"], a["acc"] + a["rej"])])
    return res


_STAGE_OPTS = (("stage", "مرحله", (_ALL_OPT,) + tuple(c.STAGE_LABELS.items())),)
_STATUS_OPTS = (("status", "وضعیت", (_ALL_OPT,) + tuple(c.STATUS_LABELS.items())),)
_INSPECTION_FILTERS = ("supplier", "item", "category", "warehouse", "work_center", "inspector")

QC_REPORTS: list[ReportDef] = [
    ReportDef("QC_INSPECTION_LOG", "دفتر بازرسی‌های کیفیت", inspection_log, _INSPECTION_FILTERS,
              "همهٔ بازرسی‌ها (رسید، مرجوعی، حین تولید، محصول نهایی) با مقادیر، تصمیم، بازرس و تأییدکننده.", "range", _G,
              options=_STAGE_OPTS + _STATUS_OPTS),
    ReportDef("QC_PARAMETER_RESULTS", "نتایج پارامترهای کیفیت", parameter_results, _INSPECTION_FILTERS,
              "مقدار اندازه‌گیری‌شدهٔ هر پارامتر در برابر حدود ثبت‌شده در همان بازرسی.", "range", _G, options=_STAGE_OPTS),
    ReportDef("QC_QUARANTINE", "موجودی قرنطینه و مردود", quarantine, ("item", "category", "warehouse"),
              "کالای انبارهای قرنطینه و ضایعات با ارزش و مدت ماندگاری.", "none", _G),
    ReportDef("QC_NCR", "عدم‌انطباق‌ها", ncr_report, ("supplier", "item"),
              "پرونده‌های عدم‌انطباق با شدت، علت، مسئول، هزینه و وضعیت رسیدگی.", "range", _G,
              options=(("status", "وضعیت", (_ALL_OPT,) + tuple(c.NCR_STATUS_LABELS.items())),
                       ("severity", "شدت", (_ALL_OPT,) + tuple(c.SEVERITY_LABELS.items())))),
    ReportDef("QC_CAPA", "اقدام‌های اصلاحی و پیشگیرانه", capa_report, (),
              "اقدام‌های باز و انجام‌شده با مهلت و تأخیر.", "none", _G,
              options=(("status", "وضعیت", (("OPEN", "باز و منتظر بررسی"), _ALL_OPT) + tuple(c.CAPA_STATUS_LABELS.items())),)),
    ReportDef("QC_SUPPLIER_CARD", "کارت کیفیت تامین‌کننده", supplier_card, ("supplier",),
              "امتیاز تامین‌کننده از بازرسی، برگشت خرید، عدم‌انطباق، تأخیر و روند — با تعداد نمونه و بازهٔ محاسبه.", "as_of", _G),
    ReportDef("QC_ITEM_CARD", "کارت کیفیت کالا", item_card, ("item", "category", "supplier", "warehouse"),
              "نرخ قبولی و مردودی، دوباره‌کاری و عدم‌انطباق هر کالا.", "range", _G, options=_STAGE_OPTS),
    ReportDef("QC_PRODUCTION", "کیفیت تولید", production_quality, ("item", "work_center", "inspector"),
              "بازرسی حین تولید و محصول نهایی به تفکیک دستور و عملیات.", "range", _G),
]
