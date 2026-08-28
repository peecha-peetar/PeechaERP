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
    MarketplaceConnection,
    MarketplaceCustomerMapping,
    MarketplaceInventoryPushLog,
    MarketplaceItemMapping,
    MarketplaceOrderSyncLog,
)
from peecha.services import commercial_documents as documents_service
from peecha.services import inventory_engine as inv_engine_service

_ZERO = decimal.Decimal("0")


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
