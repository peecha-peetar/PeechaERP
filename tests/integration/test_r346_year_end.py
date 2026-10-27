"""R346: پایان سال مالی: پیش‌نمایش سود خالص، مانع سند پیش‌نویس و نبودن حساب سود انباشته، بستن حساب‌های موقت به خلاصهٔ
سود و زیان، انتقال به سود (زیان) انباشته، سند اختتامیه (صفرشدن همهٔ مانده‌ها) و سند افتتاحیهٔ سال بعد با ماندهٔ هر
مشتری جداگانه، جلوگیری از اجرای دوباره، برگرداندن پیش از قطعی‌شدن، و پنجرهٔ پایان سال."""
import datetime, os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r346"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prd_fixture import *  # noqa: F401,F403

from peecha.db.models.accounting import FiscalYear, JournalEntry, JournalEntryLine, JournalEntryLineDetail, JournalEntryType
from peecha.services import commercial_partners as partners, journal_entries as je, year_end
from peecha.services import detail_dimensions as dims

L = je.LineInput
k11 = A("11", "نقد", "DEBIT", "ASSET", "PERMANENT", False, g1.account_id)
cash = A("111", "صندوق", "DEBIT", "ASSET", "PERMANENT", True, k11.account_id)
k13 = A("13", "دریافتنی‌ها", "DEBIT", "ASSET", "PERMANENT", False, g1.account_id)
ar = A("131", "دریافتنی مشتریان", "DEBIT", "ASSET", "PERMANENT", True, k13.account_id)
g_eq = A("3", "حقوق صاحبان سهام", "CREDIT", "EQUITY", "PERMANENT", False)
k31 = A("31", "سرمایه و اندوخته", "CREDIT", "EQUITY", "PERMANENT", False, g_eq.account_id)
capital = A("311", "سرمایه", "CREDIT", "EQUITY", "PERMANENT", True, k31.account_id)
retained = A("312", "سود (زیان) انباشته", "CREDIT", "EQUITY", "PERMANENT", True, k31.account_id)
summary = A("313", "خلاصهٔ سود و زیان", "CREDIT", "EQUITY", "TEMPORARY", True, k31.account_id)
g_rev = A("4", "درآمدها", "CREDIT", "REVENUE", "TEMPORARY", False)
k41 = A("41", "فروش", "CREDIT", "REVENUE", "TEMPORARY", False, g_rev.account_id)
revenue = A("411", "فروش کالا", "CREDIT", "REVENUE", "TEMPORARY", True, k41.account_id)
k53 = A("53", "هزینه‌های اداری", "DEBIT", "EXPENSE", "TEMPORARY", False, g3.account_id)
expense = A("531", "هزینهٔ اجاره", "DEBIT", "EXPENSE", "TEMPORARY", True, k53.account_id)

person = dims.get_person_dimension_type_id(company_id)
c1 = partners.create_customer(company_id, "C1", "مشتری یک", fast_track=True)
c2 = partners.create_customer(company_id, "C2", "مشتری دو", fast_track=True)
with new_session() as s:
    fy = s.scalar(select(FiscalYear).where(FiscalYear.company_id == company_id))
    fy_id, fy_end = fy.fiscal_year_id, fy.end_date
day = min(today, fy_end)


def post(description, *lines):
    return je.create_journal_entry(company_id, uid, day, description, list(lines)).journal_entry_id


post("آوردهٔ سرمایه", L(cash.account_id, "", D(500_000_000), D(0)), L(capital.account_id, "", D(0), D(500_000_000)))
post("فروش به یک", L(ar.account_id, "", D(120_000_000), D(0), details={person: c1}), L(revenue.account_id, "", D(0), D(120_000_000)))
post("فروش به دو", L(ar.account_id, "", D(80_000_000), D(0), details={person: c2}), L(revenue.account_id, "", D(0), D(80_000_000)))
post("اجاره", L(expense.account_id, "", D(150_000_000), D(0)), L(cash.account_id, "", D(0), D(150_000_000)))
post("وصول از یک", L(cash.account_id, "", D(20_000_000), D(0)), L(ar.account_id, "", D(0), D(20_000_000), details={person: c1}))


def refused(fn, needle):
    try:
        fn()
    except ValueError as exc:
        return needle in str(exc)
    return False


info = year_end.preview(company_id, fy_id)
check(info.net_income == D(50_000_000) and info.temporary_rows == 2, f"the preview shows a 50M profit ({info.net_income})")
check(any("انباشته" in p for p in info.problems), "without a retained-earnings account the year cannot be closed")
check(refused(lambda: year_end.save_settings(company_id, retained.account_id, retained.account_id), "فرق"),
      "the summary and retained-earnings accounts must differ")
year_end.save_settings(company_id, retained.account_id, summary.account_id)
draft = je.create_journal_entry(company_id, uid, day, "پیش‌نویس", [L(cash.account_id, "", D(1), D(0))], as_draft=True)
check(refused(lambda: year_end.close_year(company_id, fy_id, uid), "پیش‌نویس"), "a draft entry in the year blocks closing")
je.delete_journal_entry(draft.journal_entry_id, company_id)


def balance(account_id, fiscal_year_id, detail=None):
    with new_session() as s:
        query = (select(func.coalesce(func.sum(JournalEntryLine.debit_amount_base - JournalEntryLine.credit_amount_base), 0))
                 .join(JournalEntry, JournalEntry.journal_entry_id == JournalEntryLine.journal_entry_id)
                 .where(JournalEntryLine.account_id == account_id, JournalEntry.fiscal_year_id == fiscal_year_id))
        if detail is not None:
            query = query.join(JournalEntryLineDetail, JournalEntryLineDetail.line_id == JournalEntryLine.line_id).where(
                JournalEntryLineDetail.detail_account_id == detail)
        return D(s.scalar(query))


result = year_end.close_year(company_id, fy_id, uid)
check(all([result.closing_temporary_id, result.transfer_id, result.closing_id, result.opening_id]) and result.net_income == D(50_000_000),
      "four entries are created: temporary closing, transfer, closing and opening")
check(balance(revenue.account_id, fy_id) == 0 and balance(expense.account_id, fy_id) == 0 and balance(summary.account_id, fy_id) == 0,
      "revenue, expense and the income summary are closed")
check(all(balance(a.account_id, fy_id) == 0 for a in (cash, ar, capital, retained)), "the closing entry zeroes every balance")
with new_session() as s:
    opening = s.get(JournalEntry, result.opening_id)
    next_fy = opening.fiscal_year_id
    types = {e.journal_entry_id: s.get(JournalEntryType, e.entry_type_id).code
             for e in s.scalars(select(JournalEntry).where(JournalEntry.alternative_number == f"پایان سال {fy.code}"))}
check(next_fy != fy_id and opening.document_date == fy_end + datetime.timedelta(days=1), "the opening entry is dated the next year's first day")
check(sorted(types.values()) == ["CLOSING", "CLOSING", "CLOSING", "OPENING"], f"entry types are closing and opening ({types})")
check(balance(cash.account_id, next_fy) == D(370_000_000) and balance(capital.account_id, next_fy) == D(-500_000_000)
      and balance(retained.account_id, next_fy) == D(-50_000_000), "the next year opens with cash, capital and the year's profit")
check(balance(ar.account_id, next_fy, c1) == D(100_000_000) and balance(ar.account_id, next_fy, c2) == D(80_000_000),
      "each customer's receivable is carried forward separately")
check(refused(lambda: year_end.close_year(company_id, fy_id, uid), "قبلاً"), "the year end cannot run twice")

check(year_end.undo_year_end(company_id, fy_id) == 4 and balance(revenue.account_id, fy_id) == D(-200_000_000)
      and not year_end.preview(company_id, fy_id).already_done, "undo removes the four entries and restores the balances")
result = year_end.close_year(company_id, fy_id, uid)
je.approve_journal_entry(result.closing_id, company_id, uid)
check(refused(lambda: year_end.undo_year_end(company_id, fy_id), "قطعی"), "after approval the year end can no longer be undone")

# پنجرهٔ پایان سال
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton
qapp = QApplication.instance() or QApplication([])
from peecha.ui.screens.fiscal_years import FiscalYearsScreen
from peecha.ui.screens.year_end_dialog import YearEndDialog

screen = FiscalYearsScreen()
screen.refresh()
check(any(b.accessibleName() == "پایان سال مالی" for b in screen.findChildren(QPushButton)), "the fiscal-years screen has a year-end button")
dialog = YearEndDialog(None, company_id, fy_id)
check(dialog.retained.currentData() == retained.account_id and dialog.summary.currentData() == summary.account_id
      and "۵۰٬۰۰۰٬۰۰۰" in dialog.summary_label.text().replace(",", "٬") and not dialog.run_button.isEnabled()
      and dialog.undo_button.isEnabled(), f"the dialog shows the saved accounts, the profit and the done state ({dialog.summary_label.text()})")

finish()
