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
check(labels[10] == "دارایی‌هایِ ثابت" and labels[11] == "تولید", f"FA/PRD tabs in system settings {labels}")
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

fx.finish()
sys.stdout.flush()
os._exit(0)  # Qt teardown of several MDI areas is irrelevant here
