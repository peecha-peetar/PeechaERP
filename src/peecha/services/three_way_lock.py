"""R379: قفل پرداخت فاکتور خرید با تطبیق سه‌طرفه (سفارش ↔ رسید ↔ فاکتور) — اختیاری، با کلید قابلیت؛ پیش‌فرض خاموش و رفتار
قبلی بی‌تغییر.

- فقط ردیف‌های فاکتور خرید که از سفارش خرید ساخته شده‌اند سنجیده می‌شوند (خرید بدون سفارش قفل نمی‌شود). مقدار و فی هر ردیف
  سفارش با جمع همهٔ فاکتورهای ثبت‌شدهٔ همان ردیف مقایسه می‌شود، با همان قاعده‌های گزارش تطبیق سه‌طرفه:
  «منتظر رسید» (مرحلهٔ رسید انباردار روشن و رسید تایید نشده)، «فاکتور بیش از رسید»، «فاکتور بیش از سفارش» و «اختلاف فی».
- حد مجاز مقدار و فی (درصد) برای هر شرکت تعیین می‌شود.
- مغایرت مال ردیف سفارش است، پس همهٔ فاکتورهای پرداخت‌نشدهٔ آن ردیف قفل می‌مانند تا رفع یا آزادسازی.
- فاکتور قفل‌شده تسویه نمی‌شود (هیچ دریافت یا پرداختی به آن تخصیص نمی‌یابد) و فرم پرداخت پیش از ثبت سند آن را رد می‌کند،
  تا مغایرت رفع شود یا مدیر سیستم (یا دارندهٔ مجوز تایید فاکتور خرید) با ذکر دلیل آزادش کند.
"""

from __future__ import annotations

import datetime
import decimal
from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.commercial import CommercialDocument, CommercialDocumentLine, ThreeWayRelease, ThreeWaySettings

FEATURE = "PURCHASE_THREE_WAY_LOCK"
APPROVE_FORM = "commercial_document_purchase_invoice"
ZERO = decimal.Decimal(0)
HUNDRED = decimal.Decimal(100)


@dataclass
class Issue:
    order_no: int
    item_label: str
    text: str


def enabled(company_id: int) -> bool:
    from peecha.services import inventory_engine

    return inventory_engine.is_feature_enabled(company_id, FEATURE)


def get_settings(company_id: int) -> tuple[decimal.Decimal, decimal.Decimal]:
    """(حد مجاز اختلاف فی، حد مجاز اضافهٔ مقدار) به درصد."""
    with new_session() as session:
        row = session.get(ThreeWaySettings, company_id)
        return (decimal.Decimal(row.price_tolerance_percent), decimal.Decimal(row.qty_tolerance_percent)) if row else (ZERO, ZERO)


def save_settings(company_id: int, user_id: int, price_tolerance_percent, qty_tolerance_percent) -> None:
    price, qty = decimal.Decimal(price_tolerance_percent or 0), decimal.Decimal(qty_tolerance_percent or 0)
    if not (ZERO <= price < HUNDRED and ZERO <= qty < HUNDRED):
        raise ValueError("حد مجاز باید از ۰ تا کمتر از ۱۰۰ درصد باشد.")
    if not can_release(company_id, user_id):
        raise ValueError("تعیین حد مجاز با مدیر سیستم یا دارندهٔ مجوز تایید فاکتور خرید است.")
    with new_session() as session:
        row = session.get(ThreeWaySettings, company_id) or ThreeWaySettings(company_id=company_id)
        row.price_tolerance_percent, row.qty_tolerance_percent = price, qty
        row.updated_by_user_id, row.updated_at = user_id, datetime.datetime.now(datetime.timezone.utc)
        session.merge(row)
        session.commit()


def can_release(company_id: int, user_id: int) -> bool:
    from peecha.services import roles

    return roles.is_manager(user_id, company_id) or roles.user_has_permission(user_id, company_id, APPROVE_FORM, "APPROVE")


def invoice_issues(company_id: int, invoice_document_id: int) -> list[Issue]:
    """مغایرت‌های ردیف‌های سفارش خریدی که این فاکتور از آن‌ها ساخته شده است (با حد مجاز شرکت)."""
    from peecha.services import commercial_documents as documents_service
    from peecha.services import purchase_reports as base

    price_tol, qty_tol = get_settings(company_id)
    receipt_step = documents_service.order_warehouse_step_enabled(company_id, "PURCHASE_ORDER")
    with new_session() as session:
        invoice = session.get(CommercialDocument, invoice_document_id)
        if invoice is None or invoice.company_id != company_id or invoice.document_type_code != "PURCHASE_INVOICE":
            return []
        source_ids = {ln.source_line_id for ln in session.scalars(select(CommercialDocumentLine).where(
            CommercialDocumentLine.document_id == invoice_document_id)) if ln.source_line_id}
        if not source_ids:
            return []
        po_rows = session.execute(select(CommercialDocument, CommercialDocumentLine)
                                  .join(CommercialDocumentLine, CommercialDocumentLine.document_id == CommercialDocument.document_id)
                                  .where(CommercialDocumentLine.line_id.in_(source_ids),
                                         CommercialDocument.document_type_code == "PURCHASE_ORDER")).all()
        invoiced: dict[int, list[CommercialDocumentLine]] = defaultdict(list)
        for ln in session.scalars(select(CommercialDocumentLine)
                                  .join(CommercialDocument, CommercialDocument.document_id == CommercialDocumentLine.document_id)
                                  .where(CommercialDocumentLine.source_line_id.in_([ln.line_id for _d, ln in po_rows] or [0]),
                                         CommercialDocument.document_type_code == "PURCHASE_INVOICE",
                                         CommercialDocument.status_code != "CANCELLED",
                                         CommercialDocument.corrects_document_id.is_(None))):
            invoiced[ln.source_line_id].append(ln)
        from peecha.services.production import common as pc

        labels = pc.item_labels(session, [ln.item_id for _d, ln in po_rows])
    issues = []
    for po, ln in po_rows:
        lines = invoiced.get(ln.line_id, [])
        inv_qty = sum((decimal.Decimal(x.quantity_base) for x in lines), ZERO)
        inv_value = sum((base._net(x) for x in lines), ZERO)
        ordered = decimal.Decimal(ln.quantity_base)
        allowed = 1 + qty_tol / HUNDRED
        label = labels.get(ln.item_id, "")

        def add(text: str) -> None:
            issues.append(Issue(po.document_no, label, text))

        if receipt_step:
            if po.warehouse_approved_at is None:
                add("منتظر رسید انبار")
            elif inv_qty > decimal.Decimal(base._received_base(po, ln) or 0) * allowed:
                add("فاکتور بیش از رسید")
        if inv_qty > ordered * allowed:
            add("فاکتور بیش از سفارش")
        po_price = base._base_price(ln)
        if inv_qty and po_price:
            inv_price = inv_value / inv_qty
            if abs(inv_price - po_price) * HUNDRED / po_price > price_tol and abs(inv_price - po_price) >= decimal.Decimal("0.01"):
                add("اختلاف فی با سفارش")
    return issues


def release_of(company_id: int, invoice_document_id: int) -> ThreeWayRelease | None:
    with new_session() as session:
        row = session.scalar(select(ThreeWayRelease).where(ThreeWayRelease.company_id == company_id,
                                                           ThreeWayRelease.invoice_document_id == invoice_document_id))
        if row is not None:
            session.expunge(row)
        return row


def block_reason(company_id: int, invoice_document_id: int) -> str | None:
    """متن مانع پرداخت، یا None اگر قفل خاموش، فاکتور آزادشده یا بی‌مغایرت است."""
    if not enabled(company_id) or release_of(company_id, invoice_document_id) is not None:
        return None
    issues = invoice_issues(company_id, invoice_document_id)
    if not issues:
        return None
    from peecha import numerals

    detail = "؛ ".join(f"{i.item_label} (سفارش {numerals.to_persian_digits(str(i.order_no))}): {i.text}" for i in issues[:5])
    return f"پرداخت این فاکتور خرید تا رفع مغایرت تطبیق سه‌طرفه یا آزادسازی مدیر بسته است — {detail}"


def release(company_id: int, user_id: int, invoice_document_id: int, reason: str) -> int:
    reason = (reason or "").strip()
    if not reason:
        raise ValueError("دلیل آزادسازی پرداخت را بنویسید.")
    if not can_release(company_id, user_id):
        raise ValueError("آزادسازی پرداخت با مدیر سیستم یا دارندهٔ مجوز تایید فاکتور خرید است.")
    from peecha.services.audit import log_activity

    with new_session() as session:
        doc = session.get(CommercialDocument, invoice_document_id)
        if doc is None or doc.company_id != company_id or doc.document_type_code != "PURCHASE_INVOICE":
            raise ValueError("فاکتور خرید نامعتبر است.")
        existing = session.scalar(select(ThreeWayRelease).where(ThreeWayRelease.invoice_document_id == invoice_document_id))
        if existing is not None:
            raise ValueError("پرداخت این فاکتور قبلاً آزاد شده است.")
        row = ThreeWayRelease(company_id=company_id, invoice_document_id=invoice_document_id, reason=reason[:500],
                              released_by_user_id=user_id)
        session.add(row)
        session.flush()
        log_activity(session, company_id=company_id, user_id=user_id, entity_type="CommercialDocument",
                     entity_id=invoice_document_id, action="APPROVE", changes={"operation": "THREE_WAY_RELEASE", "reason": reason[:500]})
        session.commit()
        return row.release_id


@dataclass
class BlockedInvoice:
    document_id: int
    document_no: int
    document_date: datetime.date
    supplier: str
    total_amount: decimal.Decimal
    issues: list[Issue]
    released: bool
    release_reason: str


def list_invoices(company_id: int, include_released: bool = False) -> list[BlockedInvoice]:
    """فاکتورهای خرید ثبت‌شدهٔ تسویه‌نشده که مغایرت تطبیق سه‌طرفه دارند (و در صورت درخواست، آزادشده‌ها)."""
    from peecha.services import commercial_settlements as settlements

    from peecha.db.models.accounting import DetailAccount

    rows = []
    for status in settlements.list_unsettled_invoices(company_id, "PURCHASE_INVOICE"):
        doc_id = status.document_id
        issues = invoice_issues(company_id, doc_id)
        if not issues:
            continue
        rel = release_of(company_id, doc_id)
        if rel is not None and not include_released:
            continue
        with new_session() as session:
            doc = session.get(CommercialDocument, doc_id)
            party = session.get(DetailAccount, doc.counterparty_detail_account_id)
            rows.append(BlockedInvoice(doc_id, doc.document_no, doc.document_date, f"{party.code} {party.name or ''}" if party else "",
                                       doc.total_amount, issues, rel is not None, rel.reason if rel else ""))
    return rows
