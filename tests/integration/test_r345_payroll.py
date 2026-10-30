"""R345: محاسبهٔ واقعی حقوق از ابتدا تا سند: حقوق پایه از حکم، مزایای ثابت، کارکرد از حضور و غیاب تاییدشده، اضافه‌کاری،
بیمهٔ سهم کارمند و کارفرما، مالیات تجمعی پلکانی، قسط وام، بازمحاسبهٔ همان اجرا (بدون دوبار حساب‌شدن مالیات در دفتر
سالانه)، تایید، قطعی‌سازی فیش، سند حسابداری متوازن و ماه دوم."""
import datetime, decimal, os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r345_payroll"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prd_fixture import *  # noqa: F401,F403

from peecha.db.models.accounting import JournalEntryLine
from peecha.db.models.payroll import LoanInstallment, PayItemDefinition
from peecha.services import hr, hr_attendance, payroll, payroll_engine, payroll_journal, payroll_loans, payroll_overtime, \
    payroll_payslip

Q = decimal.Decimal("0.01")


def money(value):
    return decimal.Decimal(value).quantize(Q)


g6 = A("6", "هزینه‌های عمومی", "DEBIT", "EXPENSE", "TEMPORARY", False)
k61 = A("61", "هزینهٔ کارکنان", "DEBIT", "EXPENSE", "TEMPORARY", False, g6.account_id)
salary_exp = A("611", "حقوق و دستمزد", "DEBIT", "EXPENSE", "TEMPORARY", True, k61.account_id)
insurance_exp = A("612", "بیمهٔ سهم کارفرما", "DEBIT", "EXPENSE", "TEMPORARY", True, k61.account_id)
k22 = A("22", "سایر پرداختنی‌ها", "CREDIT", "LIABILITY", "PERMANENT", False, g4.account_id)
salary_pay = A("221", "حقوق پرداختنی", "CREDIT", "LIABILITY", "PERMANENT", True, k22.account_id)
insurance_pay = A("222", "بیمهٔ پرداختنی", "CREDIT", "LIABILITY", "PERMANENT", True, k22.account_id)
tax_pay = A("223", "مالیات حقوق پرداختنی", "CREDIT", "LIABILITY", "PERMANENT", True, k22.account_id)
k13 = A("13", "مطالبات کارکنان", "DEBIT", "ASSET", "PERMANENT", False, g1.account_id)
loan_recv = A("131", "وام کارکنان", "DEBIT", "ASSET", "PERMANENT", True, k13.account_id)

start = datetime.date(2026, 1, 1)
p1_from, p1_to = datetime.date(2026, 3, 21), datetime.date(2026, 4, 20)
p2_from, p2_to = datetime.date(2026, 4, 21), datetime.date(2026, 5, 21)

org = hr.create_org_unit(company_id, "ADM", "اداری", None, None)
pos = hr.create_position(company_id, "CLK", "کارمند", org, None, 5)
e1 = hr.create_employee(company_id, "E1", "علی", "رضایی", "0012345678", start, org, pos, D(100_000_000), None)
e2 = hr.create_employee(company_id, "E2", "مریم", "احمدی", "0087654321", start, org, pos, D(60_000_000), None)

payroll.save_company_settings(company_id, 30, "DAILY", "NONE", 25, None, salary_payable_gl_account_id=salary_pay.account_id)
payroll.create_pay_item(company_id, "BASE", "حقوق پایه", "EARNING", "BASE_SALARY_FROM_CONTRACT", "EARNING_PHASE",
                        is_prorated=True, is_taxable=True, is_insurable=True, gl_account_id=salary_exp.account_id)
payroll.create_pay_item(company_id, "HOUSING", "حق مسکن", "BENEFIT", "FIXED", "EARNING_PHASE", fixed_amount=D(9_000_000),
                        is_prorated=True, is_taxable=True, is_insurable=True, is_continuous_benefit=True,
                        gl_account_id=salary_exp.account_id)
payroll.create_insurance_config(company_id, start, None, D("0.07"), D("0.20"), D("0.03"), None, None,
                                employer_expense_gl_account_id=insurance_exp.account_id)
payroll.set_tax_brackets(company_id, start, [(D(0), D(50_000_000), D(0)), (D(50_000_000), None, D("0.10"))])
period1 = payroll.create_period(company_id, 1405, 1, p1_from, p1_to)

# کارکرد مریم: ۱۵ روز تاییدشده از ۳۰
for day in range(15):
    hr_attendance.create_attendance_record(company_id, e2, p1_from + datetime.timedelta(days=day), worked_hours=D(8),
                                           status="APPROVED")
# اضافه‌کاری علی: ۱۰ ساعت با ضریب ۱٫۴
rule = payroll_overtime.create_overtime_rule(company_id, "OVERTIME", D("1.4"), "ADDITIVE", None, start, None)
entry = payroll_overtime.create_overtime_entry(e1, period1, rule, D(10))
payroll_overtime.set_overtime_entry_status(entry, "APPROVED")
# وام علی: ۱۲ میلیون در ۳ قسط
loan = payroll_loans.create_loan(e1, "LOAN", D(12_000_000), D(0), 3, period1, None)
payroll_loans.approve_loan(loan)
payroll_loans.disburse_loan(loan, company_id)

run1 = payroll_engine.create_run(period1)
result = payroll_engine.run_payroll(run1)
check(result.employees_calculated == 2 and not result.errors, f"both employees are calculated ({result.errors})")


def slip(run_id, employee_id):
    row = next(p for p in payroll_engine.list_payslips(run_id) if p.employee_id == employee_id)
    return row, {l.pay_item_code: l.amount for l in payroll_engine.list_payslip_lines(row.payslip_id)}


# انتظار علی
overtime = (D(109_000_000) / (D(30) * D("7.33"))) * D(10) * D("1.4")
gross1 = D(109_000_000) + overtime
insurance1 = gross1 * D("0.07")
taxable1 = gross1 - insurance1
tax1 = (taxable1 - D(50_000_000)) * D("0.10")
net1 = gross1 - insurance1 - tax1 - D(4_000_000)
row, lines = slip(run1, e1)
check(money(lines["BASE"]) == money(100_000_000) and money(lines["HOUSING"]) == money(9_000_000), "base salary and housing")
check(money(lines["OVERTIME_PAY"]) == money(overtime), f"overtime = (base + continuous benefits) / (30 × 7.33) × hours × 1.4 ({lines['OVERTIME_PAY']})")
check(money(lines["SOCIAL_INSURANCE_EMPLOYEE"]) == money(insurance1), "employee insurance is 7% of the insurable wage")
check(money(lines["INCOME_TAX"]) == money(tax1), f"monthly tax on the cumulative bracket ({lines['INCOME_TAX']} vs {money(tax1)})")
check(money(lines["LOAN_INSTALLMENT_DEDUCTION"]) == money(4_000_000), "the loan instalment is deducted")
check(money(row.gross_amount) == money(gross1) and money(row.net_pay) == money(net1), f"gross and net ({row.net_pay} vs {money(net1)})")

# انتظار مریم (نیمی از ماه)
row2, lines2 = slip(run1, e2)
check(money(lines2["BASE"]) == money(30_000_000) and money(lines2["HOUSING"]) == money(4_500_000),
      "pay is prorated by approved attendance days (15 of 30)")
check(money(lines2["INCOME_TAX"]) == money(0) and money(row2.net_pay) == money(D(34_500_000) * D("0.93")),
      "below the tax-free bracket no tax is withheld")

# بازمحاسبهٔ همان اجرا نباید مالیات را دوبار در دفتر سالانه حساب کند
payroll_engine.run_payroll(run1)
row, lines = slip(run1, e1)
check(money(lines["INCOME_TAX"]) == money(tax1) and money(row.net_pay) == money(net1),
      f"recalculating a draft run gives the same tax ({lines['INCOME_TAX']} vs {money(tax1)})")
ledger = payroll.get_annual_tax_ledger(e1, 1405)
check(money(ledger.cumulative_taxable_income) == money(taxable1) and money(ledger.cumulative_tax_paid) == money(tax1),
      f"the annual tax ledger holds one month only ({ledger.cumulative_taxable_income})")

# تایید، قطعی‌سازی فیش، سند
with new_session() as s:
    for item in s.scalars(select(PayItemDefinition).where(PayItemDefinition.company_id == company_id)):
        item.gl_account_id = item.gl_account_id or {
            "SOCIAL_INSURANCE_EMPLOYEE": insurance_pay.account_id, "INCOME_TAX": tax_pay.account_id,
            "OVERTIME_PAY": salary_exp.account_id, "LOAN_INSTALLMENT_DEDUCTION": loan_recv.account_id}[item.code]
    s.commit()
payroll_engine.approve_run(run1)
final = payroll_payslip.finalize_payslips_for_run(run1)
with new_session() as s:
    statuses = [i.status for i in s.scalars(select(LoanInstallment).where(LoanInstallment.loan_id == loan)
                                            .order_by(LoanInstallment.installment_no))]
check(statuses[0] == "DEDUCTED" and statuses[1:] == ["PENDING", "PENDING"], f"the first instalment is settled ({statuses})")
posting = payroll_journal.post_run_to_journal(run1, uid)
with new_session() as s:
    je_lines = s.scalars(select(JournalEntryLine).where(JournalEntryLine.journal_entry_id == posting.journal_entry_id)).all()
by_account = {}
for l in je_lines:
    by_account[l.account_id] = by_account.get(l.account_id, D(0)) + (l.debit_amount_base or 0) - (l.credit_amount_base or 0)
debits = sum((l.debit_amount_base or 0) for l in je_lines)
credits = sum((l.credit_amount_base or 0) for l in je_lines)
employer = (insurance1 + D(34_500_000) * D("0.07")) * D(23) / D(7)
check(money(debits) == money(credits), f"the payroll journal entry balances ({debits} / {credits})")
check(money(by_account[salary_exp.account_id]) == money(gross1 + D(34_500_000)), "salary expense = all earnings")
check(abs(by_account[insurance_exp.account_id] - employer) < D("0.05"), "employer insurance (23%) is expensed")
check(abs(-by_account[insurance_pay.account_id] - (insurance1 + D(34_500_000) * D("0.07") + employer)) < D("0.05"),
      "insurance payable = employee + employer shares")
check(money(-by_account[tax_pay.account_id]) == money(tax1) and money(-by_account[loan_recv.account_id]) == money(4_000_000),
      "tax payable and the loan receivable are credited")
check(abs(-by_account[salary_pay.account_id] - (net1 + D(34_500_000) * D("0.93"))) < D("0.05"), "salary payable = net pay")

# ماه دوم: مالیات تجمعی درست و قسط دوم
period2 = next((p.period_id for p in payroll.list_periods(company_id) if (p.jalali_year, p.jalali_month) == (1405, 2)), None) \
    or payroll.create_period(company_id, 1405, 2, p2_from, p2_to)  # اقساط وام دوره‌های بعد را خودش می‌سازد
run2 = payroll_engine.create_run(period2)
payroll_engine.run_payroll(run2)
row, lines = slip(run2, e1)
taxable2 = D(109_000_000) * D("0.93")
tax2 = (taxable1 + taxable2 - D(50_000_000)) * D("0.10") - tax1
check(money(lines["INCOME_TAX"]) == money(tax2), f"month two tax follows the cumulative method ({lines['INCOME_TAX']} vs {money(tax2)})")
check(money(lines["LOAN_INSTALLMENT_DEDUCTION"]) == money(4_000_000), "the second instalment is deducted in month two")

finish()
