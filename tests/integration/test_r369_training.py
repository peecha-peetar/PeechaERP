"""R369: آموزش: دوره و دوره‌های الزامی پست، کلاس با ظرفیت، نتیجه و گواهی با انقضا، برگزاری فقط با نتیجهٔ همه، لغو بی‌نتیجه،
ماتریس آموزش (معتبر، رو به انقضا، منقضی، در برنامه، انجام‌نشده)، کارتابل و گزارش ساعت و سهم هزینه؛ و فرم."""
import datetime, os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r369"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prd_fixture import *  # noqa: F401,F403

from peecha.services import hr, hr_training as tr, operational_tasks

org = hr.create_org_unit(company_id, "PRD", "تولید", None, None)
p_op = hr.create_position(company_id, "OP", "اپراتور", org, None, 10)
p_cl = hr.create_position(company_id, "CL", "کارمند دفتری", org, None, 5)
hired = today - datetime.timedelta(days=400)
e1 = hr.create_employee(company_id, "E1", "علی", "کاظمی", None, hired, org, p_op, D(80_000_000), None)
e2 = hr.create_employee(company_id, "E2", "رضا", "مرادی", None, hired, org, p_op, D(80_000_000), None)
e3 = hr.create_employee(company_id, "E3", "مینا", "نوری", None, hired, org, p_cl, D(70_000_000), None)

CF = tr.CourseFields
check(raises(lambda: tr.save_course(company_id, CF("SAFE", "ایمنی", D(0))), "ساعت"), "a course needs hours")
safe = tr.save_course(company_id, CF("safe", "ایمنی کار با ماشین", D(8), "SAFETY", 12, "مرکز آموزش"))
first = tr.save_course(company_id, CF("FIRST", "کمک‌های اولیه", D(4), "SAFETY"))
height = tr.save_course(company_id, CF("HEIGHT", "کار در ارتفاع", D(6), "SAFETY", 1))
fire = tr.save_course(company_id, CF("FIRE", "اطفای حریق", D(3), "SAFETY", 1))
check(raises(lambda: tr.save_course(company_id, CF("SAFE", "تکراری", D(1))), "تکراری"), "course codes are unique")
tr.set_required_positions(company_id, safe, [p_op])
tr.set_required_positions(company_id, first, [p_op, p_cl])
tr.set_required_positions(company_id, height, [p_op])
tr.set_required_positions(company_id, fire, [p_cl])
check(sorted(next(c for c in tr.list_courses(company_id) if c.course_id == first).position_ids) == sorted([p_op, p_cl]),
      "required positions per course")

SF = tr.SessionFields
past = today - datetime.timedelta(days=40)
s1 = tr.save_session(company_id, SF(safe, past, past + datetime.timedelta(days=1), "مهندس احمدی", "سالن", 2, D(10_000_000)))
tr.enroll(company_id, s1, [e1, e2])
check(raises(lambda: tr.enroll(company_id, s1, [e3]), "ظرفیت"), "capacity is enforced")
en = {r.employee_id: r.enrollment_id for r in tr.list_enrollments(company_id, s1)}
check(raises(lambda: tr.complete_session(company_id, s1), "هنوز ثبت نشده"), "results first")
tr.record_result(company_id, en[e1], "PASSED", D(85), "C-1")
tr.record_result(company_id, en[e2], "FAILED", D(40))
tr.complete_session(company_id, s1)
r1 = next(r for r in tr.list_enrollments(company_id, s1) if r.employee_id == e1)
check(r1.completed_on == past + datetime.timedelta(days=1) and r1.expires_on == tr._add_months(past + datetime.timedelta(days=1), 12)
      and r1.certificate_no == "C-1", "the certificate date and expiry come from the session end and course validity")
check(raises(lambda: tr.cancel_session(company_id, s1), "برنامه‌ریزی‌شده"), "a held session cannot be cancelled")

future = today + datetime.timedelta(days=10)
s2 = tr.save_session(company_id, SF(safe, future, future))
tr.enroll(company_id, s2, [e2])
check(raises(lambda: tr.record_result(company_id, tr.list_enrollments(company_id, s2)[0].enrollment_id, "PASSED"), "شروع نشده"),
      "no result before the session starts")
s3 = tr.save_session(company_id, SF(first, past, past))
tr.enroll(company_id, s3, [e1, e3])
for r in tr.list_enrollments(company_id, s3):
    tr.record_result(company_id, r.enrollment_id, "PASSED")
tr.complete_session(company_id, s3)
h_end = today - datetime.timedelta(days=45)
s4 = tr.save_session(company_id, SF(height, h_end, h_end))
tr.enroll(company_id, s4, [e1])
tr.record_result(company_id, tr.list_enrollments(company_id, s4)[0].enrollment_id, "PASSED")
f_end = today - datetime.timedelta(days=10)
s5 = tr.save_session(company_id, SF(fire, f_end, f_end))
tr.enroll(company_id, s5, [e3])
tr.record_result(company_id, tr.list_enrollments(company_id, s5)[0].enrollment_id, "PASSED")

courses, rows = tr.matrix(company_id)
m = {r.employee_id: {c: cell.status_code for c, cell in r.cells.items()} for r in rows}
check(m[e1] == {safe: "VALID", first: "VALID", height: "EXPIRED"}, f"e1 matrix ({m[e1]})")
check(m[e2] == {safe: "PLANNED", first: "MISSING", height: "MISSING"}, f"e2 matrix ({m[e2]})")
check(m[e3] == {first: "VALID", fire: "EXPIRING"}, f"e3 matrix ({m[e3]})")
check(tr.gaps(company_id) == {"VALID": 3, "EXPIRING": 1, "EXPIRED": 1, "PLANNED": 1, "MISSING": 2}, f"gap counts ({tr.gaps(company_id)})")
tasks = [t for t in operational_tasks.list_operational_tasks(company_id, uid) if t.kind == "HR_TRAINING_GAPS"]
check(len(tasks) == 1 and "1 منقضی" in tasks[0].title, f"the training officer's inbox ({tasks[0].title if tasks else ''})")
tr.cancel_session(company_id, s2)
check({c: cell.status_code for c, cell in next(r for r in tr.matrix(company_id)[1] if r.employee_id == e2).cells.items()}[safe] == "MISSING",
      "a cancelled session no longer plans the training")
hours = {code: (h, cost) for code, _n, h, cost in tr.hours_report(company_id, today - datetime.timedelta(days=365), today)}
check(hours == {"E1": (D(12), D(5_000_000)), "E2": (D(8), D(5_000_000)), "E3": (D(4), D(0))}, f"hours and cost share ({hours})")

# فرم
from PySide6.QtWidgets import QApplication, QPushButton
qapp = QApplication.instance() or QApplication([])
from PySide6.QtCore import Qt
from peecha.ui.screens.hr_training import HrTrainingScreen

screen = HrTrainingScreen()
screen.refresh()
check(screen.course_table.rowCount() == 4 and screen.session_table.rowCount() == 5, "courses and sessions listed")
check(screen.matrix_table.columnCount() == 8 and screen.matrix_table.rowCount() == 3 and "منقضی: ۱" in screen.gap_label.text(),
      f"the training matrix ({screen.gap_label.text()})")
screen.co_code.setText("ISO")
screen.co_title.setText("آشنایی با ایزو")
screen.co_hours.setValue(2)
for i in range(screen.position_list.count()):
    if screen.position_list.item(i).data(Qt.UserRole) == p_cl:
        screen.position_list.item(i).setCheckState(Qt.Checked)
iso = screen.save_course()
check(iso is not None and next(c for c in tr.list_courses(company_id) if c.course_id == iso).position_ids == [p_cl],
      f"a course with its required position from the form ({screen.status_label.text()})")
screen.se_course.setCurrentIndex(screen.se_course.findData(iso))
screen.se_from.setDate(today)
screen.se_to.setDate(today)
check(screen.save_session() and screen.enroll_required() and screen.enroll_table.rowCount() == 1,
      f"a session and enrolling everyone who needs it ({screen.status_label.text()})")
screen.enroll_table.selectAll()
check(screen.record_result() and screen.complete_session() and screen.enrollments[0].status_code == "PASSED", "result and completion from the form")
check(all(len(b.text()) <= 2 for b in screen.findChildren(QPushButton) if b.text()), "icon buttons only")

finish()
