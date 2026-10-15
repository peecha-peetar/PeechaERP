"""دفتر مصرف بودجه (R313): تصویر اسناد خرید، نه دفتر موازی.

برای هر ردیف سند «وضع مطلوب» از خود سند حساب می‌شود و فقط تفاوت با برچسب رویداد ثبت می‌شود:

- سفارش خرید (تاییدشده/تصویب‌شده/ثبت‌شده): تعهد = (مقدار − مقدار فاکتورهای تاییدشده یا ثبت‌شده − مقدار بسته‌شده)
  × فی خالص سفارش × نرخ ارز سفارش.
- فاکتور خرید تاییدشده/تصویب‌شده: تعهد = مبلغ خالص ردیف × نرخ ارز فاکتور (اگر از سفارش آمده، همان مقدار از تعهد سفارش
  کم شده است؛ پس اختلاف قیمت فاکتور با سفارش همان لحظهٔ تایید فاکتور سنجیده و رزرو می‌شود).
- فاکتور خرید ثبت‌شده: واقعی = مبلغ خالص ردیف (بدون مالیات) × نرخ ارز؛ فاکتور «اصلاح‌شده» صفر و اصلاحی‌اش جایگزین.
- برگشت از خرید ثبت‌شده: واقعی منفی.
- درخواست خرید تصویب‌شده: پیش‌تعهد = ماندهٔ سفارش‌نشده (سفارش‌های غیر پیش‌نویس) × فی برآوردی (ارز پایه).

هر مقدار فقط در یک جا شمرده می‌شود: پیش‌تعهد ← تعهد سفارش ← تعهد فاکتور ← واقعی.
هر ردیف سند در هر بودجه فقط به یک کلید می‌خورد: دقیق‌ترین ردیف منطبق نسخهٔ منتشرشده (و در بازهٔ اعتبار آن).
رسید انبار و پرداخت هیچ اثری بر مصرف ندارند (پرداخت فقط شاخص نقدینگی است).
"""

from __future__ import annotations

import datetime
import decimal
from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import func, select, text

from peecha.db.models.budgeting import (
    Budget, BudgetLine, BudgetVersion, CommitmentClosure, ConsumptionEntry, ControlKey,
)
from peecha.db.models.commercial import CommercialDocument, CommercialDocumentLine, PurchaseRequest, PurchaseRequestLine
from peecha.db.models.inventory import Item
from peecha.services.budgeting import budgets as bud
from peecha.services.budgeting import common as c

DOC_TYPES = ("PURCHASE_ORDER", "PURCHASE_INVOICE", "PURCHASE_RETURN")
PR = "PURCHASE_REQUEST"
_COMMIT_STATUSES = ("CONFIRMED", "APPROVED", "POSTED")


@dataclass
class Facts:
    when: datetime.date
    cost_center: int | None
    project: int | None
    branch: int | None
    org_unit: int | None
    category: int | None
    purchase_type: int | None


@dataclass
class PlanBudget:
    budget_id: int
    date_from: datetime.date
    date_to: datetime.date
    keys: list = field(default_factory=list)  # (key, line)


class Plan:
    """نسخه‌های منتشرشدهٔ بودجه‌های فعال شرکت (فقط ردیف‌های «خرید و تعهد» در تطبیق اسناد خرید)."""

    def __init__(self, session, company_id: int) -> None:
        self.budgets: list[PlanBudget] = []
        rows = session.execute(
            select(Budget, BudgetVersion).join(BudgetVersion, BudgetVersion.budget_id == Budget.budget_id)
            .where(Budget.company_id == company_id, Budget.is_active.is_(True), BudgetVersion.status_code == "PUBLISHED")).all()
        for b, v in rows:
            pb = PlanBudget(b.budget_id, max(b.date_from, v.valid_from), min(b.date_to, v.valid_to))
            for line, key in session.execute(select(BudgetLine, ControlKey).join(ControlKey, ControlKey.key_id == BudgetLine.key_id)
                                             .where(BudgetLine.version_id == v.version_id, ControlKey.basis_code == "PURCHASE")):
                pb.keys.append((key, line))
            self.budgets.append(pb)

    def covers(self, when: datetime.date) -> bool:
        return any(b.date_from <= when <= b.date_to and b.keys for b in self.budgets)

    def match(self, f: Facts) -> list[tuple[int, int]]:
        out = []
        for b in self.budgets:
            if not (b.date_from <= f.when <= b.date_to):
                continue
            best, best_score = None, -1
            for key, _line in b.keys:
                if ((key.cost_center_detail_account_id and key.cost_center_detail_account_id != f.cost_center)
                        or (key.project_detail_account_id and key.project_detail_account_id != f.project)
                        or (key.branch_id and key.branch_id != f.branch) or (key.org_unit_id and key.org_unit_id != f.org_unit)
                        or (key.category_id and key.category_id != f.category)
                        or (key.purchase_type_id and key.purchase_type_id != f.purchase_type)):
                    continue
                score = bud.specificity(key)
                if score > best_score:
                    best, best_score = key, score
            if best is not None:
                out.append((b.budget_id, best.key_id))
        return out


@dataclass
class Target:
    budget_id: int
    key_id: int
    kind: str
    source_type: str
    document_id: int
    line_id: int
    source_no: int | None
    period_date: datetime.date
    amount: decimal.Decimal
    amount_fc: decimal.Decimal
    currency_id: int | None
    rate: decimal.Decimal


@dataclass
class Delta(Target):
    pass


@dataclass
class Result:
    deltas: list = field(default_factory=list)
    unbudgeted: list = field(default_factory=list)  # (source_type, document_id, source_no, line_id, amount, period_date)


def _net(ln: CommercialDocumentLine) -> decimal.Decimal:
    return c.money(ln.quantity * ln.unit_price - (ln.discount_amount or c.ZERO))


def _rate(doc) -> decimal.Decimal:
    return c.dec(doc.exchange_rate or 1)


def _categories(session, item_ids) -> dict[int, int | None]:
    ids = {i for i in item_ids if i}
    if not ids:
        return {}
    return dict(session.execute(select(Item.item_id, Item.category_id).where(Item.item_id.in_(ids))).all())


_INVOICED_STATUSES = ("CONFIRMED", "APPROVED", "POSTED", "CORRECTED")


def _invoiced(session, po_line_ids) -> dict[int, decimal.Decimal]:
    """مقدار پایهٔ فاکتورهای تاییدشده/ثبت‌شده (بدون اصلاحی‌ها) برای هر ردیف سفارش."""
    if not po_line_ids:
        return {}
    rows = session.execute(
        select(CommercialDocumentLine.source_line_id, func.sum(CommercialDocumentLine.quantity_base))
        .join(CommercialDocument, CommercialDocument.document_id == CommercialDocumentLine.document_id)
        .where(CommercialDocumentLine.source_line_id.in_(po_line_ids), CommercialDocument.document_type_code == "PURCHASE_INVOICE",
               CommercialDocument.status_code.in_(_INVOICED_STATUSES), CommercialDocument.corrects_document_id.is_(None))
        .group_by(CommercialDocumentLine.source_line_id)).all()
    return {k: c.dec(v) for k, v in rows}


def closed_quantities(session, po_line_ids) -> dict[int, decimal.Decimal]:
    if not po_line_ids:
        return {}
    rows = session.execute(select(CommercialDocumentLine.line_id, func.sum(CommitmentClosure.closed_qty_base))
                           .join(CommitmentClosure, CommitmentClosure.line_id == CommercialDocumentLine.line_id)
                           .where(CommercialDocumentLine.line_id.in_(po_line_ids), CommitmentClosure.reopened_at.is_(None))
                           .group_by(CommercialDocumentLine.line_id)).all()
    return {k: c.dec(v) for k, v in rows}


def po_open_quantities(session, lines) -> dict[int, decimal.Decimal]:
    ids = [ln.line_id for ln in lines]
    invoiced, closed = _invoiced(session, ids), closed_quantities(session, ids)
    return {ln.line_id: max(c.dec(ln.quantity_base) - invoiced.get(ln.line_id, c.ZERO) - closed.get(ln.line_id, c.ZERO), c.ZERO)
            for ln in lines}


def _doc_targets(session, plan: Plan, doc: CommercialDocument, lines, result: Result, status: str | None = None) -> list[Target]:
    t, status = doc.document_type_code, status or doc.status_code
    out: list[Target] = []
    rate = _rate(doc)
    rows: list[tuple] = []  # (kind، ردیف، مبلغ ارز سند)
    if t == "PURCHASE_ORDER" and status in _COMMIT_STATUSES:
        open_qty = po_open_quantities(session, lines)
        for ln in lines:
            if ln.quantity_base and open_qty[ln.line_id] > 0:
                rows.append(("COMMIT", ln, c.money(_net(ln) * open_qty[ln.line_id] / c.dec(ln.quantity_base))))
    elif t == "PURCHASE_INVOICE":
        if status == "POSTED":
            rows = [("ACTUAL", ln, _net(ln)) for ln in lines]
        elif status in ("CONFIRMED", "APPROVED") and doc.corrects_document_id is None:
            rows = [("COMMIT", ln, _net(ln)) for ln in lines]
    elif t == "PURCHASE_RETURN" and status == "POSTED":
        rows = [("ACTUAL", ln, -_net(ln)) for ln in lines]
    cats = _categories(session, [ln.item_id for _k, ln, _a in rows])
    for kind, ln, fc in rows:
        if fc == 0:
            continue
        facts = Facts(doc.document_date, doc.cost_center_detail_account_id, doc.project_detail_account_id, doc.branch_id,
                      doc.org_unit_id, cats.get(ln.item_id), doc.purchase_type_id)
        base = c.money(fc * rate)
        hits = plan.match(facts)
        if not hits and fc > 0 and plan.covers(doc.document_date):
            result.unbudgeted.append((t, doc.document_id, doc.document_no, ln.line_id, base, doc.document_date))
        for budget_id, key_id in hits:
            out.append(Target(budget_id, key_id, kind, t, doc.document_id, ln.line_id, doc.document_no, doc.document_date,
                              base, fc, doc.currency_id, rate))
    return out


def _pr_targets(session, plan: Plan, req: PurchaseRequest, lines, result: Result) -> list[Target]:
    from peecha.services import purchase_requests as pr_service

    if req.status_code != "APPROVED":
        return []
    ordered = pr_service._ordered_by_line(session, [ln.line_id for ln in lines], include_drafts=False)
    cats = _categories(session, [ln.item_id for ln in lines])
    out = []
    for ln in lines:
        remaining = c.dec(ln.quantity_base) - c.dec(ordered.get(ln.line_id))
        if remaining <= 0 or not ln.estimated_unit_price:
            continue
        amount = c.money(remaining / c.dec(ln.conversion_factor or 1) * c.dec(ln.estimated_unit_price))
        facts = Facts(req.request_date, req.cost_center_detail_account_id, req.project_detail_account_id, req.branch_id,
                      req.org_unit_id, cats.get(ln.item_id), req.purchase_type_id)
        hits = plan.match(facts)
        if not hits and plan.covers(req.request_date):
            result.unbudgeted.append((PR, req.request_id, req.request_no, ln.line_id, amount, req.request_date))
        for budget_id, key_id in hits:
            out.append(Target(budget_id, key_id, "PRE", PR, req.request_id, ln.line_id, req.request_no, req.request_date,
                              amount, amount, None, decimal.Decimal(1)))
    return out


def lock_sources(session, sources) -> None:
    """دو تراکنش هم‌زمان روی یک سند تفاوت را دو بار ثبت نمی‌کنند."""
    for stype, sid in sorted(sources):
        session.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"bud:{stype}:{sid}"})


def compute(session, company_id: int, sources: set[tuple[str, int]], plan: Plan | None = None,
            deleted: set[tuple[str, int]] = frozenset(), assume: dict[int, str] | None = None) -> Result:
    """تفاوت «وضع مطلوب» اسناد با دفتر مصرف (بدون نوشتن). assume: وضعیت فرضی سند برای پیش‌بررسی ثبت نهایی."""
    assume = assume or {}
    plan = plan or Plan(session, company_id)
    result = Result()
    targets: list[Target] = []
    doc_ids = [sid for stype, sid in sources if stype in DOC_TYPES and (stype, sid) not in deleted]
    pr_ids = [sid for stype, sid in sources if stype == PR and (stype, sid) not in deleted]
    if doc_ids:
        docs = {d.document_id: d for d in session.scalars(select(CommercialDocument).where(
            CommercialDocument.document_id.in_(doc_ids), CommercialDocument.company_id == company_id))}
        lines = defaultdict(list)
        for ln in session.scalars(select(CommercialDocumentLine).where(CommercialDocumentLine.document_id.in_(list(docs) or [0]))
                                  .order_by(CommercialDocumentLine.line_no)):
            lines[ln.document_id].append(ln)
        for did, doc in docs.items():
            if doc.document_type_code in DOC_TYPES:
                targets += _doc_targets(session, plan, doc, lines[did], result, assume.get(did))
    if pr_ids:
        reqs = {r.request_id: r for r in session.scalars(select(PurchaseRequest).where(
            PurchaseRequest.request_id.in_(pr_ids), PurchaseRequest.company_id == company_id))}
        lines = defaultdict(list)
        for ln in session.scalars(select(PurchaseRequestLine).where(PurchaseRequestLine.request_id.in_(list(reqs) or [0]))):
            lines[ln.request_id].append(ln)
        for rid, req in reqs.items():
            targets += _pr_targets(session, plan, req, lines[rid], result)

    want: dict[tuple, list] = defaultdict(lambda: [c.ZERO, c.ZERO, None])
    meta: dict[tuple, Target] = {}
    for t in targets:
        k = (t.budget_id, t.key_id, t.kind, t.source_type, t.document_id, t.line_id, t.period_date)
        want[k][0] += t.amount
        want[k][1] += t.amount_fc
        meta[k] = t
    have: dict[tuple, list] = {}
    by_type = defaultdict(list)
    for stype, sid in sources:
        by_type[stype].append(sid)
    for stype, ids in by_type.items():
        for row in session.execute(
                select(ConsumptionEntry.budget_id, ConsumptionEntry.key_id, ConsumptionEntry.kind_code, ConsumptionEntry.source_type,
                       ConsumptionEntry.source_document_id, ConsumptionEntry.source_line_id, ConsumptionEntry.period_date,
                       func.sum(ConsumptionEntry.amount), func.coalesce(func.sum(ConsumptionEntry.amount_fc), 0),
                       func.max(ConsumptionEntry.source_no), func.max(ConsumptionEntry.currency_id),
                       func.max(ConsumptionEntry.exchange_rate))
                .where(ConsumptionEntry.company_id == company_id, ConsumptionEntry.source_type == stype,
                       ConsumptionEntry.source_document_id.in_(ids))
                .group_by(ConsumptionEntry.budget_id, ConsumptionEntry.key_id, ConsumptionEntry.kind_code, ConsumptionEntry.source_type,
                          ConsumptionEntry.source_document_id, ConsumptionEntry.source_line_id, ConsumptionEntry.period_date)).all():
            have[tuple(row[:7])] = [c.dec(row[7]), c.dec(row[8]), row[9], row[10], row[11]]
    for k in set(want) | set(have):
        w_amt, w_fc = want[k][0] if k in want else c.ZERO, want[k][1] if k in want else c.ZERO
        h = have.get(k, [c.ZERO, c.ZERO, None, None, None])
        d_amt, d_fc = w_amt - h[0], w_fc - h[1]
        if d_amt == 0 and d_fc == 0:
            continue
        m = meta.get(k)
        budget_id, key_id, kind, stype, did, lid, pdate = k
        result.deltas.append(Delta(budget_id, key_id, kind, stype, did, lid, m.source_no if m else h[2], pdate, d_amt, d_fc,
                                   m.currency_id if m else h[3], m.rate if m else c.dec(h[4] or 1)))
    return result


def write(session, company_id: int, deltas: list[Delta], event: str, user_id: int | None, note: str | None = None) -> None:
    for d in deltas:
        session.add(ConsumptionEntry(
            company_id=company_id, budget_id=d.budget_id, key_id=d.key_id, kind_code=d.kind, source_type=d.source_type,
            source_document_id=d.document_id, source_line_id=d.line_id, source_no=d.source_no, period_date=d.period_date,
            amount=d.amount, amount_fc=d.amount_fc, currency_id=d.currency_id, exchange_rate=d.rate, event_code=event,
            note=note, user_id=user_id))
    session.flush()


def has_budgets(session, company_id: int) -> bool:
    return session.scalar(select(Budget.budget_id).where(Budget.company_id == company_id).limit(1)) is not None


def sync(session, company_id: int, sources: set[tuple[str, int]], event: str, user_id: int | None,
         deleted: set[tuple[str, int]] = frozenset()) -> Result:
    """بدون کنترل سیاست (رویدادهای آزادکننده، انتشار نسخه، تطبیق دوباره)."""
    if not sources or not has_budgets(session, company_id):
        return Result()
    lock_sources(session, sources)
    result = compute(session, company_id, sources, deleted=deleted)
    write(session, company_id, result.deltas, event, user_id)
    return result


# --- مجموعهٔ اسناد مرتبط -------------------------------------------------------------------------------------
def related_sources(session, doc: CommercialDocument) -> set[tuple[str, int]]:
    """سند + سفارش‌های مبدأ ردیف‌های فاکتور + درخواست‌های خرید ردیف‌های سفارش + فاکتور اصلی یک اصلاحیه."""
    out = {(doc.document_type_code, doc.document_id)}
    lines = list(session.scalars(select(CommercialDocumentLine).where(CommercialDocumentLine.document_id == doc.document_id)))
    src_ids = [ln.source_line_id for ln in lines if ln.source_line_id]
    if src_ids:
        for did, t in session.execute(select(CommercialDocument.document_id, CommercialDocument.document_type_code)
                                      .join(CommercialDocumentLine, CommercialDocumentLine.document_id == CommercialDocument.document_id)
                                      .where(CommercialDocumentLine.line_id.in_(src_ids))).all():
            if t in DOC_TYPES:
                out.add((t, did))
    pr_line_ids = [ln.purchase_request_line_id for ln in lines if ln.purchase_request_line_id]
    if pr_line_ids:
        for rid in session.scalars(select(PurchaseRequestLine.request_id).where(PurchaseRequestLine.line_id.in_(pr_line_ids))):
            out.add((PR, rid))
    if doc.corrects_document_id:
        original = session.get(CommercialDocument, doc.corrects_document_id)
        if original is not None:
            out |= related_sources(session, original)
    return out


# --- تطبیق کامل ----------------------------------------------------------------------------------------------
def all_sources(session, company_id: int) -> set[tuple[str, int]]:
    out = set()
    for did, t in session.execute(select(CommercialDocument.document_id, CommercialDocument.document_type_code).where(
            CommercialDocument.company_id == company_id, CommercialDocument.document_type_code.in_(DOC_TYPES),
            CommercialDocument.status_code.notin_(("DRAFT", "CANCELLED")))).all():
        out.add((t, did))
    for rid in session.scalars(select(PurchaseRequest.request_id).where(PurchaseRequest.company_id == company_id,
                                                                         PurchaseRequest.status_code == "APPROVED")):
        out.add((PR, rid))
    for t, did in session.execute(select(ConsumptionEntry.source_type, ConsumptionEntry.source_document_id)
                                  .where(ConsumptionEntry.company_id == company_id).distinct()).all():
        out.add((t, did))
    return out


def resync_in_session(session, company_id: int, event: str, user_id: int | None) -> int:
    """همهٔ اسناد با نسخه‌های منتشرشدهٔ فعلی تطبیق داده می‌شوند؛ اختلاف با برچسب رویداد ثبت می‌شود."""
    if not has_budgets(session, company_id):
        return 0
    plan = Plan(session, company_id)
    existing_ids = set(session.scalars(select(CommercialDocument.document_id).where(
        CommercialDocument.company_id == company_id, CommercialDocument.document_type_code.in_(DOC_TYPES))))
    sources = all_sources(session, company_id)
    deleted = {(t, i) for t, i in sources if t in DOC_TYPES and i not in existing_ids}
    count = 0
    ordered = sorted(sources)
    for i in range(0, len(ordered), 200):
        chunk = set(ordered[i:i + 200])
        lock_sources(session, chunk)
        result = compute(session, company_id, chunk, plan, deleted)
        write(session, company_id, result.deltas, event, user_id)
        count += len(result.deltas)
    return count


def resync(company_id: int, user_id: int) -> int:
    from peecha.db.base import new_session

    c.require(company_id, user_id, c.FORM_PUBLISH)
    with new_session() as session:
        n = resync_in_session(session, company_id, "RESYNC", user_id)
        c.audit(session, company_id, user_id, c.ENTITY_BUDGET, 0, "RESYNC", {"entries": n})
        session.commit()
        return n


# --- مانده‌ها ------------------------------------------------------------------------------------------------
def key_totals(session, key_ids, date_to: datetime.date | None = None, date_from: datetime.date | None = None) -> dict[int, dict[str, decimal.Decimal]]:
    """جمع مصرف هر کلید به تفکیک نوع؛ date_to برای کنترل «تجمعی تا پایان دوره»."""
    out: dict[int, dict[str, decimal.Decimal]] = defaultdict(lambda: {"PRE": c.ZERO, "COMMIT": c.ZERO, "ACTUAL": c.ZERO})
    if not key_ids:
        return out
    q = (select(ConsumptionEntry.key_id, ConsumptionEntry.kind_code, func.sum(ConsumptionEntry.amount))
         .where(ConsumptionEntry.key_id.in_(list(key_ids))).group_by(ConsumptionEntry.key_id, ConsumptionEntry.kind_code))
    if date_to is not None:
        q = q.where(ConsumptionEntry.period_date <= date_to)
    if date_from is not None:
        q = q.where(ConsumptionEntry.period_date >= date_from)
    for key_id, kind, amount in session.execute(q).all():
        out[key_id][kind] = c.dec(amount)
    return out
