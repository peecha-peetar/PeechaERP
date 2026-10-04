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
    supplier_id: int | None = None  # طرفِ حساب (تامین‌کننده یا مشتری، طبقِ side)
    item_id: int | None = None
    category_id: int | None = None
    warehouse_id: int | None = None
    side: str = "PURCHASE"
    # R238: گزینه‌هایِ اختصاصیِ هر گزارش (مثلاً مرجعِ قیمت/بُعدِ تحلیل) -- {کلید: مقدار}
    options: dict = field(default_factory=dict)
    # R245: گزارش‌هایِ حسابداری (side=ACCOUNTING)
    account_id: int | None = None
    detail_account_id: int | None = None


ReportFilters = PurchaseFilters


@dataclass(frozen=True)
class Side:
    """R236: یک گزارش برایِ خرید و فروش -- انواعِ سند، حسابِ طرف و علامتِ مانده."""
    code: str
    order: str
    proforma: str
    invoice: str
    ret: str
    consignment: str
    account_key: str
    # مانده = علامت × (بستانکار − بدهکار): خرید +۱ (بدهیِ ما)، فروش −۱ (طلبِ ما)
    sign: int
    party: str
    trade: str


SIDES = {
    "PURCHASE": Side("PURCHASE", "PURCHASE_ORDER", "PURCHASE_PROFORMA", "PURCHASE_INVOICE", "PURCHASE_RETURN",
                     "CONSIGNMENT_IN", "SUPPLIER_PAYABLE", 1, "تامین‌کننده", "خرید"),
    "SALES": Side("SALES", "SALES_ORDER", "SALES_PROFORMA", "SALES_INVOICE", "SALES_RETURN",
                  "CONSIGNMENT_OUT", "CUSTOMER_RECEIVABLE", -1, "مشتری", "فروش"),
}


def _side(f: PurchaseFilters) -> Side:
    return SIDES[f.side]


# برگردانِ عنوان‌هایِ ستون/توضیح برایِ نسخهٔ فروشِ همان گزارش (ترتیب مهم است)
_SALES_WORDS = (
    ("تامین‌کنندگانِ", "مشتریانِ"), ("تامین‌کنندگان", "مشتریان"), ("تامین‌کنندهٔ", "مشتریِ"), ("تامین‌کننده", "مشتری"),
    ("پیش‌پرداخت", "پیش‌دریافت"), ("پرداخت‌ها", "دریافت‌ها"), ("پرداختنی", "دریافتنی"), ("بدهی", "طلب"),
    ("مقدارِ دریافتی", "مقدارِ تحویلی"), ("دریافت‌شده", "تحویل‌شده"), ("تعدادِ دریافت", "تعدادِ تحویل"),
    ("خرید", "فروش"), ("رسیده", "تحویل‌شده"), ("رسید", "حواله"),
)


def sales_words(text: str) -> str:
    for old, new in _SALES_WORDS:
        text = text.replace(old, new)
    return text


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
        if all(v == "" for v in out):  # هیچ ستونِ جمع‌پذیری نیست -- ردیفِ خالیِ «جمعِ کل» نشان داده نشود
            return None
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


def _invoiced_base_by_source_line(company_id: int, invoice_type: str, source_line_ids: list[int]) -> dict[int, decimal.Decimal]:
    if not source_line_ids:
        return {}
    with new_session() as session:
        rows = session.execute(
            select(CommercialDocumentLine.source_line_id, CommercialDocumentLine.quantity_base)
            .join(CommercialDocument, CommercialDocument.document_id == CommercialDocumentLine.document_id)
            .where(
                CommercialDocumentLine.source_line_id.in_(source_line_ids),
                CommercialDocument.document_type_code == invoice_type,
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
    S = _side(f)
    ctx = _ctx(company_id)
    pairs = _lines(company_id, (S.order,), ("CONFIRMED", "APPROVED", "POSTED"), f, ctx)
    invoiced = _invoiced_base_by_source_line(company_id, S.invoice, [ln.line_id for _d, ln in pairs])
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
    S = _side(f)
    ctx = _ctx(company_id)
    result = ReportResult([
        ("نوع", TEXT), ("شماره", INT), ("تاریخ", DATE), ("تامین‌کننده", TEXT), ("انبار", TEXT),
        ("تعدادِ ردیف", INT), ("مقدارِ کل (پایه)", QTY), ("روزِ انتظار", DAYS),
    ], no_total={1})
    titles = {"PURCHASE_ORDER": "سفارشِ خرید", "CONSIGNMENT_IN": "امانیِ ورودی"} if S.code == "PURCHASE" else \
        {"SALES_ORDER": "سفارشِ فروش", "CONSIGNMENT_OUT": "امانیِ خروجی"}
    for doc in documents_service.list_purchase_order_goods_receipt_queue(company_id):
        if doc.document_type_code not in titles or doc.warehouse_approved_at is not None:
            continue
        if f.supplier_id is not None and doc.counterparty_detail_account_id != f.supplier_id:
            continue
        _doc, lines = documents_service.get_document(doc.document_id, company_id)
        lines = [ln for ln in lines if _line_matches(ctx, PurchaseFilters(f.date_from, f.date_to, None, f.item_id, f.category_id, f.warehouse_id, f.side), doc, ln)]
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
    S = _side(f)
    ctx = _ctx(company_id)
    pairs = _lines(company_id, (S.order,), ("CONFIRMED", "APPROVED", "POSTED"), f, ctx, dated=False)
    pairs = [(d, ln) for d, ln in pairs if d.warehouse_approved_at is not None and d.warehouse_approved_at.date() <= f.date_to]
    invoiced = _invoiced_base_by_source_line(company_id, S.invoice, [ln.line_id for _d, ln in pairs])
    result = ReportResult([
        ("شمارهٔ سفارش", INT), ("تاریخِ رسید", DATE), ("تامین‌کننده", TEXT), ("کالا", TEXT), ("واحد", TEXT),
        ("رسیده", QTY), ("فاکتورشده", QTY), ("فاکتورنشده", QTY), ("فیِ سفارش (پایه)", MONEY), ("ارزشِ فاکتورنشده", MONEY),
        ("روز از رسید", DAYS),
    ], no_total={0, 8},
        note="بدهیِ شناسایی‌نشده: کالایی که انبار تحویل گرفته ولی فاکتورِ خریدش هنوز صادر نشده است." if S.code == "PURCHASE"
        else "درآمدِ شناسایی‌نشده: کالایی که به مشتری تحویل شده ولی فاکتورِ فروشش هنوز صادر نشده است.")
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
    S = _side(f)
    ctx = _ctx(company_id)
    titles = {"PURCHASE_INVOICE": "فاکتورِ خرید", "PURCHASE_PROFORMA": "پیش‌فاکتورِ خرید", "PURCHASE_RETURN": "برگشت به تامین‌کننده"} \
        if S.code == "PURCHASE" else {"SALES_INVOICE": "فاکتورِ فروش", "SALES_PROFORMA": "پیش‌فاکتورِ فروش", "SALES_RETURN": "برگشت از فروش"}
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
    S = _side(f)
    purchases = _lines(company_id, (S.invoice,), ("POSTED",), f, ctx)
    returns = _lines(company_id, (S.ret,), ("POSTED",), f, ctx)
    return purchases, returns


def purchases_by_item(company_id: int, f: PurchaseFilters) -> ReportResult:
    S = _side(f)
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
    S = _side(f)
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
    S = _side(f)
    ctx = _ctx(company_id)
    purchases = _lines(company_id, (S.invoice,), ("POSTED",), f, ctx)
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
    S = _side(f)
    ctx = _ctx(company_id)
    purchases = _lines(company_id, (S.invoice,), ("POSTED",), f, ctx)
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
    S = _side(f)
    ctx = _ctx(company_id)
    all_purchases = _lines(company_id, (S.invoice,), ("POSTED",), None, ctx, dated=False)
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
        if source is not None and source[1].document_type_code in (S.order, S.proforma):
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
    S = _side(f)
    pairs = _lines(company_id, (S.order,), ("CONFIRMED", "APPROVED", "POSTED"), f, ctx)
    invoiced = _invoiced_base_by_source_line(company_id, S.invoice, [ln.line_id for _d, ln in pairs])
    first_invoice: dict[int, datetime.date] = {}
    with new_session() as session:
        for src_doc_id, inv_date in session.execute(
            select(CommercialDocument.source_document_id, CommercialDocument.document_date).where(
                CommercialDocument.company_id == company_id, CommercialDocument.document_type_code == S.invoice,
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
    S = _side(f)
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
    S = _side(f)
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
        defined = item.purchase_lead_time_days if item is not None and S.code == "PURCHASE" else None
        result.add([
            ctx.names.get(supplier_id, ""), ctx.item_label(item_id), len(days), round(sum(days) / len(days)),
            min(days), max(days), f"{defined} روز" if defined else "",
        ])
    return result


# ---------------------------------------------------------------------
# ۲۶) ماندهٔ حسابِ تامین‌کنندگان / ۲۹) صورت‌حسابِ تامین‌کننده (از دفترِ کل)
# ---------------------------------------------------------------------
def _payable_lines(company_id: int, supplier_id: int | None, date_to: datetime.date, side: Side = SIDES["PURCHASE"]):
    payable_id = engine_service.get_account_mapping(company_id, side.account_key)
    if payable_id is None:
        raise ValueError(
            f"حسابِ «{engine_service.MAPPING_LABELS.get(side.account_key, side.account_key)}» در تنظیماتِ انبار ‹ نگاشتِ حساب‌ها مشخص نشده است."
        )
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
    S = _side(f)
    agg: dict[int, dict] = defaultdict(lambda: {"open": _ZERO, "debit": _ZERO, "credit": _ZERO})
    for detail_id, je, ln in _payable_lines(company_id, f.supplier_id, f.date_to, S):
        a = agg[detail_id]
        if je.document_date < f.date_from:
            a["open"] += S.sign * (ln.credit_amount_base - ln.debit_amount_base)
        else:
            a["debit"] += ln.debit_amount_base
            a["credit"] += ln.credit_amount_base
    return agg


def supplier_balances(company_id: int, f: PurchaseFilters) -> ReportResult:
    S = _side(f)
    ctx = _ctx(company_id)
    agg = _balances(company_id, f)
    result = ReportResult([
        ("تامین‌کننده", TEXT), ("ماندهٔ اولِ دوره", MONEY),
        ("بدهکار (پرداخت/برگشت)" if S.code == "PURCHASE" else "بدهکار (فروش)", MONEY),
        ("بستانکار (خرید)" if S.code == "PURCHASE" else "بستانکار (وصول/برگشت)", MONEY),
        ("ماندهٔ پایانِ دوره", MONEY), ("وضعیت", TEXT),
    ], note="ماندهٔ مثبت = بدهیِ ما به تامین‌کننده؛ منفی = پیش‌پرداخت/طلبِ ما." if S.code == "PURCHASE"
        else "ماندهٔ مثبت = طلبِ ما از مشتری؛ منفی = پیش‌دریافت از مشتری.")
    for supplier_id, a in sorted(agg.items(), key=lambda kv: -(kv[1]["open"] + S.sign * (kv[1]["credit"] - kv[1]["debit"]))):
        closing = a["open"] + S.sign * (a["credit"] - a["debit"])
        if not (a["open"] or a["debit"] or a["credit"]):
            continue
        result.add([
            ctx.names.get(supplier_id, ""), a["open"], a["debit"], a["credit"], closing,
            ("بدهکاریم" if S.code == "PURCHASE" else "بدهکار است") if closing > 0
            else ("پیش‌پرداخت" if S.code == "PURCHASE" else "پیش‌دریافت") if closing < 0 else "تسویه",
        ])
    return result


def supplier_statement(company_id: int, f: PurchaseFilters) -> ReportResult:
    S = _side(f)
    result = ReportResult([
        ("تاریخ", DATE), ("شمارهٔ سند", INT), ("شرح", TEXT), ("بدهکار", MONEY), ("بستانکار", MONEY), ("مانده", MONEY),
    ], no_total={1, 5})
    if f.supplier_id is None:
        result.note = "برایِ صورت‌حساب، یک تامین‌کننده انتخاب کنید."
        return result
    opening = _ZERO
    running = _ZERO
    rows = []
    for _detail_id, je, ln in _payable_lines(company_id, f.supplier_id, f.date_to, S):
        amount = S.sign * (ln.credit_amount_base - ln.debit_amount_base)
        if je.document_date < f.date_from:
            opening += amount
            continue
        rows.append((je, ln))
    running = opening
    result.add([f.date_from, None, "ماندهٔ اولِ دوره", _ZERO, _ZERO, opening])
    for je, ln in rows:
        running += S.sign * (ln.credit_amount_base - ln.debit_amount_base)
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
    S = _side(f)
    ctx = _ctx(company_id)
    as_of = f.date_to
    with new_session() as session:
        docs = list(session.scalars(
            select(CommercialDocument).where(
                CommercialDocument.company_id == company_id, CommercialDocument.document_type_code == S.invoice,
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
    S = _side(f)
    ctx = _ctx(company_id)
    purchases = _lines(company_id, (S.invoice,), ("POSTED",), f, ctx)
    totals: dict[int, decimal.Decimal] = defaultdict(lambda: _ZERO)
    last: dict[int, datetime.date] = {}
    for doc, ln in purchases:
        totals[doc.counterparty_detail_account_id] += _net(ln)
        last[doc.counterparty_detail_account_id] = doc.document_date
    try:
        balances = {
            sid: a["open"] + S.sign * (a["credit"] - a["debit"])
            for sid, a in _balances(company_id, PurchaseFilters(datetime.date(1900, 1, 1), f.date_to, side=f.side)).items()
        }
    except ValueError:  # حسابِ پرداختنی هنوز نگاشت نشده
        balances = {}
    result = ReportResult([
        ("کد", TEXT), ("نام", TEXT), ("فعال", TEXT), ("تلفن", TEXT), ("موبایل", TEXT), ("کدِ اقتصادی", TEXT),
        ("شناسهٔ ملی", TEXT), ("شمارهٔ حساب", TEXT), ("نشانی", TEXT), ("خریدِ بازه", MONEY), ("آخرین خرید", DATE),
        ("ماندهٔ حساب", MONEY),
    ])
    parties = dimensions_service.list_suppliers(company_id) if S.code == "PURCHASE" else dimensions_service.list_customers(company_id)
    for s in parties:
        sid = s["detail_account_id"]
        if f.supplier_id is not None and sid != f.supplier_id:
            continue
        result.add([
            s.get("code", ""), s.get("name", ""), "بله" if s.get("is_active", True) else "خیر", s.get("phone") or "",
            s.get("mobile") or "", s.get("economic_code") or "", s.get("national_id") or "", s.get("bank_account_no") or "",
            s.get("address") or "", totals.get(sid, _ZERO), last.get(sid), balances.get(sid, _ZERO),
        ])
    return result


# =====================================================================
# فاز ۲ (R234)
# =====================================================================
def _jalali_month(value: datetime.date) -> str:
    import jdatetime

    j = jdatetime.date.fromgregorian(date=value)
    return f"{j.year}/{j.month:02d}"


def _supplier_of_lines(f: PurchaseFilters, doc: CommercialDocument) -> bool:
    return f.supplier_id is None or doc.counterparty_detail_account_id == f.supplier_id


# ۲) کالاهایِ در راه / معوق
def overdue_orders(company_id: int, f: PurchaseFilters) -> ReportResult:
    S = _side(f)
    ctx = _ctx(company_id)
    pairs = _lines(company_id, (S.order,), ("CONFIRMED", "APPROVED", "POSTED"), f, ctx, dated=False)
    invoiced = _invoiced_base_by_source_line(company_id, S.invoice, [ln.line_id for _d, ln in pairs])
    result = ReportResult([
        ("شمارهٔ سفارش", INT), ("تاریخِ سفارش", DATE), ("تاریخِ تحویلِ مورد انتظار", DATE), ("تامین‌کننده", TEXT),
        ("کالا", TEXT), ("واحد", TEXT), ("مقدارِ سفارش", QTY), ("دریافت‌شده", QTY), ("در راه/معوق", QTY),
        ("ارزش", MONEY), ("روزِ تاخیر", DAYS), ("وضعیت", TEXT),
    ], no_total={0, 10},
        note="سفارش‌هایی که هنوز کامل نرسیده‌اند؛ «تاریخِ تحویلِ مورد انتظار» در فرمِ سفارشِ خرید ثبت می‌شود.")
    as_of = f.date_to
    for doc, ln in pairs:
        received = _received_base(doc, ln)
        if received is None:
            received = invoiced.get(ln.line_id, _ZERO)
        outstanding = ln.quantity_base - received
        if outstanding <= 0:
            continue
        expected = doc.requested_delivery_date
        late = (as_of - expected).days if expected is not None else 0
        status = "بدونِ تاریخِ تحویل" if expected is None else ("معوق" if late > 0 else "در راه")
        result.add([
            doc.document_no, doc.document_date, expected, ctx.names.get(doc.counterparty_detail_account_id, ""),
            ctx.item_label(ln.item_id), ctx.base_uom(ln.item_id), ln.quantity_base, received, outstanding,
            (outstanding * _base_price(ln)).quantize(decimal.Decimal("0.01")), max(late, 0), status,
        ], (doc.document_id, doc.document_type_code))
    result.rows, result.refs = zip(*sorted(zip(result.rows, result.refs), key=lambda rr: -rr[0][10])) if result.rows else ([], [])
    result.rows, result.refs = list(result.rows), list(result.refs)
    return result


# ۶) امانی‌هایِ ورودیِ تسویه‌نشده
def open_consignments(company_id: int, f: PurchaseFilters) -> ReportResult:
    S = _side(f)
    ctx = _ctx(company_id)
    pairs = _lines(company_id, (S.consignment,), ("POSTED",), f, ctx, dated=False)
    with new_session() as session:
        settled: dict[int, decimal.Decimal] = defaultdict(lambda: _ZERO)
        ids = [ln.line_id for _d, ln in pairs]
        if ids:
            for source_line_id, qty in session.execute(
                select(CommercialDocumentLine.source_line_id, CommercialDocumentLine.quantity_base)
                .join(CommercialDocument, CommercialDocument.document_id == CommercialDocumentLine.document_id)
                .where(CommercialDocumentLine.source_line_id.in_(ids), CommercialDocument.status_code == "POSTED",
                       CommercialDocument.corrects_document_id.is_(None))
            ):
                settled[source_line_id] += qty
    result = ReportResult([
        ("شمارهٔ امانی", INT), ("تاریخ", DATE), ("تامین‌کننده", TEXT), ("کالا", TEXT), ("واحد", TEXT),
        ("مقدارِ دریافتی", QTY), ("تسویه‌شده (خرید)", QTY), ("برگشت‌داده‌شده", QTY), ("ماندهٔ امانی", QTY),
        ("فیِ توافقی", MONEY), ("ارزشِ مانده", MONEY), ("روز نزدِ ما", DAYS),
    ], no_total={0, 9})
    for doc, ln in pairs:
        returned = (ln.returned_quantity or _ZERO) * (ln.conversion_factor or 1)
        open_qty = ln.quantity_base - settled[ln.line_id] - returned
        if open_qty <= 0:
            continue
        price = _base_price(ln)
        result.add([
            doc.document_no, doc.document_date, ctx.names.get(doc.counterparty_detail_account_id, ""), ctx.item_label(ln.item_id),
            ctx.base_uom(ln.item_id), ln.quantity_base, settled[ln.line_id], returned, open_qty, price,
            (open_qty * price).quantize(decimal.Decimal("0.01")), _days(doc.document_date),
        ], (doc.document_id, doc.document_type_code))
    return result


# ۷) برگشت به تامین‌کننده
def purchase_returns(company_id: int, f: PurchaseFilters) -> ReportResult:
    S = _side(f)
    from peecha.db.models.inventory import DocumentReasonCode, StockDocumentLine

    ctx = _ctx(company_id)
    pairs = _lines(company_id, (S.ret,), ("POSTED",), f, ctx)
    reasons: dict[int, str] = {}
    with new_session() as session:
        stock_ids = [ln.stock_document_line_id for _d, ln in pairs if ln.stock_document_line_id]
        if stock_ids:
            reasons = dict(session.execute(
                select(StockDocumentLine.line_id, DocumentReasonCode.name)
                .join(DocumentReasonCode, DocumentReasonCode.reason_code_id == StockDocumentLine.reason_code_id)
                .where(StockDocumentLine.line_id.in_(stock_ids))
            ).all())
    result = ReportResult([
        ("تاریخ", DATE), ("شماره", INT), ("تامین‌کننده", TEXT), ("کالا", TEXT), ("واحد", TEXT), ("مقدار", QTY),
        ("مبلغ", MONEY), ("مالیات", MONEY), ("علت", TEXT),
    ], no_total={1})
    for doc, ln in pairs:
        result.add([
            doc.document_date, doc.document_no, ctx.names.get(doc.counterparty_detail_account_id, ""),
            ctx.item_label(ln.item_id), ctx.base_uom(ln.item_id), ln.quantity_base, _net(ln), ln.tax_amount or _ZERO,
            reasons.get(ln.stock_document_line_id, "") or (doc.description or ""),
        ], (doc.document_id, doc.document_type_code))
    return result


# ۱۰) خرید به تفکیکِ گروهِ کالا
def purchases_by_category(company_id: int, f: PurchaseFilters) -> ReportResult:
    S = _side(f)
    ctx = _ctx(company_id)
    categories = {c.category_id: f"{c.code} — {c.name}" for c in catalog_service.list_categories(company_id)}
    purchases, returns = _posted_purchase_and_returns(company_id, f, ctx)
    agg: dict[int | None, dict] = defaultdict(lambda: {"amount": _ZERO, "returns": _ZERO, "items": set(), "docs": set()})
    for doc, ln in purchases:
        item = ctx.items.get(ln.item_id)
        a = agg[item.category_id if item else None]
        a["amount"] += _net(ln)
        a["items"].add(ln.item_id)
        a["docs"].add(doc.document_id)
    for _doc, ln in returns:
        item = ctx.items.get(ln.item_id)
        agg[item.category_id if item else None]["returns"] += _net(ln)
    total = sum((a["amount"] - a["returns"] for a in agg.values()), _ZERO)
    result = ReportResult([
        ("گروهِ کالا", TEXT), ("تعدادِ کالا", INT), ("تعدادِ فاکتور", INT), ("مبلغِ خرید", MONEY), ("برگشتی", MONEY),
        ("خالص", MONEY), ("سهم از کل", PERCENT),
    ], no_total={1, 2})
    for category_id, a in sorted(agg.items(), key=lambda kv: -(kv[1]["amount"] - kv[1]["returns"])):
        net = a["amount"] - a["returns"]
        result.add([categories.get(category_id, "بدونِ گروه"), len(a["items"]), len(a["docs"]), a["amount"], a["returns"],
                    net, (net * 100 / total) if total else _ZERO])
    return result


# ۱۱) خرید به تفکیکِ مرکزِ هزینه/پروژه
def purchases_by_cost_center(company_id: int, f: PurchaseFilters) -> ReportResult:
    S = _side(f)
    ctx = _ctx(company_id)
    purchases, _returns = _posted_purchase_and_returns(company_id, f, ctx)
    agg: dict[tuple, dict] = defaultdict(lambda: {"amount": _ZERO, "docs": set(), "suppliers": set()})
    for doc, ln in purchases:
        a = agg[(doc.cost_center_detail_account_id, doc.project_detail_account_id)]
        a["amount"] += _net(ln)
        a["docs"].add(doc.document_id)
        a["suppliers"].add(doc.counterparty_detail_account_id)
    total = sum((a["amount"] for a in agg.values()), _ZERO)
    result = ReportResult([
        ("مرکزِ هزینه", TEXT), ("پروژه", TEXT), ("تعدادِ فاکتور", INT), ("تعدادِ تامین‌کننده", INT),
        ("مبلغِ خرید (بدونِ مالیات)", MONEY), ("سهم از کل", PERCENT),
    ], no_total={3})
    for (cc, pj), a in sorted(agg.items(), key=lambda kv: -kv[1]["amount"]):
        result.add([ctx.names.get(cc, "— بدونِ مرکزِ هزینه —") if cc else "— بدونِ مرکزِ هزینه —",
                    ctx.names.get(pj, "") if pj else "", len(a["docs"]), len(a["suppliers"]), a["amount"],
                    (a["amount"] * 100 / total) if total else _ZERO])
    return result


# ۱۲) روندِ ماهانهٔ خرید
def monthly_trend(company_id: int, f: PurchaseFilters) -> ReportResult:
    S = _side(f)
    ctx = _ctx(company_id)
    purchases, returns = _posted_purchase_and_returns(company_id, f, ctx)
    agg: dict[str, dict] = defaultdict(lambda: {"amount": _ZERO, "returns": _ZERO, "docs": set(), "qty": _ZERO})
    for doc, ln in purchases:
        a = agg[_jalali_month(doc.document_date)]
        a["amount"] += _net(ln)
        a["qty"] += ln.quantity_base
        a["docs"].add(doc.document_id)
    for doc, ln in returns:
        agg[_jalali_month(doc.document_date)]["returns"] += _net(ln)
    result = ReportResult([
        ("ماه", TEXT), ("تعدادِ فاکتور", INT), ("مقدار (پایه)", QTY), ("مبلغِ خرید", MONEY), ("برگشتی", MONEY),
        ("خالص", MONEY), ("تغییر نسبت به ماهِ قبل", PERCENT),
    ])
    previous = None
    for month in sorted(agg):
        a = agg[month]
        net = a["amount"] - a["returns"]
        change = ((net - previous) * 100 / previous) if previous else None
        result.add([month, len(a["docs"]), a["qty"], a["amount"], a["returns"], net, change])
        previous = net
    return result


# ۱۳) تحلیلِ ABC خرید
def abc_analysis(company_id: int, f: PurchaseFilters) -> ReportResult:
    S = _side(f)
    base = purchases_by_item(company_id, f)
    rows = sorted(base.rows, key=lambda r: -r[7])
    total = sum((r[7] for r in rows if r[7] > 0), _ZERO)
    result = ReportResult([
        ("رتبه", INT), ("کالا", TEXT), ("خالصِ مبلغِ خرید", MONEY), ("سهم", PERCENT), ("سهمِ تجمعی", PERCENT), ("کلاس", TEXT),
    ], no_total={0}, note="A = اقلامی که تا ۸۰٪ هزینه را می‌سازند (کنترلِ دقیق و مذاکره)، B = تا ۹۵٪، C = بقیه.")
    cumulative = _ZERO
    for rank, r in enumerate(rows, start=1):
        share = (r[7] * 100 / total) if total else _ZERO
        cumulative += share
        klass = "A" if cumulative - share < 80 else "B" if cumulative - share < 95 else "C"
        result.add([rank, r[0], r[7], share, cumulative, klass])
    return result


# ۱۴) تمرکزِ تامین (ریسکِ تک‌منبعی)
def supply_concentration(company_id: int, f: PurchaseFilters) -> ReportResult:
    S = _side(f)
    from peecha.db.models.inventory import ItemSupplier

    ctx = _ctx(company_id)
    purchases, _r = _posted_purchase_and_returns(company_id, f, ctx)
    agg: dict[int, dict[int, decimal.Decimal]] = defaultdict(lambda: defaultdict(lambda: _ZERO))
    for doc, ln in purchases:
        agg[ln.item_id][doc.counterparty_detail_account_id] += _net(ln)
    with new_session() as session:
        defined: dict[int, int] = defaultdict(int)
        for (item_id,) in session.execute(select(ItemSupplier.item_id)):
            defined[item_id] += 1
    result = ReportResult([
        ("کالا", TEXT), ("تعدادِ تامین‌کنندهٔ فعال", INT), ("تامین‌کنندگانِ تعریف‌شده", INT), ("تامین‌کنندهٔ اصلی", TEXT),
        ("سهمِ تامین‌کنندهٔ اصلی", PERCENT), ("مبلغِ خرید", MONEY), ("ریسک", TEXT),
    ], no_total={1, 2}, note="«تک‌منبعی» = همهٔ خریدِ این کالا از یک تامین‌کننده بوده؛ جایگزین پیدا کنید.")
    for item_id, by_supplier in sorted(agg.items(), key=lambda kv: -sum(kv[1].values())):
        total = sum(by_supplier.values(), _ZERO)
        top_id, top_amount = max(by_supplier.items(), key=lambda kv: kv[1])
        share = (top_amount * 100 / total) if total else _ZERO
        risk = "تک‌منبعی" if len(by_supplier) == 1 else "تمرکزِ بالا" if share >= 80 else "متنوع"
        result.add([ctx.item_label(item_id), len(by_supplier), defined.get(item_id, 0), ctx.names.get(top_id, ""), share,
                    total, risk])
    return result


# ۱۸) اصلاحیه‌هایِ فاکتورِ خرید
def invoice_corrections(company_id: int, f: PurchaseFilters) -> ReportResult:
    S = _side(f)
    ctx = _ctx(company_id)
    variance_id = engine_service.get_account_mapping(company_id, "INVENTORY_COST_VARIANCE")
    inventory_id = engine_service.get_account_mapping(company_id, "INVENTORY_ASSET")
    with new_session() as session:
        corrections = list(session.scalars(
            select(CommercialDocument).where(
                CommercialDocument.company_id == company_id, CommercialDocument.document_type_code == S.invoice,
                CommercialDocument.status_code == "POSTED", CommercialDocument.corrects_document_id.is_not(None),
                CommercialDocument.document_date.between(f.date_from, f.date_to),
            ).order_by(CommercialDocument.document_date)
        ))
        originals = {d.document_id: d for d in session.scalars(
            select(CommercialDocument).where(CommercialDocument.document_id.in_([c.corrects_document_id for c in corrections]))
        )} if corrections else {}
        je_amounts: dict[tuple[int, int], decimal.Decimal] = defaultdict(lambda: _ZERO)
        je_ids = [c.journal_entry_id for c in corrections if c.journal_entry_id]
        if je_ids:
            for je_id, account_id, dr, cr in session.execute(
                select(JournalEntryLine.journal_entry_id, JournalEntryLine.account_id,
                       JournalEntryLine.debit_amount_base, JournalEntryLine.credit_amount_base)
                .where(JournalEntryLine.journal_entry_id.in_(je_ids))
            ):
                je_amounts[(je_id, account_id)] += dr - cr
    result = ReportResult([
        ("تاریخِ اصلاح", DATE), ("فاکتورِ اصلی", INT), ("اصلاحیه", INT), ("تامین‌کننده", TEXT), ("مبلغِ اصلی", MONEY),
        ("مبلغِ اصلاح‌شده", MONEY), ("اختلاف", MONEY), ("اثر بر موجودی", MONEY), ("اثر بر مغایرتِ بها", MONEY),
    ], no_total={1, 2})
    for c in corrections:
        if not _supplier_of_lines(f, c):
            continue
        original = originals.get(c.corrects_document_id)
        old_total = original.total_amount if original else _ZERO
        result.add([
            c.document_date, original.document_no if original else None, c.document_no,
            ctx.names.get(c.counterparty_detail_account_id, ""), old_total, c.total_amount, c.total_amount - old_total,
            je_amounts.get((c.journal_entry_id, inventory_id), _ZERO) if c.journal_entry_id != (original.journal_entry_id if original else None) else _ZERO,
            je_amounts.get((c.journal_entry_id, variance_id), _ZERO) if c.journal_entry_id != (original.journal_entry_id if original else None) else _ZERO,
        ], (c.document_id, c.document_type_code))
    return result


# ۱۹) هزینه‌هایِ جانبیِ خرید (Landed Cost)
_COST_TYPES = {"FREIGHT": "حمل", "CUSTOMS": "گمرک", "INSURANCE": "بیمه", "HANDLING": "تخلیه/بارگیری", "OTHER": "سایر"}


def landed_costs(company_id: int, f: PurchaseFilters) -> ReportResult:
    S = _side(f)
    from peecha.db.models.commercial import LandedCostAllocation

    ctx = _ctx(company_id)
    with new_session() as session:
        rows = session.execute(
            select(LandedCostAllocation, CommercialDocument)
            .join(CommercialDocument, CommercialDocument.document_id == LandedCostAllocation.purchase_invoice_document_id)
            .where(CommercialDocument.company_id == company_id, CommercialDocument.status_code.in_(("POSTED", "CORRECTED")),
                   CommercialDocument.document_date.between(f.date_from, f.date_to))
            .order_by(CommercialDocument.document_date)
        ).all()
    result = ReportResult([
        ("تاریخ", DATE), ("شمارهٔ فاکتور", INT), ("تامین‌کننده", TEXT), ("نوعِ هزینه", TEXT), ("مبلغ", MONEY),
        ("مبلغِ کالا (فاکتور)", MONEY), ("درصد از کالا", PERCENT), ("حسابِ بستانکار", TEXT), ("شرح", TEXT),
    ], no_total={1, 5, 6})
    for alloc, doc in rows:
        if not _supplier_of_lines(f, doc):
            continue
        goods = doc.subtotal_amount - doc.discount_amount
        result.add([
            doc.document_date, doc.document_no, ctx.names.get(doc.counterparty_detail_account_id, ""),
            _COST_TYPES.get(alloc.cost_type_code or "", alloc.cost_type_code or ""), alloc.amount, goods,
            (alloc.amount * 100 / goods) if goods else _ZERO,
            ctx.names.get(alloc.credit_detail_account_id, "") if alloc.credit_detail_account_id else "", alloc.notes or "",
        ], (doc.document_id, doc.document_type_code))
    return result


# ۲۰) تخفیف‌ها و ریبیتِ خرید
def discounts_and_rebates(company_id: int, f: PurchaseFilters) -> ReportResult:
    S = _side(f)
    from peecha.services import commercial_purchasing as purchasing_service

    ctx = _ctx(company_id)
    purchases, _r = _posted_purchase_and_returns(company_id, f, ctx)
    agg: dict[int, dict] = defaultdict(lambda: {"gross": _ZERO, "discount": _ZERO, "accrued": _ZERO, "settled": _ZERO})
    for doc, ln in purchases:
        a = agg[doc.counterparty_detail_account_id]
        a["gross"] += (ln.quantity * ln.unit_price).quantize(decimal.Decimal("0.01"))
        a["discount"] += ln.discount_amount or _ZERO
    agreements = {ag.agreement_id: ag for ag in purchasing_service.list_rebate_agreements(company_id)}
    for accrual in (purchasing_service.list_rebate_accruals() if S.code == "PURCHASE" else []):
        ag = agreements.get(accrual.agreement_id)
        if ag is None or accrual.period_to < f.date_from or accrual.period_from > f.date_to:
            continue
        if f.supplier_id is not None and ag.supplier_detail_account_id != f.supplier_id:
            continue
        a = agg[ag.supplier_detail_account_id]
        key = "settled" if accrual.status_code == "SETTLED" else "accrued"
        a[key] += accrual.accrued_amount
    result = ReportResult([
        ("تامین‌کننده", TEXT), ("مبلغِ ناخالصِ خرید", MONEY), ("تخفیفِ فاکتور", MONEY), ("درصدِ تخفیف", PERCENT),
        ("ریبیتِ معوق (تسویه‌نشده)", MONEY), ("ریبیتِ تسویه‌شده", MONEY), ("جمعِ صرفه‌جویی", MONEY),
    ])
    for supplier_id, a in sorted(agg.items(), key=lambda kv: -(kv[1]["discount"] + kv[1]["accrued"] + kv[1]["settled"])):
        saving = a["discount"] + a["accrued"] + a["settled"]
        result.add([ctx.names.get(supplier_id, ""), a["gross"], a["discount"],
                    (a["discount"] * 100 / a["gross"]) if a["gross"] else _ZERO, a["accrued"], a["settled"], saving])
    return result


# ۲۲) تحویلِ به‌موقع (OTD)
def on_time_delivery(company_id: int, f: PurchaseFilters) -> ReportResult:
    S = _side(f)
    ctx = _ctx(company_id)
    agg: dict[int, dict] = defaultdict(lambda: {"docs": {}, "no_date": set()})
    for doc, _ln, _received, received_on in _received_orders(company_id, f, ctx):
        a = agg[doc.counterparty_detail_account_id]
        if doc.requested_delivery_date is None:
            a["no_date"].add(doc.document_id)
            continue
        a["docs"][doc.document_id] = (received_on - doc.requested_delivery_date).days
    result = ReportResult([
        ("تامین‌کننده", TEXT), ("سفارش‌هایِ دریافت‌شده", INT), ("به‌موقع", INT), ("با تاخیر", INT), ("درصدِ به‌موقع", PERCENT),
        ("میانگینِ روزِ تاخیر", DAYS), ("بدونِ تاریخِ تحویل", INT),
    ], no_total=set(), note="مبنا: «تاریخِ تحویلِ مورد انتظار»ِ سفارش در برابرِ تاریخِ تاییدِ رسید (یا اولین فاکتور).")
    for supplier_id, a in sorted(agg.items(), key=lambda kv: ctx.names.get(kv[0], "")):
        delays = list(a["docs"].values())
        on_time = sum(1 for d in delays if d <= 0)
        late = [d for d in delays if d > 0]
        result.add([ctx.names.get(supplier_id, ""), len(delays), on_time, len(late),
                    decimal.Decimal(on_time * 100) / len(delays) if delays else _ZERO,
                    round(sum(late) / len(late)) if late else 0, len(a["no_date"])])
    return result


# ۲۴) کیفیت / نرخِ برگشت
def quality_returns(company_id: int, f: PurchaseFilters) -> ReportResult:
    S = _side(f)
    from peecha.db.models.inventory import QcInspection

    ctx = _ctx(company_id)
    purchases, returns = _posted_purchase_and_returns(company_id, f, ctx)
    agg: dict[int, dict] = defaultdict(lambda: {"qty": _ZERO, "ret": _ZERO, "rejected": _ZERO, "inspected": 0})
    by_stock_line: dict[int, int] = {}
    for doc, ln in purchases:
        agg[doc.counterparty_detail_account_id]["qty"] += ln.quantity_base
        if ln.stock_document_line_id:
            by_stock_line[ln.stock_document_line_id] = doc.counterparty_detail_account_id
    for doc, ln in returns:
        agg[doc.counterparty_detail_account_id]["ret"] += ln.quantity_base
    if by_stock_line:
        with new_session() as session:
            for stock_line_id, rejected in session.execute(
                select(QcInspection.stock_document_line_id, QcInspection.rejected_quantity)
                .where(QcInspection.stock_document_line_id.in_(list(by_stock_line)))
            ):
                a = agg[by_stock_line[stock_line_id]]
                a["inspected"] += 1
                a["rejected"] += rejected or _ZERO
    result = ReportResult([
        ("تامین‌کننده", TEXT), ("مقدارِ خرید", QTY), ("مقدارِ برگشتی", QTY), ("نرخِ برگشت", PERCENT),
        ("تعدادِ بازرسیِ کیفیت", INT), ("مقدارِ ردشده در کنترلِ کیفیت", QTY), ("نرخِ ردی", PERCENT),
    ])
    for supplier_id, a in sorted(agg.items(), key=lambda kv: -(kv[1]["ret"] / kv[1]["qty"] if kv[1]["qty"] else 0)):
        result.add([ctx.names.get(supplier_id, ""), a["qty"], a["ret"], (a["ret"] * 100 / a["qty"]) if a["qty"] else _ZERO,
                    a["inspected"], a["rejected"], (a["rejected"] * 100 / a["qty"]) if a["qty"] else _ZERO])
    return result


# ۲۱) کارنامهٔ تامین‌کننده
def supplier_scorecard(company_id: int, f: PurchaseFilters) -> ReportResult:
    S = _side(f)
    ctx = _ctx(company_id)
    by_name = lambda rep: {r[0]: r for r in rep.rows}  # noqa: E731
    fill = by_name(fill_rate(company_id, f))
    otd = by_name(on_time_delivery(company_id, f))
    quality = by_name(quality_returns(company_id, f))
    prices = supplier_price_comparison(company_id, f)
    price_gap: dict[str, list[decimal.Decimal]] = defaultdict(list)
    for r in prices.rows:
        price_gap[r[1]].append(r[6])
    spend = by_name(purchases_by_supplier(company_id, f))
    names = set(fill) | set(otd) | set(quality) | set(price_gap) | set(spend)
    result = ReportResult([
        ("تامین‌کننده", TEXT), ("خالصِ خرید", MONEY), ("امتیازِ قیمت", PERCENT), ("دقتِ مقدار", PERCENT),
        ("تحویلِ به‌موقع", PERCENT), ("امتیازِ کیفیت", PERCENT), ("امتیازِ کل", PERCENT), ("رتبه", TEXT),
    ], no_total=set(), note="امتیازِ قیمت = ۱۰۰ − میانگینِ درصدِ گرانی نسبت به ارزان‌ترین؛ کیفیت = ۱۰۰ − نرخِ برگشت. "
                            "امتیازِ کل = میانگینِ شاخص‌هایِ موجود.")
    for name in sorted(names):
        price = (100 - sum(price_gap[name]) / len(price_gap[name])) if price_gap.get(name) else None
        fr = fill[name][5] if name in fill else None
        ot = otd[name][4] if name in otd and otd[name][1] else None
        ql = (100 - quality[name][3]) if name in quality and quality[name][1] else None
        parts = [decimal.Decimal(v) for v in (price, fr, ot, ql) if v is not None]
        overall = sum(parts, _ZERO) / len(parts) if parts else None
        grade = "" if overall is None else "عالی" if overall >= 90 else "خوب" if overall >= 75 else "متوسط" if overall >= 60 else "ضعیف"
        result.add([name, spend[name][7] if name in spend else _ZERO, price, fr, ot, ql, overall, grade])
    result.rows.sort(key=lambda r: -(r[6] or 0))
    result.refs = [None] * len(result.rows)
    return result


# ۲۸) پیش‌بینیِ پرداخت‌ها
def payment_forecast(company_id: int, f: PurchaseFilters) -> ReportResult:
    S = _side(f)
    from peecha.db.models.treasury import CheckStatus, IssuedCheck, ReceivedCheck
    from peecha.services import commercial_settlements as settlements_service

    ctx = _ctx(company_id)
    today = datetime.date.today()
    entries: list[tuple[datetime.date, str, str, str, decimal.Decimal, tuple[int, str] | None]] = []
    with new_session() as session:
        docs = {d.document_id: d for d in session.scalars(
            select(CommercialDocument).where(CommercialDocument.company_id == company_id,
                                             CommercialDocument.document_type_code == S.invoice,
                                             CommercialDocument.status_code == "POSTED"))}
        if S.code == "PURCHASE":
            checks = session.execute(
                select(IssuedCheck).join(CheckStatus, CheckStatus.status_id == IssuedCheck.status_id)
                .where(IssuedCheck.company_id == company_id, CheckStatus.code == "ISSUED")
            ).scalars().all()
        else:
            checks = session.execute(
                select(ReceivedCheck).join(CheckStatus, CheckStatus.status_id == ReceivedCheck.status_id)
                .where(ReceivedCheck.company_id == company_id, CheckStatus.code.in_(("IN_HAND", "DEPOSITED")))
            ).scalars().all()
    for status in settlements_service.list_unsettled_invoices(company_id, S.invoice):
        doc = docs.get(status.document_id)
        if doc is None or (f.supplier_id is not None and doc.counterparty_detail_account_id != f.supplier_id):
            continue
        entries.append((status.due_date or doc.document_date, "فاکتورِ تسویه‌نشده", f"فاکتور {doc.document_no}",
                        ctx.names.get(doc.counterparty_detail_account_id, ""), status.remaining_amount,
                        (doc.document_id, doc.document_type_code)))
    for chk in checks:
        if f.supplier_id is not None and chk.counterparty_detail_account_id != f.supplier_id:
            continue
        payee = getattr(chk, "payee_name", None) or getattr(chk, "drawer_name", None) or ""
        entries.append((chk.due_date, "چکِ پرداختنی" if S.code == "PURCHASE" else "چکِ دریافتیِ وصول‌نشده", f"چک {chk.check_no}",
                        ctx.names.get(chk.counterparty_detail_account_id, "") if chk.counterparty_detail_account_id else payee,
                        chk.amount, None))
    result = ReportResult([
        ("سررسید", DATE), ("بازه", TEXT), ("نوع", TEXT), ("مرجع", TEXT), ("طرفِ حساب", TEXT), ("مبلغ", MONEY), ("تجمعی", MONEY),
    ], no_total={6}, note="فاکتورهایِ خریدِ تسویه‌نشده (ماندهٔ باز) و چک‌هایِ پرداختنیِ وصول‌نشده، به ترتیبِ سررسید."
        if S.code == "PURCHASE" else "فاکتورهایِ فروشِ وصول‌نشده (ماندهٔ باز) و چک‌هایِ دریافتیِ نزدِ صندوق/بانک، به ترتیبِ سررسید.")
    running = _ZERO
    for due, kind, ref_label, party, amount, ref in sorted(entries, key=lambda e: e[0]):
        days = (due - today).days
        bucket = "سررسیدگذشته" if days < 0 else "این هفته" if days <= 7 else "هفتهٔ بعد" if days <= 14 else \
            "تا ۳۰ روز" if days <= 30 else "تا ۹۰ روز" if days <= 90 else "بعد از ۹۰ روز"
        running += amount
        result.add([due, bucket, kind, ref_label, party, amount, running], ref)
    return result


# ۳۰) پیش‌پرداخت‌ها و سفارش‌هایِ در جریانِ پرداخت
def prepayments(company_id: int, f: PurchaseFilters) -> ReportResult:
    S = _side(f)
    from peecha.services import order_tracking as order_tracking_service

    ctx = _ctx(company_id)
    result = ReportResult([
        ("بخش", TEXT), ("طرف/سفارش", TEXT), ("شرح", TEXT), ("وضعیت", TEXT), ("پرداخت‌شده", MONEY), ("برگشت/تسویه", MONEY),
        ("مانده", MONEY),
    ], note="پیش‌پرداخت = تامین‌کنندهٔ دارایِ ماندهٔ بدهکار (طلبِ ما)؛ سفارش‌هایِ «مدیریتِ سفارشات» با پرداخت‌هایِ ثبت‌شده.")
    try:
        balances = _balances(company_id, PurchaseFilters(datetime.date(1900, 1, 1), f.date_to, f.supplier_id, side=f.side))
    except ValueError:
        balances = {}
    for supplier_id, a in balances.items():
        closing = a["open"] + S.sign * (a["credit"] - a["debit"])
        if closing < 0:
            result.add(["پیش‌پرداختِ تامین‌کننده" if S.code == "PURCHASE" else "پیش‌دریافت از مشتری",
                        ctx.names.get(supplier_id, ""), "", "", a["debit"], a["credit"], -closing])
    for order in (order_tracking_service.list_orders(company_id) if S.code == "PURCHASE" else []):
        payments = [p for p in order_tracking_service.list_order_payments(company_id, order.detail_account_id)
                    if p.document_date <= f.date_to]
        paid = sum((p.debit for p in payments), _ZERO)
        back = sum((p.credit for p in payments), _ZERO)
        if not payments:
            continue
        result.add(["سفارشِ در جریان", f"{order.code} — {order.name or ''}", order.description or "",
                    "باز" if order.status_code == "OPEN" else "بسته", paid, back, paid - back])
    return result


# ۳۲) کالاهایِ قابلِ‌خرید و واحدها
def purchasable_items(company_id: int, f: PurchaseFilters) -> ReportResult:
    S = _side(f)
    from peecha.db.models.inventory import ItemSupplier
    from peecha.services import unit_conversion as uc

    ctx = _ctx(company_id)
    categories = {c.category_id: c.name for c in catalog_service.list_categories(company_id)}
    last_price: dict[int, tuple[decimal.Decimal, datetime.date]] = {}
    for doc, ln in _lines(company_id, (S.invoice,), ("POSTED",), None, ctx, dated=False):
        last_price[ln.item_id] = (_base_price(ln), doc.document_date)
    with new_session() as session:
        preferred = {
            item_id: supplier_id for item_id, supplier_id in session.execute(
                select(ItemSupplier.item_id, ItemSupplier.supplier_detail_account_id).where(ItemSupplier.is_preferred.is_(True))
            )
        }
    result = ReportResult([
        ("کد", TEXT), ("نام", TEXT), ("گروه", TEXT), ("واحدِ پایه", TEXT), ("واحدهایِ خرید (ضریب)", TEXT),
        ("واحدِ پیش‌فرضِ خرید", TEXT), ("زمانِ تحویل (روز)", TEXT), ("حداقلِ سفارش", TEXT), ("تامین‌کنندهٔ ترجیحی", TEXT),
        ("آخرین فیِ خرید (پایه)", MONEY), ("تاریخِ آخرین خرید", DATE), ("ردیابی", TEXT),
    ], no_total={9})
    for item in catalog_service.list_items(company_id, transactable_only=True):
        if not item.is_purchasable or (f.item_id is not None and item.item_id != f.item_id) \
                or (f.category_id is not None and item.category_id != f.category_id):
            continue
        units = [u for u in uc.get_item_units(item.item_id, purpose="PURCHASE") if not u.is_base]
        default_unit = next((u.name for u in units if u.is_default_purchase), ctx.uom_names.get(item.base_uom_id, ""))
        tracking = "، ".join(t for t, on in (("سریال", item.track_serial), ("بچ", item.track_batch), ("انقضا", item.track_expiry)) if on)
        price = last_price.get(item.item_id)
        result.add([
            item.code, item.name or "", categories.get(item.category_id, ""), ctx.uom_names.get(item.base_uom_id, ""),
            "، ".join(f"{u.name} ({numerals_factor(u.factor)})" for u in units), default_unit,
            str(item.purchase_lead_time_days or ""), str(item.purchase_min_order_qty.normalize()) if item.purchase_min_order_qty else "",
            ctx.names.get(preferred.get(item.item_id), "") if preferred.get(item.item_id) else "",
            price[0] if price else None, price[1] if price else None, tracking,
        ])
    return result


def numerals_factor(value: decimal.Decimal) -> str:
    return format(value.normalize(), "f")


# ۳۳) فهرستِ قیمتِ تامین‌کنندگان
def supplier_price_lists(company_id: int, f: PurchaseFilters) -> ReportResult:
    S = _side(f)
    from peecha.db.models.inventory import ItemSupplier
    from peecha.services import commercial_pricing as pricing_service

    ctx = _ctx(company_id)
    result = ReportResult([
        ("منبع", TEXT), ("فهرست/تامین‌کننده", TEXT), ("کالا", TEXT), ("واحد", TEXT), ("حداقلِ مقدار", QTY), ("فی", MONEY),
        ("اعتبار از", DATE), ("اعتبار تا", DATE), ("کدِ کالا نزدِ تامین‌کننده", TEXT), ("زمانِ تحویل", TEXT), ("ترجیحی", TEXT),
    ], no_total={4, 5})
    for price_list in pricing_service.list_price_lists(company_id, "PURCHASE"):
        for row in pricing_service.list_price_list_items(price_list.price_list_id):
            if (f.item_id is not None and row.item_id != f.item_id) or (
                    f.category_id is not None and getattr(ctx.items.get(row.item_id), "category_id", None) != f.category_id):
                continue
            result.add(["فهرستِ قیمتِ خرید", price_list.name, ctx.item_label(row.item_id), ctx.uom_names.get(row.uom_id, ""),
                        row.min_quantity, row.unit_price, price_list.valid_from, price_list.valid_to, "", "", ""])
    with new_session() as session:
        links = list(session.scalars(select(ItemSupplier)))
    for link in links:
        if link.item_id not in ctx.items or (f.supplier_id is not None and link.supplier_detail_account_id != f.supplier_id) \
                or (f.item_id is not None and link.item_id != f.item_id):
            continue
        result.add(["تامین‌کنندهٔ کالا", ctx.names.get(link.supplier_detail_account_id, ""), ctx.item_label(link.item_id), "",
                    link.min_order_qty, None, None, None, link.supplier_sku or "",
                    f"{link.lead_time_days} روز" if link.lead_time_days else "", "★" if link.is_preferred else ""])
    return result


# ۳۴) قراردادهایِ ریبیت
def rebate_agreements(company_id: int, f: PurchaseFilters) -> ReportResult:
    S = _side(f)
    from peecha.services import commercial_purchasing as purchasing_service

    ctx = _ctx(company_id)
    accruals = purchasing_service.list_rebate_accruals()
    result = ReportResult([
        ("تامین‌کننده", TEXT), ("کالا", TEXT), ("مبنا", TEXT), ("پله‌ها (حداقلِ خرید ← درصد)", TEXT), ("اعتبار از", DATE),
        ("اعتبار تا", DATE), ("وضعیت", TEXT), ("معوق", MONEY), ("تسویه‌شده", MONEY),
    ])
    for ag in purchasing_service.list_rebate_agreements(company_id):
        if f.supplier_id is not None and ag.supplier_detail_account_id != f.supplier_id:
            continue
        tiers = purchasing_service.list_rebate_tiers(ag.agreement_id)
        mine = [a for a in accruals if a.agreement_id == ag.agreement_id]
        result.add([
            ctx.names.get(ag.supplier_detail_account_id, ""), ctx.item_label(ag.item_id) if ag.item_id else "همهٔ کالاها",
            "درصدِ ثابت" if ag.rebate_basis_code == "FLAT_PERCENT" else "پلکانیِ حجمی",
            "؛ ".join(f"{t.min_purchase_amount.normalize():f} ← {t.rebate_percent.normalize():f}٪" for t in tiers),
            ag.valid_from, ag.valid_to, "فعال" if ag.status_code == "ACTIVE" else ag.status_code,
            sum((a.accrued_amount for a in mine if a.status_code != "SETTLED"), _ZERO),
            sum((a.accrued_amount for a in mine if a.status_code == "SETTLED"), _ZERO),
        ])
    return result


# ۳۵) انبارها و انباردارِ مسئول
def warehouses_and_keepers(company_id: int, f: PurchaseFilters) -> ReportResult:
    S = _side(f)
    from peecha.db.models.security import User

    queue = documents_service.list_purchase_order_goods_receipt_queue(company_id)
    pending: dict[int | None, int] = defaultdict(int)
    for doc in queue:
        if doc.warehouse_approved_at is None:
            pending[doc.warehouse_id] += 1
    with new_session() as session:
        rows = session.execute(
            select(Warehouse, User.full_name).outerjoin(User, User.user_id == Warehouse.manager_user_id)
            .where(Warehouse.company_id == company_id).order_by(Warehouse.code)
        ).all()
    result = ReportResult([
        ("کد", TEXT), ("نام", TEXT), ("انباردارِ مسئول", TEXT), ("پیش‌فرض", TEXT), ("فعال", TEXT), ("موجودیِ منفی مجاز", TEXT),
        ("نشانی", TEXT), ("رسید/حوالهٔ در انتظار", INT),
    ], note="رسید/حوالهٔ هر انبار فقط توسطِ انباردارِ مسئولِ همان انبار (یا مدیر) تایید می‌شود.")
    for wh, keeper in rows:
        if f.warehouse_id is not None and wh.warehouse_id != f.warehouse_id:
            continue
        result.add([wh.code, wh.name, keeper or "— (فقط مدیر)", "بله" if wh.is_default else "", "بله" if wh.is_active else "خیر",
                    "بله" if wh.allow_negative_stock else "", wh.address or "", pending.get(wh.warehouse_id, 0)])
    return result


# =====================================================================
# R236: دفترِ اسناد (خرید و فروش) + گزارش‌هایِ اختصاصیِ فروش
# =====================================================================
_STATUS_LABELS = {**_STAGE_LABELS, "CANCELLED": "لغوشده", "CORRECTED": "اصلاح‌شده"}


def _documents(company_id: int, f: PurchaseFilters, doc_type: str, ctx: _Ctx) -> list[tuple[CommercialDocument, list]]:
    pairs = _lines(company_id, (doc_type,), tuple(_STATUS_LABELS), f, ctx)
    grouped: dict[int, tuple[CommercialDocument, list]] = {}
    for doc, ln in pairs:
        grouped.setdefault(doc.document_id, (doc, []))[1].append(ln)
    return list(grouped.values())


def _register(company_id: int, f: PurchaseFilters, doc_type: str) -> ReportResult:
    ctx = _ctx(company_id)
    docs = _documents(company_id, f, doc_type, ctx)
    is_invoice = doc_type.endswith("_INVOICE")
    columns = [
        ("شماره", INT), ("تاریخ", DATE), ("تامین‌کننده", TEXT), ("وضعیت", TEXT), ("انبار", TEXT), ("شمارهٔ مرجع", TEXT),
        ("تعدادِ ردیف", INT), ("مبلغِ کالا", MONEY), ("تخفیف", MONEY), ("مالیات", MONEY), ("جمعِ کل", MONEY),
    ]
    settled: dict[int, decimal.Decimal] = defaultdict(lambda: _ZERO)
    converted: dict[int, decimal.Decimal] = {}
    if is_invoice:
        columns += [("تسویه‌شده", MONEY), ("مانده", MONEY), ("سررسید", DATE)]
        with new_session() as session:
            ids = [d.document_id for d, _l in docs]
            if ids:
                for invoice_id, amount in session.execute(
                    select(InvoiceSettlement.invoice_document_id, InvoiceSettlement.amount)
                    .where(InvoiceSettlement.invoice_document_id.in_(ids))
                ):
                    settled[invoice_id] += amount
    else:
        columns += [("درصدِ تبدیل به فاکتور", PERCENT)]
        invoice_type = doc_type.replace("_ORDER", "_INVOICE").replace("_PROFORMA", "_INVOICE")
        line_ids = [ln.line_id for _d, lines in docs for ln in lines]
        invoiced = _invoiced_base_by_source_line(company_id, invoice_type, line_ids)
        for doc, lines in docs:
            ordered = sum((ln.quantity_base for ln in lines), _ZERO)
            billed = sum((invoiced.get(ln.line_id, _ZERO) for ln in lines), _ZERO)
            converted[doc.document_id] = (billed * 100 / ordered) if ordered else _ZERO
    result = ReportResult(columns, no_total={0})
    for doc, lines in sorted(docs, key=lambda dl: (dl[0].document_date, dl[0].document_no)):
        row = [
            doc.document_no, doc.document_date, ctx.names.get(doc.counterparty_detail_account_id, ""),
            _STATUS_LABELS.get(doc.status_code, doc.status_code),
            ctx.warehouses.get(doc.warehouse_id, "") if doc.warehouse_id else "", doc.reference_no or "", len(lines),
            doc.subtotal_amount, doc.discount_amount, doc.tax_amount, doc.total_amount,
        ]
        if is_invoice:
            paid = settled[doc.document_id] if doc.status_code == "POSTED" else _ZERO
            row += [paid, (doc.total_amount - paid) if doc.status_code == "POSTED" else _ZERO, doc.due_date]
        else:
            row += [converted.get(doc.document_id, _ZERO)]
        result.add(row, (doc.document_id, doc.document_type_code))
    if not is_invoice:
        result.no_total.add(len(columns) - 1)
    return result


def invoice_register(company_id: int, f: PurchaseFilters) -> ReportResult:
    S = _side(f)
    return _register(company_id, f, S.invoice)


def order_register(company_id: int, f: PurchaseFilters) -> ReportResult:
    S = _side(f)
    return _register(company_id, f, S.order)


def proforma_register(company_id: int, f: PurchaseFilters) -> ReportResult:
    S = _side(f)
    return _register(company_id, f, S.proforma)


def invoice_lines_register(company_id: int, f: PurchaseFilters) -> ReportResult:
    S = _side(f)
    ctx = _ctx(company_id)
    pairs = _lines(company_id, (S.invoice,), ("CONFIRMED", "APPROVED", "POSTED"), f, ctx)
    result = ReportResult([
        ("تاریخ", DATE), ("شمارهٔ فاکتور", INT), ("تامین‌کننده", TEXT), ("وضعیت", TEXT), ("کالا", TEXT), ("واحد", TEXT),
        ("مقدار", QTY), ("مقدار (پایه)", QTY), ("فی", MONEY), ("تخفیف", MONEY), ("مالیات", MONEY), ("مبلغِ خالص", MONEY),
        ("انبار", TEXT),
    ], no_total={1, 8})
    for doc, ln in pairs:
        result.add([
            doc.document_date, doc.document_no, ctx.names.get(doc.counterparty_detail_account_id, ""),
            _STATUS_LABELS.get(doc.status_code, doc.status_code), ctx.item_label(ln.item_id), ctx.uom_names.get(ln.uom_id, ""),
            ln.quantity, ln.quantity_base, ln.unit_price, ln.discount_amount or _ZERO, ln.tax_amount or _ZERO, _net(ln),
            ctx.warehouses.get(ln.warehouse_id or doc.warehouse_id, "") if (ln.warehouse_id or doc.warehouse_id) else "",
        ], (doc.document_id, doc.document_type_code))
    return result


def _line_costs(stock_line_ids: list[int]) -> dict[int, decimal.Decimal]:
    from peecha.db.models.inventory import StockLedger

    if not stock_line_ids:
        return {}
    with new_session() as session:
        out: dict[int, decimal.Decimal] = defaultdict(lambda: _ZERO)
        for line_id, cost in session.execute(
            select(StockLedger.stock_document_line_id, StockLedger.total_cost)
            .where(StockLedger.stock_document_line_id.in_(stock_line_ids))
        ):
            out[line_id] += cost or _ZERO
    return out


def _gross_profit(company_id: int, f: PurchaseFilters, key) -> dict:
    ctx = _ctx(company_id)
    sales = _lines(company_id, ("SALES_INVOICE",), ("POSTED",), f, ctx)
    returns = _lines(company_id, ("SALES_RETURN",), ("POSTED",), f, ctx)
    costs = _line_costs([ln.stock_document_line_id for _d, ln in sales + returns if ln.stock_document_line_id])
    agg: dict = defaultdict(lambda: {"qty": _ZERO, "revenue": _ZERO, "cost": _ZERO, "docs": set()})
    for doc, ln in sales:
        a = agg[key(doc, ln)]
        a["qty"] += ln.quantity_base
        a["revenue"] += _net(ln)
        a["cost"] += costs.get(ln.stock_document_line_id, _ZERO)
        a["docs"].add(doc.document_id)
    for doc, ln in returns:
        a = agg[key(doc, ln)]
        a["qty"] -= ln.quantity_base
        a["revenue"] -= _net(ln)
        a["cost"] -= costs.get(ln.stock_document_line_id, _ZERO)
    return ctx, agg


def _gross_profit_result(first_header: str, rows) -> ReportResult:
    result = ReportResult([
        (first_header, TEXT), ("تعدادِ فاکتور", INT), ("مقدارِ خالص (پایه)", QTY), ("فروشِ خالص", MONEY),
        ("بهایِ تمام‌شده", MONEY), ("سودِ ناخالص", MONEY), ("حاشیهٔ سود", PERCENT),
    ], note="فروشِ خالص = فاکتورها منهایِ برگشت از فروش (بدونِ مالیات)؛ بها از دفترِ انبار (میانگین/FIFO).")
    for label, a in rows:
        profit = a["revenue"] - a["cost"]
        result.add([label, len(a["docs"]), a["qty"], a["revenue"], a["cost"], profit,
                    (profit * 100 / a["revenue"]) if a["revenue"] else _ZERO])
    return result


def gross_profit_by_item(company_id: int, f: PurchaseFilters) -> ReportResult:
    ctx, agg = _gross_profit(company_id, f, lambda doc, ln: ln.item_id)
    rows = sorted(((ctx.item_label(k), a) for k, a in agg.items()), key=lambda r: -(r[1]["revenue"] - r[1]["cost"]))
    return _gross_profit_result("کالا", rows)


def gross_profit_by_customer(company_id: int, f: PurchaseFilters) -> ReportResult:
    ctx, agg = _gross_profit(company_id, f, lambda doc, ln: doc.counterparty_detail_account_id)
    rows = sorted(((ctx.names.get(k, ""), a) for k, a in agg.items()), key=lambda r: -(r[1]["revenue"] - r[1]["cost"]))
    return _gross_profit_result("مشتری", rows)


def sales_by_rep(company_id: int, f: PurchaseFilters) -> ReportResult:
    ctx = _ctx(company_id)
    sales = _lines(company_id, ("SALES_INVOICE",), ("POSTED",), f, ctx)
    returns = _lines(company_id, ("SALES_RETURN",), ("POSTED",), f, ctx)
    agg: dict = defaultdict(lambda: {"amount": _ZERO, "returns": _ZERO, "docs": set(), "customers": set()})
    for doc, ln in sales:
        a = agg[doc.sales_rep_detail_account_id]
        a["amount"] += _net(ln)
        a["docs"].add(doc.document_id)
        a["customers"].add(doc.counterparty_detail_account_id)
    for doc, ln in returns:
        agg[doc.sales_rep_detail_account_id]["returns"] += _net(ln)
    total = sum((a["amount"] - a["returns"] for a in agg.values()), _ZERO)
    result = ReportResult([
        ("فروشنده/ویزیتور", TEXT), ("تعدادِ فاکتور", INT), ("تعدادِ مشتری", INT), ("فروش", MONEY), ("برگشت", MONEY),
        ("فروشِ خالص", MONEY), ("میانگینِ هر فاکتور", MONEY), ("سهم از کل", PERCENT),
    ], no_total={2, 6})
    for rep_id, a in sorted(agg.items(), key=lambda kv: -(kv[1]["amount"] - kv[1]["returns"])):
        net = a["amount"] - a["returns"]
        result.add([ctx.names.get(rep_id, "— بدونِ فروشنده —") if rep_id else "— بدونِ فروشنده —", len(a["docs"]),
                    len(a["customers"]), a["amount"], a["returns"], net,
                    (a["amount"] / len(a["docs"])) if a["docs"] else _ZERO, (net * 100 / total) if total else _ZERO])
    return result


def sellable_items(company_id: int, f: PurchaseFilters) -> ReportResult:
    from peecha.services import unit_conversion as uc

    ctx = _ctx(company_id)
    categories = {c.category_id: c.name for c in catalog_service.list_categories(company_id)}
    last_price: dict[int, tuple[decimal.Decimal, datetime.date]] = {}
    for doc, ln in _lines(company_id, ("SALES_INVOICE",), ("POSTED",), None, ctx, dated=False):
        last_price[ln.item_id] = (_base_price(ln), doc.document_date)
    result = ReportResult([
        ("کد", TEXT), ("نام", TEXT), ("گروه", TEXT), ("واحدِ پایه", TEXT), ("واحدهایِ فروش (ضریب)", TEXT),
        ("واحدِ پیش‌فرضِ فروش", TEXT), ("آخرین فیِ فروش (پایه)", MONEY), ("تاریخِ آخرین فروش", DATE), ("ردیابی", TEXT),
    ], no_total={6})
    for item in catalog_service.list_items(company_id, transactable_only=True):
        if not item.is_sellable or (f.item_id is not None and item.item_id != f.item_id) \
                or (f.category_id is not None and item.category_id != f.category_id):
            continue
        units = [u for u in uc.get_item_units(item.item_id, purpose="SALES") if not u.is_base]
        default_unit = next((u.name for u in units if u.is_default_sales), ctx.uom_names.get(item.base_uom_id, ""))
        tracking = "، ".join(t for t, on in (("سریال", item.track_serial), ("بچ", item.track_batch), ("انقضا", item.track_expiry)) if on)
        price = last_price.get(item.item_id)
        result.add([
            item.code, item.name or "", categories.get(item.category_id, ""), ctx.uom_names.get(item.base_uom_id, ""),
            "، ".join(f"{u.name} ({numerals_factor(u.factor)})" for u in units), default_unit,
            price[0] if price else None, price[1] if price else None, tracking,
        ])
    return result


def sales_price_lists(company_id: int, f: PurchaseFilters) -> ReportResult:
    from peecha.services import commercial_pricing as pricing_service

    ctx = _ctx(company_id)
    result = ReportResult([
        ("فهرستِ قیمت", TEXT), ("کانال", TEXT), ("کالا", TEXT), ("واحد", TEXT), ("حداقلِ مقدار", QTY), ("فی", MONEY),
        ("اعتبار از", DATE), ("اعتبار تا", DATE), ("فعال", TEXT),
    ], no_total={4, 5})
    for price_list in pricing_service.list_price_lists(company_id, "SALES"):
        for row in pricing_service.list_price_list_items(price_list.price_list_id):
            if (f.item_id is not None and row.item_id != f.item_id) or (
                    f.category_id is not None and getattr(ctx.items.get(row.item_id), "category_id", None) != f.category_id):
                continue
            result.add([price_list.name, price_list.channel_code or "", ctx.item_label(row.item_id), ctx.uom_names.get(row.uom_id, ""),
                        row.min_quantity, row.unit_price, price_list.valid_from, price_list.valid_to,
                        "بله" if price_list.is_active else "خیر"])
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
    date_mode: str = "range"  # range | as_of | none
    group: str = ""
    # R238: ((کلید، برچسب، ((مقدار، برچسب)، ...))، ...) -- اولین مقدار پیش‌فرض است
    options: tuple = ()


_OP, _AN, _PR, _VP, _FI, _MD = "عملیاتی", "تحلیلِ خرید", "قیمت و هزینه", "ارزیابیِ تامین‌کننده", "مالی و بدهی", "اطلاعاتِ پایه"
_ALL = ("supplier", "item", "category", "warehouse")

REPORTS: list[ReportDef] = [
    # --- عملیاتی
    ReportDef("REG_INVOICE", "دفترِ فاکتورهایِ خرید", invoice_register, _ALL,
              "همهٔ فاکتورهایِ خریدِ بازه با وضعیت، مبلغ، تسویه‌شده و مانده.", group=_OP),
    ReportDef("REG_INVOICE_LINES", "ریزِ اقلامِ فاکتورهایِ خرید", invoice_lines_register, _ALL,
              "ردیف‌به‌ردیفِ فاکتورهایِ خرید (تاییدشده/ثبت‌شده) با مقدار، فی، تخفیف و مالیات.", group=_OP),
    ReportDef("REG_ORDER", "دفترِ سفارش‌هایِ خرید", order_register, _ALL,
              "همهٔ سفارش‌هایِ خریدِ بازه با وضعیت، مبلغ و درصدِ تبدیل به فاکتور.", group=_OP),
    ReportDef("REG_PROFORMA", "دفترِ پیش‌فاکتورهایِ خرید", proforma_register, _ALL,
              "همهٔ پیش‌فاکتورهایِ خریدِ بازه با وضعیت، مبلغ و درصدِ تبدیل به فاکتور.", group=_OP),
    ReportDef("OPEN_PO", "سفارش‌هایِ خریدِ باز", open_purchase_orders, _ALL,
              "سفارش‌هایی که هنوز کامل فاکتور نشده‌اند -- مقدارِ سفارش، رسیده، فاکتورشده و مانده.", group=_OP),
    ReportDef("OVERDUE", "کالاهایِ در راه / معوق", overdue_orders, _ALL,
              "سفارش‌هایی که هنوز کامل نرسیده‌اند، با روزِ تاخیر نسبت به «تاریخِ تحویلِ مورد انتظار».", "as_of", _OP),
    ReportDef("PENDING_RECEIPTS", "رسیدهایِ در انتظارِ انبار", pending_receipts, _ALL,
              "سفارش‌ها/امانی‌هایی که منتظرِ تاییدِ انباردار هستند و چند روز است معطل مانده‌اند.", "none", _OP),
    ReportDef("GRIR", "رسیده ولی فاکتورنشده (GR/IR)", received_not_invoiced, _ALL,
              "کالایِ تحویل‌گرفته‌ای که فاکتورش هنوز صادر نشده -- بدهیِ شناسایی‌نشده تا «تا تاریخ».", "as_of", _OP),
    ReportDef("PENDING_INVOICES", "فاکتورهایِ خریدِ در انتظار", pending_invoices, _ALL,
              "فاکتور/پیش‌فاکتور/برگشتِ خریدی که در یکی از مراحل مانده‌اند.", "none", _OP),
    ReportDef("CONSIGNMENTS", "امانی‌هایِ ورودیِ تسویه‌نشده", open_consignments, _ALL,
              "کالایِ امانیِ هر تامین‌کننده: دریافتی، تسویه‌شده (خرید)، برگشتی و ماندهٔ امانی.", "none", _OP),
    ReportDef("RETURNS", "برگشت به تامین‌کننده", purchase_returns, _ALL,
              "برگشت‌هایِ خرید به تفکیکِ کالا/تامین‌کننده با علتِ برگشت.", group=_OP),
    # --- تحلیلی
    ReportDef("BY_ITEM", "خرید به تفکیکِ کالا", purchases_by_item, _ALL,
              "مقدار، مبلغ، برگشتی و میانگین/کمترین/بیشترین/آخرین فیِ هر کالا در بازه.", group=_AN),
    ReportDef("BY_SUPPLIER", "خرید به تفکیکِ تامین‌کننده", purchases_by_supplier, _ALL,
              "حجمِ خرید، تخفیف، مالیات، برگشتی و سهمِ هر تامین‌کننده.", group=_AN),
    ReportDef("BY_CATEGORY", "خرید به تفکیکِ گروهِ کالا", purchases_by_category, _ALL,
              "تحلیلِ هزینه (Spend Analysis) به تفکیکِ گروهِ کالا.", group=_AN),
    ReportDef("BY_COST_CENTER", "خرید به تفکیکِ مرکزِ هزینه/پروژه", purchases_by_cost_center, _ALL,
              "هزینهٔ خریدِ هر مرکزِ هزینه/پروژه (از سرِ فاکتور).", group=_AN),
    ReportDef("MONTHLY", "روندِ ماهانهٔ خرید", monthly_trend, _ALL,
              "خرید/برگشت/خالصِ هر ماهِ شمسی و درصدِ تغییر نسبت به ماهِ قبل.", group=_AN),
    ReportDef("ABC", "تحلیلِ ABC خرید (پارتو)", abc_analysis, _ALL,
              "کالاهایی که بیشترِ هزینهٔ خرید را می‌سازند -- کلاسِ A/B/C.", group=_AN),
    ReportDef("CONCENTRATION", "تمرکزِ تامین (ریسکِ تک‌منبعی)", supply_concentration, ("supplier", "item", "category"),
              "کالاهایی که فقط از یک تامین‌کننده خریده شده‌اند یا سهمِ یک تامین‌کننده خیلی بالاست.", group=_AN),
    # --- قیمت و هزینه
    ReportDef("PRICE_HISTORY", "تاریخچهٔ قیمتِ خرید", price_history, _ALL,
              "فیِ هر خرید به واحدِ پایه و درصدِ تغییر نسبت به خریدِ قبلیِ همان کالا.", group=_PR),
    ReportDef("PRICE_COMPARE", "مقایسهٔ قیمتِ تامین‌کنندگان", supplier_price_comparison, ("supplier", "item", "category"),
              "آخرین/میانگین/کمترین فیِ هر تامین‌کننده برایِ هر کالا؛ ★ = ارزان‌ترین آخرین قیمت.", group=_PR),
    ReportDef("PPV", "انحرافِ قیمتِ خرید (PPV)", purchase_price_variance, _ALL,
              "اختلافِ فیِ فاکتور با فیِ سفارشِ مبدا (یا آخرین خرید) و اثرِ ریالیِ آن.", group=_PR),
    ReportDef("CORRECTIONS", "اصلاحیه‌هایِ فاکتور و مغایرتِ بها", invoice_corrections, ("supplier",),
              "فاکتورهایِ خریدِ اصلاح‌شده، اختلافِ مبلغ و اثرِ آن بر موجودی و حسابِ مغایرتِ بها.", group=_PR),
    ReportDef("LANDED_COST", "هزینه‌هایِ جانبیِ خرید (Landed Cost)", landed_costs, ("supplier",),
              "حمل/گمرک/بیمه/... ثبت‌شده رویِ فاکتورهایِ خرید و درصدِ آن از مبلغِ کالا.", group=_PR),
    ReportDef("SAVINGS", "تخفیف‌ها و ریبیتِ خرید", discounts_and_rebates, ("supplier", "item", "category", "warehouse"),
              "تخفیفِ گرفته‌شده در فاکتورها و ریبیتِ معوق/تسویه‌شدهٔ هر تامین‌کننده.", group=_PR),
    # --- ارزیابیِ تامین‌کننده
    ReportDef("SCORECARD", "کارنامهٔ تامین‌کننده", supplier_scorecard, ("supplier", "item", "category"),
              "امتیازِ ترکیبیِ قیمت، دقتِ مقدار، تحویلِ به‌موقع و کیفیت.", group=_VP),
    ReportDef("OTD", "تحویلِ به‌موقع (OTD)", on_time_delivery, _ALL,
              "درصدِ سفارش‌هایی که تا «تاریخِ تحویلِ مورد انتظار» رسیده‌اند.", group=_VP),
    ReportDef("FILL_RATE", "دقتِ مقدارِ تحویلِ تامین‌کنندگان", fill_rate, _ALL,
              "مقدارِ دریافتی در برابرِ مقدارِ سفارش، به تفکیکِ تامین‌کننده.", group=_VP),
    ReportDef("QUALITY", "کیفیت / نرخِ برگشت", quality_returns, _ALL,
              "درصدِ کالایِ برگشتی و ردشده در کنترلِ کیفیت، به تفکیکِ تامین‌کننده.", group=_VP),
    ReportDef("LEAD_TIME", "زمانِ تحویل (Lead Time)", lead_time, _ALL,
              "فاصلهٔ تاریخِ سفارش تا رسید (یا اولین فاکتور) -- میانگین/کمترین/بیشترین.", group=_VP),
    # --- مالی و بدهی
    ReportDef("BALANCES", "ماندهٔ حسابِ تامین‌کنندگان", supplier_balances, ("supplier",),
              "ماندهٔ اول/گردش/ماندهٔ پایانِ دورهٔ هر تامین‌کننده از دفترِ کل.", group=_FI),
    ReportDef("AGING", "سنی‌کردنِ بدهی (AP Aging)", ap_aging, ("supplier",),
              "ماندهٔ فاکتورهایِ باز به تفکیکِ روزهایِ گذشته از سررسید، تا «تا تاریخ».", "as_of", _FI),
    ReportDef("FORECAST", "پیش‌بینیِ پرداخت‌ها", payment_forecast, ("supplier",),
              "سررسیدِ فاکتورهایِ تسویه‌نشده و چک‌هایِ پرداختنی در روزها/هفته‌هایِ آینده.", "none", _FI),
    ReportDef("STATEMENT", "صورت‌حسابِ تامین‌کننده", supplier_statement, ("supplier",),
              "ریزِ گردشِ حسابِ یک تامین‌کننده با ماندهٔ جاری.", group=_FI),
    ReportDef("PREPAYMENTS", "پیش‌پرداخت‌ها و سفارش‌هایِ در جریان", prepayments, ("supplier",),
              "تامین‌کنندگانِ دارایِ پیش‌پرداخت و پرداخت‌هایِ سفارش‌هایِ «مدیریتِ سفارشات».", "as_of", _FI),
    # --- اطلاعاتِ پایه
    ReportDef("SUPPLIERS", "فهرستِ تامین‌کنندگان", supplier_list, ("supplier",),
              "اطلاعاتِ پایهٔ تامین‌کنندگان با خریدِ بازه، آخرین خرید و ماندهٔ حساب.", group=_MD),
    ReportDef("ITEMS", "کالاهایِ قابلِ‌خرید و واحدها", purchasable_items, ("item", "category"),
              "واحدهایِ خرید و ضرایب، واحدِ پیش‌فرض، زمانِ تحویل، تامین‌کنندهٔ ترجیحی و آخرین فی.", "none", _MD),
    ReportDef("PRICE_LISTS", "فهرستِ قیمتِ تامین‌کنندگان", supplier_price_lists, ("supplier", "item", "category"),
              "فهرست‌هایِ قیمتِ خرید و تامین‌کنندگانِ تعریف‌شدهٔ هر کالا (کد/زمانِ تحویل/ترجیحی).", "none", _MD),
    ReportDef("REBATES", "قراردادهایِ ریبیت", rebate_agreements, ("supplier",),
              "قراردادهایِ ریبیت/تخفیفِ پلکانیِ تامین‌کنندگان با مبلغِ معوق و تسویه‌شده.", "none", _MD),
    ReportDef("WAREHOUSES", "انبارها و انباردارِ مسئول", warehouses_and_keepers, ("warehouse",),
              "انباردارِ هر انبار برایِ کنترلِ دسترسیِ رسید/حواله و تعدادِ سندِ در انتظار.", "none", _MD),
]

REPORTS_BY_CODE = {r.code: r for r in REPORTS}

# ---------------------------------------------------------------------
# R236: گزارشاتِ فروش -- همان موتور با side=SALES + گزارش‌هایِ اختصاصیِ فروش
# ---------------------------------------------------------------------
_SOP, _SAN, _SPR, _SDL, _SFI = "عملیاتی", "تحلیلِ فروش", "سود، قیمت و تخفیف", "عملکردِ تحویل", "مالی و مطالبات"
_CALL = ("supplier", "item", "category", "warehouse")

SALES_REPORTS: list[ReportDef] = [
    ReportDef("REG_INVOICE", "دفترِ فاکتورهایِ فروش", invoice_register, _CALL,
              "همهٔ فاکتورهایِ فروشِ بازه با وضعیت، مبلغ، وصول‌شده و مانده.", group=_SOP),
    ReportDef("REG_INVOICE_LINES", "ریزِ اقلامِ فاکتورهایِ فروش", invoice_lines_register, _CALL,
              "ردیف‌به‌ردیفِ فاکتورهایِ فروش (تاییدشده/ثبت‌شده) با مقدار، فی، تخفیف و مالیات.", group=_SOP),
    ReportDef("REG_ORDER", "دفترِ سفارش‌هایِ فروش", order_register, _CALL,
              "همهٔ سفارش‌هایِ فروشِ بازه با وضعیت، مبلغ و درصدِ تبدیل به فاکتور.", group=_SOP),
    ReportDef("REG_PROFORMA", "دفترِ پیش‌فاکتورهایِ فروش", proforma_register, _CALL,
              "همهٔ پیش‌فاکتورهایِ فروشِ بازه با وضعیت، مبلغ و درصدِ تبدیل به فاکتور.", group=_SOP),
    ReportDef("OPEN_ORDERS", "سفارش‌هایِ فروشِ باز", open_purchase_orders, _CALL,
              "سفارش‌هایی که هنوز کامل فاکتور نشده‌اند -- مقدارِ سفارش، تحویل‌شده، فاکتورشده و مانده.", group=_SOP),
    ReportDef("OVERDUE", "سفارش‌هایِ معوق در تحویل", overdue_orders, _CALL,
              "سفارش‌هایی که هنوز کامل تحویل نشده‌اند، با روزِ تاخیر نسبت به «تاریخِ تحویلِ مورد انتظار».", "as_of", _SOP),
    ReportDef("PENDING_ISSUES", "حواله‌هایِ در انتظارِ انبار", pending_receipts, _CALL,
              "سفارش‌هایِ فروش/امانی‌هایِ خروجی که منتظرِ تاییدِ انباردار هستند.", "none", _SOP),
    ReportDef("DELIVERED_NOT_INVOICED", "تحویل‌شده ولی فاکتورنشده", received_not_invoiced, _CALL,
              "کالایِ تحویل‌شده به مشتری که فاکتورش هنوز صادر نشده -- درآمدِ شناسایی‌نشده تا «تا تاریخ».", "as_of", _SOP),
    ReportDef("PENDING_INVOICES", "فاکتورهایِ فروشِ در انتظار", pending_invoices, _CALL,
              "فاکتور/پیش‌فاکتور/برگشتِ فروشی که در یکی از مراحل مانده‌اند.", "none", _SOP),
    ReportDef("CONSIGNMENTS", "امانی‌هایِ خروجیِ تسویه‌نشده", open_consignments, _CALL,
              "کالایِ امانیِ نزدِ هر مشتری/نماینده: ارسالی، تسویه‌شده (فروش)، برگشتی و مانده.", "none", _SOP),
    ReportDef("RETURNS", "برگشت از فروش", purchase_returns, _CALL,
              "برگشت‌هایِ فروش به تفکیکِ کالا/مشتری با علتِ برگشت.", group=_SOP),
    ReportDef("BY_ITEM", "فروش به تفکیکِ کالا", purchases_by_item, _CALL,
              "مقدار، مبلغ، برگشتی و میانگین/کمترین/بیشترین/آخرین فیِ فروشِ هر کالا.", group=_SAN),
    ReportDef("BY_CUSTOMER", "فروش به تفکیکِ مشتری", purchases_by_supplier, _CALL,
              "حجمِ فروش، تخفیف، مالیات، برگشتی و سهمِ هر مشتری.", group=_SAN),
    ReportDef("BY_CATEGORY", "فروش به تفکیکِ گروهِ کالا", purchases_by_category, _CALL,
              "فروشِ خالص به تفکیکِ گروهِ کالا.", group=_SAN),
    ReportDef("BY_COST_CENTER", "فروش به تفکیکِ مرکزِ هزینه/پروژه", purchases_by_cost_center, _CALL,
              "فروشِ هر مرکزِ هزینه/پروژه (از سرِ فاکتور).", group=_SAN),
    ReportDef("BY_REP", "فروش به تفکیکِ فروشنده/ویزیتور", sales_by_rep, _CALL,
              "فروش، برگشت، تعدادِ مشتری و سهمِ هر فروشنده.", group=_SAN),
    ReportDef("MONTHLY", "روندِ ماهانهٔ فروش", monthly_trend, _CALL,
              "فروش/برگشت/خالصِ هر ماهِ شمسی و درصدِ تغییر نسبت به ماهِ قبل.", group=_SAN),
    ReportDef("ABC", "تحلیلِ ABC فروش (پارتو)", abc_analysis, _CALL,
              "کالاهایی که بیشترِ فروش را می‌سازند -- کلاسِ A/B/C.", group=_SAN),
    ReportDef("GP_ITEM", "سودِ ناخالص به تفکیکِ کالا", gross_profit_by_item, _CALL,
              "فروشِ خالص، بهایِ تمام‌شده، سود و حاشیهٔ سودِ هر کالا.", group=_SPR),
    ReportDef("GP_CUSTOMER", "سودِ ناخالص به تفکیکِ مشتری", gross_profit_by_customer, _CALL,
              "فروشِ خالص، بهایِ تمام‌شده، سود و حاشیهٔ سودِ هر مشتری.", group=_SPR),
    ReportDef("PRICE_HISTORY", "تاریخچهٔ قیمتِ فروش", price_history, _CALL,
              "فیِ هر فروش به واحدِ پایه و درصدِ تغییر نسبت به فروشِ قبلیِ همان کالا.", group=_SPR),
    ReportDef("PRICE_COMPARE", "مقایسهٔ قیمتِ فروش به مشتریان", supplier_price_comparison, ("supplier", "item", "category"),
              "آخرین/میانگین/کمترین فیِ فروشِ هر کالا به هر مشتری؛ ★ = کمترین آخرین قیمت.", group=_SPR),
    ReportDef("DISCOUNTS", "تخفیف‌هایِ فروش", discounts_and_rebates, _CALL,
              "تخفیفِ داده‌شده در فاکتورهایِ فروش به تفکیکِ مشتری.", group=_SPR),
    ReportDef("CORRECTIONS", "اصلاحیه‌هایِ فاکتورِ فروش", invoice_corrections, ("supplier",),
              "فاکتورهایِ فروشِ اصلاح‌شده و اختلافِ مبلغِ آن‌ها.", group=_SPR),
    ReportDef("OTD", "تحویلِ به‌موقع به مشتری", on_time_delivery, _CALL,
              "درصدِ سفارش‌هایی که تا «تاریخِ تحویلِ مورد انتظار» تحویل شده‌اند.", group=_SDL),
    ReportDef("FILL_RATE", "دقتِ مقدارِ تحویل به مشتری", fill_rate, _CALL,
              "مقدارِ تحویلی در برابرِ مقدارِ سفارش، به تفکیکِ مشتری.", group=_SDL),
    ReportDef("LEAD_TIME", "زمانِ تحویلِ سفارش", lead_time, _CALL,
              "فاصلهٔ تاریخِ سفارش تا تحویل (یا اولین فاکتور) -- میانگین/کمترین/بیشترین.", group=_SDL),
    ReportDef("QUALITY", "نرخِ برگشت از فروش", quality_returns, _CALL,
              "درصدِ کالایِ برگشتی به تفکیکِ مشتری.", group=_SDL),
    ReportDef("BALANCES", "ماندهٔ حسابِ مشتریان", supplier_balances, ("supplier",),
              "ماندهٔ اول/گردش/ماندهٔ پایانِ دورهٔ هر مشتری از دفترِ کل.", group=_SFI),
    ReportDef("AGING", "سنی‌کردنِ مطالبات (AR Aging)", ap_aging, ("supplier",),
              "ماندهٔ فاکتورهایِ فروشِ باز به تفکیکِ روزهایِ گذشته از سررسید، تا «تا تاریخ».", "as_of", _SFI),
    ReportDef("FORECAST", "پیش‌بینیِ وصول", payment_forecast, ("supplier",),
              "سررسیدِ فاکتورهایِ وصول‌نشده و چک‌هایِ دریافتیِ نزدِ صندوق/بانک.", "none", _SFI),
    ReportDef("STATEMENT", "صورت‌حسابِ مشتری", supplier_statement, ("supplier",),
              "ریزِ گردشِ حسابِ یک مشتری با ماندهٔ جاری.", group=_SFI),
    ReportDef("PREPAYMENTS", "پیش‌دریافت‌هایِ مشتریان", prepayments, ("supplier",),
              "مشتریانی که بیش از خریدشان پرداخت کرده‌اند (ماندهٔ بستانکار).", "as_of", _SFI),
    ReportDef("CUSTOMERS", "فهرستِ مشتریان", supplier_list, ("supplier",),
              "اطلاعاتِ پایهٔ مشتریان با فروشِ بازه، آخرین فروش و ماندهٔ حساب.", group=_MD),
    ReportDef("ITEMS", "کالاهایِ قابلِ‌فروش و واحدها", sellable_items, ("item", "category"),
              "واحدهایِ فروش و ضرایب، واحدِ پیش‌فرض و آخرین فیِ فروش.", "none", _MD),
    ReportDef("PRICE_LISTS", "فهرست‌هایِ قیمتِ فروش", sales_price_lists, ("item", "category"),
              "فهرست‌هایِ قیمتِ فروش با کانال و اعتبار.", "none", _MD),
    ReportDef("WAREHOUSES", "انبارها و انباردارِ مسئول", warehouses_and_keepers, ("warehouse",),
              "انباردارِ هر انبار و تعدادِ رسید/حوالهٔ در انتظار.", "none", _MD),
]

SALES_REPORTS_BY_CODE = {r.code: r for r in SALES_REPORTS}


def report_def(code: str, side: str = "PURCHASE") -> ReportDef:
    if side == "ACCOUNTING":
        from peecha.services.accounting_reports import ACCOUNTING_REPORTS_BY_CODE

        return ACCOUNTING_REPORTS_BY_CODE[code]
    return (SALES_REPORTS_BY_CODE if side == "SALES" else REPORTS_BY_CODE)[code]


def run_report(company_id: int, code: str, f: PurchaseFilters) -> ReportResult:
    result = report_def(code, f.side).func(company_id, f)
    if f.side == "SALES":
        result.columns = [(sales_words(h), k) for h, k in result.columns]
        result.note = sales_words(result.note) if result.note else result.note
    return result


# R238: گزارش‌هایِ مرحلهٔ ۱ (کنترل/حسابرسی، فرآیند، انبار و تدارکات، مالی، ...) -- ماژولِ جدا
def register_reports(defs: list[ReportDef]) -> None:
    for r in defs:
        if r.code not in REPORTS_BY_CODE:
            REPORTS.append(r)
            REPORTS_BY_CODE[r.code] = r


try:
    from peecha.services.purchase_reports_ext import PURCHASE_EXT_REPORTS as _EXT  # noqa: E402
except ImportError:  # ماژولِ ext اول بارگذاری شده و در انتهایِ خودش ثبت می‌کند
    _EXT = []
register_reports(_EXT)

try:
    from peecha.services.purchase_reports_r245 import PURCHASE_R245_REPORTS as _R245  # noqa: E402
except ImportError:  # مثلِ ext: اگر آن ماژول اول بارگذاری شود، خودش ثبت می‌کند
    _R245 = []
register_reports(_R245)
