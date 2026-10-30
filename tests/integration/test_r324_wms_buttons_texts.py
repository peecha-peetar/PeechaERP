"""R324: دکمه‌های نقشه و عملیات انبار که تیک دکمه را به‌جای مقدار می‌فرستادند (چاپ برچسب، مسیر، تکمیل وظیفه، ثبت شمارش)
و متن‌های ساده به‌جای «جانمایی/برداشت»."""
import os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r324_wms"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crm_fixture import *  # noqa: F401,F403
import crm_fixture as fx

from PySide6.QtWidgets import QApplication, QInputDialog, QMessageBox, QPushButton

app = QApplication.instance() or QApplication([])
QMessageBox.warning = staticmethod(lambda *a, **k: None)
QMessageBox.information = staticmethod(lambda *a, **k: None)
from peecha.db.models.inventory import WarehouseTask
from peecha.services import inventory_documents as inv_docs
from peecha.services import warehouse_locations as wl
from peecha.services import warehouse_operations as ops
from peecha import numerals
from peecha.services.workflow import inbox
check, raises = fx.check, fx.raises

g_l = A("2", "بدهی‌ها", "CREDIT", "LIABILITY", "PERMANENT", False)
k_l = A("21", "پرداختنی‌ها", "CREDIT", "LIABILITY", "PERMANENT", False, g_l.account_id)
ap_gl = A("2101", "پرداختنی تامین‌کنندگان", "CREDIT", "LIABILITY", "PERMANENT", True, k_l.account_id)
engine_service.set_account_mapping(company_id, "SUPPLIER_PAYABLE", ap_gl.account_id)
supplier = dimensions_service.create_supplier(company_id, "S1", "تامین‌کننده")
whn = locations_service.create_warehouse(company_id, "WH-N", "انبار اصلی", locations_service.WarehouseFields())
zone = wl.create_location(company_id, whn, "AREA", "Z01")
rack = wl.create_location(company_id, whn, "RACK", "R01", zone)
shelf = wl.create_location(company_id, whn, "SHELF", "L01", rack)
b1, b2 = [wl.create_location(company_id, whn, "BIN", f"B0{i}", shelf) for i in (1, 2)]

d = inv_docs.create_stock_document(company_id, uid, "RECEIPT", today, inv_docs.DocumentHeaderFields(
    destination_warehouse_id=whn, counterparty_detail_account_id=supplier))
inv_docs.add_line(d, company_id, inv_docs.LineFields(item_id=item_a, uom_id=pcs, quantity=D(20), quantity_base=D(20),
                                                     unit_cost=D(1000), bin_location_id=b1))
inv_docs.confirm_stock_document(d, company_id)
inv_docs.post_stock_document(d, company_id, uid)
issue = inv_docs.create_stock_document(company_id, uid, "ISSUE", today, inv_docs.DocumentHeaderFields(source_warehouse_id=whn))
inv_docs.add_line(issue, company_id, inv_docs.LineFields(item_id=item_a, uom_id=pcs, quantity=D(5), quantity_base=D(5), bin_location_id=b1))

# --- ۱۸: متن کارتابل --------------------------------------------------------------------------------------
check(inbox.DOC_ACTIONS["PUTAWAY_PENDING"].startswith("کالای رسیده را در قفسه بچینید")
      and "برداشت" not in inbox.DOC_ACTIONS["CROSS_DOCK"], "cartable says plainly what to do with received goods")
check(ops.TASK_TYPES == {"PUTAWAY": "چیدن در قفسه", "PICK": "جمع‌آوری کالا", "REPLENISH": "تامین مجدد"},
      f"task kinds in plain words ({ops.TASK_TYPES})")

# --- ۱۹، ۲۰: نقشهٔ انبار -----------------------------------------------------------------------------------
from peecha.ui import location_labels
from peecha.ui.screens import warehouse_map as wm

printed = []
location_labels.print_location_labels = lambda parent, labels, printer=None: printed.append(labels) or True
scr = wm.WarehouseMapScreen(None)
scr.refresh()
scr.load_warehouse(whn)
tool = {b.toolTip().split(" --")[0]: b for b in scr.findChildren(QPushButton)}
check("چاپ برچسب" in tool and "مسیر جمع‌آوری کالا" in tool, f"map tools ({sorted(k for k in tool if k)[:12]})")
scr.select_location(shelf)
tool["چاپ برچسب"].click()
check(printed and {lid for lid, _c, _t in printed[0]} >= {b1, b2}, f"«print labels» button prints the selected shelf's labels ({printed})")
tool["مسیر جمع‌آوری کالا"].click()
msg = scr.status_label.text()
check("بازی" not in msg and "جمع‌آوری انجام‌نشده" in msg, f"path with no pick work: a clear sentence ({msg})")
pick = ops.generate_tasks(company_id, "PICK", ("STOCK", issue), uid)[0]
tool["مسیر جمع‌آوری کالا"].click()
check(scr.path_item is not None and "مسیر" in scr.status_label.text(), "path button draws the route of open pick work")

# --- دکمهٔ «تکمیل…» وظیفه مقدار را می‌پرسد (قبلاً صفر ثبت می‌شد) -------------------------------------------------
from peecha.ui.screens import warehouse_operations as wo

asked = []
QInputDialog.getDouble = staticmethod(lambda *a, **k: (asked.append(a[1:3]) or 5.0, True))
tab = wo._TasksTab()
tab.refresh()
tab.type_combo.setCurrentIndex(tab.type_combo.findData("PICK"))
tab._load()
row = next(r for r in range(tab.table.rowCount()) if tab.table.item(r, 0).text() == numerals.to_persian_digits(str(pick)))
tab.table.setCurrentCell(row, 0)
done_btn = next(b for b in tab.findChildren(QPushButton) if (b.property("label") or b.toolTip() or b.text()).startswith("تکمیل"))
done_btn.click()
with new_session() as s:
    t = s.get(WarehouseTask, pick)
check(asked and t.status_code == "DONE" and t.done_quantity_base == 5, f"«complete» asks the quantity and records it ({asked}, {t.done_quantity_base})")
labels = " ".join(b.toolTip() for b in tab.findChildren(QPushButton))
check("برداشت" not in labels and "جانمایی" not in labels, "no jargon on the task buttons")

finish()
