"""R344: سیاست رمز، قفل موقت پس از ورود ناموفق، تغییر رمز اجباری و دستی، کلید JWT پایدار، و ردپای خودکار تغییر
کاربر، دسترسی شرکت، نقش، مجوز، نقش کاربر، قابلیت، شماره‌گذاری، سال مالی و تنظیمات حقوق در رد حسابرسی (بدون رمز،
بدون شمارنده‌ها، و بدون ثبت اگر عملیات برگردد)."""
import datetime, decimal, importlib, os, stat, sys, tempfile
os.environ["PEECHA_DB_NAME"] = "peecha_test_r344"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prd_fixture import *  # noqa: F401,F403

from peecha.db.models.audit import ActivityLog
from peecha.db.models.commercial import DocumentNumberingSequence
from peecha.db.models.accounting import FiscalYear
from peecha.db.models.security import Role, User
from peecha.services import auth, commercial_settings, payroll, roles as roles_service, users as users_service

lang = company.default_language_id


def logs(entity_type, entity_id=None):
    with new_session() as s:
        query = select(ActivityLog).where(ActivityLog.entity_type == entity_type)
        if entity_id is not None:
            query = query.where(ActivityLog.entity_id == entity_id)
        return [(r.action, r.user_id, r.company_id, r.changes) for r in s.scalars(query.order_by(ActivityLog.log_id))]


def refused(fn, needle):
    try:
        fn()
    except ValueError as exc:
        return needle in str(exc)
    return False


# --- سیاست رمز ------------------------------------------------------------------------------------------------------
for weak in ("ab1", "abcdefgh", "12345678", "۱۲۳۴۵۶۷۸"):
    check(refused(lambda w=weak: users_service.create_user("weak", "ضعیف", w, None, lang, False, [company_id], company_id),
                  "۸ نویسه"), f"weak password {weak!r} is refused")
clerk = users_service.create_user("clerk", "کارمند", "secret123", None, lang, False, [company_id], company_id)
check(clerk.must_change_password, "a new user gets a temporary password")

# --- ردپای کاربر و دسترسی شرکت (کاربر واردشده = مدیر) -------------------------------------------------------------------
created = logs("User", clerk.user_id)
check(created and created[0][0] == "CREATE" and created[0][1] == uid and "password_hash" not in created[0][3]
      and created[0][3].get("username") == "clerk", f"creating a user is audited without the password ({created})")
access = logs("UserCompanyAccess", clerk.user_id)
check(access and access[-1][3]["company_ids"] == [[], [company_id]], "the companies granted are audited")
users_service.update_user(clerk.user_id, "کارمند فروش", None, lang, False, True, [company_id], company_id, new_password="temp4567")
changed = logs("User", clerk.user_id)[-1]
check(changed[0] == "UPDATE" and changed[3].get("password") == "تغییر کرد" and changed[3].get("full_name") == ["کارمند", "کارمند فروش"]
      and "password_salt" not in changed[3], f"a password reset is audited as «changed», never the value ({changed[3]})")
check(len(logs("UserCompanyAccess", clerk.user_id)) == 1, "saving with the same companies adds no access entry")

# --- نقش، مجوز، نقش کاربر -----------------------------------------------------------------------------------------------
forms = {f.code: f.form_id for f in roles_service.list_forms()}
role = roles_service.create_role(company_id, "انباردار", None)
roles_service.set_role_permission(role.role_id, forms["journal_entry"], "VIEW", True)
roles_service.set_role_permission(role.role_id, forms["journal_entry"], "VIEW", True)  # بدون تغییر
roles_service.set_role_permission(role.role_id, forms["journal_entry"], "VIEW", False)
roles_service.set_user_role(clerk.user_id, role.role_id, company_id, True)
check([a for a, *_ in logs("Role", role.role_id)] == ["CREATE"], "a new role is audited")
perm = logs("RoleFormPermission", role.role_id)
check([a for a, *_ in perm] == ["CREATE", "DELETE"] and all(p[1] == uid and p[2] == company_id for p in perm)
      and perm[0][3]["form_id"] == forms["journal_entry"], f"grant and revoke are audited with who and which company ({perm})")
check(logs("UserRole", clerk.user_id)[-1][0] == "CREATE", "assigning a role to a user is audited")

# --- تنظیمات: قابلیت، شماره‌گذاری (نه شمارنده)، سال مالی، حقوق ------------------------------------------------------------
commercial_settings.set_feature_enabled(company_id, "ALLOW_EDIT_POSTED_INVOICE", True)
check(logs("CompanyFeature", company_id) and logs("CompanyFeature", company_id)[-1][3].get("is_enabled") in (True, [False, True]),
      "turning a feature on is audited")
commercial_settings.set_numbering_sequence(company_id, "SALES_INVOICE", "SI-", "YEARLY")
before = len(logs("NumberingSequence", company_id))
with new_session() as s:
    row = s.get(DocumentNumberingSequence, (company_id, "SALES_INVOICE"))
    row.next_number = (row.next_number or 1) + 5
    s.commit()
check(before == 1 and len(logs("NumberingSequence", company_id)) == 1, "the running document counter is not audited")
with new_session() as s:
    fy = s.scalar(select(FiscalYear).where(FiscalYear.company_id == company_id))
    fy.is_closed = True
    fy_id = fy.fiscal_year_id
    s.commit()
check(logs("FiscalYear", fy_id)[-1][3].get("is_closed") == [False, True], "closing a fiscal year is audited")
with new_session() as s:
    s.get(FiscalYear, fy_id).is_closed = False
    s.commit()
payroll.set_tax_exemption(company_id, today, decimal.Decimal("1200000000"))
check(any(a == "CREATE" for a, *_ in logs("TaxExemption")), "a payroll tax setting is audited")

# --- تراکنش برگشتی ردپا نمی‌گذارد ------------------------------------------------------------------------------------------
count = len(logs("Role"))
with new_session() as s:
    s.add(Role(company_id=company_id, code="موقت", is_active=True))
    s.flush()
    s.rollback()
check(len(logs("Role")) == count, "a rolled-back change leaves no audit entry")

# --- ورود ناموفق، قفل، بازکردن با ذخیرهٔ مدیر ------------------------------------------------------------------------------
for attempt in range(auth.MAX_FAILED_LOGINS - 1):
    check(auth.authenticate("clerk", "wrong-pass1") is None, f"wrong password {attempt + 1} is refused")
check(auth.authenticate("clerk", "wrong-pass1") is None, "the fifth wrong password is refused too")
try:
    auth.authenticate("clerk", "temp4567")
    locked = ""
except auth.AccountLockedError as exc:
    locked = str(exc)
check("قفل" in locked and "۱۵ دقیقه" in locked, f"after five failures even the right password is locked out ({locked})")
events = [a for a, *_ in logs("User", clerk.user_id)]
check(events.count("LOGIN_FAIL") == 4 and events[-1] == "LOCK", f"failures and the lock are audited ({events[-6:]})")
check(auth.authenticate("nobody", "secret123") is None, "an unknown username simply fails")

from fastapi.testclient import TestClient
from peecha_api.main import app

client = TestClient(app)
api = client.post("/auth/login", json={"username": "clerk", "password": "temp4567"})
check(api.status_code == 423 and "قفل" in api.json()["detail"], f"the mobile login reports the lock ({api.status_code})")
users_service.update_user(clerk.user_id, "کارمند فروش", None, lang, False, True, [company_id], company_id)
user = auth.authenticate("clerk", "temp4567")
check(user is not None and logs("User", clerk.user_id)[-1][0] == "LOGIN", "an administrator's save unlocks; the login is audited")

# --- تغییر رمز -------------------------------------------------------------------------------------------------------
check(refused(lambda: auth.change_password(clerk.user_id, "short"), "۸ نویسه"), "the new password follows the policy")
check(refused(lambda: auth.change_password(clerk.user_id, "temp4567"), "فرق"), "the new password must differ")
check(refused(lambda: auth.change_password(clerk.user_id, "brandnew9", "bad-current1"), "فعلی"), "the current password is checked")
auth.change_password(clerk.user_id, "brandnew9", "temp4567")
with new_session() as s:
    row = s.get(User, clerk.user_id)
    check(not row.must_change_password and row.password_changed_at is not None, "changing the password clears the temporary flag")
check(auth.authenticate("clerk", "brandnew9") is not None, "the new password works")

# --- ورود دسکتاپ: تغییر اجباری رمز موقت -------------------------------------------------------------------------------
from PySide6.QtWidgets import QApplication, QDialog, QToolButton

qapp = QApplication.instance() or QApplication([])
users_service.update_user(clerk.user_id, "کارمند فروش", None, lang, False, True, [company_id], company_id, new_password="reset2468")
import peecha.session as app_session
from peecha.ui import password_dialog
from peecha.ui.login_window import LoginWindow

saved_user = app_session.current_user
app_session.current_user = None
login = LoginWindow("Vazirmatn")
opened = []
login._open_shell = lambda: opened.append(True)
password_dialog.ChangePasswordDialog.exec = lambda self: QDialog.Rejected
login.username_field.setText("clerk")
login.password_field.setText("reset2468")
login._attempt_login()
check(not opened and app_session.current_user is None and "رمز جدید" in login.status_label.text(),
      "a temporary password must be replaced before entering")


def accept_with(new):
    def run(self):
        self.new.setText(new)
        self.confirm.setText(new)
        self.accept()
        return self.result()
    return run


password_dialog.ChangePasswordDialog.exec = accept_with("ab1")
login._attempt_login()
check(not opened, "a weak replacement is refused in the dialog")
password_dialog.ChangePasswordDialog.exec = accept_with("chosen135")
login._attempt_login()
check(opened and app_session.current_user is not None and auth.authenticate("clerk", "chosen135") is not None,
      "with a valid new password the user enters")
app_session.current_user = saved_user

from peecha.ui.shell_window import MainWindow

win = MainWindow()
check(any(b.accessibleName() == "تغییر رمز عبور" for b in win.findChildren(QToolButton)), "the header has a change-password button")
win.hide()

# --- کلید JWT پایدار --------------------------------------------------------------------------------------------------
import peecha.config as peecha_config
import peecha_api.config as api_config

folder = tempfile.mkdtemp()
secret_env = os.environ.pop("PEECHA_API_JWT_SECRET", None)
peecha_config.SETTINGS_DIR = __import__("pathlib").Path(folder)
first = importlib.reload(api_config).JWT_SECRET
second = importlib.reload(api_config).JWT_SECRET
key_file = os.path.join(folder, "api_jwt.key")
check(first == second and len(first) == 64 and stat.S_IMODE(os.stat(key_file).st_mode) == 0o600,
      "without the environment variable the JWT key is created once, owner-only, and reused")
os.environ["PEECHA_API_JWT_SECRET"] = "x" * 40
check(importlib.reload(api_config).JWT_SECRET == "x" * 40, "the environment variable wins")
if secret_env is not None:
    os.environ["PEECHA_API_JWT_SECRET"] = secret_env

finish()
