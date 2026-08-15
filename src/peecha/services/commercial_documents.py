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
    "SALES_ORDER", "SALES_INVOICE", "SALES_RETURN",
    "PURCHASE_ORDER", "PURCHASE_INVOICE", "PURCHASE_RETURN",
)
_ORDER_TYPES = ("SALES_ORDER", "PURCHASE_ORDER")
_STOCK_DOC_TYPE_BY_TYPE = {
    "PURCHASE_INVOICE": "RECEIPT",
    "SALES_INVOICE": "ISSUE",
    "SALES_RETURN": "RETURN_IN",
    "PURCHASE_RETURN": "RETURN_OUT",
}

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


def _get_draft_document(session, document_id: int, company_id: int) -> CommercialDocument:
    doc = session.get(CommercialDocument, document_id)
    if doc is None or doc.company_id != company_id:
        raise ValueError("سند نامعتبر است.")
    if doc.status_code != "DRAFT":
        raise ValueError("فقط سندِ پیش‌نویس قابلِ‌ویرایش است.")
    return doc


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
        doc = _get_draft_document(session, document_id, company_id)
        if unit_price is None:
            resolved = pricing_service.resolve_price(
                company_id, doc.counterparty_detail_account_id, item_id, uom_id, quantity, doc.price_list_id,
                doc.document_type_code, doc.document_date,
            )
            unit_price = resolved.unit_price
            discount_amount = discount_amount + resolved.discount_amount
        tax_amount = _money(quantity * unit_price * (tax_percent / 100)) if tax_percent else _ZERO
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
        _get_draft_document(session, document_id, company_id)
        session.query(CommercialDocumentLine).filter(CommercialDocumentLine.line_id == line_id).delete()
        _recompute_header_totals(session, document_id)
        session.commit()


def delete_document(document_id: int, company_id: int) -> None:
    with new_session() as session:
        doc = _get_draft_document(session, document_id, company_id)
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
        subtotal_amount = doc.subtotal_amount
        discount_amount = doc.discount_amount
        tax_amount = doc.tax_amount
        line_snapshots = [
            (ln.line_id, ln.item_id, ln.uom_id, ln.quantity, ln.quantity_base, ln.unit_price, ln.batch_id, ln.serial_id)
            for ln in lines
        ]

    stock_document_type = _STOCK_DOC_TYPE_BY_TYPE[document_type_code]
    is_receipt_like = stock_document_type in ("RECEIPT", "RETURN_IN")
    header_fields = inv_documents_service.DocumentHeaderFields(
        destination_warehouse_id=warehouse_id if is_receipt_like else None,
        source_warehouse_id=warehouse_id if not is_receipt_like else None,
        counterparty_detail_account_id=counterparty_id,
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
                details={person_dim_type_id: counterparty_id},
            )
        )
        with new_session() as session:
            revenue_account_id = settings_service.resolve_role_account(session, company_id, "SALES_REVENUE")
            je_lines.append(
                je_service.LineInput(account_id=revenue_account_id, description=description, debit=_ZERO, credit=subtotal_amount)
            )
            if discount_amount > 0:
                discount_account_id = settings_service.resolve_role_account(session, company_id, "SALES_DISCOUNT")
                je_lines.append(
                    je_service.LineInput(account_id=discount_account_id, description=description, debit=discount_amount, credit=_ZERO)
                )
            if tax_amount > 0:
                tax_account_id = settings_service.resolve_role_account(session, company_id, "SALES_TAX_PAYABLE")
                je_lines.append(
                    je_service.LineInput(account_id=tax_account_id, description=description, debit=_ZERO, credit=tax_amount)
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
