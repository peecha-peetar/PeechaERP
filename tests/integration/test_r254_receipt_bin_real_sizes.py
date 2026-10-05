import os, sys, datetime, decimal, io
os.environ["PEECHA_DB_NAME"] = "peecha_test_r254_1"
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
# R254: مکانِ الزامی در تاییدِ رسید + انتخاب رویِ نقشه، ابعادِ واقعیِ Bin/طبقه، حذفِ روشِ قدیمیِ تعریفِ مکان
# =====================================================================
from peecha.db.models.inventory import StockBalance, StockDocumentLine
from peecha.db.models.commercial import CommercialDocumentLine
from sqlalchemy import func as sa_func

def qty_at(item_id, bin_id):
    with new_session() as s:
        return s.scalar(select(sa_func.coalesce(sa_func.sum(StockBalance.quantity_on_hand), 0)).where(
            StockBalance.item_id == item_id, StockBalance.bin_location_id == bin_id)) or 0

# ۱) ابعادِ واقعیِ Bin در طولِ قفسه و طبقه در ارتفاع
zr = wl.create_location(company_id, wh, "AREA", "Z07", fields=LF(width_m=D(20), length_m=D(15)))
rr = wl.create_location(company_id, wh, "RACK", "R07", zr, LF(width_m=D(1), length_m=D(10), height_m=D(3)))
s1 = wl.create_location(company_id, wh, "SHELF", "L01", rr, LF(height_m=D(1)))
s2 = wl.create_location(company_id, wh, "SHELF", "L02", rr)
b1 = wl.create_location(company_id, wh, "BIN", "B01", s1, LF(width_m=D(2)))
b2 = wl.create_location(company_id, wh, "BIN", "B02", s1, LF(width_m=D(3), length_m=D("0.5")))
b3 = wl.create_location(company_id, wh, "BIN", "B03", s1)
geo = wl.geometry(company_id, wh)
U = wl.UNITS_PER_M
rx, ry, rw, rh, _ = geo[rr]
check((rw, rh) == (1 * U, 10 * U), f"قفسه با ابعادِ واقعی ۱×۱۰ متر (got {rw / U}×{rh / U})")
check(abs(geo[b1][3] - 2 * U) < 0.01 and abs(geo[b2][3] - 3 * U) < 0.01, "Binها با عرضِ واقعیِ خود (۲ و ۳ متر)، نه سهمِ مساوی")
check(abs(geo[b3][3] - 5 * U) < 0.01, "Binِ بی‌اندازه باقی‌ماندهٔ طولِ قفسه (۵ متر) را گرفت")
check(abs(geo[b2][1] - (ry + 2 * U)) < 0.01 and abs(geo[b3][1] - (ry + 5 * U)) < 0.01, "Binها پشتِ‌سرِهم بدونِ هم‌پوشانی چیده شدند")
check(abs(geo[b2][2] - 0.5 * U) < 0.01 and abs(geo[b1][2] - rw) < 0.01, "عمقِ Bin: واقعی (۰٫۵ متر) یا عمقِ قفسه")
boxes = {b.location_id: b for b in wl.scene_3d(company_id, wh)}
check(abs(boxes[s1].h - 1 * U) < 0.01 and abs(boxes[s2].h - 2 * U) < 0.01 and abs(boxes[s2].z - (boxes[s1].z + 1 * U)) < 0.01,
      "سه‌بعدی: ارتفاعِ واقعیِ طبقه (۱ متر) و باقی‌مانده (۲ متر) برایِ طبقهٔ بی‌ارتفاع")
check(wl._split_real(10, [None, None]) == [(0, 5), (5, 5)], "بی‌اندازه‌ها مساوی تقسیم می‌شوند (رفتارِ قبلی حفظ شد)")

# ۲) تاییدِ رسید: مکان الزامی
from peecha.services import treasury as treasury_service
csettings_service.set_feature_enabled(company_id, "PURCHASE_ORDER_GOODS_RECEIPT", True)
csettings_service.set_feature_enabled(company_id, "PURCHASE_ORDER_SKIP_APPROVAL", True)
csettings_service.set_feature_enabled(company_id, "PURCHASE_INVOICE_SKIP_APPROVAL", True)
supplier_group_id = next(g.person_group_id for g in dimensions_service.list_person_groups(company_id) if g.code == "SUPPLIER")
treasury_service.create_counterparty_mapping(company_id, "PAYMENT", ap_gl.account_id, person_group_id=supplier_group_id)
HF = lambda w: documents_service.DocumentHeaderFields(counterparty_detail_account_id=supplier, currency_id=company.base_currency_id, warehouse_id=w)
def posted_po(w, lines):
    po = documents_service.create_document(company_id, user.user_id, "PURCHASE_ORDER", today, HF(w))
    ids = [documents_service.add_line(po, company_id, it, pcs, D(q), D(q), unit_price=D(100)) for it, q in lines]
    documents_service.confirm_document(po, company_id, user.user_id)
    documents_service.post_document(po, company_id, user.user_id)
    return po, ids
po, (l1, l2) = posted_po(wh, [(milk, 4), (g2, 6)])
check(raises(lambda: documents_service.approve_warehouse(po, company_id, user.user_id, warehouse_id=wh)),
      "تاییدِ رسید بدونِ مکان در انبارِ مکان‌بندی‌شده رد شد")
wh2 = locations_service.create_warehouse(company_id, "WH02", "فرعی", locations_service.WarehouseFields(allow_negative_stock=True))
other = wl.create_location(company_id, wh2, "AREA", "Y01")
check(raises(lambda: documents_service.approve_warehouse(po, company_id, user.user_id, warehouse_id=wh, line_bins={l1: other, l2: b1})),
      "مکانِ انبارِ دیگر رد شد")
dead = wl.create_location(company_id, wh, "BIN", "B09", s2)
with new_session() as s:
    s.get(BinLocation, dead).is_active = False
    s.commit()
check(raises(lambda: documents_service.approve_warehouse(po, company_id, user.user_id, warehouse_id=wh, line_bins={l1: dead, l2: b1})),
      "مکانِ غیرفعال رد شد")
check(raises(lambda: documents_service.approve_warehouse(po, company_id, user.user_id, warehouse_id=wh, line_bins={l1: b2})),
      "اگر فقط یکی از ردیف‌ها مکان داشته باشد هم رد می‌شود")
check(documents_service.get_document(po, company_id)[0].warehouse_approved_at is None, "تاییدِ ردشده هیچ اثری نگذاشت")

# ۳) دیالوگِ تاییدِ رسید: ستونِ «مکان» + نقشه
from peecha.ui.screens.purchase_goods_receipt import _GoodsReceiptDialog, _LINE_COLUMNS as GR_COLS, _BIN_COL
from PySide6.QtWidgets import QComboBox, QPushButton
dlg = _GoodsReceiptDialog(None, po, company_id)
check(GR_COLS[_BIN_COL] == "مکان" and not dlg.lines_table.isColumnHidden(_BIN_COL), "ستونِ «مکان» در تاییدِ رسید دیده می‌شود")
cell = dlg.lines_table.cellWidget(0, _BIN_COL)
combo = cell.findChild(QComboBox)
check(combo.findData(b1) > 0 and combo.findData(rr) < 0 and combo.findData(other) < 0, "فهرستِ مکان فقط محل‌هایِ برگِ همان انبار")
check(any(b.text() == "نقشه" for b in cell.findChildren(QPushButton)), "دکمهٔ «نقشه» کنارِ هر ردیف")
dlg._toggle_receipt()
check("مکانِ ردیفِ" in dlg.status_label.text(), f"دیالوگ بی‌مکان تایید نمی‌کند (got {dlg.status_label.text()})")
dlg._line_bin_combos[l1].setCurrentIndex(dlg._line_bin_combos[l1].findData(b2))
dlg._line_bin_combos[l2].setCurrentIndex(dlg._line_bin_combos[l2].findData(b3))
dlg._toggle_receipt()
doc, plines = documents_service.get_document(po, company_id)
check(doc.warehouse_approved_at is not None, "رسید با مکان تایید شد")
check({ln.line_id: ln.bin_location_id for ln in plines} == {l1: b2, l2: b3}, "مکانِ هر ردیف ذخیره شد")
check(not dlg._line_bin_combos[l1].isEnabled(), "پس از تایید، مکان قفل است")
dlg.close()

# انتخاب رویِ نقشه
from peecha.ui.screens.warehouse_map import LocationPickerDialog
from PySide6.QtWidgets import QDialogButtonBox
pick = LocationPickerDialog(None, wh, None, milk, D(1))
pick.map.select_location(rr, focus=False)
check(pick.selected_location_id is None and not pick.buttons.button(QDialogButtonBox.Ok).isEnabled(), "قفسهٔ دارایِ زیرمحل قابلِ‌انتخاب نیست")
pick.map.select_location(b1, focus=False)
check(pick.selected_location_id == b1 and pick.buttons.button(QDialogButtonBox.Ok).isEnabled(), "Bin رویِ نقشه انتخاب شد")
pick.map.select_location(dead, focus=False)
check(pick.selected_location_id is None, "محلِ غیرفعال قابلِ‌انتخاب نیست")
check(not pick.map.edit_check.isVisible() and not pick.map.warehouse_combo.isEnabled(), "نقشهٔ انتخاب، فقط‌خواندنی و روی همان انبار")
pick.close()

# ۴) فاکتورِ تبدیلی: مکانِ انباردار منتقل و قفل؛ ثبت → موجودی در همان مکان‌ها
inv = documents_service.convert_to_invoice(po, company_id, user.user_id, today)
ilines = documents_service.get_document(inv, company_id)[1]
check(sorted(ln.bin_location_id for ln in ilines) == sorted([b2, b3]), "مکان‌هایِ رسید به فاکتور منتقل شد")
check(raises(lambda: documents_service.set_line_bin(company_id, ilines[0].line_id, b1)), "در فاکتور، مکانِ تعیین‌شدهٔ انباردار قفل است")
from peecha.ui.screens.commercial_document import CommercialDocumentScreen, _BIN_COL as INV_BIN_COL
scr = CommercialDocumentScreen("PURCHASE_INVOICE", None)
scr.edit_document(inv)
w0 = scr.lines_table.cellWidget(0, INV_BIN_COL)
check(isinstance(w0, QComboBox) and not w0.isEnabled(), "کمبویِ مکان در فاکتور برایِ ردیفِ رسیده غیرفعال است")
documents_service.confirm_document(inv, company_id, user.user_id)
settlements_service.auto_approve_settlement_plan(inv, company_id, user.user_id, [])
documents_service.post_document(inv, company_id, user.user_id)
check(qty_at(milk, b2) == 4 and qty_at(g2, b3) == 6, "موجودی دقیقاً در مکان‌هایِ تاییدشدهٔ انباردار نشست")

# ۵) انبارِ بی‌مکان‌بندی: الزام ندارد (فقط GENERAL)
wh3 = locations_service.create_warehouse(company_id, "WH03", "بی‌نقشه", locations_service.WarehouseFields(allow_negative_stock=True))
po3, _ = posted_po(wh3, [(milk, 1)])
documents_service.approve_warehouse(po3, company_id, user.user_id, warehouse_id=wh3)
check(documents_service.get_document(po3, company_id)[0].warehouse_approved_at is not None, "انبارِ بدونِ مکان‌بندی بدونِ مکان تایید می‌شود")

# ۶) سفارشِ فروش: ستونِ مکان در حواله پنهان
from peecha.ui.screens import purchase_goods_receipt as gr
check(gr._IN_TYPES == ("PURCHASE_ORDER", "CONSIGNMENT_IN"), "مکان فقط برایِ رسیدهایِ ورودی")

# ۷) فرمِ انبار: روشِ قدیمیِ تعریفِ مکان حذف شد، بقیهٔ فرم سالم
from peecha.ui.screens import inventory_warehouses as iw
from peecha.ui.screens.inventory_warehouses import InventoryWarehousesScreen
ws = InventoryWarehousesScreen()
ws.refresh()
check(not hasattr(ws, "bins_panel") and not hasattr(iw, "_BinLocationDialog"), "پنلِ قدیمیِ «مکان‌هایِ انبار» از فرمِ انبار حذف شد")
row = next(r for r in ws._rows if r.warehouse_id == wh)
ws._load_into_form(row)
ws.name_field.setText("مرکزیِ اصلی")
ws._save()
check(next(r for r in ws._rows if r.warehouse_id == wh).name == "مرکزیِ اصلی", "ویرایش و ذخیرهٔ انبار بدونِ پنلِ قدیمی کار می‌کند")
ws._reset_form()
check(ws.default_bin_combo.count() == 1, "فرمِ انبارِ جدید سالم است")
check(any(n.full_code.endswith("GENERAL") or n.code == "GENERAL" for n in wl.tree(company_id, wh)),
      "مکان‌هایِ قدیمی (مثلِ GENERAL) همچنان در درختِ نقشه هستند")

print("RESULT:", "ALL PASS" if not FAIL else "SOME FAILED")
sys.exit(1 if FAIL else 0)
