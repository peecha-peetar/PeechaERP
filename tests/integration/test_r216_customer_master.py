import os, sys, datetime, decimal
os.environ["PEECHA_DB_NAME"] = "peecha_test_r216_1"
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
from peecha.services import commercial_credit as credit_service
from peecha.services import inventory_engine as engine_service
from peecha.services import users as users_service
from peecha.services import treasury as treasury_service
from peecha.services import detail_dimensions as dimensions_service

lang_id = company.default_language_id
g1 = coa_service.create_account(company_id, "1", "دارایی‌ها", "DEBIT", "ASSET", "PERMANENT", False, lang_id)
k2 = coa_service.create_account(company_id, "13", "حساب‌هایِ دریافتنی", "DEBIT", "ASSET", "PERMANENT", False, lang_id, parent_account_id=g1.account_id)
ar_gl = coa_service.create_account(company_id, "1304", "حساب‌هایِ دریافتنیِ مشتریان", "DEBIT", "ASSET", "PERMANENT", True, lang_id, parent_account_id=k2.account_id)
k3 = coa_service.create_account(company_id, "11b", "موجودیِ انبار", "DEBIT", "ASSET", "PERMANENT", False, lang_id, parent_account_id=g1.account_id)
inv_asset_gl = coa_service.create_account(company_id, "102", "موجودیِ کالا", "DEBIT", "ASSET", "PERMANENT", True, lang_id, parent_account_id=k3.account_id)
k3b = coa_service.create_account(company_id, "11c", "نقد و بانک", "DEBIT", "ASSET", "PERMANENT", False, lang_id, parent_account_id=g1.account_id)
cash_gl = coa_service.create_account(company_id, "1101", "صندوق", "DEBIT", "ASSET", "PERMANENT", True, lang_id, parent_account_id=k3b.account_id)
g2 = coa_service.create_account(company_id, "4", "درآمدها", "CREDIT", "REVENUE", "TEMPORARY", False, lang_id)
k4 = coa_service.create_account(company_id, "41", "درآمدِ عملیاتی", "CREDIT", "REVENUE", "TEMPORARY", False, lang_id, parent_account_id=g2.account_id)
revenue_gl = coa_service.create_account(company_id, "411", "درآمدِ فروش", "CREDIT", "REVENUE", "TEMPORARY", True, lang_id, parent_account_id=k4.account_id)
discount_gl = coa_service.create_account(company_id, "412", "تخفیفِ فروش", "DEBIT", "REVENUE", "TEMPORARY", True, lang_id, parent_account_id=k4.account_id)
g4 = coa_service.create_account(company_id, "2", "بدهی‌ها", "CREDIT", "LIABILITY", "PERMANENT", False, lang_id)
k6 = coa_service.create_account(company_id, "21", "مالیاتِ پرداختنی", "CREDIT", "LIABILITY", "PERMANENT", False, lang_id, parent_account_id=g4.account_id)
tax_gl = coa_service.create_account(company_id, "2101", "مالیاتِ فروشِ پرداختنی", "CREDIT", "LIABILITY", "PERMANENT", True, lang_id, parent_account_id=k6.account_id)
g3 = coa_service.create_account(company_id, "5", "هزینه‌ها", "DEBIT", "EXPENSE", "TEMPORARY", False, lang_id)
k5 = coa_service.create_account(company_id, "51", "بهایِ تمام‌شده", "DEBIT", "EXPENSE", "TEMPORARY", False, lang_id, parent_account_id=g3.account_id)
cogs_gl = coa_service.create_account(company_id, "511", "بهایِ تمام‌شده", "DEBIT", "EXPENSE", "TEMPORARY", True, lang_id, parent_account_id=k5.account_id)

engine_service.set_account_mapping(company_id, "INVENTORY_ASSET", inv_asset_gl.account_id)
engine_service.set_account_mapping(company_id, "CUSTOMER_RECEIVABLE", ar_gl.account_id)
engine_service.set_account_mapping(company_id, "COGS", cogs_gl.account_id)
csettings_service.set_account_mapping(company_id, "SALES_REVENUE", revenue_gl.account_id)
csettings_service.set_account_mapping(company_id, "SALES_DISCOUNT", discount_gl.account_id)
csettings_service.set_account_mapping(company_id, "SALES_TAX_PAYABLE", tax_gl.account_id)

central_warehouse_id = locations_service.create_warehouse(
    company_id, "WH-MAIN", "انبارِ مرکزی", locations_service.WarehouseFields(allow_negative_stock=True, is_default=True),
)
van_channel_code = pricing_service.create_channel(company_id, "VAN-1", "پخشِ گرمِ آزمایشی", "VAN_SALES")
uom_id = catalog_service.create_uom(company_id, "PCS", "عدد", "COUNT")
item_id = catalog_service.create_item(
    company_id, "9101", "کالایِ عادی", catalog_service.ItemFields(item_kind_code="GOOD", base_uom_id=uom_id, is_sellable=True),
)

customer_group_id = next(g.person_group_id for g in dimensions_service.list_person_groups(company_id) if g.code == "CUSTOMER")
treasury_service.create_counterparty_mapping(company_id, "RECEIPT", cash_gl.account_id, person_group_id=customer_group_id)
treasury_service.set_account_mapping(company_id, "RECEIPT_CASH", cash_gl.account_id)

from fastapi.testclient import TestClient
from peecha_api.main import app
client = TestClient(app)


def login(username):
    resp = client.post("/auth/login", json={"username": username, "password": "secret123"})
    return resp.json()["access_token"]


def auth(t):
    return {"Authorization": f"Bearer {t}"}


admin_token = login("admin")

# ---------- ۱. باگِ واقعیِ رفع‌شده: سقفِ اعتبار فقط برایِ SALES_ORDER بررسی می‌شد، هرگز برایِ فاکتور ----------
customer_low_credit = partners_service.create_customer(
    company_id, "C-CREDIT", "مشتریِ کم‌اعتبار",
    fields=partners_service.CustomerProfileFields(credit_limit_amount=decimal.Decimal("5000")), fast_track=True,
)

order = {
    "document_type_code": "SALES_INVOICE", "counterparty_detail_account_id": customer_low_credit,
    "currency_id": company.base_currency_id, "warehouse_id": central_warehouse_id,
    "channel_code": van_channel_code, "post_immediately": True,
    "lines": [{"item_id": item_id, "uom_id": uom_id, "quantity": "3", "unit_price": "10000"}],
    "settlement_lines": [{"method_code": "CASH", "amount": "2000"}],
}
r = client.post("/orders", headers=auth(admin_token), json=order)
check(r.status_code == 200, f"فاکتورِ بیش‌ازسقف رد نشد -- فقط علامت‌گذاری می‌شود (status={r.status_code}, body={r.text})")
body = r.json()
check(bool(body.get("settlement_warning")) and "اعتبار" in body["settlement_warning"], f"هشدارِ عبور از سقفِ اعتبار برگشت (got {body.get('settlement_warning')})")

open_holds = credit_service.list_open_credit_holds(customer_low_credit)
check(len(open_holds) == 1, f"یک CreditHold برایِ این مشتری ساخته شد (got {len(open_holds)})")
if open_holds:
    check(open_holds[0].related_document_id == body["document_id"], "هُلد به همین فاکتور مرتبط است")

# سفارشی که از سقف عبور نمی‌کند نباید هیچ هشدار/هُلدی بسازد
customer_ok_credit = partners_service.create_customer(
    company_id, "C-CREDIT-2", "مشتریِ اعتبارِ کافی",
    fields=partners_service.CustomerProfileFields(credit_limit_amount=decimal.Decimal("100000")), fast_track=True,
)
order2 = dict(order)
order2["counterparty_detail_account_id"] = customer_ok_credit
r2 = client.post("/orders", headers=auth(admin_token), json=order2)
check(r2.status_code == 200, f"فاکتورِ داخلِ سقف ثبت شد (status={r2.status_code}, body={r2.text})")
check(not r2.json().get("settlement_warning"), f"بدونِ هشدارِ اعتباری (got {r2.json().get('settlement_warning')})")
check(len(credit_service.list_open_credit_holds(customer_ok_credit)) == 0, "بدونِ CreditHold برایِ مشتریِ داخلِ سقف")

# ---------- ۲. فیلدهایِ هویتیِ تکمیلی -- بدونِ ساختنِ سیستمِ موازی، رویِ همان customer_details ----------
detail_id = partners_service.create_customer_detail_account(
    company_id, "C-IDENT", "فروشگاهِ آزمایشی",
    economic_code=None, national_id=None, phone=None, mobile=None, address=None, notes=None,
    customer_group_id=None, default_price_list_id=None, default_channel_code=None,
    payment_term_days=0, credit_limit_amount=decimal.Decimal(0), is_tax_exempt=False,
    distribution_route_detail_account_id=None,
    customer_type_code="STORE", person_type_code="LEGAL", customer_class="A", geographic_region="شمال ۲",
)
rows = {r["detail_account_id"]: r for r in partners_service.list_customer_detail_accounts(company_id)}
row = rows.get(detail_id)
check(row is not None, "مشتریِ تازه‌ساخته در فهرست هست")
check(row and row.get("customer_type_code") == "STORE", f"customer_type_code ذخیره شد (got {row and row.get('customer_type_code')})")
check(row and row.get("person_type_code") == "LEGAL", f"person_type_code ذخیره شد (got {row and row.get('person_type_code')})")
check(row and row.get("customer_class") == "A", f"customer_class ذخیره شد (got {row and row.get('customer_class')})")
check(row and row.get("geographic_region") == "شمال ۲", f"geographic_region ذخیره شد (got {row and row.get('geographic_region')})")

# مسیرِ موبایل: ثبت با customer_type_code/customer_class + خواندنِ همان مقادیر از GET
r = client.post(
    "/customers", headers=auth(admin_token),
    json={"name": "فروشگاهِ موبایلی", "customer_type_code": "RETAILER", "customer_class": "B"},
)
check(r.status_code == 200, f"ثبتِ مشتری از موبایل با فیلدهایِ هویتی (status={r.status_code}, body={r.text})")
mobile_customer_id = r.json()["detail_account_id"]
r = client.get(f"/customers/{mobile_customer_id}", headers=auth(admin_token))
check(r.status_code == 200, f"GETِ جزئیاتِ مشتریِ موبایلی (status={r.status_code})")
detail = r.json()
check(detail.get("customer_type_code") == "RETAILER", f"customer_type_code از موبایل برگشت (got {detail.get('customer_type_code')})")
check(detail.get("customer_class") == "B", f"customer_class از موبایل برگشت (got {detail.get('customer_class')})")

# ---------- ۳. تشخیصِ مشتریِ تکراری در ثبتِ موبایل ----------
r = client.post("/customers", headers=auth(admin_token), json={"name": "فروشگاهِ اصلی", "mobile": "09121234567"})
check(r.status_code == 200, f"مشتریِ اولیه ثبت شد (status={r.status_code}, body={r.text})")

r = client.get("/customers/duplicate-check", headers=auth(admin_token), params={"mobile": "۰۹۱۲۱۲۳۴۵۶۷"})
check(r.status_code == 200, f"duplicate-check با موبایلِ فارسی‌رقم ۲۰۰ (status={r.status_code}, body={r.text})")
found = r.json()
check(len(found) == 1 and found[0]["match_reasons"] == ["موبایلِ یکسان"], f"موبایلِ یکسان (بعدِ نرمال‌سازیِ ارقام) پیدا شد (got {found})")

r = client.get("/customers/duplicate-check", headers=auth(admin_token), params={"name": "فروشگاهِ اصلی"})
found = r.json()
check(len(found) == 1, f"نامِ یکسان هم پیدا می‌شود (got {found})")

r = client.get("/customers/duplicate-check", headers=auth(admin_token), params={"name": "یک مشتریِ کاملاً بی‌ربط"})
check(r.json() == [], f"نامِ بی‌ربط چیزی برنمی‌گرداند (got {r.json()})")

# ---------- ۴. چندآدرسیِ واقعی + GeoFence ----------
r = client.get(f"/customers/{mobile_customer_id}/addresses", headers=auth(admin_token))
check(r.status_code == 200 and r.json() == [], f"بدونِ آدرس در ابتدا (status={r.status_code}, body={r.text})")

r = client.post(
    f"/customers/{mobile_customer_id}/addresses", headers=auth(admin_token),
    json={
        "address_type_code": "STORE", "line1": "خیابانِ آزادی، پلاکِ ۱۰", "city": "تهران", "is_default": True,
        "gps_latitude": "35.699000", "gps_longitude": "51.338000", "geofence_radius_meters": 150,
    },
)
check(r.status_code == 200, f"ثبتِ آدرسِ فروشگاه (status={r.status_code}, body={r.text})")
store_address_id = r.json()["address_id"]

r = client.post(
    f"/customers/{mobile_customer_id}/addresses", headers=auth(admin_token),
    json={"address_type_code": "WAREHOUSE", "line1": "جادهٔ مخصوص، انبارِ ۳"},
)
check(r.status_code == 200, f"ثبتِ آدرسِ انبار (status={r.status_code}, body={r.text})")

r = client.get(f"/customers/{mobile_customer_id}/addresses", headers=auth(admin_token))
addr_list = r.json()
check(len(addr_list) == 2, f"دو آدرسِ مستقل ثبت شد (got {len(addr_list)})")
store_addr = next(a for a in addr_list if a["address_id"] == store_address_id)
check(store_addr["gps_latitude"] == "35.699000" and store_addr["geofence_radius_meters"] == 150, f"GPS/شعاعِ GeoFence رویِ همان آدرس ذخیره شد (got {store_addr})")
check(store_addr["is_default"] is True, "آدرسِ فروشگاه پیش‌فرض است")

r = client.post(
    f"/customers/{mobile_customer_id}/addresses", headers=auth(admin_token),
    json={"address_type_code": "INVALID", "line1": "..."},
)
check(r.status_code == 400, f"نوعِ آدرسِ نامعتبر رد می‌شود (status={r.status_code})")

r = client.delete(f"/customers/{mobile_customer_id}/addresses/{store_address_id}", headers=auth(admin_token))
check(r.status_code == 200, f"حذفِ آدرس موفق بود (status={r.status_code}, body={r.text})")
r = client.get(f"/customers/{mobile_customer_id}/addresses", headers=auth(admin_token))
check(len(r.json()) == 1, f"بعدِ حذف فقط یک آدرس مانده (got {len(r.json())})")

print("RESULT:", "ALL PASS" if not FAIL else "SOME FAILED")
