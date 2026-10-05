import os, sys, datetime, decimal, io
os.environ["PEECHA_DB_NAME"] = "peecha_test_r259_1"
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
from sqlalchemy import select, text
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
from peecha.services import warehouse_locations as wl
from peecha.services import warehouse_operations as ops
from peecha.services import users as users_service
from peecha.services import roles as roles_service
from peecha.db.models.inventory import BinLocation, Warehouse

today = datetime.date.today()
pcs = catalog_service.create_uom(company_id, "PCS", "عدد", "COUNT", decimal_places=0)
supplier = dimensions_service.create_supplier(company_id, "S1", "تامین‌کننده")
g1 = catalog_service.create_item(company_id, "G-1", "پیچ‌گوشتی", catalog_service.ItemFields(
    item_kind_code="GOOD", base_uom_id=pcs, barcode="6260000000011", weight_kg=D(2)))
g2 = catalog_service.create_item(company_id, "G-2", "انبردست", catalog_service.ItemFields(item_kind_code="GOOD", base_uom_id=pcs))

# =====================================================================
# R249: بررسیِ محل در اسناد، سازگاری، رزرو، تأمینِ مجدد، سه‌بعدی، API
# =====================================================================
from sqlalchemy import func as sa_func
from peecha.db.models.inventory import WarehouseTask, StockDocument as SD
from peecha.db.models.audit import ActivityLog
LF = wl.LocationFields
item = g1
wh = locations_service.create_warehouse(company_id, "WH01", "مرکزی", locations_service.WarehouseFields(is_default=True, allow_negative_stock=True))
general = locations_service.get_default_bin_location(wh).bin_location_id
zb = wl.create_location(company_id, wh, "AREA", "Z01", fields=LF(location_type_code="BULK"))
zp = wl.create_location(company_id, wh, "AREA", "Z02", fields=LF(location_type_code="PICK_FACE"))
zc = wl.create_location(company_id, wh, "AREA", "Z03", fields=LF(location_type_code="COLD", temperature_min_c=D(2), temperature_max_c=D(6)))
zh = wl.create_location(company_id, wh, "AREA", "Z04", fields=LF(allows_hazardous=True))
zs = wl.create_location(company_id, wh, "AREA", "Z09", fields=LF(location_type_code="SHIPPING"))
def rack_with_bins(zone, rack_code):
    r = wl.create_location(company_id, wh, "RACK", rack_code, zone)
    shelves = [wl.create_location(company_id, wh, "SHELF", f"L0{i}", r) for i in (1, 2)]
    return r, [wl.create_location(company_id, wh, "BIN", f"B0{i}", shelves[0], LF(max_weight_kg=D(100))) for i in (1, 2)]
rb, (bulk1, bulk2) = rack_with_bins(zb, "R01")
rp, (pick1, pick2) = rack_with_bins(zp, "R02")
rc, (cold1, _c2) = rack_with_bins(zc, "R03")
rh, (haz1, _h2) = rack_with_bins(zh, "R04")
milk = catalog_service.create_item(company_id, "M-1", "شیر", catalog_service.ItemFields(item_kind_code="GOOD", base_uom_id=pcs))
acid = catalog_service.create_item(company_id, "A-1", "اسید", catalog_service.ItemFields(item_kind_code="GOOD", base_uom_id=pcs))

def draft(doc_type, item_id, qty, bin_id=None, dst_bin=None, src=None, dst=None):
    doc = inv_documents_service.create_stock_document(company_id, user.user_id, doc_type, today, inv_documents_service.DocumentHeaderFields(
        source_warehouse_id=src, destination_warehouse_id=dst, counterparty_detail_account_id=supplier if doc_type == "RECEIPT" else None))
    inv_documents_service.add_line(doc, company_id, inv_documents_service.LineFields(
        item_id=item_id, uom_id=pcs, quantity=D(qty), quantity_base=D(qty), unit_cost=D(1000) if doc_type == "RECEIPT" else None,
        bin_location_id=bin_id, destination_bin_location_id=dst_bin))
    return doc
def post(doc):
    inv_documents_service.confirm_stock_document(doc, company_id)
    inv_documents_service.post_stock_document(doc, company_id, user.user_id)
    return doc
post(draft("RECEIPT", item, 80, bin_id=bulk1, dst=wh))
post(draft("RECEIPT", item, 5, bin_id=pick1, dst=wh))
post(draft("RECEIPT", milk, 10, dst=wh))
post(draft("RECEIPT", acid, 10, dst=wh))


# =====================================================================
# R259: ارزش‌گذاری در تاریخ، گزارش‌ها، داشبورد، اطلاعاتِ بهایِ کالا، بهایِ جایگزینی، دسترسی‌ها
# =====================================================================
from peecha.db.models.inventory import CostLayer, StockBalance
from peecha.db.models.accounting import JournalEntryLine
from peecha.services.costing import valuation as cv, reports as cr, dashboard as cd, replacement as crep
from peecha.services.purchase_reports import PurchaseFilters
from peecha.services import warehouse_reports as wr
from peecha import numerals

def new_item(code, method):
    return catalog_service.create_item(company_id, code, code, catalog_service.ItemFields(
        item_kind_code="GOOD", base_uom_id=pcs, costing_method_code=method))
def mk(doc_type, item_id, qty, cost=None, src=None, dst=None, date=None):
    doc = inv_documents_service.create_stock_document(company_id, user.user_id, doc_type, date or today, inv_documents_service.DocumentHeaderFields(
        source_warehouse_id=src, destination_warehouse_id=dst,
        counterparty_detail_account_id=supplier if doc_type == "RECEIPT" else None))
    line = inv_documents_service.add_line(doc, company_id, inv_documents_service.LineFields(
        item_id=item_id, uom_id=pcs, quantity=D(qty), quantity_base=D(qty), unit_cost=D(cost) if cost is not None else None))
    post(doc)
    return doc, line

d0 = today - datetime.timedelta(days=20)
d1 = today - datetime.timedelta(days=10)
fi = new_item("V-FIFO", "FIFO")
mk("RECEIPT", fi, 100, 100, dst=wh, date=d0)
mk("RECEIPT", fi, 100, 200, dst=wh, date=d1)
mk("ISSUE", fi, 150, src=wh)
li = new_item("V-LIFO", "LIFO")
mk("RECEIPT", li, 10, 50, dst=wh, date=d0)
mk("RECEIPT", li, 10, 80, dst=wh, date=d1)
mk("ISSUE", li, 5, src=wh)

# --- ۱) هم‌ترازیِ مانده با لایه‌ها (رفعِ مغایرتِ قبلی: میانگینِ ماندهٔ FIFO پس از خروج به‌روز نمی‌شد) ---------
def bal(item_id):
    with new_session() as s:
        return s.execute(select(sa_func.sum(StockBalance.quantity_on_hand), sa_func.sum(StockBalance.total_value)).where(
            StockBalance.item_id == item_id)).one()
def layer_value(item_id):
    with new_session() as s:
        return s.scalar(select(sa_func.sum(CostLayer.remaining_quantity * CostLayer.unit_cost)).where(CostLayer.item_id == item_id))
q, v = bal(fi)
check(q == 50 and abs(v - D(10000)) < D("0.01") and abs(layer_value(fi) - D(10000)) < D("0.01"),
      f"FIFO: ارزشِ مانده = ارزشِ لایه‌ها = ۵۰×۲۰۰ ({v})")
q, v = bal(li)
check(q == 15 and abs(v - layer_value(li)) < D("0.01") and abs(v - D(10 * 50 + 5 * 80)) < D("0.01"), f"LIFO: ارزشِ مانده = لایه‌ها ({v})")

# --- ۲) ارزش‌گذاری در تاریخ (snapshot) ----------------------------------------------------
pos = cv.positions(company_id, d0, item_id=fi)
check(pos[(fi, wh)] == (D(100), D("10000.00")), "ارزش در تاریخِ رسیدِ اول: ۱۰۰ × ۱۰۰")
pos = cv.positions(company_id, d1, item_id=fi)
check(pos[(fi, wh)] == (D(200), D("30000.00")), "ارزش در تاریخِ رسیدِ دوم: ۳۰٬۰۰۰")
pos = cv.positions(company_id, today, item_id=fi)
check(pos[(fi, wh)] == (D(50), D("10000.00")), "ارزشِ امروز: ۵۰ × ۲۰۰")
total_now = sum((v[1] for v in cv.positions(company_id).values()), D(0))
with new_session() as s:
    gl = s.scalar(select(sa_func.sum(JournalEntryLine.debit_amount_base - JournalEntryLine.credit_amount_base)).where(
        JournalEntryLine.account_id == inv_gl.account_id))
check(abs(total_now - gl) < D("0.05"), f"ارزش‌گذاری = ماندهٔ حسابِ موجودی در دفترِ کل ({total_now} / {gl})")

# --- ۳) اطلاعاتِ بهایِ کالا و تاریخچه --------------------------------------------------------
info = cv.item_cost_info(company_id, fi)
check(info.method == "FIFO" and info.current_cost == 200 and info.average_cost == 200 and info.last_purchase_cost == 200
      and info.quantity == 50 and info.inventory_value == D("10000.00"), "اطلاعاتِ بها: روش، بهایِ جاری، میانگین، آخرین خرید")
info = cv.item_cost_info(company_id, li)
check(info.current_cost == 80 and info.last_purchase_cost == 80, "LIFO: بهایِ جاری = لایهٔ بعدیِ خروج (۸۰، ماندهٔ لایهٔ آخر)")
hist = cv.cost_history(company_id, fi)
check([(h.direction, round(h.unit_cost, 2)) for h in hist] == [("IN", 100), ("IN", 200), ("OUT", D("133.33"))],
      f"تاریخچهٔ بها به ترتیبِ زمان ({[(h.direction, h.unit_cost) for h in hist]})")

# --- ۴) بهایِ جایگزینی (ثبتِ دستی + audit) ---------------------------------------------------
crep.set_replacement_cost(company_id, fi, D(260), today, note="قیمتِ بازار", user_id=user.user_id)
check(cv.item_cost_info(company_id, fi).replacement_cost == 260, "بهایِ جایگزینیِ دستی در اطلاعاتِ کالا")

# --- ۵) همهٔ گزارش‌ها اجرا می‌شوند و منو/ثبت دارند ---------------------------------------------
codes = [r.code for r in cr.COSTING_REPORTS]
check(len(codes) == 8 and all(c in wr.WAREHOUSE_REPORTS_BY_CODE for c in codes), "۸ گزارشِ بهایِ تمام‌شده در فهرستِ گزارش‌هایِ انبار")
f = PurchaseFilters(today - datetime.timedelta(days=60), today, side="INVENTORY")
results = {}
for r in cr.COSTING_REPORTS:
    try:
        results[r.code] = r.func(company_id, f)
        ok = True
    except Exception as exc:  # noqa: BLE001
        ok = False
        print("   ", r.code, exc)
    check(ok, f"گزارشِ {r.code} اجرا شد")
val = results["COST_VALUATION"]
check(any(numerals.to_persian_digits("V-FIFO") in str(row[0]) or "V-FIFO" in str(row[0]) for row in val.rows), "ارزش‌گذاری: ردیفِ کالا")
lay = results["COST_LAYERS"]
check(len([row for row in lay.rows if "V-FIFO" in str(row[0])]) == 1, "لایه‌ها: فقط لایهٔ باز (پیش‌فرض)")
f_all = PurchaseFilters(f.date_from, f.date_to, side="INVENTORY", options={"status": "ALL"})
check(len([row for row in cr.cost_layers(company_id, f_all).rows if "V-FIFO" in str(row[0])]) == 2, "لایه‌ها: همه")
alloc = results["COST_ALLOCATION"]
check(len([row for row in alloc.rows if "V-FIFO" in str(row)]) == 2, "تخصیص: دو ردیف برایِ خروجِ FIFO")
rep = results["COST_REPLACEMENT"]
check(any("V-FIFO" in str(row[0]) and row[3] == 260 for row in rep.rows), "گزارشِ جایگزینی: ۲۶۰ برایِ V-FIFO")
lot = cr.cost_valuation(company_id, PurchaseFilters(f.date_from, f.date_to, side="INVENTORY", options={"by": "LOT"}))
check(len(lot.rows) >= 2, "ارزش‌گذاری به تفکیکِ بچ/سریال اجرا شد")

# --- ۶) داشبورد ------------------------------------------------------------------------
kpis, charts = cd.dashboard(company_id, f.date_from, f.date_to)
k = {x.code: x for x in kpis}
check(set(k) == {"VALUE", "COGS", "AVG", "VARIANCE", "REPLACEMENT", "LAYERS", "PENDING"}, "داشبورد: ۷ شاخص")
check(abs(k["VALUE"].value - total_now) < D("0.05"), "داشبورد: ارزشِ موجودی = ارزش‌گذاری")
check(set(charts) == {c[0] for c in cd.CHART_TITLES}, "داشبورد: ۵ نمودار")
check(all(x.report_code in wr.WAREHOUSE_REPORTS_BY_CODE for x in kpis), "هر شاخص به گزارشِ مبدأ وصل است")

# --- ۷) صفحه‌ها (دسکتاپ) ----------------------------------------------------------------
sess.current_user = user
from peecha.ui.screens import costing as costing_ui
dash = costing_ui.CostingDashboard()
dash.refresh() if hasattr(dash, "refresh") else dash.reload()
check(dash.cards["VALUE"]._title_label.text() == "ارزشِ موجودی", "صفحهٔ داشبوردِ بهایِ تمام‌شده")
settings_screen = costing_ui.CostingSettingsScreen()
settings_screen.refresh()
check(all(b.isEnabled() for b in settings_screen.tab.findChildren(costing_ui.QPushButton)), "تنظیمات: مدیر اجازهٔ ویرایش دارد")
rs = costing_ui.ReplacementCostScreen()
rs.refresh()
rs.item_combo.setCurrentIndex(rs.item_combo.findData(li))
check(rs.uom_combo.count() >= 1, "بهایِ جایگزینی: واحدهایِ کالا")
rs.cost_field.setValue(95)
rs.note_field.setText("آزمونِ صفحه")
check(rs.save() and crep.get_replacement_cost(company_id, li)[0] == 95, "ثبتِ بهایِ جایگزینی از صفحه")
check(rs.table.rowCount() == 2, "فهرستِ بهایِ جایگزینی")
from peecha.ui.screens.inventory_item_panel import ItemDetailPanel
panel = ItemDetailPanel(); panel.refresh(company_id)
panel.load(next(i for i in catalog_service.list_items(company_id) if i.item_id == fi))
check(panel.tabs.isTabVisible(panel.tab_indexes["cost"]) and panel.cost_history_table.rowCount() == 3
      and "FIFO" in panel.cost_labels["method_label"].text(), "فرمِ کالا: تبِ اطلاعاتِ بها")
check(numerals.to_persian_digits("260") in panel.cost_labels["replacement_cost"].text(), "فرمِ کالا: بهایِ جایگزینی")

# --- ۸) دسترسی‌ها ------------------------------------------------------------------------
forms = {fo.code for fo in roles_service.list_forms()}
check({"costing_dashboard", "costing_settings", "costing_replacement"} <= forms, "سه فرمِ بهایِ تمام‌شده در فهرستِ دسترسی‌ها")
clerk = users_service.create_user("clerk259", "انباردار", "secret123", None, company.default_language_id, False, [company_id], company_id)
sess.current_user = clerk
check(not costing_ui.can("costing_settings", "EDIT") and not costing_ui.can("costing_dashboard", "VIEW"), "کاربرِ بدونِ نقش: بدونِ دسترسی")
role = roles_service.create_role(company_id, "COSTVIEW", None)
fid = {fo.code: fo.form_id for fo in roles_service.list_forms()}
roles_service.set_role_permission(role.role_id, fid["costing_dashboard"], "VIEW", True)
roles_service.set_user_role(clerk.user_id, role.role_id, company_id, True)
check(costing_ui.can("costing_dashboard", "VIEW") and not costing_ui.can("costing_settings", "EDIT"), "نقش: مشاهده بله، ویرایشِ تنظیمات نه")
settings_screen.refresh()
check(not any(b.isEnabled() for b in settings_screen.tab.findChildren(costing_ui.QPushButton)), "تنظیمات: دکمه‌ها برایِ کاربرِ فاقدِ EDIT غیرفعال")
rs.refresh()
check(not rs.save_button.isEnabled(), "بهایِ جایگزینی: ثبت برایِ کاربرِ فاقدِ EDIT غیرفعال")
panel.load(next(i for i in catalog_service.list_items(company_id) if i.item_id == fi))
check(panel.tabs.isTabVisible(panel.tab_indexes["cost"]), "تبِ بها برایِ دارندهٔ VIEW داشبورد")
roles_service.set_role_permission(role.role_id, fid["costing_dashboard"], "VIEW", False)
panel.load(next(i for i in catalog_service.list_items(company_id) if i.item_id == fi))
check(not panel.tabs.isTabVisible(panel.tab_indexes["cost"]), "تبِ بها برایِ کاربرِ بدونِ دسترسی پنهان")
sess.current_user = user

print("RESULT:", "ALL PASS" if not FAIL else "SOME FAILED")
sys.exit(1 if FAIL else 0)
