"""R359: شیفت و تأخیر: تعریف شیفت (اعتبارسنجی، روزهای استراحت)، واگذاری با تاریخ شروع و تغییر شیفت، و گزارش روزانه و
خلاصه: ارفاق تأخیر، تعجیل، اضافه‌ماندن، تعطیل تقویم، استراحت هفتگی، مرخصی تاییدشده، رکورد فقط‌ساعت، رکورد ردشده و
منتظر تایید، غیبت؛ و فرم."""
import datetime, os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r359"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prd_fixture import *  # noqa: F401,F403

from peecha.services import hr, hr_attendance, hr_leave, hr_shifts as sh
from peecha.services.workflow import calendar

T = datetime.time
org = hr.create_org_unit(company_id, "ADM", "اداری", None, None)
pos = hr.create_position(company_id, "CLK", "کارمند", org, None, 5)
emp = hr.create_employee(company_id, "E1", "علی", "رضایی", None, today - datetime.timedelta(days=400), org, pos, D(100_000_000), None)
other = hr.create_employee(company_id, "E2", "مریم", "احمدی", None, today - datetime.timedelta(days=400), org, pos, D(80_000_000), None)

check(raises(lambda: sh.save_shift(company_id, sh.ShiftFields("N", "شب", T(22), T(6))), "بعد از شروع"), "night shifts are refused")
day_shift = sh.save_shift(company_id, sh.ShiftFields("D", "روزکار", T(8), T(16), break_minutes=30, grace_minutes=10, off_weekdays=(3, 4)))
late_shift = sh.save_shift(company_id, sh.ShiftFields("L", "عصرکار", T(9), T(17), off_weekdays=(4,)))
check(raises(lambda: sh.save_shift(company_id, sh.ShiftFields("d", "تکراری", T(8), T(12))), "قبلاً"), "shift codes are unique")
check(raises(lambda: sh.save_shift(company_id, sh.ShiftFields("X", "بی‌روز", T(8), T(12), off_weekdays=tuple(range(7)))), "روز کاری"),
      "a shift needs a working day")
rows = {s.code: s for s in sh.list_shifts(company_id)}
check(rows["D"].work_minutes == 450 and rows["D"].off_label == "پنجشنبه، جمعه", "work minutes and rest days")

sat1 = today - datetime.timedelta(days=14)
sat1 -= datetime.timedelta(days=(sat1.weekday() - 5) % 7)
d = {name: sat1 + datetime.timedelta(days=i) for i, name in enumerate(
    ["sat1", "sun1", "mon1", "tue1", "wed1", "thu1", "fri1", "sat2", "sun2", "mon2", "tue2"])}
sh.assign_shift(company_id, emp, day_shift, d["sat1"])
sh.assign_shift(company_id, emp, late_shift, d["sat2"])
check(raises(lambda: sh.delete_shift(company_id, day_shift), "واگذار"), "an assigned shift cannot be deleted")

A_ = hr_attendance.create_attendance_record
A_(company_id, emp, d["sat1"], T(8, 5), T(16), status="APPROVED")
A_(company_id, emp, d["sun1"], T(8, 25), T(15, 30), status="APPROVED")
A_(company_id, emp, d["mon1"], T(7, 55), T(17, 10), status="APPROVED")
calendar.add_holiday(company_id, uid, d["tue1"], "تعطیل رسمی")
leave = hr_leave.create_request(company_id, uid, emp, "ANNUAL", d["wed1"], d["wed1"], submit=True)
hr_leave.approve(company_id, leave, uid)
A_(company_id, emp, d["sun2"], worked_hours=D(8), status="APPROVED")
A_(company_id, emp, d["mon2"], T(9), T(17), status="REJECTED")
A_(company_id, emp, d["tue2"], T(9), T(16))  # منتظر تایید

days = {r.work_date: r for r in sh.daily_report(company_id, d["sat1"], d["tue2"])}
check(len(days) == 11 and all(r.employee_id == emp for r in days.values()), "only employees with a shift are reported")
check(days[d["sat1"]].kind == "PRESENT" and days[d["sat1"]].late_minutes == 0, "five minutes late is within the grace")
check(days[d["sun1"]].late_minutes == 25 and days[d["sun1"]].early_minutes == 30, "late 25 (all minutes past the grace) and left 30 early")
check(days[d["mon1"]].late_minutes == 0 and days[d["mon1"]].extra_minutes == 70, "stayed 70 minutes after the shift")
check([days[d[k]].kind for k in ("tue1", "wed1", "thu1", "fri1")] == ["HOLIDAY", "LEAVE", "OFF", "OFF"],
      "holiday, approved leave and the shift's rest days")
check(days[d["sat2"]].kind == "ABSENT" and days[d["mon2"]].kind == "ABSENT", "no record or a rejected record is an absence")
check(days[d["sun2"]].kind == "PRESENT" and days[d["sun2"]].late_minutes == 0, "an hours-only record counts as present")
check(days[d["tue2"]].pending and days[d["tue2"]].late_minutes == 0 and days[d["tue2"]].early_minutes == 60
      and days[d["tue2"]].shift_label.startswith("L"), "the new shift applies from its start date; pending records are flagged")
s = sh.summary(company_id, d["sat1"], d["tue2"])[0]
check((s.workdays, s.present, s.absent, s.leave, s.late_days, s.late_minutes, s.early_minutes, s.extra_minutes)
      == (8, 5, 2, 1, 1, 25, 90, 70) and s.absent_dates == [d["sat2"], d["mon2"]], f"summary ({s})")
check(sh.daily_report(company_id, today + datetime.timedelta(days=1), today + datetime.timedelta(days=5)) == [],
      "future days are not counted as absences")

# فرم
from PySide6.QtWidgets import QApplication, QPushButton
qapp = QApplication.instance() or QApplication([])
from peecha.ui.screens.hr_shifts import HrShiftsScreen

screen = HrShiftsScreen()
screen.refresh()
check(screen.shift_table.rowCount() == 2 and screen.assign_table.rowCount() == 2
      and all(len(b.text()) <= 2 for b in screen.findChildren(QPushButton) if b.text()), "the form lists shifts and assignments with icon buttons")
screen.employee_combo.setCurrentIndex(screen.employee_combo.findData(other))
screen.shift_combo.setCurrentIndex(screen.shift_combo.findData(day_shift))
screen.valid_from_field.setDate(d["sat1"])
check(screen.assign() is not None and screen.assign_table.rowCount() == 3, "a shift is assigned from the form")
screen.from_field.setDate(d["sat1"])
screen.to_field.setDate(d["tue2"])
screen.load_report()
check(screen.summary_table.rowCount() == 2 and screen.day_table.rowCount() == 22, "the report lists both employees and their days")
screen.code_field.setText("S")
screen.name_field.setText("شیفت کوتاه")
check(screen.save_shift() is not None and screen.shift_table.rowCount() == 3, "a shift is defined from the form")

finish()
