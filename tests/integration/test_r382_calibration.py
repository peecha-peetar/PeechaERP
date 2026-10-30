"""R382: کالیبراسیون: ثبت ابزار و اعتبارسنجی، وضعیت سررسید (در موعد، نزدیک، گذشته)، کارتابل مدیر و مسئول ابزار، نتیجهٔ قبول
(سررسید بعدی از تاریخ کالیبراسیون)، نتیجهٔ مردود (خارج از خدمت، سررسید ثابت، عدم‌انطباق با علت اندازه‌گیری و تاریخ آخرین
قبول)، بازگشت به خدمت فقط با قبول بعدی، تاریخ آینده یا عقب‌تر، بازنشسته؛ و فرم."""
import datetime, os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r382"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prd_fixture import *  # noqa: F401,F403

from peecha import numerals
from peecha.services import operational_tasks, users as users_service
from peecha.services.maintenance import calibration as cal
from peecha.services.qms import ncr as ncr_service

tech = users_service.create_user("tech1", "تکنسین", "secret123", None, lang_id, False, [company_id], company_id).user_id
other = users_service.create_user("other1", "کاربر دیگر", "secret123", None, lang_id, False, [company_id], company_id).user_id
day = datetime.timedelta(days=1)
I = cal.InstrumentInput

check(raises(lambda: cal.save_instrument(company_id, uid, I(" ", "کولیس", 180, today)), "الزامی"), "code and name are required")
check(raises(lambda: cal.save_instrument(company_id, uid, I("C1", "کولیس", 0, today)), "دوره"), "the interval must be positive")
check(raises(lambda: cal.save_instrument(company_id, uid, I("C1", "کولیس", 180, today, asset_id=999999)), "تجهیز"), "a linked asset must exist")
i1 = cal.save_instrument(company_id, uid, I("c1", "کولیس دیجیتال", 180, today + 30 * day, measure_range="0-150 mm", tolerance="±0.02 mm"))
i2 = cal.save_instrument(company_id, uid, I("M1", "میکرومتر", 365, today + 5 * day, responsible_user_id=tech, serial_no="SN-77"))
i3 = cal.save_instrument(company_id, uid, I("G1", "گیج فشار", 90, today - 3 * day, method_code="INTERNAL"))
check(raises(lambda: cal.save_instrument(company_id, uid, I("C1", "تکراری", 30, today)), "تکراری"), "codes are unique (case-insensitive)")
states = {r.code: r.state for r in cal.list_instruments(company_id)}
check(states == {"C1": "OK", "M1": "DUE", "G1": "OVERDUE"}, f"due states with warning days ({states})")
check(cal.due_counts(company_id) == {"OVERDUE": 1, "DUE": 1, "OUT_OF_SERVICE": 0}, "due counts")


def task(user):
    return next((t for t in operational_tasks.list_operational_tasks(company_id, user) if t.kind == "MNT_CALIBRATION"), None)


t_admin, t_tech = task(uid), task(tech)
check(t_admin is not None and "۱" in numerals.to_persian_digits(t_admin.title) and "گذشته از سررسید" in t_admin.title,
      f"the maintenance manager sees all due instruments ({t_admin and t_admin.title})")
check(t_tech is not None and "نزدیک سررسید" in t_tech.title and "گذشته" not in t_tech.title and task(other) is None,
      "the responsible user sees only their own instrument; others see nothing")

# قبول
check(raises(lambda: cal.record_calibration(company_id, uid, i3, today + day, "PASS"), "آینده"), "no future dates")
cal.record_calibration(company_id, uid, i3, today - day, "PASS", performed_by="آزمایشگاه مرجع", certificate_no="CAL-1", cost_amount=D(2_500_000))
g1 = cal.get_instrument(company_id, i3)
check(g1.next_due_date == today - day + 90 * day and g1.last_calibrated_on == today - day and g1.state == "OK",
      "a pass sets the next due date from the calibration date")
check(raises(lambda: cal.record_calibration(company_id, uid, i3, today - 2 * day, "PASS"), "پیش از آخرین"), "no older date than the last one")

# مردود
check(raises(lambda: cal.record_calibration(company_id, uid, i3, today, "FAIL"), "خطای یافت‌شده"), "a fail needs the found error")
before_due = cal.get_instrument(company_id, i3).next_due_date
rec = cal.record_calibration(company_id, uid, i3, today, "FAIL", as_found="+0.3 bar در ۱۰ bar", certificate_no="CAL-2")
g1 = cal.get_instrument(company_id, i3)
r_fail = cal.list_records(company_id, i3)[0]
check(g1.status_code == "OUT_OF_SERVICE" and g1.next_due_date == before_due and g1.state == "OUT_OF_SERVICE"
      and not cal.is_usable(company_id, i3), "a fail takes the instrument out of service without moving the due date")
ncr = ncr_service.get_ncr(company_id, r_fail.ncr_id).ncr
check(r_fail.record_id == rec and r_fail.ncr_no is not None and "G1" in ncr.title and ncr.cause_code == "MEASUREMENT"
      and numerals.format_jalali_date(today - day) in (ncr.description or ""),
      "a quality nonconformance is opened with the last pass date to check earlier measurements")
check(raises(lambda: cal.set_status(company_id, uid, i3, "ACTIVE"), "قبول دوباره"), "a failed instrument returns only with a new pass")
cal.record_calibration(company_id, uid, i3, today, "ADJUSTED", as_found="+0.3 bar", as_left="+0.01 bar")
g1 = cal.get_instrument(company_id, i3)
check(g1.status_code == "ACTIVE" and g1.next_due_date == today + 90 * day and cal.is_usable(company_id, i3),
      "adjusted and passed: back in service")
cal.record_calibration(company_id, uid, i2, today, "FAIL", as_found="-0.01 mm", open_ncr=False)
check(cal.list_records(company_id, i2)[0].ncr_id is None, "the nonconformance is optional")

# وضعیت دستی
check(raises(lambda: cal.set_status(company_id, uid, i1, "OUT_OF_SERVICE"), "دلیل"), "taking out of service needs a reason")
cal.set_status(company_id, uid, i1, "OUT_OF_SERVICE", "افتاده و ضربه خورده")
cal.set_status(company_id, uid, i1, "ACTIVE")
cal.set_status(company_id, uid, i1, "RETIRED", "از رده خارج")
check(raises(lambda: cal.record_calibration(company_id, uid, i1, today, "PASS"), "بازنشسته"), "a retired instrument is not calibrated")
check(sorted(r.code for r in cal.list_instruments(company_id)) == ["G1", "M1"],
      "retired instruments are hidden by default")
check(len(cal.list_instruments(company_id, include_retired=True)) == 3, "and shown on request")

# فرم
from PySide6.QtWidgets import QApplication, QPushButton
qapp = QApplication.instance() or QApplication([])
from peecha.ui.screens.mnt_calibration import CalibrationScreen

screen = CalibrationScreen()
screen.refresh()
check(screen.table.rowCount() == 2, "the list")
screen.code_field.setText("T1")
screen.name_field.setText("ترازوی دقیق")
screen.interval_field.setValue(30)
screen.due_field.setDate(today + 10 * day)
check(screen.save_instrument() and screen._instrument_id is not None, "a new instrument from the form")
screen.result_combo.setCurrentIndex(screen.result_combo.findData("PASS"))
screen.certificate_field.setText("W-9")
screen.cost_field.setText("۱٬۲۰۰٬۰۰۰")
check(screen.record() and screen.records_table.rowCount() == 1, "a result from the form")
check(cal.get_instrument(company_id, screen._instrument_id).next_due_date == today + 30 * day and not screen.due_field.isEnabled(),
      "the due date is computed after the first result")
screen.ask_reason = lambda: "تعمیر"
check(screen.change_status("OUT_OF_SERVICE") and cal.get_instrument(company_id, screen._instrument_id).status_code == "OUT_OF_SERVICE",
      "out of service from the form")
check(all(len(b.text()) <= 2 for b in screen.findChildren(QPushButton) if b.text()), "icon buttons only")

finish()
