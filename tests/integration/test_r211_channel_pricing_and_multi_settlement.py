import os, sys, datetime, decimal
os.environ["PEECHA_DB_NAME"] = "peecha_test_r211_1"
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

lang_id = company.default_language_id
g1 = coa_service.create_account(company_id, "1", "دارایی‌ها", "DEBIT", "ASSET", "PERMANENT", False, lang_id)
k2 = coa_service.create_account(company_id, "13", "حساب‌هایِ دریافتنی", "DEBIT", "ASSET", "PERMANENT", False, lang_id, parent_account_id=g1.account_id)
ar_gl = coa_service.create_account(company_id, "1304", "حساب‌هایِ دریافتنیِ مشتریان", "DEBIT", "ASSET", "PERMANENT", True, lang_id, parent_account_id=k2.account_id)
k3 = coa_service.create_account(company_id, "11b", "موجودیِ انبار", "DEBIT", "ASSET", "PERMANENT", False, lang_id, parent_account_id=g1.account_id)
inv_asset_gl = coa_service.create_account(company_id, "102", "موجودیِ کالا", "DEBIT", "ASSET", "PERMANENT", True, lang_id, parent_account_id=k3.account_id)
g2 = coa_service.create_account(company_id, "4", "درآمدها", "CREDIT", "REVENUE", "TEMPORARY", False, lang_id)
k4 = coa_service.create_account(company_id, "41", "درآمدِ عملیاتی", "CREDIT", "REVENUE", "TEMPORARY", False, lang_id, parent_account_id=g2.account_id)
revenue_gl = coa_service.create_account(company_id, "411", "درآمدِ فروش", "CREDIT", "REVENUE", "TEMPORARY", True, lang_id, parent_account_id=k4.account_id)
discount_gl = coa_service.create_account(company_id, "412", "تخفیفِ فروش", "DEBIT", "REVENUE", "TEMPORARY", True, lang_id, parent_account_id=k4.account_id)
g3 = coa_service.create_account(company_id, "5", "هزینه‌ها", "DEBIT", "EXPENSE", "TEMPORARY", False, lang_id)
k5 = coa_service.create_account(company_id, "51", "بهایِ تمام‌شده", "DEBIT", "EXPENSE", "TEMPORARY", False, lang_id, parent_account_id=g3.account_id)
cogs_gl = coa_service.create_account(company_id, "511", "بهایِ تمام‌شده", "DEBIT", "EXPENSE", "TEMPORARY", True, lang_id, parent_account_id=k5.account_id)

engine_service.set_account_mapping(company_id, "INVENTORY_ASSET", inv_asset_gl.account_id)
engine_service.set_account_mapping(company_id, "CUSTOMER_RECEIVABLE", ar_gl.account_id)
engine_service.set_account_mapping(company_id, "COGS", cogs_gl.account_id)
csettings_service.set_account_mapping(company_id, "SALES_REVENUE", revenue_gl.account_id)
csettings_service.set_account_mapping(company_id, "SALES_DISCOUNT", discount_gl.account_id)

central_warehouse_id = locations_service.create_warehouse(
    company_id, "WH-MAIN", "انبارِ مرکزی", locations_service.WarehouseFields(allow_negative_stock=True, is_default=True),
)
vehicle_warehouse_id = locations_service.create_warehouse(
    company_id, "VEH-1", "خودرویِ ۱", locations_service.WarehouseFields(warehouse_type_code="VEHICLE", allow_negative_stock=True),
)
van_channel_code = pricing_service.create_channel(company_id, "VAN-1", "پخشِ گرمِ آزمایشی", "VAN_SALES")
pre_channel_code = pricing_service.create_channel(company_id, "PRE-1", "پخشِ سردِ آزمایشی", "PRE_SALES")
uom_id = catalog_service.create_uom(company_id, "PCS", "عدد", "COUNT")
item_id = catalog_service.create_item(
    company_id, "9101", "کالایِ عادی", catalog_service.ItemFields(item_kind_code="GOOD", base_uom_id=uom_id, is_sellable=True),
)

from fastapi.testclient import TestClient
from peecha_api.main import app
client = TestClient(app)


def login(username):
    resp = client.post("/auth/login", json={"username": username, "password": "secret123"})
    return resp.json()["access_token"]


def auth(t):
    return {"Authorization": f"Bearer {t}"}


admin_token = login("admin")

# ---------- ۱. لیست‌قیمت/تخفیفِ پیش‌فرضِ یک کانال -- طبقِ درخواستِ صریحِ کاربر ----------
pl_customer = pricing_service.create_price_list(company_id, "PL-CUST", "فهرستِ مشتری", "SALES", company.base_currency_id, datetime.date.today())
pl_van = pricing_service.create_price_list(company_id, "PL-VAN", "فهرستِ پخشِ گرم", "SALES", company.base_currency_id, datetime.date.today())
pricing_service.set_price_list_item(pl_customer, item_id, uom_id, decimal.Decimal("10000"))
pricing_service.set_price_list_item(pl_van, item_id, uom_id, decimal.Decimal("9000"))

customer = partners_service.create_customer(
    company_id, "C-1", "مشتریِ آزمایشی",
    fields=partners_service.CustomerProfileFields(default_price_list_id=pl_customer), fast_track=True,
)

rule_generic = pricing_service.create_discount_rule(company_id, "D-ALL", "تخفیفِ عمومی", "PERCENT", "ALL", discount_value=decimal.Decimal("5"))
rule_van = pricing_service.create_discount_rule(company_id, "D-VAN", "تخفیفِ ویژهٔ پخشِ گرم", "PERCENT", "ALL", discount_value=decimal.Decimal("20"))

# بدونِ تنظیمِ چیزی رویِ کانال -- باید هنوز رفتارِ قبلی (پیش‌فرضِ خودِ مشتری + بهترین قاعدهٔ عمومی) باشد.
r = client.get("/pricing/resolve", headers=auth(admin_token), params={
    "counterparty_detail_account_id": customer, "item_id": item_id, "uom_id": uom_id,
    "quantity": "1", "document_type_code": "SALES_INVOICE", "channel_code": pre_channel_code,
})
check(r.status_code == 200, f"resolve بدونِ تنظیمِ کانال ۲۰۰ (body={r.text[:200]})")
resolved = r.json()
check(decimal.Decimal(resolved["unit_price"]) == decimal.Decimal("10000"), f"بدونِ تنظیمِ کانال: قیمتِ پیش‌فرضِ مشتری (got {resolved})")
check(decimal.Decimal(resolved["discount_amount"]) == decimal.Decimal("500"), f"بدونِ تنظیمِ کانال: تخفیفِ ۵٪ِ عمومی (got {resolved})")

pricing_service.set_channel_pricing_defaults(company_id, van_channel_code, pl_van, rule_van)
r = client.get("/pricing/resolve", headers=auth(admin_token), params={
    "counterparty_detail_account_id": customer, "item_id": item_id, "uom_id": uom_id,
    "quantity": "1", "document_type_code": "SALES_INVOICE", "channel_code": van_channel_code,
})
check(r.status_code == 200, f"resolve با کانالِ گرم ۲۰۰ (body={r.text[:200]})")
resolved = r.json()
check(decimal.Decimal(resolved["unit_price"]) == decimal.Decimal("9000"), f"با تنظیمِ کانالِ گرم: قیمتِ فهرستِ کانال (got {resolved})")
check(decimal.Decimal(resolved["discount_amount"]) == decimal.Decimal("1800"), f"با تنظیمِ کانالِ گرم: تخفیفِ ۲۰٪ِ اختصاصی (got {resolved})")

# کانالِ سرد هنوز چیزی تنظیم نکرده -- باید دست‌نخورده بماند.
r = client.get("/pricing/resolve", headers=auth(admin_token), params={
    "counterparty_detail_account_id": customer, "item_id": item_id, "uom_id": uom_id,
    "quantity": "1", "document_type_code": "SALES_INVOICE", "channel_code": pre_channel_code,
})
resolved = r.json()
check(decimal.Decimal(resolved["unit_price"]) == decimal.Decimal("10000"), f"کانالِ سرد دست‌نخورده: قیمتِ مشتری (got {resolved})")
check(decimal.Decimal(resolved["discount_amount"]) == decimal.Decimal("500"), f"کانالِ سرد دست‌نخورده: تخفیفِ عمومی (got {resolved})")

# ---------- ۲. چند بار پخشِ گرم و تسویه در یک روز -- طبقِ درخواستِ صریحِ کاربر ----------
visitor = users_service.create_user("visitor_van", "ویزیتور", "secret123", None, lang_id, False, [company_id], company_id)
driver = users_service.create_user("driver_van", "راننده", "secret123", None, lang_id, False, [company_id], company_id)
users_service.set_mobile_channel_type(visitor.user_id, company_id, "VAN_SALES")
vehicle_team_service.set_team_member(vehicle_warehouse_id, company_id, "VISITOR", visitor.user_id)
vehicle_team_service.set_team_member(vehicle_warehouse_id, company_id, "DRIVER", driver.user_id)
vehicle_team_service.set_team_member(vehicle_warehouse_id, company_id, "DISTRIBUTOR", visitor.user_id)
settlement_service.set_settlement_role(company_id, "DISTRIBUTOR")

today = datetime.date.today()
loading_id = vehicle_loading_service.create_vehicle_loading(
    company_id, user.user_id, vehicle_warehouse_id, central_warehouse_id, today,
    [vehicle_loading_service.VehicleLoadingLineFields(item_id=item_id, uom_id=uom_id, planned_quantity=decimal.Decimal(10))],
)
vehicle_loading_service.confirm_vehicle_loading(loading_id, company_id, driver.user_id)

def sell(qty: str) -> None:
    order = {
        "document_type_code": "SALES_INVOICE", "counterparty_detail_account_id": customer,
        "currency_id": company.base_currency_id, "warehouse_id": vehicle_warehouse_id,
        "channel_code": van_channel_code, "post_immediately": True,
        "lines": [{"item_id": item_id, "uom_id": uom_id, "quantity": qty, "unit_price": "10000"}],
    }
    resp = client.post("/orders", headers=auth(admin_token), json=order)
    check(resp.status_code == 200, f"فروشِ {qty} عدد ثبت شد (status={resp.status_code}, body={resp.text})")

distributor_token = login("visitor_van")

# --- دورِ اول: فروشِ ۳ عدد و تسویه ---
sell("3")
r = client.get("/vehicle-settlement/today-summary", headers=auth(distributor_token))
check(r.status_code == 200, f"today-summaryِ دورِ اول ۲۰۰ (body={r.text[:200]})")
summary1 = r.json()
check(decimal.Decimal(summary1["lines"][0]["sold_quantity"]) == decimal.Decimal(3), f"دورِ اول: فروخته‌شده=۳ (got {summary1['lines']})")
check(decimal.Decimal(summary1["invoiced_amount"]) == decimal.Decimal(30000), f"دورِ اول: مبلغِ فاکتورشده=۳۰۰۰۰ (got {summary1['invoiced_amount']})")

r = client.post(
    "/vehicle-settlement", headers=auth(distributor_token),
    json={"declared_cash_amount": "30000", "lines": [{"item_id": item_id, "uom_id": uom_id, "returned_quantity": "0"}]},
)
check(r.status_code == 200, f"ثبتِ تسویهٔ دورِ اول موفق بود (status={r.status_code}, body={r.text})")
settlement1_id = r.json()["vehicle_settlement_id"]

# --- دورِ دوم، همان روز: فروشِ ۲ عددِ دیگر و تسویهٔ دوم -- نباید رد شود ---
sell("2")
r = client.get("/vehicle-settlement/today-summary", headers=auth(distributor_token))
check(r.status_code == 200, f"today-summaryِ دورِ دوم ۲۰۰ (body={r.text[:200]})")
summary2 = r.json()
check(
    decimal.Decimal(summary2["lines"][0]["sold_quantity"]) == decimal.Decimal(2),
    f"دورِ دوم: فقط فروشِ *بعدِ* تسویهٔ اول حساب می‌شود -- ۲، نه ۵ (got {summary2['lines']})",
)
check(
    decimal.Decimal(summary2["invoiced_amount"]) == decimal.Decimal(20000),
    f"دورِ دوم: مبلغِ فاکتورشده فقط همین دور -- ۲۰۰۰۰، نه ۵۰۰۰۰ (got {summary2['invoiced_amount']})",
)

r = client.post(
    "/vehicle-settlement", headers=auth(distributor_token),
    json={"declared_cash_amount": "20000", "lines": [{"item_id": item_id, "uom_id": uom_id, "returned_quantity": "0"}]},
)
check(r.status_code == 200, f"ثبتِ تسویهٔ دورِ دومِ همان روز رد نشد (status={r.status_code}, body={r.text})")
settlement2_id = r.json()["vehicle_settlement_id"]
check(settlement2_id != settlement1_id, "تسویهٔ دوم رکوردِ جداگانه است")

rows = settlement_service.list_settlements(company_id)
same_day = [s for s in rows if s.vehicle_warehouse_id == vehicle_warehouse_id and s.settlement_date == today]
check(len(same_day) == 2, f"دو ردیفِ تسویهٔ جدا برایِ همان خودرو/روز (got {len(same_day)})")
check(sum(s.invoiced_amount for s in same_day) == decimal.Decimal(50000), f"جمعِ دو تسویه = ۵۰۰۰۰ (got {[str(s.invoiced_amount) for s in same_day]})")
check(same_day[0].lines[0].sold_quantity == decimal.Decimal(2), f"دورِ دوم (جدیدتر) اولِ فهرست است (got {same_day[0].lines[0].sold_quantity})")

print("RESULT:", "ALL PASS" if not FAIL else "SOME FAILED")
sys.exit(1 if FAIL else 0)
