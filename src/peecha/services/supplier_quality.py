"""R310 — امتیاز کیفیت تامین‌کننده از بازرسی‌های کنترل کیفیت رسید.

امتیاز (۰ تا ۱۰) = مقدار پذیرفته ÷ مقدار بازرسی‌شده × ۱۰ در یک سال اخیر. هر عدد تا تک‌تک بازرسی‌ها ردیابی می‌شود
(گزارش «بازرسی‌های کیفیت رسید»). تامین‌کننده‌ای که بازرسی ندارد امتیاز ندارد؛ نه صفر و نه ده.
"""

from __future__ import annotations

import datetime
import decimal
from types import SimpleNamespace

from sqlalchemy import exists, func, select
from sqlalchemy.orm import aliased

from peecha.db.models.inventory import QcInspection, StockDocument, StockDocumentLine

_Rev = aliased(StockDocument)  # سند برگشت (reference_no = REVERSAL-<شناسه>)

_ZERO = decimal.Decimal(0)
_TEN = decimal.Decimal(10)
WINDOW_DAYS = 365
RESULT_LABELS = {"APPROVED": "پذیرفته", "PARTIAL": "پذیرش بخشی", "REJECTED": "ردشده"}


def rating(inspected: decimal.Decimal, rejected: decimal.Decimal) -> decimal.Decimal | None:
    if not inspected or inspected <= 0:
        return None
    accepted = max(_ZERO, inspected - rejected)
    return (accepted * _TEN / inspected).quantize(decimal.Decimal("0.1"))


def inspections(session, company_id: int, date_from: datetime.date | None = None, date_to: datetime.date | None = None,
                supplier_id: int | None = None) -> list[SimpleNamespace]:
    """بازرسی‌های ردیف رسید با تامین‌کنندهٔ همان رسید (قدیمی‌ترین اول)."""
    q = (select(QcInspection, StockDocumentLine, StockDocument)
         .join(StockDocumentLine, StockDocumentLine.line_id == QcInspection.stock_document_line_id)
         .join(StockDocument, StockDocument.stock_document_id == StockDocumentLine.stock_document_id)
         .where(QcInspection.company_id == company_id, StockDocument.counterparty_detail_account_id.is_not(None),
                # R311: فقط تصمیم نهایی رسید خرید؛ رسید برگشت‌خورده و مرجوعی مشتری و تولید حساب نمی‌شوند
                QcInspection.status_code == "APPROVED", QcInspection.stage_code == "RECEIPT",
                StockDocument.status_code == "POSTED",
                ~exists().where(_Rev.company_id == company_id,
                                _Rev.reference_no == func.concat("REVERSAL-", StockDocument.stock_document_id)))
         .order_by(QcInspection.inspected_at, QcInspection.qc_inspection_id))
    if date_from is not None:
        q = q.where(QcInspection.inspected_at >= datetime.datetime.combine(date_from, datetime.time.min))
    if date_to is not None:
        q = q.where(QcInspection.inspected_at < datetime.datetime.combine(date_to + datetime.timedelta(days=1), datetime.time.min))
    if supplier_id is not None:
        q = q.where(StockDocument.counterparty_detail_account_id == supplier_id)
    out = []
    for qc, ln, doc in session.execute(q).all():
        out.append(SimpleNamespace(
            inspection_id=qc.qc_inspection_id, inspected_at=qc.inspected_at, supplier_id=doc.counterparty_detail_account_id,
            stock_document_id=doc.stock_document_id, document_no=doc.document_no, document_date=doc.document_date,
            line_id=ln.line_id, item_id=ln.item_id, warehouse_id=doc.destination_warehouse_id,
            inspected=_decided(qc, ln), rejected=decimal.Decimal(qc.rejected_quantity or 0),
            approved_at=qc.approved_at or qc.inspected_at, posted_at=doc.posted_at,
            result_code=qc.result_code, user_id=qc.inspected_by_user_id, notes=qc.notes))
    return out


def _decided(qc: QcInspection, ln: StockDocumentLine) -> decimal.Decimal:
    """مقدار تصمیم‌گرفته = پذیرفته + ردشده («در انتظار» در بازرسی بعدی حساب می‌شود)."""
    rejected = decimal.Decimal(qc.rejected_quantity or 0)
    accepted = decimal.Decimal(qc.accepted_quantity) if qc.accepted_quantity is not None else decimal.Decimal(ln.quantity_base) - rejected
    return accepted + rejected


def by_supplier(session, company_id: int, date_from: datetime.date | None = None, date_to: datetime.date | None = None,
                rows: list[SimpleNamespace] | None = None) -> dict[int, SimpleNamespace]:
    out: dict[int, SimpleNamespace] = {}
    for r in rows if rows is not None else inspections(session, company_id, date_from, date_to):
        s = out.setdefault(r.supplier_id, SimpleNamespace(count=0, inspected=_ZERO, rejected=_ZERO, rating=None))
        s.count += 1
        s.inspected += r.inspected
        s.rejected += r.rejected
    for s in out.values():
        s.rating = rating(s.inspected, s.rejected)
    return out


def window(today: datetime.date | None = None) -> tuple[datetime.date, datetime.date]:
    today = today or datetime.date.today()
    return today - datetime.timedelta(days=WINDOW_DAYS), today


def refresh(session, company_id: int, supplier_id: int) -> decimal.Decimal | None:
    """امتیاز ذخیره‌شدهٔ پروفایل تامین‌کننده = امتیاز یک سال اخیر (فقط از رخداد کنترل کیفیت صدا زده می‌شود)."""
    from peecha.db.models.commercial import SupplierProfile

    date_from, date_to = window()
    s = by_supplier(session, company_id, rows=inspections(session, company_id, date_from, date_to, supplier_id)).get(supplier_id)
    value = s.rating if s is not None else None
    profile = session.get(SupplierProfile, supplier_id)
    if profile is not None and profile.company_id == company_id:
        profile.quality_rating = value
    return value


def label(value: decimal.Decimal | None) -> str:
    return "بدون بازرسی" if value is None else f"{value.normalize():f} از ۱۰"
