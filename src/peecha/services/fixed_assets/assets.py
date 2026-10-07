"""شناسنامه، تحصیل، سرمایه‌ای‌شدن، انتقال و تغییر طبقهٔ دارایی — R262."""

from __future__ import annotations

import datetime
import decimal
from dataclasses import dataclass, field, fields as dc_fields
from types import SimpleNamespace

from sqlalchemy import func, select

from peecha.db.base import new_session
from peecha.db.models.fixed_assets import (
    Asset, AssetCategory, AssetCostItem, AssetEvent, AssetTransaction, DepreciationLine,
)
from peecha.services.fixed_assets import common as c

ZERO = c.ZERO
COST_TYPES = {"PURCHASE": "قیمت خرید", "TRANSPORT": "حمل", "INSTALLATION": "نصب", "CUSTOMS": "گمرک", "INSURANCE": "بیمه",
              "COMMISSION": "کارمزد", "TESTING": "آزمایش", "SETUP": "راه‌اندازی", "PROFESSIONAL": "خدمات تخصصی",
              "OTHER": "سایر هزینه‌های قابل‌سرمایه‌ای‌شدن"}
SOURCE_LABELS = {"PURCHASE": "خرید", "IMPORT": "واردات", "PRODUCTION": "تولید داخلی", "CAPITALIZATION": "سرمایه‌ای‌کردن",
                 "TRANSFER": "انتقال", "CONSTRUCTION": "ساخت (CIP)", "OPENING": "افتتاحیه", "MANUAL": "دستی", "SPLIT": "تقسیم",
                 "LEGACY": "دارایی‌های قبلی"}
_FA_REASON_CODE = "FA_CAP"


@dataclass
class AssetFields:
    asset_code: str
    name: str
    category_id: int
    asset_type_code: str = "EQUIPMENT"
    group_id: int | None = None
    description: str | None = None
    brand: str | None = None
    model: str | None = None
    serial_no: str | None = None
    part_no: str | None = None
    barcode: str | None = None
    parent_asset_id: int | None = None
    source_code: str = "MANUAL"
    acquisition_date: datetime.date | None = None
    residual_value: decimal.Decimal | None = None
    useful_life: decimal.Decimal | None = None
    useful_life_unit: str = "MONTH"
    depreciation_method: str | None = None
    declining_rate: decimal.Decimal | None = None
    branch_id: int | None = None
    department_id: int | None = None
    cost_center_detail_account_id: int | None = None
    project_detail_account_id: int | None = None
    location_id: int | None = None
    custodian_employee_id: int | None = None
    supplier_detail_account_id: int | None = None
    invoice_document_id: int | None = None
    invoice_reference: str | None = None
    currency_id: int | None = None
    exchange_rate: decimal.Decimal | None = None
    purchase_price_fc: decimal.Decimal | None = None
    is_production_machine: bool = False
    work_center_code: str | None = None
    production_line: str | None = None
    machine_rate: decimal.Decimal | None = None
    capacity_per_hour: decimal.Decimal | None = None
    standard_hours: decimal.Decimal | None = None
    notes: str | None = None


@dataclass
class CostItem:
    cost_type: str
    amount: decimal.Decimal
    offset_account_id: int | None = None
    offset_detail_account_id: int | None = None
    reference: str | None = None


# --- اعتبارسنجی ---------------------------------------------------------------------------
def _validate(session, company_id: int, f: AssetFields, asset_id: int | None) -> AssetCategory:
    if not (f.asset_code or "").strip():
        raise ValueError("کد دارایی الزامی است.")
    if not (f.name or "").strip():
        raise ValueError("نام دارایی الزامی است.")
    dup = session.scalar(select(Asset.asset_id).where(Asset.company_id == company_id, Asset.asset_code == f.asset_code.strip()))
    if dup is not None and dup != asset_id:
        raise ValueError(f"کد دارایی «{f.asset_code}» تکراری است.")
    if not f.category_id:
        raise ValueError("طبقهٔ دارایی مشخص نشده است.")
    category = session.get(AssetCategory, f.category_id)
    if category is None or category.company_id != company_id:
        raise ValueError("طبقهٔ دارایی نامعتبر است.")
    if f.asset_type_code not in c.TYPE_LABELS:
        raise ValueError("نوع دارایی نامعتبر است.")
    method = f.depreciation_method or category.default_method
    if method not in c.METHOD_LABELS:
        raise ValueError("روش استهلاک مشخص نشده است.")
    life = f.useful_life if f.useful_life is not None else category.default_life_months
    if method in ("STRAIGHT_LINE",) and not life:
        raise ValueError("برای روش خط مستقیم، عمر مفید الزامی است.")
    if method == "DECLINING_BALANCE" and not (f.declining_rate or category.default_declining_rate or life):
        raise ValueError("برای روش نزولی، نرخ یا عمر مفید الزامی است.")
    if method == "UNITS_OF_PRODUCTION" and (not f.useful_life or f.useful_life_unit not in ("HOUR", "UNIT")):
        raise ValueError("برای روش بر اساس تولید، ظرفیت کل کارکرد (ساعت/واحد) الزامی است.")
    if f.residual_value is not None and f.residual_value < 0:
        raise ValueError("ارزش اسقاط نمی‌تواند منفی باشد.")
    if f.parent_asset_id is not None:
        parent = session.get(Asset, f.parent_asset_id)
        if parent is None or parent.company_id != company_id or parent.asset_id == asset_id:
            raise ValueError("دارایی اصلی جزء نامعتبر است.")
    cost_center = f.cost_center_detail_account_id or category.default_cost_center_detail_account_id
    if (category.cost_center_required or c.settings(session, company_id).require_cost_center) and not cost_center:
        raise ValueError("مرکز هزینه برای این دارایی الزامی است.")
    return category


def _apply_fields(asset: Asset, f: AssetFields, category: AssetCategory) -> None:
    asset.asset_code, asset.name = f.asset_code.strip(), f.name.strip()
    asset.category_id, asset.group_id, asset.asset_type_code = f.category_id, f.group_id, f.asset_type_code
    for key in ("description", "brand", "model", "serial_no", "part_no", "barcode", "parent_asset_id", "source_code",
                "acquisition_date", "useful_life_unit", "branch_id", "department_id", "project_detail_account_id", "location_id",
                "custodian_employee_id", "supplier_detail_account_id", "invoice_document_id", "invoice_reference", "currency_id",
                "exchange_rate", "purchase_price_fc", "is_production_machine", "work_center_code", "production_line",
                "machine_rate", "capacity_per_hour", "standard_hours", "notes"):
        setattr(asset, key, getattr(f, key))
    asset.depreciation_method = f.depreciation_method or category.default_method
    asset.useful_life = f.useful_life if f.useful_life is not None else (
        decimal.Decimal(category.default_life_months) if category.default_life_months else None)
    if f.useful_life is None and category.default_life_months:
        asset.useful_life_unit = "MONTH"
    asset.declining_rate = f.declining_rate or category.default_declining_rate
    asset.cost_center_detail_account_id = f.cost_center_detail_account_id or category.default_cost_center_detail_account_id
    if f.residual_value is not None:
        asset.residual_value = c.money(f.residual_value)
    asset.barcode = f.barcode or asset.barcode or f.asset_code.strip()


def insert_asset(session, company_id: int, user_id: int | None, f: AssetFields, status: str = "DRAFT") -> Asset:
    """درج دارایی درون تراکنش فراخوان (برای عملیات اتمیک CIP/تقسیم)."""
    category = _validate(session, company_id, f, None)
    c.primary_book(session, company_id)
    asset = Asset(company_id=company_id, status_code=status, created_by_user_id=user_id, purchase_price=ZERO,
                  residual_value=ZERO, gross_cost=ZERO, accumulated_depreciation=ZERO, accumulated_impairment=ZERO,
                  revaluation_surplus=ZERO, units_consumed=ZERO, depreciated_months_offset=0)
    _apply_fields(asset, f, category)
    session.add(asset)
    session.flush()
    c.ensure_asset_detail(session, asset)
    c.audit(session, company_id, user_id, asset.asset_id, "CREATE",
            {"asset_code": asset.asset_code, "name": asset.name, "category_id": asset.category_id})
    return asset


def create_asset(company_id: int, user_id: int | None, f: AssetFields, status: str = "DRAFT") -> int:
    with new_session() as session:
        asset = insert_asset(session, company_id, user_id, f, status)
        session.commit()
        return asset.asset_id


_TRACKED = ("name", "category_id", "group_id", "depreciation_method", "useful_life", "residual_value", "declining_rate",
            "location_id", "custodian_employee_id", "cost_center_detail_account_id", "branch_id", "department_id", "status_code")


def update_asset(company_id: int, user_id: int | None, asset_id: int, f: AssetFields, reason: str | None = None) -> None:
    """ویرایش شناسنامه (ارقام مالی فقط از راه عملیات/دفتر عوض می‌شوند). تغییر طبقه/محل/مرکز هزینهٔ دارایی
    سرمایه‌ای‌شده باید از «تغییر طبقه/انتقال» برود تا سند و تاریخچه بسازد."""
    with new_session() as session:
        asset = c.lock_asset(session, asset_id, company_id)
        c.ensure_open(asset)
        category = _validate(session, company_id, f, asset_id)
        if asset.status_code != "DRAFT":
            for key in ("category_id", "location_id", "custodian_employee_id", "cost_center_detail_account_id", "branch_id",
                        "department_id"):
                new = getattr(f, key) if key != "cost_center_detail_account_id" else (
                    f.cost_center_detail_account_id or category.default_cost_center_detail_account_id)
                if new != getattr(asset, key):
                    raise ValueError("برای تغییر طبقه/محل/تحویل‌گیرنده/مرکز هزینه از «انتقال» یا «تغییر طبقه» استفاده کنید.")
        before = {k: getattr(asset, k) for k in _TRACKED}
        _apply_fields(asset, f, category)
        asset.updated_at = datetime.datetime.now()
        changes = {k: [str(before[k]), str(getattr(asset, k))] for k in _TRACKED if before[k] != getattr(asset, k)}
        if changes:
            c.audit(session, company_id, user_id, asset_id, "EDIT", {**changes, "reason": reason})
        c.ensure_asset_detail(session, asset)
        session.commit()


# --- تحصیل ----------------------------------------------------------------------------------
def _cost_lines(asset: Asset, category: AssetCategory, items: list[CostItem], memo: str) -> list[c.JLine]:
    total = sum((c.money(i.amount) for i in items), ZERO)
    lines = [c.JLine(category.asset_account_id, debit=total, detail_ids=(asset.cost_center_detail_account_id,
                                                                       asset.project_detail_account_id, c.asset_detail_id(asset)),
                     description=memo)]
    for i in items:
        if i.offset_account_id is None:
            raise ValueError(f"حساب طرف مقابل «{COST_TYPES.get(i.cost_type, i.cost_type)}» مشخص نشده است.")
        lines.append(c.JLine(i.offset_account_id, credit=c.money(i.amount), detail_ids=(i.offset_detail_account_id,),
                             description=f"{memo} -- {COST_TYPES.get(i.cost_type, i.cost_type)}"))
    return lines


def acquire(company_id: int, user_id: int, asset_id: int, date: datetime.date, items: list[CostItem],
            idempotency_key: str | None = None, source_code: str | None = None) -> int:
    """بهای تحصیل (قیمت خرید + حمل/نصب/گمرک/...): بدهکار حساب دارایی، بستانکار حساب‌های طرف مقابل — اتمیک.
    دوباره صدا زدن با همان idempotency_key سند دوم نمی‌سازد."""
    if not items:
        raise ValueError("حداقل یک جزء بها لازم است.")
    for i in items:
        if i.cost_type not in COST_TYPES or decimal.Decimal(i.amount) <= 0:
            raise ValueError("جزء بهای تحصیل نامعتبر است.")
    with new_session() as session:
        if idempotency_key:
            done = session.scalar(select(AssetEvent).where(AssetEvent.company_id == company_id,
                                                          AssetEvent.idempotency_key == idempotency_key))
            if done is not None:
                return done.journal_entry_id
        asset = c.lock_asset(session, asset_id, company_id)
        c.ensure_open(asset)
        if asset.status_code not in ("DRAFT", "ACQUIRED", "UNDER_CONSTRUCTION", "CAPITALIZED", "IN_SERVICE"):
            raise ValueError("در این وضعیت، بهای تحصیل قابل‌ثبت نیست.")
        category = session.get(AssetCategory, asset.category_id)
        c.require_accounts(category, ("asset_account_id",))
        book = c.primary_book(session, company_id)
        memo = f"تحصیل دارایی {asset.asset_code} -- {asset.name}"
        je_id = c.post_journal(session, company_id, user_id, date, memo, _cost_lines(asset, category, items, memo))
        total = sum((c.money(i.amount) for i in items), ZERO)
        for i in items:
            session.add(AssetCostItem(asset_id=asset_id, cost_type=i.cost_type, amount=c.money(i.amount),
                                      offset_account_id=i.offset_account_id, offset_detail_account_id=i.offset_detail_account_id,
                                      reference=i.reference, journal_entry_id=je_id))
        asset.purchase_price = c.money(asset.purchase_price + sum((c.money(i.amount) for i in items if i.cost_type == "PURCHASE"), ZERO))
        c.record_txn(session, asset, book.book_id, "ACQUISITION", date, cost=total, description=memo, journal_entry_id=je_id,
                     user_id=user_id, source_type="COST_ITEMS")
        if asset.status_code == "DRAFT":
            asset.status_code = "ACQUIRED"
        asset.acquisition_date = asset.acquisition_date or date
        if source_code:
            asset.source_code = source_code
        session.add(AssetEvent(company_id=company_id, asset_id=asset_id, event_type="STATUS", event_date=date, status_code="POSTED",
                               amount=total, reason="تحصیل", journal_entry_id=je_id, idempotency_key=idempotency_key,
                               created_by_user_id=user_id, posted_at=datetime.datetime.now()))
        c.audit(session, company_id, user_id, asset_id, "ACQUIRE", {"amount": str(total), "journal_entry_id": je_id,
                                                                   "items": [i.cost_type for i in items]})
        session.commit()
        return je_id


def _fa_reason_code(company_id: int) -> int:
    from peecha.services import inventory_documents as inv_docs

    for row in inv_docs.list_reason_codes(company_id, "ADJUSTMENT", active_only=False):
        if row.code == _FA_REASON_CODE:
            return row.reason_code_id
    return inv_docs.create_reason_code(company_id, "ADJUSTMENT", _FA_REASON_CODE, "سرمایه‌ای‌شدن به‌عنوان دارایی ثابت")


def acquire_from_receipt(company_id: int, user_id: int, f: AssetFields, stock_line_id: int, date: datetime.date,
                         quantity: decimal.Decimal = decimal.Decimal(1), extra_items: list[CostItem] | None = None) -> int:
    """خرید دارایی که با فاکتور/رسید وارد انبار شده: کالا با موتور انبار (سند اصلاح کسری با دلیل FA_CAP) خارج
    و بهایش به حساب دارایی منتقل می‌شود؛ فاکتور/رسید قابل‌ردیابی می‌ماند. تکرار برای همان ردیف رسید ممنوع است."""
    from peecha.db.models.inventory import StockDocument, StockDocumentLine, StockLedger
    from peecha.services import inventory_documents as inv_docs
    from peecha.services import inventory_engine

    with new_session() as session:
        line = session.get(StockDocumentLine, stock_line_id)
        doc = session.get(StockDocument, line.stock_document_id) if line is not None else None
        if doc is None or doc.company_id != company_id or doc.document_type_code != "RECEIPT" or doc.status_code != "POSTED":
            raise ValueError("ردیف رسید ثبت‌شده نامعتبر است.")
        if session.scalar(select(Asset.asset_id).where(Asset.source_stock_line_id == stock_line_id)) is not None:
            raise ValueError("این ردیف رسید قبلاً به دارایی تبدیل شده است.")
        category = _validate(session, company_id, f, None)
        c.require_accounts(category, ("asset_account_id",))
        loss_account = inventory_engine.get_account_mapping(company_id, "INVENTORY_ADJUSTMENT_LOSS")
        if loss_account is None:
            raise ValueError("حساب «کسری انبار» در تنظیمات انبار مشخص نشده است.")
        item_id, warehouse_id, uom_id = line.item_id, doc.destination_warehouse_id, line.uom_id
        invoice_id = None
        if doc.reference_no and doc.reference_no.startswith("COMM-"):
            invoice_id = int(doc.reference_no[5:])
    f.source_code, f.invoice_document_id = "PURCHASE", f.invoice_document_id or invoice_id
    f.supplier_detail_account_id = f.supplier_detail_account_id or doc.counterparty_detail_account_id
    asset_id = create_asset(company_id, user_id, f)
    stock_doc = inv_docs.create_stock_document(company_id, user_id, "ADJUSTMENT", date, inv_docs.DocumentHeaderFields(
        source_warehouse_id=warehouse_id, reference_no=f"FA-{asset_id}", description=f"سرمایه‌ای‌شدن دارایی {f.asset_code}"))
    inv_docs.add_line(stock_doc, company_id, inv_docs.LineFields(
        item_id=item_id, uom_id=uom_id, quantity=quantity, quantity_base=quantity, unit_cost=None,
        reason_code_id=_fa_reason_code(company_id), source_line_id=stock_line_id))
    inv_docs.confirm_stock_document(stock_doc, company_id)
    inv_docs.post_stock_document(stock_doc, company_id, user_id)
    with new_session() as session:
        asset = c.lock_asset(session, asset_id, company_id)
        asset.source_stock_line_id, asset.capitalization_stock_document_id = stock_line_id, stock_doc
        session.commit()
        issued = session.scalar(select(func.coalesce(func.sum(StockLedger.quantity_base * StockLedger.unit_cost), 0))
                                .join(StockDocumentLine, StockDocumentLine.line_id == StockLedger.stock_document_line_id)
                                .where(StockDocumentLine.stock_document_id == stock_doc, StockLedger.movement_direction == "OUT"))
    items = [CostItem("PURCHASE", c.money(issued), loss_account, None, f"رسید → دارایی (سند انبار {stock_doc})")]
    acquire(company_id, user_id, asset_id, date, items + list(extra_items or []), idempotency_key=f"FA-RCPT-{stock_line_id}",
            source_code="PURCHASE")
    return asset_id


def complete_receipt_acquisition(company_id: int, user_id: int, asset_id: int, date: datetime.date) -> int | None:
    """اگر خروج انبار انجام شد ولی ثبت دارایی (مثلاً قطع برق) نماند، همان مبلغ را بدون خروج دوباره ثبت می‌کند."""
    from peecha.db.models.inventory import StockDocumentLine, StockLedger
    from peecha.services import inventory_engine

    with new_session() as session:
        asset = session.get(Asset, asset_id)
        if asset is None or asset.company_id != company_id or asset.capitalization_stock_document_id is None:
            raise ValueError("این دارایی از رسید انبار نیامده است.")
        if asset.status_code != "DRAFT":
            return None
        issued = session.scalar(select(func.coalesce(func.sum(StockLedger.quantity_base * StockLedger.unit_cost), 0))
                                .join(StockDocumentLine, StockDocumentLine.line_id == StockLedger.stock_document_line_id)
                                .where(StockDocumentLine.stock_document_id == asset.capitalization_stock_document_id,
                                       StockLedger.movement_direction == "OUT"))
        line_id = asset.source_stock_line_id
    return acquire(company_id, user_id, asset_id, date, [CostItem(
        "PURCHASE", c.money(issued), inventory_engine.get_account_mapping(company_id, "INVENTORY_ADJUSTMENT_LOSS"))],
        idempotency_key=f"FA-RCPT-{line_id}", source_code="PURCHASE")


# --- سرمایه‌ای‌شدن و بهره‌برداری ------------------------------------------------------------------
def depreciation_start(rule: str, *, acquisition: datetime.date | None, in_service: datetime.date | None,
                       capitalization: datetime.date, specific: datetime.date | None) -> datetime.date:
    if rule == "SPECIFIC" and specific:
        return specific
    if rule == "ACQUISITION" and acquisition:
        return acquisition
    base = in_service or capitalization
    if rule == "NEXT_MONTH":
        return c.add_months(base, 1)
    return base


def capitalize(company_id: int, user_id: int, asset_id: int, date: datetime.date, in_service_date: datetime.date | None = None,
               depreciation_start_date: datetime.date | None = None, reason: str | None = None) -> None:
    """تحصیل‌شده ← سرمایه‌ای‌شده (و اگر تاریخ بهره‌برداری داده شود، در حال بهره‌برداری). شروع استهلاک طبق سیاست تنظیمات."""
    with new_session() as session:
        asset = c.lock_asset(session, asset_id, company_id)
        c.ensure_open(asset)
        if asset.status_code not in ("ACQUIRED", "UNDER_CONSTRUCTION"):
            raise ValueError("فقط دارایی تحصیل‌شده قابل‌سرمایه‌ای‌شدن است.")
        if asset.gross_cost <= 0:
            raise ValueError("بهای تحصیل دارایی ثبت نشده است.")
        category = session.get(AssetCategory, asset.category_id)
        needed = ("asset_account_id",) if asset.depreciation_method == "NONE" else (
            "asset_account_id", "accumulated_depreciation_account_id", "depreciation_expense_account_id")
        c.require_accounts(category, needed)
        if not asset.residual_value and category.default_residual_percent:
            asset.residual_value = c.money(asset.gross_cost * category.default_residual_percent / 100)
        if asset.residual_value > asset.gross_cost:
            raise ValueError("ارزش اسقاط از بهای دارایی بیشتر است.")
        rule = c.settings(session, company_id).depreciation_start_rule
        asset.capitalization_date = date
        asset.in_service_date = in_service_date
        asset.depreciation_start_date = depreciation_start(rule, acquisition=asset.acquisition_date, in_service=in_service_date,
                                                          capitalization=date, specific=depreciation_start_date)
        asset.status_code = "IN_SERVICE" if in_service_date else "CAPITALIZED"
        book = c.primary_book(session, company_id)
        c.record_txn(session, asset, book.book_id, "CAPITALIZATION", date, description=reason or "سرمایه‌ای‌شدن", user_id=user_id)
        session.add(AssetEvent(company_id=company_id, asset_id=asset_id, event_type="CAPITALIZATION", event_date=date,
                               status_code="POSTED", amount=asset.gross_cost, reason=reason, created_by_user_id=user_id,
                               details={"depreciation_start": asset.depreciation_start_date.isoformat(), "rule": rule},
                               posted_at=datetime.datetime.now()))
        c.audit(session, company_id, user_id, asset_id, "CAPITALIZE",
                {"status": asset.status_code, "depreciation_start": asset.depreciation_start_date.isoformat()})
        session.commit()


def put_in_service(company_id: int, user_id: int, asset_id: int, date: datetime.date) -> None:
    with new_session() as session:
        asset = c.lock_asset(session, asset_id, company_id)
        c.ensure_open(asset)
        if asset.status_code not in ("CAPITALIZED", "UNDER_MAINTENANCE", "SUSPENDED"):
            raise ValueError("این دارایی برای شروع بهره‌برداری آماده نیست.")
        previous = asset.status_code
        asset.status_code, asset.in_service_date = "IN_SERVICE", asset.in_service_date or date
        if previous == "CAPITALIZED" and c.settings(session, company_id).depreciation_start_rule in ("IN_SERVICE", "NEXT_MONTH") \
                and not asset.accumulated_depreciation:
            asset.depreciation_start_date = depreciation_start(
                c.settings(session, company_id).depreciation_start_rule, acquisition=asset.acquisition_date, in_service=date,
                capitalization=asset.capitalization_date or date, specific=None)
        session.add(AssetEvent(company_id=company_id, asset_id=asset_id, event_type="STATUS", event_date=date, status_code="POSTED",
                               details={"from": previous, "to": "IN_SERVICE"}, created_by_user_id=user_id,
                               posted_at=datetime.datetime.now()))
        c.audit(session, company_id, user_id, asset_id, "STATUS", {"status_code": [previous, "IN_SERVICE"]})
        session.commit()


def set_status(company_id: int, user_id: int, asset_id: int, status: str, date: datetime.date, reason: str | None = None) -> None:
    """وضعیت‌های عملیاتی (در تعمیر/متوقف/بهره‌برداری)؛ واگذاری فقط از عملیات فروش/اسقاط."""
    if status not in ("UNDER_MAINTENANCE", "SUSPENDED", "IN_SERVICE"):
        raise ValueError("این وضعیت را فقط عملیات مربوط تعیین می‌کند.")
    with new_session() as session:
        asset = c.lock_asset(session, asset_id, company_id)
        c.ensure_open(asset)
        if asset.status_code in ("DRAFT", "ACQUIRED", "UNDER_CONSTRUCTION"):
            raise ValueError("دارایی سرمایه‌ای‌نشده وضعیت عملیاتی ندارد.")
        previous = asset.status_code
        asset.status_code = status
        session.add(AssetEvent(company_id=company_id, asset_id=asset_id, event_type="STATUS", event_date=date, status_code="POSTED",
                               reason=reason, details={"from": previous, "to": status}, created_by_user_id=user_id,
                               posted_at=datetime.datetime.now()))
        c.audit(session, company_id, user_id, asset_id, "STATUS", {"status_code": [previous, status], "reason": reason})
        session.commit()


# --- انتقال و تغییرِ طبقه --------------------------------------------------------------------------
TRANSFER_FIELDS = {"branch_id": "شعبه", "department_id": "دپارتمان", "cost_center_detail_account_id": "مرکز هزینه",
                   "project_detail_account_id": "پروژه", "location_id": "محل", "custodian_employee_id": "تحویل‌گیرنده"}


def transfer(company_id: int, user_id: int, asset_id: int, date: datetime.date, reason: str | None = None,
             idempotency_key: str | None = None, **targets) -> int:
    """انتقال بین شعبه/دپارتمان/مرکز هزینه/محل/تحویل‌گیرنده — تاریخچه در رویدادها و دفتر؛ استهلاک بعدی با مرکز هزینهٔ جدید."""
    unknown = set(targets) - set(TRANSFER_FIELDS)
    if unknown:
        raise ValueError(f"فیلد انتقال نامعتبر: {', '.join(unknown)}")
    with new_session() as session:
        if idempotency_key:
            done = session.scalar(select(AssetEvent.event_id).where(AssetEvent.company_id == company_id,
                                                                    AssetEvent.idempotency_key == idempotency_key))
            if done is not None:
                return done
        asset = c.lock_asset(session, asset_id, company_id)
        c.ensure_open(asset)
        changes = {k: [getattr(asset, k), v] for k, v in targets.items() if getattr(asset, k) != v}
        if not changes:
            raise ValueError("هیچ تغییری برای انتقال انتخاب نشده است.")
        category = session.get(AssetCategory, asset.category_id)
        if "cost_center_detail_account_id" in changes and not targets["cost_center_detail_account_id"] and (
                category.cost_center_required or c.settings(session, company_id).require_cost_center):
            raise ValueError("مرکز هزینه برای این دارایی الزامی است.")
        for k, (_old, new) in changes.items():
            setattr(asset, k, new)
        asset.updated_at = datetime.datetime.now()
        event = AssetEvent(company_id=company_id, asset_id=asset_id, event_type="TRANSFER", event_date=date, status_code="POSTED",
                           reason=reason, details={k: v for k, v in changes.items()}, idempotency_key=idempotency_key,
                           created_by_user_id=user_id, posted_at=datetime.datetime.now())
        session.add(event)
        session.flush()
        book = c.primary_book(session, company_id)
        c.record_txn(session, asset, book.book_id, "TRANSFER", date, user_id=user_id, source_type="EVENT", source_id=event.event_id,
                     description="انتقال: " + "، ".join(TRANSFER_FIELDS[k] for k in changes))
        c.audit(session, company_id, user_id, asset_id, "TRANSFER", {**{k: [str(o), str(n)] for k, (o, n) in changes.items()},
                                                                    "reason": reason})
        session.commit()
        return event.event_id


def reclassify(company_id: int, user_id: int, asset_id: int, new_category_id: int, date: datetime.date,
               reason: str | None = None, adopt_defaults: bool = False) -> int:
    """تغییر طبقه (مثلاً تجهیزات ← ماشین‌آلات تولید) بدون ازدست‌رفتن تاریخچه؛ اگر حساب‌ها فرق کنند، بها و استهلاک
    انباشته با یک سند بین حساب‌ها جابه‌جا می‌شوند."""
    with new_session() as session:
        asset = c.lock_asset(session, asset_id, company_id)
        c.ensure_open(asset)
        old = session.get(AssetCategory, asset.category_id)
        new = session.get(AssetCategory, new_category_id)
        if new is None or new.company_id != company_id or new.category_id == old.category_id:
            raise ValueError("طبقهٔ مقصد نامعتبر است.")
        je_id = None
        if asset.gross_cost and asset.status_code not in ("DRAFT",):
            c.require_accounts(new, ("asset_account_id",) + (("accumulated_depreciation_account_id",)
                                                              if asset.accumulated_depreciation + asset.accumulated_impairment else ()))
            accumulated = asset.accumulated_depreciation + asset.accumulated_impairment
            dims = (asset.cost_center_detail_account_id, asset.project_detail_account_id, c.asset_detail_id(asset))
            memo = f"تغییر طبقهٔ دارایی {asset.asset_code}: {old.name} ← {new.name}"
            lines = [c.JLine(new.asset_account_id, debit=asset.gross_cost, detail_ids=dims),
                     c.JLine(old.asset_account_id, credit=asset.gross_cost, detail_ids=dims)]
            if accumulated:
                lines += [c.JLine(old.accumulated_depreciation_account_id, debit=accumulated, detail_ids=dims),
                          c.JLine(new.accumulated_depreciation_account_id, credit=accumulated, detail_ids=dims)]
            je_id = c.post_journal(session, company_id, user_id, date, memo, lines)
        asset.category_id = new.category_id
        if adopt_defaults:
            asset.depreciation_method = new.default_method
            if new.default_life_months:
                asset.useful_life, asset.useful_life_unit = decimal.Decimal(new.default_life_months), "MONTH"
        event = AssetEvent(company_id=company_id, asset_id=asset_id, event_type="RECLASS", event_date=date, status_code="POSTED",
                           reason=reason, details={"category_id": [old.category_id, new.category_id]}, journal_entry_id=je_id,
                           created_by_user_id=user_id, posted_at=datetime.datetime.now())
        session.add(event)
        session.flush()
        c.record_txn(session, asset, c.primary_book(session, company_id).book_id, "RECLASS", date, journal_entry_id=je_id,
                     user_id=user_id, source_type="EVENT", source_id=event.event_id, description=f"{old.name} ← {new.name}")
        c.audit(session, company_id, user_id, asset_id, "RECLASSIFY",
                {"category_id": [old.category_id, new.category_id], "reason": reason, "journal_entry_id": je_id})
        session.commit()
        return event.event_id


# --- خواندن ------------------------------------------------------------------------------------
@dataclass
class AssetRow:
    asset_id: int
    asset_code: str
    name: str
    category_id: int
    category_name: str
    status_code: str
    gross_cost: decimal.Decimal
    accumulated_depreciation: decimal.Decimal
    accumulated_impairment: decimal.Decimal
    book_value: decimal.Decimal
    location_id: int | None
    cost_center_detail_account_id: int | None
    custodian_employee_id: int | None
    branch_id: int | None
    parent_asset_id: int | None
    is_production_machine: bool
    acquisition_date: datetime.date | None
    extra: dict = field(default_factory=dict)


def list_assets(company_id: int, *, category_id: int | None = None, status: str | None = None, location_id: int | None = None,
                cost_center_id: int | None = None, search: str | None = None, include_closed: bool = True) -> list[AssetRow]:
    with new_session() as session:
        q = (select(Asset, AssetCategory.name).join(AssetCategory, AssetCategory.category_id == Asset.category_id)
             .where(Asset.company_id == company_id))
        if category_id:
            q = q.where(Asset.category_id == category_id)
        if status:
            q = q.where(Asset.status_code == status)
        if location_id:
            q = q.where(Asset.location_id == location_id)
        if cost_center_id:
            q = q.where(Asset.cost_center_detail_account_id == cost_center_id)
        if not include_closed:
            q = q.where(Asset.status_code.not_in(c.CLOSED_STATUSES))
        if search:
            like = f"%{search.strip()}%"
            q = q.where(Asset.asset_code.ilike(like) | Asset.name.ilike(like) | Asset.serial_no.ilike(like)
                        | Asset.barcode.ilike(like))
        return [AssetRow(a.asset_id, a.asset_code, a.name, a.category_id, cat, a.status_code, a.gross_cost,
                         a.accumulated_depreciation, a.accumulated_impairment, a.book_value, a.location_id,
                         a.cost_center_detail_account_id, a.custodian_employee_id, a.branch_id, a.parent_asset_id,
                         a.is_production_machine, a.acquisition_date)
                for a, cat in session.execute(q.order_by(Asset.asset_code)).all()]


def get_asset(company_id: int, asset_id: int) -> Asset:
    with new_session() as session:
        asset = session.get(Asset, asset_id)
        if asset is None or asset.company_id != company_id:
            raise ValueError("دارایی نامعتبر است.")
        session.expunge(asset)
        return asset


def find_by_code(company_id: int, code: str) -> Asset | None:
    """جستجو با کد/بارکد/محتوای QR (PEECHA-FA:شناسه:کد)."""
    code = (code or "").strip()
    with new_session() as session:
        if code.startswith("PEECHA-FA:"):
            parts = code.split(":")
            asset = session.get(Asset, int(parts[1])) if len(parts) > 1 and parts[1].isdigit() else None
        else:
            asset = session.scalar(select(Asset).where(Asset.company_id == company_id,
                                                       (Asset.asset_code == code) | (Asset.barcode == code)))
        if asset is None or asset.company_id != company_id:
            return None
        session.expunge(asset)
        return asset


def qr_payload(asset: Asset) -> str:
    return f"PEECHA-FA:{asset.asset_id}:{asset.asset_code}"


def ledger(company_id: int, asset_id: int) -> list[SimpleNamespace]:
    """دفتر دارایی با ماندهٔ جاری ارزش دفتری."""
    with new_session() as session:
        rows = session.scalars(select(AssetTransaction).where(AssetTransaction.asset_id == asset_id,
                                                              AssetTransaction.company_id == company_id)
                               .order_by(AssetTransaction.txn_date, AssetTransaction.txn_id)).all()
        out, nbv = [], ZERO
        for t in rows:
            nbv += t.cost_delta - t.depreciation_delta - t.impairment_delta
            out.append(SimpleNamespace(txn_id=t.txn_id, date=t.txn_date, txn_type=t.txn_type,
                                       label=c.TXN_LABELS.get(t.txn_type, t.txn_type), cost=t.cost_delta,
                                       depreciation=t.depreciation_delta, impairment=t.impairment_delta,
                                       revaluation=t.revaluation_delta, book_value=nbv, description=t.description,
                                       journal_entry_id=t.journal_entry_id, user_id=t.created_by_user_id, reference=t.reference,
                                       units=t.units))
        return out


def events(company_id: int, asset_id: int, event_type: str | None = None) -> list[AssetEvent]:
    with new_session() as session:
        q = select(AssetEvent).where(AssetEvent.asset_id == asset_id, AssetEvent.company_id == company_id)
        if event_type:
            q = q.where(AssetEvent.event_type == event_type)
        rows = list(session.scalars(q.order_by(AssetEvent.event_date, AssetEvent.event_id)))
        for r in rows:
            session.expunge(r)
        return rows


def cost_items(asset_id: int) -> list[AssetCostItem]:
    with new_session() as session:
        rows = list(session.scalars(select(AssetCostItem).where(AssetCostItem.asset_id == asset_id)
                                    .order_by(AssetCostItem.cost_item_id)))
        for r in rows:
            session.expunge(r)
        return rows


def depreciation_history(asset_id: int) -> list[DepreciationLine]:
    from peecha.db.models.fixed_assets import DepreciationRun

    with new_session() as session:
        rows = session.execute(select(DepreciationLine, DepreciationRun.period_code, DepreciationRun.status_code)
                               .join(DepreciationRun, DepreciationRun.run_id == DepreciationLine.run_id)
                               .where(DepreciationLine.asset_id == asset_id)
                               .order_by(DepreciationRun.period_start)).all()
        return [SimpleNamespace(period_code=p, status=s, amount=ln.amount, opening=ln.opening_book_value,
                                closing=ln.closing_book_value, units=ln.units) for ln, p, s in rows]


def fields_of(asset: Asset) -> AssetFields:
    """شناسنامهٔ فعلی به‌صورت AssetFields (برای ویرایش)."""
    return AssetFields(**{f.name: getattr(asset, f.name) for f in dc_fields(AssetFields)})
