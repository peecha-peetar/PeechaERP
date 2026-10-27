"""R345: دریافت سفارش از فروشگاه اینترنتی (با کلاینت ساختگی، بدون اتصال بیرونی): سفارش تطبیق‌شده سفارش فروش با کانال،
انبار، فهرست قیمت و شمارهٔ مرجع می‌شود؛ دریافت دوباره تکراری نمی‌سازد؛ کالای تطبیق‌نشده و مشتری تطبیق‌نشده رد و ثبت
می‌شوند؛ پس از تطبیق مشتری، همان سفارش ناموفق در دریافت بعدی وارد می‌شود."""
import os, sys
from types import SimpleNamespace
os.environ["PEECHA_DB_NAME"] = "peecha_test_r345_ecommerce"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prd_fixture import *  # noqa: F401,F403

from peecha.services import commercial_documents as docs, commercial_ecommerce as ecommerce, commercial_partners as partners, \
    commercial_pricing as pricing

price_list = pricing.create_price_list(company_id, "WEB", "قیمت فروشگاه", "SALES", company.base_currency_id, today)
pricing.set_price_list_item(price_list, byp, pcs, D(250_000))
pricing.create_channel(company_id, "WEB", "فروشگاه اینترنتی", "ONLINE")
pricing.set_channel_pricing_defaults(company_id, "WEB", price_list, None)
connection = ecommerce.create_connection(company_id, "WOOCOMMERCE", "https://shop.example.ir", "WEB", wh_rm)
customer = partners.create_customer(company_id, "C1", "خریدار اینترنتی", fast_track=True)
late_customer = partners.create_customer(company_id, "C2", "خریدار دیرتطبیق", fast_track=True)
ecommerce.map_item(connection, "SKU-1", byp)
ecommerce.map_customer(connection, "77", customer)
receive(byp, 20, 100_000)

store_orders = [
    SimpleNamespace(external_order_id="1001", external_customer_id="77", lines=[{"sku": "SKU-1", "quantity": 3}]),
    SimpleNamespace(external_order_id="1002", external_customer_id="77", lines=[{"sku": "SKU-X", "quantity": 1}]),
    SimpleNamespace(external_order_id="1003", external_customer_id="99", lines=[{"sku": "SKU-1", "quantity": 2}]),
]
ecommerce._client_module_for_platform = lambda code: SimpleNamespace(fetch_new_orders=lambda client: list(store_orders))
ecommerce._build_store_client = lambda conn, creds=None: object()

first = ecommerce.pull_new_orders(connection, uid, company.base_currency_id)
check(first.imported == 1 and first.failed == 2, f"one order imported, two refused ({first})")
check(any("SKU-X" in e for e in first.errors) and any("1003" in e for e in first.errors), "the reasons name the SKU and the order")
with new_session() as s:
    from peecha.db.models.commercial import CommercialDocument
    order = s.scalar(select(CommercialDocument).where(CommercialDocument.reference_no == "EXT-1001"))
check(order is not None and order.document_type_code == "SALES_ORDER" and order.channel_code == "WEB"
      and order.warehouse_id == wh_rm and order.counterparty_detail_account_id == customer,
      "the store order becomes a sales order with channel, warehouse and customer")
header, lines = docs.get_document(order.document_id, company_id)
check(len(lines) == 1 and lines[0].quantity == D(3) and lines[0].unit_price == D(250_000), "lines carry the store price list")

second = ecommerce.pull_new_orders(connection, uid, company.base_currency_id)
check(second.duplicate >= 1 and second.imported == 0, f"pulling again does not duplicate the order ({second})")

ecommerce.map_customer(connection, "99", late_customer)
third = ecommerce.pull_new_orders(connection, uid, company.base_currency_id)
with new_session() as s:
    late = s.scalar(select(CommercialDocument).where(CommercialDocument.reference_no == "EXT-1003"))
check(third.imported == 1 and late is not None and late.counterparty_detail_account_id == late_customer,
      f"once the customer is matched, the earlier failed order is imported ({third})")

finish()
