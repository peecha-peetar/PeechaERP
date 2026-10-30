"""R349: تسعیر ارز: ماندهٔ ارزی بانک ارزی و طلب ارزی مشتری با نرخ روز، بستن تفاوت ریالی طلب تسویه‌شده (ماندهٔ ارزی صفر)،
نبود نرخ و حساب سود و زیان، سند موقت تسعیر روی حساب ارزی، حفظ محدودیت ارز حساب برای اسناد عادی، تسعیر دوباره فقط تفاوت
تازه، زیان تسعیر و برگرداندن، انتقال ماندهٔ ارزی با همان ارز به سال بعد (با باقی‌ماندهٔ گردکردن) و فرم."""
import datetime, decimal, os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r349"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prd_fixture import *  # noqa: F401,F403

from peecha.db.models.accounting import ChartOfAccount, FiscalYear, FxPositionAdjustment, JournalEntry, JournalEntryLine
from peecha.services import commercial_partners as partners, currencies, fx_revaluation as fx, journal_entries as je, year_end
from peecha.services import detail_dimensions as dims

L = je.LineInput
usd = next(c.currency_id for c in currencies.list_all_currencies() if c.iso_code == "USD")
currencies.set_company_currency(company_id, usd, True)
k11 = A("11", "نقد و بانک", "DEBIT", "ASSET", "PERMANENT", False, g1.account_id)
bank = A("111", "بانک ارزی", "DEBIT", "ASSET", "PERMANENT", True, k11.account_id)
k13 = A("13", "دریافتنی‌ها", "DEBIT", "ASSET", "PERMANENT", False, g1.account_id)
ar = A("131", "دریافتنی مشتریان", "DEBIT", "ASSET", "PERMANENT", True, k13.account_id)
g_eq = A("3", "حقوق صاحبان سهام", "CREDIT", "EQUITY", "PERMANENT", False)
k31 = A("31", "سرمایه", "CREDIT", "EQUITY", "PERMANENT", False, g_eq.account_id)
capital = A("311", "سرمایه", "CREDIT", "EQUITY", "PERMANENT", True, k31.account_id)
retained = A("312", "سود انباشته", "CREDIT", "EQUITY", "PERMANENT", True, k31.account_id)
g_rev = A("4", "درآمدها", "CREDIT", "REVENUE", "TEMPORARY", False)
k41 = A("41", "درآمدها", "CREDIT", "REVENUE", "TEMPORARY", False, g_rev.account_id)
revenue = A("411", "فروش", "CREDIT", "REVENUE", "TEMPORARY", True, k41.account_id)
fx_gain = A("412", "سود تسعیر ارز", "CREDIT", "REVENUE", "TEMPORARY", True, k41.account_id)
k59 = A("59", "سایر هزینه‌ها", "DEBIT", "EXPENSE", "TEMPORARY", False, g3.account_id)
fx_loss = A("591", "زیان تسعیر ارز", "DEBIT", "EXPENSE", "TEMPORARY", True, k59.account_id)
with new_session() as s:
    s.get(ChartOfAccount, bank.account_id).currency_id = usd  # حساب فقط دلاری
    s.commit()
    fy = s.scalar(select(FiscalYear).where(FiscalYear.company_id == company_id))
    start, fy_end, fy_id = fy.start_date, fy.end_date, fy.fiscal_year_id
person = dims.get_person_dimension_type_id(company_id)
c1 = partners.create_customer(company_id, "C1", "مشتری ارزی", fast_track=True)
d0, d1, d2, d3 = (start + datetime.timedelta(days=n) for n in (1, 10, 20, 15))


def money(value):
    return decimal.Decimal(value).quantize(decimal.Decimal("0.01"))


def post(day, *lines):
    return je.create_journal_entry(company_id, uid, day, "سند", list(lines)).journal_entry_id


post(d0, L(bank.account_id, "", D(1000), D(0), currency_id=usd, exchange_rate=D(500_000)),
     L(capital.account_id, "", D(0), D(500_000_000)))
post(d0, L(ar.account_id, "", D(200), D(0), details={person: c1}, currency_id=usd, exchange_rate=D(510_000)),
     L(revenue.account_id, "", D(0), D(102_000_000)))
post(d0, L(bank.account_id, "", D(200), D(0), currency_id=usd, exchange_rate=D(520_000)),
     L(ar.account_id, "", D(0), D(200), details={person: c1}, currency_id=usd, exchange_rate=D(520_000)))
check(raises(lambda: post(d0, L(bank.account_id, "", D(1), D(0)), L(capital.account_id, "", D(0), D(1))), "ارز"),
      "an ordinary entry still cannot post rials to the dollar account")

info = fx.preview(company_id, d0)
check(any("نرخ ارز USD" in p for p in info.problems), f"a missing rate is reported ({info.problems})")
currencies.set_exchange_rate(company_id, usd, d1, D(530_000))
currencies.set_exchange_rate(company_id, usd, d2, D(520_000))
info = fx.preview(company_id, d1)
rows = {(r.account_id, r.details): r for r in info.rows}
b, a = rows[(bank.account_id, ())], rows[(ar.account_id, ((person, c1),))]
check(b.fc_balance == D(1200) and money(b.base_before) == money(604_000_000) and money(b.base_after) == money(636_000_000)
      and money(b.difference) == money(32_000_000), f"the dollar bank is revalued at the day's rate ({b})")
check(a.fc_balance == 0 and money(a.base_before) == money(-2_000_000) and money(a.difference) == money(2_000_000)
      and a.details_label == "مشتری ارزی", "a settled receivable's rial residue is closed as an FX difference")
check(money(info.gain) == money(34_000_000) and any("سود تسعیر" in p for p in info.problems), "without a gain account it cannot run")
check(raises(lambda: fx.run(company_id, d1, uid), "سود تسعیر"), "run refuses with the reason")
fx.save_accounts(company_id, fx_gain.account_id, fx_loss.account_id)
entry1 = fx.run(company_id, d1, uid)
with new_session() as s:
    lines = s.scalars(select(JournalEntryLine).where(JournalEntryLine.journal_entry_id == entry1)).all()
    adjustments = s.scalars(select(FxPositionAdjustment).where(FxPositionAdjustment.line_id.in_([l.line_id for l in lines]))).all()
by_account = {l.account_id: l.debit_amount_base - l.credit_amount_base for l in lines}
check(money(by_account[bank.account_id]) == money(32_000_000) and money(by_account[ar.account_id]) == money(2_000_000)
      and money(by_account[fx_gain.account_id]) == money(-34_000_000) and len(adjustments) == 2
      and all(x.currency_id == usd for x in adjustments), "the revaluation entry adjusts the dollar positions in rials")
after = fx.preview(company_id, d1)
check(all(not r.difference for r in after.rows), "revaluing again on the same rate finds no difference")
check(fx.run(company_id, d1, uid) is None, "nothing to post the second time")

loss = fx.preview(company_id, d2)
b2 = next(r for r in loss.rows if r.account_id == bank.account_id)
check(money(b2.base_before) == money(636_000_000) and money(b2.difference) == money(-12_000_000) and money(loss.loss) == money(12_000_000),
      "a later lower rate gives a loss on the revalued balance only")
fx.run(company_id, d2, uid)
history = fx.list_revaluations(company_id)
check([h.revaluation_date for h in history] == [d2, d1] and history[0].status_code == "TEMPORARY", "both revaluations are listed")
fx.undo(history[0].revaluation_id, company_id)
check(money(next(r for r in fx.preview(company_id, d2).rows if r.account_id == bank.account_id).base_before) == money(636_000_000)
      and len(fx.list_revaluations(company_id)) == 1, "undo removes the entry and its adjustments")

# انتقال سال: ماندهٔ ارزی با همان ارز و باقی‌ماندهٔ گردکردن
post(d3, L(bank.account_id, "", D("12345.67"), D(0), currency_id=usd, exchange_rate=D("498765.432109")),
     L(capital.account_id, "", D(0), D("6157593432.23")))
year_end.save_settings(company_id, retained.account_id, None)
with new_session() as s:
    old = {k: v for k, v in fx.balances(s, company_id, fy_id).items() if k[0] in (bank.account_id, ar.account_id)}
result = year_end.close_year(company_id, fy_id, uid)
with new_session() as s:
    next_fy = s.get(JournalEntry, result.opening_id).fiscal_year_id
    new = {k: v for k, v in fx.balances(s, company_id, next_fy).items() if k[0] in (bank.account_id, ar.account_id)}
    opening_lines = s.scalars(select(JournalEntryLine).where(JournalEntryLine.journal_entry_id == result.opening_id,
                                                             JournalEntryLine.account_id == bank.account_id)).all()
    opening_adjustments = s.scalars(select(FxPositionAdjustment).where(
        FxPositionAdjustment.line_id.in_([l.line_id for l in opening_lines]))).all()
fc, base = old[(bank.account_id, (), usd)]
rate = abs(base / fc).quantize(decimal.Decimal("0.000001"))
residual = base - (fc * rate).quantize(decimal.Decimal("0.01"))
check(new == old and fc == D("13545.67") and money(base) == money(D(636_000_000) + D("6157593432.23")),
      f"the next year opens with the same dollar and rial balances ({new} vs {old})")
check(any(l.currency_id == usd and l.debit_amount_fc == fc for l in opening_lines)
      and len(opening_adjustments) == (1 if residual else 0) and residual != 0,
      f"the opening carries dollars at the average rate and registers the rounding residue ({residual})")
next_start = fy_end + datetime.timedelta(days=1)
nxt = next(r for r in fx.preview(company_id, next_start, {usd: D(530_000)}).rows if r.account_id == bank.account_id)
check(money(nxt.difference) == money(D("13545.67") * 530_000 - base), "revaluation in the new year starts from the carried balance")

# فرم
from PySide6.QtWidgets import QApplication, QPushButton
qapp = QApplication.instance() or QApplication([])
from peecha.ui.screens.fx_revaluation import FxRevaluationScreen

screen = FxRevaluationScreen()
screen.refresh()
screen.date_field.setDate(d2)
check(screen.table.rowCount() >= 1 and screen.rates_table.rowCount() == 1 and screen.gain_combo.currentData() == fx_gain.account_id
      and screen.history_table.rowCount() == 1 and any(b.accessibleName() == "ثبت سند تسعیر" for b in screen.findChildren(QPushButton)),
      "the screen shows positions, the rate, the saved accounts and the history")

finish()
