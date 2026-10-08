import os, sys, datetime, decimal, io
os.environ["PEECHA_DB_NAME"] = "peecha_test_r260_1"
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
# R260: سندِ عقب‌دار، بازمحاسبه (لایه‌ای/میانگین/انتقال/در انتظار)، سندِ اصلاحی، دسترسی
# =====================================================================
from peecha.db.models.inventory import CostLayer, CostAllocation, StockBalance, StockLedger, CostRecalculationLine
from peecha.db.models.accounting import JournalEntryLine
from peecha.services.costing import valuation as cv, recalculation as rc

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
def days(n):
    return today - datetime.timedelta(days=n)
def allocs(line_id):
    with new_session() as s:
        return [(a.quantity_base.normalize(), a.unit_cost.normalize(), a.costing_status_code)
                for a in s.scalars(select(CostAllocation).where(CostAllocation.stock_document_line_id == line_id).order_by(CostAllocation.allocation_id))]
def gl(account_id):
    with new_session() as s:
        return s.scalar(select(sa_func.coalesce(sa_func.sum(JournalEntryLine.debit_amount_base - JournalEntryLine.credit_amount_base), 0))
                        .where(JournalEntryLine.account_id == account_id))
def item_value(item_id):
    return sum((v[1] for v in cv.positions(company_id, item_id=item_id).values()), D(0))
def bal_value(item_id):
    with new_session() as s:
        return s.scalar(select(sa_func.coalesce(sa_func.sum(StockBalance.total_value), 0)).where(StockBalance.item_id == item_id))
def consistent(label):
    total = sum((v[1] for v in cv.positions(company_id).values()), D(0))
    check(abs(total - gl(inv_gl.account_id)) < D("0.05"), f"{label}: ارزش‌گذاری = حساب موجودی ({total} / {gl(inv_gl.account_id)})")

# --- ۱) FIFO + رسیدِ عقب‌دار ------------------------------------------------------------------
f = new_item("R-FIFO", "FIFO")
mk("RECEIPT", f, 10, 100, dst=wh, date=days(10))
_, iss = mk("ISSUE", f, 5, src=wh, date=days(5))
check(allocs(iss) == [(D(5), D(100), "CALCULATED")], "FIFO: خروج اولیه با ۱۰۰")
mk("RECEIPT", f, 10, 50, dst=wh, date=days(20))
check(allocs(iss)[0][2] == "RECALCULATION_REQUIRED", "سند عقب‌دار: خروج بعدی «نیازمند بازمحاسبه» شد")
check(rc.flagged_count(company_id) >= 1, "شمارش نیازمند بازمحاسبه")
prev = rc.preview(company_id, item_id=f, date_from=days(30))
ch = [ln for r in prev for ln in r.changed]
check(len(ch) == 1 and ch[0].old_amount == 500 and ch[0].new_amount == 250 and ch[0].delta == -250,
      f"پیش‌نمایش: ۵ × ۵۰ به جای ۵ × ۱۰۰ ({[(l.old_amount, l.new_amount) for l in ch]})")
check(allocs(iss)[0][1] == 100, "پیش‌نمایش چیزی را تغییر نمی‌دهد")
cogs_before, inv_before = gl(cogs_gl.account_id), gl(inv_gl.account_id)
run = rc.recalculate(company_id, user.user_id, item_id=f, date_from=days(30), reason="رسید عقب‌دار")
check(run is not None and run.lines_count == 1 and run.total_delta == -250 and run.journal_entry_id, "بازمحاسبه با سند اصلاحی")
check(gl(cogs_gl.account_id) - cogs_before == -250 and gl(inv_gl.account_id) - inv_before == 250,
      "سند اصلاحی: بهای تمام‌شده −۲۵۰، موجودی +۲۵۰")
check(allocs(iss) == [(D(5), D(50), "CALCULATED")], "تخصیص به لایهٔ عقب‌دار و وضعیت «محاسبه‌شده»")
with new_session() as s:
    rem = sorted((l.unit_cost.normalize(), l.remaining_quantity.normalize()) for l in s.scalars(select(CostLayer).where(CostLayer.item_id == f)))
    old_ledger = s.scalar(select(sa_func.sum(sa_func.abs(StockLedger.unit_cost))).where(
        StockLedger.stock_document_line_id == iss))
check(rem == [(D(50), D(5)), (D(100), D(10))], f"لایه‌ها پس از بازمحاسبه ({rem})")
check(old_ledger == 100, "دفتر انبار دست نخورد (تغییرناپذیر)")
check(abs(item_value(f) - D(1250)) < D("0.01") and abs(bal_value(f) - D(1250)) < D("0.01"), f"ارزش کالا = ۵×۵۰ + ۱۰×۱۰۰ ({item_value(f)} / {bal_value(f)})")
consistent("FIFO")
check(rc.recalculate(company_id, user.user_id, item_id=f, date_from=days(30)) is None, "اجرای دوباره: اختلافی نیست")
with new_session() as s:
    logs = s.scalars(select(ActivityLog).where(ActivityLog.entity_type == "CostRecalculation")).all()
    lines = s.scalars(select(CostRecalculationLine).where(CostRecalculationLine.run_id == run.run_id)).all()
check(len(logs) == 1 and logs[0].changes.get("reason") == "رسید عقب‌دار", f"Audit بازمحاسبه با علت ({[l.changes for l in logs]})")
check(len(lines) == 1 and lines[0].old_amount == 500 and lines[0].new_amount == 250, "سابقهٔ مبلغ قبلی/جدید")

# --- ۲) میانگینِ متحرک + رسیدِ عقب‌دار ------------------------------------------------------------
a = new_item("R-AVG", "WEIGHTED_AVERAGE")
mk("RECEIPT", a, 10, 100, dst=wh, date=days(10))
_, iss_a = mk("ISSUE", a, 5, src=wh, date=days(5))
check(rc.preview(company_id, item_id=a, date_from=days(30))[0].changed == [], "میانگین: بدون تغییر، اختلاف صفر")
mk("RECEIPT", a, 10, 200, dst=wh, date=days(8))
check(allocs(iss_a)[0][2] == "RECALCULATION_REQUIRED", "میانگین: خروج بعدی علامت خورد")
run = rc.recalculate(company_id, user.user_id, item_id=a, date_from=days(30))
check(run is not None and run.total_delta == 250, f"میانگین: ۵ × ۱۵۰ به جای ۵ × ۱۰۰ ({run and run.total_delta})")
check(allocs(iss_a) == [(D(5), D(150), "CALCULATED")], "میانگین: تخصیص ۱۵۰")
with new_session() as s:
    avg = s.scalar(select(StockBalance.average_unit_cost).where(StockBalance.item_id == a, StockBalance.quantity_on_hand > 0))
check(avg == 150 and abs(bal_value(a) - D(2250)) < D("0.01") and abs(item_value(a) - D(2250)) < D("0.01"),
      f"میانگین: ماندهٔ ۱۵ × ۱۵۰ ({avg})")
consistent("میانگین")
mk("RECEIPT", a, 5, 90, dst=wh)
_, iss_a2 = mk("ISSUE", a, 4, src=wh)
check(rc.preview(company_id, item_id=a, date_from=days(30))[0].changed == [], "میانگین: پس از بازمحاسبه و حرکت تازه، اختلاف صفر")

# --- ۳) انتقال: لایهٔ مقصد بهایِ جدید می‌گیرد ------------------------------------------------------------
wh2 = locations_service.create_warehouse(company_id, "WH02", "فرعی", locations_service.WarehouseFields(allow_negative_stock=False))
t = new_item("R-TR", "FIFO")
mk("RECEIPT", t, 10, 100, dst=wh, date=days(10))
mk("TRANSFER", t, 5, src=wh, dst=wh2, date=days(6))
_, iss_t = mk("ISSUE", t, 5, src=wh2, date=days(3))
mk("RECEIPT", t, 10, 40, dst=wh, date=days(15))
check(rc.preview(company_id, warehouse_id=wh2, date_from=days(30)) and True, "پیش‌نمایش با فیلتر انبار")
inv_before, cogs_before = gl(inv_gl.account_id), gl(cogs_gl.account_id)
run = rc.recalculate(company_id, user.user_id, item_id=t, date_from=days(30))
check(allocs(iss_t) == [(D(5), D(40), "CALCULATED")], "انتقال: خروج از انبار مقصد با بهای لایهٔ عقب‌دار (۴۰)")
check(gl(cogs_gl.account_id) - cogs_before == -300 and gl(inv_gl.account_id) - inv_before == 300,
      "انتقال: فقط خروج فروش سند حسابداری دارد (−۳۰۰)")
with new_session() as s:
    dest = s.scalars(select(CostLayer).where(CostLayer.item_id == t, CostLayer.warehouse_id == wh2)).all()
check(len(dest) == 1 and dest[0].unit_cost == 40 and dest[0].remaining_quantity == 0, "انتقال: بهای لایهٔ مقصد ۴۰")
check(abs(item_value(t) - D(5 * 40 + 10 * 100)) < D("0.01") and abs(bal_value(t) - D(1200)) < D("0.01"), "انتقال: ارزش هر انبار درست")
consistent("انتقال")

# --- ۴) بهایِ در انتظار (موجودیِ منفی) با رسیدِ بعدی تسویه می‌شود --------------------------------------------
engine_service.set_costing_settings(company_id, "WEIGHTED_AVERAGE", True, negative_stock_policy="PENDING", user_id=user.user_id)
p = new_item("R-PEND", "FIFO")
_, iss_p = mk("ISSUE", p, 3, src=wh, date=days(4))
check(allocs(iss_p)[-1][2] == "PENDING", "خروج بدون موجودی: «در انتظار»")
mk("RECEIPT", p, 10, 70, dst=wh, date=days(2))
check(any(ln.item_id == p for r in rc.preview(company_id, date_from=days(30)) for ln in r.changed), "در انتظار: در پیش‌نمایش کلی")
run = rc.recalculate(company_id, user.user_id, item_id=p, date_from=days(30))
check(allocs(iss_p) == [(D(3), D(70), "CALCULATED")], f"در انتظار → محاسبه‌شده با بهای رسید بعدی ({allocs(iss_p)})")
with new_session() as s:
    lyr = s.scalars(select(CostLayer).where(CostLayer.item_id == p)).all()
check(len(lyr) == 1 and lyr[0].remaining_quantity == 7 and abs(bal_value(p) - D(490)) < D("0.01"), "لایه با کمبود قبلی تسویه شد (۷ × ۷۰)")
consistent("در انتظار")
engine_service.set_costing_settings(company_id, "WEIGHTED_AVERAGE", True, negative_stock_policy="WAREHOUSE", user_id=user.user_id)

# --- ۵) روش‌هایِ غیرِ ترتیبی بازمحاسبه نمی‌شوند -------------------------------------------------------
sp = new_item("R-SPEC", "SPECIFIC")
mk("RECEIPT", sp, 2, 10, dst=wh)
res = rc.preview(company_id, item_id=sp, date_from=days(30))
check(len(res) == 1 and not res[0].ok and "ویژه" in res[0].message, "شناسایی ویژه: با علت کنار گذاشته شد")
check(rc.flagged_count(company_id) == 0, "پس از بازمحاسبه، خروج «نیازمند بازمحاسبه» نمانده")

# --- ۶) صفحه و دسترسی ------------------------------------------------------------------------------
sess.current_user = user
from peecha.ui.screens import costing as costing_ui
scr = costing_ui.RecalculationScreen()
scr.refresh()
check(scr.apply_button.isEnabled(), "مدیر: اجرای بازمحاسبه فعال")
b = new_item("R-UI", "LIFO")
mk("RECEIPT", b, 10, 100, dst=wh, date=days(10))
_, iss_b = mk("ISSUE", b, 5, src=wh, date=days(5))
mk("RECEIPT", b, 10, 300, dst=wh, date=days(7))
scr.refresh()
scr.item_combo.setCurrentIndex(scr.item_combo.findData(b))
scr.from_date.setDate(days(30))
check(len(scr.preview()) == 1 and scr.table.rowCount() == 1, "صفحه: پیش‌نمایش یک ردیف")
scr.confirm = lambda text: False
check(scr.apply() is None and allocs(iss_b)[0][1] == 100, "صفحه: بدون تایید هشدار، چیزی اعمال نمی‌شود")
warned = []
scr.confirm = lambda text: warned.append(text) or True
check(scr.apply() and allocs(iss_b) == [(D(5), D(300), "CALCULATED")] and "هشدار" in warned[0], "صفحه: با تایید هشدار، LIFO ۳۰۰")
consistent("صفحه")
forms = {fo.code for fo in roles_service.list_forms()}
check("costing_recalculation" in forms, "فرم بازمحاسبه در فهرست دسترسی‌ها")
clerk = users_service.create_user("clerk260", "انباردار", "secret123", None, company.default_language_id, False, [company_id], company_id)
sess.current_user = clerk
scr.refresh()
check(not scr.apply_button.isEnabled() and scr.apply() is None, "کاربر بدون دسترسی: اجرا ممنوع")
sess.current_user = user

# --- ۷) هزینه‌یابی: بهایِ مصرف به تفکیکِ مرکزِ هزینه -----------------------------------------------
from peecha.services.costing import reports as cr
from peecha.services.purchase_reports import PurchaseFilters
cc = dimensions_service.create_detail_account(company_id, dimensions_service.get_specialized_dimension_type_id(
    company_id, dimensions_service.COST_CENTER_CODE), "CC1", "تولید").detail_account_id
k = new_item("R-CC", "FIFO")
mk("RECEIPT", k, 10, 30, dst=wh)
doc = inv_documents_service.create_stock_document(company_id, user.user_id, "ISSUE", today, inv_documents_service.DocumentHeaderFields(
    source_warehouse_id=wh, cost_center_detail_account_id=cc))
inv_documents_service.add_line(doc, company_id, inv_documents_service.LineFields(item_id=k, uom_id=pcs, quantity=D(4), quantity_base=D(4)))
post(doc)
rep = cr.cost_by_center(company_id, PurchaseFilters(days(60), today, side="INVENTORY"))
row = next((x for x in rep.rows if "R-CC" in str(x[1])), None)
check(row is not None and row[3] == 120 and "تولید" in str(row[0]), f"مرکز هزینه: ۴ × ۳۰ = ۱۲۰ برای «تولید» ({row})")
check(any("بدون" in str(x[0]) for x in rep.rows), "خروج‌های بدون مرکز هزینه جدا")
check(len(cr.cost_by_center(company_id, PurchaseFilters(days(60), today, side="INVENTORY", options={"by": "PROJECT"})).rows) > 0,
      "تفکیک به پروژه اجرا شد")

print("RESULT:", "ALL PASS" if not FAIL else "SOME FAILED")
sys.exit(1 if FAIL else 0)
