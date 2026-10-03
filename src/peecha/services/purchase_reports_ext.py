"""گزارش‌گیریِ حرفه‌ایِ خرید -- R238، مرحلهٔ ۱.

فقط لایهٔ گزارش: همهٔ توابع فقط می‌خوانند (هیچ سند/مانده/تنظیمی تغییر نمی‌کند) و
هر مغایرتی فقط گزارش می‌شود. منابعِ داده:
- comm.commercial_documents / _lines (سفارش، فاکتور، برگشت، امانی؛ زنجیرهٔ source_line_id)
- warehouse_approved_at / warehouse_delivered_quantity (رسیدِ انباردار)
- comm.invoice_settlements (تسویه/پرداخت)، treasury.issued_checks (چکِ پرداختنی)
- inv.stock_ledger / stock_balance / reorder_policies / item_suppliers (موجودی و سیاستِ سفارش)
- comm.landed_cost_allocations، comm.supplier_profiles، comm.commercial_contracts، comm.discount_rules
- acc.activity_log (فقط برایِ سندهایِ حسابداریِ مرتبط -- اسنادِ بازرگانی تاریخچهٔ تغییر ندارند)

فرمولِ شاخص‌ها در docstringِ هر تابع آمده است.
"""

from __future__ import annotations

import datetime
import decimal
import statistics
from collections import defaultdict
from types import SimpleNamespace

from sqlalchemy import func, select

from peecha.db.base import new_session
from peecha.db.models.commercial import CommercialDocument, CommercialDocumentLine, InvoiceSettlement
from peecha.services import commercial_documents as documents_service
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import inventory_catalog as catalog_service
from peecha.services import purchase_reports as base
from peecha.services.purchase_reports import (
    DATE, DAYS, INT, MONEY, PERCENT, QTY, TEXT, PurchaseFilters, ReportDef, ReportResult,
)

_ZERO = decimal.Decimal(0)
_Q2 = decimal.Decimal("0.01")
_OPEN_ORDER_STATUSES = ("CONFIRMED", "APPROVED", "POSTED")
_TITLES = {
    "PURCHASE_ORDER": "سفارشِ خرید", "PURCHASE_PROFORMA": "پیش‌فاکتورِ خرید", "PURCHASE_INVOICE": "فاکتورِ خرید",
    "PURCHASE_RETURN": "برگشت به تامین‌کننده", "CONSIGNMENT_IN": "امانیِ ورودی",
}


def _opt(f: PurchaseFilters, key: str, default: str) -> str:
    return (f.options or {}).get(key) or default


def _money(value: decimal.Decimal) -> decimal.Decimal:
    return value.quantize(_Q2)


def _users() -> dict[int, str]:
    from peecha.db.models.security import User

    with new_session() as session:
        return {u.user_id: u.full_name or u.username for u in session.scalars(select(User))}


# =====================================================================
# دادهٔ مشترکِ تطبیقِ سه‌طرفه (سفارش ↔ رسید ↔ فاکتور)
# =====================================================================
def _invoice_lines_by_source(company_id: int, source_line_ids: list[int]) -> dict[int, list[CommercialDocumentLine]]:
    out: dict[int, list] = defaultdict(list)
    if not source_line_ids:
        return out
    with new_session() as session:
        for ln in session.scalars(
            select(CommercialDocumentLine)
            .join(CommercialDocument, CommercialDocument.document_id == CommercialDocumentLine.document_id)
            .where(
                CommercialDocumentLine.source_line_id.in_(source_line_ids),
                CommercialDocument.document_type_code == "PURCHASE_INVOICE",
                CommercialDocument.status_code != "CANCELLED", CommercialDocument.corrects_document_id.is_(None),
            )
        ):
            out[ln.source_line_id].append(ln)
    return out


def _three_way(company_id: int, f: PurchaseFilters) -> list[dict]:
    """هر ردیفِ سفارشِ خرید با مقدارِ سفارش/رسید/فاکتور و فیِ سفارش/فاکتور.
    - رسیده: اگر مرحلهٔ رسیدِ انباردار روشن است = مقدارِ تاییدشدهٔ انباردار (پیش از تایید صفر)؛
      وگرنه فاکتور همان رسید است (رسیده = فاکتورشده).
    - فیِ فاکتور = میانگینِ وزنیِ فیِ خالصِ ردیف‌هایِ فاکتورِ مرجع (واحدِ پایه)."""
    ctx = base._ctx(company_id)
    receipt_step = documents_service.order_warehouse_step_enabled(company_id, "PURCHASE_ORDER")
    pairs = base._lines(company_id, ("PURCHASE_ORDER",), _OPEN_ORDER_STATUSES, f, ctx)
    invoices = _invoice_lines_by_source(company_id, [ln.line_id for _d, ln in pairs])
    rows = []
    for doc, ln in pairs:
        inv_lines = invoices.get(ln.line_id, [])
        invoiced = sum((x.quantity_base for x in inv_lines), _ZERO)
        inv_value = sum((base._net(x) for x in inv_lines), _ZERO)
        if receipt_step:
            received = base._received_base(doc, ln) or _ZERO
        else:
            received = invoiced
        po_price = base._base_price(ln)
        inv_price = (inv_value / invoiced) if invoiced else None
        issues = []
        if receipt_step and doc.warehouse_approved_at is None:
            issues.append("منتظرِ رسید")
        if received > ln.quantity_base:
            issues.append("رسید بیش از سفارش")
        if receipt_step and doc.warehouse_approved_at is not None and received < ln.quantity_base:
            issues.append("رسیدِ ناقص")
        if invoiced > ln.quantity_base:
            issues.append("فاکتور بیش از سفارش")
        if receipt_step and invoiced > received:
            issues.append("فاکتور بیش از رسید")
        if received > invoiced:
            issues.append("فاکتورنشده")
        if inv_price is not None and abs(inv_price - po_price) >= _Q2:
            issues.append("اختلافِ فی")
        rows.append({
            "doc": doc, "line": ln, "ordered": ln.quantity_base, "received": received, "invoiced": invoiced,
            "po_price": po_price, "inv_price": inv_price, "issues": issues, "receipt_step": receipt_step,
            "supplier": ctx.names.get(doc.counterparty_detail_account_id, ""), "item": ctx.item_label(ln.item_id),
            "uom": ctx.base_uom(ln.item_id),
        })
    return rows


_THREE_WAY_COLUMNS = [
    ("شمارهٔ سفارش", INT), ("تاریخ", DATE), ("تامین‌کننده", TEXT), ("کالا", TEXT), ("واحد", TEXT),
    ("مقدارِ سفارش", QTY), ("مقدارِ رسید", QTY), ("مقدارِ فاکتور", QTY), ("فیِ سفارش", MONEY), ("فیِ فاکتور", MONEY),
    ("اختلافِ مقدار (فاکتور−رسید)", QTY), ("اختلافِ ریالیِ فی", MONEY), ("نتیجه", TEXT),
]


def _three_way_report(company_id: int, f: PurchaseFilters, keep, note: str = "") -> ReportResult:
    result = ReportResult(list(_THREE_WAY_COLUMNS), no_total={0, 8, 9}, note=note)
    for r in _three_way(company_id, f):
        if not keep(r):
            continue
        price_gap = ((r["inv_price"] - r["po_price"]) * r["invoiced"]) if r["inv_price"] is not None else _ZERO
        result.add([
            r["doc"].document_no, r["doc"].document_date, r["supplier"], r["item"], r["uom"], r["ordered"], r["received"],
            r["invoiced"], r["po_price"], r["inv_price"], r["invoiced"] - r["received"], _money(price_gap),
            "، ".join(r["issues"]) or "تطبیقِ کامل",
        ], (r["doc"].document_id, r["doc"].document_type_code))
    return result


def three_way_match(company_id: int, f: PurchaseFilters) -> ReportResult:
    only = _opt(f, "view", "ISSUES")
    return _three_way_report(
        company_id, f, lambda r: only == "ALL" or bool(r["issues"]),
        note="مقایسهٔ هر ردیفِ سفارش با رسیدِ انبار و فاکتور. هیچ اختلافی اصلاح نمی‌شود -- فقط گزارش.",
    )


def invoice_without_receipt(company_id: int, f: PurchaseFilters) -> ReportResult:
    return _three_way_report(company_id, f, lambda r: r["receipt_step"] and r["invoiced"] > r["received"],
                             note="فاکتور (کامل یا جزئی) برایِ مقداری که هنوز رسیدِ انبار نخورده است.")


def invoice_over_po(company_id: int, f: PurchaseFilters) -> ReportResult:
    return _three_way_report(
        company_id, f,
        lambda r: r["invoiced"] > r["ordered"] or (r["inv_price"] is not None and r["inv_price"] - r["po_price"] >= _Q2),
        note="مقدار یا فیِ فاکتور بیشتر از سفارش.",
    )


def receipt_over_po(company_id: int, f: PurchaseFilters) -> ReportResult:
    return _three_way_report(company_id, f, lambda r: r["received"] > r["ordered"], note="مقدارِ رسیدشده بیشتر از سفارش.")


def receipt_mismatch(company_id: int, f: PurchaseFilters) -> ReportResult:
    return _three_way_report(
        company_id, f, lambda r: r["receipt_step"] and r["doc"].warehouse_approved_at is not None and r["received"] != r["ordered"],
        note="رسیدهایی که مقدارشان با سفارش برابر نیست (کم یا زیاد).",
    )


def partial_receipt(company_id: int, f: PurchaseFilters) -> ReportResult:
    return _three_way_report(
        company_id, f, lambda r: r["receipt_step"] and r["doc"].warehouse_approved_at is not None and r["received"] < r["ordered"],
        note="سفارش‌هایی که کمتر از مقدارِ سفارش رسید خورده‌اند.",
    )


def orders_without_receipt(company_id: int, f: PurchaseFilters) -> ReportResult:
    return _three_way_report(company_id, f, lambda r: r["receipt_step"] and r["doc"].warehouse_approved_at is None,
                             note="سفارش‌هایی که هنوز رسیدِ انباردار نخورده‌اند (فقط وقتی مرحلهٔ رسید روشن است).")


def orders_without_invoice(company_id: int, f: PurchaseFilters) -> ReportResult:
    return _three_way_report(company_id, f, lambda r: r["invoiced"] == 0, note="ردیف‌هایِ سفارشی که هیچ فاکتوری از آن‌ها صادر نشده.")


def purchase_without_po(company_id: int, f: PurchaseFilters) -> ReportResult:
    """فاکتورِ خریدِ ثبت‌شده‌ای که ردیفش به سفارش/پیش‌فاکتور ارجاع ندارد (اصلاحیه‌ها و تسویهٔ امانی جدا)."""
    ctx = base._ctx(company_id)
    pairs = base._lines(company_id, ("PURCHASE_INVOICE",), ("POSTED",), f, ctx)
    with new_session() as session:
        source_types = dict(session.execute(
            select(CommercialDocumentLine.line_id, CommercialDocument.document_type_code)
            .join(CommercialDocument, CommercialDocument.document_id == CommercialDocumentLine.document_id)
            .where(CommercialDocumentLine.line_id.in_([ln.source_line_id for _d, ln in pairs if ln.source_line_id]))
        ).all()) if pairs else {}
    result = ReportResult([
        ("تاریخ", DATE), ("شمارهٔ فاکتور", INT), ("تامین‌کننده", TEXT), ("کالا", TEXT), ("مقدار (پایه)", QTY),
        ("مبلغِ خالص", MONEY), ("ثبت‌کننده", TEXT),
    ], no_total={1}, note="خرید مستقیم با فاکتور، بدونِ سفارشِ خرید/پیش‌فاکتور.")
    users = _users()
    for doc, ln in pairs:
        if doc.corrects_document_id is not None:
            continue
        source_type = source_types.get(ln.source_line_id)
        if source_type in ("PURCHASE_ORDER", "PURCHASE_PROFORMA", "CONSIGNMENT_IN"):
            continue
        result.add([doc.document_date, doc.document_no, ctx.names.get(doc.counterparty_detail_account_id, ""),
                    ctx.item_label(ln.item_id), ln.quantity_base, base._net(ln), users.get(doc.created_by_user_id, "")],
                   (doc.document_id, doc.document_type_code))
    return result


def cancelled_documents(company_id: int, f: PurchaseFilters) -> ReportResult:
    ctx = base._ctx(company_id)
    users = _users()
    with new_session() as session:
        docs = list(session.scalars(
            select(CommercialDocument).where(
                CommercialDocument.company_id == company_id, CommercialDocument.document_type_code.in_(tuple(_TITLES)),
                CommercialDocument.status_code == "CANCELLED",
                CommercialDocument.document_date.between(f.date_from, f.date_to),
            ).order_by(CommercialDocument.document_date)
        ))
    reasons = _cancel_reason_names(company_id)
    result = ReportResult([
        ("نوع", TEXT), ("شماره", INT), ("تاریخ", DATE), ("تامین‌کننده", TEXT), ("مبلغ", MONEY), ("ثبت‌کننده", TEXT),
        ("علتِ لغو", TEXT), ("توضیحِ لغو", TEXT), ("لغوکننده", TEXT), ("زمانِ لغو", TEXT), ("شرح", TEXT),
    ], no_total={1}, note="علت/کاربر/زمانِ لغو از R240 ثبت می‌شود؛ اسنادِ لغوشدهٔ قبلی «ثبت‌نشده» نشان داده می‌شوند.")
    for doc in docs:
        if f.supplier_id is not None and doc.counterparty_detail_account_id != f.supplier_id:
            continue
        result.add([_TITLES[doc.document_type_code], doc.document_no, doc.document_date,
                    ctx.names.get(doc.counterparty_detail_account_id, ""), doc.total_amount,
                    users.get(doc.created_by_user_id, ""), reasons.get(doc.cancellation_reason_id, "— ثبت‌نشده —"),
                    doc.cancellation_note or "", users.get(doc.cancelled_by_user_id, ""), _when(doc.cancelled_at),
                    doc.description or ""], (doc.document_id, doc.document_type_code))
    return result


def _cancel_reason_names(company_id: int) -> dict[int, str]:
    from peecha.services import procurement_masters as masters_service

    return {r.reason_id: r.name for r in masters_service.list_cancellation_reasons(company_id)}


def _when(value) -> str:
    from peecha import numerals

    return numerals.format_jalali_datetime(value) if value else ""


# =====================================================================
# ردِ سند، فعالیتِ کاربران، ثبت بدونِ تصویب
# =====================================================================
def _purchase_docs(company_id: int, f: PurchaseFilters, types=tuple(_TITLES)) -> list[CommercialDocument]:
    with new_session() as session:
        docs = list(session.scalars(
            select(CommercialDocument).where(
                CommercialDocument.company_id == company_id, CommercialDocument.document_type_code.in_(types),
                CommercialDocument.document_date.between(f.date_from, f.date_to),
            ).order_by(CommercialDocument.document_date, CommercialDocument.document_id)
        ))
    return [d for d in docs if f.supplier_id is None or d.counterparty_detail_account_id == f.supplier_id]


def document_trail(company_id: int, f: PurchaseFilters) -> ReportResult:
    """ردِ هر سندِ خرید از رویِ خودِ سند (ایجاد/ثبت/رسید/سندِ حسابداری/اصلاح/تسویه)
    + تعدادِ رویدادهایِ ثبت‌شده در activity_log برایِ سندِ حسابداریِ همان سند."""
    from peecha.db.models.accounting import JournalEntry
    from peecha.db.models.audit import ActivityLog

    ctx = base._ctx(company_id)
    users = _users()
    docs = _purchase_docs(company_id, f)
    ids = [d.document_id for d in docs]
    je_ids = [d.journal_entry_id for d in docs if d.journal_entry_id]
    with new_session() as session:
        je_no = {je.journal_entry_id: je.permanent_no or je.temporary_no for je in session.scalars(
            select(JournalEntry).where(JournalEntry.journal_entry_id.in_(je_ids)))} if je_ids else {}
        activity = dict(session.execute(
            select(ActivityLog.entity_id, func.count()).where(ActivityLog.entity_id.in_(je_ids), ActivityLog.entity_type.ilike("%journal%"))
            .group_by(ActivityLog.entity_id)
        ).all()) if je_ids else {}
        settled = defaultdict(lambda: [_ZERO, None])
        if ids:
            for invoice_id, amount, when in session.execute(
                select(InvoiceSettlement.invoice_document_id, InvoiceSettlement.amount, InvoiceSettlement.settlement_date)
                .where(InvoiceSettlement.invoice_document_id.in_(ids))
            ):
                settled[invoice_id][0] += amount
                settled[invoice_id][1] = max(filter(None, (settled[invoice_id][1], when)))
        numbers = {d.document_id: d.document_no for d in session.scalars(
            select(CommercialDocument).where(CommercialDocument.document_id.in_(
                [x for d in docs for x in (d.corrects_document_id, d.corrected_by_document_id, d.source_document_id) if x])))}
    result = ReportResult([
        ("نوع", TEXT), ("شماره", INT), ("تاریخ", DATE), ("تامین‌کننده", TEXT), ("وضعیت", TEXT), ("مبلغ", MONEY),
        ("ایجاد (کاربر/زمان)", TEXT), ("ثبتِ نهایی (کاربر/زمان)", TEXT), ("رسیدِ انبار (کاربر/زمان)", TEXT),
        ("سندِ مبدا", TEXT), ("شمارهٔ سندِ حسابداری", TEXT), ("اصلاحیه", TEXT), ("تسویه‌شده", MONEY), ("آخرین تسویه", DATE),
        ("رویدادهایِ ثبت‌شده", INT),
    ], no_total={1, 5}, note="سوابقِ هر سند از فیلدهایِ خودِ سند؛ تاریخچهٔ تغییرِ ردیف‌ها در سیستم ثبت نمی‌شود (GAP).")

    def stamp(user_id, when):
        if when is None:
            return ""
        from peecha import numerals

        return f"{users.get(user_id, '')} -- {numerals.format_jalali_datetime(when)}"

    for d in docs:
        correction = ""
        if d.corrects_document_id:
            correction = f"اصلاحیهٔ سندِ {numbers.get(d.corrects_document_id, '')}"
        elif d.corrected_by_document_id:
            correction = f"اصلاح‌شده با {numbers.get(d.corrected_by_document_id, '')}"
        result.add([
            _TITLES[d.document_type_code], d.document_no, d.document_date, ctx.names.get(d.counterparty_detail_account_id, ""),
            base._STATUS_LABELS.get(d.status_code, d.status_code), d.total_amount, stamp(d.created_by_user_id, d.created_at),
            stamp(d.posted_by_user_id, d.posted_at), stamp(d.warehouse_approved_by_user_id, d.warehouse_approved_at),
            str(numbers.get(d.source_document_id, "")) if d.source_document_id else "",
            str(je_no.get(d.journal_entry_id, "")) if d.journal_entry_id else "", correction,
            settled[d.document_id][0], settled[d.document_id][1], activity.get(d.journal_entry_id, 0),
        ], (d.document_id, d.document_type_code))
    return result


def user_activity(company_id: int, f: PurchaseFilters) -> ReportResult:
    users = _users()
    agg: dict[int, dict] = defaultdict(lambda: defaultdict(int))
    values: dict[int, decimal.Decimal] = defaultdict(lambda: _ZERO)
    for d in _purchase_docs(company_id, f):
        agg[d.created_by_user_id][f"create_{d.document_type_code}"] += 1
        values[d.created_by_user_id] += d.total_amount if d.document_type_code == "PURCHASE_INVOICE" else _ZERO
        if d.posted_by_user_id:
            agg[d.posted_by_user_id]["posted"] += 1
        if d.warehouse_approved_by_user_id:
            agg[d.warehouse_approved_by_user_id]["receipts"] += 1
        if d.status_code == "CANCELLED":
            agg[d.created_by_user_id]["cancelled"] += 1
    result = ReportResult([
        ("کاربر", TEXT), ("سفارشِ ایجادشده", INT), ("پیش‌فاکتور", INT), ("فاکتور", INT), ("برگشت", INT), ("امانی", INT),
        ("ثبتِ نهایی", INT), ("تاییدِ رسید", INT), ("لغوشده", INT), ("مبلغِ فاکتورهایِ ایجادشده", MONEY),
    ])
    for user_id, a in sorted(agg.items(), key=lambda kv: users.get(kv[0], "")):
        result.add([users.get(user_id, str(user_id)), a["create_PURCHASE_ORDER"], a["create_PURCHASE_PROFORMA"],
                    a["create_PURCHASE_INVOICE"], a["create_PURCHASE_RETURN"], a["create_CONSIGNMENT_IN"], a["posted"],
                    a["receipts"], a["cancelled"], values[user_id]])
    return result


def approval_check(company_id: int, f: PurchaseFilters) -> ReportResult:
    """اسنادی که تنظیمات برایشان تصویبِ مدیر می‌خواهد و هنوز تصویب نشده‌اند (گلوگاهِ تایید).
    ثبتِ نهاییِ بدونِ تصویب را خودِ post_document رد می‌کند؛ هویتِ تصویب‌کننده ذخیره نمی‌شود (GAP)."""
    ctx = base._ctx(company_id)
    users = _users()
    today = min(f.date_to, datetime.date.today())
    result = ReportResult([
        ("نوع", TEXT), ("شماره", INT), ("تاریخ", DATE), ("تامین‌کننده", TEXT), ("مبلغ", MONEY), ("ثبت‌کننده", TEXT),
        ("روزِ انتظار", DAYS),
    ], no_total={1, 6}, note="اسنادِ تاییدشده توسطِ کاربر که منتظرِ تصویبِ مدیر مانده‌اند.")
    for d in _purchase_docs(company_id, f, ("PURCHASE_ORDER", "PURCHASE_PROFORMA", "PURCHASE_INVOICE")):
        if d.status_code != "CONFIRMED" or not documents_service.requires_manager_approval(company_id, d.document_type_code):
            continue
        result.add([_TITLES[d.document_type_code], d.document_no, d.document_date, ctx.names.get(d.counterparty_detail_account_id, ""),
                    d.total_amount, users.get(d.created_by_user_id, ""), (today - d.document_date).days],
                   (d.document_id, d.document_type_code))
    return result


# =====================================================================
# فرآیندِ خرید: گردشِ سفارش و زمانِ چرخه
# =====================================================================
def _order_flow(company_id: int, f: PurchaseFilters) -> list[dict]:
    users = _users()
    ctx = base._ctx(company_id)
    orders = _purchase_docs(company_id, f, ("PURCHASE_ORDER",))
    order_ids = [o.document_id for o in orders if o.status_code != "DRAFT"]
    with new_session() as session:
        invoices = list(session.scalars(
            select(CommercialDocument).where(
                CommercialDocument.source_document_id.in_(order_ids), CommercialDocument.document_type_code == "PURCHASE_INVOICE",
                CommercialDocument.status_code != "CANCELLED",
            )
        )) if order_ids else []
        inv_ids = [i.document_id for i in invoices]
        settlements: dict[int, list] = defaultdict(list)
        if inv_ids:
            for invoice_id, amount, when in session.execute(
                select(InvoiceSettlement.invoice_document_id, InvoiceSettlement.amount, InvoiceSettlement.settlement_date)
                .where(InvoiceSettlement.invoice_document_id.in_(inv_ids)).order_by(InvoiceSettlement.settlement_date)
            ):
                settlements[invoice_id].append((amount, when))
    by_order: dict[int, list] = defaultdict(list)
    for inv in invoices:
        by_order[inv.source_document_id].append(inv)
    rows = []
    for o in orders:
        if o.status_code == "DRAFT":
            continue
        invs = by_order.get(o.document_id, [])
        invoice_date = min((i.document_date for i in invs), default=None)
        paid_date = None
        if invs and all(i.status_code == "POSTED" for i in invs):
            total = sum((i.total_amount for i in invs), _ZERO)
            paid = sum((a for i in invs for a, _w in settlements.get(i.document_id, [])), _ZERO)
            if total and paid >= total:
                paid_date = max(w for i in invs for _a, w in settlements.get(i.document_id, []))
        receipt_date = o.warehouse_approved_at.date() if o.warehouse_approved_at else invoice_date
        rows.append({
            "doc": o, "supplier": ctx.names.get(o.counterparty_detail_account_id, ""), "created": o.created_at,
            "created_by": users.get(o.created_by_user_id, ""), "posted": o.posted_at, "posted_by": users.get(o.posted_by_user_id, ""),
            "received": receipt_date, "received_by": users.get(o.warehouse_approved_by_user_id, ""),
            "invoiced": invoice_date, "paid": paid_date,
        })
    return rows


def _gap(a, b) -> int | None:
    if a is None or b is None:
        return None
    a = a.date() if isinstance(a, datetime.datetime) else a
    b = b.date() if isinstance(b, datetime.datetime) else b
    return (b - a).days


def order_flow(company_id: int, f: PurchaseFilters) -> ReportResult:
    """گردشِ سفارش: ایجاد → ثبتِ نهایی → رسید → فاکتور → پرداختِ کامل، با کاربر و فاصلهٔ روز."""
    result = ReportResult([
        ("شماره", INT), ("تاریخ", DATE), ("تامین‌کننده", TEXT), ("وضعیت", TEXT), ("ایجادکننده", TEXT), ("ثبتِ نهایی", DATE),
        ("ثبت‌کننده", TEXT), ("رسید", DATE), ("تاییدکنندهٔ رسید", TEXT), ("اولین فاکتور", DATE), ("پرداختِ کامل", DATE),
        ("سفارش→رسید (روز)", DAYS), ("رسید→فاکتور", DAYS), ("فاکتور→پرداخت", DAYS), ("کلِ چرخه", DAYS),
    ], no_total={0, 11, 12, 13, 14})
    for r in _order_flow(company_id, f):
        o = r["doc"]
        result.add([
            o.document_no, o.document_date, r["supplier"], base._STATUS_LABELS.get(o.status_code, o.status_code), r["created_by"],
            r["posted"].date() if r["posted"] else None, r["posted_by"], r["received"], r["received_by"], r["invoiced"], r["paid"],
            _gap(o.document_date, r["received"]), _gap(r["received"], r["invoiced"]), _gap(r["invoiced"], r["paid"]),
            _gap(o.document_date, r["paid"]),
        ], (o.document_id, o.document_type_code))
    return result


def cycle_time(company_id: int, f: PurchaseFilters) -> ReportResult:
    """میانگینِ روز: سفارش→رسید، رسید→فاکتور، فاکتور→پرداخت، سفارش→پرداخت (فقط سفارش‌هایی که مرحله را طی کرده‌اند)."""
    agg: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for r in _order_flow(company_id, f):
        o = r["doc"]
        for key, gap in (("po_rcv", _gap(o.document_date, r["received"])), ("rcv_inv", _gap(r["received"], r["invoiced"])),
                         ("inv_pay", _gap(r["invoiced"], r["paid"])), ("po_pay", _gap(o.document_date, r["paid"]))):
            if gap is not None:
                agg[r["supplier"]][key].append(gap)
                agg["— همهٔ تامین‌کنندگان —"][key].append(gap)

    def avg(values):
        return round(sum(values) / len(values)) if values else None

    result = ReportResult([
        ("تامین‌کننده", TEXT), ("تعدادِ سفارش", INT), ("سفارش→رسید", DAYS), ("رسید→فاکتور", DAYS), ("فاکتور→پرداخت", DAYS),
        ("سفارش→پرداخت", DAYS),
    ], no_total={1, 2, 3, 4, 5}, note="درخواستِ خرید و تصویب در سیستم وجود ندارد (GAP)؛ چرخه از سفارش شروع می‌شود.")
    for supplier, a in sorted(agg.items()):
        result.add([supplier, len(a["po_rcv"]) or len(a["rcv_inv"]), avg(a["po_rcv"]), avg(a["rcv_inv"]), avg(a["inv_pay"]),
                    avg(a["po_pay"])])
    return result


# =====================================================================
# تحلیلِ خرید به تفکیکِ ابعادِ دیگر
# =====================================================================
_DIMENSIONS = (
    ("PROJECT", "پروژه"), ("WAREHOUSE", "انبار"), ("BRAND", "برند"), ("USER", "کاربرِ ثبت‌کننده"),
    ("KIND", "کالا / خدمت"), ("CURRENCY", "داخلی (ریالی) / ارزی"), ("PAYMENT", "نقدی / نسیه"),
    ("PURCHASE_TYPE", "نوعِ خرید (برنامه‌ای / اضطراری)"),
)


def purchases_by_dimension(company_id: int, f: PurchaseFilters) -> ReportResult:
    """نقدی/نسیه: بخشِ نقدی = جمعِ روش‌هایِ نحوهٔ تسویهٔ فاکتور؛ باقیِ مبلغِ فاکتور = نسیه."""
    from peecha.services import commercial_settlements as settlements_service

    dim = _opt(f, "dimension", "PROJECT")
    ctx = base._ctx(company_id)
    users = _users()
    brands = {b.brand_id: b.name for b in catalog_service.list_brands(company_id)}
    from peecha.services import procurement_masters as masters_service

    purchase_types = {t.purchase_type_id: t.name for t in masters_service.list_purchase_types(company_id)}
    purchases, returns = base._posted_purchase_and_returns(company_id, f, ctx)
    agg: dict[str, dict] = defaultdict(lambda: {"amount": _ZERO, "returns": _ZERO, "docs": set(), "suppliers": set()})
    if dim == "PAYMENT":
        seen = set()
        for doc, _ln in purchases:
            if doc.document_id in seen:
                continue
            seen.add(doc.document_id)
            plan = settlements_service.get_settlement_plan(doc.document_id, company_id)
            cash = min(sum((ln.amount for ln in plan.lines), _ZERO), doc.total_amount) if plan else _ZERO
            for key, amount in (("نقدی/بانکی (طبقِ نحوهٔ تسویه)", cash), ("نسیه", doc.total_amount - cash)):
                if amount:
                    a = agg[key]
                    a["amount"] += amount
                    a["docs"].add(doc.document_id)
                    a["suppliers"].add(doc.counterparty_detail_account_id)
    else:
        def key(doc, ln):
            item = ctx.items.get(ln.item_id)
            if dim == "PROJECT":
                return ctx.names.get(doc.project_detail_account_id, "— بدونِ پروژه —") if doc.project_detail_account_id else "— بدونِ پروژه —"
            if dim == "WAREHOUSE":
                wid = ln.warehouse_id or doc.warehouse_id
                return ctx.warehouses.get(wid, "— بدونِ انبار —") if wid else "— بدونِ انبار —"
            if dim == "BRAND":
                return brands.get(item.brand_id, "— بدونِ برند —") if item and item.brand_id else "— بدونِ برند —"
            if dim == "USER":
                return users.get(doc.created_by_user_id, "")
            if dim == "KIND":
                return "خدمت" if item and item.item_kind_code == "SERVICE" else "کالا"
            if dim == "PURCHASE_TYPE":
                return purchase_types.get(doc.purchase_type_id, "— تعیین‌نشده —")
            return "ارزی" if doc.currency_id != _base_currency(company_id) else "داخلی (ریالی)"

        for doc, ln in purchases:
            a = agg[key(doc, ln)]
            a["amount"] += base._net(ln)
            a["docs"].add(doc.document_id)
            a["suppliers"].add(doc.counterparty_detail_account_id)
        for doc, ln in returns:
            agg[key(doc, ln)]["returns"] += base._net(ln)
    total = sum((a["amount"] - a["returns"] for a in agg.values()), _ZERO)
    label = dict(_DIMENSIONS)[dim]
    result = ReportResult([
        (label, TEXT), ("تعدادِ فاکتور", INT), ("تعدادِ تامین‌کننده", INT), ("مبلغ", MONEY), ("برگشتی", MONEY), ("خالص", MONEY),
        ("سهم از کل", PERCENT),
    ], no_total={1, 2}, note="نقدی/نسیه با مالیات است؛ بقیهٔ ابعاد مبلغِ خالصِ کالا (بدونِ مالیات)." if dim == "PAYMENT" else "")
    for name, a in sorted(agg.items(), key=lambda kv: -(kv[1]["amount"] - kv[1]["returns"])):
        net = a["amount"] - a["returns"]
        result.add([name, len(a["docs"]), len(a["suppliers"]), a["amount"], a["returns"], net, (net * 100 / total) if total else _ZERO])
    return result


def _base_currency(company_id: int) -> int:
    from peecha.db.models.core import Company

    with new_session() as session:
        return session.get(Company, company_id).base_currency_id


# =====================================================================
# قیمت و هزینه
# =====================================================================
def price_movers(company_id: int, f: PurchaseFilters) -> ReportResult:
    """تغییرِ قیمت = (آخرین فیِ بازه − اولین فیِ بازه) ÷ اولین فی؛ واحدِ پایه، خالص از تخفیف."""
    direction = _opt(f, "direction", "UP")
    ctx = base._ctx(company_id)
    first: dict[int, tuple] = {}
    last: dict[int, tuple] = {}
    for doc, ln in base._lines(company_id, ("PURCHASE_INVOICE",), ("POSTED",), f, ctx):
        price = base._base_price(ln)
        first.setdefault(ln.item_id, (price, doc.document_date))
        last[ln.item_id] = (price, doc.document_date)
    result = ReportResult([
        ("کالا", TEXT), ("اولین فی", MONEY), ("تاریخِ اول", DATE), ("آخرین فی", MONEY), ("تاریخِ آخر", DATE),
        ("تغییر", MONEY), ("درصدِ تغییر", PERCENT),
    ], no_total={1, 3, 5, 6})
    rows = []
    for item_id, (p0, d0) in first.items():
        p1, d1 = last[item_id]
        if not p0 or d0 == d1 and p0 == p1:
            continue
        change = (p1 - p0) * 100 / p0
        if (direction == "UP" and change <= 0) or (direction == "DOWN" and change >= 0):
            continue
        rows.append([ctx.item_label(item_id), p0, d0, p1, d1, p1 - p0, change])
    for row in sorted(rows, key=lambda r: -r[6] if direction != "DOWN" else r[6]):
        result.add(row)
    return result


def _price_list_reference(company_id: int) -> dict[int, decimal.Decimal]:
    """کمترین فیِ فهرست‌هایِ قیمتِ خریدِ فعال، به واحدِ پایه."""
    from peecha.services import commercial_pricing as pricing_service
    from peecha.services import unit_conversion as uc

    today = datetime.date.today()
    out: dict[int, decimal.Decimal] = {}
    for pl in pricing_service.list_price_lists(company_id, "PURCHASE"):
        if not pl.is_active or pl.valid_from > today or (pl.valid_to and pl.valid_to < today):
            continue
        for row in pricing_service.list_price_list_items(pl.price_list_id):
            try:
                factor = uc.get_factor(row.item_id, row.uom_id)
            except ValueError:
                continue
            price = row.unit_price / factor if factor else row.unit_price
            out[row.item_id] = min(out.get(row.item_id, price), price)
    return out


_REFERENCES = (("ORDER", "فیِ سفارشِ مبدا"), ("PREVIOUS", "آخرین خریدِ قبلی"), ("PRICE_LIST", "فهرستِ قیمتِ خرید"),
               ("AVERAGE", "میانگینِ فیِ دوره"))


def price_vs_reference(company_id: int, f: PurchaseFilters) -> ReportResult:
    """انحرافِ قیمت با مرجعِ انتخابیِ کاربر (بدونِ حدس):
    انحراف = فیِ واقعی − فیِ مرجع؛ اثر = انحراف × مقدار. فقط ردیف‌هایی که مرجعشان موجود است."""
    reference = _opt(f, "reference", "ORDER")
    direction = _opt(f, "direction", "ALL")
    doc_type = _opt(f, "document", "PURCHASE_INVOICE")
    ctx = base._ctx(company_id)
    all_lines = base._lines(company_id, (doc_type,), ("POSTED", "CONFIRMED", "APPROVED") if doc_type == "PURCHASE_ORDER" else ("POSTED",),
                            None, ctx, dated=False)
    sources: dict[int, decimal.Decimal] = {}
    if reference == "ORDER":
        with new_session() as session:
            ids = [ln.source_line_id for _d, ln in all_lines if ln.source_line_id]
            for src, sdoc in session.execute(
                select(CommercialDocumentLine, CommercialDocument)
                .join(CommercialDocument, CommercialDocument.document_id == CommercialDocumentLine.document_id)
                .where(CommercialDocumentLine.line_id.in_(ids))
            ).all() if ids else []:
                if sdoc.document_type_code in ("PURCHASE_ORDER", "PURCHASE_PROFORMA"):
                    sources[src.line_id] = base._base_price(src)
    price_list = _price_list_reference(company_id) if reference == "PRICE_LIST" else {}
    in_range = [(d, ln) for d, ln in all_lines if f.date_from <= d.document_date <= f.date_to and base._line_matches(ctx, f, d, ln)]
    in_range_ids = {ln.line_id for _d, ln in in_range}
    averages: dict[int, decimal.Decimal] = {}
    if reference == "AVERAGE":
        sums: dict[int, list] = defaultdict(lambda: [_ZERO, _ZERO])
        for _d, ln in in_range:
            sums[ln.item_id][0] += base._net(ln)
            sums[ln.item_id][1] += ln.quantity_base
        averages = {k: (v[0] / v[1]) for k, v in sums.items() if v[1]}
    previous: dict[int, decimal.Decimal] = {}
    ref_label = dict(_REFERENCES)[reference]
    result = ReportResult([
        ("تاریخ", DATE), ("شماره", INT), ("تامین‌کننده", TEXT), ("کالا", TEXT), ("مرجع", TEXT), ("فیِ مرجع", MONEY),
        ("فیِ واقعی", MONEY), ("انحرافِ فی", MONEY), ("درصد", PERCENT), ("مقدار (پایه)", QTY), ("اثرِ ریالی", MONEY),
    ], no_total={1, 5, 6, 7, 8}, note=f"مرجع: {ref_label}. اثرِ مثبت = گران‌تر از مرجع، منفی = ارزان‌تر.")
    for doc, ln in all_lines:
        price = base._base_price(ln)
        ref = None
        if reference == "ORDER":
            ref = sources.get(ln.source_line_id)
        elif reference == "PREVIOUS":
            ref = previous.get(ln.item_id)
        elif reference == "PRICE_LIST":
            ref = price_list.get(ln.item_id)
        else:
            ref = averages.get(ln.item_id)
        previous[ln.item_id] = price
        if ref is None or ln.line_id not in in_range_ids:
            continue
        diff = price - ref
        if (direction == "ABOVE" and diff < _Q2) or (direction == "BELOW" and diff > -_Q2):
            continue
        result.add([doc.document_date, doc.document_no, ctx.names.get(doc.counterparty_detail_account_id, ""),
                    ctx.item_label(ln.item_id), ref_label, ref, price, diff, (diff * 100 / ref) if ref else _ZERO,
                    ln.quantity_base, _money(diff * ln.quantity_base)], (doc.document_id, doc.document_type_code))
    return result


def landed_cost_by_type(company_id: int, f: PurchaseFilters) -> ReportResult:
    """جمعِ هزینه‌هایِ جانبی به تفکیکِ نوع (حمل، گمرک، بیمه، ...) و نسبتِ آن به کلِ خریدِ کالا در بازه."""
    from peecha.db.models.commercial import LandedCostAllocation

    ctx = base._ctx(company_id)
    purchases, _r = base._posted_purchase_and_returns(company_id, f, ctx)
    goods_total = sum((base._net(ln) for _d, ln in purchases), _ZERO)
    doc_ids = {d.document_id for d, _ln in purchases}
    with new_session() as session:
        rows = session.execute(
            select(LandedCostAllocation.cost_type_code, func.sum(LandedCostAllocation.amount),
                   func.count(func.distinct(LandedCostAllocation.purchase_invoice_document_id)))
            .where(LandedCostAllocation.purchase_invoice_document_id.in_(doc_ids))
            .group_by(LandedCostAllocation.cost_type_code)
        ).all() if doc_ids else []
    result = ReportResult([("نوعِ هزینه", TEXT), ("تعدادِ فاکتور", INT), ("مبلغ", MONEY), ("درصد از خریدِ کالا", PERCENT)],
                          no_total={1})
    for code, amount, count in sorted(rows, key=lambda r: -(r[1] or 0)):
        result.add([base._COST_TYPES.get(code or "", code or "نامشخص"), count, amount or _ZERO,
                    ((amount or _ZERO) * 100 / goods_total) if goods_total else _ZERO])
    return result


def actual_procurement_cost(company_id: int, f: PurchaseFilters) -> ReportResult:
    """بهایِ واقعیِ تامین = ارزشِ ثبت‌شده در دفترِ انبار برایِ رسیدِ فاکتورهایِ خرید (فیِ خالص + سهمِ هزینهٔ جانبی)."""
    ctx = base._ctx(company_id)
    purchases, _r = base._posted_purchase_and_returns(company_id, f, ctx)
    ledger = base._line_costs([ln.stock_document_line_id for _d, ln in purchases if ln.stock_document_line_id])
    agg: dict[int, dict] = defaultdict(lambda: {"qty": _ZERO, "invoice": _ZERO, "ledger": _ZERO})
    for _doc, ln in purchases:
        a = agg[ln.item_id]
        a["qty"] += ln.quantity_base
        a["invoice"] += base._net(ln)
        a["ledger"] += ledger.get(ln.stock_document_line_id, base._net(ln))
    result = ReportResult([
        ("کالا", TEXT), ("مقدار (پایه)", QTY), ("مبلغِ فاکتور (خالص)", MONEY), ("هزینهٔ جانبیِ تسهیم‌شده", MONEY),
        ("بهایِ واقعیِ تامین", MONEY), ("فیِ فاکتور", MONEY), ("بهایِ واقعیِ واحد", MONEY), ("درصدِ سربار", PERCENT),
    ], no_total={5, 6, 7})
    for item_id, a in sorted(agg.items(), key=lambda kv: -kv[1]["ledger"]):
        extra = a["ledger"] - a["invoice"]
        result.add([ctx.item_label(item_id), a["qty"], a["invoice"], extra, a["ledger"],
                    (a["invoice"] / a["qty"]) if a["qty"] else _ZERO, (a["ledger"] / a["qty"]) if a["qty"] else _ZERO,
                    (extra * 100 / a["invoice"]) if a["invoice"] else _ZERO])
    return result


# =====================================================================
# عملکردِ تامین‌کننده
# =====================================================================
def _price_cv(company_id: int, f: PurchaseFilters) -> dict[int, dict]:
    """ضریبِ تغییراتِ فی (CV = انحرافِ معیار ÷ میانگین) برایِ هر تامین‌کننده×کالا با ≥ ۲ خرید."""
    ctx = base._ctx(company_id)
    prices: dict[tuple[int, int], list] = defaultdict(list)
    for doc, ln in base._lines(company_id, ("PURCHASE_INVOICE",), ("POSTED",), f, ctx):
        prices[(doc.counterparty_detail_account_id, ln.item_id)].append(base._base_price(ln))
    out: dict[int, dict] = defaultdict(lambda: {"cvs": [], "purchases": 0, "max_change": _ZERO})
    for (supplier_id, _item), values in prices.items():
        a = out[supplier_id]
        a["purchases"] += len(values)
        if len(values) < 2:
            continue
        mean = sum(values, _ZERO) / len(values)
        if mean:
            a["cvs"].append(decimal.Decimal(statistics.pstdev([float(v) for v in values])) / mean * 100)
            a["max_change"] = max(a["max_change"], (max(values) - min(values)) * 100 / min(values) if min(values) else _ZERO)
    return out


def price_stability(company_id: int, f: PurchaseFilters) -> ReportResult:
    """ثباتِ قیمت = ۱۰۰ − میانگینِ CVِ فیِ کالاهایِ تامین‌کننده (کالاهایِ دارایِ ≥ ۲ خرید در بازه)."""
    ctx = base._ctx(company_id)
    result = ReportResult([
        ("تامین‌کننده", TEXT), ("تعدادِ خرید", INT), ("کالاهایِ قابلِ‌مقایسه", INT), ("میانگینِ ضریبِ تغییرات", PERCENT),
        ("بیشترین نوسانِ فی", PERCENT), ("ثباتِ قیمت", PERCENT),
    ], no_total={2})
    for supplier_id, a in sorted(_price_cv(company_id, f).items(), key=lambda kv: ctx.names.get(kv[0], "")):
        cv = (sum(a["cvs"], _ZERO) / len(a["cvs"])) if a["cvs"] else None
        result.add([ctx.names.get(supplier_id, ""), a["purchases"], len(a["cvs"]), cv, a["max_change"],
                    max(_ZERO, 100 - cv) if cv is not None else None])
    return result


def late_orders(company_id: int, f: PurchaseFilters) -> ReportResult:
    """سفارش‌هایِ دیرکرد: رسیده پس از «تاریخِ تحویلِ مورد انتظار»، یا هنوز نرسیده و گذشته از آن."""
    ctx = base._ctx(company_id)
    today = min(f.date_to, datetime.date.today())
    received = {doc.document_id: on for doc, _ln, _r, on in base._received_orders(company_id, f, ctx)}
    result = ReportResult([
        ("شمارهٔ سفارش", INT), ("تاریخ", DATE), ("تامین‌کننده", TEXT), ("تحویلِ مورد انتظار", DATE), ("تاریخِ رسید", DATE),
        ("روزِ تاخیر", DAYS), ("وضعیت", TEXT), ("مبلغ", MONEY),
    ], no_total={0, 5})
    line_dates = _earliest_line_dates([o.document_id for o in _purchase_docs(company_id, f, ("PURCHASE_ORDER",))])
    for o in _purchase_docs(company_id, f, ("PURCHASE_ORDER",)):
        expected = line_dates.get(o.document_id) or o.requested_delivery_date
        if expected is None or o.status_code in ("DRAFT", "CANCELLED"):
            continue
        on = received.get(o.document_id)
        late = ((on or today) - expected).days
        if late <= 0:
            continue
        result.add([o.document_no, o.document_date, ctx.names.get(o.counterparty_detail_account_id, ""), expected,
                    on, late, "رسیده با تاخیر" if on else "هنوز نرسیده", o.total_amount], (o.document_id, o.document_type_code))
    return result


def _earliest_line_dates(document_ids: list[int]) -> dict[int, datetime.date]:
    if not document_ids:
        return {}
    with new_session() as session:
        return dict(session.execute(
            select(CommercialDocumentLine.document_id, func.min(CommercialDocumentLine.expected_delivery_date))
            .where(CommercialDocumentLine.document_id.in_(document_ids), CommercialDocumentLine.expected_delivery_date.is_not(None))
            .group_by(CommercialDocumentLine.document_id)
        ).all())


def inactive_suppliers(company_id: int, f: PurchaseFilters) -> ReportResult:
    days = int(_opt(f, "days", "180"))
    ctx = base._ctx(company_id)
    last: dict[int, datetime.date] = {}
    total: dict[int, decimal.Decimal] = defaultdict(lambda: _ZERO)
    for doc, ln in base._lines(company_id, ("PURCHASE_INVOICE",), ("POSTED",), None, ctx, dated=False):
        last[doc.counterparty_detail_account_id] = max(last.get(doc.counterparty_detail_account_id, doc.document_date), doc.document_date)
        total[doc.counterparty_detail_account_id] += base._net(ln)
    cutoff = f.date_to - datetime.timedelta(days=days)
    result = ReportResult([
        ("تامین‌کننده", TEXT), ("آخرین خرید", DATE), ("روز از آخرین خرید", DAYS), ("کلِ خریدِ سابق", MONEY), ("وضعیت", TEXT),
    ], no_total={2}, note=f"تامین‌کنندگانی که در {days} روزِ پیش از «تا تاریخ» خریدی نداشته‌اند.")
    for s in dimensions_service.list_suppliers(company_id):
        sid = s["detail_account_id"]
        when = last.get(sid)
        if when is not None and when > cutoff:
            continue
        result.add([ctx.names.get(sid, ""), when, (f.date_to - when).days if when else None, total.get(sid, _ZERO),
                    "بدونِ هیچ خرید" if when is None else "غیرفعال"])
    return result


# =====================================================================
# مالی
# =====================================================================
def _open_invoices(company_id: int, as_of: datetime.date, supplier_id: int | None):
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
                    InvoiceSettlement.settlement_date <= as_of)
            ):
                settled[invoice_id] += amount
    return [(d, settled[d.document_id]) for d in docs
            if d.total_amount - settled[d.document_id] > 0 and (supplier_id is None or d.counterparty_detail_account_id == supplier_id)]


def unpaid_invoices(company_id: int, f: PurchaseFilters) -> ReportResult:
    view = _opt(f, "view", "ALL")
    ctx = base._ctx(company_id)
    result = ReportResult([
        ("شماره", INT), ("تاریخ", DATE), ("سررسید", DATE), ("تامین‌کننده", TEXT), ("مبلغِ فاکتور", MONEY), ("پرداخت‌شده", MONEY),
        ("مانده", MONEY), ("روزِ گذشته از سررسید", DAYS), ("وضعیت", TEXT),
    ], no_total={0, 7})
    for doc, paid in sorted(_open_invoices(company_id, f.date_to, f.supplier_id), key=lambda x: x[0].due_date or x[0].document_date):
        due = doc.due_date or doc.document_date
        overdue = (f.date_to - due).days
        if (view == "OVERDUE" and overdue <= 0) or (view == "NOT_DUE" and overdue > 0):
            continue
        result.add([doc.document_no, doc.document_date, due, ctx.names.get(doc.counterparty_detail_account_id, ""), doc.total_amount,
                    paid, doc.total_amount - paid, max(overdue, 0), "سررسیدگذشته" if overdue > 0 else "سررسیدنشده"],
                   (doc.document_id, doc.document_type_code))
    return result


def purchase_payments(company_id: int, f: PurchaseFilters) -> ReportResult:
    from peecha.db.models.accounting import JournalEntry

    ctx = base._ctx(company_id)
    with new_session() as session:
        rows = session.execute(
            select(InvoiceSettlement, CommercialDocument)
            .join(CommercialDocument, CommercialDocument.document_id == InvoiceSettlement.invoice_document_id)
            .where(CommercialDocument.company_id == company_id, CommercialDocument.document_type_code == "PURCHASE_INVOICE",
                   InvoiceSettlement.settlement_date.between(f.date_from, f.date_to))
            .order_by(InvoiceSettlement.settlement_date)
        ).all()
        je_ids = [s.journal_entry_id for s, _d in rows if s.journal_entry_id]
        je_no = {je.journal_entry_id: je.permanent_no or je.temporary_no for je in session.scalars(
            select(JournalEntry).where(JournalEntry.journal_entry_id.in_(je_ids)))} if je_ids else {}
    result = ReportResult([
        ("تاریخِ پرداخت", DATE), ("فاکتور", INT), ("تامین‌کننده", TEXT), ("مبلغ", MONEY), ("سندِ حسابداری", TEXT), ("مرجع", TEXT),
        ("شرح", TEXT),
    ], no_total={1}, note="پرداخت‌هایی که به فاکتورِ خرید تخصیص یافته‌اند (comm.invoice_settlements).")
    for settlement, doc in rows:
        if f.supplier_id is not None and doc.counterparty_detail_account_id != f.supplier_id:
            continue
        result.add([settlement.settlement_date, doc.document_no, ctx.names.get(doc.counterparty_detail_account_id, ""),
                    settlement.amount, str(je_no.get(settlement.journal_entry_id, "")), settlement.reference_no or "",
                    settlement.description or ""], (doc.document_id, doc.document_type_code))
    return result


def purchase_commitments(company_id: int, f: PurchaseFilters) -> ReportResult:
    """تعهداتِ خرید به تفکیکِ تامین‌کننده تا «تا تاریخ»:
    سفارش‌شدهٔ نرسیده = (سفارش − رسید) × فیِ سفارش؛ رسیدهٔ فاکتورنشده = (رسید − فاکتور) × فی؛
    فاکتورِ پرداخت‌نشده = مانده‌یِ فاکتورهایِ ثبت‌شده؛ چکِ پرداختنیِ وصول‌نشده."""
    from peecha.db.models.treasury import CheckStatus, IssuedCheck

    ctx = base._ctx(company_id)
    as_of = PurchaseFilters(datetime.date(1900, 1, 1), f.date_to, f.supplier_id, f.item_id, f.category_id, f.warehouse_id)
    agg: dict[int, dict] = defaultdict(lambda: {"open": _ZERO, "grir": _ZERO, "unpaid": _ZERO, "checks": _ZERO})
    for r in _three_way(company_id, as_of):
        if r["doc"].status_code == "CANCELLED":
            continue
        a = agg[r["doc"].counterparty_detail_account_id]
        a["open"] += max(r["ordered"] - max(r["received"], r["invoiced"]), _ZERO) * r["po_price"]
        a["grir"] += max(r["received"] - r["invoiced"], _ZERO) * r["po_price"]
    for doc, paid in _open_invoices(company_id, f.date_to, f.supplier_id):
        agg[doc.counterparty_detail_account_id]["unpaid"] += doc.total_amount - paid
    with new_session() as session:
        for chk in session.scalars(
            select(IssuedCheck).join(CheckStatus, CheckStatus.status_id == IssuedCheck.status_id)
            .where(IssuedCheck.company_id == company_id, CheckStatus.code == "ISSUED", IssuedCheck.counterparty_detail_account_id.is_not(None))
        ):
            if f.supplier_id is None or chk.counterparty_detail_account_id == f.supplier_id:
                agg[chk.counterparty_detail_account_id]["checks"] += chk.amount
    result = ReportResult([
        ("تامین‌کننده", TEXT), ("سفارش‌شدهٔ نرسیده", MONEY), ("رسیدهٔ فاکتورنشده", MONEY), ("فاکتورِ پرداخت‌نشده", MONEY),
        ("چکِ پرداختنیِ وصول‌نشده", MONEY), ("جمعِ تعهدِ آینده", MONEY),
    ], note="سفارش‌شده/رسیده به فیِ سفارش و بدونِ مالیات؛ فاکتور با مالیات.")
    for sid, a in sorted(agg.items(), key=lambda kv: -sum(kv[1].values())):
        total = _money(a["open"]) + _money(a["grir"]) + a["unpaid"]
        if not (total or a["checks"]):
            continue
        result.add([ctx.names.get(sid, ""), _money(a["open"]), _money(a["grir"]), a["unpaid"], a["checks"], total])
    return result


# =====================================================================
# انبار و تدارکات
# =====================================================================
def _stock_snapshot(company_id: int):
    """(موجودی[کالا، انبار]، موجودی[کالا]، ورودیِ درراه[کالا] از سفارشِ خرید، تقاضایِ باز[کالا] از سفارشِ فروش)."""
    from peecha.db.models.inventory import StockBalance

    with new_session() as session:
        by_wh: dict[tuple[int, int], decimal.Decimal] = defaultdict(lambda: _ZERO)
        for item_id, wid, qty in session.execute(
            select(StockBalance.item_id, StockBalance.warehouse_id, func.sum(StockBalance.quantity_on_hand))
            .where(StockBalance.company_id == company_id).group_by(StockBalance.item_id, StockBalance.warehouse_id)
        ):
            by_wh[(item_id, wid)] = qty or _ZERO
    by_item: dict[int, decimal.Decimal] = defaultdict(lambda: _ZERO)
    for (item_id, _w), qty in by_wh.items():
        by_item[item_id] += qty
    full = PurchaseFilters(datetime.date(1900, 1, 1), datetime.date.today())
    incoming: dict[int, decimal.Decimal] = defaultdict(lambda: _ZERO)
    for r in _three_way(company_id, full):
        incoming[r["line"].item_id] += max(r["ordered"] - max(r["received"], r["invoiced"]), _ZERO)
    ctx = base._ctx(company_id)
    demand: dict[int, decimal.Decimal] = defaultdict(lambda: _ZERO)
    so_pairs = base._lines(company_id, ("SALES_ORDER",), _OPEN_ORDER_STATUSES, None, ctx, dated=False)
    billed = base._invoiced_base_by_source_line(company_id, "SALES_INVOICE", [ln.line_id for _d, ln in so_pairs])
    for _doc, ln in so_pairs:
        demand[ln.item_id] += max(ln.quantity_base - billed.get(ln.line_id, _ZERO), _ZERO)
    return by_wh, by_item, incoming, demand


def _policies(company_id: int) -> list[SimpleNamespace]:
    """سیاستِ سفارشِ کالا×انبار (inv.reorder_policies)؛ برایِ کالاهایِ بدونِ سیاست، پیش‌فرضِ
    حداقل/حداکثر/نقطهٔ سفارشِ خودِ انبار (فرمِ انبار) -- هیچ داده‌ای نوشته نمی‌شود."""
    from peecha.db.models.inventory import ReorderPolicy, Warehouse

    with new_session() as session:
        explicit = [
            SimpleNamespace(item_id=p.item_id, warehouse_id=p.warehouse_id, min_qty=p.min_qty, max_qty=p.max_qty,
                            reorder_point_qty=p.reorder_point_qty, reorder_qty=p.reorder_qty, lead_time_days=p.lead_time_days,
                            source="سیاستِ کالا")
            for p in session.scalars(select(ReorderPolicy).where(ReorderPolicy.company_id == company_id, ReorderPolicy.is_active.is_(True)))
        ]
        defaults = [w for w in session.scalars(select(Warehouse).where(Warehouse.company_id == company_id))
                    if w.default_min_qty is not None or w.default_max_qty is not None or w.default_reorder_point_qty is not None]
    covered = {(p.item_id, p.warehouse_id) for p in explicit} | {(p.item_id, None) for p in explicit if p.warehouse_id is None}
    stocked = [i.item_id for i in catalog_service.list_items(company_id, transactable_only=True)
               if i.is_stock_tracked and i.item_kind_code != "SERVICE"]
    for w in defaults:
        for item_id in stocked:
            if (item_id, w.warehouse_id) in covered or (item_id, None) in covered:
                continue
            explicit.append(SimpleNamespace(
                item_id=item_id, warehouse_id=w.warehouse_id, min_qty=w.default_min_qty, max_qty=w.default_max_qty,
                reorder_point_qty=w.default_reorder_point_qty, reorder_qty=None, lead_time_days=None, source="پیش‌فرضِ انبار"))
    return explicit


_STOCK_VIEWS = (("BELOW_ROP", "زیرِ نقطهٔ سفارش"), ("BELOW_MIN", "زیرِ حداقلِ موجودی"), ("OUT", "ناموجود"),
                ("OVER", "مازاد (بیش از حداکثر)"), ("ALL", "همه"))


def stock_policy_status(company_id: int, f: PurchaseFilters) -> ReportResult:
    """وضعیتِ موجودی در برابرِ سیاستِ سفارش (inv.reorder_policies) برایِ هر کالا×انبار."""
    view = _opt(f, "view", "BELOW_ROP")
    ctx = base._ctx(company_id)
    by_wh, _by_item, incoming, _demand = _stock_snapshot(company_id)
    result = ReportResult([
        ("کالا", TEXT), ("انبار", TEXT), ("موجودی", QTY), ("حداقل", QTY), ("نقطهٔ سفارش", QTY), ("حداکثر", QTY),
        ("در راه (سفارشِ خرید)", QTY), ("وضعیت", TEXT), ("منبعِ سیاست", TEXT),
    ], no_total={3, 4, 5}, note="سیاستِ سفارشِ کالا، وگرنه پیش‌فرضِ حداقل/حداکثر/نقطهٔ سفارشِ انبار (فرمِ انبار).")
    for p in _policies(company_id):
        if (f.item_id is not None and p.item_id != f.item_id) or (f.warehouse_id is not None and p.warehouse_id != f.warehouse_id):
            continue
        item = ctx.items.get(p.item_id)
        if f.category_id is not None and (item is None or item.category_id != f.category_id):
            continue
        qty = by_wh.get((p.item_id, p.warehouse_id), _ZERO) if p.warehouse_id else sum(
            (q for (i, _w), q in by_wh.items() if i == p.item_id), _ZERO)
        states = []
        if qty <= 0:
            states.append("OUT")
        if p.min_qty is not None and qty < p.min_qty:
            states.append("BELOW_MIN")
        if p.reorder_point_qty is not None and qty <= p.reorder_point_qty:
            states.append("BELOW_ROP")
        if p.max_qty is not None and qty > p.max_qty:
            states.append("OVER")
        if view != "ALL" and view not in states:
            continue
        labels = dict(_STOCK_VIEWS)
        result.add([ctx.item_label(p.item_id), ctx.warehouses.get(p.warehouse_id, "همهٔ انبارها") if p.warehouse_id else "همهٔ انبارها",
                    qty, p.min_qty, p.reorder_point_qty, p.max_qty, incoming.get(p.item_id, _ZERO),
                    "، ".join(labels[s] for s in states) or "عادی", p.source])
    return result


def suggested_purchase(company_id: int, f: PurchaseFilters) -> ReportResult:
    """پیشنهادِ خرید (فقط پیشنهاد -- سندی ساخته نمی‌شود):
    در دسترس = موجودی + در راه − تقاضایِ بازِ سفارشِ فروش؛ اگر ≤ نقطهٔ سفارش:
    پیشنهاد = (حداکثر، وگرنه نقطهٔ سفارش + مقدارِ سفارش) − در دسترس؛ گردشده به بسته‌بندی و حداقلِ سفارشِ کالا."""
    from peecha.db.models.inventory import ItemSupplier

    ctx = base._ctx(company_id)
    _by_wh, by_item, incoming, demand = _stock_snapshot(company_id)
    last_price: dict[int, tuple] = {}
    for doc, ln in base._lines(company_id, ("PURCHASE_INVOICE",), ("POSTED",), None, ctx, dated=False):
        last_price[ln.item_id] = (base._base_price(ln), doc.counterparty_detail_account_id)
    with new_session() as session:
        preferred = {i: s for i, s in session.execute(
            select(ItemSupplier.item_id, ItemSupplier.supplier_detail_account_id).where(ItemSupplier.is_preferred.is_(True)))}
    policies: dict[int, list] = defaultdict(list)
    for p in _policies(company_id):
        policies[p.item_id].append(p)
    result = ReportResult([
        ("کالا", TEXT), ("موجودی", QTY), ("در راه", QTY), ("تقاضایِ باز", QTY), ("در دسترس", QTY), ("نقطهٔ سفارش", QTY),
        ("هدف", QTY), ("مقدارِ پیشنهادی", QTY), ("تامین‌کنندهٔ پیشنهادی", TEXT), ("آخرین فی", MONEY), ("ارزشِ تقریبی", MONEY),
    ], no_total={5, 6, 9}, note="سیاستِ سفارشِ همهٔ انبارهایِ کالا با هم جمع می‌شود؛ هیچ سفارشی خودکار ساخته نمی‌شود.")
    for item_id, plist in policies.items():
        item = ctx.items.get(item_id)
        if item is None or (f.item_id is not None and item_id != f.item_id) or (f.category_id is not None and item.category_id != f.category_id):
            continue
        rop = sum((p.reorder_point_qty or _ZERO for p in plist), _ZERO)
        target = sum(((p.max_qty if p.max_qty is not None else (p.reorder_point_qty or _ZERO) + (p.reorder_qty or _ZERO)) for p in plist), _ZERO)
        available = by_item.get(item_id, _ZERO) + incoming.get(item_id, _ZERO) - demand.get(item_id, _ZERO)
        if available > rop:
            continue
        qty = max(target - available, _ZERO)
        if item.purchase_package_qty:
            pack = item.purchase_package_qty
            qty = (qty / pack).to_integral_value(rounding=decimal.ROUND_CEILING) * pack
        if item.purchase_min_order_qty and qty < item.purchase_min_order_qty:
            qty = item.purchase_min_order_qty
        if qty <= 0:
            continue
        price, last_supplier = last_price.get(item_id, (None, None))
        supplier = preferred.get(item_id) or last_supplier
        result.add([ctx.item_label(item_id), by_item.get(item_id, _ZERO), incoming.get(item_id, _ZERO), demand.get(item_id, _ZERO),
                    available, rop, target, qty, ctx.names.get(supplier, "") if supplier else "", price,
                    _money(price * qty) if price else None])
    return result


def demand_without_po(company_id: int, f: PurchaseFilters) -> ReportResult:
    """تقاضایِ سفارش‌هایِ فروشِ باز که با موجودی و سفارشِ خریدِ درراه پوشش داده نشده:
    کمبود = تقاضایِ باز − موجودی − در راه."""
    ctx = base._ctx(company_id)
    _by_wh, by_item, incoming, demand = _stock_snapshot(company_id)
    result = ReportResult([
        ("کالا", TEXT), ("تقاضایِ سفارشِ فروش", QTY), ("موجودی", QTY), ("در راه (سفارشِ خرید)", QTY), ("کمبود", QTY),
    ])
    for item_id, need in sorted(demand.items(), key=lambda kv: ctx.item_label(kv[0])):
        item = ctx.items.get(item_id)
        if (f.item_id is not None and item_id != f.item_id) or (f.category_id is not None and (item is None or item.category_id != f.category_id)):
            continue
        shortage = need - by_item.get(item_id, _ZERO) - incoming.get(item_id, _ZERO)
        if shortage > 0:
            result.add([ctx.item_label(item_id), need, by_item.get(item_id, _ZERO), incoming.get(item_id, _ZERO), shortage])
    return result


def _outflow(company_id: int, date_from: datetime.date, date_to: datetime.date):
    """مصرف/فروش (خروجِ ISSUE -- نه برگشت/انتقال) و آخرین آن، از دفترِ انبار."""
    from peecha.db.models.inventory import StockDocument, StockDocumentLine, StockLedger

    with new_session() as session:
        usage = dict(session.execute(
            select(StockLedger.item_id, func.sum(StockLedger.quantity_base))
            .join(StockDocumentLine, StockDocumentLine.line_id == StockLedger.stock_document_line_id)
            .join(StockDocument, StockDocument.stock_document_id == StockDocumentLine.stock_document_id)
            .where(StockLedger.company_id == company_id, StockLedger.movement_direction == "OUT",
                   StockDocument.document_type_code == "ISSUE", StockLedger.movement_date.between(date_from, date_to))
            .group_by(StockLedger.item_id)
        ).all())
        last_out = dict(session.execute(
            select(StockLedger.item_id, func.max(StockLedger.movement_date))
            .join(StockDocumentLine, StockDocumentLine.line_id == StockLedger.stock_document_line_id)
            .join(StockDocument, StockDocument.stock_document_id == StockDocumentLine.stock_document_id)
            .where(StockLedger.company_id == company_id, StockLedger.movement_direction == "OUT",
                   StockDocument.document_type_code == "ISSUE").group_by(StockLedger.item_id)
        ).all())
        value = dict(session.execute(
            select(StockLedger.item_id, func.sum(StockLedger.quantity_base * StockLedger.unit_cost))
            .where(StockLedger.company_id == company_id).group_by(StockLedger.item_id)
        ).all())
    return usage, last_out, value


def reorder_analysis(company_id: int, f: PurchaseFilters) -> ReportResult:
    """مصرفِ روزانه = خروجِ ISSUEِ بازه ÷ روزهایِ بازه؛ پوشش (روز) = موجودی ÷ مصرفِ روزانه؛
    نقطهٔ سفارشِ محاسبه‌ای = مصرفِ روزانه × زمانِ تحویل + ذخیرهٔ اطمینان (= حداقلِ سیاست)."""
    from peecha.db.models.inventory import ItemSupplier

    ctx = base._ctx(company_id)
    days = max((f.date_to - f.date_from).days + 1, 1)
    usage, _last, _v = _outflow(company_id, f.date_from, f.date_to)
    _by_wh, by_item, _inc, _dem = _stock_snapshot(company_id)
    with new_session() as session:
        supplier_lead = {i: d for i, d in session.execute(
            select(ItemSupplier.item_id, ItemSupplier.lead_time_days).where(ItemSupplier.is_preferred.is_(True)))}
    policies: dict[int, list] = defaultdict(list)
    for p in _policies(company_id):
        policies[p.item_id].append(p)
    items = set(policies) | set(usage)
    result = ReportResult([
        ("کالا", TEXT), ("موجودی", QTY), ("مصرفِ بازه", QTY), ("مصرفِ روزانه", QTY), ("زمانِ تحویل (روز)", DAYS),
        ("ذخیرهٔ اطمینان", QTY), ("نقطهٔ سفارشِ تعریف‌شده", QTY), ("نقطهٔ سفارشِ محاسبه‌ای", QTY), ("پوشش (روز)", DAYS),
        ("ارزیابی", TEXT),
    ], no_total={3, 4, 5, 6, 7, 8})
    for item_id in sorted(items, key=ctx.item_label):
        item = ctx.items.get(item_id)
        if item is None or (f.item_id is not None and item_id != f.item_id) or (f.category_id is not None and item.category_id != f.category_id):
            continue
        plist = policies.get(item_id, [])
        lead = next((p.lead_time_days for p in plist if p.lead_time_days), None) or item.purchase_lead_time_days or supplier_lead.get(item_id)
        safety = sum((p.min_qty or _ZERO for p in plist), _ZERO)
        defined = sum((p.reorder_point_qty or _ZERO for p in plist), _ZERO) if plist else None
        daily = (usage.get(item_id, _ZERO) or _ZERO) / days
        computed = daily * (lead or 0) + safety
        on_hand = by_item.get(item_id, _ZERO)
        coverage = int(on_hand / daily) if daily else None
        if lead is None:
            verdict = "زمانِ تحویل تعریف نشده"
        elif coverage is not None and coverage < lead:
            verdict = "خطرِ کمبود (پوشش کمتر از زمانِ تحویل)"
        elif defined is not None and computed and abs(defined - computed) > computed * decimal.Decimal("0.2"):
            verdict = "نقطهٔ سفارش نیازِ بازبینی دارد"
        else:
            verdict = "مناسب"
        result.add([ctx.item_label(item_id), on_hand, usage.get(item_id, _ZERO) or _ZERO, daily, lead, safety, defined,
                    computed, coverage, verdict])
    return result


def slow_and_dead_stock(company_id: int, f: PurchaseFilters) -> ReportResult:
    """راکد = موجودی > ۰ و بدونِ هیچ خروج در N روزِ اخیر؛ کم‌گردش = پوششِ موجودی (بر مبنایِ مصرفِ N روز) بیش از N روز."""
    threshold = int(_opt(f, "days", "180"))
    view = _opt(f, "view", "DEAD")
    ctx = base._ctx(company_id)
    as_of = f.date_to
    usage, last_out, value = _outflow(company_id, as_of - datetime.timedelta(days=threshold), as_of)
    _by_wh, by_item, _inc, _dem = _stock_snapshot(company_id)
    result = ReportResult([
        ("کالا", TEXT), ("موجودی", QTY), ("ارزشِ موجودی", MONEY), ("آخرین فروش/مصرف", DATE), ("روز از آخرین فروش/مصرف", DAYS),
        (f"مصرفِ {threshold} روزِ اخیر", QTY), ("پوشش (روز)", DAYS), ("وضعیت", TEXT),
    ], no_total={4, 6})
    for item_id, qty in sorted(by_item.items(), key=lambda kv: ctx.item_label(kv[0])):
        item = ctx.items.get(item_id)
        if qty <= 0 or item is None or (f.item_id is not None and item_id != f.item_id) \
                or (f.category_id is not None and item.category_id != f.category_id):
            continue
        used = usage.get(item_id) or _ZERO
        coverage = int(qty / (used / threshold)) if used else None
        status = "راکد" if not used else "کم‌گردش" if coverage is not None and coverage > threshold else "فعال"
        if (view == "DEAD" and status != "راکد") or (view == "SLOW" and status != "کم‌گردش") or (view == "BOTH" and status == "فعال"):
            continue
        last = last_out.get(item_id)
        result.add([ctx.item_label(item_id), qty, _money(value.get(item_id) or _ZERO), last, (as_of - last).days if last else None,
                    used, coverage, status])
    return result


# =====================================================================
# اطلاعاتِ پایه
# =====================================================================
def supplier_terms(company_id: int, f: PurchaseFilters) -> ReportResult:
    from peecha.db.models.commercial import SupplierProfile

    ctx = base._ctx(company_id)
    with new_session() as session:
        profiles = {p.supplier_detail_account_id: p for p in session.scalars(
            select(SupplierProfile).where(SupplierProfile.company_id == company_id))}
    result = ReportResult([
        ("تامین‌کننده", TEXT), ("مهلتِ پرداخت (روز)", INT), ("شرطِ تحویل (Incoterm)", TEXT), ("زمانِ تحویلِ پیش‌فرض", TEXT),
        ("سقفِ اعتبار", MONEY), ("امتیازِ کیفیت", TEXT), ("وضعیت", TEXT),
    ], no_total={1})
    for s in dimensions_service.list_suppliers(company_id):
        sid = s["detail_account_id"]
        if f.supplier_id is not None and sid != f.supplier_id:
            continue
        p = profiles.get(sid)
        result.add([ctx.names.get(sid, ""), p.payment_term_days if p else 0, (p.incoterm_code or "") if p else "",
                    f"{p.default_lead_time_days} روز" if p and p.default_lead_time_days else "", p.credit_limit_amount if p else _ZERO,
                    str(p.quality_rating) if p and p.quality_rating is not None else "", (p.status_code if p else "بدونِ پروفایل")])
    return result


def purchase_contracts(company_id: int, f: PurchaseFilters) -> ReportResult:
    from peecha.db.models.commercial import CommercialContract

    ctx = base._ctx(company_id)
    with new_session() as session:
        rows = list(session.scalars(select(CommercialContract).where(
            CommercialContract.company_id == company_id, CommercialContract.contract_type_code == "PURCHASE")))
    result = ReportResult([
        ("تامین‌کننده", TEXT), ("کالا", TEXT), ("فیِ قرارداد", MONEY), ("مقدارِ تعهد", QTY), ("مصرف‌شده", QTY), ("مبلغِ تعهد", MONEY),
        ("مبلغِ مصرف‌شده", MONEY), ("از", DATE), ("تا", DATE), ("وضعیت", TEXT),
    ], no_total={2})
    for c in rows:
        if f.supplier_id is not None and c.counterparty_detail_account_id != f.supplier_id:
            continue
        result.add([ctx.names.get(c.counterparty_detail_account_id, ""), ctx.item_label(c.item_id) if c.item_id else "همه",
                    c.contract_price, c.committed_quantity, c.consumed_quantity, c.committed_amount, c.consumed_amount,
                    c.valid_from, c.valid_to, c.status_code])
    return result


def discount_rules(company_id: int, f: PurchaseFilters) -> ReportResult:
    from peecha.db.models.commercial import DiscountRule

    with new_session() as session:
        rows = list(session.scalars(select(DiscountRule).where(DiscountRule.company_id == company_id).order_by(DiscountRule.priority)))
    types = {"PERCENT": "درصدی", "AMOUNT": "مبلغی", "TIERED": "پلکانی", "BUNDLE": "بسته‌ای"}
    scopes = {"ITEM": "کالا", "CATEGORY": "گروهِ کالا", "CUSTOMER_GROUP": "گروهِ مشتری", "ALL": "همه"}
    result = ReportResult([
        ("کد", TEXT), ("نام", TEXT), ("نوع", TEXT), ("دامنه", TEXT), ("مقدار", MONEY), ("اولویت", INT), ("ترکیب‌پذیر", TEXT),
        ("از", DATE), ("تا", DATE), ("فعال", TEXT),
    ], no_total={4, 5}, note="قواعدِ تخفیفِ تعریف‌شده در «قیمت‌گذاری» (عمدتاً سمتِ فروش).")
    for r in rows:
        result.add([r.code, r.name, types.get(r.discount_type_code, r.discount_type_code), scopes.get(r.scope_type_code, r.scope_type_code),
                    r.discount_value, r.priority, "بله" if r.is_stackable else "خیر", r.valid_from, r.valid_to,
                    "بله" if r.is_active else "خیر"])
    return result


def return_reasons(company_id: int, f: PurchaseFilters) -> ReportResult:
    from peecha.db.models.inventory import DocumentReasonCode, StockDocumentLine

    with new_session() as session:
        rows = list(session.scalars(select(DocumentReasonCode).where(
            (DocumentReasonCode.company_id == company_id) | DocumentReasonCode.company_id.is_(None),
            DocumentReasonCode.applies_to.in_(("RETURN_OUT", "RETURN_IN")))))
        usage = dict(session.execute(
            select(StockDocumentLine.reason_code_id, func.count()).where(
                StockDocumentLine.reason_code_id.in_([r.reason_code_id for r in rows])).group_by(StockDocumentLine.reason_code_id)
        ).all()) if rows else {}
    result = ReportResult([("نوع", TEXT), ("کد", TEXT), ("عنوان", TEXT), ("فعال", TEXT), ("دفعاتِ استفاده", INT)],
                          note="علت‌هایِ برگشت قابلِ‌تعریف در «کدهایِ علتِ اسنادِ انبار» هستند (inv.document_reason_codes).")
    for r in sorted(rows, key=lambda x: (x.applies_to, x.code)):
        result.add(["برگشت به تامین‌کننده" if r.applies_to == "RETURN_OUT" else "برگشت از فروش", r.code, r.name,
                    "بله" if r.is_active else "خیر", usage.get(r.reason_code_id, 0)])
    return result


_APPROVAL_FEATURES = (
    "PURCHASE_ORDER_SKIP_APPROVAL", "PURCHASE_INVOICE_SKIP_APPROVAL", "PURCHASE_ORDER_GOODS_RECEIPT", "PURCHASE_ORDER_SKIP_POST",
    "RECEIPT_LOCKS_INVOICE_QUANTITY", "INVOICE_ONE_STEP_POST", "CONSIGNMENT_WAREHOUSE_APPROVAL", "ALLOW_EDIT_POSTED_INVOICE",
    "SALES_ORDER_WAREHOUSE_ISSUE", "SALES_ORDER_SKIP_POST", "SALES_ORDER_MANAGER_APPROVAL", "SALES_INVOICE_MANAGER_APPROVAL",
)


def approval_rules(company_id: int, f: PurchaseFilters) -> ReportResult:
    from peecha.services import commercial_settings as settings_service

    names = {row.feature_code: row.name for row in settings_service.list_features(company_id)}
    result = ReportResult([("قاعده", TEXT), ("کد", TEXT), ("وضعیت", TEXT)],
                          note="قواعدِ تایید/مراحلِ گردشِ کارِ خرید و فروش (تنظیمات ‹ فعال‌سازیِ امکانات).")
    for code in _APPROVAL_FEATURES:
        result.add([names.get(code, code), code, "روشن" if settings_service.is_feature_enabled(company_id, code) else "خاموش"])
    return result


# =====================================================================
# R240: تاریخچهٔ تغییرات/تصویب، تفکیکِ وظایف، لغو، نوعِ خرید، تحویلِ ردیفی
# =====================================================================
_FIELD_LABELS = {
    "quantity": "مقدار", "unit_price": "فی", "discount_amount": "تخفیف", "tax_percent": "درصدِ مالیات",
    "expected_delivery_date": "تاریخِ تحویلِ ردیف", "document_date": "تاریخِ سند", "counterparty_detail_account_id": "طرفِ حساب",
    "warehouse_id": "انبار", "requested_delivery_date": "تاریخِ تحویل", "purchase_type_id": "نوعِ خرید", "status_code": "وضعیت",
}
_ACTION_LABELS = {"ADD_LINE": "افزودنِ ردیف", "UPDATE_LINE": "ویرایشِ ردیف", "DELETE_LINE": "حذفِ ردیف",
                  "UPDATE_HEADER": "ویرایشِ سرِ سند", "STATUS": "تغییرِ وضعیت"}


def _change_logs(company_id: int, f: PurchaseFilters, actions: tuple[str, ...]):
    from peecha.db.models.commercial import DocumentChangeLog

    start = datetime.datetime.combine(f.date_from, datetime.time.min)
    end = datetime.datetime.combine(f.date_to, datetime.time.max)
    with new_session() as session:
        rows = session.execute(
            select(DocumentChangeLog, CommercialDocument)
            .join(CommercialDocument, CommercialDocument.document_id == DocumentChangeLog.document_id)
            .where(CommercialDocument.company_id == company_id, CommercialDocument.document_type_code.in_(tuple(_TITLES)),
                   DocumentChangeLog.action.in_(actions), DocumentChangeLog.changed_at.between(start, end))
            .order_by(DocumentChangeLog.changed_at, DocumentChangeLog.log_id)
        ).all()
        line_items = dict(session.execute(
            select(CommercialDocumentLine.line_id, CommercialDocumentLine.item_id)
            .where(CommercialDocumentLine.line_id.in_({log.line_id for log, _d in rows if log.line_id}))
        ).all()) if rows else {}
    return [(log, doc) for log, doc in rows if f.supplier_id is None or doc.counterparty_detail_account_id == f.supplier_id], line_items


def changes_after_approval(company_id: int, f: PurchaseFilters) -> ReportResult:
    """تغییرِ ردیف/سرِ سند پس از اولین تایید (سند به پیش‌نویس برگشته و ویرایش شده)."""
    scope = _opt(f, "scope", "PRICE_QTY")
    ctx = base._ctx(company_id)
    users = _users()
    logs, line_items = _change_logs(company_id, f, ("ADD_LINE", "UPDATE_LINE", "DELETE_LINE", "UPDATE_HEADER"))
    result = ReportResult([
        ("زمانِ تغییر", TEXT), ("نوع", TEXT), ("شماره", INT), ("تامین‌کننده", TEXT), ("کالا", TEXT), ("عملیات", TEXT),
        ("فیلد", TEXT), ("مقدارِ قبلی", TEXT), ("مقدارِ جدید", TEXT), ("کاربر", TEXT),
    ], no_total={2}, note="از R240 ثبت می‌شود: هر تغییری که پس از اولین تایید/تصویبِ سند انجام شده است.")
    for log, doc in logs:
        if scope == "PRICE_QTY" and log.field_name not in ("quantity", "unit_price", "discount_amount"):
            continue
        item_id = line_items.get(log.line_id)
        result.add([_when(log.changed_at), _TITLES[doc.document_type_code], doc.document_no,
                    ctx.names.get(doc.counterparty_detail_account_id, ""),
                    ctx.item_label(item_id) if item_id else ("ردیفِ حذف‌شده" if log.action == "DELETE_LINE" else ""),
                    _ACTION_LABELS.get(log.action, log.action), _FIELD_LABELS.get(log.field_name, log.field_name or ""),
                    log.old_value or "", log.new_value or "", users.get(log.user_id, "")], (doc.document_id, doc.document_type_code))
    return result


def modified_documents(company_id: int, f: PurchaseFilters) -> ReportResult:
    ctx = base._ctx(company_id)
    users = _users()
    logs, _items = _change_logs(company_id, f, ("ADD_LINE", "UPDATE_LINE", "DELETE_LINE", "UPDATE_HEADER", "STATUS"))
    agg: dict[int, dict] = {}
    for log, doc in logs:
        a = agg.setdefault(doc.document_id, {"doc": doc, "changes": 0, "reverts": 0, "users": set(), "last": None})
        if log.action == "STATUS":
            if log.new_value == "DRAFT":
                a["reverts"] += 1
            continue
        a["changes"] += 1
        a["users"].add(users.get(log.user_id, ""))
        a["last"] = log.changed_at
    result = ReportResult([
        ("نوع", TEXT), ("شماره", INT), ("تاریخ", DATE), ("تامین‌کننده", TEXT), ("وضعیت", TEXT), ("دفعاتِ بازگشت به پیش‌نویس", INT),
        ("تعدادِ تغییر پس از تایید", INT), ("آخرین تغییر", TEXT), ("تغییردهندگان", TEXT), ("مبلغ", MONEY),
    ], no_total={1}, note="اسنادی که پس از تایید به پیش‌نویس برگشته یا ویرایش شده‌اند.")
    for a in sorted(agg.values(), key=lambda a: -a["changes"]):
        if not (a["changes"] or a["reverts"]):
            continue
        d = a["doc"]
        result.add([_TITLES[d.document_type_code], d.document_no, d.document_date, ctx.names.get(d.counterparty_detail_account_id, ""),
                    base._STATUS_LABELS.get(d.status_code, d.status_code), a["reverts"], a["changes"], _when(a["last"]),
                    "، ".join(sorted(u for u in a["users"] if u)), d.total_amount], (d.document_id, d.document_type_code))
    return result


def _status_events(document_ids: list[int]) -> dict[int, list]:
    from peecha.db.models.commercial import DocumentChangeLog

    out: dict[int, list] = defaultdict(list)
    if not document_ids:
        return out
    with new_session() as session:
        for log in session.scalars(select(DocumentChangeLog).where(
                DocumentChangeLog.document_id.in_(document_ids), DocumentChangeLog.action == "STATUS")
                .order_by(DocumentChangeLog.changed_at, DocumentChangeLog.log_id)):
            out[log.document_id].append(log)
    return out


def approval_history(company_id: int, f: PurchaseFilters) -> ReportResult:
    """ایجاد → تایید → تصویبِ مدیر → ثبتِ نهایی، با کاربر و زمانِ هر مرحله و فاصلهٔ ساعتِ تصویب."""
    ctx = base._ctx(company_id)
    users = _users()
    docs = [d for d in _purchase_docs(company_id, f, ("PURCHASE_ORDER", "PURCHASE_PROFORMA", "PURCHASE_INVOICE"))
            if d.status_code != "DRAFT"]
    events = _status_events([d.document_id for d in docs])

    def stamp(user_id, when):
        return f"{users.get(user_id, '')} -- {_when(when)}" if when else ""

    result = ReportResult([
        ("نوع", TEXT), ("شماره", INT), ("تاریخ", DATE), ("تامین‌کننده", TEXT), ("وضعیت", TEXT), ("ایجاد", TEXT),
        ("تاییدِ کاربر", TEXT), ("تصویبِ مدیر", TEXT), ("ثبتِ نهایی", TEXT), ("بازگشت به پیش‌نویس", INT),
        ("ساعتِ انتظارِ تصویب", INT), ("مبلغ", MONEY),
    ], no_total={1, 10}, note="مراحلِ تایید از R240 ثبت می‌شوند؛ برایِ اسنادِ قدیمی فقط ایجاد و ثبتِ نهایی موجود است.")
    for d in docs:
        evs = events.get(d.document_id, [])
        confirm = next((e for e in reversed(evs) if e.new_value == "CONFIRMED"), None)
        wait = None
        if confirm is not None and d.approved_at is not None:
            wait = int((d.approved_at - confirm.changed_at).total_seconds() // 3600)
        result.add([_TITLES[d.document_type_code], d.document_no, d.document_date, ctx.names.get(d.counterparty_detail_account_id, ""),
                    base._STATUS_LABELS.get(d.status_code, d.status_code), stamp(d.created_by_user_id, d.created_at),
                    stamp(confirm.user_id, confirm.changed_at) if confirm else "", stamp(d.approved_by_user_id, d.approved_at),
                    stamp(d.posted_by_user_id, d.posted_at), sum(1 for e in evs if e.new_value == "DRAFT"), wait, d.total_amount],
                   (d.document_id, d.document_type_code))
    return result


def segregation_violations(company_id: int, f: PurchaseFilters) -> ReportResult:
    """تخلفاتِ تفکیکِ وظایف: ایجادکننده = تصویب‌کننده، تصویب‌کننده بدونِ نقشِ مدیر، ایجادکننده = تاییدکنندهٔ رسید."""
    from peecha.services import roles as roles_service

    ctx = base._ctx(company_id)
    users = _users()
    managers: dict[int, bool] = {}
    result = ReportResult([
        ("نوع", TEXT), ("شماره", INT), ("تاریخ", DATE), ("تامین‌کننده", TEXT), ("مبلغ", MONEY), ("کاربر", TEXT), ("تخلف", TEXT),
    ], no_total={1}, note="قاعده‌ها فقط گزارش می‌شوند؛ جلویِ عملیات گرفته نمی‌شود.")
    for d in _purchase_docs(company_id, f, ("PURCHASE_ORDER", "PURCHASE_PROFORMA", "PURCHASE_INVOICE")):
        issues = []
        if d.approved_by_user_id is not None:
            if d.approved_by_user_id == d.created_by_user_id:
                issues.append((d.approved_by_user_id, "ایجاد و تصویبِ سند توسطِ یک کاربر"))
            if d.approved_by_user_id not in managers:
                managers[d.approved_by_user_id] = roles_service.is_manager(d.approved_by_user_id, company_id)
            if not managers[d.approved_by_user_id]:
                issues.append((d.approved_by_user_id, "تصویب توسطِ کاربرِ بدونِ نقشِ مدیر"))
        if d.warehouse_approved_by_user_id is not None and d.warehouse_approved_by_user_id == d.created_by_user_id:
            issues.append((d.created_by_user_id, "ثبتِ سفارش و تاییدِ رسیدِ انبار توسطِ یک کاربر"))
        for user_id, text in issues:
            result.add([_TITLES[d.document_type_code], d.document_no, d.document_date,
                        ctx.names.get(d.counterparty_detail_account_id, ""), d.total_amount, users.get(user_id, ""), text],
                       (d.document_id, d.document_type_code))
    return result


def cancellation_analysis(company_id: int, f: PurchaseFilters) -> ReportResult:
    reasons = _cancel_reason_names(company_id)
    docs = [d for d in _purchase_docs(company_id, f) if d.status_code == "CANCELLED"]
    agg: dict[str, list] = defaultdict(lambda: [0, _ZERO])
    for d in docs:
        a = agg[reasons.get(d.cancellation_reason_id, "— ثبت‌نشده —")]
        a[0] += 1
        a[1] += d.total_amount
    total = sum(a[0] for a in agg.values())
    result = ReportResult([("علتِ لغو", TEXT), ("تعداد", INT), ("مبلغ", MONEY), ("سهم از لغوها", PERCENT)])
    for name, (count, amount) in sorted(agg.items(), key=lambda kv: -kv[1][0]):
        result.add([name, count, amount, decimal.Decimal(count * 100) / total if total else _ZERO])
    return result


def emergency_purchases(company_id: int, f: PurchaseFilters) -> ReportResult:
    from peecha.services import procurement_masters as masters_service

    ctx = base._ctx(company_id)
    types = {t.purchase_type_id: t for t in masters_service.list_purchase_types(company_id)}
    result = ReportResult([
        ("نوع", TEXT), ("شماره", INT), ("تاریخ", DATE), ("تامین‌کننده", TEXT), ("نوعِ خرید", TEXT), ("وضعیت", TEXT), ("مبلغ", MONEY),
    ], no_total={1}, note="اسنادی که نوعِ خریدشان «اضطراری» علامت خورده است.")
    for d in _purchase_docs(company_id, f, ("PURCHASE_ORDER", "PURCHASE_INVOICE")):
        t = types.get(d.purchase_type_id)
        if t is None or not t.is_emergency or d.status_code == "CANCELLED":
            continue
        result.add([_TITLES[d.document_type_code], d.document_no, d.document_date, ctx.names.get(d.counterparty_detail_account_id, ""),
                    t.name, base._STATUS_LABELS.get(d.status_code, d.status_code), d.total_amount], (d.document_id, d.document_type_code))
    return result


def line_delivery(company_id: int, f: PurchaseFilters) -> ReportResult:
    """تحویلِ ردیفی: تاریخِ موردِ انتظارِ ردیف (وگرنه سرِ سند) در برابرِ تاریخِ رسید."""
    view = _opt(f, "view", "ALL")
    ctx = base._ctx(company_id)
    today = min(f.date_to, datetime.date.today())
    received = {ln.line_id: on for _doc, ln, _r, on in base._received_orders(company_id, f, ctx)}
    result = ReportResult([
        ("شمارهٔ سفارش", INT), ("تامین‌کننده", TEXT), ("کالا", TEXT), ("مقدار", QTY), ("تحویلِ موردِ انتظار", DATE), ("منبعِ تاریخ", TEXT),
        ("تاریخِ رسید", DATE), ("روزِ تاخیر", DAYS), ("وضعیت", TEXT),
    ], no_total={0, 7})
    for doc, ln in base._lines(company_id, ("PURCHASE_ORDER",), _OPEN_ORDER_STATUSES, f, ctx):
        expected = ln.expected_delivery_date or doc.requested_delivery_date
        if expected is None:
            continue
        on = received.get(ln.line_id)
        delay = ((on or today) - expected).days
        state = ("به‌موقع" if delay <= 0 else "با تاخیر") if on else ("دیرکرد -- نرسیده" if delay > 0 else "در انتظار")
        if (view == "LATE" and delay <= 0) or (view == "OPEN" and on is not None):
            continue
        result.add([doc.document_no, ctx.names.get(doc.counterparty_detail_account_id, ""), ctx.item_label(ln.item_id), ln.quantity_base,
                    expected, "ردیف" if ln.expected_delivery_date else "سرِ سند", on, max(delay, 0), state],
                   (doc.document_id, doc.document_type_code))
    return result


def purchase_types_master(company_id: int, f: PurchaseFilters) -> ReportResult:
    from peecha.services import procurement_masters as masters_service

    with new_session() as session:
        usage = dict(session.execute(select(CommercialDocument.purchase_type_id, func.count()).where(
            CommercialDocument.company_id == company_id, CommercialDocument.purchase_type_id.is_not(None))
            .group_by(CommercialDocument.purchase_type_id)).all())
    result = ReportResult([("کد", TEXT), ("عنوان", TEXT), ("اضطراری", TEXT), ("فعال", TEXT), ("تعدادِ اسناد", INT)])
    for t in masters_service.list_purchase_types(company_id):
        result.add([t.code, t.name, "بله" if t.is_emergency else "خیر", "بله" if t.is_active else "خیر", usage.get(t.purchase_type_id, 0)])
    return result


def cancellation_reasons_master(company_id: int, f: PurchaseFilters) -> ReportResult:
    from peecha.services import procurement_masters as masters_service

    with new_session() as session:
        usage = dict(session.execute(select(CommercialDocument.cancellation_reason_id, func.count()).where(
            CommercialDocument.company_id == company_id, CommercialDocument.cancellation_reason_id.is_not(None))
            .group_by(CommercialDocument.cancellation_reason_id)).all())
    result = ReportResult([("کد", TEXT), ("عنوان", TEXT), ("فعال", TEXT), ("تعدادِ اسناد", INT)])
    for r in masters_service.list_cancellation_reasons(company_id):
        result.add([r.code, r.name, "بله" if r.is_active else "خیر", usage.get(r.reason_id, 0)])
    return result


def reorder_policies_master(company_id: int, f: PurchaseFilters) -> ReportResult:
    from peecha.services import procurement_masters as masters_service

    ctx = base._ctx(company_id)
    result = ReportResult([
        ("کالا", TEXT), ("انبار", TEXT), ("حداقل", QTY), ("نقطهٔ سفارش", QTY), ("حداکثر", QTY), ("مقدارِ سفارش", QTY),
        ("زمانِ تحویل (روز)", DAYS), ("فعال", TEXT),
    ], no_total={2, 3, 4, 5, 6})
    for p in masters_service.list_reorder_policies(company_id):
        if f.item_id is not None and p.item_id != f.item_id:
            continue
        result.add([ctx.item_label(p.item_id), ctx.warehouses.get(p.warehouse_id, "همهٔ انبارها") if p.warehouse_id else "همهٔ انبارها",
                    p.min_qty, p.reorder_point_qty, p.max_qty, p.reorder_qty, p.lead_time_days, "بله" if p.is_active else "خیر"])
    return result


# =====================================================================
# R241: درخواستِ خرید
# =====================================================================
def _requests(company_id: int, f: PurchaseFilters, statuses=None):
    from peecha.db.models.commercial import PurchaseRequestLine
    from peecha.services import purchase_requests as pr_service

    reqs = pr_service.list_requests(company_id, f.date_from, f.date_to, statuses)
    with new_session() as session:
        lines: dict[int, list] = defaultdict(list)
        if reqs:
            for ln in session.scalars(select(PurchaseRequestLine).where(
                    PurchaseRequestLine.request_id.in_([r.request_id for r in reqs])).order_by(PurchaseRequestLine.line_no)):
                lines[ln.request_id].append(ln)
    ordered = pr_service.ordered_quantities([ln.line_id for ls in lines.values() for ln in ls])
    ctx = base._ctx(company_id)
    out = []
    for r in reqs:
        ls = [ln for ln in lines.get(r.request_id, [])
              if (f.item_id is None or ln.item_id == f.item_id)
              and (f.category_id is None or (ctx.items.get(ln.item_id) and ctx.items[ln.item_id].category_id == f.category_id))
              and (f.supplier_id is None or ln.suggested_supplier_detail_account_id == f.supplier_id)]
        if (f.item_id is not None or f.category_id is not None or f.supplier_id is not None) and not ls:
            continue
        if f.warehouse_id is not None and r.warehouse_id != f.warehouse_id:
            continue
        out.append((r, ls))
    return out, ordered, ctx


def _estimated(lines) -> decimal.Decimal:
    return sum(((ln.estimated_unit_price or _ZERO) * ln.quantity for ln in lines), _ZERO)


def request_register(company_id: int, f: PurchaseFilters) -> ReportResult:
    from peecha.services import purchase_requests as pr_service

    reqs, ordered, _ctx = _requests(company_id, f)
    users = _users()
    result = ReportResult([
        ("شمارهٔ درخواست", INT), ("تاریخ", DATE), ("درخواست‌کننده", TEXT), ("اولویت", TEXT), ("تاریخِ نیاز", DATE), ("وضعیت", TEXT),
        ("تعدادِ ردیف", INT), ("ارزشِ برآوردی", MONEY), ("وضعیتِ سفارش", TEXT), ("درصدِ سفارش‌شده", PERCENT), ("تصویب‌کننده", TEXT),
    ], no_total={0, 9})
    for r, ls in reqs:
        total = sum((ln.quantity_base for ln in ls), _ZERO)
        done = sum((min(ordered.get(ln.line_id, _ZERO), ln.quantity_base) for ln in ls), _ZERO)
        result.add([r.request_no, r.request_date, users.get(r.requester_user_id, ""), pr_service.PRIORITY_LABELS[r.priority_code],
                    r.required_date, pr_service.STATUS_LABELS[r.status_code], len(ls), _estimated(ls),
                    pr_service.FULFILMENT_LABELS[pr_service.fulfilment(ls, ordered)] if r.status_code == "APPROVED" else "",
                    (done * 100 / total) if total else _ZERO, users.get(r.approved_by_user_id, "")], (r.request_id, "PURCHASE_REQUEST"))
    return result


def requests_pending_approval(company_id: int, f: PurchaseFilters) -> ReportResult:
    from peecha.services import purchase_requests as pr_service

    reqs, _ordered, _ctx = _requests(company_id, f, ("SUBMITTED",))
    users = _users()
    now = datetime.datetime.now()
    result = ReportResult([
        ("شمارهٔ درخواست", INT), ("تاریخ", DATE), ("درخواست‌کننده", TEXT), ("اولویت", TEXT), ("تاریخِ نیاز", DATE),
        ("ارزشِ برآوردی", MONEY), ("روزِ انتظار", DAYS),
    ], no_total={0, 6})
    for r, ls in reqs:
        result.add([r.request_no, r.request_date, users.get(r.requester_user_id, ""), pr_service.PRIORITY_LABELS[r.priority_code],
                    r.required_date, _estimated(ls), (now - r.submitted_at).days if r.submitted_at else None],
                   (r.request_id, "PURCHASE_REQUEST"))
    return result


def approved_not_ordered(company_id: int, f: PurchaseFilters) -> ReportResult:
    """ردیف‌هایِ درخواستِ تصویب‌شده که (کامل یا بخشی) هنوز سفارش نشده‌اند."""
    reqs, ordered, ctx = _requests(company_id, f, ("APPROVED",))
    today = datetime.date.today()
    result = ReportResult([
        ("شمارهٔ درخواست", INT), ("تاریخِ تصویب", DATE), ("کالا", TEXT), ("واحدِ پایه", TEXT), ("مقدارِ درخواست", QTY), ("سفارش‌شده", QTY),
        ("مانده", QTY), ("تاریخِ نیاز", DATE), ("روز تا نیاز", INT), ("تامین‌کنندهٔ پیشنهادی", TEXT), ("ارزشِ برآوردیِ مانده", MONEY),
    ], no_total={0, 8})
    for r, ls in reqs:
        for ln in ls:
            remaining = ln.quantity_base - ordered.get(ln.line_id, _ZERO)
            if remaining <= 0:
                continue
            needed = ln.required_date or r.required_date
            result.add([r.request_no, r.approved_at.date() if r.approved_at else None, ctx.item_label(ln.item_id), ctx.base_uom(ln.item_id),
                        ln.quantity_base, ordered.get(ln.line_id, _ZERO), remaining, needed, (needed - today).days if needed else None,
                        ctx.names.get(ln.suggested_supplier_detail_account_id, ""),
                        _money((ln.estimated_unit_price or _ZERO) * remaining / ln.conversion_factor)], (r.request_id, "PURCHASE_REQUEST"))
    return result


def request_cycle(company_id: int, f: PurchaseFilters) -> ReportResult:
    """زمانِ چرخهٔ درخواست: ثبت → ارسال → تصویب → اولین سفارش (روز)."""
    from peecha.services import purchase_requests as pr_service

    reqs, _ordered, _ctx = _requests(company_id, f, ("SUBMITTED", "APPROVED", "REJECTED"))
    users = _users()
    result = ReportResult([
        ("شمارهٔ درخواست", INT), ("تاریخ", DATE), ("درخواست‌کننده", TEXT), ("وضعیت", TEXT), ("ارسال", DATE), ("تصویب", DATE),
        ("اولین سفارش", DATE), ("ثبت→ارسال", DAYS), ("ارسال→تصویب", DAYS), ("تصویب→سفارش", DAYS), ("کلِ چرخه", DAYS),
    ], no_total={0, 7, 8, 9, 10})
    for r, _ls in reqs:
        orders = [o for o in pr_service.linked_orders(r.request_id) if o.status_code != "CANCELLED"]
        first = min((o.document_date for o in orders), default=None)
        sub = r.submitted_at.date() if r.submitted_at else None
        appr = r.approved_at.date() if r.approved_at else None
        result.add([r.request_no, r.request_date, users.get(r.requester_user_id, ""), pr_service.STATUS_LABELS[r.status_code], sub, appr,
                    first, _gap(r.request_date, sub), _gap(sub, appr), _gap(appr, first), _gap(r.request_date, first)],
                   (r.request_id, "PURCHASE_REQUEST"))
    return result


def requests_by_requester(company_id: int, f: PurchaseFilters) -> ReportResult:
    reqs, ordered, ctx = _requests(company_id, f)
    users = _users()
    agg: dict[str, dict] = defaultdict(lambda: {"count": 0, "approved": 0, "rejected": 0, "value": _ZERO, "ordered": 0})
    from peecha.services import purchase_requests as pr_service

    for r, ls in reqs:
        key = users.get(r.requester_user_id, "")
        if r.cost_center_detail_account_id:
            key = f"{key} / {ctx.names.get(r.cost_center_detail_account_id, '')}"
        a = agg[key]
        a["count"] += 1
        a["value"] += _estimated(ls)
        a["approved"] += r.status_code == "APPROVED"
        a["rejected"] += r.status_code == "REJECTED"
        a["ordered"] += r.status_code == "APPROVED" and pr_service.fulfilment(ls, ordered) == "FULL"
    result = ReportResult([
        ("درخواست‌کننده / مرکزِ هزینه", TEXT), ("تعدادِ درخواست", INT), ("تصویب‌شده", INT), ("ردشده", INT), ("کاملاً سفارش‌شده", INT),
        ("نرخِ رد", PERCENT), ("ارزشِ برآوردی", MONEY),
    ])
    for key, a in sorted(agg.items(), key=lambda kv: -kv[1]["value"]):
        result.add([key, a["count"], a["approved"], a["rejected"], a["ordered"],
                    decimal.Decimal(a["rejected"] * 100) / a["count"] if a["count"] else _ZERO, a["value"]])
    return result


def rejected_requests(company_id: int, f: PurchaseFilters) -> ReportResult:
    reqs, _ordered, _ctx = _requests(company_id, f, ("REJECTED", "CANCELLED"))
    users = _users()
    reasons = _cancel_reason_names(company_id)
    result = ReportResult([
        ("شمارهٔ درخواست", INT), ("تاریخ", DATE), ("درخواست‌کننده", TEXT), ("وضعیت", TEXT), ("علت", TEXT), ("ارزشِ برآوردی", MONEY),
    ], no_total={0})
    for r, ls in reqs:
        why = r.rejected_reason if r.status_code == "REJECTED" else reasons.get(r.cancellation_reason_id, "")
        result.add([r.request_no, r.request_date, users.get(r.requester_user_id, ""), "ردشده" if r.status_code == "REJECTED" else "لغوشده",
                    why or "", _estimated(ls)], (r.request_id, "PURCHASE_REQUEST"))
    return result


def orders_without_request(company_id: int, f: PurchaseFilters) -> ReportResult:
    """ردیف‌هایِ سفارشِ خریدِ ثبت‌شده که از درخواستِ خرید نیامده‌اند."""
    ctx = base._ctx(company_id)
    users = _users()
    result = ReportResult([
        ("شمارهٔ سفارش", INT), ("تاریخ", DATE), ("تامین‌کننده", TEXT), ("کالا", TEXT), ("مقدار (پایه)", QTY), ("مبلغِ خالص", MONEY),
        ("ثبت‌کننده", TEXT),
    ], no_total={0}, note="خریدِ بدونِ درخواست؛ سفارش‌هایِ پیش از R241 هم این‌جا می‌آیند.")
    for doc, ln in base._lines(company_id, ("PURCHASE_ORDER",), _OPEN_ORDER_STATUSES, f, ctx):
        if ln.purchase_request_line_id is not None:
            continue
        result.add([doc.document_no, doc.document_date, ctx.names.get(doc.counterparty_detail_account_id, ""), ctx.item_label(ln.item_id),
                    ln.quantity_base, base._net(ln), users.get(doc.created_by_user_id, "")], (doc.document_id, doc.document_type_code))
    return result


# =====================================================================
# ثبتِ گزارش‌ها
# =====================================================================
_OP, _AN, _PR, _VP, _FI, _MD = "عملیاتی", "تحلیلِ خرید", "قیمت و هزینه", "ارزیابیِ تامین‌کننده", "مالی و بدهی", "اطلاعاتِ پایه"
_CT, _PC, _IN = "کنترل و حسابرسی", "فرآیندِ خرید", "انبار و تدارکات"
_RQ = "درخواستِ خرید"
_ALL = ("supplier", "item", "category", "warehouse")
_DAYS_OPT = ("days", "آستانه (روز)", (("180", "۱۸۰ روز"), ("90", "۹۰ روز"), ("365", "۳۶۵ روز"), ("30", "۳۰ روز")))

PURCHASE_EXT_REPORTS: list[ReportDef] = [
    # --- کنترل و حسابرسی
    ReportDef("THREE_WAY", "تطبیقِ سه‌طرفه (سفارش/رسید/فاکتور)", three_way_match, _ALL,
              "مقدار و فیِ هر ردیفِ سفارش در برابرِ رسیدِ انبار و فاکتور.", group=_CT,
              options=(("view", "نمایش", (("ISSUES", "فقط مغایرت‌ها"), ("ALL", "همه"))),)),
    ReportDef("NO_PO", "خریدِ بدونِ سفارش", purchase_without_po, _ALL, "فاکتورهایِ خریدِ مستقیم، بدونِ سفارش/پیش‌فاکتور.", group=_CT),
    ReportDef("INVOICE_NO_RECEIPT", "فاکتورِ بدونِ رسید", invoice_without_receipt, _ALL,
              "مقدارِ فاکتورشده‌ای که رسیدِ انبار ندارد.", group=_CT),
    ReportDef("INVOICE_OVER_PO", "فاکتورِ بیش از سفارش", invoice_over_po, _ALL, "مقدار یا فیِ فاکتور بیشتر از سفارش.", group=_CT),
    ReportDef("RECEIPT_OVER_PO", "رسیدِ بیش از سفارش", receipt_over_po, _ALL, "مقدارِ رسید بیشتر از سفارش.", group=_CT),
    ReportDef("APPROVAL_PENDING", "اسنادِ منتظرِ تصویبِ مدیر", approval_check, ("supplier",),
              "اسنادِ خریدی که تصویبِ مدیر لازم دارند و هنوز تصویب نشده‌اند، با روزِ انتظار.", group=_CT),
    ReportDef("DOC_TRAIL", "ردِ اسنادِ خرید (Audit Trail)", document_trail, ("supplier",),
              "ایجاد، ثبت، رسید، سندِ حسابداری، اصلاحیه و تسویهٔ هر سندِ خرید با کاربر و زمان.", group=_CT),
    ReportDef("USER_ACTIVITY", "فعالیتِ کاربران در خرید", user_activity, ("supplier",),
              "تعدادِ اسنادِ ایجاد/ثبت/تاییدِ رسید و لغوِ هر کاربر.", group=_CT),
    # --- عملیاتیِ تکمیلی
    ReportDef("PARTIAL_RECEIPT", "سفارش‌هایِ با دریافتِ ناقص", partial_receipt, _ALL, "رسیدِ کمتر از مقدارِ سفارش.", group=_OP),
    ReportDef("NO_RECEIPT", "سفارش‌هایِ بدونِ رسید", orders_without_receipt, _ALL, "سفارش‌هایی که رسیدِ انبار نخورده‌اند.", group=_OP),
    ReportDef("NO_INVOICE", "سفارش‌هایِ بدونِ فاکتور", orders_without_invoice, _ALL, "ردیف‌هایِ سفارشِ بدونِ هیچ فاکتور.", group=_OP),
    ReportDef("RECEIPT_MISMATCH", "رسیدهایِ دارایِ مغایرت", receipt_mismatch, _ALL, "رسیدهایی که با مقدارِ سفارش برابر نیستند.", group=_OP),
    ReportDef("CANCELLED", "اسنادِ خریدِ لغوشده", cancelled_documents, ("supplier",), "سفارش/فاکتور/برگشت‌هایِ لغوشده.", group=_OP),
    # --- فرآیند
    ReportDef("PO_FLOW", "گردشِ سفارشِ خرید", order_flow, ("supplier",),
              "ایجاد → ثبت → رسید → فاکتور → پرداخت، با کاربر، تاریخ و فاصلهٔ روزِ هر مرحله.", group=_PC),
    ReportDef("CYCLE_TIME", "زمانِ چرخهٔ خرید", cycle_time, ("supplier",),
              "میانگینِ روزِ سفارش→رسید، رسید→فاکتور، فاکتور→پرداخت و کلِ چرخه.", group=_PC),
    # --- تحلیلی
    ReportDef("BY_DIMENSION", "خرید به تفکیکِ پروژه/انبار/برند/کاربر/...", purchases_by_dimension, _ALL,
              "تحلیلِ خرید بر اساسِ بُعدِ انتخابی.", group=_AN, options=(("dimension", "بُعد", _DIMENSIONS),)),
    ReportDef("PRICE_MOVERS", "بیشترین افزایش/کاهشِ قیمت", price_movers, _ALL,
              "تغییرِ فیِ آخرین خرید نسبت به اولین خریدِ بازه.", group=_PR,
              options=(("direction", "جهت", (("UP", "افزایش"), ("DOWN", "کاهش"), ("ALL", "همه"))),)),
    ReportDef("PRICE_VS_REFERENCE", "خرید بالاتر/پایین‌تر از قیمتِ مرجع", price_vs_reference, _ALL,
              "انحرافِ فی با مرجعِ انتخابی (سفارش، خریدِ قبلی، فهرستِ قیمت یا میانگین) -- PPV/IPV/POPV.", group=_PR,
              options=(("reference", "مرجعِ قیمت", _REFERENCES),
                       ("direction", "جهت", (("ALL", "همه"), ("ABOVE", "بالاتر از مرجع"), ("BELOW", "پایین‌تر از مرجع"))),
                       ("document", "سند", (("PURCHASE_INVOICE", "فاکتورِ خرید"), ("PURCHASE_ORDER", "سفارشِ خرید"))))),
    ReportDef("LANDED_BY_TYPE", "هزینه‌هایِ جانبی به تفکیکِ نوع", landed_cost_by_type, ("supplier",),
              "حمل، گمرک، بیمه و ... و درصدِ آن از خریدِ کالا.", group=_PR),
    ReportDef("ACTUAL_COST", "بهایِ واقعیِ تامین", actual_procurement_cost, _ALL,
              "مبلغِ فاکتور + سهمِ هزینهٔ جانبی = بهایِ ثبت‌شده در انبار، برایِ هر کالا.", group=_PR),
    # --- عملکردِ تامین‌کننده
    ReportDef("PRICE_STABILITY", "ثباتِ قیمتِ تامین‌کننده", price_stability, ("supplier", "item", "category"),
              "ضریبِ تغییراتِ فیِ کالاهایِ هر تامین‌کننده در بازه.", group=_VP),
    ReportDef("LATE_ORDERS", "سفارش‌هایِ دیرکرد", late_orders, ("supplier",),
              "سفارش‌هایی که پس از تاریخِ تحویلِ مورد انتظار رسیده‌اند یا هنوز نرسیده‌اند.", group=_VP),
    ReportDef("INACTIVE_SUPPLIERS", "تامین‌کنندگانِ غیرفعال", inactive_suppliers, (),
              "تامین‌کنندگانی که در N روزِ اخیر خریدی نداشته‌اند.", "as_of", _VP, options=(_DAYS_OPT,)),
    # --- مالی
    ReportDef("UNPAID", "فاکتورهایِ پرداخت‌نشده (معوق/سررسیدنشده)", unpaid_invoices, ("supplier",),
              "ماندهٔ هر فاکتورِ خرید تا «تا تاریخ».", "as_of", _FI,
              options=(("view", "نمایش", (("ALL", "همه"), ("OVERDUE", "سررسیدگذشته"), ("NOT_DUE", "سررسیدنشده"))),)),
    ReportDef("PAYMENTS", "پرداخت‌هایِ خرید", purchase_payments, ("supplier",),
              "پرداخت‌هایِ تخصیص‌یافته به فاکتورهایِ خرید در بازه.", group=_FI),
    ReportDef("COMMITMENTS", "تعهداتِ خرید و پرداخت", purchase_commitments, _ALL,
              "سفارش‌شدهٔ نرسیده، رسیدهٔ فاکتورنشده، فاکتورِ پرداخت‌نشده و چکِ وصول‌نشده.", "as_of", _FI),
    # --- انبار و تدارکات
    ReportDef("STOCK_POLICY", "وضعیتِ موجودی نسبت به سیاستِ سفارش", stock_policy_status, ("item", "category", "warehouse"),
              "زیرِ نقطهٔ سفارش، زیرِ حداقل، ناموجود و مازاد.", "none", _IN,
              options=(("view", "نمایش", _STOCK_VIEWS),)),
    ReportDef("SUGGESTED", "پیشنهادِ خرید", suggested_purchase, ("item", "category"),
              "مقدارِ پیشنهادیِ خرید بر اساسِ موجودی، در راه، تقاضایِ فروش و سیاستِ سفارش.", "none", _IN),
    ReportDef("DEMAND_NO_PO", "تقاضایِ فروشِ بدونِ پوششِ خرید", demand_without_po, ("item", "category"),
              "کمبودِ سفارش‌هایِ فروشِ باز پس از موجودی و سفارش‌هایِ خریدِ درراه.", "none", _IN),
    ReportDef("REORDER_ANALYSIS", "تحلیلِ نقطهٔ سفارش و پوششِ موجودی", reorder_analysis, ("item", "category"),
              "مصرفِ روزانه، پوششِ موجودی در برابرِ زمانِ تحویل و نقطهٔ سفارشِ محاسبه‌ای.", group=_IN),
    ReportDef("SLOW_DEAD", "کالاهایِ راکد و کم‌گردش", slow_and_dead_stock, ("item", "category"),
              "موجودی‌هایی که در N روزِ اخیر خروج نداشته یا پوششِ بیش از N روز دارند.", "as_of", _IN,
              options=(("view", "نمایش", (("DEAD", "راکد"), ("SLOW", "کم‌گردش"), ("BOTH", "راکد و کم‌گردش"), ("ALL", "همه"))), _DAYS_OPT)),
    # --- اطلاعاتِ پایه
    ReportDef("SUPPLIER_TERMS", "شرایطِ پرداخت و تحویلِ تامین‌کنندگان", supplier_terms, ("supplier",),
              "مهلتِ پرداخت، Incoterm، زمانِ تحویل، سقفِ اعتبار و وضعیتِ پروفایلِ تامین‌کننده.", "none", _MD),
    ReportDef("CONTRACTS", "قراردادهایِ خرید", purchase_contracts, ("supplier",), "قراردادهایِ خرید با تعهد و مصرف.", "none", _MD),
    ReportDef("DISCOUNT_RULES", "قواعدِ تخفیف", discount_rules, (), "قواعدِ تخفیفِ تعریف‌شده.", "none", _MD),
    ReportDef("RETURN_REASONS", "علت‌هایِ برگشت", return_reasons, (), "علت‌هایِ برگشت و تعدادِ استفاده.", "none", _MD),
    ReportDef("APPROVAL_RULES", "قواعدِ تایید و گردشِ کار", approval_rules, (), "وضعیتِ تنظیماتِ مراحلِ تایید.", "none", _MD),
    # --- R240
    ReportDef("CHANGED_AFTER_APPROVAL", "تغییرِ قیمت/مقدار پس از تایید", changes_after_approval, ("supplier",),
              "ویرایش‌هایِ ردیف و سرِ سند پس از اولین تایید، با مقدارِ قبلی/جدید و کاربر.", group=_CT,
              options=(("scope", "نمایش", (("PRICE_QTY", "فقط قیمت/مقدار/تخفیف"), ("ALL", "همهٔ تغییرات"))),)),
    ReportDef("MODIFIED_DOCS", "اسنادِ اصلاح‌شده پس از تایید", modified_documents, ("supplier",),
              "اسنادی که به پیش‌نویس برگشته یا پس از تایید ویرایش شده‌اند.", group=_CT),
    ReportDef("APPROVAL_HISTORY", "تاریخچهٔ تایید و تصویب", approval_history, ("supplier",),
              "کاربر و زمانِ ایجاد، تایید، تصویبِ مدیر و ثبتِ نهایی، و زمانِ انتظارِ تصویب.", group=_CT),
    ReportDef("SOD_VIOLATIONS", "تخلفاتِ تفکیکِ وظایف", segregation_violations, ("supplier",),
              "ایجاد و تصویب یا ثبت و رسید توسطِ یک کاربر، تصویبِ کاربرِ غیرمدیر.", group=_CT),
    ReportDef("CANCEL_ANALYSIS", "تحلیلِ علت‌هایِ لغو", cancellation_analysis, ("supplier",),
              "تعداد و مبلغِ اسنادِ لغوشده به تفکیکِ علت.", group=_OP),
    ReportDef("EMERGENCY", "خریدهایِ اضطراری", emergency_purchases, ("supplier",), "سفارش/فاکتورهایِ با نوعِ خریدِ اضطراری.", group=_OP),
    ReportDef("LINE_DELIVERY", "تحویلِ ردیفیِ سفارش‌ها", line_delivery, _ALL,
              "تاریخِ تحویلِ هر ردیف (یا سرِ سند) در برابرِ رسید.", group=_VP,
              options=(("view", "نمایش", (("ALL", "همه"), ("LATE", "فقط با تاخیر"), ("OPEN", "فقط نرسیده"))),)),
    ReportDef("PURCHASE_TYPES", "انواعِ خرید", purchase_types_master, (), "انواعِ خریدِ تعریف‌شده و تعدادِ استفاده.", "none", _MD),
    ReportDef("CANCEL_REASONS", "علت‌هایِ لغو", cancellation_reasons_master, (), "علت‌هایِ لغوِ تعریف‌شده و تعدادِ استفاده.", "none", _MD),
    ReportDef("REORDER_POLICIES", "سیاست‌هایِ سفارشِ کالا", reorder_policies_master, ("item",),
              "حداقل/نقطهٔ سفارش/حداکثر/زمانِ تحویلِ تعریف‌شده برایِ کالاها.", "none", _MD),
    # --- R241: درخواستِ خرید
    ReportDef("PR_REGISTER", "دفترِ درخواست‌هایِ خرید", request_register, _ALL,
              "همهٔ درخواست‌ها با وضعیت، ارزشِ برآوردی و درصدِ سفارش‌شده.", group=_RQ),
    ReportDef("PR_PENDING", "درخواست‌هایِ منتظرِ تصویب", requests_pending_approval, _ALL,
              "درخواست‌هایِ ارسال‌شده‌ای که هنوز تصویب/رد نشده‌اند.", group=_RQ),
    ReportDef("PR_NOT_ORDERED", "درخواست‌هایِ تصویب‌شدهٔ بدونِ سفارش", approved_not_ordered, _ALL,
              "ماندهٔ سفارش‌نشدهٔ ردیف‌هایِ درخواستِ تصویب‌شده.", group=_RQ),
    ReportDef("PR_CYCLE", "زمانِ چرخهٔ درخواست تا سفارش", request_cycle, _ALL,
              "ثبت → ارسال → تصویب → اولین سفارش (روز).", group=_RQ),
    ReportDef("PR_BY_REQUESTER", "درخواست‌ها به تفکیکِ درخواست‌کننده", requests_by_requester, _ALL,
              "تعداد، نرخِ رد و ارزشِ برآوردیِ درخواست‌هایِ هر کاربر/مرکزِ هزینه.", group=_RQ),
    ReportDef("PR_REJECTED", "درخواست‌هایِ ردشده/لغوشده", rejected_requests, _ALL, "با علتِ رد یا لغو.", group=_RQ),
    ReportDef("PO_WITHOUT_PR", "سفارشِ خریدِ بدونِ درخواست", orders_without_request, _ALL,
              "ردیف‌هایِ سفارش که از درخواستِ خرید نیامده‌اند.", group=_CT),
]
base.register_reports(PURCHASE_EXT_REPORTS)
