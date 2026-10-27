"""R347: لیست بیمه و لیست مالیات حقوق: مشخصات هویتی بیمه از فرم پرسنل (بدون پاک‌شدن در ویرایش‌های دیگر)، مشخصات
کارگاه، ذخیرهٔ مزد مشمول و کارکرد در فیش، لیست بیمه فقط از فیش قطعی (دستمزد، مزایا، مشمول/غیرمشمول، سهم کارمند،
کارفرما و بیکاری، تاریخ شروع کار، کمبود اطلاعات)، فیش قدیمی بدون مزد مشمول، لیست مالیات (مستمر/غیرمستمر، مشمول،
مالیات)، کد ملی، و خروجی اکسل از فرم اجرای حقوق."""
import datetime, decimal, os, sys, tempfile
os.environ["PEECHA_DB_NAME"] = "peecha_test_r347"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prd_fixture import *  # noqa: F401,F403

from peecha import numerals
from peecha.db.models.hr import Employee
from peecha.db.models.payroll import Payslip
from peecha.services import hr, hr_attendance, payroll, payroll_engine, payroll_payslip, payroll_statutory as statutory

Q = decimal.Decimal("0.01")


def money(value):
    return decimal.Decimal(value).quantize(Q)


def national_id(prefix):
    total = sum(int(d) * (10 - i) for i, d in enumerate(prefix))
    r = total % 11
    return prefix + str(r if r < 2 else 11 - r)


nid1, nid2 = national_id("001234567"), national_id("008765432")
check(statutory.valid_national_id(nid1) and statutory.valid_national_id(numerals.to_persian_digits(nid2))
      and not statutory.valid_national_id("1111111111") and not statutory.valid_national_id(nid1[:9] + str((int(nid1[9]) + 1) % 10)),
      "the national-ID check digit is validated")

start = datetime.date(2026, 1, 1)
p1_from, p1_to = datetime.date(2026, 3, 21), datetime.date(2026, 4, 20)
org = hr.create_org_unit(company_id, "ADM", "اداری", None, None)
pos = hr.create_position(company_id, "CLK", "کارمند اداری", org, None, 5)
male = next(v.lookup_value_id for v in hr.list_lookup_values(company_id, "GENDER") if v.code == "MALE")

# فرم پرسنل: مشخصات بیمه‌ای با رقم فارسی
d1 = hr.create_personnel_detail_account(
    company_id, "E1", "علی رضایی", org_unit_id=org, position_id=pos, employment_type_lookup_id=None,
    base_salary=D(100_000_000), national_id=nid1, hire_date=start, social_security_no="۱۲۳۴۵۶۷۸",
    date_of_birth=datetime.date(1990, 5, 1), gender_lookup_id=male, father_name="حسن", id_card_no="۴۵۶",
    id_issue_place="تهران", nationality_code="IR", insurance_job_code="۲۴۱۱")
d2 = hr.create_personnel_detail_account(
    company_id, "E2", "مریم احمدی", org_unit_id=org, position_id=pos, employment_type_lookup_id=None,
    base_salary=D(60_000_000), national_id=nid2, hire_date=p1_from)
e1 = hr.get_employee_by_personnel_detail_account_id(d1)
e2 = hr.get_employee_by_personnel_detail_account_id(d2)
check(e1.social_security_no == "12345678" and e1.id_card_no == "456" and e1.insurance_job_code == "2411"
      and e1.father_name == "حسن" and e1.gender_lookup_id == male and e1.date_of_birth == datetime.date(1990, 5, 1),
      "the personnel form stores the insurance identity fields (digits normalised)")
row = next(r for r in hr.list_personnel_detail_accounts(company_id) if r["detail_account_id"] == d1)
check(row["father_name"] == "حسن" and row["social_security_no"] == "12345678" and row["nationality_code"] == "IR",
      "the personnel list returns them for the form")
hr.update_personnel_detail_account(d1, company_id, "E1", "علی رضایی", True, org_unit_id=org, position_id=pos,
                                   employment_type_lookup_id=None, base_salary=D(100_000_000), national_id=nid1,
                                   hire_date=start)
check(hr.get_employee(e1.employee_id).father_name == "حسن" and hr.get_employee(e1.employee_id).social_security_no == "12345678",
      "an update without these fields keeps them")
hr.update_personnel_detail_account(d1, company_id, "E1", "علی رضایی", True, org_unit_id=org, position_id=pos,
                                   employment_type_lookup_id=None, base_salary=D(100_000_000), national_id=nid1,
                                   hire_date=start, id_issue_place="شیراز", father_name="حسن")
check(hr.get_employee(e1.employee_id).id_issue_place == "شیراز", "an update with them changes them")

# مشخصات کارگاه
check(raises(lambda: payroll.save_workshop_info(company_id, "12AB", "", "", "", ""), "رقم"), "the workshop code must be digits")
payroll.save_workshop_info(company_id, "۱۲۳۴۵۶۷۸۹۰", " کارگاه مرکزی ", "شرکت تولیدی", "تهران، خیابان آزادی", "")
settings = payroll.get_company_settings(company_id)
check(settings.sso_workshop_code == "1234567890" and settings.sso_workshop_name == "کارگاه مرکزی" and settings.sso_contract_row is None,
      "workshop details are saved")

# حقوق: پایه + مسکن (مشمول بیمه) + بن (غیرمشمول بیمه، غیرمستمر)
payroll.save_company_settings(company_id, 30, "DAILY", "NONE", 25, None)
check(payroll.get_company_settings(company_id).sso_workshop_code == "1234567890", "saving general settings keeps the workshop code")
payroll.create_pay_item(company_id, "BASE", "حقوق پایه", "EARNING", "BASE_SALARY_FROM_CONTRACT", "EARNING_PHASE",
                        is_prorated=True, is_taxable=True, is_insurable=True)
payroll.create_pay_item(company_id, "HOUSING", "حق مسکن", "BENEFIT", "FIXED", "EARNING_PHASE", fixed_amount=D(9_000_000),
                        is_prorated=True, is_taxable=True, is_insurable=True, is_continuous_benefit=True)
payroll.create_pay_item(company_id, "BON", "بن", "BENEFIT", "FIXED", "EARNING_PHASE", fixed_amount=D(2_000_000),
                        is_taxable=True)
payroll.create_insurance_config(company_id, start, None, D("0.07"), D("0.20"), D("0.03"), None, None)
payroll.set_tax_brackets(company_id, start, [(D(0), D(50_000_000), D(0)), (D(50_000_000), None, D("0.10"))])
period1 = payroll.create_period(company_id, 1405, 1, p1_from, p1_to)
for day in range(15):
    hr_attendance.create_attendance_record(company_id, e2.employee_id, p1_from + datetime.timedelta(days=day),
                                           worked_hours=D(8), status="APPROVED")
run1 = payroll_engine.create_run(period1)
result = payroll_engine.run_payroll(run1)
check(result.employees_calculated == 2 and not result.errors, f"both employees are calculated ({result.errors})")
with new_session() as s:
    slips = {p.employee_id: p for p in s.scalars(select(Payslip).where(Payslip.run_id == run1))}
check(money(slips[e1.employee_id].insurable_wage) == money(109_000_000) and slips[e1.employee_id].worked_days == 30
      and money(slips[e2.employee_id].insurable_wage) == money(34_500_000) and slips[e2.employee_id].worked_days == 15,
      "the payslip stores the insurable wage and worked days")

draft = statutory.insurance_list(company_id, period1)
check(not draft.rows and any("قطعی" in p for p in draft.problems), "draft payslips are not listed")
payroll_engine.approve_run(run1)
payroll_payslip.finalize_payslips_for_run(run1)

data = statutory.insurance_list(company_id, period1)
r1, r2 = data.rows
check(data.workshop_code == "1234567890" and (data.jalali_year, data.jalali_month) == (1405, 1) and len(data.rows) == 2,
      "the list has the workshop header and both employees")
check(r1.insurance_no == "12345678" and r1.national_id == nid1 and r1.father_name == "حسن" and r1.gender == "مرد"
      and r1.nationality == "ایرانی" and r1.job_code == "2411" and r1.job_title == "کارمند اداری" and r1.start_date is None,
      "identity columns come from the personnel form")
check(r1.days == 30 and money(r1.monthly_wage) == money(100_000_000) and money(r1.benefits) == money(9_000_000)
      and money(r1.insurable_wage) == money(109_000_000) and money(r1.total_pay) == money(111_000_000),
      f"wage, insurable benefits and total pay incl. non-insurable ({r1.monthly_wage}, {r1.benefits}, {r1.total_pay})")
check(money(r1.employee_share) == money(7_630_000) and money(r1.employer_share) == money(21_800_000)
      and money(r1.unemployment_share) == money(3_270_000), "employee 7%, employer 20% and unemployment 3%")
check(r2.days == 15 and money(r2.daily_wage) == money(2_000_000) and money(r2.monthly_wage) == money(30_000_000)
      and money(r2.benefits) == money(4_500_000) and r2.start_date == p1_from,
      "a mid-month hire shows the start date and 15 days of daily wage")
check(not any("کارگاه" in p for p in data.problems) and any("E2" in p and "نام پدر" in p for p in data.problems)
      and not any("E1" in p for p in data.problems), f"missing identity data is reported per employee ({data.problems})")
headers, rows, footer = statutory.insurance_table(data)
check(len(headers) == len(rows[0]) == len(footer) and footer[15] == 45 and money(footer[19]) == money(143_500_000)
      and money(footer[23]) == money(D(143_500_000) * D("0.03")), "the table totals days, insurable wage and shares")

# فیش پیش از R347 (بدون مزد مشمول و کارکرد ذخیره‌شده)
with new_session() as s:
    old = s.get(Payslip, slips[e1.employee_id].payslip_id)
    old.insurable_wage, old.worked_days = None, None
    s.commit()
legacy = statutory.insurance_list(company_id, period1).rows[0]
check(money(legacy.insurable_wage) == money(109_000_000) and legacy.days == 30,
      "older payslips derive the insurable wage from the employee share and use standard month days")

taxes = statutory.tax_list(company_id, period1)
t1, t2 = taxes.rows
check(money(t1.continuous) == money(109_000_000) and money(t1.non_continuous) == money(2_000_000)
      and money(t1.gross) == money(111_000_000) and money(t1.employee_insurance) == money(7_630_000),
      "the tax list splits continuous and non-continuous pay")
check(money(t1.taxable_income) == money(103_370_000) and money(t1.tax) == money(5_337_000) and money(t2.tax) == 0,
      f"taxable income and withheld tax ({t1.taxable_income}, {t1.tax})")
check(not taxes.problems, f"valid national IDs raise no problem ({taxes.problems})")
with new_session() as s:
    s.get(Employee, e2.employee_id).national_id = "1234"
    s.commit()
check(any("E2" in p for p in statutory.tax_list(company_id, period1).problems), "an invalid national ID is reported")
headers, rows, footer = statutory.tax_table(taxes)
check(len(headers) == len(rows[0]) == len(footer) and money(footer[-1]) == money(5_337_000), "tax table totals")

# فرم اجرای حقوق: خروجی اکسل
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox, QPushButton
qapp = QApplication.instance() or QApplication([])
from peecha.ui.screens.payroll_run import PayrollRunScreen
from peecha.ui.screens.payroll_settings import _GeneralSettingsTab
import openpyxl

out = os.path.join(tempfile.mkdtemp(), "insurance.xlsx")
asked = []
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (out, ""))
QMessageBox.question = staticmethod(lambda *a, **k: asked.append(a[2]) or QMessageBox.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
screen = PayrollRunScreen()
screen.refresh()
names = {b.accessibleName() for b in screen.findChildren(QPushButton)}
check({"لیست بیمه", "لیست مالیات حقوق"} <= names, "the payroll run screen has both list buttons")
screen._selected_period_id = period1
screen._export_insurance_list()
sheet = openpyxl.load_workbook(out).active
values = [[c for c in r] for r in sheet.iter_rows(values_only=True)]
header_row = next(i for i, r in enumerate(values) if r and r[0] == "ردیف")
check(asked and "E2" in asked[0] and "شمارهٔ بیمه" in values[header_row] and values[header_row + 1][1] == "12345678"
      and any("1234567890" in str(c) for r in values[:header_row] for c in r if c),
      "the Excel file has the workshop header, the warning was shown and the rows follow")
tab = _GeneralSettingsTab()
tab.refresh()
check(tab.workshop_code_field.text() == "1234567890" and tab.workshop_name_field.text() == "کارگاه مرکزی",
      "the payroll settings form shows the workshop details")

finish()
