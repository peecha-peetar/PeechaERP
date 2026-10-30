"""R355: یکی‌شدن بودجهٔ سادهٔ خرید با بودجه‌ریزی سازمانی: پیش از انتشار، گزارش‌ها و هشدار از بودجهٔ ساده؛ پس از انتشار
نسخهٔ دارای ردیف «خرید و تعهد»، همهٔ گزارش‌های بودجهٔ منوی خرید (در برابر واقعی، ریز تعهد، روند ماهانه با مبلغ دوره‌ها،
خرید خارج از بودجه) از دفتر مصرف بودجه‌ریزی، هشدار ساده خاموش، بودجهٔ سادهٔ بعدی در گزارش‌ها نمی‌آید و فرم پیام راهنما دارد."""
import os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r355"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bud_fixture import *  # noqa: F401,F403
import bud_fixture as fx

from peecha.services import purchase_budgets as simple
from peecha.services import purchase_reports as base
from peecha.services import purchase_reports_ext as ext

check, raises = fx.check, fx.raises
f = base.PurchaseFilters(fy_start, fy_end)


def simple_fields(code, amount, **kw):
    return simple.BudgetFields(code, "بودجهٔ ساده " + code, fy_start, fy_end, D(amount), **kw)


legacy_id = simple.save_budget(company_id, simple_fields("S1", 1_100_000, cost_center_detail_account_id=cc_a))
o1 = po([(other, 10, 100_000)], cc=cc_a)
o2 = po([(other, 3, 100_000)], pj=pj_1)
check(not simple.organizational_active(company_id), "no published organizational purchase budget yet")
rows = ext.budget_vs_actual(company_id, f).rows
check(len(rows) == 1 and rows[0][0].startswith("S1") and rows[0][6] == D(1_000_000), f"reports read the simple budget ({rows})")
check(any("S1" in w for w in simple.warnings_for_document(o1, company_id)), "the simple budget warns on the purchase document")
unbudgeted = {r[1] for r in ext.unbudgeted_purchases(company_id, f).rows}
check(unbudgeted == {docs.get_document(o2, company_id)[0].document_no}, "the project order is outside the simple budget")

# نسخهٔ پیش‌نویس سازمانی: بودجهٔ ساده منتقل می‌شود و ردیف پروژه همهٔ مبلغ را در دورهٔ اول دارد
toggle(sc.BUD_SELF_APPROVAL, True)
bid = bud.create_budget(company_id, uid, fy_id, "B1", "بودجهٔ خرید سالانه", "MONTH")
vid = next(b.open_version_id for b in bud.list_budgets(company_id) if b.budget_id == bid)
check(bud.import_simple_budgets(company_id, uid, vid) == 1, "the simple budget is brought into the draft version")
l_pj = bud.add_line(company_id, uid, vid, P(project_detail_account_id=pj_1), D(2_000_000))
bud.set_period_amounts(company_id, uid, l_pj, {n: (D(2_000_000) if n == 1 else D(0))
                                               for n, *_r in bud.split_periods(fy_start, fy_end, "MONTH")})
check(not simple.organizational_active(company_id), "a draft version does not switch the purchase reports")
for step in (bap.submit, bap.review, bap.approve, bap.publish):
    step(company_id, uid, vid)
toggle(sc.BUD_SELF_APPROVAL, False)

check(simple.organizational_active(company_id), "the published version with purchase lines takes over")
rows = {r[0]: r for r in ext.budget_vs_actual(company_id, f).rows}
cc_row = next((r for name, r in rows.items() if "واحد تولید" in name), None)
pj_row = next((r for name, r in rows.items() if "پروژه" in name), None)
check(len(rows) == 2 and not any(name.startswith("S1") for name in rows), f"only the organizational lines are listed ({list(rows)})")
check(cc_row is not None and cc_row[4] == D(1_100_000) and cc_row[6] == D(1_000_000) and "واحد تولید" in cc_row[1],
      f"the imported line carries the order commitment from the budgeting ledger ({cc_row})")
check(pj_row is not None and pj_row[6] == D(300_000) and pj_row[4] == D(2_000_000), f"the project line too ({pj_row})")
check(simple.warnings_for_document(o1, company_id) == [], "the simple-budget warning gives way to the organizational control")
check(ext.unbudgeted_purchases(company_id, f).rows == [], "the project order is budgeted now")
o3 = po([(other, 1, 70_000)])
check([r[1] for r in ext.unbudgeted_purchases(company_id, f).rows] == [docs.get_document(o3, company_id)[0].document_no],
      "an order matching no organizational line is unbudgeted")

commitments = ext.budget_commitments(company_id, f)
check(sorted(r[6] for r in commitments.rows) == [D(300_000), D(1_000_000)]
      and {ref[0] for ref in commitments.refs} == {o1, o2}, "the commitment detail lists the orders from the ledger")
months = [r for r in ext.budget_monthly(company_id, f).rows if "پروژه" in r[0]]
check(len(months) >= 12 and months[0][2] == D(2_000_000) and all(r[2] == 0 for r in months[1:]),
      f"the monthly trend follows the version's period amounts ({[r[2] for r in months[:3]]})")
overrun = ext.budget_overrun(company_id, f).rows
check(len(overrun) == 1 and "واحد تولید" in overrun[0][0], "the over-threshold line is the cost-center one (1.0M of 1.1M)")

simple.save_budget(company_id, simple_fields("S2", 500_000))
check(not any(r[0].startswith("S2") for r in ext.budget_vs_actual(company_id, f).rows),
      "a simple budget defined later stays out of the purchase reports while organizational budgeting is in use")
simple.save_budget(company_id, simple_fields("S1", 1_100_000, cost_center_detail_account_id=cc_a, is_active=False), legacy_id)
check([b.code for b in simple.list_budgets(company_id, active_only=True)] == ["S2"], "an existing simple budget can still be deactivated")

# فرم بودجهٔ ساده
from PySide6.QtWidgets import QApplication
qapp = QApplication.instance() or QApplication([])
from peecha.ui.screens.procurement_masters import ProcurementMastersScreen

screen = ProcurementMastersScreen()
screen.budgets_tab.refresh()
check(not screen.budgets_tab.org_notice.isHidden() and "بودجه‌ریزی و کنترل بودجه" in screen.budgets_tab.org_notice.text()
      and screen.budgets_tab.table.rowCount() == 2, "the simple-budget form shows the guidance and keeps the old rows")

finish()
