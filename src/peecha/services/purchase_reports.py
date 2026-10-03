"""گزارشاتِ تدارکات (خرید) -- R233، فاز ۱.

هر گزارش یک تابع است با ورودیِ (company_id, PurchaseFilters) و خروجیِ
ReportResult (ستون‌ها با نوعِ داده، ردیف‌هایِ خام، ارجاعِ سند برایِ بازکردن).
قالب‌بندیِ عدد/تاریخ در لایهٔ UI انجام می‌شود.

قراردادها:
- فاکتورِ مؤثر = PURCHASE_INVOICEِ POSTED (اصلاح‌شده‌ها CORRECTED هستند و جایگزینشان POSTED است).
- مبلغِ ردیف = مقدار × فی − تخفیف (بدونِ مالیات)؛ مقدارها به واحدِ پایهٔ کالا.
- مانده‌هایِ حساب از دفترِ کل (حسابِ «پرداختنیِ تامین‌کنندگان» + تفصیلیِ شخص).
"""

from __future__ import annotations

import datetime
import decimal
from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.accounting import (
    DetailAccount, JournalEntry, JournalEntryLine, JournalEntryLineDetail, JournalEntryStatus,
)
from peecha.db.models.commercial import CommercialDocument, CommercialDocumentLine, InvoiceSettlement
from peecha.db.models.inventory import Item, Warehouse
from peecha.services import commercial_documents as documents_service
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import inventory_catalog as catalog_service
from peecha.services import inventory_engine as engine_service

_ZERO = decimal.Decimal(0)

# نوعِ ستون: text | date | money | qty | int | percent | days
TEXT, DATE, MONEY, QTY, INT, PERCENT, DAYS = "text", "date", "money", "qty", "int", "percent", "days"
_SUMMABLE = (MONEY, QTY, INT)

_STAGE_LABELS = {"DRAFT": "پیش‌نویس", "CONFIRMED": "تاییدشده", "APPROVED": "تصویب‌شده", "POSTED": "ثبتِ نهایی"}
_OPEN_INVOICE_STAGE = {
    "DRAFT": "پیش‌نویس -- در انتظارِ تاییدِ کاربر",
    "CONFIRMED": "تاییدشده -- در انتظارِ تصویب/ثبتِ نهایی",
    "APPROVED": "تصویب‌شده -- در انتظارِ ثبتِ نهایی",
}


@dataclass
class PurchaseFilters:
    date_from: datetime.date
    date_to: datetime.date
    supplier_id: int | None = None
    item_id: int | None = None
    category_id: int | None = None
    warehouse_id: int | None = None


@dataclass
class ReportResult:
    columns: list[tuple[str, str]]
    rows: list[list] = field(default_factory=list)
    # (document_id, document_type_code) برایِ بازکردنِ سند با دابل‌کلیک
    refs: list[tuple[int, str] | None] = field(default_factory=list)
    # ستون‌هایی که جمعِ کل نمی‌خورند (مثلاً فی یا درصد)، جدا از نوعشان
    no_total: set[int] = field(default_factory=set)
    note: str = ""

    def add(self, row: list, ref: tuple[int, str] | None = None) -> None:
        self.rows.append(row)
        self.refs.append(ref)

    def footer(self) -> list | None:
        if not self.rows:
            return None
        out: list = []
        for index, (_header, kind) in enumerate(self.columns):
            if kind in _SUMMABLE and index not in self.no_total:
                out.append(sum((r[index] or 0 for r in self.rows), _ZERO if kind != INT else 0))
            else:
                out.append("")
        out[0] = "جمعِ کل"
        return out


# ---------------------------------------------------------------------
# داده‌هایِ پایهٔ مشترک
# ---------------------------------------------------------------------
@dataclass
class _Ctx:
    items: dict[int, catalog_service.ItemRow]
    uom_names: dict[int, str]
    names: dict[int, str]
    warehouses: dict[int, str]

    def item_label(self, item_id: int) -> str:
        item = self.items.get(item_id)
        return f"{item.code} — {item.name or ''}" if item else str(item_id)

    def base_uom(self, item_id: int) -> str:
        item = self.items.get(item_id)
        return self.uom_names.get(item.base_uom_id, "") if item else ""


def _ctx(company_id: int) -> _Ctx:
    items = {i.item_id: i for i in catalog_service.list_items(company_id)}
    uom_names = {u.uom_id: u.name or u.code for u in catalog_service.list_uoms(company_id)}
    with new_session() as session:
        names = {
            detail_id: f"{code} — {name or ''}"
            for detail_id, code, name in session.execute(
                select(DetailAccount.detail_account_id, DetailAccount.code, DetailAccount.name)
                .where(DetailAccount.company_id == company_id)
            )
        }
        warehouses = {w.warehouse_id: w.name for w in session.scalars(select(Warehouse).where(Warehouse.company_id == company_id))}
    return _Ctx(items, uom_names, names, warehouses)


def _line_matches(ctx: _Ctx, f: PurchaseFilters, doc: CommercialDocument, ln: CommercialDocumentLine) -> bool:
    if f.supplier_id is not None and doc.counterparty_detail_account_id != f.supplier_id:
        return False
    if f.item_id is not None and ln.item_id != f.item_id:
        return False
    if f.category_id is not None:
        item = ctx.items.get(ln.item_id)
        if item is None or item.category_id != f.category_id:
            return False
    if f.warehouse_id is not None and (ln.warehouse_id or doc.warehouse_id) != f.warehouse_id:
        return False
    return True


def _lines(company_id: int, types: tuple[str, ...], statuses: tuple[str, ...], f: PurchaseFilters | None,
           ctx: _Ctx, dated: bool = True) -> list[tuple[CommercialDocument, CommercialDocumentLine]]:
    with new_session() as session:
        stmt = (
            select(CommercialDocument, CommercialDocumentLine)
            .join(CommercialDocumentLine, CommercialDocumentLine.document_id == CommercialDocument.document_id)
            .where(
                CommercialDocument.company_id == company_id,
                CommercialDocument.document_type_code.in_(types),
                CommercialDocument.status_code.in_(statuses),
            )
            .order_by(CommercialDocument.document_date, CommercialDocument.document_id, CommercialDocumentLine.line_no)
        )
        if dated and f is not None:
            stmt = stmt.where(CommercialDocument.document_date.between(f.date_from, f.date_to))
        rows = list(session.execute(stmt).all())
    return [(d, ln) for d, ln in rows if f is None or _line_matches(ctx, f, d, ln)]


def _net(ln: CommercialDocumentLine) -> decimal.Decimal:
    return (ln.quantity * ln.unit_price - (ln.discount_amount or _ZERO)).quantize(decimal.Decimal("0.01"))


def _base_price(ln: CommercialDocumentLine) -> decimal.Decimal:
    return _net(ln) / ln.quantity_base if ln.quantity_base else _ZERO


def _invoiced_base_by_source_line(company_id: int, source_line_ids: list[int]) -> dict[int, decimal.Decimal]:
    if not source_line_ids:
        return {}
    with new_session() as session:
        rows = session.execute(
            select(CommercialDocumentLine.source_line_id, CommercialDocumentLine.quantity_base)
            .join(CommercialDocument, CommercialDocument.document_id == CommercialDocumentLine.document_id)
            .where(
                CommercialDocumentLine.source_line_id.in_(source_line_ids),
                CommercialDocument.document_type_code == "PURCHASE_INVOICE",
                CommercialDocument.status_code != "CANCELLED",
                CommercialDocument.corrects_document_id.is_(None),
            )
        ).all()
    out: dict[int, decimal.Decimal] = defaultdict(lambda: _ZERO)
    for source_line_id, qty in rows:
        out[source_line_id] += qty
    return out


def _received_base(doc: CommercialDocument, ln: CommercialDocumentLine) -> decimal.Decimal | None:
    """مقدارِ رسیدشده (پایه) طبقِ تاییدِ انباردار؛ None یعنی سفارش هنوز رسید نخورده."""
    if doc.warehouse_approved_at is None:
        return None
    delivered = ln.warehouse_delivered_quantity if ln.warehouse_delivered_quantity is not None else ln.quantity
    return delivered * (ln.conversion_factor or 1)


def _days(since: datetime.date | datetime.datetime | None) -> int:
    if since is None:
        return 0
    if isinstance(since, datetime.datetime):
        since = since.date()
    return (datetime.date.today() - since).days


# ---------------------------------------------------------------------
# ۱) سفارش‌هایِ خریدِ باز
# ---------------------------------------------------------------------
def open_purchase_orders(company_id: int, f: PurchaseFilters) -> ReportResult:
    ctx = _ctx(company_id)
    pairs = _lines(company_id, ("PURCHASE_ORDER",), ("CONFIRMED", "APPROVED", "POSTED"), f, ctx)
    invoiced = _invoiced_base_by_source_line(company_id, [ln.line_id for _d, ln in pairs])
    result = ReportResult([
        ("شمارهٔ سفارش", INT), ("تاریخ", DATE), ("تامین‌کننده", TEXT), ("وضعیت", TEXT), ("کالا", TEXT), ("واحد", TEXT),
        ("مقدارِ سفارش", QTY), ("رسیده", QTY), ("فاکتورشده", QTY), ("مانده", QTY), ("فیِ واحدِ پایه", MONEY),
        ("ارزشِ مانده", MONEY), ("روزِ باز", DAYS),
    ], no_total={0, 10})
    for doc, ln in pairs:
        received = _received_base(doc, ln)
        billed = invoiced.get(ln.line_id, _ZERO)
        remaining = ln.quantity_base - billed
        if remaining <= 0:
            continue
        price = _base_price(ln)
        result.add([
            doc.document_no, doc.document_date, ctx.names.get(doc.counterparty_detail_account_id, ""),
            _STAGE_LABELS.get(doc.status_code, doc.status_code)
            + ("" if received is None else " -- رسیده"),
            ctx.item_label(ln.item_id), ctx.base_uom(ln.item_id),
            ln.quantity_base, received if received is not None else _ZERO, billed, remaining, price,
            (remaining * price).quantize(decimal.Decimal("0.01")), _days(doc.document_date),
        ], (doc.document_id, doc.document_type_code))
    return result


# ---------------------------------------------------------------------
# ۳) رسیدهایِ در انتظارِ انباردار
# ---------------------------------------------------------------------
def pending_receipts(company_id: int, f: PurchaseFilters) -> ReportResult:
    ctx = _ctx(company_id)
    result = ReportResult([
        ("نوع", TEXT), ("شماره", INT), ("تاریخ", DATE), ("تامین‌کننده", TEXT), ("انبار", TEXT),
        ("تعدادِ ردیف", INT), ("مقدارِ کل (پایه)", QTY), ("روزِ انتظار", DAYS),
    ], no_total={1})
    titles = {"PURCHASE_ORDER": "سفارشِ خرید", "CONSIGNMENT_IN": "امانیِ ورودی"}
    for doc in documents_service.list_purchase_order_goods_receipt_queue(company_id):
        if doc.document_type_code not in titles or doc.warehouse_approved_at is not None:
            continue
        if f.supplier_id is not None and doc.counterparty_detail_account_id != f.supplier_id:
            continue
        _doc, lines = documents_service.get_document(doc.document_id, company_id)
        lines = [ln for ln in lines if _line_matches(ctx, PurchaseFilters(f.date_from, f.date_to, None, f.item_id, f.category_id, f.warehouse_id), doc, ln)]
        if not lines:
            continue
        result.add([
            titles[doc.document_type_code], doc.document_no, doc.document_date,
            ctx.names.get(doc.counterparty_detail_account_id, ""), ctx.warehouses.get(doc.warehouse_id, "") if doc.warehouse_id else "",
            len(lines), sum((ln.quantity_base for ln in lines), _ZERO), _days(doc.posted_at or doc.document_date),
        ], (doc.document_id, doc.document_type_code))
    return result


# ---------------------------------------------------------------------
# ۴) رسیده ولی فاکتورنشده (GR/IR)
# ---------------------------------------------------------------------
def received_not_invoiced(company_id: int, f: PurchaseFilters) -> ReportResult:
    ctx = _ctx(company_id)
    pairs = _lines(company_id, ("PURCHASE_ORDER",), ("CONFIRMED", "APPROVED", "POSTED"), f, ctx, dated=False)
    pairs = [(d, ln) for d, ln in pairs if d.warehouse_approved_at is not None and d.warehouse_approved_at.date() <= f.date_to]
    invoiced = _invoiced_base_by_source_line(company_id, [ln.line_id for _d, ln in pairs])
    result = ReportResult([
        ("شمارهٔ سفارش", INT), ("تاریخِ رسید", DATE), ("تامین‌کننده", TEXT), ("کالا", TEXT), ("واحد", TEXT),
        ("رسیده", QTY), ("فاکتورشده", QTY), ("فاکتورنشده", QTY), ("فیِ سفارش (پایه)", MONEY), ("ارزشِ فاکتورنشده", MONEY),
        ("روز از رسید", DAYS),
    ], no_total={0, 8},
        note="بدهیِ شناسایی‌نشده: کالایی که انبار تحویل گرفته ولی فاکتورِ خریدش هنوز صادر نشده است.")
    for doc, ln in pairs:
        received = _received_base(doc, ln) or _ZERO
        billed = invoiced.get(ln.line_id, _ZERO)
        open_qty = received - billed
        if open_qty <= 0:
            continue
        price = _base_price(ln)
        result.add([
            doc.document_no, doc.warehouse_approved_at.date(), ctx.names.get(doc.counterparty_detail_account_id, ""),
            ctx.item_label(ln.item_id), ctx.base_uom(ln.item_id), received, billed, open_qty, price,
            (open_qty * price).quantize(decimal.Decimal("0.01")), _days(doc.warehouse_approved_at),
        ], (doc.document_id, doc.document_type_code))
    return result


# ---------------------------------------------------------------------
# ۵) فاکتورهایِ خریدِ در انتظار
# ---------------------------------------------------------------------
def pending_invoices(company_id: int, f: PurchaseFilters) -> ReportResult:
    ctx = _ctx(company_id)
    titles = {"PURCHASE_INVOICE": "فاکتورِ خرید", "PURCHASE_PROFORMA": "پیش‌فاکتورِ خرید", "PURCHASE_RETURN": "برگشت به تامین‌کننده"}
    pairs = _lines(company_id, tuple(titles), ("DRAFT", "CONFIRMED", "APPROVED"), f, ctx, dated=False)
    docs: dict[int, CommercialDocument] = {}
    for doc, _ln in pairs:
        docs[doc.document_id] = doc
    result = ReportResult([
        ("نوع", TEXT), ("شماره", INT), ("تاریخ", DATE), ("تامین‌کننده", TEXT), ("مرحله", TEXT), ("مبلغِ کل", MONEY),
        ("روزِ انتظار", DAYS),
    ], no_total={1})
    for doc in sorted(docs.values(), key=lambda d: (d.document_date, d.document_id)):
        stage = _OPEN_INVOICE_STAGE.get(doc.status_code, doc.status_code)
        if doc.status_code == "CONFIRMED" and not documents_service.requires_manager_approval(company_id, doc.document_type_code):
            stage = "تاییدشده -- در انتظارِ تسویه/ثبتِ نهایی"
        result.add([
            titles[doc.document_type_code], doc.document_no, doc.document_date,
            ctx.names.get(doc.counterparty_detail_account_id, ""), stage, doc.total_amount, _days(doc.created_at),
        ], (doc.document_id, doc.document_type_code))
    return result


# ---------------------------------------------------------------------
# ۸ و ۹) خرید به تفکیکِ کالا / تامین‌کننده
# ---------------------------------------------------------------------
def _posted_purchase_and_returns(company_id: int, f: PurchaseFilters, ctx: _Ctx):
    purchases = _lines(company_id, ("PURCHASE_INVOICE",), ("POSTED",), f, ctx)
    returns = _lines(company_id, ("PURCHASE_RETURN",), ("POSTED",), f, ctx)
    return purchases, returns


def purchases_by_item(company_id: int, f: PurchaseFilters) -> ReportResult:
    ctx = _ctx(company_id)
    purchases, returns = _posted_purchase_and_returns(company_id, f, ctx)
    agg: dict[int, dict] = {}
    for doc, ln in purchases:
        a = agg.setdefault(ln.item_id, {"qty": _ZERO, "amount": _ZERO, "ret_qty": _ZERO, "ret_amount": _ZERO,
                                        "docs": set(), "suppliers": set(), "last": None, "min": None, "max": None})
        a["qty"] += ln.quantity_base
        a["amount"] += _net(ln)
        a["docs"].add(doc.document_id)
        a["suppliers"].add(doc.counterparty_detail_account_id)
        price = _base_price(ln)
        a["last"] = price
        a["min"] = price if a["min"] is None else min(a["min"], price)
        a["max"] = price if a["max"] is None else max(a["max"], price)
    for _doc, ln in returns:
        a = agg.setdefault(ln.item_id, {"qty": _ZERO, "amount": _ZERO, "ret_qty": _ZERO, "ret_amount": _ZERO,
                                        "docs": set(), "suppliers": set(), "last": None, "min": None, "max": None})
        a["ret_qty"] += ln.quantity_base
        a["ret_amount"] += _net(ln)
    result = ReportResult([
        ("کالا", TEXT), ("واحد", TEXT), ("مقدارِ خرید", QTY), ("مبلغِ خرید", MONEY), ("مقدارِ برگشتی", QTY),
        ("مبلغِ برگشتی", MONEY), ("خالصِ مقدار", QTY), ("خالصِ مبلغ", MONEY), ("میانگینِ فی", MONEY),
        ("کمترین فی", MONEY), ("بیشترین فی", MONEY), ("آخرین فی", MONEY), ("تعدادِ فاکتور", INT), ("تعدادِ تامین‌کننده", INT),
    ], no_total={8, 9, 10, 11, 13})
    for item_id, a in sorted(agg.items(), key=lambda kv: -(kv[1]["amount"] - kv[1]["ret_amount"])):
        net_qty, net_amount = a["qty"] - a["ret_qty"], a["amount"] - a["ret_amount"]
        result.add([
            ctx.item_label(item_id), ctx.base_uom(item_id), a["qty"], a["amount"], a["ret_qty"], a["ret_amount"],
            net_qty, net_amount, (a["amount"] / a["qty"]) if a["qty"] else _ZERO,
            a["min"] or _ZERO, a["max"] or _ZERO, a["last"] or _ZERO, len(a["docs"]), len(a["suppliers"]),
        ])
    return result


def purchases_by_supplier(company_id: int, f: PurchaseFilters) -> ReportResult:
    ctx = _ctx(company_id)
    purchases, returns = _posted_purchase_and_returns(company_id, f, ctx)
    agg: dict[int, dict] = defaultdict(lambda: {"docs": set(), "gross": _ZERO, "discount": _ZERO, "tax": _ZERO,
                                                "returns": _ZERO, "items": set()})
    for doc, ln in purchases:
        a = agg[doc.counterparty_detail_account_id]
        a["docs"].add(doc.document_id)
        a["gross"] += (ln.quantity * ln.unit_price).quantize(decimal.Decimal("0.01"))
        a["discount"] += ln.discount_amount or _ZERO
        a["tax"] += ln.tax_amount or _ZERO
        a["items"].add(ln.item_id)
    for doc, ln in returns:
        agg[doc.counterparty_detail_account_id]["returns"] += _net(ln) + (ln.tax_amount or _ZERO)
    total_net = sum((a["gross"] - a["discount"] + a["tax"] - a["returns"] for a in agg.values()), _ZERO)
    result = ReportResult([
        ("تامین‌کننده", TEXT), ("تعدادِ فاکتور", INT), ("تعدادِ کالا", INT), ("مبلغِ ناخالص", MONEY), ("تخفیف", MONEY),
        ("مالیات", MONEY), ("برگشتی", MONEY), ("خالصِ خرید", MONEY), ("سهم از کل", PERCENT),
    ], no_total={2})
    for supplier_id, a in sorted(agg.items(), key=lambda kv: -(kv[1]["gross"] - kv[1]["discount"])):
        net = a["gross"] - a["discount"] + a["tax"] - a["returns"]
        result.add([
            ctx.names.get(supplier_id, ""), len(a["docs"]), len(a["items"]), a["gross"], a["discount"], a["tax"],
            a["returns"], net, (net * 100 / total_net) if total_net else _ZERO,
        ])
    return result


# ---------------------------------------------------------------------
# ۱۵) تاریخچهٔ قیمتِ خرید / ۱۶) مقایسهٔ قیمتِ تامین‌کنندگان
# ---------------------------------------------------------------------
def price_history(company_id: int, f: PurchaseFilters) -> ReportResult:
    ctx = _ctx(company_id)
    purchases = _lines(company_id, ("PURCHASE_INVOICE",), ("POSTED",), f, ctx)
    result = ReportResult([
        ("تاریخ", DATE), ("شمارهٔ فاکتور", INT), ("کالا", TEXT), ("تامین‌کننده", TEXT), ("مقدار (پایه)", QTY),
        ("واحد", TEXT), ("فیِ واحدِ پایه", MONEY), ("تغییر نسبت به خریدِ قبلی", PERCENT),
    ], no_total={1, 4, 6, 7})
    last: dict[int, decimal.Decimal] = {}
    for doc, ln in purchases:
        price = _base_price(ln)
        prev = last.get(ln.item_id)
        change = ((price - prev) * 100 / prev) if prev else None
        last[ln.item_id] = price
        result.add([
            doc.document_date, doc.document_no, ctx.item_label(ln.item_id), ctx.names.get(doc.counterparty_detail_account_id, ""),
            ln.quantity_base, ctx.base_uom(ln.item_id), price, change,
        ], (doc.document_id, doc.document_type_code))
    return result


def supplier_price_comparison(company_id: int, f: PurchaseFilters) -> ReportResult:
    ctx = _ctx(company_id)
    purchases = _lines(company_id, ("PURCHASE_INVOICE",), ("POSTED",), f, ctx)
    agg: dict[tuple[int, int], dict] = {}
    for doc, ln in purchases:
        key = (ln.item_id, doc.counterparty_detail_account_id)
        a = agg.setdefault(key, {"qty": _ZERO, "amount": _ZERO, "min": None, "last": None, "last_date": None, "count": 0})
        price = _base_price(ln)
        a["qty"] += ln.quantity_base
        a["amount"] += _net(ln)
        a["min"] = price if a["min"] is None else min(a["min"], price)
        a["last"], a["last_date"] = price, doc.document_date
        a["count"] += 1
    best_last: dict[int, decimal.Decimal] = {}
    for (item_id, _s), a in agg.items():
        best_last[item_id] = min(best_last.get(item_id, a["last"]), a["last"])
    result = ReportResult([
        ("کالا", TEXT), ("تامین‌کننده", TEXT), ("آخرین فی", MONEY), ("تاریخِ آخرین خرید", DATE), ("میانگینِ فی", MONEY),
        ("کمترین فی", MONEY), ("اختلاف با ارزان‌ترین", PERCENT), ("مقدارِ خرید", QTY), ("تعدادِ خرید", INT), ("ارزان‌ترین", TEXT),
    ], no_total={2, 4, 5, 6})
    for (item_id, supplier_id), a in sorted(agg.items(), key=lambda kv: (ctx.item_label(kv[0][0]), kv[1]["last"])):
        best = best_last[item_id]
        result.add([
            ctx.item_label(item_id), ctx.names.get(supplier_id, ""), a["last"], a["last_date"],
            (a["amount"] / a["qty"]) if a["qty"] else _ZERO, a["min"], ((a["last"] - best) * 100 / best) if best else _ZERO,
            a["qty"], a["count"], "★" if a["last"] == best else "",
        ])
    return result


# ---------------------------------------------------------------------
# ۱۷) انحرافِ قیمتِ خرید (PPV)
# ---------------------------------------------------------------------
def purchase_price_variance(company_id: int, f: PurchaseFilters) -> ReportResult:
    """فیِ فاکتور در برابرِ فیِ سفارشِ مبدا؛ برایِ فاکتورِ بدونِ سفارش، در برابرِ آخرین خریدِ قبلی."""
    ctx = _ctx(company_id)
    all_purchases = _lines(company_id, ("PURCHASE_INVOICE",), ("POSTED",), None, ctx, dated=False)
    with new_session() as session:
        source_ids = [ln.source_line_id for _d, ln in all_purchases if ln.source_line_id]
        sources = {
            ln.line_id: (ln, d) for ln, d in session.execute(
                select(CommercialDocumentLine, CommercialDocument)
                .join(CommercialDocument, CommercialDocument.document_id == CommercialDocumentLine.document_id)
                .where(CommercialDocumentLine.line_id.in_(source_ids))
            ).all()
        } if source_ids else {}
    result = ReportResult([
        ("تاریخ", DATE), ("شمارهٔ فاکتور", INT), ("تامین‌کننده", TEXT), ("کالا", TEXT), ("مبنایِ مقایسه", TEXT),
        ("فیِ مبنا", MONEY), ("فیِ فاکتور", MONEY), ("اختلافِ فی", MONEY), ("درصد", PERCENT), ("مقدار (پایه)", QTY),
        ("اثرِ ریالی", MONEY),
    ], no_total={1, 5, 6, 7, 8},
        note="اثرِ مثبت = گران‌تر از مبنا (زیان)، منفی = ارزان‌تر (صرفه‌جویی).")
    last_price: dict[int, decimal.Decimal] = {}
    for doc, ln in all_purchases:
        price = _base_price(ln)
        basis_label, basis = None, None
        source = sources.get(ln.source_line_id)
        if source is not None and source[1].document_type_code in ("PURCHASE_ORDER", "PURCHASE_PROFORMA"):
            basis, basis_label = _base_price(source[0]), f"سفارشِ {source[1].document_no}"
        elif ln.item_id in last_price:
            basis, basis_label = last_price[ln.item_id], "آخرین خریدِ قبلی"
        last_price[ln.item_id] = price
        if basis is None or not (f.date_from <= doc.document_date <= f.date_to) or not _line_matches(ctx, f, doc, ln):
            continue
        diff = price - basis
        if diff == 0:
            continue
        result.add([
            doc.document_date, doc.document_no, ctx.names.get(doc.counterparty_detail_account_id, ""), ctx.item_label(ln.item_id),
            basis_label, basis, price, diff, (diff * 100 / basis) if basis else _ZERO, ln.quantity_base,
            (diff * ln.quantity_base).quantize(decimal.Decimal("0.01")),
        ], (doc.document_id, doc.document_type_code))
    return result


# ---------------------------------------------------------------------
# ۲۳) دقتِ مقدارِ تحویل (Fill Rate) / ۲۵) زمانِ تحویل (Lead Time)
# ---------------------------------------------------------------------
def _received_orders(company_id: int, f: PurchaseFilters, ctx: _Ctx):
    """سفارش‌هایِ خریدی که رسیدشان تایید شده یا (بدونِ مرحلهٔ رسید) فاکتور شده‌اند."""
    pairs = _lines(company_id, ("PURCHASE_ORDER",), ("CONFIRMED", "APPROVED", "POSTED"), f, ctx)
    invoiced = _invoiced_base_by_source_line(company_id, [ln.line_id for _d, ln in pairs])
    first_invoice: dict[int, datetime.date] = {}
    with new_session() as session:
        for src_doc_id, inv_date in session.execute(
            select(CommercialDocument.source_document_id, CommercialDocument.document_date).where(
                CommercialDocument.company_id == company_id, CommercialDocument.document_type_code == "PURCHASE_INVOICE",
                CommercialDocument.status_code != "CANCELLED", CommercialDocument.source_document_id.is_not(None),
            )
        ):
            if src_doc_id not in first_invoice or inv_date < first_invoice[src_doc_id]:
                first_invoice[src_doc_id] = inv_date
    out = []
    for doc, ln in pairs:
        received = _received_base(doc, ln)
        received_on = doc.warehouse_approved_at.date() if doc.warehouse_approved_at else first_invoice.get(doc.document_id)
        if received is None:
            received = invoiced.get(ln.line_id)
            if not received:
                continue
        if received_on is None:
            continue
        out.append((doc, ln, received, received_on))
    return out


def fill_rate(company_id: int, f: PurchaseFilters) -> ReportResult:
    ctx = _ctx(company_id)
    agg: dict[int, dict] = defaultdict(lambda: {"ordered": _ZERO, "received": _ZERO, "lines": 0, "full": 0, "docs": set()})
    for doc, ln, received, _on in _received_orders(company_id, f, ctx):
        a = agg[doc.counterparty_detail_account_id]
        a["ordered"] += ln.quantity_base
        a["received"] += received
        a["lines"] += 1
        a["full"] += 1 if received >= ln.quantity_base else 0
        a["docs"].add(doc.document_id)
    result = ReportResult([
        ("تامین‌کننده", TEXT), ("تعدادِ سفارش", INT), ("تعدادِ ردیف", INT), ("مقدارِ سفارش", QTY), ("مقدارِ دریافتی", QTY),
        ("دقتِ مقدار", PERCENT), ("ردیف‌هایِ کامل", INT), ("درصدِ ردیفِ کامل", PERCENT),
    ])
    for supplier_id, a in sorted(agg.items(), key=lambda kv: ctx.names.get(kv[0], "")):
        result.add([
            ctx.names.get(supplier_id, ""), len(a["docs"]), a["lines"], a["ordered"], a["received"],
            (a["received"] * 100 / a["ordered"]) if a["ordered"] else _ZERO, a["full"],
            decimal.Decimal(a["full"] * 100) / a["lines"] if a["lines"] else _ZERO,
        ])
    return result


def lead_time(company_id: int, f: PurchaseFilters) -> ReportResult:
    ctx = _ctx(company_id)
    agg: dict[tuple[int, int], list[int]] = defaultdict(list)
    for doc, ln, _received, received_on in _received_orders(company_id, f, ctx):
        agg[(doc.counterparty_detail_account_id, ln.item_id)].append((received_on - doc.document_date).days)
    result = ReportResult([
        ("تامین‌کننده", TEXT), ("کالا", TEXT), ("تعدادِ دریافت", INT), ("میانگینِ روز", DAYS), ("کمترین", DAYS),
        ("بیشترین", DAYS), ("زمانِ تحویلِ تعریف‌شده در کالا", TEXT),
    ], no_total={2})
    for (supplier_id, item_id), days in sorted(agg.items(), key=lambda kv: (ctx.names.get(kv[0][0], ""), ctx.item_label(kv[0][1]))):
        item = ctx.items.get(item_id)
        defined = item.purchase_lead_time_days if item is not None else None
        result.add([
            ctx.names.get(supplier_id, ""), ctx.item_label(item_id), len(days), round(sum(days) / len(days)),
            min(days), max(days), f"{defined} روز" if defined else "",
        ])
    return result


# ---------------------------------------------------------------------
# ۲۶) ماندهٔ حسابِ تامین‌کنندگان / ۲۹) صورت‌حسابِ تامین‌کننده (از دفترِ کل)
# ---------------------------------------------------------------------
def _payable_lines(company_id: int, supplier_id: int | None, date_to: datetime.date):
    payable_id = engine_service.get_account_mapping(company_id, "SUPPLIER_PAYABLE")
    if payable_id is None:
        raise ValueError("حسابِ «پرداختنیِ تامین‌کنندگان» در تنظیماتِ انبار ‹ نگاشتِ حساب‌ها مشخص نشده است.")
    person_dim = dimensions_service.get_person_dimension_type_id(company_id)
    with new_session() as session:
        stmt = (
            select(JournalEntryLineDetail.detail_account_id, JournalEntry, JournalEntryLine)
            .join(JournalEntryLine, JournalEntryLine.line_id == JournalEntryLineDetail.line_id)
            .join(JournalEntry, JournalEntry.journal_entry_id == JournalEntryLine.journal_entry_id)
            .join(JournalEntryStatus, JournalEntryStatus.status_id == JournalEntry.status_id)
            .where(
                JournalEntry.company_id == company_id, JournalEntryLine.account_id == payable_id,
                JournalEntryLineDetail.dimension_type_id == person_dim,
                JournalEntryStatus.code.notin_(("DRAFT", "CANCELLED")), JournalEntry.document_date <= date_to,
            )
            .order_by(JournalEntry.document_date, JournalEntry.journal_entry_id, JournalEntryLine.line_no)
        )
        if supplier_id is not None:
            stmt = stmt.where(JournalEntryLineDetail.detail_account_id == supplier_id)
        return list(session.execute(stmt).all())


def _balances(company_id: int, f: PurchaseFilters) -> dict[int, dict]:
    agg: dict[int, dict] = defaultdict(lambda: {"open": _ZERO, "debit": _ZERO, "credit": _ZERO})
    for detail_id, je, ln in _payable_lines(company_id, f.supplier_id, f.date_to):
        a = agg[detail_id]
        if je.document_date < f.date_from:
            a["open"] += ln.credit_amount_base - ln.debit_amount_base
        else:
            a["debit"] += ln.debit_amount_base
            a["credit"] += ln.credit_amount_base
    return agg


def supplier_balances(company_id: int, f: PurchaseFilters) -> ReportResult:
    ctx = _ctx(company_id)
    agg = _balances(company_id, f)
    result = ReportResult([
        ("تامین‌کننده", TEXT), ("ماندهٔ اولِ دوره", MONEY), ("بدهکار (پرداخت/برگشت)", MONEY),
        ("بستانکار (خرید)", MONEY), ("ماندهٔ پایانِ دوره", MONEY), ("وضعیت", TEXT),
    ], note="ماندهٔ مثبت = بدهیِ ما به تامین‌کننده؛ منفی = پیش‌پرداخت/طلبِ ما.")
    for supplier_id, a in sorted(agg.items(), key=lambda kv: -(kv[1]["open"] + kv[1]["credit"] - kv[1]["debit"])):
        closing = a["open"] + a["credit"] - a["debit"]
        if not (a["open"] or a["debit"] or a["credit"]):
            continue
        result.add([
            ctx.names.get(supplier_id, ""), a["open"], a["debit"], a["credit"], closing,
            "بدهکاریم" if closing > 0 else "پیش‌پرداخت/طلب" if closing < 0 else "تسویه",
        ])
    return result


def supplier_statement(company_id: int, f: PurchaseFilters) -> ReportResult:
    result = ReportResult([
        ("تاریخ", DATE), ("شمارهٔ سند", INT), ("شرح", TEXT), ("بدهکار", MONEY), ("بستانکار", MONEY), ("مانده", MONEY),
    ], no_total={1, 5})
    if f.supplier_id is None:
        result.note = "برایِ صورت‌حساب، یک تامین‌کننده انتخاب کنید."
        return result
    opening = _ZERO
    running = _ZERO
    rows = []
    for _detail_id, je, ln in _payable_lines(company_id, f.supplier_id, f.date_to):
        amount = ln.credit_amount_base - ln.debit_amount_base
        if je.document_date < f.date_from:
            opening += amount
            continue
        rows.append((je, ln))
    running = opening
    result.add([f.date_from, None, "ماندهٔ اولِ دوره", _ZERO, _ZERO, opening])
    for je, ln in rows:
        running += ln.credit_amount_base - ln.debit_amount_base
        result.add([
            je.document_date, je.permanent_no or je.temporary_no, ln.description or je.description or "",
            ln.debit_amount_base, ln.credit_amount_base, running,
        ])
    return result


# ---------------------------------------------------------------------
# ۲۷) سنی‌کردنِ بدهی (AP Aging)
# ---------------------------------------------------------------------
_BUCKETS = ((0, "جاری"), (30, "۱–۳۰"), (60, "۳۱–۶۰"), (90, "۶۱–۹۰"))


def ap_aging(company_id: int, f: PurchaseFilters) -> ReportResult:
    ctx = _ctx(company_id)
    as_of = f.date_to
    with new_session() as session:
        docs = list(session.scalars(
            select(CommercialDocument).where(
                CommercialDocument.company_id == company_id, CommercialDocument.document_type_code == "PURCHASE_INVOICE",
                CommercialDocument.status_code == "POSTED", CommercialDocument.document_date <= as_of,
            )
        ))
        settled: dict[int, decimal.Decimal] = defaultdict(lambda: _ZERO)
        if docs:
            for invoice_id, amount in session.execute(
                select(InvoiceSettlement.invoice_document_id, InvoiceSettlement.amount).where(
                    InvoiceSettlement.invoice_document_id.in_([d.document_id for d in docs]),
                    InvoiceSettlement.settlement_date <= as_of,
                )
            ):
                settled[invoice_id] += amount
    columns = [("تامین‌کننده", TEXT), ("تعدادِ فاکتورِ باز", INT)]
    columns += [(f"{label} روز" if days else "سررسیدنشده", MONEY) for days, label in _BUCKETS]
    columns += [("بیش از ۹۰ روز", MONEY), ("جمعِ ماندهٔ باز", MONEY), ("میانگینِ روزِ گذشته از سررسید", DAYS)]
    result = ReportResult(columns, no_total={len(columns) - 1},
                          note="بر مبنایِ سررسیدِ فاکتور (اگر نداشت، تاریخِ فاکتور) و تسویه‌هایِ ثبت‌شده تا «تا تاریخ».")
    agg: dict[int, dict] = defaultdict(lambda: {"count": 0, "buckets": [_ZERO] * 5, "weighted": _ZERO})
    for doc in docs:
        if f.supplier_id is not None and doc.counterparty_detail_account_id != f.supplier_id:
            continue
        remaining = doc.total_amount - settled[doc.document_id]
        if remaining <= 0:
            continue
        overdue = (as_of - (doc.due_date or doc.document_date)).days
        index = 0 if overdue <= 0 else 1 if overdue <= 30 else 2 if overdue <= 60 else 3 if overdue <= 90 else 4
        a = agg[doc.counterparty_detail_account_id]
        a["count"] += 1
        a["buckets"][index] += remaining
        a["weighted"] += remaining * max(overdue, 0)
    for supplier_id, a in sorted(agg.items(), key=lambda kv: -sum(kv[1]["buckets"])):
        total = sum(a["buckets"], _ZERO)
        result.add([ctx.names.get(supplier_id, ""), a["count"], *a["buckets"], total,
                    round(a["weighted"] / total) if total else 0])
    return result


# ---------------------------------------------------------------------
# ۳۱) فهرستِ تامین‌کنندگان
# ---------------------------------------------------------------------
def supplier_list(company_id: int, f: PurchaseFilters) -> ReportResult:
    ctx = _ctx(company_id)
    purchases = _lines(company_id, ("PURCHASE_INVOICE",), ("POSTED",), f, ctx)
    totals: dict[int, decimal.Decimal] = defaultdict(lambda: _ZERO)
    last: dict[int, datetime.date] = {}
    for doc, ln in purchases:
        totals[doc.counterparty_detail_account_id] += _net(ln)
        last[doc.counterparty_detail_account_id] = doc.document_date
    try:
        balances = {
            sid: a["open"] + a["credit"] - a["debit"]
            for sid, a in _balances(company_id, PurchaseFilters(datetime.date(1900, 1, 1), f.date_to)).items()
        }
    except ValueError:  # حسابِ پرداختنی هنوز نگاشت نشده
        balances = {}
    result = ReportResult([
        ("کد", TEXT), ("نام", TEXT), ("فعال", TEXT), ("تلفن", TEXT), ("موبایل", TEXT), ("کدِ اقتصادی", TEXT),
        ("شناسهٔ ملی", TEXT), ("شمارهٔ حساب", TEXT), ("نشانی", TEXT), ("خریدِ بازه", MONEY), ("آخرین خرید", DATE),
        ("ماندهٔ حساب", MONEY),
    ])
    for s in dimensions_service.list_suppliers(company_id):
        sid = s["detail_account_id"]
        if f.supplier_id is not None and sid != f.supplier_id:
            continue
        result.add([
            s.get("code", ""), s.get("name", ""), "بله" if s.get("is_active", True) else "خیر", s.get("phone") or "",
            s.get("mobile") or "", s.get("economic_code") or "", s.get("national_id") or "", s.get("bank_account_no") or "",
            s.get("address") or "", totals.get(sid, _ZERO), last.get(sid), balances.get(sid, _ZERO),
        ])
    return result


# ---------------------------------------------------------------------
# فهرستِ گزارش‌ها (ترتیبِ منو)
# ---------------------------------------------------------------------
@dataclass
class ReportDef:
    code: str
    title: str
    func: object
    filters: tuple[str, ...]  # supplier, item, category, warehouse
    hint: str
    dated: bool = True


REPORTS: list[ReportDef] = [
    ReportDef("OPEN_PO", "سفارش‌هایِ خریدِ باز", open_purchase_orders, ("supplier", "item", "category", "warehouse"),
              "سفارش‌هایی که هنوز کامل فاکتور نشده‌اند -- مقدارِ سفارش، رسیده، فاکتورشده و مانده."),
    ReportDef("PENDING_RECEIPTS", "رسیدهایِ در انتظارِ انبار", pending_receipts, ("supplier", "item", "category", "warehouse"),
              "سفارش‌ها/امانی‌هایی که منتظرِ تاییدِ انباردار هستند و چند روز است معطل مانده‌اند.", dated=False),
    ReportDef("GRIR", "رسیده ولی فاکتورنشده (GR/IR)", received_not_invoiced, ("supplier", "item", "category", "warehouse"),
              "کالایِ تحویل‌گرفته‌ای که فاکتورش هنوز صادر نشده -- بدهیِ شناسایی‌نشده تا «تا تاریخ».", dated=False),
    ReportDef("PENDING_INVOICES", "فاکتورهایِ خریدِ در انتظار", pending_invoices, ("supplier", "item", "category", "warehouse"),
              "فاکتور/پیش‌فاکتور/برگشتِ خریدی که در یکی از مراحل مانده‌اند.", dated=False),
    ReportDef("BY_ITEM", "خرید به تفکیکِ کالا", purchases_by_item, ("supplier", "item", "category", "warehouse"),
              "مقدار، مبلغ، برگشتی و میانگین/کمترین/بیشترین/آخرین فیِ هر کالا در بازه."),
    ReportDef("BY_SUPPLIER", "خرید به تفکیکِ تامین‌کننده", purchases_by_supplier, ("supplier", "item", "category", "warehouse"),
              "حجمِ خرید، تخفیف، مالیات، برگشتی و سهمِ هر تامین‌کننده."),
    ReportDef("PRICE_HISTORY", "تاریخچهٔ قیمتِ خرید", price_history, ("supplier", "item", "category", "warehouse"),
              "فیِ هر خرید به واحدِ پایه و درصدِ تغییر نسبت به خریدِ قبلیِ همان کالا."),
    ReportDef("PRICE_COMPARE", "مقایسهٔ قیمتِ تامین‌کنندگان", supplier_price_comparison, ("supplier", "item", "category"),
              "آخرین/میانگین/کمترین فیِ هر تامین‌کننده برایِ هر کالا؛ ★ = ارزان‌ترین آخرین قیمت."),
    ReportDef("PPV", "انحرافِ قیمتِ خرید (PPV)", purchase_price_variance, ("supplier", "item", "category", "warehouse"),
              "اختلافِ فیِ فاکتور با فیِ سفارشِ مبدا (یا آخرین خرید) و اثرِ ریالیِ آن."),
    ReportDef("FILL_RATE", "دقتِ مقدارِ تحویلِ تامین‌کنندگان", fill_rate, ("supplier", "item", "category", "warehouse"),
              "مقدارِ دریافتی در برابرِ مقدارِ سفارش، به تفکیکِ تامین‌کننده."),
    ReportDef("LEAD_TIME", "زمانِ تحویل (Lead Time)", lead_time, ("supplier", "item", "category", "warehouse"),
              "فاصلهٔ تاریخِ سفارش تا رسید (یا اولین فاکتور) -- میانگین/کمترین/بیشترین."),
    ReportDef("BALANCES", "ماندهٔ حسابِ تامین‌کنندگان", supplier_balances, ("supplier",),
              "ماندهٔ اول/گردش/ماندهٔ پایانِ دورهٔ هر تامین‌کننده از دفترِ کل."),
    ReportDef("AGING", "سنی‌کردنِ بدهی (AP Aging)", ap_aging, ("supplier",),
              "ماندهٔ فاکتورهایِ باز به تفکیکِ روزهایِ گذشته از سررسید، تا «تا تاریخ».", dated=False),
    ReportDef("STATEMENT", "صورت‌حسابِ تامین‌کننده", supplier_statement, ("supplier",),
              "ریزِ گردشِ حسابِ یک تامین‌کننده با ماندهٔ جاری."),
    ReportDef("SUPPLIERS", "فهرستِ تامین‌کنندگان", supplier_list, ("supplier",),
              "اطلاعاتِ پایهٔ تامین‌کنندگان با خریدِ بازه، آخرین خرید و ماندهٔ حساب."),
]

REPORTS_BY_CODE = {r.code: r for r in REPORTS}


def run_report(company_id: int, code: str, f: PurchaseFilters) -> ReportResult:
    return REPORTS_BY_CODE[code].func(company_id, f)
