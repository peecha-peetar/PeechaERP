"""R377: ورود دومرحله‌ای: کد TOTP مطابق RFC 6238، پنجرهٔ زمانی و جلوگیری از کد تکراری، فعال‌سازی با QR و کدهای بازیابی
یک‌بارمصرف، قفل حساب با کدهای نادرست (رمز درست شمارنده را صفر نمی‌کند)، ورود موبایل (۴۲۸، کد نادرست، کد بازیابی)، الزام
شرکتی (فعال‌سازی در اولین ورود دسکتاپ، رد موبایل، خاموش نشدن)، بازنشانی با مدیر و ردپای حسابرسی؛ و پنجرهٔ ورود و دیالوگ‌ها."""
import os, sys, time
os.environ["PEECHA_DB_NAME"] = "peecha_test_r377"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prd_fixture import *  # noqa: F401,F403

from peecha.db.models.audit import ActivityLog
from peecha.db.models.security import User
from peecha.services import auth, mfa, users as users_service

lang = company.default_language_id
RFC_SECRET = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"   # «12345678901234567890»
check(mfa.code_at(RFC_SECRET, 59) == "287082" and mfa.code_at(RFC_SECRET, 1111111109) == "081804", "RFC 6238 test vectors")
code = mfa.code_at(RFC_SECRET, 1000)
check(mfa.matching_step(RFC_SECRET, code, 1000 + 30) is not None and mfa.matching_step(RFC_SECRET, code, 1000 + 90) is None,
      "one step of clock drift is accepted, not more")
step = mfa.matching_step(RFC_SECRET, code, 1000)
check(mfa.matching_step(RFC_SECRET, code, 1000, after_step=step) is None, "a used code is not accepted again")
check(mfa.matching_step(RFC_SECRET, "۲۸۷ ۰۸۲", 59) is not None, "Persian digits and spaces are accepted")


def logs(user_id):
    with new_session() as s:
        return [(r.action, r.user_id, r.changes) for r in s.scalars(select(ActivityLog).where(
            ActivityLog.entity_type == "User", ActivityLog.entity_id == user_id).order_by(ActivityLog.log_id))]


def raises_text(fn, needle):
    try:
        fn()
    except ValueError as exc:
        return needle in str(exc)
    return False


clerk = users_service.create_user("clerk", "کارمند", "secret123", None, lang, False, [company_id], company_id).user_id
auth.change_password(clerk, "clerk2024")
check(mfa.next_step(clerk) is None and mfa.status(clerk).enabled is False, "off by default")
secret, uri = mfa.start_enrollment(clerk)
check(uri.startswith("otpauth://totp/Peecha%3Aclerk?secret=" + secret) and mfa.qr_png(uri)[:4] == b"\x89PNG", "QR for the app")
check(raises_text(lambda: mfa.confirm_enrollment(clerk, "000000" if mfa.code_at(secret) != "000000" else "111111"), "نادرست")
      and not mfa.status(clerk).enabled, "a wrong code does not enable it")
codes = mfa.confirm_enrollment(clerk, mfa.code_at(secret))
check(len(codes) == 8 and len(set(codes)) == 8 and mfa.status(clerk).recovery_left == 8 and mfa.next_step(clerk) == "VERIFY",
      "enabled with eight recovery codes")
with new_session() as s:
    from peecha.db.models.security import UserMfa
    stored = s.get(UserMfa, clerk).recovery_hashes
check(not any(c.replace("-", "") in str(stored) or c in str(stored) for c in codes), "recovery codes are stored hashed only")

# رمز درست شمارنده را صفر نمی‌کند تا کد دوم درست شود
check(auth.authenticate("clerk", "wrong-pass1") is None and auth.authenticate("clerk", "clerk2024") is not None, "password step")
with new_session() as s:
    check(s.get(User, clerk).failed_login_count == 1, "the failure counter waits for the second factor")
check(logs(clerk)[-1][0] == "LOGIN_FAIL", "no login is recorded before the code")
kind = auth.verify_second_factor(clerk, mfa.code_at(secret, time.time() + 30))
with new_session() as s:
    check(kind == "TOTP" and s.get(User, clerk).failed_login_count == 0 and logs(clerk)[-1][0] == "LOGIN"
          and logs(clerk)[-1][2].get("mfa") == "TOTP", "the code completes the login")
check(auth.verify_second_factor(clerk, codes[0].lower()) == "RECOVERY" and mfa.status(clerk).recovery_left == 7, "a recovery code works once")
check(raises_text(lambda: auth.verify_second_factor(clerk, codes[0]), "نادرست"), "a used recovery code is refused")
for _ in range(3):
    raises_text(lambda: auth.verify_second_factor(clerk, "123456" if mfa.code_at(secret) != "123456" else "654321"), "نادرست")
check(raises_text(lambda: auth.verify_second_factor(clerk, "000001"), "قفل") or raises_text(lambda: auth.verify_second_factor(clerk, "000001"), "قفل"),
      "wrong codes lock the account like wrong passwords")
check(raises_text(lambda: auth.authenticate("clerk", "clerk2024"), "قفل"), "the password step is locked too")
check([a for a, *_ in logs(clerk)].count("MFA_FAIL") >= 3 and "LOCK" in [a for a, *_ in logs(clerk)], "failures and lock are audited")
users_service.update_user(clerk, "کارمند", None, lang, False, True, [company_id], company_id)   # مدیر قفل را باز می‌کند

from fastapi.testclient import TestClient
from peecha_api.main import app

client = TestClient(app)
r = client.post("/auth/login", json={"username": "clerk", "password": "clerk2024"})
check(r.status_code == 428 and "کد" in r.json()["detail"], f"the app is asked for the code ({r.status_code})")
r = client.post("/auth/login", json={"username": "clerk", "password": "clerk2024", "otp": "12345"})
check(r.status_code == 401 and "نادرست" in r.json()["detail"], "a wrong code is refused")
r = client.post("/auth/login", json={"username": "clerk", "password": "clerk2024", "otp": codes[1]})
check(r.status_code == 200 and r.json()["access_token"], f"login with a recovery code ({r.status_code})")
r = client.post("/auth/login", json={"username": "clerk", "password": "wrong-pass1", "otp": codes[2]})
check(r.status_code == 401 and mfa.status(clerk).recovery_left == 6, "a wrong password never reaches the code")

# الزام شرکتی
engine_service.set_feature_enabled(company_id, mfa.POLICY_FEATURE, True)
seller = users_service.create_user("seller", "فروشنده", "secret123", None, lang, False, [company_id], company_id).user_id
auth.change_password(seller, "seller2024")
check(mfa.next_step(seller) == "ENROLL", "required but not set up")
r = client.post("/auth/login", json={"username": "seller", "password": "seller2024"})
check(r.status_code == 403 and "دسکتاپ" in r.json()["detail"], "the app sends the user to the desktop to set it up")
check(raises_text(lambda: mfa.disable(clerk, codes[3]), "الزامی") and mfa.status(clerk).enabled, "it cannot be turned off while required")

# پنجرهٔ ورود
from PySide6.QtWidgets import QApplication, QPushButton
qapp = QApplication.instance() or QApplication([])
from peecha.ui.login_window import LoginWindow
from peecha.ui.mfa_dialogs import MfaCodeDialog, MfaEnrollDialog, MfaSettingsDialog

opened = []
window = LoginWindow("Vazirmatn")
window._open_shell = lambda: opened.append(True)
seen = []


def enroll_runner(dialog):
    seen.append(type(dialog).__name__)
    if isinstance(dialog, MfaEnrollDialog):
        dialog.code.setText(mfa.code_at(dialog.secret))
        return dialog.confirm() and dialog.confirm()
    return False


window.dialog_runner = enroll_runner
window.username_field.setText("seller")
window.password_field.setText("seller2024")
window._attempt_login()
check(seen == ["MfaEnrollDialog"] and opened and mfa.status(seller).enabled and logs(seller)[-1][2].get("mfa") == "ENROLL",
      "first desktop login sets it up and then logs in")
opened.clear()
window.username_field.setText("clerk")
window.password_field.setText("clerk2024")
window._attempt_login()
check(seen[-1] == "MfaCodeDialog" and not opened and "کد ورود دومرحله‌ای" in window.status_label.text(), "cancelling the code keeps you out")
dialog = MfaCodeDialog(window, clerk)
dialog.code.setText("999999" if mfa.code_at(secret) != "999999" else "888888")
dialog.accept()
check(dialog.result() == 0 and "نادرست" in dialog.error.text(), "the code dialog shows the error and stays open")

settings = MfaSettingsDialog(None, clerk)
check(not settings.disable_button.isEnabled() and not settings.recovery_button.isHidden() and "الزامی" in settings.state_label.text(),
      "settings: required, cannot be turned off")
settings.code.setText(codes[4])
check(settings.new_recovery_codes() and len(settings.codes_view.toPlainText().split()) == 8 and mfa.status(clerk).recovery_left == 8,
      "new recovery codes replace the old ones")
new_codes = settings.codes_view.toPlainText().split()
check(raises_text(lambda: auth.verify_second_factor(clerk, codes[5]), "نادرست"), "old recovery codes are void")
check(all(len(b.text()) <= 2 for b in (settings.enable_button, settings.recovery_button, settings.disable_button)), "icon buttons")

engine_service.set_feature_enabled(company_id, mfa.POLICY_FEATURE, False)
settings.refresh()
settings.code.setText(new_codes[0])
check(settings.disable_button.isEnabled() and settings.disable() and mfa.next_step(clerk) is None, "turned off with a code when not required")
settings.enroll_runner = lambda d: (d.code.setText(mfa.code_at(d.secret)), d.confirm(), d.confirm())[-1]
check(settings.enable() and mfa.status(clerk).enabled, "turned on again from the account settings")

# بازنشانی با مدیر
check(raises_text(lambda: mfa.reset_by_admin(seller, company_id, clerk), "مدیر سیستم"), "only the system administrator resets")
from peecha.ui.screens.users import UsersScreen

sess.current_user = user   # پنجرهٔ ورود بالا کاربر جاری را فروشنده کرده بود

screen = UsersScreen()
screen.refresh()
screen._load_into_form(next(r for r in users_service.list_users() if r.user_id == clerk))
screen.confirm_runner = lambda question: True
check(screen.reset_mfa() and not mfa.status(clerk).enabled and logs(clerk)[-1][:2] == ("MFA_RESET", uid), "reset by the administrator is audited")
check(not screen.reset_mfa() and "فعال نیست" in screen.status_label.text(), "nothing to reset")
check(len(screen.mfa_reset_button.text()) <= 2, "icon button")

finish()
