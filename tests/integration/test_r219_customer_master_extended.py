import os, sys, datetime, decimal
os.environ["PEECHA_DB_NAME"] = "peecha_test_r219_1"
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

from peecha.services import chart_of_accounts as coa_service
from peecha.services import commercial_contracts as contracts_service
from peecha.services import commercial_partners as partners_service
from peecha.services import commercial_pricing as pricing_service
from peecha.services import commercial_settings as csettings_service
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import fiscal_years as fiscal_years_service
from peecha.services import inventory_catalog as catalog_service
from peecha.services import inventory_engine as engine_service
from peecha.services import inventory_locations as locations_service
from peecha.services import treasury as treasury_service

fiscal_years_service.create_fiscal_year_for_date(company_id, 1, 1, datetime.date.today())
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
customer_group_id_for_receipt = next(g.person_group_id for g in dimensions_service.list_person_groups(company_id) if g.code == "CUSTOMER")
treasury_service.create_counterparty_mapping(company_id, "RECEIPT", cash_gl.account_id, person_group_id=customer_group_id_for_receipt)
treasury_service.set_account_mapping(company_id, "RECEIPT_CASH", cash_gl.account_id)
van_channel_code = pricing_service.create_channel(company_id, "VAN-1", "پخشِ گرمِ آزمایشی", "VAN_SALES")
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

# ---------- R219-1: نوعِ کانال + تنظیماتِ سفارش ----------
wh_id = locations_service.create_warehouse(
    company_id, "WH-MAIN", "انبارِ مرکزی", locations_service.WarehouseFields(allow_negative_stock=True, is_default=True),
)
customer_id = partners_service.create_customer_detail_account(
    company_id, "C-OUTLET", "سوپرِ نمونه",
    economic_code=None, national_id=None, phone=None, mobile=None, address=None, notes=None,
    customer_group_id=None, default_price_list_id=None, default_channel_code=None,
    payment_term_days=0, credit_limit_amount=decimal.Decimal(0), is_tax_exempt=False,
    distribution_route_detail_account_id=None,
    outlet_type_code="SUPERMARKET", priority_code="HIGH",
    min_order_amount=decimal.Decimal("500000"), min_order_quantity=decimal.Decimal("10"),
    allowed_order_days_mask=31, allowed_order_hour_from=8, allowed_order_hour_to=18,
    expected_delivery_days=2, shipment_type_code="VEHICLE_ROUTE", default_warehouse_id=wh_id,
)
rows = {r["detail_account_id"]: r for r in partners_service.list_customer_detail_accounts(company_id)}
row = rows.get(customer_id)
check(row is not None, "مشتریِ تازه‌ساخته در فهرست هست")
check(row and row.get("outlet_type_code") == "SUPERMARKET", f"outlet_type_code ذخیره شد (got {row and row.get('outlet_type_code')})")
check(row and row.get("priority_code") == "HIGH", f"priority_code ذخیره شد (got {row and row.get('priority_code')})")
check(row and str(row.get("min_order_amount")) == "500000.00", f"min_order_amount ذخیره شد (got {row and row.get('min_order_amount')})")
check(row and row.get("allowed_order_days_mask") == 31, f"allowed_order_days_mask ذخیره شد (got {row and row.get('allowed_order_days_mask')})")
check(row and row.get("default_warehouse_id") == wh_id, f"default_warehouse_id ذخیره شد (got {row and row.get('default_warehouse_id')})")

r = client.get(f"/customers/{customer_id}", headers=auth(admin_token))
check(r.status_code == 200, f"GETِ جزئیاتِ مشتری (status={r.status_code})")
detail = r.json()
check(detail.get("outlet_type_code") == "SUPERMARKET", f"outlet_type_code از موبایل برگشت (got {detail.get('outlet_type_code')})")
check(detail.get("priority_code") == "HIGH", f"priority_code از موبایل برگشت (got {detail.get('priority_code')})")

# ---------- R219-2: سفته/ضامن/وثیقه/چکِ تضمینی رویِ مشتری ----------
r = client.get(f"/customers/{customer_id}/guarantees", headers=auth(admin_token))
check(r.status_code == 200 and r.json() == [], f"بدونِ ضمانت در ابتدا (status={r.status_code}, body={r.text})")

r = client.post(
    f"/customers/{customer_id}/guarantees", headers=auth(admin_token),
    json={"guarantee_type_code": "PROMISSORY_NOTE", "amount": "20000000", "description": "سفته‌یِ شماره‌یِ ۱۲۳"},
)
check(r.status_code == 200, f"ثبتِ سفته موفق بود (status={r.status_code}, body={r.text})")
note_guarantee_id = r.json()["guarantee_id"]

r = client.post(
    f"/customers/{customer_id}/guarantees", headers=auth(admin_token),
    json={"guarantee_type_code": "GUARANTOR", "amount": "10000000", "description": "ضامن: آقایِ محمدی"},
)
check(r.status_code == 200, f"ثبتِ ضامن موفق بود (status={r.status_code}, body={r.text})")

r = client.get(f"/customers/{customer_id}/guarantees", headers=auth(admin_token))
guarantees = r.json()
check(len(guarantees) == 2, f"دو ضمانتِ مستقل ثبت شد (got {len(guarantees)})")
check(all(g["status_code"] == "ACTIVE" for g in guarantees), "هردو ضمانت فعال‌اند")
check(decimal.Decimal(partners_service.total_active_guarantee_amount(customer_id)) == decimal.Decimal("30000000"), f"جمعِ ضمانتِ فعال ۳۰میلیون است (got {partners_service.total_active_guarantee_amount(customer_id)})")

r = client.post(f"/customers/{customer_id}/guarantees", headers=auth(admin_token), json={"guarantee_type_code": "INVALID", "amount": "1000"})
check(r.status_code == 400, f"نوعِ ضمانتِ نامعتبر رد می‌شود (status={r.status_code})")

r = client.post(f"/customers/{customer_id}/guarantees/{note_guarantee_id}/release", headers=auth(admin_token))
check(r.status_code == 200, f"آزادسازیِ سفته موفق بود (status={r.status_code}, body={r.text})")
check(decimal.Decimal(partners_service.total_active_guarantee_amount(customer_id)) == decimal.Decimal("10000000"), f"بعدِ آزادسازی فقط ضامن فعال می‌ماند (got {partners_service.total_active_guarantee_amount(customer_id)})")

r = client.post(f"/customers/{customer_id}/guarantees/{note_guarantee_id}/release", headers=auth(admin_token))
check(r.status_code == 400, f"آزادسازیِ دوباره‌یِ همان ضمانت رد می‌شود (status={r.status_code})")

# ---------- R219-3: قراردادِ نمایندگی/سازمانی/سهمیه ----------
r = client.get(f"/customers/{customer_id}/contracts", headers=auth(admin_token))
check(r.status_code == 200 and r.json() == [], f"بدونِ قرارداد در ابتدا (status={r.status_code}, body={r.text})")

r = client.post(
    f"/customers/{customer_id}/contracts", headers=auth(admin_token),
    json={
        "contract_category_code": "AGENCY", "valid_from": str(datetime.date.today()),
        "committed_amount": "100000000", "commitments_text": "تعهد به پوششِ کاملِ منطقه‌یِ شمال",
    },
)
check(r.status_code == 200, f"ثبتِ قراردادِ نمایندگی موفق بود (status={r.status_code}, body={r.text})")
agency_contract_id = r.json()["contract_id"]

r = client.get(f"/customers/{customer_id}/contracts", headers=auth(admin_token))
contracts = r.json()
check(len(contracts) == 1, f"یک قرارداد ثبت شد (got {len(contracts)})")
check(contracts[0]["contract_category_code"] == "AGENCY", f"دسته‌یِ قرارداد نمایندگی است (got {contracts[0]['contract_category_code']})")
check(contracts[0]["committed_amount"] == "100000000.00", f"سهمیه‌یِ مبلغی ذخیره شد (got {contracts[0]['committed_amount']})")
check(contracts[0]["status_code"] == "ACTIVE", "قرارداد فعال است")

contracts_service.record_contract_consumption(agency_contract_id, decimal.Decimal(0), decimal.Decimal("15000000"))
r = client.get(f"/customers/{customer_id}/contracts", headers=auth(admin_token))
check(r.json()[0]["consumed_amount"] == "15000000.00", f"مصرفِ ثبت‌شده منعکس شد (got {r.json()[0]['consumed_amount']})")

r = client.post(f"/customers/{customer_id}/contracts/{agency_contract_id}/cancel", headers=auth(admin_token))
check(r.status_code == 200, f"لغوِ قرارداد موفق بود (status={r.status_code}, body={r.text})")
r = client.get(f"/customers/{customer_id}/contracts", headers=auth(admin_token))
check(r.json()[0]["status_code"] == "CANCELLED", "قرارداد بعدِ لغو CANCELLED است")

r = client.post(
    f"/customers/{customer_id}/contracts", headers=auth(admin_token),
    json={"contract_category_code": "INVALID", "valid_from": str(datetime.date.today())},
)
check(r.status_code == 400, f"دسته‌یِ نامعتبر رد می‌شود (status={r.status_code})")

# ---------- R219-4: اعمالِ GeoFence رویِ ثبتِ ویزیت (غیرِمسدودکننده) ----------
from peecha.services import field_sales as field_sales_service

r = client.post(
    f"/customers/{customer_id}/addresses", headers=auth(admin_token),
    json={
        "address_type_code": "STORE", "line1": "فروشگاهِ اصلی", "is_default": True,
        "gps_latitude": "35.700000", "gps_longitude": "51.400000", "geofence_radius_meters": 100,
    },
)
check(r.status_code == 200, f"ثبتِ آدرسِ فروشگاه با GeoFence موفق بود (status={r.status_code}, body={r.text})")

visitor_role = None  # از همان admin_token استفاده می‌کنیم چون فقط نیازِ سنجشِ منطقِ سرویس داریم

# داخلِ محدوده (چند متر با مرکزِ GeoFence فاصله)
visit_in_id = field_sales_service.start_visit(
    company_id, customer_id, user.user_id,
    check_in_latitude=decimal.Decimal("35.700010"), check_in_longitude=decimal.Decimal("51.400010"),
)
check(field_sales_service.get_visit_geofence_status(visit_in_id) is False, f"ویزیتِ داخلِ محدوده پرچم نمی‌خورد (got {field_sales_service.get_visit_geofence_status(visit_in_id)})")

# خارج از محدوده (چند کیلومتر با مرکزِ GeoFence فاصله)
visit_out_id = field_sales_service.start_visit(
    company_id, customer_id, user.user_id,
    check_in_latitude=decimal.Decimal("35.750000"), check_in_longitude=decimal.Decimal("51.450000"),
)
check(field_sales_service.get_visit_geofence_status(visit_out_id) is True, f"ویزیتِ خارجِ محدوده پرچم می‌خورد (got {field_sales_service.get_visit_geofence_status(visit_out_id)})")

r = client.post(
    "/visits/start", headers=auth(admin_token),
    json={"customer_detail_account_id": customer_id, "check_in_latitude": "35.750000", "check_in_longitude": "51.450000"},
)
check(r.status_code == 200, f"ثبتِ ویزیتِ خارجِ محدوده رد نمی‌شود -- فقط پرچم می‌خورد (status={r.status_code}, body={r.text})")
check(r.json().get("is_outside_geofence") is True, f"پاسخِ API پرچمِ GeoFence را برمی‌گرداند (got {r.json()})")

# مشتریِ بدونِ هیچ GeoFence -- باید None بماند (نه True/False)
customer_no_geofence_id = partners_service.create_customer(company_id, "C-NOGEO", "مشتریِ بدونِ ژئوفنس", fast_track=True)
visit_none_id = field_sales_service.start_visit(
    company_id, customer_no_geofence_id, user.user_id,
    check_in_latitude=decimal.Decimal("35.700000"), check_in_longitude=decimal.Decimal("51.400000"),
)
check(field_sales_service.get_visit_geofence_status(visit_none_id) is None, f"بدونِ GeoFence یعنی None، نه False (got {field_sales_service.get_visit_geofence_status(visit_none_id)})")

# ---------- R219-5: اطلاعاتِ فروشگاهی/Merchandising ----------
r = client.get(f"/customers/{customer_id}/merchandising", headers=auth(admin_token))
check(r.status_code == 200 and r.json()["store_area_sqm"] is None, f"بدونِ اطلاعاتِ فروشگاهی در ابتدا (status={r.status_code}, body={r.text})")

r = client.put(
    f"/customers/{customer_id}/merchandising", headers=auth(admin_token),
    json={
        "store_area_sqm": "45.5", "checkout_count": 2, "fridge_count": 3, "shelf_count": 12,
        "available_brands": "کوکاکولا، پپسی", "competitor_brands": "زمزم", "layout_status_code": "GOOD",
    },
)
check(r.status_code == 200, f"ثبتِ اطلاعاتِ فروشگاهی موفق بود (status={r.status_code}, body={r.text})")

r = client.get(f"/customers/{customer_id}/merchandising", headers=auth(admin_token))
merch = r.json()
check(merch["store_area_sqm"] == "45.5", f"متراژ ذخیره شد (got {merch['store_area_sqm']})")
check(merch["shelf_count"] == 12, f"تعدادِ قفسه ذخیره شد (got {merch['shelf_count']})")
check(merch["layout_status_code"] == "GOOD", f"وضعیتِ چیدمان ذخیره شد (got {merch['layout_status_code']})")

r = client.put(f"/customers/{customer_id}/merchandising", headers=auth(admin_token), json={"layout_status_code": "INVALID"})
check(r.status_code == 400, f"وضعیتِ چیدمانِ نامعتبر رد می‌شود (status={r.status_code})")

# ---------- R219-6: CRMِ کامل (شکایت/جلسه/فرصتِ فروش/وظیفه) ----------
r = client.get(f"/customers/{customer_id}/activities", headers=auth(admin_token))
check(r.status_code == 200 and r.json() == [], f"بدونِ فعالیت در ابتدا (status={r.status_code}, body={r.text})")

r = client.post(
    f"/customers/{customer_id}/activities", headers=auth(admin_token),
    json={"activity_type_code": "COMPLAINT", "subject": "تأخیر در تحویل", "description": "فاکتورِ اخیر دیر رسید"},
)
check(r.status_code == 200, f"ثبتِ شکایت موفق بود (status={r.status_code}, body={r.text})")
complaint_id = r.json()["activity_id"]

r = client.post(
    f"/customers/{customer_id}/activities", headers=auth(admin_token),
    json={"activity_type_code": "OPPORTUNITY", "subject": "خطِ تولیدِ جدید", "estimated_value": "50000000"},
)
check(r.status_code == 200, f"ثبتِ فرصتِ فروش موفق بود (status={r.status_code}, body={r.text})")
opportunity_id = r.json()["activity_id"]

r = client.get(f"/customers/{customer_id}/activities", headers=auth(admin_token), params={"open_only": True})
check(len(r.json()) == 2, f"دو فعالیتِ بازِ مستقل ثبت شد (got {len(r.json())})")

r = client.post(f"/customers/{customer_id}/activities/{complaint_id}/close", headers=auth(admin_token), json={"status_code": "RESOLVED"})
check(r.status_code == 200, f"بستنِ شکایت با RESOLVED موفق بود (status={r.status_code}, body={r.text})")

r = client.post(f"/customers/{customer_id}/activities/{opportunity_id}/close", headers=auth(admin_token), json={"status_code": "RESOLVED"})
check(r.status_code == 400, f"وضعیتِ نامتناسب با نوعِ فعالیت (RESOLVED برایِ فرصتِ فروش) رد می‌شود (status={r.status_code})")

r = client.post(f"/customers/{customer_id}/activities/{opportunity_id}/close", headers=auth(admin_token), json={"status_code": "WON"})
check(r.status_code == 200, f"بستنِ فرصتِ فروش با WON موفق بود (status={r.status_code}, body={r.text})")

r = client.get(f"/customers/{customer_id}/activities", headers=auth(admin_token), params={"open_only": True})
check(r.json() == [], f"بعدِ بستنِ هردو، فعالیتِ بازی نمانده (got {r.json()})")

r = client.post(f"/customers/{customer_id}/activities/{complaint_id}/close", headers=auth(admin_token), json={"status_code": "RESOLVED"})
check(r.status_code == 400, f"بستنِ دوباره‌یِ فعالیتِ بسته‌شده رد می‌شود (status={r.status_code})")

# ---------- R219-7: صفحه‌یِ Customer 360 (یک endpointِ تکی) ----------
r = client.get(f"/customers/{customer_id}/360", headers=auth(admin_token))
check(r.status_code == 200, f"GETِ Customer 360 موفق بود (status={r.status_code}, body={r.text[:300]})")
c360 = r.json()
check(c360["detail"]["code"] == "C-OUTLET", f"بخشِ detail درست است (got {c360['detail'].get('code')})")
check(len(c360["guarantees"]) == 2, f"بخشِ guarantees تاریخچه‌یِ کامل (فعال+آزادشده) را می‌دهد (got {len(c360['guarantees'])})")
check(len(c360["contracts"]) == 1, f"بخشِ contracts شاملِ قراردادِ لغوشده هم هست (got {len(c360['contracts'])})")
check(len(c360["activities"]) == 2, f"بخشِ activities شاملِ هر دو فعالیتِ بسته‌شده است (got {len(c360['activities'])})")
check(len(c360["addresses"]) == 1, f"بخشِ addresses شاملِ آدرسِ فروشگاه است (got {len(c360['addresses'])})")
check(c360["merchandising"] is not None and c360["merchandising"]["shelf_count"] == 12, f"بخشِ merchandising درست است (got {c360['merchandising']})")
check(len(c360["recent_visits"]) == 3, f"بخشِ recent_visits شاملِ هر سه ویزیتِ ثبت‌شده است (got {len(c360['recent_visits'])})")

# ---------- R219-8: امتیازدهی/سگمنت‌بندیِ مشتری ----------
from peecha.services import commercial_documents as documents_service

r = client.get(f"/customers/{customer_id}/segment", headers=auth(admin_token))
check(r.status_code == 200, f"GETِ سگمنتِ مشتری موفق بود (status={r.status_code}, body={r.text})")
seg = r.json()
check(seg["segment_code"] == "NEW", f"مشتریِ بدونِ فاکتورِ POSTED هنوز NEW است (got {seg['segment_code']})")

# مشتریِ بدهکار (طبقِ اصلِ صریح: بدهیِ نامتناسب با حجمِ خریدِ عادی)
customer_debtor_id = partners_service.create_customer(
    company_id, "C-SEG-DEBTOR", "مشتریِ بدهکارِ آزمایشی",
    fields=partners_service.CustomerProfileFields(credit_limit_amount=decimal.Decimal("0")), fast_track=True,
)
order_debtor = {
    "document_type_code": "SALES_INVOICE", "counterparty_detail_account_id": customer_debtor_id,
    "currency_id": company.base_currency_id, "warehouse_id": wh_id,
    "channel_code": van_channel_code, "post_immediately": True,
    "lines": [{"item_id": item_id, "uom_id": uom_id, "quantity": "3", "unit_price": "10000"}],
    "settlement_lines": [{"method_code": "CASH", "amount": "1000"}],
}
r = client.post("/orders", headers=auth(admin_token), json=order_debtor)
check(r.status_code == 200, f"فاکتورِ نسیه برایِ سنجشِ سگمنت ثبت شد (status={r.status_code}, body={r.text})")

seg_info = documents_service.compute_customer_segment(company_id, customer_debtor_id)
check(seg_info.balance_nature == "بدهکار" and seg_info.balance_amount > 0, f"مانده‌یِ بدهکار محاسبه شد (got {seg_info.balance_amount} {seg_info.balance_nature})")
check(seg_info.order_count_last_12_months == 1, f"تعدادِ سفارشِ ۱۲ماهِ اخیر درست است (got {seg_info.order_count_last_12_months})")

# ---------- R219-9: داشبوردِ بالایِ فرمِ مشتری (سودِ برآوردیِ ۳ماهِ اخیر) ----------
# بدونِ سابقه‌یِ رسیدِ کالا، بهایِ تمام‌شدهٔ آخرینِ شناخته‌شده صفر است؛ پس سودِ
# برآوردی باید با خودِ فروشِ ۳ماهِ اخیر برابر باشد (۳ عدد × ۱۰٬۰۰۰).
check(
    seg_info.estimated_profit_last_3_months == seg_info.sales_last_3_months == decimal.Decimal("30000"),
    f"سودِ برآوردیِ ۳ماهِ اخیر بدونِ بهایِ شناخته‌شده برابرِ فروش است (got profit={seg_info.estimated_profit_last_3_months}, sales={seg_info.sales_last_3_months})",
)

r = client.get(f"/customers/{customer_debtor_id}/segment", headers=auth(admin_token))
check(r.status_code == 200 and decimal.Decimal(r.json()["estimated_profit_last_3_months"]) == decimal.Decimal("30000"), f"فیلدِ سود در پاسخِ /segment ارائه شد (status={r.status_code}, body={r.text})")

r = client.get(f"/customers/{customer_debtor_id}/360", headers=auth(admin_token))
check(r.status_code == 200 and decimal.Decimal(r.json()["segment"]["estimated_profit_last_3_months"]) == decimal.Decimal("30000"), f"فیلدِ سود در پاسخِ /360 هم ارائه شد (status={r.status_code}, body={r.text[:300]})")

print("RESULT:", "ALL PASS" if not FAIL else "SOME FAILED")
