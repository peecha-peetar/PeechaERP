"""خدماتِ پس‌ازفروش و گارانتی (مرحلهٔ ۹): گارانتیِ سریالی، تیکتِ خدماتی
با محاسبهٔ خودکارِ رایگان/هزینه‌بردار، و RMA به‌عنوانِ دروازهٔ پیشِ‌از
برگشتِ فروش."""

from __future__ import annotations

import datetime
import decimal
from dataclasses import dataclass

from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.accounting import DetailAccount
from peecha.db.models.commercial import (
    CommercialDocument,
    CommercialDocumentLine,
    RmaRequest,
    ServiceTicket,
    ServiceTicketPartUsed,
    Warranty,
)
from peecha.services import commercial_documents as documents_service

_REASON_CODES = ("DEFECTIVE", "WRONG_ITEM", "NOT_SATISFIED", "DAMAGED_IN_TRANSIT")


# ---------------------------------------------------------------------
# گارانتی
# ---------------------------------------------------------------------
def create_warranty(sales_document_line_id: int, item_id: int, duration_months: int, terms: str | None = None, serial_id: int | None = None, start_date: datetime.date | None = None) -> int:
    if duration_months <= 0:
        raise ValueError("مدتِ گارانتی باید بزرگ‌تر از صفر باشد.")
    start_date = start_date or datetime.date.today()
    end_date = _add_months(start_date, duration_months)
    with new_session() as session:
        row = Warranty(
            sales_document_line_id=sales_document_line_id, serial_id=serial_id, item_id=item_id, start_date=start_date,
            end_date=end_date, terms=terms,
        )
        session.add(row)
        session.commit()
        return row.warranty_id


def _add_months(d: datetime.date, months: int) -> datetime.date:
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    day = min(d.day, [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1])
    return datetime.date(year, month, day)


def void_warranty(warranty_id: int, reason: str) -> None:
    with new_session() as session:
        row = session.get(Warranty, warranty_id)
        if row is None:
            raise ValueError("گارانتی نامعتبر است.")
        row.status_code = "VOIDED"
        row.voided_reason = reason
        session.commit()


def get_effective_warranty_status(warranty_id: int) -> str:
    """EXPIRED محاسبه‌شده در لحظهٔ پرس‌وجو، نه یک Job (مرحلهٔ ۹، بخشِ ۶)."""
    with new_session() as session:
        row = session.get(Warranty, warranty_id)
        if row is None:
            raise ValueError("گارانتی نامعتبر است.")
        if row.status_code == "VOIDED":
            return "VOIDED"
        if row.end_date < datetime.date.today():
            return "EXPIRED"
        return "ACTIVE"


def list_warranties_for_serial(serial_id: int) -> list[Warranty]:
    with new_session() as session:
        return list(session.scalars(select(Warranty).where(Warranty.serial_id == serial_id)))


def list_warranties(company_id: int) -> list[Warranty]:
    with new_session() as session:
        stmt = (
            select(Warranty)
            .join(CommercialDocumentLine, Warranty.sales_document_line_id == CommercialDocumentLine.line_id)
            .join(CommercialDocument, CommercialDocumentLine.document_id == CommercialDocument.document_id)
            .where(CommercialDocument.company_id == company_id)
            .order_by(Warranty.warranty_id.desc())
        )
        return list(session.scalars(stmt))


# ---------------------------------------------------------------------
# تیکتِ خدماتی
# ---------------------------------------------------------------------
def open_ticket(customer_detail_account_id: int, subject: str, warranty_id: int | None = None, item_id: int | None = None, description: str | None = None, assigned_to_user_id: int | None = None) -> int:
    is_billable = True
    if warranty_id is not None:
        is_billable = get_effective_warranty_status(warranty_id) != "ACTIVE"
    with new_session() as session:
        row = ServiceTicket(
            customer_detail_account_id=customer_detail_account_id, warranty_id=warranty_id, item_id=item_id, subject=subject,
            description=description, is_billable=is_billable, assigned_to_user_id=assigned_to_user_id,
        )
        session.add(row)
        session.commit()
        return row.ticket_id


def advance_ticket_status(ticket_id: int, status_code: str) -> None:
    if status_code not in ("OPEN", "IN_PROGRESS", "RESOLVED", "CLOSED"):
        raise ValueError("وضعیتِ نامعتبر است.")
    with new_session() as session:
        row = session.get(ServiceTicket, ticket_id)
        if row is None:
            raise ValueError("تیکت نامعتبر است.")
        if status_code == "CLOSED" and row.is_billable and row.resulting_invoice_document_id is None:
            raise ValueError("تیکتِ هزینه‌بردار بدونِ فاکتورِ تسویه قابلِ‌بستن نیست.")
        row.status_code = status_code
        if status_code == "CLOSED":
            row.closed_at = datetime.datetime.now(datetime.timezone.utc)
        session.commit()


def link_ticket_invoice(ticket_id: int, resulting_invoice_document_id: int) -> None:
    with new_session() as session:
        row = session.get(ServiceTicket, ticket_id)
        if row is None:
            raise ValueError("تیکت نامعتبر است.")
        row.resulting_invoice_document_id = resulting_invoice_document_id
        session.commit()


def record_part_used(ticket_id: int, item_id: int, quantity: decimal.Decimal, stock_document_id: int | None = None) -> int:
    with new_session() as session:
        row = ServiceTicketPartUsed(ticket_id=ticket_id, item_id=item_id, quantity=quantity, stock_document_id=stock_document_id)
        session.add(row)
        session.commit()
        return row.usage_id


def list_tickets(company_id: int, customer_detail_account_id: int | None = None, status_code: str | None = None) -> list[ServiceTicket]:
    with new_session() as session:
        stmt = (
            select(ServiceTicket)
            .join(DetailAccount, ServiceTicket.customer_detail_account_id == DetailAccount.detail_account_id)
            .where(DetailAccount.company_id == company_id)
            .order_by(ServiceTicket.ticket_id.desc())
        )
        if customer_detail_account_id is not None:
            stmt = stmt.where(ServiceTicket.customer_detail_account_id == customer_detail_account_id)
        if status_code is not None:
            stmt = stmt.where(ServiceTicket.status_code == status_code)
        return list(session.scalars(stmt))


def list_service_ticket_parts_used(ticket_id: int) -> list[ServiceTicketPartUsed]:
    with new_session() as session:
        return list(session.scalars(select(ServiceTicketPartUsed).where(ServiceTicketPartUsed.ticket_id == ticket_id)))


# ---------------------------------------------------------------------
# RMA
# ---------------------------------------------------------------------
def request_rma(customer_detail_account_id: int, original_document_id: int, reason_code: str, requested_quantity: decimal.Decimal, related_ticket_id: int | None = None) -> int:
    if reason_code not in _REASON_CODES:
        raise ValueError("دلیلِ نامعتبر است.")
    with new_session() as session:
        row = RmaRequest(
            customer_detail_account_id=customer_detail_account_id, original_document_id=original_document_id,
            related_ticket_id=related_ticket_id, reason_code=reason_code, requested_quantity=requested_quantity,
        )
        session.add(row)
        session.commit()
        return row.rma_id


def reject_rma(rma_id: int) -> None:
    with new_session() as session:
        row = session.get(RmaRequest, rma_id)
        if row is None or row.status_code != "REQUESTED":
            raise ValueError("فقط RMAیِ درانتظار قابلِ‌رد است.")
        row.status_code = "REJECTED"
        session.commit()


def approve_rma(rma_id: int, company_id: int, created_by_user_id: int, warehouse_id: int, currency_id: int) -> int:
    """پسِ تایید، یک SALES_RETURNِ استاندارد ساخته می‌شود — RMA خودش سند
    نیست، فقط دروازهٔ تایید (مرحلهٔ ۹، بخشِ ۲)."""
    with new_session() as session:
        rma = session.get(RmaRequest, rma_id)
        if rma is None or rma.status_code != "REQUESTED":
            raise ValueError("فقط RMAیِ درانتظار قابلِ‌تایید است.")
        original_document_id = rma.original_document_id
        requested_quantity = rma.requested_quantity
        rma.status_code = "APPROVED"
        session.commit()

    original_doc, original_lines = documents_service.get_document(original_document_id, company_id)
    return_document_id = documents_service.create_document(
        company_id, created_by_user_id, "SALES_RETURN", datetime.date.today(),
        documents_service.DocumentHeaderFields(
            counterparty_detail_account_id=original_doc.counterparty_detail_account_id, currency_id=currency_id,
            warehouse_id=warehouse_id, source_document_id=original_document_id,
        ),
    )
    remaining = requested_quantity
    for line in original_lines:
        if remaining <= 0:
            break
        take = min(line.quantity, remaining)
        documents_service.add_line(
            return_document_id, company_id, line.item_id, line.uom_id, take, take, unit_price=line.unit_price,
            source_line_id=line.line_id,
        )
        remaining -= take

    with new_session() as session:
        rma = session.get(RmaRequest, rma_id)
        rma.resulting_return_document_id = return_document_id
        rma.status_code = "COMPLETED"
        session.commit()

    return return_document_id


def list_rma_requests(company_id: int, status_code: str | None = None) -> list[RmaRequest]:
    with new_session() as session:
        stmt = (
            select(RmaRequest)
            .join(DetailAccount, RmaRequest.customer_detail_account_id == DetailAccount.detail_account_id)
            .where(DetailAccount.company_id == company_id)
            .order_by(RmaRequest.rma_id.desc())
        )
        if status_code is not None:
            stmt = stmt.where(RmaRequest.status_code == status_code)
        return list(session.scalars(stmt))
