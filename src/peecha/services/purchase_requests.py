"""درخواستِ خرید (Purchase Request) -- R241.

گردش: DRAFT → SUBMITTED → APPROVED | REJECTED ؛ CANCELLED پیش از تبدیل.
درخواستِ تصویب‌شده با convert_to_orders به سفارشِ خرید تبدیل می‌شود (یک سفارش برایِ هر
تامین‌کننده) -- خودِ سفارش با همان create_document/add_line ساخته می‌شود، پس منطقِ سفارش،
موجودی و حسابداری هیچ تغییری نمی‌کند. مقدارِ سفارش‌شدهٔ هر ردیف ذخیره نمی‌شود و همیشه از
ردیف‌هایِ لغونشدهٔ سفارش‌هایِ مرتبط (purchase_request_line_id) محاسبه می‌شود.
"""

from __future__ import annotations

import datetime
import decimal
from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import func, select

from peecha.db.base import new_session
from peecha.db.models.commercial import (
    CommercialDocument, CommercialDocumentLine, PurchaseRequest, PurchaseRequestLine,
)
from peecha.services import commercial_documents as documents_service
from peecha.services import unit_conversion as uc

_ZERO = decimal.Decimal(0)
STATUS_LABELS = {
    "DRAFT": "پیش‌نویس", "SUBMITTED": "ارسال‌شده برایِ تصویب", "APPROVED": "تصویب‌شده", "REJECTED": "ردشده",
    "CANCELLED": "لغوشده",
}
FULFILMENT_LABELS = {"NONE": "سفارش نشده", "PARTIAL": "سفارشِ ناقص", "FULL": "کاملاً سفارش شده"}
PRIORITY_LABELS = {"NORMAL": "عادی", "URGENT": "فوری"}


@dataclass
class RequestFields:
    request_date: datetime.date
    required_date: datetime.date | None = None
    priority_code: str = "NORMAL"
    purchase_type_id: int | None = None
    warehouse_id: int | None = None
    cost_center_detail_account_id: int | None = None
    project_detail_account_id: int | None = None
    description: str | None = None
    branch_id: int | None = None
    org_unit_id: int | None = None


def _get(session, request_id: int, company_id: int) -> PurchaseRequest:
    row = session.get(PurchaseRequest, request_id)
    if row is None or row.company_id != company_id:
        raise ValueError("درخواستِ خرید نامعتبر است.")
    return row


def _editable(session, request_id: int, company_id: int) -> PurchaseRequest:
    row = _get(session, request_id, company_id)
    if row.status_code not in ("DRAFT", "REJECTED"):
        raise ValueError("فقط درخواستِ پیش‌نویس (یا ردشده) قابلِ‌ویرایش است.")
    return row


def _apply(row: PurchaseRequest, fields: RequestFields) -> None:
    if fields.priority_code not in PRIORITY_LABELS:
        raise ValueError("اولویتِ درخواست نامعتبر است.")
    if fields.required_date is not None and fields.required_date < fields.request_date:
        raise ValueError("تاریخِ نیاز نمی‌تواند پیش از تاریخِ درخواست باشد.")
    row.request_date = fields.request_date
    row.required_date = fields.required_date
    row.priority_code = fields.priority_code
    row.purchase_type_id = fields.purchase_type_id
    row.warehouse_id = fields.warehouse_id
    row.cost_center_detail_account_id = fields.cost_center_detail_account_id
    row.project_detail_account_id = fields.project_detail_account_id
    row.description = (fields.description or None)
    row.branch_id = fields.branch_id
    row.org_unit_id = fields.org_unit_id


def create_request(company_id: int, requester_user_id: int, fields: RequestFields) -> int:
    with new_session() as session:
        next_no = (session.scalar(select(func.max(PurchaseRequest.request_no)).where(PurchaseRequest.company_id == company_id)) or 0) + 1
        row = PurchaseRequest(company_id=company_id, request_no=next_no, requester_user_id=requester_user_id, status_code="DRAFT")
        _apply(row, fields)
        session.add(row)
        session.commit()
        return row.request_id


def update_request(request_id: int, company_id: int, fields: RequestFields) -> None:
    with new_session() as session:
        _apply(_editable(session, request_id, company_id), fields)
        session.commit()


def add_line(
    request_id: int, company_id: int, item_id: int, uom_id: int, quantity: decimal.Decimal,
    required_date: datetime.date | None = None, suggested_supplier_id: int | None = None,
    estimated_unit_price: decimal.Decimal | None = None, description: str | None = None,
) -> int:
    if quantity <= 0:
        raise ValueError("مقدار باید بزرگ‌تر از صفر باشد.")
    uc.validate_quantity(item_id, uom_id, quantity, purpose="PURCHASE")
    factor = uc.get_factor(item_id, uom_id, require_active=True)
    with new_session() as session:
        _editable(session, request_id, company_id)
        from peecha.db.models.inventory import Item

        item = session.get(Item, item_id)
        if item is None or item.company_id != company_id:
            raise ValueError("کالا نامعتبر است.")
        if session.scalar(select(Item.item_id).where(Item.variant_parent_item_id == item_id).limit(1)) is not None:
            raise ValueError("کالایِ اصلیِ دارایِ متغیر قابلِ‌درخواست نیست -- یکی از متغیرها را انتخاب کنید.")
        next_no = (session.scalar(select(func.max(PurchaseRequestLine.line_no)).where(PurchaseRequestLine.request_id == request_id)) or 0) + 1
        line = PurchaseRequestLine(
            request_id=request_id, line_no=next_no, item_id=item_id, uom_id=uom_id, quantity=quantity, conversion_factor=factor,
            quantity_base=quantity * factor, required_date=required_date, suggested_supplier_detail_account_id=suggested_supplier_id,
            estimated_unit_price=estimated_unit_price, description=(description or None),
        )
        session.add(line)
        session.commit()
        return line.line_id


def update_line(line_id: int, request_id: int, company_id: int, quantity: decimal.Decimal,
                required_date: datetime.date | None = None, suggested_supplier_id: int | None = None,
                estimated_unit_price: decimal.Decimal | None = None, description: str | None = None) -> None:
    if quantity <= 0:
        raise ValueError("مقدار باید بزرگ‌تر از صفر باشد.")
    with new_session() as session:
        _editable(session, request_id, company_id)
        line = session.get(PurchaseRequestLine, line_id)
        if line is None or line.request_id != request_id:
            raise ValueError("ردیف نامعتبر است.")
        line.quantity = quantity
        line.quantity_base = quantity * line.conversion_factor
        line.required_date = required_date
        line.suggested_supplier_detail_account_id = suggested_supplier_id
        line.estimated_unit_price = estimated_unit_price
        line.description = description or None
        session.commit()


def delete_line(line_id: int, request_id: int, company_id: int) -> None:
    with new_session() as session:
        _editable(session, request_id, company_id)
        line = session.get(PurchaseRequestLine, line_id)
        if line is None or line.request_id != request_id:
            raise ValueError("ردیف نامعتبر است.")
        session.delete(line)
        session.commit()


def get_request(request_id: int, company_id: int) -> tuple[PurchaseRequest, list[PurchaseRequestLine]]:
    with new_session() as session:
        row = _get(session, request_id, company_id)
        lines = list(session.scalars(select(PurchaseRequestLine).where(PurchaseRequestLine.request_id == request_id)
                                     .order_by(PurchaseRequestLine.line_no)))
        return row, lines


def list_requests(company_id: int, date_from: datetime.date | None = None, date_to: datetime.date | None = None,
                  statuses: tuple[str, ...] | None = None) -> list[PurchaseRequest]:
    with new_session() as session:
        stmt = select(PurchaseRequest).where(PurchaseRequest.company_id == company_id)
        if date_from is not None:
            stmt = stmt.where(PurchaseRequest.request_date >= date_from)
        if date_to is not None:
            stmt = stmt.where(PurchaseRequest.request_date <= date_to)
        if statuses:
            stmt = stmt.where(PurchaseRequest.status_code.in_(statuses))
        return list(session.scalars(stmt.order_by(PurchaseRequest.request_date, PurchaseRequest.request_no)))


# --- گردشِ تصویب --------------------------------------------------------------
def submit_request(request_id: int, company_id: int) -> None:
    with new_session() as session:
        row = _editable(session, request_id, company_id)
        if session.scalar(select(PurchaseRequestLine.line_id).where(PurchaseRequestLine.request_id == request_id).limit(1)) is None:
            raise ValueError("درخواست حداقل باید یک ردیف داشته باشد.")
        row.status_code = "SUBMITTED"
        row.submitted_at = datetime.datetime.now()
        row.rejected_reason = None
        session.commit()


def approve_request(request_id: int, company_id: int, approved_by_user_id: int) -> None:
    from peecha.services import roles as roles_service

    if not roles_service.is_manager(approved_by_user_id, company_id):
        raise ValueError("تصویبِ درخواستِ خرید فقط برایِ مدیر ممکن است.")
    with new_session() as session:
        row = _get(session, request_id, company_id)
        if row.status_code != "SUBMITTED":
            raise ValueError("فقط درخواستِ ارسال‌شده قابلِ‌تصویب است.")
        row.status_code = "APPROVED"
        row.approved_by_user_id = approved_by_user_id
        row.approved_at = datetime.datetime.now()
        session.commit()


def reject_request(request_id: int, company_id: int, reason: str) -> None:
    if not (reason or "").strip():
        raise ValueError("علتِ رد را بنویسید.")
    with new_session() as session:
        row = _get(session, request_id, company_id)
        if row.status_code != "SUBMITTED":
            raise ValueError("فقط درخواستِ ارسال‌شده قابلِ‌رد است.")
        row.status_code = "REJECTED"
        row.rejected_reason = reason.strip()
        session.commit()


def cancel_request(request_id: int, company_id: int, reason_id: int | None = None) -> None:
    with new_session() as session:
        row = _get(session, request_id, company_id)
        if row.status_code == "CANCELLED":
            return
        if _ordered_by_line(session, [ln.line_id for ln in session.scalars(
                select(PurchaseRequestLine).where(PurchaseRequestLine.request_id == request_id))]):
            raise ValueError("از این درخواست سفارشِ خرید ساخته شده -- ابتدا آن سفارش‌ها را لغو کنید.")
        row.status_code = "CANCELLED"
        row.cancellation_reason_id = reason_id
        session.commit()


# --- سفارش‌شده/مانده --------------------------------------------------------------
def _ordered_by_line(session, line_ids: list[int], include_drafts: bool = True) -> dict[int, decimal.Decimal]:
    if not line_ids:
        return {}
    excluded = ("CANCELLED",) if include_drafts else ("CANCELLED", "DRAFT")
    rows = session.execute(
        select(CommercialDocumentLine.purchase_request_line_id, func.sum(CommercialDocumentLine.quantity_base))
        .join(CommercialDocument, CommercialDocument.document_id == CommercialDocumentLine.document_id)
        .where(CommercialDocumentLine.purchase_request_line_id.in_(line_ids), CommercialDocument.status_code.notin_(excluded),
               CommercialDocument.document_type_code == "PURCHASE_ORDER")
        .group_by(CommercialDocumentLine.purchase_request_line_id)
    ).all()
    return {k: v or _ZERO for k, v in rows}


def ordered_quantities(line_ids: list[int], include_drafts: bool = True) -> dict[int, decimal.Decimal]:
    """include_drafts=False: فقط سفارش‌هایِ تاییدشده (برایِ بودجه، تا مبلغ نه در «در جریان» گم شود نه دوبار شمرده شود)."""
    with new_session() as session:
        return _ordered_by_line(session, line_ids, include_drafts)


def fulfilment(lines: list[PurchaseRequestLine], ordered: dict[int, decimal.Decimal]) -> str:
    total = sum((ln.quantity_base for ln in lines), _ZERO)
    done = sum((min(ordered.get(ln.line_id, _ZERO), ln.quantity_base) for ln in lines), _ZERO)
    if not done:
        return "NONE"
    return "FULL" if done >= total else "PARTIAL"


def linked_orders(request_id: int) -> list[CommercialDocument]:
    with new_session() as session:
        return list(session.scalars(
            select(CommercialDocument).where(CommercialDocument.document_id.in_(
                select(CommercialDocumentLine.document_id)
                .join(PurchaseRequestLine, PurchaseRequestLine.line_id == CommercialDocumentLine.purchase_request_line_id)
                .where(PurchaseRequestLine.request_id == request_id)
            )).order_by(CommercialDocument.document_date, CommercialDocument.document_id)
        ))


def convert_to_orders(
    request_id: int, company_id: int, user_id: int, supplier_id: int | None = None,
    quantities: dict[int, decimal.Decimal] | None = None, order_date: datetime.date | None = None,
) -> list[int]:
    """درخواستِ تصویب‌شده → سفارشِ خرید (یک سفارش برایِ هر تامین‌کننده).
    supplier_id: تامین‌کنندهٔ همهٔ ردیف‌ها (وگرنه تامین‌کنندهٔ پیشنهادیِ هر ردیف).
    quantities: {line_id: مقدار به واحدِ ردیف} برایِ سفارشِ بخشی؛ پیش‌فرض = کلِ مانده."""
    from peecha import session as app_session

    with new_session() as session:
        row = _get(session, request_id, company_id)
        if row.status_code != "APPROVED":
            raise ValueError("فقط درخواستِ تصویب‌شده به سفارش تبدیل می‌شود.")
        lines = list(session.scalars(select(PurchaseRequestLine).where(PurchaseRequestLine.request_id == request_id)
                                     .order_by(PurchaseRequestLine.line_no)))
        ordered = _ordered_by_line(session, [ln.line_id for ln in lines])
        session.expunge_all()
    groups: dict[int, list[tuple[PurchaseRequestLine, decimal.Decimal]]] = defaultdict(list)
    for ln in lines:
        remaining_base = ln.quantity_base - ordered.get(ln.line_id, _ZERO)
        if quantities is not None:
            if ln.line_id not in quantities:
                continue
            wanted_base = quantities[ln.line_id] * ln.conversion_factor
            if wanted_base > remaining_base:
                raise ValueError("مقدارِ سفارش از ماندهٔ ردیفِ درخواست بیشتر است.")
            remaining_base = wanted_base
        if remaining_base <= 0:
            continue
        supplier = supplier_id or ln.suggested_supplier_detail_account_id
        if supplier is None:
            raise ValueError("برایِ ردیف‌هایِ بدونِ تامین‌کنندهٔ پیشنهادی، تامین‌کننده را انتخاب کنید.")
        groups[supplier].append((ln, remaining_base))
    if not groups:
        raise ValueError("ماندهٔ قابلِ‌سفارشی در این درخواست وجود ندارد.")
    company = app_session.current_company
    currency_id = company.base_currency_id if company is not None and company.company_id == company_id else _base_currency(company_id)
    order_ids = []
    for supplier, items in groups.items():
        header = documents_service.DocumentHeaderFields(
            counterparty_detail_account_id=supplier, currency_id=currency_id, warehouse_id=row.warehouse_id,
            requested_delivery_date=row.required_date, cost_center_detail_account_id=row.cost_center_detail_account_id,
            project_detail_account_id=row.project_detail_account_id, purchase_type_id=row.purchase_type_id,
            branch_id=row.branch_id, org_unit_id=row.org_unit_id,
            description=f"از درخواستِ خریدِ شمارهٔ {row.request_no}",
        )
        order_id = documents_service.create_document(company_id, user_id, "PURCHASE_ORDER", order_date or datetime.date.today(), header)
        for ln, qty_base in items:
            documents_service.add_line(
                order_id, company_id, ln.item_id, ln.uom_id, qty_base / ln.conversion_factor, qty_base,
                unit_price=ln.estimated_unit_price or _ZERO, conversion_factor=ln.conversion_factor,
                expected_delivery_date=ln.required_date or row.required_date, description=ln.description,
                purchase_request_line_id=ln.line_id,
            )
        order_ids.append(order_id)
    return order_ids


def _base_currency(company_id: int) -> int:
    from peecha.db.models.core import Company

    with new_session() as session:
        return session.get(Company, company_id).base_currency_id
