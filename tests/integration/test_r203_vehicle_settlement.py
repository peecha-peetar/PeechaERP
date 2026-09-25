import os, sys, datetime, decimal
os.environ["PEECHA_DB_NAME"] = "peecha_test_r203_1"
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
from peecha.services import users as users_service
from peecha.services import vehicle_team as vehicle_team_service
from peecha.services import vehicle_loading as vehicle_loading_service
from peecha.services import vehicle_settlement as settlement_service
from peecha.services import commercial_documents as documents_service

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

central_warehouse_id = locations_service.create_warehouse(
    company_id, "WH-MAIN", "انبارِ مرکزی", locations_service.WarehouseFields(allow_negative_stock=True, is_default=True),
)
vehicle_warehouse_id = locations_service.create_warehouse(
    company_id, "VEH-1", "خودرویِ ۱", locations_service.WarehouseFields(warehouse_type_code="VEHICLE", allow_negative_stock=True),
)
van_channel_code = pricing_service.create_channel(company_id, "VAN-1", "پخشِ گرمِ آزمایشی", "VAN_SALES")
customer = partners_service.create_customer(company_id, "C-1", "مشتریِ آزمایشی", fast_track=True)
uom_id = catalog_service.create_uom(company_id, "PCS", "عدد", "COUNT")
item_id = catalog_service.create_item(
    company_id, "9101", "کالایِ عادی", catalog_service.ItemFields(item_kind_code="GOOD", base_uom_id=uom_id, is_sellable=True),
)
visitor = users_service.create_user("visitor_van", "ویزیتور", "secret123", None, lang_id, False, [company_id], company_id)
driver = users_service.create_user("driver_van", "راننده", "secret123", None, lang_id, False, [company_id], company_id)
users_service.set_mobile_channel_type(visitor.user_id, company_id, "VAN_SALES")
vehicle_team_service.set_team_member(vehicle_warehouse_id, company_id, "VISITOR", visitor.user_id)
vehicle_team_service.set_team_member(vehicle_warehouse_id, company_id, "DRIVER", driver.user_id)
vehicle_team_service.set_team_member(vehicle_warehouse_id, company_id, "DISTRIBUTOR", visitor.user_id)

# طبقِ درخواستِ صریحِ کاربر: نقشِ مسئولِ تسویه را روی DISTRIBUTOR
# می‌گذاریم (نه صرفاً VISITOR) تا نشان دهیم انتخابی است.
settlement_service.set_settlement_role(company_id, "DISTRIBUTOR")
check(settlement_service.get_settlement_role(company_id) == "DISTRIBUTOR", "نقشِ مسئولِ تسویه ذخیره شد")

today = datetime.date.today()
loading_id = vehicle_loading_service.create_vehicle_loading(
    company_id, user.user_id, vehicle_warehouse_id, central_warehouse_id, today,
    [vehicle_loading_service.VehicleLoadingLineFields(item_id=item_id, uom_id=uom_id, planned_quantity=decimal.Decimal(10))],
)
vehicle_loading_service.confirm_vehicle_loading(loading_id, company_id, driver.user_id)

order = {
    "document_type_code": "SALES_INVOICE",
    "counterparty_detail_account_id": customer,
    "currency_id": company.base_currency_id,
    "warehouse_id": vehicle_warehouse_id,
    "channel_code": van_channel_code,
    "post_immediately": True,
    "lines": [{"item_id": item_id, "uom_id": uom_id, "quantity": "3", "unit_price": "10000"}],
}

from fastapi.testclient import TestClient
from peecha_api.main import app
client = TestClient(app)


def login(username):
    resp = client.post("/auth/login", json={"username": username, "password": "secret123"})
    return resp.json()["access_token"]


def auth(t):
    return {"Authorization": f"Bearer {t}"}


admin_token = login("admin")
resp = client.post("/orders", headers=auth(admin_token), json=order)
check(resp.status_code == 200, f"سفارشِ ۳ عددی از انبارِ خودرو ثبت شد (status={resp.status_code}, body={resp.text})")

# طبقِ گزارشِ واقعیِ کاربر: مسئولِ تسویه، موزع (همان ویزیتور در این
# تست) است، نه لزوماً ویزیتوری که سفارش می‌گیرد.
distributor_token = login("visitor_van")
resp = client.get("/auth/me", headers=auth(distributor_token))
check(
    resp.json()["settlement_vehicle_warehouse_id"] == vehicle_warehouse_id,
    f"/auth/me خودروی درست را برایِ مسئولِ تسویه برمی‌گرداند (body={resp.text})",
)

resp = client.get("/vehicle-settlement/today-summary", headers=auth(distributor_token))
check(resp.status_code == 200, f"GET today-summary موفق بود (status={resp.status_code}, body={resp.text})")
summary = resp.json()
check(decimal.Decimal(summary["lines"][0]["loaded_quantity"]) == decimal.Decimal(10), f"بارگیری‌شده=۱۰ (got {summary['lines']})")
check(decimal.Decimal(summary["lines"][0]["sold_quantity"]) == decimal.Decimal(3), f"فروخته‌شده=۳ (got {summary['lines']})")

# راننده به‌جایِ ۷ (۱۰-۳)، فقط ۵ برمی‌گرداند -- یعنی ۲ عدد کسری.
resp = client.post(
    "/vehicle-settlement", headers=auth(distributor_token),
    json={"declared_cash_amount": "30000", "lines": [{"item_id": item_id, "uom_id": uom_id, "returned_quantity": "5"}]},
)
check(resp.status_code == 200, f"ثبتِ تسویه موفق بود (status={resp.status_code}, body={resp.text})")
vehicle_settlement_id = resp.json()["vehicle_settlement_id"]

row = settlement_service.get_settlement(vehicle_settlement_id, company_id)
check(row.status_code == "SUBMITTED", f"وضعیتِ اولیه SUBMITTED است (got {row.status_code})")
check(row.lines[0].shortage_or_surplus == decimal.Decimal(2), f"کسریِ محاسبه‌شده = ۲ (got {row.lines[0].shortage_or_surplus})")

# طبقِ درخواستِ صریح: تاییدِ انبار قبل از تاییدِ حسابداری الزامی است.
try:
    settlement_service.approve_accounting(vehicle_settlement_id, company_id, user.user_id)
    check(False, "تاییدِ حسابداری قبل از تاییدِ انبار باید رد شود")
except ValueError:
    check(True, "تاییدِ حسابداری قبل از تاییدِ انبار رد شد (گیتِ دومرحله‌ای کار می‌کند)")

settlement_service.approve_warehouse(vehicle_settlement_id, company_id, user.user_id)
row = settlement_service.get_settlement(vehicle_settlement_id, company_id)
check(row.status_code == "WAREHOUSE_APPROVED", f"بعدِ تاییدِ انبار (got {row.status_code})")

balance_before = engine_service.list_balances(company_id, warehouse_id=central_warehouse_id)
central_qty_before = next((b.quantity_available for b in balance_before if b.item_id == item_id), decimal.Decimal(0))

return_doc_id = settlement_service.approve_accounting(vehicle_settlement_id, company_id, user.user_id)
check(return_doc_id is not None, f"تاییدِ حسابداری سندِ برگشت ساخت (got {return_doc_id})")

row = settlement_service.get_settlement(vehicle_settlement_id, company_id)
check(row.status_code == "ACCOUNTING_APPROVED", f"وضعیتِ نهایی ACCOUNTING_APPROVED است (got {row.status_code})")

balance_after = engine_service.list_balances(company_id, warehouse_id=central_warehouse_id)
central_qty_after = next((b.quantity_available for b in balance_after if b.item_id == item_id), decimal.Decimal(0))
check(
    central_qty_after == central_qty_before + decimal.Decimal(5),
    f"۵ عددِ برگشتی واقعاً به انبارِ مرکزی اضافه شد (before={central_qty_before}, after={central_qty_after})",
)

print("RESULT:", "ALL PASS" if not FAIL else "SOME FAILED")
sys.exit(1 if FAIL else 0)
