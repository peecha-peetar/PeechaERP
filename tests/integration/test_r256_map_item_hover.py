import os, sys, datetime, decimal, io
os.environ["PEECHA_DB_NAME"] = "peecha_test_r256_1"
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
# R256: تولتیپِ خوانا + نمایشِ مقدار/سریالِ کالایِ جستجوشده با ماوس
# =====================================================================
from peecha.db.models.inventory import StockDocumentLine as SDL
from peecha import numerals
P = numerals.to_persian_digits
TE = lt.TrackingEntry

phone = catalog_service.create_item(company_id, "P-1", "گوشی", catalog_service.ItemFields(item_kind_code="GOOD", base_uom_id=pcs, track_serial=True))
def serial_receipt(serials, bin_id):
    doc = draft("RECEIPT", phone, len(serials), bin_id=bin_id, dst=wh)
    with new_session() as s:
        line_id = s.scalar(select(SDL.line_id).where(SDL.stock_document_id == doc))
    lt.set_line_tracking(company_id, [TE(D(1), serial_no=x) for x in serials], stock_line_id=line_id)
    return post(doc)
serial_receipt(["SN-1", "SN-2", "SN-3"], pick1)
serial_receipt(["SN-9"], pick2)

# ۱) سرویس: مقدار/سریال در هر محل و جمع رویِ قفسه/منطقه
pr = wl.item_presence(company_id, wh, [phone])
check(pr[pick1].quantity == 3 and pr[pick1].serials == ["SN-1", "SN-2", "SN-3"], "محل: ۳ عدد با سریال‌های SN-1..3")
check(pr[pick2].serials == ["SN-9"], "محل دیگر: SN-9")
check(pr[rp].quantity == 4 and len(pr[rp].serials) == 4 and pr[zp].quantity == 4, "قفسه و منطقه جمع زیرمحل‌ها را دارند")
check(bulk1 not in pr, "محلی که این کالا را ندارد در نتیجه نیست")
pr_g = wl.item_presence(company_id, wh, [item])
check(pr_g[bulk1].quantity == 80 and pr_g[pick1].quantity == 5 and not pr_g[bulk1].serials, "کالای بی‌سریال: فقط مقدار")

# جستجو با شمارهٔ سریال
res = wl.search(company_id, "sn-2")
check(res.kind == "SERIAL" and res.location_ids == [pick1] and res.item_ids == [phone], "جستجوی شمارهٔ سریال، محل همان سریال را می‌دهد")

# ۲) نقشه: پس از جستجو، تولتیپِ هر محل مقدار و سریال‌ها را نشان می‌دهد
from peecha.ui.screens.warehouse_map import WarehouseMapScreen
ms = WarehouseMapScreen(None); ms.refresh(); ms.load_warehouse(wh)
check("سریال" not in ms.items[pick1].toolTip(), "بدون جستجو، تولتیپ عادی محل")
found = ms.search("P-1")
check(set(found) == {pick1, pick2}, "جستجوی کالا دو محل را یافت")
tip = ms.items[pick1].toolTip()
check("SN-1" in tip and "SN-3" in tip and "سریال‌ها" in tip and "گوشی" in tip, f"تولتیپ محل: نام کالا و سریال‌ها (got {tip[:160]})")
check(P("3") in tip and "مقدار در این محل" in tip, "تولتیپ محل: تعداد در همین محل")
check("موجودی ندارد" in ms.items[bulk1].toolTip(), "محل فاقد کالا: «موجودی ندارد»")
check("سریال‌ها" in ms.detail_info.text(), "جزئیات محل انتخاب‌شده هم سریال‌ها را نشان می‌دهد")
ms.view3d_check.setChecked(True)
check("SN-9" in ms.view3d.info[pick2] and P("4") in ms.view3d.info[rp], "سه‌بعدی: سریال‌ها روی خانه و جمع روی قفسه با ماوس")
ms.view3d.hover(pick1, None)
check("SN-2" in ms.view3d.hover_label.text(), "سه‌بعدی: نوار اطلاعات زیر ماوس سریال‌ها را نشان می‌دهد")
ms.select_location(pick1, focus=False)
cells = [ms.elevation_table.item(r, c) for r in range(ms.elevation_table.rowCount()) for c in range(ms.elevation_table.columnCount())]
check(any(c is not None and "SN-1" in c.toolTip() for c in cells), "نمای قفسه: تولتیپ خانه سریال‌ها را دارد")
ms.search("")
check("سریال" not in ms.items[pick1].toolTip(), "پاک‌کردن جستجو، اطلاعات کالا را از تولتیپ برمی‌دارد")
ms.search("SN-9")
check("SN-9" in ms.items[pick2].toolTip(), "جستجو با سریال هم همان اطلاعات را می‌دهد")

# ۳) تولتیپ خوانا: سبکِ نقشه/سه‌بعدی به تولتیپ نشت نمی‌کند
check(ms.view.styleSheet().strip().startswith("QGraphicsView") and ms.view3d.view.styleSheet().strip().startswith("QGraphicsView"),
      "سبک زمینهٔ نقشه فقط به خود نما محدود است (تولتیپ رنگ تم عمومی را می‌گیرد)")

print("RESULT:", "ALL PASS" if not FAIL else "SOME FAILED")
sys.exit(1 if FAIL else 0)
