import os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r274"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PySide6.QtWidgets import QApplication, QPushButton
app = QApplication.instance() or QApplication([])
from prd_fixture import *  # noqa: F401,F403
import prd_fixture as fx
from peecha import nav_catalog
from peecha.ui.screens import costing as cst, fixed_assets as fa, module_style as ms, production as prd
from peecha.ui.widgets import SummaryCard
check = fx.check

# ۱) ریبونِ ماژول‌ها مثلِ خرید/فروش
flat = {i["code"] for i in nav_catalog.flatten_nav_items()}
for module in ("COSTING", "FA", "PRD"):
    items = nav_catalog.DEFAULT_QUICK_ACCESS_BY_MODULE.get(module, [])
    check(len(items) >= 5 and all(code in flat for code, _ in items), f"{module} ribbon shortcuts")

# ۲) دستورِ تولید و دارایی: کارت‌هایِ خلاصه + نوارِ دکمه‌هایِ آیکونی با تول‌تیپ
for scr, n_actions in ((prd.OrdersScreen(), 18), (fa.AssetsScreen(), 12)):
    name = type(scr).__name__
    check(len(scr.findChildren(SummaryCard)) == 8 and all(lbl.text() == "—" for lbl in scr.cards.values()), f"{name}: 8 summary cards")
    acts = list(scr.actions.values())
    check(len(acts) == n_actions and all(b.objectName() in ("iconButton", "primaryIconButton", "dangerIconButton") for b in acts),
          f"{name}: actions are icon buttons")
    check(all(b.toolTip() and b.property("label") and len(b.text()) <= 3 for b in acts), f"{name}: label kept in tooltip")
check(prd.OrdersScreen().actions["receipt"].objectName() == "primaryIconButton", "main production action is primary")

# ۳) هیچ دکمهٔ متنیِ بی‌سبک در صفحه‌هایِ ماژول‌ها نمی‌ماند
for mod, names in ((prd, ["MasterDataScreen", "PlanningScreen", "PrdCostingScreen", "PrdSettingsScreen"]),
                   (fa, ["DepreciationScreen", "CipScreen", "PhysicalCountScreen", "SetupScreen"]),
                   (cst, ["ReplacementCostScreen", "RecalculationScreen"])):
    for n in names:
        w = getattr(mod, n)()
        plain = [b.text() for b in w.findChildren(QPushButton) if len(b.text()) > 2 and not b.objectName()]
        check(not plain, f"{n}: no unstyled text buttons {plain}")
check(set(ms.ICONS) >= {"ذخیره", "ثبت تولید", "فروش", "محاسبهٔ نیاز مواد (MRP)"}, "icon map covers main actions")

fx.finish()
sys.stdout.flush()
os._exit(0)
