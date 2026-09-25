import os, sys, datetime
os.environ["PEECHA_DB_NAME"] = "peecha_test_r206_1"
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

from peecha.services import commercial_partners as partners_service

customer = partners_service.create_customer(company_id, "C-1", "مشتریِ آزمایشی", fast_track=True)

from fastapi.testclient import TestClient
from peecha_api.main import app
client = TestClient(app)

resp = client.post("/auth/login", json={"username": "admin", "password": "secret123"})
admin_token = resp.json()["access_token"]


def auth(t):
    return {"Authorization": f"Bearer {t}"}


resp = client.post("/visits/start", headers=auth(admin_token), json={"customer_detail_account_id": customer})
check(resp.status_code == 200, f"شروعِ ویزیت موفق بود (status={resp.status_code}, body={resp.text})")
customer_visit_id = resp.json()["customer_visit_id"]

fake_photo = "data:image/jpeg;base64,AAAA"
resp = client.post(
    f"/visits/{customer_visit_id}/complete", headers=auth(admin_token),
    json={"notes": "قفسه‌چینی انجام شد", "photo_base64": fake_photo},
)
check(resp.status_code == 204, f"تکمیلِ ویزیت با عکس موفق بود (status={resp.status_code}, body={resp.text})")

from peecha.db.models.commercial import CustomerVisit
with new_session() as s:
    visit = s.get(CustomerVisit, customer_visit_id)
    check(visit.status_code == "COMPLETED", f"وضعیتِ ویزیت COMPLETED است (got {visit.status_code})")
    check(visit.photo_base64 == fake_photo, f"عکس واقعاً ذخیره شد (got {visit.photo_base64!r})")
    check(visit.notes == "قفسه‌چینی انجام شد", "یادداشت هم ذخیره شد")

# طبقِ درخواستِ صریح: عکس اختیاری است -- بدونِ آن هم باید کار کند
# (رگرسیون با رفتارِ قبلی).
resp = client.post("/visits/start", headers=auth(admin_token), json={"customer_detail_account_id": customer})
customer_visit_id_2 = resp.json()["customer_visit_id"]
resp = client.post(f"/visits/{customer_visit_id_2}/complete", headers=auth(admin_token), json={"notes": None})
check(resp.status_code == 204, f"تکمیلِ ویزیت بدونِ عکس هنوز کار می‌کند (status={resp.status_code}, body={resp.text})")

print("RESULT:", "ALL PASS" if not FAIL else "SOME FAILED")
sys.exit(1 if FAIL else 0)
