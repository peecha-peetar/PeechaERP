"""R364: کارکرد پروژه: اعتبارسنجی (روز آینده، سقف ۲۴ ساعت، فاز، پروژهٔ بسته)، ارسال، تایید فقط با مدیر پروژه یا مجوز و نه
کارکرد خود، رد با دلیل و ویرایش دوباره، نرخ ساعتی کارمند و پیش‌فرض از تاریخ و ثابت‌شدن نرخ هنگام تایید، کارتابل، هزینهٔ دفاتر
(بدون پیش‌نویس) و درآمد و سود پروژه، جلوگیری از حذف، API موبایل با کلید تکرارنشدن؛ و فرم‌ها."""
import datetime, os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r364"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prd_fixture import *  # noqa: F401,F403

from peecha.services import hr, journal_entries as je, operational_tasks, users as users_service
from peecha.services.projects import core as prj, costs, timesheets as ts

lang_id = company.default_language_id
pm_user = users_service.create_user("pm", "مدیر پروژه", "secret123", None, lang_id, False, [company_id], company_id).user_id
staff_user = users_service.create_user("staff", "کارشناس", "secret123", None, lang_id, False, [company_id], company_id).user_id
stranger = users_service.create_user("stranger", "بی‌پرونده", "secret123", None, lang_id, False, [company_id], company_id).user_id
org = hr.create_org_unit(company_id, "ENG", "فنی", None, None)
pos = hr.create_position(company_id, "ENG", "کارشناس", org, None, 5)
hired = today - datetime.timedelta(days=400)
pm = hr.create_employee(company_id, "E1", "سارا", "کریمی", None, hired, org, pos, D(90_000_000), None)
worker = hr.create_employee(company_id, "E2", "رضا", "نوری", None, hired, org, pos, D(70_000_000), None)
hr.set_employee_user(company_id, pm, pm_user)
hr.set_employee_user(company_id, worker, staff_user)

pid = prj.save_project(company_id, uid, prj.ProjectFields(today - datetime.timedelta(days=30), code="P1", name="پروژهٔ آزمون",
                                                         manager_employee_id=pm, status_code="ACTIVE"))
phase = prj.save_task(company_id, pid, prj.TaskFields("طراحی"))
a = prj.save_task(company_id, pid, prj.TaskFields("نقشه", 5, phase, responsible_employee_id=worker, planned_hours=D(40),
                                                  planned_cost=D(20_000_000)))
b = prj.save_task(company_id, pid, prj.TaskFields("محاسبات", 3, phase, planned_cost=D(10_000_000)))
ts.save_rate(company_id, None, today - datetime.timedelta(days=100), D(400_000))
ts.save_rate(company_id, worker, today - datetime.timedelta(days=10), D(600_000))
check(ts.save_rate(company_id, None, today - datetime.timedelta(days=100), D(400_000)) == ts.list_rates(company_id)[0].rate_id
      and len(ts.list_rates(company_id)) == 2, "the same date replaces the rate instead of duplicating it")

E = ts.EntryFields
d20, d5 = today - datetime.timedelta(days=20), today - datetime.timedelta(days=5)
check(raises(lambda: ts.save_entry(company_id, uid, E(pid, worker, today + datetime.timedelta(days=1), D(2), a)), "بعد از امروز"),
      "no time on a future day")
check(raises(lambda: ts.save_entry(company_id, uid, E(pid, worker, d5, D(2), phase)), "فاز"), "time goes on a task, not a phase")
check(raises(lambda: ts.save_entry(company_id, uid, E(pid, worker, d5, D(0), a)), "۲۴"), "hours must be positive")
e1 = ts.save_entry(company_id, uid, E(pid, worker, d20, D(8), a, "نقشهٔ طبقهٔ اول"), submit=True)
e2 = ts.save_entry(company_id, uid, E(pid, worker, d5, D(6), b), submit=True)
check(raises(lambda: ts.save_entry(company_id, uid, E(pid, worker, d5, D(19), a)), "۲۴ ساعت"), "a day holds at most 24 hours")
e3 = ts.save_entry(company_id, uid, E(pid, pm, d5, D(3), a))
check(raises(lambda: ts.save_entry(company_id, uid, E(pid, worker, d20, D(1), a), e1), "ویرایش"), "a submitted entry is locked")
check(ts.submit(company_id, [e3]) == 1, "a draft is submitted")

check(not ts.can_approve(company_id, stranger, pid) and ts.can_approve(company_id, pm_user, pid), "the project manager approves")
check(raises(lambda: ts.approve(company_id, stranger, [e1]), "مدیر پروژه"), "others cannot approve")
check(raises(lambda: ts.approve(company_id, pm_user, [e3]), "خودتان"), "the manager cannot approve their own time")
tasks = {t.kind: t for t in operational_tasks.list_operational_tasks(company_id, pm_user)}
check("PRJ_TIMESHEET" in tasks and "۳" not in tasks["PRJ_TIMESHEET"].title and tasks["PRJ_TIMESHEET"].title.startswith("3"),
      f"the manager's inbox shows the waiting time ({tasks.get('PRJ_TIMESHEET')})")
check("PRJ_TIMESHEET" not in {t.kind for t in operational_tasks.list_operational_tasks(company_id, stranger)}, "not for others")
check(ts.approve(company_id, pm_user, [e1, e2]) == 2 and ts.approve(company_id, uid, [e3]) == 1, "approve in bulk")
rows = {r.entry_id: r for r in ts.list_entries(company_id, project_id=pid)}
check(rows[e1].hourly_cost == D(400_000) and rows[e2].hourly_cost == D(600_000) and rows[e1].cost == D(3_200_000),
      "the rate valid on the work day is frozen at approval")
check(raises(lambda: ts.reject(company_id, pm_user, [e1], "x"), "ارسال‌شده"), "an approved entry is final")
e4 = ts.save_entry(company_id, uid, E(pid, worker, d5, D(2), a), submit=True)
check(raises(lambda: ts.reject(company_id, pm_user, [e4], " "), "دلیل"), "rejecting needs a reason")
ts.reject(company_id, pm_user, [e4], "ساعت اشتباه است")
check(ts.save_entry(company_id, uid, E(pid, worker, d5, D(1.5), a), e4, submit=True) == e4
      and ts.list_entries(company_id, status="SUBMITTED")[0].hours == D("1.5"), "a rejected entry is corrected and sent again")

# هزینهٔ دفاتر و درآمد با تفصیلی پروژه
from peecha.services import detail_dimensions as dims
ptype = dims.get_specialized_dimension_type_id(company_id, dims.PROJECT_CODE)
pdetail = prj.get_project(company_id, pid).project_detail_account_id
g6 = A("6", "هزینه‌های عمومی", "DEBIT", "EXPENSE", "TEMPORARY", False)
k61 = A("61", "هزینهٔ پروژه‌ها", "DEBIT", "EXPENSE", "TEMPORARY", False, g6.account_id)
site_exp = A("611", "هزینهٔ کارگاه", "DEBIT", "EXPENSE", "TEMPORARY", True, k61.account_id)
g7 = A("7", "درآمدها", "CREDIT", "REVENUE", "TEMPORARY", False)
k71 = A("71", "درآمد پیمان", "CREDIT", "REVENUE", "TEMPORARY", False, g7.account_id)
rev = A("711", "درآمد پیمانکاری", "CREDIT", "REVENUE", "TEMPORARY", True, k71.account_id)
L = je.LineInput
je.create_journal_entry(company_id, uid, today, "هزینهٔ کارگاه", [
    L(site_exp.account_id, "مصالح", D(10_000_000), D(0), {ptype: pdetail}), L(ap_gl.account_id, "", D(0), D(10_000_000))])
je.create_journal_entry(company_id, uid, today, "صورت‌وضعیت", [
    L(inv_gl.account_id, "", D(50_000_000), D(0)), L(rev.account_id, "درآمد", D(0), D(50_000_000), {ptype: pdetail})])
je.create_journal_entry(company_id, uid, today, "پیش‌نویس", [
    L(site_exp.account_id, "", D(99_000_000), D(0), {ptype: pdetail}), L(ap_gl.account_id, "", D(0), D(99_000_000))], as_draft=True)
c = costs.project_cost(company_id, pid)
check(c.gl_cost == D(10_000_000) and c.revenue == D(50_000_000) and [r.name for r in c.cost_accounts] == ["هزینهٔ کارگاه"],
      f"ledger cost and revenue come from non-draft entries with the project detail ({c.gl_cost}, {c.revenue})")
check(c.labor_hours == D(17) and c.labor_cost == D(8_000_000) and c.pending_hours == D("1.5") and c.unpriced_hours == 0,
      f"labour hours and cost ({c.labor_hours}, {c.labor_cost}, {c.pending_hours})")
check(c.total_cost == D(18_000_000) and c.margin == D(32_000_000) and c.planned_cost == D(30_000_000) and c.budget_left == D(12_000_000),
      "total cost, margin and budget left")
labor = {t.task_id: t for t in c.tasks}
check(labor[a].hours == D(11) and labor[a].cost == D(4_400_000) and labor[b].cost == D(3_600_000), "labour by task")

check(raises(lambda: prj.delete_task(company_id, b), "کارکرد"), "a task with time cannot be deleted")
prj.save_project(company_id, uid, prj.ProjectFields(today - datetime.timedelta(days=30), name="پروژهٔ آزمون", manager_employee_id=pm,
                                                     status_code="CANCELLED"), pid)
check(raises(lambda: prj.delete_project(company_id, pid), "کارکرد"), "a project with time cannot be deleted")
check(raises(lambda: ts.save_entry(company_id, uid, E(pid, worker, d5, D(1), a)), "در حال برنامه‌ریزی یا اجرا"), "no time on a closed project")
prj.save_project(company_id, uid, prj.ProjectFields(today - datetime.timedelta(days=30), name="پروژهٔ آزمون", manager_employee_id=pm,
                                                     status_code="ACTIVE"), pid)

# API موبایل
from fastapi.testclient import TestClient
from peecha_api.main import app
client = TestClient(app)


def h(login, key=None):
    token = client.post("/auth/login", json={"username": login, "password": "secret123"}).json()["access_token"]
    return {"Authorization": "Bearer " + token, **({"Idempotency-Key": key} if key else {})}


r = client.get("/self/projects", headers=h("staff"))
check(r.status_code == 200 and r.json()[0]["project_id"] == pid and r.json()[0]["tasks"][0]["task_id"] == a
      and r.json()[0]["tasks"][0]["mine"] is True, f"open projects with my tasks first ({r.text[:200]})")
body = {"project_id": pid, "task_id": b, "work_date": today.isoformat(), "hours": "4.5", "description": "بازدید"}
first = client.post("/self/timesheets", json=body, headers=h("staff", "k-1"))
again = client.post("/self/timesheets", json=body, headers=h("staff", "k-1"))
check(first.status_code == 201 and again.json()["entry_id"] == first.json()["entry_id"] and first.json()["status_code"] == "SUBMITTED"
      and len(ts.list_entries(company_id, employee_id=worker, date_from=today)) == 1, "one submitted entry for a repeated request")
bad = client.post("/self/timesheets", json={**body, "work_date": (today + datetime.timedelta(days=2)).isoformat()}, headers=h("staff", "k-2"))
check(bad.status_code == 400 and "امروز" in bad.json()["detail"], "a future day is refused with a clear message")
mine = client.get("/self/timesheets", headers=h("staff")).json()
check(len(mine) == 4 and mine[0]["hours"] == "4.50", f"my recent time ({len(mine)})")
check(client.get("/self/projects", headers=h("stranger")).status_code == 404, "a user without an employee file gets 404")

# فرم‌ها
from PySide6.QtWidgets import QApplication, QPushButton
qapp = QApplication.instance() or QApplication([])
from peecha.ui.screens.project_timesheets import ProjectTimesheetsScreen
from peecha.ui.screens.projects import ProjectsScreen

screen = ProjectTimesheetsScreen()
screen.refresh()
screen.project_combo.setCurrentIndex(screen.project_combo.findData(pid))
screen.task_combo.setCurrentIndex(screen.task_combo.findData(a))
screen.employee_combo.setCurrentIndex(screen.employee_combo.findData(worker))
screen.hours_field.setValue(2)
check(screen.save_entry(True) and screen.pending_table.rowCount() == 3, f"enter and send time from the form ({screen.status_label.text()})")
screen.pending_table.selectAll()
check(screen.approve_selected() == 3 and screen.pending_table.rowCount() == 0, "bulk approval from the form")
screen.rate_field.setText("۷۰۰٬۰۰۰")
check(screen.save_rate() and len(screen.rates) == 3, "save a rate from the form")
check(all(len(x.text()) <= 2 for x in screen.findChildren(QPushButton) if x.text()), "icon buttons only")
projects = ProjectsScreen()
projects.refresh()
projects.project_table.setCurrentCell(0, 0)
check(projects.costs is not None and projects.labor_table.rowCount() == 2 and "سود ناخالص" in projects.cost_label.text(),
      f"the cost tab ({projects.cost_label.text()[:80]})")

finish()
