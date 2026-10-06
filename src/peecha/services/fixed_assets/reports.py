"""گزارش‌هایِ دارایی‌هایِ ثابت -- R264 (موتور و صفحهٔ عمومیِ گزارش؛ فقط خواندنی از دفترِ دارایی).

دابل‌کلیک: (شناسهٔ دارایی، «FA_ASSET») صفحهٔ دارایی؛ (شناسهٔ سند، «JOURNAL_ENTRY») سندِ حسابداری.
"""

from __future__ import annotations

import datetime
import decimal
from collections import defaultdict

from sqlalchemy import func, select

from peecha.db.base import new_session
from peecha.db.models.fixed_assets import (
    Asset, AssetCategory, AssetEvent, AssetTransaction, DepreciationLine, DepreciationRun, MachineCostAllocation, PhysicalCount,
)
from peecha.services.fixed_assets import common as c
from peecha.services.purchase_reports import DATE, INT, MONEY, PERCENT, QTY, TEXT, ReportDef, ReportResult

ZERO = c.ZERO
_GROUP = "دارایی‌هایِ ثابت"
_STATUS_OPT = (("status", "وضعیت", (("ACTIVE", "فعال"), ("ALL", "همه"), ("CLOSED", "واگذارشده"))),)


def _ref(asset_id):
    return (asset_id, "FA_ASSET")


class _Labels:
    def __init__(self, session, company_id: int):
        from peecha.db.models.commercial import Branch
        from peecha.db.models.hr import Employee
        from peecha.services import detail_dimensions as dims

        self.session = session
        self.cats = dict(session.execute(select(AssetCategory.category_id, AssetCategory.name)
                                         .where(AssetCategory.company_id == company_id)).all())
        self.branches = dict(session.execute(select(Branch.branch_id, Branch.name).where(Branch.company_id == company_id)).all())
        self._dims = dims
        self._detail: dict[int, str] = {}
        self._loc: dict[int, str] = {}
        self._emp: dict[int, str] = {}
        self._Employee = Employee

    def detail(self, detail_id):
        if not detail_id:
            return ""
        if detail_id not in self._detail:
            self._detail[detail_id] = self._dims.get_detail_account_label(detail_id)
        return self._detail[detail_id]

    def location(self, location_id):
        if not location_id:
            return ""
        if location_id not in self._loc:
            self._loc[location_id] = c.location_path(self.session, location_id)
        return self._loc[location_id]

    def employee(self, employee_id):
        if not employee_id:
            return ""
        if employee_id not in self._emp:
            emp = self.session.get(self._Employee, employee_id)
            self._emp[employee_id] = self.detail(emp.personnel_detail_account_id) if emp is not None else str(employee_id)
        return self._emp[employee_id]


def _filtered(session, company_id: int, f) -> set[int] | None:
    """R275: شناسهٔ دارایی‌هایِ مجاز طبقِ فیلترهایِ طبقه/محل (با زیرمحل‌ها)/شعبه/مرکزِ هزینه؛ None یعنی بدونِ فیلتر."""
    from peecha.db.models.fixed_assets import AssetLocation

    category, location = getattr(f, "fa_category_id", None), getattr(f, "fa_location_id", None)
    branch, cost_center = getattr(f, "branch_id", None), getattr(f, "cost_center_id", None)
    if not any((category, location, branch, cost_center)):
        return None
    q = select(Asset.asset_id).where(Asset.company_id == company_id)
    if category:
        q = q.where(Asset.category_id == category)
    if branch:
        q = q.where(Asset.branch_id == branch)
    if cost_center:
        q = q.where(Asset.cost_center_detail_account_id == cost_center)
    if location:
        children: dict[int, list[int]] = defaultdict(list)
        for loc_id, parent in session.execute(select(AssetLocation.location_id, AssetLocation.parent_location_id)
                                              .where(AssetLocation.company_id == company_id)).all():
            children[parent].append(loc_id)
        ids, stack = set(), [location]
        while stack:
            node = stack.pop()
            if node not in ids:
                ids.add(node)
                stack.extend(children.get(node, ()))
        q = q.where(Asset.location_id.in_(ids))
    return set(session.scalars(q))


def _assets(session, company_id: int, f, status_default: str = "ACTIVE"):
    status = str(f.options.get("status") or status_default)
    q = select(Asset).where(Asset.company_id == company_id)
    if status == "ACTIVE":
        q = q.where(Asset.status_code.not_in(c.CLOSED_STATUSES))
    elif status == "CLOSED":
        q = q.where(Asset.status_code.in_(c.CLOSED_STATUSES))
    allowed = _filtered(session, company_id, f)
    if allowed is not None:
        q = q.where(Asset.asset_id.in_(allowed or {-1}))
    return list(session.scalars(q.order_by(Asset.asset_code)))


# --- دفترِ دارایی‌ها و تفکیک‌ها -----------------------------------------------------------------------------
def register(company_id: int, f) -> ReportResult:
    r = ReportResult([("کد", TEXT), ("نام", TEXT), ("طبقه", TEXT), ("بهایِ تمام‌شده", MONEY), ("استهلاکِ انباشته", MONEY),
                      ("کاهشِ ارزش", MONEY), ("ارزشِ دفتری", MONEY), ("محل", TEXT), ("مرکزِ هزینه", TEXT), ("وضعیت", TEXT)],
                     note="ارقام از دفترِ دارایی (دفترِ اصلیِ حسابداری).")
    with new_session() as session:
        lab = _Labels(session, company_id)
        for a in _assets(session, company_id, f):
            r.add([a.asset_code, a.name, lab.cats.get(a.category_id, ""), a.gross_cost, a.accumulated_depreciation,
                   a.accumulated_impairment, a.book_value, lab.location(a.location_id), lab.detail(a.cost_center_detail_account_id),
                   c.STATUS_LABELS[a.status_code]], _ref(a.asset_id))
    return r


def _by(dimension: str):
    titles = {"LOCATION": "محل", "BRANCH": "شعبه", "COST_CENTER": "مرکزِ هزینه", "CATEGORY": "طبقه"}

    def report(company_id: int, f) -> ReportResult:
        agg: dict[str, list] = defaultdict(lambda: [0, ZERO, ZERO, ZERO])
        with new_session() as session:
            lab = _Labels(session, company_id)
            for a in _assets(session, company_id, f):
                key = {"LOCATION": lambda: lab.location(a.location_id), "BRANCH": lambda: lab.branches.get(a.branch_id, ""),
                       "COST_CENTER": lambda: lab.detail(a.cost_center_detail_account_id),
                       "CATEGORY": lambda: lab.cats.get(a.category_id, "")}[dimension]() or f"بدونِ {titles[dimension]}"
                g = agg[key]
                g[0] += 1
                g[1] += a.gross_cost
                g[2] += a.accumulated_depreciation + a.accumulated_impairment
                g[3] += a.book_value
        r = ReportResult([(titles[dimension], TEXT), ("تعداد", INT), ("بهایِ تمام‌شده", MONEY),
                          ("استهلاک و کاهشِ ارزشِ انباشته", MONEY), ("ارزشِ دفتری", MONEY), ("سهم از ارزش", PERCENT)], no_total={5})
        total = sum((g[3] for g in agg.values()), ZERO)
        for key, (n, gross, acc, nbv) in sorted(agg.items(), key=lambda kv: -kv[1][3]):
            r.add([key, n, gross, acc, nbv, (nbv * 100 / total).quantize(decimal.Decimal("0.1")) if total else None])
        return r
    return report


def fully_depreciated(company_id: int, f) -> ReportResult:
    r = ReportResult([("کد", TEXT), ("نام", TEXT), ("طبقه", TEXT), ("بهایِ تمام‌شده", MONEY), ("ارزشِ اسقاط", MONEY),
                      ("تاریخِ بهره‌برداری", DATE), ("محل", TEXT)], note="دارایی‌هایی که هنوز در اختیارند ولی کاملاً مستهلک شده‌اند.")
    with new_session() as session:
        lab = _Labels(session, company_id)
        allowed = _filtered(session, company_id, f)
        for a in session.scalars(select(Asset).where(Asset.company_id == company_id, Asset.status_code == "FULLY_DEPRECIATED")
                                 .order_by(Asset.asset_code)):
            if allowed is not None and a.asset_id not in allowed:
                continue
            r.add([a.asset_code, a.name, lab.cats.get(a.category_id, ""), a.gross_cost, a.residual_value, a.in_service_date,
                   lab.location(a.location_id)], _ref(a.asset_id))
    return r


# --- استهلاک و حرکت‌ها --------------------------------------------------------------------------------------
def depreciation(company_id: int, f) -> ReportResult:
    r = ReportResult([("دوره", TEXT), ("کد", TEXT), ("نام", TEXT), ("ارزشِ اولِ دوره", MONEY), ("استهلاک", MONEY),
                      ("ارزشِ پایانِ دوره", MONEY), ("کارکرد", QTY), ("مرکزِ هزینه", TEXT)], no_total={3, 5},
                     note="فقط اجراهایِ ثبت‌شده در بازه.")
    with new_session() as session:
        lab = _Labels(session, company_id)
        rows = session.execute(
            select(DepreciationRun.period_code, DepreciationRun.journal_entry_id, DepreciationLine, Asset.asset_code, Asset.name)
            .join(DepreciationLine, DepreciationLine.run_id == DepreciationRun.run_id)
            .join(Asset, Asset.asset_id == DepreciationLine.asset_id)
            .where(DepreciationRun.company_id == company_id, DepreciationRun.status_code == "POSTED",
                   DepreciationRun.period_end >= f.date_from, DepreciationRun.period_start <= f.date_to)
            .order_by(DepreciationRun.period_start, Asset.asset_code)).all()
        allowed = _filtered(session, company_id, f)
        for period, _je, ln, code, name in rows:
            if allowed is not None and ln.asset_id not in allowed:
                continue
            r.add([period, code, name, ln.opening_book_value, ln.amount, ln.closing_book_value, ln.units,
                   lab.detail(ln.cost_center_detail_account_id)], _ref(ln.asset_id))
    return r


def movement(company_id: int, f) -> ReportResult:
    r = ReportResult([("تاریخ", DATE), ("کد", TEXT), ("نام", TEXT), ("نوع", TEXT), ("تغییرِ بها", MONEY), ("استهلاک", MONEY),
                      ("کاهشِ ارزش", MONEY), ("مازادِ تجدیدِ ارزیابی", MONEY), ("شرح", TEXT)],
                     note="همهٔ حرکت‌هایِ دفترِ دارایی (تحصیل، انتقال، بهسازی، تجدیدِ ارزیابی، کاهشِ ارزش، واگذاری، ...).")
    kinds = f.options.get("kind")
    with new_session() as session:
        q = (select(AssetTransaction, Asset.asset_code, Asset.name).join(Asset, Asset.asset_id == AssetTransaction.asset_id)
             .where(AssetTransaction.company_id == company_id, AssetTransaction.txn_date.between(f.date_from, f.date_to)))
        if kinds and kinds != "ALL":
            q = q.where(AssetTransaction.txn_type == kinds)
        allowed = _filtered(session, company_id, f)
        for t, code, name in session.execute(q.order_by(AssetTransaction.txn_date, AssetTransaction.txn_id)).all():
            if allowed is not None and t.asset_id not in allowed:
                continue
            r.add([t.txn_date, code, name, c.TXN_LABELS.get(t.txn_type, t.txn_type), t.cost_delta, t.depreciation_delta,
                   t.impairment_delta, t.revaluation_delta, t.description or ""],
                  (t.journal_entry_id, "JOURNAL_ENTRY") if t.journal_entry_id else _ref(t.asset_id))
    return r


def disposals(company_id: int, f) -> ReportResult:
    r = ReportResult([("تاریخ", DATE), ("کد", TEXT), ("نام", TEXT), ("نوع", TEXT), ("بهایِ تمام‌شده", MONEY),
                      ("استهلاک و کاهشِ ارزش", MONEY), ("ارزشِ دفتری", MONEY), ("مبلغِ دریافتی", MONEY), ("سود/زیان", MONEY),
                      ("علت", TEXT)])
    labels = {"SALE": "فروش", "SCRAP": "اسقاط", "DONATION": "اهدا", "WRITE_OFF": "حذف از دفاتر"}
    with new_session() as session:
        rows = session.execute(select(AssetEvent, Asset.asset_code, Asset.name).join(Asset, Asset.asset_id == AssetEvent.asset_id)
                               .where(AssetEvent.company_id == company_id, AssetEvent.event_type.in_(tuple(labels)),
                                      AssetEvent.status_code == "POSTED", AssetEvent.event_date.between(f.date_from, f.date_to))
                               .order_by(AssetEvent.event_date)).all()
        allowed = _filtered(session, company_id, f)
        for ev, code, name in rows:
            if allowed is not None and ev.asset_id not in allowed:
                continue
            d = ev.details or {}
            acc = decimal.Decimal(d.get("accumulated_depreciation", 0)) + decimal.Decimal(d.get("impairment", 0))
            r.add([ev.event_date, code, name, labels[ev.event_type], ev.amount, acc, ev.previous_book_value, ev.proceeds,
                   ev.gain_loss, ev.reason or ""], (ev.journal_entry_id, "JOURNAL_ENTRY") if ev.journal_entry_id else _ref(ev.asset_id))
    return r


def gain_loss(company_id: int, f) -> ReportResult:
    detail = disposals(company_id, f)
    agg: dict[str, list] = defaultdict(lambda: [0, ZERO, ZERO, ZERO, ZERO])
    for row in detail.rows:
        g = agg[row[3]]
        g[0] += 1
        g[1] += row[6] or ZERO
        g[2] += row[7] or ZERO
        g[3] += max(row[8] or ZERO, ZERO)
        g[4] += min(row[8] or ZERO, ZERO)
    r = ReportResult([("نوعِ واگذاری", TEXT), ("تعداد", INT), ("ارزشِ دفتری", MONEY), ("مبلغِ دریافتی", MONEY), ("سود", MONEY),
                      ("زیان", MONEY), ("خالص", MONEY)])
    for kind, (n, nbv, proceeds, gain, loss) in agg.items():
        r.add([kind, n, nbv, proceeds, gain, -loss, gain + loss])
    return r


def cip_report(company_id: int, f) -> ReportResult:
    from peecha.services.fixed_assets import events as fe

    r = ReportResult([("کد", TEXT), ("نام", TEXT), ("تاریخِ شروع", DATE), ("وضعیت", TEXT), ("جمعِ هزینه", MONEY), ("داراییِ حاصل", TEXT)])
    status = {"OPEN": "در جریان", "CAPITALIZED": "سرمایه‌ای‌شده", "CANCELLED": "لغو"}
    with new_session() as session:
        codes = dict(session.execute(select(Asset.asset_id, Asset.asset_code).where(Asset.company_id == company_id)).all())
    for p in fe.list_cip(company_id):
        if f.options.get("status", "ACTIVE") == "ACTIVE" and p.status != "OPEN":
            continue
        r.add([p.code, p.name, p.start_date, status[p.status], p.total, codes.get(p.capitalized_asset_id, "")],
              _ref(p.capitalized_asset_id) if p.capitalized_asset_id else None)
    return r


def physical(company_id: int, f) -> ReportResult:
    from peecha.services.fixed_assets import physical as fp

    r = ReportResult([("شمارش", TEXT), ("کد", TEXT), ("نام", TEXT), ("نتیجه", TEXT), ("محلِ مورد انتظار", TEXT),
                      ("محلِ یافت‌شده", TEXT), ("روش", TEXT), ("توضیح", TEXT)], note="مغایرت‌هایِ آخرین شمارش (یا همهٔ ردیف‌ها).")
    with new_session() as session:
        count = session.scalar(select(PhysicalCount).where(PhysicalCount.company_id == company_id)
                               .order_by(PhysicalCount.count_date.desc(), PhysicalCount.count_id.desc()).limit(1))
        if count is None:
            return r
        code, count_id = count.code, count.count_id
        allowed = _filtered(session, company_id, f)
    for it in fp.count_items(company_id, count_id, discrepancies_only=f.options.get("rows", "DIFF") == "DIFF"):
        if allowed is not None and it.asset_id not in allowed:
            continue
        r.add([code, it.asset_code, it.name, it.label, it.expected_location, it.found_location, it.method or "", it.note or ""],
              _ref(it.asset_id))
    return r


def aging(company_id: int, f) -> ReportResult:
    buckets = ((1, "کمتر از ۱ سال"), (3, "۱ تا ۳ سال"), (5, "۳ تا ۵ سال"), (10, "۵ تا ۱۰ سال"), (10_000, "بیش از ۱۰ سال"))
    agg = {label: [0, ZERO, ZERO] for _limit, label in buckets}
    today = f.date_to or datetime.date.today()
    with new_session() as session:
        for a in _assets(session, company_id, f):
            if a.acquisition_date is None:
                continue
            years = (today - a.acquisition_date).days / 365.25
            label = next(lb for limit, lb in buckets if years < limit)
            agg[label][0] += 1
            agg[label][1] += a.gross_cost
            agg[label][2] += a.book_value
    r = ReportResult([("سنِ دارایی", TEXT), ("تعداد", INT), ("بهایِ تمام‌شده", MONEY), ("ارزشِ دفتری", MONEY),
                      ("نسبتِ ارزشِ باقی‌مانده", PERCENT)], no_total={4})
    for _limit, label in buckets:
        n, gross, nbv = agg[label]
        r.add([label, n, gross, nbv, (nbv * 100 / gross).quantize(decimal.Decimal("0.1")) if gross else None])
    return r


def forecast_report(company_id: int, f) -> ReportResult:
    from peecha.services.fixed_assets import depreciation as fd

    months = int(f.options.get("months") or 12)
    by_period: dict[str, decimal.Decimal] = defaultdict(lambda: ZERO)
    with new_session() as session:
        ids = list(session.scalars(select(Asset.asset_id).where(Asset.company_id == company_id,
                                                                Asset.status_code.in_(c.DEPRECIABLE_STATUSES))))
        allowed = _filtered(session, company_id, f)
    if allowed is not None:
        ids = [i for i in ids if i in allowed]
    for asset_id in ids:
        for row in fd.forecast(company_id, asset_id, months=months):
            by_period[row.period_code] += row.amount
    r = ReportResult([("دوره", TEXT), ("استهلاکِ پیش‌بینی‌شده", MONEY), ("تجمعی", MONEY)],
                     note="بر اساسِ روش و عمرِ باقی‌ماندهٔ هر دارایی (بدونِ خرید/واگذاریِ آینده).", no_total={2})
    running = ZERO
    for period in sorted(by_period):
        running += by_period[period]
        r.add([period, by_period[period], running])
    return r


def machine_cost(company_id: int, f) -> ReportResult:
    from peecha.services.fixed_assets import production as fprod

    r = ReportResult([("کد", TEXT), ("ماشین", TEXT), ("مرکزِ کار", TEXT), ("دوره", TEXT), ("استهلاکِ دوره", MONEY),
                      ("ساعتِ کارکرد", QTY), ("نرخِ هر ساعت", MONEY), ("تخصیص به تولید", MONEY)], no_total={6},
                     note="نرخ = استهلاکِ دوره ÷ ساعتِ کارکرد (یا نرخِ دستیِ ماشین) -- مبنایِ بهایِ تولید.")
    period_code = c.period_of(f.date_to or datetime.date.today())[0]
    with new_session() as session:
        allocated = dict(session.execute(select(MachineCostAllocation.asset_id, func.sum(MachineCostAllocation.amount))
                                         .where(MachineCostAllocation.company_id == company_id,
                                                MachineCostAllocation.period_code == period_code)
                                         .group_by(MachineCostAllocation.asset_id)).all())
        allowed = _filtered(session, company_id, f)
    for m in fprod.machines(company_id):
        if allowed is not None and m.asset_id not in allowed:
            continue
        info = fprod.machine_rate(company_id, m.asset_id, period_code)
        r.add([m.asset_code, m.name, m.work_center_code or "", period_code, info.depreciation, info.hours, info.rate,
               allocated.get(m.asset_id, ZERO)], _ref(m.asset_id))
    return r


_NONE = ()
# R275: فیلترهایِ دارایی (طبقه، محل، شعبه، مرکزِ هزینه)
_FA = ("fa_category", "fa_location", "branch", "cost_center")
FA_REPORTS: list[ReportDef] = [
    ReportDef("FA_REGISTER", "دفترِ دارایی‌هایِ ثابت", register, _FA,
              "کد، نام، طبقه، بها، استهلاک، ارزشِ دفتری، محل، مرکزِ هزینه و وضعیت.", "none", _GROUP, options=_STATUS_OPT),
    ReportDef("FA_DEPRECIATION", "گزارشِ استهلاک", depreciation, _FA, "استهلاکِ ثبت‌شدهٔ هر دارایی در هر دوره.", "range", _GROUP),
    ReportDef("FA_MOVEMENT", "گردشِ دارایی‌ها", movement, _FA, "تحصیل، انتقال، بهسازی، تجدیدِ ارزیابی، کاهشِ ارزش، واگذاری.",
              "range", _GROUP, options=(("kind", "نوع", (("ALL", "همه"),) + tuple(c.TXN_LABELS.items())),)),
    ReportDef("FA_FULLY_DEPRECIATED", "دارایی‌هایِ کاملاً مستهلک", fully_depreciated, _FA, "در اختیار ولی بدونِ ارزشِ قابلِ استهلاک.",
              "none", _GROUP),
    ReportDef("FA_BY_LOCATION", "دارایی‌ها به تفکیکِ محل", _by("LOCATION"), _FA, "تعداد و ارزش در هر محل.", "none", _GROUP,
              options=_STATUS_OPT),
    ReportDef("FA_BY_BRANCH", "دارایی‌ها به تفکیکِ شعبه", _by("BRANCH"), _FA, "تعداد و ارزش در هر شعبه.", "none", _GROUP,
              options=_STATUS_OPT),
    ReportDef("FA_BY_COST_CENTER", "دارایی‌ها به تفکیکِ مرکزِ هزینه", _by("COST_CENTER"), _FA, "تعداد و ارزش در هر مرکزِ هزینه.",
              "none", _GROUP, options=_STATUS_OPT),
    ReportDef("FA_BY_CATEGORY", "دارایی‌ها به تفکیکِ طبقه", _by("CATEGORY"), _FA, "تعداد و ارزش در هر طبقه.", "none", _GROUP,
              options=_STATUS_OPT),
    ReportDef("FA_CIP", "دارایی‌هایِ در جریانِ تکمیل", cip_report, _NONE, "پروژه‌هایِ ساخت و جمعِ هزینه.", "none", _GROUP,
              options=(("status", "وضعیت", (("ACTIVE", "در جریان"), ("ALL", "همه"))),)),
    ReportDef("FA_DISPOSALS", "واگذاری‌ها (فروش/اسقاط)", disposals, _FA, "بها، استهلاک، ارزشِ دفتری، مبلغِ دریافتی و سود/زیان.",
              "range", _GROUP),
    ReportDef("FA_GAIN_LOSS", "سود و زیانِ واگذاری", gain_loss, _FA, "جمعِ سود/زیان به تفکیکِ نوعِ واگذاری.", "range", _GROUP),
    ReportDef("FA_PHYSICAL", "شمارشِ فیزیکیِ دارایی", physical, _FA, "مغایرت‌هایِ آخرین شمارش.", "none", _GROUP,
              options=(("rows", "ردیف‌ها", (("DIFF", "فقط مغایرت"), ("ALL", "همه"))),)),
    ReportDef("FA_AGING", "سنِ دارایی‌ها", aging, _FA, "تعداد و ارزش به تفکیکِ سنِ دارایی.", "as_of", _GROUP, options=_STATUS_OPT),
    ReportDef("FA_FORECAST", "پیش‌بینیِ استهلاک", forecast_report, _FA, "استهلاکِ ماه‌هایِ آینده.", "none", _GROUP,
              options=(("months", "ماه", (("12", "۱۲ ماه"), ("24", "۲۴ ماه"), ("60", "۶۰ ماه"))),)),
    ReportDef("FA_MACHINE_COST", "بهایِ ماشین‌آلاتِ تولید", machine_cost, _FA, "نرخِ هر ساعتِ ماشین و تخصیص به تولید.",
              "as_of", _GROUP),
]
