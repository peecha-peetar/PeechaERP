import os, sys, datetime
os.environ["PEECHA_DB_NAME"] = "peecha_test_r199_1"
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
from peecha.services import commercial_partners as partners_service
from peecha.services import inventory_engine as engine_service

lang_id = company.default_language_id
g1 = coa_service.create_account(company_id, "1", "دارایی‌ها", "DEBIT", "ASSET", "PERMANENT", False, lang_id)
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

engine_service.set_account_mapping(company_id, "INVENTORY_ASSET", inv_asset_gl.account_id)
engine_service.set_account_mapping(company_id, "CUSTOMER_RECEIVABLE", ar_gl.account_id)
engine_service.set_account_mapping(company_id, "COGS", cogs_gl.account_id)
csettings_service.set_account_mapping(company_id, "SALES_REVENUE", revenue_gl.account_id)

uom_id = catalog_service.create_uom(company_id, "PCS", "عدد", "COUNT")
item_id = catalog_service.create_item(
    company_id, "9101", "کالایِ عادی",
    catalog_service.ItemFields(item_kind_code="GOOD", base_uom_id=uom_id, is_sellable=True),
)

real_warehouse_id = locations_service.create_warehouse(
    company_id, "WH-1", "انبارِ اصلی", locations_service.WarehouseFields(allow_negative_stock=True, is_default=True),
)
real_channel_code = pricing_service.create_channel(company_id, "VAN-1", "پخشِ گرمِ آزمایشی", "VAN_SALES")
customer = partners_service.create_customer(company_id, "C-1", "مشتریِ آزمایشی", fast_track=True)

from fastapi.testclient import TestClient
from peecha_api.main import app
client = TestClient(app)

resp = client.post("/auth/login", json={"username": "admin", "password": "secret123"})
admin_token = resp.json()["access_token"]


def auth(t):
    return {"Authorization": f"Bearer {t}"}


base_order = {
    "document_type_code": "SALES_INVOICE",
    "counterparty_detail_account_id": customer,
    "currency_id": company.base_currency_id,
    "warehouse_id": real_warehouse_id,
    "channel_code": real_channel_code,
    "post_immediately": False,
    "lines": [{"item_id": item_id, "uom_id": uom_id, "quantity": "1", "unit_price": "10000"}],
}

# طبقِ باگِ واقعیِ اصلیِ کشف‌شده رویِ گوشیِ فیزیکیِ کاربر: قبلاً موبایل
# warehouse_id=1ِ هاردکد می‌فرستاد که در comm.warehouses/inv.warehouses
# این شرکت اصلاً وجود نداشت -- سرور یک ForeignKeyViolationِ خامِ
# SQLAlchemy پرتاب می‌کرد (۵۰۰ِ بی‌پیام)، که در SyncEngineِ موبایل چون
# ۵۰۰ (نه ۴xx) بود، کلِ صفِ آفلاین را برایِ همیشه قفل می‌کرد. این‌جا
# تایید می‌کنیم که چنین درخواستی حالا یک ۴۰۰ِ تمیز با پیامِ فارسی
# می‌گیرد -- که SyncEngine می‌تواند آن را از صف حذف کند.
bad_warehouse = dict(base_order, warehouse_id=999999)
resp = client.post("/orders", headers=auth(admin_token), json=bad_warehouse)
check(resp.status_code == 400, f"warehouse_idِ نامعتبر -> ۴۰۰ِ تمیز (status={resp.status_code}, body={resp.text})")

bad_channel = dict(base_order, channel_code="NONEXISTENT")
resp = client.post("/orders", headers=auth(admin_token), json=bad_channel)
check(resp.status_code == 400, f"channel_codeِ نامعتبر -> ۴۰۰ِ تمیز (status={resp.status_code}, body={resp.text})")

bad_currency = dict(base_order, currency_id=999999)
resp = client.post("/orders", headers=auth(admin_token), json=bad_currency)
check(resp.status_code == 400, f"currency_idِ نامعتبر -> ۴۰۰ِ تمیز (status={resp.status_code}, body={resp.text})")

# طبقِ سلامتِ رگرسیون: سفارشِ کاملاً معتبر هنوز باید موفق شود (این چک
# نباید سفارش‌هایِ درست را هم رد کند).
resp = client.post("/orders", headers=auth(admin_token), json=base_order)
check(resp.status_code == 200, f"سفارشِ معتبر هنوز موفق است (status={resp.status_code}, body={resp.text})")

print("RESULT:", "ALL PASS" if not FAIL else "SOME FAILED")
sys.exit(1 if FAIL else 0)
