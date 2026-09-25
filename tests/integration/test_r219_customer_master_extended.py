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

from peecha.services import commercial_contracts as contracts_service
from peecha.services import commercial_partners as partners_service
from peecha.services import inventory_locations as locations_service

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

print("RESULT:", "ALL PASS" if not FAIL else "SOME FAILED")
