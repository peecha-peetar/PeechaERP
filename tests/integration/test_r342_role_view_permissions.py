"""R342: نقش‌ها در پنجرهٔ اصلی اعمال می‌شوند: کاربر محدود فقط منو، ریبون و جستجوی صفحه‌هایی را می‌بیند که نقشش اجازهٔ
«مشاهده» داده و صفحهٔ دیگر (حتی از میان‌بر یا لینک فرم دیگر) باز نمی‌شود؛ کاربر بی‌نقش پیام روشن می‌گیرد؛ با تعویض شرکت
دسترسی همان شرکت اعمال می‌شود؛ مدیر کل سیستم همه را دارد."""
import os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r342"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))
for k, v in (("PEECHA_DB_USER", "peecha"), ("PEECHA_DB_PASSWORD", "peecha"), ("PEECHA_DB_HOST", "localhost"), ("PEECHA_DB_PORT", "5432")):
    os.environ.setdefault(k, v)

FAIL = False


def check(cond, msg):
    global FAIL
    FAIL = FAIL or not cond
    print(("OK: " if cond else "FAIL: ") + msg)


from PySide6.QtWidgets import QApplication, QMessageBox

app = QApplication.instance() or QApplication([])
infos = []
QMessageBox.information = staticmethod(lambda *a, **k: infos.append(a[2]))
QMessageBox.warning = staticmethod(lambda *a, **k: None)

from sqlalchemy import select
from peecha import session as sess
from peecha.db.base import get_engine, new_session
from peecha.db.models.core import Company
from peecha.db.models.security import UserCompany
from peecha.db.schema_bootstrap import apply_pending_schema_files
from peecha.services import companies as companies_service, roles as roles_service, users as users_service
from peecha.services.bootstrap import bootstrap_system

apply_pending_schema_files(get_engine())
admin = bootstrap_system("admin", "مدیر سیستم", "secret123", "شرکت اول")
with new_session() as s:
    company = s.get(Company, s.scalar(select(UserCompany.company_id).where(UserCompany.user_id == admin.user_id)))
    s.expunge(company)
cid = company.company_id
other = companies_service.create_company("C2", "شرکت دوم", "شرکت دوم", company.base_currency_id, company.default_language_id)
users_service.grant_company_access(admin.user_id, other.company_id)

forms = {f.code: f.form_id for f in roles_service.list_forms()}
role = roles_service.create_role(cid, "انباردار", None)
for code in ("inventory_documents_list", "inventory_warehouses"):
    roles_service.set_role_permission(role.role_id, forms[code], "VIEW", True)
roles_service.set_role_permission(role.role_id, forms["journal_entries_list"], "EDIT", True)  # بدون «مشاهده»
keeper = users_service.create_user("keeper", "انباردار", "secret123", None, company.default_language_id, False,
                                   [cid, other.company_id], cid)
roles_service.set_user_role(keeper.user_id, role.role_id, cid, True)
nobody = users_service.create_user("nobody", "بی‌نقش", "secret123", None, company.default_language_id, False, [cid], cid)

check(roles_service.user_allowed_forms(admin.user_id, cid) is None, "the system administrator has every form")
check(roles_service.user_allowed_forms(keeper.user_id, cid) == {"inventory_documents_list", "inventory_warehouses"},
      "the service lists exactly the forms the role may view")
check(roles_service.user_allowed_forms(keeper.user_id, other.company_id) == set(), "a role of one company gives nothing in another")

from peecha.nav_catalog import flatten_nav_items
from peecha.ui.shell_window import _NAV_ALIASES, MainWindow

code_of = {}
for i in flatten_nav_items():
    code_of.setdefault(i["screen"], i["code"])
DOCS, WAREHOUSES, JE_LIST = code_of["inventory_documents_list"], code_of["inventory_warehouses"], code_of["journal_entries_list"]


def visible_leaves(window):
    return {code for group in window._sidebar_groups.values() if not group.isHidden()
            for code, button in group._entries.items() if not button.isHidden()}


def visible_groups(window):
    return {code for code, group in window._sidebar_groups.items() if not group.isHidden()}


# --- کاربر محدود ------------------------------------------------------------------------------------------------------
sess.current_user, sess.current_company = keeper, company
infos.clear()
win = MainWindow()
win.load_context_switcher()
leaves = visible_leaves(win)
check({DOCS, WAREHOUSES} <= leaves and JE_LIST not in leaves and leaves <= {DOCS, WAREHOUSES, "MY_TASKS"},
      f"the menu shows only the allowed forms and the personal inbox ({sorted(leaves)})")
check(visible_groups(win) == {"INV", "MY_TASKS"}, f"modules without an allowed form are hidden ({sorted(visible_groups(win))})")
check("dashboard" not in win._mdi_subwindows and not infos, "the dashboard is not opened for a user without its permission")
win.open_screen(JE_LIST)
check(win._mdi_subwindows.get("journal_entries_list") is None and infos and "دسترسی ندارید" in infos[-1],
      "a form without «مشاهده» does not open (e.g. from a shortcut or another form), with a message")
win.open_screen(DOCS)
check(win._mdi_subwindows.get("inventory_documents_list") is not None, "an allowed form opens")
win.open_screen("MY_TASKS")
check(win._mdi_subwindows.get("my_tasks") is not None, "the personal inbox always opens")
ALLOWED = {"inventory_documents_list", "inventory_warehouses", "my_tasks"}


def screen(code):
    return win._screen_by_code[_NAV_ALIASES.get(code, code)]


completions = win.search_field.completer().model().stringList()
check(completions and all(screen(win._search_code_by_breadcrumb[c]) in ALLOWED for c in completions),
      f"the global search lists only allowed forms ({completions[:4]})")
win.search_field.setText("اسناد حسابداری")
infos.clear()
win._on_global_search_return_pressed()
check(win._mdi_subwindows.get("journal_entries_list") is None, "typing a forbidden form's name in search does not open it")
ribbon_codes = {x["code"] for _title, leaves in win._allowed_ribbon_choices("dashboard") for x in leaves}
check(ribbon_codes and all(screen(c) in ALLOWED for c in ribbon_codes), f"ribbon choices are only allowed forms ({sorted(ribbon_codes)})")

# --- تعویض شرکت: نقش این کاربر در شرکت دوم نیست ------------------------------------------------------------------------
infos.clear()
index = win.company_combo.findData(other.company_id)
win.company_combo.setCurrentIndex(index)
check(visible_groups(win) == {"MY_TASKS"} and not win._mdi_subwindows["inventory_documents_list"].isVisible(),
      "after switching company the forms of the other company's role disappear and its open form closes")
check("هیچ فرمی مجاز نشده" in win._no_access_box.text() and not win._no_access_box.isModal(),
      "and a clear, non-blocking message says nothing is allowed there")
win.hide()

# --- کاربر بی‌نقش و مدیر کل سیستم ---------------------------------------------------------------------------------------
sess.current_user, sess.current_company = nobody, company
infos.clear()
win2 = MainWindow()
win2.load_context_switcher()
check(visible_groups(win2) == {"MY_TASKS"} and "نقشی بدهد" in win2._no_access_box.text(),
      "a user without a role sees only the inbox and is told why")
win2.hide()
sess.current_user = admin
win3 = MainWindow()
win3.load_context_switcher()
check(len(visible_groups(win3)) == len(win3._sidebar_groups) and "dashboard" in win3._mdi_subwindows,
      "the system administrator sees every module and the dashboard")
win3.hide()

print("ALL PASS" if not FAIL else "SOME FAILED")
