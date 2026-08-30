"""سرویسِ اسنادِ عملیاتیِ انبار — رسید/حواله/انتقال/برگشت/اصلاح.

گردشِ کار: DRAFT → CONFIRMED → POSTED (یا CANCELLED از DRAFT/CONFIRMED).
Post هرگز مستقیماً این‌جا انجام نمی‌شود — همیشه inventory_engine.
post_stock_document() صدا زده می‌شود (تنها نقطهٔ نوشتنِ Ledger/Balance)."""

from __future__ import annotations

import datetime
import decimal
from dataclasses import dataclass

from sqlalchemy import func, select

from peecha.db.base import new_session
from peecha.db.models.accounting import FiscalYear
from peecha.db.models.inventory import (
    CompanyCostingSettings,
    CostingMethod,
    DocumentReasonCode,
    Item,
    StockDocument,
    StockDocumentLine,
    StockLedger,
)
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import inventory_engine as engine_service

DOCUMENT_TYPE_CODES = ("RECEIPT", "ISSUE", "TRANSFER", "RETURN_IN", "RETURN_OUT", "ADJUSTMENT")
_REASON_REQUIRED_TYPES = ("ADJUSTMENT", "RETURN_IN", "RETURN_OUT")

# طبقِ گزارشِ صریح («در فرمِ رسیدِ اصلاح جایی برایِ ورودِ مرکزِ هزینه
# نیست، مثلِ فرم‌هایِ فروش/خرید نیست»): نگاشتِ نوعِ سند -> کلیدهایِ
# نقش‌محورِ حسابی که ممکن است در inventory_engine.post_stock_document
# برایِ آن نوعِ سند به‌کار روند — برایِ تشخیصِ اینکه آیا مرکزِ هزینه/پروژه
# رویِ سرِسند *الزامی* است یا نه (هم‌الگو با
# commercial_documents._HEADER_DIMENSION_ROLE_KEYS).
_HEADER_DIMENSION_ROLE_KEYS: dict[str, tuple[str, ...]] = {
    "RECEIPT": ("INVENTORY_ASSET", "INVENTORY_COST_VARIANCE", "SUPPLIER_PAYABLE", "INVENTORY_ADJUSTMENT_GAIN"),
    "ISSUE": ("INVENTORY_ASSET", "COGS", "SUPPLIER_PAYABLE", "INVENTORY_ADJUSTMENT_LOSS"),
    "RETURN_IN": ("INVENTORY_ASSET", "CUSTOMER_RECEIVABLE", "INVENTORY_ADJUSTMENT_GAIN"),
    "RETURN_OUT": ("INVENTORY_ASSET", "SUPPLIER_PAYABLE", "INVENTORY_ADJUSTMENT_LOSS"),
    "ADJUSTMENT": ("INVENTORY_ASSET", "INVENTORY_ADJUSTMENT_GAIN", "INVENTORY_ADJUSTMENT_LOSS"),
    "TRANSFER": (),
}


def get_header_dimension_requirement(company_id: int, document_type_code: str, dimension_code: str) -> tuple[bool, list]:
    """(آیا الزامی است, فهرستِ حساب‌هایِ تفصیلیِ سطحِ آخرِ آن گروه) —
    هم‌الگو با commercial_documents.get_header_dimension_requirement."""
    dim_type_id = dimensions_service.get_specialized_dimension_type_id(company_id, dimension_code)
    options = dimensions_service.list_leaf_detail_accounts(company_id, dim_type_id)
    is_required = False
    for key in _HEADER_DIMENSION_ROLE_KEYS.get(document_type_code, ()):
        account_id = engine_service.get_account_mapping(company_id, key)
        if account_id is None:
            continue
        required = dimensions_service.get_required_dimensions_for_account(account_id)
        if any(r.dimension_type_id == dim_type_id for r in required):
            is_required = True
            break
    return is_required, options


# ---------------------------------------------------------------------
# دلیل‌هایِ ساختاریافتهٔ اصلاح/برگشت
# ---------------------------------------------------------------------
@dataclass
class ReasonCodeRow:
    reason_code_id: int
    applies_to: str
    code: str
    name: str
    is_active: bool


def list_reason_codes(company_id: int, applies_to: str, active_only: bool = True) -> list[ReasonCodeRow]:
    with new_session() as session:
        query = select(DocumentReasonCode).where(
            DocumentReasonCode.applies_to == applies_to,
            (DocumentReasonCode.company_id == company_id) | (DocumentReasonCode.company_id.is_(None)),
        )
        if active_only:
            query = query.where(DocumentReasonCode.is_active)
        rows = session.scalars(query.order_by(DocumentReasonCode.code)).all()
        return [ReasonCodeRow(r.reason_code_id, r.applies_to, r.code, r.name, r.is_active) for r in rows]


def create_reason_code(company_id: int, applies_to: str, code: str, name: str) -> int:
    if applies_to not in _REASON_REQUIRED_TYPES:
        raise ValueError("applies_to نامعتبر است.")
    with new_session() as session:
        row = DocumentReasonCode(company_id=company_id, applies_to=applies_to, code=code.strip(), name=name.strip())
        session.add(row)
        session.commit()
        return row.reason_code_id


def delete_reason_code(reason_code_id: int, company_id: int) -> None:
    with new_session() as session:
        row = session.get(DocumentReasonCode, reason_code_id)
        if row is None or row.company_id != company_id:
            raise ValueError("دلیل نامعتبر است (فقط دلیل‌هایِ اختصاصیِ همین شرکت قابلِ‌حذف‌اند).")
        if session.scalar(select(func.count()).select_from(StockDocumentLine).where(StockDocumentLine.reason_code_id == reason_code_id)):
            raise ValueError("این دلیل در سندی استفاده شده و قابلِ‌حذف نیست.")
        session.delete(row)
        session.commit()


# ---------------------------------------------------------------------
# سرِسند
# ---------------------------------------------------------------------
@dataclass
class StockDocumentRow:
    stock_document_id: int
    document_type_code: str
    document_no: int
    document_date: datetime.date
    status_code: str
    source_warehouse_id: int | None
    destination_warehouse_id: int | None
    counterparty_detail_account_id: int | None
    cost_center_detail_account_id: int | None
    project_detail_account_id: int | None
    reference_no: str | None
    description: str | None
    journal_entry_id: int | None
    created_by_user_id: int
    posted_at: datetime.datetime | None


@dataclass
class StockDocumentLineRow:
    line_id: int
    line_no: int
    item_id: int
    uom_id: int
    quantity: decimal.Decimal
    quantity_base: decimal.Decimal
    bin_location_id: int | None
    destination_bin_location_id: int | None
    batch_id: int | None
    unit_cost: decimal.Decimal | None
    line_total_cost: decimal.Decimal | None
    tax_amount: decimal.Decimal
    quality_status_code: str
    reason_code_id: int | None
    source_line_id: int | None
    description: str | None


def _to_document_row(d: StockDocument) -> StockDocumentRow:
    return StockDocumentRow(
        d.stock_document_id, d.document_type_code, d.document_no, d.document_date, d.status_code,
        d.source_warehouse_id, d.destination_warehouse_id, d.counterparty_detail_account_id,
        d.cost_center_detail_account_id, d.project_detail_account_id, d.reference_no, d.description,
        d.journal_entry_id, d.created_by_user_id, d.posted_at,
    )


def list_stock_documents(
    company_id: int, document_type_code: str | None = None, status_code: str | None = None
) -> list[StockDocumentRow]:
    with new_session() as session:
        query = select(StockDocument).where(StockDocument.company_id == company_id)
        if document_type_code is not None:
            query = query.where(StockDocument.document_type_code == document_type_code)
        if status_code is not None:
            query = query.where(StockDocument.status_code == status_code)
        rows = session.scalars(query.order_by(StockDocument.document_date.desc(), StockDocument.stock_document_id.desc())).all()
        return [_to_document_row(r) for r in rows]


def get_stock_document(stock_document_id: int, company_id: int) -> tuple[StockDocumentRow, list[StockDocumentLineRow]]:
    with new_session() as session:
        doc = session.get(StockDocument, stock_document_id)
        if doc is None or doc.company_id != company_id:
            raise ValueError("سند نامعتبر است.")
        lines = session.scalars(
            select(StockDocumentLine).where(StockDocumentLine.stock_document_id == stock_document_id).order_by(StockDocumentLine.line_no)
        ).all()
        line_rows = [
            StockDocumentLineRow(
                ln.line_id, ln.line_no, ln.item_id, ln.uom_id, ln.quantity, ln.quantity_base, ln.bin_location_id,
                ln.destination_bin_location_id, ln.batch_id, ln.unit_cost, ln.line_total_cost, ln.tax_amount,
                ln.quality_status_code, ln.reason_code_id, ln.source_line_id, ln.description,
            )
            for ln in lines
        ]
        return _to_document_row(doc), line_rows


WAREHOUSE_REQUIREMENTS = {
    "RECEIPT": {"destination": True, "source": False},
    "RETURN_IN": {"destination": True, "source": False},
    "ISSUE": {"destination": False, "source": True},
    "RETURN_OUT": {"destination": False, "source": True},
    "TRANSFER": {"destination": True, "source": True},
}


def _resolve_fiscal_year_id(session, company_id: int, document_date: datetime.date) -> int:
    fiscal_year = session.scalar(
        select(FiscalYear).where(
            FiscalYear.company_id == company_id, FiscalYear.start_date <= document_date, FiscalYear.end_date >= document_date
        )
    )
    if fiscal_year is None:
        raise ValueError("سالِ مالیِ دربرگیرندهٔ این تاریخ تعریف نشده است.")
    if fiscal_year.is_closed:
        raise ValueError("سالِ مالیِ این تاریخ بسته است.")
    return fiscal_year.fiscal_year_id


@dataclass
class DocumentHeaderFields:
    source_warehouse_id: int | None = None
    destination_warehouse_id: int | None = None
    counterparty_detail_account_id: int | None = None
    cost_center_detail_account_id: int | None = None
    project_detail_account_id: int | None = None
    reference_no: str | None = None
    description: str | None = None


def _validate_header_warehouses(document_type_code: str, fields: DocumentHeaderFields) -> None:
    if document_type_code == "ADJUSTMENT":
        if fields.source_warehouse_id is None and fields.destination_warehouse_id is None:
            raise ValueError("برایِ سندِ اصلاح، حداقل یکی از انبارِ مبدا/مقصد باید مشخص شود.")
        return
    req = WAREHOUSE_REQUIREMENTS[document_type_code]
    if req["destination"] and fields.destination_warehouse_id is None:
        raise ValueError("انبارِ مقصد الزامی است.")
    if not req["destination"] and fields.destination_warehouse_id is not None:
        raise ValueError("این نوعِ سند انبارِ مقصد نمی‌پذیرد.")
    if req["source"] and fields.source_warehouse_id is None:
        raise ValueError("انبارِ مبدا الزامی است.")
    if not req["source"] and fields.source_warehouse_id is not None:
        raise ValueError("این نوعِ سند انبارِ مبدا نمی‌پذیرد.")
    if document_type_code == "TRANSFER" and fields.source_warehouse_id == fields.destination_warehouse_id:
        # مجاز است (انتقالِ فقط‌مکانی)؛ تمایزِ واقعی رویِ ردیف‌ها بررسی می‌شود.
        pass


def create_stock_document(
    company_id: int, created_by_user_id: int, document_type_code: str, document_date: datetime.date,
    fields: DocumentHeaderFields | None = None,
) -> int:
    if document_type_code not in DOCUMENT_TYPE_CODES:
        raise ValueError("نوعِ سند نامعتبر است.")
    fields = fields or DocumentHeaderFields()
    _validate_header_warehouses(document_type_code, fields)
    with new_session() as session:
        fiscal_year_id = _resolve_fiscal_year_id(session, company_id, document_date)
        next_no = (
            session.scalar(
                select(func.max(StockDocument.document_no)).where(
                    StockDocument.company_id == company_id, StockDocument.fiscal_year_id == fiscal_year_id,
                    StockDocument.document_type_code == document_type_code,
                )
            )
            or 0
        ) + 1
        doc = StockDocument(
            company_id=company_id, fiscal_year_id=fiscal_year_id, document_type_code=document_type_code,
            document_no=next_no, document_date=document_date, status_code="DRAFT",
            source_warehouse_id=fields.source_warehouse_id, destination_warehouse_id=fields.destination_warehouse_id,
            counterparty_detail_account_id=fields.counterparty_detail_account_id,
            cost_center_detail_account_id=fields.cost_center_detail_account_id,
            project_detail_account_id=fields.project_detail_account_id,
            reference_no=(fields.reference_no or None), description=(fields.description or None),
            created_by_user_id=created_by_user_id,
        )
        session.add(doc)
        session.commit()
        return doc.stock_document_id


def _get_draft_document(session, stock_document_id: int, company_id: int) -> StockDocument:
    doc = session.get(StockDocument, stock_document_id)
    if doc is None or doc.company_id != company_id:
        raise ValueError("سند نامعتبر است.")
    if doc.status_code != "DRAFT":
        raise ValueError("فقط سندِ پیش‌نویس قابلِ‌ویرایش است.")
    return doc


def update_stock_document_header(stock_document_id: int, company_id: int, document_date: datetime.date, fields: DocumentHeaderFields) -> None:
    with new_session() as session:
        doc = _get_draft_document(session, stock_document_id, company_id)
        _validate_header_warehouses(doc.document_type_code, fields)
        doc.document_date = document_date
        doc.fiscal_year_id = _resolve_fiscal_year_id(session, company_id, document_date)
        doc.source_warehouse_id = fields.source_warehouse_id
        doc.destination_warehouse_id = fields.destination_warehouse_id
        doc.counterparty_detail_account_id = fields.counterparty_detail_account_id
        doc.cost_center_detail_account_id = fields.cost_center_detail_account_id
        doc.project_detail_account_id = fields.project_detail_account_id
        doc.reference_no = fields.reference_no or None
        doc.description = fields.description or None
        session.commit()


def delete_stock_document(stock_document_id: int, company_id: int) -> None:
    """حذفِ مستقیم فقط برایِ سندی مجاز است که هنوز هرگز ثبتِ‌نهایی نشده —
    یعنی DRAFT/CONFIRMED/CANCELLED با posted_at خالی — چون چنین سندی هیچ
    ردیفی در inv.stock_ledger ندارد. سندِ ثبتِ‌نهایی‌شده باید از مسیرِ
    reverse_and_cancel_stock_document برود (نه اینجا)، چون هم دفترِ انبار
    را ناهم‌خوان می‌کند و هم فنی به‌خاطرِ ارجاعِ stock_ledger به همین
    ردیف‌ها امکان‌پذیر نیست."""
    with new_session() as session:
        doc = session.get(StockDocument, stock_document_id)
        if doc is None or doc.company_id != company_id:
            raise ValueError("سند نامعتبر است.")
        if doc.posted_at is not None:
            raise ValueError("سندِ ثبتِ‌نهایی‌شده را نمی‌توان مستقیماً حذف کرد — باید ابتدا اثرش خنثی شود.")
        session.query(StockDocumentLine).filter(StockDocumentLine.stock_document_id == stock_document_id).delete()
        session.delete(doc)
        session.commit()


# ---------------------------------------------------------------------
# برگشتِ خودکار + لغوِ سندِ ثبتِ‌نهایی‌شده (برایِ «حذفِ» سندهایِ POSTED)
# ---------------------------------------------------------------------
# طبقِ تصمیمِ صریحِ کاربر: سندِ POSTED هرگز فیزیکی حذف نمی‌شود (هم به‌خاطرِ
# یکپارچگیِ دفترِ انبار/حسابداری، هم چون stock_ledger به ردیف‌هایِ همین سند
# ارجاع دارد) — به‌جایش یک سندِ برگشتیِ هم‌نوع/معکوس ساخته+تاییدشده+
# ثبتِ‌نهایی می‌شود تا اثرش را خنثی کند، سپس خودِ سند «لغوشده» علامت
# می‌خورد (برایِ حفظِ ردِ حسابرسی).
_REVERSAL_TYPE_MAP = {
    "RECEIPT": "ISSUE",
    "ISSUE": "RECEIPT",
    "RETURN_IN": "RETURN_OUT",
    "RETURN_OUT": "RETURN_IN",
    "TRANSFER": "TRANSFER",
    "ADJUSTMENT": "ADJUSTMENT",
}
_AUTO_REVERSAL_REASON_CODE = "AUTO_REVERSAL"


def _ensure_auto_reversal_reason_code(company_id: int, applies_to: str) -> int:
    for row in list_reason_codes(company_id, applies_to, active_only=False):
        if row.code == _AUTO_REVERSAL_REASON_CODE:
            return row.reason_code_id
    return create_reason_code(company_id, applies_to, _AUTO_REVERSAL_REASON_CODE, "برگشتِ خودکار (حذفِ سندِ ثبت‌شده)")


def reverse_and_cancel_stock_document(stock_document_id: int, company_id: int, user_id: int) -> int:
    """معادلِ «حذفِ» یک سندِ POSTED: سندِ برگشتیِ خودکار می‌سازد (نوعِ
    معکوس — مثلاً رسید با حواله خنثی می‌شود، انتقال با انتقالِ معکوس، اصلاح
    با جهتِ معکوس) با همان ردیف‌ها، آن را تاییدوثبت می‌کند، و در پایان
    وضعیتِ سندِ اصلی را CANCELLED می‌کند. شناسهٔ سندِ برگشتی را برمی‌گرداند."""
    with new_session() as session:
        original = session.get(StockDocument, stock_document_id)
        if original is None or original.company_id != company_id:
            raise ValueError("سند نامعتبر است.")
        if original.status_code != "POSTED":
            raise ValueError("این عملیات فقط برایِ سندِ ثبتِ‌نهایی‌شده معنا دارد.")
        original_no = original.document_no
        original_type = original.document_type_code
        header = DocumentHeaderFields(
            source_warehouse_id=original.destination_warehouse_id,
            destination_warehouse_id=original.source_warehouse_id,
            counterparty_detail_account_id=original.counterparty_detail_account_id,
            cost_center_detail_account_id=original.cost_center_detail_account_id,
            project_detail_account_id=original.project_detail_account_id,
            reference_no=f"برگشتِ سندِ #{original_no}",
            description=f"سندِ برگشتیِ خودکار برایِ خنثی‌کردنِ اثرِ سندِ #{original_no} پیش از حذفِ آن.",
        )
        lines_snapshot = [
            (
                ln.line_no, ln.item_id, ln.uom_id, ln.quantity, ln.quantity_base,
                ln.destination_bin_location_id if original_type == "TRANSFER" else ln.bin_location_id,
                ln.bin_location_id if original_type == "TRANSFER" else None,
            )
            for ln in session.scalars(
                select(StockDocumentLine).where(StockDocumentLine.stock_document_id == stock_document_id).order_by(StockDocumentLine.line_no)
            )
        ]

    reversal_type = _REVERSAL_TYPE_MAP[original_type]
    reason_code_id = (
        _ensure_auto_reversal_reason_code(company_id, reversal_type) if reversal_type in _REASON_REQUIRED_TYPES else None
    )

    reversal_doc_id = create_stock_document(company_id, user_id, reversal_type, datetime.date.today(), header)
    try:
        for line_no, item_id, uom_id, quantity, quantity_base, bin_location_id, destination_bin_location_id in lines_snapshot:
            add_line(reversal_doc_id, company_id, LineFields(
                item_id=item_id, uom_id=uom_id, quantity=quantity, quantity_base=quantity_base,
                bin_location_id=bin_location_id, destination_bin_location_id=destination_bin_location_id,
                reason_code_id=reason_code_id, description=f"برگشتِ ردیفِ #{line_no} از سندِ #{original_no}",
            ))
        confirm_stock_document(reversal_doc_id, company_id)
        post_stock_document(reversal_doc_id, company_id, user_id)
    except ValueError:
        try:
            delete_stock_document(reversal_doc_id, company_id)
        except ValueError:
            pass
        raise

    with new_session() as session:
        original = session.get(StockDocument, stock_document_id)
        original.status_code = "CANCELLED"
        session.commit()

    return reversal_doc_id


# ---------------------------------------------------------------------
# ردیف‌ها
# ---------------------------------------------------------------------
@dataclass
class LineFields:
    item_id: int
    uom_id: int
    quantity: decimal.Decimal
    quantity_base: decimal.Decimal
    bin_location_id: int | None = None
    destination_bin_location_id: int | None = None
    batch_id: int | None = None
    unit_cost: decimal.Decimal | None = None
    # طبقِ رفعِ باگِ واقعی («مالياتِ ردیفِ فاکتورِ خرید هیچ‌وقت به سندِ
    # حسابداری نمی‌رسد»): وقتی این ردیف از یک سندِ بازرگانی (فاکتورِ
    # خرید) می‌آید، مالياتِ همان ردیف جداگانه این‌جا هم منتقل می‌شود —
    # نه بخشی از unit_cost (که ارزشِ خودِ موجودی است).
    tax_amount: decimal.Decimal | None = None
    reason_code_id: int | None = None
    source_line_id: int | None = None
    description: str | None = None


def add_line(stock_document_id: int, company_id: int, fields: LineFields) -> int:
    if fields.quantity <= 0 or fields.quantity_base <= 0:
        raise ValueError("مقدار باید بزرگ‌تر از صفر باشد.")
    with new_session() as session:
        doc = _get_draft_document(session, stock_document_id, company_id)
        next_no = (
            session.scalar(
                select(func.max(StockDocumentLine.line_no)).where(StockDocumentLine.stock_document_id == stock_document_id)
            )
            or 0
        ) + 1
        if doc.document_type_code == "TRANSFER" and doc.source_warehouse_id == doc.destination_warehouse_id:
            if fields.bin_location_id is not None and fields.bin_location_id == fields.destination_bin_location_id:
                raise ValueError("مکانِ مبدا و مقصد نمی‌توانند یکسان باشند.")
        line = StockDocumentLine(
            stock_document_id=stock_document_id, line_no=next_no, item_id=fields.item_id, uom_id=fields.uom_id,
            quantity=fields.quantity, quantity_base=fields.quantity_base, bin_location_id=fields.bin_location_id,
            destination_bin_location_id=fields.destination_bin_location_id, batch_id=fields.batch_id,
            unit_cost=fields.unit_cost, tax_amount=(fields.tax_amount or decimal.Decimal(0)),
            reason_code_id=fields.reason_code_id, source_line_id=fields.source_line_id,
            description=(fields.description or None),
        )
        if doc.document_type_code == "RECEIPT":
            item = session.get(Item, fields.item_id)
            if item is not None and item.requires_qc and engine_service.is_feature_enabled(company_id, "QUALITY_CONTROL"):
                line.quality_status_code = "PENDING"
        session.add(line)
        session.commit()
        return line.line_id


def update_line(line_id: int, stock_document_id: int, company_id: int, fields: LineFields) -> None:
    if fields.quantity <= 0 or fields.quantity_base <= 0:
        raise ValueError("مقدار باید بزرگ‌تر از صفر باشد.")
    with new_session() as session:
        _get_draft_document(session, stock_document_id, company_id)
        line = session.get(StockDocumentLine, line_id)
        if line is None or line.stock_document_id != stock_document_id:
            raise ValueError("ردیف نامعتبر است.")
        line.item_id, line.uom_id = fields.item_id, fields.uom_id
        line.quantity, line.quantity_base = fields.quantity, fields.quantity_base
        line.bin_location_id = fields.bin_location_id
        line.destination_bin_location_id = fields.destination_bin_location_id
        line.batch_id = fields.batch_id
        line.unit_cost = fields.unit_cost
        line.tax_amount = fields.tax_amount or decimal.Decimal(0)
        line.reason_code_id = fields.reason_code_id
        line.source_line_id = fields.source_line_id
        line.description = fields.description or None
        session.commit()


def delete_line(line_id: int, stock_document_id: int, company_id: int) -> None:
    with new_session() as session:
        _get_draft_document(session, stock_document_id, company_id)
        line = session.get(StockDocumentLine, line_id)
        if line is None or line.stock_document_id != stock_document_id:
            raise ValueError("ردیف نامعتبر است.")
        session.delete(line)
        session.commit()


# ---------------------------------------------------------------------
# گردشِ کار: DRAFT → CONFIRMED → POSTED / CANCELLED
# ---------------------------------------------------------------------
def confirm_stock_document(stock_document_id: int, company_id: int) -> None:
    with new_session() as session:
        doc = session.get(StockDocument, stock_document_id)
        if doc is None or doc.company_id != company_id:
            raise ValueError("سند نامعتبر است.")
        if doc.status_code != "DRAFT":
            raise ValueError("فقط سندِ پیش‌نویس قابلِ‌تایید است.")

        lines = session.scalars(select(StockDocumentLine).where(StockDocumentLine.stock_document_id == stock_document_id)).all()
        if not lines:
            raise ValueError("سند حداقل باید یک ردیف داشته باشد.")

        if doc.document_type_code in _REASON_REQUIRED_TYPES:
            # باگِ واقعیِ رفع‌شده: مقایسه‌یِ «تعدادِ دلیل‌هایِ *یکتا*» با
            # «تعدادِ ردیف‌ها» فقط وقتی هر ردیف دلیلِ متفاوتی داشت درست
            # کار می‌کرد — به‌محضِ این‌که دو ردیف (مثلاً هردو با دلیلِ
            # «اصلاحِ ممیزی») همان یک دلیلِ مشترک را داشتند، len(reason_ids)
            # از len(lines) کمتر می‌شد و کاربر با پیامِ «انتخابِ دلیل الزامی
            # است» رد می‌شد، حتی وقتی همه‌یِ ردیف‌ها واقعاً دلیل داشتند.
            reason_ids = {ln.reason_code_id for ln in lines if ln.reason_code_id is not None}
            if any(ln.reason_code_id is None for ln in lines):
                raise ValueError("انتخابِ دلیل برایِ این نوعِ سند الزامی است.")
            if reason_ids:
                valid_count = session.scalar(
                    select(func.count()).select_from(DocumentReasonCode).where(
                        DocumentReasonCode.reason_code_id.in_(reason_ids),
                        DocumentReasonCode.applies_to == doc.document_type_code,
                    )
                )
                if valid_count != len(reason_ids):
                    raise ValueError("دلیلِ انتخاب‌شده با نوعِ این سند سازگار نیست.")

        if doc.document_type_code == "TRANSFER" and doc.source_warehouse_id == doc.destination_warehouse_id:
            for ln in lines:
                if ln.destination_bin_location_id is None:
                    raise ValueError("برایِ انتقالِ فقط‌مکانی، انتخابِ مکانِ مقصد الزامی است.")
                effective_source_bin = ln.bin_location_id
                if effective_source_bin is not None and effective_source_bin == ln.destination_bin_location_id:
                    raise ValueError("مکانِ مبدا و مقصد نمی‌توانند یکسان باشند.")

        doc.status_code = "CONFIRMED"
        session.commit()


def revert_to_draft(stock_document_id: int, company_id: int) -> None:
    with new_session() as session:
        doc = session.get(StockDocument, stock_document_id)
        if doc is None or doc.company_id != company_id:
            raise ValueError("سند نامعتبر است.")
        if doc.status_code != "CONFIRMED":
            raise ValueError("فقط سندِ تاییدشده قابلِ‌بازگشت به پیش‌نویس است.")
        doc.status_code = "DRAFT"
        session.commit()


def cancel_stock_document(stock_document_id: int, company_id: int) -> None:
    with new_session() as session:
        doc = session.get(StockDocument, stock_document_id)
        if doc is None or doc.company_id != company_id:
            raise ValueError("سند نامعتبر است.")
        if doc.status_code not in ("DRAFT", "CONFIRMED"):
            raise ValueError("سندِ ثبت‌شده هرگز لغو نمی‌شود — برایِ اصلاح، سندِ تازه‌ای ثبت کنید.")
        doc.status_code = "CANCELLED"
        session.commit()


def post_stock_document(stock_document_id: int, company_id: int, posted_by_user_id: int) -> engine_service.PostResult:
    return engine_service.post_stock_document(stock_document_id, company_id, posted_by_user_id)


def reverse_stock_document(stock_document_id: int, company_id: int, reversed_by_user_id: int) -> engine_service.PostResult:
    """طبقِ درخواستِ صریح («اصلاحِ فاکتورِ ثبت‌شده باید عیناً برگشت بخورد،
    نه اینکه سندِ اصلی با تاریخِ عقب‌دار دست‌کاری شود») -- پیاده‌سازیِ کاملش
    در inventory_engine.py است (تنها نقطه‌یِ نوشتنِ stock_ledger/
    stock_balance)؛ این‌جا فقط delegate می‌کند، هم‌الگو با post_stock_document."""
    return engine_service.reverse_stock_document(stock_document_id, company_id, reversed_by_user_id)
