import os, sys, datetime, decimal
os.environ["PEECHA_DB_NAME"] = "peecha_test_r218_1"
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
from peecha.services import detail_dimensions as dimensions_service

from fastapi.testclient import TestClient
from peecha_api.main import app
client = TestClient(app)


def login(username):
    resp = client.post("/auth/login", json={"username": username, "password": "secret123"})
    return resp.json()["access_token"]


def auth(t):
    return {"Authorization": f"Bearer {t}"}


admin_token = login("admin")

# ---------- ۱. حالتِ پیش‌فرض (تک‌سطحی) -- بدونِ تغییرِ رفتار ----------
r = client.get("/customers/new-form-options", headers=auth(admin_token))
check(r.status_code == 200, f"new-form-options در حالتِ تک‌سطحی ۲۰۰ (status={r.status_code}, body={r.text})")
opts_flat = r.json()
check(opts_flat["max_level_no"] == 1, f"max_level_no پیش‌فرض ۱ است (got {opts_flat['max_level_no']})")
check(opts_flat["parent_options"] == [], f"parent_options در حالتِ تک‌سطحی خالی است (got {opts_flat['parent_options']})")

r = client.post("/customers", headers=auth(admin_token), json={"name": "مشتریِ تک‌سطحی", "code": "FLAT-1"})
check(r.status_code == 200, f"ثبتِ مشتری بدونِ والد در حالتِ تک‌سطحی موفق است (status={r.status_code}, body={r.text})")
flat_customer_id = r.json()["detail_account_id"]
check(dimensions_service.get_detail_account_level_no(flat_customer_id) == 1, "مشتریِ تک‌سطحی در سطحِ ۱ ساخته شد")

# ---------- ۲. تبدیل به چندسطحی (۲ سطح) -- طبقِ بازبینیِ صریحِ کاربر ----------
dimension_type_id = dimensions_service.get_person_dimension_type_id(company_id)
customer_group_id = dimensions_service.get_person_group_id(company_id, dimensions_service.CUSTOMER_GROUP_CODE)
dimensions_service.set_group_max_level_no(dimension_type_id, company_id, max_level_no=2, person_group_id=customer_group_id)

# گرهِ سطحِ ۱ (مثلاً «منطقه») -- طبقِ همان الگویِ دسکتاپ، یک گروه‌بندیِ صرف بدونِ CustomerProfile.
region_id = dimensions_service.create_customer(company_id, "REGION-1", "منطقه‌یِ شمال")
check(dimensions_service.get_detail_account_level_no(region_id) == 1, "گرهِ منطقه در سطحِ ۱ ساخته شد")

r = client.get("/customers/new-form-options", headers=auth(admin_token))
opts_leveled = r.json()
check(opts_leveled["max_level_no"] == 2, f"max_level_no بعدِ تنظیم ۲ است (got {opts_leveled['max_level_no']})")
check(
    len(opts_leveled["parent_options"]) == 1 and opts_leveled["parent_options"][0]["detail_account_id"] == region_id,
    f"parent_options فقط گرهِ سطحِ ماقبلِ‌آخر (منطقه) را می‌دهد (got {opts_leveled['parent_options']})",
)

# بدونِ والد -- باید رد شود (نه رکوردِ اشتباه در سطحِ ۱)
r = client.post("/customers", headers=auth(admin_token), json={"name": "مشتریِ بدونِ والد"})
check(r.status_code == 400, f"ثبتِ مشتری بدونِ والد در حالتِ چندسطحی رد می‌شود (status={r.status_code})")

# والدِ نامعتبر -- باید رد شود
r = client.post("/customers", headers=auth(admin_token), json={"name": "مشتریِ والدِ‌نامعتبر", "parent_detail_account_id": flat_customer_id})
check(r.status_code == 400, f"والدِ نامعتبر (سطحِ اشتباه) رد می‌شود (status={r.status_code})")

# والدِ درست -- باید در سطحِ آخر (۲) ساخته شود
r = client.post(
    "/customers", headers=auth(admin_token),
    json={"name": "فروشگاهِ زیرِ منطقه", "parent_detail_account_id": region_id},
)
check(r.status_code == 200, f"ثبتِ مشتری با والدِ درست موفق است (status={r.status_code}, body={r.text})")
leveled_customer_id = r.json()["detail_account_id"]
check(dimensions_service.get_detail_account_level_no(leveled_customer_id) == 2, "مشتریِ تازه در سطحِ آخر (۲) ساخته شد")
with new_session() as s:
    from peecha.db.models.accounting import DetailAccount
    row = s.get(DetailAccount, leveled_customer_id)
    check(row.parent_detail_account_id == region_id, f"والدِ مشتری همان منطقه‌یِ انتخاب‌شده است (got {row.parent_detail_account_id})")

print("RESULT:", "ALL PASS" if not FAIL else "SOME FAILED")
