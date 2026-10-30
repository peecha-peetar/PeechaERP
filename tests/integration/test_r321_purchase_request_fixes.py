"""R321: درخواست خرید — نمایش در اسناد خرید، اندازهٔ فیلدها، ذخیرهٔ عرض ستون، لغو/رد، پیمایش با Enter،
تبدیل به سفارش به تفکیک تامین‌کننده یا یکجا، پاک‌شدن ردیف‌ها با خام‌کردن داده، و فقط کالای قابل‌خرید در فرم‌های خرید."""
import os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r321"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prd_fixture import *  # noqa: F401,F403

import datetime as dt

from PySide6.QtCore import QSettings, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QInputDialog, QMessageBox, QPushButton

app = QApplication.instance() or QApplication([])
QMessageBox.warning = staticmethod(lambda *a, **k: None)
QMessageBox.information = staticmethod(lambda *a, **k: None)
from peecha.ui import app_style

app_style.install(app)

from peecha.db.models.commercial import PurchaseRequest, PurchaseRequestLine
from peecha.services import data_reset
from peecha.services import purchase_requests as prs
from peecha.ui.persian_numbers import NumberEdit
from peecha.ui.screens.procurement_dialogs import CancellationReasonDialog
from peecha.ui.screens.purchase_requests import ConvertToOrderDialog, PurchaseRequestScreen

s2 = dimensions_service.create_supplier(company_id, "S2", "تامین‌کنندهٔ دوم")
blocked = item("NP-1", "کالای غیرخریدنی", "GOOD", is_purchasable=False)
cc_type = dimensions_service.get_specialized_dimension_type_id(company_id, dimensions_service.COST_CENTER_CODE)
QSettings("Peecha", "PeechaERP").remove("columnWidths/purchaseRequest")

# --- ۲، ۵، ۱۱: فرم — اندازهٔ فیلدها، Enter، فقط کالای قابل‌خرید ------------------------------------------
scr = PurchaseRequestScreen()
scr.resize(1500, 950)
scr.show()
scr.refresh()
app.processEvents()
check(scr.item_combo.findData(blocked) < 0 and scr.item_combo.findData(r1) >= 0, "only purchasable items offered")
check(isinstance(scr.qty_field, NumberEdit) and isinstance(scr.price_field, NumberEdit)
      and scr.qty_field.minimumWidth() >= 130 and scr.price_field.minimumWidth() >= 160, "quantity/price fields wide enough")
scr.price_field.setFocus()
QTest.keyClicks(scr.price_field, "1250000")
check(scr.price_field.displayText() == "۱,۲۵۰,۰۰۰" and scr.price_field.text() == "۱۲۵۰۰۰۰",
      f"price typed with Persian digits and live grouping ({scr.price_field.displayText()})")
scr.price_field.clear()
scr.date_field.setFocus()
QTest.keyClick(scr.date_field, Qt.Key_Return)
check(QApplication.focusWidget() is scr.required_field, "Enter moves from date to the next header field")
scr.description_field.setFocus()
QTest.keyClick(scr.description_field, Qt.Key_Return)
check(QApplication.focusWidget() in (scr.item_combo, scr.item_combo.lineEdit()), "Enter from the last header field goes to the item")
check(not [b.text() for b in scr.findChildren(QPushButton) if b.text() and any("؀" <= ch <= "ۿ" for ch in b.text())],
      "form buttons are icon-only")

# ثبت درخواست از فرم با Enter در آخرین فیلد ردیف
scr.new_request()
scr.description_field.setText("نیاز تولید")
scr.item_combo.setCurrentIndex(scr.item_combo.findData(r1))
scr.qty_field.setText("12")
scr.price_field.setText("95000")
scr.supplier_combo.setCurrentIndex(scr.supplier_combo.findData(supplier))
scr.line_description_field.setFocus()
QTest.keyClick(scr.line_description_field, Qt.Key_Return)
app.processEvents()
check(scr._request_id is not None and scr.lines_table.rowCount() == 1, "Enter in the last row field adds the row")
scr.item_combo.setCurrentIndex(scr.item_combo.findData(r2))
scr.qty_field.setText("5")
scr.supplier_combo.setCurrentIndex(scr.supplier_combo.findData(s2))
scr.add_line()
scr.item_combo.setCurrentIndex(scr.item_combo.findData(pk))
scr.qty_field.setText("3")
scr.supplier_combo.setCurrentIndex(0)
scr.add_line()
check(scr.lines_table.rowCount() == 3, "three rows")
scr.edit_line(1)
check(not scr.item_combo.isEnabled() and scr.qty_field.text() == "۵", "double-click loads the row for editing")
scr.qty_field.setText("7")
scr.add_line()
_row, lines = prs.get_request(scr._request_id, company_id)
check(lines[1].quantity == 7 and len(lines) == 3, "row edited in place")

# --- ۳: عرض ستون‌ها ذخیره می‌شود ---------------------------------------------------------------------------
scr.lines_table.setColumnWidth(2, 222)
app.processEvents()
check(QSettings("Peecha", "PeechaERP").value("columnWidths/purchaseRequest/lines/2", type=int) == 222, "column width saved")
scr2 = PurchaseRequestScreen()
check(scr2.lines_table.columnWidth(2) == 222, "column width restored in a new form")

# --- ۹: فقط سطح آخر مرکز هزینه --------------------------------------------------------------------------
scr.refresh()
leaf_ids = {d.detail_account_id for d in dimensions_service.list_leaf_detail_accounts(company_id, cc_type)}
offered = {scr.cost_center_combo.itemData(i) for i in range(scr.cost_center_combo.count())} - {None}
check(offered <= leaf_ids, "cost center combo offers only last-level centers")

# --- ۴: رد و لغو از دکمه‌ها --------------------------------------------------------------------------------
req = scr._request_id
scr.buttons["submit"].click()
QInputDialog.getText = staticmethod(lambda *a, **k: ("قیمت‌ها نیاز به بررسی دارد", True))
scr.buttons["reject"].click()
check(prs.get_request(req, company_id)[0].status_code == "REJECTED", "reject button asks for the reason and rejects")
scr.buttons["submit"].click()
scr.buttons["approve"].click()
check(scr._status == "APPROVED", "submit and approve from the buttons")

# --- ۶: تبدیل به سفارش -------------------------------------------------------------------------------------
_row, lines = prs.get_request(req, company_id)
dlg = ConvertToOrderDialog(scr, scr._suppliers, lines, {}, scr._items)
groups, errors = dlg.plan()
check(errors and "همهٔ ردیف‌ها" in errors[0], "split mode: a row without supplier blocks conversion")
dlg.line_supplier_combos[2].setCurrentIndex(dlg.line_supplier_combos[2].findData(supplier))
groups, errors = dlg.plan()
check(not errors and groups == {supplier: 2, s2: 1} and dlg.preview_label.text().startswith("۲ سفارش"),
      f"split mode: one order per supplier ({dlg.preview_label.text()})")
dlg.single_radio.setChecked(True)
groups, errors = dlg.plan()
check(not errors and groups == {supplier: 3} and dlg.selected_supplier() == supplier, "single mode: all rows in one order")
created = scr.convert(ask=False, line_suppliers=dlg.line_suppliers())
check(len(created) == 2, "split conversion creates two purchase orders")
by_supplier = {documents_service_doc.counterparty_detail_account_id for documents_service_doc in prs.linked_orders(req)}
check(by_supplier == {supplier, s2}, "each order belongs to its supplier")

req2 = prs.create_request(company_id, uid, prs.RequestFields(request_date=today))
for it, sup in ((r1, supplier), (r2, s2)):
    prs.add_line(req2, company_id, it, base_uom(it), D(2), None, sup, D(10))
prs.submit_request(req2, company_id)
prs.approve_request(req2, company_id, uid)
one = prs.convert_to_orders(req2, company_id, uid, supplier_id=s2)
check(len(one) == 1 and prs.linked_orders(req2)[0].counterparty_detail_account_id == s2,
      "single order with one supplier despite different suggested suppliers")

req3 = prs.create_request(company_id, uid, prs.RequestFields(request_date=today))
prs.add_line(req3, company_id, r3, base_uom(r3), D(1), None, supplier, D(10))
prs.submit_request(req3, company_id)
prs.approve_request(req3, company_id, uid)
scr.edit_document(req3)
CancellationReasonDialog.auto_answer = (0, "")
scr.buttons["cancel"].click()
CancellationReasonDialog.auto_answer = None
check(prs.get_request(req3, company_id)[0].status_code == "CANCELLED", "approved request cancelled from the button")

# --- ۱: درخواست در «اسناد خرید» -------------------------------------------------------------------------
from peecha.ui.screens.commercial_documents_list import CommercialDocumentsListScreen


class FakeMain:
    calls = []

    def open_screen(self, code, then=None):
        self.calls.append(code)
        if then is not None:
            then(scr)


lst = CommercialDocumentsListScreen(FakeMain(), type_filter_codes=(
    "PURCHASE_ORDER", "PURCHASE_PROFORMA", "PURCHASE_INVOICE", "PURCHASE_RETURN", "CONSIGNMENT_IN"))
lst.refresh()
types = [lst.table.item(r, 1).text() for r in range(lst.table.rowCount())]
check(types.count("درخواست خرید") == 3 and types.count("سفارش خرید") == 3, f"purchase requests listed with purchase documents ({types})")
lst.type_filter.setCurrentIndex(lst.type_filter.findData("PURCHASE_REQUEST"))
check(lst.table.rowCount() == 3, "filter: only purchase requests")
lst.status_filter.setCurrentIndex(lst.status_filter.findData("CANCELLED"))
check(lst.table.rowCount() == 1 and lst.table.item(0, 6).text() == "لغوشده", "status filter works for requests")
lst._on_row_double_clicked(0, 0)
check(FakeMain.calls[-1] == "PURCH_REQUESTS" and scr._request_id == req3, "double-click opens the request in its form")
sales = CommercialDocumentsListScreen(None, type_filter_codes=("SALES_ORDER", "SALES_INVOICE"))
sales.refresh()
check(sales.type_filter.findData("PURCHASE_REQUEST") < 0, "sales list unchanged")

# --- ۱۱: فرم سفارش خرید فقط کالای قابل‌خرید ---------------------------------------------------------------
from peecha.ui.screens.commercial_document import _LineDialog, _pickable_items

items = catalog_service.list_items(company_id, active_only=True)
check(blocked not in {i.item_id for i in _pickable_items(items, "PURCHASE_ORDER")}
      and blocked in {i.item_id for i in _pickable_items(items, "SALES_ORDER")}, "purchase picker excludes non-purchasable items")
line_dlg = _LineDialog(None, items, company_id, None, 0, document_type_code="PURCHASE_INVOICE")
check(line_dlg.item_combo.findData(blocked) < 0 and line_dlg.item_combo.findData(r1) >= 0, "purchase invoice row dialog")
edit_dlg = _LineDialog(None, items, company_id, None, 0, {"item_id": blocked, "quantity": D(1), "unit_price": D(1),
                                                          "discount_amount": D(0), "discount_percent": D(0), "tax_percent": D(0),
                                                          "description": None, "warehouse_id": None, "uom_id": pcs},
                       document_type_code="PURCHASE_INVOICE")
check(edit_dlg.item_combo.findData(blocked) >= 0, "an existing row keeps its item when edited")

# --- ۷: خام‌کردن داده ردیف‌های درخواست را هم پاک می‌کند --------------------------------------------------
scr.edit_document(req2)
data_reset.wipe_documents(company_id)
with new_session() as s:
    left_headers = s.scalar(select(func.count()).select_from(PurchaseRequest).where(PurchaseRequest.company_id == company_id))
    left_lines = s.scalar(select(func.count()).select_from(PurchaseRequestLine))
check(left_headers == 0 and left_lines == 0, f"reset removes request headers and rows ({left_headers}, {left_lines})")
scr.refresh()
check(scr._request_id is None and scr.lines_table.rowCount() == 0 and scr.list_table.rowCount() == 0,
      "open form shows no stale rows after the reset")

finish()
