import os, sys, datetime, decimal, io
os.environ["PEECHA_DB_NAME"] = "peecha_test_r247_1"
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
k1 = A("11", "موجودی نقد", "DEBIT", "ASSET", "PERMANENT", False, g1.account_id)
cash_gl = A("101", "صندوق", "DEBIT", "ASSET", "PERMANENT", True, k1.account_id)
k2 = A("13", "دریافتنی‌ها", "DEBIT", "ASSET", "PERMANENT", False, g1.account_id)
ar_gl = A("1304", "دریافتنی مشتریان", "DEBIT", "ASSET", "PERMANENT", True, k2.account_id)
k3 = A("12", "موجودی انبار", "DEBIT", "ASSET", "PERMANENT", False, g1.account_id)
inv_gl = A("121", "موجودی کالا", "DEBIT", "ASSET", "PERMANENT", True, k3.account_id)
g2 = A("4", "درآمدها", "CREDIT", "REVENUE", "TEMPORARY", False)
k4 = A("41", "درآمد عملیاتی", "CREDIT", "REVENUE", "TEMPORARY", False, g2.account_id)
rev_gl = A("411", "فروش", "CREDIT", "REVENUE", "TEMPORARY", True, k4.account_id)
discount_gl = A("412", "تخفیف فروش", "DEBIT", "REVENUE", "TEMPORARY", True, k4.account_id)
g4 = A("2", "بدهی‌ها", "CREDIT", "LIABILITY", "PERMANENT", False)
k7 = A("21", "بدهی مالیاتی", "CREDIT", "LIABILITY", "PERMANENT", False, g4.account_id)
tax_gl = A("2101", "مالیات ارزش‌افزودهٔ فروش", "CREDIT", "LIABILITY", "PERMANENT", True, k7.account_id)
g3 = A("5", "هزینه‌ها", "DEBIT", "EXPENSE", "TEMPORARY", False)
k5 = A("51", "بهای تمام‌شده", "DEBIT", "EXPENSE", "TEMPORARY", False, g3.account_id)
cogs_gl = A("511", "بهای تمام‌شده", "DEBIT", "EXPENSE", "TEMPORARY", True, k5.account_id)
k6 = A("59", "سایر", "DEBIT", "EXPENSE", "TEMPORARY", False, g3.account_id)
adj_gl = A("599", "اصلاح موجودی", "DEBIT", "EXPENSE", "TEMPORARY", True, k6.account_id)
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
ap_gl = A("3201", "پرداختنی تامین‌کنندگان", "CREDIT", "LIABILITY", "PERMANENT", True, k8.account_id)
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
brand = catalog_service.create_brand(company_id, "BR", "برند یک")
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

# =====================================================================
# R247: اجرایِ پس‌زمینه، صفحه‌بندی، مبنایِ ارزش، لاگِ اصلاحِ بها، ظرفیت، برنامهٔ شمارش، جانمایی/برداشت
# =====================================================================
from peecha.services import warehouse_operations as ops
from peecha.services import inventory_engine as engine_service
from peecha.ui.screens import purchase_reports as report_screens
from peecha.ui.screens.purchase_reports import PurchaseReportScreen
from peecha.db.models.inventory import CostAdjustmentLog
F = pr.PurchaseFilters(today - datetime.timedelta(days=90), today, side="INVENTORY")
def run(code, **kw):
    options = kw.pop("options", {})
    return pr.run_report(company_id, code, dataclasses.replace(F, options=options, **kw))
label = lambda item_id: next(f"{i.code} — {i.name}" for i in catalog_service.list_items(company_id) if i.item_id == item_id)  # noqa: E731
def bal_value(item_id=None, wid=None):
    with new_session() as s:
        q = select(sa_func.sum(StockBalance.total_value)).where(StockBalance.company_id == company_id)
        if item_id: q = q.where(StockBalance.item_id == item_id)
        if wid: q = q.where(StockBalance.warehouse_id == wid)
        return s.scalar(q)

# --- ۱) اجرایِ پس‌زمینه و صفحه‌بندی ------------------------------------------
sync = PurchaseReportScreen("STOCK_ON_HAND", None, side="INVENTORY"); sync.refresh()
report_screens.BACKGROUND_REPORTS = True
bg = PurchaseReportScreen("STOCK_ON_HAND", None, side="INVENTORY"); bg.refresh()
check(bg.busy_label.text() != "" and bg._workers, "گزارش در رشتهٔ پس‌زمینه اجرا می‌شود")
bg.wait_for_report()
check(bg._export_data()[1] == sync._export_data()[1] and bg.busy_label.text() == "", "نتیجهٔ پس‌زمینه با اجرای همگام یکی است")
before = bg._export_data()[1]
bg._on_worker_done(bg._generation - 1, None, ValueError("کهنه"))
check(bg._export_data()[1] == before, "نتیجهٔ اجرای کهنه (نسل قبل) نادیده گرفته می‌شود")
report_screens.BACKGROUND_REPORTS = False
sync.page_size_combo.setCurrentIndex(sync.page_size_combo.findData(100))
rows_all = len(sync._rows)
sync.page_size_combo.addItem("۱", 1); sync.page_size_combo.setCurrentIndex(sync.page_size_combo.count() - 1)
check(sync.table.rowCount() == 2 and "از" in sync.page_label.text() and sync.next_page_button.isEnabled(), "صفحه‌بندی: یک ردیف + جمع در هر صفحه")
sync._go_page(1)
check(sync._page_offset == 1 and sync.raw_row(0) == sync._result.rows[sync._row_raw[id(sync._rows[1])]], "صفحهٔ دوم و نگاشت ردیف")
check(len(sync._export_data()[1]) == rows_all, "خروجی همهٔ ردیف‌ها را دارد، نه فقط صفحهٔ جاری")

# --- ۲) مبنایِ ارزشِ کارتکس و لاگِ اصلاحِ بها -------------------------------
led = run("STOCK_CARD", item_id=g1, warehouse_id=wh, options={"basis": "LEDGER"})
check(led.rows[-1][11] == bal_value(g1, wh), f"کاردکس با مبنای دفتر انبار = ارزش ماندهٔ سیستم ({led.rows[-1][11]} / {bal_value(g1, wh)})")
res = engine_service.apply_purchase_cost_correction(g1, wh, None, company_id, D(50), D(100))
with new_session() as s:
    logs = list(s.scalars(select(CostAdjustmentLog).where(CostAdjustmentLog.item_id == g1)))
check(len(logs) == 1 and logs[0].inventory_value_delta == res.inventory_value_delta and logs[0].warehouse_id == wh,
      "اصلاح بها با تاریخ در inv.cost_adjustment_log ثبت شد")
pos = wr._ledger_position(company_id, today)
check(abs(pos[(g1, wh)][2] - bal_value(g1, wh)) <= D("0.05"), f"ارزش تاریخی (دفتر انبار + اصلاح) = مانده ({pos[(g1, wh)][2]} / {bal_value(g1, wh)})")
led2 = run("STOCK_CARD", item_id=g1, warehouse_id=wh, options={"basis": "LEDGER"})
check(led2.rows[-1][3] == "اصلاح بهای خرید (تعدیل ارزش)" and abs(led2.rows[-1][11] - bal_value(g1, wh)) <= D("0.05"),
      "ردیف اصلاح بها در کاردکس (مبنای حسابداری)")
check(run("VALUE_TREND").rows[-1][2] == sum((r[2] for r in wr._ledger_position(company_id, today).values()), D(0)), "روند ارزش با اصلاح بها")

# --- ۳) ظرفیت و برنامهٔ شمارش -----------------------------------------------
row = locations_service.get_warehouse(wh, company_id)
locations_service.update_warehouse(wh, company_id, row.code, row.name, True,
                                   dataclasses.replace(row.fields, capacity_weight_kg=D(1000), capacity_volume_m3=D(50)))
cap = {r[0]: r for r in run("CAPACITY").rows}
check(cap["WH — مرکزی"][1] == 1000 and cap["WH — مرکزی"][5] == 50, "ظرفیت وزنی/حجمی انبار غیر خودرو")
ops.save_plan(company_id, ops.PlanFields("P-G2", "انبردست ماهانه", wh, 30, item_id=g2))
ops.save_plan(company_id, ops.PlanFields("P-G1", "پیچ‌گوشتی", wh, 30, item_id=g1))
check(raises(lambda: ops.save_plan(company_id, ops.PlanFields("p-g1", "تکراری", wh, 30))), "کد تکراری برنامه رد شد")
check(raises(lambda: ops.save_plan(company_id, ops.PlanFields("X", "دو دامنه", wh, 30, item_id=g1, category_id=cat_a))), "دامنهٔ دوگانه رد شد")
check(raises(lambda: ops.save_plan(company_id, ops.PlanFields("Y", "صفر", wh, 0))), "تواتر صفر رد شد")
due = {r[2]: r for r in run("CYCLE_COUNT_DUE").rows}
check(label(g2) in due and due[label(g2)][7] == "هرگز شمرده نشده" and label(g1) not in due, f"سررسید شمارش (پیچ‌گوشتی امروز شمرده شد) (got {list(due)})")
check(ops.due_counts(company_id, today + datetime.timedelta(days=31))[0].item_id in (g1, g2) and
      len(ops.due_counts(company_id, today + datetime.timedelta(days=31))) == 2, "پس از ۳۰ روز هر دو سررسید")

# --- ۴) جانمایی و برداشت ----------------------------------------------------
a01 = locations_service.create_bin_location(wh, "A-01", "قفسهٔ الف")
from peecha.db.models.inventory import StockDocumentLine as SDL, StockDocument as SD
with new_session() as s_:
    g2_doc = s_.scalar(select(SDL.stock_document_id).join(SD, SD.stock_document_id == SDL.stock_document_id)
                       .where(SDL.item_id == g2, SD.document_type_code == "RECEIPT"))
g2_receipt = next(s for s in ops.putaway_sources(company_id) if s.key == ("STOCK", g2_doc))
ids = ops.generate_tasks(company_id, "PUTAWAY", g2_receipt.key, user.user_id)
check(len(ids) == 1 and ops.generate_tasks(company_id, "PUTAWAY", g2_receipt.key, user.user_id) == [], "وظیفهٔ جانمایی یک‌بار ساخته می‌شود")
check(any(r[0] == label(g2) for r in run("UNLOCATED_STOCK").rows), "دریافت‌شده ولی جانمایی‌نشده")
total_before = bal_value()
ops.start_task(ids[0], company_id, user.user_id)
check(raises(lambda: ops.complete_putaway(ids[0], company_id, user.user_id, locations_service.get_default_bin_location(wq).bin_location_id)),
      "جانمایی به محل انبار دیگر رد شد")
doc_id = ops.complete_putaway(ids[0], company_id, user.user_id, a01)
bins = {(r[1].split(" — ")[0], r[3]): r[4] for r in run("BIN_STOCK").rows}
check(doc_id and bins.get(("A-01", label(g2))) == 20 and bins.get(("GENERAL", label(g2))) == -25 and bal_value() == total_before,
      f"جانمایی با سند انتقال: ۲۰ عدد به A-01، ارزش کل ثابت (got {bins})")
pa = run("PUTAWAY", options={"view": "DONE"}).rows
check(len(pa) == 1 and pa[0][6].startswith("A-01") and pa[0][11] == "مدیر سیستم", "گزارش جانمایی با محل و اپراتور")
issue_draft = inv_documents_service.create_stock_document(company_id, user.user_id, "ISSUE", today,
    inv_documents_service.DocumentHeaderFields(source_warehouse_id=wh))
inv_documents_service.add_line(issue_draft, company_id, inv_documents_service.LineFields(item_id=g1, uom_id=pcs, quantity=D(5), quantity_base=D(5)))
check(any(s.key == ("STOCK", issue_draft) for s in ops.pick_sources(company_id)), "حوالهٔ ثبت‌نشده منبع برداشت است")
pick = ops.generate_tasks(company_id, "PICK", ("STOCK", issue_draft), user.user_id)
ops.start_task(pick[0], company_id, user.user_id)
ops.complete_pick(pick[0], company_id, user.user_id, D(4))
pk = run("PICKING", options={"view": "PARTIAL"}).rows
check(len(pk) == 1 and pk[0][5] == 4 and pk[0][6] == 80, f"برداشت ناقص با دقت ۸۰٪ (got {pk})")
check(raises(lambda: ops.complete_pick(pick[0], company_id, user.user_id, D(5))), "وظیفهٔ انجام‌شده دوباره تکمیل نمی‌شود")
perf = {r[0]: r for r in run("WMS_PERFORMANCE").rows}
check(perf["برداشت"][2] == 1 and perf["برداشت"][5] == 0 and perf["جانمایی"][2] == 1, "عملکرد اپراتور")
kpis, _charts = wd.dashboard(company_id, F.date_from, today)
check(len(kpis) == 26 and {k.code for k in kpis} >= {"PUTAWAY", "PICKS", "COUNT_DUE"}, "شاخص‌های تازهٔ داشبورد")

# --- ۵) صفحهٔ عملیات -----------------------------------------------------------
from peecha.ui.screens.warehouse_operations import WarehouseOperationsScreen
QMessageBox.warning = staticmethod(lambda *a, **k: None)
screen = WarehouseOperationsScreen(); screen.refresh()
check(screen.plans_tab.table.rowCount() == 2 and screen.tasks_tab.table.rowCount() == 1, "صفحهٔ عملیات: برنامه‌ها و وظایف")
screen.plans_tab.code_field.setText("P-ALL"); screen.plans_tab.name_field.setText("همهٔ کالا")
screen.plans_tab.frequency_spin.setValue(90)
check(screen.plans_tab.save() and len(ops.list_plans(company_id)) == 3, "ذخیرهٔ برنامه از صفحه")
screen.tasks_tab.type_combo.setCurrentIndex(screen.tasks_tab.type_combo.findData("PICK"))
check(screen.tasks_tab.table.rowCount() == 1, "فهرست وظایف برداشت در صفحه")

print("RESULT:", "ALL PASS" if not FAIL else "SOME FAILED")
sys.exit(1 if FAIL else 0)
