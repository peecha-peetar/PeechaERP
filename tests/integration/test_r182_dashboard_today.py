import os, sys, decimal, datetime
os.environ["PEECHA_DB_NAME"] = "peecha_test_r182_1"
os.environ["PEECHA_DB_USER"] = "peecha"
os.environ["PEECHA_DB_PASSWORD"] = "peecha"
os.environ["PEECHA_DB_HOST"] = "localhost"
os.environ["PEECHA_DB_PORT"] = "5432"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))

FAIL = False
def check(cond, msg):
    global FAIL
    if not cond:
        FAIL = True
        print("FAIL:", msg)
    else:
        print("OK:", msg)

from PySide6.QtWidgets import QApplication, QMessageBox
app_qt = QApplication.instance() or QApplication([])
QMessageBox.warning = staticmethod(lambda *a, **k: None)
QMessageBox.information = staticmethod(lambda *a, **k: None)
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)

from peecha.db.schema_bootstrap import apply_pending_schema_files
from peecha.db.base import get_engine, new_session
apply_pending_schema_files(get_engine())
from peecha.services.bootstrap import bootstrap_system
from peecha import session as sess
user = bootstrap_system("admin", "مدیر سیستم", "secret123", "شرکت آزمایشی")
sess.current_user = user
from sqlalchemy import select
from peecha.db.models.security import UserCompany
from peecha.db.models.core import Company
with new_session() as s:
    uc = s.scalar(select(UserCompany).where(UserCompany.user_id == user.user_id))
    company = s.get(Company, uc.company_id)
company_id = company.company_id
sess.current_company = company

from peecha.services import fiscal_years as fiscal_years_service
fiscal_years_service.create_fiscal_year_for_date(company_id, 1, 1, datetime.date.today())

from peecha.services import chart_of_accounts as coa_service
from peecha.services import inventory_catalog as catalog_service
from peecha.services import inventory_locations as locations_service
from peecha.services import commercial_pricing as pricing_service
from peecha.services import commercial_settings as csettings_service
from peecha.services import commercial_documents as documents_service
from peecha.services import commercial_settlements as settlements_service
from peecha.services import treasury as treasury_service
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import field_sales as field_sales_service
from peecha.services import users as users_service
from peecha.db.models.commercial import CreditHold
from peecha.services import commercial_credit as credit_service

lang_id = company.default_language_id
g1 = coa_service.create_account(company_id, "1", "دارایی‌ها", "DEBIT", "ASSET", "PERMANENT", False, lang_id)
k1 = coa_service.create_account(company_id, "11", "صندوق", "DEBIT", "ASSET", "PERMANENT", False, lang_id, parent_account_id=g1.account_id)
cash_gl = coa_service.create_account(company_id, "101", "صندوقِ اصلی", "DEBIT", "ASSET", "PERMANENT", True, lang_id, parent_account_id=k1.account_id)
k2 = coa_service.create_account(company_id, "13", "حساب‌هایِ دریافتنی", "DEBIT", "ASSET", "PERMANENT", False, lang_id, parent_account_id=g1.account_id)
ar_gl = coa_service.create_account(company_id, "1304", "حساب‌هایِ دریافتنیِ مشتریان", "DEBIT", "ASSET", "PERMANENT", True, lang_id, parent_account_id=k2.account_id)
k3 = coa_service.create_account(company_id, "11b", "موجودیِ انبار", "DEBIT", "ASSET", "PERMANENT", False, lang_id, parent_account_id=g1.account_id)
inv_asset_gl = coa_service.create_account(company_id, "102", "موجودیِ کالا", "DEBIT", "ASSET", "PERMANENT", True, lang_id, parent_account_id=k3.account_id)
g2 = coa_service.create_account(company_id, "4", "درآمدها", "CREDIT", "REVENUE", "TEMPORARY", False, lang_id)
k4 = coa_service.create_account(company_id, "41", "درآمدِ عملیاتی", "CREDIT", "REVENUE", "TEMPORARY", False, lang_id, parent_account_id=g2.account_id)
revenue_gl = coa_service.create_account(company_id, "411", "درآمدِ فروش", "CREDIT", "REVENUE", "TEMPORARY", True, lang_id, parent_account_id=k4.account_id)
g3 = coa_service.create_account(company_id, "5", "هزینه‌ها", "DEBIT", "EXPENSE", "TEMPORARY", False, lang_id)
k5 = coa_service.create_account(company_id, "51", "بهایِ تمام‌شده", "DEBIT", "EXPENSE", "TEMPORARY", False, lang_id, parent_account_id=g3.account_id)
cogs_gl = coa_service.create_account(company_id, "511", "بهایِ تمام‌شده", "DEBIT", "EXPENSE", "TEMPORARY", True, lang_id, parent_account_id=k5.account_id)

from peecha.services import inventory_engine as engine_service
engine_service.set_account_mapping(company_id, "INVENTORY_ASSET", inv_asset_gl.account_id)
engine_service.set_account_mapping(company_id, "CUSTOMER_RECEIVABLE", ar_gl.account_id)
engine_service.set_account_mapping(company_id, "COGS", cogs_gl.account_id)
csettings_service.set_account_mapping(company_id, "SALES_REVENUE", revenue_gl.account_id)

customer_group_id = dimensions_service.get_person_group_id(company_id, dimensions_service.CUSTOMER_GROUP_CODE)
treasury_service.create_counterparty_mapping(company_id, "RECEIPT", ar_gl.account_id, person_group_id=customer_group_id)
treasury_service.set_account_mapping(company_id, "RECEIPT_CASH", cash_gl.account_id)

uom_id = catalog_service.create_uom(company_id, "PCS", "عدد", "COUNT")
item_id = catalog_service.create_item(
    company_id, "9101", "کالایِ عادی",
    catalog_service.ItemFields(item_kind_code="GOOD", base_uom_id=uom_id, is_sellable=True),
)
warehouse_id = locations_service.create_warehouse(
    company_id, "WH-1", "انبارِ آزمایشی", locations_service.WarehouseFields(allow_negative_stock=True),
)
channel_code = pricing_service.create_channel(company_id, "VAN-1", "پخشِ گرمِ آزمایشی", "VAN_SALES")
customer_id = dimensions_service.create_customer(company_id, "C-1", "فروشگاهِ محمدی")
customer2_id = dimensions_service.create_customer(company_id, "C-2", "فروشگاهِ کریمی")

visitor_user = users_service.create_user(
    "visitor1", "ویزیتورِ یک", "secret123", None, company.default_language_id, False, [company_id], company_id,
)
visitor_user_id = visitor_user.user_id

today = datetime.date.today()
weekday = today.weekday()
field_sales_service.create_visit_plan(company_id, customer_id, weekday, 1, visitor_user_id)
field_sales_service.create_visit_plan(company_id, customer2_id, weekday, 2, visitor_user_id)

# ==========================================================================
# ۱: یک ویزیتِ تکمیل‌شده‌یِ امروز.
# ==========================================================================
visit_id = field_sales_service.start_visit(company_id, customer_id, visitor_user_id)
field_sales_service.complete_visit(visit_id, company_id, "بازدیدِ خوب بود")

# ==========================================================================
# ۲: یک فاکتورِ پخشِ گرمِ امروز به‌نامِ همین ویزیتور.
# ==========================================================================
invoice_id = documents_service.create_document(
    company_id, visitor_user_id, "SALES_INVOICE", today,
    documents_service.DocumentHeaderFields(
        counterparty_detail_account_id=customer_id, currency_id=company.base_currency_id,
        warehouse_id=warehouse_id, channel_code=channel_code,
    ),
)
documents_service.add_line(
    invoice_id, company_id, item_id=item_id, uom_id=uom_id, quantity=decimal.Decimal(3),
    quantity_base=decimal.Decimal(3), unit_price=decimal.Decimal(100000),
)
documents_service.confirm_document(invoice_id, company_id, visitor_user_id)
settlements_service.auto_approve_full_cash_settlement_plan(invoice_id, company_id, visitor_user_id)
documents_service.post_document(invoice_id, company_id, visitor_user_id)

# ==========================================================================
# ۳: یک وصولِ نقدیِ امروز.
# ==========================================================================
treasury_service.create_treasury_voucher(
    company_id, visitor_user_id, "RECEIPT", ar_gl.account_id, {dimensions_service.get_person_dimension_type_id(company_id): customer2_id},
    today, "وصولِ نقدی", [treasury_service.MethodLine(method="CASH", amount=decimal.Decimal(250000))],
)

from fastapi.testclient import TestClient
from peecha_api.main import app
client = TestClient(app)

resp = client.post("/auth/login", json={"username": "visitor1", "password": "secret123"})
check(resp.status_code == 200, f"ورودِ ویزیتور موفق بود (status={resp.status_code})")
token = resp.json()["access_token"]

resp = client.get("/dashboard/today", headers={"Authorization": f"Bearer {token}"})
check(resp.status_code == 200, f"خلاصه‌یِ امروز موفق بود (status={resp.status_code}, body={resp.text})")
body = resp.json()
check(body["visit_count"] == 1, f"تعدادِ ویزیتِ امروز درست است (got {body['visit_count']})")
check(body["visit_completed_count"] == 1, "تعدادِ ویزیتِ تکمیل‌شده درست است")
check(body["order_count"] == 1, f"تعدادِ سفارش/فاکتورِ امروز درست است (got {body['order_count']})")
check(decimal.Decimal(body["sales_amount"]) == decimal.Decimal(300000), f"مبلغِ فروشِ امروز درست است (got {body['sales_amount']})")
check(decimal.Decimal(body["collection_amount"]) == decimal.Decimal(250000), f"مبلغِ وصولِ امروز درست است (got {body['collection_amount']})")
check(
    body["next_visit"] is not None and body["next_visit"]["customer_detail_account_id"] == customer2_id,
    f"ویزیتِ بعدی همان مشتریِ ویزیت‌نشده است (got {body['next_visit']})",
)
route_by_customer = {r["customer_detail_account_id"]: r["state"] for r in body["today_route"]}
check(route_by_customer.get(customer_id) == "DONE", f"وضعیتِ مشتریِ تکمیل‌شده در برنامه‌یِ امروز DONE است (got {route_by_customer})")
check(route_by_customer.get(customer2_id) == "UPCOMING", f"وضعیتِ مشتریِ ویزیت‌نشده UPCOMING است (got {route_by_customer})")

print("RESULT:", "ALL PASS" if not FAIL else "SOME FAILED")
sys.exit(1 if FAIL else 0)
