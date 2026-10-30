"""R317: حالت لمسی (پیمایش با انگشت، لمس طولانی، اندازهٔ بزرگ‌تر، کلید روشن/خاموش در نوار بالا) و مرتب‌کردن فرم‌های
پراکنده (فیلدها در کارت چندستونه با برچسب، حداقل اندازهٔ جدول و فهرست کشویی، توضیح گزارش با «…»)."""
import os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r317_ui"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prd_fixture import *  # noqa: F401,F403
from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import (QApplication, QComboBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QScroller, QScrollArea,
                               QAbstractSpinBox, QTableWidget, QVBoxLayout, QWidget)

app = QApplication.instance() or QApplication([])
from peecha.ui import app_style, layout_guard, theme, touch

app_style.install(app)

# --- ۳: حالت لمسی ---------------------------------------------------------------------------------------------
touch.save_mode("off")
check(not touch.resolve() and touch.resolve("on") and touch.saved_mode() == "off", "mode resolution (off / on)")
check(touch.resolve("auto") == touch.has_touchscreen(), "auto follows touchscreen detection")
host = QWidget(); lay = QVBoxLayout(host)
table = QTableWidget(5, 2); table.setContextMenuPolicy(Qt.CustomContextMenu)
button = QPushButton("💾"); button.setToolTip("ذخیره")
lay.addWidget(table); lay.addWidget(button)
host.show(); app.processEvents()
check(not QScroller.hasScroller(table.viewport()), "no kinetic scrolling while touch mode is off")
touch.apply(app, True)
app.processEvents()
check(touch.is_enabled() and "حالت لمسی" in app.styleSheet(), "touch stylesheet applied app-wide")
check(QScroller.hasScroller(table.viewport()) or table.property("touch_ready"), "kinetic finger scrolling on tables")
check(table.verticalHeader().defaultSectionSize() >= touch.ROW_HEIGHT, f"taller rows ({table.verticalHeader().defaultSectionSize()})")
requested = []
table.customContextMenuRequested.connect(lambda pos: requested.append(pos))
touch.long_press(table.viewport(), QPoint(10, 10))
check(requested, "long press opens the context menu")
touch.long_press(button, QPoint(5, 5))
from PySide6.QtWidgets import QToolTip
check(QToolTip.text() == "ذخیره", f"long press on an icon button shows its title ({QToolTip.text()!r})")
late = QTableWidget(2, 2); late.show(); app.processEvents()
check(late.property("touch_ready"), "tables opened later get touch support too")
touch.apply(app, False)
check(not touch.is_enabled() and "حالت لمسی" not in app.styleSheet() and not table.property("touch_ready"),
      "touch mode can be turned off again")
touch.save_mode("auto")

from peecha.ui.shell_window import MainWindow

mw = MainWindow(); mw.resize(1400, 900); mw.show(); app.processEvents()
check(hasattr(mw, "touch_toggle") and mw.touch_toggle.isCheckable() and "لمسی" in mw.touch_toggle.toolTip(),
      "touch switch in the top bar")
mw.touch_toggle.setChecked(True); app.processEvents()
check(touch.is_enabled() and touch.saved_mode() == "on", "switch turns touch mode on and remembers it")
mw.touch_toggle.setChecked(False) if hasattr(mw, "touch_toggle") and mw.touch_toggle.isChecked() else None
app.processEvents()
toggle = mw.touch_toggle
if toggle.isChecked():
    toggle.setChecked(False)
app.processEvents()
check(not touch.is_enabled() and touch.saved_mode() == "off", "switch turns it off")
touch.save_mode("auto")

# --- ۷: حداقل اندازه و فرم‌های مرتب -------------------------------------------------------------------------------
scroll_host = QScrollArea(); scroll_host.setWidgetResizable(True)
body = QWidget(); bl = QVBoxLayout(body)
squeezed = QTableWidget(3, 2); small_combo = QComboBox(); small_combo.addItems(["همه", "باز"])
capped = QTableWidget(2, 2); capped.setMaximumHeight(80)
for w in (squeezed, small_combo, capped):
    bl.addWidget(w)
for _ in range(8):
    bl.addWidget(QTableWidget(2, 2))
scroll_host.setWidget(body); scroll_host.resize(600, 300); scroll_host.show(); app.processEvents()
check(squeezed.minimumHeight() >= layout_guard.TABLE_MIN_HEIGHT and squeezed.height() >= layout_guard.TABLE_MIN_HEIGHT,
      f"tables are not squeezed to a sliver ({squeezed.height()})")
check(capped.minimumHeight() <= 80, "an intentional maximum height is respected")
check(small_combo.minimumWidth() >= layout_guard.COMBO_MIN_WIDTH, "drop-downs get a readable minimum width")
small_combo.showPopup(); app.processEvents()
check(small_combo.view().minimumHeight() < layout_guard.TABLE_MIN_HEIGHT, "drop-down popup lists are not enlarged")
small_combo.hidePopup()

INPUTS = (QLineEdit, QComboBox, QAbstractSpinBox)


def long_rows(root):
    found = []

    def walk(layout):
        if isinstance(layout, QHBoxLayout):
            ws = [layout.itemAt(i).widget() for i in range(layout.count()) if layout.itemAt(i).widget() is not None]
            n = sum(1 for w in ws if isinstance(w, INPUTS) or type(w).__name__ in ("JalaliDateEdit", "NumberEdit"))
            if n >= 5:
                found.append(n)
        for i in range(layout.count()):
            if layout.itemAt(i).layout() is not None:
                walk(layout.itemAt(i).layout())
    for w in [root] + root.findChildren(QWidget):
        if w.layout() is not None:
            walk(w.layout())
    return found


def captions(root):
    return {l.text() for l in root.findChildren(QLabel) if l.objectName() == "fieldCaption"}


from peecha.ui.screens import procurement_masters as pm, costing as cost_ui, warehouse_operations as wo
from peecha.ui.screens.commercial_pricing import CommercialPricingScreen
from peecha.ui.screens.commercial_coupons import CommercialCouponsScreen

budgets = pm._BudgetsTab(); budgets.refresh()
check(not long_rows(budgets) and {"کد", "نام", "مبلغ", "درصد هشدار", "مرکز هزینه"} <= captions(budgets),
      f"purchase budget form in a labelled grid ({sorted(captions(budgets))})")
check(budgets.code_field is not None and budgets.warn_spin.value() == 90 and budgets.active_check.isChecked(), "same fields kept")
reorder = pm._ReorderPoliciesTab(); reorder.refresh()
check(not long_rows(reorder) and {"کالا", "حداقل", "نقطهٔ سفارش", "زمان تحویل (روز)"} <= captions(reorder), "reorder policy grid")
for screen_cls, expect in ((cost_ui.ReplacementCostScreen, {"کالا", "بها", "از تاریخ"}),
                           (cost_ui.RecalculationScreen, {"کالا", "تاریخ ثبت", "علت"})):
    scr = screen_cls()
    check(not long_rows(scr) and expect <= captions(scr), f"{screen_cls.__name__} in a labelled grid")
plans, rep = wo._PlansTab(), wo._ReplenishTab()
check(not long_rows(plans) and {"کد", "نام", "دامنه", "تواتر"} <= captions(plans), "count plans: code/name now labelled")
check(not long_rows(rep) and {"انبار", "محل", "کالا", "حداقل", "حداکثر"} <= captions(rep), "replenish rules grid")
pricing = CommercialPricingScreen()
check({"کد", "نام", "نوع", "مقدار/درصد", "اولویت"} <= captions(pricing), "discount rule and price list fields labelled")
coupons = CommercialCouponsScreen()
check(not long_rows(coupons) and {"کد کوپن", "نوع تخفیف", "مقدار", "معتبر تا"} <= captions(coupons), "coupon form labelled")
from peecha.ui.screens.commercial_cms import CommercialCmsScreen
from peecha.ui.screens.commercial_social import CommercialSocialScreen

for cls, expect in ((CommercialCmsScreen, {"پلتفرم", "آدرس سایت", "رمز برنامه"}), (CommercialSocialScreen, {"پیام‌رسان", "توکن ربات"})):
    scr = cls()
    check(not long_rows(scr) and expect <= captions(scr), f"{cls.__name__} connection form labelled")

from peecha.ui.widgets import ElidedLabel

hint = ElidedLabel("توضیح بسیار بلند یک گزارش که در کنار عنوان جا نمی‌شود و باید با سه نقطه کوتاه شود")
hint.resize(150, 24); hint.show(); app.processEvents()
check(hint.text().endswith("کوتاه شود") and QLabel.text(hint).endswith("…") and hint.toolTip() == hint.text(),
      "long report description ends with … and keeps the full text in the tooltip")

finish()
