"""R312 — گزارش‌های نگهداری و تعمیرات روی همان موتور گزارش (فیلتر، گروه‌بندی، چاپ PDF و خروجی Excel).

فیلترها: بازهٔ تاریخ، محل (کارخانه/ناحیه/خط با زیرشاخه‌ها)، تجهیز، مرکز هزینه، مسئول و نوع کار.
"""

from __future__ import annotations

import datetime
import decimal
from collections import defaultdict

from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.fixed_assets import Asset
from peecha.db.models.maintenance import FailureCode, PmPlan, WorkOrder, WorkOrderPart, WorkOrderPartMove
from peecha.services.purchase_reports import DATE, INT, MONEY, PERCENT, QTY, TEXT, ReportDef, ReportResult
from peecha.services.maintenance import common as c

_G = "نگهداری و تعمیرات"
_ALL_OPT = ("ALL", "همه")
_SCOPE = ("fa_location", "equipment", "cost_center")
_WORK_TYPE_OPT = ("work_type", "نوع کار", (_ALL_OPT,) + tuple(c.WORK_TYPE_LABELS.items()))


def _opt(f, key):
    v = (f.options or {}).get(key)
    return None if v in (None, "ALL") else v


def _scope(session, company_id: int, f) -> set[int] | None:
    """شناسهٔ تجهیزات داخل فیلتر محل/تجهیز/مرکز هزینه؛ None یعنی بدون محدودیت."""
    from peecha.services.maintenance import equipment

    if not (getattr(f, "fa_location_id", None) or getattr(f, "asset_id", None) or getattr(f, "cost_center_id", None)):
        return None
    q = select(Asset.asset_id).where(Asset.company_id == company_id)
    if getattr(f, "fa_location_id", None):
        q = q.where(Asset.location_id.in_(equipment._subtree(session, company_id, f.fa_location_id)))
    if getattr(f, "asset_id", None):
        q = q.where(Asset.asset_id == f.asset_id)
    if getattr(f, "cost_center_id", None):
        q = q.where(Asset.cost_center_detail_account_id == f.cost_center_id)
    return set(session.scalars(q))


def _in_range(value, f) -> bool:
    if value is None:
        return False
    d = c.aware(value).date() if isinstance(value, datetime.datetime) else value
    return f.date_from <= d <= f.date_to


def _hours(v) -> decimal.Decimal | None:
    return v if v is None else c.dec(v).quantize(decimal.Decimal("0.01"))


def work_order_log(company_id: int, f) -> ReportResult:
    from peecha.services.maintenance import costs, work_orders as wos

    res = ReportResult([
        ("شماره", INT), ("تاریخ ایجاد", DATE), ("تجهیز", TEXT), ("خط", TEXT), ("نوع کار", TEXT), ("اولویت", TEXT), ("عنوان", TEXT),
        ("وضعیت", TEXT), ("مسئول", TEXT), ("شروع برنامه", DATE), ("پایان برنامه", DATE), ("شروع واقعی", DATE),
        ("پایان واقعی", DATE), ("ساعت کار", QTY), ("قطعه", MONEY), ("نیروی کار", MONEY), ("خدمات و سایر", MONEY),
        ("جمع هزینه", MONEY), ("بازگشایی", INT),
    ], note="هزینهٔ قطعه = خالص سند انبار (صدور − برگشت)؛ نیروی کار اطلاعاتی است و جدا در حقوق ثبت می‌شود.")
    rows = wos.board(company_id, include_closed=True, work_type_code=_opt(f, "work_type"),
                     responsible_user_id=getattr(f, "responsible_id", None), limit=100000)
    status = _opt(f, "status")
    with new_session() as session:
        scope = _scope(session, company_id, f)
        rows = [r for r in rows if _in_range(r.created_at, f) and (scope is None or r.asset_id in scope)
                and (status is None or r.status_code == status)]
        cost = costs.summary_in_session(session, [r.work_order_id for r in rows])
    for r in sorted(rows, key=lambda x: x.wo_no):
        s = cost[r.work_order_id]
        res.add([r.wo_no, c.aware(r.created_at).date(), r.asset_label, r.production_line or "", r.work_type_label, r.priority_label,
                 r.title, r.status_label, r.responsible_name, _d(r.planned_start), _d(r.planned_end), _d(r.actual_start),
                 _d(r.actual_end), s.hours, s.parts, s.labor, s.services + s.other, s.total, r.reopened_count])
    return res


def _d(v):
    return c.aware(v).date() if isinstance(v, datetime.datetime) else v


def request_log(company_id: int, f) -> ReportResult:
    from peecha.services.maintenance import requests as reqs

    res = ReportResult([("شماره", INT), ("تاریخ گزارش", DATE), ("تجهیز", TEXT), ("شرح", TEXT), ("شدت", TEXT), ("اولویت", TEXT),
                        ("ماشین متوقف", TEXT), ("وضعیت", TEXT), ("منبع", TEXT), ("گزارش‌دهنده", TEXT), ("ارجاع به", TEXT),
                        ("علت احتمالی", TEXT), ("نظر بررسی", TEXT)])
    status = _opt(f, "status")
    rows = reqs.queue(company_id, statuses=(status,) if status else tuple(c.REQUEST_STATUS_LABELS), limit=100000)
    with new_session() as session:
        scope = _scope(session, company_id, f)
    for r in sorted(rows, key=lambda x: x.request_no):
        if not _in_range(r.reported_at, f) or (scope is not None and r.asset_id not in scope):
            continue
        res.add([r.request_no, _d(r.reported_at), r.asset_label, r.title, r.severity_label, r.priority_label,
                 "بله" if r.machine_stopped else "خیر", r.status_label, r.source_label, r.reported_by, r.assigned_to,
                 r.probable_cause or "", r.decision_note or ""])
    return res


def downtime_log(company_id: int, f) -> ReportResult:
    from peecha.services.maintenance import availability

    res = ReportResult([("تجهیز", TEXT), ("نوع توقف", TEXT), ("شروع توقف", TEXT), ("ثبت گزارش", TEXT), ("آماده‌به‌کاری", TEXT),
                        ("مدت (ساعت)", QTY), ("وضعیت", TEXT), ("دستور کار", TEXT), ("توضیح", TEXT)],
                       note="مدت = از شروع توقف تا ثبت آماده‌به‌کاری (پس از آزمون)؛ توقف باز تا اکنون حساب شده است.")
    from peecha.numerals import format_jalali_datetime

    rows = availability.list_downtimes(company_id, date_from=f.date_from, date_to=f.date_to)
    with new_session() as session:
        scope = _scope(session, company_id, f)
        wo_no = dict(session.execute(select(WorkOrder.work_order_id, WorkOrder.wo_no).where(
            WorkOrder.work_order_id.in_([r.work_order_id for r in rows if r.work_order_id] or [-1]))).all())
    for r in rows:
        if scope is not None and r.asset_id not in scope:
            continue
        res.add([r.asset_label, r.type_label, format_jalali_datetime(r.down_from), format_jalali_datetime(r.reported_at),
                 format_jalali_datetime(r.available_at) if r.available_at else "", r.hours, "باز" if r.is_open else "بسته",
                 str(wo_no.get(r.work_order_id, "")), r.note or ""])
    return res


def pm_compliance(company_id: int, f) -> ReportResult:
    res = ReportResult([("برنامه", TEXT), ("تجهیز", TEXT), ("نوع کار", TEXT), ("سررسید", DATE), ("دستور کار", INT),
                        ("انجام‌شده در", DATE), ("تأخیر (روز)", INT), ("وضعیت", TEXT), ("به‌موقع", TEXT)],
                       note="به‌موقع = پایان واقعی کار تا روز سررسید (پس از تعویق تأییدشده، سررسید جدید ملاک است).")
    today = datetime.date.today()
    with new_session() as session:
        scope = _scope(session, company_id, f)
        q = select(WorkOrder, PmPlan, Asset).join(PmPlan, PmPlan.plan_id == WorkOrder.pm_plan_id).join(
            Asset, Asset.asset_id == WorkOrder.asset_id).where(WorkOrder.company_id == company_id,
                                                               WorkOrder.pm_due_date.between(f.date_from, f.date_to))
        for wo, plan, asset in session.execute(q.order_by(WorkOrder.pm_due_date)).all():
            if scope is not None and asset.asset_id not in scope:
                continue
            if _opt(f, "work_type") and wo.work_type_code != _opt(f, "work_type"):
                continue
            done = _d(wo.actual_end) if wo.status_code in ("COMPLETED", "VERIFIED", "CLOSED") else None
            ref = done or (today if wo.status_code in c.OPEN_WO else None)
            delay = max(0, (ref - wo.pm_due_date).days) if ref else None
            on_time = "لغوشده" if wo.status_code == "CANCELLED" else ("بله" if done and done <= wo.pm_due_date else
                                                                     ("هنوز سررسید نشده" if wo.pm_due_date > today and not done else "خیر"))
            res.add([f"{plan.code} — {plan.title}", c.asset_label(asset), c.WORK_TYPE_LABELS[wo.work_type_code], wo.pm_due_date,
                     wo.wo_no, done, delay, c.WO_STATUS_LABELS[wo.status_code], on_time])
    return res


def reliability(company_id: int, f) -> ReportResult:
    from peecha.services.maintenance import equipment, reliability as rel

    res = ReportResult([("تجهیز", TEXT), ("خط", TEXT), ("تعداد خرابی", INT), ("میانگین زمان تعمیر (ساعت)", QTY),
                        ("میانگین زمان بین خرابی‌ها (ساعت)", QTY), ("نرخ خرابی در ۱۰۰۰ ساعت", QTY), ("ساعت توقف", QTY),
                        ("دسترس‌پذیری٪", PERCENT), ("هزینهٔ نگهداری", MONEY)], no_total={3, 4, 5, 7},
                       note="خانهٔ خالی = «داده ناکافی» (مخرج صفر). " + rel.DEFINITIONS["MTTR"][1] + " " + rel.DEFINITIONS["MTBF"][1])
    with new_session() as session:
        scope = _scope(session, company_id, f)
    for e in equipment.list_equipment(company_id):
        if scope is not None and e.asset_id not in scope:
            continue
        k = rel.compute(company_id, rel.Filters(date_from=f.date_from, date_to=f.date_to, asset_id=e.asset_id,
                                                work_type_code=_opt(f, "work_type"),
                                                responsible_user_id=getattr(f, "responsible_id", None)))
        b = k.by_code
        res.add([e.label, e.line, k.breakdowns, b["MTTR"].value, b["MTBF"].value, b["FAILURE_RATE"].value, b["DOWNTIME"].value,
                 b["AVAILABILITY"].value, b["COST"].value])
    return res


def cost_by_equipment(company_id: int, f) -> ReportResult:
    from peecha.services.maintenance import costs

    res = ReportResult([("تجهیز", TEXT), ("مرکز هزینه", TEXT), ("دستور کار", INT), ("قطعه", MONEY), ("نیروی کار", MONEY),
                        ("خدمات", MONEY), ("سایر", MONEY), ("جمع", MONEY), ("سهم از کل٪", PERCENT)], no_total={8},
                       note="دستورهای کار ایجادشده در بازه (بدون لغوشده). قطعه از سند انبار، خدمات از فاکتور خرید یا "
                            "ثبت دارایی؛ نیروی کار اطلاعاتی است.")
    from peecha.db.models.accounting import DetailAccount

    with new_session() as session:
        scope = _scope(session, company_id, f)
        q = select(WorkOrder).where(WorkOrder.company_id == company_id, WorkOrder.status_code != "CANCELLED")
        if _opt(f, "work_type"):
            q = q.where(WorkOrder.work_type_code == _opt(f, "work_type"))
        if getattr(f, "responsible_id", None):
            q = q.where(WorkOrder.responsible_user_id == f.responsible_id)
        wos_ = [w for w in session.scalars(q) if _in_range(w.created_at, f) and (scope is None or w.asset_id in scope)]
        s = costs.summary_in_session(session, [w.work_order_id for w in wos_])
        agg: dict[int, list] = defaultdict(lambda: [0, c.ZERO, c.ZERO, c.ZERO, c.ZERO])
        for w in wos_:
            a = agg[w.asset_id]
            a[0] += 1
            a[1] += s[w.work_order_id].parts
            a[2] += s[w.work_order_id].labor
            a[3] += s[w.work_order_id].services
            a[4] += s[w.work_order_id].other
        assets = {a.asset_id: a for a in session.scalars(select(Asset).where(Asset.asset_id.in_(list(agg) or [-1])))}
        cc = {d.detail_account_id: d.name for d in session.scalars(select(DetailAccount).where(DetailAccount.detail_account_id.in_(
            [a.cost_center_detail_account_id for a in assets.values() if a.cost_center_detail_account_id] or [-1])))}
    grand = sum((sum(v[1:]) for v in agg.values()), c.ZERO)
    for aid, (n, p, lab, srv, oth) in sorted(agg.items(), key=lambda kv: -sum(kv[1][1:])):
        total = p + lab + srv + oth
        a = assets[aid]
        res.add([c.asset_label(a), cc.get(a.cost_center_detail_account_id, ""), n, p, lab, srv, oth, total,
                 (total * 100 / grand).quantize(decimal.Decimal("0.1")) if grand else None])
    return res


def parts_usage(company_id: int, f) -> ReportResult:
    from peecha.services.maintenance.parts import item_label
    from peecha.db.models.inventory import StockDocument

    res = ReportResult([("تاریخ", DATE), ("دستور کار", INT), ("تجهیز", TEXT), ("کالا", TEXT), ("نوع", TEXT), ("مقدار", QTY),
                        ("مبلغ", MONEY), ("سند انبار", TEXT)],
                       note="هر ردیف یک سند انبار ثبت‌شده است؛ برگشت با علامت منفی در جمع می‌آید.")
    with new_session() as session:
        scope = _scope(session, company_id, f)
        q = (select(WorkOrderPartMove, WorkOrderPart, WorkOrder, Asset, StockDocument)
             .join(WorkOrderPart, WorkOrderPart.part_id == WorkOrderPartMove.part_id)
             .join(WorkOrder, WorkOrder.work_order_id == WorkOrderPart.work_order_id)
             .join(Asset, Asset.asset_id == WorkOrder.asset_id)
             .join(StockDocument, StockDocument.stock_document_id == WorkOrderPartMove.stock_document_id)
             .where(WorkOrder.company_id == company_id, StockDocument.document_date.between(f.date_from, f.date_to)))
        if getattr(f, "item_id", None):
            q = q.where(WorkOrderPart.item_id == f.item_id)
        if getattr(f, "warehouse_id", None):
            q = q.where(WorkOrderPart.warehouse_id == f.warehouse_id)
        for m, p, w, a, doc in session.execute(q.order_by(StockDocument.document_date, WorkOrderPartMove.move_id)).all():
            if scope is not None and a.asset_id not in scope:
                continue
            sign = -1 if m.direction_code == "RETURN" else 1
            res.add([doc.document_date, w.wo_no, c.asset_label(a), item_label(session, p.item_id),
                     "برگشت" if sign < 0 else "صدور", m.quantity * sign, m.amount * sign, str(doc.document_no)],
                    (doc.stock_document_id, doc.document_type_code))
    return res


def failures(company_id: int, f) -> ReportResult:
    res = ReportResult([("نوع کد", TEXT), ("کد", TEXT), ("تعداد دستور کار", INT), ("سهم٪", PERCENT), ("تجهیزات", TEXT)],
                       no_total={3}, note="دستورهای کار غیرپیشگیرانهٔ بسته‌شده در بازه؛ کد ثبت‌نشده جدا شمرده می‌شود.")
    with new_session() as session:
        scope = _scope(session, company_id, f)
        q = select(WorkOrder, Asset).join(Asset, Asset.asset_id == WorkOrder.asset_id).where(
            WorkOrder.company_id == company_id, WorkOrder.status_code == "CLOSED", WorkOrder.work_type_code.not_in(c.PM_TYPES))
        rows = [(w, a) for w, a in session.execute(q).all() if _in_range(w.closed_at, f) and (scope is None or a.asset_id in scope)]
        codes = {x.failure_code_id: x for x in session.scalars(select(FailureCode).where(FailureCode.company_id == company_id))}
    for kind, attr in (("PROBLEM", "problem_code_id"), ("CAUSE", "cause_code_id"), ("REMEDY", "remedy_code_id")):
        count: dict = defaultdict(int)
        assets: dict = defaultdict(set)
        for w, a in rows:
            key = getattr(w, attr)
            count[key] += 1
            assets[key].add(a.asset_code)
        total = sum(count.values())
        for key, n in sorted(count.items(), key=lambda kv: -kv[1]):
            label = f"{codes[key].code} — {codes[key].name}" if key in codes else "ثبت نشده"
            res.add([c.FAILURE_KIND_LABELS[kind], label, n, (decimal.Decimal(n) * 100 / total).quantize(decimal.Decimal("0.1")),
                     "، ".join(sorted(assets[key])[:8])])
    return res


_WO_STATUS_OPT = ("status", "وضعیت", (_ALL_OPT,) + tuple(c.WO_STATUS_LABELS.items()))
_REQ_STATUS_OPT = ("status", "وضعیت", (_ALL_OPT,) + tuple(c.REQUEST_STATUS_LABELS.items()))

MNT_REPORTS: list[ReportDef] = [
    ReportDef("MNT_WORK_ORDERS", "دفتر دستورهای کار", work_order_log, _SCOPE + ("responsible",),
              "همهٔ دستورهای کار بازه با وضعیت، زمان برنامه‌ای و واقعی و هزینهٔ هر کدام.", "range", _G,
              options=(_WORK_TYPE_OPT, _WO_STATUS_OPT)),
    ReportDef("MNT_REQUESTS", "درخواست‌های تعمیر", request_log, _SCOPE,
              "درخواست‌های ثبت‌شده با شدت، اولویت، توقف ماشین و نتیجهٔ بررسی.", "range", _G, options=(_REQ_STATUS_OPT,)),
    ReportDef("MNT_DOWNTIME", "توقف‌ها و آماده‌به‌کاری", downtime_log, _SCOPE,
              "هر توقف از زمان خرابی تا ثبت آماده‌به‌کاری، مستقل از زمان کار تعمیرکار.", "range", _G),
    ReportDef("MNT_PM_COMPLIANCE", "انجام نگهداری پیشگیرانه", pm_compliance, _SCOPE,
              "سررسیدهای نگهداری پیشگیرانه، زمان انجام، تأخیر و به‌موقع بودن.", "range", _G, options=(_WORK_TYPE_OPT,)),
    ReportDef("MNT_RELIABILITY", "قابلیت اطمینان تجهیزات", reliability, _SCOPE + ("responsible",),
              "میانگین زمان تعمیر، میانگین زمان بین خرابی‌ها، نرخ خرابی، توقف، دسترس‌پذیری و هزینهٔ هر تجهیز.", "range", _G,
              options=(_WORK_TYPE_OPT,)),
    ReportDef("MNT_COST", "هزینهٔ نگهداری تجهیزات", cost_by_equipment, _SCOPE + ("responsible",),
              "هزینهٔ قطعه، نیروی کار، خدمات و سایر به تفکیک تجهیز؛ پرهزینه‌ترین‌ها اول.", "range", _G,
              options=(_WORK_TYPE_OPT,)),
    ReportDef("MNT_PARTS", "مصرف قطعات", parts_usage, _SCOPE + ("item", "warehouse"),
              "قطعه‌های صادر و برگشت‌شدهٔ دستورهای کار با سند انبار.", "range", _G),
    ReportDef("MNT_FAILURES", "علل و نشانه‌های خرابی", failures, _SCOPE,
              "پرتکرارترین نشانه‌ها، علت‌ها و اقدام‌های خرابی‌های بسته‌شده.", "range", _G),
]
