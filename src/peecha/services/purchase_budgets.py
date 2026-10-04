"""بودجهٔ خرید -- R243.

مصرفِ هر بودجه همیشه از خودِ اسناد محاسبه می‌شود (هیچ عددی ذخیره نمی‌شود):
- واقعی = Σ مبلغِ خالصِ (بدونِ مالیات) ردیف‌هایِ فاکتورِ خریدِ ثبت‌شده − برگشت به تامین‌کننده
- تعهد  = Σ (مقدارِ سفارش − فاکتورشده) × فیِ واحدِ پایهٔ سفارش، برایِ سفارش‌هایِ خریدِ باز
- در جریان = Σ ماندهٔ سفارش‌نشدهٔ درخواست‌هایِ خریدِ تصویب‌شده × فیِ برآوردی
- مانده = بودجه − واقعی − تعهد ؛ درصدِ مصرف = (واقعی + تعهد) ÷ بودجه
ردیف در بودجه حساب می‌شود اگر تاریخِ سند در دورهٔ بودجه باشد و هر بُعدِ پرشدهٔ بودجه
(مرکزِ هزینه، پروژه، گروهِ کالا) با سند/کالا بخواند. کنترل فقط هشدار است و جلویِ ثبت را نمی‌گیرد.
"""

from __future__ import annotations

import datetime
import decimal
from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.commercial import PurchaseBudget
from peecha.services import purchase_reports as base

_ZERO = decimal.Decimal(0)
_OPEN = ("CONFIRMED", "APPROVED", "POSTED")


@dataclass
class BudgetFields:
    code: str
    name: str
    period_from: datetime.date
    period_to: datetime.date
    amount: decimal.Decimal
    cost_center_detail_account_id: int | None = None
    project_detail_account_id: int | None = None
    category_id: int | None = None
    warn_percent: decimal.Decimal = decimal.Decimal(90)
    is_active: bool = True
    note: str | None = None


def list_budgets(company_id: int, active_only: bool = False) -> list[PurchaseBudget]:
    with new_session() as session:
        rows = list(session.scalars(select(PurchaseBudget).where(PurchaseBudget.company_id == company_id)
                                    .order_by(PurchaseBudget.period_from, PurchaseBudget.code)))
    return [r for r in rows if r.is_active or not active_only]


def save_budget(company_id: int, fields: BudgetFields, budget_id: int | None = None) -> int:
    code, name = (fields.code or "").strip().upper(), (fields.name or "").strip()
    if not code or not name:
        raise ValueError("کد و نامِ بودجه الزامی است.")
    if fields.period_to < fields.period_from:
        raise ValueError("پایانِ دورهٔ بودجه نمی‌تواند پیش از شروعِ آن باشد.")
    if fields.amount is None or fields.amount < 0:
        raise ValueError("مبلغِ بودجه نامعتبر است.")
    if not (0 < fields.warn_percent <= 100):
        raise ValueError("درصدِ هشدار باید بینِ ۰ و ۱۰۰ باشد.")
    with new_session() as session:
        clash = session.scalar(select(PurchaseBudget).where(PurchaseBudget.company_id == company_id, PurchaseBudget.code == code))
        if clash is not None and clash.budget_id != budget_id:
            raise ValueError("این کدِ بودجه قبلاً تعریف شده است.")
        row = session.get(PurchaseBudget, budget_id) if budget_id else PurchaseBudget(company_id=company_id)
        if row is None or row.company_id != company_id:
            raise ValueError("بودجه نامعتبر است.")
        for name_ in ("period_from", "period_to", "amount", "cost_center_detail_account_id", "project_detail_account_id",
                      "category_id", "warn_percent", "is_active"):
            setattr(row, name_, getattr(fields, name_))
        row.code, row.name, row.note = code, name, (fields.note or None)
        session.add(row)
        session.commit()
        return row.budget_id


def delete_budget(company_id: int, budget_id: int) -> None:
    with new_session() as session:
        row = session.get(PurchaseBudget, budget_id)
        if row is None or row.company_id != company_id:
            raise ValueError("بودجه نامعتبر است.")
        session.delete(row)
        session.commit()


# --- مصرف -------------------------------------------------------------------
@dataclass
class Usage:
    budget: PurchaseBudget
    actual: decimal.Decimal = _ZERO
    commitment: decimal.Decimal = _ZERO
    pipeline: decimal.Decimal = _ZERO
    details: list = field(default_factory=list)   # (نوع، سند/درخواست، ردیف، مبلغ)

    @property
    def consumed(self) -> decimal.Decimal:
        return self.actual + self.commitment

    @property
    def available(self) -> decimal.Decimal:
        return self.budget.amount - self.consumed

    @property
    def used_percent(self) -> decimal.Decimal:
        return (self.consumed * 100 / self.budget.amount) if self.budget.amount else (decimal.Decimal(100) if self.consumed else _ZERO)

    @property
    def state(self) -> str:
        if self.consumed > self.budget.amount:
            return "OVER"
        return "WARN" if self.used_percent >= self.budget.warn_percent else "OK"


STATE_LABELS = {"OK": "در محدوده", "WARN": "نزدیک به سقف", "OVER": "عبور از بودجه"}


def _matches(budget: PurchaseBudget, when: datetime.date, cost_center: int | None, project: int | None, category: int | None) -> bool:
    if not (budget.period_from <= when <= budget.period_to):
        return False
    if budget.cost_center_detail_account_id is not None and cost_center != budget.cost_center_detail_account_id:
        return False
    if budget.project_detail_account_id is not None and project != budget.project_detail_account_id:
        return False
    return budget.category_id is None or category == budget.category_id


def usages(company_id: int, budgets: list[PurchaseBudget] | None = None, with_details: bool = False) -> list[Usage]:
    from peecha.services import purchase_requests as pr_service

    budgets = list_budgets(company_id, active_only=True) if budgets is None else budgets
    out = [Usage(b) for b in budgets]
    if not out:
        return out
    ctx = base._ctx(company_id)
    lo, hi = min(b.period_from for b in budgets), max(b.period_to for b in budgets)
    f = base.PurchaseFilters(lo, hi)

    def category_of(item_id):
        item = ctx.items.get(item_id)
        return item.category_id if item else None

    def apply(kind, doc_like, ln, when, cc, pj, amount):
        for u in out:
            if _matches(u.budget, when, cc, pj, category_of(ln.item_id)):
                if kind == "ACTUAL":
                    u.actual += amount
                elif kind == "COMMITMENT":
                    u.commitment += amount
                else:
                    u.pipeline += amount
                if with_details:
                    u.details.append((kind, doc_like, ln, amount))

    for doc, ln in base._lines(company_id, ("PURCHASE_INVOICE",), ("POSTED",), f, ctx):
        apply("ACTUAL", doc, ln, doc.document_date, doc.cost_center_detail_account_id, doc.project_detail_account_id, base._net(ln))
    for doc, ln in base._lines(company_id, ("PURCHASE_RETURN",), ("POSTED",), f, ctx):
        apply("ACTUAL", doc, ln, doc.document_date, doc.cost_center_detail_account_id, doc.project_detail_account_id, -base._net(ln))
    orders = base._lines(company_id, ("PURCHASE_ORDER",), _OPEN, f, ctx)
    invoiced = base._invoiced_base_by_source_line(company_id, "PURCHASE_INVOICE", [ln.line_id for _d, ln in orders])
    for doc, ln in orders:
        remaining = ln.quantity_base - invoiced.get(ln.line_id, _ZERO)
        if remaining > 0:
            apply("COMMITMENT", doc, ln, doc.document_date, doc.cost_center_detail_account_id, doc.project_detail_account_id,
                  (remaining * base._base_price(ln)).quantize(decimal.Decimal("0.01")))
    requests = pr_service.list_requests(company_id, lo, hi, ("APPROVED",))
    for req in requests:
        _r, lines = pr_service.get_request(req.request_id, company_id)
        ordered = pr_service.ordered_quantities([ln.line_id for ln in lines])
        for ln in lines:
            remaining = ln.quantity_base - ordered.get(ln.line_id, _ZERO)
            if remaining > 0 and ln.estimated_unit_price:
                apply("PIPELINE", req, ln, req.request_date, req.cost_center_detail_account_id, req.project_detail_account_id,
                      (remaining / ln.conversion_factor * ln.estimated_unit_price).quantize(decimal.Decimal("0.01")))
    return out


def warnings_for_document(document_id: int, company_id: int) -> list[str]:
    """بودجه‌هایی که ردیف‌هایِ این سند در آن‌ها حساب می‌شود و به آستانهٔ هشدار رسیده یا عبور کرده‌اند."""
    from peecha import numerals
    from peecha.services import commercial_documents as documents_service

    doc, lines = documents_service.get_document(document_id, company_id)
    if not doc.document_type_code.startswith("PURCHASE"):
        return []
    ctx = base._ctx(company_id)
    hit = [b for b in list_budgets(company_id, active_only=True)
           if any(_matches(b, doc.document_date, doc.cost_center_detail_account_id, doc.project_detail_account_id,
                           ctx.items[ln.item_id].category_id if ln.item_id in ctx.items else None) for ln in lines)]
    out = []
    for u in usages(company_id, hit):
        if u.state != "OK":
            out.append(f"بودجهٔ «{u.budget.name}»: {numerals.format_money(u.used_percent, 1, None)}٪ مصرف شده "
                       f"(مانده {numerals.format_money(u.available, 0, None)}) -- {STATE_LABELS[u.state]}")
    return out
