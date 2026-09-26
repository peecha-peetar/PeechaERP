"""فاکتورِ امانی (Consignment) -- هردو جهت: خروجی (کالایِ خودمان نزدِ
نماینده/مشتری تا زمانِ فروش) و ورودی (کالایِ تامین‌کننده نزدِ ما تا زمانِ
مصرف/فروش).

طبقِ اصلِ این ویژگی: خودِ سندِ CONSIGNMENT_OUT/CONSIGNMENT_IN هیچ اثرِ
حسابداری‌ای ندارد -- فقط جابه‌جاییِ فیزیکیِ کالا
(services/commercial_documents.py، از طریقِ inventory_engine.py).
تسویه (تبدیل به فاکتورِ واقعیِ فروش/خرید) از طریقِ همان
commercial_documents.convert_to_invoiceِ ازپیش‌موجود انجام می‌شود -- این
ماژول فقط دیدِ کلی (چقدر باقی‌مانده) و بازگردانیِ کالایِ فروخته‌نشده/
مصرف‌نشده را اضافه می‌کند."""

from __future__ import annotations

import datetime
import decimal
from dataclasses import dataclass

from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.commercial import CommercialDocument, CommercialDocumentLine
from peecha.services import commercial_documents as documents_service
from peecha.services import inventory_documents as inv_documents_service

_ZERO = decimal.Decimal("0")
_CONSIGNMENT_TYPES = ("CONSIGNMENT_OUT", "CONSIGNMENT_IN")


@dataclass
class ConsignmentLineStatus:
    line_id: int
    item_id: int
    quantity: decimal.Decimal
    settled_quantity: decimal.Decimal
    returned_quantity: decimal.Decimal
    remaining_quantity: decimal.Decimal


def get_consignment_status(document_id: int, company_id: int) -> list[ConsignmentLineStatus]:
    """مقدارِ تسویه‌شده (طبقِ همان مکانیزمِ ازپیش‌موجودِ source_line_id --
    یعنی چقدر واقعاً به فاکتورِ فروش/خریدِ حقیقی تبدیل شده)، مقدارِ
    بازگردانده‌شده، و مانده‌یِ هر ردیف."""
    with new_session() as session:
        doc = session.get(CommercialDocument, document_id)
        if doc is None or doc.company_id != company_id:
            raise ValueError("سند نامعتبر است.")
        if doc.document_type_code not in _CONSIGNMENT_TYPES:
            raise ValueError("این سند از نوعِ امانی نیست.")
    fulfillment = documents_service.get_line_fulfillment(document_id, company_id)
    with new_session() as session:
        returned_by_line = dict(
            session.execute(
                select(CommercialDocumentLine.line_id, CommercialDocumentLine.returned_quantity)
                .where(CommercialDocumentLine.document_id == document_id)
            ).all()
        )
    result = []
    for f in fulfillment:
        returned = returned_by_line.get(f.line_id, _ZERO)
        result.append(ConsignmentLineStatus(
            line_id=f.line_id, item_id=f.item_id, quantity=f.quantity, settled_quantity=f.invoiced_quantity,
            returned_quantity=returned, remaining_quantity=f.remaining_quantity - returned,
        ))
    return result


def unsettled_consignment_in_quantity(company_id: int, item_id: int, warehouse_id: int) -> decimal.Decimal:
    """جمعِ مقدارِ باقی‌مانده (هنوز تسویه/بازگردانده‌نشده) از همه‌یِ
    اسنادِ CONSIGNMENT_IN بازِ یک کالا در یک انبارِ مشخص -- برایِ
    هشدارِ غیرمسدودکننده‌یِ اختلاطِ بهایِ میانگین (WEIGHTED_AVERAGE) با
    موجودیِ خریداری‌شده‌یِ همان کالا در همان انبار، نه برایِ جلوگیری از
    فروش (که یک ویژگیِ آگاهانه و تست‌شده است -- به `list_open_consignments`
    نگاه کنید)."""
    total = _ZERO
    for doc in list_open_consignments(company_id, "CONSIGNMENT_IN"):
        if doc.warehouse_id != warehouse_id:
            continue
        for status in get_consignment_status(doc.document_id, company_id):
            if status.item_id == item_id:
                total += status.remaining_quantity
    return total


def list_open_consignments(company_id: int, document_type_code: str | None = None) -> list[CommercialDocument]:
    """فاکتورهایِ امانیِ ثبت‌شده‌ای که هنوز کاملاً تسویه/بازگردانده
    نشده‌اند."""
    with new_session() as session:
        stmt = select(CommercialDocument).where(
            CommercialDocument.company_id == company_id, CommercialDocument.status_code == "POSTED",
        )
        if document_type_code:
            stmt = stmt.where(CommercialDocument.document_type_code == document_type_code)
        else:
            stmt = stmt.where(CommercialDocument.document_type_code.in_(_CONSIGNMENT_TYPES))
        docs = list(session.scalars(stmt.order_by(CommercialDocument.document_id.desc())))
    return [doc for doc in docs if any(s.remaining_quantity > 0 for s in get_consignment_status(doc.document_id, company_id))]


def _return_consignment(
    document_id: int, company_id: int, posted_by_user_id: int, line_quantities: dict[int, decimal.Decimal],
    return_date: datetime.date, expected_type: str, stock_document_type: str, source_warehouse_id: int,
    destination_warehouse_id: int | None,
) -> int:
    with new_session() as session:
        doc = session.get(CommercialDocument, document_id)
        if doc is None or doc.company_id != company_id:
            raise ValueError("سند نامعتبر است.")
        if doc.document_type_code != expected_type:
            raise ValueError("نوعِ سند با این عملیات سازگار نیست.")
        lines_by_id = {
            ln.line_id: ln for ln in session.scalars(
                select(CommercialDocumentLine).where(CommercialDocumentLine.document_id == document_id)
            )
        }
        description = f"بازگشتِ امانی #{doc.document_no}"

    statuses = {s.line_id: s for s in get_consignment_status(document_id, company_id)}
    header_fields = inv_documents_service.DocumentHeaderFields(
        source_warehouse_id=source_warehouse_id, destination_warehouse_id=destination_warehouse_id,
        reference_no=f"COMM-{document_id}-RETURN", description=description,
    )
    stock_document_id = inv_documents_service.create_stock_document(
        company_id, posted_by_user_id, stock_document_type, return_date, header_fields
    )
    returned_by_line: dict[int, decimal.Decimal] = {}
    for line_id, quantity in line_quantities.items():
        if quantity <= 0:
            continue
        status = statuses.get(line_id)
        if status is None:
            raise ValueError("ردیف نامعتبر است.")
        if quantity > status.remaining_quantity:
            raise ValueError(f"مقدارِ درخواستی برایِ ردیف بیشتر از مانده ({status.remaining_quantity}) است.")
        ln = lines_by_id[line_id]
        inv_documents_service.add_line(
            stock_document_id, company_id,
            inv_documents_service.LineFields(
                item_id=ln.item_id, uom_id=ln.uom_id, quantity=quantity, quantity_base=quantity, batch_id=ln.batch_id,
            ),
        )
        returned_by_line[line_id] = quantity
    if not returned_by_line:
        raise ValueError("چیزی برایِ بازگشت مشخص نشده است.")

    inv_documents_service.confirm_stock_document(stock_document_id, company_id)
    inv_documents_service.post_stock_document(stock_document_id, company_id, posted_by_user_id)

    with new_session() as session:
        for line_id, quantity in returned_by_line.items():
            ln = session.get(CommercialDocumentLine, line_id)
            ln.returned_quantity = ln.returned_quantity + quantity
        session.commit()
    return stock_document_id


def return_unsold_consignment_out(
    document_id: int, company_id: int, posted_by_user_id: int, line_quantities: dict[int, decimal.Decimal],
    return_date: datetime.date,
) -> int:
    """بازگرداندنِ کالایِ فروخته‌نشده‌یِ امانیِ خروجی به انبارِ اصلی --
    یک TRANSFERِ ساده و معکوس (بدونِ اثرِ حسابداری، دقیقاً مثلِ ارسال)."""
    with new_session() as session:
        doc = session.get(CommercialDocument, document_id)
        if doc is None or doc.company_id != company_id:
            raise ValueError("سند نامعتبر است.")
        if doc.warehouse_id is None or doc.consignment_warehouse_id is None:
            raise ValueError("انبارهایِ این سند کامل نیست.")
        source_warehouse_id, destination_warehouse_id = doc.consignment_warehouse_id, doc.warehouse_id
    return _return_consignment(
        document_id, company_id, posted_by_user_id, line_quantities, return_date,
        expected_type="CONSIGNMENT_OUT", stock_document_type="TRANSFER",
        source_warehouse_id=source_warehouse_id, destination_warehouse_id=destination_warehouse_id,
    )


def return_unused_consignment_in(
    document_id: int, company_id: int, posted_by_user_id: int, line_quantities: dict[int, decimal.Decimal],
    return_date: datetime.date,
) -> int:
    """بازگرداندنِ کالایِ مصرف‌نشده‌یِ امانیِ ورودی به تامین‌کننده -- چون
    هرگز خریداری نشده، هیچ اثرِ حسابداری‌ای ندارد."""
    with new_session() as session:
        doc = session.get(CommercialDocument, document_id)
        if doc is None or doc.company_id != company_id:
            raise ValueError("سند نامعتبر است.")
        if doc.warehouse_id is None:
            raise ValueError("انبارِ نگه‌داریِ این سند مشخص نیست.")
        source_warehouse_id = doc.warehouse_id
    return _return_consignment(
        document_id, company_id, posted_by_user_id, line_quantities, return_date,
        expected_type="CONSIGNMENT_IN", stock_document_type="CONSIGN_RETURN",
        source_warehouse_id=source_warehouse_id, destination_warehouse_id=None,
    )
