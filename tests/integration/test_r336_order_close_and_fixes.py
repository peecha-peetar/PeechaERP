"""R336: تایید تولید با حساب کالای در جریان ساخت که تفصیلی کالا می‌خواهد، تخفیف ردیف از مبلغی به درصدی، دکمه‌های آیکونی
پنجرهٔ ردیابی و تبدیل به فاکتور، پرسش «آیا فاکتور نسیه است؟»، اتمام/بازگشایی سفارش نیمه‌تمام، و «جدید» به‌جای «تازه»."""
import ast, os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r336"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prd_fixture import *  # noqa: F401,F403

from PySide6.QtWidgets import QApplication, QDialogButtonBox, QMessageBox, QPushButton

app = QApplication.instance() or QApplication([])
from peecha.ui import app_style, icon_buttons

app_style.install(app)
asked: list[str] = []
answer = {"q": QMessageBox.Yes}
QMessageBox.warning = staticmethod(lambda *a, **k: print("WARN", a[2] if len(a) > 2 else a))
QMessageBox.information = staticmethod(lambda *a, **k: None)
QMessageBox.question = staticmethod(lambda *a, **k: (asked.append(a[2]), answer["q"])[1])

from peecha.services import commercial_documents as ds
from peecha.services import commercial_settlements as settlements
from peecha.services import detail_dimensions as dims
from peecha.services import purchase_reports
from peecha.services.production import common as pc, costing as pcost, master as pm, orders as po

# --- ۶) تایید تولید: حساب «کالای در جریان ساخت» با تفصیلی کالای الزامی ------------------------------------------------
pc.update_settings(company_id, uid, default_material_warehouse_id=wh_rm, default_fg_warehouse_id=wh_fg,
                   default_scrap_warehouse_id=wh_scrap, auto_cost_calculation=True)
item_dim = dims.get_specialized_dimension_type_id(company_id, dims.INVENTORY_ITEM_CODE)
for acc in (wip_gl, inv_gl):
    dims.set_account_dimension_types(acc.account_id, company_id, [item_dim])
wc = pm.save_work_center(company_id, pm.WorkCenterFields(code="CUT", name="برش", labor_rate=D(500000),
                                                        machine_rate=D(800000), overhead_rate=D(200000)))
px = item("PX", "محصول X", "FINISHED_GOOD")
rt = pm.create_routing(company_id, px, "مسیر", [pm.RoutingOpFields(10, "برش", wc, run_minutes=D(6), machine_minutes=D(12))])
bom = pm.create_bom_version(company_id, px, pm.BomFields(batch_size_qty=D(1), routing_id=rt))
pm.add_bom_component(company_id, bom, pm.BomLineFields(r1, D(1)))
receive(r1, 1000, 10000)
order = po.create_order(company_id, uid, po.OrderFields(item_id=px, planned_qty=D(100)))
po.release_order(company_id, uid, order)
po.start_order(company_id, uid, order)
op = po.order_view(company_id, order).operations[0].order_operation_id
steps = [("issue", lambda: po.issue_all_remaining(company_id, uid, order)),
         ("labor", lambda: pcost.record_labor(company_id, uid, order, pcost.LaborInput(hours=D(10), order_operation_id=op))),
         ("machine", lambda: pcost.record_machine(company_id, uid, order, pcost.MachineInput(hours=D(5), order_operation_id=op))),
         ("receipt", lambda: po.report_production(company_id, uid, order, po.ReceiptInput(D(40), {}))),
         ("complete", lambda: po.complete_order(company_id, uid, order, po.ReceiptInput(D(55), {}))),
         ("close", lambda: po.close_order(company_id, uid, order))]
failed = []
for name, fn in steps:
    try:
        fn()
    except ValueError as exc:
        failed.append(f"{name}: {exc}")
check(not failed, f"production with item detail required on WIP/inventory accounts posts every step ({failed})")

# --- اتمام سفارش نیمه‌تمام ------------------------------------------------------------------------------------------------
def purchase_order(qty=D(10)):
    d = ds.create_document(company_id, uid, "PURCHASE_ORDER", today, ds.DocumentHeaderFields(
        counterparty_detail_account_id=supplier, currency_id=company.base_currency_id, warehouse_id=wh_rm))
    ds.add_line(d, company_id, r1, kg, qty, qty, unit_price=D(1000))
    ds.add_line(d, company_id, pk, base_uom(pk), qty, qty, unit_price=D(500))
    ds.confirm_document(d, company_id, uid)
    return d


po_a = purchase_order()
state = ds.order_close_state(po_a, company_id)
check(not state.can_close and "لغو" in state.reason, "an order with nothing delivered or invoiced is cancelled, not closed")
check(raises(lambda: ds.close_order(po_a, company_id, uid), "لغو"), "close is refused for an untouched order")
_d, lines = ds.get_document(po_a, company_id)
invoice_id = ds.convert_to_invoice(po_a, company_id, uid, today, line_quantities={lines[0].line_id: D(4), lines[1].line_id: D(0)})
check(ds.order_close_state(po_a, company_id).can_close, "a partly invoiced order can be closed")
open_before = purchase_reports.open_purchase_orders(company_id, purchase_reports.PurchaseFilters(today, today))
ds.close_order(po_a, company_id, uid, "تامین‌کننده بقیه را ندارد")
closed = ds.order_close_state(po_a, company_id)
check(closed.closed and closed.note == "تامین‌کننده بقیه را ندارد" and closed.closed_at is not None, "close keeps time and reason")
doc_after, _ = ds.get_document(po_a, company_id)
check(doc_after.status_code == "CONFIRMED", "the document status itself does not change")
fulfil = ds.get_line_fulfillment(po_a, company_id)
check(all(f.closed and f.remaining_quantity == 0 for f in fulfil) and fulfil[0].invoiced_quantity == 4,
      "after close nothing remains to invoice; invoiced quantity stays")
check(raises(lambda: ds.convert_to_invoice(po_a, company_id, uid, today), "بازگشایی"), "a closed order is not converted")
check(raises(lambda: ds.close_order(po_a, company_id, uid), "قبلاً"), "closing twice is refused")
open_after = purchase_reports.open_purchase_orders(company_id, purchase_reports.PurchaseFilters(today, today))
check(any(ref and ref[0] == po_a for ref in open_before.refs) and not any(ref and ref[0] == po_a for ref in open_after.refs),
      "closed order leaves the open purchase orders report")
from peecha.services.workflow.adapters import commerce as wf_commerce

check(wf_commerce._fully_invoiced(company_id, po_a), "the automatic invoice step counts a closed order as done")
from peecha.db.models.commercial import DocumentChangeLog

with new_session() as s:
    actions = [a for (a,) in s.execute(select(DocumentChangeLog.action).where(DocumentChangeLog.document_id == po_a))]
check("CLOSE" in actions, "close is written to the document history")

# فرم سفارش
from peecha.ui.screens.commercial_document import CommercialDocumentScreen, _AmountField, _EnterComboBox

scr = CommercialDocumentScreen("PURCHASE_ORDER", None)
scr.show()
scr.edit_document(po_a)
app.processEvents()
check(scr.status_badge.text().endswith("اتمام‌شده") and not scr.convert_button.isEnabled()
      and "بازگشایی" in scr.convert_button.toolTip(), "form shows the closed state and disables convert")
check(scr.reopen_order_button.isVisible() and not scr.close_order_button.isVisible()
      and "تامین‌کننده بقیه را ندارد" in scr.reopen_order_button.toolTip(), "reopen button shows when and why it was closed")
check(len(scr.close_order_button.text()) <= 2 and len(scr.reopen_order_button.text()) <= 2, "close/reopen are icon buttons")
answer["q"] = QMessageBox.Yes
check(scr._reopen_order() and scr.convert_button.isEnabled() and scr.close_order_button.isEnabled()
      and not scr.reopen_order_button.isVisible(), "reopen brings convert back")
check(ds.get_line_fulfillment(po_a, company_id)[0].remaining_quantity == 6, "after reopen the remainder is open again")
check(scr._close_order("آزمون") and scr.status_badge.text().endswith("اتمام‌شده"), "the form closes the order")
po_b = purchase_order()
scr.edit_document(po_b)
app.processEvents()
check(not scr.close_order_button.isEnabled() and "لغو" in scr.close_order_button.toolTip(),
      "close button is disabled with the reason for an untouched order")

# فهرست اسناد
from peecha.ui.screens.commercial_documents_list import CommercialDocumentsListScreen

lst = CommercialDocumentsListScreen(None, ("PURCHASE_ORDER",))
lst.refresh()
app.processEvents()
row = next(r for r in range(lst.table.rowCount()) if lst.table.item(r, 0).data(256) == po_a)
convert = [b for b in lst.table.cellWidget(row, lst.table.columnCount() - 1).findChildren(QPushButton) if b.text() == "→"]
check(lst.table.item(row, 8).text().startswith("اتمام‌شده") and convert and not convert[0].isEnabled(),
      "documents list shows «اتمام‌شده» and disables convert for the closed order")

# --- ۱) تخفیف ردیف: مبلغی ← درصدی ---------------------------------------------------------------------------------------
po_c = ds.create_document(company_id, uid, "PURCHASE_ORDER", today, ds.DocumentHeaderFields(
    counterparty_detail_account_id=supplier, currency_id=company.base_currency_id, warehouse_id=wh_rm))
ds.add_line(po_c, company_id, r1, kg, D(10), D(10), unit_price=D(100000), discount_amount=D(50000))
scr.edit_document(po_c)
app.processEvents()


def line_state():
    ln = ds.get_document(po_c, company_id)[1][0]
    return ln.discount_amount, ln.discount_percent, ln.line_total


def discount_widgets():
    cell = scr.lines_table.cellWidget(0, 4)
    return cell.findChild(_AmountField, "inlineDiscountField"), cell.findChild(_EnterComboBox, "inlineDiscountType")


check(line_state()[0] == 50000, "line starts with an amount discount")
field, combo = discount_widgets()
combo.setCurrentIndex(combo.findData("PERCENT"))
app.processEvents()
amount, percent, total = line_state()
field, combo = discount_widgets()
check(amount == 0 and total == 1000000 and combo.currentData() == "PERCENT",
      f"switching to percent drops the old amount discount and keeps «درصدی» ({amount}, {total}, {combo.currentData()})")
field.setValue(10)
field.editingFinished.emit()
app.processEvents()
amount, percent, total = line_state()
check(percent == 10 and amount == 100000 and total == 900000, f"10 percent is applied ({amount}, {percent}, {total})")

# --- ۵) «آیا فاکتور نسیه است؟» --------------------------------------------------------------------------------------------
ds.confirm_document(invoice_id, company_id, uid)
inv_scr = CommercialDocumentScreen("PURCHASE_INVOICE", None)
inv_scr.show()
inv_scr.edit_document(invoice_id)
opened = []
inv_scr._open_settlement_plan = lambda: opened.append(True)
asked.clear()
answer["q"] = QMessageBox.No
inv_scr._prompt_settlement_after_confirm()
check(asked and asked[-1].startswith("آیا این فاکتور نسیه است؟"), "the question is «آیا این فاکتور نسیه است؟»")
check(opened and settlements.get_settlement_plan(invoice_id, company_id) is None, "«خیر» opens the receive/pay form")
opened.clear()
answer["q"] = QMessageBox.Yes
inv_scr._prompt_settlement_after_confirm()
plan = settlements.get_settlement_plan(invoice_id, company_id)
check(not opened and plan is not None and not plan.lines, "«بله» records the whole invoice as credit")

# --- ۳) دکمه‌های آیکونی: ردیابی و تبدیل به فاکتور -------------------------------------------------------------------------
from types import SimpleNamespace

from peecha.ui.screens.commercial_document import _ConvertToInvoiceDialog
from peecha.ui.screens.lot_tracking_dialog import LotTrackingDialog


def text_buttons(dialog):
    dialog.show()
    app.processEvents()
    app.processEvents()
    return [b.text() for b in dialog.findChildren(QPushButton) if b.isVisible() and len(b.text().strip()) > 2]


tracking = LotTrackingDialog(None, company_id, r1, "RM-1", D(5), "kg")
check(not text_buttons(tracking), "tracking (batch/serial) window has no text buttons")
row_info = SimpleNamespace(line_id=1, item_id=r1, quantity=D(10), delivered_quantity=D(4), invoiced_quantity=D(0),
                           remaining_quantity=D(10), uom_id=kg, warehouse_id=None)
convert_dialog = _ConvertToInvoiceDialog(None, [row_info], {})
left = text_buttons(convert_dialog)
ok = convert_dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.Ok)
check(not left and "تبدیل" in ok.toolTip(), f"convert window has icon buttons; the custom text becomes the tooltip ({left})")
plain = QPushButton("ذخیره")
plain.show()
app.processEvents()
plain.setText("انصراف")
plain.hide()
plain.show()
app.processEvents()
check(len(plain.text()) <= 2 and plain.property("label") == "انصراف", "text written after iconizing is iconized again")

# --- ۲) «جدید» به‌جای «تازه» -------------------------------------------------------------------------------------------------
root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src")
left = []
for base in ("peecha", "peecha_api"):
    for dp, _dn, fn in os.walk(os.path.join(root, base)):
        for f in fn:
            if not f.endswith(".py") or f == "icon_buttons.py":
                continue
            tree = ast.parse(open(os.path.join(dp, f), encoding="utf-8").read())
            docs = {id(n.value) for n in ast.walk(tree) if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)}
            left += [f"{f}:{n.lineno}" for n in ast.walk(tree)
                     if isinstance(n, ast.Constant) and isinstance(n.value, str) and "تازه" in n.value and id(n) not in docs]
check(not left, f"no user-facing text says «تازه» ({left[:5]})")
scr.edit_document(po_b)
check(scr.convert_button.toolTip().endswith("فاکتور جدید می‌سازد"), f"convert tooltip says «جدید» ({scr.convert_button.toolTip()})")
with new_session() as s:
    name = s.execute(text("SELECT name FROM inv.feature_definitions WHERE feature_code = 'NEW_ITEM_APPROVAL'")).scalar()
check(name == "تایید کالای جدید", f"stored setting text is updated too ({name})")

scr.hide()
inv_scr.hide()
finish()
