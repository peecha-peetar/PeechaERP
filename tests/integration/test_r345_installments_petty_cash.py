"""R345: طرح اقساط آزاد با بهره و هزینه (تقسیم، سررسیدها، وصول جزئی، رد وصول بیش از مانده، معوق‌شدن، تکمیل طرح)
و تنخواه‌گردان (افتتاح با سند پرداخت، ثبت ردیف‌ها، رد روش نامجاز، بستن با سند متوازن و قفل پس از بستن)."""
import datetime, os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r345_cash"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prd_fixture import *  # noqa: F401,F403

from peecha.db.models.accounting import JournalEntryLine
from peecha.services import installments, petty_cash, treasury
from peecha.services import detail_dimensions as dims

customer = dims.create_customer(company_id, "C1", "مشتری اقساطی")
customer_id = getattr(customer, "detail_account_id", customer)


def refused(fn, needle):
    try:
        fn()
    except ValueError as exc:
        return needle in str(exc)
    return False


# --- اقساط ---------------------------------------------------------------------------------------------------------------
due1 = today + datetime.timedelta(days=10)  # آینده، تا فهرست اقساط خودش معوق نزند
check(refused(lambda: installments.create_installment_plan(None, 1, due1, D(1000), company_id=company_id,
                                                           counterparty_detail_account_id=customer_id, direction="RECEIPT"),
              "حداقل ۲"), "a plan needs at least two instalments")
check(refused(lambda: installments.create_installment_plan(None, 3, due1, D(9_000_000), company_id=company_id), "الزامی"),
      "a plan without an invoice needs a counterparty and a direction")
plan = installments.create_installment_plan(None, 3, due1, D(9_000_000), company_id=company_id,
                                            counterparty_detail_account_id=customer_id, direction="RECEIPT",
                                            interest_rate_percent=D(10), misc_fee_amount=D(300_000), due_interval_days=30)
rows = sorted(installments.list_installments(company_id), key=lambda r: r.installment_no)
check([r.amount for r in rows] == [D(3_400_000)] * 3, f"principal plus 10% interest and the fee is split evenly ({[r.amount for r in rows]})")
check([r.due_date for r in rows] == [due1, due1 + datetime.timedelta(days=30), due1 + datetime.timedelta(days=60)],
      "due dates are 30 days apart")
first = rows[0]
line_id = getattr(first, "installment_line_id", None) or getattr(first, "line_id")
installments.record_installment_collection(line_id, D(1_000_000), None, due1, uid, "پیش‌قسط")
check(installments.get_installment_remaining_amount(line_id) == D(2_400_000)
      and installments.get_installment_line(line_id).status_code != "PAID", "a partial collection leaves the rest open")
check(refused(lambda: installments.record_installment_collection(line_id, D(3_000_000), None, due1, uid), "بیشتر"),
      "collecting more than the remainder is refused")
installments.record_installment_collection(line_id, D(2_400_000), None, due1, uid)
check(installments.get_installment_line(line_id).status_code == "PAID", "the instalment is paid once fully collected")
overdue = installments.list_overdue_installments(company_id, due1 + datetime.timedelta(days=31))
check(len(overdue) == 1 and overdue[0].installment_no == 2, "a passed due date marks only that instalment overdue")
for r in rows[1:]:
    other = getattr(r, "installment_line_id", None) or getattr(r, "line_id")
    installments.record_installment_collection(other, D(3_400_000), None, due1, uid)
check(installments.get_installment_plan(plan).status_code == "COMPLETED", "collecting everything completes the plan")

# --- تنخواه‌گردان ------------------------------------------------------------------------------------------------------------
k11 = A("11", "موجودی نقد و بانک", "DEBIT", "ASSET", "PERMANENT", False, g1.account_id)
cash = A("111", "صندوق", "DEBIT", "ASSET", "PERMANENT", True, k11.account_id)
bank = A("112", "بانک", "DEBIT", "ASSET", "PERMANENT", True, k11.account_id)
advance = A("113", "پیش‌پرداخت تنخواه", "DEBIT", "ASSET", "PERMANENT", True, k11.account_id)
treasury.set_account_mapping(company_id, "PAYMENT_CASH", cash.account_id)
treasury.set_account_mapping(company_id, "PAYMENT_BANK", bank.account_id)
treasury.set_account_mapping(company_id, petty_cash.PETTY_CASH_ADVANCE_MAPPING_KEY, advance.account_id)
petty_type = dims.get_specialized_dimension_type_id(company_id, dims.PETTY_CASH_CODE)
custodian = dims.create_detail_account(company_id, petty_type, "01", "تنخواه‌دار دفتر").detail_account_id

fund, opening = petty_cash.open_fund(company_id, uid, custodian, today, "افتتاح تنخواه",
                                     [treasury.MethodLine("CASH", D(50_000_000))])
check(gl_balance(advance.account_id) == D(50_000_000) and gl_balance(cash.account_id) == D(-50_000_000),
      "opening the fund pays cash to the custodian's advance")
petty_cash.add_line(fund, "CASH", D(20_000_000), "خرید ملزومات")
petty_cash.add_line(fund, "BANK", D(10_000_000), "پرداخت قبض")
check(refused(lambda: petty_cash.add_line(fund, "CHECK_DISBURSEMENT", D(1000), "x"), "نامعتبر"),
      "a method outside the fund's list is refused")
closing = petty_cash.close_fund(fund, uid, today)
with new_session() as s:
    lines = s.scalars(select(JournalEntryLine).where(JournalEntryLine.journal_entry_id == closing.journal_entry_id)).all()
debit = {l.account_id: l.debit_amount_base for l in lines if l.debit_amount_base}
credit = {l.account_id: l.credit_amount_base for l in lines if l.credit_amount_base}
check(debit == {cash.account_id: D(20_000_000), bank.account_id: D(10_000_000)} and credit == {advance.account_id: D(30_000_000)},
      f"closing settles the spent lines against the advance ({debit} / {credit})")
check(petty_cash.get_fund(fund).status == "CLOSED"
      and refused(lambda: petty_cash.add_line(fund, "CASH", D(1000), "x"), "بسته"), "a closed fund takes no new lines")
check(refused(lambda: petty_cash.open_fund(company_id, uid, supplier, today, "x", [treasury.MethodLine("CASH", D(1))]),
              "تنخواه"), "only a petty-cash detail account can hold a fund")

finish()
