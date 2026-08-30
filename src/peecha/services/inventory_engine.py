"""موتورِ پستِ اسنادِ انبار (inv.stock_documents → stock_ledger → stock_balance).

طبقِ سندِ معماری (مرحله‌هایِ ۵، ۶، ۸): تنها نقطهٔ نوشتنِ inv.stock_ledger/
stock_balance همین‌جاست — هیچ کدِ دیگری مستقیماً این دو جدول را تغییر
نمی‌دهد. سه روشِ قیمت‌گذاری (FIFO/میانگینِ موزون/استاندارد) دقیقاً درونِ
همین گامِ Post اجرا می‌شوند، نه یک مرحلهٔ جدا. هر Postِ موفق، سندِ
حسابداریِ خودکار را از رویِ inv.account_mappings می‌سازد؛ اگر کلیدِ لازم
نگاشت نشده باشد، Post متوقف می‌شود و پیامِ روشن نمایش داده می‌شود، نه
سکوت — دقیقاً همان اصلی که برایِ خزانه‌داری اجرا شده."""

from __future__ import annotations

import datetime
import decimal
from dataclasses import dataclass

from sqlalchemy import func, select

from peecha.db.base import new_session
from peecha.db.models.accounting import DetailAccount, FiscalYear
from peecha.db.models.inventory import (
    BinLocation,
    CategoryAccountMapping,
    CompanyCostingSettings,
    CompanyFeature,
    CostingMethod,
    CostLayer,
    FeatureDefinition,
    InventoryAccountMapping,
    Item,
    StandardCost,
    StockBalance,
    StockDocument,
    StockDocumentLine,
    StockLedger,
    Warehouse,
    WarehouseAccountMapping,
)
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import journal_entries as je_service

_Q2 = decimal.Decimal("0.01")
_ZERO = decimal.Decimal(0)

MAPPING_LABELS: dict[str, str] = {
    "INVENTORY_ASSET": "داراییِ موجودیِ کالا",
    "COGS": "بهایِ تمام‌شدهٔ کالایِ فروخته/مصرف‌شده",
    "INVENTORY_ADJUSTMENT_GAIN": "مازادِ اصلاحِ موجودی",
    "INVENTORY_ADJUSTMENT_LOSS": "کسریِ اصلاحِ موجودی",
    "INVENTORY_COST_VARIANCE": "مغایرتِ بهایِ استاندارد",
    "SUPPLIER_PAYABLE": "حساب‌هایِ پرداختنیِ تامین‌کنندگان",
    "CUSTOMER_RECEIVABLE": "حساب‌هایِ دریافتنیِ مشتریان",
    "PURCHASE_TAX_RECEIVABLE": "مالياتِ خرید — قابلِ مطالبه",
}


def _money(value: decimal.Decimal) -> decimal.Decimal:
    return value.quantize(_Q2, rounding=decimal.ROUND_HALF_UP)


# ---------------------------------------------------------------------
# نگاشتِ حساب‌ها (inv.account_mappings)
# ---------------------------------------------------------------------
@dataclass
class AccountMappingRow:
    mapping_key: str
    label: str
    account_id: int | None
    account_label: str | None
    detail_account_id: int | None = None


def get_account_mapping(company_id: int, mapping_key: str) -> int | None:
    with new_session() as session:
        row = session.get(InventoryAccountMapping, (company_id, mapping_key))
        return row.account_id if row is not None else None


def get_account_mapping_detail(company_id: int, mapping_key: str) -> int | None:
    """تفصیلیِ ثابتِ ازپیش‌تخصیص‌یافته (اگر تنظیم شده باشد) برایِ این
    حسابِ نقش‌محور -- طبقِ رفعِ باگِ واقعی («حسابِ مالياتِ خرید تفصیلی
    می‌خواهد ولی جایی برایِ انتخابش نیست»)."""
    with new_session() as session:
        row = session.get(InventoryAccountMapping, (company_id, mapping_key))
        return row.detail_account_id if row is not None else None


def set_account_mapping(company_id: int, mapping_key: str, account_id: int, detail_account_id: int | None = None) -> None:
    if mapping_key not in MAPPING_LABELS:
        raise ValueError("کلیدِ نگاشتِ نامعتبر است.")
    with new_session() as session:
        row = session.get(InventoryAccountMapping, (company_id, mapping_key))
        if row is None:
            session.add(
                InventoryAccountMapping(
                    company_id=company_id, mapping_key=mapping_key, account_id=account_id,
                    detail_account_id=detail_account_id,
                )
            )
        else:
            row.account_id = account_id
            row.detail_account_id = detail_account_id
        session.commit()


def list_account_mappings(company_id: int) -> list[AccountMappingRow]:
    from peecha.services import chart_of_accounts as coa_service

    with new_session() as session:
        rows = {
            r.mapping_key: (r.account_id, r.detail_account_id)
            for r in session.scalars(select(InventoryAccountMapping).where(InventoryAccountMapping.company_id == company_id))
        }
    accounts_by_id = {a.account_id: f"{a.full_code} — {a.name}" for a in coa_service.list_accounts(company_id)}
    result = []
    for key, label in MAPPING_LABELS.items():
        account_id, detail_account_id = rows.get(key, (None, None))
        result.append(
            AccountMappingRow(key, label, account_id, accounts_by_id.get(account_id) if account_id else None, detail_account_id)
        )
    return result


def _resolve_role_account(session, company_id: int, mapping_key: str) -> int:
    row = session.get(InventoryAccountMapping, (company_id, mapping_key))
    if row is None:
        raise ValueError(f"حسابِ «{MAPPING_LABELS.get(mapping_key, mapping_key)}» هنوز در تنظیماتِ انبار مشخص نشده است.")
    return row.account_id


# ---------------------------------------------------------------------
# تنظیماتِ قیمت‌گذاریِ شرکت
# ---------------------------------------------------------------------
def get_costing_settings(company_id: int) -> tuple[str | None, bool]:
    with new_session() as session:
        row = session.get(CompanyCostingSettings, company_id)
        if row is None:
            return None, True
        method = session.get(CostingMethod, row.default_costing_method_id)
        return (method.code if method is not None else None), row.allow_item_override


def set_costing_settings(company_id: int, default_costing_method_code: str, allow_item_override: bool = True) -> None:
    with new_session() as session:
        method = session.scalar(select(CostingMethod).where(CostingMethod.code == default_costing_method_code))
        if method is None:
            raise ValueError("روشِ قیمت‌گذاری نامعتبر است.")
        row = session.get(CompanyCostingSettings, company_id)
        if row is None:
            session.add(
                CompanyCostingSettings(
                    company_id=company_id, default_costing_method_id=method.costing_method_id,
                    allow_item_override=allow_item_override,
                )
            )
        else:
            row.default_costing_method_id = method.costing_method_id
            row.allow_item_override = allow_item_override
        session.commit()


# ---------------------------------------------------------------------
# Feature Toggle (inv.feature_definitions/inv.company_features)
# ---------------------------------------------------------------------
@dataclass
class FeatureRow:
    feature_code: str
    name: str
    category: str
    requires_feature_code: str | None
    is_enabled: bool


def list_features(company_id: int) -> list[FeatureRow]:
    with new_session() as session:
        definitions = session.scalars(select(FeatureDefinition)).all()
        enabled = {
            r.feature_code
            for r in session.scalars(
                select(CompanyFeature).where(CompanyFeature.company_id == company_id, CompanyFeature.is_enabled.is_(True))
            )
        }
        return [
            FeatureRow(d.feature_code, d.name, d.category, d.requires_feature_code, d.feature_code in enabled)
            for d in definitions
        ]


def set_feature_enabled(company_id: int, feature_code: str, is_enabled: bool) -> None:
    with new_session() as session:
        definition = session.get(FeatureDefinition, feature_code)
        if definition is None:
            raise ValueError("ویژگیِ نامعتبر است.")
        if is_enabled and definition.requires_feature_code is not None:
            dep_row = session.get(CompanyFeature, (company_id, definition.requires_feature_code))
            if dep_row is None or not dep_row.is_enabled:
                dep = session.get(FeatureDefinition, definition.requires_feature_code)
                raise ValueError(f"ابتدا باید ویژگیِ «{dep.name}» فعال شود.")
        row = session.get(CompanyFeature, (company_id, feature_code))
        if row is None:
            session.add(CompanyFeature(company_id=company_id, feature_code=feature_code, is_enabled=is_enabled))
        else:
            row.is_enabled = is_enabled
        session.commit()


def is_feature_enabled(company_id: int, feature_code: str) -> bool:
    with new_session() as session:
        row = session.get(CompanyFeature, (company_id, feature_code))
        return row is not None and row.is_enabled


# ---------------------------------------------------------------------
# استعلامِ موجودی
# ---------------------------------------------------------------------
@dataclass
class BalanceRow:
    stock_balance_id: int
    item_id: int
    warehouse_id: int
    bin_location_id: int
    quantity_on_hand: decimal.Decimal
    quantity_reserved: decimal.Decimal
    quantity_available: decimal.Decimal
    average_unit_cost: decimal.Decimal
    total_value: decimal.Decimal


def list_balances(company_id: int, item_id: int | None = None, warehouse_id: int | None = None) -> list[BalanceRow]:
    with new_session() as session:
        query = select(StockBalance).where(StockBalance.company_id == company_id, StockBalance.batch_id.is_(None))
        if item_id is not None:
            query = query.where(StockBalance.item_id == item_id)
        if warehouse_id is not None:
            query = query.where(StockBalance.warehouse_id == warehouse_id)
        rows = session.scalars(query).all()
        return [
            BalanceRow(
                r.stock_balance_id, r.item_id, r.warehouse_id, r.bin_location_id, r.quantity_on_hand,
                r.quantity_reserved, r.quantity_available, r.average_unit_cost, r.total_value,
            )
            for r in rows
        ]


def get_item_total_on_hand(item_id: int) -> decimal.Decimal:
    with new_session() as session:
        total = session.scalar(
            select(func.coalesce(func.sum(StockBalance.quantity_on_hand), 0)).where(StockBalance.item_id == item_id)
        )
        return total or _ZERO


@dataclass
class WarehouseStockRow:
    warehouse_id: int
    warehouse_name: str
    quantity_on_hand: decimal.Decimal


def get_item_stock_by_warehouse(company_id: int, item_id: int) -> list[WarehouseStockRow]:
    """موجودیِ یک کالا در هر انبار -- برخلافِ list_balances، بدونِ فیلترِ
    batch_id تا موجودیِ ردیابی‌شده بر اساسِ بچ هم در جمعِ هر انبار بیاید."""
    with new_session() as session:
        rows = session.execute(
            select(Warehouse.warehouse_id, Warehouse.name, func.coalesce(func.sum(StockBalance.quantity_on_hand), 0))
            .join(StockBalance, StockBalance.warehouse_id == Warehouse.warehouse_id)
            .where(StockBalance.company_id == company_id, StockBalance.item_id == item_id)
            .group_by(Warehouse.warehouse_id, Warehouse.name)
            .order_by(Warehouse.name)
        ).all()
        return [WarehouseStockRow(wid, name, qty or _ZERO) for wid, name, qty in rows]


@dataclass
class ItemLedgerRow:
    movement_date: datetime.date
    document_type_code: str
    document_no: int
    warehouse_name: str
    quantity_in: decimal.Decimal
    quantity_out: decimal.Decimal
    unit_cost: decimal.Decimal | None
    running_balance: decimal.Decimal
    counterparty_detail_account_id: int | None


def list_item_ledger(
    company_id: int, item_id: int, warehouse_id: int | None = None,
    date_from: datetime.date | None = None, date_to: datetime.date | None = None,
) -> list[ItemLedgerRow]:
    """کاردکسِ یک کالا -- مانده‌یِ رواگرد همیشه با جمعِ *همه‌یِ* حرکاتِ
    تاریخی تا date_to محاسبه می‌شود (نه فقط ردیف‌هایِ نمایش‌داده‌شده)، و
    فقط پس‌ازآن ردیف‌هایِ زودتر از date_from از خروجی کنار گذاشته می‌شوند --
    وگرنه مانده‌یِ نمایش‌داده‌شده از همان ابتدایِ بازه غلط می‌شد."""
    with new_session() as session:
        query = (
            select(
                StockLedger.movement_date, StockDocument.document_type_code, StockDocument.document_no,
                Warehouse.name, StockLedger.movement_direction, StockLedger.quantity_base, StockLedger.unit_cost,
                StockLedger.ledger_id, StockDocument.counterparty_detail_account_id, StockDocumentLine.tax_amount,
            )
            .join(StockDocumentLine, StockDocumentLine.line_id == StockLedger.stock_document_line_id)
            .join(StockDocument, StockDocument.stock_document_id == StockDocumentLine.stock_document_id)
            .join(Warehouse, Warehouse.warehouse_id == StockLedger.warehouse_id)
            .where(StockLedger.company_id == company_id, StockLedger.item_id == item_id)
        )
        if warehouse_id is not None:
            query = query.where(StockLedger.warehouse_id == warehouse_id)
        if date_to is not None:
            query = query.where(StockLedger.movement_date <= date_to)
        query = query.order_by(StockLedger.movement_date, StockLedger.ledger_id)
        rows = session.execute(query).all()

    result: list[ItemLedgerRow] = []
    balance = _ZERO
    for movement_date, doc_type, doc_no, warehouse_name, direction, quantity, unit_cost, _ledger_id, counterparty_id, tax_amount in rows:
        signed = quantity if direction == "IN" else -quantity
        balance += signed
        if date_from is not None and movement_date < date_from:
            continue
        # طبقِ درخواستِ صریح («بهایِ تمام‌شده باید با احتسابِ مالياتِ
        # فاکتور ثبت شود -- فی ۱۰۰ با ۱۰٪ مالیات باید ۱۱۰ نشان بدهد»):
        # بهایِ نمایش‌داده‌شده در کاردکس، بهایِ رواگردِ کالا به‌اضافه‌یِ
        # سهمِ هرواحد از مالياتِ همان ردیف است -- این فقط برایِ *نمایش*
        # در همین گزارش است، نه بهایِ خالصی که در حسابداری (دفترِ کل/
        # موجودی) طبقِ رفعِ باگِ قبلی (R17-2/R17-3) عمداً بدونِ مالیات و
        # مبنایِ بدهکارِ «مالياتِ خرید-قابلِ مطالبه» ثبت می‌شود.
        landed_unit_cost = unit_cost
        if unit_cost is not None and tax_amount and quantity:
            landed_unit_cost = _money(unit_cost + (tax_amount / quantity))
        result.append(
            ItemLedgerRow(
                movement_date, doc_type, doc_no, warehouse_name,
                quantity if direction == "IN" else _ZERO, quantity if direction == "OUT" else _ZERO,
                landed_unit_cost, balance, counterparty_id,
            )
        )
    return result


@dataclass
class ItemCostHistoryRow:
    stock_document_id: int
    document_type_code: str
    document_no: int
    document_date: datetime.date
    unit_cost: decimal.Decimal


def list_item_cost_history(
    company_id: int, item_id: int, counterparty_detail_account_id: int, limit: int = 10,
) -> list[ItemCostHistoryRow]:
    """طبقِ درخواستِ صریح («۱۰ قیمتِ آخرِ کالا به طرفِ‌حساب» -- در فرم‌هایِ
    انبار معادلِ آن بهایِ واحدِ رسیدهایِ ثبت‌شده از همان طرفِ‌حساب است).
    طبقِ رفعِ باگِ واقعیِ بعدی («بهایِ تمام‌شده باید با احتسابِ مالياتِ
    فاکتور نمایش داده شود»)، بهایِ برگردانده‌شده، بهایِ رواگرد به‌اضافه‌یِ
    سهمِ هرواحد از مالياتِ همان ردیف است -- فقط برایِ نمایش، بدونِ تغییر
    در بهایِ خالصی که در حسابداری/موجودی ثبت شده."""
    with new_session() as session:
        rows = session.execute(
            select(
                StockDocument.stock_document_id, StockDocument.document_type_code, StockDocument.document_no,
                StockDocument.document_date, StockDocumentLine.unit_cost, StockDocumentLine.tax_amount,
                StockDocumentLine.quantity_base,
            )
            .join(StockDocumentLine, StockDocumentLine.stock_document_id == StockDocument.stock_document_id)
            .where(
                StockDocument.company_id == company_id,
                StockDocument.counterparty_detail_account_id == counterparty_detail_account_id,
                StockDocument.status_code == "POSTED",
                StockDocumentLine.item_id == item_id,
                StockDocumentLine.unit_cost.is_not(None),
            )
            .order_by(StockDocument.document_date.desc(), StockDocument.stock_document_id.desc())
            .limit(limit)
        ).all()
        result = []
        for stock_document_id, doc_type, doc_no, doc_date, unit_cost, tax_amount, quantity in rows:
            landed_unit_cost = unit_cost
            if tax_amount and quantity:
                landed_unit_cost = _money(unit_cost + (tax_amount / quantity))
            result.append(ItemCostHistoryRow(stock_document_id, doc_type, doc_no, doc_date, landed_unit_cost))
        return result


# ---------------------------------------------------------------------
# موتورِ Post
# ---------------------------------------------------------------------
@dataclass
class PostResult:
    stock_document_id: int
    journal_entry_id: int | None


def _standard_cost(session, item_id: int, as_of_date: datetime.date) -> decimal.Decimal:
    row = session.scalar(
        select(StandardCost)
        .where(StandardCost.item_id == item_id, StandardCost.effective_date <= as_of_date)
        .order_by(StandardCost.effective_date.desc())
    )
    if row is None:
        raise ValueError("بهایِ استانداردی برایِ این کالا تعریف نشده است.")
    return row.standard_unit_cost


def _last_known_unit_cost(session, item_id: int) -> decimal.Decimal | None:
    """آخرین بهایِ واحدِ واقعاً ثبت‌شده برایِ این کالا در دفترِ انبار —
    وقتی سندِ مستقیمِ انبار (رسید/برگشت) بدونِ بهایِ واحد ثبتِ نهایی
    می‌شود و روشِ قیمت‌گذاری STANDARD نیست، به‌جایِ خطایِ سخت، همین
    مقدار جایگزین می‌شود. طبقِ رفعِ باگِ واقعی («سندِ حسابداریِ بهایِ
    تمام‌شده/موجودی هیچ‌وقت ساخته نمی‌شود»): فقط بهایِ *مثبت* یک سابقهٔ
    واقعی حساب می‌شود — قبلاً صفر هم قبول می‌شد، یعنی اگر یک اصلاحِ
    موجودیِ بدونِ‌بها زودتر همین کالا را با بهایِ ۰ ثبت کرده بود، آن صفر
    برایِ همیشه به‌عنوانِ «آخرین بهایِ شناخته‌شده» تکرار می‌شد و موجودی/
    بهایِ‌تمام‌شده تا ابد صفر (و بی‌اثر در حسابداری) می‌ماند."""
    row = session.scalar(
        select(StockLedger.unit_cost)
        .where(StockLedger.item_id == item_id, StockLedger.unit_cost > 0)
        .order_by(StockLedger.movement_date.desc(), StockLedger.ledger_id.desc())
        .limit(1)
    )
    return row


def _source_line_unit_cost(session, source_line_id: int) -> decimal.Decimal:
    rows = session.scalars(select(StockLedger).where(StockLedger.stock_document_line_id == source_line_id)).all()
    if not rows:
        raise ValueError("ردیفِ سندِ مرجع هنوز ثبتِ نهایی نشده یا حرکتی ندارد.")
    total_qty = sum((r.quantity_base for r in rows), _ZERO)
    total_cost = sum(((r.unit_cost or _ZERO) * r.quantity_base for r in rows), _ZERO)
    return (total_cost / total_qty) if total_qty else _ZERO


def post_stock_document(stock_document_id: int, company_id: int, posted_by_user_id: int) -> PostResult:
    with new_session() as session:
        doc = session.get(StockDocument, stock_document_id)
        if doc is None or doc.company_id != company_id:
            raise ValueError("سند نامعتبر است.")
        if doc.status_code == "POSTED":
            raise ValueError("این سند قبلاً ثبتِ نهایی شده است.")
        if doc.status_code != "CONFIRMED":
            raise ValueError("فقط سندِ تاییدشده قابلِ‌ثبتِ‌نهایی است.")

        lines = session.scalars(
            select(StockDocumentLine).where(StockDocumentLine.stock_document_id == stock_document_id)
        ).all()
        if not lines:
            raise ValueError("سند حداقل باید یک ردیف داشته باشد.")

        # ترتیبِ قفل‌گذاری: (item_id, warehouse_id, bin_location_id) — طبقِ
        # قاعدهٔ ۶۰ (پیشگیری از Deadlock در اسنادِ چندردیفی).
        sorted_lines = sorted(
            lines, key=lambda ln: (ln.item_id, ln.bin_location_id or 0, ln.destination_bin_location_id or 0)
        )

        item_ids = {ln.item_id for ln in lines}
        items_by_id = {it.item_id: it for it in session.scalars(select(Item).where(Item.item_id.in_(item_ids)))}
        item_codes = dict(
            session.execute(
                select(Item.item_id, DetailAccount.code)
                .join(DetailAccount, DetailAccount.detail_account_id == Item.item_detail_account_id)
                .where(Item.item_id.in_(item_ids))
            ).all()
        )
        warehouse_ids = {wid for wid in (doc.source_warehouse_id, doc.destination_warehouse_id) if wid is not None}
        warehouses_by_id = {
            w.warehouse_id: w for w in session.scalars(select(Warehouse).where(Warehouse.warehouse_id.in_(warehouse_ids)))
        }

        costing_settings = session.get(CompanyCostingSettings, company_id)
        default_costing_method_code = None
        if costing_settings is not None:
            method_row = session.get(CostingMethod, costing_settings.default_costing_method_id)
            default_costing_method_code = method_row.code if method_row is not None else None

        def costing_method(item: Item) -> str:
            return item.costing_method_code or default_costing_method_code or "WEIGHTED_AVERAGE"

        def resolve_bin(warehouse_id: int, bin_location_id: int | None) -> int:
            if bin_location_id is not None:
                return bin_location_id
            default_bin = session.scalar(
                select(BinLocation).where(BinLocation.warehouse_id == warehouse_id, BinLocation.code == "GENERAL")
            )
            if default_bin is None:
                default_bin = session.scalar(
                    select(BinLocation).where(BinLocation.warehouse_id == warehouse_id).order_by(BinLocation.bin_location_id)
                )
            if default_bin is None:
                raise ValueError("این انبار هیچ مکانی ندارد.")
            return default_bin.bin_location_id

        def get_or_create_balance(item_id: int, warehouse_id: int, bin_location_id: int) -> StockBalance:
            bal = session.scalar(
                select(StockBalance)
                .where(
                    StockBalance.item_id == item_id,
                    StockBalance.warehouse_id == warehouse_id,
                    StockBalance.bin_location_id == bin_location_id,
                    StockBalance.batch_id.is_(None),
                )
                .with_for_update()
            )
            if bal is None:
                bal = StockBalance(
                    company_id=company_id, item_id=item_id, warehouse_id=warehouse_id, bin_location_id=bin_location_id,
                    quantity_on_hand=_ZERO, quantity_reserved=_ZERO, average_unit_cost=_ZERO,
                )
                session.add(bal)
                session.flush()
            return bal

        def insert_ledger(
            *, stock_document_line_id: int, item_id: int, warehouse_id: int, bin_location_id: int,
            direction: str, quantity_base: decimal.Decimal, unit_cost: decimal.Decimal, movement_date: datetime.date,
        ) -> StockLedger:
            ledger = StockLedger(
                company_id=company_id, stock_document_line_id=stock_document_line_id, item_id=item_id,
                warehouse_id=warehouse_id, bin_location_id=bin_location_id, movement_direction=direction,
                quantity_base=quantity_base, unit_cost=unit_cost, movement_date=movement_date,
            )
            session.add(ledger)
            session.flush()
            return ledger

        def apply_in(item: Item, warehouse_id: int, bin_location_id: int, quantity_base: decimal.Decimal, unit_cost: decimal.Decimal, movement_date: datetime.date) -> None:
            bal = get_or_create_balance(item.item_id, warehouse_id, bin_location_id)
            method = costing_method(item)
            if method == "STANDARD":
                bal.average_unit_cost = _standard_cost(session, item.item_id, movement_date)
            elif bal.quantity_on_hand < 0:
                bal.average_unit_cost = unit_cost
            else:
                denom = bal.quantity_on_hand + quantity_base
                bal.average_unit_cost = (
                    ((bal.quantity_on_hand * bal.average_unit_cost) + (quantity_base * unit_cost)) / denom
                    if denom != 0 else unit_cost
                )
            bal.quantity_on_hand += quantity_base
            bal.last_movement_at = datetime.datetime.now()

        def consume_out(item: Item, warehouse_id: int, bin_location_id: int, quantity_base: decimal.Decimal, movement_date: datetime.date) -> list[tuple[decimal.Decimal, decimal.Decimal]]:
            """موجودی را کم می‌کند و لیستِ بخش‌هایِ (unit_cost, quantity)
            مصرف‌شده را برمی‌گرداند — برایِ درجِ ردیف(هایِ) Ledger و برایِ
            بازتولیدِ عینیِ همان بهایِ خروجی در مقصدِ TRANSFER."""
            bal = get_or_create_balance(item.item_id, warehouse_id, bin_location_id)
            warehouse = warehouses_by_id[warehouse_id]
            item_label = item_codes.get(item.item_id, str(item.item_id))
            if bal.quantity_on_hand < quantity_base and not warehouse.allow_negative_stock:
                raise ValueError(
                    f"موجودیِ کافی در انبار «{warehouse.name}» برایِ کالایِ «{item_label}» وجود ندارد "
                    f"(موجود: {bal.quantity_on_hand}، درخواستی: {quantity_base})."
                )

            method = costing_method(item)
            segments: list[tuple[decimal.Decimal, decimal.Decimal]] = []
            if method == "FIFO":
                remaining = quantity_base
                layers = session.scalars(
                    select(CostLayer)
                    .where(CostLayer.item_id == item.item_id, CostLayer.warehouse_id == warehouse_id, CostLayer.remaining_quantity > 0)
                    .order_by(CostLayer.received_at)
                    .with_for_update()
                ).all()
                for layer in layers:
                    if remaining <= 0:
                        break
                    take = min(layer.remaining_quantity, remaining)
                    layer.remaining_quantity -= take
                    segments.append((layer.unit_cost, take))
                    remaining -= take
                if remaining > 0:
                    segments.append((bal.average_unit_cost or _ZERO, remaining))
            elif method == "STANDARD":
                segments.append((_standard_cost(session, item.item_id, movement_date), quantity_base))
            else:
                segments.append((bal.average_unit_cost or _ZERO, quantity_base))

            bal.quantity_on_hand -= quantity_base
            if method == "STANDARD":
                bal.average_unit_cost = _standard_cost(session, item.item_id, movement_date)
            bal.last_movement_at = datetime.datetime.now()
            return segments

        # طبقِ رفعِ باگِ واقعی («برای حساب X انتخابِ کالا الزامی است» رویِ
        # حساب‌هایِ نقش‌محورِ اسنادِ انبار — رسید/حواله/اصلاح/برگشت — نه
        # فقط حسابِ درآمدِ فروش): این‌جا هم مثلِ فروش، مبلغِ هر نقش قبلاً
        # به‌صورتِ یک جمعِ کلی (بدونِ ردِ کالا) جمع می‌شد، پس اگر معینِ آن
        # نقش «کالا» را الزامی می‌کرد، هرگز قابلِ‌تامین نبود. حالا مبلغِ
        # هر نقش به‌تفکیکِ تفصیلیِ کالایِ همان ردیف هم نگه داشته می‌شود.
        debits: dict[str, dict[int | None, decimal.Decimal]] = {}
        credits: dict[str, dict[int | None, decimal.Decimal]] = {}

        def add_debit(role: str, amount: decimal.Decimal, item_detail_account_id: int | None = None) -> None:
            if amount == 0:
                return
            by_item = debits.setdefault(role, {})
            by_item[item_detail_account_id] = by_item.get(item_detail_account_id, _ZERO) + amount

        def add_credit(role: str, amount: decimal.Decimal, item_detail_account_id: int | None = None) -> None:
            if amount == 0:
                return
            by_item = credits.setdefault(role, {})
            by_item[item_detail_account_id] = by_item.get(item_detail_account_id, _ZERO) + amount

        doc_type = doc.document_type_code
        movement_date = doc.document_date

        for line in sorted_lines:
            item = items_by_id.get(line.item_id)
            if item is None or item.company_id != company_id:
                raise ValueError("کالایِ ردیف نامعتبر است.")
            if item.lifecycle_status_code != "ACTIVE":
                raise ValueError(f"کالایِ «{item_codes.get(item.item_id, item.item_id)}» در وضعیتِ فعال نیست و قابلِ‌ثبت در سند نیست.")
            if not item.is_stock_tracked:
                raise ValueError("این کالا موجودی‌محور نیست.")

            if doc_type in ("RECEIPT", "RETURN_IN"):
                warehouse_id = doc.destination_warehouse_id
                bin_id = resolve_bin(warehouse_id, line.bin_location_id)
                method = costing_method(item)

                if doc_type == "RETURN_IN" and line.source_line_id is not None:
                    actual_cost = _source_line_unit_cost(session, line.source_line_id)
                else:
                    actual_cost = line.unit_cost
                    if actual_cost is None:
                        if method == "STANDARD":
                            actual_cost = _standard_cost(session, item.item_id, movement_date)
                        else:
                            # طبقِ تصمیمِ صریح: بهایِ واحد در رسیدِ مستقیمِ
                            # انبار الزامی نیست — اگر خالی بماند، آخرین بهایِ
                            # واقعاً ثبت‌شده برایِ همین کالا (از دفترِ انبار)
                            # به‌طورِ نامرئی جایگزین می‌شود. طبقِ رفعِ باگِ
                            # واقعی («سندِ حسابداریِ بهایِ تمام‌شده/موجودی
                            # هیچ‌وقت ساخته نمی‌شود»): اگر هیچ سابقه‌یِ
                            # بهایِ *مثبتی* هم نبود، دیگر صفرِ نامرئی جایگزین
                            # نمی‌شود (چون آن صفر عملاً یعنی این حواله هیچ‌وقت
                            # اثرِ حسابداری پیدا نمی‌کند و هیچ‌جا هم دیده
                            # نمی‌شود) — به‌جایش صریحاً بهایِ واحد خواسته می‌شود.
                            actual_cost = _last_known_unit_cost(session, item.item_id)
                            if actual_cost is None:
                                raise ValueError(
                                    f"برایِ کالایِ «{item_codes.get(item.item_id, item.item_id)}» هنوز هیچ بهایِ "
                                    "ثبت‌شده‌ای در سابقه نیست — واردکردنِ بهایِ واحد برایِ این ردیف الزامی است."
                                )

                ledger_unit_cost = _standard_cost(session, item.item_id, movement_date) if method == "STANDARD" else actual_cost

                in_ledger = insert_ledger(
                    stock_document_line_id=line.line_id, item_id=item.item_id, warehouse_id=warehouse_id,
                    bin_location_id=bin_id, direction="IN", quantity_base=line.quantity_base,
                    unit_cost=ledger_unit_cost, movement_date=movement_date,
                )
                apply_in(item, warehouse_id, bin_id, line.quantity_base, ledger_unit_cost, movement_date)
                if method == "FIFO":
                    session.add(
                        CostLayer(
                            item_id=item.item_id, warehouse_id=warehouse_id, stock_ledger_id=in_ledger.ledger_id,
                            received_at=datetime.datetime.now(), original_quantity=line.quantity_base,
                            remaining_quantity=line.quantity_base, unit_cost=ledger_unit_cost,
                        )
                    )

                inventory_amount = _money(ledger_unit_cost * line.quantity_base)
                payable_amount = _money(actual_cost * line.quantity_base)
                add_debit("INVENTORY_ASSET", inventory_amount, item.item_detail_account_id)
                variance = payable_amount - inventory_amount
                if doc_type == "RECEIPT" and variance != 0:
                    if variance > 0:
                        add_debit("INVENTORY_COST_VARIANCE", variance, item.item_detail_account_id)
                    else:
                        add_credit("INVENTORY_COST_VARIANCE", -variance, item.item_detail_account_id)
                # طبقِ رفعِ باگِ واقعی («مالياتِ ردیفِ فاکتورِ خرید محاسبه
                # می‌شود ولی سندش ثبت نمی‌شود»): مالياتِ همین ردیف (اگر از
                # یک فاکتورِ خرید آمده باشد) بدهکارِ «مالياتِ خرید-قابلِ
                # مطالبه» می‌شود و رویِ بستانکاریِ حساب‌هایِ پرداختنی هم
                # افزوده می‌شود — بدونِ اینکه وارد ارزشِ خودِ موجودی شود.
                tax_amount = line.tax_amount or _ZERO
                if tax_amount:
                    add_debit("PURCHASE_TAX_RECEIVABLE", tax_amount, item.item_detail_account_id)
                credit_amount = payable_amount + tax_amount
                credit_role = "SUPPLIER_PAYABLE" if doc_type == "RECEIPT" else "CUSTOMER_RECEIVABLE"
                if doc.counterparty_detail_account_id is not None:
                    add_credit(credit_role, credit_amount, item.item_detail_account_id)
                else:
                    add_credit("INVENTORY_ADJUSTMENT_GAIN", credit_amount, item.item_detail_account_id)

            elif doc_type in ("ISSUE", "RETURN_OUT"):
                warehouse_id = doc.source_warehouse_id
                bin_id = resolve_bin(warehouse_id, line.bin_location_id)
                segments = consume_out(item, warehouse_id, bin_id, line.quantity_base, movement_date)
                total_amount = _ZERO
                for seg_cost, seg_qty in segments:
                    insert_ledger(
                        stock_document_line_id=line.line_id, item_id=item.item_id, warehouse_id=warehouse_id,
                        bin_location_id=bin_id, direction="OUT", quantity_base=seg_qty, unit_cost=seg_cost,
                        movement_date=movement_date,
                    )
                    total_amount += _money(seg_cost * seg_qty)
                add_credit("INVENTORY_ASSET", total_amount, item.item_detail_account_id)
                if doc_type == "ISSUE":
                    add_debit("COGS", total_amount, item.item_detail_account_id)
                elif doc.counterparty_detail_account_id is not None:
                    add_debit("SUPPLIER_PAYABLE", total_amount, item.item_detail_account_id)
                else:
                    add_debit("INVENTORY_ADJUSTMENT_LOSS", total_amount, item.item_detail_account_id)

            elif doc_type == "TRANSFER":
                source_wh, dest_wh = doc.source_warehouse_id, doc.destination_warehouse_id
                source_bin = resolve_bin(source_wh, line.bin_location_id)
                dest_bin = resolve_bin(dest_wh, line.destination_bin_location_id)
                segments = consume_out(item, source_wh, source_bin, line.quantity_base, movement_date)
                method = costing_method(item)
                for seg_cost, seg_qty in segments:
                    insert_ledger(
                        stock_document_line_id=line.line_id, item_id=item.item_id, warehouse_id=source_wh,
                        bin_location_id=source_bin, direction="OUT", quantity_base=seg_qty, unit_cost=seg_cost,
                        movement_date=movement_date,
                    )
                    in_ledger = insert_ledger(
                        stock_document_line_id=line.line_id, item_id=item.item_id, warehouse_id=dest_wh,
                        bin_location_id=dest_bin, direction="IN", quantity_base=seg_qty, unit_cost=seg_cost,
                        movement_date=movement_date,
                    )
                    apply_in(item, dest_wh, dest_bin, seg_qty, seg_cost, movement_date)
                    if method == "FIFO":
                        session.add(
                            CostLayer(
                                item_id=item.item_id, warehouse_id=dest_wh, stock_ledger_id=in_ledger.ledger_id,
                                received_at=datetime.datetime.now(), original_quantity=seg_qty,
                                remaining_quantity=seg_qty, unit_cost=seg_cost,
                            )
                        )
                # طبقِ قاعدهٔ ۷۶: بینِ دو انبارِ همان شرکت، TRANSFER هرگز اثرِ
                # حسابداری تولید نمی‌کند — فقط جابه‌جاییِ Ledger است.

            elif doc_type == "ADJUSTMENT":
                if doc.source_warehouse_id is not None:
                    warehouse_id = doc.source_warehouse_id
                    bin_id = resolve_bin(warehouse_id, line.bin_location_id)
                    segments = consume_out(item, warehouse_id, bin_id, line.quantity_base, movement_date)
                    total_amount = _ZERO
                    for seg_cost, seg_qty in segments:
                        insert_ledger(
                            stock_document_line_id=line.line_id, item_id=item.item_id, warehouse_id=warehouse_id,
                            bin_location_id=bin_id, direction="OUT", quantity_base=seg_qty, unit_cost=seg_cost,
                            movement_date=movement_date,
                        )
                        total_amount += _money(seg_cost * seg_qty)
                    add_credit("INVENTORY_ASSET", total_amount, item.item_detail_account_id)
                    add_debit("INVENTORY_ADJUSTMENT_LOSS", total_amount, item.item_detail_account_id)
                if doc.destination_warehouse_id is not None:
                    warehouse_id = doc.destination_warehouse_id
                    bin_id = resolve_bin(warehouse_id, line.bin_location_id)
                    method = costing_method(item)
                    if method == "STANDARD":
                        unit_cost = _standard_cost(session, item.item_id, movement_date)
                    elif line.unit_cost is not None:
                        unit_cost = line.unit_cost
                    else:
                        # طبقِ رفعِ باگِ واقعی («سندِ حسابداریِ بهایِ
                        # تمام‌شده/موجودی هیچ‌وقت ساخته نمی‌شود»): قبلاً
                        # اگر این کالا هنوز میانگینِ بهایِ واقعی‌ای نداشت
                        # (اولین حرکتش)، این‌جا صفر جایگزین می‌شد و همان
                        # صفر برایِ همیشه به کالا می‌چسبید — هر فروشِ بعدی
                        # هم بهایِ تمام‌شده‌اش صفر می‌شد و اصلاً سندِ
                        # حسابداری نمی‌ساخت (چون ردیفِ صفر مجاز نیست).
                        # حالا اگر میانگینِ محلی صفر بود، آخرین بهایِ
                        # مثبتِ واقعیِ همین کالا (از هر انباری) امتحان
                        # می‌شود؛ اگر آن هم نبود، صریحاً بهایِ واحد خواسته
                        # می‌شود.
                        bal = get_or_create_balance(item.item_id, warehouse_id, bin_id)
                        if bal.quantity_on_hand > 0 and bal.average_unit_cost > 0:
                            unit_cost = bal.average_unit_cost
                        else:
                            unit_cost = _last_known_unit_cost(session, item.item_id)
                            if unit_cost is None:
                                raise ValueError(
                                    f"برایِ افزایشِ موجودیِ کالایِ «{item_codes.get(item.item_id, item.item_id)}» که "
                                    "هنوز هیچ بهایِ ثبت‌شده‌ای ندارد، واردکردنِ بهایِ واحد برایِ این ردیف الزامی است."
                                )
                    in_ledger = insert_ledger(
                        stock_document_line_id=line.line_id, item_id=item.item_id, warehouse_id=warehouse_id,
                        bin_location_id=bin_id, direction="IN", quantity_base=line.quantity_base,
                        unit_cost=unit_cost, movement_date=movement_date,
                    )
                    apply_in(item, warehouse_id, bin_id, line.quantity_base, unit_cost, movement_date)
                    if method == "FIFO":
                        session.add(
                            CostLayer(
                                item_id=item.item_id, warehouse_id=warehouse_id, stock_ledger_id=in_ledger.ledger_id,
                                received_at=datetime.datetime.now(), original_quantity=line.quantity_base,
                                remaining_quantity=line.quantity_base, unit_cost=unit_cost,
                            )
                        )
                    amount = _money(unit_cost * line.quantity_base)
                    add_debit("INVENTORY_ASSET", amount, item.item_detail_account_id)
                    add_credit("INVENTORY_ADJUSTMENT_GAIN", amount, item.item_detail_account_id)

            elif doc_type == "CONSIGNMENT_IN":
                # طبقِ اصلِ فاکتورِ امانیِ ورودی: کالا در این لحظه هنوز مالِ
                # شرکت نیست (فقط در اختیارِ فیزیکی‌اش قرار گرفته) -- پس
                # درست مثلِ TRANSFER، هیچ اثرِ حسابداری‌ای (add_debit/
                # add_credit) این‌جا ثبت نمی‌شود. با این‌حال، بهایِ
                # توافق‌شده باید ثبت شود تا اگر همین کالا پیش از تسویه با
                # تامین‌کننده فروخته شد، بهایِ تمام‌شده‌اش درست محاسبه شود؛
                # سندِ حسابداریِ واقعیِ دریافتنی/پرداختنی فقط در لحظهٔ تسویه
                # (services/commercial_consignment.py) ساخته می‌شود.
                warehouse_id = doc.destination_warehouse_id
                bin_id = resolve_bin(warehouse_id, line.bin_location_id)
                method = costing_method(item)
                if line.unit_cost is None:
                    raise ValueError(
                        f"برایِ کالایِ «{item_codes.get(item.item_id, item.item_id)}» در امانیِ ورودی، "
                        "واردکردنِ بهایِ توافق‌شده الزامی است."
                    )
                unit_cost = line.unit_cost
                in_ledger = insert_ledger(
                    stock_document_line_id=line.line_id, item_id=item.item_id, warehouse_id=warehouse_id,
                    bin_location_id=bin_id, direction="IN", quantity_base=line.quantity_base,
                    unit_cost=unit_cost, movement_date=movement_date,
                )
                apply_in(item, warehouse_id, bin_id, line.quantity_base, unit_cost, movement_date)
                if method == "FIFO":
                    session.add(
                        CostLayer(
                            item_id=item.item_id, warehouse_id=warehouse_id, stock_ledger_id=in_ledger.ledger_id,
                            received_at=datetime.datetime.now(), original_quantity=line.quantity_base,
                            remaining_quantity=line.quantity_base, unit_cost=unit_cost,
                        )
                    )

            elif doc_type == "CONSIGN_RETURN":
                # طبقِ اصلِ فاکتورِ امانیِ ورودی: بازگرداندنِ کالایِ
                # مصرف‌نشده به تامین‌کننده -- چون هرگز خریداری نشده، هیچ
                # اثرِ حسابداری‌ای هم ندارد (بدونِ add_debit/add_credit).
                warehouse_id = doc.source_warehouse_id
                bin_id = resolve_bin(warehouse_id, line.bin_location_id)
                segments = consume_out(item, warehouse_id, bin_id, line.quantity_base, movement_date)
                for seg_cost, seg_qty in segments:
                    insert_ledger(
                        stock_document_line_id=line.line_id, item_id=item.item_id, warehouse_id=warehouse_id,
                        bin_location_id=bin_id, direction="OUT", quantity_base=seg_qty, unit_cost=seg_cost,
                        movement_date=movement_date,
                    )
            else:
                raise ValueError("نوعِ سند نامعتبر است.")

        person_dimension_type_id = dimensions_service.get_person_dimension_type_id(company_id)
        # طبقِ رفعِ باگِ واقعی («برای حساب X انتخابِ گروه‌هایِ تفصیلیِ
        # الزامی فراموش شده است» حتی وقتی تفصیلیِ طرفِ‌حساب درست انتخاب
        # شده بود): قبلاً هیچ‌کدام از ردیف‌هایِ خودکارِ این سند (موجودیِ
        # کالا، بهایِ تمام‌شده، و...) مرکزِ هزینه/پروژهٔ خودِ سند را
        # نمی‌فرستادند — اگر حسابِ نقش‌محورشان به آن بُعدها هم نیاز
        # داشت، ثبتِ نهایی همیشه رد می‌شد.
        extra_dims: dict[int, int] = {}
        if doc.cost_center_detail_account_id is not None:
            extra_dims[dimensions_service.get_specialized_dimension_type_id(company_id, dimensions_service.COST_CENTER_CODE)] = doc.cost_center_detail_account_id
        if doc.project_detail_account_id is not None:
            extra_dims[dimensions_service.get_specialized_dimension_type_id(company_id, dimensions_service.PROJECT_CODE)] = doc.project_detail_account_id
        # «مرکزِ سود» هیچ فیلدی در سرِسند ندارد — تنها منبعِ آن انبارِ خودِ
        # سند است (که از قبل در فرمِ انبارها قابلِ تعریف است). بدونِ این،
        # هر حسابِ نقش‌محوری که این بُعد را الزامی کند، ثبت را همیشه با
        # پیامِ «تفصیلیِ الزامی» رد می‌کرد — چون هیچ‌جا راهی برایِ فرستادنش نبود.
        warehouse_id_for_profit_center = doc.destination_warehouse_id or doc.source_warehouse_id
        if warehouse_id_for_profit_center is not None:
            warehouse = session.get(Warehouse, warehouse_id_for_profit_center)
            if warehouse is not None and warehouse.profit_center_detail_account_id is not None:
                extra_dims[dimensions_service.get_specialized_dimension_type_id(company_id, dimensions_service.PROFIT_CENTER_CODE)] = (
                    warehouse.profit_center_detail_account_id
                )
        item_dim_type_id = dimensions_service.get_specialized_dimension_type_id(company_id, dimensions_service.INVENTORY_ITEM_CODE)

        def _account_requires_item_dim(account_id: int) -> bool:
            required = dimensions_service.get_required_dimensions_for_account(account_id)
            return any(r.dimension_type_id == item_dim_type_id for r in required)

        je_lines: list[je_service.LineInput] = []
        description = doc.description or f"سندِ انبار #{doc.document_no}"

        # طبقِ رفعِ باگِ واقعی («حسابِ مالياتِ خرید تفصیلی می‌خواهد ولی
        # جایی برایِ انتخابش نیست»): بعضی حساب‌هایِ نقش‌محور یک تفصیلیِ
        # الزامی دارند که نه از سرِسند (مرکزِ هزینه/پروژه) و نه از
        # طرفِ‌حساب/کالایِ ردیف تامین می‌شود -- و معمولاً هم همیشه یک
        # مقدارِ *ثابت* دارد (مثلاً یک ردیفِ تعریف‌شده برایِ «ماليات»).
        # این تفصیلیِ ثابت را از خودِ نگاشتِ همان نقش می‌خوانیم.
        def _fixed_role_detail(role: str) -> tuple[int, int] | None:
            mapping_row = session.get(InventoryAccountMapping, (company_id, role))
            if mapping_row is None or mapping_row.detail_account_id is None:
                return None
            detail = session.get(DetailAccount, mapping_row.detail_account_id)
            if detail is None:
                return None
            return detail.dimension_type_id, detail.detail_account_id

        def _build_lines(role_amounts: dict[str, dict[int | None, decimal.Decimal]], is_debit: bool) -> None:
            for role, by_item in role_amounts.items():
                account_id = _resolve_role_account(session, company_id, role)
                base_details: dict[int, int] = {}
                fixed_detail = _fixed_role_detail(role)
                if fixed_detail is not None:
                    base_details[fixed_detail[0]] = fixed_detail[1]
                base_details.update(extra_dims)
                if role in ("SUPPLIER_PAYABLE", "CUSTOMER_RECEIVABLE") and doc.counterparty_detail_account_id is not None:
                    base_details[person_dimension_type_id] = doc.counterparty_detail_account_id
                if _account_requires_item_dim(account_id):
                    for item_detail_account_id, item_amount in by_item.items():
                        details = dict(base_details)
                        if item_detail_account_id is not None:
                            details[item_dim_type_id] = item_detail_account_id
                        je_lines.append(
                            je_service.LineInput(
                                account_id=account_id, description=description,
                                debit=item_amount if is_debit else _ZERO, credit=_ZERO if is_debit else item_amount,
                                details=details,
                            )
                        )
                else:
                    total = sum(by_item.values(), _ZERO)
                    je_lines.append(
                        je_service.LineInput(
                            account_id=account_id, description=description,
                            debit=total if is_debit else _ZERO, credit=_ZERO if is_debit else total,
                            details=dict(base_details),
                        )
                    )

        _build_lines(debits, is_debit=True)
        _build_lines(credits, is_debit=False)

        doc.status_code = "POSTED"
        doc.posted_by_user_id = posted_by_user_id
        doc.posted_at = datetime.datetime.now()
        session.commit()

        result_stock_document_id = doc.stock_document_id
        result_document_date = doc.document_date

    journal_entry_id = None
    if je_lines:
        result = je_service.create_journal_entry(
            company_id, posted_by_user_id, result_document_date, description, je_lines, entry_type_code="INVENTORY"
        )
        journal_entry_id = result.journal_entry_id
        with new_session() as session:
            doc = session.get(StockDocument, result_stock_document_id)
            doc.journal_entry_id = journal_entry_id
            session.commit()

    return PostResult(stock_document_id=result_stock_document_id, journal_entry_id=journal_entry_id)


def reverse_stock_document(stock_document_id: int, company_id: int, reversed_by_user_id: int) -> PostResult:
    """طبقِ درخواستِ صریح («اصلاحِ فاکتورِ ثبت‌شده باید عیناً برگشت بخورد،
    نه اینکه سندِ اصلی با تاریخِ عقب‌دار دست‌کاری شود»): دقیقاً هم‌الگو با
    journal_entries.reverse_journal_entry -- یک سندِ انبارِ *تازه* با نوعِ
    معکوس (RECEIPT<->ISSUE)، همان کالا/مقدار/انبار/مکان، در تاریخِ *امروز*
    ساخته و بلافاصله ثبتِ نهایی می‌شود؛ سندِ اصلی هرگز دست‌کاری نمی‌شود
    (stock_ledger هم طبقِ طراحیِ دیتابیس Append-Only است).

    برخلافِ post_stock_document، این‌جا میانگینِ موزونِ جدید با فرمولِ
    معکوسِ همان فرمولِ apply_in محاسبه می‌شود -- نه از طریقِ یک ردیفِ
    عادیِ ISSUE/RECEIPT، چون ISSUE هرگز average_unit_cost را تغییر
    نمی‌دهد و نمی‌تواند اثرِ یک RECEیPT را واقعاً خنثی کند.

    محدودیتِ آگاهانه: فقط برایِ کالاهایِ میانگینِ موزون/استاندارد (نه
    FIFO، که ردیابیِ دقیقِ لایه‌به‌لایه لازم دارد) و فقط وقتی این سند
    هنوز *آخرین* حرکتِ انبار برایِ کالاهایِ خودش باشد -- وگرنه برگشت‌زدنِ
    آن ترتیبِ محاسبه‌یِ هزینه‌یِ سندهایِ بعدی را به‌هم می‌ریزد. سندِ
    حسابداریِ خودش را هم نمی‌سازد -- بازتابِ حسابداریِ درست از طریقِ
    برگشت‌زدنِ عینیِ سندِ حسابداریِ *سندِ اصلی* (journal_entries.
    reverse_journal_entry، توسطِ تماس‌گیرنده) به‌دست می‌آید."""
    with new_session() as session:
        doc = session.get(StockDocument, stock_document_id)
        if doc is None or doc.company_id != company_id:
            raise ValueError("سند نامعتبر است.")
        if doc.status_code != "POSTED":
            raise ValueError("فقط سندهایِ ثبت‌نهایی‌شده قابلِ برگشت‌اند.")
        if doc.document_type_code not in ("RECEIPT", "ISSUE"):
            raise ValueError("برگشت‌زدنِ این نوعِ سندِ انبار فعلاً پشتیبانی نمی‌شود.")

        lines = session.scalars(
            select(StockDocumentLine).where(StockDocumentLine.stock_document_id == stock_document_id)
        ).all()
        if not lines:
            raise ValueError("سند ردیفی ندارد.")
        line_ids = [ln.line_id for ln in lines]

        original_ledger_rows = session.scalars(
            select(StockLedger).where(StockLedger.stock_document_line_id.in_(line_ids))
        ).all()
        if len(original_ledger_rows) != len(lines):
            raise ValueError("سند هنوز کاملاً به دفترِ انبار منتقل نشده — برگشت‌زدن ممکن نیست.")

        item_ids = {r.item_id for r in original_ledger_rows}
        items_by_id = {it.item_id: it for it in session.scalars(select(Item).where(Item.item_id.in_(item_ids)))}

        costing_settings = session.get(CompanyCostingSettings, company_id)
        default_costing_method_code = None
        if costing_settings is not None:
            method_row = session.get(CostingMethod, costing_settings.default_costing_method_id)
            default_costing_method_code = method_row.code if method_row is not None else None

        for item in items_by_id.values():
            method = item.costing_method_code or default_costing_method_code or "WEIGHTED_AVERAGE"
            if method == "FIFO":
                raise ValueError(
                    "برگشت‌زدنِ سند برایِ کالایی که با روشِ FIFO قیمت‌گذاری می‌شود، فعلاً پشتیبانی نمی‌شود."
                )

        is_receipt = doc.document_type_code == "RECEIPT"

        # قاعده‌یِ ایمنی: این سند باید همچنان آخرین حرکتِ انبار برایِ
        # کالا/انبارِ خودش باشد -- وگرنه ترتیبِ محاسبه‌یِ میانگینِ موزونِ
        # سندهایِ بعدی به‌هم می‌ریزد.
        this_doc_max_ledger_id = max(r.ledger_id for r in original_ledger_rows)
        for r in original_ledger_rows:
            later_count = session.scalar(
                select(func.count()).select_from(StockLedger).where(
                    StockLedger.item_id == r.item_id,
                    StockLedger.warehouse_id == r.warehouse_id,
                    StockLedger.bin_location_id == r.bin_location_id,
                    StockLedger.ledger_id > this_doc_max_ledger_id,
                )
            )
            if later_count:
                raise ValueError(
                    "این سند دیگر آخرین حرکتِ انبار برایِ یکی از کالاهایش نیست — سندهایِ دیگری "
                    "بعد از آن رویِ همین کالا/انبار ثبت شده‌اند، پس اصلاحِ آن دیگر ایمن نیست."
                )

        fiscal_year = session.scalar(
            select(FiscalYear).where(
                FiscalYear.company_id == company_id,
                FiscalYear.start_date <= datetime.date.today(),
                FiscalYear.end_date >= datetime.date.today(),
            )
        )
        if fiscal_year is None:
            raise ValueError("سالِ مالیِ امروز تعریف نشده است.")

        original_warehouse_id = doc.destination_warehouse_id if is_receipt else doc.source_warehouse_id
        reversal_type = "ISSUE" if is_receipt else "RECEIPT"
        next_no = (
            session.scalar(
                select(func.max(StockDocument.document_no)).where(
                    StockDocument.company_id == company_id, StockDocument.fiscal_year_id == fiscal_year.fiscal_year_id,
                    StockDocument.document_type_code == reversal_type,
                )
            )
            or 0
        ) + 1
        today = datetime.date.today()
        reversal_doc = StockDocument(
            company_id=company_id, fiscal_year_id=fiscal_year.fiscal_year_id, document_type_code=reversal_type,
            document_no=next_no, document_date=today, status_code="POSTED",
            source_warehouse_id=original_warehouse_id if reversal_type == "ISSUE" else None,
            destination_warehouse_id=original_warehouse_id if reversal_type == "RECEIPT" else None,
            counterparty_detail_account_id=doc.counterparty_detail_account_id,
            cost_center_detail_account_id=doc.cost_center_detail_account_id,
            project_detail_account_id=doc.project_detail_account_id,
            reference_no=f"REVERSAL-{stock_document_id}",
            description=f"سندِ برگشتیِ سندِ انبارِ شماره‌ی {doc.document_no}",
            created_by_user_id=reversed_by_user_id,
        )
        session.add(reversal_doc)
        session.flush()

        for line_no, r in enumerate(original_ledger_rows, start=1):
            item = items_by_id[r.item_id]
            bal = session.scalar(
                select(StockBalance).where(
                    StockBalance.item_id == r.item_id, StockBalance.warehouse_id == r.warehouse_id,
                    StockBalance.bin_location_id == r.bin_location_id, StockBalance.batch_id.is_(None),
                ).with_for_update()
            )
            if bal is None:
                raise ValueError("موجودیِ این کالا/انبار یافت نشد.")

            method = item.costing_method_code or default_costing_method_code or "WEIGHTED_AVERAGE"
            q = r.quantity_base
            if r.movement_direction == "IN":
                # طبقِ فرمولِ معکوسِ apply_in: Q0 = Q1 - q؛
                # A0 = (A1*Q1 - q*C) / Q0 (اگر Q0 > 0).
                new_qty = bal.quantity_on_hand - q
                if new_qty > 0:
                    if method == "STANDARD":
                        new_avg = _standard_cost(session, item.item_id, today)
                    else:
                        new_avg = ((bal.average_unit_cost * bal.quantity_on_hand) - (q * r.unit_cost)) / new_qty
                else:
                    new_avg = _ZERO
                bal.quantity_on_hand = new_qty
                bal.average_unit_cost = new_avg
                reversal_direction = "OUT"
            else:
                # طبقِ apply_in/consume_out: OUT هرگز average_unit_cost را
                # تغییر نمی‌دهد، پس برگشتِ آن هم صرفاً بازگردانِ مقدار است.
                bal.quantity_on_hand += q
                reversal_direction = "IN"
            bal.last_movement_at = datetime.datetime.now()

            new_line = StockDocumentLine(
                stock_document_id=reversal_doc.stock_document_id, line_no=line_no, item_id=r.item_id,
                uom_id=item.base_uom_id, quantity=q, quantity_base=q,
                bin_location_id=r.bin_location_id, unit_cost=r.unit_cost,
            )
            session.add(new_line)
            session.flush()
            session.add(
                StockLedger(
                    company_id=company_id, stock_document_line_id=new_line.line_id, item_id=r.item_id,
                    warehouse_id=r.warehouse_id, bin_location_id=r.bin_location_id,
                    movement_direction=reversal_direction, quantity_base=q, unit_cost=r.unit_cost,
                    movement_date=today,
                )
            )

        reversal_doc.posted_by_user_id = reversed_by_user_id
        reversal_doc.posted_at = datetime.datetime.now()
        session.commit()
        return PostResult(stock_document_id=reversal_doc.stock_document_id, journal_entry_id=None)


def get_effective_costing_method(item_id: int, company_id: int) -> str:
    """روشِ قیمت‌گذاریِ واقعاً مؤثرِ این کالا (خودِ کالا، وگرنه پیش‌فرضِ
    شرکت) -- طبقِ رفعِ باگِ واقعی («اصلاحِ فاکتوری که شاملِ کالایِ FIFO
    است، نیمه‌کاره حسابداری‌اش را برگشت می‌زند و بعد با خطا متوقف
    می‌شود»): این تابع اجازه می‌دهد اهلیتِ FIFO پیش از هر نوشتنی
    (برگشت‌زدنِ سند یا ساختِ سندِ تازه) بررسی شود، نه وسطِ کار."""
    with new_session() as session:
        item = session.get(Item, item_id)
        if item is None:
            raise ValueError("کالا نامعتبر است.")
        costing_settings = session.get(CompanyCostingSettings, company_id)
        default_costing_method_code = None
        if costing_settings is not None:
            method_row = session.get(CostingMethod, costing_settings.default_costing_method_id)
            default_costing_method_code = method_row.code if method_row is not None else None
        return item.costing_method_code or default_costing_method_code or "WEIGHTED_AVERAGE"


def get_recent_consumption_cost(stock_document_id: int, item_id: int, quantity: decimal.Decimal) -> decimal.Decimal:
    """میانگینِ وزنیِ بهایِ *آخرین* quantity واحدِ مصرف‌شده (OUT) برایِ این
    کالا در همین سندِ انبار -- به‌ترتیبِ معکوسِ ثبت (جدیدترین بخشِ
    مصرف‌شده اول). طبقِ درخواستِ صریح («اصلاحِ فاکتور برایِ کالایِ FIFO
    هم پیاده شود»): وقتی اصلاحِ فاکتورِ فروش تعدادِ فروخته‌شده‌یِ یک
    کالایِ FIFO را *کم* می‌کند (یعنی چند واحد باید «برگردانده» شوند)،
    میانگینِ فعلیِ کالا معنایی برایِ FIFO ندارد -- به‌جایش بهایِ صادقانه‌یِ
    همان واحدهایی که واقعاً در همین فاکتور مصرف شده بودند از رویِ خودِ
    Ledger خوانده می‌شود."""
    with new_session() as session:
        line_ids = list(
            session.scalars(
                select(StockDocumentLine.line_id).where(
                    StockDocumentLine.stock_document_id == stock_document_id, StockDocumentLine.item_id == item_id,
                )
            )
        )
        rows = session.scalars(
            select(StockLedger)
            .where(StockLedger.stock_document_line_id.in_(line_ids), StockLedger.movement_direction == "OUT")
            .order_by(StockLedger.ledger_id.desc())
        ).all()
        remaining = quantity
        total_value = _ZERO
        total_qty = _ZERO
        for row in rows:
            if remaining <= 0:
                break
            take = min(row.quantity_base, remaining)
            total_value += take * row.unit_cost
            total_qty += take
            remaining -= take
        if total_qty == 0:
            raise ValueError("سابقه‌یِ مصرفِ این کالا در سندِ انبارِ اصلی یافت نشد.")
        return total_value / total_qty


@dataclass
class AdjustmentResult:
    stock_document_id: int
    direction: str
    unit_cost: decimal.Decimal
    quantity: decimal.Decimal
    amount: decimal.Decimal


def adjust_stock_quantity(
    item_id: int, warehouse_id: int, bin_location_id: int | None, company_id: int, quantity_delta: decimal.Decimal,
    created_by_user_id: int, reference_no: str, description: str, in_unit_cost: decimal.Decimal | None = None,
) -> AdjustmentResult:
    """طبقِ درخواستِ صریح («اصلاحِ فاکتوری که آخرین حرکتِ انبار نیست هم
    فکری بشود»): برخلافِ reverse_stock_document (که تلاش می‌کند دقیقاً
    یک حرکتِ خاصِ گذشته را خنثی کند و برایِ همین به قاعده‌یِ «هنوز آخرین
    حرکت باشد» نیاز دارد)، این تابع هرگز به گذشته کاری ندارد — فقط یک
    حرکتِ *تازه* و رو به جلو ثبت می‌کند؛ دقیقاً مثلِ این‌که همین امروز یک
    فروش/خریدِ معمولیِ کوچک اتفاق افتاده باشد. پس هیچ‌وقت به «آخرین حرکت
    بودن» نیاز ندارد و همیشه امن است.

    quantity_delta مثبت یعنی مصرفِ بیشتر (OUT — مثلِ افزایشِ مقدارِ
    فروخته‌شده)، منفی یعنی افزودن (IN — مثلِ کاهشِ مقدارِ فروخته‌شده، یا
    افزایشِ مقدارِ خریداری‌شده).

    برایِ میانگینِ موزون/استاندارد: OUT همیشه با میانگینِ *فعلی* (بدونِ
    تغییرِ میانگین)؛ IN بدونِ in_unit_cost یعنی بازگرداندنِ خنثی (دقیقاً
    در قیمتِ خودِ میانگین وارد می‌شود)، با in_unit_cost یعنی یک apply_in
    واقعی با همان بهایِ مشخص.

    برایِ FIFO: OUT دقیقاً مثلِ consume_out معمولی از لایه‌هایِ موجود
    (قدیمی‌ترین اول) مصرف می‌کند -- رو به جلو و کاملاً امن، چون به هیچ
    لایه‌یِ گذشته‌ای دست نمی‌زند. IN برایِ FIFO همیشه به in_unit_cost نیاز
    دارد (میانگینی برایِ بلندکردن وجود ندارد) و یک لایه‌یِ هزینه‌یِ *تازه*
    می‌سازد -- دقیقاً مثلِ یک رسیدِ معمولیِ امروز؛ لایه‌هایِ قدیمی هرگز
    دست‌کاری نمی‌شوند."""
    if quantity_delta == 0:
        raise ValueError("مقدارِ تفاوت نمی‌تواند صفر باشد.")
    with new_session() as session:
        item = session.get(Item, item_id)
        if item is None:
            raise ValueError("کالا نامعتبر است.")
        warehouse = session.get(Warehouse, warehouse_id)
        if warehouse is None:
            raise ValueError("انبار نامعتبر است.")

        method = get_effective_costing_method(item_id, company_id)
        if method == "FIFO" and quantity_delta < 0 and in_unit_cost is None:
            raise ValueError("برایِ کالایِ FIFO، بازگرداندن/افزایشِ مقدار بدونِ مشخص‌کردنِ بهایِ واحد ممکن نیست.")

        if bin_location_id is None:
            default_bin = session.scalar(
                select(BinLocation).where(BinLocation.warehouse_id == warehouse_id, BinLocation.code == "GENERAL")
            )
            if default_bin is None:
                raise ValueError("مکانِ انبارِ پیش‌فرض یافت نشد.")
            bin_location_id = default_bin.bin_location_id

        bal = session.scalar(
            select(StockBalance).where(
                StockBalance.item_id == item_id, StockBalance.warehouse_id == warehouse_id,
                StockBalance.bin_location_id == bin_location_id, StockBalance.batch_id.is_(None),
            ).with_for_update()
        )
        if bal is None:
            bal = StockBalance(
                company_id=company_id, item_id=item_id, warehouse_id=warehouse_id, bin_location_id=bin_location_id,
                quantity_on_hand=_ZERO, average_unit_cost=_ZERO,
            )
            session.add(bal)
            session.flush()

        today = datetime.date.today()
        # (unit_cost, quantity) به‌ازایِ هر بخش -- برایِ FIFOِ OUT ممکن
        # است چند لایه‌یِ جداگانه باشد؛ در بقیه‌یِ حالت‌ها همیشه یکی است.
        segments: list[tuple[decimal.Decimal, decimal.Decimal]] = []

        if quantity_delta > 0:
            qty = quantity_delta
            if bal.quantity_on_hand < qty and not warehouse.allow_negative_stock:
                raise ValueError(
                    f"موجودیِ کافی برایِ اعمالِ این اصلاح در انبار «{warehouse.name}» وجود ندارد "
                    f"(موجود: {bal.quantity_on_hand}، نیاز به کاهشِ: {qty})."
                )
            direction = "OUT"
            if method == "FIFO":
                remaining = qty
                layers = session.scalars(
                    select(CostLayer)
                    .where(CostLayer.item_id == item_id, CostLayer.warehouse_id == warehouse_id, CostLayer.remaining_quantity > 0)
                    .order_by(CostLayer.received_at)
                    .with_for_update()
                ).all()
                for layer in layers:
                    if remaining <= 0:
                        break
                    take = min(layer.remaining_quantity, remaining)
                    layer.remaining_quantity -= take
                    segments.append((layer.unit_cost, take))
                    remaining -= take
                if remaining > 0:
                    segments.append((bal.average_unit_cost or _ZERO, remaining))
            elif method == "STANDARD":
                segments.append((_standard_cost(session, item_id, today), qty))
            else:
                segments.append((bal.average_unit_cost or _ZERO, qty))
            bal.quantity_on_hand -= qty
        else:
            qty = -quantity_delta
            direction = "IN"
            if method == "STANDARD":
                segments.append((_standard_cost(session, item_id, today), qty))
            elif method == "FIFO":
                # طبقِ طراحی: بازگرداندن/افزایشِ مقدارِ FIFO همیشه یک
                # لایه‌یِ هزینه‌یِ *تازه* می‌سازد، دقیقاً مثلِ یک رسیدِ
                # معمولیِ امروز -- لایه‌هایِ قدیمی هرگز دست‌کاری نمی‌شوند.
                segments.append((in_unit_cost, qty))
            elif in_unit_cost is not None:
                # طبقِ درخواستِ صریح (اصلاحِ فاکتورِ خرید با افزایشِ مقدار):
                # این‌جا برخلافِ حالتِ خنثی، واقعاً کالایِ *تازه‌ای* با
                # بهایِ *واقعیِ* خودش وارد می‌شود -- پس باید مثلِ apply_in
                # واقعی در میانگین بلند شود، نه با میانگینِ فعلی.
                denom = bal.quantity_on_hand + qty
                bal.average_unit_cost = (
                    ((bal.quantity_on_hand * bal.average_unit_cost) + (qty * in_unit_cost)) / denom
                    if denom != 0 else in_unit_cost
                )
                segments.append((in_unit_cost, qty))
            else:
                segments.append((bal.average_unit_cost or _ZERO, qty))
            bal.quantity_on_hand += qty
        bal.last_movement_at = datetime.datetime.now()

        fiscal_year = session.scalar(
            select(FiscalYear).where(
                FiscalYear.company_id == company_id, FiscalYear.start_date <= today, FiscalYear.end_date >= today,
            )
        )
        if fiscal_year is None:
            raise ValueError("سالِ مالیِ امروز تعریف نشده است.")

        doc_type = "ISSUE" if direction == "OUT" else "RECEIPT"
        next_no = (
            session.scalar(
                select(func.max(StockDocument.document_no)).where(
                    StockDocument.company_id == company_id, StockDocument.fiscal_year_id == fiscal_year.fiscal_year_id,
                    StockDocument.document_type_code == doc_type,
                )
            )
            or 0
        ) + 1
        adjustment_doc = StockDocument(
            company_id=company_id, fiscal_year_id=fiscal_year.fiscal_year_id, document_type_code=doc_type,
            document_no=next_no, document_date=today, status_code="POSTED",
            source_warehouse_id=warehouse_id if doc_type == "ISSUE" else None,
            destination_warehouse_id=warehouse_id if doc_type == "RECEIPT" else None,
            reference_no=reference_no, description=description, created_by_user_id=created_by_user_id,
        )
        session.add(adjustment_doc)
        session.flush()
        # طبقِ الگویِ خودِ post_stock_document: برایِ RECEIPT بهایِ ردیف
        # پر می‌شود، برایِ ISSUE خالی می‌ماند (بهایِ واقعی از رویِ خودِ
        # ردیف‌هایِ Ledger -- که ممکن است چند لایه‌یِ FIFOِ جدا باشند --
        # خوانده می‌شود، نه از یک عددِ تکی رویِ خودِ سند).
        line = StockDocumentLine(
            stock_document_id=adjustment_doc.stock_document_id, line_no=1, item_id=item_id, uom_id=item.base_uom_id,
            quantity=qty, quantity_base=qty, bin_location_id=bin_location_id,
            unit_cost=segments[0][0] if direction == "IN" else None,
        )
        session.add(line)
        session.flush()
        total_amount = _ZERO
        for seg_cost, seg_qty in segments:
            in_ledger = StockLedger(
                company_id=company_id, stock_document_line_id=line.line_id, item_id=item_id, warehouse_id=warehouse_id,
                bin_location_id=bin_location_id, movement_direction=direction, quantity_base=seg_qty, unit_cost=seg_cost,
                movement_date=today,
            )
            session.add(in_ledger)
            session.flush()
            if direction == "IN" and method == "FIFO":
                session.add(
                    CostLayer(
                        item_id=item_id, warehouse_id=warehouse_id, stock_ledger_id=in_ledger.ledger_id,
                        received_at=datetime.datetime.now(), original_quantity=seg_qty,
                        remaining_quantity=seg_qty, unit_cost=seg_cost,
                    )
                )
            total_amount += _money(seg_cost * seg_qty)
        adjustment_doc.posted_by_user_id = created_by_user_id
        adjustment_doc.posted_at = datetime.datetime.now()
        session.commit()
        weighted_unit_cost = (total_amount / qty) if qty else _ZERO
        return AdjustmentResult(
            stock_document_id=adjustment_doc.stock_document_id, direction=direction, unit_cost=weighted_unit_cost,
            quantity=qty, amount=total_amount,
        )


@dataclass
class CostCorrectionResult:
    quantity_remaining: decimal.Decimal
    quantity_consumed: decimal.Decimal
    inventory_value_delta: decimal.Decimal
    variance_value_delta: decimal.Decimal


def apply_purchase_cost_correction(
    item_id: int, warehouse_id: int, bin_location_id: int | None, company_id: int,
    original_quantity: decimal.Decimal, unit_cost_delta: decimal.Decimal,
) -> CostCorrectionResult:
    """طبقِ رویه‌یِ استانداردِ صنعت (مشابهِ حسابِ Purchase/Invoice Price
    Variance در ERPهایِ بزرگ): وقتی فقط بهایِ واحدِ یک فاکتورِ خریدِ
    قدیمی (که دیگر آخرین حرکتِ انبار نیست) اصلاح می‌شود، بدونِ بازمحاسبه‌
    یِ کاملِ زنجیره نمی‌شود دقیقاً تشخیص داد کدام واحدها هنوز مانده‌اند و
    کدام قبلاً مصرف/فروخته شده‌اند -- پس اختلافِ ارزش دو‌تکه می‌شود: سهمِ
    مقداری که هنوز در انبار مانده (طبقِ نسبتِ فعلی، مستقیم در میانگینِ
    موجودی بلند می‌شود) و سهمِ مقداری که قبلاً مصرف شده (چون نمی‌شود
    فروش‌هایِ گذشته را دوباره نوشت، به‌جایش با یک حسابِ مغایرتِ بها ثبت
    می‌شود -- شفاف و جداگانه، نه قاطی‌شده در بهایِ‌تمام‌شده‌یِ امروز).
    برایِ کالایِ استاندارد-قیمت‌گذاری، ارزشِ موجودی همیشه با بهایِ
    استاندارد ثابت می‌ماند -- پس کلِ اختلاف به حسابِ مغایرت می‌رود، دقیقاً
    هم‌الگو با نحوه‌یِ رفتارِ خودِ post_stock_document با اختلافِ بهایِ
    واقعی/استاندارد در لحظه‌یِ رسیدِ اصلی."""
    with new_session() as session:
        item = session.get(Item, item_id)
        if item is None:
            raise ValueError("کالا نامعتبر است.")
        costing_settings = session.get(CompanyCostingSettings, company_id)
        default_costing_method_code = None
        if costing_settings is not None:
            method_row = session.get(CostingMethod, costing_settings.default_costing_method_id)
            default_costing_method_code = method_row.code if method_row is not None else None
        method = item.costing_method_code or default_costing_method_code or "WEIGHTED_AVERAGE"
        if method == "FIFO":
            raise ValueError("اصلاحِ بهایِ واحد برایِ کالایی که با روشِ FIFO قیمت‌گذاری می‌شود، فعلاً پشتیبانی نمی‌شود.")

        if bin_location_id is None:
            default_bin = session.scalar(
                select(BinLocation).where(BinLocation.warehouse_id == warehouse_id, BinLocation.code == "GENERAL")
            )
            bin_location_id = default_bin.bin_location_id if default_bin is not None else None

        bal = session.scalar(
            select(StockBalance).where(
                StockBalance.item_id == item_id, StockBalance.warehouse_id == warehouse_id,
                StockBalance.bin_location_id == bin_location_id, StockBalance.batch_id.is_(None),
            ).with_for_update()
        )
        current_on_hand = bal.quantity_on_hand if bal is not None else _ZERO
        quantity_remaining = min(original_quantity, current_on_hand) if current_on_hand > 0 else _ZERO
        quantity_consumed = original_quantity - quantity_remaining

        if method == "STANDARD" or bal is None or quantity_remaining <= 0:
            inventory_value_delta = _ZERO
            variance_value_delta = _money(original_quantity * unit_cost_delta)
        else:
            inventory_value_delta = _money(quantity_remaining * unit_cost_delta)
            variance_value_delta = _money(quantity_consumed * unit_cost_delta)
            bal.average_unit_cost = bal.average_unit_cost + (inventory_value_delta / current_on_hand)
            bal.last_movement_at = datetime.datetime.now()
        session.commit()
        return CostCorrectionResult(
            quantity_remaining=quantity_remaining, quantity_consumed=quantity_consumed,
            inventory_value_delta=inventory_value_delta, variance_value_delta=variance_value_delta,
        )


def apply_purchase_cost_correction_fifo(
    original_stock_document_id: int, item_id: int, unit_cost_delta: decimal.Decimal,
) -> CostCorrectionResult:
    """هم‌ارزِ apply_purchase_cost_correction، ولی برایِ FIFO -- و در واقع
    *دقیق‌تر*: چون FIFO هر رسید را در یک CostLayer جداگانه ردیابی
    می‌کند (نه یک میانگینِ سراسری)، اینجا لازم نیست نسبتِ «هنوز مانده به
    مصرف‌شده» را از رویِ موجودیِ کلِ کالا حدس زد -- خودِ لایه‌یِ دقیقِ
    همین رسید (از طریقِ ردیفِ آن در سندِ انبار -> ردیفِ Ledgerِ IN -> خودِ
    CostLayer) پیدا و مستقیماً اصلاح می‌شود: سهمِ هنوز-باقی‌مانده
    (remaining_quantity) با تغییرِ unit_cost خودِ لایه (بدونِ لمسِ
    مقدارش -- پس اثری رویِ مصرفِ آینده جز بهایِ درست ندارد)، سهمِ
    قبلاً-مصرف‌شده هم مثلِ حالتِ میانگینِ موزون، به حسابِ مغایرتِ بها."""
    with new_session() as session:
        lines = session.scalars(
            select(StockDocumentLine).where(
                StockDocumentLine.stock_document_id == original_stock_document_id, StockDocumentLine.item_id == item_id,
            )
        ).all()
        if not lines:
            raise ValueError("ردیفِ این کالا در سندِ رسیدِ اصلی یافت نشد.")
        layers = []
        for ln in lines:
            ledger_row = session.scalar(
                select(StockLedger).where(
                    StockLedger.stock_document_line_id == ln.line_id, StockLedger.movement_direction == "IN",
                )
            )
            if ledger_row is None:
                continue
            layer = session.scalar(
                select(CostLayer).where(CostLayer.stock_ledger_id == ledger_row.ledger_id).with_for_update()
            )
            if layer is not None:
                layers.append(layer)
        if not layers:
            raise ValueError("لایه‌یِ هزینه‌یِ این رسید یافت نشد.")

        total_remaining = sum((layer.remaining_quantity for layer in layers), _ZERO)
        total_original = sum((layer.original_quantity for layer in layers), _ZERO)
        total_consumed = total_original - total_remaining

        for layer in layers:
            if layer.remaining_quantity > 0:
                layer.unit_cost = layer.unit_cost + unit_cost_delta

        inventory_value_delta = _money(total_remaining * unit_cost_delta)
        variance_value_delta = _money(total_consumed * unit_cost_delta)
        session.commit()
        return CostCorrectionResult(
            quantity_remaining=total_remaining, quantity_consumed=total_consumed,
            inventory_value_delta=inventory_value_delta, variance_value_delta=variance_value_delta,
        )


# ---------------------------------------------------------------------
# نگاشتِ حسابِ حسابداری در سطحِ دسته‌بندی — بخشِ ۱۴ (override رویِ نگاشتِ
# سراسری). این دور فقط CRUD است؛ post_stock_document/_resolve_role_account
# هنوز از نگاشتِ سراسریِ company-wide می‌خوانند — اتصالِ این override به
# موتورِ ثبت، دورِ بعدی.
# ---------------------------------------------------------------------
@dataclass
class CategoryAccountMappingRow:
    category_id: int
    mapping_key: str
    account_id: int


def list_category_account_mappings(category_id: int) -> list[CategoryAccountMappingRow]:
    with new_session() as session:
        rows = session.scalars(
            select(CategoryAccountMapping).where(CategoryAccountMapping.category_id == category_id)
        ).all()
        return [CategoryAccountMappingRow(r.category_id, r.mapping_key, r.account_id) for r in rows]


def set_category_account_mapping(category_id: int, mapping_key: str, account_id: int) -> None:
    if mapping_key not in MAPPING_LABELS:
        raise ValueError("کلیدِ نگاشت نامعتبر است.")
    with new_session() as session:
        row = session.get(CategoryAccountMapping, (category_id, mapping_key))
        if row is None:
            session.add(CategoryAccountMapping(category_id=category_id, mapping_key=mapping_key, account_id=account_id))
        else:
            row.account_id = account_id
        session.commit()


def delete_category_account_mapping(category_id: int, mapping_key: str) -> None:
    with new_session() as session:
        row = session.get(CategoryAccountMapping, (category_id, mapping_key))
        if row is not None:
            session.delete(row)
            session.commit()


# ---------------------------------------------------------------------
# نگاشتِ حسابِ حسابداری در سطحِ‌انبار — عیناً هم‌شکلِ نگاشتِ سطحِ‌دسته‌بندیِ
# بالا. این دور فقط CRUD است؛ اتصال به _resolve_role_account/
# post_stock_document دورِ بعدی است.
# ---------------------------------------------------------------------
@dataclass
class WarehouseAccountMappingRow:
    warehouse_id: int
    mapping_key: str
    account_id: int


def list_warehouse_account_mappings(warehouse_id: int) -> list[WarehouseAccountMappingRow]:
    with new_session() as session:
        rows = session.scalars(
            select(WarehouseAccountMapping).where(WarehouseAccountMapping.warehouse_id == warehouse_id)
        ).all()
        return [WarehouseAccountMappingRow(r.warehouse_id, r.mapping_key, r.account_id) for r in rows]


def set_warehouse_account_mapping(warehouse_id: int, mapping_key: str, account_id: int) -> None:
    if mapping_key not in MAPPING_LABELS:
        raise ValueError("کلیدِ نگاشت نامعتبر است.")
    with new_session() as session:
        row = session.get(WarehouseAccountMapping, (warehouse_id, mapping_key))
        if row is None:
            session.add(WarehouseAccountMapping(warehouse_id=warehouse_id, mapping_key=mapping_key, account_id=account_id))
        else:
            row.account_id = account_id
        session.commit()


def delete_warehouse_account_mapping(warehouse_id: int, mapping_key: str) -> None:
    with new_session() as session:
        row = session.get(WarehouseAccountMapping, (warehouse_id, mapping_key))
        if row is not None:
            session.delete(row)
            session.commit()
