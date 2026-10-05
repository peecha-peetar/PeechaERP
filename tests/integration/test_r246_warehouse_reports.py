import os, sys, datetime, decimal, io
os.environ["PEECHA_DB_NAME"] = "peecha_test_r246_1"
os.environ["PEECHA_DB_USER"] = "peecha"
os.environ["PEECHA_DB_PASSWORD"] = "peecha"
os.environ["PEECHA_DB_HOST"] = "localhost"
os.environ["PEECHA_DB_PORT"] = "5432"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))

FAIL = False
def check(cond, msg):
    global FAIL
    if not cond:
        FAIL = True
        print("FAIL:", msg)
    else:
        print("OK:", msg)

from PySide6.QtWidgets import QApplication, QMessageBox
app = QApplication.instance() or QApplication([])
QMessageBox.warning = staticmethod(lambda *a, **k: None)
QMessageBox.information = staticmethod(lambda *a, **k: None)
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)

from peecha.db.schema_bootstrap import apply_pending_schema_files
from peecha.db.base import get_engine, new_session
apply_pending_schema_files(get_engine())
from peecha.services.bootstrap import bootstrap_system
from peecha import session as sess
user = bootstrap_system("admin", "مدیر سیستم", "secret123", "شرکت آزمایشی")
sess.current_user = user
from sqlalchemy import select
from peecha.db.models.security import UserCompany
from peecha.db.models.core import Company
with new_session() as s:
    uc = s.scalar(select(UserCompany).where(UserCompany.user_id == user.user_id))
    company = s.get(Company, uc.company_id)
company_id = company.company_id
sess.current_company = company

from peecha.services import fiscal_years as fiscal_years_service
fiscal_years_service.create_fiscal_year_for_date(company_id, 1, 1, datetime.date.today())
from peecha.services import chart_of_accounts as coa_service
from peecha.services import inventory_catalog as catalog_service
from peecha.services import inventory_locations as locations_service
from peecha.services import commercial_pricing as pricing_service
from peecha.services import commercial_settings as csettings_service
from peecha.services import commercial_partners as partners_service
from peecha.services import inventory_engine as engine_service
from peecha.services import inventory_documents as inv_documents_service
from peecha.services import commercial_documents as documents_service
from peecha.services import detail_dimensions as dimensions_service

lang_id = company.default_language_id
A = lambda code, name, nature, typ, perm, post, parent=None: coa_service.create_account(company_id, code, name, nature, typ, perm, post, lang_id, parent_account_id=parent)
g1 = A("1", "دارایی‌ها", "DEBIT", "ASSET", "PERMANENT", False)
k1 = A("11", "موجودیِ نقد", "DEBIT", "ASSET", "PERMANENT", False, g1.account_id)
cash_gl = A("101", "صندوق", "DEBIT", "ASSET", "PERMANENT", True, k1.account_id)
k2 = A("13", "دریافتنی‌ها", "DEBIT", "ASSET", "PERMANENT", False, g1.account_id)
ar_gl = A("1304", "دریافتنیِ مشتریان", "DEBIT", "ASSET", "PERMANENT", True, k2.account_id)
k3 = A("12", "موجودیِ انبار", "DEBIT", "ASSET", "PERMANENT", False, g1.account_id)
inv_gl = A("121", "موجودیِ کالا", "DEBIT", "ASSET", "PERMANENT", True, k3.account_id)
g2 = A("4", "درآمدها", "CREDIT", "REVENUE", "TEMPORARY", False)
k4 = A("41", "درآمدِ عملیاتی", "CREDIT", "REVENUE", "TEMPORARY", False, g2.account_id)
rev_gl = A("411", "فروش", "CREDIT", "REVENUE", "TEMPORARY", True, k4.account_id)
discount_gl = A("412", "تخفیفِ فروش", "DEBIT", "REVENUE", "TEMPORARY", True, k4.account_id)
g4 = A("2", "بدهی‌ها", "CREDIT", "LIABILITY", "PERMANENT", False)
k7 = A("21", "بدهیِ مالياتی", "CREDIT", "LIABILITY", "PERMANENT", False, g4.account_id)
tax_gl = A("2101", "مالياتِ ارزش‌افزودهٔ فروش", "CREDIT", "LIABILITY", "PERMANENT", True, k7.account_id)
g3 = A("5", "هزینه‌ها", "DEBIT", "EXPENSE", "TEMPORARY", False)
k5 = A("51", "بهایِ تمام‌شده", "DEBIT", "EXPENSE", "TEMPORARY", False, g3.account_id)
cogs_gl = A("511", "بهایِ تمام‌شده", "DEBIT", "EXPENSE", "TEMPORARY", True, k5.account_id)
k6 = A("59", "سایر", "DEBIT", "EXPENSE", "TEMPORARY", False, g3.account_id)
adj_gl = A("599", "اصلاحِ موجودی", "DEBIT", "EXPENSE", "TEMPORARY", True, k6.account_id)
engine_service.set_account_mapping(company_id, "INVENTORY_ASSET", inv_gl.account_id)
engine_service.set_account_mapping(company_id, "CUSTOMER_RECEIVABLE", ar_gl.account_id)
engine_service.set_account_mapping(company_id, "COGS", cogs_gl.account_id)
engine_service.set_account_mapping(company_id, "INVENTORY_ADJUSTMENT_GAIN", adj_gl.account_id)
csettings_service.set_account_mapping(company_id, "SALES_REVENUE", rev_gl.account_id)
csettings_service.set_account_mapping(company_id, "SALES_DISCOUNT", discount_gl.account_id)
csettings_service.set_account_mapping(company_id, "SALES_TAX_PAYABLE", tax_gl.account_id)

from peecha.services import unit_conversion as uc
from peecha.services import stock_count as stock_count_service
from peecha.services import commercial_settlements as settlements_service

D = decimal.Decimal
def raises(fn):
    try:
        fn()
    except ValueError:
        return True
    return False

k8 = A("32", "پرداختنی‌ها", "CREDIT", "LIABILITY", "PERMANENT", False, g4.account_id)
ap_gl = A("3201", "پرداختنیِ تامین‌کنندگان", "CREDIT", "LIABILITY", "PERMANENT", True, k8.account_id)
engine_service.set_account_mapping(company_id, "SUPPLIER_PAYABLE", ap_gl.account_id)
engine_service.set_account_mapping(company_id, "INVENTORY_ADJUSTMENT_LOSS", adj_gl.account_id)

from peecha.services import lot_tracking as lt
from peecha.services import commercial_consignment as consignment_service
from peecha.services import commercial_settlements as settlements_service
D = decimal.Decimal
TE = lt.TrackingEntry
def raises(fn):
    try:
        fn()
    except ValueError:
        return True
    return False

wh = locations_service.create_warehouse(company_id, "WH", "مرکزی", locations_service.WarehouseFields(is_default=True, allow_negative_stock=True))
wh2 = locations_service.create_warehouse(company_id, "WH2", "شعبه", locations_service.WarehouseFields(allow_negative_stock=True))
customer = partners_service.create_customer(company_id, "C-1", "فروشگاه", fast_track=True)
supplier = dimensions_service.create_supplier(company_id, "S1", "تامین‌کنندهٔ یک")
supplier2 = dimensions_service.create_supplier(company_id, "S2", "تامین‌کنندهٔ دو")
pcs = catalog_service.create_uom(company_id, "PCS", "عدد", "COUNT", decimal_places=0)
med = catalog_service.create_item(company_id, "M-1", "دارو", catalog_service.ItemFields(
    item_kind_code="GOOD", base_uom_id=pcs, track_batch=True, track_expiry=True))
phone = catalog_service.create_item(company_id, "P-1", "گوشی", catalog_service.ItemFields(
    item_kind_code="GOOD", base_uom_id=pcs, track_serial=True))
plain = catalog_service.create_item(company_id, "N-1", "پارچه", catalog_service.ItemFields(item_kind_code="GOOD", base_uom_id=pcs))
today = datetime.date.today()

def bal(item_id, warehouse_id=None, **kw):
    return lt.list_lot_balances(company_id, item_id=item_id, warehouse_id=warehouse_id, **kw)

# =====================================================================
# R246: گزارش‌ها و تحلیلِ انبار
# =====================================================================
import dataclasses
from peecha.services import purchase_reports as pr
from peecha.services import warehouse_reports as wr
from peecha.services import warehouse_dashboard as wd
from peecha.services import stock_count as count_service
from peecha.services import procurement_masters as masters
from peecha.db.models.inventory import StockBalance
from sqlalchemy import func as sa_func, text
from peecha import nav_catalog

cat_a = catalog_service.create_category(company_id, "CA", "ابزار")
brand = catalog_service.create_brand(company_id, "BR", "برندِ یک")
g1 = catalog_service.create_item(company_id, "G-1", "پیچ‌گوشتی", catalog_service.ItemFields(
    item_kind_code="GOOD", base_uom_id=pcs, category_id=cat_a, brand_id=brand))
g2 = catalog_service.create_item(company_id, "G-2", "انبردست", catalog_service.ItemFields(item_kind_code="GOOD", base_uom_id=pcs, category_id=cat_a))
wq = locations_service.create_warehouse(company_id, "WQ", "قرنطینه", locations_service.WarehouseFields(warehouse_type_code="QUARANTINE"))
d60, d20, d10 = today - datetime.timedelta(days=60), today - datetime.timedelta(days=20), today - datetime.timedelta(days=10)

def stock_doc(doc_type, item_id, qty, when, src=None, dst=None, cost=None, tracking=None):
    doc = inv_documents_service.create_stock_document(company_id, user.user_id, doc_type, when, inv_documents_service.DocumentHeaderFields(
        source_warehouse_id=src, destination_warehouse_id=dst, counterparty_detail_account_id=supplier if doc_type == "RECEIPT" else None))
    line = inv_documents_service.add_line(doc, company_id, inv_documents_service.LineFields(
        item_id=item_id, uom_id=pcs, quantity=D(qty), quantity_base=D(qty), unit_cost=D(cost) if cost else None))
    if tracking:
        lt.set_line_tracking(company_id, tracking, stock_line_id=line)
    inv_documents_service.confirm_stock_document(doc, company_id)
    inv_documents_service.post_stock_document(doc, company_id, user.user_id)
    return doc

stock_doc("RECEIPT", g1, 100, d60, dst=wh, cost=1000)
stock_doc("RECEIPT", g1, 50, d20, dst=wh, cost=1200)
issue_g1 = stock_doc("ISSUE", g1, 30, d10, src=wh)
transfer = stock_doc("TRANSFER", g1, 10, today, src=wh, dst=wq)
stock_doc("RECEIPT", g2, 20, today, dst=wh, cost=500)
neg_issue = stock_doc("ISSUE", g2, 25, today, src=wh)
stock_doc("RECEIPT", med, 30, today, dst=wh, cost=800, tracking=[
    TE(D(20), batch_no="B-EARLY", expiry_date=today + datetime.timedelta(days=20)),
    TE(D(10), batch_no="B-LATE", expiry_date=today + datetime.timedelta(days=300))])
stock_doc("ISSUE", med, 5, today, src=wh)
masters.save_reorder_policy(company_id, masters.PolicyFields(item_id=g2, warehouse_id=wh, min_qty=D(10), reorder_point_qty=D(15), max_qty=D(40)))
count_id = count_service.create_count_session(company_id, wh, user.user_id)
count_service.record_count(count_id, company_id, g1, pcs, D(100))

F = pr.PurchaseFilters(today - datetime.timedelta(days=90), today, side="INVENTORY")
def run(code, **kw):
    options = kw.pop("options", {})
    return pr.run_report(company_id, code, dataclasses.replace(F, options=options, **kw))
def rows_by(result, *headers):
    idx = [[h for h, _k in result.columns].index(h) for h in headers]
    return [tuple(r[i] for i in idx) for r in result.rows]
label = lambda item_id: next(f"{i.code} — {i.name}" for i in catalog_service.list_items(company_id) if i.item_id == item_id)  # noqa: E731
WH, WQ = "WH — مرکزی", "WQ — قرنطینه"

# --- ۱) موجودی -----------------------------------------------------------------
on_hand = run("STOCK_ON_HAND", options={"state": "ALL"})
oh = {(r[0], r[4]): r for r in on_hand.rows}
check(oh[("G-1", WH)][6] == 110 and oh[("G-1", WQ)][6] == 10 and oh[("G-1", WQ)][9] == 10 and oh[("G-1", WH)][9] == 0,
      "موجودیِ لحظه‌ای: ۱۱۰ در مرکزی و ۱۰ در قرنطینه (ستونِ قرنطینه)")
with new_session() as s:
    balance_value = s.scalar(select(sa_func.sum(StockBalance.total_value)).where(StockBalance.company_id == company_id))
check(on_hand.footer()[13] == balance_value, f"ارزشِ موجودی = جمعِ ماندهٔ سیستم ({on_hand.footer()[13]} / {balance_value})")
past = run("STOCK_ON_HAND", date_to=today - datetime.timedelta(days=30))
check(rows_by(past, "کدِ کالا", "موجودی") == [("G-1", 100)], "موجودی در تاریخِ گذشته از دفترِ انبار (۱۰۰)")
check(all(r[0] == "G-1" for r in run("STOCK_ON_HAND", brand_id=brand).rows), "فیلترِ برند")
check({r[0] for r in run("STOCK_ON_HAND", category_id=cat_a).rows} == {"G-1", "G-2"}, "فیلترِ گروهِ کالا")
check(not run("STOCK_ON_HAND", warehouse_id=wq).rows[1:] and run("STOCK_ON_HAND", warehouse_id=wq).rows[0][0] == "G-1", "فیلترِ انبار")
neg = run("NEGATIVE_STOCK")
check(len(neg.rows) == 1 and neg.rows[0][2] == -5 and neg.refs[0] == (neg_issue, "STOCK:ISSUE"),
      f"موجودیِ منفی با Drill-down به حوالهٔ ایجادکننده (got {neg.rows}, {neg.refs})")
zero = run("ZERO_STOCK")
check({r[0].split(" — ")[0] for r in zero.rows} >= {"N-1"} and "G-1 — پیچ‌گوشتی" not in [r[0] for r in zero.rows], "کالاهایِ بدونِ موجودی")
q = run("QUARANTINE_STOCK")
check(len(q.rows) == 1 and q.rows[0][4] == "انبارِ قرنطینه" and q.refs[0] == (transfer, "STOCK:TRANSFER"), "قرنطینه با دلیل و سندِ ورود")
free = {(r[0], r[1]): r for r in run("FREE_STOCK").rows}
check(free[(label(g1), WQ)][5] == 0 and free[(label(g1), WH)][5] == 110, "آزاد: موجودیِ قرنطینه قابلِ استفاده نیست")
byw = run("STOCK_BY_WAREHOUSE")
check(wr.WAREHOUSE_REPORTS_BY_CODE["STOCK_BY_WAREHOUSE"].default_group == "انبار" and byw.columns[0][0] == "انبار", "انبار ← گروه ← کالا")

# --- ۲) کارتکس و گردش -------------------------------------------------------------
card = run("STOCK_CARD", item_id=g1, warehouse_id=wh, options={"view": "SUMMARY"})
summary = {r[0]: r[2] for r in card.rows}
check(summary["موجودیِ اولِ دوره"] == 0 and summary["رسیدِ خرید/ورود"] == 150 and summary["حواله/مصرف"] == 30
      and summary["انتقالِ خروجی"] == 10 and summary["موجودیِ پایانِ دوره"] == 110, f"کارتکس: ۰ + ۱۵۰ − ۳۰ − ۱۰ = ۱۱۰ (got {summary})")
detail = run("STOCK_CARD", item_id=g1, warehouse_id=wh, date_from=d20)
check(detail.rows[0][3] == "ماندهٔ اولِ دوره" and detail.rows[0][7] == 100 and detail.rows[-1][7] == 110
      and all(ref and ref[1].startswith("STOCK:") for ref in detail.refs[1:]), "ریزِ کارتکس: مانده از اولِ بازه و ارجاع به سند")
check(raises(lambda: run("STOCK_CARD")), "کارتکس بدونِ کالا پیامِ راهنما می‌دهد")
mv = run("ITEM_MOVEMENT", item_id=g1, options={"period": "DAY"})
check(sum(r[1] for r in mv.rows) == 160 and sum(r[2] for r in mv.rows) == 40, "گردشِ روزانه (ورود ۱۶۰ با انتقالِ ورودی، خروج ۴۰)")
check(len(run("ITEM_MOVEMENT", options={"period": "YEAR", "doc_type": "TRANSFER"}).rows) >= 1, "فیلترِ نوعِ سند در گردش")

# --- ۳) ارزش، سن، تحلیل ----------------------------------------------------------
val = run("VALUATION", options={"by": "CATEGORY"})
check(sum(r[3] for r in val.rows) == balance_value, "ارزشِ موجودی به تفکیکِ گروه = کل")
aging = {(r[0], r[1]): r for r in run("STOCK_AGING").rows}
a = aging[(label(g1), WH)]
check(a[5] == 50 and a[6] == 60 and sum(a[5:11]) == 110, f"سنِ موجودی: ۵۰ در ۰–۳۰ و ۶۰ در ۳۱–۶۰ (got {a[5:11]})")
abc = run("ABC")
check([(r[0], r[6]) for r in abc.rows] == [(label(g1), "A"), (label(g2), "A"), (label(med), "B")], f"ABC بر اساسِ ارزشِ مصرف (got {[(r[0], r[6]) for r in abc.rows]})")
check(len(run("ABC_XYZ").rows) == 3, "ماتریسِ ABC-XYZ")
reorder = run("REORDER")
check(rows_by(reorder, "کالا", "آزاد", "نقطهٔ سفارش", "مقدارِ پیشنهادی") == [(label(g2), -5, 15, 45)], "نقطهٔ سفارش و مقدارِ پیشنهادی (۴۰ − (−۵))")
check(any(r[0] == label(g1) for r in run("DEAD_STOCK", date_from=d10 + datetime.timedelta(days=1)).rows), "راکد: بدونِ خروج در بازه")
cover = {(r[0], r[1]): r for r in run("STOCK_COVERAGE").rows}
check(cover[(label(g1), WH)][5] == int(D(110) / (D(30) / 91)), "پوششِ موجودی (روز)")

# --- ۴) شمارش، بچ، انقضا، عملیات ------------------------------------------------
var = run("VARIANCE")
check(len(var.rows) == 1 and var.rows[0][6] == -10 and var.rows[0][7] < 0, f"مغایرت: سیستم ۱۱۰، شمارش ۱۰۰ (got {var.rows})")
check(run("ACCURACY").rows[0][3] == 0 and len(run("STOCK_COUNTS", options={"view": "UNAPPROVED"}).rows) == 1, "دقتِ موجودی و شمارشِ تاییدنشده")
exp = run("EXPIRY", options={"window": "30"})
check(rows_by(exp, "بچ/لات", "مقدار") == [("B-EARLY", 15)], f"نزدیکِ انقضا (FEFO: ۵ عدد از بچِ زودانقضا رفت) (got {exp.rows})")
check({r[1] for r in run("BATCH_STOCK").rows} == {"B-EARLY", "B-LATE"}, "موجودیِ بچ")
check(len(run("TRANSFERS", options={"view": "POSTED"}).rows) == 1, "انتقال‌هایِ انجام‌شده")
check(len(run("RECEIVING", options={"view": "TODAY"}).rows) == 2, "رسیدهایِ امروز")
check(len(run("MD_WAREHOUSES").rows) >= 3 and run("MD_TRACKED").rows, "اطلاعاتِ پایه")
for r in wr.WAREHOUSE_REPORTS:
    try:
        res = run(r.code, item_id=g1 if r.code == "STOCK_CARD" else None)
        assert all(len(x) == len(res.columns) for x in res.rows)
    except Exception as exc:  # noqa: BLE001
        check(False, f"گزارشِ {r.code} خطا داد: {exc}")
check(sorted(e[0] for _g, _l, es in nav_catalog.WAREHOUSE_REPORT_MENU for e in es if not isinstance(e, dict))
      == sorted(r.code for r in wr.WAREHOUSE_REPORTS) and len(wr.WAREHOUSE_REPORTS) == 59, "۵۹ گزارشِ انبار در منو (R259: +۸ بهایِ تمام‌شده)")
with new_session() as s:
    idx = {r[0] for r in s.execute(text("select indexname from pg_indexes where indexname like 'ix_%stock_line' or indexname like 'ix_inv_stock_ledger_doc_line'"))}
check({"ix_inv_stock_ledger_doc_line", "ix_comm_document_lines_stock_line"} <= idx, "ایندکس‌هایِ گزارش ساخته شدند")

# --- ۵) داشبورد ---------------------------------------------------------------------
kpis, charts = wd.dashboard(company_id, F.date_from, today)
k = {x.code: x for x in kpis}
check(len(kpis) == 26 and k["VALUE"].value == balance_value and k["NEGATIVE"].value == 1 and k["NEAR_EXPIRY"].value == 1
      and k["QUARANTINE"].value == oh[("G-1", WQ)][13] and k["ROP"].value == 1 and k["COUNTS"].value == 1,
      f"شاخص‌هایِ داشبورد با گزارش‌ها یکی است ({[(x.code, x.value) for x in kpis]})")
check(len(charts) == 15 and charts["aging"]["series"]["ارزش"] and sum(charts["value_by_wh"]["series"]["ارزش"]) == balance_value,
      "۱۵ نمودار؛ جمعِ ارزشِ انبارها = ارزشِ کل")

# --- ۶) صفحه: فیلتر، گروه‌بندی، خروجی، Drill-down -----------------------------------
from peecha.ui.screens.purchase_reports import PurchaseReportScreen
calls = []
class FakeMain:
    def open_screen(self, code, then=None):
        calls.append(code)
        if then and code.startswith("INV_RPT_"):
            target = PurchaseReportScreen(code[len("INV_RPT_"):], None, side="INVENTORY")
            target.refresh()
            then(target)
            calls.append(target)
scr = PurchaseReportScreen("STOCK_BY_WAREHOUSE", FakeMain(), side="INVENTORY")
scr.refresh()
check(scr.group_combo.currentText() == "انبار", "گروه‌بندیِ پیش‌فرض: انبار")
check(scr.brand_combo.count() == 2 and scr.branch_combo.count() >= 1, "فیلترهایِ برند و شعبه در صفحه")
target = scr.inventory_drill_target([WH, "ابزار", label(g1)])
check(target == ("STOCK_CARD", {"item_id": g1, "warehouse_id": wh}), f"Drill-down: کالا و انبار ← کارتکس (got {target})")
neg_scr = PurchaseReportScreen("NEGATIVE_STOCK", FakeMain(), side="INVENTORY"); neg_scr.refresh()
neg_scr._open_row(0, 0)
check(calls and calls[-1] == "INV_ISSUE", f"Drill-down: موجودیِ منفی ← حوالهٔ انبار (got {calls})")
oh_scr = PurchaseReportScreen("STOCK_ON_HAND", FakeMain(), side="INVENTORY"); oh_scr.refresh()
oh_scr.item_combo.setCurrentIndex(oh_scr.item_combo.findData(g1)); oh_scr._reload()
headers, data, footer = oh_scr._export_data()
check(all(r[0] == "G-1" or r[0] == "G‑1" or "۱" in r[0] for r in data) and len(data) == 2, "فیلترِ کالا در صفحه")
check(("کالا", oh_scr.item_combo.currentText()) in oh_scr.extra_filters_summary(), "خروجی با همان فیلترهایِ صفحه (سربرگِ چاپ/اکسل)")
check("ارزشِ موجودی" in oh_scr.csv_text().splitlines()[0] and len(oh_scr.csv_text().splitlines()) == 4, "خروجیِ CSV با جمع")
oh_scr.set_hidden_columns({"برند"})
check("برند" not in oh_scr._export_data()[0], "ستون‌هایِ پنهان در خروجی نمی‌آیند")
oh_scr.set_hidden_columns(set())
from peecha.ui.screens.warehouse_dashboard import WarehouseDashboard
dash = WarehouseDashboard(FakeMain()); dash.refresh()
check(dash.cards["VALUE"]._title_label.text() == "ارزشِ کلِ موجودی" and len(dash.chart_views) == 15, "صفحهٔ داشبوردِ انبار")
dash._open_kpi("NEGATIVE")
check(calls[-2] == "INV_RPT_NEGATIVE_STOCK" and len(calls[-1]._result.rows) == 1, "کلیک رویِ شاخص ← گزارشِ مبدا")

print("RESULT:", "ALL PASS" if not FAIL else "SOME FAILED")
sys.exit(1 if FAIL else 0)
