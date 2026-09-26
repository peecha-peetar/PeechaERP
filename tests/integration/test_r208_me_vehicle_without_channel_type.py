import os, sys, datetime
os.environ["PEECHA_DB_NAME"] = "peecha_test_r208_1"
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

from peecha.services import inventory_locations as locations_service
from peecha.services import users as users_service
from peecha.services import vehicle_team as vehicle_team_service

vehicle_wh = locations_service.create_warehouse(
    company_id, "N01", "نیسان آقای جمالی", locations_service.WarehouseFields(warehouse_type_code="VEHICLE"),
)
# سناریویِ دقیقِ گزارش‌شده: «نوعِ کانالِ موبایل» کاربر در دسکتاپ تنظیم
# نشده (از R205 انتخابِ گرم/سرد در خودِ موبایل است).
check(users_service.get_mobile_channel_type(user.user_id, company_id) is None, "نوعِ کانالِ موبایلِ کاربر تنظیم نشده (مثلِ گزارش)")

# ذخیره از همان صفحهٔ دسکتاپِ «تیمِ خودرو» -- هر سه نقش = همان کاربر.
from peecha.ui.screens.vehicle_team import VehicleTeamScreen
screen = VehicleTeamScreen()
screen.refresh()
screen.vehicle_combo.setCurrentIndex(screen.vehicle_combo.findData(vehicle_wh))
for combo in screen._role_combos().values():
    combo.setCurrentIndex(combo.findData(user.user_id))
screen._save()
team = vehicle_team_service.get_team(vehicle_wh, company_id)
check((team.driver_user_id, team.visitor_user_id, team.distributor_user_id) == (user.user_id,) * 3,
      f"هر سه نقش از صفحهٔ دسکتاپ ذخیره شد (got {team})")

from fastapi.testclient import TestClient
from peecha_api.main import app
client = TestClient(app)
token = client.post("/auth/login", json={"username": "admin", "password": "secret123"}).json()["access_token"]
resp = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
check(resp.status_code == 200 and resp.json()["assigned_vehicle_warehouse_id"] == vehicle_wh,
      f"/auth/me خودرو را برمی‌گرداند حتی بدونِ تنظیمِ نوعِ کانال (body={resp.text})")

print("RESULT:", "ALL PASS" if not FAIL else "SOME FAILED")
sys.exit(1 if FAIL else 0)
