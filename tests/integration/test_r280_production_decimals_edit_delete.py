import os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r280"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PySide6.QtWidgets import QApplication, QMessageBox
app = QApplication.instance() or QApplication([])
warnings = []
QMessageBox.warning = staticmethod(lambda *a, **k: warnings.append(a[2] if len(a) > 2 else a))
QMessageBox.information = staticmethod(lambda *a, **k: None)
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
from prd_fixture import *  # noqa: F401,F403
import prd_fixture as fx
from sqlalchemy import select
from peecha import decimals, numerals
from peecha.services.production import common as pc, master as pm, orders as po, planning as pp
from peecha.db.models.inventory import BomHeader
from peecha.db.models.production import ProductionOrder, ProductionPlanLine
check = fx.check
P = numerals.to_persian_digits

pc.update_settings(company_id, uid, default_material_warehouse_id=wh_rm, default_fg_warehouse_id=wh_fg, default_scrap_warehouse_id=wh_scrap)
BF, BL, RO = pm.BomFields, pm.BomLineFields, pm.RoutingOpFields
wc = pm.save_work_center(company_id, pm.WorkCenterFields(code="ASM", name="مونتاژ", labor_rate=D(1000)))
rt = pm.create_routing(company_id, fg, "مسیر", [RO(10, "مونتاژ", wc, run_minutes=D(6))])
bom = pm.create_bom_version(company_id, fg, BF(batch_size_qty=D(1), routing_id=rt))
pm.add_bom_component(company_id, bom, BL(r1, D("2.5")))
pk_line = pm.add_bom_component(company_id, bom, BL(pk, D(1), component_type="PACKAGING"))
receive(r1, 1000, 100)
receive(pk, 500, 10)

from peecha.ui.screens import production as ui
from peecha.ui.screens.fixed_assets import FormDialog, num_field, qty_field

# ===== ۱) اعشار مقدار طبق واحد کالا =================================================================
check(num_field(D("5.000")).text() == P("5") and num_field(D("2.500")).text() == P("2.5"), "edit fields show no padded zeros")
box = ui.combo([("محصول", fg), ("ماده", r1)])
field = qty_field(D("3.000"), item_combo=box)
check(field.property("qty_dp") == 0 and field.text() == P("3"), "count unit → whole numbers in the field")
dlg = FormDialog("t", [("item", "کالا", box), ("q", "مقدار", field)])
field.setText("2.5")
check(dlg.qty_precision_problem() and "اعشار" in dlg.qty_precision_problem(), "2.5 rejected for a unit without decimals")
box.setCurrentIndex(1)
check(field.property("qty_dp") == 3 and dlg.qty_precision_problem() is None, "kg item → three decimals accepted")
field.setText("1.2345")
check(dlg.qty_precision_problem() is not None, "four decimals rejected for kg")

wiz = ui.ProductionWizard(ui.PrdLookups(company_id))
ui.set_combo(wiz.item_box, fg)
wiz.next(); wiz.next()
wiz.qty_edit.setText("10.5")
check(not wiz.next() and wiz.stack.currentIndex() == 2 and "عدد صحیح" in warnings.pop(), "wizard blocks fractional quantity for count product")

oid = po.create_order(company_id, uid, po.OrderFields(item_id=fg, planned_qty=D(100)))
scr = ui.OrdersScreen()
scr.dialog_runner = lambda dlg: True
scr.confirm = lambda text: True
scr.refresh()
scr.open_order(oid)
check(scr.list_table.item(0, 3).text() == P("100"), f"orders list planned qty without decimals ({scr.list_table.item(0, 3).text()})")
check(scr.cards["planned"].text() == P("100"), "order card planned qty")
po.release_order(company_id, uid, oid)
scr.load_order(oid)
rows = {scr.t_materials.item(r, 0).text(): scr.t_materials.item(r, 2).text() for r in range(scr.t_materials.rowCount())}
check(any(v == P("250.000") for v in rows.values()) and any(v == P("100") for v in rows.values()),
      f"materials: kg with 3 decimals, pieces whole {rows}")

# ===== ۲) قفل فهرست مواد فقط با گردش ======================================================================
check(not pm.list_bom_versions(company_id, fg)[0].is_locked, "released order without movement does not lock the BOM")
pm.update_bom_component(company_id, pk_line, BL(pk, D(2), component_type="PACKAGING"))
check(True, "BOM component editable while used only by an order without movement")

# ===== ۳) ویرایش دستور صادرشده (بازگشت به پیش‌نویس) و حذف =============================================
values = {k: None for k, _l, _w in scr._order_form()}
values.update(item_id=fg, planned_qty=D(50), start_date=today, due_date=today, priority=2, notes="ویرایش‌شده")
check(scr.edit_order(values), "edit released order (reverts to draft)")
o = po.get_order(company_id, oid)
check(o.status_code == "DRAFT" and o.planned_qty == D(50) and o.notes == "ویرایش‌شده", "order edited and back to draft")
plan = pp.create_plan(company_id, uid, "P1", "برنامه", today, today + datetime.timedelta(days=10))
pl = pp.add_plan_line(company_id, plan, fg, today, D(5))
with new_session() as s:
    s.get(ProductionPlanLine, pl).order_id = oid
    s.commit()
check(scr.delete_order(), "delete order without movement")
with new_session() as s:
    check(s.get(ProductionOrder, oid) is None and s.get(ProductionPlanLine, pl).order_id is None, "order removed, plan link cleared")

# دستور با گردش: حذف و بازگشت ممنوع، فهرست مواد قفل
oid2 = po.create_order(company_id, uid, po.OrderFields(item_id=fg, planned_qty=D(10)))
po.release_order(company_id, uid, oid2)
po.start_order(company_id, uid, oid2)
view = po.order_view(company_id, oid2)
po.issue_materials(company_id, uid, oid2, [po.IssueLine(view.materials[0].material_id, D(5))])
check(fx.raises(lambda: po.delete_order(company_id, uid, oid2), "گردش"), "order with movement cannot be deleted")
check(fx.raises(lambda: po.revert_to_draft(company_id, uid, oid2), "گردش"), "order with movement cannot revert to draft")
check(pm.list_bom_versions(company_id, fg)[0].is_locked, "BOM locked once an order has movement")
check(fx.raises(lambda: pm.remove_bom_component(company_id, pk_line), "قفل"), "locked BOM component cannot be removed")

# ===== ۴) حذف نسخهٔ فهرست مواد، مسیر و برنامه ==============================================================
check(fx.raises(lambda: pm.delete_bom_version(company_id, bom), "دستور تولید"), "used BOM version cannot be deleted")
md = ui.MasterDataScreen()
md.dialog_runner = lambda dlg: True
md.refresh()
ui.set_combo(md.bom_item, fg)
md.load_boms()
check(md.bom_action("new", {"batch_size_qty": D(1), "scrap_percent": D(0), "name": "آزمایشی", "valid_from": today}), "new BOM version")
bom2 = max(v.bom_id for v in pm.list_bom_versions(company_id, fg))
md.t_versions.selectRow(md.t_versions.rowCount() - 1)
check(md.bom_action("component", {"component_item_id": r2, "quantity": D(1), "scrap_percent": D(0), "component_type": "MATERIAL",
                                  "fixed": False, "operation_seq": None, "substitute_item_id": None, "is_optional": False}), "add component")
check(md.bom_action("output", {"item_id": byp, "output_type": "BY_PRODUCT", "quantity_per": D(1), "value": D(5)}), "add output")
md.t_outputs.selectRow(0)
check(md.bom_action("edit_output", {"item_id": byp, "output_type": "BY_PRODUCT", "quantity_per": D(2), "value": D(5)})
      and pm.bom_outputs(company_id, bom2)[0].quantity_per == D(2), "edit by-product output")
check(md.bom_action("delete_version", {}), "delete unused BOM version from the screen")
with new_session() as s:
    check(s.get(BomHeader, bom2) is None, "BOM version deleted with its lines and outputs")
rt2 = pm.create_routing(company_id, fg, "مسیر دوم", [RO(10, "بسته‌بندی", wc)])
pm.update_routing(company_id, rt2, "مسیر بسته‌بندی")
check(next(r for r in pm.list_routings(company_id, fg) if r.routing_id == rt2).name == "مسیر بسته‌بندی", "edit routing name")
pm.delete_routing(company_id, rt2)
check(all(r.routing_id != rt2 for r in pm.list_routings(company_id, fg)), "delete unused routing")
check(fx.raises(lambda: pm.delete_routing(company_id, rt), "دستور تولید"), "routing used by an order cannot be deleted")

pp.update_plan_line(company_id, pl, fg, today, D(7))
pp.update_plan(company_id, uid, plan, "P1", "برنامهٔ ویرایش‌شده", today, today + datetime.timedelta(days=20))
check(pp.plan_lines(company_id, plan)[0].quantity == D(7) and pp.list_plans(company_id)[0].name == "برنامهٔ ویرایش‌شده",
      "edit plan and plan line")
pp.remove_plan_line(company_id, pl)
pp.delete_plan(company_id, uid, plan)
check(not pp.list_plans(company_id), "delete plan")
check(not warnings, f"no unexpected warnings {warnings}")

fx.finish()
