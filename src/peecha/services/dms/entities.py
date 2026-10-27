"""R343: فهرست رکوردهای ERP که سند به آن‌ها پیوسته می‌شود. هر نوع: جدول و ستون شناسه (برای بررسی وجود و شرکت)،
فرم‌هایی که دسترسی «مشاهده»ی هرکدام برای دیدن/پیوست کافی است، و متن نمایشی. جدول و ستون‌ها ثابت همین فهرست‌اند و
هیچ‌وقت از ورودی کاربر ساخته نمی‌شوند؛ شناسه همیشه پارامتر پرس‌وجوست."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text

from peecha import numerals
from peecha.services import roles as roles_service
from peecha.services.dms.common import escape_like


@dataclass(frozen=True)
class EntityType:
    code: str
    label: str
    forms: tuple[str, ...]
    table: str
    key: str
    display_sql: str
    active_sql: str = "TRUE"
    date_sql: str | None = None  # تاریخ رکورد جدا خوانده می‌شود تا شمسی نمایش داده شود
    kind_sql: str | None = None  # کد نوع سند که با عنوان فارسی جایگزین می‌شود


# عنوان فارسی نوع سندهای خرید و فروش و انبار (همان عنوان‌های فرم‌ها)
_KIND_TITLES = {
    "SALES_ORDER": "سفارش فروش", "SALES_PROFORMA": "پیش‌فاکتور فروش", "SALES_INVOICE": "فاکتور فروش",
    "SALES_RETURN": "برگشت از فروش", "PURCHASE_ORDER": "سفارش خرید", "PURCHASE_PROFORMA": "پیش‌فاکتور خرید",
    "PURCHASE_INVOICE": "فاکتور خرید", "PURCHASE_RETURN": "برگشت به تامین‌کننده", "CONSIGNMENT_OUT": "امانی خروجی",
    "CONSIGNMENT_IN": "امانی ورودی", "RECEIPT": "رسید", "ISSUE": "حواله", "TRANSFER": "انتقال", "RETURN_IN": "برگشت از فروش",
    "RETURN_OUT": "برگشت به تامین‌کننده", "ADJUSTMENT": "اصلاح موجودی", "CONSIGN_RETURN": "برگشت امانی",
}


_COMMERCIAL_FORMS = tuple(f"commercial_document_{t}" for t in (
    "sales_order", "sales_proforma", "sales_invoice", "sales_return", "consignment_out", "purchase_order",
    "purchase_proforma", "purchase_invoice", "purchase_return", "consignment_in")) + (
    "commercial_documents_list_sales", "commercial_documents_list_purchase")
_STOCK_FORMS = tuple(f"inventory_document_{t}" for t in ("receipt", "issue", "transfer", "return_in", "return_out", "adjustment")) + (
    "inventory_documents_list",)
_DETAIL_FORMS = ("detail_dimensions", "detail_accounts_list")

ENTITY_TYPES: dict[str, EntityType] = {e.code: e for e in (
    EntityType("journal_entry", "سند حسابداری", ("journal_entry", "journal_entries_list", "treasury_voucher_receipt",
                                                 "treasury_voucher_payment", "treasury_vouchers_list"),
               "acc.journal_entries", "journal_entry_id",
               "'سند ' || COALESCE(permanent_no::text, 'موقت ' || temporary_no::text)", date_sql="document_date"),
    EntityType("commercial_document", "سند خرید و فروش", _COMMERCIAL_FORMS, "comm.commercial_documents", "document_id",
               "document_no::text", date_sql="document_date", kind_sql="document_type_code"),
    EntityType("stock_document", "سند انبار", _STOCK_FORMS, "inv.stock_documents", "stock_document_id",
               "document_no::text", date_sql="document_date", kind_sql="document_type_code"),
    EntityType("detail_account", "تفصیلی (مشتری، تامین‌کننده، پرسنل، ...)", _DETAIL_FORMS, "acc.detail_accounts",
               "detail_account_id", "code || ' — ' || COALESCE(name, '')", "is_active"),
    EntityType("item", "کالا", _DETAIL_FORMS, "inv.items", "item_id",
               "(SELECT d.code || ' — ' || COALESCE(d.name, '') FROM acc.detail_accounts d WHERE d.detail_account_id = item_detail_account_id)"),
    EntityType("production_order", "دستور تولید", ("prd_orders",), "prd.production_orders", "order_id", "order_code",
               "status_code <> 'CANCELLED'"),
    EntityType("fixed_asset", "دارایی ثابت", ("fa_assets",), "fa.assets", "asset_id", "asset_code || ' — ' || name"),
    EntityType("work_order", "دستور کار نگهداری", ("mnt_work_orders",), "mnt.work_orders", "work_order_id",
               "wo_no::text || ' — ' || COALESCE(title, '')"),
    EntityType("qc_inspection", "بازرسی کیفیت", ("qc_queue",), "inv.qc_inspections", "qc_inspection_id",
               "'بازرسی ' || qc_inspection_id::text"),
    EntityType("nonconformance", "عدم‌انطباق", ("qc_ncr",), "qms.nonconformances", "ncr_id", "'عدم‌انطباق ' || ncr_no::text"),
    EntityType("crm_lead", "سرنخ", ("crm_leads",), "crm.leads", "lead_id", "lead_no::text || ' — ' || COALESCE(full_name, '')"),
    EntityType("service_ticket", "تیکت", ("crm_tickets",), "comm.service_tickets", "ticket_id", "'تیکت ' || ticket_no::text"),
    EntityType("employee", "پرسنل", _DETAIL_FORMS, "hr.employees", "employee_id",
               "employee_code || ' — ' || COALESCE(first_name, '') || ' ' || COALESCE(last_name, '')"),
)}


def get(entity_type: str) -> EntityType:
    entity = ENTITY_TYPES.get(entity_type)
    if entity is None:
        raise ValueError("نوع رکورد برای پیوست سند معتبر نیست.")
    return entity


def can_access(user_id: int, company_id: int, entity_type: str) -> bool:
    entity = ENTITY_TYPES.get(entity_type)
    return entity is not None and any(
        roles_service.user_has_permission(user_id, company_id, form, "VIEW") for form in entity.forms)


def _columns(entity: EntityType) -> str:
    return f"{entity.date_sql or 'NULL'} AS on_date, {entity.kind_sql or 'NULL'} AS kind"


def _label(label, when, fallback, kind=None) -> str:
    shown = numerals.to_persian_digits(str(label or fallback))
    if kind:
        shown = f"{_KIND_TITLES.get(kind, kind)} {shown}"
    return f"{shown} — {numerals.format_jalali_date(when)}" if when is not None else shown


def describe(session, company_id: int, entity_type: str, entity_id: int) -> tuple[str, bool] | None:
    """(متن نمایشی، فعال؟) رکورد همین شرکت؛ None اگر رکورد نیست یا مال شرکت دیگری است."""
    entity = get(entity_type)
    row = session.execute(text(
        f"SELECT ({entity.display_sql}) AS label, ({entity.active_sql}) AS active, {_columns(entity)} "
        f"FROM {entity.table} "
        f"WHERE {entity.key} = :id AND company_id = :company"), {"id": int(entity_id), "company": company_id}).first()
    if row is None:
        return None
    return _label(row.label, row.on_date, entity_id, row.kind), bool(row.active)


def validate(session, user_id: int, company_id: int, entity_type: str, entity_id: int) -> str:
    """پیش از پیوست: نوع معتبر، رکورد موجود و فعال در همین شرکت، و دسترسی کاربر به همان فرم‌ها."""
    entity = get(entity_type)
    found = describe(session, company_id, entity_type, entity_id)
    if found is None:
        raise LookupError(f"{entity.label} موردنظر پیدا نشد.")
    if not found[1]:
        raise ValueError(f"{entity.label} «{found[0]}» غیرفعال یا لغو شده است و سند جدید به آن پیوست نمی‌شود.")
    if not can_access(user_id, company_id, entity_type):
        raise PermissionError(f"به {entity.label} دسترسی ندارید.")
    return found[0]


def search(session, company_id: int, entity_type: str, needle: str, limit: int = 30) -> list[tuple[int, str]]:
    """برای انتخاب رکورد هنگام پیوست: جست‌وجو در متن نمایشی یا شناسهٔ دقیق، فقط رکوردهای همین شرکت."""
    entity = get(entity_type)
    raw = (needle or "").strip()
    rows = session.execute(text(
        f"SELECT {entity.key} AS id, ({entity.display_sql}) AS label, {_columns(entity)} FROM {entity.table} "
        f"WHERE company_id = :company AND (:q = '' OR ({entity.display_sql}) ILIKE :like ESCAPE '\\' OR {entity.key}::text = :q) "
        f"ORDER BY {entity.key} DESC LIMIT :limit"), {"company": company_id, "q": raw, "like": f"%{escape_like(raw)}%", "limit": limit}).all()
    return [(row.id, _label(row.label, row.on_date, row.id, row.kind)) for row in rows]
