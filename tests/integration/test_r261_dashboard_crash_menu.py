import os, sys, datetime, decimal, io
os.environ["PEECHA_DB_NAME"] = "peecha_test_r261_1"
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
# R261: کرشِ داشبوردِ انبار، بهایِ تمام‌شده در منویِ اصلی، تفکیکِ رنگیِ سطوحِ منو
# =====================================================================
import gc, time
from peecha.ui.screens import purchase_reports as report_screens
from peecha.ui.screens.warehouse_dashboard import WarehouseDashboard

# --- ۱) بارگذاریِ دوباره در حینِ اجرایِ پس‌زمینه برنامه را نمی‌بندد ---------------------------------
report_screens.BACKGROUND_REPORTS = True
dash = WarehouseDashboard(None)
dash.refresh(); dash.refresh(); dash.reload()
gc.collect()
for _ in range(400):
    app.processEvents(); time.sleep(0.03)
    if not report_screens.ReportWorker._live:
        break
check(not report_screens.ReportWorker._live, "همهٔ کارهای پس‌زمینه تمام شدند (بدون پاک‌شدن رشتهٔ در حال اجرا)")
check(bool(dash._kpis), "داشبورد انبار مقادیر را بارگذاری کرد")
errors = []
from PySide6.QtWidgets import QMessageBox as _MB
_MB.warning = staticmethod(lambda *a, **k: errors.append(a[2]))
dash._generation = 99
dash._on_worker_done(99, None, RuntimeError("خطای آزمایشی"))
check(errors and "خطای آزمایشی" in errors[0], "خطای پس‌زمینه پیام می‌دهد، برنامه را نمی‌بندد")
report_screens.BACKGROUND_REPORTS = False

# --- ۲) بهایِ تمام‌شده ماژولِ منویِ اصلی -------------------------------------------------------
from peecha import nav_catalog
codes = [i["code"] for i in nav_catalog.NAV_ITEMS]
check("COSTING" in codes and codes.index("COSTING") == codes.index("INV") + 1, "«بهای تمام‌شده» کنار انبار در منوی اصلی")
inv = next(i for i in nav_catalog.NAV_ITEMS if i["code"] == "INV")
check(not any(c.get("code") == "INV_COSTING" for c in inv["children"]), "دیگر زیرمنوی انبار نیست")
catalog = {f: m for f, m, _l in nav_catalog.build_form_catalog()}
check(all(catalog[f] == "COSTING" for f in ("costing_dashboard", "costing_settings", "costing_replacement", "costing_recalculation")),
      "فرم‌های بهای تمام‌شده در ماژول COSTING (دسترسی‌ها)")
from peecha.db.models.security import Form, Module
roles_service.ensure_catalog()
with new_session() as s:
    inv_module = s.scalar(select(Module.module_id).where(Module.code == "INV"))
    f = s.scalar(select(Form).where(Form.code == "costing_dashboard"))
    f.module_id = inv_module  # وضعیتِ نصب‌هایِ R259/R260
    s.commit()
roles_service.ensure_catalog()
with new_session() as s:
    mod = s.scalar(select(Module.code).join(Form, Form.module_id == Module.module_id).where(Form.code == "costing_dashboard"))
check(mod == "COSTING", "فرم موجود هنگام ارتقا به ماژول جدید منتقل شد (همان فرم و دسترسی‌ها)")

# --- ۳) منو: بدنهٔ ماژول و زیرگروه زمینه/خطِ جدا دارند ------------------------------------------------
from peecha.ui.shell_window import MainWindow
from peecha.ui import theme
check("QWidget#sidebarGroupBody" in theme.GLOBAL_QSS and "QWidget#sidebarSubGroupBody" in theme.GLOBAL_QSS, "استایل سطوح منو")
mw = MainWindow()
g = mw._sidebar_groups["COSTING"]
check(g.body.objectName() == "sidebarGroupBody" and g.body.testAttribute(theme.Qt.WA_StyledBackground), "بدنهٔ ماژول زمینهٔ خودش را می‌کشد")
sub = mw._sidebar_groups["INV"]._subgroups
check(all(sg.body.objectName() == "sidebarSubGroupBody" for sg in sub), "زیرگروه‌ها خط راهنما دارند")
mw.open_screen("COST_DASHBOARD")
check(mw._current_screen_code == "COST_DASHBOARD", "بازشدن داشبورد بهای تمام‌شده از منوی جدید")

print("RESULT:", "ALL PASS" if not FAIL else "SOME FAILED")
sys.exit(1 if FAIL else 0)
