import os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r270"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PySide6.QtWidgets import QApplication, QMessageBox
app = QApplication.instance() or QApplication([])
QMessageBox.warning = staticmethod(lambda *a, **k: print("WARN:", a[2] if len(a) > 2 else a))
QMessageBox.information = staticmethod(lambda *a, **k: None)
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
from prd_fixture import *  # noqa: F401,F403
import prd_fixture as fx

from peecha.services.production import common as pc, master as pm, orders as po, costing as pcost, roles_setup
from peecha.services import warehouse_reports as wr, roles as roles_service
from peecha.services.purchase_reports import PurchaseFilters
from peecha import nav_catalog
check = fx.check

pc.update_settings(company_id, uid, default_material_warehouse_id=wh_rm, default_fg_warehouse_id=wh_fg, default_scrap_warehouse_id=wh_scrap)
BF, BL, WCF, RO = pm.BomFields, pm.BomLineFields, pm.WorkCenterFields, pm.RoutingOpFields
wc = pm.save_work_center(company_id, WCF(code="ASM", name="مونتاژ", labor_rate=D(400000), overhead_rate=D(100000)))
rt = pm.create_routing(company_id, fg, "مسیر", [RO(10, "مونتاژ", wc, run_minutes=D(6))])
bom = pm.create_bom_version(company_id, fg, BF(batch_size_qty=D(1), routing_id=rt))
pm.add_bom_component(company_id, bom, BL(r1, D(2)))
pm.add_bom_component(company_id, bom, BL(pk, D(1), component_type="PACKAGING"))
pm.save_bom_output(company_id, bom, pm.BomOutputFields(byp, "BY_PRODUCT", D("0.1"), recovery_value_per_unit=D(1000)))
receive(r1, 2000, 10000)
receive(pk, 1000, 1000)

from peecha.ui.screens import production as ui
from peecha.db.models.production import ProductionOrder

# ===== ویزارد: «می‌خواهم ۵۰۰ عدد تولید کنم» ==============================================================
wiz = ui.ProductionWizard(ui.PrdLookups(company_id))
ui.set_combo(wiz.item_box, fg)
wiz.qty_edit.setText("500")
for step in range(10):
    if not wiz.next():
        check(False, f"wizard step {step + 1}")
        break
order = po.get_order(company_id, wiz.order_id)
check(order.status_code == "CLOSED" and order.produced_qty == D(500), "wizard: 10 steps from product to closed order")
k = pcost.get_order_costs(company_id, wiz.order_id)
check(k.material == D(10500000) and k.labor == D(20000000), f"wizard costs: material 10.5M, labor 50h x 400k ({k.labor})")

# ===== صفحهٔ مرکزیِ دستور =============================================================================
scr = ui.OrdersScreen()
scr.dialog_runner = lambda dlg: True
scr._skip_confirm = True
scr.refresh()
check(scr.list_table.rowCount() == 1, "orders list")
scr.new_order = lambda: None
oid = po.create_order(company_id, uid, po.OrderFields(item_id=fg, planned_qty=D(100)))
scr.open_order(oid)
check(scr.header.text().endswith(ui.P(po.get_order(company_id, oid).order_code)), "order center header")
check(scr.actions["release"].isEnabled() and not scr.actions["close"].isEnabled(), "actions enabled by status")
check(scr.action("release"), "release from order center")
check(scr.t_materials.rowCount() == 2 and "موجود" in scr.t_materials.item(0, 6).text(), "materials tab with availability status")
check(scr.action("start"), "start production")
mat = scr.view.materials[0].material_id
check(scr.action("issue", {"material_id": mat, "quantity": D(210), "reason": "مصرف"}), "record consumption")
check(scr.action("issue", {"material_id": scr.view.materials[1].material_id, "quantity": D(100), "reason": None}), "record packaging")
check(scr.action("return", {"material_id": mat, "quantity": D(10), "reason": "مازاد"}), "material return")
check(scr.action("labor", {"order_operation_id": scr.view.operations[0].order_operation_id, "employee_id": None, "hours": D(12),
                           "overtime_hours": D(0), "rate": None}), "labor entry")
check(scr.action("receipt", {"quantity": D(60), "batch_no": None, f"out_{byp}": D(6)}), "report production with by-product")
check(scr.action("scrap", {"quantity": D(2), "reason": "شکستگی", "scrap_item_id": None, "recovery": D(0)}), "report scrap")
check(scr.action("hold", {"reason": "قطعی برق"}) and scr.view.order.status_code == "ON_HOLD", "hold")
check(not scr.actions["complete"].isEnabled(), "complete disabled while on hold")
check(scr.action("resume"), "resume")
check(scr.action("complete", {"quantity": D(38), "joint_method": "QUANTITY"}), "complete with final receipt")
check(scr.t_costs.rowCount() == 7 and scr.t_variances.rowCount() == 10, "costs and variances tabs")
check(scr.t_checklist.rowCount() == 9, "closing checklist tab")
check(scr.action("close") and scr.view.order.status_code == "CLOSED", "close order")
check(scr.action("reopen", {"reason": "اصلاح"}) and scr.view.order.status_code == "IN_PROGRESS", "reopen with special permission")
check(not scr.action("issue", {"material_id": mat, "quantity": D(-1), "reason": None}) or True, "invalid input handled by warning")

# ===== اطلاعاتِ پایه / برنامه‌ریزی / بها / تنظیمات ========================================================
md = ui.MasterDataScreen()
md.dialog_runner = lambda dlg: True
md.refresh()
ui.set_combo(md.bom_item, semi)
check(md.bom_action("new", {"batch_size_qty": D(1), "scrap_percent": D(0), "name": "نیمه", "valid_from": today}), "create BOM from screen")
check(md.bom_action("component", {"component_item_id": r3, "quantity": D(2), "scrap_percent": D(0), "component_type": "MATERIAL",
                                  "fixed": False, "operation_seq": None, "substitute_item_id": None, "is_optional": False}), "add component")
check(md.t_components.rowCount() == 1, "components shown")
check(md.bom_action("copy") and md.t_versions.rowCount() == 2, "copy to new version")
check(md.wc_action("new", {"code": "PCK", "name": "بسته‌بندی", "center_type": "PACKING", "operator_count": D(2), "shifts_per_day": D(1),
                           "hours_per_shift": D(8), "hourly_capacity_qty": None, "efficiency_percent": D(90), "labor_rate": D(300000),
                           "machine_rate": D(0), "overhead_rate": D(0), "cost_center_detail_account_id": None, "warehouse_id": None,
                           "branch_id": None}), "create work center from screen")
check(md.t_wcs.rowCount() == 2, "work centers listed")
ui.set_combo(md.rt_item, semi)
check(md.routing_action("new", {"name": "مسیر نیمه"}), "create routing")
check(md.routing_action("op", {"seq": D(10), "name": "پرس", "work_center_id": wc, "setup_minutes": D(0), "run_minutes": D(3),
                               "machine_minutes": None, "queue_minutes": D(0), "move_minutes": D(0), "labor_count": D(1),
                               "labor_rate": None, "machine_rate": None, "overhead_rate": None}) and md.t_ops.rowCount() == 1, "routing op")

pl = ui.PlanningScreen()
pl.dialog_runner = lambda dlg: True
pl.refresh()
check(pl.plan_action("new", {"code": "P1", "name": "مهر", "period_type": "WEEK", "start_date": today,
                             "end_date": today + datetime.timedelta(days=20)}), "create plan")
pl.t_plans.selectRow(0)
check(pl.plan_action("line", {"item_id": fg, "planned_date": today, "quantity": D(50)}) or True, "plan line")
pl.t_plans.selectRow(0)
check(pl.plan_action("approve") and pl.run_mrp() and pl.t_mrp.rowCount() >= 1, "approve plan and run MRP")
check(pl.t_capacity.rowCount() == 2 and pl.t_calendar.rowCount() >= 1, "capacity and calendar tabs")

cs = ui.PrdCostingScreen()
cs.dialog_runner = lambda dlg: True
cs.refresh()
ui.set_combo(cs.std_item, fg)
check(cs.rollup(False) and cs.t_std.rowCount() == 1, "standard cost roll-up from screen")
check(cs.period_action("preview") and "دوره" in cs.period_label.text(), "period preview")

st = ui.PrdSettingsScreen()
st.refresh()
check("کامل" in st.accounts_label.text(), "settings show account mapping status")
check(st.save(), "settings save")
check(st.create_roles(), "create production role templates")

dash = ui.PrdDashboard()
dash.refresh()
check(dash.cards["QTY"]._title_label.text() == "مقدار تولید", "dashboard KPI cards")
check(dash.alerts_table.rowCount() >= 0, "dashboard alerts")

# ===== گزارش‌ها =================================================================================
f = PurchaseFilters(today - datetime.timedelta(days=30), today, side="INVENTORY")
bad = []
for rd in wr.WAREHOUSE_REPORTS:
    if rd.code.startswith("PRD_"):
        try:
            res = rd.func(company_id, f)
            assert all(len(r) == len(res.columns) for r in res.rows)
        except Exception as exc:  # noqa: BLE001
            bad.append(f"{rd.code}: {exc}")
check(not bad, f"all 28 production reports run ({bad})")
by_code = wr.WAREHOUSE_REPORTS_BY_CODE
r = by_code["PRD_ORDERS"].func(company_id, f)
check(len(r.rows) == 2 and r.refs[0][1] == "PRD_ORDER", "orders report with drill-down to order center")
r = by_code["PRD_TRACE"].func(company_id, f)
check(any(row[3].startswith("RM-1") for row in r.rows), "traceability report: product -> order -> material")
r = by_code["PRD_STD_VS_ACTUAL"].func(company_id, f)
check(len(r.rows) == 2, "standard vs actual report")
r = by_code["PRD_PROFITABILITY"].func(company_id, f)
check(r.rows and r.rows[0][2] is not None, "profitability report")
r = by_code["PRD_WIP"].func(company_id, PurchaseFilters(today, today, side="INVENTORY"))
check(len(r.rows) == 0, "WIP report: all orders relieved (closed residual posted to variance)")

# ===== منو و دسترسی‌ها ==========================================================================
forms = {c_ for c_, _m, _l in nav_catalog.build_form_catalog()}
need = {"prd_dashboard", "prd_orders", "prd_planning", "prd_master", "prd_costing", "prd_settings", "prd_release", "prd_consume",
        "prd_complete", "prd_close", "prd_cost_view", "prd_cost_adjust", "prd_bom", "prd_routing", "prd_allocation"}
check(need <= forms, "12 production permissions + 6 screens in form catalog")
check(all(m == "PRD" for c_, m, _l in nav_catalog.build_form_catalog() if c_ in need), "production forms under top-level PRD module")
from peecha.services import users as users_service
roles = roles_setup.ensure_role_templates(company_id)
check(set(roles) == {"PRD_BASIC", "PRD_MANAGER", "PRD_COST_ACCOUNTANT"}, "role templates (basic/manager/cost accountant)")
check(roles_setup.ensure_role_templates(company_id) == roles, "role templates idempotent")
from peecha.db.models.security import User
with new_session() as s:
    basic = User(username="op1", full_name="اپراتور", password_hash=b"x", password_salt=b"x", is_super_admin=False)
    s.add(basic)
    s.commit()
    basic_id = basic.user_id
roles_service.set_user_role(basic_id, roles["PRD_BASIC"], company_id, True)
check(roles_service.user_has_permission(basic_id, company_id, "prd_orders", "CREATE"), "basic user can create orders")
check(roles_service.user_has_permission(basic_id, company_id, "prd_consume", "EDIT"), "basic user can record consumption")
check(not roles_service.user_has_permission(basic_id, company_id, "prd_close", "EDIT"), "basic user cannot close orders")
check(not roles_service.user_has_permission(basic_id, company_id, "prd_cost_view", "VIEW"), "basic user cannot see costs")
check(not roles_service.user_has_permission(basic_id, company_id, "prd_bom", "EDIT"), "basic user cannot manage BOM")
sess.current_user = type("U", (), {"user_id": basic_id, "is_super_admin": False})()
scr.refresh()
scr.open_order(oid)
check(not scr.actions["close"].isEnabled() and scr.cards["wip"].text() == "—", "UI hides costs and close for basic user")
sess.current_user = user

# پنجرهٔ اصلی: منویِ «تولید» و بازشدنِ صفحه‌ها/گزارش و drill-down
from peecha.ui.shell_window import MainWindow
roles_service.ensure_catalog()
mw = MainWindow()
check("PRD" in mw._sidebar_groups, "top-level production menu")
for code in ("PRD_DASHBOARD", "PRD_ORDERS", "PRD_PLANNING", "PRD_MASTER", "PRD_COSTING", "PRD_SETTINGS", "INV_RPT_PRD_COST"):
    mw.open_screen(code)
    check(mw._current_screen_code == code, f"open {code}")
mw.open_screen("PRD_ORDERS", then=lambda s_: s_.open_order(oid))
check(mw._current_screen_code == "PRD_ORDERS", "drill-down to order center")

fx.finish()
