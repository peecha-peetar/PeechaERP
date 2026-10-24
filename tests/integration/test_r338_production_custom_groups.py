"""R338: حسابی که گروه «پروژه»ی ساخت خود کاربر (هم‌نام گروه سیستمی) را الزامی کرده: فهرست پروژهٔ دستور تولید از همان
گروه است، پروژهٔ گروه دیگر پذیرفته نمی‌شود، سند انبار و تولید با همان تفصیلی ثبت می‌شوند، گروه الزامی بی‌جا از همان
ابتدا گفته می‌شود و «الان تعیین می‌کنید؟» بیش از یک بار پرسیده نمی‌شود."""
import os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r338"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prd_fixture import *  # noqa: F401,F403

from PySide6.QtWidgets import QApplication, QMessageBox

app = QApplication.instance() or QApplication([])
warned = []
QMessageBox.warning = staticmethod(lambda *a, **k: warned.append(a[2]))
QMessageBox.information = staticmethod(lambda *a, **k: None)

from peecha.db.models.accounting import ChartOfAccount
from peecha.services import detail_dimensions as dims
from peecha.services.production import common as pc, master as pm, orders as po
from peecha.ui.screens import production as screen_mod

pc.update_settings(company_id, uid, default_material_warehouse_id=wh_rm, default_fg_warehouse_id=wh_fg,
                   default_scrap_warehouse_id=wh_scrap, auto_cost_calculation=True)
sys_pj_type = dims.get_specialized_dimension_type_id(company_id, dims.PROJECT_CODE)
sys_pj = dims.create_detail_account(company_id, sys_pj_type, "PJ-S", "پروژهٔ سیستمی").detail_account_id
my_pj_type = dims.create_dimension_type(company_id, "پروژه").dimension_type_id  # گروهی که کاربر خودش ساخته
my_pj = dims.create_detail_account(company_id, my_pj_type, "PJ-M", "پروژهٔ فلفل").detail_account_id
wc = pm.save_work_center(company_id, pm.WorkCenterFields(code="CUT", name="برش", labor_rate=D(500000),
                                                        machine_rate=D(800000), overhead_rate=D(200000)))
px = item("PX", "محصول X", "FINISHED_GOOD")
rt = pm.create_routing(company_id, px, "مسیر", [pm.RoutingOpFields(10, "برش", wc, run_minutes=D(6), machine_minutes=D(12))])
bom = pm.create_bom_version(company_id, px, pm.BomFields(batch_size_qty=D(1), routing_id=rt))
pm.add_bom_component(company_id, bom, pm.BomLineFields(r1, D(1)))
receive(r1, 1000, 10000)

# مثل 7-72-7202 کاربر: سربار جذب‌شده و کالای در جریان ساخت گروه «پروژه»ی کاربر را می‌خواهند
dims.set_account_dimension_types(overhead_gl.account_id, company_id, [my_pj_type])
dims.set_account_dimension_types(wip_gl.account_id, company_id, [my_pj_type])
with new_session() as s:
    oh_code = s.get(ChartOfAccount, overhead_gl.account_id).full_code
rules = po.dimension_rules(company_id)
check(rules.project and oh_code in rules.project and rules.project_types == [my_pj_type] and not rules.other,
      f"a user-made «پروژه» group counts as the project ({rules.project_types})")

# --- پروژهٔ گروه سیستمی همان اشتباهی است که کاربر دید؛ حالا از همان ابتدا گفته می‌شود ---------------------------------
check(raises(lambda: po.create_order(company_id, uid, po.OrderFields(item_id=px, planned_qty=D(10), project_detail_account_id=sys_pj)),
             "گروه تفصیلی"), "a project from the other «پروژه» group is refused at creation")
order = po.create_order(company_id, uid, po.OrderFields(item_id=px, planned_qty=D(20), project_detail_account_id=my_pj))
failed = []
for name, fn in (("release", lambda: po.release_order(company_id, uid, order)), ("start", lambda: po.start_order(company_id, uid, order)),
                 ("issue", lambda: po.issue_all_remaining(company_id, uid, order)),
                 ("complete", lambda: po.complete_order(company_id, uid, order, po.ReceiptInput(D(20), {}))),
                 ("close", lambda: po.close_order(company_id, uid, order))):
    try:
        fn()
    except ValueError as exc:
        failed.append(f"{name}: {exc}")
check(not failed, f"with the right project the stock and production entries post through to closing ({failed})")

# --- فرم: فهرست پروژه از گروه الزامی ---------------------------------------------------------------------------------------
scr = screen_mod.OrdersScreen()
scr.refresh()
project_ids = [data for _label, data in scr.lk.projects]
check(my_pj in project_ids and sys_pj not in project_ids, "the order form lists projects of the required group")

# --- دستور قدیمی با پروژهٔ گروه دیگر: اصلاح می‌شود و «اتمام تولید» انجام می‌شود ---------------------------------------------
dims.set_account_dimension_types(overhead_gl.account_id, company_id, [])
dims.set_account_dimension_types(wip_gl.account_id, company_id, [])
old = po.create_order(company_id, uid, po.OrderFields(item_id=px, planned_qty=D(30), project_detail_account_id=sys_pj))
po.release_order(company_id, uid, old)
po.start_order(company_id, uid, old)
po.issue_all_remaining(company_id, uid, old)
dims.set_account_dimension_types(overhead_gl.account_id, company_id, [my_pj_type])
scr.refresh()
scr.open_order(old)
app.processEvents()
check("از گروهی که حساب‌ها نمی‌خواهند" in scr.dims_label.text(), f"the header says the project is from the wrong group ({scr.dims_label.text()})")
asked = []
scr.confirm = lambda text: (asked.append(text), True)[1]
scr._skip_confirm = True
scr.dialog_runner = lambda dlg: (screen_mod.set_combo(dlg.widgets["project_detail_account_id"], my_pj), True)[1]
ok = scr.action("complete", {"quantity": D(30), "joint_method": None})
check(ok and po.get_order(company_id, old).project_detail_account_id == my_pj and po.get_order(company_id, old).status_code == "COMPLETED",
      "a project from the wrong group is corrected after release and «اتمام تولید» goes through")
check(len(asked) == 1, "asked once")

# --- گروه الزامی‌ای که دستور جایی برایش ندارد: از همان ابتدا روشن گفته می‌شود و پرسش تکرار نمی‌شود ---------------------------
odd_type = dims.create_dimension_type(company_id, "خط تولید").dimension_type_id
dims.create_detail_account(company_id, odd_type, "L1", "خط یک")
held = po.create_order(company_id, uid, po.OrderFields(item_id=px, planned_qty=D(5), project_detail_account_id=my_pj))
po.release_order(company_id, uid, held)
po.start_order(company_id, uid, held)
po.issue_all_remaining(company_id, uid, held)
dims.set_account_dimension_types(machine_gl.account_id, company_id, [odd_type])
check(raises(lambda: po.create_order(company_id, uid, po.OrderFields(item_id=px, planned_qty=D(5), project_detail_account_id=my_pj)),
             "جایی برای آن ندارد"), "a required group the order cannot carry is named at creation")
scr.refresh()
scr.open_order(held)
asked.clear()
warned.clear()
ok = scr.action("complete", {"quantity": D(5), "joint_method": None})
check(not ok and len(asked) <= 1 and po.get_order(company_id, held).status_code == "IN_PROGRESS" and warned,
      f"no endless «set it now?» loop ({len(asked)} questions, {warned[-1:]})")

finish()
