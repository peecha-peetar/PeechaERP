"""R378: رمز اتصال پایگاه داده در انبار امن (در فایل فقط نشانه، انتقال خودکار فایل قدیمی، رمز خالی اگر باز نشود، دسترسی 0600 فایل)
و محدودیت نرخ ورود در پایگاه داده (مشترک بین پروسه‌ها، پاک‌سازی، شمارش جدای کلیدها). DPAPI واقعی ویندوز این‌جا اجرا نمی‌شود؛
روش ساختگی جای آن آزمون می‌شود."""
import json, os, stat, sys, tempfile
os.environ["PEECHA_DB_NAME"] = "peecha_test_r378"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prd_fixture import *  # noqa: F401,F403

from pathlib import Path
from sqlalchemy import text
from peecha import config, secret_store


class FakeStore(secret_store.Protector):
    name = "fake"
    broken = False

    def protect(self, secret, account):
        return "enc:" + secret[::-1] + "|" + account

    def unprotect(self, token, account):
        if self.broken or not token.endswith("|" + account):
            raise OSError("cannot open")
        return token[4:-len(account) - 1][::-1]


tmp = Path(tempfile.mkdtemp())
config.SETTINGS_DIR, config.SETTINGS_FILE = tmp, tmp / "connection.json"
fake = FakeStore()
secret_store.use(fake)
cfg = config.DatabaseConfig("db.local", 5432, "erp", "peecha", "S3cret!pass")
config.save_database_config(cfg)
raw = json.loads(config.SETTINGS_FILE.read_text(encoding="utf-8"))
check("password" not in raw and raw["password_store"] == "fake" and "S3cret!pass" not in config.SETTINGS_FILE.read_text(),
      "the password is not in the file")
check(stat.S_IMODE(os.stat(config.SETTINGS_FILE).st_mode) == 0o600, "the settings file is private to its owner")
check(config.load_database_config() == cfg and config.password_is_protected(), "the password comes back from the secure store")
fake.broken = True
check(config.load_database_config().password == "", "an unreadable secret gives an empty password (the form asks again)")
fake.broken = False

legacy = {"host": "db.local", "port": 5432, "name": "erp", "user": "peecha", "password": "old-plain1"}
config.SETTINGS_FILE.write_text(json.dumps(legacy), encoding="utf-8")
check(config.load_database_config().password == "old-plain1", "an old plain file still works")
raw = json.loads(config.SETTINGS_FILE.read_text(encoding="utf-8"))
check("password" not in raw and raw["password_store"] == "fake" and config.load_database_config().password == "old-plain1",
      "and is moved to the secure store on first read")

secret_store.use(secret_store.Protector())
config.save_database_config(cfg)
raw = json.loads(config.SETTINGS_FILE.read_text(encoding="utf-8"))
check(raw["password"] == "S3cret!pass" and not config.password_is_protected()
      and stat.S_IMODE(os.stat(config.SETTINGS_FILE).st_mode) == 0o600, "without a secure store the file stays owner-only")
secret_store.use(None)
real_platform = sys.platform
try:
    sys.platform = "win32"
    check(secret_store.current().name == "dpapi", "Windows uses DPAPI")
finally:
    sys.platform = real_platform
check(secret_store.current().name in ("keyring", "plain"), "other systems use keyring when installed")
check(secret_store.unprotect("dpapi", "not-base64", "a") is None, "a broken token never raises")

# پنجرهٔ تنظیمات اتصال
from PySide6.QtWidgets import QApplication
qapp = QApplication.instance() or QApplication([])
from peecha.ui.login_window import LoginWindow

secret_store.use(fake)
config.save_database_config(cfg)
import peecha.ui.login_window as lw
lw.load_database_config = config.load_database_config
window = LoginWindow("Vazirmatn")
window._open_connection_settings()
check(window.conn_password_field.text() == "S3cret!pass" and "انبار امن" in window.connection_status_label.text(),
      "the connection form says where the password is kept")
config.SETTINGS_FILE.unlink()
secret_store.use(None)

# محدودیت نرخ در پایگاه داده
from fastapi.testclient import TestClient
from peecha_api import rate_limit
from peecha_api.main import app

client = TestClient(app)
codes = [client.post("/auth/login", json={"username": "admin", "password": "wrong"}).status_code for _ in range(6)]
check(codes == [401] * 5 + [429], f"five tries a minute ({codes})")
rate_limit._attempts.clear()
rate_limit._buckets.clear()
check(client.post("/auth/login", json={"username": "admin", "password": "secret123"}).status_code == 429,
      "the limit is kept in the database, so another worker sees it too")
with new_session() as s:
    hits = s.execute(text("SELECT count(*) FROM sec.rate_limit_hits WHERE bucket_key LIKE :k"), {"k": "login:%:admin"}).scalar()
check(hits == 5, f"one row per allowed try ({hits})")
check(client.post("/auth/login", json={"username": "other", "password": "x"}).status_code == 401, "keys are per user")
rate_limit.reset()
check(client.post("/auth/login", json={"username": "admin", "password": "secret123"}).status_code == 423,
      "reset clears the counters (the five wrong passwords have locked the account itself)")

finish()
