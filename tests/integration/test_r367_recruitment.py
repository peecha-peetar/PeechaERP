"""R367: جذب و استخدام: اعتبارسنجی فرصت و متقاضی (کد ملی یکتا)، درخواست فقط برای فرصت باز و یک بار، مراحل با سابقه، مصاحبه
با امتیاز میانگین، پیشنهاد در سقف حقوق، استخدام با ساخت پروندهٔ پرسنلی و تکمیل ظرفیت، رد با دلیل و بازگشایی، کارتابل
مصاحبه‌گر و کارشناس، گزارش مراحل و منابع؛ و فرم."""
import datetime, os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r367"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prd_fixture import *  # noqa: F401,F403

from peecha.db.models.hr import Employee
from peecha.services import hr, hr_recruitment as rec, operational_tasks, users as users_service

org = hr.create_org_unit(company_id, "ENG", "فنی", None, None)
pos = hr.create_position(company_id, "DEV", "برنامه‌نویس", org, None, 5)
boss_user = users_service.create_user("boss", "مدیر فنی", "secret123", None, company.default_language_id, False, [company_id], company_id).user_id
boss = hr.create_employee(company_id, "E1", "نرگس", "امیری", None, today - datetime.timedelta(days=500), org, pos, D(120_000_000), None)
hr.set_employee_user(company_id, boss, boss_user)

OF = rec.OpeningFields
check(raises(lambda: rec.save_opening(company_id, uid, OF("J1", "برنامه‌نویس", pos, today, salary_min=D(80), salary_max=D(50))), "سقف"),
      "salary max below min is refused")
check(raises(lambda: rec.save_opening(company_id, uid, OF("J1", "برنامه‌نویس", pos, today, close_by=today - datetime.timedelta(days=1))),
             "مهلت"), "a deadline before the start is refused")
o1 = rec.save_opening(company_id, uid, OF("j1", "برنامه‌نویس ارشد", pos, today, 2, salary_min=D(50_000_000), salary_max=D(80_000_000),
                                          hiring_manager_employee_id=boss))
o2 = rec.save_opening(company_id, uid, OF("J2", "کارآموز", pos, today, status_code="ON_HOLD"))
check(raises(lambda: rec.save_opening(company_id, uid, OF("J1", "تکراری", pos, today)), "تکراری"), "opening codes are unique")

CF = rec.CandidateFields
check(raises(lambda: rec.save_candidate(company_id, CF("علی", "", "0012345678")), "نام خانوادگی"), "a candidate needs a full name")
check(raises(lambda: rec.save_candidate(company_id, CF("علی", "رضایی", "۱۲۳")), "۱۰ رقم"), "a national id has ten digits")
c1 = rec.save_candidate(company_id, CF("علی", "رضایی", "۰۰۱۲۳۴۵۶۷۸", "۰۹۱۲۱۱۱۲۲۳۳", source_code="REFERRAL",
                                       experience_years=D(6)))
c2 = rec.save_candidate(company_id, CF("مینا", "صادقی", "0098765432", source_code="JOB_BOARD"))
c3 = rec.save_candidate(company_id, CF("حسن", "کاظمی", source_code="JOB_BOARD"))
check(raises(lambda: rec.save_candidate(company_id, CF("دیگری", "تکراری", "0012345678")), "قبلاً"), "a national id is registered once")
check([c.candidate_id for c in rec.list_candidates(company_id, "۰۹۱۲۱۱۱")] == [c1], "search by mobile in Persian digits")

a1 = rec.apply(company_id, uid, o1, c1)
a2 = rec.apply(company_id, uid, o1, c2)
check(raises(lambda: rec.apply(company_id, uid, o1, c1), "درخواست دارد"), "one application per opening")
check(raises(lambda: rec.apply(company_id, uid, o2, c1), "غیرباز"), "no application to a held opening")
check(rec.advance(company_id, uid, a1) == "SCREENING", "advance to screening")
when = datetime.datetime.combine(today + datetime.timedelta(days=1), datetime.time(10)).astimezone()
i1 = rec.schedule_interview(company_id, uid, a1, when, boss, "VIDEO")
check(rec.list_applications(company_id, o1)[-1].stage_code == "INTERVIEW", "scheduling an interview moves to the interview stage")
inbox = [t for t in operational_tasks.list_operational_tasks(company_id, boss_user) if t.kind == "HR_INTERVIEW"]
check(len(inbox) == 1 and inbox[0].document_id == a1 and "علی رضایی" in inbox[0].title, "the interviewer's inbox shows the interview")
check(raises(lambda: rec.record_interview(company_id, i1, 6, "HIRE"), "۱ تا ۵"), "scores are 1 to 5")
rec.record_interview(company_id, i1, 4, "HIRE", "مسلط")
i2 = rec.schedule_interview(company_id, uid, a1, when, None, "IN_PERSON")
rec.record_interview(company_id, i2, 5, "HIRE")
i3 = rec.schedule_interview(company_id, uid, a1, when, boss)
rec.cancel_interview(company_id, i3)
row = next(a for a in rec.list_applications(company_id) if a.application_id == a1)
check(row.rating == D("4.5") and row.interviews == 2, f"the rating averages done interviews ({row.rating}, {row.interviews})")
check(not [t for t in operational_tasks.list_operational_tasks(company_id, boss_user) if t.kind == "HR_INTERVIEW"],
      "done and cancelled interviews leave the inbox")
check(raises(lambda: rec.advance(company_id, uid, a1), "پیشنهاد همکاری"), "after the interview comes the offer")
check(raises(lambda: rec.make_offer(company_id, uid, a1, D(90_000_000), today), "سقف"), "an offer above the salary range is refused")
check(raises(lambda: rec.hire(company_id, uid, a1, "E9"), "پیشنهاد"), "no hire before an offer")
start = today + datetime.timedelta(days=10)
rec.make_offer(company_id, uid, a1, D(70_000_000), start)
emp = rec.hire(company_id, uid, a1, "E9")
with new_session() as s:
    e = s.get(Employee, emp)
staff = {r.employee_id: r for r in hr.list_employees(company_id)}
check(e.first_name == "علی" and e.national_id == "0012345678" and e.hire_date == start and staff[emp].base_salary == D(70_000_000)
      and staff[emp].position_title == "برنامه‌نویس", "the hire creates the employee file with the offer")
steps = [h[2] for h in rec.history(company_id, a1)]
check(steps == ["دریافت درخواست", "بررسی اولیه", "مصاحبه", "پیشنهاد همکاری", "استخدام‌شده"], f"stage history ({steps})")
check(raises(lambda: rec.save_opening(company_id, uid, OF("J1", "برنامه‌نویس ارشد", pos, today, 0)), "دست‌کم"), "headcount at least one")

check(raises(lambda: rec.close(company_id, uid, a2, "REJECTED", " "), "دلیل"), "rejecting needs a reason")
rec.close(company_id, uid, a2, "REJECTED", "سابقهٔ کم")
rec.reopen(company_id, uid, a2)
rec.make_offer(company_id, uid, a2, D(60_000_000), start)
rec.hire(company_id, uid, a2, "E10")
check(next(o for o in rec.list_openings(company_id) if o.opening_id == o1).status_code == "FILLED", "the opening is filled at headcount")
check(raises(lambda: rec.apply(company_id, uid, o1, c3), "غیرباز"), "a filled opening takes no more applications")
check(raises(lambda: rec.save_opening(company_id, uid, OF("J1", "برنامه‌نویس ارشد", pos, today, 1, "FILLED"), o1), "استخدام شده"),
      "headcount cannot drop below hires")
rec.save_opening(company_id, uid, OF("J2", "کارآموز", pos, today), o2)
a3 = rec.apply(company_id, uid, o2, c3)
apps = [t for t in operational_tasks.list_operational_tasks(company_id, uid) if t.kind == "HR_APPLICATIONS"]
check(len(apps) == 1 and apps[0].title.startswith("1 "), "new applications reach the recruiter's inbox")
report = {r["opening"].opening_id: r for r in rec.pipeline_report(company_id)}
check(report[o1]["counts"]["HIRED"] == 2 and report[o1]["days_to_hire"] == 10.0 and report[o2]["counts"]["APPLIED"] == 1,
      "pipeline report with days to hire")
check(dict((s, (n, h)) for s, n, h in rec.source_report(company_id)) == {"سایت کاریابی": (2, 1), "معرفی همکاران": (1, 1)},
      "source effectiveness")

# فرم
from PySide6.QtWidgets import QApplication, QPushButton
qapp = QApplication.instance() or QApplication([])
from peecha.ui.screens.hr_recruitment import HrRecruitmentScreen

screen = HrRecruitmentScreen()
screen.refresh()
check(screen.opening_table.rowCount() == 2 and screen.candidate_table.rowCount() == 3 and screen.app_table.rowCount() == 3,
      "the form lists openings, candidates and applications")
screen.op_code.setText("J3")
screen.op_title.setText("حسابدار")
screen.op_position.setCurrentIndex(screen.op_position.findData(pos))
check(screen.save_opening() and screen.opening_table.rowCount() == 3, f"an opening from the form ({screen.status_label.text()})")
screen.c_first.setText("زهرا")
screen.c_last.setText("نوری")
check(screen.save_candidate() and screen.candidate_table.rowCount() == 4, "a candidate from the form")
o3 = next(o.opening_id for o in screen.openings if o.code == "J3")
c4 = next(c.candidate_id for c in screen.candidates if c.first_name == "زهرا")
screen.app_opening.setCurrentIndex(screen.app_opening.findData(o3))
screen.app_candidate.setCurrentIndex(screen.app_candidate.findData(c4))
a4 = screen.add_application()
row = next(i for i, a in enumerate(screen.applications) if a.application_id == a4)
screen.app_table.setCurrentCell(row, 0)
check(screen.advance() and screen.schedule_interview(), f"advance and schedule from the form ({screen.status_label.text()})")
screen.interview_table.setCurrentCell(0, 0)
screen.iv_score.setValue(3)
check(screen.record_interview() and "مصاحبه" in screen.history_label.text(), f"record the interview from the form ({screen.status_label.text()}, {screen.history_label.text()})")
screen.offer_salary.setText("۴۵٬۰۰۰٬۰۰۰")
screen.ask_text = lambda: "E11"
check(screen.offer() and screen.hire() and any(a.stage_code == "HIRED" and a.application_id == a4 for a in screen.applications),
      f"offer and hire from the form ({screen.status_label.text()})")
check(screen.report_table.rowCount() == 3 and screen.source_table.rowCount() == 3, "the recruitment report")
check(all(len(b.text()) <= 2 for b in screen.findChildren(QPushButton) if b.text()), "icon buttons only")

finish()
