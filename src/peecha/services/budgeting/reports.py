"""R313 — گزارش‌های بودجه روی همان موتور گزارش (فیلتر، گروه‌بندی، چاپ PDF و خروجی Excel، Drill-down تا سند منبع).

تعریف‌ها (همه به ارز پایهٔ شرکت):
- بودجهٔ بازه = جمع مبلغ دوره‌های نسخهٔ منتخب (پیش‌فرض: منتشرشده) که در بازه می‌افتند؛ دورهٔ نیمه‌کاره به نسبت روز.
- پیش‌تعهد/تعهد/واقعی = جمع دفتر مصرف با «تاریخ دوره» در بازه (تاریخ سفارش برای تعهد، تاریخ فاکتور برای واقعی).
- ردیف «حساب دفتر کل»: واقعی = بدهکار − بستانکار ارز پایهٔ ردیف‌های سند حسابداری (موقت، دائم و برگشت‌خورده؛ برگشت و
  سند برگشتی هم را خنثی می‌کنند) روی حساب و زیرحساب‌هایش با همان مرکز هزینه/پروژه؛ تعهد ندارد.
- مصرف‌شده = واقعی + تعهد (+ پیش‌تعهد اگر کلید «کسر درخواست خرید» روشن است)؛ ماندهٔ قابل تعهد = بودجه − مصرف‌شده.
- انحراف = بودجه − واقعی − تعهد؛ درصد انحراف = انحراف ÷ بودجه.
- پرداخت‌شده = سهم پرداخت فاکتورهای واقعی ردیف (تخصیص پرداخت ÷ جمع فاکتور) — فقط شاخص نقدینگی، نه هزینه.
- پیش‌بینی پایان دوره (روش نرخ خطی) = واقعی + تعهد باز + (واقعی ÷ روزهای گذشته) × روزهای باقی‌مانده.
"""

from __future__ import annotations

import datetime
import decimal
from collections import defaultdict
from types import SimpleNamespace

from sqlalchemy import func, select

from peecha.db.base import new_session
from peecha.db.models.accounting import ChartOfAccount, JournalEntry, JournalEntryLine, JournalEntryLineDetail, JournalEntryStatus
from peecha.db.models.budgeting import (
    Budget, BudgetException, BudgetLine, BudgetPeriod, BudgetVersion, ConsumptionEntry, ControlEvent, ControlKey, LinePeriodAmount,
)
from peecha.db.models.commercial import CommercialDocument, PurchaseRequest
from peecha.services import stock_controls
from peecha.services.budgeting import budgets as bud
from peecha.services.budgeting import common as c
from peecha.services.purchase_reports import DATE, INT, MONEY, PERCENT, TEXT, ReportDef, ReportResult

_G = "بودجه‌ریزی و کنترل بودجه"
_SCOPE = ("budget", "bud_version", "cost_center", "project", "branch", "account", "responsible")
_GL_STATUSES = ("TEMPORARY", "PERMANENT", "REVERSED")
_RELEASE_EVENTS = ("CANCEL", "REVERT", "DELETE", "CLOSE")


def _opt(f, key, default=None):
    v = (f.options or {}).get(key)
    return default if v in (None, "ALL") else v


def _overlap(a0, a1, b0, b1) -> int:
    return max((min(a1, b1) - max(a0, b0)).days + 1, 0)


def _ratio(part, whole):
    return (part * 100 / whole) if whole else None


# --- دامنهٔ ردیف‌ها ------------------------------------------------------------------------------------------
def _scope(session, company_id: int, f) -> list[SimpleNamespace]:
    q = select(Budget, BudgetVersion).join(BudgetVersion, BudgetVersion.budget_id == Budget.budget_id).where(Budget.company_id == company_id)
    version_id = getattr(f, "budget_version_id", None)
    if version_id:
        q = q.where(BudgetVersion.version_id == version_id)
    else:
        q = q.where(BudgetVersion.status_code == "PUBLISHED", Budget.is_active.is_(True))
    if getattr(f, "budget_id", None):
        q = q.where(Budget.budget_id == f.budget_id)
    q = q.where(Budget.date_to >= f.date_from, Budget.date_from <= f.date_to)
    pairs = session.execute(q.order_by(Budget.code)).all()
    if not pairs:
        return []
    lines = list(session.execute(select(BudgetLine, ControlKey).join(ControlKey, ControlKey.key_id == BudgetLine.key_id)
                                 .where(BudgetLine.version_id.in_([v.version_id for _b, v in pairs])).order_by(BudgetLine.line_no)).all())
    periods = defaultdict(list)
    for p in session.scalars(select(BudgetPeriod).where(BudgetPeriod.budget_id.in_([b.budget_id for b, _v in pairs]))
                             .order_by(BudgetPeriod.period_no)):
        periods[p.budget_id].append(p)
    amounts = defaultdict(dict)
    for p in session.scalars(select(LinePeriodAmount).where(LinePeriodAmount.line_id.in_([ln.line_id for ln, _k in lines] or [0]))):
        amounts[p.line_id][p.period_no] = p.amount
    subtree = None
    if getattr(f, "account_id", None):
        subtree = _subtree(session, company_id, f.account_id)
    by_version = {v.version_id: (b, v) for b, v in pairs}
    out = []
    for ln, key in lines:
        b, v = by_version[ln.version_id]
        if getattr(f, "cost_center_id", None) and key.cost_center_detail_account_id != f.cost_center_id:
            continue
        if getattr(f, "project_id", None) and key.project_detail_account_id != f.project_id:
            continue
        if getattr(f, "branch_id", None) and key.branch_id != f.branch_id:
            continue
        if getattr(f, "responsible_id", None) and ln.responsible_user_id != f.responsible_id:
            continue
        if subtree is not None and key.account_id not in subtree:
            continue
        ps = periods[b.budget_id]
        rng = c.ZERO
        for p in ps:
            days = (p.date_to - p.date_from).days + 1
            rng += c.dec(amounts[ln.line_id].get(p.period_no)) * _overlap(p.date_from, p.date_to, f.date_from, f.date_to) / days
        out.append(SimpleNamespace(budget=b, version=v, line=ln, key=key, periods=ps, period_amounts=amounts[ln.line_id],
                                   total=bud.line_amount(ln), budget_amount=c.money(rng)))
    return out


def _subtree(session, company_id: int, account_id: int) -> set[int]:
    parent = dict(session.execute(select(ChartOfAccount.account_id, ChartOfAccount.parent_account_id)
                                  .where(ChartOfAccount.company_id == company_id)).all())
    out, changed = {account_id}, True
    while changed:
        changed = False
        for child, par in parent.items():
            if par in out and child not in out:
                out.add(child)
                changed = True
    return out


def _consumption(session, key_ids, d0, d1) -> dict[int, dict[str, decimal.Decimal]]:
    out = defaultdict(lambda: {"PRE": c.ZERO, "COMMIT": c.ZERO, "ACTUAL": c.ZERO})
    if not key_ids:
        return out
    for key_id, kind, amount in session.execute(
            select(ConsumptionEntry.key_id, ConsumptionEntry.kind_code, func.sum(ConsumptionEntry.amount))
            .where(ConsumptionEntry.key_id.in_(list(key_ids)), ConsumptionEntry.period_date.between(d0, d1))
            .group_by(ConsumptionEntry.key_id, ConsumptionEntry.kind_code)).all():
        out[key_id][kind] = c.dec(amount)
    return out


def _gl_lines(session, company_id: int, keys, d0, d1):
    """ردیف‌های دفتر کل برای ردیف‌های «حساب دفتر کل»: {key_id: [(journal_entry_id، تاریخ، شماره، شرح، مبلغ)]}."""
    keys = [k for k in keys if k.basis_code == "ACCOUNT"]
    if not keys:
        return {}
    from peecha.services import detail_dimensions as dims

    cc_type = dims.get_specialized_dimension_type_id(company_id, dims.COST_CENTER_CODE)
    pj_type = dims.get_specialized_dimension_type_id(company_id, dims.PROJECT_CODE)
    trees = {k.key_id: _subtree(session, company_id, k.account_id) for k in keys}
    accounts = set().union(*trees.values())
    rows = session.execute(
        select(JournalEntryLine.line_id, JournalEntryLine.account_id, JournalEntryLine.debit_amount_base,
               JournalEntryLine.credit_amount_base, JournalEntry.journal_entry_id, JournalEntry.document_date, JournalEntry.temporary_no,
               JournalEntry.description, JournalEntryStatus.code)
        .join(JournalEntry, JournalEntry.journal_entry_id == JournalEntryLine.journal_entry_id)
        .join(JournalEntryStatus, JournalEntryStatus.status_id == JournalEntry.status_id)
        .where(JournalEntry.company_id == company_id, JournalEntry.document_date.between(d0, d1),
               JournalEntryLine.account_id.in_(accounts), JournalEntryStatus.code.in_(_GL_STATUSES))).all()
    details = defaultdict(dict)
    if rows:
        for line_id, dim_type, detail in session.execute(
                select(JournalEntryLineDetail.line_id, JournalEntryLineDetail.dimension_type_id, JournalEntryLineDetail.detail_account_id)
                .where(JournalEntryLineDetail.line_id.in_([r[0] for r in rows]))).all():
            details[line_id][dim_type] = detail
    out = defaultdict(list)
    for r in rows:
        for k in keys:
            if r[1] not in trees[k.key_id]:
                continue
            d = details.get(r[0], {})
            if k.cost_center_detail_account_id and d.get(cc_type) != k.cost_center_detail_account_id:
                continue
            if k.project_detail_account_id and d.get(pj_type) != k.project_detail_account_id:
                continue
            out[k.key_id].append((r[4], r[5], r[6], r[7], c.dec(r[2]) - c.dec(r[3]), r[8]))
    return out


def _paid(session, key_ids, d0, d1) -> dict[int, decimal.Decimal]:
    """سهم پرداخت فاکتورهای واقعی هر ردیف (شاخص نقدینگی)."""
    from peecha.services import commercial_settlements as settlements

    rows = session.execute(
        select(ConsumptionEntry.key_id, ConsumptionEntry.source_document_id, func.sum(ConsumptionEntry.amount))
        .where(ConsumptionEntry.key_id.in_(list(key_ids) or [0]), ConsumptionEntry.kind_code == "ACTUAL",
               ConsumptionEntry.source_type == "PURCHASE_INVOICE", ConsumptionEntry.period_date.between(d0, d1))
        .group_by(ConsumptionEntry.key_id, ConsumptionEntry.source_document_id)).all()
    totals = {d.document_id: (c.dec(d.total_amount), c.dec(d.exchange_rate or 1)) for d in session.scalars(
        select(CommercialDocument).where(CommercialDocument.document_id.in_({r[1] for r in rows} or {0})))}
    out = defaultdict(lambda: c.ZERO)
    for key_id, doc_id, amount in rows:
        total, rate = totals.get(doc_id, (c.ZERO, c.ZERO))
        if total > 0:
            share = min(c.dec(settlements._settled_amount(session, doc_id)) / total, decimal.Decimal(1))
            out[key_id] += c.money(c.dec(amount) * share)
    return out


def _data(company_id: int, f, with_paid: bool = False):
    lookups = bud.Lookups(company_id)
    pre_counts = c.is_on(company_id, stock_controls.BUD_PR_COMMIT)
    with new_session() as session:
        scope = _scope(session, company_id, f)
        cons = _consumption(session, {s.key.key_id for s in scope}, f.date_from, f.date_to)
        gl = _gl_lines(session, company_id, [s.key for s in scope], f.date_from, f.date_to)
        paid = _paid(session, {s.key.key_id for s in scope}, f.date_from, f.date_to) if with_paid else {}
        names = c.user_names(session, [s.line.responsible_user_id for s in scope])
        settings = c.settings(company_id, session)
    for s in scope:
        t = cons[s.key.key_id]
        if s.key.basis_code == "ACCOUNT":
            s.pre, s.commit, s.actual = c.ZERO, c.ZERO, sum((x[4] for x in gl.get(s.key.key_id, [])), c.ZERO)
        else:
            s.pre, s.commit, s.actual = t["PRE"], t["COMMIT"], t["ACTUAL"]
        s.consumed = s.actual + s.commit + (s.pre if pre_counts else c.ZERO)
        s.available = s.budget_amount - s.consumed
        s.variance = s.budget_amount - s.actual - s.commit
        s.paid = paid.get(s.key.key_id, c.ZERO)
        s.label = lookups.key_label(s.key)
        s.responsible = names.get(s.line.responsible_user_id, "")
        warn = c.dec(s.line.warn_percent or settings.warn_percent)
        if s.consumed > s.budget_amount:
            s.state = "عبور از بودجه"
        elif s.budget_amount and s.consumed * 100 >= s.budget_amount * warn:
            s.state = "نزدیک به سقف"
        elif not s.consumed:
            s.state = "بدون مصرف"
        else:
            s.state = "در محدوده"
    return scope, lookups


def _name(s) -> str:
    return f"{s.budget.code} — {s.budget.name}"


def _ref(s):
    return (s.key.key_id, "BUD_KEY")


# --- گزارش‌ها ------------------------------------------------------------------------------------------------
def budget_vs_actual(company_id: int, f) -> ReportResult:
    scope, _l = _data(company_id, f, with_paid=True)
    result = ReportResult([
        ("بودجه", TEXT), ("نسخه", INT), ("ردیف بودجه", TEXT), ("مبنا", TEXT), ("مسئول", TEXT), ("بودجهٔ بازه", MONEY),
        ("پیش‌تعهد", MONEY), ("تعهد", MONEY), ("واقعی", MONEY), ("مصرف‌شده", MONEY), ("ماندهٔ قابل تعهد", MONEY),
        ("درصد مصرف", PERCENT), ("پرداخت‌شده (نقدینگی)", MONEY), ("وضعیت", TEXT),
    ], no_total={1, 11}, note="مصرف‌شده = واقعی + تعهد (+ پیش‌تعهد با کلید مربوط). پرداخت فقط شاخص نقدینگی است و جای هزینهٔ واقعی را نمی‌گیرد.")
    for s in scope:
        result.add([_name(s), s.version.version_no, s.label, c.BASIS_LABELS[s.key.basis_code], s.responsible, s.budget_amount, s.pre,
                    s.commit, s.actual, s.consumed, s.available, _ratio(s.consumed, s.budget_amount), s.paid, s.state], _ref(s))
    return result


def available(company_id: int, f) -> ReportResult:
    scope, _l = _data(company_id, f)
    with new_session() as session:
        pend = defaultdict(lambda: [0, c.ZERO])
        for key_id, amount in session.execute(select(BudgetException.key_id, BudgetException.excess_amount).where(
                BudgetException.company_id == company_id, BudgetException.status_code == "PENDING")).all():
            pend[key_id][0] += 1
            pend[key_id][1] += c.dec(amount)
    result = ReportResult([
        ("بودجه", TEXT), ("ردیف بودجه", TEXT), ("بودجهٔ بازه", MONEY), ("واقعی + تعهد", MONEY), ("مانده بدون پیش‌تعهد", MONEY),
        ("پیش‌تعهد", MONEY), ("مانده پس از پیش‌تعهد", MONEY), ("مجوز منتظر", INT), ("مبلغ مجوزهای منتظر", MONEY),
    ], note="ماندهٔ قابل تعهد = بودجهٔ بازه − واقعی − تعهد؛ ستون بعد پیش‌تعهد درخواست‌های خرید تصویب‌شده را هم کم می‌کند.")
    for s in scope:
        used = s.actual + s.commit
        result.add([_name(s), s.label, s.budget_amount, used, s.budget_amount - used, s.pre, s.budget_amount - used - s.pre,
                    pend[s.key.key_id][0], pend[s.key.key_id][1]], _ref(s))
    return result


def periodic(company_id: int, f) -> ReportResult:
    """عملکرد هر دوره و انحراف مبلغ/درصد، با جمع تجمعی."""
    lookups = bud.Lookups(company_id)
    with new_session() as session:
        scope = _scope(session, company_id, f)
        by_period = defaultdict(lambda: defaultdict(lambda: c.ZERO))
        for key_id, kind, pdate, amount in session.execute(
                select(ConsumptionEntry.key_id, ConsumptionEntry.kind_code, ConsumptionEntry.period_date, func.sum(ConsumptionEntry.amount))
                .where(ConsumptionEntry.key_id.in_([s.key.key_id for s in scope] or [0]))
                .group_by(ConsumptionEntry.key_id, ConsumptionEntry.kind_code, ConsumptionEntry.period_date)).all():
            by_period[key_id][(kind, pdate)] += c.dec(amount)
        gl = _gl_lines(session, company_id, [s.key for s in scope], min((s.budget.date_from for s in scope), default=f.date_from),
                       max((s.budget.date_to for s in scope), default=f.date_to))
    result = ReportResult([
        ("بودجه", TEXT), ("ردیف بودجه", TEXT), ("دوره", TEXT), ("از", DATE), ("تا", DATE), ("بودجهٔ دوره", MONEY), ("واقعی", MONEY),
        ("تعهد", MONEY), ("انحراف", MONEY), ("درصد انحراف", PERCENT), ("بودجهٔ تجمعی", MONEY), ("واقعی + تعهد تجمعی", MONEY),
        ("انحراف تجمعی", MONEY), ("وضعیت دوره", TEXT),
    ], no_total={9, 10, 11, 12}, note="انحراف = بودجه − واقعی − تعهد (مثبت یعنی زیر بودجه). تعهد در دورهٔ تاریخ سفارش و واقعی در دورهٔ تاریخ فاکتور.")
    for s in scope:
        cum_b = cum_u = c.ZERO
        for p in s.periods:
            if p.date_to < f.date_from or p.date_from > f.date_to:
                continue
            amt = c.dec(s.period_amounts.get(p.period_no))
            if s.key.basis_code == "ACCOUNT":
                actual = sum((x[4] for x in gl.get(s.key.key_id, []) if p.date_from <= x[1] <= p.date_to), c.ZERO)
                commit = c.ZERO
            else:
                actual = sum((v for (k, d), v in by_period[s.key.key_id].items() if k == "ACTUAL" and p.date_from <= d <= p.date_to), c.ZERO)
                commit = sum((v for (k, d), v in by_period[s.key.key_id].items() if k == "COMMIT" and p.date_from <= d <= p.date_to), c.ZERO)
            var = amt - actual - commit
            cum_b += amt
            cum_u += actual + commit
            result.add([_name(s), lookups.key_label(s.key), p.label, p.date_from, p.date_to, amt, actual, commit, var, _ratio(var, amt),
                        cum_b, cum_u, cum_b - cum_u, "بسته" if p.is_closed else "باز"], _ref(s))
    return result


def forecast(company_id: int, f) -> ReportResult:
    scope, _l = _data(company_id, f)
    today = min(datetime.date.today(), f.date_to)
    result = ReportResult([
        ("بودجه", TEXT), ("ردیف بودجه", TEXT), ("بودجهٔ بازه", MONEY), ("واقعی", MONEY), ("تعهد باز", MONEY), ("روز گذشته", INT),
        ("روز باقی‌مانده", INT), ("پیش‌بینی پایان دوره", MONEY), ("انحراف پیش‌بینی", MONEY), ("وضعیت", TEXT),
    ], no_total={5, 6}, note="روش نرخ خطی: واقعی + تعهد باز + (واقعی ÷ روزهای گذشته) × روزهای باقی‌مانده.")
    for s in scope:
        start, end = max(f.date_from, s.budget.date_from), min(f.date_to, s.budget.date_to)
        elapsed = max(min((today - start).days + 1, (end - start).days + 1), 0)
        remaining = max((end - today).days, 0) if today >= start else (end - start).days + 1
        rate = (s.actual / elapsed) if elapsed else c.ZERO
        fc = c.money(s.actual + s.commit + rate * remaining)
        result.add([_name(s), s.label, s.budget_amount, s.actual, s.commit, elapsed, remaining, fc, s.budget_amount - fc,
                    "پیش‌بینی عبور" if fc > s.budget_amount else "در محدوده"], _ref(s))
    return result


_VIEW_STATUS = ("view", "نمایش", (("ALL", "همه"), ("UNUSED", "بدون مصرف"), ("NEAR", "نزدیک به سقف"), ("OVER", "عبورکرده"),
                                  ("PENDING", "منتظر اصلاحیه")))


def status_lists(company_id: int, f) -> ReportResult:
    view = _opt(f, "view")
    scope, _l = _data(company_id, f)
    with new_session() as session:
        pending = {v.budget_id: v for v in session.scalars(select(BudgetVersion).where(
            BudgetVersion.status_code.in_(("SUBMITTED", "REVIEWED", "APPROVED"))))}
    result = ReportResult([
        ("بودجه", TEXT), ("ردیف بودجه", TEXT), ("بودجهٔ بازه", MONEY), ("مصرف‌شده", MONEY), ("درصد مصرف", PERCENT), ("وضعیت", TEXT),
        ("نسخهٔ در جریان", TEXT),
    ], no_total={4})
    wanted = {"UNUSED": "بدون مصرف", "NEAR": "نزدیک به سقف", "OVER": "عبور از بودجه"}
    for s in scope:
        pv = pending.get(s.budget.budget_id)
        if view == "PENDING" and pv is None:
            continue
        if view in wanted and s.state != wanted[view]:
            continue
        result.add([_name(s), s.label, s.budget_amount, s.consumed, _ratio(s.consumed, s.budget_amount), s.state,
                    f"{c.KIND_LABELS[pv.kind_code]} {pv.version_no} — {c.VERSION_STATUS_LABELS[pv.status_code]}" if pv else ""], _ref(s))
    return result


_DIM_OPT = ("dimension", "تفکیک", (("ACCOUNT", "حساب"), ("COST_CENTER", "مرکز هزینه"), ("PROJECT", "پروژه"), ("BRANCH", "شعبه"),
                                    ("DEPARTMENT", "دپارتمان"), ("CATEGORY", "گروه کالا"), ("RESPONSIBLE", "مسئول")))


def by_dimension(company_id: int, f) -> ReportResult:
    dim = _opt(f, "dimension", "COST_CENTER")
    scope, lk = _data(company_id, f)
    getters = {"ACCOUNT": lambda s: lk.accounts.get(s.key.account_id), "COST_CENTER": lambda s: lk.details.get(s.key.cost_center_detail_account_id),
               "PROJECT": lambda s: lk.details.get(s.key.project_detail_account_id), "BRANCH": lambda s: lk.branches.get(s.key.branch_id),
               "DEPARTMENT": lambda s: lk.departments.get(s.key.org_unit_id), "CATEGORY": lambda s: lk.categories.get(s.key.category_id),
               "RESPONSIBLE": lambda s: s.responsible or None}
    agg = defaultdict(lambda: [0, c.ZERO, c.ZERO, c.ZERO, c.ZERO])
    for s in scope:
        a = agg[getters[dim](s) or "— بدون این بُعد —"]
        a[0] += 1
        a[1] += s.budget_amount
        a[2] += s.actual
        a[3] += s.commit
        a[4] += s.consumed
    label = dict(_DIM_OPT[2])[dim]
    result = ReportResult([
        (label, TEXT), ("تعداد ردیف", INT), ("بودجهٔ بازه", MONEY), ("واقعی", MONEY), ("تعهد", MONEY), ("انحراف", MONEY),
        ("درصد انحراف", PERCENT), ("ماندهٔ قابل تعهد", MONEY), ("درصد مصرف", PERCENT),
    ], no_total={6, 8})
    for k, (n, b, a, cm, used) in sorted(agg.items()):
        result.add([k, n, b, a, cm, b - a - cm, _ratio(b - a - cm, b), b - used, _ratio(used, b)])
    return result


_KIND_OPT = ("kind", "نوع مصرف", (("ALL", "همه"), ("PRE", "پیش‌تعهد"), ("COMMIT", "تعهد"), ("ACTUAL", "واقعی")))
_DETAIL_VIEW = ("view", "نمایش", (("NET", "خالص هر سند"), ("ENTRIES", "همهٔ رویدادها")))


def _doc_status(session, entries) -> dict[tuple[str, int], tuple[str, str]]:
    from peecha.services.purchase_reports import _OPEN_INVOICE_STAGE  # noqa: F401 -- همان برچسب‌های وضعیت

    labels = {"DRAFT": "پیش‌نویس", "CONFIRMED": "تاییدشده", "APPROVED": "تصویب‌شده", "POSTED": "ثبت‌شده", "CANCELLED": "لغوشده",
              "CORRECTED": "اصلاح‌شده", "SUBMITTED": "ارسال‌شده", "REJECTED": "ردشده"}
    doc_ids = {e[1] for e in entries if e[0] != "PURCHASE_REQUEST"}
    pr_ids = {e[1] for e in entries if e[0] == "PURCHASE_REQUEST"}
    out = {}
    for d in session.scalars(select(CommercialDocument).where(CommercialDocument.document_id.in_(doc_ids or {0}))):
        out[(d.document_type_code, d.document_id)] = (labels.get(d.status_code, d.status_code), str(d.document_no))
    for r in session.scalars(select(PurchaseRequest).where(PurchaseRequest.request_id.in_(pr_ids or {0}))):
        out[("PURCHASE_REQUEST", r.request_id)] = (labels.get(r.status_code, r.status_code), str(r.request_no))
    return out


def detail(company_id: int, f) -> ReportResult:
    """ریز مصرف هر ردیف تا سند منبع (با وضعیت فعلی سند)؛ ردیف «حساب دفتر کل» با سند حسابداری."""
    kind, view = _opt(f, "kind"), _opt(f, "view", "NET")
    key_only = (f.options or {}).get("key")
    scope, _l = _data(company_id, f)
    if key_only:
        scope = [s for s in scope if s.key.key_id == key_only]
    keys = {s.key.key_id: s for s in scope}
    result = ReportResult([
        ("بودجه", TEXT), ("ردیف بودجه", TEXT), ("تاریخ دوره", DATE), ("نوع", TEXT), ("رویداد", TEXT), ("سند منبع", TEXT), ("شماره", TEXT),
        ("وضعیت فعلی سند", TEXT), ("مبلغ ارز سند", MONEY), ("نرخ", TEXT), ("مبلغ (ارز پایه)", MONEY), ("کاربر", TEXT), ("زمان ثبت", DATE),
    ], no_total={8}, note="«خالص هر سند» جمع تفاوت‌های ثبت‌شدهٔ هر سند است؛ «همهٔ رویدادها» تک‌تک تفاوت‌ها را با علت نشان می‌دهد.")
    with new_session() as session:
        q = select(ConsumptionEntry).where(ConsumptionEntry.key_id.in_(list(keys) or [0]),
                                           ConsumptionEntry.period_date.between(f.date_from, f.date_to))
        if kind:
            q = q.where(ConsumptionEntry.kind_code == kind)
        if getattr(f, "currency_id", None):
            q = q.where(ConsumptionEntry.currency_id == f.currency_id)
        entries = list(session.scalars(q.order_by(ConsumptionEntry.period_date, ConsumptionEntry.entry_id)))
        status = _doc_status(session, [(e.source_type, e.source_document_id) for e in entries])
        names = c.user_names(session, [e.user_id for e in entries])
        if view == "NET":
            net = {}
            for e in entries:
                k = (e.key_id, e.kind_code, e.source_type, e.source_document_id)
                if k not in net:
                    net[k] = [e, c.ZERO, c.ZERO]
                net[k][1] += c.dec(e.amount)
                net[k][2] += c.dec(e.amount_fc)
            rows = [(e, amt, fc) for e, amt, fc in net.values() if amt or fc]
        else:
            rows = [(e, c.dec(e.amount), c.dec(e.amount_fc)) for e in entries]
        for e, amt, fc in rows:
            s = keys[e.key_id]
            st, no = status.get((e.source_type, e.source_document_id), ("حذف‌شده", str(e.source_no or "")))
            result.add([_name(s), s.label, e.period_date, c.CONSUMPTION_LABELS[e.kind_code],
                        "خالص" if view == "NET" else c.EVENT_LABELS.get(e.event_code, e.event_code),
                        c.SOURCE_LABELS.get(e.source_type, e.source_type), no, st, fc, str(e.exchange_rate.normalize()) if e.exchange_rate else "",
                        amt, "" if view == "NET" else names.get(e.user_id, ""), None if view == "NET" else e.created_at.date()],
                       (e.source_document_id, e.source_type))
        gl = _gl_lines(session, company_id, [s.key for s in scope], f.date_from, f.date_to)
    if kind in (None, "ACTUAL"):
        for key_id, lines in gl.items():
            s = keys[key_id]
            for je_id, when, no, desc, amount, st in lines:
                result.add([_name(s), s.label, when, "هزینهٔ واقعی", desc or "", "سند حسابداری", str(no), st, amount, "", amount, "", None],
                           (je_id, "JOURNAL_ENTRY"))
    return result


_RELEASE_OPT = ("view", "نمایش", (("RELEASE", "آزادسازی (لغو، بازگشت، حذف، بستن)"), ("ALL", "همهٔ کاهش‌ها")))


def releases(company_id: int, f) -> ReportResult:
    view = _opt(f, "view", "RELEASE")
    scope, _l = _data(company_id, f)
    keys = {s.key.key_id: s for s in scope}
    result = ReportResult([
        ("بودجه", TEXT), ("ردیف بودجه", TEXT), ("تاریخ", DATE), ("نوع", TEXT), ("علت", TEXT), ("سند منبع", TEXT), ("شماره", TEXT),
        ("مبلغ آزادشده", MONEY), ("کاربر", TEXT),
    ], note="مبلغی که با لغو، بازگشت به پیش‌نویس، حذف یا بستن تعهد از پیش‌تعهد/تعهد کم شده است.")
    with new_session() as session:
        q = select(ConsumptionEntry).where(ConsumptionEntry.key_id.in_(list(keys) or [0]), ConsumptionEntry.amount < 0,
                                           ConsumptionEntry.kind_code.in_(("PRE", "COMMIT")),
                                           func.date(ConsumptionEntry.created_at).between(f.date_from, f.date_to))
        if view == "RELEASE":
            q = q.where(ConsumptionEntry.event_code.in_(_RELEASE_EVENTS))
        entries = list(session.scalars(q.order_by(ConsumptionEntry.created_at)))
        names = c.user_names(session, [e.user_id for e in entries])
    for e in entries:
        s = keys[e.key_id]
        result.add([_name(s), s.label, e.created_at.date(), c.CONSUMPTION_LABELS[e.kind_code], c.EVENT_LABELS.get(e.event_code, e.event_code),
                    c.SOURCE_LABELS.get(e.source_type, e.source_type), str(e.source_no or ""), -c.dec(e.amount), names.get(e.user_id, "")],
                   (e.source_document_id, e.source_type))
    return result


_EXC_OPT = ("status", "وضعیت", (("ALL", "همه"),) + tuple(c.EXCEPTION_STATUS_LABELS.items()))


def exceptions_log(company_id: int, f) -> ReportResult:
    from peecha.services.budgeting import exceptions

    status = _opt(f, "status")
    result = ReportResult([
        ("تاریخ درخواست", DATE), ("سند", TEXT), ("ردیف بودجه", TEXT), ("نوع مجوز", TEXT), ("مبلغ تجاوز", MONEY), ("وضعیت", TEXT),
        ("درخواست‌کننده", TEXT), ("تصمیم‌گیرنده", TEXT), ("تاریخ تصمیم", DATE), ("نظر", TEXT), ("شرح", TEXT),
    ])
    for e in exceptions.list_exceptions(company_id, status):
        if not (f.date_from <= e.requested_at.date() <= f.date_to):
            continue
        result.add([e.requested_at.date(), e.source_label, e.key_label, e.level_label, e.excess_amount, e.status_label, e.requested_by,
                    e.decided_by, e.decided_at.date() if e.decided_at else None, e.decision_note or "", e.reason or ""],
                   (e.document_id, e.source_type))
    return result


_VER_OPT = ("view", "نمایش", (("VERSIONS", "نسخه‌ها"), ("LINES", "تغییر ردیف‌ها")))


def versions(company_id: int, f) -> ReportResult:
    view = _opt(f, "view", "VERSIONS")
    lookups = bud.Lookups(company_id)
    budgets = [b for b in bud.list_budgets(company_id) if not getattr(f, "budget_id", None) or b.budget_id == f.budget_id]
    if view == "LINES":
        result = ReportResult([
            ("بودجه", TEXT), ("نسخه", INT), ("نوع", TEXT), ("وضعیت", TEXT), ("ردیف بودجه", TEXT), ("مبلغ قبلی", MONEY),
            ("مبلغ پیشنهادی", MONEY), ("مبلغ مصوب", MONEY), ("تغییر", MONEY),
        ], no_total={1})
    else:
        result = ReportResult([
            ("بودجه", TEXT), ("نسخه", INT), ("نوع", TEXT), ("عنوان", TEXT), ("وضعیت", TEXT), ("جمع قبلی", MONEY), ("جمع مصوب/پیشنهادی", MONEY),
            ("تغییر", MONEY), ("تهیه‌کننده", TEXT), ("بررسی‌کننده", TEXT), ("تأییدکننده", TEXT), ("تاریخ انتشار", DATE), ("دلیل رد", TEXT),
        ], no_total={1})
    for b in budgets:
        for vs in bud.get_budget(company_id, b.budget_id).versions:
            v = bud.get_version(company_id, vs.version_id, lookups)
            if view == "LINES":
                for ln in v.lines:
                    result.add([f"{b.code} — {b.name}", v.version_no, v.kind_label, v.status_label, ln.label, ln.previous_amount,
                                ln.proposed_amount, ln.approved_amount, ln.change])
            else:
                result.add([f"{b.code} — {b.name}", v.version_no, v.kind_label, v.title, v.status_label,
                            v.total_previous if v.based_on_version_id else None, v.total_amount,
                            (v.total_amount - v.total_previous) if v.based_on_version_id else None, v.prepared_by, v.reviewed_by,
                            v.approved_by, v.published_at.date() if v.published_at else None, v.reject_reason or ""])
    return result


_OUT_OPT = ("outcome", "نتیجه", (("ALL", "همه"),) + tuple(c.OUTCOME_LABELS.items()))


def control_log(company_id: int, f) -> ReportResult:
    outcome = _opt(f, "outcome")
    lookups = bud.Lookups(company_id)
    result = ReportResult([
        ("زمان", DATE), ("سند", TEXT), ("شماره", TEXT), ("مرحله", TEXT), ("ردیف بودجه", TEXT), ("سیاست", TEXT), ("بودجه", MONEY),
        ("مصرف قبلی", MONEY), ("افزایش این سند", MONEY), ("مانده پس از سند", MONEY), ("نتیجه", TEXT), ("کاربر", TEXT), ("پیام", TEXT),
    ], no_total={6, 7, 9})
    with new_session() as session:
        q = select(ControlEvent).where(ControlEvent.company_id == company_id,
                                       func.date(ControlEvent.created_at).between(f.date_from, f.date_to))
        if outcome:
            q = q.where(ControlEvent.outcome_code == outcome)
        events = list(session.scalars(q.order_by(ControlEvent.event_id)))
        keys = {k.key_id: k for k in session.scalars(select(ControlKey).where(ControlKey.key_id.in_({e.key_id for e in events if e.key_id} or {0})))}
        names = c.user_names(session, [e.user_id for e in events])
    for e in events:
        result.add([e.created_at.date(), c.SOURCE_LABELS.get(e.source_type, e.source_type), str(e.source_no or ""),
                    c.EVENT_LABELS.get(e.stage_code, e.stage_code), lookups.key_label(keys[e.key_id]) if e.key_id in keys else "خارج از بودجه",
                    c.POLICY_LABELS.get(e.policy_code, c.UNBUDGETED_LABELS.get(e.policy_code, "")), e.budget_amount, e.consumed_before, e.delta,
                    e.available_after, c.OUTCOME_LABELS.get(e.outcome_code, e.outcome_code), names.get(e.user_id, ""), e.message or ""],
                   (e.source_document_id, e.source_type))
    return result


BUD_REPORTS: list[ReportDef] = [
    ReportDef("BUD_VS_ACTUAL", "بودجه در برابر واقعی و تعهد", budget_vs_actual, _SCOPE,
              "برای هر ردیف بودجه: بودجهٔ بازه، پیش‌تعهد، تعهد، واقعی، ماندهٔ قابل تعهد، درصد مصرف و پرداخت‌شده.", "range", _G),
    ReportDef("BUD_AVAILABLE", "ماندهٔ قابل تعهد", available, _SCOPE,
              "مانده با و بدون پیش‌تعهد درخواست‌های خرید و مجوزهای منتظر تصمیم.", "range", _G),
    ReportDef("BUD_MONTHLY", "عملکرد دوره‌ای و انحراف", periodic, _SCOPE,
              "بودجه، واقعی، تعهد و انحراف (مبلغ و درصد) هر دوره و تجمعی.", "range", _G),
    ReportDef("BUD_FORECAST", "پیش‌بینی پایان دوره", forecast, _SCOPE,
              "پیش‌بینی مصرف تا پایان بازه به روش نرخ خطی و انحراف آن از بودجه.", "range", _G),
    ReportDef("BUD_STATUS", "بی‌مصرف، نزدیک به سقف، عبورکرده و منتظر اصلاحیه", status_lists, _SCOPE,
              "ردیف‌های بودجه بر اساس وضعیت مصرف و نسخه‌های در جریان تأیید.", "range", _G, options=(_VIEW_STATUS,)),
    ReportDef("BUD_BY_DIMENSION", "بودجه به تفکیک حساب، مرکز هزینه، پروژه، شعبه و مسئول", by_dimension, _SCOPE,
              "جمع بودجه، واقعی، تعهد و انحراف به تفکیک بُعد انتخابی.", "range", _G, options=(_DIM_OPT,)),
    ReportDef("BUD_DETAIL", "ریز مصرف تا سند منبع", detail, _SCOPE + ("currency",),
              "هر عدد مصرف تا سند منبع (سفارش، فاکتور، برگشت، درخواست خرید یا سند حسابداری) با وضعیت فعلی آن؛ دوبار کلیک سند را باز می‌کند.",
              "range", _G, options=(_KIND_OPT, _DETAIL_VIEW)),
    ReportDef("BUD_RELEASES", "مبالغ آزادشده", releases, _SCOPE,
              "تعهد و پیش‌تعهد آزادشده با لغو، بازگشت به پیش‌نویس، حذف یا بستن تعهد.", "range", _G, options=(_RELEASE_OPT,)),
    ReportDef("BUD_EXCEPTIONS", "مجوزهای تجاوز از بودجه", exceptions_log, (),
              "درخواست‌های مجوز تجاوز، دورهٔ بسته و خرید خارج از بودجه با تصمیم، دلیل و تصمیم‌گیرنده.", "range", _G, options=(_EXC_OPT,)),
    ReportDef("BUD_VERSIONS", "نسخه‌ها و اصلاحیه‌ها", versions, ("budget",),
              "همهٔ نسخه‌ها (اولیه، اصلاحیه، تکمیلی) با وضعیت، تغییر مبلغ و تأییدکنندگان؛ یا تغییر تک‌تک ردیف‌ها.", "none", _G,
              options=(_VER_OPT,)),
    ReportDef("BUD_CONTROL_LOG", "ردپای کنترل بودجه روی اسناد", control_log, (),
              "هر بار اجرای کنترل روی سند: سیاست، مانده، افزایش، نتیجه و پیام.", "range", _G, options=(_OUT_OPT,)),
]
