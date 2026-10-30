"""R363: پروژه روی تفصیلی «پروژه»، فاز و فعالیت، پیوندهای FS/SS، زمان‌بندی روزکاری با جمعه و تعطیلی، مسیر بحرانی و شناوری،
حلقه و پیوند فاز ممنوع، پیشرفت و تاریخ واقعی، پیشرفت برنامه‌ای با خط مبنا، جابه‌جایی و حذف؛ و فرم و نمودار گانت."""
import datetime, os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r363"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prd_fixture import *  # noqa: F401,F403

from peecha.db.models.accounting import DetailAccount
from peecha.services import hr
from peecha.services.projects import core as prj, schedule as sch
from peecha.services.workflow import calendar

days = {d: ("08:00", "16:00") for d in (5, 6, 0, 1, 2)}
days[3] = ("08:00", "12:00")
calendar.save_work_hours(company_id, uid, days)  # شنبه تا پنجشنبه کاری، جمعه تعطیل
S = today + datetime.timedelta(days=14)
S -= datetime.timedelta(days=(S.weekday() - 5) % 7)  # یک شنبهٔ آینده
DAY = lambda n: S + datetime.timedelta(days=n)  # noqa: E731

org = hr.create_org_unit(company_id, "ENG", "فنی", None, None)
pos = hr.create_position(company_id, "PM", "مدیر پروژه", org, None, 5)
manager = hr.create_employee(company_id, "E1", "سارا", "کریمی", None, today - datetime.timedelta(days=300), org, pos, D(90_000_000), None)
client = dimensions_service.create_customer(company_id, "C1", "کارفرمای نمونه")

F = prj.ProjectFields
check(raises(lambda: prj.save_project(company_id, uid, F(S, code="P1", name="ساختمان", target_end_date=DAY(-1))), "پایان هدف"),
      "the target end cannot be before the start")
check(raises(lambda: prj.save_project(company_id, uid, F(S)), "کد و نام"), "a new project needs a code and a name")
pid = prj.save_project(company_id, uid, F(S, code="P1", name="ساختمان اداری", customer_detail_account_id=client,
                                          manager_employee_id=manager, target_end_date=DAY(8), contract_amount=D(5_000_000_000)))
p = prj.get_project(company_id, pid)
with new_session() as s:
    detail = s.get(DetailAccount, p.project_detail_account_id)
check(detail.code == "P1" and detail.name == "ساختمان اداری" and p.manager == "سارا کریمی" and p.customer == "کارفرمای نمونه",
      "the project creates its project detail account and keeps client and manager")
check(raises(lambda: prj.save_project(company_id, uid, F(S, project_detail_account_id=p.project_detail_account_id)), "تعریف شده"),
      "one project per project detail account")
check(p.project_detail_account_id not in {d for _l, d in prj.free_project_details(company_id)}, "a used detail is not offered again")

T = prj.TaskFields
design = prj.save_task(company_id, pid, T("طراحی"))
a = prj.save_task(company_id, pid, T("نقشهٔ معماری", 3, design, responsible_employee_id=manager, planned_cost=D(30_000_000)))
b = prj.save_task(company_id, pid, T("نقشهٔ سازه", 2, design, planned_cost=D(20_000_000)))
build = prj.save_task(company_id, pid, T("اجرا"))
c = prj.save_task(company_id, pid, T("فونداسیون", 4, build, planned_cost=D(40_000_000)))
d = prj.save_task(company_id, pid, T("تجهیز کارگاه", 2, build, planned_cost=D(10_000_000)))
m = prj.save_task(company_id, pid, T("تحویل فونداسیون", 0, build))
prj.add_link(company_id, a, b)
prj.add_link(company_id, b, c)
prj.add_link(company_id, a, d, "SS", 1)
prj.add_link(company_id, c, m)
prj.add_link(company_id, d, m)
check(raises(lambda: prj.add_link(company_id, c, a), "حلقه"), "a loop is refused")
check(raises(lambda: prj.add_link(company_id, design, c), "فاز"), "a phase takes no link")
check(raises(lambda: prj.add_link(company_id, b, a), "وجود دارد"), "a second link between the same pair is refused")
check(raises(lambda: prj.save_task(company_id, pid, T("زیرکار", 1, a)), "پیوند دارد"), "a linked task cannot become a phase")

plan = sch.compute(company_id, pid, as_of=DAY(-1))
r = {t.task_id: t for t in plan.tasks}
check([t.wbs for t in plan.tasks] == ["1", "1.1", "1.2", "2", "2.1", "2.2", "2.3"], f"WBS numbers ({[t.wbs for t in plan.tasks]})")
check((r[a].start, r[a].finish, r[b].start, r[b].finish) == (DAY(0), DAY(2), DAY(3), DAY(4)), "finish-to-start in working days")
check((r[c].start, r[c].finish) == (DAY(5), DAY(9)), f"Friday is skipped ({r[c].start}..{r[c].finish})")
check((r[d].start, r[d].finish) == (DAY(1), DAY(2)) and r[d].predecessors == "1.1SS+1", "start-to-start with one day lag")
check(r[m].is_milestone and r[m].start == DAY(9), "the milestone sits on its predecessor's finish")
check([x for x in (a, b, c, d, m) if r[x].critical] == [a, b, c, m] and r[d].total_float == 6, "critical path and float")
check((r[design].start, r[design].finish, r[build].start, r[build].finish) == (DAY(0), DAY(4), DAY(1), DAY(9))
      and r[design].is_summary and r[design].planned_cost == D(50_000_000), "phases roll up dates and cost")
check(plan.finish == DAY(9) and plan.planned_cost == D(100_000_000) and plan.percent == 0, "project finish and cost")

check(prj.set_baseline(company_id, pid) == 5, "baseline for every task")
check(raises(lambda: prj.update_progress(company_id, design, D(50)), "فاز"), "a phase's progress comes from its tasks")
check(raises(lambda: prj.update_progress(company_id, a, D(100), DAY(0), DAY(1), today=DAY(0)), "بعد از امروز"),
      "actual dates cannot be in the future")
prj.update_progress(company_id, a, D(100), DAY(0), DAY(1), today=DAY(4))
prj.update_progress(company_id, b, D(50), DAY(2), today=DAY(4))
plan = sch.compute(company_id, pid, as_of=DAY(4))
r = {t.task_id: t for t in plan.tasks}
check(r[a].finish == DAY(1) and r[b].start == DAY(2) and r[c].start == DAY(4) and r[c].finish == DAY(8),
      "actual dates move the successors")
check(r[a].baseline_finish == DAY(2) and r[a].state_code == "DONE" and r[b].state_code == "LATE",
      f"baseline kept; a half-done task past its finish is late ({r[a].baseline_finish}, {r[a].state_code}, {r[b].state_code})")
check(plan.percent == D("36.36") and r[design].percent == D("80.00"), f"weighted progress ({plan.percent}, {r[design].percent})")
check(plan.planned_percent == D("63.64"), f"planned progress against the baseline ({plan.planned_percent})")
check(raises(lambda: prj.delete_task(company_id, design), "پیشرفت"), "a task with progress cannot be deleted")

extra = prj.save_task(company_id, pid, T("موقت", 1))
prj.delete_task(company_id, extra)
check(prj.move_task(company_id, build, -1) and [t.name for t in sch.compute(company_id, pid).tasks][0] == "اجرا"
      and not prj.move_task(company_id, build, -1), "moving a phase up renumbers the WBS")
prj.move_task(company_id, build, 1)

hid = calendar.add_holiday(company_id, uid, DAY(5), "تعطیل")
check(sch.compute(company_id, pid, as_of=DAY(4)).by_id()[c].finish == DAY(9), "a holiday pushes the work one day")
calendar.delete_holiday(company_id, uid, hid)

prj.save_project(company_id, uid, F(S, name="ساختمان اداری", status_code="ACTIVE", manager_employee_id=manager), pid)
check(raises(lambda: prj.delete_project(company_id, pid), "در جریان"), "an active project is not deleted")

# فرم و نمودار
from PySide6.QtWidgets import QApplication, QPushButton
qapp = QApplication.instance() or QApplication([])
from peecha.ui import report_export
from peecha.ui.screens.projects import ProjectsScreen

printed = []
report_export.print_report = lambda parent, title, headers, rows, **kw: printed.append((title, rows))
screen = ProjectsScreen()
screen.refresh()
screen.project_table.setCurrentCell(0, 0)
check(screen.project_id == pid and screen.tree.topLevelItemCount() == 2 and screen.link_table.rowCount() == 5,
      "the form shows the phases and the links")
check("۳۶٫۳۶" in screen.summary_label.text() or "۳۶.۳۶" in screen.summary_label.text(), f"summary ({screen.summary_label.text()})")
screen.tree.setCurrentItem(screen.tree.topLevelItem(1).child(1))
screen.task_name_field.setText("تجهیز و آماده‌سازی کارگاه")
check(screen.save_task() and "تجهیز و آماده‌سازی کارگاه" in [t.name for t in screen.schedule.tasks], "edit a task from the form")
screen.new_task()
screen.task_name_field.setText("گزارش نهایی")
screen.duration_field.setValue(2)
new_id = screen.save_task()
screen.tree.setCurrentItem(screen.tree.topLevelItem(2))
screen.pred_combo.setCurrentIndex(screen.pred_combo.findData(m))
link = screen.add_link()
check(link and screen.schedule.by_id()[new_id].start > screen.schedule.by_id()[m].start, f"link from the form ({screen.status_label.text()})")
check(screen.print_schedule() and printed and len(printed[0][1]) == 8, "print the schedule")
image = screen.gantt.grab()
check(not image.isNull() and screen.gantt.minimumWidth() > 300, "the Gantt chart paints")
check(all(len(b.text()) <= 2 for b in screen.findChildren(QPushButton) if b.text()), "icon buttons only")

from peecha import nav_catalog
check(any(i.get("screen") == "projects" for i in nav_catalog.flatten_nav_items()), "menu entry")

finish()
