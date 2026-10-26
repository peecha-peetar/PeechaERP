"""R341: در فرم تعریف تفصیلی، کلیک روی یک ردیف «بازکردن حساب تفصیلی موجود» برنامه را می‌انداخت (درخت پیش از پایان کلیک
بازسازی و ردیف کلیک‌شده پاک می‌شد). حالا حساب در فرم باز می‌شود و پنجره بسته می‌شود؛ برای گروه تفصیلی و گروه اشخاص."""
import os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r341"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prd_fixture import *  # noqa: F401,F403

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

app = QApplication.instance() or QApplication([])
QMessageBox.warning = staticmethod(lambda *a, **k: None)

from peecha.services import detail_dimensions as dims
from peecha.ui.screens.detail_dimensions import DetailDimensionsScreen

cc_type = dims.get_specialized_dimension_type_id(company_id, dims.COST_CENTER_CODE)
dims.create_detail_account(company_id, cc_type, "C1", "واحد یک")
c2 = dims.create_detail_account(company_id, cc_type, "C2", "واحد دو").detail_account_id
s2 = dims.create_supplier(company_id, "S2", "تامین‌کنندهٔ دوم")

scr = DetailDimensionsScreen()
scr.show()


def click_row(group, detail_id):
    scr.select_type_for_new_entry(group)
    scr._rebuild_accounts_tree()
    dialog = scr._account_picker_dialog
    dialog.show()
    app.processEvents()
    tree = scr.accounts_table
    item = next(tree.topLevelItem(i) for i in range(tree.topLevelItemCount())
                if tree.topLevelItem(i).data(0, Qt.UserRole) == detail_id)
    QTest.mouseClick(tree.viewport(), Qt.LeftButton, Qt.NoModifier, tree.visualItemRect(item).center())
    for _ in range(3):
        app.processEvents()
    return dialog


dialog = click_row(("dim", cc_type), c2)
check(scr._editing_account_id == c2 and scr.account_name_field.text() == "واحد دو" and not dialog.isVisible(),
      "clicking a cost center row opens it in the form and closes the picker")
dialog = click_row(("person", dims.SUPPLIER_GROUP_CODE), s2)
check(scr._editing_account_id == s2 and scr.account_name_field.text() == "تامین‌کنندهٔ دوم" and not dialog.isVisible(),
      "clicking a supplier row opens it too")
dialog = click_row(("dim", cc_type), c2)
check(scr._editing_account_id == c2, "the picker can be used again after a click")

finish()
