"""R337: مرکز هزینه و پروژهٔ دستور تولید: اگر حساب‌های تولید آن‌ها را الزامی کرده‌اند، هنگام ایجاد دستور (فرم، ویزارد و سرویس)
خواسته می‌شوند؛ دستوری که قبلاً صادر شده و پروژه ندارد، همان‌جا تکمیل و «اتمام تولید» دوباره انجام می‌شود."""
import os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r337"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prd_fixture import *  # noqa: F401,F403

from PySide6.QtWidgets import QApplication, QMessageBox

app = QApplication.instance() or QApplication([])
QMessageBox.warning = staticmethod(lambda *a, **k: print("WARN", a[2] if len(a) > 2 else a))
QMessageBox.information = staticmethod(lambda *a, **k: None)

from peecha.services import detail_dimensions as dims
from peecha.services.production import common as pc, costing as pcost, master as pm, orders as po
from peecha.ui.screens import production as screen_mod

pc.update_settings(company_id, uid, default_material_warehouse_id=wh_rm, default_fg_warehouse_id=wh_fg,
                   default_scrap_warehouse_id=wh_scrap, auto_cost_calculation=True)
cc_type = dims.get_specialized_dimension_type_id(company_id, dims.COST_CENTER_CODE)
pj_type = dims.get_specialized_dimension_type_id(company_id, dims.PROJECT_CODE)
cc_a = dims.create_detail_account(company_id, cc_type, "CC-A", "واحد تولید").detail_account_id
cc_b = dims.create_detail_account(company_id, cc_type, "CC-B", "واحد بسته‌بندی").detail_account_id
pj_1 = dims.create_detail_account(company_id, pj_type, "PJ-1", "پروژهٔ فلفل").detail_account_id
wc = pm.save_work_center(company_id, pm.WorkCenterFields(code="CUT", name="برش", labor_rate=D(500000),
                                                        machine_rate=D(800000), overhead_rate=D(200000)))
px = item("PX", "محصول X", "FINISHED_GOOD")
rt = pm.create_routing(company_id, px, "مسیر", [pm.RoutingOpFields(10, "برش", wc, run_minutes=D(6), machine_minutes=D(12))])
bom = pm.create_bom_version(company_id, px, pm.BomFields(batch_size_qty=D(1), routing_id=rt))
pm.add_bom_component(company_id, bom, pm.BomLineFields(r1, D(1)))
receive(r1, 1000, 10000)


def run_to_complete(order_id, labor=True):
    po.release_order(company_id, uid, order_id)
    po.start_order(company_id, uid, order_id)
    po.issue_all_remaining(company_id, uid, order_id)
    if labor:
        op = po.order_view(company_id, order_id).operations[0].order_operation_id
        pcost.record_labor(company_id, uid, order_id, pcost.LaborInput(hours=D(10), order_operation_id=op))


# --- دستوری که پیش از الزام پروژه صادر شده (مثل PO-1 کاربر) -----------------------------------------------------------
old = po.create_order(company_id, uid, po.OrderFields(item_id=px, planned_qty=D(50)))
run_to_complete(old, labor=False)  # تولید و بهای تبدیل استاندارد هنگام «اتمام تولید» ثبت می‌شود
check(po.dimension_rules(company_id).project is None and po.dimension_rules(company_id).cost_center is None,
      "without account rules nothing is required")

# سربار جذب‌شده (مثل 7202-72-7 کاربر) پروژه و کالای در جریان ساخت مرکز هزینه می‌خواهد
dims.set_account_dimension_types(overhead_gl.account_id, company_id, [pj_type])
dims.set_account_dimension_types(wip_gl.account_id, company_id, [cc_type])
rules = po.dimension_rules(company_id)
with new_session() as s:
    from peecha.db.models.accounting import ChartOfAccount

    var_code = s.get(ChartOfAccount, overhead_gl.account_id).full_code
    wip_code = s.get(ChartOfAccount, wip_gl.account_id).full_code
check(rules.project and var_code in rules.project and rules.cost_center and wip_code in rules.cost_center,
      f"rules name the accounts that need them ({rules.cost_center} / {rules.project})")

# --- ایجاد دستور: مرکز هزینه و پروژه همان ابتدا خواسته می‌شوند -------------------------------------------------------------
check(raises(lambda: po.create_order(company_id, uid, po.OrderFields(item_id=px, planned_qty=D(10))), "مرکز هزینهٔ دستور تولید"),
      "a new order without cost center is refused at creation")
check(raises(lambda: po.create_order(company_id, uid, po.OrderFields(item_id=px, planned_qty=D(10), cost_center_detail_account_id=cc_a)),
             "پروژهٔ دستور تولید"), "and without project too, naming the account")
new = po.create_order(company_id, uid, po.OrderFields(item_id=px, planned_qty=D(20), cost_center_detail_account_id=cc_a,
                                                      project_detail_account_id=pj_1))
run_to_complete(new)
po.complete_order(company_id, uid, new, po.ReceiptInput(D(20), {}))
po.close_order(company_id, uid, new)
check(po.get_order(company_id, new).status_code == "CLOSED", "an order created with both finishes and closes")

# --- دستور قبلی بدون پروژه: «اتمام تولید» خطا می‌دهد، همان‌جا پروژه تعیین و دوباره انجام می‌شود ---------------------------
check(raises(lambda: po.set_order_dimensions(company_id, uid, old, cc_b, None), "پروژهٔ دستور تولید")
      and po.get_order(company_id, old).cost_center_detail_account_id is None, "a required project cannot be left empty")
scr = screen_mod.OrdersScreen()
scr.refresh()
scr.open_order(old)
app.processEvents()
form = dict((k, lb) for k, lb, _w in scr._order_form())
check(form["project_detail_account_id"] == "پروژه (الزامی)" and form["cost_center_detail_account_id"] == "مرکز هزینه (الزامی)",
      "the order form has cost center and project, marked required")
check(scr.actions["dims"].isEnabled() and len(scr.actions["dims"].text()) <= 2 and "پروژه" in scr.actions["dims"].toolTip(),
      "an icon button sets cost center/project of an order in progress")
check("پروژه: —" in scr.dims_label.text(), f"the order shows its cost center and project ({scr.dims_label.text()})")
asked = []
scr.confirm = lambda text: (asked.append(text), True)[1]
scr._skip_confirm = True


def fill_dims(dlg):
    screen_mod.set_combo(dlg.widgets["project_detail_account_id"], pj_1)
    if dlg.widgets["cost_center_detail_account_id"].currentData() is None:
        screen_mod.set_combo(dlg.widgets["cost_center_detail_account_id"], cc_a)
    return True


scr.dialog_runner = fill_dims
ok = scr.action("complete", {"quantity": D(50), "joint_method": None})
check(asked and ("«پروژه»" in asked[0] or "«مرکز هزینه»" in asked[0]) and "الان تعیین" in asked[0],
      f"the missing cost center/project error offers to set it ({asked[:1]})")
order_old = po.get_order(company_id, old)
check(ok and order_old.project_detail_account_id == pj_1 and order_old.status_code == "COMPLETED",
      f"after setting the project, «اتمام تولید» goes through ({order_old.status_code})")
check("پروژهٔ فلفل" in scr.dims_label.text(), "the header now shows the project")
check(raises(lambda: po.set_order_dimensions(company_id, uid, old, cc_b, pj_1), "عوض نمی‌شود"),
      "a set cost center is not changed after release")

# --- ویزارد: همان مرحلهٔ مقدار، مرکز هزینه و پروژه دارد ------------------------------------------------------------------------
wiz = screen_mod.ProductionWizard(scr.lk)
screen_mod.set_combo(wiz.item_box, px)
wiz._item_changed()
wiz.go(2)
check(wiz.cost_center_box.count() > 1 and wiz.project_box.count() > 1, "the wizard asks for cost center and project")
screen_mod.set_combo(wiz.cost_center_box, cc_a)
screen_mod.set_combo(wiz.project_box, pj_1)
wiz.go(3)
wiz.next()
check(wiz.order_id and po.get_order(company_id, wiz.order_id).project_detail_account_id == pj_1,
      "the wizard creates the order with its project")

finish()
