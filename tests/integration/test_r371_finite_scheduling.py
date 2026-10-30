"""R371: زمان‌بندی با ظرفیت محدود: پخش ساعت عملیات روی ظرفیت روزانه، ترتیب عملیات هر دستور، قاعدهٔ اولویت در برابر زودترین موعد،
دیرکرد، خارج از افق، بهره‌برداری مراکز و ردیف‌های گانت؛ و فرم (بی‌آن‌که دستورها تغییر کنند)."""
import os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r371"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prd_fixture import *  # noqa: F401,F403

from peecha.db.models.production import ProductionOrder
from peecha.services.production import common as pc, master as pm, orders as po, scheduling as sch

pc.update_settings(company_id, uid, default_material_warehouse_id=wh_rm, default_fg_warehouse_id=wh_fg)
WCF, RO = pm.WorkCenterFields, pm.RoutingOpFields
l1 = pm.save_work_center(company_id, WCF(code="L1", name="برش", hours_per_shift=D(8), working_days_per_week=7))
l2 = pm.save_work_center(company_id, WCF(code="L2", name="مونتاژ", hours_per_shift=D(8), working_days_per_week=7))
rt = pm.create_routing(company_id, fg, "مسیر", [RO(10, "برش", l1, run_minutes=D(6)), RO(20, "مونتاژ", l2, run_minutes=D(3))])
bom = pm.create_bom_version(company_id, fg, pm.BomFields(batch_size_qty=D(1), routing_id=rt))
pm.add_bom_component(company_id, bom, pm.BomLineFields(r1, D(1)))
DAY = lambda n: today + datetime.timedelta(days=n)  # noqa: E731


def order(qty, priority, due):
    oid = po.create_order(company_id, uid, po.OrderFields(item_id=fg, planned_qty=D(qty), start_date=today, due_date=due, priority=priority))
    po.plan_order(company_id, uid, oid)
    return oid


a, b, c = order(100, 1, DAY(1)), order(80, 3, DAY(0)), order(40, 2, DAY(1))   # ساعت برش: ۱۰، ۸، ۴؛ مونتاژ: ۵، ۴، ۲
check(raises(lambda: sch.schedule(company_id, today, 0), "افق"), "the horizon has bounds")
r = sch.schedule(company_id, today, 30, "PRIORITY")
p = {o.order_id: o for o in r.orders}
check([o.order_id for o in r.orders] == [a, c, b], "priority first, then due date")
check([(op.start, op.finish) for op in p[a].ops] == [(DAY(0), DAY(1)), (DAY(1), DAY(1))],
      f"10 hours on an 8-hour center spill to the next day; the next operation follows ({[(op.start, op.finish) for op in p[a].ops]})")
check([(op.start, op.finish) for op in p[c].ops] == [(DAY(1), DAY(1)), (DAY(1), DAY(1))], "the second order uses what is left")
check(p[b].finish == DAY(2) and p[b].late_days == 2 and p[a].late_days == 0, "projected finish and lateness")
check(r.load[l1][DAY(0)].used == 8 and r.load[l1][DAY(1)].used == 8 and r.load[l1][DAY(2)].used == 6, "daily load never exceeds capacity")
check(r.utilization(l1) == D("9.2") and [o.order_id for o in r.late] == [b], f"utilization and late orders ({r.utilization(l1)})")
e = {o.order_id: o for o in sch.schedule(company_id, today, 30, "EDD").orders}
check(e[b].late_days == 0 and e[a].late_days == 1 and e[c].late_days == 1, "earliest due date reorders the work")
short = {o.order_id: o for o in sch.schedule(company_id, today, 2, "PRIORITY").orders}
check(short[b].finish is None and not short[b].ops[0].scheduled and not short[b].ops[1].scheduled and short[a].finish == DAY(1),
      "what does not fit in the horizon is reported, not squeezed")
rows = sch.gantt_rows(r)
check(len(rows.tasks) == 9 and rows.tasks[0].is_summary and rows.tasks[-1].critical, "gantt rows: order with its operations, late in red")
with new_session() as s:
    check(s.get(ProductionOrder, b).due_date == DAY(0) and s.get(ProductionOrder, b).status_code == "PLANNED", "orders are not changed")

# فرم
from PySide6.QtWidgets import QApplication, QPushButton
qapp = QApplication.instance() or QApplication([])
from peecha.ui import report_export
from peecha.ui.screens.production_scheduling import ProductionSchedulingScreen

printed = []
report_export.print_report = lambda parent, title, headers, rows, **kw: printed.append(title)
screen = ProductionSchedulingScreen()
screen.horizon_field.setValue(5)
screen.refresh()
check(screen.order_table.rowCount() == 3 and screen.op_table.rowCount() == 6 and screen.load_table.columnCount() == 6,
      "orders, operations and the daily load")
check(screen.order_table.item(2, 7).text() == "۲" and "۱ دستور دیر" in screen.summary_label.text(), f"late order shown ({screen.summary_label.text()})")
check(screen.gantt.minimumWidth() > 300 and not screen.gantt.grab().isNull() and screen.print_orders() and printed, "gantt and print")
check(all(len(x.text()) <= 2 for x in screen.findChildren(QPushButton) if x.text()), "icon buttons only")

finish()
