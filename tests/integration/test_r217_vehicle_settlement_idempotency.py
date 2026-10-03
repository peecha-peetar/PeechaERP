import os, sys, datetime, decimal
os.environ["PEECHA_DB_NAME"] = "peecha_test_r217_1"
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
from peecha.services import users as users_service
from peecha.services import vehicle_team as vehicle_team_service
from peecha.services import vehicle_loading as vehicle_loading_service
from peecha.services import vehicle_settlement as settlement_service
from peecha.services import audit as audit_service

lang_id = company.default_language_id
g1 = coa_service.create_account(company_id, "1", "دارایی‌ها", "DEBIT", "ASSET", "PERMANENT", False, lang_id)
k3 = coa_service.create_account(company_id, "11b", "موجودیِ انبار", "DEBIT", "ASSET", "PERMANENT", False, lang_id, parent_account_id=g1.account_id)
inv_asset_gl = coa_service.create_account(company_id, "102", "موجودیِ کالا", "DEBIT", "ASSET", "PERMANENT", True, lang_id, parent_account_id=k3.account_id)
engine_service.set_account_mapping(company_id, "INVENTORY_ASSET", inv_asset_gl.account_id)

central_warehouse_id = locations_service.create_warehouse(
    company_id, "WH-MAIN", "انبارِ مرکزی", locations_service.WarehouseFields(allow_negative_stock=True, is_default=True),
)
vehicle_warehouse_id = locations_service.create_warehouse(
    company_id, "VEH-1", "خودرویِ ۱", locations_service.WarehouseFields(warehouse_type_code="VEHICLE", allow_negative_stock=True),
)
uom_id = catalog_service.create_uom(company_id, "PCS", "عدد", "COUNT")
item_id = catalog_service.create_item(
    company_id, "9101", "کالایِ عادی", catalog_service.ItemFields(item_kind_code="GOOD", base_uom_id=uom_id, is_sellable=True),
)

distributor = users_service.create_user("dist_1", "توزیع‌کننده", "secret123", None, lang_id, False, [company_id], company_id)
driver = users_service.create_user("driver_1", "راننده", "secret123", None, lang_id, False, [company_id], company_id)
vehicle_team_service.set_team_member(vehicle_warehouse_id, company_id, "DISTRIBUTOR", distributor.user_id)
vehicle_team_service.set_team_member(vehicle_warehouse_id, company_id, "DRIVER", driver.user_id)
settlement_service.set_settlement_role(company_id, "DISTRIBUTOR")

today = datetime.date.today()
loading_id = vehicle_loading_service.create_vehicle_loading(
    company_id, user.user_id, vehicle_warehouse_id, central_warehouse_id, today,
    [vehicle_loading_service.VehicleLoadingLineFields(item_id=item_id, uom_id=uom_id, planned_quantity=decimal.Decimal(10))],
)
vehicle_loading_service.confirm_vehicle_loading(loading_id, company_id, driver.user_id)

from fastapi.testclient import TestClient
from peecha_api.main import app
client = TestClient(app)


def login(username):
    resp = client.post("/auth/login", json={"username": username, "password": "secret123"})
    return resp.json()["access_token"]


def auth(t):
    return {"Authorization": f"Bearer {t}"}


distributor_token = login("dist_1")

# ---------- Idempotency + Audit روی POST /vehicle-settlement (R217) ----------
idem_key = "test-idem-key-vehicle-settlement-001"
payload = {"declared_cash_amount": "0", "lines": [{"item_id": item_id, "uom_id": uom_id, "returned_quantity": "10"}]}

r1 = client.post("/vehicle-settlement", headers={**auth(distributor_token), "Idempotency-Key": idem_key}, json=payload)
check(r1.status_code == 200, f"تسویهٔ اول موفق بود (status={r1.status_code}, body={r1.text})")
settlement_id_1 = r1.json()["vehicle_settlement_id"]

r2 = client.post("/vehicle-settlement", headers={**auth(distributor_token), "Idempotency-Key": idem_key}, json=payload)
check(r2.status_code == 200, f"تلاشِ دومِ همان کلید هم ۲۰۰ برمی‌گرداند (status={r2.status_code}, body={r2.text})")
check(r2.json()["vehicle_settlement_id"] == settlement_id_1, f"تلاشِ دوم همان تسویه را برمی‌گرداند، نه رکوردِ تازه (got {r2.json()})")

rows = settlement_service.list_settlements(company_id)
same_day = [s for s in rows if s.vehicle_warehouse_id == vehicle_warehouse_id and s.settlement_date == today]
check(len(same_day) == 1, f"با وجودِ دو POST با یک کلید، فقط یک رکوردِ تسویه ساخته شد (got {len(same_day)})")

log_rows = audit_service.list_activity_log(company_id=company_id, entity_type="VehicleSettlement")
check(len(log_rows) == 1, f"دقیقاً یک رکوردِ حسابرسی برایِ همین تسویه ثبت شد (got {len(log_rows)})")
check(log_rows and log_rows[0].entity_id == settlement_id_1 and log_rows[0].action == "CREATE", f"جزئیاتِ رکوردِ حسابرسی درست است (got {log_rows[0] if log_rows else None})")

print("RESULT:", "ALL PASS" if not FAIL else "SOME FAILED")
