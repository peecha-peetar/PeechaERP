"""R340: حسابی مثل 7-72-7203 کاربر که علاوه بر مرکز هزینه و پروژه، گروه دیگری («هزینه ها») را هم الزامی کرده: همان گروه در
فرم و ویزارد ایجاد دستور تولید پرسیده می‌شود، روی سند همان حساب (همراه مرکز هزینه و پروژهٔ دستور) می‌نشیند، برای دستور در
جریان همان‌جا تعیین می‌شود، و تا وقتی گروه تفصیلی ندارد پیام روشن می‌گوید مرکز هزینه و پروژهٔ دستور اعمال شده‌اند."""
import os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r340"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prd_fixture import *  # noqa: F401,F403

from PySide6.QtWidgets import QApplication, QMessageBox

app = QApplication.instance() or QApplication([])
warned = []
QMessageBox.warning = staticmethod(lambda *a, **k: warned.append(a[2]))
QMessageBox.information = staticmethod(lambda *a, **k: None)

from peecha.db.models.accounting import ChartOfAccount, JournalEntryLine, JournalEntryLineDetail
from peecha.services import detail_dimensions as dims
from peecha.services.production import common as pc, master as pm, orders as po
from peecha.ui.screens import production as screen_mod

pc.update_settings(company_id, uid, default_material_warehouse_id=wh_rm, default_fg_warehouse_id=wh_fg,
                   default_scrap_warehouse_id=wh_scrap, auto_cost_calculation=True)
cc_type = dims.get_specialized_dimension_type_id(company_id, dims.COST_CENTER_CODE)
pj_type = dims.get_specialized_dimension_type_id(company_id, dims.PROJECT_CODE)
cc_a = dims.create_detail_account(company_id, cc_type, "CC-A", "واحد تولید").detail_account_id
pj_1 = dims.create_detail_account(company_id, pj_type, "PJ-1", "پروژهٔ فلفل").detail_account_id
wc = pm.save_work_center(company_id, pm.WorkCenterFields(code="CUT", name="برش", labor_rate=D(500000),
                                                        machine_rate=D(800000), overhead_rate=D(200000)))
px = item("PX", "محصول X", "FINISHED_GOOD")
rt = pm.create_routing(company_id, px, "مسیر", [pm.RoutingOpFields(10, "برش", wc, run_minutes=D(6), machine_minutes=D(12))])
bom = pm.create_bom_version(company_id, px, pm.BomFields(batch_size_qty=D(1), routing_id=rt))
pm.add_bom_component(company_id, bom, pm.BomLineFields(r1, D(1)))
receive(r1, 1000, 10000)
MACHINE_ROLE = pc.ROLE_LABELS[pc.MACHINE_APPLIED]
with new_session() as s:
    m_code = s.get(ChartOfAccount, machine_gl.account_id).full_code


def run(order_id):
    po.release_order(company_id, uid, order_id)
    po.start_order(company_id, uid, order_id)
    po.issue_all_remaining(company_id, uid, order_id)


def machine_lines(detail_id):
    with new_session() as s:
        return s.scalar(select(func.count()).select_from(JournalEntryLine).join(
            JournalEntryLineDetail, JournalEntryLineDetail.line_id == JournalEntryLine.line_id).where(
            JournalEntryLine.account_id == machine_gl.account_id, JournalEntryLineDetail.detail_account_id == detail_id))


# دستوری که پیش از الزام صادر شده
old = po.create_order(company_id, uid, po.OrderFields(item_id=px, planned_qty=D(10), cost_center_detail_account_id=cc_a,
                                                      project_detail_account_id=pj_1))
run(old)

# --- مثل 7203 کاربر: مرکز هزینه، پروژه و گروه «هزینه ها» که هنوز تفصیلی ندارد --------------------------------------------------
costs_type = dims.create_dimension_type(company_id, "هزینه ها").dimension_type_id
dims.set_account_dimension_types(machine_gl.account_id, company_id, [cc_type, pj_type, costs_type])
rules = po.dimension_rules(company_id)
group = rules.extra[0] if len(rules.extra) == 1 else None
check(not rules.other and group and group.type_id == costs_type and group.accounts == [m_code] and group.roles == [MACHINE_ROLE]
      and group.empty and group.with_order_dims, f"«هزینه ها» is a group the order itself carries ({rules.extra}, {rules.other})")
try:
    po.create_order(company_id, uid, po.OrderFields(item_id=px, planned_qty=D(5), cost_center_detail_account_id=cc_a,
                                                    project_detail_account_id=pj_1))
    message = ""
except ValueError as exc:
    message = str(exc)
check(all(t in message for t in (f"مرکز هزینه و پروژهٔ دستور روی حساب «{m_code}»", "«هزینه ها»", "گروه جداگانه‌ای",
                                 "هیچ تفصیلی‌ای", "تعریف تفصیلی‌ها", "تنظیم حساب‌ها", "کدینگ حساب‌ها")),
      f"the message says cost center and project are applied and the other group is empty ({message})")
scr = screen_mod.OrdersScreen()
scr.refresh()
form = dict((k, lb) for k, lb, _w in scr._order_form())
check(form.get(f"detail_{costs_type}") == "هزینه ها (الزامی)" and form["cost_center_detail_account_id"] == "مرکز هزینه (الزامی)",
      f"the order form asks for «هزینه ها» next to cost center and project ({list(form.values())[-4:]})")
check(po.dimension_problem(company_id) == message, "the posting-error advice is the same text")

# --- گروه تفصیلی می‌گیرد: از فرم دستور انتخاب می‌شود ------------------------------------------------------------------------------
h1 = dims.create_detail_account(company_id, costs_type, "H1", "هزینهٔ ماشین‌آلات").detail_account_id
h2 = dims.create_detail_account(company_id, costs_type, "H2", "هزینهٔ تعمیرات").detail_account_id
check(raises(lambda: po.create_order(company_id, uid, po.OrderFields(item_id=px, planned_qty=D(5), cost_center_detail_account_id=cc_a,
                                                                     project_detail_account_id=pj_1)),
             "«هزینه ها» دستور تولید را انتخاب کنید"), "without it the order is refused, naming the group")
check(raises(lambda: po.create_order(company_id, uid, po.OrderFields(item_id=px, planned_qty=D(5), cost_center_detail_account_id=cc_a,
                                                                     project_detail_account_id=pj_1, other_details={costs_type: cc_a})),
             "از همان گروهی نیست"), "a detail of another group is refused")
scr.refresh()


def fill_new(dlg):
    screen_mod.set_combo(dlg.widgets["item_id"], px)
    dlg.widgets["planned_qty"].setText("20")
    screen_mod.set_combo(dlg.widgets["cost_center_detail_account_id"], cc_a)
    screen_mod.set_combo(dlg.widgets["project_detail_account_id"], pj_1)
    screen_mod.set_combo(dlg.widgets[f"detail_{costs_type}"], h1)
    return True


scr.dialog_runner = fill_new
new = scr.new_order()
check(new and po.order_details(company_id, new) == {costs_type: h1}, f"the form creates the order with «هزینه ها» ({warned[-1:]})")
check("هزینه ها: H۱ — هزینهٔ ماشین‌آلات" in scr.dims_label.text(), f"the order header shows it ({scr.dims_label.text()})")
before = machine_lines(h1)
run(new)
po.complete_order(company_id, uid, new, po.ReceiptInput(D(20), {}))
with new_session() as s:
    wip_h1 = s.scalar(select(func.count()).select_from(JournalEntryLine).join(
        JournalEntryLineDetail, JournalEntryLineDetail.line_id == JournalEntryLine.line_id).where(
        JournalEntryLine.account_id == wip_gl.account_id, JournalEntryLineDetail.detail_account_id == h1))
check(po.get_order(company_id, new).status_code == "COMPLETED" and machine_lines(h1) > before and machine_lines(cc_a) > 0
      and machine_lines(pj_1) > 0 and not wip_h1,
      "«اتمام تولید» posts the machine cost with «هزینه ها», cost center and project; other accounts do not get it")
fields = po.OrderFields(item_id=px, planned_qty=D(7), cost_center_detail_account_id=cc_a, project_detail_account_id=pj_1,
                        other_details={costs_type: h2})
draft = po.create_order(company_id, uid, fields)
po.update_order(company_id, uid, draft, po.OrderFields(item_id=px, planned_qty=D(8), cost_center_detail_account_id=cc_a,
                                                       project_detail_account_id=pj_1))
check(po.order_details(company_id, draft) == {costs_type: h2}, "editing without the field keeps the saved detail")

# --- دستور در جریان که پیش از الزام صادر شده: همان‌جا تعیین و «اتمام تولید» انجام می‌شود -----------------------------------------
scr.refresh()
scr.open_order(old)
asked = []
scr.confirm = lambda text: (asked.append(text), True)[1]
scr._skip_confirm = True
scr.dialog_runner = lambda dlg: (screen_mod.set_combo(dlg.widgets[f"detail_{costs_type}"], h2), True)[1]
warned.clear()
ok = scr.action("complete", {"quantity": D(10), "joint_method": None})
check(len(asked) == 1 and "«هزینه ها»" in asked[0] and "الان تعیین" in asked[0], f"the posting error offers to set it ({asked[:1]})")
check(ok and po.get_order(company_id, old).status_code == "COMPLETED" and po.order_details(company_id, old) == {costs_type: h2},
      f"after choosing «هزینه ها», «اتمام تولید» goes through ({warned})")
check(raises(lambda: po.set_order_dimensions(company_id, uid, old, cc_a, pj_1, {costs_type: h1}), "عوض نمی‌شود"),
      "a set detail is not changed after release")

# --- ویزارد ---------------------------------------------------------------------------------------------------------------------
wiz = screen_mod.ProductionWizard(scr.lk)
screen_mod.set_combo(wiz.item_box, px)
wiz._item_changed()
wiz.go(2)
screen_mod.set_combo(wiz.cost_center_box, cc_a)
screen_mod.set_combo(wiz.project_box, pj_1)
check(costs_type in wiz.detail_boxes and wiz.detail_boxes[costs_type].count() > 2, "the wizard asks for «هزینه ها»")
screen_mod.set_combo(wiz.detail_boxes[costs_type], h1)
wiz.go(3)
wiz.next()
check(wiz.order_id and po.order_details(company_id, wiz.order_id) == {costs_type: h1}, "the wizard creates the order with it")

# --- تفصیلی ثابت همان نقش جای انتخاب در دستور را می‌گیرد ---------------------------------------------------------------------------
engine_service.set_account_mapping(company_id, "PRODUCTION_MACHINE_APPLIED", machine_gl.account_id, h2)
check(not po.dimension_rules(company_id).extra, "with a fixed detail for the role the order no longer asks for it")
before_h1, before_h2 = machine_lines(h1), machine_lines(h2)
po.start_order(company_id, uid, wiz.order_id)  # ویزارد دستور را صادر کرده است
po.issue_all_remaining(company_id, uid, wiz.order_id)
po.complete_order(company_id, uid, wiz.order_id, po.ReceiptInput(D(100), {}))
check(machine_lines(h2) > before_h2 and machine_lines(h1) == before_h1, "the role's fixed detail wins over the order's")
plain = po.create_order(company_id, uid, po.OrderFields(item_id=px, planned_qty=D(3), cost_center_detail_account_id=cc_a,
                                                        project_detail_account_id=pj_1))
check(po.order_details(company_id, plain) == {}, "a new order then needs nothing extra")

finish()
