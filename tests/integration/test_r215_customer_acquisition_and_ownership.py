import os, sys, datetime, decimal
os.environ["PEECHA_DB_NAME"] = "peecha_test_r215_1"
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
from peecha.services import roles as roles_service
from peecha.services import treasury as treasury_service
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import field_sales as field_sales_service

lang_id = company.default_language_id
g1 = coa_service.create_account(company_id, "1", "دارایی‌ها", "DEBIT", "ASSET", "PERMANENT", False, lang_id)
k1 = coa_service.create_account(company_id, "11", "موجودیِ انبار", "DEBIT", "ASSET", "PERMANENT", False, lang_id, parent_account_id=g1.account_id)
inv_asset_gl = coa_service.create_account(company_id, "101", "موجودیِ کالا", "DEBIT", "ASSET", "PERMANENT", True, lang_id, parent_account_id=k1.account_id)
cash_gl = coa_service.create_account(company_id, "102", "صندوق", "DEBIT", "ASSET", "PERMANENT", True, lang_id, parent_account_id=k1.account_id)
k2 = coa_service.create_account(company_id, "13", "حساب‌هایِ دریافتنی", "DEBIT", "ASSET", "PERMANENT", False, lang_id, parent_account_id=g1.account_id)
ar_gl = coa_service.create_account(company_id, "1304", "حساب‌هایِ دریافتنیِ مشتریان", "DEBIT", "ASSET", "PERMANENT", True, lang_id, parent_account_id=k2.account_id)
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
treasury_service.set_account_mapping(company_id, "RECEIPT_CASH", cash_gl.account_id)
customer_group_id = dimensions_service.get_person_group_id(company_id, dimensions_service.CUSTOMER_GROUP_CODE)
treasury_service.create_counterparty_mapping(company_id, "RECEIPT", ar_gl.account_id, person_group_id=customer_group_id)

central_warehouse_id = locations_service.create_warehouse(company_id, "WH-MAIN", "انبارِ مرکزی", locations_service.WarehouseFields(allow_negative_stock=True, is_default=True))
channel_code = pricing_service.create_channel(company_id, "PRE-1", "پخشِ سردِ آزمایشی", "PRE_SALES")
uom_id = catalog_service.create_uom(company_id, "PCS", "عدد", "COUNT")
item_id = catalog_service.create_item(company_id, "9101", "کالایِ عادی", catalog_service.ItemFields(item_kind_code="GOOD", base_uom_id=uom_id, is_sellable=True))

customer_own = partners_service.create_customer(company_id, "C-OWN", "مشتریِ ثابتِ راننده", fast_track=True)
customer_other = partners_service.create_customer(company_id, "C-OTHER", "مشتریِ راننده‌یِ دیگر", fast_track=True)
customer_unassigned = partners_service.create_customer(company_id, "C-FREE", "مشتریِ بدونِ مسیر", fast_track=True)

rep1 = users_service.create_user("rep1", "ویزیتورِ یک", "secret123", None, lang_id, False, [company_id], company_id)
rep2 = users_service.create_user("rep2", "ویزیتورِ دو", "secret123", None, lang_id, False, [company_id], company_id)
manager = users_service.create_user("mgr1", "سرپرست", "secret123", None, lang_id, False, [company_id], company_id)

field_role = roles_service.create_role(company_id, "FIELD_REP", None)
gl_dim_form_id = next(f.form_id for f in roles_service.list_forms() if f.code == "detail_dimensions")
cold_form_id = next(f.form_id for f in roles_service.list_forms() if f.code == "cold_distribution")
receipt_form_id = next(f.form_id for f in roles_service.list_forms() if f.code == "treasury_voucher_receipt")
roles_service.set_role_permission(field_role.role_id, gl_dim_form_id, "CREATE", True)
roles_service.set_role_permission(field_role.role_id, cold_form_id, "CREATE", True)
roles_service.set_role_permission(field_role.role_id, receipt_form_id, "CREATE", True)
roles_service.set_user_role(rep1.user_id, field_role.role_id, company_id, True)
roles_service.set_user_role(rep2.user_id, field_role.role_id, company_id, True)

manager_role = roles_service.create_role(company_id, "MANAGER", None)
roles_service.set_role_permission(manager_role.role_id, gl_dim_form_id, "EDIT", True)
roles_service.set_role_permission(manager_role.role_id, cold_form_id, "CREATE", True)
roles_service.set_role_permission(manager_role.role_id, receipt_form_id, "CREATE", True)
roles_service.set_user_role(manager.user_id, manager_role.role_id, company_id, True)

# مشتریِ ثابتِ راننده فقط به rep1 اختصاص دارد؛ مشتریِ راننده‌یِ دیگر فقط به rep2.
field_sales_service.create_visit_plan(company_id, customer_own, visit_day_of_week=0, assigned_visitor_user_id=rep1.user_id)
field_sales_service.create_visit_plan(company_id, customer_other, visit_day_of_week=0, assigned_visitor_user_id=rep2.user_id)

from fastapi.testclient import TestClient
from peecha_api.main import app
client = TestClient(app)


def login(username):
    return client.post("/auth/login", json={"username": username, "password": "secret123"}).json()["access_token"]


def auth(t):
    return {"Authorization": f"Bearer {t}"}


rep1_token = login("rep1")
rep2_token = login("rep2")
manager_token = login("mgr1")

# ---------- ۱. /auth/me is_manager ----------
r = client.get("/auth/me", headers=auth(rep1_token))
check(r.json()["is_manager"] is False, f"ویزیتورِ معمولی is_manager=False (got {r.json()})")
r = client.get("/auth/me", headers=auth(manager_token))
check(r.json()["is_manager"] is True, f"سرپرست is_manager=True (got {r.json()})")

# ---------- ۲. محدودهٔ مالکیت روی سفارش ----------
def order_payload(customer_id):
    return {
        "document_type_code": "SALES_ORDER", "counterparty_detail_account_id": customer_id,
        "warehouse_id": central_warehouse_id, "channel_code": channel_code, "currency_id": company.base_currency_id,
        "post_immediately": False, "lines": [{"item_id": item_id, "uom_id": uom_id, "quantity": "1", "unit_price": "10000"}],
    }

r = client.post("/orders", headers=auth(rep2_token), json=order_payload(customer_own))
check(r.status_code == 403, f"rep2 نمی‌تواند برایِ مشتریِ rep1 سفارش ثبت کند (status={r.status_code}, body={r.text})")
r = client.post("/orders", headers=auth(rep1_token), json=order_payload(customer_own))
check(r.status_code == 200, f"rep1 برایِ مشتریِ خودش سفارش ثبت می‌کند (status={r.status_code}, body={r.text})")
r = client.post("/orders", headers=auth(rep1_token), json=order_payload(customer_unassigned))
check(r.status_code == 200, f"مشتریِ بدونِ مسیر برایِ هرکسی آزاد است (status={r.status_code}, body={r.text})")
r = client.post("/orders", headers=auth(manager_token), json=order_payload(customer_other))
check(r.status_code == 200, f"سرپرست از محدودیتِ مالکیت معاف است (status={r.status_code}, body={r.text})")

# ---------- ۳. محدودهٔ مالکیت روی وصولی ----------
def payment_payload(customer_id):
    return {"customer_detail_account_id": customer_id, "method_lines": [{"method": "CASH", "amount": "5000"}]}

r = client.post("/payments", headers=auth(rep2_token), json=payment_payload(customer_own))
check(r.status_code == 403, f"rep2 نمی‌تواند از مشتریِ rep1 وصول کند (status={r.status_code}, body={r.text})")
r = client.post("/payments", headers=auth(rep1_token), json=payment_payload(customer_own))
check(r.status_code == 200, f"rep1 از مشتریِ خودش وصول می‌کند (status={r.status_code}, body={r.text})")

# ---------- ۴. Customer Acquisition: کدِ خودکار (آفلاین‌سازگار) ----------
r = client.post(
    "/customers", headers=auth(rep1_token),
    json={"name": "مشتریِ تازه", "phone": "09120000001", "mobile": "09120000001", "address": "تهران", "notes": "یادداشتِ آزمایشی"},
)
check(r.status_code == 200, f"ثبتِ مشتریِ جدید بدونِ کد (status={r.status_code}, body={r.text})")
new_customer_id = r.json()["detail_account_id"]
assigned_code = r.json()["code"]
check(bool(assigned_code), f"کدِ خودکار تخصیص یافت (got {assigned_code})")
check(r.json()["status_code"] == "PENDING_APPROVAL", "مشتریِ تازه در انتظارِ تایید است")

r = client.get(f"/customers/{new_customer_id}", headers=auth(rep1_token))
check(r.json()["mobile"] == "09120000001" and r.json()["notes"] == "یادداشتِ آزمایشی", f"موبایل/یادداشت ذخیره شد (got {r.json()})")

# ---------- ۵. گزینه‌هایِ فرمِ مشتریِ جدید ----------
r = client.get("/customers/new-form-options", headers=auth(rep1_token))
check(r.status_code == 200 and r.json().get("suggested_code"), f"new-form-options کدِ پیشنهادی دارد (body={r.text})")

# ---------- ۶. تاییدِ مشتری ----------
r = client.post(f"/customers/{new_customer_id}/approve", headers=auth(manager_token))
check(r.status_code == 200 and r.json()["status_code"] == "ACTIVE", f"تاییدِ سرپرست موفق بود (body={r.text})")
r = client.post(f"/customers/{new_customer_id}/approve", headers=auth(manager_token))
check(r.status_code == 400, f"تاییدِ دوباره‌یِ مشتریِ فعال رد می‌شود (status={r.status_code})")

# ---------- ۷. ردِ مشتری ----------
r = client.post("/customers", headers=auth(rep1_token), json={"name": "مشتریِ ردشدنی"})
reject_customer_id = r.json()["detail_account_id"]
r = client.post(f"/customers/{reject_customer_id}/reject", headers=auth(manager_token), json={"reason": "آدرس نامعتبر است"})
check(r.status_code == 200 and r.json()["status_code"] == "INACTIVE", f"ردِ مشتری موفق بود (body={r.text})")
r = client.post(f"/customers/{reject_customer_id}/reject", headers=auth(manager_token), json={"reason": "دوباره"})
check(r.status_code == 400, f"ردِ دوباره‌یِ مشتریِ ردشده رد می‌شود (status={r.status_code})")
# ویزیتورِ معمولی (بدونِ اکشنِ EDIT رویِ detail_dimensions) نباید بتواند تایید/رد کند.
r = client.post("/customers", headers=auth(rep1_token), json={"name": "مشتریِ سوم"})
third_customer_id = r.json()["detail_account_id"]
r = client.post(f"/customers/{third_customer_id}/approve", headers=auth(rep1_token))
check(r.status_code == 403, f"ویزیتورِ معمولی نمی‌تواند تایید کند (status={r.status_code})")

# ---------- ۸. عکسِ فروشگاه ----------
dimensions_service.set_dimension_type_photo_enabled(
    dimensions_service.get_person_dimension_type_id(company_id), company_id, True,
)
import base64, io
from PIL import Image as PILImage
buf = io.BytesIO()
PILImage.new("RGB", (300, 300), color=(20, 140, 90)).save(buf, format="PNG")
photo_b64 = base64.b64encode(buf.getvalue()).decode("ascii")
r = client.post("/customers", headers=auth(rep1_token), json={"name": "مشتریِ با عکس", "photo_base64": photo_b64})
check(r.status_code == 200, f"ثبتِ مشتری با عکس موفق بود (body={r.text[:200]})")
photo_customer_id = r.json()["detail_account_id"]
photo = dimensions_service.get_primary_detail_account_photo(company_id, photo_customer_id)
check(photo is not None, "عکسِ اصلیِ مشتری واقعاً ذخیره و به‌عنوانِ عکسِ اصلی ثبت شد")

print("RESULT:", "ALL PASS" if not FAIL else "SOME FAILED")
sys.exit(1 if FAIL else 0)
