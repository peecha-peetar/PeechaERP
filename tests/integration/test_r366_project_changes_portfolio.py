"""R366: درخواست تغییر (مبلغ، مدت و ردیف جدید فهرست بها؛ تایید فقط با مجوز، رد با دلیل، کد تکراری و قرارداد منفی) و سبد
پروژه‌ها با ارزش برنامه‌ای و کسب‌شده، شاخص زمان و هزینه، برآورد تکمیل و سلامت؛ کارتابل؛ و فرم‌ها."""
import datetime, os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r366"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prd_fixture import *  # noqa: F401,F403

from peecha.services import journal_entries as je, operational_tasks, users as users_service
from peecha.services.projects import billing as bl, changes as ch, core as prj, portfolio as pf
from peecha.services.workflow import calendar

days = {d: ("08:00", "16:00") for d in (5, 6, 0, 1, 2, 3)}
calendar.save_work_hours(company_id, uid, days)  # شنبه تا پنجشنبه
S = today + datetime.timedelta(days=7)
S -= datetime.timedelta(days=(S.weekday() - 5) % 7)
DAY = lambda n: S + datetime.timedelta(days=n + n // 6)  # noqa: E731  روز کاری n ام (جمعه‌ها رد می‌شوند)
staff = users_service.create_user("staff", "کارشناس", "secret123", None, company.default_language_id, False, [company_id], company_id).user_id

client_id = dimensions_service.create_customer(company_id, "C1", "کارفرما")
pid = prj.save_project(company_id, uid, prj.ProjectFields(S, code="P1", name="ساختمان", customer_detail_account_id=client_id,
                                                         target_end_date=DAY(19), contract_amount=D(1_000_000_000), status_code="ACTIVE"))
a = prj.save_task(company_id, pid, prj.TaskFields("سفت‌کاری", 10, planned_cost=D(20_000_000)))
b = prj.save_task(company_id, pid, prj.TaskFields("نازک‌کاری", 10, planned_cost=D(10_000_000)))
prj.add_link(company_id, a, b)
prj.set_baseline(company_id, pid)
bl.save_contract_item(company_id, pid, bl.ContractItemFields("01", "بتن", "متر مکعب", D(100), D(10_000_000)))

C, LF = ch.ChangeFields, ch.LineFields
check(raises(lambda: ch.save_change(company_id, staff, pid, C("خالی")), "مبلغ، مدت"), "a change must change something")
check(raises(lambda: ch.save_change(company_id, staff, pid, C("")), "عنوان"), "a change needs a title")
check(raises(lambda: ch.save_change(company_id, staff, pid, C("دو ردیف", lines=[LF("05", "الف", "عدد", D(1), D(1)),
                                                                                   LF("05", "ب", "عدد", D(1), D(1))])), "تکراری"),
      "duplicate codes inside one change are refused")
c1 = ch.save_change(company_id, staff, pid, C("افزایش طبقه", "درخواست کارفرما", D(200_000_000), 30,
                                              [LF("04", "طبقهٔ اضافه", "مترمربع", D(400), D(500_000))]), submit=True)
check(not ch.can_decide(company_id, staff) and raises(lambda: ch.approve(company_id, staff, c1), "مجوز"), "staff cannot approve")
tasks = [t for t in operational_tasks.list_operational_tasks(company_id, uid) if t.kind == "PRJ_CHANGE"]
check(len(tasks) == 1 and tasks[0].document_id == pid and "افزایش طبقه" in tasks[0].title, "the approver's inbox shows the change")
check(not [t for t in operational_tasks.list_operational_tasks(company_id, staff) if t.kind == "PRJ_CHANGE"], "not in the requester's inbox")
ch.approve(company_id, uid, c1, "موافقت")
p = prj.get_project(company_id, pid)
check(p.contract_amount == D(1_200_000_000) and p.target_end_date == DAY(19) + datetime.timedelta(days=30), "contract and target end move")
check([i.code for i in bl.list_contract_items(company_id, pid)] == ["01", "04"], "the new bill item is added")
check(raises(lambda: ch.save_change(company_id, staff, pid, C("x", amount_change=D(1)), c1), "ویرایش"), "an approved change is locked")

c2 = ch.save_change(company_id, staff, pid, C("کد تکراری", lines=[LF("01", "بتن دوم", "متر مکعب", D(1), D(1))]), submit=True)
check(raises(lambda: ch.approve(company_id, uid, c2), "وجود دارد"), "a clashing bill code blocks approval")
check(raises(lambda: ch.reject(company_id, uid, c2, " "), "دلیل"), "rejecting needs a reason")
ch.reject(company_id, uid, c2, "کد را عوض کنید")
check(ch.save_change(company_id, staff, pid, C("کد اصلاح‌شده", lines=[LF("05", "بتن دوم", "متر مکعب", D(1), D(1))]), c2) == c2
      and ch.list_changes(company_id, pid, "DRAFT")[0].change_id == c2, "a rejected change is corrected back to draft")
ch.delete_change(company_id, c2)
c3 = ch.save_change(company_id, staff, pid, C("کاهش زیاد", amount_change=D(-2_000_000_000)), submit=True)
check(raises(lambda: ch.approve(company_id, uid, c3), "منفی"), "the contract amount cannot go negative")
amount, extra_days, open_count = ch.approved_totals(company_id, pid)
check((amount, extra_days, open_count) == (D(200_000_000), 30, 1), "approved totals and open changes")

# سبد پروژه‌ها و ارزش کسب‌شده
prj.update_progress(company_id, a, D(40), S, today=DAY(9))
from peecha.services import detail_dimensions as dims
ptype = dims.get_specialized_dimension_type_id(company_id, dims.PROJECT_CODE)
g6 = A("6", "هزینه‌ها", "DEBIT", "EXPENSE", "TEMPORARY", False)
k61 = A("61", "هزینهٔ پروژه", "DEBIT", "EXPENSE", "TEMPORARY", False, g6.account_id)
site = A("611", "هزینهٔ کارگاه", "DEBIT", "EXPENSE", "TEMPORARY", True, k61.account_id)
je.create_journal_entry(company_id, uid, today, "هزینه", [
    je.LineInput(site.account_id, "", D(8_000_000), D(0), {ptype: p.project_detail_account_id}),
    je.LineInput(ap_gl.account_id, "", D(0), D(8_000_000))])
p2 = prj.save_project(company_id, uid, prj.ProjectFields(S, code="P2", name="انبار", status_code="PLANNING"))
rows = {r.project_id: r for r in pf.portfolio(company_id, as_of=DAY(4))}
r = rows[pid]
check(r.bac == D(30_000_000) and r.planned_percent == D(25) and r.percent == D(20), f"BAC and progress ({r.bac}, {r.planned_percent}, {r.percent})")
check(r.pv == D(7_500_000) and r.ev == D(6_000_000) and r.ac == D(8_000_000), f"PV, EV and AC ({r.pv}, {r.ev}, {r.ac})")
check(r.spi == D("0.80") and r.cpi == D("0.75") and r.eac == D(40_000_000) and r.health == "RED", f"SPI, CPI, EAC, health ({r.spi}, {r.cpi})")
check(r.contract_amount == D(1_200_000_000) and r.approved_changes == D(200_000_000) and r.open_changes == 1, "changes in the portfolio")
check(rows[p2].bac == 0 and rows[p2].spi is None and rows[p2].health == "GREEN" and rows[p2].finish is None, "an empty project")
t = pf.totals(list(rows.values()))
check(t["count"] == 2 and t["contract"] == D(1_200_000_000) and t["red"] == 1, f"totals ({t})")
check(raises(lambda: (prj.save_project(company_id, uid, prj.ProjectFields(S, name="ساختمان", status_code="CANCELLED"), pid),
                      prj.delete_project(company_id, pid)), "درخواست تغییر"), "a project with changes cannot be deleted")
prj.save_project(company_id, uid, prj.ProjectFields(S, name="ساختمان", customer_detail_account_id=client_id, target_end_date=DAY(49),
                                                     contract_amount=D(1_200_000_000), status_code="ACTIVE"), pid)

from peecha.services.dms import entities
with new_session() as s:
    label = entities.describe(s, company_id, "project", pid)
    found = entities.search(s, company_id, "project", "ساختمان")
check(label and "P۱" in label[0] and label[1] and [i for i, _l in found] == [pid], f"projects take related documents ({label}, {found})")

# فرم‌ها
from PySide6.QtWidgets import QApplication, QPushButton
qapp = QApplication.instance() or QApplication([])
from peecha.ui.screens.project_portfolio import ProjectPortfolioScreen
from peecha.ui.screens.projects import ProjectsScreen

portfolio = ProjectPortfolioScreen()
portfolio.refresh()
health = [portfolio.table.item(i, 4).text() for i in range(portfolio.table.rowCount())]
check(portfolio.table.rowCount() == 2 and pf.HEALTH["GREEN"] in health, f"the portfolio lists the open projects ({health})")
portfolio.filter_combo.setCurrentIndex(1)
check(portfolio.table.rowCount() == 2, "all projects")
screen = ProjectsScreen()
screen.open_project(pid, tab="changes")
tab = screen.changes_tab
check(screen.tabs.currentWidget() is tab and tab.change_table.rowCount() == 2, "open a project on its changes tab")
tab.title_field.setText("تمدید مهلت")
tab.days_field.setValue(10)
tab.line_code.setText("06")
tab.line_desc.setText("نما")
tab.line_unit.setText("مترمربع")
tab.line_qty.setText("۱۰۰")
tab.line_price.setText("۱٬۰۰۰٬۰۰۰")
check(tab.add_line() and tab.line_table.rowCount() == 1, "add a bill line to the change")
cid = tab.save(True)
check(cid is not None and tab.change_table.rowCount() == 3, f"submit a change from the form ({screen.status_label.text()})")
tab.change_table.setCurrentCell(0, 0)
check(tab.approve() and prj.get_project(company_id, pid).target_end_date == DAY(49) + datetime.timedelta(days=10)
      and "۰۶" in [screen.billing_tab.item_table.item(i, 0).text() for i in range(screen.billing_tab.item_table.rowCount())],
      f"approve from the form updates the project and its bill ({screen.status_label.text()})")
check(screen.related_documents_button.accessibleName() == "اسناد مرتبط", "related documents button on the project form")
check(all(len(x.text()) <= 2 for w in (portfolio, screen) for x in w.findChildren(QPushButton) if x.text()), "icon buttons only")

finish()
