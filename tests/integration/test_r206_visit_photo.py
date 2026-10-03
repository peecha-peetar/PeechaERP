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

# طبقِ رفعِ ناسازگاریِ ذخیره‌سازی (R222 -- «عکس/امضایِ ویزیت کجا ذخیره
# می‌شود؟»): عکس/امضا دیگر مستقیماً در ستونِ دیتابیس نیست؛ رویِ دیسک
# ذخیره می‌شود (هم‌الگو با تاییدِ تحویل) و فقط مسیرش در دیتابیس می‌ماند.
import base64
fake_photo_bytes = b"fake-photo-bytes"
fake_signature_bytes = b"fake-signature-bytes"
fake_photo = base64.b64encode(fake_photo_bytes).decode()
fake_signature = base64.b64encode(fake_signature_bytes).decode()
resp = client.post(
    f"/visits/{customer_visit_id}/complete", headers=auth(admin_token),
    json={"notes": "قفسه‌چینی انجام شد", "photo_base64": fake_photo, "signature_base64": fake_signature},
)
check(resp.status_code == 204, f"تکمیلِ ویزیت با عکس/امضا موفق بود (status={resp.status_code}, body={resp.text})")

from peecha.db.models.commercial import CustomerVisit
with new_session() as s:
    visit = s.get(CustomerVisit, customer_visit_id)
    check(visit.status_code == "COMPLETED", f"وضعیتِ ویزیت COMPLETED است (got {visit.status_code})")
    check(visit.photo_storage_key is not None and visit.photo_storage_key.endswith(".jpg"), f"مسیرِ فایلِ عکس ذخیره شد (got {visit.photo_storage_key!r})")
    check(visit.signature_storage_key is not None and visit.signature_storage_key.endswith(".png"), f"مسیرِ فایلِ امضا ذخیره شد (got {visit.signature_storage_key!r})")
    import pathlib
    check(pathlib.Path(visit.photo_storage_key).read_bytes() == fake_photo_bytes, "محتوایِ عکس رویِ دیسک درست است")
    check(pathlib.Path(visit.signature_storage_key).read_bytes() == fake_signature_bytes, "محتوایِ امضا رویِ دیسک درست است")
    check(visit.notes == "قفسه‌چینی انجام شد", "یادداشت هم ذخیره شد")

# طبقِ درخواستِ صریح: عکس اختیاری است -- بدونِ آن هم باید کار کند
# (رگرسیون با رفتارِ قبلی).
resp = client.post("/visits/start", headers=auth(admin_token), json={"customer_detail_account_id": customer})
customer_visit_id_2 = resp.json()["customer_visit_id"]
resp = client.post(f"/visits/{customer_visit_id_2}/complete", headers=auth(admin_token), json={"notes": None})
check(resp.status_code == 204, f"تکمیلِ ویزیت بدونِ عکس هنوز کار می‌کند (status={resp.status_code}, body={resp.text})")

# طبقِ گزارشِ واقعیِ کاربر («جلوگیری از ویزیتِ تکراری»): همان ویزیتور
# نباید بتواند رویِ همان مشتری، درحالی‌که ویزیتِ قبلی هنوز باز است،
# دوباره «شروعِ ویزیت» بزند؛ بعدِ تکمیل/ردِ آن، ویزیتِ بعدی مجاز است.
resp = client.post("/visits/start", headers=auth(admin_token), json={"customer_detail_account_id": customer})
check(resp.status_code == 200, f"ویزیتِ اول شروع شد (status={resp.status_code})")
open_visit_id = resp.json()["customer_visit_id"]

resp_dup = client.post("/visits/start", headers=auth(admin_token), json={"customer_detail_account_id": customer})
check(resp_dup.status_code == 400, f"ویزیتِ دومِ هم‌زمانِ رویِ همان مشتری رد می‌شود (status={resp_dup.status_code}, body={resp_dup.text})")

resp = client.post(f"/visits/{open_visit_id}/complete", headers=auth(admin_token), json={"notes": None})
check(resp.status_code == 204, f"تکمیلِ ویزیتِ اول موفق بود (status={resp.status_code})")

resp_after = client.post("/visits/start", headers=auth(admin_token), json={"customer_detail_account_id": customer})
check(resp_after.status_code == 200, f"بعدِ تکمیلِ ویزیتِ اول، ویزیتِ تازه مجاز است (status={resp_after.status_code}, body={resp_after.text})")

print("RESULT:", "ALL PASS" if not FAIL else "SOME FAILED")
sys.exit(1 if FAIL else 0)
