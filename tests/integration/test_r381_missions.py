"""R381: حق مأموریت: فقط برای مأموریت تاییدشده و یک بار، نرخ ثابت یا درصد حقوق پایهٔ روزانه (ثبت‌شده هنگام ساخت)، سقف روزها،
هزینه‌ها با رسید، ویرایش فقط در پیش‌نویس یا ردشده، تایید و رد با مجوز، سند موقت (بدهکار هزینه، بستانکار پرداختنی با تفصیلی
پرسنلی) و صدور دوباره پس از حذف سند، کارتابل و دست‌نخوردن محاسبهٔ حقوق؛ و فرم."""
import datetime, os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r381"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prd_fixture import *  # noqa: F401,F403

from peecha.db.models.accounting import JournalEntryLine
from peecha.db.models.hr import Employee
from peecha.db.models.security import Form
from peecha.services import hr, hr_leave, hr_missions as hm, journal_entries as je, operational_tasks, roles, users as users_service

roles.ensure_catalog()


def user(login, perms=()):
    u = users_service.create_user(login, login, "secret123", None, lang_id, False, [company_id], company_id).user_id
    if perms:
        role = roles.create_role(company_id, login.upper(), None)
        roles.set_user_role(u, role.role_id, company_id, True)
        with new_session() as s:
            for form, action in perms:
                roles.set_role_permission(role.role_id, s.scalar(select(Form.form_id).where(Form.code == form)), action, True)
    return u


approver = user("hm1", [("hr_missions", "APPROVE")])
clerk = user("hm2", [("hr_missions", "EDIT")])

org = hr.create_org_unit(company_id, "ADM", "اداری", None, None)
pos = hr.create_position(company_id, "SAL", "کارشناس فروش", org, None, 5)
hired = today - datetime.timedelta(days=400)
e1 = hr.create_employee(company_id, "E1", "علی", "رضایی", None, hired, org, pos, D(90_000_000), None)
e2 = hr.create_employee(company_id, "E2", "سارا", "احمدی", None, hired, org, pos, D(60_000_000), None)
start = today - datetime.timedelta(days=10)


def mission(emp, days, approve=True, kind="MISSION", offset=0):
    first = start + datetime.timedelta(days=offset)
    lid = hr_leave.create_request(company_id, uid, emp, kind, first, first + datetime.timedelta(days=days - 1), reason="بازدید مشتری",
                                  submit=True)
    if approve:
        hr_leave.approve(company_id, lid, uid)
    return lid


m1, m2 = mission(e1, 3), mission(e2, 2)
pending = mission(e1, 1, approve=False, offset=5)
annual = mission(e2, 1, kind="ANNUAL", offset=5)
check(raises(lambda: hm.create_claim(company_id, uid, pending, "شیراز"), "تاییدشده"), "only approved missions")
check(raises(lambda: hm.create_claim(company_id, uid, annual, "شیراز"), "نامعتبر"), "only missions, not other leave")
check(sorted(m.leave_request_id for m in hm.eligible_missions(company_id)) == sorted([m1, m2]), "approved missions without a claim")

# نرخ
check(raises(lambda: hm.save_settings(company_id, clerk, hm.Settings("FIXED", D(1_500_000))), "مدیر"), "settings need approval rights")
hm.save_settings(company_id, uid, hm.Settings("FIXED", D(1_500_000)))
check(raises(lambda: hm.create_claim(company_id, uid, m1, " "), "مقصد"), "destination is required")
check(raises(lambda: hm.create_claim(company_id, uid, m1, "شیراز", days=D(4)), "روزهای مأموریت"), "days cannot pass the mission dates")
c1 = hm.create_claim(company_id, clerk, m1, "شیراز", "بازدید نمایندگی")
row = hm.get_claim(company_id, c1)
check(row.days == D(3) and row.daily_rate == D(1_500_000) and row.per_diem_amount == D(4_500_000) and row.claim_no == 1,
      f"fixed per diem: 3 days × 1,500,000 ({row.days}, {row.per_diem_amount})")
check(raises(lambda: hm.create_claim(company_id, uid, m1, "شیراز"), "قبلاً"), "one claim per mission")
hm.save_settings(company_id, uid, hm.Settings("PERCENT", D(0), D(50)))
c2 = hm.create_claim(company_id, clerk, m2, "تبریز", days=D("1.5"))
row2 = hm.get_claim(company_id, c2)
check(row2.daily_rate == D(1_000_000) and row2.per_diem_amount == D(1_500_000),
      f"percent of daily base salary: 60,000,000 / 30 × 50% × 1.5 days ({row2.daily_rate}, {row2.per_diem_amount})")
check(hm.get_claim(company_id, c1).daily_rate == D(1_500_000), "an existing claim keeps its rate when settings change")

# هزینه‌ها
check(raises(lambda: hm.add_expense(company_id, clerk, c1, "TRANSPORT", D(0)), "بیشتر از صفر"), "expense amount must be positive")
x1 = hm.add_expense(company_id, clerk, c1, "TRANSPORT", D(3_200_000), "بلیت قطار", "T-55")
hm.add_expense(company_id, clerk, c1, "LODGING", D(5_000_000), "هتل دو شب", "H-12")
x3 = hm.add_expense(company_id, clerk, c1, "MEALS", D(700_000))
hm.delete_expense(company_id, clerk, x3)
row = hm.get_claim(company_id, c1)
check(row.expenses_amount == D(8_200_000) and row.total_amount == D(12_700_000) and len(hm.list_expenses(c1)) == 2,
      f"expenses add up ({row.expenses_amount}, {row.total_amount})")

# گردش
hm.submit(company_id, clerk, c1)
check(raises(lambda: hm.add_expense(company_id, clerk, c1, "OTHER", D(1)), "تغییر نمی‌کند"), "a submitted claim is locked")
check(raises(lambda: hm.approve(company_id, clerk, c1), "مجوز"), "approval needs the approve right")
tasks = {t.kind for t in operational_tasks.list_operational_tasks(company_id, approver)}
check("HR_MISSION_APPROVE" in tasks and "HR_MISSION_APPROVE" not in {t.kind for t in operational_tasks.list_operational_tasks(company_id, clerk)},
      f"the approver's inbox shows the claim ({tasks})")
check(raises(lambda: hm.reject(company_id, approver, c1, " "), "دلیل"), "rejection needs a reason")
hm.reject(company_id, approver, c1, "رسید غذا ناخواناست")
check(hm.get_claim(company_id, c1).status_code == "REJECTED", "rejected")
hm.update_claim(company_id, clerk, c1, "شیراز و مرودشت", "بازدید نمایندگی", D(3))
row = hm.get_claim(company_id, c1)
check(row.destination == "شیراز و مرودشت" and row.daily_rate == D(1_500_000), "a rejected claim can be fixed")
# با نرخ درصدی فعلی: ۹۰٬۰۰۰٬۰۰۰ / ۳۰ × ۵۰٪ = ۱٬۵۰۰٬۰۰۰ (برابر نرخ ثابت قبلی)
hm.submit(company_id, clerk, c1)
hm.approve(company_id, approver, c1, "تایید")
check(hm.get_claim(company_id, c1).status_code == "APPROVED", "approved")
check("HR_MISSION_POST" in {t.kind for t in operational_tasks.list_operational_tasks(company_id, approver)}, "approved claims wait for posting")

# سند
check(raises(lambda: hm.post(company_id, approver, c1), "تنظیمات مأموریت"), "posting needs the accounts")
travel_gl = A("531", "هزینهٔ سفر و مأموریت", "DEBIT", "EXPENSE", "TEMPORARY", True, k6.account_id)
staff_gl = A("212", "پرداختنی به کارکنان", "CREDIT", "LIABILITY", "PERMANENT", True, k7.account_id)
hm.save_settings(company_id, uid, hm.Settings("PERCENT", D(0), D(50), travel_gl.account_id, None, staff_gl.account_id))
check(raises(lambda: hm.post(company_id, approver, c2), "تاییدشده"), "only approved claims are posted")
je_id = hm.post(company_id, approver, c1)
with new_session() as s:
    lines = list(s.scalars(select(JournalEntryLine).where(JournalEntryLine.journal_entry_id == je_id)))
    personnel = s.get(Employee, e1).personnel_detail_account_id
debits = sorted(D(l.debit_amount_base) for l in lines if l.account_id == travel_gl.account_id)
credit = [l for l in lines if l.account_id == staff_gl.account_id]
check(debits == [D(4_500_000), D(8_200_000)] and len(credit) == 1 and D(credit[0].credit_amount_base) == D(12_700_000),
      f"debit per diem and expenses, credit the staff payable ({debits})")
with new_session() as s:
    from peecha.db.models.accounting import JournalEntryLineDetail
    detail_ids = set(s.scalars(select(JournalEntryLineDetail.detail_account_id).where(
        JournalEntryLineDetail.line_id == credit[0].line_id)))
check(personnel in detail_ids, "the payable line carries the employee's personnel detail")
row = hm.get_claim(company_id, c1)
check(row.status_code == "POSTED" and row.journal_entry_id == je_id, "posted")
check(raises(lambda: hm.post(company_id, approver, c1), "تاییدشده"), "no second entry")
je.delete_journal_entry(je_id, company_id, uid)
row = hm.get_claim(company_id, c1)
check(row.status_code == "APPROVED" and row.journal_entry_id is None, "deleting the entry sends the claim back to posting")
je_id2 = hm.post(company_id, approver, c1)
check(je_id2 != je_id and hm.get_claim(company_id, c1).status_code == "POSTED", "posted again")
check(raises(lambda: hm.delete_claim(company_id, uid, c1), "تغییر نمی‌کند"), "a posted claim cannot be deleted")
hm.delete_claim(company_id, clerk, c2)
check([m.leave_request_id for m in hm.eligible_missions(company_id)] == [m2], "deleting a draft frees the mission")

# محاسبهٔ حقوق دست نخورده است
import inspect
from peecha.services import payroll_engine
check("mission" not in inspect.getsource(payroll_engine).lower(), "the payroll engine is untouched")

# فرم
from PySide6.QtWidgets import QApplication, QPushButton
qapp = QApplication.instance() or QApplication([])
from peecha.ui.screens.hr_missions import HrMissionsScreen

screen = HrMissionsScreen()
screen.refresh()
check(screen.claims_table.rowCount() == 1 and screen.mission_combo.count() == 1, "the list and the free mission")
screen.destination_field.setText("تبریز")
check(screen.save_claim() and screen._claim_id is not None, "a claim from the form")
screen.expense_amount_field.setText("۲٬۰۰۰٬۰۰۰")
screen.expense_receipt_field.setText("B-1")
check(screen.add_expense() and screen.expenses_table.rowCount() == 1, "an expense with Persian digits")
check(screen.submit_claim() and hm.get_claim(company_id, screen._claim_id).status_code == "SUBMITTED", "submitted from the form")
screen.ask_reason = lambda: "مبلغ بلیت بیشتر از سقف است"
sess.current_user = type("U", (), {"user_id": approver})()
check(screen.reject_claim() and hm.get_claim(company_id, screen._claim_id).status_code == "REJECTED", "rejected from the form")
screen.show_status("REJECTED")
check(screen.claims_table.rowCount() == 1, "filtered by status (from the inbox)")
check(all(len(b.text()) <= 2 for b in screen.findChildren(QPushButton) if b.text()), "icon buttons only")

finish()
