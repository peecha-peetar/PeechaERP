import os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r272"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PySide6.QtWidgets import QApplication, QComboBox, QLineEdit, QMdiArea, QMessageBox, QScrollArea
app = QApplication.instance() or QApplication([])
QMessageBox.warning = staticmethod(lambda *a, **k: None)
QMessageBox.information = staticmethod(lambda *a, **k: None)
from prd_fixture import *  # noqa: F401,F403
import prd_fixture as fx
from peecha import nav_catalog
from peecha.ui import theme
from peecha.ui.screens import costing as cst, fixed_assets as fa, production as prd
from peecha.ui.screens.system_settings import SystemSettingsScreen
check = fx.check
theme.set_theme_mode(app, False)

# ۱) فیلدها در پنجرهٔ کوچک له نمی‌شوند: صفحه داخلِ اسکرول می‌نشیند
_keep = []
def squeezed_inputs(screen):
    host = screen
    if getattr(screen, "scroll_in_mdi", False):
        host = QScrollArea()
        host.setWidgetResizable(True)
        host.setWidget(screen)
    area = QMdiArea()
    area.resize(1000, 480)
    sub = area.addSubWindow(host)
    area.show()
    sub.showMaximized()
    if hasattr(screen, "refresh"):
        screen.refresh()
    app.processEvents()
    _keep.append(area)
    # لاین‌ادیتِ داخلیِ کمبوی قابل‌ویرایش همیشه از sizeHint خودش کوتاه‌تر است؛ خودِ کمبو سنجیده می‌شود
    fields = [w for w in screen.findChildren(QLineEdit) if not isinstance(w.parent(), QComboBox)] + screen.findChildren(QComboBox)
    return [w for w in fields if w.isVisible() and w.height() < w.sizeHint().height() - 2]

for mod, names in ((prd, ["OrdersScreen", "MasterDataScreen", "PlanningScreen", "PrdCostingScreen", "PrdSettingsScreen"]),
                   (fa, ["DepreciationScreen", "SetupScreen", "CipScreen", "PhysicalCountScreen"]),
                   (cst, ["CostingSettingsScreen", "ReplacementCostScreen", "RecalculationScreen"])):
    for name in names:
        cls = getattr(mod, name)
        check(getattr(cls, "scroll_in_mdi", False), f"{name} scrolls in MDI")
        check(not squeezed_inputs(cls()), f"{name}: no squeezed fields in a small window")

dlg = fa.FormDialog("t", [(f"k{i}", f"f{i}", QLineEdit()) for i in range(30)])
dlg.show()
app.processEvents()
check(dlg.findChildren(QScrollArea) and dlg.height() < 900, "long action dialog scrolls instead of squeezing")

# ۲) تنظیماتِ ماژول‌هایِ جدید در «تنظیماتِ سیستم»، نه آیتمِ جدا در منو
flat = {i["code"]: i for i in nav_catalog.flatten_nav_items()}
for code in ("COST_SETTINGS", "FA_SETUP", "PRD_SETTINGS"):
    check(flat[code].get("hidden_from_sidebar") is True, f"{code} hidden from sidebar (permission kept)")
ss = SystemSettingsScreen()
labels = [ss.tabs.tabText(i) for i in range(ss.tabs.count())]
check(labels[10] == "دارایی‌های ثابت" and labels[11] == "تولید", f"FA/PRD tabs in system settings {labels}")
ss.select_tab(11)
check(ss.tabs.currentIndex() == 11, "gear jumps to production settings")
ss.select_tab(7, "قیمت‌گذاری")
inner = ss.tabs.widget(7)
check(inner.tabText(inner.currentIndex()) == "قیمت‌گذاری", "costing gear jumps to inventory > pricing")

from peecha.ui import shell_window
check(shell_window._SETTINGS_TAB_BY_GROUP_CODE["FA"] == 10 and shell_window._SETTINGS_TAB_BY_GROUP_CODE["PRD"] == 11
      and shell_window._SETTINGS_TAB_BY_GROUP_CODE["REPORTS"] == 9, "gear map")
check(shell_window._SETTINGS_SUBTAB_BY_GROUP_CODE["COSTING"] == (7, "قیمت‌گذاری"), "costing gear map")

from peecha.services import roles as roles_service
roles_service.ensure_catalog()
mw = shell_window.MainWindow()
for code in ("COSTING", "FA", "PRD"):
    group = mw._sidebar_groups[code]
    check(group._gear_click is not None, f"{code} has settings gear")
    check(not any(c in group._widgets_by_code for c in ("COST_SETTINGS", "FA_SETUP", "PRD_SETTINGS")), f"{code}: no settings leaf")
mw.open_screen("PRD_ORDERS")
wrapper = mw._mdi_subwindows["prd_orders"].widget()
check(any(isinstance(w, QScrollArea) and w.widget() is mw.get_screen("prd_orders") for w in wrapper.findChildren(QScrollArea)),
      "shell wraps production screen in a scroll area")
mw._sidebar_groups["PRD"]._gear_click()
check(mw._current_screen_code == "SETTINGS" and mw.get_screen("system_settings").tabs.currentIndex() == 11, "PRD gear opens settings")

# ۳) دسترسیِ جداگانهٔ هر تبِ تنظیمات برایِ هر کاربر/نقش
from peecha.db.models.security import User
from peecha.services.production import roles_setup
forms = {c_ for c_, _m, _l in nav_catalog.build_form_catalog()}
check({"treasury_settings", "inventory_settings", "commercial_settings", "report_settings"} <= forms, "settings tab forms in role catalog")
roles_service.ensure_catalog()
form_ids = {f.code: f.form_id for f in roles_service.list_forms()}


def make_user(name, grants):
    with new_session() as s:
        u = User(username=name, full_name=name, password_hash=b"x", password_salt=b"x", is_super_admin=False)
        s.add(u)
        s.commit()
        uid_ = u.user_id
    if grants:
        role = roles_service.create_role(company_id, "R_" + name.upper(), None)
        for code in grants:
            roles_service.set_role_permission(role.role_id, form_ids[code], "VIEW", True)
        roles_service.set_user_role(uid_, role.role_id, company_id, True)
    return type("U", (), {"user_id": uid_, "is_super_admin": False})()


def visible_tabs(u):
    sess.current_user = u
    scr = SystemSettingsScreen()
    scr.refresh()
    out = {}
    for i in range(scr.tabs.count()):
        if scr.tabs.isTabVisible(i):
            inner = scr.tabs.widget(i)
            out[scr.tabs.tabText(i)] = ([inner.tabText(j) for j in range(inner.count()) if inner.isTabVisible(j)]
                                        if hasattr(inner, "count") else [])
    return scr, out


admin_user = sess.current_user
_, tabs = visible_tabs(make_user("prd_only", ["prd_settings"]))
check(list(tabs) == ["تولید"], f"production-settings user sees only production tab {tabs}")
_, tabs = visible_tabs(make_user("cost_only", ["costing_settings"]))
check(tabs == {"انبار و موجودی": ["قیمت‌گذاری"]}, f"costing user sees only inventory > pricing {tabs}")
_, tabs = visible_tabs(make_user("fa_users", ["fa_setup", "users"]))
check(tabs == {"کاربران و دسترسی‌ها": ["کاربران"], "دارایی‌های ثابت": ["طبقه‌ها، حساب‌ها، محل‌ها و سیاست‌ها"]}, f"mixed grants {tabs}")
scr_, tabs = visible_tabs(make_user("nobody", []))
check(not tabs and not scr_.no_access_label.isHidden(), "no grants -> no settings, explanatory message")
scr_.select_tab(11)
check(not scr_.tabs.isVisible() or not scr_.tabs.isTabVisible(11), "gear cannot open a hidden tab")
_, tabs = visible_tabs(make_user("all_settings", ["system_settings"]))
check(len(tabs) == 14, "whole system_settings permission keeps every tab")  # R289: + ارتباط با مشتری، R293: + گردش کار
mgr = roles_setup.ensure_role_templates(company_id)["PRD_MANAGER"]
u = make_user("prd_mgr", [])
roles_service.set_user_role(u.user_id, mgr, company_id, True)
_, tabs = visible_tabs(u)
check("تولید" in tabs and "دارایی‌های ثابت" not in tabs, "production manager template reaches production settings")
sess.current_user = admin_user
_, tabs = visible_tabs(admin_user)
check(len(tabs) == 14, "admin sees all tabs")

fx.finish()
sys.stdout.flush()
os._exit(0)  # Qt teardown of several MDI areas is irrelevant here
