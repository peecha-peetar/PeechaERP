import os, sys, decimal, datetime
os.environ["PEECHA_DB_NAME"] = "peecha_test_r180_1"
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
from peecha.services import inventory_engine as engine_service
from peecha.services import inventory_documents as inv_documents_service
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import roles as roles_service
from peecha.services import users as users_service

lang_id = company.default_language_id
g1 = coa_service.create_account(company_id, "1", "دارایی‌ها", "DEBIT", "ASSET", "PERMANENT", False, lang_id)
k1 = coa_service.create_account(company_id, "11", "موجودیِ انبار", "DEBIT", "ASSET", "PERMANENT", False, lang_id, parent_account_id=g1.account_id)
inv_asset_gl = coa_service.create_account(company_id, "101", "موجودیِ کالا", "DEBIT", "ASSET", "PERMANENT", True, lang_id, parent_account_id=k1.account_id)
g4 = coa_service.create_account(company_id, "2", "بدهی‌ها", "CREDIT", "LIABILITY", "PERMANENT", False, lang_id)
k6 = coa_service.create_account(company_id, "21", "سایرِ بدهی‌ها", "CREDIT", "LIABILITY", "PERMANENT", False, lang_id, parent_account_id=g4.account_id)
ap_gl = coa_service.create_account(company_id, "211", "پرداختنیِ تامین‌کنندگان", "CREDIT", "LIABILITY", "PERMANENT", True, lang_id, parent_account_id=k6.account_id)
engine_service.set_account_mapping(company_id, "INVENTORY_ASSET", inv_asset_gl.account_id)
engine_service.set_account_mapping(company_id, "SUPPLIER_PAYABLE", ap_gl.account_id)

# ==========================================================================
# دادهٔ آزمایشی: کالا + موجودی + مسیرِ توزیع + نقشِ مدیر
# ==========================================================================
uom_id = catalog_service.create_uom(company_id, "PCS", "عدد", "COUNT")
item = catalog_service.create_item(
    company_id, "P-100", "نوشابهٔ خانواده",
    catalog_service.ItemFields(item_kind_code="GOOD", base_uom_id=uom_id, is_sellable=True, barcode="6260000000019"),
)
warehouse_id = locations_service.create_warehouse(
    company_id, "WH-1", "انبارِ آزمایشی", locations_service.WarehouseFields(allow_negative_stock=True),
)
supplier_id = dimensions_service.create_supplier(company_id, "S-1", "تامین‌کننده‌یِ آزمایشی")
receipt_id = inv_documents_service.create_stock_document(
    company_id, user.user_id, "RECEIPT", datetime.date.today(),
    inv_documents_service.DocumentHeaderFields(destination_warehouse_id=warehouse_id, counterparty_detail_account_id=supplier_id),
)
inv_documents_service.add_line(receipt_id, company_id, inv_documents_service.LineFields(
    item_id=item, uom_id=uom_id, quantity=decimal.Decimal(50), quantity_base=decimal.Decimal(50), unit_cost=decimal.Decimal(1000),
))
inv_documents_service.confirm_stock_document(receipt_id, company_id)
inv_documents_service.post_stock_document(receipt_id, company_id, user.user_id)

route_dim_id = dimensions_service.get_specialized_dimension_type_id(company_id, dimensions_service.DISTRIBUTION_ROUTE_CODE)
route_id = dimensions_service.create_detail_account(company_id, route_dim_id, "R-1", "مسیرِ شمالِ شهر")

roles_service.ensure_catalog()
manager_role = roles_service.create_role(company_id, "MANAGER", None)
gl_dim_form_id = next(f.form_id for f in roles_service.list_forms() if f.code == "detail_dimensions")
roles_service.set_role_permission(manager_role.role_id, gl_dim_form_id, "EDIT", True)

manager_user = users_service.create_user(
    "manager1", "مدیرِ فروش", "secret123", None, company.default_language_id, False, [company_id], company_id,
)
roles_service.set_user_role(manager_user.user_id, manager_role.role_id, company_id, True)

visitor_user = users_service.create_user(
    "visitor1", "ویزیتورِ یک", "secret123", None, company.default_language_id, False, [company_id], company_id,
)
gl_dim_create_role = roles_service.create_role(company_id, "VISITOR", None)
roles_service.set_role_permission(gl_dim_create_role.role_id, gl_dim_form_id, "CREATE", True)
roles_service.set_user_role(visitor_user.user_id, gl_dim_create_role.role_id, company_id, True)

from fastapi.testclient import TestClient
from peecha_api.main import app
client = TestClient(app)


def _login(username, password):
    resp = client.post("/auth/login", json={"username": username, "password": password, "device_name": "test"})
    check(resp.status_code == 200, f"ورودِ {username} موفق بود (status={resp.status_code})")
    return resp.json()["access_token"]


admin_token = _login("admin", "secret123")
manager_token = _login("manager1", "secret123")
visitor_token = _login("visitor1", "secret123")


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


# ==========================================================================
# ۱: /routes -- درختِ مسیر/منطقه (نه جدولِ تازه، همان DISTRIBUTION_ROUTE).
# ==========================================================================
resp = client.get("/routes", headers=_auth(visitor_token))
check(resp.status_code == 200, f"لیستِ مسیرها موفق بود (status={resp.status_code})")
codes = {r["code"] for r in resp.json()}
check("R-1" in codes, "مسیرِ تازه‌ساخته در فهرست هست")

# ==========================================================================
# ۲: /products -- جستجو با کد/نام/بارکد.
# ==========================================================================
resp = client.get("/products", params={"q": "نوشابه"}, headers=_auth(visitor_token))
check(resp.status_code == 200 and len(resp.json()) == 1, f"جستجویِ کالا با نام کار کرد (status={resp.status_code})")
resp = client.get("/products", params={"q": "6260000000019"}, headers=_auth(visitor_token))
check(resp.status_code == 200 and len(resp.json()) == 1, "جستجویِ کالا با بارکد کار کرد")
resp = client.get("/products", params={"q": "چیزی‌که‌نیست"}, headers=_auth(visitor_token))
check(resp.status_code == 200 and len(resp.json()) == 0, "جستجویِ بدون‌نتیجه لیستِ خالی برمی‌گرداند")

# ==========================================================================
# ۳: /inventory -- موجودیِ واقعی از StockBalance.
# ==========================================================================
resp = client.get(f"/inventory/{item}", headers=_auth(visitor_token))
check(resp.status_code == 200, f"موجودیِ کالا موفق بود (status={resp.status_code})")
stock_rows = resp.json()
check(len(stock_rows) == 1 and decimal.Decimal(stock_rows[0]["quantity_on_hand"]) == decimal.Decimal(50), f"موجودیِ صحیح برگشت (got {stock_rows})")

# ==========================================================================
# ۴: /notifications -- ثبتِ مشتریِ جدید باید مدیر را Notify کند.
# ==========================================================================
resp = client.post("/customers", json={"code": "C-9", "name": "مشتریِ آزمونِ اعلان"}, headers=_auth(visitor_token))
check(resp.status_code == 200, f"ثبتِ مشتری برایِ تستِ اعلان موفق بود (status={resp.status_code})")
new_customer_id = resp.json()["detail_account_id"]

resp = client.get("/notifications", headers=_auth(manager_token))
check(resp.status_code == 200, f"لیستِ اعلان‌هایِ مدیر موفق بود (status={resp.status_code})")
notifs = resp.json()
check(
    any(n["type_code"] == "CUSTOMER_APPROVAL_NEEDED" and n["entity_id"] == new_customer_id for n in notifs),
    f"اعلانِ نیازِ تاییدِ مشتری برایِ مدیر ساخته شد (got {notifs})",
)
check(all(not n["is_read"] for n in notifs), "اعلان‌هایِ تازه خوانده‌نشده‌اند")

resp = client.get("/notifications", headers=_auth(visitor_token))
check(resp.status_code == 200 and len(resp.json()) == 0, "ویزیتور اعلانِ مدیر را نمی‌بیند (فقط اعلانِ خودش)")

unread_id = notifs[0]["notification_id"]
resp = client.post(f"/notifications/{unread_id}/read", headers=_auth(manager_token))
check(resp.status_code == 200 and resp.json()["is_read"] is True, "علامت‌زدنِ اعلان به‌عنوانِ خوانده‌شده کار کرد")
resp = client.post(f"/notifications/{unread_id}/read", headers=_auth(visitor_token))
check(resp.status_code == 404, "کاربرِ دیگر نمی‌تواند اعلانِ متعلق به مدیر را بخواند/تغییر دهد")

# ==========================================================================
# ۵: /approvals -- تجمیعِ مشتریانِ درانتظار (کارتابل خالی است چون هیچ
#    workflowِ فعالی برایِ هیچ فرمی تعریف نشده -- طبقِ طراحیِ خودِ cartable.py).
# ==========================================================================
resp = client.get("/approvals", headers=_auth(manager_token))
check(resp.status_code == 200, f"صندوقِ تاییدِ مدیر موفق بود (status={resp.status_code})")
body = resp.json()
check(
    any(p["customer_detail_account_id"] == new_customer_id for p in body["pending_customers"]),
    f"مشتریِ درانتظار در صندوقِ تاییدِ مدیر دیده می‌شود (got {body['pending_customers']})",
)
check(body["cartable_tasks"] == [], "بدونِ workflowِ فعال، کارتابل خالی است (طبقِ طراحیِ موجود)")

resp = client.get("/approvals", headers=_auth(visitor_token))
check(resp.status_code == 200 and resp.json()["pending_customers"] == [], "ویزیتورِ بدونِ GL_DIM/EDIT مشتریانِ درانتظار را نمی‌بیند")

print("RESULT:", "ALL PASS" if not FAIL else "SOME FAILED")
sys.exit(1 if FAIL else 0)
