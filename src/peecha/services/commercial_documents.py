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
from peecha.db.models.accounting import DetailAccount, FiscalYear, JournalEntryLine
from peecha.db.models.commercial import CommercialDocument, CommercialDocumentLine, CreditHold, LandedCostAllocation
from peecha.db.models.inventory import Item, StockDocument
from peecha.services import commercial_contracts as contracts_service
from peecha.services import commercial_credit as credit_service
from peecha.services import commercial_pricing as pricing_service
from peecha.services import commercial_purchasing as purchasing_service
from peecha.services import commercial_settings as settings_service
from peecha.services import commercial_settlements as settlements_service
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import inventory_documents as inv_documents_service
from peecha.services import inventory_engine as inv_engine_service
from peecha.services import inventory_locations as locations_service
from peecha.services import journal_entries as je_service
from peecha.services import roles as roles_service

DOCUMENT_TYPE_CODES = (
    "SALES_ORDER", "SALES_PROFORMA", "SALES_INVOICE", "SALES_RETURN",
    "PURCHASE_ORDER", "PURCHASE_PROFORMA", "PURCHASE_INVOICE", "PURCHASE_RETURN",
    # طبقِ درخواستِ صریح («سیستمِ فاکتورِ امانی، هردو جهت»): امانیِ خروجی
    # (کالایِ خودمان نزدِ نماینده/مشتری تا زمانِ فروش) و امانیِ ورودی
    # (کالایِ تامین‌کننده نزدِ ما تا زمانِ مصرف/فروش) — هردو سندِ قصد/
    # ردیابی‌اند: مثلِ سفارش، هیچ اثرِ حسابداری‌ای در لحظه‌یِ ثبتِ خودشان
    # ندارند؛ برخلافِ سفارش، اثرِ انباریِ واقعی (جابه‌جاییِ فیزیکی) دارند.
    "CONSIGNMENT_OUT", "CONSIGNMENT_IN",
)
# سفارش/پیش‌فاکتور فقط سندِ قصد/پیشنهاد هستند — هرگز اثری در انبار یا
# حسابداری نمی‌گذارند؛ POSTED برایِ این دو یعنی صرفاً «قفل و ارسال‌شده».
_ORDER_TYPES = ("SALES_ORDER", "SALES_PROFORMA", "PURCHASE_ORDER", "PURCHASE_PROFORMA")
# طبقِ همان اصل: این دو POSTED یعنی «کالا فیزیکی جابه‌جا شد» (نه یک سندِ
# صرفاً کاغذی مثلِ سفارش) اما هنوز هیچ مالکیتی منتقل نشده — پس هیچ‌کدام
# سندِ حسابداری نمی‌سازند؛ _post_consignment_document جداگانه مدیریتشان
# می‌کند (نه _STOCK_DOC_TYPE_BY_TYPEِ زیر، چون امانیِ خروجی به دو انبار
# هم‌زمان نیاز دارد -- ناسازگار با ساختارِ تک‌انبارِ آن نگاشت).
_CONSIGNMENT_TYPES = ("CONSIGNMENT_OUT", "CONSIGNMENT_IN")

# طبقِ رفعِ باگِ واقعی («در دفترِ روزنامه شرحِ همه‌یِ فاکتورها یکسان و
# مبهم -- «سندِ بازرگانی #۱» -- است، نه مشخص که فاکتورِ فروش/خرید است و
# نه طرفِ‌حساب»): این جدول هم‌الگو با DOC_TYPE_TITLESِ خودِ UI
# (ui/screens/commercial_document.py) است -- در همین لایه هم لازم بود تا
# شرحِ پیش‌فرض (وقتی کاربر شرحِ دستی وارد نکرده) معنادار باشد.
_DOC_TYPE_TITLES = {
    "SALES_ORDER": "سفارشِ فروش",
    "SALES_PROFORMA": "پیش‌فاکتورِ فروش",
    "SALES_INVOICE": "فاکتورِ فروش",
    "SALES_RETURN": "برگشت از فروش",
    "PURCHASE_ORDER": "سفارشِ خرید",
    "PURCHASE_PROFORMA": "پیش‌فاکتورِ خرید",
    "PURCHASE_INVOICE": "فاکتورِ خرید",
    "PURCHASE_RETURN": "برگشت به تامین‌کننده",
    "CONSIGNMENT_OUT": "امانیِ خروجی",
    "CONSIGNMENT_IN": "امانیِ ورودی",
}


def _is_informal_tax_posting(company_id: int, tax_posting_mode: str | None) -> bool:
    """طبقِ درخواستِ صریح («دو نوعِ ثبت: رسمی/غیررسمی»): tax_posting_mode
    رویِ خودِ سند (اگر تنظیم شده) اولویت دارد؛ وگرنه پیش‌فرضِ سراسریِ
    شرکت (Feature Toggleِ INFORMAL_TAX_POSTING، پیش‌فرضِ خاموش = همان
    رفتارِ فعلی/رسمی) ملاک است."""
    if tax_posting_mode == "OFFICIAL":
        return False
    if tax_posting_mode == "INFORMAL":
        return True
    return settings_service.is_feature_enabled(company_id, "INFORMAL_TAX_POSTING")


def _default_document_description(document_type_code: str, document_no: int, counterparty_id: int | None) -> str:
    title = _DOC_TYPE_TITLES.get(document_type_code, "سندِ بازرگانی")
    counterparty_name = ""
    if counterparty_id is not None:
        label = dimensions_service.get_detail_account_label(counterparty_id)
        counterparty_name = label.split("—", 1)[-1].strip() if "—" in label else label
    text = f"{title} #{document_no}"
    return f"{text} {counterparty_name}" if counterparty_name else text


_STOCK_DOC_TYPE_BY_TYPE = {
    "PURCHASE_INVOICE": "RECEIPT",
    "SALES_INVOICE": "ISSUE",
    "SALES_RETURN": "RETURN_IN",
    "PURCHASE_RETURN": "RETURN_OUT",
}

# طبقِ کشفِ یک باگِ واقعیِ مسدودکننده در حینِ تستِ همین قابلیت: موتورِ
# انبار برایِ RETURN_IN/RETURN_OUT همیشه یک reason_code_id بر رویِ ردیف
# می‌خواهد (تاییدِ سندِ انبار با «انتخابِ دلیل الزامی است» رد می‌شود)، ولی
# فرمِ سندِ بازرگانی (برگشت از خرید/فروش) هیچ فیلدی برایِ انتخابِ آن ندارد
# -- پس تا پیش از این، ثبتِ نهاییِ هر برگشتِ بازرگانی‌ای (چه رسمی چه
# غیررسمی) شکست می‌خورد. یک دلیلِ عمومیِ خودکار (به‌ازایِ هر شرکت، یک‌بار
# ساخته می‌شود) این‌جا استفاده می‌شود تا برگشت‌ها قابلِ‌ثبت شوند؛ انتخابِ
# دستیِ دلیل‌هایِ خاص‌تر (کالایِ معیوب/اضافی/...) یک نیازِ UIِ جداگانه است.
_AUTO_RETURN_REASON_CODE = "COMM-RETURN"


def _ensure_return_reason_code(company_id: int, stock_document_type: str) -> int:
    for row in inv_documents_service.list_reason_codes(company_id, stock_document_type, active_only=False):
        if row.code == _AUTO_RETURN_REASON_CODE:
            return row.reason_code_id
    return inv_documents_service.create_reason_code(
        company_id, stock_document_type, _AUTO_RETURN_REASON_CODE, "برگشتِ سندِ بازرگانی"
    )
# طبقِ درخواستِ صریح («سفارش/پیش‌فاکتور باید بتواند به فاکتور تبدیل
# شود»): مقصدِ تبدیل برایِ هر نوعِ سندِ غیرِمالی. امانیِ خروجی/ورودی هم
# طبقِ همین درخواست («تسویه‌یِ امانی یعنی تبدیل به فاکتورِ واقعی») به
# همین مکانیزمِ ازپیش‌موجودِ تبدیلِ مرحله‌ای/جزئی وصل می‌شوند.
_CONVERT_TO_INVOICE_TARGET = {
    "SALES_ORDER": "SALES_INVOICE",
    "SALES_PROFORMA": "SALES_INVOICE",
    "PURCHASE_ORDER": "PURCHASE_INVOICE",
    "PURCHASE_PROFORMA": "PURCHASE_INVOICE",
    "CONSIGNMENT_OUT": "SALES_INVOICE",
    "CONSIGNMENT_IN": "PURCHASE_INVOICE",
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


def is_per_line_warehouse_enabled(company_id: int) -> bool:
    """طبقِ درخواستِ صریح («انبار در سطرِ کالا، اختیاری در تنظیمات»):
    وقتی روشن باشد، فرم اجازه می‌دهد هر ردیف انبارِ خودش را جدا از هدر
    انتخاب کند."""
    return settings_service.is_feature_enabled(company_id, "PER_LINE_WAREHOUSE")


def _account_requires_dimension(account_id: int, dimension_type_id: int) -> bool:
    required = dimensions_service.get_required_dimensions_for_account(account_id)
    return any(r.dimension_type_id == dimension_type_id for r in required)


def _role_line_amounts_by_item(
    line_snapshots: list[tuple], item_detail_account_by_item_id: dict[int, int], amount_of,
) -> dict[int, decimal.Decimal]:
    """جمعِ مبلغِ یک نقش (درآمد/تخفیف/مالیات) به‌تفکیکِ تفصیلیِ کالایِ هر
    ردیفِ فاکتور — طبقِ رفعِ باگِ واقعی («کالا» روی حسابِ درآمد الزامی شده
    ولی ساختِ خودکارِ سند یک ردیفِ جمعیِ تک‌مبلغ می‌سازد که نمی‌تواند
    هم‌زمان تفصیلیِ چند کالایِ مختلف را حمل کند)."""
    amounts: dict[int, decimal.Decimal] = {}
    for snapshot in line_snapshots:
        item_id = snapshot[1]
        detail_account_id = item_detail_account_by_item_id.get(item_id)
        if detail_account_id is None:
            continue
        amount = amount_of(snapshot)
        if amount <= 0:
            continue
        amounts[detail_account_id] = amounts.get(detail_account_id, _ZERO) + amount
    return amounts


def _build_role_je_lines(
    account_id: int, description: str, extra_dims: dict[int, int], total_amount: decimal.Decimal, is_debit: bool,
    item_dim_type_id: int, amounts_by_item_detail_account: dict[int, decimal.Decimal],
    fixed_detail: tuple[int, int] | None = None,
) -> list["je_service.LineInput"]:
    """ردیفِ حسابداریِ یک نقش را می‌سازد — اگر معینِ آن نقش «کالا» را هم
    الزامی کرده باشد، به‌جایِ یک ردیفِ جمعی، به‌ازایِ هر کالا یک ردیفِ
    جداگانه با تفصیلیِ همان کالا می‌سازد (وگرنه رفتارِ قبلی: یک ردیفِ جمعی).
    طبقِ درخواستِ صریح («برایِ فاکتورِ فروش هم تفصیلیِ ثابت برایِ مالیات،
    مثلِ فاکتورِ خرید»): اگر این نقش یک تفصیلیِ ثابت داشته باشد (مثلاً
    یک تفصیلیِ اشخاصِ ثابت برایِ حسابِ مالياتِ فروش)، این‌جا با پایین‌ترین
    اولویت (extra_dims رویش override می‌شود) اضافه می‌شود."""
    base_details: dict[int, int] = {}
    if fixed_detail is not None:
        base_details[fixed_detail[0]] = fixed_detail[1]
    base_details.update(extra_dims)
    if not _account_requires_dimension(account_id, item_dim_type_id):
        return [
            je_service.LineInput(
                account_id=account_id, description=description,
                debit=total_amount if is_debit else _ZERO, credit=_ZERO if is_debit else total_amount,
                details=dict(base_details),
            )
        ]
    lines = []
    for item_detail_account_id, amount in amounts_by_item_detail_account.items():
        details = {**base_details, item_dim_type_id: item_detail_account_id}
        lines.append(
            je_service.LineInput(
                account_id=account_id, description=description,
                debit=amount if is_debit else _ZERO, credit=_ZERO if is_debit else amount,
                details=details,
            )
        )
    return lines

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
    # فقط برایِ CONSIGNMENT_OUT -- انبارِ مقصد/محلِ‌نگه‌داریِ کالایِ امانی
    # نزدِ طرفِ‌حساب.
    consignment_warehouse_id: int | None = None
    channel_code: str | None = None
    price_list_id: int | None = None
    pos_session_id: int | None = None
    source_document_id: int | None = None
    linked_exchange_document_id: int | None = None
    exchange_rate: decimal.Decimal = decimal.Decimal(1)
    requested_delivery_date: datetime.date | None = None
    # None یعنی «خودکار از رویِ payment_term_days طرفِ‌حساب محاسبه شود»
    # (فقط برایِ SALES_INVOICE/PURCHASE_INVOICE) -- برایِ تنظیمِ دستی،
    # مقداری غیرِ None بدهید.
    due_date: datetime.date | None = None
    sales_rep_detail_account_id: int | None = None
    cost_center_detail_account_id: int | None = None
    project_detail_account_id: int | None = None
    reference_no: str | None = None
    description: str | None = None
    # طبقِ درخواستِ صریح («دو نوعِ ثبت: رسمی/غیررسمی»): None یعنی از
    # پیش‌فرضِ سراسریِ شرکت پیروی کن؛ "OFFICIAL"/"INFORMAL" یعنی override
    # رویِ همین سند.
    tax_posting_mode: str | None = None


def create_document(
    company_id: int, created_by_user_id: int, document_type_code: str, document_date: datetime.date,
    fields: DocumentHeaderFields,
) -> int:
    if document_type_code not in DOCUMENT_TYPE_CODES:
        raise ValueError("نوعِ سند نامعتبر است.")
    if fields.tax_posting_mode is not None and fields.tax_posting_mode not in ("OFFICIAL", "INFORMAL"):
        raise ValueError("نوعِ ثبتِ سند نامعتبر است.")
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
        due_date = fields.due_date
        if due_date is None:
            due_date = settlements_service.compute_due_date(
                company_id, document_type_code, fields.counterparty_detail_account_id, document_date,
            )
        doc = CommercialDocument(
            company_id=company_id, fiscal_year_id=fiscal_year_id, document_type_code=document_type_code,
            document_no=next_no, document_date=document_date, status_code="DRAFT",
            channel_code=fields.channel_code, counterparty_detail_account_id=fields.counterparty_detail_account_id,
            warehouse_id=fields.warehouse_id, consignment_warehouse_id=fields.consignment_warehouse_id,
            price_list_id=fields.price_list_id, pos_session_id=fields.pos_session_id,
            source_document_id=fields.source_document_id, linked_exchange_document_id=fields.linked_exchange_document_id,
            currency_id=fields.currency_id, exchange_rate=fields.exchange_rate,
            requested_delivery_date=fields.requested_delivery_date, due_date=due_date,
            sales_rep_detail_account_id=fields.sales_rep_detail_account_id,
            cost_center_detail_account_id=fields.cost_center_detail_account_id,
            project_detail_account_id=fields.project_detail_account_id,
            reference_no=(fields.reference_no or None), description=(fields.description or None),
            tax_posting_mode=fields.tax_posting_mode,
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
                "unit_price": ln.unit_price, "discount_amount": _money(ln.discount_amount * ratio),
                "discount_percent": ln.discount_percent, "tax_percent": ln.tax_percent,
                "batch_id": ln.batch_id, "serial_id": ln.serial_id, "description": ln.description, "line_id": ln.line_id,
                "warehouse_id": ln.warehouse_id,
            })
        if not line_snapshots:
            raise ValueError("چیزی برایِ تبدیل به فاکتور باقی نمانده است.")

        # طبقِ اصلِ فاکتورِ امانیِ خروجی: کالا فیزیکی نزدِ طرفِ‌حساب است
        # (انبارِ consignment_warehouse_id)، نه انبارِ اصلیِ شرکت -- پس
        # فاکتورِ فروشِ حاصل از تسویه باید دقیقاً از همان انبار کسر کند.
        invoice_warehouse_id = (
            source.consignment_warehouse_id if source.document_type_code == "CONSIGNMENT_OUT" else source.warehouse_id
        )
        header_fields = DocumentHeaderFields(
            counterparty_detail_account_id=source.counterparty_detail_account_id, currency_id=source.currency_id,
            warehouse_id=invoice_warehouse_id, channel_code=source.channel_code, price_list_id=source.price_list_id,
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
            discount_percent=snap["discount_percent"], tax_percent=snap["tax_percent"], batch_id=snap["batch_id"],
            serial_id=snap["serial_id"], source_line_id=snap["line_id"], description=snap["description"],
            warehouse_id=snap["warehouse_id"],
        )
    return new_document_id


def can_correct_posted_document(company_id: int, correcting_user_id: int) -> bool:
    """طبقِ درخواستِ صریح: فقط برایِ نمایش/پنهان‌کردنِ دکمه‌یِ «اصلاح» در
    UI -- خودِ start_invoice_correction هم دوباره همین دو شرط را
    اعتبارسنجی می‌کند."""
    return (
        roles_service.is_manager(correcting_user_id, company_id)
        and settings_service.is_feature_enabled(company_id, "ALLOW_EDIT_POSTED_INVOICE")
    )


def describe_correction_ineligibility(company_id: int, correcting_user_id: int) -> str:
    """طبقِ گزارشِ صریح («دکمه‌یِ اصلاح غیرِفعال است ولی معلوم نیست چرا»):
    برخلافِ can_correct_posted_document (که فقط True/False می‌دهد)، این
    تابع دقیقاً می‌گوید کدام‌یک از دو شرط برقرار نیست -- برایِ نمایش در
    Tooltipِ دکمه، نه برایِ اعتبارسنجیِ خودِ عملیات."""
    reasons = []
    if not roles_service.is_manager(correcting_user_id, company_id):
        reasons.append("شما نقشِ مدیر (ادمین/سوپروایزر) ندارید -- در تنظیماتِ سیستم، تبِ «نقش‌ها و دسترسی‌ها»، نقشی با این عنوان به کاربرِ خودتان بدهید")
    if not settings_service.is_feature_enabled(company_id, "ALLOW_EDIT_POSTED_INVOICE"):
        reasons.append("تنظیمِ «اجازه‌یِ اصلاحِ فاکتورِ ثبت‌شده» در تنظیماتِ بازرگانی، تبِ «قابلیت‌هایِ فعال»، خاموش است")
    return "؛ و همچنین ".join(reasons)


def start_invoice_correction(document_id: int, company_id: int, correcting_user_id: int) -> int:
    """طبقِ درخواستِ صریح («مدیر بتواند فاکتورِ ثبت‌شده را اصلاح کند، بدونِ
    اینکه سند با تاریخِ عقب‌دار برگردد») و بازخوردِ بعدی («اصلاحِ فاکتوری
    که آخرین حرکتِ انبار نیست هم فکری بشود»): این تابع هیچ اثرِ مالی/
    انباری فوری ایجاد نمی‌کند -- فقط یک فاکتورِ *پیش‌نویسِ* تازه (کپیِ
    کاملِ سرِسند/ردیف‌ها، دیگر با تاریخِ *امروز*، با رفرنسِ صریح به فاکتورِ
    اصلی) می‌سازد که از همینِ فرمِ عادیِ فاکتور قابلِ‌ویرایش است. فاکتورِ
    اصلی هم‌چنان POSTED می‌ماند (و اثرش دست‌نخورده) تا وقتی همین پیش‌نویس
    واقعاً ثبتِ‌نهایی شود -- محاسبه/برگشت‌زدنِ واقعی در همان لحظه، توسطِ
    post_invoice_correction، انجام می‌شود (نه این‌جا)، چون فقط آن‌جاست که
    مقدار/بهایِ *نهاییِ* اصلاح‌شده معلوم است."""
    if not roles_service.is_manager(correcting_user_id, company_id):
        raise ValueError("فقط مدیر (نقشِ سوپروایزر/ادمین) اجازه‌یِ اصلاحِ فاکتورِ ثبت‌شده را دارد.")
    if not settings_service.is_feature_enabled(company_id, "ALLOW_EDIT_POSTED_INVOICE"):
        raise ValueError("اصلاحِ فاکتورِ ثبت‌شده در تنظیماتِ این شرکت مجاز نشده است.")

    with new_session() as session:
        original = session.get(CommercialDocument, document_id)
        if original is None or original.company_id != company_id:
            raise ValueError("سند نامعتبر است.")
        if original.status_code != "POSTED":
            raise ValueError("فقط سندِ ثبتِ‌نهایی‌شده قابلِ‌اصلاح است.")
        if original.document_type_code not in ("SALES_INVOICE", "PURCHASE_INVOICE"):
            raise ValueError("اصلاح فقط برایِ فاکتورِ خرید/فروش پشتیبانی می‌شود.")
        if original.corrected_by_document_id is not None:
            raise ValueError("برایِ این سند از قبل یک اصلاح در جریان است یا قبلاً اصلاح شده است.")

        lines = session.scalars(
            select(CommercialDocumentLine).where(CommercialDocumentLine.document_id == document_id).order_by(CommercialDocumentLine.line_no)
        ).all()
        line_snapshots = [
            {
                "item_id": ln.item_id, "uom_id": ln.uom_id, "quantity": ln.quantity, "quantity_base": ln.quantity_base,
                "unit_price": ln.unit_price, "discount_amount": ln.discount_amount, "discount_percent": ln.discount_percent,
                "tax_percent": ln.tax_percent, "batch_id": ln.batch_id, "serial_id": ln.serial_id,
                "description": ln.description, "warehouse_id": ln.warehouse_id,
            }
            for ln in lines
        ]
        header_fields = DocumentHeaderFields(
            counterparty_detail_account_id=original.counterparty_detail_account_id, currency_id=original.currency_id,
            warehouse_id=original.warehouse_id, channel_code=original.channel_code, price_list_id=original.price_list_id,
            exchange_rate=original.exchange_rate,
            # موعدِ تسویه‌یِ اصلی عیناً منتقل می‌شود (نه بازمحاسبه) -- اگر
            # کاربر آن را دستی تغییر داده بود، اصلاح نباید بی‌سروصدا
            # نادیده‌اش بگیرد.
            due_date=original.due_date,
            sales_rep_detail_account_id=original.sales_rep_detail_account_id,
            cost_center_detail_account_id=original.cost_center_detail_account_id,
            project_detail_account_id=original.project_detail_account_id,
            reference_no=original.reference_no, description=original.description,
        )
        original_type = original.document_type_code

    new_document_id = create_document(company_id, correcting_user_id, original_type, datetime.date.today(), header_fields)
    for snap in line_snapshots:
        add_line(
            new_document_id, company_id, item_id=snap["item_id"], uom_id=snap["uom_id"], quantity=snap["quantity"],
            quantity_base=snap["quantity_base"], unit_price=snap["unit_price"], discount_amount=snap["discount_amount"],
            discount_percent=snap["discount_percent"], tax_percent=snap["tax_percent"], batch_id=snap["batch_id"],
            serial_id=snap["serial_id"], description=snap["description"], warehouse_id=snap["warehouse_id"],
        )

    with new_session() as session:
        original = session.get(CommercialDocument, document_id)
        # طبقِ درخواستِ صریح: original هنوز POSTED می‌ماند -- فقط
        # corrected_by_document_id به‌عنوانِ قفلِ «اصلاحِ دیگری در جریان
        # است» تنظیم می‌شود؛ وضعیتِ نهاییِ CORRECTED را
        # post_invoice_correction، بعدِ ثبتِ واقعیِ همین پیش‌نویس، تنظیم
        # می‌کند.
        original.corrected_by_document_id = new_document_id
        new_doc = session.get(CommercialDocument, new_document_id)
        new_doc.corrects_document_id = document_id
        session.commit()

    return new_document_id


def post_invoice_correction(document_id: int, company_id: int, posted_by_user_id: int) -> PostResult:
    """طبقِ بازخوردِ صریح («اگر فاکتور اصلاح بشه ولی از تاریخِ آن تا الان
    حرکتِ دیگری رویِ همان کالا رخ داده باشد، برگشت‌زدنِ کامل سودِ آن کالا
    را به‌هم می‌ریزد»): به‌جایِ برگشت‌زدنِ کاملِ اثرِ انبارِ سندِ اصلی (که
    فقط وقتی امن است که آن سند هنوز آخرین حرکتِ انبار باشد -- محدودیتِ
    reverse_stock_document)، این تابع سندِ اصلی را دست‌نخورده می‌گذارد و
    فقط *تفاوتِ* مقدار/بها بینِ فاکتورِ اصلی و همین پیش‌نویسِ اصلاح‌شده را،
    با تاریخِ امروز، ثبت می‌کند -- دقیقاً مثلِ یک فروش/خریدِ کوچکِ تازه.
    وقتی از فاکتورِ اصلی تا امروز هیچ حرکتِ دیگری رویِ آن کالا نبوده، این
    روش دقیقاً همان نتیجه‌یِ برگشتِ کامل را می‌دهد؛ وقتی بوده، سهمِ اصلی
    (با بهایِ تاریخیِ خودش) دست‌نخورده و صادقانه می‌ماند و فقط تفاوت با
    قیمتِ امروز ثبت می‌شود -- پس هرگز به «آخرین حرکت بودن» نیاز ندارد.

    سمتِ بازرگانیِ فاکتورِ فروش (دریافتنی/درآمد/تخفیف/مالیات) همیشه به‌طورِ
    کامل برگشت‌وتازه‌سازی می‌شود -- آن بخش هیچ ارتباطی به انبار/قیمت‌گذاری
    ندارد، پس همیشه ۱۰۰٪ امن است، فارغ از این‌که سند آخرین حرکت باشد یا
    نه."""
    with new_session() as session:
        draft = session.get(CommercialDocument, document_id)
        if draft is None or draft.company_id != company_id:
            raise ValueError("سند نامعتبر است.")
        if draft.corrects_document_id is None:
            raise ValueError("این سند یک پیش‌نویسِ اصلاحی نیست.")
        if draft.status_code == "POSTED":
            raise ValueError("این سند قبلاً ثبتِ نهایی شده است.")
        if draft.status_code not in ("CONFIRMED", "APPROVED"):
            raise ValueError("فقط سندِ تاییدشده قابلِ‌ثبتِ‌نهایی است.")
        original = session.get(CommercialDocument, draft.corrects_document_id)
        if original is None:
            raise ValueError("سندِ اصلیِ این اصلاح یافت نشد.")

        original_lines = session.scalars(
            select(CommercialDocumentLine).where(CommercialDocumentLine.document_id == original.document_id)
        ).all()
        draft_lines = session.scalars(
            select(CommercialDocumentLine).where(CommercialDocumentLine.document_id == document_id).order_by(CommercialDocumentLine.line_no)
        ).all()
        if not draft_lines:
            raise ValueError("سند حداقل باید یک ردیف داشته باشد.")

        document_type_code = draft.document_type_code
        warehouse_id = draft.warehouse_id
        counterparty_id = draft.counterparty_detail_account_id
        document_date = draft.document_date
        description = draft.description or _default_document_description(document_type_code, draft.document_no, counterparty_id)
        sales_rep_id = draft.sales_rep_detail_account_id
        cost_center_id = draft.cost_center_detail_account_id
        project_id = draft.project_detail_account_id
        subtotal_amount = draft.subtotal_amount
        discount_amount = draft.discount_amount
        tax_amount = draft.tax_amount
        is_informal_tax = _is_informal_tax_posting(company_id, draft.tax_posting_mode)
        original_journal_entry_id = original.journal_entry_id
        original_stock_document_id = original.stock_document_id
        original_document_no = original.document_no

        def _aggregate_by_item(lines_):
            agg: dict[int, dict] = {}
            for ln in lines_:
                bucket = agg.setdefault(
                    ln.item_id,
                    {"quantity_base": _ZERO, "net_value": _ZERO, "tax_amount": _ZERO, "warehouse_id": ln.warehouse_id},
                )
                bucket["quantity_base"] += ln.quantity_base
                bucket["net_value"] += _money(ln.quantity * ln.unit_price - ln.discount_amount)
                bucket["tax_amount"] += ln.tax_amount
            return agg

        original_by_item = _aggregate_by_item(original_lines)
        draft_by_item = _aggregate_by_item(draft_lines)
        all_item_ids = set(original_by_item) | set(draft_by_item)
        line_snapshots = [
            (ln.line_id, ln.item_id, ln.uom_id, ln.quantity, ln.quantity_base, ln.unit_price, ln.batch_id,
             ln.serial_id, ln.discount_amount, ln.tax_amount, ln.warehouse_id)
            for ln in draft_lines
        ]

    extra_dims: dict[int, int] = {}
    if cost_center_id is not None:
        extra_dims[dimensions_service.get_specialized_dimension_type_id(company_id, dimensions_service.COST_CENTER_CODE)] = cost_center_id
    if project_id is not None:
        extra_dims[dimensions_service.get_specialized_dimension_type_id(company_id, dimensions_service.PROJECT_CODE)] = project_id
    if warehouse_id is not None:
        warehouse_row = locations_service.get_warehouse(warehouse_id, company_id)
        if warehouse_row is not None and warehouse_row.fields.profit_center_detail_account_id is not None:
            extra_dims[dimensions_service.get_specialized_dimension_type_id(company_id, dimensions_service.PROFIT_CENTER_CODE)] = (
                warehouse_row.fields.profit_center_detail_account_id
            )

    def _role_account(role_key: str) -> int:
        account_id = inv_engine_service.get_account_mapping(company_id, role_key)
        if account_id is None:
            raise ValueError(f"حسابِ «{inv_engine_service.MAPPING_LABELS.get(role_key, role_key)}» هنوز در تنظیماتِ انبار مشخص نشده است.")
        return account_id

    stock_document_id: int | None = None
    journal_entry_id: int | None = None
    zero = decimal.Decimal(0)

    if document_type_code == "SALES_INVOICE":
        # طبقِ رفعِ باگِ واقعی («اصلاحِ فاکتوری که شاملِ کالایِ FIFO است،
        # نیمه‌کاره سندِ حسابداری را برگشت می‌زند/می‌سازد و بعد با خطا
        # متوقف می‌شود»): سمتِ انبار (که ممکن است روی یک لبه‌یِ نادر خطا
        # بدهد -- مثلاً سابقه‌یِ مصرفِ FIFOِ ناکافی) قبل از هرگونه
        # برگشت‌زدن/ساختنِ سندِ حسابداری اجرا می‌شود -- تا اگر شکست خورد،
        # هیچ اثری در حسابداری باقی نماند.
        adj_je_lines: list[je_service.LineInput] = []
        for item_id in all_item_ids:
            old_qty = original_by_item.get(item_id, {}).get("quantity_base", zero)
            new_qty = draft_by_item.get(item_id, {}).get("quantity_base", zero)
            delta = new_qty - old_qty
            if delta == 0:
                continue
            effective_warehouse_id = (draft_by_item.get(item_id) or original_by_item.get(item_id))["warehouse_id"] or warehouse_id
            in_unit_cost = None
            if delta < 0 and inv_engine_service.get_effective_costing_method(item_id, company_id) == "FIFO":
                # طبقِ طراحی: FIFO میانگینی برایِ «بازگرداندنِ خنثی» ندارد --
                # بهایِ صادقانه‌یِ همان واحدهایی که در همین فاکتورِ اصلی
                # واقعاً مصرف شده بودند از رویِ خودِ Ledger خوانده می‌شود.
                in_unit_cost = inv_engine_service.get_recent_consumption_cost(
                    original_stock_document_id, item_id, -delta
                )
            result = inv_engine_service.adjust_stock_quantity(
                item_id, effective_warehouse_id, None, company_id, delta, posted_by_user_id,
                reference_no=f"CORR-{document_id}",
                description=f"اصلاحِ مقدارِ فاکتورِ فروشِ شماره‌ی {original_document_no}",
                in_unit_cost=in_unit_cost,
            )
            if stock_document_id is None:
                stock_document_id = result.stock_document_id
            cogs_account_id = _role_account("COGS")
            inventory_account_id = _role_account("INVENTORY_ASSET")
            if result.direction == "OUT":
                adj_je_lines.append(je_service.LineInput(account_id=cogs_account_id, description=description, debit=result.amount, credit=_ZERO))
                adj_je_lines.append(je_service.LineInput(account_id=inventory_account_id, description=description, debit=_ZERO, credit=result.amount))
            else:
                adj_je_lines.append(je_service.LineInput(account_id=inventory_account_id, description=description, debit=result.amount, credit=_ZERO))
                adj_je_lines.append(je_service.LineInput(account_id=cogs_account_id, description=description, debit=_ZERO, credit=result.amount))

        if original_journal_entry_id is not None:
            je_service.reverse_journal_entry(original_journal_entry_id, company_id, posted_by_user_id)
        journal_entry_id = _build_sales_invoice_commercial_je(
            company_id, posted_by_user_id, document_date, description, counterparty_id, extra_dims,
            subtotal_amount, discount_amount, tax_amount, sales_rep_id, line_snapshots,
            is_informal_tax=is_informal_tax,
        )

        if adj_je_lines:
            adj_result = je_service.create_journal_entry(
                company_id, posted_by_user_id, document_date, description, adj_je_lines, entry_type_code="COMMERCIAL",
            )
            if stock_document_id is not None:
                with new_session() as session:
                    session.get(StockDocument, stock_document_id).journal_entry_id = adj_result.journal_entry_id
                    session.commit()

    elif document_type_code == "PURCHASE_INVOICE":
        adj_je_lines = []
        for item_id in all_item_ids:
            old = original_by_item.get(item_id)
            new = draft_by_item.get(item_id)
            old_qty = old["quantity_base"] if old else zero
            new_qty = new["quantity_base"] if new else zero
            delta = new_qty - old_qty
            effective_warehouse_id = (new or old)["warehouse_id"] or warehouse_id
            old_unit_cost = (old["net_value"] / old_qty) if old and old_qty else zero
            new_unit_cost = (new["net_value"] / new_qty) if new and new_qty else old_unit_cost
            old_tax = old["tax_amount"] if old else zero
            new_tax = new["tax_amount"] if new else zero

            if delta != 0:
                result = inv_engine_service.adjust_stock_quantity(
                    item_id, effective_warehouse_id, None, company_id, -delta, posted_by_user_id,
                    reference_no=f"CORR-{document_id}",
                    description=f"اصلاحِ مقدارِ فاکتورِ خریدِ شماره‌ی {original_document_no}",
                    in_unit_cost=new_unit_cost if delta > 0 else None,
                )
                if stock_document_id is None:
                    stock_document_id = result.stock_document_id
                inventory_account_id = _role_account("INVENTORY_ASSET")
                payable_account_id = _role_account("SUPPLIER_PAYABLE")
                if result.direction == "IN":
                    adj_je_lines.append(je_service.LineInput(account_id=inventory_account_id, description=description, debit=result.amount, credit=_ZERO))
                    adj_je_lines.append(je_service.LineInput(account_id=payable_account_id, description=description, debit=_ZERO, credit=result.amount))
                else:
                    adj_je_lines.append(je_service.LineInput(account_id=payable_account_id, description=description, debit=result.amount, credit=_ZERO))
                    adj_je_lines.append(je_service.LineInput(account_id=inventory_account_id, description=description, debit=_ZERO, credit=result.amount))
            elif old_unit_cost != new_unit_cost and old_qty > 0:
                if inv_engine_service.get_effective_costing_method(item_id, company_id) == "FIFO":
                    cost_result = inv_engine_service.apply_purchase_cost_correction_fifo(
                        original_stock_document_id, item_id, new_unit_cost - old_unit_cost,
                    )
                else:
                    cost_result = inv_engine_service.apply_purchase_cost_correction(
                        item_id, effective_warehouse_id, None, company_id, old_qty, new_unit_cost - old_unit_cost,
                    )
                total = cost_result.inventory_value_delta + cost_result.variance_value_delta
                inventory_account_id = _role_account("INVENTORY_ASSET")
                variance_account_id = _role_account("INVENTORY_COST_VARIANCE")
                payable_account_id = _role_account("SUPPLIER_PAYABLE")
                if total > 0:
                    if cost_result.inventory_value_delta:
                        adj_je_lines.append(je_service.LineInput(account_id=inventory_account_id, description=description, debit=cost_result.inventory_value_delta, credit=_ZERO))
                    if cost_result.variance_value_delta:
                        adj_je_lines.append(je_service.LineInput(account_id=variance_account_id, description=description, debit=cost_result.variance_value_delta, credit=_ZERO))
                    adj_je_lines.append(je_service.LineInput(account_id=payable_account_id, description=description, debit=_ZERO, credit=total))
                elif total < 0:
                    if cost_result.inventory_value_delta:
                        adj_je_lines.append(je_service.LineInput(account_id=inventory_account_id, description=description, debit=_ZERO, credit=-cost_result.inventory_value_delta))
                    if cost_result.variance_value_delta:
                        adj_je_lines.append(je_service.LineInput(account_id=variance_account_id, description=description, debit=_ZERO, credit=-cost_result.variance_value_delta))
                    adj_je_lines.append(je_service.LineInput(account_id=payable_account_id, description=description, debit=-total, credit=_ZERO))

            tax_delta = new_tax - old_tax
            if tax_delta != 0:
                tax_account_id = _role_account("PURCHASE_TAX_RECEIVABLE")
                payable_account_id = _role_account("SUPPLIER_PAYABLE")
                if tax_delta > 0:
                    adj_je_lines.append(je_service.LineInput(account_id=tax_account_id, description=description, debit=tax_delta, credit=_ZERO))
                    adj_je_lines.append(je_service.LineInput(account_id=payable_account_id, description=description, debit=_ZERO, credit=tax_delta))
                else:
                    adj_je_lines.append(je_service.LineInput(account_id=tax_account_id, description=description, debit=_ZERO, credit=-tax_delta))
                    adj_je_lines.append(je_service.LineInput(account_id=payable_account_id, description=description, debit=-tax_delta, credit=_ZERO))

        if adj_je_lines:
            adj_result = je_service.create_journal_entry(
                company_id, posted_by_user_id, document_date, description, adj_je_lines, entry_type_code="COMMERCIAL",
            )
            journal_entry_id = adj_result.journal_entry_id
            if stock_document_id is not None:
                with new_session() as session:
                    session.get(StockDocument, stock_document_id).journal_entry_id = journal_entry_id
                    session.commit()
        else:
            # هیچ چیزِ مالی‌ای عوض نشده (فقط مثلاً توضیحات/مرجع) --
            # سندِ حسابداری/انبارِ اصلی هم‌چنان معتبر است، همان را به
            # اشتراک می‌گذاریم.
            stock_document_id = original_stock_document_id
            journal_entry_id = original_journal_entry_id

    else:
        raise ValueError("اصلاح فقط برایِ فاکتورِ خرید/فروش پشتیبانی می‌شود.")

    with new_session() as session:
        draft = session.get(CommercialDocument, document_id)
        draft.stock_document_id = stock_document_id
        draft.journal_entry_id = journal_entry_id
        draft.status_code = "POSTED"
        draft.posted_by_user_id = posted_by_user_id
        draft.posted_at = datetime.datetime.now()
        original = session.get(CommercialDocument, draft.corrects_document_id)
        original.status_code = "CORRECTED"
        session.commit()

    return PostResult(document_id=document_id, stock_document_id=stock_document_id, journal_entry_id=journal_entry_id)


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
    if fields.tax_posting_mode is not None and fields.tax_posting_mode not in ("OFFICIAL", "INFORMAL"):
        raise ValueError("نوعِ ثبتِ سند نامعتبر است.")
    with new_session() as session:
        doc = _get_editable_document(session, document_id, company_id)
        doc.document_date = document_date
        doc.fiscal_year_id = _resolve_fiscal_year_id(session, company_id, document_date)
        doc.counterparty_detail_account_id = fields.counterparty_detail_account_id
        doc.warehouse_id = fields.warehouse_id
        doc.consignment_warehouse_id = fields.consignment_warehouse_id
        doc.channel_code = fields.channel_code
        doc.price_list_id = fields.price_list_id
        if fields.due_date is not None:
            doc.due_date = fields.due_date
        else:
            doc.due_date = settlements_service.compute_due_date(
                company_id, doc.document_type_code, fields.counterparty_detail_account_id, document_date,
            )
        doc.sales_rep_detail_account_id = fields.sales_rep_detail_account_id
        doc.cost_center_detail_account_id = fields.cost_center_detail_account_id
        doc.project_detail_account_id = fields.project_detail_account_id
        doc.reference_no = fields.reference_no or None
        doc.description = fields.description or None
        doc.tax_posting_mode = fields.tax_posting_mode
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


def list_documents(
    company_id: int, document_type_code: str | None = None, status_code: str | None = None,
    counterparty_detail_account_id: int | None = None, limit: int | None = None,
) -> list[CommercialDocument]:
    with new_session() as session:
        stmt = select(CommercialDocument).where(CommercialDocument.company_id == company_id)
        if document_type_code:
            stmt = stmt.where(CommercialDocument.document_type_code == document_type_code)
        if status_code:
            stmt = stmt.where(CommercialDocument.status_code == status_code)
        if counterparty_detail_account_id is not None:
            stmt = stmt.where(CommercialDocument.counterparty_detail_account_id == counterparty_detail_account_id)
        stmt = stmt.order_by(CommercialDocument.document_id.desc())
        if limit is not None:
            stmt = stmt.limit(limit)
        return list(session.scalars(stmt))


@dataclass
class ItemPriceHistoryRow:
    document_id: int
    document_type_code: str
    document_no: int
    document_date: datetime.date
    unit_price: decimal.Decimal


def list_item_price_history(
    company_id: int, item_id: int, counterparty_detail_account_id: int, limit: int = 10,
) -> list[ItemPriceHistoryRow]:
    """طبقِ درخواستِ صریح («۱۰ قیمتِ آخرِ کالا به همین طرفِ‌حساب»): فقط
    اسنادِ ثبتِ‌نهایی‌شده (POSTED) -- پیش‌نویس/لغوشده معیارِ قیمت‌گذاری
    نیستند."""
    with new_session() as session:
        rows = session.execute(
            select(
                CommercialDocument.document_id, CommercialDocument.document_type_code,
                CommercialDocument.document_no, CommercialDocument.document_date, CommercialDocumentLine.unit_price,
            )
            .join(CommercialDocumentLine, CommercialDocumentLine.document_id == CommercialDocument.document_id)
            .where(
                CommercialDocument.company_id == company_id,
                CommercialDocument.counterparty_detail_account_id == counterparty_detail_account_id,
                CommercialDocument.status_code == "POSTED",
                CommercialDocumentLine.item_id == item_id,
            )
            .order_by(CommercialDocument.document_date.desc(), CommercialDocument.document_id.desc())
            .limit(limit)
        ).all()
        return [ItemPriceHistoryRow(*row) for row in rows]


@dataclass
class CrossSellSuggestion:
    item_id: int
    item_code: str
    item_name: str
    co_occurrence_count: int
    base_count: int
    confidence_percent: decimal.Decimal


def suggest_frequently_bought_together(
    company_id: int, item_id: int, limit: int = 3, counterparty_detail_account_id: int | None = None,
) -> list[CrossSellSuggestion]:
    """طبقِ درخواستِ صریح («سبدِ پیشنهادی» -- وقتی فروشنده یک کالا به
    فاکتور اضافه می‌کند، کالاهایی که معمولاً همراهِ آن خریده می‌شوند
    پیشنهاد شود): از رویِ فاکتورهایِ فروشِ ثبتِ‌نهایی‌شده (POSTED) --
    پیش‌نویس/لغوشده معیار نیستند -- کالاهایی که بیشترین هم‌خریدی را با
    این کالا دارند پیدا می‌کند. این فقط یک هم‌بستگیِ آماریِ ساده
    (co-occurrence) است، نه یادگیریِ ماشین، ولی برایِ پیشنهادِ فروشِ
    مکمل کافی است.

    طبقِ رفعِ بازخوردِ صریح («این پیام باید به همان مشتریِ رویِ هدرِ سند
    اشاره کند، نه به «مشتری‌ها» به‌طورِ کلی»): وقتی counterparty_
    detail_account_id داده شود، فقط سابقهٔ خریدِ همان مشتریِ خاص در نظر
    گرفته می‌شود -- نه هم‌بستگیِ آماریِ کلِ مشتریان."""
    with new_session() as session:
        base_query = (
            select(CommercialDocumentLine.document_id)
            .join(CommercialDocument, CommercialDocument.document_id == CommercialDocumentLine.document_id)
            .where(
                CommercialDocument.company_id == company_id,
                CommercialDocument.document_type_code == "SALES_INVOICE",
                CommercialDocument.status_code == "POSTED",
                CommercialDocumentLine.item_id == item_id,
            )
        )
        if counterparty_detail_account_id is not None:
            base_query = base_query.where(
                CommercialDocument.counterparty_detail_account_id == counterparty_detail_account_id
            )
        base_doc_ids = [row[0] for row in session.execute(base_query.distinct()).all()]
        if not base_doc_ids:
            return []
        base_count = len(base_doc_ids)

        rows = session.execute(
            select(
                CommercialDocumentLine.item_id,
                func.count(func.distinct(CommercialDocumentLine.document_id)).label("co_count"),
            )
            .where(
                CommercialDocumentLine.document_id.in_(base_doc_ids),
                CommercialDocumentLine.item_id != item_id,
            )
            .group_by(CommercialDocumentLine.item_id)
            .order_by(func.count(func.distinct(CommercialDocumentLine.document_id)).desc())
            .limit(limit)
        ).all()

    if not rows:
        return []
    # کد/نامِ کالا رویِ acc.detail_accounts است، نه خودِ inv.items -- طبقِ
    # همان الگویِ inventory_catalog.list_items -- پس این‌جا هم از همان
    # سرویس استفاده می‌کنیم به‌جایِ تکرارِ Joinِ تفصیلی.
    from peecha.services import inventory_catalog as catalog_service

    items_by_id = {i.item_id: i for i in catalog_service.list_items(company_id)}
    result: list[CrossSellSuggestion] = []
    for r in rows:
        item = items_by_id.get(r.item_id)
        if item is None:
            continue
        result.append(
            CrossSellSuggestion(
                item_id=r.item_id, item_code=item.code, item_name=item.name or "",
                co_occurrence_count=r.co_count, base_count=base_count,
                confidence_percent=(decimal.Decimal(r.co_count) / decimal.Decimal(base_count) * 100).quantize(decimal.Decimal("1")),
            )
        )
    return result


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
    discount_amount: decimal.Decimal = _ZERO, discount_percent: decimal.Decimal = _ZERO,
    tax_percent: decimal.Decimal = _ZERO,
    batch_id: int | None = None, serial_id: int | None = None, source_line_id: int | None = None,
    description: str | None = None, warehouse_id: int | None = None,
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
        # طبقِ درخواستِ صریح («تخفیف هم روی ردیف کالا فقط مبلغی است، باید
        # درصدی هم باشد»): وقتی discount_percent وارد شده، مبنایِ صحتِ
        # مبلغِ تخفیف همین درصد است — دقیقاً هم‌الگو با tax_percent پایین‌تر
        # (رویِ جمعِ ناخالصِ همین ردیف، بعدِ حل‌شدنِ unit_price)، نه هرچه
        # پیش‌تر در discount_amount بوده.
        gross_amount = quantity * unit_price
        if discount_percent:
            discount_amount = _money(gross_amount * (discount_percent / 100))
        # طبقِ رفعِ باگِ واقعی: مالیات باید رویِ مبلغِ *بعدِ تخفیف* محاسبه
        # شود (همان‌طور که ستون‌بندیِ خودِ جدولِ ردیف‌ها هم نشان می‌دهد:
        # «تخفیف» پیش از «درصدِ مالیات» می‌آید) — قبلاً رویِ جمعِ ناخالص
        # (quantity*unit_price) محاسبه می‌شد، بدونِ کسرِ تخفیف.
        net_amount = gross_amount - discount_amount
        tax_amount = _money(net_amount * (tax_percent / 100)) if tax_percent and net_amount > 0 else _ZERO
        next_no = (
            session.scalar(select(func.max(CommercialDocumentLine.line_no)).where(CommercialDocumentLine.document_id == document_id)) or 0
        ) + 1
        line = CommercialDocumentLine(
            document_id=document_id, line_no=next_no, item_id=item_id, uom_id=uom_id, quantity=quantity,
            quantity_base=quantity_base, unit_price=unit_price, discount_amount=discount_amount,
            discount_percent=discount_percent, tax_percent=tax_percent, tax_amount=tax_amount,
            batch_id=batch_id, serial_id=serial_id,
            source_line_id=source_line_id, description=(description or None), warehouse_id=warehouse_id,
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
        # طبقِ همان منطق: CORRECTED هم (برخلافِ DRAFT/CONFIRMED/APPROVED/
        # CANCELLED) واقعاً stock_document_id/journal_entry_id دارد --
        # چون خودش قبلاً POSTED بوده -- و corrected_by_document_id به
        # فاکتورِ اصلاحیِ دیگری اشاره دارد که نباید یتیم بماند.
        if doc.status_code == "CORRECTED":
            raise ValueError("سندِ اصلاح‌شده هرگز حذف نمی‌شود — تاریخچه‌یِ اصلاح باید دست‌نخورده بماند.")
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
        # طبقِ رفعِ باگِ واقعی («اگر پیش‌نویسِ اصلاح لغو شود، سندِ اصلی برایِ
        # همیشه قفل می‌ماند»): وقتی خودِ این سند یک پیش‌نویسِ اصلاحیِ
        # ناتمام است، لغوش یعنی «اصلاح منصرف شد» -- قفلِ سندِ اصلی هم باید
        # باز شود تا بشود دوباره اصلاح را (مثلاً با اعدادِ درست) از نو
        # شروع کرد.
        if doc.corrects_document_id is not None:
            original = session.get(CommercialDocument, doc.corrects_document_id)
            if original is not None and original.corrected_by_document_id == document_id:
                original.corrected_by_document_id = None
        session.commit()


@dataclass
class PostResult:
    document_id: int
    stock_document_id: int | None
    journal_entry_id: int | None


def _build_sales_invoice_commercial_je(
    company_id: int, posted_by_user_id: int, document_date: datetime.date, description: str, counterparty_id: int,
    extra_dims: dict[int, int], subtotal_amount: decimal.Decimal, discount_amount: decimal.Decimal,
    tax_amount: decimal.Decimal, sales_rep_id: int | None, line_snapshots: list[tuple],
    is_informal_tax: bool = False,
) -> int:
    """سندِ حسابداریِ «بازرگانیِ» فاکتورِ فروش (دریافتنی/درآمد/تخفیف/
    مالیات + کمیسیونِ فروشنده) -- استخراج‌شده از دلِ post_document تا هم
    آن‌جا و هم start_invoice_correction/post_invoice_correction بتوانند
    دقیقاً همان منطق را (بدونِ تکرار) صدا بزنند.

    is_informal_tax=True (طبقِ درخواستِ صریح، «ثبتِ غیررسمی»): مالیات
    ردیفِ جداگانه‌یِ «مالياتِ فروش-پرداختنی» نمی‌گیرد -- مستقیماً به
    درآمدِ فروش اضافه می‌شود (بدهکارِ دریافتنیِ مشتری هیچ تغییری نمی‌کند،
    چون آن از پیش با احتسابِ مالیات محاسبه شده است)."""
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
    # طبقِ رفعِ باگِ واقعیِ دیگر («کالا» هم می‌تواند رویِ حسابِ درآمد/
    # تخفیف/مالیات الزامی شده باشد): چون این حساب‌ها فقط یک ردیفِ جمعی
    # برایِ کلِ فاکتور داشتند، وقتی «کالا» الزامی بود هرگز قابلِ‌تامین
    # نبود (یک ردیف نمی‌تواند هم‌زمان تفصیلیِ چند کالایِ مختلف را حمل
    # کند). حالا اگر معین این بُعد را الزامی کرده باشد، به‌جایِ یک
    # ردیفِ جمعی، به‌ازایِ هر کالایِ فاکتور یک ردیفِ جداگانه ساخته
    # می‌شود.
    item_dim_type_id = dimensions_service.get_specialized_dimension_type_id(company_id, dimensions_service.INVENTORY_ITEM_CODE)
    item_ids = {snap[1] for snap in line_snapshots}
    with new_session() as session:
        item_detail_account_by_item_id = dict(
            session.execute(
                select(Item.item_id, Item.item_detail_account_id).where(Item.item_id.in_(item_ids))
            ).all()
        )
    # طبقِ درخواستِ صریح («دو نوعِ ثبت: رسمی/غیررسمی»): در حالتِ غیررسمی،
    # مالياتِ فروش ردیفِ جداگانه‌یِ «مالياتِ فروش-پرداختنی» نمی‌گیرد --
    # مستقیماً به درآمدِ فروش اضافه می‌شود (اگر مالياتی نباشد، دو حالت
    # یکسان‌اند).
    fold_tax_into_revenue = is_informal_tax and tax_amount > 0
    revenue_total = subtotal_amount + tax_amount if fold_tax_into_revenue else subtotal_amount
    if fold_tax_into_revenue:
        revenue_amount_of = lambda snap: _money(snap[3] * snap[5]) + snap[9]
    else:
        revenue_amount_of = lambda snap: _money(snap[3] * snap[5])
    with new_session() as session:
        revenue_account_id = settings_service.resolve_role_account(session, company_id, "SALES_REVENUE")
        revenue_by_item = _role_line_amounts_by_item(
            line_snapshots, item_detail_account_by_item_id, revenue_amount_of
        )
        je_lines.extend(
            _build_role_je_lines(
                revenue_account_id, description, extra_dims, revenue_total, is_debit=False,
                item_dim_type_id=item_dim_type_id, amounts_by_item_detail_account=revenue_by_item,
                fixed_detail=settings_service.get_fixed_detail_for_mapping(company_id, "SALES_REVENUE"),
            )
        )
        if discount_amount > 0:
            discount_account_id = settings_service.resolve_role_account(session, company_id, "SALES_DISCOUNT")
            discount_by_item = _role_line_amounts_by_item(
                line_snapshots, item_detail_account_by_item_id, lambda snap: snap[8]
            )
            je_lines.extend(
                _build_role_je_lines(
                    discount_account_id, description, extra_dims, discount_amount, is_debit=True,
                    item_dim_type_id=item_dim_type_id, amounts_by_item_detail_account=discount_by_item,
                    fixed_detail=settings_service.get_fixed_detail_for_mapping(company_id, "SALES_DISCOUNT"),
                )
            )
        if tax_amount > 0 and not fold_tax_into_revenue:
            tax_account_id = settings_service.resolve_role_account(session, company_id, "SALES_TAX_PAYABLE")
            tax_by_item = _role_line_amounts_by_item(
                line_snapshots, item_detail_account_by_item_id, lambda snap: snap[9]
            )
            je_lines.extend(
                _build_role_je_lines(
                    tax_account_id, description, extra_dims, tax_amount, is_debit=False,
                    item_dim_type_id=item_dim_type_id, amounts_by_item_detail_account=tax_by_item,
                    fixed_detail=settings_service.get_fixed_detail_for_mapping(company_id, "SALES_TAX_PAYABLE"),
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
            for line_id, item_id, uom_id, quantity, quantity_base, unit_price, batch_id, serial_id, _discount_amt, _tax_amt, _wh_id in line_snapshots:
                base_amount = _money(quantity * unit_price)
                contracts_service.create_commission_entry_for_line(line_id, sales_rep_id, rule_id, base_amount)

    return journal_entry_id


def _build_consignment_in_settlement_je(
    company_id: int, posted_by_user_id: int, document_date: datetime.date, description: str, counterparty_id: int,
    extra_dims: dict[int, int], line_snapshots: list[tuple],
) -> int:
    """سندِ حسابداریِ تسویه‌یِ امانیِ ورودی -- طبقِ اصلِ فاکتورِ امانی: کالا
    از پیش (بدونِ اثرِ حسابداری، در لحظه‌یِ خودِ سندِ CONSIGNMENT_IN)
    فیزیکی وارد شده، پس این‌جا هیچ RECEIPTِ تازه‌ای لازم نیست -- فقط اکنون
    که مالکیت رسماً منتقل می‌شود، بدهکارِ موجودیِ کالا/بستانکارِ
    حساب‌هایِ پرداختنی ثبت می‌شود (این معادلِ دقیقِ اثرِ نهاییِ یک RECEIPTِ
    معمولی است -- چه پیش از تسویه فروخته شده باشد چه هنوز در انبار باشد،
    چون فروشِ احتمالیِ پیش‌تر همان مقدار را از حسابِ موجودیِ کالا بستانکار
    کرده بود، این سند دقیقاً آن را جبران می‌کند).

    محدودیتِ آگاهانه: مالياتِ ردیف در این مسیر پشتیبانی نمی‌شود (فقط
    قیمتِ خالص) و بهایِ تسویه باید همان بهایِ توافق‌شده‌یِ زمانِ
    CONSIGNMENT_IN بماند -- تغییرِ قیمت در لحظه‌یِ تسویه به یک دورِ بعدی
    موکول شده است."""
    person_dim_type_id = dimensions_service.get_person_dimension_type_id(company_id)
    ap_account_id = inv_engine_service.get_account_mapping(company_id, "SUPPLIER_PAYABLE")
    if ap_account_id is None:
        raise ValueError("حسابِ «پرداختنیِ تامین‌کنندگان» هنوز در تنظیماتِ انبار مشخص نشده است.")
    inventory_account_id = inv_engine_service.get_account_mapping(company_id, "INVENTORY_ASSET")
    if inventory_account_id is None:
        raise ValueError("حسابِ «موجودیِ کالا» هنوز در تنظیماتِ انبار مشخص نشده است.")

    item_dim_type_id = dimensions_service.get_specialized_dimension_type_id(company_id, dimensions_service.INVENTORY_ITEM_CODE)
    item_ids = {snap[1] for snap in line_snapshots}
    with new_session() as session:
        item_detail_account_by_item_id = dict(
            session.execute(select(Item.item_id, Item.item_detail_account_id).where(Item.item_id.in_(item_ids))).all()
        )

    total = _ZERO
    inventory_by_item: dict[int, decimal.Decimal] = {}
    for snap in line_snapshots:
        item_id, quantity, unit_cost = snap[1], snap[3], snap[5]
        amount = _money(quantity * unit_cost)
        total += amount
        detail_account_id = item_detail_account_by_item_id.get(item_id)
        if detail_account_id is not None:
            inventory_by_item[detail_account_id] = inventory_by_item.get(detail_account_id, _ZERO) + amount

    je_lines: list[je_service.LineInput] = _build_role_je_lines(
        inventory_account_id, description, extra_dims, total, is_debit=True,
        item_dim_type_id=item_dim_type_id, amounts_by_item_detail_account=inventory_by_item,
    )
    je_lines.append(
        je_service.LineInput(
            account_id=ap_account_id, description=description, debit=_ZERO, credit=total,
            details={person_dim_type_id: counterparty_id, **extra_dims},
        )
    )
    result = je_service.create_journal_entry(
        company_id, posted_by_user_id, document_date, description, je_lines, entry_type_code="COMMERCIAL"
    )
    return result.journal_entry_id


def _post_consignment_document(
    document_id: int, company_id: int, posted_by_user_id: int, line_snapshots: list[tuple], header_fields: tuple,
) -> PostResult:
    """ثبتِ‌نهاییِ CONSIGNMENT_OUT/CONSIGNMENT_IN -- طبقِ اصلِ فاکتورِ
    امانی: فقط جابه‌جاییِ فیزیکیِ کالاست (بدونِ هیچ اثرِ حسابداری‌ای)، پس
    به‌جایِ نگاشتِ عمومیِ _STOCK_DOC_TYPE_BY_TYPE (که فرضِ یک‌انباره
    دارد)، این‌جا مستقیماً سندِ انبارِ مناسب ساخته می‌شود:
      - CONSIGNMENT_OUT: یک TRANSFERِ عادی از انبارِ مبدا (warehouse_id)
        به انبارِ امانتِ نزدِ طرفِ‌حساب (consignment_warehouse_id) --
        TRANSFER هرگز اثرِ حسابداری تولید نمی‌کند (طبقِ قاعدهٔ ۷۶
        ازپیش‌موجود)، دقیقاً هم‌معنیِ «کالا هنوز مالِ ماست، فقط جایش
        عوض شده».
      - CONSIGNMENT_IN: نوعِ تازه‌یِ CONSIGNMENT_IN در inventory_engine.py
        (مثلِ نیمه‌یِ ورودیِ TRANSFER، بدونِ اثرِ حسابداری) -- بهایِ
        توافق‌شده لازم است تا اگر پیش از تسویه فروخته شود، بهایِ
        تمام‌شده درست محاسبه شود."""
    warehouse_id, consignment_warehouse_id, cost_center_id, project_id, document_date, description = header_fields
    with new_session() as session:
        doc = session.get(CommercialDocument, document_id)
        document_type_code = doc.document_type_code

    if document_type_code == "CONSIGNMENT_OUT":
        if warehouse_id is None or consignment_warehouse_id is None:
            raise ValueError("برایِ امانیِ خروجی، انبارِ مبدا و انبارِ امانتِ نزدِ طرفِ‌حساب هردو الزامی‌اند.")
        stock_document_type = "TRANSFER"
        stock_header_fields = inv_documents_service.DocumentHeaderFields(
            source_warehouse_id=warehouse_id, destination_warehouse_id=consignment_warehouse_id,
            cost_center_detail_account_id=cost_center_id, project_detail_account_id=project_id,
            reference_no=f"COMM-{document_id}", description=description,
        )
    else:
        if warehouse_id is None:
            raise ValueError("انبارِ نگه‌داریِ کالایِ امانیِ ورودی الزامی است.")
        stock_document_type = "CONSIGNMENT_IN"
        stock_header_fields = inv_documents_service.DocumentHeaderFields(
            destination_warehouse_id=warehouse_id,
            cost_center_detail_account_id=cost_center_id, project_detail_account_id=project_id,
            reference_no=f"COMM-{document_id}", description=description,
        )

    stock_document_id = inv_documents_service.create_stock_document(
        company_id, posted_by_user_id, stock_document_type, document_date, stock_header_fields
    )
    for line_id, item_id, uom_id, quantity, quantity_base, unit_price, batch_id, discount_amount, tax_amount in line_snapshots:
        # CONSIGNMENT_OUT چون TRANSFER است، unit_cost=None کافیست (موتورِ
        # انبار خودش از بهایِ فعلیِ کالا استفاده می‌کند)؛ CONSIGNMENT_IN
        # چون هیچ سابقه‌ای در انبارِ مقصد ندارد، بهایِ توافق‌شده‌یِ همان
        # ردیف صریحاً به‌عنوانِ unit_cost منتقل می‌شود -- طبقِ رفعِ باگِ
        # واقعیِ گزارش‌شده («ردیفِ فاکتور با ۱۰٪ مالیات شد ۱۱٬۰۰۰٬۰۰۰ ولی
        # در کاردکس ۱۰٬۰۰۰٬۰۰۰ نشان می‌داد»): این‌جا هم -- درست هم‌الگو با
        # RECEIPTِ فاکتورِ خرید -- خالص از تخفیف محاسبه و مالياتِ ردیف
        # جداگانه منتقل می‌شود تا کاردکس بتواند بهایِ تمام‌شده را با
        # احتسابِ مالیات نشان بدهد.
        line_unit_cost = None
        line_tax_amount = None
        if document_type_code == "CONSIGNMENT_IN":
            net_of_discount = (quantity * unit_price - discount_amount) / quantity if quantity else unit_price
            line_unit_cost = _money(net_of_discount)
            line_tax_amount = tax_amount
        inv_line_id = inv_documents_service.add_line(
            stock_document_id, company_id,
            inv_documents_service.LineFields(
                item_id=item_id, uom_id=uom_id, quantity=quantity, quantity_base=quantity_base,
                batch_id=batch_id, unit_cost=line_unit_cost, tax_amount=line_tax_amount,
            ),
        )
        with new_session() as session:
            comm_line = session.get(CommercialDocumentLine, line_id)
            comm_line.stock_document_line_id = inv_line_id
            session.commit()

    inv_documents_service.confirm_stock_document(stock_document_id, company_id)
    inv_documents_service.post_stock_document(stock_document_id, company_id, posted_by_user_id)

    with new_session() as session:
        doc = session.get(CommercialDocument, document_id)
        doc.stock_document_id = stock_document_id
        doc.status_code = "POSTED"
        doc.posted_by_user_id = posted_by_user_id
        doc.posted_at = datetime.datetime.now()
        session.commit()

    return PostResult(document_id=document_id, stock_document_id=stock_document_id, journal_entry_id=None)


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

        if document_type_code in _CONSIGNMENT_TYPES:
            # طبقِ اصلِ فاکتورِ امانی: فقط جابه‌جاییِ فیزیکیِ کالاست، هیچ
            # اثرِ حسابداری‌ای در همین لحظه ندارد -- _post_consignment_document
            # جداگانه (خارج از همین session) مدیریتش می‌کند، چون امانیِ
            # خروجی به دو انبارِ هم‌زمان (مبدا+مقصد) نیاز دارد.
            lines = session.scalars(
                select(CommercialDocumentLine).where(CommercialDocumentLine.document_id == document_id).order_by(CommercialDocumentLine.line_no)
            ).all()
            if not lines:
                raise ValueError("سند حداقل باید یک ردیف داشته باشد.")
            consignment_line_snapshots = [
                (ln.line_id, ln.item_id, ln.uom_id, ln.quantity, ln.quantity_base, ln.unit_price, ln.batch_id, ln.discount_amount, ln.tax_amount)
                for ln in lines
            ]
            consignment_fields = (
                doc.warehouse_id, doc.consignment_warehouse_id, doc.cost_center_detail_account_id,
                doc.project_detail_account_id, doc.document_date,
                doc.description or _default_document_description(document_type_code, doc.document_no, doc.counterparty_detail_account_id),
            )
        else:
            consignment_line_snapshots = None
            consignment_fields = None

        # طبقِ اصلِ تسویه‌یِ امانیِ ورودی: فاکتورِ خریدی که از یک سندِ
        # CONSIGNMENT_IN تبدیل شده، هرگز نباید دوباره RECEIPT بزند (کالا
        # از پیش، در لحظه‌یِ خودِ CONSIGNMENT_IN، فیزیکی وارد شده) -- فقط
        # سندِ حسابداریِ تسویه (موجودی/پرداختنی) لازم دارد.
        is_consignment_in_settlement = False
        if document_type_code == "PURCHASE_INVOICE" and doc.source_document_id is not None:
            source_doc = session.get(CommercialDocument, doc.source_document_id)
            is_consignment_in_settlement = source_doc is not None and source_doc.document_type_code == "CONSIGNMENT_IN"

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
        description = doc.description or _default_document_description(document_type_code, doc.document_no, counterparty_id)
        sales_rep_id = doc.sales_rep_detail_account_id
        cost_center_id = doc.cost_center_detail_account_id
        project_id = doc.project_detail_account_id
        subtotal_amount = doc.subtotal_amount
        discount_amount = doc.discount_amount
        tax_amount = doc.tax_amount
        is_informal_tax = _is_informal_tax_posting(company_id, doc.tax_posting_mode)
        line_snapshots = [
            (
                ln.line_id, ln.item_id, ln.uom_id, ln.quantity, ln.quantity_base, ln.unit_price, ln.batch_id,
                ln.serial_id, ln.discount_amount, ln.tax_amount, ln.warehouse_id,
            )
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
        # (این سند و سندِ انبارِ خودکارِ همراهش، و ردیف‌هایِ هزینه‌هایِ جانبی
        # پایین‌تر) فرستاده می‌شود. این‌جا (پیش‌تر از محاسبهٔ هزینه‌هایِ
        # جانبی) محاسبه می‌شود تا آن‌ها هم بتوانند از همین extra_dims
        # استفاده کنند.
        extra_dims: dict[int, int] = {}
        if cost_center_id is not None:
            extra_dims[dimensions_service.get_specialized_dimension_type_id(company_id, dimensions_service.COST_CENTER_CODE)] = cost_center_id
        if project_id is not None:
            extra_dims[dimensions_service.get_specialized_dimension_type_id(company_id, dimensions_service.PROJECT_CODE)] = project_id
        # «مرکزِ سود» فیلدی در سرِسندِ اسنادِ بازرگانی ندارد — تنها منبعِ آن
        # انبارِ خودِ سند است (طبقِ رفعِ همین باگ در inventory_engine.py).
        if warehouse_id is not None:
            warehouse_row = locations_service.get_warehouse(warehouse_id, company_id)
            if warehouse_row is not None and warehouse_row.fields.profit_center_detail_account_id is not None:
                extra_dims[dimensions_service.get_specialized_dimension_type_id(company_id, dimensions_service.PROFIT_CENTER_CODE)] = (
                    warehouse_row.fields.profit_center_detail_account_id
                )

        # طبقِ درخواستِ صریح («فرمِ تسهیمِ هزینه رویِ فاکتورِ خرید — مبلغ +
        # حسابِ معین و تفصیلیِ بستانکار برایِ هر ردیف، همراهِ خودِ سندِ
        # فاکتور»): سهمِ هر ردیفِ فاکتور از جمعِ هزینه‌هایِ جانبی (متناسب
        # با ارزشِ خالص از تخفیفِ همان ردیف) این‌جا محاسبه می‌شود؛ باقیماندهٔ
        # گردِکردن به آخرین ردیف داده می‌شود تا جمعِ سهم‌ها دقیقاً با جمعِ
        # هزینه‌ها برابر بماند. ردیف‌هایِ بستانکاریِ سندِ حسابداری (حسابِ
        # آزادانه‌ایِ خودِ کاربر برایِ هر هزینه) هم همین‌جا ساخته می‌شوند تا
        # مستقیماً به سندِ حسابداریِ خودکارِ همین فاکتور اضافه شوند — طبقِ
        # گزارشِ صریح («مرکزِ هزینه/پروژهٔ رویِ فاکتور برایِ حساب‌هایِ فرمِ
        # هزینه‌ها هم لحاظ شود»)، extra_dimsِ سرِسند به این ردیف‌ها هم
        # اضافه می‌شود.
        landed_cost_share_by_line: dict[int, decimal.Decimal] = {}
        landed_cost_je_lines: list[je_service.LineInput] = []
        if document_type_code == "PURCHASE_INVOICE":
            allocations = session.scalars(
                select(LandedCostAllocation).where(LandedCostAllocation.purchase_invoice_document_id == document_id)
            ).all()
            landed_cost_total = sum((a.amount for a in allocations), _ZERO)
            if landed_cost_total > 0:
                line_values = {ln.line_id: _money(ln.quantity * ln.unit_price - ln.discount_amount) for ln in lines}
                total_value = sum(line_values.values(), _ZERO)
                if total_value > 0:
                    allocated_so_far = _ZERO
                    ordered_line_ids = [ln.line_id for ln in lines]
                    for idx, line_id in enumerate(ordered_line_ids):
                        if idx == len(ordered_line_ids) - 1:
                            share = landed_cost_total - allocated_so_far
                        else:
                            share = _money(landed_cost_total * line_values[line_id] / total_value)
                            allocated_so_far += share
                        landed_cost_share_by_line[line_id] = share
                for allocation in allocations:
                    credit_details: dict[int, int] = dict(extra_dims)
                    if allocation.credit_detail_account_id is not None:
                        credit_detail = session.get(DetailAccount, allocation.credit_detail_account_id)
                        if credit_detail is not None:
                            credit_details[credit_detail.dimension_type_id] = credit_detail.detail_account_id
                    landed_cost_je_lines.append(
                        je_service.LineInput(
                            account_id=allocation.credit_account_id, description=allocation.notes or description,
                            debit=_ZERO, credit=allocation.amount, details=credit_details,
                        )
                    )

    if document_type_code in _CONSIGNMENT_TYPES:
        return _post_consignment_document(document_id, company_id, posted_by_user_id, consignment_line_snapshots, consignment_fields)

    stock_document_id = None
    journal_entry_id = None

    if is_consignment_in_settlement:
        # طبقِ اصلِ تسویه‌یِ امانیِ ورودی: کالا از پیش (بدونِ اثرِ
        # حسابداری، در لحظه‌یِ خودِ CONSIGNMENT_IN) فیزیکی وارد شده -- پس
        # این‌جا هیچ RECEIPTِ تازه‌ای ساخته نمی‌شود، فقط سندِ حسابداریِ
        # موجودی/پرداختنی.
        journal_entry_id = _build_consignment_in_settlement_je(
            company_id, posted_by_user_id, document_date, description, counterparty_id, extra_dims, line_snapshots,
        )
    else:
        stock_document_type = _STOCK_DOC_TYPE_BY_TYPE[document_type_code]
        is_receipt_like = stock_document_type in ("RECEIPT", "RETURN_IN")

        # طبقِ درخواستِ صریح («کالایِ ردیف بتواند انبارِ مستقل از هدر داشته
        # باشد، حتی یک کالا در چند انبار، و به‌ازایِ هر انبار یک حوالهٔ
        # جداگانه صادر شود» — Toggleِ PER_LINE_WAREHOUSE): ردیف‌ها بر اساسِ
        # انبارِ مؤثرِشان (انبارِ خودِ ردیف، وگرنه انبارِ هدر) گروه‌بندی
        # می‌شوند و به‌ازایِ هر انبار یک سندِ انبارِ جداگانه ساخته می‌شود —
        # هرکدام خودکار مرکزِ سودِ همان انبار را می‌گیرد (طبقِ رفعِ باگِ قبلی
        # در inventory_engine.py، چون هرکدام سندِ انبارِ خودش را دارد). وقتی
        # همه‌یِ ردیف‌ها به یک انبار برمی‌گردند (پیش‌فرض، بدونِ این Toggle)،
        # دقیقاً یک سندِ انبار مثلِ قبل ساخته می‌شود — رفتار بدونِ تغییر.
        lines_by_warehouse: dict[int | None, list[tuple]] = {}
        for snapshot in line_snapshots:
            effective_warehouse_id = snapshot[10] or warehouse_id
            lines_by_warehouse.setdefault(effective_warehouse_id, []).append(snapshot)

        for group_warehouse_id, group_lines in lines_by_warehouse.items():
            group_header_fields = inv_documents_service.DocumentHeaderFields(
                destination_warehouse_id=group_warehouse_id if is_receipt_like else None,
                source_warehouse_id=group_warehouse_id if not is_receipt_like else None,
                counterparty_detail_account_id=counterparty_id,
                cost_center_detail_account_id=cost_center_id, project_detail_account_id=project_id,
                reference_no=f"COMM-{document_id}", description=description,
            )
            group_stock_document_id = inv_documents_service.create_stock_document(
                company_id, posted_by_user_id, stock_document_type, document_date, group_header_fields
            )
            for line_id, item_id, uom_id, quantity, quantity_base, unit_price, batch_id, serial_id, _discount_amt, _tax_amt, _wh_id in group_lines:
                # برایِ ISSUE، unit_cost=None می‌ماند تا موتورِ انبار از میانگینِ
                # موزونِ فعلی استفاده کند (قیمتِ فروش هرگز بهایِ تمام‌شده نیست).
                # طبقِ رفعِ باگِ واقعی («مالياتِ ردیفِ فاکتورِ خرید محاسبه
                # می‌شود ولی سندش ثبت نمی‌شود»): قبلاً این‌جا تخفیف/مالياتِ
                # ردیف (_discount_amt/_tax_amt) کاملاً نادیده گرفته می‌شد —
                # بهایِ واحدِ خامِ ردیف (بدونِ کسرِ تخفیف) مستقیماً به‌عنوانِ
                # ارزشِ موجودی/مبنایِ بستانکاریِ پرداختنی می‌رفت. حالا برایِ
                # فاکتورِ خرید (RECEIPT)، ارزشِ موجودی خالص از تخفیف است، و
                # مالياتِ ردیف جداگانه (نه در unit_cost) به موتورِ انبار
                # منتقل می‌شود تا بدهکارِ «مالياتِ خرید-قابلِ مطالبه» شود و
                # به بستانکاریِ حساب‌هایِ پرداختنی هم اضافه شود — دقیقاً هم‌
                # مبلغِ doc.total_amount که کاربر رویِ فاکتور می‌بیند.
                line_tax_amount = None
                if stock_document_type == "ISSUE":
                    stock_unit_cost = None
                elif stock_document_type == "RECEIPT":
                    net_of_discount = (quantity * unit_price - _discount_amt) / quantity if quantity else unit_price
                    # طبقِ درخواستِ صریح («دو نوعِ ثبت: رسمی/غیررسمی»): در
                    # حالتِ غیررسمی، مالياتِ خرید ردیفِ جداگانه‌یِ «مالياتِ
                    # خرید-قابلِ‌مطالبه» نمی‌گیرد -- مستقیماً به بهایِ
                    # موجودیِ همین ردیف اضافه می‌شود (اگر ماليات صفر باشد
                    # هردو حالت یکسان‌اند).
                    if is_informal_tax and _tax_amt and quantity:
                        net_of_discount += _tax_amt / quantity
                    else:
                        line_tax_amount = _tax_amt
                    stock_unit_cost = _money(net_of_discount)
                else:
                    # RETURN_IN/RETURN_OUT (برگشت از فروش/خرید): طبقِ درخواستِ
                    # صریح («برای برگشت از خرید و برگشت از فروش هم به همین
                    # صورت انجام بشه»)، مالياتِ ردیف این‌جا هم منتقل می‌شود؛
                    # تصمیمِ رسمی/غیررسمی (ردیفِ جداگانه یا ادغام در موجودی)
                    # خودِ موتورِ انبار می‌گیرد (پارامترِ is_informal_tax در
                    # پایین‌تر) — چون بهایِ برگشت از رویِ سابقهٔ همان کالا
                    # محاسبه می‌شود، نه از unit_price همین ردیف.
                    stock_unit_cost = unit_price
                    line_tax_amount = _tax_amt
                line_reason_code_id = (
                    _ensure_return_reason_code(company_id, stock_document_type)
                    if stock_document_type in ("RETURN_IN", "RETURN_OUT") else None
                )
                inv_line_id = inv_documents_service.add_line(
                    group_stock_document_id, company_id,
                    inv_documents_service.LineFields(
                        item_id=item_id, uom_id=uom_id, quantity=quantity, quantity_base=quantity_base,
                        batch_id=batch_id, unit_cost=stock_unit_cost, tax_amount=line_tax_amount,
                        landed_cost_amount=landed_cost_share_by_line.get(line_id, _ZERO),
                        reason_code_id=line_reason_code_id,
                    ),
                )
                with new_session() as session:
                    comm_line = session.get(CommercialDocumentLine, line_id)
                    comm_line.stock_document_line_id = inv_line_id
                    session.commit()

            inv_documents_service.confirm_stock_document(group_stock_document_id, company_id)
            # طبقِ همان محدودیتِ آگاهانه‌یِ چند-انباره (پایین‌تر): ردیف‌هایِ
            # بستانکاریِ هزینه‌هایِ جانبی فقط به سندِ *اولین* گروه اضافه
            # می‌شوند (stock_document_id هنوز None است، یعنی هنوز هیچ
            # گروهی پردازش نشده) -- طبقِ تصمیمِ صریح («همراهِ سندِ خودِ
            # فاکتور»)، این تنها JEای است که comm.commercial_documents هم
            # به آن لینک می‌شود.
            group_post_result = inv_documents_service.post_stock_document(
                group_stock_document_id, company_id, posted_by_user_id, is_informal_tax=is_informal_tax,
                extra_je_lines=(landed_cost_je_lines if stock_document_id is None else None),
            )

            # طبقِ محدودیتِ آگاهانه: comm.commercial_documents فقط یک
            # stock_document_id/journal_entry_id دارد — با چند انبار، این
            # فیلدها به اولین حواله/سندِ ساخته‌شده اشاره می‌کنند؛ بقیه هم به
            # همان reference_no («COMM-{document_id}») قابلِ‌پیداکردن در
            # فهرستِ اسنادِ انبار هستند، فقط از طریقِ این یک FK لینک نمی‌شوند.
            if stock_document_id is None:
                stock_document_id = group_stock_document_id
                journal_entry_id = group_post_result.journal_entry_id

    if document_type_code == "SALES_INVOICE":
        journal_entry_id = _build_sales_invoice_commercial_je(
            company_id, posted_by_user_id, document_date, description, counterparty_id, extra_dims,
            subtotal_amount, discount_amount, tax_amount, sales_rep_id, line_snapshots,
            is_informal_tax=is_informal_tax,
        )

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


@dataclass
class CustomerProfitRow:
    counterparty_detail_account_id: int
    customer_name: str
    invoice_count: int
    net_revenue: decimal.Decimal
    cogs: decimal.Decimal
    gross_profit: decimal.Decimal
    margin_percent: decimal.Decimal | None


def compute_customer_profit(
    company_id: int, date_from: datetime.date, date_to: datetime.date,
) -> list[CustomerProfitRow]:
    """طبقِ درخواستِ صریح («سودِ واقعیِ هر مشتری»): برخلافِ گزارش‌هایِ
    مالیِ موجود (که فقط رویِ acc.journal_entry_lines کار می‌کنند)، این‌جا
    باید فروشِ خالص (طبقِ خودِ سندِ فاکتور) با بهایِ تمام‌شده‌یِ واقعیِ
    کالایِ خارج‌شده (طبقِ inv.stock_document_lines، همان بهایی که موتورِ
    انبار در Postِ فاکتور محاسبه کرده) به‌ازایِ هر مشتری جمع بسته شود --
    نه بازنویسیِ این منطق در قالبِ SQLِ حسابداری.

    دو کوئریِ جداگانه (نه یک JOIN): چون هر فاکتور دقیقاً یک سندِ انبار
    دارد ولی آن سند می‌تواند چند ردیف داشته باشد، JOINِ مستقیم مقادیرِ
    سرِسندِ فاکتور (subtotal/discount) را به‌ازایِ هر ردیف تکرار می‌کرد."""
    with new_session() as session:
        revenue_stmt = (
            select(
                CommercialDocument.counterparty_detail_account_id,
                func.count(CommercialDocument.document_id),
                func.coalesce(func.sum(CommercialDocument.subtotal_amount), 0),
                func.coalesce(func.sum(CommercialDocument.discount_amount), 0),
            )
            .where(
                CommercialDocument.company_id == company_id,
                CommercialDocument.document_type_code == "SALES_INVOICE",
                CommercialDocument.status_code == "POSTED",
                CommercialDocument.document_date >= date_from,
                CommercialDocument.document_date <= date_to,
            )
            .group_by(CommercialDocument.counterparty_detail_account_id)
        )
        revenue_by_customer = {
            row[0]: (row[1], row[2] - row[3]) for row in session.execute(revenue_stmt)
        }

        # طبقِ رفعِ باگِ واقعی («بهایِ تمام‌شده همیشه صفر می‌آمد»): برخلافِ
        # فرضِ اولیه، inv.stock_document_lines.unit_cost برایِ سمتِ ISSUE
        # (خروجِ فروش) هرگز پر نمی‌شود -- تنها جایی که مبلغِ واقعیِ COGS
        # ثبت می‌شود، ردیفِ بدهکارِ حسابِ COGS در همان سندِ حسابداریِ دومِ
        # «بهایِ تمام‌شده/موجودی» است (StockDocument.journal_entry_id) --
        # دقیقاً همان سندی که خودِ فرمِ سند (R12-2) پیوندش را نشان می‌دهد.
        cogs_account_id = inv_engine_service.get_account_mapping(company_id, "COGS")
        cogs_by_customer: dict[int, decimal.Decimal] = {}
        if cogs_account_id is not None:
            cogs_stmt = (
                select(
                    CommercialDocument.counterparty_detail_account_id,
                    func.coalesce(func.sum(JournalEntryLine.debit_amount_base), 0),
                )
                .join(StockDocument, StockDocument.stock_document_id == CommercialDocument.stock_document_id)
                .join(JournalEntryLine, JournalEntryLine.journal_entry_id == StockDocument.journal_entry_id)
                .where(
                    CommercialDocument.company_id == company_id,
                    CommercialDocument.document_type_code == "SALES_INVOICE",
                    CommercialDocument.status_code == "POSTED",
                    CommercialDocument.document_date >= date_from,
                    CommercialDocument.document_date <= date_to,
                    JournalEntryLine.account_id == cogs_account_id,
                )
                .group_by(CommercialDocument.counterparty_detail_account_id)
            )
            cogs_by_customer = {row[0]: row[1] for row in session.execute(cogs_stmt)}

    rows: list[CustomerProfitRow] = []
    for counterparty_id, (invoice_count, net_revenue) in revenue_by_customer.items():
        cogs = cogs_by_customer.get(counterparty_id, decimal.Decimal(0))
        gross_profit = net_revenue - cogs
        margin_percent = (gross_profit / net_revenue * 100) if net_revenue > 0 else None
        rows.append(CustomerProfitRow(
            counterparty_detail_account_id=counterparty_id,
            customer_name=dimensions_service.get_detail_account_label(counterparty_id),
            invoice_count=invoice_count,
            net_revenue=net_revenue,
            cogs=cogs,
            gross_profit=gross_profit,
            margin_percent=margin_percent,
        ))
    rows.sort(key=lambda r: r.gross_profit, reverse=True)
    return rows


@dataclass
class SalesTrendResult:
    period_labels: list[str]
    amounts: list[decimal.Decimal]
    forecast_next: decimal.Decimal | None


def compute_sales_trend(
    company_id: int, periods: list[tuple[datetime.date, datetime.date, str]],
) -> SalesTrendResult:
    """طبقِ درخواستِ صریح («پیش‌بینیِ فروش»): هم‌الگو با اصلِ رعایت‌شده در
    sales_assistant.py («بدونِ هیچ مدلِ یادگیریِ ماشین، فقط آمارِ ساده‌یِ
    توصیفی») -- فروشِ خالصِ هر دوره جمع بسته می‌شود و با یک رگرسیونِ
    خطیِ سادهٔ حداقلِ مربعات (نه ARIMA/ML)، فروشِ دورهٔ بعدی تخمین زده
    می‌شود. اگر کمتر از دو دوره وجود داشته باشد، امکانِ رسمِ خط نیست --
    forecast_next برابرِ None می‌ماند."""
    amounts: list[decimal.Decimal] = []
    with new_session() as session:
        for date_from, date_to, _label in periods:
            stmt = select(
                func.coalesce(func.sum(CommercialDocument.subtotal_amount - CommercialDocument.discount_amount), 0)
            ).where(
                CommercialDocument.company_id == company_id,
                CommercialDocument.document_type_code == "SALES_INVOICE",
                CommercialDocument.status_code == "POSTED",
                CommercialDocument.document_date >= date_from,
                CommercialDocument.document_date <= date_to,
            )
            amounts.append(session.scalar(stmt))

    forecast_next = None
    n = len(amounts)
    if n >= 2:
        x_mean = decimal.Decimal(n - 1) / 2
        y_mean = sum(amounts, decimal.Decimal(0)) / n
        numerator = sum(
            ((decimal.Decimal(x) - x_mean) * (amounts[x] - y_mean) for x in range(n)), decimal.Decimal(0)
        )
        denominator = sum(((decimal.Decimal(x) - x_mean) ** 2 for x in range(n)), decimal.Decimal(0))
        if denominator != 0:
            slope = numerator / denominator
            intercept = y_mean - slope * x_mean
            # طبقِ منطقِ کسب‌وکار: فروشِ منفی بی‌معناست -- روندِ نزولیِ
            # تندی که خطِ رگرسیون را زیرِ صفر ببرد، به صفر محدود می‌شود.
            forecast_next = max(decimal.Decimal(0), intercept + slope * n)

    return SalesTrendResult(
        period_labels=[label for _f, _t, label in periods],
        amounts=amounts,
        forecast_next=forecast_next,
    )
