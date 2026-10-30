"""R368: ارزیابی عملکرد: قالب با جمع وزن ۱۰۰ و قفل پس از استفاده، دوره و ساخت ارزیابی برای کارکنان فعال با ارزیاب مدیر واحد
(و مدیر واحد بالاتر برای خود مدیر)، خودارزیابی فقط خود کارمند، ارزیابی مدیر فقط ارزیاب، امتیاز وزنی و رده، نهایی‌کردن با مجوز،
دورهٔ بسته، کارتابل، گزارش؛ و فرم."""
import datetime, os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r368"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prd_fixture import *  # noqa: F401,F403

from peecha import session as app_session
from peecha.db.models.security import User
from peecha.services import hr, hr_appraisals as ap, operational_tasks, users as users_service

lang = company.default_language_id
U = lambda login, name: users_service.create_user(login, name, "secret123", None, lang, False, [company_id], company_id).user_id  # noqa: E731
ceo_user, boss_user, w1_user = U("ceo", "مدیرعامل"), U("boss", "مدیر فنی"), U("w1", "کارشناس")
hq = hr.create_org_unit(company_id, "HQ", "ستاد", None, None)
eng = hr.create_org_unit(company_id, "ENG", "فنی", hq, None)
p_hq = hr.create_position(company_id, "CEO", "مدیرعامل", hq, None, 1)
p_eng = hr.create_position(company_id, "ENG", "کارشناس", eng, None, 5)
hired = today - datetime.timedelta(days=400)
E = lambda code, first, pos: hr.create_employee(company_id, code, first, "آزمون", None, hired, hq if pos == p_hq else eng, pos,  # noqa: E731
                                                D(100_000_000), None)
ceo, boss, w1, w2 = E("E0", "مدیر", p_hq), E("E1", "سرپرست", p_eng), E("E2", "علی", p_eng), E("E3", "مینا", p_eng)
for emp, usr in ((ceo, ceo_user), (boss, boss_user), (w1, w1_user)):
    hr.set_employee_user(company_id, emp, usr)
hr.set_org_unit_manager(company_id, hq, ceo)
hr.set_org_unit_manager(company_id, eng, boss)

CF = ap.CriterionFields
check(raises(lambda: ap.save_template(company_id, "T1", "قالب", [CF("کیفیت", D(60)), CF("سرعت", D(30))]), "۱۰۰"), "weights must total 100")
t1 = ap.save_template(company_id, "t1", "قالب کارشناسی", [CF("کیفیت کار", D(50)), CF("همکاری", D(30)), CF("نظم", D(20))])
check(raises(lambda: ap.save_cycle(company_id, "دوره", t1, today, today - datetime.timedelta(days=1)), "بازه"), "a valid period")
c1 = ap.save_cycle(company_id, "ارزیابی سالانهٔ ۱۴۰۵", t1, today - datetime.timedelta(days=180), today)
check(ap.open_cycle(company_id, c1) == 4, "appraisals for all active employees")
check(raises(lambda: ap.save_template(company_id, "T1", "قالب کارشناسی", [CF("کیفیت کار", D(100))], t1), "قالب جدید"),
      "criteria of a used template are locked")
check(ap.save_template(company_id, "T1", "قالب کارشناسی (نام جدید)", [CF("کیفیت کار", D(50)), CF("همکاری", D(30)), CF("نظم", D(20))], t1) == t1,
      "renaming a used template keeps its criteria")
rows = {a.employee_id: a for a in ap.list_appraisals(company_id, c1)}
check(rows[w1].reviewer_employee_id == boss and rows[boss].reviewer_employee_id == ceo and rows[ceo].reviewer_employee_id is None,
      "the reviewer is the unit manager, and the parent unit's manager for the manager")
check(all(a.status_code == "PENDING_SELF" for a in rows.values()), "self assessment comes first")

a1 = ap.get_appraisal(company_id, rows[w1].appraisal_id)
crit = {s.title: s.criterion_id for s in a1.scores}
self_scores = {crit["کیفیت کار"]: 4, crit["همکاری"]: 5, crit["نظم"]: 3}
check(raises(lambda: ap.submit_self(company_id, boss_user, a1.appraisal_id, self_scores), "خود کارمند"), "only the employee self-assesses")
check(raises(lambda: ap.submit_self(company_id, w1_user, a1.appraisal_id, {crit["نظم"]: 3}), "همهٔ معیارها"), "all criteria must be scored")
check(raises(lambda: ap.submit_review(company_id, boss_user, a1.appraisal_id, self_scores), "خودارزیابی"), "the manager waits for the self assessment")
inbox = {t.kind for t in operational_tasks.list_operational_tasks(company_id, w1_user)}
check("HR_APPRAISAL_SELF" in inbox, "the employee's inbox asks for the self assessment")
ap.submit_self(company_id, w1_user, a1.appraisal_id, self_scores, "سال خوبی بود")
review = [t for t in operational_tasks.list_operational_tasks(company_id, boss_user) if t.kind == "HR_APPRAISAL_REVIEW"]
check(len(review) == 1 and review[0].title.startswith("1 "), "the reviewer's inbox shows the waiting review")
check(raises(lambda: ap.submit_review(company_id, w1_user, a1.appraisal_id, self_scores), "ارزیاب"), "only the reviewer reviews")
mgr = {crit["کیفیت کار"]: 5, crit["همکاری"]: 4, crit["نظم"]: 2}
score = ap.submit_review(company_id, boss_user, a1.appraisal_id, mgr, strengths="دقت", improvements="نظم", goals="مستندسازی")
check(score == D("4.10") and ap.band(score) == "GOOD", f"weighted score (5×50+4×30+2×20)/100 = 4.1 ({score})")
check(raises(lambda: ap.finalize(company_id, boss_user, [a1.appraisal_id]), "مجوز"), "finalizing needs the approval permission")
ap.finalize(company_id, uid, [a1.appraisal_id])
check(raises(lambda: ap.submit_review(company_id, boss_user, a1.appraisal_id, mgr), "نهایی"), "a finalized appraisal is locked")
check(ap.history(company_id, w1) == [("ارزیابی سالانهٔ ۱۴۰۵", D("4.10"), "خوب")], "the employee's finalized history")

ap.reassign_reviewer(company_id, rows[w2].appraisal_id, ceo)
check(raises(lambda: ap.reassign_reviewer(company_id, rows[w2].appraisal_id, w2), "خودش"), "an employee does not review themselves")
report = ap.cycle_report(company_id, c1)
check(report["average"] == D("4.10") and ("خوب", 1) in report["bands"] and report["units"][0][0] == "فنی", f"cycle report ({report})")
check(ap.close_cycle(company_id, c1) == 3 and raises(lambda: ap.submit_self(company_id, w1_user, rows[w2].appraisal_id, self_scores), "باز نیست"),
      "a closed cycle is read-only and reports unfinished appraisals")
check(not [t for t in operational_tasks.list_operational_tasks(company_id, boss_user) if t.kind.startswith("HR_APPRAISAL")],
      "a closed cycle leaves the inbox")

# فرم
from PySide6.QtWidgets import QApplication, QPushButton
qapp = QApplication.instance() or QApplication([])
from peecha.ui.screens.hr_appraisals import HrAppraisalsScreen

c2 = ap.save_cycle(company_id, "ارزیابی میان‌دوره", t1, today - datetime.timedelta(days=30), today, self_assessment=False)
screen = HrAppraisalsScreen()
screen.refresh()
check(screen.template_table.rowCount() == 1 and screen.cycle_table.rowCount() == 2, "templates and cycles listed")
row = next(i for i, c in enumerate(screen.cycles) if c.cycle_id == c2)
screen.cycle_table.setCurrentCell(row, 0)
screen.cy_unit.setCurrentIndex(screen.cy_unit.findData(eng))
check(screen.open_cycle() == 3, f"open a cycle for one unit from the form ({screen.status_label.text()})")
app_session.current_user = User(user_id=boss_user, username="boss")
screen.refresh()
screen.review_cycle.setCurrentIndex(screen.review_cycle.findData(c2))
screen.only_mine.setChecked(True)
check(screen.appraisal_table.rowCount() == 2, f"only my reviews ({screen.appraisal_table.rowCount()})")
screen.appraisal_table.setCurrentCell(0, 0)
screen._load_appraisal()
for spin in screen.review_scores.spins.values():
    spin.setValue(3)
check(screen.submit_review() and screen.current.overall_score == D(3), f"review from the form ({screen.status_label.text()})")
app_session.current_user = User(user_id=uid, username="admin")
screen.refresh()
screen.review_cycle.setCurrentIndex(screen.review_cycle.findData(c2))
reviewed = next(i for i, a in enumerate(screen.appraisals) if a.status_code == "REVIEWED")
screen.appraisal_table.setCurrentCell(reviewed, 0)
check(screen.finalize() == 1, "finalize from the form")
check(screen.band_table.rowCount() == 5, "results tab")
check(all(len(b.text()) <= 2 for b in screen.findChildren(QPushButton) if b.text()), "icon buttons only")

finish()
