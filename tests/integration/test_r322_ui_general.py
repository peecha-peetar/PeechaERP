"""R322: فلش کمبوباکس، فقط آخرین سطح مرکز هزینه/پروژه، کنترل لحظه‌ای ورود، رقم فارسی و سه‌رقمی زنده در فیلدهای مبلغ،
دکمه‌های آیکونی تایید/انصراف پایین راست، و ردیف اول سند که پس از ثبت کم‌رنگ/درهم می‌شد."""
import os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r322"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prd_fixture import *  # noqa: F401,F403

import datetime as dt
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QComboBox, QDialog, QDialogButtonBox, QMessageBox, QStyle, QVBoxLayout

app = QApplication.instance() or QApplication([])
app.setLayoutDirection(Qt.RightToLeft)
QMessageBox.warning = staticmethod(lambda *a, **k: None)
QMessageBox.information = staticmethod(lambda *a, **k: None)
from peecha.ui import app_style, theme

app_style.install(app)
theme.set_theme_mode(app, False)

# --- ۸: فلش کمبوباکس ------------------------------------------------------------------------------------
qss = app.styleSheet()
arrow = qss[qss.find("QComboBox::down-arrow"):].split("url(\"", 1)[1].split("\"", 1)[0]
check(Path(arrow).exists() and "stroke" in Path(arrow).read_text(), f"combo arrow drawn in the theme colour ({arrow})")
theme.set_theme_mode(app, True)
dark_arrow = app.styleSheet().split("QComboBox::down-arrow")[1].split("url(\"", 1)[1].split("\"", 1)[0]
check(dark_arrow != arrow or theme.TEXT_SECONDARY.lower() in arrow, "arrow follows the theme")
theme.set_theme_mode(app, False)

# --- ۱۶: دکمه‌های پنجره‌ها ----------------------------------------------------------------------------------
dlg = QDialog()
box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
QVBoxLayout(dlg).addWidget(box)
dlg.show()
app.processEvents()
app.processEvents()
ok, cancel = box.button(QDialogButtonBox.Ok), box.button(QDialogButtonBox.Cancel)
check(ok.text() == "✅" and ok.toolTip().startswith("تایید") and cancel.text() == "✖️" and cancel.toolTip().startswith("انصراف"),
      f"OK/Cancel are icons with Persian tooltips ({ok.text()} {ok.toolTip()} / {cancel.text()} {cancel.toolTip()})")
check(box.layoutDirection() == Qt.LeftToRight and ok.geometry().x() > cancel.geometry().x()
      and ok.geometry().right() > box.width() * 0.7, "buttons sit bottom-right, confirm right-most")
check(app.style().styleHint(QStyle.SH_DialogButtonLayout) == QDialogButtonBox.MacLayout.value, "dialog button layout hint")
msg = QMessageBox(QMessageBox.Question, "تایید", "این ردیف حذف شود؟", QMessageBox.Yes | QMessageBox.No)
msg.show()
app.processEvents()
app.processEvents()
tips = {b.text(): b.toolTip() for b in msg.buttons()}
check(tips.get("✅", "").startswith("بله") and tips.get("✖️", "").startswith("خیر"), f"message box buttons iconized ({tips})")
msg.close()
dlg.close()

# --- ۱۲ و ۱۰: فیلد عددی ------------------------------------------------------------------------------------
from peecha.ui.persian_numbers import NumberEdit

edit = NumberEdit()
edit.show()
edit.setFocus()
QTest.keyClicks(edit, "12a3b4.5x")
check(edit.displayText() == "۱,۲۳۴.۵" and edit.text() == "۱۲۳۴.۵", f"letters rejected while typing, live grouping ({edit.displayText()})")
from peecha.ui.screens.inventory_warehouses import InventoryWarehousesScreen
from peecha.ui.screens.currencies import CurrenciesScreen

check(isinstance(InventoryWarehousesScreen().default_tax_percent_field, NumberEdit), "warehouse tax percent is a numeric field")
check(isinstance(CurrenciesScreen().rate_value_field, NumberEdit), "currency rate is a numeric field")

from peecha.ui.screens.purchase_requests import PurchaseRequestScreen

pr = PurchaseRequestScreen()
pr.show()
pr.refresh()
pr.date_field.setDate(today)
pr.required_field.setDate(today - dt.timedelta(days=3))
pr.required_field.editingFinished.emit()
check(pr.required_field.property("invalid") and "پیش از تاریخ درخواست" in pr.status_label.text(),
      "required date before request date flagged on leaving the field")
pr.required_field.setDate(today + dt.timedelta(days=3))
pr.required_field.editingFinished.emit()
check(not pr.required_field.property("invalid") and pr.status_label.text() == "", "flag cleared once corrected")
pr.item_combo.setCurrentIndex(pr.item_combo.findData(pk))
pr.qty_field.setText("2.5")
pr.qty_field.editingFinished.emit()
check(pr.qty_field.property("invalid"), f"fractional quantity of a count unit flagged immediately ({pr.qty_field.toolTip()})")
pr.qty_field.setText("0")
pr.qty_field.editingFinished.emit()
check("بزرگ‌تر از صفر" in pr.qty_field.toolTip(), "zero quantity flagged immediately")

# --- ۹: فقط آخرین سطح مرکز هزینه/پروژه ----------------------------------------------------------------------
cc_type = dimensions_service.get_specialized_dimension_type_id(company_id, dimensions_service.COST_CENTER_CODE)
from peecha.db.models.accounting import DetailAccount

parent = dimensions_service.create_detail_account(company_id, cc_type, "CC-P", "گروه تولید")
with new_session() as s:  # زیرمجموعه مستقیم (گروه مرکز هزینهٔ فیکسچر یک‌سطحی است)
    row = DetailAccount(company_id=company_id, dimension_type_id=cc_type, code="CC-C", name="خط مونتاژ",
                        parent_detail_account_id=parent.detail_account_id, level_no=2, extra_fields={})
    s.add(row)
    s.commit()
    s.refresh(row)
    s.expunge(row)
    child = row
from peecha.ui.screens.fixed_assets import Lookups, combo, set_combo
from peecha.ui.screens import production as prd_ui

lk = Lookups(company_id)
ids = {d for _l, d in lk.cost_centers}
check(child.detail_account_id in ids and parent.detail_account_id not in ids, "fixed assets offer only the last level")
check(parent.detail_account_id in prd_ui.PrdLookups(company_id).cost_centers.legacy
      and parent.detail_account_id not in {d for _l, d in prd_ui.PrdLookups(company_id).cost_centers}, "production too")
box_cc = combo(lk.cost_centers, "—")
set_combo(box_cc, parent.detail_account_id)
check(box_cc.currentData() == parent.detail_account_id, "an old upper-level value stays visible when editing")
pr.refresh()
check(pr.cost_center_combo.findData(parent.detail_account_id) < 0 and pr.cost_center_combo.findData(child.detail_account_id) >= 0,
      "purchase request: only last level")

# --- ۱۷: ردیف اول سند پس از افزودن ------------------------------------------------------------------------
from peecha.services import commercial_documents as documents_service
from peecha.ui.screens.commercial_document import CommercialDocumentScreen

doc = documents_service.create_document(company_id, uid, "PURCHASE_ORDER", today, documents_service.DocumentHeaderFields(
    counterparty_detail_account_id=supplier, currency_id=company.base_currency_id))
scr = CommercialDocumentScreen("PURCHASE_ORDER", None)
scr.edit_document(doc)
check(scr.lines_table.cellWidget(0, 1) is not None, "empty order: entry row at the top")
documents_service.add_line(doc, company_id, r1, kg, D(3), D(3), unit_price=D(100))
scr.edit_document(doc)
check(scr.lines_table.cellWidget(0, 1) is None and scr.lines_table.item(0, 1).text().startswith("RM-1")
      and scr.lines_table.cellWidget(0, 8) is None, "first saved row has no leftover entry widgets on top of it")
check(scr.lines_table.cellWidget(1, 1) is not None, "entry row moved below")

finish()
