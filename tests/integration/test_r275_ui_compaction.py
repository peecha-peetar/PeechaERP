import datetime, os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r275"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PySide6.QtWidgets import QApplication, QWidget
app = QApplication.instance() or QApplication([])
from prd_fixture import *  # noqa: F401,F403
import prd_fixture as fx
from peecha import nav_catalog
from peecha.services import purchase_reports as pr, warehouse_reports as wr, accounting_reports as ar
from peecha.services.fixed_assets import common as fac
from peecha.ui.screens import fixed_assets as fa, production as prd
from peecha.ui.screens.purchase_reports import PurchaseReportScreen, effective_filters
from peecha.ui.screens.inventory_warehouses import InventoryWarehousesScreen
from peecha.ui.screens.hr_org_units import OrgUnitsScreen
from peecha.ui.widgets import FieldHelpPanel, FormDrawer
from peecha.ui import shell_window
check = fx.check

# ۱) ریبونِ صفحهٔ اصلی خالی نیست و صفحه‌هایِ تک‌برگ همان ریبون را نشان می‌دهند
flat = {i["code"] for i in nav_catalog.flatten_nav_items()}
dash = nav_catalog.DEFAULT_QUICK_ACCESS_BY_MODULE["dashboard"]
check(len(dash) >= 10 and all(code in flat for code, _ in dash), "dashboard ribbon shortcuts")
check(shell_window._ribbon_module("MY_TASKS") == "dashboard" and shell_window._ribbon_module("SETTINGS") == "dashboard",
      "leaf modules fall back to dashboard ribbon")
check(shell_window._ribbon_module("GL") == "GL", "module ribbon unchanged")
choices = shell_window._ribbon_choices("dashboard")
check(sum(len(v) for _t, v in choices) > 50, "dashboard ribbon config lists all modules' forms")

# ۲) فرمِ کنارِ فهرست جمع‌شونده است؛ هیچ فیلدی حذف نمی‌شود
for cls in (InventoryWarehousesScreen, OrgUnitsScreen):
    scr = cls()
    d = scr.form_drawer
    before = len(d.form_panel.findChildren(QWidget))
    check(not d.is_open() and d.rail.isVisibleTo(d), f"{cls.__name__}: form collapsed by default")
    d.new_button.click()
    check(d.is_open() and d.form_panel.isVisibleTo(d), f"{cls.__name__}: new opens the form")
    d.collapse()
    check(len(d.form_panel.findChildren(QWidget)) == before, f"{cls.__name__}: no widget removed")
orders = prd.OrdersScreen()
check(isinstance(orders.detail_drawer, FormDrawer) and not orders.detail_drawer.is_open(), "orders detail collapsed")
assets = fa.AssetsScreen()
check(isinstance(assets.detail_drawer, FormDrawer), "assets detail drawer")

# ۳) راهنمایِ فیلد با فوکوسِ خودکارِ لحظهٔ بازشدن ظاهر نمی‌شود
host = QWidget()
panel = FieldHelpPanel(host)
panel.activate()
panel.show_text("x")
check(not panel._has_text, "field help quiet right after activation")
panel._quiet_until = 0
panel.show_text("y")
check(panel._has_text, "field help shows on later focus")

# ۴) فیلترهایِ مرتبطِ گزارش‌ها + فیلترهایِ تازهٔ دارایی
fa_defs = [d for d in wr.WAREHOUSE_REPORTS if d.code.startswith("FA_") and d.code != "FA_CIP"]
check(fa_defs and all({"fa_category", "fa_location", "cost_center"} <= set(effective_filters("INVENTORY", d)) for d in fa_defs),
      "FA reports offer category/location/cost-center filters")
gaps = next(d for d in ar.ACCOUNTING_REPORTS if d.code == "NUMBER_GAPS")
check({"account", "detail"} <= set(effective_filters("ACCOUNTING", gaps)), "number gaps has account/detail filters")
fac.ensure_default_categories(company_id)
cat = fac.list_categories(company_id)[0].category_id
errors = []
for d in fa_defs:
    f = pr.PurchaseFilters(date_from=datetime.date(2020, 1, 1), date_to=today, side="INVENTORY", fa_category_id=cat,
                           options={k: ch[0][0] for k, _l, ch in d.options})
    try:
        pr.run_report(company_id, d.code, f)
    except ValueError:
        pass
    except Exception as exc:  # noqa: BLE001
        errors.append(f"{d.code}: {exc}")
check(not errors, f"FA reports run with category filter {errors}")
screen = PurchaseReportScreen(fa_defs[0].code, side="INVENTORY")
check("fa_category" in screen._filters_used and screen.fa_category_combo is not None, "FA report screen shows category filter")

fx.finish()
