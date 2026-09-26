import os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r190_1"
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
from peecha.db.base import get_engine
apply_pending_schema_files(get_engine())
from peecha.services.bootstrap import bootstrap_system
from peecha import session as sess
user = bootstrap_system("admin", "مدیر سیستم", "secret123", "شرکت آزمایشی")
sess.current_user = user

from fastapi.testclient import TestClient
from peecha_api.main import app
client = TestClient(app)

# ۵ تلاشِ اول (رمزِ غلط) باید عادی ۴۰۱ بدهند (نه ۴۲۹)
for i in range(5):
    resp = client.post("/auth/login", json={"username": "admin", "password": "wrong"})
    check(resp.status_code == 401, f"تلاشِ #{i+1} با رمزِ غلط، ۴۰۱ عادی (status={resp.status_code})")

# تلاشِ ششم رویِ همان (IP، نامِ‌کاربری) باید ۴۲۹ بدهد
resp = client.post("/auth/login", json={"username": "admin", "password": "wrong"})
check(resp.status_code == 429, f"تلاشِ ششم مسدود شد (status={resp.status_code})")

# حتی با رمزِ درست هم دیگر رد نمی‌شود (شمارش رویِ هر تلاش است، نه فقط شکست)
resp = client.post("/auth/login", json={"username": "admin", "password": "secret123"})
check(resp.status_code == 429, f"حتی با رمزِ درست هم رد شد چون سقفِ ۶۰ثانیه پر است (status={resp.status_code})")

# یک نامِ‌کاربریِ دیگر (هرچند نامعتبر) رویِ همان IP هنوز مسدود نیست -- کلید جداست
resp = client.post("/auth/login", json={"username": "someone-else", "password": "x"})
check(resp.status_code == 401, f"نامِ‌کاربریِ دیگر رویِ همان IP هنوز مسدود نیست (status={resp.status_code})")

print("RESULT:", "ALL PASS" if not FAIL else "SOME FAILED")
sys.exit(1 if FAIL else 0)
