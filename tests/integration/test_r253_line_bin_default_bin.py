import os, sys, datetime, decimal, io
os.environ["PEECHA_DB_NAME"] = "peecha_test_r253_1"
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
# R253: مکانِ پیش‌فرضِ قابلِ‌تغییرِ انبار + ستونِ «مکان» در فاکتورِ خرید
# =====================================================================
from peecha.db.models.inventory import StockBalance, StockDocumentLine
from peecha.db.models.commercial import CommercialDocumentLine
from peecha.services import warehouse_reports as wr
from sqlalchemy import func as sa_func

def qty_at(item_id, bin_id):
    with new_session() as s:
        return s.scalar(select(sa_func.coalesce(sa_func.sum(StockBalance.quantity_on_hand), 0)).where(
            StockBalance.item_id == item_id, StockBalance.bin_location_id == bin_id)) or 0

# ۱) پیش‌فرض: بدونِ تنظیم = GENERAL؛ با تنظیم = همان مکان
check(locations_service.get_default_bin_location(wh).bin_location_id == general, "بدونِ تنظیم، مکانِ پیش‌فرض همان GENERAL است")
locations_service.set_default_bin_location(company_id, wh, bulk2, user.user_id)
check(locations_service.get_explicit_default_bin_id(wh) == bulk2, "مکانِ پیش‌فرضِ انبار ذخیره شد")
with new_session() as s:
    logged = s.scalar(select(sa_func.count()).select_from(ActivityLog).where(ActivityLog.entity_type == "Warehouse", ActivityLog.entity_id == wh))
check(logged >= 1, "تغییرِ مکانِ پیش‌فرض در Audit ثبت شد")
post(draft("RECEIPT", g2, 7, dst=wh))
check(qty_at(g2, bulk2) == 7, "رسیدِ بی‌مکان در مکانِ پیش‌فرضِ انتخابی (نه GENERAL) ثبت شد")
check(qty_at(g2, general) == 0, "چیزی در GENERAL ننشست")

# ۲) اعتبارسنجی
wh2 = locations_service.create_warehouse(company_id, "WH02", "فرعی", locations_service.WarehouseFields(allow_negative_stock=True))
other = wl.create_location(company_id, wh2, "AREA", "Y01")
check(raises(lambda: locations_service.set_default_bin_location(company_id, wh, other)), "مکانِ انبارِ دیگر پیش‌فرض نمی‌شود")
spare = wl.create_location(company_id, wh, "BIN", "B09", rb)
with new_session() as s:
    s.get(BinLocation, spare).is_active = False
    s.commit()
check(raises(lambda: locations_service.set_default_bin_location(company_id, wh, spare)), "مکانِ غیرفعال پیش‌فرض نمی‌شود")

# ۳) غیرفعال‌شدنِ پیش‌فرض → بازگشت به GENERAL؛ حذفِ پیش‌فرض → پاک‌شدنِ تنظیم
locations_service.set_default_bin_location(company_id, wh, bulk2, user.user_id)
with new_session() as s:
    s.get(BinLocation, bulk2).is_active = False
    s.commit()
check(locations_service.get_default_bin_location(wh).bin_location_id == general, "پیش‌فرضِ غیرفعال‌شده → GENERAL")
post(draft("RECEIPT", g2, 1, dst=wh))
check(qty_at(g2, general) == 1, "موتورِ انبار هم به GENERAL برمی‌گردد")
with new_session() as s:
    s.get(BinLocation, bulk2).is_active = True
    s.commit()
temp = wl.create_location(company_id, wh, "BIN", "B08", rb)
locations_service.set_default_bin_location(company_id, wh, temp, user.user_id)
wl.delete_location(company_id, temp, user.user_id)
check(locations_service.get_explicit_default_bin_id(wh) is None, "حذفِ مکانِ پیش‌فرض، تنظیمِ انبار را پاک کرد")
check(locations_service.get_default_bin_location(wh).bin_location_id == general, "پس از حذف، پیش‌فرض GENERAL است")
locations_service.set_default_bin_location(company_id, wh, bulk2, user.user_id)

# ۴) ستونِ «مکان» در فاکتورِ خرید
csettings_service.set_feature_enabled(company_id, "PURCHASE_INVOICE_SKIP_APPROVAL", True)
supplier_group_id = next(g.person_group_id for g in dimensions_service.list_person_groups(company_id) if g.code == "SUPPLIER")
from peecha.services import treasury as treasury_service
treasury_service.create_counterparty_mapping(company_id, "PAYMENT", ap_gl.account_id, person_group_id=supplier_group_id)
HF = lambda: documents_service.DocumentHeaderFields(counterparty_detail_account_id=supplier, currency_id=company.base_currency_id, warehouse_id=wh)
inv = documents_service.create_document(company_id, user.user_id, "PURCHASE_INVOICE", today, HF())
ln_a = documents_service.add_line(inv, company_id, milk, pcs, D(4), D(4), unit_price=D(500))
ln_b = documents_service.add_line(inv, company_id, acid, pcs, D(3), D(3), unit_price=D(500))
check(raises(lambda: documents_service.set_line_bin(company_id, ln_a, other)), "مکانِ انبارِ دیگر برایِ ردیف رد شد")
check(raises(lambda: documents_service.set_line_bin(company_id, ln_a, spare)), "مکانِ غیرفعال برایِ ردیف رد شد")
documents_service.set_line_bin(company_id, ln_a, pick2)

from peecha.ui.screens.commercial_document import CommercialDocumentScreen, _LINE_COLUMNS, _BIN_COL, _ACTIONS_COL
from PySide6.QtWidgets import QComboBox
screen = CommercialDocumentScreen("PURCHASE_INVOICE", None)
screen.edit_document(inv)
check(_LINE_COLUMNS[_BIN_COL] == "مکان" and _ACTIONS_COL == len(_LINE_COLUMNS) - 1, "ستونِ «مکان» پیش از «عملیات»")
check(not screen.lines_table.isColumnHidden(_BIN_COL), "ستونِ مکان در فاکتورِ خرید دیده می‌شود")
combo = screen.lines_table.cellWidget(0, _BIN_COL)
check(isinstance(combo, QComboBox) and combo.currentData() == pick2, "کمبویِ مکانِ ردیف مقدارِ ذخیره‌شده را نشان می‌دهد")
check(screen.lines_table.cellWidget(0, _ACTIONS_COL) is not None, "دکمه‌هایِ عملیات به ستونِ آخر رفتند")
combo_b = screen.lines_table.cellWidget(1, _BIN_COL)
idx = combo_b.findData(cold1)
check(idx > 0 and combo_b.findData(zb) < 0, "فقط محل‌هایِ برگ (نه منطقه/قفسه) در کمبو هستند")
combo_b.setCurrentIndex(idx)
with new_session() as s:
    check(s.get(CommercialDocumentLine, ln_b).bin_location_id == cold1, "تغییرِ کمبو در ردیف ذخیره شد")
documents_service.set_line_bin(company_id, ln_b, None)
sales_screen = CommercialDocumentScreen("SALES_INVOICE", None)
check(sales_screen.lines_table.isColumnHidden(_BIN_COL), "ستونِ مکان در فاکتورِ فروش پنهان است")

documents_service.confirm_document(inv, company_id, user.user_id)
settlements_service.auto_approve_settlement_plan(inv, company_id, user.user_id, [])
documents_service.post_document(inv, company_id, user.user_id)
with new_session() as s:
    a = s.get(CommercialDocumentLine, ln_a)
    b = s.get(CommercialDocumentLine, ln_b)
    sa = s.get(StockDocumentLine, a.stock_document_line_id)
    sb = s.get(StockDocumentLine, b.stock_document_line_id)
check(sa is not None and sa.bin_location_id == pick2, "ردیفِ رسیدِ انبار همان مکانِ انتخابیِ فاکتور را گرفت")
check(qty_at(milk, pick2) == 4, "موجودیِ کالا در همان مکان نشست")
check(qty_at(acid, bulk2) == 3, "ردیفِ بی‌مکان در مکانِ پیش‌فرضِ انبار نشست")
check(raises(lambda: documents_service.set_line_bin(company_id, ln_a, pick1)), "پس از صدورِ رسید، مکانِ ردیف قفل است")
screen.edit_document(inv)
cell = screen.lines_table.item(0, _BIN_COL)
check(cell is not None and "B02" in cell.text(), "در سندِ ثبت‌شده کدِ مکان به‌صورتِ متن نمایش داده می‌شود")

# ۵) تبدیلِ سفارش به فاکتور مکان را منتقل می‌کند
csettings_service.set_feature_enabled(company_id, "PURCHASE_ORDER_SKIP_APPROVAL", True)
po = documents_service.create_document(company_id, user.user_id, "PURCHASE_ORDER", today, HF())
po_line = documents_service.add_line(po, company_id, milk, pcs, D(2), D(2), unit_price=D(500))
documents_service.set_line_bin(company_id, po_line, pick1)
documents_service.confirm_document(po, company_id, user.user_id)
documents_service.post_document(po, company_id, user.user_id)
inv2 = documents_service.convert_to_invoice(po, company_id, user.user_id, today)
inv2_line = documents_service.get_document(inv2, company_id)[1][0]
check(inv2_line.bin_location_id == pick1, "مکانِ ردیفِ سفارش به فاکتورِ تبدیلی منتقل شد")

# ۶) فرمِ انبار: کمبویِ مکانِ پیش‌فرض
from peecha.ui.screens.inventory_warehouses import InventoryWarehousesScreen
ws = InventoryWarehousesScreen()
ws.refresh()
row = next(r for r in ws._rows if r.warehouse_id == wh)
ws._load_into_form(row)
check(ws.default_bin_combo.currentData() == bulk2, "فرمِ انبار مکانِ پیش‌فرضِ فعلی را نشان می‌دهد")
ws.default_bin_combo.setCurrentIndex(ws.default_bin_combo.findData(pick2))
ws._save()
check(locations_service.get_explicit_default_bin_id(wh) == pick2, "ذخیرهٔ فرمِ انبار مکانِ پیش‌فرض را تغییر داد")
row = next(r for r in ws._rows if r.warehouse_id == wh)
ws._load_into_form(row)
ws.default_bin_combo.setCurrentIndex(0)
ws._save()
check(locations_service.get_explicit_default_bin_id(wh) is None, "انتخابِ «—» پیش‌فرض را به GENERAL برگرداند")
locations_service.set_default_bin_location(company_id, wh, bulk2, user.user_id)

# ۷) گزارشِ «جانمایی‌نشده» مکانِ پیش‌فرضِ تازه را مبنا می‌گیرد
from peecha.services import purchase_reports as pr
rep = pr.run_report(company_id, "UNLOCATED_STOCK", pr.PurchaseFilters(today - datetime.timedelta(days=30), today, side="INVENTORY"))
labels = [r[0] for r in rep.rows]
check(any("انبردست" in str(l) for l in labels), "موجودیِ مکانِ پیش‌فرضِ انتخابی در گزارشِ جانمایی‌نشده آمد")

# ۸) نقشه: دکمهٔ «مکانِ پیش‌فرض»
from peecha.ui.screens.warehouse_map import WarehouseMapScreen
ms = WarehouseMapScreen(None); ms.refresh(); ms.load_warehouse(wh)
ms.select_location(pick1, focus=False)
ms.run_operation("DEFAULT")
check(locations_service.get_explicit_default_bin_id(wh) == pick1, "از نقشه مکانِ پیش‌فرض تعیین شد")
check("پیش‌فرض" in ms.detail_info.text(), "جزئیاتِ نقشه پیش‌فرض بودن را نشان می‌دهد")
ms.run_operation("DEFAULT")
check(locations_service.get_explicit_default_bin_id(wh) is None, "زدنِ دوباره پیش‌فرض را برمی‌دارد")

print("RESULT:", "ALL PASS" if not FAIL else "SOME FAILED")
sys.exit(1 if FAIL else 0)
