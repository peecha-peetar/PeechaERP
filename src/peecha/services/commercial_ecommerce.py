"""فروشِ اینترنتی و Omnichannel (مرحلهٔ ۸): لایهٔ اتصال‌گرِ انتزاعی و
مسیریابیِ توزیع‌شدهٔ سفارش. سفارشِ آنلاین دقیقاً همان SALES_ORDER است —
این فایل فقط نگاشت/ایمپورت/مسیریابی را اضافه می‌کند."""

from __future__ import annotations

import datetime
import decimal
from dataclasses import dataclass

from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.commercial import (
    Channel,
    FulfillmentRoutingRule,
    MarketplaceCategoryMapping,
    MarketplaceConnection,
    MarketplaceCustomerMapping,
    MarketplaceInventoryPushLog,
    MarketplaceItemMapping,
    MarketplaceOrderSyncLog,
)
from peecha.db.models.inventory import Item, ItemCategory
from peecha.services import commercial_documents as documents_service
from peecha.services import inventory_engine as inv_engine_service

_ZERO = decimal.Decimal("0")

# طبقِ درخواستِ صریح («این برنامه [PeechaSync] رو با امکاناتش تحتِ ماژولِ
# فروشِ اینترنتی به این ERP اضافه کن»): این‌جا فقط ووکامرس پیاده‌سازی
# شده -- پرستاشاپ (که در PeechaSync خودش هم توسطِ نویسنده‌اش «هنوز رویِ
# فروشگاهِ واقعی تست‌نشده» علامت خورده بود) عمداً به دورِ بعدی موکول شد
# تا بدونِ آزمونِ کافی به این ERP اضافه نشود.
_SUPPORTED_SYNC_PLATFORMS = ("WOOCOMMERCE",)


# ---------------------------------------------------------------------
# اتصال
# ---------------------------------------------------------------------
def list_connections(company_id: int) -> list[MarketplaceConnection]:
    with new_session() as session:
        return list(session.scalars(select(MarketplaceConnection).where(MarketplaceConnection.company_id == company_id)))


def create_connection(company_id: int, platform_code: str, store_url: str, channel_code: str, warehouse_id: int | None = None) -> int:
    if platform_code not in ("WOOCOMMERCE", "PRESTASHOP", "OTHER"):
        raise ValueError("پلتفرمِ نامعتبر است.")
    with new_session() as session:
        channel = session.get(Channel, (channel_code, company_id))
        if channel is None:
            raise ValueError("کانالِ نامعتبر است.")
        row = MarketplaceConnection(company_id=company_id, platform_code=platform_code, store_url=store_url, channel_code=channel_code, warehouse_id=warehouse_id)
        session.add(row)
        session.commit()
        return row.connection_id


def disconnect(connection_id: int) -> None:
    with new_session() as session:
        row = session.get(MarketplaceConnection, connection_id)
        if row is None:
            raise ValueError("اتصال نامعتبر است.")
        row.sync_status = "DISCONNECTED"
        session.commit()


def set_connection_credentials(connection_id: int, credentials: dict) -> None:
    """طبقِ درخواستِ صریح («کدامِ کاربردیِ PeechaSync را به ERP اضافه کن»):
    کلیدِ API/رازِ اتصال (مثلاً Consumer Key/Secretِ ووکامرس) قبل از
    ذخیره در ستونِ credentials_encrypted رمزنگاری می‌شود."""
    from peecha.services import ecommerce_credentials

    encrypted = ecommerce_credentials.encrypt_credentials(credentials)
    with new_session() as session:
        row = session.get(MarketplaceConnection, connection_id)
        if row is None:
            raise ValueError("اتصال نامعتبر است.")
        row.credentials_encrypted = encrypted
        session.commit()


# ---------------------------------------------------------------------
# نگاشتِ کالا/مشتری
# ---------------------------------------------------------------------
def map_item(connection_id: int, external_sku: str, item_id: int, external_price: decimal.Decimal | None = None) -> None:
    with new_session() as session:
        row = session.scalar(select(MarketplaceItemMapping).where(MarketplaceItemMapping.connection_id == connection_id, MarketplaceItemMapping.external_sku == external_sku))
        if row is None:
            row = MarketplaceItemMapping(connection_id=connection_id, external_sku=external_sku, item_id=item_id, external_price=external_price)
            session.add(row)
        else:
            row.item_id = item_id
            row.external_price = external_price
        session.commit()


def resolve_item(connection_id: int, external_sku: str) -> int | None:
    with new_session() as session:
        row = session.scalar(select(MarketplaceItemMapping).where(MarketplaceItemMapping.connection_id == connection_id, MarketplaceItemMapping.external_sku == external_sku))
        return row.item_id if row is not None else None


def list_item_mappings(connection_id: int) -> list[MarketplaceItemMapping]:
    with new_session() as session:
        return list(session.scalars(select(MarketplaceItemMapping).where(MarketplaceItemMapping.connection_id == connection_id)))


def map_customer(connection_id: int, external_customer_id: str, customer_detail_account_id: int) -> None:
    with new_session() as session:
        row = session.scalar(select(MarketplaceCustomerMapping).where(MarketplaceCustomerMapping.connection_id == connection_id, MarketplaceCustomerMapping.external_customer_id == external_customer_id))
        if row is None:
            session.add(MarketplaceCustomerMapping(connection_id=connection_id, external_customer_id=external_customer_id, customer_detail_account_id=customer_detail_account_id))
            session.commit()


def resolve_customer(connection_id: int, external_customer_id: str) -> int | None:
    with new_session() as session:
        row = session.scalar(select(MarketplaceCustomerMapping).where(MarketplaceCustomerMapping.connection_id == connection_id, MarketplaceCustomerMapping.external_customer_id == external_customer_id))
        return row.customer_detail_account_id if row is not None else None


def list_customer_mappings(connection_id: int) -> list[MarketplaceCustomerMapping]:
    with new_session() as session:
        return list(session.scalars(select(MarketplaceCustomerMapping).where(MarketplaceCustomerMapping.connection_id == connection_id)))


# ---------------------------------------------------------------------
# ایمپورتِ سفارش
# ---------------------------------------------------------------------
@dataclass
class ExternalOrderLine:
    external_sku: str
    quantity: decimal.Decimal
    uom_id: int


@dataclass
class ImportResult:
    sync_status: str  # IMPORTED | FAILED | DUPLICATE
    document_id: int | None
    error_message: str | None


def import_order(
    connection_id: int, external_order_id: str, external_customer_id: str, company_id: int, created_by_user_id: int,
    currency_id: int, price_list_id: int, warehouse_id: int, lines: list[ExternalOrderLine],
) -> ImportResult:
    with new_session() as session:
        existing = session.scalar(
            select(MarketplaceOrderSyncLog).where(
                MarketplaceOrderSyncLog.connection_id == connection_id, MarketplaceOrderSyncLog.external_order_id == external_order_id
            )
        )
        if existing is not None:
            return ImportResult(sync_status="DUPLICATE", document_id=existing.document_id, error_message=None)
        connection = session.get(MarketplaceConnection, connection_id)

    customer_id = resolve_customer(connection_id, external_customer_id)
    if customer_id is None:
        _log_sync(connection_id, external_order_id, None, "FAILED", "مشتریِ خارجی به هیچ مشتریِ داخلی نگاشت نشده است.")
        return ImportResult(sync_status="FAILED", document_id=None, error_message="مشتریِ خارجی نگاشت نشده است.")

    resolved_lines: list[tuple[int, decimal.Decimal, int]] = []
    for ext_line in lines:
        item_id = resolve_item(connection_id, ext_line.external_sku)
        if item_id is None:
            _log_sync(connection_id, external_order_id, None, "FAILED", f"SKUِ «{ext_line.external_sku}» نگاشت نشده است.")
            return ImportResult(sync_status="FAILED", document_id=None, error_message=f"SKUِ «{ext_line.external_sku}» نگاشت نشده است.")
        resolved_lines.append((item_id, ext_line.quantity, ext_line.uom_id))

    document_id = None
    try:
        document_id = documents_service.create_document(
            company_id, created_by_user_id, "SALES_ORDER", datetime.date.today(),
            documents_service.DocumentHeaderFields(
                counterparty_detail_account_id=customer_id, currency_id=currency_id, warehouse_id=warehouse_id,
                channel_code=connection.channel_code, price_list_id=price_list_id, reference_no=f"EXT-{external_order_id}",
            ),
        )
        for item_id, quantity, uom_id in resolved_lines:
            documents_service.add_line(document_id, company_id, item_id, uom_id, quantity, quantity)
    except ValueError as exc:
        if document_id is not None:
            documents_service.delete_document(document_id, company_id)
        _log_sync(connection_id, external_order_id, None, "FAILED", str(exc))
        return ImportResult(sync_status="FAILED", document_id=None, error_message=str(exc))

    _log_sync(connection_id, external_order_id, document_id, "IMPORTED", None)
    return ImportResult(sync_status="IMPORTED", document_id=document_id, error_message=None)


def _log_sync(connection_id: int, external_order_id: str, document_id: int | None, sync_status: str, error_message: str | None) -> None:
    with new_session() as session:
        session.add(
            MarketplaceOrderSyncLog(
                connection_id=connection_id, external_order_id=external_order_id, document_id=document_id,
                sync_status=sync_status, error_message=error_message,
            )
        )
        session.commit()


def list_sync_log(connection_id: int, sync_status: str | None = None) -> list[MarketplaceOrderSyncLog]:
    with new_session() as session:
        stmt = select(MarketplaceOrderSyncLog).where(MarketplaceOrderSyncLog.connection_id == connection_id)
        if sync_status:
            stmt = stmt.where(MarketplaceOrderSyncLog.sync_status == sync_status)
        return list(session.scalars(stmt))


# ---------------------------------------------------------------------
# Pushِ موجودی
# ---------------------------------------------------------------------
def push_inventory_snapshot(connection_id: int, item_id: int, warehouse_id: int | None = None) -> decimal.Decimal:
    balances = inv_engine_service.list_balances(company_id=_connection_company_id(connection_id), item_id=item_id, warehouse_id=warehouse_id)
    atp = max(sum((b.quantity_available for b in balances), _ZERO), _ZERO)
    with new_session() as session:
        session.add(MarketplaceInventoryPushLog(connection_id=connection_id, item_id=item_id, pushed_atp_quantity=atp))
        session.commit()
    return atp


def _connection_company_id(connection_id: int) -> int:
    with new_session() as session:
        connection = session.get(MarketplaceConnection, connection_id)
        if connection is None:
            raise ValueError("اتصال نامعتبر است.")
        return connection.company_id


# ---------------------------------------------------------------------
# سینکِ کاتالوگ/سفارش/مشتری با فروشگاهِ اینترنتی -- طبقِ درخواستِ صریحِ
# کاربر («ماژولِ فروشِ اینترنتی» با استفاده از دیتابیسِ همینِ ERP، بدونِ
# اتکا به هلو/دژاوو). فعلاً فقط ووکامرس (_SUPPORTED_SYNC_PLATFORMS).
# ---------------------------------------------------------------------
def _build_store_client(connection: MarketplaceConnection):
    from peecha.integrations.ecommerce import wc_client
    from peecha.services import ecommerce_credentials

    if connection.platform_code not in _SUPPORTED_SYNC_PLATFORMS:
        raise ValueError(f"سینک برایِ پلتفرمِ «{connection.platform_code}» هنوز پیاده‌سازی نشده است.")
    creds = ecommerce_credentials.decrypt_credentials(connection.credentials_encrypted)
    return wc_client.build_wcapi(connection.store_url, creds.get("consumer_key", ""), creds.get("consumer_secret", ""))


def _get_connection(connection_id: int) -> MarketplaceConnection:
    with new_session() as session:
        connection = session.get(MarketplaceConnection, connection_id)
        if connection is None:
            raise ValueError("اتصال نامعتبر است.")
        return connection


def _channel_default_price_list(connection: MarketplaceConnection) -> int | None:
    with new_session() as session:
        channel = session.get(Channel, (connection.channel_code, connection.company_id))
        return channel.default_price_list_id if channel is not None else None


def _resolve_category_external_id(wcapi, connection_id: int, category_id: int | None) -> int | None:
    if category_id is None:
        return None
    from peecha.integrations.ecommerce import wc_client

    with new_session() as session:
        mapping = session.scalar(
            select(MarketplaceCategoryMapping).where(
                MarketplaceCategoryMapping.connection_id == connection_id,
                MarketplaceCategoryMapping.category_id == category_id,
            )
        )
        if mapping is not None:
            return int(mapping.external_category_id)
        category = session.get(ItemCategory, category_id)
        if category is None:
            return None
        parent_category_id, name = category.parent_category_id, category.name

    parent_external_id = _resolve_category_external_id(wcapi, connection_id, parent_category_id)
    found = wc_client.find_category_by_name(wcapi, name, parent_external_id)
    external_id = int(found["id"]) if found else int(wc_client.create_category(wcapi, name, parent_external_id)["id"])
    with new_session() as session:
        session.add(
            MarketplaceCategoryMapping(connection_id=connection_id, category_id=category_id, external_category_id=str(external_id))
        )
        session.commit()
    return external_id


@dataclass
class CatalogSyncResult:
    pushed: int
    skipped: int
    failed: int
    errors: list[str]


def _format_store_price(value: decimal.Decimal) -> str:
    """طبقِ رفعِ باگِ واقعیِ کشف‌شده حینِ تست: چون unit_price در ERP با
    دقتِ ۶ رقمِ اعشار ذخیره می‌شود (Numeric(18,6))، str() خام رشته‌ای
    مثلِ «250000.000000» تولید می‌کرد -- درست کار می‌کند ولی برایِ فیلدِ
    قیمتِ فروشگاه غیرِضروری/شلخته است. این‌جا به دو رقمِ اعشارِ متداولِ
    قیمت گرد می‌شود."""
    return f"{value.quantize(decimal.Decimal('0.01')):f}"


def sync_catalog_to_store(connection_id: int) -> CatalogSyncResult:
    """طبقِ گزارشِ کاربر: کالا/قیمت/موجودیِ همینِ ERP را به فروشگاه
    می‌فرستد -- قیمت از فهرستِ قیمتِ پیش‌فرضِ کانالِ همین اتصال خوانده
    می‌شود؛ کالاهایِ متغیر (دارایِ چند حالت) فعلاً رد می‌شوند (فازِ بعدی)."""
    from peecha.integrations.ecommerce import wc_client
    from peecha.services import commercial_pricing as pricing_service
    from peecha.services import inventory_catalog as catalog_service

    connection = _get_connection(connection_id)
    price_list_id = _channel_default_price_list(connection)
    if price_list_id is None:
        raise ValueError("کانالِ این اتصال فهرستِ قیمتِ پیش‌فرض ندارد -- در تنظیماتِ کانال یک فهرستِ قیمت مشخص کنید.")

    wcapi = _build_store_client(connection)
    price_by_item: dict[int, decimal.Decimal] = {
        row.item_id: row.unit_price for row in pricing_service.list_price_list_items(price_list_id) if row.min_quantity == 1
    }

    pushed = skipped = failed = 0
    errors: list[str] = []
    for item in catalog_service.list_items(connection.company_id, active_only=True):
        if item.variant_parent_item_id is not None or not item.is_sellable:
            skipped += 1
            continue
        sku = (item.sku or item.code or "").strip()
        if not sku:
            skipped += 1
            continue
        price = price_by_item.get(item.item_id)
        if price is None:
            skipped += 1
            errors.append(f"{sku}: قیمتی در فهرستِ قیمتِ کانال یافت نشد -- سینک نشد.")
            continue
        try:
            balances = inv_engine_service.list_balances(company_id=connection.company_id, item_id=item.item_id, warehouse_id=connection.warehouse_id)
            stock_qty = max(sum((b.quantity_available for b in balances), _ZERO), _ZERO)
            category_external_id = _resolve_category_external_id(wcapi, connection_id, item.category_id)
            payload = {
                "name": item.name or sku,
                "regular_price": _format_store_price(price),
                "manage_stock": True,
                "stock_quantity": int(stock_qty),
                "status": "publish" if item.is_active else "draft",
            }
            if category_external_id:
                payload["categories"] = [{"id": category_external_id}]
            wc_client.upsert_product(wcapi, sku, payload)
            map_item(connection_id, sku, item.item_id, external_price=price)
            pushed += 1
        except Exception as exc:  # noqa: BLE001 -- یک کالایِ خراب نباید کلِ سینک را متوقف کند
            failed += 1
            errors.append(f"{sku}: {exc}")

    with new_session() as session:
        row = session.get(MarketplaceConnection, connection_id)
        row.last_synced_at = datetime.datetime.now()
        session.commit()
    return CatalogSyncResult(pushed=pushed, skipped=skipped, failed=failed, errors=errors)


@dataclass
class CustomerPullResult:
    created: int
    already_mapped: int
    failed: int
    errors: list[str]


def pull_new_customers(connection_id: int) -> CustomerPullResult:
    """طبقِ گزارشِ کاربر: مشتریانِ تازه‌ثبت‌شده در فروشگاه را می‌خواند --
    فقط مشتریانِ سفارش‌هایِ اخیر (نه کلِ مشتریانِ فروشگاه، که ممکن است
    خیلی زیاد و نامرتبط باشند)."""
    from peecha.integrations.ecommerce import wc_client
    from peecha.services import commercial_partners as partners_service

    connection = _get_connection(connection_id)
    wcapi = _build_store_client(connection)
    orders = wc_client.fetch_new_orders(wcapi)
    external_ids = {o.external_customer_id for o in orders if o.external_customer_id and o.external_customer_id != "0"}

    created = already_mapped = failed = 0
    errors: list[str] = []
    for external_customer_id in external_ids:
        if resolve_customer(connection_id, external_customer_id) is not None:
            already_mapped += 1
            continue
        try:
            customer = wc_client.fetch_customer(wcapi, external_customer_id)
            if customer is None:
                failed += 1
                errors.append(f"مشتریِ #{external_customer_id}: در فروشگاه یافت نشد.")
                continue
            full_name = f"{customer.first_name} {customer.last_name}".strip() or customer.email or f"مشتریِ فروشگاه #{external_customer_id}"
            customer_detail_account_id = partners_service.create_customer(
                connection.company_id, f"WC-{external_customer_id}", full_name,
                partners_service.CustomerProfileFields(), fast_track=True,
            )
            map_customer(connection_id, external_customer_id, customer_detail_account_id)
            created += 1
        except Exception as exc:  # noqa: BLE001
            failed += 1
            errors.append(f"مشتریِ #{external_customer_id}: {exc}")
    return CustomerPullResult(created=created, already_mapped=already_mapped, failed=failed, errors=errors)


@dataclass
class OrderPullResult:
    imported: int
    duplicate: int
    failed: int
    errors: list[str]


def pull_new_orders(connection_id: int, created_by_user_id: int, currency_id: int) -> OrderPullResult:
    """طبقِ گزارشِ کاربر: سفارش‌هایِ پرداخت‌شدهٔ تازه را از فروشگاه
    می‌خواند و از طریقِ import_order (که از قبل در ERP آماده بود) به
    سفارشِ فروش تبدیل می‌کند."""
    from peecha.integrations.ecommerce import wc_client

    connection = _get_connection(connection_id)
    price_list_id = _channel_default_price_list(connection)
    if price_list_id is None or connection.warehouse_id is None:
        raise ValueError("این اتصال باید هم انبار و هم فهرستِ قیمتِ پیش‌فرض (رویِ کانال) داشته باشد.")

    wcapi = _build_store_client(connection)
    imported = duplicate = failed = 0
    errors: list[str] = []
    for order in wc_client.fetch_new_orders(wcapi):
        lines: list[ExternalOrderLine] = []
        unmapped_sku = None
        for line in order.lines:
            item_id = resolve_item(connection_id, line["sku"])
            if item_id is None:
                unmapped_sku = line["sku"]
                break
            with new_session() as session:
                item_row = session.get(Item, item_id)
                uom_id = item_row.base_uom_id
            lines.append(ExternalOrderLine(external_sku=line["sku"], quantity=decimal.Decimal(str(line["quantity"])), uom_id=uom_id))
        if unmapped_sku is not None:
            failed += 1
            errors.append(f"سفارشِ #{order.external_order_id}: SKUِ «{unmapped_sku}» نگاشت نشده است.")
            continue
        result = import_order(
            connection_id, order.external_order_id, order.external_customer_id, connection.company_id,
            created_by_user_id, currency_id, price_list_id, connection.warehouse_id, lines,
        )
        if result.sync_status == "IMPORTED":
            imported += 1
        elif result.sync_status == "DUPLICATE":
            duplicate += 1
        else:
            failed += 1
            errors.append(f"سفارشِ #{order.external_order_id}: {result.error_message}")
    return OrderPullResult(imported=imported, duplicate=duplicate, failed=failed, errors=errors)


@dataclass
class FullSyncResult:
    catalog: CatalogSyncResult
    customers: CustomerPullResult
    orders: OrderPullResult


def sync_now(connection_id: int, created_by_user_id: int, currency_id: int) -> FullSyncResult:
    """دکمهٔ «سینکِ الان» -- طبقِ تصمیمِ کاربر (فازِ ۱ فقط دستی، بدونِ
    زمان‌بندیِ خودکار): کاتالوگ → مشتریانِ تازه → سفارش‌هایِ تازه، به
    همین ترتیب (سفارش به نگاشتِ مشتری نیاز دارد)."""
    catalog = sync_catalog_to_store(connection_id)
    customers = pull_new_customers(connection_id)
    orders = pull_new_orders(connection_id, created_by_user_id, currency_id)
    return FullSyncResult(catalog=catalog, customers=customers, orders=orders)


# ---------------------------------------------------------------------
# مسیریابیِ توزیع‌شدهٔ سفارش (DOM)
# ---------------------------------------------------------------------
def list_routing_rules(company_id: int) -> list[FulfillmentRoutingRule]:
    with new_session() as session:
        return list(
            session.scalars(
                select(FulfillmentRoutingRule).where(FulfillmentRoutingRule.company_id == company_id).order_by(FulfillmentRoutingRule.priority)
            )
        )


def create_routing_rule(company_id: int, strategy_code: str, fallback_warehouse_id: int, channel_code: str | None = None, priority: int = 100) -> int:
    if strategy_code not in ("MOST_STOCK", "REGION_MATCH", "LOWEST_COST", "FIXED_WAREHOUSE"):
        raise ValueError("استراتژیِ نامعتبر است.")
    with new_session() as session:
        row = FulfillmentRoutingRule(company_id=company_id, channel_code=channel_code, strategy_code=strategy_code, fallback_warehouse_id=fallback_warehouse_id, priority=priority)
        session.add(row)
        session.commit()
        return row.rule_id


def resolve_fulfillment_warehouse(company_id: int, item_id: int, channel_code: str | None, warehouse_provinces: dict[int, str], customer_province: str | None = None) -> int:
    """warehouse_provinces: نگاشتِ warehouse_id → نامِ استان (چون این
    اطلاعات رویِ خودِ آدرسِ انبار است، نه این سرویس)."""
    with new_session() as session:
        rules = session.scalars(
            select(FulfillmentRoutingRule)
            .where(FulfillmentRoutingRule.company_id == company_id)
            .order_by(FulfillmentRoutingRule.priority)
        ).all()
        applicable = [r for r in rules if r.channel_code is None or r.channel_code == channel_code]
    if not applicable:
        raise ValueError("قاعدهٔ مسیریابی‌ای تعریف نشده است.")
    rule = applicable[0]
    balances = inv_engine_service.list_balances(company_id=company_id, item_id=item_id)
    by_warehouse: dict[int, decimal.Decimal] = {}
    for b in balances:
        by_warehouse[b.warehouse_id] = by_warehouse.get(b.warehouse_id, _ZERO) + b.quantity_available

    if rule.strategy_code == "FIXED_WAREHOUSE":
        return rule.fallback_warehouse_id
    if rule.strategy_code == "REGION_MATCH" and customer_province:
        for warehouse_id, province in warehouse_provinces.items():
            if province == customer_province and by_warehouse.get(warehouse_id, _ZERO) > 0:
                return warehouse_id
    if rule.strategy_code in ("MOST_STOCK", "REGION_MATCH", "LOWEST_COST"):
        candidates = {wid: qty for wid, qty in by_warehouse.items() if qty > 0}
        if candidates:
            return max(candidates, key=candidates.get)
    return rule.fallback_warehouse_id
