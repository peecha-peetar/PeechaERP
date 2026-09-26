import os, sys, datetime
os.environ["PEECHA_DB_NAME"] = "peecha_test_r200_1"
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
from peecha.services import detail_dimensions as dimensions_service

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

warehouse_id = locations_service.create_warehouse(
    company_id, "WH-1", "انبارِ اصلی", locations_service.WarehouseFields(allow_negative_stock=True, is_default=True),
)
channel_code = pricing_service.create_channel(company_id, "VAN-1", "پخشِ گرمِ آزمایشی", "VAN_SALES")
customer = partners_service.create_customer(company_id, "C-1", "مشتریِ آزمایشی", fast_track=True)

# طبقِ گزارشِ واقعیِ کاربر: «برای حساب ۱-۱۳-۱۳۰۴ انتخاب مرکز هزینه و
# پروژه الزامی است» -- یعنی حسابِ نقش‌محورِ CUSTOMER_RECEIVABLE این
# شرکت، مرکزِ هزینه را الزامی کرده. این‌جا همان حالت را می‌سازیم.
cost_center_type_id = dimensions_service.get_specialized_dimension_type_id(company_id, dimensions_service.COST_CENTER_CODE)
cost_center = dimensions_service.create_detail_account(company_id, cost_center_type_id, "CC-1", "مرکزِ هزینهٔ فروشِ سیار")
dimensions_service.set_account_dimension_types(ar_gl.account_id, company_id, [cost_center_type_id])

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
    "warehouse_id": warehouse_id,
    "channel_code": channel_code,
    # طبقِ جریانِ واقعیِ OrderScreen.tsx: فاکتورِ پخشِ گرم همیشه
    # post_immediately=True است (کالا همان‌لحظه تحویل داده شده) -- فقط
    # با پستِ واقعیِ سند است که journal_entries.create_journal_entry
    # صدا زده می‌شود و بُعدهایِ الزامی چک می‌شوند.
    "post_immediately": True,
    "lines": [{"item_id": item_id, "uom_id": uom_id, "quantity": "1", "unit_price": "10000"}],
}

# ۱. بدونِ ارسالِ cost_center_detail_account_id (رفتارِ موبایلِ قبل از
# این رفع): باید همان خطایِ واقعیِ کاربر را بگیریم -- نه یک ۵۰۰ِ خام.
resp = client.post("/orders", headers=auth(admin_token), json=base_order)
check(resp.status_code == 400, f"بدونِ مرکزِ هزینه -> ۴۰۰ (status={resp.status_code}, body={resp.text})")
check("مرکز هزینه" in resp.text or "مرکزِ هزینه" in resp.text, f"پیامِ خطا دربارهٔ مرکزِ هزینه است (body={resp.text})")

# ۲. تنظیمِ پیش‌فرضِ کانال (شبیه‌سازیِ اقدامِ مدیر در تبِ کانال‌هایِ
# دسکتاپ) -- باید در GET /pricing/channels هم منعکس شود.
pricing_service.set_channel_mobile_defaults(company_id, channel_code, cost_center.detail_account_id, None)
resp = client.get("/pricing/channels", headers=auth(admin_token))
check(resp.status_code == 200, f"GET /pricing/channels موفق بود (status={resp.status_code})")
channels = resp.json()
van_channel = next(c for c in channels if c["channel_code"] == channel_code)
check(
    van_channel["default_cost_center_detail_account_id"] == cost_center.detail_account_id,
    f"پیش‌فرضِ مرکزِ هزینه در پاسخ برگشت (got {van_channel})",
)

# ۳. حالا موبایل (طبقِ کدِ جدیدِ App.tsx) همین مقدار را در سفارش
# می‌فرستد -- باید موفق شود.
order_with_default = dict(base_order, cost_center_detail_account_id=cost_center.detail_account_id)
resp = client.post("/orders", headers=auth(admin_token), json=order_with_default)
check(resp.status_code == 200, f"سفارش با مرکزِ هزینهٔ پیش‌فرض موفق بود (status={resp.status_code}, body={resp.text})")

print("RESULT:", "ALL PASS" if not FAIL else "SOME FAILED")
sys.exit(1 if FAIL else 0)
