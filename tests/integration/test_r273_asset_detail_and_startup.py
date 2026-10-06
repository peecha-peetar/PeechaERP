import os, sys, time
os.environ["PEECHA_DB_NAME"] = "peecha_test_r273"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PySide6.QtWidgets import QApplication, QMessageBox
app = QApplication.instance() or QApplication([])
QMessageBox.warning = staticmethod(lambda *a, **k: None)
QMessageBox.information = staticmethod(lambda *a, **k: None)
from prd_fixture import *  # noqa: F401,F403
import prd_fixture as fx
import jdatetime
from peecha.db.models.accounting import DetailAccount, JournalEntryLine, JournalEntryLineDetail
from peecha.db.models.fixed_assets import Asset
from peecha.services.fixed_assets import common as fac, assets as fa, depreciation as fd, events as fe
check, raises = fx.check, fx.raises

# --- حساب‌ها و طبقه -------------------------------------------------------------------------------------
k9 = A("14", "دارایی‌هایِ ثابت", "DEBIT", "ASSET", "PERMANENT", False, g1.account_id)
fa_gl = A("1401", "ماشین‌آلات", "DEBIT", "ASSET", "PERMANENT", True, k9.account_id)
accum_gl = A("1409", "استهلاکِ انباشته", "CREDIT", "ASSET", "PERMANENT", True, k9.account_id)
dep_gl = A("531", "هزینهٔ استهلاک", "DEBIT", "EXPENSE", "TEMPORARY", True, k6.account_id)
gain_gl = A("532", "سود/زیانِ واگذاری", "CREDIT", "EXPENSE", "TEMPORARY", True, k6.account_id)
k13 = A("13", "دریافتنی‌ها", "DEBIT", "ASSET", "PERMANENT", False, g1.account_id)
ar_gl = A("131", "دریافتنی", "DEBIT", "ASSET", "PERMANENT", True, k13.account_id)
fac.ensure_default_categories(company_id)
cats = {x.code: x for x in fac.list_categories(company_id)}
mach = fac.save_category(company_id, fac.CategoryFields("MACHINERY", "ماشین‌آلات", "STRAIGHT_LINE", 12, accounts=dict(
    asset_account_id=fa_gl.account_id, accumulated_depreciation_account_id=accum_gl.account_id,
    depreciation_expense_account_id=dep_gl.account_id, disposal_gain_account_id=gain_gl.account_id,
    disposal_loss_account_id=gain_gl.account_id)), category_id=cats["MACHINERY"].category_id, user_id=uid)
fa_type = dimensions_service.get_specialized_dimension_type_id(company_id, dimensions_service.FIXED_ASSET_CODE)


def jd(m, d=1):
    return jdatetime.date(1405, m, d).togregorian()


def detail_of(asset_id):
    with new_session() as s:
        a = s.get(Asset, asset_id)
        return a.detail_account_id, (s.get(DetailAccount, a.detail_account_id) if a.detail_account_id else None)


def lines_with_asset_detail(je_id, detail_id):
    with new_session() as s:
        rows = s.execute(select(JournalEntryLine.account_id, JournalEntryLine.debit_amount_base, JournalEntryLine.credit_amount_base)
                         .join(JournalEntryLineDetail, JournalEntryLineDetail.line_id == JournalEntryLine.line_id)
                         .where(JournalEntryLine.journal_entry_id == je_id, JournalEntryLineDetail.detail_account_id == detail_id,
                                JournalEntryLineDetail.dimension_type_id == fa_type)).all()
    return {r[0]: (r[1], r[2]) for r in rows}


# ۱) دارایی تازه: تفصیلیِ «دارایی ثابت» با همان کد و نام
F = lambda code, **kw: fa.AssetFields(asset_code=code, name=kw.pop("name", "دستگاهِ " + code), category_id=mach, **kw)
cnc = fa.create_asset(company_id, uid, F("CNC-001", name="ماشینِ CNC"))
did, det = detail_of(cnc)
check(det is not None and det.dimension_type_id == fa_type and det.code == "CNC-001" and det.name == "ماشینِ CNC",
      "new asset gets its own FIXED_ASSET detail account (same code/name)")

# ۲) تحصیل، استهلاک، فروش: ردیف‌هایِ دارایی/انباشته/هزینه با تفصیلیِ دارایی
je = fa.acquire(company_id, uid, cnc, jd(3, 10), [fa.CostItem("PURCHASE", D(1_200_000), ap_gl.account_id, supplier)],
                idempotency_key="ACQ")
fa.capitalize(company_id, uid, cnc, jd(3, 15), in_service_date=jd(3, 1))
check(lines_with_asset_detail(je, did) == {fa_gl.account_id: (D(1_200_000), D(0))}, "acquisition: asset line carries asset detail")
rid = fd.calculate_run(company_id, uid, "1405/03")
fd.approve_run(company_id, uid, rid)
je_dep = fd.post_run(company_id, uid, rid)
got = lines_with_asset_detail(je_dep, did)
check(got.get(dep_gl.account_id) == (D(100_000), D(0)) and got.get(accum_gl.account_id) == (D(0), D(100_000)),
      f"depreciation: expense + accumulated per asset detail {got}")

# دو دارایی در یک اجرا: سند به تفکیکِ هر دارایی (نه جمعی)
press = fa.create_asset(company_id, uid, F("PRS-01", name="پرس"))
fa.acquire(company_id, uid, press, jd(3, 10), [fa.CostItem("PURCHASE", D(600_000), ap_gl.account_id, supplier)])
fa.capitalize(company_id, uid, press, jd(3, 15), in_service_date=jd(4, 1))
rid4 = fd.calculate_run(company_id, uid, "1405/04")
fd.approve_run(company_id, uid, rid4)
je4 = fd.post_run(company_id, uid, rid4)
pid, _ = detail_of(press)
check(lines_with_asset_detail(je4, did).get(accum_gl.account_id) == (D(0), D(100_000))
      and lines_with_asset_detail(je4, pid).get(accum_gl.account_id) == (D(0), D(50_000)), "one run, separate line per asset detail")

ev = fe.sell(company_id, uid, press, jd(5, 1), D(700_000), ar_gl.account_id, idempotency_key="SELL")
with new_session() as s:
    from peecha.db.models.fixed_assets import AssetEvent
    sell_je = s.get(AssetEvent, ev.event_id).journal_entry_id
got = lines_with_asset_detail(sell_je, pid)
check(got.get(fa_gl.account_id) == (D(0), D(600_000)) and got.get(accum_gl.account_id) == (D(50_000), D(0)),
      f"sale: asset and accumulated closed on the asset detail {got}")


# ۳) ماندهٔ هر دارایی در دفترِ کل به تفکیکِ تفصیلی
def gl_by_detail(account_id, detail_id):
    with new_session() as s:
        return s.scalar(select(func.coalesce(func.sum(JournalEntryLine.debit_amount_base - JournalEntryLine.credit_amount_base), 0))
                        .join(JournalEntryLineDetail, JournalEntryLineDetail.line_id == JournalEntryLine.line_id)
                        .where(JournalEntryLine.account_id == account_id, JournalEntryLineDetail.detail_account_id == detail_id))


check(gl_by_detail(fa_gl.account_id, did) == fa.get_asset(company_id, cnc).gross_cost == D(1_200_000)
      and gl_by_detail(accum_gl.account_id, did) == -fa.get_asset(company_id, cnc).accumulated_depreciation,
      "GL balance by asset detail equals asset ledger (cost and accumulated)")
check(gl_by_detail(fa_gl.account_id, pid) == 0 and gl_by_detail(accum_gl.account_id, pid) == 0, "sold asset: zero balance on its detail")

# ۴) دارایی‌هایِ قبل از R273: تفصیلی خودکار ساخته می‌شود؛ تفصیلیِ دستیِ هم‌کد به‌کار می‌رود
manual = dimensions_service.create_detail_account(company_id, fa_type, "OLD-2", "قدیمی ۲ (دستی)").detail_account_id
old1 = fa.create_asset(company_id, uid, F("OLD-1", name="قدیمی ۱"))
old2 = fa.create_asset(company_id, uid, F("OLD-2", name="قدیمی ۲"))
with new_session() as s:
    s.execute(text("UPDATE fa.assets SET detail_account_id = NULL WHERE asset_id IN (:a, :b)"), {"a": old1, "b": old2})
    s.commit()
check(fac.backfill_asset_details(company_id) == 2, "backfill fills assets without detail")
check(detail_of(old2)[0] == manual and detail_of(old2)[1].name == "قدیمی ۲", "existing manual detail with same code is linked and renamed")
check(detail_of(old1)[0] is not None, "old asset gets a detail")
check(fac.backfill_asset_details(company_id) == 0, "backfill is idempotent")

# ۵) تغییرِ نام دارایی ← نامِ تفصیلی
fa.update_asset(company_id, uid, cnc, F("CNC-001", name="ماشینِ CNC (بازسازی‌شده)"), reason="آزمون")
check(detail_of(cnc)[1].name == "ماشینِ CNC (بازسازی‌شده)", "asset rename syncs detail name")

# ۶) کدِ دارایی که به‌عنوانِ کدِ تفصیلی جا نمی‌شود (بیش از ۳۰ نویسه) ← کدِ عددیِ بعدی
x = fa.create_asset(company_id, uid, F("LONG-ASSET-CODE-0123456789-ABCDEFG", name="کدِ بلند"))
code = detail_of(x)[1].code
check(code.isdigit(), f"incompatible asset code -> generated numeric detail code {code}")

# ۷) سرعتِ بالا آمدن: صفحه‌ها در اولین بازشدن ساخته می‌شوند
from peecha.services import roles as roles_service
from peecha.ui import shell_window
roles_service.ensure_catalog()
t = time.time()
mw = shell_window.MainWindow()
elapsed = time.time() - t
built = len(dict.keys(mw._screens))
check(built < 15, f"only a few screens built at startup ({built}), MainWindow {elapsed:.1f}s")
check("warehouse_report_prd_orders" in mw._screens and not dict.__contains__(mw._screens, "warehouse_report_prd_orders"),
      "report screen registered but not built")
mw.open_screen("PRD_RPT_ORDERS")
check(dict.__contains__(mw._screens, "warehouse_report_prd_orders"), "report screen built on first open")
r1_ = mw._screens["purchase_report_" + __import__("peecha.services.purchase_reports", fromlist=["REPORTS"]).REPORTS[0].code.lower()]
r2_ = mw._screens["purchase_report_" + __import__("peecha.services.purchase_reports", fromlist=["REPORTS"]).REPORTS[1].code.lower()]
check(r1_ is not r2_ and r1_._def.code != r2_._def.code, "lazy report factories keep their own report code")

mw.resize(1200, 800)
mw.show()
app.processEvents()
was_active = app.activeWindow() is mw
mw._screens["commercial_document_purchase_invoice"]
app.processEvents()
check(not was_active or app.activeWindow() is mw, "building a document form lazily keeps the main window active (no stray button windows)")

fx.finish()
sys.stdout.flush()
os._exit(0)
