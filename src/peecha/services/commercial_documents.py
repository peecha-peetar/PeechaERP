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
from dataclasses import dataclass, field

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError

from peecha.db.base import new_session
from peecha.db.models.accounting import AccountDetailDimension, DetailAccount, FiscalYear, JournalEntryLine
from peecha.db.models.commercial import (
    Channel, CommercialDocument, CommercialDocumentLine, CreditHold, CustomerProfile, DocumentChangeLog, LandedCostAllocation, PosSettings,
)
from peecha.db.models.inventory import Item, StockDocument, Warehouse
from peecha.services import commercial_contracts as contracts_service
from peecha.services import commercial_credit as credit_service
from peecha.services import commercial_pricing as pricing_service
from peecha.services import commercial_purchasing as purchasing_service
from peecha.services import commercial_settings as settings_service
from peecha.services import commercial_settlements as settlements_service
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import inventory_catalog as catalog_service
from peecha.services import unit_conversion as uc
from peecha.services import inventory_documents as inv_documents_service
from peecha.services import inventory_engine as inv_engine_service
from peecha.services import inventory_locations as locations_service
from peecha.services import journal_entries as je_service
from peecha.services import roles as roles_service
from peecha.services import treasury as treasury_service

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
_INVOICE_TYPES = ("SALES_INVOICE", "PURCHASE_INVOICE")

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


def _pos_receivable_dims_fallback(company_id: int, pos_session_id: int | None) -> dict[int, int]:
    """طبقِ رفعِ باگِ واقعیِ گزارش‌شده («در فرمِ تاییدِ سرپرست، برایِ
    حسابِ مشتری مرکزِ هزینه/پروژه می‌خواهد -- باید در تنظیماتِ تک‌فروشی
    وارد بشه»): فاکتورِ تک‌فروشی (POS) هیچ فیلدِ سرِسندی برایِ مرکزِ
    هزینه/پروژه ندارد -- اگر حسابِ دریافتنیِ نگاشت‌شده این ابعاد را
    الزامی کرده باشد، همان پیش‌فرضِ ذخیره‌شده در تنظیماتِ POS
    (commercial_pos.set_pos_receivable_dimension_defaults) استفاده
    می‌شود. فقط برایِ اسنادِ POS و فقط وقتی سرِسند خودش چیزی برایِ این
    ابعاد ندارد (اولویت با ورودیِ صریحِ کاربر است)."""
    if pos_session_id is None:
        return {}
    with new_session() as session:
        pos_settings = session.get(PosSettings, company_id)
    if pos_settings is None:
        return {}
    fallback: dict[int, int] = {}
    if pos_settings.default_receivable_cost_center_detail_account_id is not None:
        fallback[dimensions_service.get_specialized_dimension_type_id(company_id, dimensions_service.COST_CENTER_CODE)] = (
            pos_settings.default_receivable_cost_center_detail_account_id
        )
    if pos_settings.default_receivable_project_detail_account_id is not None:
        fallback[dimensions_service.get_specialized_dimension_type_id(company_id, dimensions_service.PROJECT_CODE)] = (
            pos_settings.default_receivable_project_detail_account_id
        )
    return fallback


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
    return dimension_type_id in _required_dimension_ids(account_id)


def _required_dimension_ids(account_id: int) -> set[int]:
    with new_session() as session:
        return set(session.scalars(
            select(AccountDetailDimension.dimension_type_id).where(
                AccountDetailDimension.account_id == account_id, AccountDetailDimension.is_required.is_(True),
            )
        ).all())


def auto_line(
    account_id: int, description: str, debit: decimal.Decimal, credit: decimal.Decimal, extra_dims: dict[int, int],
    *, item: tuple[int, int] | None = None, person: tuple[int, int] | None = None,
    fixed_detail_account_id: int | None = None,
) -> "je_service.LineInput":
    """R231: ردیفِ سندِ خودکار با تفصیلی‌هایی که خودِ حساب الزامی کرده
    (کالا/مرکزِ هزینه/پروژه...) -- item/person = (نوعِ‌بُعد، تفصیلی).
    شخص (طرفِ حساب) همیشه رویِ ردیف می‌نشیند تا حسابِ طرف درست بماند."""
    required = _required_dimension_ids(account_id)
    details = {}
    if fixed_detail_account_id is not None:
        with new_session() as session:
            fixed = session.get(DetailAccount, fixed_detail_account_id)
        if fixed is not None:
            details[fixed.dimension_type_id] = fixed.detail_account_id
    details.update(extra_dims)
    if item is not None and item[1] is not None and item[0] in required:
        details[item[0]] = item[1]
    if person is not None and person[1] is not None:
        details[person[0]] = person[1]
    return je_service.LineInput(account_id=account_id, description=description, debit=debit, credit=credit, details=details)


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
    # طبقِ درخواستِ صریح («امکانِ کنسل‌کردنِ مالیات رویِ فاکتور»).
    tax_exempt: bool = False
    # طبقِ درخواستِ صریح («نوعِ تسویه در سفارش/فاکتورِ پخشِ سرد مشخص
    # بشه»): برچسبِ نمایشیِ سبک -- جدا از نقشه‌یِ کاملِ تسویه‌یِ فاکتور.
    settlement_type_code: str | None = None
    # R240: نوعِ خرید (comm.purchase_types) -- فقط برایِ اسنادِ خرید معنا دارد
    purchase_type_id: int | None = None
    # R244: شعبه (خالی = شعبهٔ انبار) و دپارتمان (واحدِ سازمانی)
    branch_id: int | None = None
    org_unit_id: int | None = None


# ---------------------------------------------------------------------
# R240: تاریخچهٔ تغییرات/وضعیتِ اسناد (comm.document_change_log) -- فقط ثبت، بدونِ اثر بر منطق
# ---------------------------------------------------------------------
def _actor(user_id: int | None = None) -> int | None:
    if user_id is not None:
        return user_id
    from peecha import session as app_session

    return app_session.current_user.user_id if app_session.current_user is not None else None


def _log_change(session, doc, action: str, *, user_id: int | None = None, line_id: int | None = None,
                field_name: str | None = None, old=None, new=None) -> None:
    if doc.pos_session_id is not None:
        return
    session.add(DocumentChangeLog(
        document_id=doc.document_id, line_id=line_id, user_id=_actor(user_id), action=action, status_code=doc.status_code,
        field_name=field_name, old_value=None if old is None else str(old), new_value=None if new is None else str(new),
    ))


def _was_confirmed(session, document_id: int) -> bool:
    """آیا سند قبلاً تایید/تصویب شده (پس تغییرِ فعلی «تغییر پس از تایید» است)؟"""
    return session.scalar(
        select(DocumentChangeLog.log_id).where(
            DocumentChangeLog.document_id == document_id, DocumentChangeLog.action == "STATUS",
            or_(DocumentChangeLog.new_value.in_(("CONFIRMED", "APPROVED")), DocumentChangeLog.old_value.in_(("CONFIRMED", "APPROVED"))),
        ).limit(1)
    ) is not None


def _warehouse_branch(session, warehouse_id: int | None) -> int | None:
    if warehouse_id is None:
        return None
    warehouse = session.get(Warehouse, warehouse_id)
    return warehouse.branch_id if warehouse is not None else None


def _log_status(session, doc, old_status: str, user_id: int | None = None) -> None:
    _log_change(session, doc, "STATUS", user_id=user_id, field_name="status_code", old=old_status, new=doc.status_code)


def list_document_changes(document_id: int) -> list[DocumentChangeLog]:
    with new_session() as session:
        return list(session.scalars(
            select(DocumentChangeLog).where(DocumentChangeLog.document_id == document_id)
            .order_by(DocumentChangeLog.changed_at, DocumentChangeLog.log_id)
        ))


def set_line_expected_delivery_date(line_id: int, document_id: int, company_id: int, value: datetime.date | None) -> None:
    """R240: تاریخِ تحویلِ ردیف -- در هر وضعیتی جز لغو قابلِ‌تغییر است (اثری بر موجودی/حسابداری ندارد)."""
    with new_session() as session:
        doc = session.get(CommercialDocument, document_id)
        line = session.get(CommercialDocumentLine, line_id)
        if doc is None or doc.company_id != company_id or line is None or line.document_id != document_id:
            raise ValueError("ردیف نامعتبر است.")
        if doc.status_code == "CANCELLED":
            raise ValueError("سندِ لغوشده قابلِ‌تغییر نیست.")
        if line.expected_delivery_date != value:
            _log_change(session, doc, "UPDATE_LINE", line_id=line_id, field_name="expected_delivery_date",
                        old=line.expected_delivery_date, new=value)
            line.expected_delivery_date = value
        session.commit()


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
            tax_posting_mode=fields.tax_posting_mode, tax_exempt=fields.tax_exempt,
            settlement_type_code=fields.settlement_type_code, purchase_type_id=fields.purchase_type_id,
            branch_id=fields.branch_id or _warehouse_branch(session, fields.warehouse_id), org_unit_id=fields.org_unit_id,
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
    # طبقِ درخواستِ صریح («کالایی سفارشِ اولیه ۹ عدد بوده ولی انبار ۸ عدد
    # تحویلی صادر می‌کند -- در تبدیل باید مقدارِ سفارش به ۸ تغییرِ
    # خودکار کند و تعدادِ اولیه را هم نشان بدهد»): None یعنی انباردار
    # هنوز مقدارِ تحویلی جداگانه‌ای ثبت نکرده -- quantity (مقدارِ اصلیِ
    # سفارش) همچنان مبنا می‌ماند.
    delivered_quantity: decimal.Decimal | None
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
            base_quantity = ln.warehouse_delivered_quantity if ln.warehouse_delivered_quantity is not None else ln.quantity
            result.append(LineFulfillment(
                line_id=ln.line_id, item_id=ln.item_id, uom_id=ln.uom_id, quantity=ln.quantity,
                delivered_quantity=ln.warehouse_delivered_quantity,
                invoiced_quantity=invoiced, remaining_quantity=base_quantity - invoiced,
            ))
        return result


def get_order_fulfillment_summary(document_id: int, company_id: int) -> tuple[decimal.Decimal, decimal.Decimal]:
    """(جمعِ مقدارِ سفارش‌شده، جمعِ مقدارِ تاکنون‌فاکتورشده) — نسخه‌یِ
    سبک‌ترِ get_line_fulfillment، برایِ نمایشِ خلاصه در لیستِ اسناد."""
    fulfillment = get_line_fulfillment(document_id, company_id)
    ordered_total = sum((f.quantity for f in fulfillment), _ZERO)
    invoiced_total = sum((f.invoiced_quantity for f in fulfillment), _ZERO)
    return ordered_total, invoiced_total


def _receipt_locks_quantity(order: CommercialDocument) -> bool:
    """طبقِ درخواستِ صریحِ کاربر («بعدِ تاییدِ رسید توسطِ انباردار، در صدورِ
    فاکتور تعداد قابلِ‌تغییر نباشد -- انبار مسئولِ تعداد است»). R226: همیشه
    فعال (دیگر Toggle نیست -- مقدارِ تاییدشدهٔ انبار در فاکتور قفل است)."""
    # R232: حوالهٔ تاییدشدهٔ سفارشِ فروش هم مقدارِ فاکتور را قفل می‌کند
    return order.document_type_code in ("PURCHASE_ORDER", "SALES_ORDER") and order.warehouse_approved_at is not None \
        and (order.document_type_code == "PURCHASE_ORDER" or order_warehouse_step_enabled(order.company_id, "SALES_ORDER"))


def _locked_line_ids(session, document_id: int) -> set[int]:
    locked = set()
    lines = session.scalars(
        select(CommercialDocumentLine).where(
            CommercialDocumentLine.document_id == document_id, CommercialDocumentLine.source_line_id.is_not(None)
        )
    ).all()
    for ln in lines:
        # زنجیرهٔ مبدا دنبال می‌شود: اصلاحیهٔ فاکتور -> فاکتور -> سفارشِ رسیده (R226)
        source_line_id, depth = ln.source_line_id, 0
        while source_line_id is not None and depth < 6:
            source_line = session.get(CommercialDocumentLine, source_line_id)
            if source_line is None:
                break
            source_doc = session.get(CommercialDocument, source_line.document_id)
            if source_doc is not None and _receipt_locks_quantity(source_doc):
                locked.add(ln.line_id)
                break
            source_line_id, depth = source_line.source_line_id, depth + 1
    return locked


def receipt_locks_quantity(document_id: int, company_id: int) -> bool:
    with new_session() as session:
        doc = session.get(CommercialDocument, document_id)
        return doc is not None and doc.company_id == company_id and _receipt_locks_quantity(doc)


def get_quantity_locked_line_ids(document_id: int, company_id: int) -> set[int]:
    """ردیف‌هایی از این سند که مقدارشان از رسیدِ تاییدشده‌یِ انبار آمده و
    قابلِ‌تغییر/حذف نیست."""
    with new_session() as session:
        doc = session.get(CommercialDocument, document_id)
        if doc is None or doc.company_id != company_id:
            return set()
        return _locked_line_ids(session, document_id)


def convert_to_invoice(
    document_id: int, company_id: int, created_by_user_id: int, document_date: datetime.date,
    line_quantities: dict[int, decimal.Decimal] | None = None,
    line_warehouses: dict[int, int] | None = None,
) -> int:
    """line_warehouses (R226): انبارِ هر ردیفِ فاکتور هنگامِ تبدیل (وقتی سفارش
    انبار/رسید نداشته). طبقِ درخواستِ صریح («تبدیلِ مرحله‌ای»): سفارش/پیش‌فاکتور می‌تواند
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
        # طبقِ درخواستِ صریح («روالِ پخشِ سرد: سفارشِ تصویب‌شده باید اول
        # انبار و توزین را طی کند، بعد تبدیل به فاکتور شود»): این گیت
        # فقط برایِ سفارش‌هایِ کانالِ PRE_SALES بررسی می‌شود.
        if (
            source.document_type_code == "PURCHASE_ORDER" and source.warehouse_approved_at is None
            and settings_service.is_feature_enabled(company_id, "PURCHASE_ORDER_GOODS_RECEIPT")
        ):
            raise ValueError("رسیدِ کالایِ این سفارش هنوز توسطِ انباردار تایید نشده -- ابتدا از «تاییدِ رسیدِ کالا» تایید شود.")
        if (
            source.document_type_code == "SALES_ORDER" and source.warehouse_approved_at is None
            and order_warehouse_step_enabled(company_id, "SALES_ORDER") and not _is_pre_sales_order(session, source)
        ):
            raise ValueError("حوالهٔ انبارِ این سفارش هنوز توسطِ انباردار تایید نشده -- ابتدا از «تاییدِ انبار» تایید شود.")
        if _is_pre_sales_order(session, source):
            if source.warehouse_approved_at is None:
                raise ValueError("این سفارش هنوز تاییدِ انبار نگرفته -- ابتدا از تبِ «تاییدِ انبار و توزین» تایید کنید.")
            if document_requires_weighing(document_id, company_id) and source.weighing_approved_at is None:
                raise ValueError("این سفارش کالایِ توزینی دارد و هنوز توزین/تایید نشده -- ابتدا از تبِ «تاییدِ انبار و توزین» تایید کنید.")
        source_lines = session.scalars(
            select(CommercialDocumentLine).where(CommercialDocumentLine.document_id == document_id).order_by(CommercialDocumentLine.line_no)
        ).all()
        if not source_lines:
            raise ValueError("سند حداقل باید یک ردیف داشته باشد.")
        _validate_line_warehouses(session, company_id, line_warehouses)

        receipt_locked = _receipt_locks_quantity(source)
        line_snapshots = []
        for ln in source_lines:
            # طبقِ درخواستِ صریحِ کاربر (روالِ پخشِ سرد): اگر انباردار
            # مقدارِ واقعیِ تحویلی/توزین‌شده را ثبت کرده باشد (که ممکن
            # است با مقدارِ سفارش‌داده‌شده فرق کند)، فاکتور باید از رویِ
            # همان مقدار ساخته شود، نه مقدارِ اصلیِ سفارش.
            base_quantity = ln.warehouse_delivered_quantity if ln.warehouse_delivered_quantity is not None else ln.quantity
            remaining = base_quantity - _invoiced_quantity(session, ln.line_id)
            if line_quantities is None:
                qty_this_time = remaining
            else:
                qty_this_time = line_quantities.get(ln.line_id, _ZERO)
                if qty_this_time < 0:
                    raise ValueError("مقدار نمی‌تواند منفی باشد.")
                if qty_this_time > remaining:
                    raise ValueError(f"مقدارِ درخواستی برایِ ردیفِ #{ln.line_no} از مانده ({remaining}) بیشتر است.")
                if receipt_locked and 0 < qty_this_time < remaining:
                    raise ValueError(
                        f"مقدارِ ردیفِ #{ln.line_no} توسطِ انباردار تایید شده و قابلِ‌تغییر نیست -- یا کلِ مانده یا هیچ."
                    )
            if qty_this_time <= 0:
                continue
            ratio = qty_this_time / ln.quantity
            line_snapshots.append({
                "item_id": ln.item_id, "uom_id": ln.uom_id, "quantity": qty_this_time, "quantity_base": qty_this_time,
                "unit_price": ln.unit_price, "discount_amount": _money(ln.discount_amount * ratio),
                "discount_percent": ln.discount_percent, "tax_percent": ln.tax_percent,
                "batch_id": ln.batch_id, "serial_id": ln.serial_id, "description": ln.description, "line_id": ln.line_id,
                "warehouse_id": (line_warehouses or {}).get(ln.line_id) or ln.warehouse_id,
            })
        if not line_snapshots:
            raise ValueError("چیزی برایِ تبدیل به فاکتور باقی نمانده است.")

        # طبقِ اصلِ فاکتورِ امانیِ خروجی: کالا فیزیکی نزدِ طرفِ‌حساب است
        # (انبارِ consignment_warehouse_id)، نه انبارِ اصلیِ شرکت -- پس
        # فاکتورِ فروشِ حاصل از تسویه باید دقیقاً از همان انبار کسر کند.
        invoice_warehouse_id = (
            source.consignment_warehouse_id if source.document_type_code == "CONSIGNMENT_OUT" else source.warehouse_id
        )
        if invoice_warehouse_id is None and line_snapshots and line_snapshots[0]["warehouse_id"] is not None:
            invoice_warehouse_id = line_snapshots[0]["warehouse_id"]
        # طبقِ رفعِ باگِ واقعیِ گزارش‌شده: اگر سفارشِ مبدا هیچ‌وقت انباری
        # نداشته (کاربر در هدرِ سفارش انتخاب نکرده بود)، فاکتورِ حاصل
        # هم با انبارِ خالی می‌ماند و بعداً در ثبتِ‌نهایی با خطایِ «انبار
        # الزامی است» رد می‌شد -- درحالی‌که یک انبارِ پیش‌فرض در تنظیماتِ
        # انبار مشخص شده بود و باید همان پیشنهاد می‌شد (کاربر هنوز
        # می‌تواند رویِ هدرِ فاکتور آن را عوض کند).
        if invoice_warehouse_id is None:
            default_warehouse = locations_service.get_default_warehouse(company_id)
            if default_warehouse is not None:
                invoice_warehouse_id = default_warehouse.warehouse_id
        header_fields = DocumentHeaderFields(
            counterparty_detail_account_id=source.counterparty_detail_account_id, currency_id=source.currency_id,
            warehouse_id=invoice_warehouse_id, channel_code=source.channel_code, price_list_id=source.price_list_id,
            source_document_id=source.document_id, exchange_rate=source.exchange_rate,
            sales_rep_detail_account_id=source.sales_rep_detail_account_id,
            cost_center_detail_account_id=source.cost_center_detail_account_id,
            project_detail_account_id=source.project_detail_account_id,
            reference_no=source.reference_no, description=source.description,
            settlement_type_code=source.settlement_type_code, purchase_type_id=source.purchase_type_id,
            branch_id=source.branch_id, org_unit_id=source.org_unit_id,
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
                "conversion_factor": ln.conversion_factor,
                "unit_price": ln.unit_price, "discount_amount": ln.discount_amount, "discount_percent": ln.discount_percent,
                "tax_percent": ln.tax_percent, "batch_id": ln.batch_id, "serial_id": ln.serial_id,
                "description": ln.description, "warehouse_id": ln.warehouse_id, "line_id": ln.line_id,
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
            purchase_type_id=original.purchase_type_id, branch_id=original.branch_id, org_unit_id=original.org_unit_id,
        )
        original_type = original.document_type_code

    new_document_id = create_document(company_id, correcting_user_id, original_type, datetime.date.today(), header_fields)
    for snap in line_snapshots:
        add_line(
            new_document_id, company_id, item_id=snap["item_id"], uom_id=snap["uom_id"], quantity=snap["quantity"],
            quantity_base=snap["quantity_base"], unit_price=snap["unit_price"], discount_amount=snap["discount_amount"],
            discount_percent=snap["discount_percent"], tax_percent=snap["tax_percent"], batch_id=snap["batch_id"],
            serial_id=snap["serial_id"], description=snap["description"], warehouse_id=snap["warehouse_id"],
            conversion_factor=snap["conversion_factor"], source_line_id=snap["line_id"],
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
    for dim_type_id, detail_account_id in _pos_receivable_dims_fallback(company_id, draft.pos_session_id).items():
        extra_dims.setdefault(dim_type_id, detail_account_id)

    # R231: تفصیلیِ کالا/شخص/مرکزِ هزینه/پروژه برایِ ردیف‌هایِ اصلاحی (مثلاً
    # «کالا» الزامی رویِ «مغایرتِ بهایِ استاندارد» یا موجودی).
    corr_item_dim = dimensions_service.get_specialized_dimension_type_id(company_id, dimensions_service.INVENTORY_ITEM_CODE)
    corr_person = (dimensions_service.get_person_dimension_type_id(company_id), counterparty_id)
    with new_session() as session:
        corr_item_details = dict(session.execute(
            select(Item.item_id, Item.item_detail_account_id).where(Item.item_id.in_(all_item_ids))
        ).all()) if all_item_ids else {}

    corr_fixed_details = {
        key: inv_engine_service.get_account_mapping_detail(company_id, key) for key in ("PURCHASE_TAX_RECEIVABLE",)
    }

    def _L(account_id: int, debit, credit, item_id: int | None = None, party: bool = False, role: str | None = None) -> je_service.LineInput:
        return auto_line(
            account_id, description, debit, credit, extra_dims,
            item=(corr_item_dim, corr_item_details.get(item_id)) if item_id is not None else None,
            person=corr_person if party else None,
            fixed_detail_account_id=corr_fixed_details.get(role) if role else None,
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
                adj_je_lines.append(_L(cogs_account_id, result.amount, _ZERO, item_id=item_id))
                adj_je_lines.append(_L(inventory_account_id, _ZERO, result.amount, item_id=item_id))
            else:
                adj_je_lines.append(_L(inventory_account_id, result.amount, _ZERO, item_id=item_id))
                adj_je_lines.append(_L(cogs_account_id, _ZERO, result.amount, item_id=item_id))

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
                    adj_je_lines.append(_L(inventory_account_id, result.amount, _ZERO, item_id=item_id))
                    adj_je_lines.append(_L(payable_account_id, _ZERO, result.amount, item_id=item_id, party=True))
                else:
                    adj_je_lines.append(_L(payable_account_id, result.amount, _ZERO, item_id=item_id, party=True))
                    adj_je_lines.append(_L(inventory_account_id, _ZERO, result.amount, item_id=item_id))
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
                        adj_je_lines.append(_L(inventory_account_id, cost_result.inventory_value_delta, _ZERO, item_id=item_id))
                    if cost_result.variance_value_delta:
                        adj_je_lines.append(_L(variance_account_id, cost_result.variance_value_delta, _ZERO, item_id=item_id))
                    adj_je_lines.append(_L(payable_account_id, _ZERO, total, item_id=item_id, party=True))
                elif total < 0:
                    if cost_result.inventory_value_delta:
                        adj_je_lines.append(_L(inventory_account_id, _ZERO, -cost_result.inventory_value_delta, item_id=item_id))
                    if cost_result.variance_value_delta:
                        adj_je_lines.append(_L(variance_account_id, _ZERO, -cost_result.variance_value_delta, item_id=item_id))
                    adj_je_lines.append(_L(payable_account_id, -total, _ZERO, item_id=item_id, party=True))

            tax_delta = new_tax - old_tax
            if tax_delta != 0:
                tax_account_id = _role_account("PURCHASE_TAX_RECEIVABLE")
                payable_account_id = _role_account("SUPPLIER_PAYABLE")
                if tax_delta > 0:
                    adj_je_lines.append(_L(tax_account_id, tax_delta, _ZERO, item_id=item_id, role="PURCHASE_TAX_RECEIVABLE"))
                    adj_je_lines.append(_L(payable_account_id, _ZERO, tax_delta, item_id=item_id, party=True))
                else:
                    adj_je_lines.append(_L(tax_account_id, _ZERO, -tax_delta, item_id=item_id, role="PURCHASE_TAX_RECEIVABLE"))
                    adj_je_lines.append(_L(payable_account_id, -tax_delta, _ZERO, item_id=item_id, party=True))

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


def _get_editable_document(session, document_id: int, company_id: int) -> CommercialDocument:
    doc = session.get(CommercialDocument, document_id)
    if doc is None or doc.company_id != company_id:
        raise ValueError("سند نامعتبر است.")
    # R226: سفارشِ تاییدشده هم فقط با «بازگشت به پیش‌نویس» ویرایش می‌شود
    # (قبلاً سرویس آن را می‌پذیرفت و ویرایش از دیالوگِ ردیف بی‌صدا ذخیره می‌شد).
    if doc.status_code != "DRAFT":
        if doc.document_type_code in _ORDER_TYPES:
            raise ValueError("سفارشِ تاییدشده قابلِ‌ویرایش نیست -- ابتدا «بازگشت به پیش‌نویس» را بزنید.")
        raise ValueError("فقط سندِ پیش‌نویس قابلِ‌ویرایش است.")
    return doc


def update_document_header(document_id: int, company_id: int, document_date: datetime.date, fields: DocumentHeaderFields) -> None:
    if fields.tax_posting_mode is not None and fields.tax_posting_mode not in ("OFFICIAL", "INFORMAL"):
        raise ValueError("نوعِ ثبتِ سند نامعتبر است.")
    with new_session() as session:
        doc = _get_editable_document(session, document_id, company_id)
        if _was_confirmed(session, document_id):
            for field_name, new in (
                ("document_date", document_date), ("counterparty_detail_account_id", fields.counterparty_detail_account_id),
                ("warehouse_id", fields.warehouse_id), ("requested_delivery_date", fields.requested_delivery_date),
                ("purchase_type_id", fields.purchase_type_id),
            ):
                old = getattr(doc, field_name)
                if new is not None and old != new:
                    _log_change(session, doc, "UPDATE_HEADER", field_name=field_name, old=old, new=new)
        if fields.purchase_type_id is not None:
            doc.purchase_type_id = fields.purchase_type_id
        if fields.branch_id is not None:
            doc.branch_id = fields.branch_id
        elif doc.branch_id is None:
            doc.branch_id = _warehouse_branch(session, fields.warehouse_id)
        if fields.org_unit_id is not None:
            doc.org_unit_id = fields.org_unit_id
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
        if fields.requested_delivery_date is not None:
            doc.requested_delivery_date = fields.requested_delivery_date
        doc.sales_rep_detail_account_id = fields.sales_rep_detail_account_id
        doc.cost_center_detail_account_id = fields.cost_center_detail_account_id
        doc.project_detail_account_id = fields.project_detail_account_id
        doc.reference_no = fields.reference_no or None
        doc.description = fields.description or None
        doc.tax_posting_mode = fields.tax_posting_mode
        doc.settlement_type_code = fields.settlement_type_code
        session.commit()


def set_tax_exempt(document_id: int, company_id: int, tax_exempt: bool) -> None:
    """طبقِ درخواستِ صریح («امکانِ کنسل‌کردنِ مالیات رویِ فاکتور»): روشن‌کردنِ
    این پرچم بلافاصله مالیاتِ همه‌یِ ردیف‌هایِ ازپیش‌ثبت‌شده را هم صفر
    می‌کند (نه فقط ردیف‌هایِ بعدی) -- چون «کنسل‌کردنِ مالیاتِ فاکتور»
    یعنی کلِ فاکتور، نه فقط ردیف‌هایِ آینده‌اش. خاموش‌کردن، خودش مالیاتِ
    قبلی را بازنمی‌گرداند (چون آن مقدار دیگر نگه‌داری نشده) -- کاربر
    باید مالیاتِ لازم را دوباره رویِ ردیف‌ها وارد کند."""
    with new_session() as session:
        doc = _get_editable_document(session, document_id, company_id)
        doc.tax_exempt = tax_exempt
        if tax_exempt:
            lines = session.scalars(
                select(CommercialDocumentLine).where(CommercialDocumentLine.document_id == document_id)
            ).all()
            for line in lines:
                line.tax_percent = _ZERO
                line.tax_amount = _ZERO
            session.flush()
            _recompute_header_totals(session, document_id)
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


@dataclass
class DocumentSummary:
    document_count: int
    total_amount: decimal.Decimal


def summarize_documents_for_user_on_date(
    company_id: int, created_by_user_id: int, document_date: datetime.date, document_type_codes: tuple[str, ...],
    channel_type_code: str | None = None,
) -> DocumentSummary:
    """جمعِ تعداد/مبلغِ اسنادِ ثبت‌شده‌یِ یک کاربر در یک روز -- برایِ
    داشبوردِ خانه‌یِ اپِ موبایل («سفارشِ امروز»/«فروشِ امروز»، R135).
    اسنادِ لغوشده جزوِ فروشِ واقعی نیستند. channel_type_code (طبقِ
    «پخشِ سرد و گرم کاملاً مجزا باشند») فقط اسنادِ همان نوعِ کانال را
    حساب می‌کند -- هم‌الگو با list_documents."""
    with new_session() as session:
        stmt = select(func.count(), func.coalesce(func.sum(CommercialDocument.total_amount), 0)).where(
            CommercialDocument.company_id == company_id,
            CommercialDocument.created_by_user_id == created_by_user_id,
            CommercialDocument.document_date == document_date,
            CommercialDocument.document_type_code.in_(document_type_codes),
            CommercialDocument.status_code != "CANCELLED",
        )
        if channel_type_code:
            stmt = stmt.join(
                Channel, (Channel.channel_code == CommercialDocument.channel_code) & (Channel.company_id == CommercialDocument.company_id)
            ).where(Channel.channel_type_code == channel_type_code)
        count, total = session.execute(stmt).one()
        return DocumentSummary(document_count=count, total_amount=total or decimal.Decimal(0))


def summarize_documents_for_company(
    company_id: int, date_from: datetime.date, date_to: datetime.date, document_type_codes: tuple[str, ...],
    created_by_user_id: int | None = None, route_detail_account_id: int | None = None,
) -> DocumentSummary:
    """هم‌الگو با summarize_documents_for_user_on_date ولی برایِ بازهٔ
    تاریخ (نه یک روز) و بدونِ الزامِ فیلترِ کاربر -- برایِ داشبوردِ
    مدیریتی (Phase 7): «فروشِ ماه» (created_by_user_id=None، همهٔ
    شرکت) یا «عملکردِ فلان ویزیتور» (created_by_user_id مشخص).
    route_detail_account_id (طبقِ R189) با joinِ
    CustomerProfile.distribution_route_detail_account_id رویِ
    counterparty_detail_account_idِ سند اعمال می‌شود."""
    with new_session() as session:
        stmt = select(func.count(), func.coalesce(func.sum(CommercialDocument.total_amount), 0)).where(
            CommercialDocument.company_id == company_id,
            CommercialDocument.document_date >= date_from,
            CommercialDocument.document_date <= date_to,
            CommercialDocument.document_type_code.in_(document_type_codes),
            CommercialDocument.status_code != "CANCELLED",
        )
        if created_by_user_id is not None:
            stmt = stmt.where(CommercialDocument.created_by_user_id == created_by_user_id)
        if route_detail_account_id is not None:
            stmt = stmt.join(
                CustomerProfile, CustomerProfile.customer_detail_account_id == CommercialDocument.counterparty_detail_account_id,
            ).where(CustomerProfile.distribution_route_detail_account_id == route_detail_account_id)
        count, total = session.execute(stmt).one()
        return DocumentSummary(document_count=count, total_amount=total or decimal.Decimal(0))


def list_document_creators(
    company_id: int, date_from: datetime.date, date_to: datetime.date, document_type_codes: tuple[str, ...],
) -> list[int]:
    """شناسه‌یِ کاربرانی که در این بازه حداقل یک سندِ فروش ثبت کرده‌اند --
    برایِ ساختِ فهرستِ «عملکردِ ویزیتورها» (Phase 7) بدونِ نیازِ حدسِ
    از قبلِ کدامین کاربر ویزیتور است."""
    with new_session() as session:
        rows = session.scalars(
            select(CommercialDocument.created_by_user_id)
            .where(
                CommercialDocument.company_id == company_id,
                CommercialDocument.document_date >= date_from,
                CommercialDocument.document_date <= date_to,
                CommercialDocument.document_type_code.in_(document_type_codes),
                CommercialDocument.status_code != "CANCELLED",
            )
            .distinct()
        ).all()
        return list(rows)


@dataclass
class TopProductRow:
    item_id: int
    total_quantity: decimal.Decimal
    total_amount: decimal.Decimal


@dataclass
class CustomerPurchaseSummary:
    last_purchase_date: datetime.date | None
    top_products: list[TopProductRow]


def summarize_customer_purchases(
    company_id: int, customer_detail_account_id: int, top_n: int = 5,
) -> CustomerPurchaseSummary:
    """آخرین تاریخِ خرید + پرفروش‌ترین کالاهایِ یک مشتری -- برایِ صفحه‌یِ
    جزئیاتِ مشتریِ اپِ موبایل (Phase 2/UI-2). فقط فاکتورهایِ POSTED
    (لغوشده/پیش‌نویس معیارِ خریدِ واقعی نیستند)."""
    with new_session() as session:
        last_purchase_date = session.scalar(
            select(func.max(CommercialDocument.document_date)).where(
                CommercialDocument.company_id == company_id,
                CommercialDocument.counterparty_detail_account_id == customer_detail_account_id,
                CommercialDocument.document_type_code == "SALES_INVOICE",
                CommercialDocument.status_code == "POSTED",
            )
        )
        top_rows = session.execute(
            select(
                CommercialDocumentLine.item_id,
                func.sum(CommercialDocumentLine.quantity_base),
                func.sum(CommercialDocumentLine.line_total),
            )
            .join(CommercialDocument, CommercialDocument.document_id == CommercialDocumentLine.document_id)
            .where(
                CommercialDocument.company_id == company_id,
                CommercialDocument.counterparty_detail_account_id == customer_detail_account_id,
                CommercialDocument.document_type_code == "SALES_INVOICE",
                CommercialDocument.status_code == "POSTED",
            )
            .group_by(CommercialDocumentLine.item_id)
            .order_by(func.sum(CommercialDocumentLine.quantity_base).desc())
            .limit(top_n)
        ).all()
        return CustomerPurchaseSummary(
            last_purchase_date=last_purchase_date,
            top_products=[TopProductRow(item_id=r[0], total_quantity=r[1], total_amount=r[2]) for r in top_rows],
        )


_SEGMENT_LABELS_FA = {
    "NEW": "مشتریِ جدید", "ACTIVE": "فعال", "LOYAL": "وفادار", "LOW_PURCHASE": "کم‌خرید",
    "AT_RISK": "در معرضِ ریزش", "INACTIVE": "غیرفعال", "DEBTOR": "بدهکار", "VIP": "VIP",
}


@dataclass
class CustomerSegmentInfo:
    segment_code: str
    sales_this_month: decimal.Decimal
    sales_last_3_months: decimal.Decimal
    order_count_last_12_months: int
    avg_order_value: decimal.Decimal
    avg_days_between_orders: decimal.Decimal | None
    balance_amount: decimal.Decimal
    balance_nature: str
    return_percent: decimal.Decimal
    estimated_profit_last_3_months: decimal.Decimal


def compute_customer_segment(company_id: int, customer_detail_account_id: int) -> CustomerSegmentInfo:
    """طبقِ بازبینیِ ساختارِ «تعریفِ مشتری» (R219، بخشِ ۱۳ -- امتیازدهی/
    سگمنت‌بندی): همیشه محاسبه‌شده از دادهٔ واقعیِ فروش/دریافت -- هیچ
    فیلدِ ذخیره‌شده‌ای ندارد که بتواند با واقعیت ناهم‌گام شود. آستانه‌ها
    (۳۰/۹۰/۱۸۰ روز، ۱۰ سفارش برایِ «وفادار») تصمیمِ ابتداییِ معقول‌اند --
    اگر شرکت آستانه‌یِ دیگری بخواهد، تنظیم‌پذیر شدنشان کارِ آینده است."""
    today = datetime.date.today()
    month_start = today.replace(day=1)
    d90 = today - datetime.timedelta(days=90)
    d365 = today - datetime.timedelta(days=365)
    with new_session() as session:
        base_filter = (
            CommercialDocument.company_id == company_id,
            CommercialDocument.counterparty_detail_account_id == customer_detail_account_id,
            CommercialDocument.document_type_code == "SALES_INVOICE",
            CommercialDocument.status_code == "POSTED",
        )
        sales_this_month = session.scalar(
            select(func.coalesce(func.sum(CommercialDocument.total_amount), 0)).where(
                *base_filter, CommercialDocument.document_date >= month_start
            )
        )
        sales_last_3_months = session.scalar(
            select(func.coalesce(func.sum(CommercialDocument.total_amount), 0)).where(
                *base_filter, CommercialDocument.document_date >= d90
            )
        )
        year_rows = session.execute(
            select(CommercialDocument.document_date, CommercialDocument.total_amount).where(
                *base_filter, CommercialDocument.document_date >= d365
            ).order_by(CommercialDocument.document_date)
        ).all()
        first_order_date = session.scalar(
            select(func.min(CommercialDocument.document_date)).where(*base_filter)
        )
        last_order_date = session.scalar(
            select(func.max(CommercialDocument.document_date)).where(*base_filter)
        )
        returned_amount = session.scalar(
            select(func.coalesce(func.sum(CommercialDocument.total_amount), 0)).where(
                CommercialDocument.company_id == company_id,
                CommercialDocument.counterparty_detail_account_id == customer_detail_account_id,
                CommercialDocument.document_type_code == "SALES_RETURN",
                CommercialDocument.status_code == "POSTED",
                CommercialDocument.document_date >= d365,
            )
        )
        last_3m_lines = session.execute(
            select(CommercialDocumentLine.item_id, CommercialDocumentLine.quantity_base, CommercialDocumentLine.line_total)
            .join(CommercialDocument, CommercialDocument.document_id == CommercialDocumentLine.document_id)
            .where(*base_filter, CommercialDocument.document_date >= d90)
        ).all()

    order_count = len(year_rows)
    avg_order_value = (sum((r[1] for r in year_rows), decimal.Decimal(0)) / order_count) if order_count else decimal.Decimal(0)
    avg_days_between_orders = None
    if order_count >= 2:
        dates = [r[0] for r in year_rows]
        gaps = [(dates[i + 1] - dates[i]).days for i in range(len(dates) - 1)]
        avg_days_between_orders = decimal.Decimal(sum(gaps)) / len(gaps)
    gross_sales_last_365 = sum((r[1] for r in year_rows), decimal.Decimal(0))
    return_percent = (returned_amount / gross_sales_last_365 * 100) if gross_sales_last_365 else decimal.Decimal(0)

    # طبقِ بازبینیِ ساختارِ «تعریفِ مشتری» (R219، بخشِ ۱۸ -- «سود» در
    # داشبوردِ بالایِ فرم): برآوردِ سودِ ناخالص با آخرین بهایِ شناخته‌شدهٔ
    # هر کالا -- تقریبی است، نه سودِ دقیقِ حسابداری‌شده در لحظه‌یِ همان
    # فروش (که نیازمندِ اتصال به آرتیکل‌هایِ واقعیِ COGSِ دفترِ روزنامه
    # است، فراتر از این گزارشِ خلاصه).
    _cost_cache: dict[int, decimal.Decimal] = {}
    estimated_profit_last_3_months = decimal.Decimal(0)
    for item_id, qty, line_total in last_3m_lines:
        if item_id not in _cost_cache:
            cost = inv_engine_service.get_last_known_unit_cost(item_id)
            _cost_cache[item_id] = cost if cost is not None else decimal.Decimal(0)
        estimated_profit_last_3_months += line_total - (_cost_cache[item_id] * qty)

    balance_amount, balance_nature = treasury_service.get_counterparty_balance(company_id, customer_detail_account_id)
    is_debtor = balance_nature == "بدهکار" and balance_amount > 0

    if first_order_date is None:
        segment_code = "NEW"
    elif is_debtor and balance_amount > (avg_order_value * 3 if avg_order_value else decimal.Decimal(0)):
        # طبقِ اصلِ صریح («اگر اعتبار ۵۰ میلیون بوده، بدهی ۸۰ میلیون شده،
        # آیا نباید تاثیری داشته باشه؟» -- sales_assistant.py، همان روح):
        # بدهیِ نامتناسب با حجمِ خریدِ عادی، مهم‌تر از سگمنت‌هایِ رفتاری است.
        segment_code = "DEBTOR"
    elif last_order_date is not None and (today - first_order_date).days <= 30:
        segment_code = "NEW"
    elif last_order_date is not None and (today - last_order_date).days <= 30 and order_count >= 10:
        segment_code = "LOYAL"
    elif last_order_date is not None and (today - last_order_date).days <= 30:
        segment_code = "ACTIVE"
    elif last_order_date is not None and (today - last_order_date).days <= 90:
        segment_code = "AT_RISK" if order_count >= 3 else "LOW_PURCHASE"
    elif last_order_date is not None and (today - last_order_date).days <= 180:
        segment_code = "AT_RISK"
    else:
        segment_code = "INACTIVE"

    return CustomerSegmentInfo(
        segment_code=segment_code, sales_this_month=sales_this_month or 0, sales_last_3_months=sales_last_3_months or 0,
        order_count_last_12_months=order_count, avg_order_value=avg_order_value,
        avg_days_between_orders=avg_days_between_orders, balance_amount=balance_amount, balance_nature=balance_nature,
        return_percent=return_percent, estimated_profit_last_3_months=estimated_profit_last_3_months,
    )


def list_documents(
    company_id: int, document_type_code: str | None = None, status_code: str | None = None,
    counterparty_detail_account_id: int | None = None, limit: int | None = None,
    pos_session_id: int | None = None, channel_type_code: str | None = None,
) -> list[CommercialDocument]:
    with new_session() as session:
        stmt = select(CommercialDocument).where(CommercialDocument.company_id == company_id)
        if document_type_code:
            stmt = stmt.where(CommercialDocument.document_type_code == document_type_code)
        if status_code:
            stmt = stmt.where(CommercialDocument.status_code == status_code)
        if counterparty_detail_account_id is not None:
            stmt = stmt.where(CommercialDocument.counterparty_detail_account_id == counterparty_detail_account_id)
        if pos_session_id is not None:
            stmt = stmt.where(CommercialDocument.pos_session_id == pos_session_id)
        if channel_type_code:
            # طبقِ درخواستِ صریح («در منویِ فروشِ اینترنتی فقط سفارش‌هایِ
            # فروشِ مشتری بیاید»): سندی که channel_code ندارد اصلاً کانالِ
            # اینترنتی محسوب نمی‌شود -- پس join به‌جایِ outerjoin.
            stmt = stmt.join(
                Channel, (Channel.channel_code == CommercialDocument.channel_code) & (Channel.company_id == CommercialDocument.company_id)
            ).where(Channel.channel_type_code == channel_type_code)
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
    conversion_factor: decimal.Decimal | None = None, expected_delivery_date: datetime.date | None = None,
    purchase_request_line_id: int | None = None, rfq_quote_id: int | None = None,
) -> int:
    if quantity <= 0 or quantity_base <= 0:
        raise ValueError("مقدار باید بزرگ‌تر از صفر باشد.")
    # سیستمِ واحد (R225): موجودی همیشه به واحدِ پایه است؛ مقدارِ پایه همین‌جا
    # (نه از فراخوان -- مثلاً موبایل) با ضریبِ واحد محاسبه و ضریب در ردیف
    # snapshot می‌شود تا تغییرِ بعدیِ ضریب اسنادِ قبلی را عوض نکند. ردیفِ
    # کپی‌شده از سندِ مبدا (تبدیل/اصلاح) ضریبِ همان ردیفِ مبدا را نگه می‌دارد.
    if conversion_factor is None and source_line_id is not None:
        with new_session() as session:
            source_line = session.get(CommercialDocumentLine, source_line_id)
            if source_line is not None and source_line.uom_id == uom_id:
                conversion_factor = source_line.conversion_factor
    if conversion_factor is None:
        with new_session() as session:
            doc_row = session.get(CommercialDocument, document_id)
            doc_type = doc_row.document_type_code if doc_row is not None else None
        uc.validate_quantity(item_id, uom_id, quantity, purpose=uc.purpose_for_document_type(doc_type))
        conversion_factor = uc.get_factor(item_id, uom_id, require_active=True)
    quantity_base = quantity * conversion_factor
    with new_session() as session:
        doc = _get_editable_document(session, document_id, company_id)
        # طبقِ درخواستِ صریح («امکانِ کنسل‌کردنِ مالیات رویِ فاکتور»): وقتی
        # سند معاف از مالیات علامت‌گذاری شده، هیچ ردیفِ تازه‌ای -- صرفِ‌نظر
        # از درصدِ رسیده از پارامتر/سیاستِ اولویتی -- نباید مالیات بگیرد.
        if doc.tax_exempt:
            tax_percent = _ZERO
        # طبقِ درخواستِ صریح («کالایِ اصلیِ دارایِ متغیر نباید مستقیم در
        # سند ثبت شود»، خرید و فروش هردو): این چک قبلاً فقط در UIِ
        # commercial_document.py (کمبویِ کالا/دیالوگِ ردیف) رعایت
        # می‌شد -- خودِ سرویس هیچ راهِ مستقلی برایِ جلوگیری نداشت، پس هر
        # مسیرِ دیگری (بای‌پاسِ UI، API، وارداتِ گروهی) می‌توانست کالایِ
        # اصلی را مستقیم ثبت کند. حالا این محدودیت مستقلاً در خودِ
        # سرویس هم اعمال می‌شود -- برایِ همه‌یِ انواعِ سند (خرید/فروش)
        # یکسان.
        has_variants = session.scalar(
            select(func.count()).select_from(Item).where(Item.variant_parent_item_id == item_id)
        )
        if has_variants:
            raise ValueError(
                "این کالا دارایِ چند متغیر است؛ نمی‌تواند مستقیم در سند ثبت شود -- یکی از متغیرهایش را انتخاب کنید."
            )
        # طبقِ گزارشِ صریحِ کاربر («در ثبتِ سفارشات آپشنی داشته باشه که
        # بتونیم کالای عدم موجودی را ثبت کنیم یا نتوانیم»): این آپشن
        # همان تنظیمِ ازپیش‌موجودِ هر انبار (allow_negative_stock) است --
        # که سندهایِ واقعاً موجودی‌کاهنده (فاکتور/رسیدِ انبار) از قبل
        # رعایتش می‌کنند، ولی سفارش/پیش‌فاکتور چون هرگز به inventory_
        # engine نمی‌رسند (Postشان فقط قفل‌کردنِ سند است، بدونِ اثرِ
        # انبار)، تا الان هیچ‌وقت این تنظیم را چک نمی‌کردند -- یعنی
        # همیشه امکانِ ثبتِ کالایِ بدونِ موجودی وجود داشت. حالا همان
        # انبارِ مؤثرِ همین ردیف (warehouse_id ردیف یا، اگر خالی بود،
        # انبارِ پیش‌فرضِ سرِسند) چک می‌شود.
        if doc.document_type_code in ("SALES_ORDER", "SALES_PROFORMA"):
            effective_warehouse_id = warehouse_id or doc.warehouse_id
            if effective_warehouse_id is not None:
                warehouse = locations_service.get_warehouse(effective_warehouse_id, company_id)
                if warehouse is not None and not warehouse.fields.allow_negative_stock:
                    on_hand = next(
                        (r.quantity_on_hand for r in inv_engine_service.get_item_stock_by_warehouse(company_id, item_id)
                         if r.warehouse_id == effective_warehouse_id),
                        decimal.Decimal(0),
                    )
                    existing_lines = session.scalars(
                        select(CommercialDocumentLine).where(
                            CommercialDocumentLine.document_id == document_id,
                            CommercialDocumentLine.item_id == item_id,
                        )
                    ).all()
                    existing_qty = sum(
                        (ln.quantity_base for ln in existing_lines if (ln.warehouse_id or doc.warehouse_id) == effective_warehouse_id),
                        decimal.Decimal(0),
                    )
                    if existing_qty + quantity_base > on_hand:
                        raise ValueError(
                            f"موجودیِ این کالا در انبارِ انتخاب‌شده کافی نیست "
                            f"(موجود: {on_hand}، قبلاً در همین سند: {existing_qty}، درخواستی: {quantity_base}) -- "
                            "طبقِ تنظیمِ این انبار، ثبتِ سفارش/پیش‌فاکتورِ بیش از موجودی مجاز نیست."
                        )
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
            quantity_base=quantity_base, conversion_factor=conversion_factor, unit_price=unit_price, discount_amount=discount_amount,
            discount_percent=discount_percent, tax_percent=tax_percent, tax_amount=tax_amount,
            batch_id=batch_id, serial_id=serial_id,
            source_line_id=source_line_id, description=(description or None), warehouse_id=warehouse_id,
            expected_delivery_date=expected_delivery_date, purchase_request_line_id=purchase_request_line_id,
            rfq_quote_id=rfq_quote_id,
        )
        session.add(line)
        session.flush()
        if _was_confirmed(session, document_id):
            _log_change(session, doc, "ADD_LINE", line_id=line.line_id, field_name="quantity", new=quantity)
        _recompute_header_totals(session, document_id)
        session.commit()
        return line.line_id


def update_line(
    line_id: int, document_id: int, company_id: int, quantity: decimal.Decimal, unit_price: decimal.Decimal,
    discount_amount: decimal.Decimal = _ZERO, discount_percent: decimal.Decimal = _ZERO,
    tax_percent: decimal.Decimal = _ZERO, description: str | None | object = ...,
    expected_delivery_date: datetime.date | None | object = ...,
) -> None:
    """طبقِ درخواستِ صریحِ کاربر («در همان ردیف تعداد و قیمت و تخفیف و
    مالیات را وارد کرد»): برایِ ویرایشِ زنده/درجایِ یک ردیفِ ازپیش‌ذخیره‌شده
    مستقیماً در جدول -- برخلافِ الگویِ قدیمیِ حذف+افزودنِ دوباره (که
    line_no را همیشه به آخرِ سند می‌انداخت، چون add_line همیشه
    line_no=max+1 می‌دهد؛ برایِ ویرایشِ زنده که با هر خروج از هر فیلد
    فوراً commit می‌شود، این جابه‌جاییِ ردیف بسیار مزاحم/گیج‌کننده
    می‌بود)، این تابع فقط مقادیرِ عددیِ همین ردیف را درجا به‌روزرسانی
    می‌کند -- ترتیبِ ردیف‌ها دست‌نخورده می‌ماند."""
    if quantity <= 0:
        raise ValueError("مقدار باید بزرگ‌تر از صفر باشد.")
    with new_session() as session:
        doc = _get_editable_document(session, document_id, company_id)
        if doc.tax_exempt:
            tax_percent = _ZERO
        line = session.get(CommercialDocumentLine, line_id)
        if line is None or line.document_id != document_id:
            raise ValueError("ردیف نامعتبر است.")
        if quantity != line.quantity and line_id in _locked_line_ids(session, document_id):
            raise ValueError("مقدارِ این ردیف را انباردار در رسیدِ کالا تایید کرده -- قابلِ‌تغییر نیست.")
        # طبقِ صحتِ ردگیریِ تبدیل‌شدنِ سفارش به فاکتور/رسیدِ انبار: کاهشِ
        # مقدار به کمتر از مقدارِ قبلاً دریافت‌شده/فاکتورشده، آن ردگیری
        # را به یک عددِ منفیِ بی‌معنا می‌رساند -- هم‌الگو با بررسیِ
        # source_line_id در delete_line بالاتر.
        if line.invoiced_quantity_total and quantity < line.invoiced_quantity_total:
            raise ValueError(
                f"مقدارِ این ردیف نمی‌تواند کمتر از مقدارِ قبلاً فاکتورشده ({line.invoiced_quantity_total}) باشد."
            )
        if line.received_quantity_total and quantity < line.received_quantity_total:
            raise ValueError(
                f"مقدارِ این ردیف نمی‌تواند کمتر از مقدارِ قبلاً دریافت‌شده ({line.received_quantity_total}) باشد."
            )
        gross_amount = quantity * unit_price
        if discount_percent:
            discount_amount = _money(gross_amount * (discount_percent / 100))
        net_amount = gross_amount - discount_amount
        tax_amount = _money(net_amount * (tax_percent / 100)) if tax_percent and net_amount > 0 else _ZERO
        if _was_confirmed(session, document_id):
            for field_name, old, new in (
                ("quantity", line.quantity, quantity), ("unit_price", line.unit_price, unit_price),
                ("discount_amount", line.discount_amount, discount_amount), ("tax_percent", line.tax_percent, tax_percent),
            ):
                if old != new:
                    _log_change(session, doc, "UPDATE_LINE", line_id=line_id, field_name=field_name, old=old, new=new)
        if expected_delivery_date is not ...:
            line.expected_delivery_date = expected_delivery_date
        line.quantity = quantity
        if quantity != line.quantity:
            uc.validate_quantity(line.item_id, line.uom_id, quantity, check_min_max=False, require_active=False)
        line.quantity_base = quantity * line.conversion_factor
        line.unit_price = unit_price
        line.discount_amount = discount_amount
        line.discount_percent = discount_percent
        line.tax_percent = tax_percent
        line.tax_amount = tax_amount
        if description is not ...:
            line.description = description or None
        session.flush()
        _recompute_header_totals(session, document_id)
        session.commit()


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
        if line_id in _locked_line_ids(session, document_id):
            raise ValueError("مقدارِ این ردیف را انباردار در رسیدِ کالا تایید کرده -- قابلِ‌حذف نیست.")
        if _was_confirmed(session, document_id):
            deleted = session.get(CommercialDocumentLine, line_id)
            doc = session.get(CommercialDocument, document_id)
            _log_change(session, doc, "DELETE_LINE", line_id=line_id, field_name="quantity",
                        old=deleted.quantity if deleted is not None else None)
        session.query(CommercialDocumentLine).filter(CommercialDocumentLine.line_id == line_id).delete()
        _recompute_header_totals(session, document_id)
        session.commit()


def update_document_dimensions(
    document_id: int, company_id: int, cost_center_detail_account_id: int | None,
    project_detail_account_id: int | None,
) -> None:
    """R226: مرکزِ هزینه/پروژه پس از تایید (تا پیش از ثبتِ نهایی) هم قابلِ‌تکمیل
    است -- فقط این دو فیلد؛ بقیهٔ هدر همچنان فقط در پیش‌نویس."""
    with new_session() as session:
        doc = session.get(CommercialDocument, document_id)
        if doc is None or doc.company_id != company_id:
            raise ValueError("سند نامعتبر است.")
        if doc.status_code not in ("DRAFT", "CONFIRMED", "APPROVED"):
            raise ValueError("مرکزِ هزینه/پروژهٔ سندِ ثبت‌شده/لغوشده قابلِ‌تغییر نیست.")
        doc.cost_center_detail_account_id = cost_center_detail_account_id
        doc.project_detail_account_id = project_detail_account_id
        session.commit()


def can_delete_document(doc) -> bool:
    """فاکتور/برگشتِ تاییدشده حذف نمی‌شود، فقط لغو (R226)."""
    if doc.status_code in ("POSTED", "CORRECTED"):
        return False
    if doc.document_type_code in _INVOICE_TYPES + ("SALES_RETURN", "PURCHASE_RETURN") and doc.status_code != "DRAFT":
        return False
    return True


def delete_document(document_id: int, company_id: int) -> None:
    with new_session() as session:
        doc = session.get(CommercialDocument, document_id)
        if doc is None or doc.company_id != company_id:
            raise ValueError("سند نامعتبر است.")
        if doc.status_code not in ("POSTED", "CORRECTED") and not can_delete_document(doc):
            raise ValueError("فاکتورِ تاییدشده حذف نمی‌شود -- آن را «لغو» کنید یا به پیش‌نویس برگردانید.")
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
    # نقشهٔ تسویهٔ پیش‌نویس هم حذف می‌شود؛ هر وابستگیِ دیگر به‌جایِ خطایِ خامِ
    # پایگاه‌داده (که در UI بی‌صدا گم می‌شد) پیامِ روشن می‌دهد.
    settlements_service.delete_settlement_plan(document_id, company_id)
    with new_session() as session:
        doc = session.get(CommercialDocument, document_id)
        session.query(CreditHold).filter(CreditHold.related_document_id == document_id).delete()
        session.query(CommercialDocumentLine).filter(CommercialDocumentLine.document_id == document_id).delete()
        session.delete(doc)
        try:
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            raise ValueError("این سند به سوابقِ دیگری (تسویه/تحویل/...) وابسته است و حذف نمی‌شود -- آن را «لغو» کنید.") from exc


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
        # طبقِ رفعِ باگِ واقعیِ گزارش‌شده («سندِ بن‌بست»): قبلاً هیچ‌جا
        # پیش از ثبتِ‌نهایی بررسی نمی‌شد که سندهایِ فروش/خرید/برگشت
        # (که به‌صورتِ خودکار یک سندِ انبار می‌سازند) واقعاً یک انبار
        # دارند یا نه — کاربر بدونِ هیچ پیامی تایید می‌کرد، و فقط در
        # لحظه‌یِ ثبتِ‌نهایی (وقتی دیگر فیلدِ انبار قابلِ‌ویرایش نیست)
        # با خطایِ «انبارِ مبدا/مقصد الزامی است» رد می‌شد — سند برایِ
        # همیشه در وضعیتِ تاییدشده گیر می‌کرد. حالا همین‌جا، پیش از
        # تایید: اگر هدر انبار ندارد، اول انبارِ پیش‌فرضِ شرکت (تنظیماتِ
        # انبار) به‌کار می‌رود؛ اگر آن هم تنظیم نشده، همین‌جا با پیامی
        # روشن رد می‌شود تا کاربر بتواند همین حالا (وقتی هنوز پیش‌نویس
        # و کاملاً قابلِ‌ویرایش است) انبار را انتخاب کند.
        if doc.document_type_code in _STOCK_DOC_TYPE_BY_TYPE and doc.warehouse_id is None:
            default_warehouse = locations_service.get_default_warehouse(company_id)
            if default_warehouse is not None:
                doc.warehouse_id = default_warehouse.warehouse_id
            else:
                raise ValueError(
                    "انبار مشخص نشده و انبارِ پیش‌فرضِ شرکت هم در تنظیماتِ انبار تعیین نشده — "
                    "لطفاً یک انبار انتخاب کنید یا انبارِ پیش‌فرض را در تنظیماتِ انبار مشخص کنید."
                )
        doc.status_code = "CONFIRMED"
        _log_status(session, doc, "DRAFT", confirmed_by_user_id)
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


def approve_document(document_id: int, company_id: int, approved_by_user_id: int | None = None) -> None:
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
        doc.approved_by_user_id = _actor(approved_by_user_id)
        doc.approved_at = datetime.datetime.now()
        _log_status(session, doc, "CONFIRMED", approved_by_user_id)
        session.commit()


# ---------------------------------------------------------------------
# روالِ پخشِ سرد — طبقِ درخواستِ صریحِ کاربر: سفارش (از همان لحظه‌یِ
# ثبتِ‌نهایی/تاییدِ کاربر -- CONFIRMED؛ تصویبِ مدیرِ APPROVED هم اگر
# جداگانه انجام شود پذیرفته می‌شود، ولی اجباری نیست) باید قبل از تبدیل
# به فاکتور، هم‌زمان از تاییدِ انبار و (اگر کالایِ توزینی داشت) تاییدِ
# توزین عبور کند. طبقِ رفعِ باگِ واقعیِ گزارش‌شده («سفارشات را در قسمتِ
# توزین/تاییدِ انبار نمی‌آورد»): این گیت قبلاً فقط سفارشِ APPROVED را
# می‌پذیرفت -- درحالی‌که در روالِ واقعیِ کاربر، سفارش‌هایِ پخشِ سرد اغلب
# بعدِ تاییدِ کاربر (CONFIRMED) مستقیماً به انبار می‌روند، بدونِ کلیکِ
# جداگانه‌یِ «تصویبِ مدیر». این دو گیت فقط برایِ سفارش‌هایِ کانالِ
# PRE_SALES بررسی می‌شوند -- برایِ بقیه‌یِ کانال‌ها/انواعِ سند بدونِ اثر.
# ---------------------------------------------------------------------
_PRE_SALES_FULFILLMENT_ELIGIBLE_STATUSES = ("CONFIRMED", "APPROVED")
def _is_pre_sales_order(session, doc: CommercialDocument) -> bool:
    if doc.document_type_code != "SALES_ORDER" or doc.channel_code is None:
        return False
    channel = session.get(Channel, (doc.channel_code, doc.company_id))
    return channel is not None and channel.channel_type_code == "PRE_SALES"


# R232: تنظیماتِ گردشِ کارِ انبارِ سفارش، برایِ خرید و فروش هم‌تراز
_ORDER_WAREHOUSE_TOGGLES = {
    "PURCHASE_ORDER": ("PURCHASE_ORDER_GOODS_RECEIPT", "PURCHASE_ORDER_SKIP_POST"),
    "SALES_ORDER": ("SALES_ORDER_WAREHOUSE_ISSUE", "SALES_ORDER_SKIP_POST"),
}


def order_warehouse_step_enabled(company_id: int, document_type_code: str) -> bool:
    """رسیدِ انبارِ سفارشِ خرید / حوالهٔ انبارِ سفارشِ فروش توسطِ انباردار روشن است؟"""
    toggles = _ORDER_WAREHOUSE_TOGGLES.get(document_type_code)
    return toggles is not None and settings_service.is_feature_enabled(company_id, toggles[0])


def requires_manager_approval(company_id: int, document_type_code: str) -> bool:
    """R232: تصویبِ مدیر پیش از ثبتِ نهایی -- خرید پیش‌فرض روشن (قابلِ‌حذف)، فروش پیش‌فرض خاموش."""
    if document_type_code == "PURCHASE_ORDER":
        return not settings_service.is_feature_enabled(company_id, "PURCHASE_ORDER_SKIP_APPROVAL")
    if document_type_code in ("PURCHASE_INVOICE", "PURCHASE_PROFORMA"):
        return not settings_service.is_feature_enabled(company_id, "PURCHASE_INVOICE_SKIP_APPROVAL")
    if document_type_code == "SALES_ORDER":
        return settings_service.is_feature_enabled(company_id, "SALES_ORDER_MANAGER_APPROVAL")
    if document_type_code in ("SALES_INVOICE", "SALES_PROFORMA"):
        return settings_service.is_feature_enabled(company_id, "SALES_INVOICE_MANAGER_APPROVAL")
    return False


def receipt_eligible_statuses(company_id: int, document_type_code: str) -> tuple[str, ...]:
    """R230: سفارشِ خرید فقط پس از «ثبتِ نهایی» به تاییدِ رسیدِ انبار می‌رسد -- مگر
    مرحلهٔ ثبتِ نهاییِ سفارش در تنظیمات (PURCHASE_ORDER_SKIP_POST) حذف شده باشد.
    R232: سفارشِ فروش با حوالهٔ انبار هم به همین شکل (SALES_ORDER_SKIP_POST)."""
    toggles = _ORDER_WAREHOUSE_TOGGLES.get(document_type_code)
    if toggles is not None and settings_service.is_feature_enabled(company_id, toggles[0]) \
            and not settings_service.is_feature_enabled(company_id, toggles[1]):
        return ("POSTED",)
    return _PRE_SALES_FULFILLMENT_ELIGIBLE_STATUSES


def consignment_requires_warehouse_approval(company_id: int, document_type_code: str) -> bool:
    """R230: امانیِ ورودی/خروجی پیش از ثبتِ نهایی به تاییدِ انباردار برسد (تنظیمی)."""
    return document_type_code in _CONSIGNMENT_TYPES and settings_service.is_feature_enabled(
        company_id, "CONSIGNMENT_WAREHOUSE_APPROVAL"
    )


def _is_goods_receipt_eligible_order(session, doc: CommercialDocument) -> bool:
    """طبقِ گزارشِ صریحِ کاربر («بعدِ تاییدِ سفارشِ خرید، انباردار کجا
    رسیدِ کالا را تایید کند؟»): همان زیرساختِ تاییدِ انبار/مقدارِ تحویلیِ
    پخشِ سرد (پایین‌تر) حالا برایِ سفارشِ خرید هم -- فقط وقتی Toggleِ
    PURCHASE_ORDER_GOODS_RECEIPT برایِ شرکت روشن باشد -- قابلِ‌استفاده
    است؛ پیش‌فرض خاموش، یعنی رفتارِ قبلی (تبدیلِ مستقیم به فاکتور بدونِ
    مرحلهٔ جداگانهٔ رسید) دست‌نخورده می‌ماند."""
    if _is_pre_sales_order(session, doc):
        return True
    if consignment_requires_warehouse_approval(doc.company_id, doc.document_type_code):
        return True
    return order_warehouse_step_enabled(doc.company_id, doc.document_type_code)


def document_requires_weighing(document_id: int, company_id: int) -> bool:
    """طبقِ درخواستِ صریح («توزین اگر داشته باشه»): یعنی حداقل یک ردیفِ
    سند، کالایی با pos_requires_weight=true (کالایِ وزنی/ترازویی -- همان
    فیلدِ ازپیش‌موجودِ فروشِ حضوری) دارد."""
    with new_session() as session:
        return bool(
            session.scalar(
                select(func.count()).select_from(CommercialDocumentLine)
                .join(Item, Item.item_id == CommercialDocumentLine.item_id)
                .where(CommercialDocumentLine.document_id == document_id, Item.pos_requires_weight.is_(True))
            )
        )


def list_pre_sales_pending_warehouse_approval(company_id: int) -> list[CommercialDocument]:
    with new_session() as session:
        stmt = (
            select(CommercialDocument)
            .join(Channel, (Channel.channel_code == CommercialDocument.channel_code) & (Channel.company_id == CommercialDocument.company_id))
            .where(
                CommercialDocument.company_id == company_id, CommercialDocument.document_type_code == "SALES_ORDER",
                CommercialDocument.status_code.in_(_PRE_SALES_FULFILLMENT_ELIGIBLE_STATUSES),
                Channel.channel_type_code == "PRE_SALES",
                CommercialDocument.warehouse_approved_at.is_(None),
            )
            .order_by(CommercialDocument.document_id)
        )
        return list(session.scalars(stmt))


def list_pre_sales_pending_weighing_approval(company_id: int) -> list[CommercialDocument]:
    with new_session() as session:
        stmt = (
            select(CommercialDocument)
            .join(Channel, (Channel.channel_code == CommercialDocument.channel_code) & (Channel.company_id == CommercialDocument.company_id))
            .where(
                CommercialDocument.company_id == company_id, CommercialDocument.document_type_code == "SALES_ORDER",
                CommercialDocument.status_code.in_(_PRE_SALES_FULFILLMENT_ELIGIBLE_STATUSES),
                Channel.channel_type_code == "PRE_SALES",
                CommercialDocument.warehouse_approved_at.is_not(None),
                CommercialDocument.weighing_approved_at.is_(None),
            )
            .order_by(CommercialDocument.document_id)
        )
        return [doc for doc in session.scalars(stmt) if document_requires_weighing(doc.document_id, company_id)]


def receivable_warehouse_ids(company_id: int, user_id: int) -> set[int] | None:
    """طبقِ درخواستِ صریحِ کاربر («برایِ انبار، انباردار معلوم باشد و دسترسی
    از همان طریق باشد»): انبارهایی که این کاربر انباردارِ آن‌هاست (فیلدِ
    «مسئولِ انبار» در فرمِ انبار). None یعنی همه (کاربرِ مدیر)."""
    if roles_service.is_manager(user_id, company_id):
        return None
    with new_session() as session:
        return set(session.scalars(
            select(Warehouse.warehouse_id).where(
                Warehouse.company_id == company_id, Warehouse.manager_user_id == user_id, Warehouse.is_active.is_(True),
            )
        ))


def _validate_line_warehouses(session, company_id: int, line_warehouses: dict[int, int] | None) -> None:
    for warehouse_id in set((line_warehouses or {}).values()):
        warehouse = session.get(Warehouse, warehouse_id)
        if warehouse is None or warehouse.company_id != company_id or not warehouse.is_active:
            raise ValueError("انبارِ انتخاب‌شده برایِ ردیف نامعتبر است.")


def _require_receipt_tracking(session, ln: CommercialDocumentLine) -> None:
    """R227: کالایِ دارایِ بچ/سریال بدونِ اطلاعاتِ کاملِ ردیابی رسید نمی‌شود."""
    from peecha.db.models.inventory import LineTrackingEntry

    item = session.get(Item, ln.item_id)
    if item is None or not (item.track_batch or item.track_serial):
        return
    delivered = ln.warehouse_delivered_quantity if ln.warehouse_delivered_quantity is not None else ln.quantity
    needed = delivered * (ln.conversion_factor or 1)
    entered = decimal.Decimal(session.scalar(
        select(func.coalesce(func.sum(LineTrackingEntry.quantity), 0)).where(LineTrackingEntry.commercial_line_id == ln.line_id)
    ) or 0)
    if entered != needed:
        raise ValueError(
            f"بچ/سریال/انقضایِ کالایِ ردیفِ #{ln.line_no} کامل نیست ({entered.normalize()} از {needed.normalize()}) "
            "-- از دکمهٔ «🏷 ردیابی» همان ردیف وارد کنید."
        )


def approve_warehouse(
    document_id: int, company_id: int, approved_by_user_id: int, warehouse_id: int | None = None,
    line_warehouses: dict[int, int] | None = None,
) -> None:
    """line_warehouses (R226): انبارِ هر ردیف -- انباردارِ چند انبار می‌تواند
    هر کالا را در انبارِ جداگانه رسید کند."""
    with new_session() as session:
        doc = session.get(CommercialDocument, document_id)
        if doc is None or doc.company_id != company_id:
            raise ValueError("سند نامعتبر است.")
        if doc.document_type_code == "PURCHASE_ORDER" or (
            doc.document_type_code == "SALES_ORDER" and not _is_pre_sales_order(session, doc)
        ):
            # طبقِ درخواستِ صریحِ کاربر: در سفارشِ خرید انبار لازم نیست --
            # انباردار هنگامِ رسید مشخص می‌کند کالا به کدام انبار وارد شد.
            _validate_line_warehouses(session, company_id, line_warehouses)
            allowed = receivable_warehouse_ids(company_id, approved_by_user_id)
            default_warehouse_id = warehouse_id or doc.warehouse_id
            lines = session.scalars(
                select(CommercialDocumentLine).where(CommercialDocumentLine.document_id == document_id)
            ).all()
            used: list[int] = []
            for ln in lines:
                target = (line_warehouses or {}).get(ln.line_id) or ln.warehouse_id or default_warehouse_id
                if target is None:
                    raise ValueError(f"انبارِ دریافت‌کنندهٔ ردیفِ #{ln.line_no} را مشخص کنید.")
                if allowed is not None and target not in allowed:
                    raise ValueError(
                        "شما انباردارِ این انبار نیستید -- فقط انباردارِ همان انبار یا مدیر می‌تواند رسید را تایید کند."
                    )
                ln.warehouse_id = target
                used.append(target)
                _require_receipt_tracking(session, ln)
            if default_warehouse_id is None and used:
                default_warehouse_id = used[0]
            if default_warehouse_id is None:
                raise ValueError("انبارِ دریافت‌کننده را مشخص کنید.")
            if allowed is not None and default_warehouse_id not in allowed:
                default_warehouse_id = used[0] if used else default_warehouse_id
            doc.warehouse_id = default_warehouse_id
        if not _is_goods_receipt_eligible_order(session, doc):
            raise ValueError("این عملیات فقط برایِ سفارش‌هایِ کانالِ «پخشِ سرد» یا سفارشِ خریدِ دارایِ Toggleِ رسیدِ انبار معنا دارد.")
        if doc.status_code not in receipt_eligible_statuses(company_id, doc.document_type_code):
            raise ValueError(
                "سفارشِ خرید ابتدا باید ثبتِ نهایی شود، سپس رسیدِ انبار." if doc.document_type_code == "PURCHASE_ORDER"
                else "سفارشِ فروش ابتدا باید ثبتِ نهایی شود، سپس حوالهٔ انبار."
                if doc.document_type_code == "SALES_ORDER" and not _is_pre_sales_order(session, doc)
                else "فقط سندِ تاییدشده/تصویب‌شده قابلِ‌تاییدِ انبار است."
            )
        if doc.warehouse_approved_at is not None:
            raise ValueError("این سفارش قبلاً از سویِ انبار تایید شده است.")
        if doc.document_type_code in _CONSIGNMENT_TYPES:
            allowed = receivable_warehouse_ids(company_id, approved_by_user_id)
            if allowed is not None and doc.warehouse_id not in allowed:
                raise ValueError("شما انباردارِ انبارِ این سندِ امانی نیستید.")
        doc.warehouse_approved_by_user_id = approved_by_user_id
        doc.warehouse_approved_at = datetime.datetime.now()
        session.commit()


def approve_weighing(document_id: int, company_id: int, approved_by_user_id: int) -> None:
    with new_session() as session:
        doc = session.get(CommercialDocument, document_id)
        if doc is None or doc.company_id != company_id:
            raise ValueError("سند نامعتبر است.")
        if not _is_pre_sales_order(session, doc):
            raise ValueError("این عملیات فقط برایِ سفارش‌هایِ کانالِ «پخشِ سرد» معنا دارد.")
        if doc.warehouse_approved_at is None:
            raise ValueError("این سفارش هنوز از سویِ انبار تایید نشده است.")
        if doc.weighing_approved_at is not None:
            raise ValueError("این سفارش قبلاً توزین/تایید شده است.")
        doc.weighing_approved_by_user_id = approved_by_user_id
        doc.weighing_approved_at = datetime.datetime.now()
        session.commit()


def describe_pre_sales_fulfillment_status(document_id: int, company_id: int) -> str | None:
    """طبقِ نیازِ نمایشِ وضعیت در فهرستِ اسناد/دکمه‌یِ «تبدیل به فاکتور» --
    اگر سند پخشِ سرد نباشد، None (یعنی این گیت اصلاً برایش معنا ندارد)."""
    with new_session() as session:
        doc = session.get(CommercialDocument, document_id)
        if doc is None or not _is_pre_sales_order(session, doc):
            return None
    requires_weighing = document_requires_weighing(document_id, company_id)
    with new_session() as session:
        doc = session.get(CommercialDocument, document_id)
        if doc.warehouse_approved_at is None:
            return "در انتظارِ تاییدِ انبار"
        if requires_weighing and doc.weighing_approved_at is None:
            return "در انتظارِ توزین"
        return "آمادهٔ تبدیل به فاکتور"


def _has_any_invoiced_quantity(session, document_id: int) -> bool:
    """طبقِ همان الگویِ _invoiced_quantity: ستونِ CommercialDocumentLine.
    invoiced_quantity_total هرگز در جایی از کد به‌روزرسانی نمی‌شود (همیشه
    صفرِ پیش‌فرض می‌ماند) -- پس «آیا این سفارش قبلاً تبدیل شده؟» باید
    مثلِ خودِ تبدیل، با پیداکردنِ ردیف‌هایِ فاکتورِ غیرِلغوشده‌ای که
    source_line_id‌شان به ردیف‌هایِ همین سفارش اشاره می‌کند، محاسبه شود."""
    line_ids = list(session.scalars(select(CommercialDocumentLine.line_id).where(CommercialDocumentLine.document_id == document_id)))
    if not line_ids:
        return False
    return bool(
        session.scalar(
            select(func.count()).select_from(CommercialDocumentLine)
            .join(CommercialDocument, CommercialDocument.document_id == CommercialDocumentLine.document_id)
            .where(CommercialDocumentLine.source_line_id.in_(line_ids), CommercialDocument.status_code != "CANCELLED")
        )
    )


def document_has_been_converted(document_id: int, company_id: int) -> bool:
    """طبقِ درخواستِ صریح («امکانِ بازگشت و ادیتِ مجدد برایِ انباردار تا
    تاییدِ نهایی [=تبدیل به فاکتور] فعال شود»): همین تابع مرزِ «تاییدِ
    نهایی» را مشخص می‌کند -- به‌محضِ این‌که حتیّ یک ردیف از این سفارش به
    فاکتور تبدیل شده باشد، دیگر مقدارِ تحویلی/تاییدِ انبار/توزین
    قابلِ‌بازگشت یا ویرایش نیستند (چون فاکتورِ صادرشده از رویِ همان
    مقدارها ساخته شده و برگرداندنشان سند را با فاکتور ناهم‌خوان می‌کند)."""
    with new_session() as session:
        doc = session.get(CommercialDocument, document_id)
        if doc is None or doc.company_id != company_id:
            raise ValueError("سند نامعتبر است.")
        return _has_any_invoiced_quantity(session, document_id)


def set_warehouse_delivered_quantities(
    document_id: int, company_id: int, quantities: dict[int, decimal.Decimal],
) -> None:
    """طبقِ درخواستِ صریحِ کاربر («انباردار سفارش را باز کند، مقدارِ
    تحویلی را وارد/ادیت کند -- وزنی و تعدادی»): مقدارِ واقعیِ تحویلی/
    توزین‌شده‌یِ هر ردیف را ثبت می‌کند؛ این مقدار (اگر ثبت شود) بعداً به‌
    جایِ مقدارِ سفارش، مبنایِ پیش‌فرضِ تبدیل به فاکتور می‌شود
    (convert_to_invoice). قابلِ‌ویرایش تا وقتی سفارش هنوز به هیچ
    فاکتوری تبدیل نشده -- صرفِ‌نظر از این‌که تاییدِ انبار/توزین قبلاً
    زده شده یا نه (همان چیزی که «بازگشت و ادیتِ مجدد» را ممکن می‌کند)."""
    with new_session() as session:
        doc = session.get(CommercialDocument, document_id)
        if doc is None or doc.company_id != company_id:
            raise ValueError("سند نامعتبر است.")
        if not _is_goods_receipt_eligible_order(session, doc):
            raise ValueError("این عملیات فقط برایِ سفارش‌هایِ کانالِ «پخشِ سرد» یا سفارشِ خریدِ دارایِ Toggleِ رسیدِ انبار معنا دارد.")
        if _has_any_invoiced_quantity(session, document_id):
            raise ValueError("این سفارش قبلاً (به‌طورِ کامل/جزئی) به فاکتور تبدیل شده -- مقدارِ تحویلی دیگر قابلِ‌ویرایش نیست.")
        lines_by_id = {
            ln.line_id: ln
            for ln in session.scalars(select(CommercialDocumentLine).where(CommercialDocumentLine.document_id == document_id))
        }
        for line_id, qty in quantities.items():
            line = lines_by_id.get(line_id)
            if line is None:
                raise ValueError("ردیفِ نامعتبر.")
            if qty < 0:
                raise ValueError("مقدارِ تحویلی نمی‌تواند منفی باشد.")
            line.warehouse_delivered_quantity = qty
        session.commit()


def revert_warehouse_approval(document_id: int, company_id: int) -> None:
    with new_session() as session:
        doc = session.get(CommercialDocument, document_id)
        if doc is None or doc.company_id != company_id:
            raise ValueError("سند نامعتبر است.")
        if not _is_goods_receipt_eligible_order(session, doc):
            raise ValueError("این عملیات فقط برایِ سفارش‌هایِ کانالِ «پخشِ سرد» یا سفارشِ خریدِ دارایِ Toggleِ رسیدِ انبار معنا دارد.")
        if doc.warehouse_approved_at is None:
            raise ValueError("این سفارش هنوز تاییدِ انبار نگرفته است.")
        if doc.weighing_approved_at is not None:
            raise ValueError("ابتدا تاییدِ توزین را برگردانید.")
        if _has_any_invoiced_quantity(session, document_id):
            raise ValueError("این سفارش قبلاً به فاکتور تبدیل شده -- دیگر قابلِ‌بازگشت نیست.")
        doc.warehouse_approved_by_user_id = None
        doc.warehouse_approved_at = None
        session.commit()


def revert_weighing_approval(document_id: int, company_id: int) -> None:
    with new_session() as session:
        doc = session.get(CommercialDocument, document_id)
        if doc is None or doc.company_id != company_id:
            raise ValueError("سند نامعتبر است.")
        if not _is_pre_sales_order(session, doc):
            raise ValueError("این عملیات فقط برایِ سفارش‌هایِ کانالِ «پخشِ سرد» معنا دارد.")
        if doc.weighing_approved_at is None:
            raise ValueError("این سفارش هنوز توزین/تایید نشده است.")
        if _has_any_invoiced_quantity(session, document_id):
            raise ValueError("این سفارش قبلاً به فاکتور تبدیل شده -- دیگر قابلِ‌بازگشت نیست.")
        doc.weighing_approved_by_user_id = None
        doc.weighing_approved_at = None
        session.commit()


def list_pre_sales_fulfillment_queue(company_id: int) -> list[CommercialDocument]:
    """همه‌یِ سفارش‌هایِ پخشِ سردِ CONFIRMED/APPROVED که هنوز به هیچ
    فاکتوری (حتی جزئی) تبدیل نشده‌اند -- صرفِ‌نظر از مرحله‌یِ فعلیِ
    تاییدِ انبار/توزین؛ یک فهرستِ واحد برایِ صفحه‌یِ «تاییدِ انبار و
    توزین» که هم موردهایِ در انتظار و هم موردهایِ ازپیش‌تاییدشده (برایِ
    امکانِ بازگشت/ویرایشِ مجدد) را نشان می‌دهد."""
    with new_session() as session:
        stmt = (
            select(CommercialDocument)
            .join(Channel, (Channel.channel_code == CommercialDocument.channel_code) & (Channel.company_id == CommercialDocument.company_id))
            .where(
                CommercialDocument.company_id == company_id, CommercialDocument.document_type_code == "SALES_ORDER",
                CommercialDocument.status_code.in_(_PRE_SALES_FULFILLMENT_ELIGIBLE_STATUSES),
                Channel.channel_type_code == "PRE_SALES",
            )
            .order_by(CommercialDocument.document_id)
        )
        return [doc for doc in session.scalars(stmt) if not _has_any_invoiced_quantity(session, doc.document_id)]


def list_purchase_order_goods_receipt_queue(company_id: int, user_id: int | None = None) -> list[CommercialDocument]:
    """هم‌الگو با list_pre_sales_fulfillment_queue، برایِ سفارشِ خرید --
    طبقِ گزارشِ صریحِ کاربر («بعدِ تاییدِ سفارش، انباردار کجا رسیدِ کالا را
    تایید کند؟»). فقط وقتی Toggleِ PURCHASE_ORDER_GOODS_RECEIPT برایِ
    شرکت روشن باشد نتیجه‌ای برمی‌گرداند -- وگرنه فهرست همیشه خالی است."""
    docs: list[CommercialDocument] = []
    with new_session() as session:
        if settings_service.is_feature_enabled(company_id, "PURCHASE_ORDER_GOODS_RECEIPT"):
            stmt = (
                select(CommercialDocument)
                .where(
                    CommercialDocument.company_id == company_id, CommercialDocument.document_type_code == "PURCHASE_ORDER",
                    CommercialDocument.status_code.in_(receipt_eligible_statuses(company_id, "PURCHASE_ORDER")),
                )
                .order_by(CommercialDocument.document_id)
            )
            docs = [doc for doc in session.scalars(stmt) if not _has_any_invoiced_quantity(session, doc.document_id)]
        if order_warehouse_step_enabled(company_id, "SALES_ORDER"):
            # R232: حوالهٔ انبارِ سفارشِ فروش (سفارش‌هایِ پخشِ سرد روالِ «انبار و توزین» خودشان را دارند)
            stmt = (
                select(CommercialDocument)
                .where(
                    CommercialDocument.company_id == company_id, CommercialDocument.document_type_code == "SALES_ORDER",
                    CommercialDocument.status_code.in_(receipt_eligible_statuses(company_id, "SALES_ORDER")),
                )
                .order_by(CommercialDocument.document_id)
            )
            docs += [
                doc for doc in session.scalars(stmt)
                if not _is_pre_sales_order(session, doc) and not _has_any_invoiced_quantity(session, doc.document_id)
            ]
        if settings_service.is_feature_enabled(company_id, "CONSIGNMENT_WAREHOUSE_APPROVAL"):
            # R230: امانیِ ورودی/خروجیِ تاییدشده که هنوز ثبتِ نهایی (جابه‌جاییِ کالا) نشده
            docs += list(session.scalars(
                select(CommercialDocument).where(
                    CommercialDocument.company_id == company_id,
                    CommercialDocument.document_type_code.in_(_CONSIGNMENT_TYPES),
                    CommercialDocument.status_code.in_(_PRE_SALES_FULFILLMENT_ELIGIBLE_STATUSES),
                ).order_by(CommercialDocument.document_id)
            ))
    allowed = receivable_warehouse_ids(company_id, user_id) if user_id is not None else None
    if allowed is None:
        return docs
    with new_session() as session:
        line_warehouses = {}
        for wid, did in session.execute(
            select(CommercialDocumentLine.warehouse_id, CommercialDocumentLine.document_id).where(
                CommercialDocumentLine.document_id.in_([d.document_id for d in docs]),
                CommercialDocumentLine.warehouse_id.is_not(None),
            )
        ):
            line_warehouses.setdefault(did, set()).add(wid)
    return [
        d for d in docs
        if (d.warehouse_id in allowed) or (d.warehouse_id is None and allowed) or (line_warehouses.get(d.document_id, set()) & allowed)
    ]


def revert_to_draft(document_id: int, company_id: int) -> None:
    """طبقِ رفعِ کلاسِ باگِ گزارش‌شده («سندِ بن‌بست -- نه ادیت می‌شه، نه
    حذف، نه ثبتِ‌نهایی»): تا پیش از این، تنها راهِ خروج از یک سندِ
    CONFIRMED که به هر دلیلی (مثلاً همان کمبودِ انبار) دیگر قابلِ‌ثبتِ‌
    نهایی نبود، لغوِ کاملِ آن بود. حالا سندِ CONFIRMED (که هنوز تصویب/
    ثبتِ‌نهایی نشده) می‌تواند به DRAFT برگردد -- هم‌الگو با inventory_
    documents.revert_to_draft برایِ اسنادِ انبار -- تا هدر (ازجمله
    انبار) دوباره کاملاً قابلِ‌ویرایش شود."""
    with new_session() as session:
        doc = session.get(CommercialDocument, document_id)
        if doc is None or doc.company_id != company_id:
            raise ValueError("سند نامعتبر است.")
        # سفارش‌ها (که پس از تایید فقط با بازگشت به پیش‌نویس ویرایش می‌شوند)
        # از وضعیتِ تصویب‌شده هم برمی‌گردند؛ بقیه فقط از تاییدشده.
        # R226: فاکتورِ تصویب‌شده (هنوز ثبت‌نشده) هم -- وگرنه با کمبودِ مرکزِ
        # هزینه/پروژه در ثبتِ نهایی، نه برمی‌گشت نه حذف می‌شد.
        allowed_statuses = ("CONFIRMED", "APPROVED")
        if doc.status_code not in allowed_statuses:
            raise ValueError("فقط سندِ تاییدشده (که هنوز ثبتِ‌نهایی نشده) قابلِ‌بازگشت به پیش‌نویس است.")
        if doc.warehouse_approved_at is not None:
            raise ValueError("رسید/تاییدِ انبارِ این سفارش ثبت شده -- ابتدا انباردار باید تاییدش را برگرداند.")
        if _has_any_invoiced_quantity(session, document_id):
            raise ValueError("این سفارش (کامل یا جزئی) به فاکتور تبدیل شده و دیگر به پیش‌نویس برنمی‌گردد.")
        # اگر تاییدِ این سند یک قفلِ اعتباری ساخته بود (مثلاً سفارشی که
        # از سقفِ اعتبار عبور کرده)، با بازگشت به پیش‌نویس آن قفل دیگر
        # معنا ندارد -- وگرنه برایِ همیشه بازِ حل‌نشده می‌ماند.
        session.query(CreditHold).filter(
            CreditHold.related_document_id == document_id, CreditHold.released_at.is_(None)
        ).delete()
        _old_status = doc.status_code
        doc.status_code = "DRAFT"
        _log_status(session, doc, _old_status)
        session.commit()


@dataclass
class StockShortage:
    item_id: int
    item_label: str
    warehouse_id: int
    warehouse_label: str
    shortage_qty: decimal.Decimal
    base_uom_id: int


def get_stock_shortages(document_id: int, company_id: int) -> list[StockShortage]:
    """طبقِ درخواستِ صریح («وقتی هنگامِ تاییدِ سرپرست انبار موجودی ندارد،
    اتوماتیک انتقالِ انبار صادر کند»): پیش از فراخوانیِ post_document
    (بدونِ تلاشِ واقعی برایِ ثبتِ سندِ انبار، فقط خواندنِ موجودیِ فعلی)
    کمبودِ هر ردیف را برمی‌گرداند تا فراخوان بتواند به‌جایِ شکستِ گنگِ
    post_document در ادامه، پیش از آن یک سندِ انتقالِ جبرانی صادر کند."""
    with new_session() as session:
        doc = session.get(CommercialDocument, document_id)
        if doc is None or doc.company_id != company_id:
            raise ValueError("سند نامعتبر است.")
        stock_document_type = _STOCK_DOC_TYPE_BY_TYPE.get(doc.document_type_code)
        if stock_document_type not in ("ISSUE", "RETURN_OUT"):
            return []
        lines = session.scalars(select(CommercialDocumentLine).where(CommercialDocumentLine.document_id == document_id)).all()
        shortages: list[StockShortage] = []
        for ln in lines:
            effective_warehouse_id = ln.warehouse_id or doc.warehouse_id
            if effective_warehouse_id is None:
                continue
            warehouse = session.get(Warehouse, effective_warehouse_id)
            # طبقِ درخواستِ صریح («وقتی امکانِ فروشِ منفی در انبار تیک
            # خورده باشه، سیستم باید اجازه بدهد تاییدِ سرپرست انجام
            # شود»): وقتی خودِ انبار صراحتاً موجودیِ منفی را مجاز کرده،
            # این اصلاً یک «کمبود» نیست -- post_document بدونِ نیاز به
            # هیچ سندِ انتقالی موفق می‌شود؛ پس نباید سرِ راهِ تاییدِ
            # سرپرست را با انتقالِ غیرِلازم بگیریم.
            if warehouse is not None and warehouse.allow_negative_stock:
                continue
            item = session.get(Item, ln.item_id)
            if item is None or not item.is_stock_tracked:
                continue
            available = locations_service.get_available_quantity(ln.item_id, effective_warehouse_id)
            if available >= ln.quantity_base:
                continue
            shortages.append(StockShortage(
                item_id=ln.item_id, item_label=dimensions_service.get_detail_account_label(item.item_detail_account_id),
                warehouse_id=effective_warehouse_id,
                warehouse_label=warehouse.name if warehouse is not None else "?",
                shortage_qty=ln.quantity_base - available, base_uom_id=item.base_uom_id,
            ))
        return shortages


def create_compensating_transfer(company_id: int, user_id: int, shortage: StockShortage) -> int | None:
    """برایِ یک ردیفِ کم‌موجود (خروجیِ get_stock_shortages)، اگر انبارِ
    دیگری از همین شرکت موجودیِ کافی داشته باشد، یک سندِ TRANSFER
    (تاییدشده، هنوز ثبتِ‌نهایی‌نشده) از آن انبار به انبارِ کم‌موجود
    می‌سازد و شناسه‌اش را برمی‌گرداند -- ثبتِ‌نهاییِ واقعی (که موجودی را
    واقعاً جابه‌جا می‌کند) با انباردار است. اگر هیچ انبارِ دیگری موجودیِ
    کافی نداشت، هیچ سندی ساخته نمی‌شود و None برمی‌گردد."""
    candidates = [
        w for w in locations_service.list_warehouses(company_id, active_only=True)
        if w.warehouse_id != shortage.warehouse_id
    ]
    best_warehouse_id = None
    best_available = decimal.Decimal("0")
    for warehouse in candidates:
        available = locations_service.get_available_quantity(shortage.item_id, warehouse.warehouse_id)
        if available > best_available:
            best_available = available
            best_warehouse_id = warehouse.warehouse_id
    if best_warehouse_id is None or best_available < shortage.shortage_qty:
        return None
    header = inv_documents_service.DocumentHeaderFields(
        source_warehouse_id=best_warehouse_id, destination_warehouse_id=shortage.warehouse_id,
        description=(
            f"انتقالِ خودکارِ جبرانِ کمبودِ موجودیِ «{shortage.item_label}» "
            f"در انبارِ «{shortage.warehouse_label}» (طیِ تاییدِ سرپرستِ فروشِ حضوری)."
        ),
    )
    transfer_doc_id = inv_documents_service.create_stock_document(
        company_id, user_id, "TRANSFER", datetime.date.today(), header,
    )
    inv_documents_service.add_line(
        transfer_doc_id, company_id,
        inv_documents_service.LineFields(
            item_id=shortage.item_id, uom_id=shortage.base_uom_id,
            quantity=shortage.shortage_qty, quantity_base=shortage.shortage_qty,
        ),
    )
    inv_documents_service.confirm_stock_document(transfer_doc_id, company_id)
    return transfer_doc_id


def cancel_document(
    document_id: int, company_id: int, *, reason_id: int | None = None, note: str | None = None,
    cancelled_by_user_id: int | None = None,
) -> None:
    """R240: علت/توضیح/کاربر/زمانِ لغو هم ثبت می‌شود (اختیاری؛ فراخوان‌هایِ قبلی بی‌تغییر کار می‌کنند)."""
    with new_session() as session:
        doc = session.get(CommercialDocument, document_id)
        if doc is None or doc.company_id != company_id:
            raise ValueError("سند نامعتبر است.")
        if doc.status_code not in ("DRAFT", "CONFIRMED", "APPROVED"):
            raise ValueError("سندِ ثبت‌شده هرگز لغو نمی‌شود — برایِ اصلاح، سندِ تازه‌ای ثبت کنید.")
        _old_status = doc.status_code
        doc.status_code = "CANCELLED"
        doc.cancellation_reason_id = reason_id
        doc.cancellation_note = (note or None)
        doc.cancelled_at = datetime.datetime.now()
        doc.cancelled_by_user_id = _actor(cancelled_by_user_id)
        _log_status(session, doc, _old_status, cancelled_by_user_id)
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

    # R230: بهایِ ثبت‌شده در لحظهٔ امانیِ ورودی (حتی صفر/تخمینی) همان بهایِ موجودی
    # است؛ اختلافِ قیمتِ نهاییِ تسویه با آن، برایِ بخشی که هنوز در انبار است
    # ارزشِ موجودی را اصلاح می‌کند و برایِ بخشی که پیش از تسویه فروخته شده
    # به بهایِ تمام‌شدهٔ فروش می‌رود (همان روشِ اصلاحِ بهایِ خرید).
    total = _ZERO
    inventory_by_item: dict[int, decimal.Decimal] = {}
    cogs_by_item: dict[int, decimal.Decimal] = {}
    for snap in line_snapshots:
        line_id, item_id, quantity, quantity_base, unit_price = snap[0], snap[1], snap[3], snap[4], snap[5]
        settled_amount = _money(quantity * unit_price - (snap[8] or _ZERO))
        total += settled_amount
        recorded_amount = settled_amount
        inventory_amount, cogs_amount = settled_amount, _ZERO
        with new_session() as session:
            line = session.get(CommercialDocumentLine, line_id)
            source = session.get(CommercialDocumentLine, line.source_line_id) if line and line.source_line_id else None
            source_doc = session.get(CommercialDocument, source.document_id) if source is not None else None
        if source is not None and source.quantity_base and quantity_base:
            recorded_unit = (source.quantity * source.unit_price - (source.discount_amount or _ZERO)) / source.quantity_base
            recorded_amount = _money(quantity_base * recorded_unit)
            delta_per_base = (settled_amount / quantity_base) - recorded_unit
            inventory_amount, cogs_amount = recorded_amount, _ZERO
            if delta_per_base and source_doc is not None and source_doc.warehouse_id is not None:
                try:
                    correction = inv_engine_service.apply_purchase_cost_correction(
                        item_id, source_doc.warehouse_id, None, company_id, quantity_base, delta_per_base,
                    )
                    inventory_amount += correction.inventory_value_delta
                    cogs_amount += correction.variance_value_delta
                except ValueError:
                    cogs_amount += _money(quantity_base * delta_per_base)
            # گردِ کردن: جمعِ بدهکار دقیقاً برابرِ بستانکار
            cogs_amount += settled_amount - (inventory_amount + cogs_amount)
        detail_account_id = item_detail_account_by_item_id.get(item_id)
        inventory_by_item[detail_account_id] = inventory_by_item.get(detail_account_id, _ZERO) + inventory_amount
        if cogs_amount:
            cogs_by_item[detail_account_id] = cogs_by_item.get(detail_account_id, _ZERO) + cogs_amount

    je_lines: list[je_service.LineInput] = []
    for k, v in inventory_by_item.items():
        if v:
            je_lines += _build_role_je_lines(
                inventory_account_id, description, extra_dims, abs(v), is_debit=v > 0,
                item_dim_type_id=item_dim_type_id, amounts_by_item_detail_account={k: abs(v)},
            )
    if any(cogs_by_item.values()):
        cogs_account_id = inv_engine_service.get_account_mapping(company_id, "COGS")
        if cogs_account_id is None:
            raise ValueError("حسابِ «بهایِ تمام‌شده» در تنظیماتِ انبار مشخص نشده است (اختلافِ بهایِ امانیِ فروخته‌شده).")
        for k, v in cogs_by_item.items():
            if v:
                je_lines += _build_role_je_lines(
                    cogs_account_id, f"{description} -- اختلافِ بهایِ امانیِ فروخته‌شده", extra_dims, abs(v), is_debit=v > 0,
                    item_dim_type_id=item_dim_type_id, amounts_by_item_detail_account={k: abs(v)},
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
            net_of_discount = (quantity * unit_price - discount_amount) / quantity_base if quantity_base else unit_price
            line_unit_cost = _money(net_of_discount)
            line_tax_amount = tax_amount
        inv_line_id = inv_documents_service.add_line(
            stock_document_id, company_id,
            inv_documents_service.LineFields(
                item_id=item_id, uom_id=uom_id, quantity=quantity, quantity_base=quantity_base,
                conversion_factor=(quantity_base / quantity) if quantity else None,
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


def post_document(
    document_id: int, company_id: int, posted_by_user_id: int, *, from_field_sales: bool = False,
) -> PostResult:
    """from_field_sales: فروشِ موبایل (کالا تحویل شده) -- تصویبِ مدیرِ فروش مانعش نمی‌شود."""
    with new_session() as session:
        doc = session.get(CommercialDocument, document_id)
        if doc is None or doc.company_id != company_id:
            raise ValueError("سند نامعتبر است.")
        if doc.status_code == "POSTED":
            raise ValueError("این سند قبلاً ثبتِ نهایی شده است.")
        if doc.status_code not in ("CONFIRMED", "APPROVED"):
            raise ValueError("فقط سندِ تاییدشده قابلِ‌ثبتِ‌نهایی است.")
        # طبقِ درخواستِ صریحِ کاربر («مراحلِ تاییدِ فاکتورِ خرید هم در دو
        # مرحله باشه: تاییدِ کاربر و تاییدِ مدیر» -- و تعمیمِ صریحِ خودش
        # به پیش‌فاکتورِ خرید هم): برایِ این دو نوعِ سند، دیگر کافی نیست
        # که سند فقط CONFIRMED باشد -- باید حتماً از مرحلهٔ تصویبِ مدیر
        # (APPROVED) هم عبور کرده باشد.
        if doc.document_type_code in ("PURCHASE_INVOICE", "PURCHASE_PROFORMA", "SALES_ORDER", "SALES_INVOICE", "SALES_PROFORMA") \
                and doc.status_code != "APPROVED" and requires_manager_approval(company_id, doc.document_type_code) \
                and not from_field_sales and doc.pos_session_id is None:
            raise ValueError("این سند ابتدا باید توسطِ مدیر تصویب شود -- تاییدِ کاربر به‌تنهایی برایِ ثبتِ نهایی کافی نیست.")

        document_type_code = doc.document_type_code

        # طبقِ رفعِ باگِ واقعیِ «سندِ بن‌بست»: این بررسی حالا زودتر، در
        # confirm_document، انجام می‌شود -- این‌جا فقط دفاعِ اضافه برایِ
        # سندهایِ CONFIRMED/APPROVEDِ ازقبل‌موجودی است که پیش از افزودنِ
        # همان بررسی ساخته شده‌اند و ممکن است هنوز بدونِ انبار مانده
        # باشند؛ بدونِ آن، این سندها برایِ همیشه در همین حلقه‌یِ ثبتِ‌
        # نهایی/شکست گیر می‌کردند.
        if consignment_requires_warehouse_approval(company_id, document_type_code) and doc.warehouse_approved_at is None:
            raise ValueError("این سندِ امانی هنوز به تاییدِ انباردار نرسیده است -- ابتدا از «تاییدِ رسیدِ کالا» تایید شود.")

        if document_type_code in _STOCK_DOC_TYPE_BY_TYPE and doc.warehouse_id is None:
            default_warehouse = locations_service.get_default_warehouse(company_id)
            if default_warehouse is not None:
                doc.warehouse_id = default_warehouse.warehouse_id
                session.commit()

        # طبقِ درخواستِ صریح («یک دکمه در فرمِ فاکتور... با تاییدِ مدیر
        # نسبت به نحوه‌یِ تسویه، فاکتور سند بخوره و تسویه بشه»): این
        # گذرگاه فقط برایِ فاکتورهایِ واردشده از همان فرمِ عمومیِ فاکتور
        # (commercial_document.py) اجباری است -- فروشِ صندوق/POS
        # (pos_session_id مشخص) سیستمِ پرداختِ کاملاً جداگانه و ازپیش‌
        # تکمیل‌شده‌یِ خودش را دارد (نقد/کارت/دسترسیِ‌سریع، …) و نباید با
        # این نقشه‌یِ تسویه‌یِ جدید تداخل کند.
        if document_type_code in _INVOICE_TYPES and doc.pos_session_id is None:
            settlements_service.require_approved_settlement_plan(document_id, company_id)

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
        for dim_type_id, detail_account_id in _pos_receivable_dims_fallback(company_id, doc.pos_session_id).items():
            extra_dims.setdefault(dim_type_id, detail_account_id)

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
        # R227: مالکیتِ کالایِ امانیِ همین تامین‌کننده در دفترِ ردیابی منتقل می‌شود.
        from peecha.services import lot_tracking

        lot_tracking.settle_consignment(document_id, company_id)
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
                    # بهایِ لجر به‌ازایِ واحدِ پایه است (موجودی به واحدِ پایه نگه‌داری می‌شود).
                    net_of_discount = (quantity * unit_price - _discount_amt) / quantity_base if quantity_base else unit_price
                    # طبقِ درخواستِ صریح («دو نوعِ ثبت: رسمی/غیررسمی»): در
                    # حالتِ غیررسمی، مالياتِ خرید ردیفِ جداگانه‌یِ «مالياتِ
                    # خرید-قابلِ‌مطالبه» نمی‌گیرد -- مستقیماً به بهایِ
                    # موجودیِ همین ردیف اضافه می‌شود (اگر ماليات صفر باشد
                    # هردو حالت یکسان‌اند).
                    if is_informal_tax and _tax_amt and quantity_base:
                        net_of_discount += _tax_amt / quantity_base
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
                    stock_unit_cost = unit_price * quantity / quantity_base if quantity_base else unit_price
                    if quantity_base:
                        # R235/R237: مبلغِ برگشت (به تامین‌کننده یا از مشتری) خالص از تخفیفِ ردیف؛
                        # بهایِ کالا را خودِ موتورِ انبار جدا محاسبه می‌کند.
                        stock_unit_cost = (quantity * unit_price - _discount_amt) / quantity_base
                    line_tax_amount = _tax_amt
                line_reason_code_id = (
                    _ensure_return_reason_code(company_id, stock_document_type)
                    if stock_document_type in ("RETURN_IN", "RETURN_OUT") else None
                )
                # R237: برگشت از فروشِ دارایِ ارجاع به فاکتور -> بهایِ همان فروش (ردیفِ حوالهٔ فاکتور)
                source_stock_line_id = None
                if stock_document_type == "RETURN_IN":
                    with new_session() as session:
                        comm_line = session.get(CommercialDocumentLine, line_id)
                        source_comm_line = session.get(CommercialDocumentLine, comm_line.source_line_id) \
                            if comm_line is not None and comm_line.source_line_id else None
                        source_stock_line_id = source_comm_line.stock_document_line_id if source_comm_line is not None else None
                inv_line_id = inv_documents_service.add_line(
                    group_stock_document_id, company_id,
                    inv_documents_service.LineFields(
                        source_line_id=source_stock_line_id,
                        item_id=item_id, uom_id=uom_id, quantity=quantity, quantity_base=quantity_base,
                conversion_factor=(quantity_base / quantity) if quantity else None,
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
class SalesReportRow:
    item_id: int
    item_name: str
    quantity_sold: decimal.Decimal
    invoice_count: int
    net_revenue: decimal.Decimal
    # سیستمِ واحد (R225): quantity_sold به واحدِ پایه است؛ این‌جا مقدارِ
    # تراکنش به تفکیکِ واحدِ ثبت‌شده (مثلاً {«کارتن»: ۲، «عدد»: ۳}).
    base_uom_name: str = ""
    transaction_quantities: dict[str, decimal.Decimal] = field(default_factory=dict)


def compute_sales_report_by_item(
    company_id: int, date_from: datetime.date, date_to: datetime.date,
) -> list[SalesReportRow]:
    """طبقِ ادامه‌یِ اولویت‌بندی («گزارشِ فروش»): برخلافِ سودِ واقعیِ
    مشتری (که مشتری-محور است)، این گزارش کالا-محور است -- تعدادِ فروخته‌
    شده، تعدادِ فاکتور، و فروشِ خالص (بدونِ مالیات) به‌ازایِ هر کالا در
    بازه‌یِ تاریخِ داده‌شده."""
    with new_session() as session:
        stmt = (
            select(
                CommercialDocumentLine.item_id,
                func.coalesce(func.sum(CommercialDocumentLine.quantity_base), 0),
                func.count(func.distinct(CommercialDocumentLine.document_id)),
                func.coalesce(
                    func.sum(CommercialDocumentLine.quantity * CommercialDocumentLine.unit_price - CommercialDocumentLine.discount_amount), 0,
                ),
            )
            .join(CommercialDocument, CommercialDocument.document_id == CommercialDocumentLine.document_id)
            .where(
                CommercialDocument.company_id == company_id,
                CommercialDocument.document_type_code == "SALES_INVOICE",
                CommercialDocument.status_code == "POSTED",
                CommercialDocument.document_date >= date_from,
                CommercialDocument.document_date <= date_to,
            )
            .group_by(CommercialDocumentLine.item_id)
        )
        item_totals = {row[0]: (row[1], row[2], row[3]) for row in session.execute(stmt)}
        from peecha.db.models.inventory import Uom

        uom_names = {u.uom_id: u.name for u in session.scalars(select(Uom))}
        breakdown: dict[int, dict[str, decimal.Decimal]] = {}
        for item_id, uom_id, qty in session.execute(
            select(CommercialDocumentLine.item_id, CommercialDocumentLine.uom_id, func.sum(CommercialDocumentLine.quantity))
            .join(CommercialDocument, CommercialDocument.document_id == CommercialDocumentLine.document_id)
            .where(
                CommercialDocument.company_id == company_id,
                CommercialDocument.document_type_code == "SALES_INVOICE",
                CommercialDocument.status_code == "POSTED",
                CommercialDocument.document_date >= date_from,
                CommercialDocument.document_date <= date_to,
            )
            .group_by(CommercialDocumentLine.item_id, CommercialDocumentLine.uom_id)
        ):
            breakdown.setdefault(item_id, {})[uom_names.get(uom_id, str(uom_id))] = qty
        base_uom_by_item = dict(session.execute(select(Item.item_id, Item.base_uom_id).where(Item.item_id.in_(item_totals.keys()))).all())
        item_detail_account_by_id = {
            item_id: detail_account_id
            for item_id, detail_account_id in session.execute(
                select(Item.item_id, Item.item_detail_account_id).where(Item.item_id.in_(item_totals.keys()))
            )
        }

    rows = [
        SalesReportRow(
            item_id=item_id,
            item_name=dimensions_service.get_detail_account_label(item_detail_account_by_id.get(item_id)),
            quantity_sold=quantity_sold,
            invoice_count=invoice_count,
            net_revenue=net_revenue,
            base_uom_name=uom_names.get(base_uom_by_item.get(item_id), ""),
            transaction_quantities=breakdown.get(item_id, {}),
        )
        for item_id, (quantity_sold, invoice_count, net_revenue) in item_totals.items()
    ]
    rows.sort(key=lambda r: r.net_revenue, reverse=True)
    return rows


@dataclass
class ChannelSalesReportRow:
    channel_code: str | None
    channel_name: str
    channel_type_code: str | None
    invoice_count: int
    quantity_sold: decimal.Decimal
    net_revenue: decimal.Decimal


def compute_sales_report_by_channel(
    company_id: int, date_from: datetime.date, date_to: datetime.date,
) -> list[ChannelSalesReportRow]:
    """طبقِ بازخوردِ صریحِ کاربر («امکاناتِ حیاتیِ PeechaSync -- گزارشِ
    فروشِ اینترنتی بر اساسِ کانال»): هم‌الگو با compute_sales_report_by_item،
    فقط به‌جایِ گروه‌بندی بر اساسِ کالا، بر اساسِ کانالِ سند (POS/عمده/
    اینترنتی/نماینده/مارکت‌پلیس) گروه‌بندی می‌کند -- تا معلوم شود چند
    درصدِ فروش از کدام کانال آمده، نه فقط «فروشِ اینترنتی» به‌تنهایی."""
    with new_session() as session:
        stmt = (
            select(
                CommercialDocument.channel_code,
                func.count(func.distinct(CommercialDocument.document_id)),
                func.coalesce(func.sum(CommercialDocumentLine.quantity_base), 0),
                func.coalesce(
                    func.sum(CommercialDocumentLine.quantity * CommercialDocumentLine.unit_price - CommercialDocumentLine.discount_amount), 0,
                ),
            )
            .join(CommercialDocumentLine, CommercialDocumentLine.document_id == CommercialDocument.document_id)
            .where(
                CommercialDocument.company_id == company_id,
                CommercialDocument.document_type_code == "SALES_INVOICE",
                CommercialDocument.status_code == "POSTED",
                CommercialDocument.document_date >= date_from,
                CommercialDocument.document_date <= date_to,
            )
            .group_by(CommercialDocument.channel_code)
        )
        channel_totals = {row[0]: (row[1], row[2], row[3]) for row in session.execute(stmt)}
        channel_codes = [c for c in channel_totals if c is not None]
        channels_by_code = {
            c.channel_code: c
            for c in session.scalars(
                select(Channel).where(Channel.company_id == company_id, Channel.channel_code.in_(channel_codes))
            )
        }

    rows = [
        ChannelSalesReportRow(
            channel_code=channel_code,
            channel_name=channels_by_code[channel_code].name if channel_code in channels_by_code else "(بدونِ کانال)",
            channel_type_code=channels_by_code[channel_code].channel_type_code if channel_code in channels_by_code else None,
            invoice_count=invoice_count,
            quantity_sold=quantity_sold,
            net_revenue=net_revenue,
        )
        for channel_code, (invoice_count, quantity_sold, net_revenue) in channel_totals.items()
    ]
    rows.sort(key=lambda r: r.net_revenue, reverse=True)
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
