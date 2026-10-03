import os, sys, decimal, datetime
os.environ["PEECHA_DB_NAME"] = "peecha_test_r183_1"
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
from peecha.services import commercial_partners as partners_service
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import users as users_service

lang_id = company.default_language_id
g1 = coa_service.create_account(company_id, "1", "دارایی‌ها", "DEBIT", "ASSET", "PERMANENT", False, lang_id)
k1 = coa_service.create_account(company_id, "11", "موجودیِ انبار", "DEBIT", "ASSET", "PERMANENT", False, lang_id, parent_account_id=g1.account_id)
inv_asset_gl = coa_service.create_account(company_id, "101", "موجودیِ کالا", "DEBIT", "ASSET", "PERMANENT", True, lang_id, parent_account_id=k1.account_id)
k2 = coa_service.create_account(company_id, "13", "حساب‌هایِ دریافتنی", "DEBIT", "ASSET", "PERMANENT", False, lang_id, parent_account_id=g1.account_id)
ar_gl = coa_service.create_account(company_id, "1304", "حساب‌هایِ دریافتنیِ مشتریان", "DEBIT", "ASSET", "PERMANENT", True, lang_id, parent_account_id=k2.account_id)
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

uom_id = catalog_service.create_uom(company_id, "PCS", "عدد", "COUNT")
item_id = catalog_service.create_item(
    company_id, "9101", "کالایِ پرفروش",
    catalog_service.ItemFields(item_kind_code="GOOD", base_uom_id=uom_id, is_sellable=True),
)
warehouse_id = locations_service.create_warehouse(
    company_id, "WH-1", "انبارِ آزمایشی", locations_service.WarehouseFields(allow_negative_stock=True),
)
channel_code = pricing_service.create_channel(company_id, "VAN-1", "پخشِ گرمِ آزمایشی", "VAN_SALES")
customer_id = partners_service.create_customer(
    company_id, "C-1", "فروشگاهِ محمدی",
    partners_service.CustomerProfileFields(credit_limit_amount=decimal.Decimal(5000000), payment_term_days=15),
    fast_track=True, phone="09121112233", address="تهران، خیابانِ آزادی",
)

visitor_user = users_service.create_user(
    "visitor1", "ویزیتورِ یک", "secret123", None, company.default_language_id, False, [company_id], company_id,
)

invoice_id = documents_service.create_document(
    company_id, visitor_user.user_id, "SALES_INVOICE", datetime.date.today(),
    documents_service.DocumentHeaderFields(
        counterparty_detail_account_id=customer_id, currency_id=company.base_currency_id,
        warehouse_id=warehouse_id, channel_code=channel_code,
    ),
)
documents_service.add_line(
    invoice_id, company_id, item_id=item_id, uom_id=uom_id, quantity=decimal.Decimal(4),
    quantity_base=decimal.Decimal(4), unit_price=decimal.Decimal(200000),
)
documents_service.confirm_document(invoice_id, company_id, visitor_user.user_id)
settlements_service.auto_approve_full_cash_settlement_plan(invoice_id, company_id, visitor_user.user_id)
documents_service.post_document(invoice_id, company_id, visitor_user.user_id)

from fastapi.testclient import TestClient
from peecha_api.main import app
client = TestClient(app)

resp = client.post("/auth/login", json={"username": "visitor1", "password": "secret123"})
token = resp.json()["access_token"]
auth = {"Authorization": f"Bearer {token}"}

resp = client.get("/customers", params={"q": "محمدی"}, headers=auth)
check(resp.status_code == 200 and len(resp.json()) == 1, f"جستجویِ مشتری با نام کار کرد (status={resp.status_code}, body={resp.text})")

resp = client.get(f"/customers/{customer_id}", headers=auth)
check(resp.status_code == 200, f"جزئیاتِ مشتری موفق بود (status={resp.status_code}, body={resp.text})")
body = resp.json()
check(body["name"] == "فروشگاهِ محمدی", "نامِ مشتری درست است")
check(body["phone"] == "09121112233", "تلفنِ مشتری درست است")
check(body["credit_limit_amount"] == "5000000.00", f"سقفِ اعتبار درست است (got {body['credit_limit_amount']})")
check(body["balance_nature"] == "بدهکار" and decimal.Decimal(body["balance_amount"]) == decimal.Decimal(800000), f"ماندهٔ حساب درست است (got {body['balance_amount']}/{body['balance_nature']})")
check(body["last_purchase_date"] == datetime.date.today().isoformat(), "تاریخِ آخرین خرید درست است")
check(len(body["top_products"]) == 1 and body["top_products"][0]["item_id"] == item_id, f"پرفروش‌ترین کالا درست است (got {body['top_products']})")
check(len(body["recent_documents"]) == 1 and body["recent_documents"][0]["document_id"] == invoice_id, "تاریخچهٔ سفارش/فاکتور درست است")

resp = client.get("/customers/999999", headers=auth)
check(resp.status_code == 404, f"مشتریِ نامعتبر ۴۰۴ برمی‌گرداند (status={resp.status_code})")

print("RESULT:", "ALL PASS" if not FAIL else "SOME FAILED")
sys.exit(1 if FAIL else 0)
