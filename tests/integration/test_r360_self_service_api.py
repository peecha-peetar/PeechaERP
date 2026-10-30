"""R360: سلف‌سرویس موبایل کارمند: فقط پروندهٔ خود کاربر؛ فیش‌های قطعی‌شده (نه پیش‌نویس، نه فیش دیگران) با ردیف‌ها؛
درخواست مرخصی با کلید تکرارنشدن و خطای همپوشانی، لغو فقط درخواست خود؛ و حضور و تأخیر روزهای اخیر با خلاصه."""
import datetime, os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r360"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prd_fixture import *  # noqa: F401,F403

from peecha.db.models.payroll import Payslip
from peecha.services import hr, hr_attendance, hr_leave, hr_shifts, payroll, payroll_engine, payroll_payslip, users as users_service

T = datetime.time
lang_id = company.default_language_id
staff_user = users_service.create_user("staff", "کارمند", "secret123", None, lang_id, False, [company_id], company_id).user_id
other_user = users_service.create_user("other", "همکار", "secret123", None, lang_id, False, [company_id], company_id).user_id
stranger = users_service.create_user("stranger", "بی‌پرونده", "secret123", None, lang_id, False, [company_id], company_id).user_id
org = hr.create_org_unit(company_id, "ADM", "اداری", None, None)
pos = hr.create_position(company_id, "CLK", "کارمند", org, None, 5)
start = today - datetime.timedelta(days=400)
me = hr.create_employee(company_id, "E1", "علی", "رضایی", "0012345678", start, org, pos, D(100_000_000), None)
colleague = hr.create_employee(company_id, "E2", "مریم", "احمدی", "0087654321", start, org, pos, D(80_000_000), None)
hr.set_employee_user(company_id, me, staff_user)
hr.set_employee_user(company_id, colleague, other_user)

# فیش: دورهٔ اول قطعی، دورهٔ دوم پیش‌نویس
g6 = A("6", "هزینه‌های عمومی", "DEBIT", "EXPENSE", "TEMPORARY", False)
k61 = A("61", "هزینهٔ کارکنان", "DEBIT", "EXPENSE", "TEMPORARY", False, g6.account_id)
salary_exp = A("611", "حقوق و دستمزد", "DEBIT", "EXPENSE", "TEMPORARY", True, k61.account_id)
k22 = A("22", "سایر پرداختنی‌ها", "CREDIT", "LIABILITY", "PERMANENT", False, g4.account_id)
salary_pay = A("221", "حقوق پرداختنی", "CREDIT", "LIABILITY", "PERMANENT", True, k22.account_id)
payroll.save_company_settings(company_id, 30, "DAILY", "NONE", 25, None, salary_payable_gl_account_id=salary_pay.account_id)
payroll.create_pay_item(company_id, "BASE", "حقوق پایه", "EARNING", "BASE_SALARY_FROM_CONTRACT", "EARNING_PHASE",
                        is_prorated=False, is_taxable=False, is_insurable=False, gl_account_id=salary_exp.account_id)
insurance_exp = A("612", "بیمهٔ سهم کارفرما", "DEBIT", "EXPENSE", "TEMPORARY", True, k61.account_id)
payroll.create_insurance_config(company_id, start, None, D("0.07"), D("0.20"), D("0.03"), None, None,
                                employer_expense_gl_account_id=insurance_exp.account_id)
payroll.set_tax_brackets(company_id, start, [(D(0), None, D(0))])
p1 = payroll.create_period(company_id, 1405, 1, datetime.date(2026, 3, 21), datetime.date(2026, 4, 20))
p2 = payroll.create_period(company_id, 1405, 2, datetime.date(2026, 4, 21), datetime.date(2026, 5, 21))
for period, final in ((p1, True), (p2, False)):
    run = payroll_engine.create_run(period)
    result = payroll_engine.run_payroll(run)
    check(result.employees_calculated == 2 and not result.errors, f"payroll period {period} is calculated ({result.errors})")
    if final:
        payroll_engine.approve_run(run)
        payroll_payslip.finalize_payslips_for_run(run)
with new_session() as s:
    mine = {p.status: p.payslip_id for p in s.scalars(select(Payslip).where(Payslip.employee_id == me))}
    theirs = s.scalar(select(Payslip.payslip_id).where(Payslip.employee_id == colleague, Payslip.status == "FINALIZED"))

from fastapi.testclient import TestClient
from peecha_api.main import app
client = TestClient(app)


def h(login):
    return {"Authorization": "Bearer " + client.post("/auth/login", json={"username": login, "password": "secret123"}).json()["access_token"]}


me_h, other_h, stranger_h = h("staff"), h("other"), h("stranger")
r = client.get("/self/profile", headers=me_h)
check(r.status_code == 200 and r.json()["name"] == "علی رضایی" and "ANNUAL" in r.json()["leave_types"], "profile of the linked employee")
check(client.get("/self/profile", headers=stranger_h).status_code == 404, "a user without a personnel file gets a clear 404")

slips = client.get("/self/payslips", headers=me_h).json()
check([s["payslip_id"] for s in slips] == [mine["FINALIZED"]] and slips[0]["jalali_month"] == 1,
      f"only the finalized payslip is listed ({slips})")
d = client.get(f"/self/payslips/{mine['FINALIZED']}", headers=me_h).json()
check(D(d["net_pay"]) > 0 and any(e["code"] == "BASE" for e in d["earnings"]), "the payslip opens with its lines")
check(client.get(f"/self/payslips/{mine['DRAFT']}", headers=me_h).status_code == 404
      and client.get(f"/self/payslips/{theirs}", headers=me_h).status_code == 404, "draft or a colleague's payslip is hidden")

body = {"leave_type": "ANNUAL", "from_date": str(today + datetime.timedelta(days=10)), "to_date": str(today + datetime.timedelta(days=12)),
        "reason": "سفر"}
first = client.post("/self/leave", headers={**me_h, "Idempotency-Key": "lv-1"}, json=body)
again = client.post("/self/leave", headers={**me_h, "Idempotency-Key": "lv-1"}, json=body)
check(first.status_code == 201 and first.json()["status_code"] == "SUBMITTED" and D(first.json()["days"]) == 3
      and again.json()["leave_request_id"] == first.json()["leave_request_id"]
      and len(hr_leave.list_requests(company_id, employee_id=me)) == 1,
      f"leave is submitted once even if the queue retries ({first.status_code} {first.json()} {again.json()})")
overlap = client.post("/self/leave", headers={**me_h, "Idempotency-Key": "lv-2"}, json=body)
check(overlap.status_code == 400 and "بازه" in overlap.json()["detail"], "an overlapping leave is refused with a message")
lid = first.json()["leave_request_id"]
check(client.post(f"/self/leave/{lid}/cancel", headers=other_h).status_code == 400, "a colleague cannot cancel my leave")
check(client.post(f"/self/leave/{lid}/cancel", headers=me_h).json()["status_code"] == "CANCELLED", "I can cancel my own request")
check([x["status_code"] for x in client.get("/self/leave", headers=me_h).json()] == ["CANCELLED"]
      and client.get("/self/leave", headers=other_h).json() == [], "each user sees only their own requests")

shift = hr_shifts.save_shift(company_id, hr_shifts.ShiftFields("D", "روزکار", T(8), T(16), grace_minutes=5, off_weekdays=()))
hr_shifts.assign_shift(company_id, me, shift, today - datetime.timedelta(days=2))
hr_attendance.create_attendance_record(company_id, me, today - datetime.timedelta(days=2), T(8, 20), T(16), status="APPROVED")
hr_attendance.create_attendance_record(company_id, me, today, T(8), T(15, 30))
att = client.get("/self/attendance?days=7", headers=me_h).json()
check([x["kind"] for x in att["days"]] == ["PRESENT", "ABSENT", "PRESENT"] and att["days"][2]["late_minutes"] == 20
      and att["days"][0]["pending"] and att["days"][0]["early_minutes"] == 30,
      f"recent days, newest first, with lateness ({att['days']})")
check(att["summary"]["absent"] == 1 and att["summary"]["late_minutes"] == 20, "attendance summary")

finish()
