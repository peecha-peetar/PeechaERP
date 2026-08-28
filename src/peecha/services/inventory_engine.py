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
from peecha.db.models.accounting import DetailAccount
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


def get_account_mapping(company_id: int, mapping_key: str) -> int | None:
    with new_session() as session:
        row = session.get(InventoryAccountMapping, (company_id, mapping_key))
        return row.account_id if row is not None else None


def set_account_mapping(company_id: int, mapping_key: str, account_id: int) -> None:
    if mapping_key not in MAPPING_LABELS:
        raise ValueError("کلیدِ نگاشتِ نامعتبر است.")
    with new_session() as session:
        row = session.get(InventoryAccountMapping, (company_id, mapping_key))
        if row is None:
            session.add(InventoryAccountMapping(company_id=company_id, mapping_key=mapping_key, account_id=account_id))
        else:
            row.account_id = account_id
        session.commit()


def list_account_mappings(company_id: int) -> list[AccountMappingRow]:
    from peecha.services import chart_of_accounts as coa_service

    with new_session() as session:
        rows = {
            r.mapping_key: r.account_id
            for r in session.scalars(select(InventoryAccountMapping).where(InventoryAccountMapping.company_id == company_id))
        }
    accounts_by_id = {a.account_id: f"{a.full_code} — {a.name}" for a in coa_service.list_accounts(company_id)}
    return [
        AccountMappingRow(key, label, rows.get(key), accounts_by_id.get(rows.get(key)) if rows.get(key) else None)
        for key, label in MAPPING_LABELS.items()
    ]


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
    طبقِ تصمیمِ صریح: وقتی سندِ مستقیمِ انبار (رسید/برگشت) بدونِ بهایِ
    واحد ثبتِ نهایی می‌شود و روشِ قیمت‌گذاری STANDARD نیست، به‌جایِ
    خطایِ سخت، همین مقدار به‌طورِ نامرئی جایگزین می‌شود."""
    row = session.scalar(
        select(StockLedger.unit_cost)
        .where(StockLedger.item_id == item_id, StockLedger.unit_cost.is_not(None))
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

        debits: dict[str, decimal.Decimal] = {}
        credits: dict[str, decimal.Decimal] = {}

        def add_debit(role: str, amount: decimal.Decimal) -> None:
            if amount == 0:
                return
            debits[role] = debits.get(role, _ZERO) + amount

        def add_credit(role: str, amount: decimal.Decimal) -> None:
            if amount == 0:
                return
            credits[role] = credits.get(role, _ZERO) + amount

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
                            # به‌طورِ نامرئی جایگزین می‌شود؛ اگر هیچ سابقه‌ای
                            # نبود، صفر (نه خطا) تا Postِ سند هرگز مسدود نشود.
                            actual_cost = _last_known_unit_cost(session, item.item_id) or _ZERO

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
                add_debit("INVENTORY_ASSET", inventory_amount)
                variance = payable_amount - inventory_amount
                if doc_type == "RECEIPT" and variance != 0:
                    if variance > 0:
                        add_debit("INVENTORY_COST_VARIANCE", variance)
                    else:
                        add_credit("INVENTORY_COST_VARIANCE", -variance)
                credit_role = "SUPPLIER_PAYABLE" if doc_type == "RECEIPT" else "CUSTOMER_RECEIVABLE"
                if doc.counterparty_detail_account_id is not None:
                    add_credit(credit_role, payable_amount)
                else:
                    add_credit("INVENTORY_ADJUSTMENT_GAIN", payable_amount)

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
                add_credit("INVENTORY_ASSET", total_amount)
                if doc_type == "ISSUE":
                    add_debit("COGS", total_amount)
                elif doc.counterparty_detail_account_id is not None:
                    add_debit("SUPPLIER_PAYABLE", total_amount)
                else:
                    add_debit("INVENTORY_ADJUSTMENT_LOSS", total_amount)

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
                    add_credit("INVENTORY_ASSET", total_amount)
                    add_debit("INVENTORY_ADJUSTMENT_LOSS", total_amount)
                if doc.destination_warehouse_id is not None:
                    warehouse_id = doc.destination_warehouse_id
                    bin_id = resolve_bin(warehouse_id, line.bin_location_id)
                    method = costing_method(item)
                    if method == "STANDARD":
                        unit_cost = _standard_cost(session, item.item_id, movement_date)
                    elif line.unit_cost is not None:
                        unit_cost = line.unit_cost
                    else:
                        bal = get_or_create_balance(item.item_id, warehouse_id, bin_id)
                        unit_cost = bal.average_unit_cost or _ZERO
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
                    add_debit("INVENTORY_ASSET", amount)
                    add_credit("INVENTORY_ADJUSTMENT_GAIN", amount)
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
        je_lines: list[je_service.LineInput] = []
        description = doc.description or f"سندِ انبار #{doc.document_no}"
        for role, amount in debits.items():
            account_id = _resolve_role_account(session, company_id, role)
            details = dict(extra_dims)
            if role in ("SUPPLIER_PAYABLE", "CUSTOMER_RECEIVABLE") and doc.counterparty_detail_account_id is not None:
                details[person_dimension_type_id] = doc.counterparty_detail_account_id
            je_lines.append(je_service.LineInput(account_id=account_id, description=description, debit=amount, credit=_ZERO, details=details))
        for role, amount in credits.items():
            account_id = _resolve_role_account(session, company_id, role)
            details = dict(extra_dims)
            if role in ("SUPPLIER_PAYABLE", "CUSTOMER_RECEIVABLE") and doc.counterparty_detail_account_id is not None:
                details[person_dimension_type_id] = doc.counterparty_detail_account_id
            je_lines.append(je_service.LineInput(account_id=account_id, description=description, debit=_ZERO, credit=amount, details=details))

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
