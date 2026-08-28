"""موتورِ اسنادِ بازرگانی (comm.commercial_documents → inv.stock_documents +
acc.journal_entries + comm.commission_entries)، طبقِ مراحلِ ۲/۴/۵.

اصلِ «دو سندِ حسابداریِ خودکارِ جدا»: هر Postِ فاکتور، دو مسیرِ مالی را
فعال می‌کند —
  ۱) موتورِ ازپیش‌ساخته‌شدهٔ انبار (inventory_engine.post_stock_document)
     که خودش، وقتی counterparty_detail_account_id رویِ سرِسندِ انبار
     تنظیم شده باشد، مستقیماً SUPPLIER_PAYABLE/CUSTOMER_RECEIVABLE را
     می‌شناسد (inv.account_mappings) — برایِ PURCHASE_INVOICE (→RECEIPT)
     و PURCHASE_RETURN (→RETURN_OUT) همین یک سند برایِ کل اثرِ مالی کافی
     است؛ SALES_RETURN (→RETURN_IN) هم به همین شکل مستقیماً
     CUSTOMER_RECEIVABLE را بستانکار می‌کند.
  ۲) فقط برایِ SALES_INVOICE (→ISSUE)، موتورِ انبار صرفاً COGS/کاهشِ
     موجودی را ثبت می‌کند (هرگز به AR/درآمد دست نمی‌زند) — پس این‌جا
     یک سندِ حسابداریِ دومِ مستقلِ «بازرگانی» برایِ شناساییِ درآمد/AR/
     مالیات/تخفیف ساخته می‌شود.

محدودیتِ آگاهانهٔ همین دور: PURCHASE_TAX_RECEIVABLE/PURCHASE_DISCOUNT
هنوز به سندِ جداگانه تبدیل نمی‌شوند (فقط رویِ ردیف ذخیره می‌مانند) —
دورِ بعد."""

from __future__ import annotations

import datetime
import decimal
from dataclasses import dataclass

from sqlalchemy import func, select

from peecha.db.base import new_session
from peecha.db.models.accounting import FiscalYear
from peecha.db.models.commercial import CommercialDocument, CommercialDocumentLine, CreditHold
from peecha.services import commercial_contracts as contracts_service
from peecha.services import commercial_credit as credit_service
from peecha.services import commercial_pricing as pricing_service
from peecha.services import commercial_settings as settings_service
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import inventory_documents as inv_documents_service
from peecha.services import inventory_engine as inv_engine_service
from peecha.services import journal_entries as je_service

DOCUMENT_TYPE_CODES = (
    "SALES_ORDER", "SALES_PROFORMA", "SALES_INVOICE", "SALES_RETURN",
    "PURCHASE_ORDER", "PURCHASE_PROFORMA", "PURCHASE_INVOICE", "PURCHASE_RETURN",
)
# سفارش/پیش‌فاکتور فقط سندِ قصد/پیشنهاد هستند — هرگز اثری در انبار یا
# حسابداری نمی‌گذارند؛ POSTED برایِ این دو یعنی صرفاً «قفل و ارسال‌شده».
_ORDER_TYPES = ("SALES_ORDER", "SALES_PROFORMA", "PURCHASE_ORDER", "PURCHASE_PROFORMA")
_STOCK_DOC_TYPE_BY_TYPE = {
    "PURCHASE_INVOICE": "RECEIPT",
    "SALES_INVOICE": "ISSUE",
    "SALES_RETURN": "RETURN_IN",
    "PURCHASE_RETURN": "RETURN_OUT",
}
# طبقِ درخواستِ صریح («سفارش/پیش‌فاکتور باید بتواند به فاکتور تبدیل
# شود»): مقصدِ تبدیل برایِ هر نوعِ سندِ غیرِمالی.
_CONVERT_TO_INVOICE_TARGET = {
    "SALES_ORDER": "SALES_INVOICE",
    "SALES_PROFORMA": "SALES_INVOICE",
    "PURCHASE_ORDER": "PURCHASE_INVOICE",
    "PURCHASE_PROFORMA": "PURCHASE_INVOICE",
}

# طبقِ رفعِ باگِ واقعی («برای حساب X انتخابِ گروه‌هایِ تفصیلیِ الزامی
# فراموش شده است»): حساب‌هایِ نقش‌محورِ درگیر در ثبتِ نهاییِ هر نوعِ سند —
# برایِ تشخیصِ این‌که مرکزِ هزینه/پروژه در سرِسند باید الزامی نمایش داده
# شود یا نه (هرکدام از این حساب‌ها که تنظیم شده و آن بُعد رویش الزامی
# باشد، کافی‌ست). (منبعِ نگاشت, کلید) — منبعِ "comm" یعنی
# commercial_settings، "inv" یعنی inventory_engine.
_HEADER_DIMENSION_ROLE_KEYS = {
    "SALES_INVOICE": [("comm", "SALES_REVENUE"), ("inv", "CUSTOMER_RECEIVABLE"), ("inv", "INVENTORY_ASSET"), ("inv", "COGS")],
    "SALES_RETURN": [("inv", "CUSTOMER_RECEIVABLE"), ("inv", "INVENTORY_ASSET")],
    "PURCHASE_INVOICE": [("inv", "SUPPLIER_PAYABLE"), ("inv", "INVENTORY_ASSET")],
    "PURCHASE_RETURN": [("inv", "SUPPLIER_PAYABLE"), ("inv", "INVENTORY_ASSET")],
}


def get_header_dimension_requirement(company_id: int, document_type_code: str, dimension_code: str) -> tuple[bool, list]:
    """(آیا الزامی است, فهرستِ حساب‌هایِ تفصیلیِ سطحِ آخرِ آن گروه) — برایِ
    فیلدهایِ همیشه‌حاضرِ «مرکزِ هزینه»/«پروژه» در سرِسند، هم‌الگو با
    petty_cash.get_advance_shared_dimension_options."""
    dim_type_id = dimensions_service.get_specialized_dimension_type_id(company_id, dimension_code)
    options = dimensions_service.list_leaf_detail_accounts(company_id, dim_type_id)
    is_required = False
    for source, key in _HEADER_DIMENSION_ROLE_KEYS.get(document_type_code, []):
        account_id = (
            settings_service.get_account_mapping(company_id, key) if source == "comm"
            else inv_engine_service.get_account_mapping(company_id, key)
        )
        if account_id is None:
            continue
        required = dimensions_service.get_required_dimensions_for_account(account_id)
        if any(r.dimension_type_id == dim_type_id for r in required):
            is_required = True
            break
    return is_required, options

_ZERO = decimal.Decimal("0")
_Q2 = decimal.Decimal("0.01")


def _money(value: decimal.Decimal) -> decimal.Decimal:
    return value.quantize(_Q2, rounding=decimal.ROUND_HALF_UP)


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


# ---------------------------------------------------------------------
# سرِسند
# ---------------------------------------------------------------------
@dataclass
class DocumentHeaderFields:
    counterparty_detail_account_id: int
    currency_id: int
    warehouse_id: int | None = None
    channel_code: str | None = None
    price_list_id: int | None = None
    pos_session_id: int | None = None
    source_document_id: int | None = None
    linked_exchange_document_id: int | None = None
    exchange_rate: decimal.Decimal = decimal.Decimal(1)
    requested_delivery_date: datetime.date | None = None
    sales_rep_detail_account_id: int | None = None
    cost_center_detail_account_id: int | None = None
    project_detail_account_id: int | None = None
    reference_no: str | None = None
    description: str | None = None


def create_document(
    company_id: int, created_by_user_id: int, document_type_code: str, document_date: datetime.date,
    fields: DocumentHeaderFields,
) -> int:
    if document_type_code not in DOCUMENT_TYPE_CODES:
        raise ValueError("نوعِ سند نامعتبر است.")
    with new_session() as session:
        fiscal_year_id = _resolve_fiscal_year_id(session, company_id, document_date)
        next_no = (
            session.scalar(
                select(func.max(CommercialDocument.document_no)).where(
                    CommercialDocument.company_id == company_id, CommercialDocument.fiscal_year_id == fiscal_year_id,
                    CommercialDocument.document_type_code == document_type_code,
                )
            )
            or 0
        ) + 1
        doc = CommercialDocument(
            company_id=company_id, fiscal_year_id=fiscal_year_id, document_type_code=document_type_code,
            document_no=next_no, document_date=document_date, status_code="DRAFT",
            channel_code=fields.channel_code, counterparty_detail_account_id=fields.counterparty_detail_account_id,
            warehouse_id=fields.warehouse_id, price_list_id=fields.price_list_id, pos_session_id=fields.pos_session_id,
            source_document_id=fields.source_document_id, linked_exchange_document_id=fields.linked_exchange_document_id,
            currency_id=fields.currency_id, exchange_rate=fields.exchange_rate,
            requested_delivery_date=fields.requested_delivery_date,
            sales_rep_detail_account_id=fields.sales_rep_detail_account_id,
            cost_center_detail_account_id=fields.cost_center_detail_account_id,
            project_detail_account_id=fields.project_detail_account_id,
            reference_no=(fields.reference_no or None), description=(fields.description or None),
            created_by_user_id=created_by_user_id,
        )
        session.add(doc)
        session.commit()
        return doc.document_id


@dataclass
class LineFulfillment:
    line_id: int
    item_id: int
    uom_id: int
    quantity: decimal.Decimal
    invoiced_quantity: decimal.Decimal
    remaining_quantity: decimal.Decimal


def _invoiced_quantity(session, source_line_id: int) -> decimal.Decimal:
    """جمعِ مقدارِ ردیف‌هایِ فاکتورهایی که از این ردیفِ سفارش/پیش‌فاکتور
    ساخته شده‌اند (طبقِ source_line_id) — فاکتورهایِ لغوشده حساب نمی‌شوند
    (اثری ندارند، پس مانده را کم نمی‌کنند)."""
    return session.scalar(
        select(func.coalesce(func.sum(CommercialDocumentLine.quantity), 0))
        .select_from(CommercialDocumentLine)
        .join(CommercialDocument, CommercialDocument.document_id == CommercialDocumentLine.document_id)
        .where(CommercialDocumentLine.source_line_id == source_line_id, CommercialDocument.status_code != "CANCELLED")
    ) or _ZERO


def get_line_fulfillment(document_id: int, company_id: int) -> list[LineFulfillment]:
    """طبقِ درخواستِ صریح («مانده‌یِ هر سفارش را بتوان دید»): برایِ هر
    ردیفِ سفارش/پیش‌فاکتور، مقدارِ تاکنون‌فاکتورشده و مانده را برمی‌گرداند."""
    with new_session() as session:
        doc = session.get(CommercialDocument, document_id)
        if doc is None or doc.company_id != company_id:
            raise ValueError("سند نامعتبر است.")
        lines = session.scalars(
            select(CommercialDocumentLine).where(CommercialDocumentLine.document_id == document_id).order_by(CommercialDocumentLine.line_no)
        ).all()
        result = []
        for ln in lines:
            invoiced = _invoiced_quantity(session, ln.line_id)
            result.append(LineFulfillment(
                line_id=ln.line_id, item_id=ln.item_id, uom_id=ln.uom_id, quantity=ln.quantity,
                invoiced_quantity=invoiced, remaining_quantity=ln.quantity - invoiced,
            ))
        return result


def get_order_fulfillment_summary(document_id: int, company_id: int) -> tuple[decimal.Decimal, decimal.Decimal]:
    """(جمعِ مقدارِ سفارش‌شده، جمعِ مقدارِ تاکنون‌فاکتورشده) — نسخه‌یِ
    سبک‌ترِ get_line_fulfillment، برایِ نمایشِ خلاصه در لیستِ اسناد."""
    fulfillment = get_line_fulfillment(document_id, company_id)
    ordered_total = sum((f.quantity for f in fulfillment), _ZERO)
    invoiced_total = sum((f.invoiced_quantity for f in fulfillment), _ZERO)
    return ordered_total, invoiced_total


def convert_to_invoice(
    document_id: int, company_id: int, created_by_user_id: int, document_date: datetime.date,
    line_quantities: dict[int, decimal.Decimal] | None = None,
) -> int:
    """طبقِ درخواستِ صریح («تبدیلِ مرحله‌ای»): سفارش/پیش‌فاکتور می‌تواند
    بارها، هر بار برایِ بخشی از مقدار، به فاکتور تبدیل شود — نه فقط یک
    بارِ کاملِ همه‌یِ ردیف‌ها. اگر line_quantities داده نشود، هرچه از هر
    ردیف مانده (هنوز فاکتور نشده) باشد یک‌جا تبدیل می‌شود؛ در غیرِاین‌صورت
    فقط مقدارهایِ مشخص‌شده (نباید از مانده‌یِ همان ردیف بیشتر باشد)."""
    with new_session() as session:
        source = session.get(CommercialDocument, document_id)
        if source is None or source.company_id != company_id:
            raise ValueError("سند نامعتبر است.")
        target_type = _CONVERT_TO_INVOICE_TARGET.get(source.document_type_code)
        if target_type is None:
            raise ValueError("این نوعِ سند قابلِ‌تبدیل به فاکتور نیست.")
        if source.status_code in ("DRAFT", "CANCELLED"):
            raise ValueError("فقط سندِ تاییدشده/تصویب‌شده/ثبت‌شده قابلِ‌تبدیل به فاکتور است.")
        source_lines = session.scalars(
            select(CommercialDocumentLine).where(CommercialDocumentLine.document_id == document_id).order_by(CommercialDocumentLine.line_no)
        ).all()
        if not source_lines:
            raise ValueError("سند حداقل باید یک ردیف داشته باشد.")

        line_snapshots = []
        for ln in source_lines:
            remaining = ln.quantity - _invoiced_quantity(session, ln.line_id)
            if line_quantities is None:
                qty_this_time = remaining
            else:
                qty_this_time = line_quantities.get(ln.line_id, _ZERO)
                if qty_this_time < 0:
                    raise ValueError("مقدار نمی‌تواند منفی باشد.")
                if qty_this_time > remaining:
                    raise ValueError(f"مقدارِ درخواستی برایِ ردیفِ #{ln.line_no} از مانده ({remaining}) بیشتر است.")
            if qty_this_time <= 0:
                continue
            ratio = qty_this_time / ln.quantity
            line_snapshots.append({
                "item_id": ln.item_id, "uom_id": ln.uom_id, "quantity": qty_this_time, "quantity_base": qty_this_time,
                "unit_price": ln.unit_price, "discount_amount": _money(ln.discount_amount * ratio), "tax_percent": ln.tax_percent,
                "batch_id": ln.batch_id, "serial_id": ln.serial_id, "description": ln.description, "line_id": ln.line_id,
            })
        if not line_snapshots:
            raise ValueError("چیزی برایِ تبدیل به فاکتور باقی نمانده است.")

        header_fields = DocumentHeaderFields(
            counterparty_detail_account_id=source.counterparty_detail_account_id, currency_id=source.currency_id,
            warehouse_id=source.warehouse_id, channel_code=source.channel_code, price_list_id=source.price_list_id,
            source_document_id=source.document_id, exchange_rate=source.exchange_rate,
            sales_rep_detail_account_id=source.sales_rep_detail_account_id,
            cost_center_detail_account_id=source.cost_center_detail_account_id,
            project_detail_account_id=source.project_detail_account_id,
            reference_no=source.reference_no, description=source.description,
        )

    new_document_id = create_document(company_id, created_by_user_id, target_type, document_date, header_fields)
    for snap in line_snapshots:
        add_line(
            new_document_id, company_id, item_id=snap["item_id"], uom_id=snap["uom_id"], quantity=snap["quantity"],
            quantity_base=snap["quantity_base"], unit_price=snap["unit_price"], discount_amount=snap["discount_amount"],
            tax_percent=snap["tax_percent"], batch_id=snap["batch_id"], serial_id=snap["serial_id"],
            source_line_id=snap["line_id"], description=snap["description"],
        )
    return new_document_id


# طبقِ درخواستِ صریح («سفارشات در حال حاضر ویرایش نمیشه»): برخلافِ
# فاکتور/برگشت (که برایِ حفظِ صحتِ حسابداری، بعدِ تاییدشدن قفل می‌مانند)،
# سفارش/پیش‌فاکتور تا وقتی ثبتِ‌نهایی/لغو نشده صرفاً یک سندِ قصد است —
# می‌تواند حتی بعدِ تاییدشدن ویرایش شود.
_ORDER_EDITABLE_STATUSES = ("DRAFT", "CONFIRMED", "APPROVED")


def _get_editable_document(session, document_id: int, company_id: int) -> CommercialDocument:
    doc = session.get(CommercialDocument, document_id)
    if doc is None or doc.company_id != company_id:
        raise ValueError("سند نامعتبر است.")
    if doc.document_type_code in _ORDER_TYPES:
        if doc.status_code not in _ORDER_EDITABLE_STATUSES:
            raise ValueError("این سند دیگر ویرایش‌پذیر نیست.")
    elif doc.status_code != "DRAFT":
        raise ValueError("فقط سندِ پیش‌نویس قابلِ‌ویرایش است.")
    return doc


def update_document_header(document_id: int, company_id: int, document_date: datetime.date, fields: DocumentHeaderFields) -> None:
    with new_session() as session:
        doc = _get_editable_document(session, document_id, company_id)
        doc.document_date = document_date
        doc.fiscal_year_id = _resolve_fiscal_year_id(session, company_id, document_date)
        doc.counterparty_detail_account_id = fields.counterparty_detail_account_id
        doc.warehouse_id = fields.warehouse_id
        doc.channel_code = fields.channel_code
        doc.price_list_id = fields.price_list_id
        doc.sales_rep_detail_account_id = fields.sales_rep_detail_account_id
        doc.cost_center_detail_account_id = fields.cost_center_detail_account_id
        doc.project_detail_account_id = fields.project_detail_account_id
        doc.reference_no = fields.reference_no or None
        doc.description = fields.description or None
        session.commit()


def get_document(document_id: int, company_id: int) -> tuple[CommercialDocument, list[CommercialDocumentLine]]:
    with new_session() as session:
        doc = session.get(CommercialDocument, document_id)
        if doc is None or doc.company_id != company_id:
            raise ValueError("سند نامعتبر است.")
        lines = session.scalars(
            select(CommercialDocumentLine).where(CommercialDocumentLine.document_id == document_id).order_by(CommercialDocumentLine.line_no)
        ).all()
        return doc, list(lines)


def list_documents(company_id: int, document_type_code: str | None = None, status_code: str | None = None) -> list[CommercialDocument]:
    with new_session() as session:
        stmt = select(CommercialDocument).where(CommercialDocument.company_id == company_id)
        if document_type_code:
            stmt = stmt.where(CommercialDocument.document_type_code == document_type_code)
        if status_code:
            stmt = stmt.where(CommercialDocument.status_code == status_code)
        return list(session.scalars(stmt.order_by(CommercialDocument.document_id.desc())))


def _recompute_header_totals(session, document_id: int) -> None:
    lines = session.scalars(select(CommercialDocumentLine).where(CommercialDocumentLine.document_id == document_id)).all()
    subtotal = sum((_money(ln.quantity * ln.unit_price) for ln in lines), _ZERO)
    discount = sum((ln.discount_amount for ln in lines), _ZERO)
    tax = sum((ln.tax_amount for ln in lines), _ZERO)
    doc = session.get(CommercialDocument, document_id)
    doc.subtotal_amount = subtotal
    doc.discount_amount = discount
    doc.tax_amount = tax


# ---------------------------------------------------------------------
# ردیف‌ها
# ---------------------------------------------------------------------
def add_line(
    document_id: int, company_id: int, item_id: int, uom_id: int, quantity: decimal.Decimal,
    quantity_base: decimal.Decimal, unit_price: decimal.Decimal | None = None,
    discount_amount: decimal.Decimal = _ZERO, tax_percent: decimal.Decimal = _ZERO,
    batch_id: int | None = None, serial_id: int | None = None, source_line_id: int | None = None,
    description: str | None = None,
) -> int:
    if quantity <= 0 or quantity_base <= 0:
        raise ValueError("مقدار باید بزرگ‌تر از صفر باشد.")
    with new_session() as session:
        doc = _get_editable_document(session, document_id, company_id)
        if unit_price is None:
            resolved = pricing_service.resolve_price(
                company_id, doc.counterparty_detail_account_id, item_id, uom_id, quantity, doc.price_list_id,
                doc.document_type_code, doc.document_date,
            )
            unit_price = resolved.unit_price
            discount_amount = discount_amount + resolved.discount_amount
        # طبقِ رفعِ باگِ واقعی: مالیات باید رویِ مبلغِ *بعدِ تخفیف* محاسبه
        # شود (همان‌طور که ستون‌بندیِ خودِ جدولِ ردیف‌ها هم نشان می‌دهد:
        # «تخفیف» پیش از «درصدِ مالیات» می‌آید) — قبلاً رویِ جمعِ ناخالص
        # (quantity*unit_price) محاسبه می‌شد، بدونِ کسرِ تخفیف.
        net_amount = quantity * unit_price - discount_amount
        tax_amount = _money(net_amount * (tax_percent / 100)) if tax_percent and net_amount > 0 else _ZERO
        next_no = (
            session.scalar(select(func.max(CommercialDocumentLine.line_no)).where(CommercialDocumentLine.document_id == document_id)) or 0
        ) + 1
        line = CommercialDocumentLine(
            document_id=document_id, line_no=next_no, item_id=item_id, uom_id=uom_id, quantity=quantity,
            quantity_base=quantity_base, unit_price=unit_price, discount_amount=discount_amount,
            tax_percent=tax_percent, tax_amount=tax_amount, batch_id=batch_id, serial_id=serial_id,
            source_line_id=source_line_id, description=(description or None),
        )
        session.add(line)
        session.flush()
        _recompute_header_totals(session, document_id)
        session.commit()
        return line.line_id


def delete_line(line_id: int, document_id: int, company_id: int) -> None:
    with new_session() as session:
        _get_editable_document(session, document_id, company_id)
        # طبقِ صحتِ ردگیریِ تبدیل‌شدنِ سفارش به فاکتور: اگر این ردیف
        # قبلاً (کامل یا جزئی) در فاکتوری کپی شده (source_line_id)، حذفش
        # آن اثر را یتیم می‌کند — هم به خاطرِ FK (بدونِ ON DELETE) خطایِ
        # خام می‌داد، هم منطقاً اشتباه است.
        referencing_docs = select(CommercialDocumentLine.document_id).where(CommercialDocumentLine.source_line_id == line_id)
        still_referenced = session.scalar(
            select(CommercialDocument.document_id).where(
                CommercialDocument.document_id.in_(referencing_docs), CommercialDocument.status_code != "CANCELLED",
            )
        )
        if still_referenced is not None:
            raise ValueError("این ردیف قبلاً (به‌طور کامل یا جزئی) به فاکتور تبدیل شده و دیگر حذف نمی‌شود.")
        session.query(CommercialDocumentLine).filter(CommercialDocumentLine.line_id == line_id).delete()
        _recompute_header_totals(session, document_id)
        session.commit()


def delete_document(document_id: int, company_id: int) -> None:
    with new_session() as session:
        doc = session.get(CommercialDocument, document_id)
        if doc is None or doc.company_id != company_id:
            raise ValueError("سند نامعتبر است.")
        # DRAFT/CONFIRMED/APPROVED/CANCELLED هرگز stock_document_id/
        # journal_entry_id پر نمی‌کنند (فقط POSTED این دو را پر می‌کند) —
        # پس حذفِ مستقیمِ هرکدام از این چهار وضعیت همیشه بی‌خطر است.
        if doc.status_code == "POSTED":
            raise ValueError("سندِ ثبت‌شده هرگز حذف نمی‌شود — برایِ اصلاح، سندِ تازه‌ای ثبت کنید.")
        # طبقِ صحتِ ردگیریِ تبدیل‌شدنِ سفارش به فاکتور: اگر این سند (یا
        # یکی از ردیف‌هایش) مبدایِ فاکتوریِ دیگر است، حذفش آن پیوند را
        # یتیم می‌کند — هم به خاطرِ FK (بدونِ ON DELETE) خطایِ خام می‌داد.
        own_line_ids = select(CommercialDocumentLine.line_id).where(CommercialDocumentLine.document_id == document_id)
        still_referenced = session.scalar(
            select(CommercialDocument.document_id).where(
                (CommercialDocument.source_document_id == document_id)
                | (CommercialDocument.document_id.in_(
                    select(CommercialDocumentLine.document_id).where(CommercialDocumentLine.source_line_id.in_(own_line_ids))
                )),
                CommercialDocument.status_code != "CANCELLED",
            )
        )
        if still_referenced is not None:
            raise ValueError("این سند قبلاً (به‌طور کامل یا جزئی) به فاکتور تبدیل شده و دیگر حذف نمی‌شود.")
        # طبقِ رفعِ باگِ واقعی: سفارش/پیش‌فاکتورِ تاییدشده ممکن است حینِ
        # تایید یک قفلِ اعتباری (comm.credit_holds) ساخته باشد — قبلاً
        # حذف فقط برایِ DRAFT مجاز بود (پیش از هر تاییدی)، پس این حالت
        # هرگز رخ نمی‌داد؛ حالا که CONFIRMED/APPROVED هم حذف‌پذیرند، خودِ
        # قفل‌هایِ متعلق به همین سند هم باید حذف شوند، وگرنه FK خطایِ خام
        # می‌دهد.
        session.query(CreditHold).filter(CreditHold.related_document_id == document_id).delete()
        session.query(CommercialDocumentLine).filter(CommercialDocumentLine.document_id == document_id).delete()
        session.delete(doc)
        session.commit()


# ---------------------------------------------------------------------
# گردشِ کار
# ---------------------------------------------------------------------
def confirm_document(document_id: int, company_id: int, confirmed_by_user_id: int) -> None:
    with new_session() as session:
        doc = session.get(CommercialDocument, document_id)
        if doc is None or doc.company_id != company_id:
            raise ValueError("سند نامعتبر است.")
        if doc.status_code != "DRAFT":
            raise ValueError("فقط سندِ پیش‌نویس قابلِ‌تایید است.")
        lines = session.scalars(select(CommercialDocumentLine).where(CommercialDocumentLine.document_id == document_id)).all()
        if not lines:
            raise ValueError("سند حداقل باید یک ردیف داشته باشد.")
        doc.status_code = "CONFIRMED"
        document_type_code = doc.document_type_code
        counterparty_id = doc.counterparty_detail_account_id
        total_amount = doc.total_amount
        session.commit()

    if document_type_code == "SALES_ORDER":
        if credit_service.check_credit_exposure(company_id, counterparty_id, total_amount):
            credit_service.create_credit_hold(
                counterparty_id, f"عبور از سقفِ اعتبار در سفارشِ #{document_id}", confirmed_by_user_id,
                related_document_id=document_id,
            )


def approve_document(document_id: int, company_id: int) -> None:
    with new_session() as session:
        doc = session.get(CommercialDocument, document_id)
        if doc is None or doc.company_id != company_id:
            raise ValueError("سند نامعتبر است.")
        if doc.status_code != "CONFIRMED":
            raise ValueError("فقط سندِ تاییدشده قابلِ‌تصویب است.")
        open_hold = session.scalar(
            select(CreditHold).where(CreditHold.related_document_id == document_id, CreditHold.released_at.is_(None))
        )
        if open_hold is not None:
            raise ValueError("این سند قفلِ اعتباریِ بازِ حل‌نشده دارد — ابتدا آزادسازی کنید.")
        doc.status_code = "APPROVED"
        session.commit()


def cancel_document(document_id: int, company_id: int) -> None:
    with new_session() as session:
        doc = session.get(CommercialDocument, document_id)
        if doc is None or doc.company_id != company_id:
            raise ValueError("سند نامعتبر است.")
        if doc.status_code not in ("DRAFT", "CONFIRMED", "APPROVED"):
            raise ValueError("سندِ ثبت‌شده هرگز لغو نمی‌شود — برایِ اصلاح، سندِ تازه‌ای ثبت کنید.")
        doc.status_code = "CANCELLED"
        session.commit()


@dataclass
class PostResult:
    document_id: int
    stock_document_id: int | None
    journal_entry_id: int | None


def post_document(document_id: int, company_id: int, posted_by_user_id: int) -> PostResult:
    with new_session() as session:
        doc = session.get(CommercialDocument, document_id)
        if doc is None or doc.company_id != company_id:
            raise ValueError("سند نامعتبر است.")
        if doc.status_code == "POSTED":
            raise ValueError("این سند قبلاً ثبتِ نهایی شده است.")
        if doc.status_code not in ("CONFIRMED", "APPROVED"):
            raise ValueError("فقط سندِ تاییدشده قابلِ‌ثبتِ‌نهایی است.")

        document_type_code = doc.document_type_code

        if document_type_code in _ORDER_TYPES:
            # برایِ سفارش، POSTED فقط یعنی «قفل و ارسال‌شده» — بدونِ اثرِ
            # مالی/انبار (مرحلهٔ ۴، بخشِ ۲).
            doc.status_code = "POSTED"
            doc.posted_by_user_id = posted_by_user_id
            doc.posted_at = datetime.datetime.now()
            session.commit()
            return PostResult(document_id=document_id, stock_document_id=None, journal_entry_id=None)

        open_hold = session.scalar(
            select(CreditHold).where(CreditHold.related_document_id == document_id, CreditHold.released_at.is_(None))
        )
        if open_hold is not None:
            raise ValueError("این سند قفلِ اعتباریِ بازِ حل‌نشده دارد — ابتدا آزادسازی کنید.")

        lines = session.scalars(
            select(CommercialDocumentLine).where(CommercialDocumentLine.document_id == document_id).order_by(CommercialDocumentLine.line_no)
        ).all()
        if not lines:
            raise ValueError("سند حداقل باید یک ردیف داشته باشد.")

        warehouse_id = doc.warehouse_id
        counterparty_id = doc.counterparty_detail_account_id
        document_date = doc.document_date
        description = doc.description or f"سندِ بازرگانی #{doc.document_no}"
        sales_rep_id = doc.sales_rep_detail_account_id
        cost_center_id = doc.cost_center_detail_account_id
        project_id = doc.project_detail_account_id
        subtotal_amount = doc.subtotal_amount
        discount_amount = doc.discount_amount
        tax_amount = doc.tax_amount
        line_snapshots = [
            (ln.line_id, ln.item_id, ln.uom_id, ln.quantity, ln.quantity_base, ln.unit_price, ln.batch_id, ln.serial_id)
            for ln in lines
        ]

    # طبقِ رفعِ باگِ واقعی («برای حساب X انتخابِ گروه‌هایِ تفصیلیِ الزامی
    # فراموش شده است» حتی وقتی تفصیلیِ طرفِ‌حساب درست انتخاب شده بود):
    # اگر حسابِ نقش‌محورِ (دریافتنی/پرداختنی/درآمد/موجودی/...) این سند
    # یک بُعدِ الزامیِ اضافه (مثلاً مرکزِ هزینه/پروژه) هم داشته باشد،
    # ساختِ خودکارِ سندِ حسابداری قبلاً فقط تفصیلیِ طرفِ‌حساب را می‌فرستاد
    # و آن بُعدِ اضافه را هیچ‌وقت نمی‌فرستاد — دقیقاً هم‌الگو با باگِ حسابِ
    # پیش‌پرداختِ تنخواه که پیش‌تر رفع شد. حالا مرکزِ هزینه/پروژهٔ خودِ سند
    # (اگر در سرِسند انتخاب شده باشد) به همه‌یِ ردیف‌هایِ سندِ حسابداری
    # (این سند و سندِ انبارِ خودکارِ همراهش) فرستاده می‌شود.
    extra_dims: dict[int, int] = {}
    if cost_center_id is not None:
        extra_dims[dimensions_service.get_specialized_dimension_type_id(company_id, dimensions_service.COST_CENTER_CODE)] = cost_center_id
    if project_id is not None:
        extra_dims[dimensions_service.get_specialized_dimension_type_id(company_id, dimensions_service.PROJECT_CODE)] = project_id

    stock_document_type = _STOCK_DOC_TYPE_BY_TYPE[document_type_code]
    is_receipt_like = stock_document_type in ("RECEIPT", "RETURN_IN")
    header_fields = inv_documents_service.DocumentHeaderFields(
        destination_warehouse_id=warehouse_id if is_receipt_like else None,
        source_warehouse_id=warehouse_id if not is_receipt_like else None,
        counterparty_detail_account_id=counterparty_id,
        cost_center_detail_account_id=cost_center_id, project_detail_account_id=project_id,
        reference_no=f"COMM-{document_id}", description=description,
    )
    stock_document_id = inv_documents_service.create_stock_document(
        company_id, posted_by_user_id, stock_document_type, document_date, header_fields
    )
    for line_id, item_id, uom_id, quantity, quantity_base, unit_price, batch_id, serial_id in line_snapshots:
        # برایِ ISSUE، unit_cost=None می‌ماند تا موتورِ انبار از میانگینِ
        # موزونِ فعلی استفاده کند (قیمتِ فروش هرگز بهایِ تمام‌شده نیست).
        stock_unit_cost = None if stock_document_type == "ISSUE" else unit_price
        inv_line_id = inv_documents_service.add_line(
            stock_document_id, company_id,
            inv_documents_service.LineFields(
                item_id=item_id, uom_id=uom_id, quantity=quantity, quantity_base=quantity_base,
                batch_id=batch_id, unit_cost=stock_unit_cost,
            ),
        )
        with new_session() as session:
            comm_line = session.get(CommercialDocumentLine, line_id)
            comm_line.stock_document_line_id = inv_line_id
            session.commit()

    inv_documents_service.confirm_stock_document(stock_document_id, company_id)
    inv_post_result = inv_documents_service.post_stock_document(stock_document_id, company_id, posted_by_user_id)

    journal_entry_id = inv_post_result.journal_entry_id

    if document_type_code == "SALES_INVOICE":
        person_dim_type_id = dimensions_service.get_person_dimension_type_id(company_id)
        je_lines: list[je_service.LineInput] = []
        ar_account_id = inv_engine_service.get_account_mapping(company_id, "CUSTOMER_RECEIVABLE")
        if ar_account_id is None:
            raise ValueError("حسابِ «حساب‌هایِ دریافتنیِ مشتریان» هنوز در تنظیماتِ انبار مشخص نشده است.")
        total = _money(subtotal_amount - discount_amount + tax_amount)
        je_lines.append(
            je_service.LineInput(
                account_id=ar_account_id, description=description, debit=total, credit=_ZERO,
                details={person_dim_type_id: counterparty_id, **extra_dims},
            )
        )
        with new_session() as session:
            revenue_account_id = settings_service.resolve_role_account(session, company_id, "SALES_REVENUE")
            je_lines.append(
                je_service.LineInput(
                    account_id=revenue_account_id, description=description, debit=_ZERO, credit=subtotal_amount,
                    details=dict(extra_dims),
                )
            )
            if discount_amount > 0:
                discount_account_id = settings_service.resolve_role_account(session, company_id, "SALES_DISCOUNT")
                je_lines.append(
                    je_service.LineInput(
                        account_id=discount_account_id, description=description, debit=discount_amount, credit=_ZERO,
                        details=dict(extra_dims),
                    )
                )
            if tax_amount > 0:
                tax_account_id = settings_service.resolve_role_account(session, company_id, "SALES_TAX_PAYABLE")
                je_lines.append(
                    je_service.LineInput(
                        account_id=tax_account_id, description=description, debit=_ZERO, credit=tax_amount,
                        details=dict(extra_dims),
                    )
                )

        je_result = je_service.create_journal_entry(
            company_id, posted_by_user_id, document_date, description, je_lines, entry_type_code="COMMERCIAL"
        )
        journal_entry_id = je_result.journal_entry_id

        if sales_rep_id is not None:
            with new_session() as session:
                from peecha.db.models.commercial import SalesRepresentative

                rep = session.get(SalesRepresentative, sales_rep_id)
                rule_id = rep.default_commission_rule_id if rep is not None else None
            if rule_id is not None:
                for line_id, item_id, uom_id, quantity, quantity_base, unit_price, batch_id, serial_id in line_snapshots:
                    base_amount = _money(quantity * unit_price)
                    contracts_service.create_commission_entry_for_line(line_id, sales_rep_id, rule_id, base_amount)

    elif document_type_code == "SALES_RETURN":
        with new_session() as session:
            doc = session.get(CommercialDocument, document_id)
            source_document_id = doc.source_document_id
        if source_document_id is not None:
            contracts_service.reverse_commission_entries_for_document(source_document_id)

    with new_session() as session:
        doc = session.get(CommercialDocument, document_id)
        doc.stock_document_id = stock_document_id
        doc.journal_entry_id = journal_entry_id
        doc.status_code = "POSTED"
        doc.posted_by_user_id = posted_by_user_id
        doc.posted_at = datetime.datetime.now()
        session.commit()

    return PostResult(document_id=document_id, stock_document_id=stock_document_id, journal_entry_id=journal_entry_id)
