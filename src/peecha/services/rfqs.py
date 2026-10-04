"""استعلامِ قیمت (RFQ) -- R242.

گردش: DRAFT → SENT (دعوت از تامین‌کنندگان، ثبتِ پیشنهادها) → AWARDED (انتخابِ برندهٔ هر ردیف)
→ ORDERED (ساختِ سفارشِ خرید برایِ برندگان) ؛ CANCELLED پیش از سفارش.
فیِ خالصِ پیشنهاد = فی × (۱ − درصدِ تخفیف ÷ ۱۰۰) ، به واحدِ ردیفِ استعلام.
سفارش با همان create_document/add_line ساخته می‌شود؛ منطقِ سفارش تغییری نمی‌کند.
"""

from __future__ import annotations

import datetime
import decimal
from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import func, select

from peecha.db.base import new_session
from peecha.db.models.commercial import PurchaseRequest, Rfq, RfqLine, RfqQuote, RfqSupplier
from peecha.services import commercial_documents as documents_service
from peecha.services import unit_conversion as uc

_ZERO = decimal.Decimal(0)
STATUS_LABELS = {"DRAFT": "پیش‌نویس", "SENT": "ارسال‌شده", "AWARDED": "برنده انتخاب شد", "ORDERED": "سفارش داده شد",
                 "CANCELLED": "لغوشده"}
SUPPLIER_STATUS_LABELS = {"INVITED": "منتظرِ پاسخ", "RESPONDED": "پاسخ داده", "DECLINED": "انصراف"}


def net_price(quote: RfqQuote) -> decimal.Decimal:
    return quote.unit_price * (1 - (quote.discount_percent or _ZERO) / 100)


def _get(session, rfq_id: int, company_id: int) -> Rfq:
    row = session.get(Rfq, rfq_id)
    if row is None or row.company_id != company_id:
        raise ValueError("استعلام نامعتبر است.")
    return row


def _require(row: Rfq, *statuses: str, message: str) -> None:
    if row.status_code not in statuses:
        raise ValueError(message)


def create_rfq(company_id: int, user_id: int, rfq_date: datetime.date, response_due_date: datetime.date | None = None,
               description: str | None = None, request_id: int | None = None) -> int:
    if response_due_date is not None and response_due_date < rfq_date:
        raise ValueError("مهلتِ پاسخ نمی‌تواند پیش از تاریخِ استعلام باشد.")
    with new_session() as session:
        next_no = (session.scalar(select(func.max(Rfq.rfq_no)).where(Rfq.company_id == company_id)) or 0) + 1
        row = Rfq(company_id=company_id, rfq_no=next_no, rfq_date=rfq_date, response_due_date=response_due_date,
                  description=description or None, request_id=request_id, created_by_user_id=user_id, status_code="DRAFT")
        session.add(row)
        session.commit()
        return row.rfq_id


def update_rfq(rfq_id: int, company_id: int, rfq_date: datetime.date, response_due_date: datetime.date | None,
               description: str | None) -> None:
    with new_session() as session:
        row = _get(session, rfq_id, company_id)
        _require(row, "DRAFT", "SENT", message="استعلامِ انتخاب‌شده/لغوشده قابلِ‌ویرایش نیست.")
        if response_due_date is not None and response_due_date < rfq_date:
            raise ValueError("مهلتِ پاسخ نمی‌تواند پیش از تاریخِ استعلام باشد.")
        row.rfq_date, row.response_due_date, row.description = rfq_date, response_due_date, description or None
        session.commit()


def create_from_request(request_id: int, company_id: int, user_id: int, response_due_date: datetime.date | None = None) -> int:
    """استعلام از ماندهٔ سفارش‌نشدهٔ یک درخواستِ خریدِ تصویب‌شده؛ تامین‌کنندگانِ پیشنهادیِ ردیف‌ها دعوت می‌شوند."""
    from peecha.services import purchase_requests as pr_service

    request, lines = pr_service.get_request(request_id, company_id)
    if request.status_code != "APPROVED":
        raise ValueError("فقط از درخواستِ تصویب‌شده می‌توان استعلام گرفت.")
    ordered = pr_service.ordered_quantities([ln.line_id for ln in lines])
    open_lines = [(ln, ln.quantity_base - ordered.get(ln.line_id, _ZERO)) for ln in lines]
    open_lines = [(ln, rest) for ln, rest in open_lines if rest > 0]
    if not open_lines:
        raise ValueError("ماندهٔ سفارش‌نشده‌ای در این درخواست وجود ندارد.")
    rfq_id = create_rfq(company_id, user_id, datetime.date.today(), response_due_date,
                        f"از درخواستِ خریدِ شمارهٔ {request.request_no}", request_id)
    with new_session() as session:
        for no, (ln, rest) in enumerate(open_lines, start=1):
            session.add(RfqLine(rfq_id=rfq_id, line_no=no, item_id=ln.item_id, uom_id=ln.uom_id, quantity=rest / ln.conversion_factor,
                                conversion_factor=ln.conversion_factor, quantity_base=rest,
                                required_date=ln.required_date or request.required_date, purchase_request_line_id=ln.line_id,
                                description=ln.description))
        for supplier in {ln.suggested_supplier_detail_account_id for ln, _r in open_lines if ln.suggested_supplier_detail_account_id}:
            session.add(RfqSupplier(rfq_id=rfq_id, supplier_detail_account_id=supplier, status_code="INVITED"))
        session.commit()
    return rfq_id


def add_line(rfq_id: int, company_id: int, item_id: int, uom_id: int, quantity: decimal.Decimal,
             required_date: datetime.date | None = None, description: str | None = None) -> int:
    if quantity <= 0:
        raise ValueError("مقدار باید بزرگ‌تر از صفر باشد.")
    uc.validate_quantity(item_id, uom_id, quantity, purpose="PURCHASE")
    factor = uc.get_factor(item_id, uom_id, require_active=True)
    with new_session() as session:
        row = _get(session, rfq_id, company_id)
        _require(row, "DRAFT", message="ردیف فقط به استعلامِ پیش‌نویس اضافه می‌شود.")
        next_no = (session.scalar(select(func.max(RfqLine.line_no)).where(RfqLine.rfq_id == rfq_id)) or 0) + 1
        line = RfqLine(rfq_id=rfq_id, line_no=next_no, item_id=item_id, uom_id=uom_id, quantity=quantity, conversion_factor=factor,
                       quantity_base=quantity * factor, required_date=required_date, description=description or None)
        session.add(line)
        session.commit()
        return line.line_id


def delete_line(line_id: int, rfq_id: int, company_id: int) -> None:
    with new_session() as session:
        row = _get(session, rfq_id, company_id)
        _require(row, "DRAFT", message="ردیف فقط از استعلامِ پیش‌نویس حذف می‌شود.")
        line = session.get(RfqLine, line_id)
        if line is None or line.rfq_id != rfq_id:
            raise ValueError("ردیف نامعتبر است.")
        session.delete(line)
        session.commit()


def add_supplier(rfq_id: int, company_id: int, supplier_id: int) -> int:
    with new_session() as session:
        row = _get(session, rfq_id, company_id)
        _require(row, "DRAFT", "SENT", message="به این استعلام دیگر تامین‌کننده اضافه نمی‌شود.")
        if session.scalar(select(RfqSupplier).where(RfqSupplier.rfq_id == rfq_id, RfqSupplier.supplier_detail_account_id == supplier_id)):
            raise ValueError("این تامین‌کننده قبلاً دعوت شده است.")
        s = RfqSupplier(rfq_id=rfq_id, supplier_detail_account_id=supplier_id, status_code="INVITED")
        session.add(s)
        session.commit()
        return s.rfq_supplier_id


def remove_supplier(rfq_supplier_id: int, rfq_id: int, company_id: int) -> None:
    with new_session() as session:
        row = _get(session, rfq_id, company_id)
        _require(row, "DRAFT", message="تامین‌کننده فقط از استعلامِ پیش‌نویس حذف می‌شود.")
        s = session.get(RfqSupplier, rfq_supplier_id)
        if s is None or s.rfq_id != rfq_id:
            raise ValueError("تامین‌کننده نامعتبر است.")
        session.delete(s)
        session.commit()


def send_rfq(rfq_id: int, company_id: int) -> None:
    with new_session() as session:
        row = _get(session, rfq_id, company_id)
        _require(row, "DRAFT", message="فقط استعلامِ پیش‌نویس ارسال می‌شود.")
        if session.scalar(select(RfqLine.line_id).where(RfqLine.rfq_id == rfq_id).limit(1)) is None:
            raise ValueError("استعلام حداقل یک ردیف لازم دارد.")
        if session.scalar(select(RfqSupplier.rfq_supplier_id).where(RfqSupplier.rfq_id == rfq_id).limit(1)) is None:
            raise ValueError("حداقل یک تامین‌کننده دعوت کنید.")
        row.status_code = "SENT"
        row.sent_at = datetime.datetime.now()
        session.commit()


def record_quote(rfq_supplier_id: int, rfq_line_id: int, company_id: int, unit_price: decimal.Decimal,
                 discount_percent: decimal.Decimal = _ZERO, lead_time_days: int | None = None,
                 valid_until: datetime.date | None = None, note: str | None = None) -> int:
    if unit_price < 0 or not (0 <= discount_percent <= 100):
        raise ValueError("فی یا درصدِ تخفیف نامعتبر است.")
    with new_session() as session:
        s = session.get(RfqSupplier, rfq_supplier_id)
        line = session.get(RfqLine, rfq_line_id)
        if s is None or line is None or s.rfq_id != line.rfq_id:
            raise ValueError("پیشنهاد نامعتبر است.")
        row = _get(session, s.rfq_id, company_id)
        _require(row, "SENT", message="پیشنهاد فقط برایِ استعلامِ ارسال‌شده ثبت می‌شود.")
        quote = session.scalar(select(RfqQuote).where(RfqQuote.rfq_supplier_id == rfq_supplier_id, RfqQuote.rfq_line_id == rfq_line_id))
        if quote is None:
            quote = RfqQuote(rfq_supplier_id=rfq_supplier_id, rfq_line_id=rfq_line_id)
            session.add(quote)
        quote.unit_price, quote.discount_percent, quote.lead_time_days = unit_price, discount_percent, lead_time_days
        quote.valid_until, quote.note = valid_until, note or None
        s.status_code = "RESPONDED"
        s.responded_at = s.responded_at or datetime.datetime.now()
        session.commit()
        return quote.quote_id


def decline(rfq_supplier_id: int, company_id: int, note: str | None = None) -> None:
    with new_session() as session:
        s = session.get(RfqSupplier, rfq_supplier_id)
        if s is None:
            raise ValueError("تامین‌کننده نامعتبر است.")
        _require(_get(session, s.rfq_id, company_id), "SENT", message="فقط در استعلامِ ارسال‌شده.")
        s.status_code, s.note = "DECLINED", note or None
        s.responded_at = s.responded_at or datetime.datetime.now()
        session.commit()


def get_rfq(rfq_id: int, company_id: int):
    """(استعلام، ردیف‌ها، تامین‌کنندگان، پیشنهادها)."""
    with new_session() as session:
        row = _get(session, rfq_id, company_id)
        lines = list(session.scalars(select(RfqLine).where(RfqLine.rfq_id == rfq_id).order_by(RfqLine.line_no)))
        suppliers = list(session.scalars(select(RfqSupplier).where(RfqSupplier.rfq_id == rfq_id).order_by(RfqSupplier.rfq_supplier_id)))
        quotes = list(session.scalars(select(RfqQuote).where(RfqQuote.rfq_supplier_id.in_([s.rfq_supplier_id for s in suppliers])))) \
            if suppliers else []
        return row, lines, suppliers, quotes


def list_rfqs(company_id: int, date_from: datetime.date | None = None, date_to: datetime.date | None = None) -> list[Rfq]:
    with new_session() as session:
        stmt = select(Rfq).where(Rfq.company_id == company_id)
        if date_from is not None:
            stmt = stmt.where(Rfq.rfq_date >= date_from)
        if date_to is not None:
            stmt = stmt.where(Rfq.rfq_date <= date_to)
        return list(session.scalars(stmt.order_by(Rfq.rfq_date, Rfq.rfq_no)))


@dataclass
class ComparisonRow:
    line: RfqLine
    supplier: RfqSupplier
    quote: RfqQuote
    net: decimal.Decimal
    total: decimal.Decimal
    rank: int
    is_best: bool


def compare(rfq_id: int, company_id: int) -> list[ComparisonRow]:
    """رتبهٔ پیشنهادهایِ هر ردیف بر اساسِ فیِ خالص (برابر: زمانِ تحویلِ کمتر)."""
    _row, lines, suppliers, quotes = get_rfq(rfq_id, company_id)
    by_supplier = {s.rfq_supplier_id: s for s in suppliers}
    out = []
    for line in lines:
        line_quotes = sorted((q for q in quotes if q.rfq_line_id == line.line_id),
                             key=lambda q: (net_price(q), q.lead_time_days if q.lead_time_days is not None else 10 ** 6))
        for rank, q in enumerate(line_quotes, start=1):
            net = net_price(q)
            out.append(ComparisonRow(line, by_supplier[q.rfq_supplier_id], q, net, net * line.quantity, rank, rank == 1))
    return out


def award(rfq_id: int, company_id: int, user_id: int, quote_ids: list[int] | None = None) -> None:
    """انتخابِ برنده: quote_ids (حداکثر یکی برایِ هر ردیف) یا، اگر داده نشود، بهترین پیشنهادِ هر ردیف."""
    rows = compare(rfq_id, company_id)
    if quote_ids is None:
        quote_ids = [r.quote.quote_id for r in rows if r.is_best]
    chosen = [r for r in rows if r.quote.quote_id in set(quote_ids)]
    if len(chosen) != len(set(quote_ids)) or not chosen:
        raise ValueError("پیشنهادِ انتخاب‌شده نامعتبر است.")
    if len({r.line.line_id for r in chosen}) != len(chosen):
        raise ValueError("برایِ هر ردیف فقط یک برنده انتخاب کنید.")
    today = datetime.date.today()
    if any(r.quote.valid_until is not None and r.quote.valid_until < today for r in chosen):
        raise ValueError("اعتبارِ پیشنهادِ انتخاب‌شده تمام شده است.")
    with new_session() as session:
        row = _get(session, rfq_id, company_id)
        _require(row, "SENT", "AWARDED", message="فقط استعلامِ ارسال‌شده قابلِ‌انتخابِ برنده است.")
        for q in session.scalars(select(RfqQuote).where(RfqQuote.quote_id.in_([r.quote.quote_id for r in rows]))):
            q.is_awarded = q.quote_id in set(quote_ids)
        row.status_code = "AWARDED"
        row.awarded_at = datetime.datetime.now()
        row.awarded_by_user_id = user_id
        session.commit()


def create_orders(rfq_id: int, company_id: int, user_id: int, warehouse_id: int | None = None,
                  order_date: datetime.date | None = None) -> list[int]:
    """سفارشِ خرید برایِ پیشنهادهایِ برنده (یک سفارش برایِ هر تامین‌کننده)."""
    row, lines, suppliers, quotes = get_rfq(rfq_id, company_id)
    if row.status_code != "AWARDED":
        raise ValueError("ابتدا برندهٔ استعلام را انتخاب کنید.")
    by_line = {ln.line_id: ln for ln in lines}
    by_supplier = {s.rfq_supplier_id: s for s in suppliers}
    groups: dict[int, list[RfqQuote]] = defaultdict(list)
    for q in quotes:
        if q.is_awarded:
            groups[by_supplier[q.rfq_supplier_id].supplier_detail_account_id].append(q)
    request = None
    if row.request_id is not None:
        with new_session() as session:
            request = session.get(PurchaseRequest, row.request_id)
    from peecha.services.purchase_requests import _base_currency

    order_ids = []
    for supplier_id, qs in groups.items():
        header = documents_service.DocumentHeaderFields(
            counterparty_detail_account_id=supplier_id, currency_id=_base_currency(company_id),
            warehouse_id=warehouse_id or (request.warehouse_id if request else None),
            requested_delivery_date=min((by_line[q.rfq_line_id].required_date for q in qs if by_line[q.rfq_line_id].required_date),
                                        default=None),
            cost_center_detail_account_id=request.cost_center_detail_account_id if request else None,
            project_detail_account_id=request.project_detail_account_id if request else None,
            purchase_type_id=request.purchase_type_id if request else None,
            description=f"از استعلامِ قیمتِ شمارهٔ {row.rfq_no}",
        )
        order_id = documents_service.create_document(company_id, user_id, "PURCHASE_ORDER", order_date or datetime.date.today(), header)
        for q in qs:
            ln = by_line[q.rfq_line_id]
            expected = ln.required_date
            if q.lead_time_days is not None:
                expected = max(filter(None, (expected, (order_date or datetime.date.today()) + datetime.timedelta(days=q.lead_time_days))))
            documents_service.add_line(
                order_id, company_id, ln.item_id, ln.uom_id, ln.quantity, ln.quantity_base, unit_price=q.unit_price,
                discount_percent=q.discount_percent or _ZERO, conversion_factor=ln.conversion_factor, expected_delivery_date=expected,
                description=ln.description, purchase_request_line_id=ln.purchase_request_line_id, rfq_quote_id=q.quote_id,
            )
        order_ids.append(order_id)
    with new_session() as session:
        _get(session, rfq_id, company_id).status_code = "ORDERED"
        session.commit()
    return order_ids


def cancel_rfq(rfq_id: int, company_id: int) -> None:
    with new_session() as session:
        row = _get(session, rfq_id, company_id)
        _require(row, "DRAFT", "SENT", "AWARDED", message="استعلامی که سفارشش ساخته شده لغو نمی‌شود.")
        row.status_code = "CANCELLED"
        session.commit()
