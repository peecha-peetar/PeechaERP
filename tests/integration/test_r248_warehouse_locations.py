import os, sys, datetime, decimal, io
os.environ["PEECHA_DB_NAME"] = "peecha_test_r248_1"
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

# --- ۱) انبار: ایجاد/ویرایش/ابعاد/غیرفعال‌سازی -------------------------------------
wh = locations_service.create_warehouse(company_id, "WH01", "مرکزی", locations_service.WarehouseFields(
    is_default=True, warehouse_type_code="DISTRIBUTION", width_m=D(40), length_m=D(25), height_m=D(8), description="انبارِ اصلی"))
row = locations_service.get_warehouse(wh, company_id)
check(row.fields.warehouse_type_code == "DISTRIBUTION" and row.fields.width_m == 40 and row.fields.description == "انبارِ اصلی",
      "انبار با نوعِ تازه و ابعاد ساخته شد")
wl.save_warehouse_dimensions(company_id, wh, D(50), D(30), D(10), D(20000), "ویرایش‌شده")
with new_session() as s:
    w = s.get(Warehouse, wh)
    check(w.width_m == 50 and w.capacity_weight_kg == 20000 and w.capacity_volume_m3 == 15000 and w.description == "ویرایش‌شده",
          "ابعاد و ظرفیتِ انبار ویرایش شد")
check(raises(lambda: wl.save_warehouse_dimensions(company_id, wh, D(-1))), "ابعادِ منفیِ انبار رد شد")
for t in ("COLD_STORAGE", "HOT_STORAGE"):
    locations_service.create_warehouse(company_id, "W" + t[:3], t, locations_service.WarehouseFields(warehouse_type_code=t))
wtmp = locations_service.create_warehouse(company_id, "WTMP", "موقت", locations_service.WarehouseFields())
r = locations_service.get_warehouse(wtmp, company_id)
locations_service.update_warehouse(wtmp, company_id, r.code, r.name, False, r.fields)
check(not locations_service.get_warehouse(wtmp, company_id).is_active, "انبار غیرفعال شد")

# --- ۲) محل: سلسله‌مراتب، کدِ یکتا، ظرفیت، وضعیت -----------------------------------
LF = wl.LocationFields
z1 = wl.create_location(company_id, wh, "AREA", "Z01", fields=LF(name="ذخیره", location_type_code="BULK"), user_id=user.user_id)
zs = wl.create_location(company_id, wh, "AREA", "Z09", fields=LF(name="ارسال", location_type_code="SHIPPING"))
a3 = wl.create_location(company_id, wh, "AISLE", "A03", z1)
r2 = wl.create_location(company_id, wh, "RACK", "R02", a3, LF(max_weight_kg=D(500)))
l4 = wl.create_location(company_id, wh, "SHELF", "L04", r2)
b7 = wl.create_location(company_id, wh, "BIN", "B07", l4, LF(max_weight_kg=D(100), max_volume_m3=D(2)))
b8 = wl.create_location(company_id, wh, "BIN", "B08", l4, LF(max_weight_kg=D(100)))
nodes = {n.location_id: n for n in wl.tree(company_id, wh)}
check(nodes[b7].full_code == "WH01-Z01-A03-R02-L04-B07" and nodes[b7].code == "Z01-A03-R02-L04-B07" and nodes[l4].level_number == 1,
      f"کدِ کاملِ سلسله‌مراتبی ({nodes[b7].full_code})")
check(raises(lambda: wl.create_location(company_id, wh, "BIN", "b07", l4)), "کدِ تکراری رد شد")
check(raises(lambda: wl.create_location(company_id, wh, "BIN", "B99", None)), "Binِ بی‌والد رد شد")
check(raises(lambda: wl.create_location(company_id, wh, "SHELF", "L01", z1)), "والدِ نامعتبر (طبقه زیرِ منطقه) رد شد")
check(raises(lambda: wl.create_location(company_id, wh, "BIN", "B01", 999999)), "والدِ ناموجود رد شد")
check(raises(lambda: wl.create_location(company_id, wh, "BIN", "B-1", l4)), "کدِ بخش با «-» رد شد")
check(raises(lambda: wl.create_location(company_id, wh, "BIN", "B10", l4, LF(max_weight_kg=D(-5)))), "ظرفیتِ منفی رد شد")
check(raises(lambda: wl.create_location(company_id, wh, "BIN", "B11", l4, LF(status_code="BAD"))), "وضعیتِ نامعتبر رد شد")
with new_session() as s:
    raised = False
    try:
        s.execute(text("UPDATE inv.bin_locations SET max_weight_kg = -1 WHERE bin_location_id = :i"), {"i": b8}); s.commit()
    except Exception:
        raised = True
check(raised, "قیدِ پایگاه‌داده ظرفیتِ منفی را رد می‌کند")
check(wl.capacity_of(nodes[b7]) == (D(100), D(2)), "ظرفیتِ وزنی/حجمیِ محل")
f = wl.get_fields(company_id, b8); f.description = "کنارِ درب"; wl.update_location(company_id, b8, f, user.user_id)
check(wl.get_fields(company_id, b8).description == "کنارِ درب", "ویرایشِ محل")
for st in wl.STATUSES:
    wl.set_status(company_id, b8, st)
check(wl.get_fields(company_id, b8).status_code == "MAINTENANCE", "همهٔ وضعیت‌ها پذیرفته شد")
wl.set_status(company_id, b8, "ACTIVE")

# --- ۳) کالا ↔ محل (چند محل برایِ یک کالا) ----------------------------------------
def stock_doc(doc_type, item_id, qty, src=None, dst=None, cost=None):
    doc = inv_documents_service.create_stock_document(company_id, user.user_id, doc_type, today, inv_documents_service.DocumentHeaderFields(
        source_warehouse_id=src, destination_warehouse_id=dst, counterparty_detail_account_id=supplier if doc_type == "RECEIPT" else None))
    inv_documents_service.add_line(doc, company_id, inv_documents_service.LineFields(
        item_id=item_id, uom_id=pcs, quantity=D(qty), quantity_base=D(qty), unit_cost=D(cost) if cost else None))
    inv_documents_service.confirm_stock_document(doc, company_id)
    inv_documents_service.post_stock_document(doc, company_id, user.user_id)
    return doc
stock_doc("RECEIPT", g1, 60, dst=wh, cost=1000)
stock_doc("RECEIPT", g2, 10, dst=wh, cost=500)
general = locations_service.get_default_bin_location(wh).bin_location_id
doc = wl.transfer(company_id, user.user_id, g1, general, b7, D(30))
wl.transfer(company_id, user.user_id, g1, general, b8, D(10))
wl.transfer(company_id, user.user_id, g2, general, b7, D(4))
locs = {r.location_id: r for r in wl.product_locations(company_id, g1)}
check(doc and locs[b7].quantity == 30 and locs[b8].quantity == 10 and locs[general].quantity == 20 and locs[b7].bin == "B07"
      and locs[b7].rack == "R02" and locs[b7].zone == "Z01", "کالا در چند محل با زنجیرهٔ منطقه/قفسه/Bin")
cont = {(c.location_id, c.item_id): c for c in wl.contents(company_id, b7)}
check(len(cont) == 2 and cont[(b7, g2)].quantity == 4, "محتوایِ محل (چند کالا)")
check(sum(c.quantity for c in wl.contents(company_id, z1) if c.item_id == g1) == 40, "محتوایِ منطقه = جمعِ زیرمحل‌ها")
occ = wl.occupancy(company_id, wh)
check(occ[b7].weight == 60 and occ[b7].percent == 60 and occ[r2].weight == 80, f"اشغالِ وزنی و تجمیع (got {occ[b7].percent})")
check(raises(lambda: wl.transfer(company_id, user.user_id, g1, general, b7, D(30))), "عبور از ظرفیت بدونِ تایید رد شد")
check(raises(lambda: wl.transfer(company_id, user.user_id, g1, b7, b8, D(999))), "انتقالِ بیش از موجودی رد شد")
wl.set_status(company_id, b8, "BLOCKED")
check(raises(lambda: wl.transfer(company_id, user.user_id, g1, b7, b8, D(1))), "انتقال به محلِ مسدود رد شد")
wl.set_status(company_id, b8, "ACTIVE")
check(raises(lambda: wl.transfer(company_id, user.user_id, g1, b7, b8, D(0))), "مقدارِ صفر رد شد")

# --- ۴) نقشه: ذخیره/جابه‌جایی/تغییرِ اندازه/چرخش/بارگذاری ---------------------------
geo = wl.geometry(company_id, wh)
check(all(i in geo for i in (z1, a3, r2, l4, b7, b8)) and geo[l4][:4] == geo[r2][:4], "هندسهٔ پیش‌فرض برایِ همهٔ سطوح")
bx = geo[b7]; check(geo[b8][1] > bx[1] or geo[b8][0] > bx[0], "Binها سلول‌هایِ قفسه‌اند")
wl.save_geometry(company_id, r2, 120.5, 80, 50, 220, 450, user.user_id)
g = wl.geometry(company_id, wh)[r2]
check(g == (120.5, 80.0, 50.0, 220.0, 90.0), f"جابه‌جایی/اندازه/چرخش ذخیره و بازخوانی شد ({g})")
check(raises(lambda: wl.save_geometry(company_id, r2, 0, 0, 0, 10)), "اندازهٔ صفر رد شد")
f = wl.get_fields(company_id, r2); f.map_z = D("1.5"); wl.update_location(company_id, r2, f)
check(next(n for n in wl.tree(company_id, wh) if n.location_id == r2).map_z == D("1.5"), "مختصاتِ Z (سه‌بعدیِ آینده)")

from peecha.ui.screens.warehouse_map import WarehouseMapScreen
screen = WarehouseMapScreen(None); screen.refresh()
screen.load_warehouse(wh)
item = screen.items[a3]
item.setPos(item.pos().x() + 40, item.pos().y() + 10)
screen.item_geometry_changed(item)
check(abs(wl.geometry(company_id, wh)[a3][0] - (geo[a3][0] + 40)) < 0.6, "جابه‌جایی در نقشه ذخیره شد")
screen.select_location(r2); screen.rotation_spin.setValue(0); screen.apply_rotation()
check(wl.geometry(company_id, wh)[r2][4] == 0, "چرخش از صفحه ذخیره شد")
moved_x = item.pos().x()
screen.load_warehouse(wh)
check(abs(screen.items[a3].pos().x() - moved_x) < 0.6 and screen.items[r2].rotation() == 0, "بارگذاریِ دوبارهٔ نقشه با مختصاتِ ذخیره‌شده")
for i in range(screen.mode_combo.count()):
    screen.mode_combo.setCurrentIndex(i); screen.apply_mode()
check(screen.mode_combo.count() == len(wl.HEATMAP_MODES), "همهٔ حالت‌هایِ نقشه بدونِ خطا")

# --- ۵) جستجو ---------------------------------------------------------------------
res = wl.search(company_id, "G-1")
check(res.kind == "PRODUCT" and res.item_ids == [g1] and {b7, b8} <= set(res.location_ids), "جستجویِ کالا با کد")
res = wl.search(company_id, "۶۲۶۰۰۰۰۰۰۰۰۱۱")
check(res.kind == "PRODUCT" and res.item_ids == [g1], "جستجویِ بارکد (با ارقامِ فارسی)")
check(wl.search(company_id, "wh01-z01-a03-r02-l04-b07").location_ids == [b7], "جستجویِ کدِ محل")
check(wl.search(company_id, "پیچ").item_ids == [g1], "جستجویِ نامِ کالا")
check(wl.search(company_id, "ناموجود").kind == "NONE", "جستجویِ بی‌نتیجه")
screen.search("WH01-Z01-A03-R02-L04-B07")
check(screen.selected_id == b7, "جستجو در صفحه محل را انتخاب کرد")
screen.focus_item(g1)

# --- ۶) QR و بارکد ----------------------------------------------------------------
payload = wl.qr_payload(b7, nodes[b7].full_code)
check(payload == f"PEECHA-LOC:{b7}:WH01-Z01-A03-R02-L04-B07" and wl.decode_qr(company_id, payload) == b7, "تولید/خواندنِ QR")
check(wl.search(company_id, payload).location_ids == [b7], "جستجو با QR")
check(raises(lambda: wl.decode_qr(company_id, "XYZ")) and raises(lambda: wl.decode_qr(company_id, f"PEECHA-LOC:{b7}:WRONG")), "QRِ نامعتبر رد شد")
m = wl.qr_matrix(payload)
check(len(m) >= 21 and len(m) == len(m[0]) and m[0][0] == 1, "ماتریسِ QR")
import segno
check(set(wl.barcode_bits("WH01-Z01").strip("01")) == set() and wl.barcode_bits("WH01-Z01").startswith("11"), "میله‌هایِ Code128")
from peecha.ui.location_labels import label_image, print_location_labels
img = label_image(b7, nodes[b7].full_code, "Bin B07", dpi=150)
check(not img.isNull() and img.width() > 300, "تصویرِ برچسب")
from PySide6.QtPrintSupport import QPrinter
import tempfile
printer = QPrinter(QPrinter.HighResolution); printer.setOutputFormat(QPrinter.PdfFormat)
pdf = os.path.join(tempfile.mkdtemp(), "labels.pdf"); printer.setOutputFileName(pdf)
check(print_location_labels(None, [(b7, nodes[b7].full_code, ""), (b8, nodes[b8].full_code, "")], printer) and os.path.getsize(pdf) > 1000,
      "چاپِ گروهیِ برچسب (PDF)")

# --- ۷) جانمایی، مسیرِ برداشت، Heatmap، تاریخچه --------------------------------------
sug = wl.putaway_suggestions(company_id, wh, g1, D(5))
check(sug and sug[0].location_id in (b7, b8) and all(s.location_id not in (z1, a3, r2) for s in sug), f"پیشنهادِ جانمایی ({[(s.location_code, s.score) for s in sug]})")
check(all(s.location_id != b7 for s in wl.putaway_suggestions(company_id, wh, g1, D(30))), "محلِ بدونِ ظرفیت پیشنهاد نمی‌شود")
path = wl.picking_path(company_id, wh, [b8, b7, b8])
check(len(path.order) == 2 and path.distance > 0 and path.end == zs, "مسیرِ برداشت تا منطقهٔ ارسال")
check(wl.heatmap(company_id, wh, "OCCUPANCY")[b7] == 60 and wl.heatmap(company_id, wh, "VALUE")[b7] > 0, "heatmapِ اشغال/ارزش")
for mode in wl.HEATMAP_MODES:
    wl.heatmap(company_id, wh, mode)
hist = wl.history(company_id, b8)
check(any(h.kind == "ورود" for h in hist) and any(h.kind == "تغییرِ مشخصات" and "status_code" in h.detail for h in hist)
      and any(h.kind == "ایجاد" for h in wl.history(company_id, z1)), "تاریخچه = دفترِ انبار + audit")

# --- ۸) حذف/غیرفعال‌سازی -----------------------------------------------------------
tmp = wl.create_location(company_id, wh, "BIN", "B09", l4)
check(wl.delete_location(company_id, tmp) == "DELETED", "محلِ بی‌سابقه حذف شد")
check(wl.delete_location(company_id, b8) == "DEACTIVATED" and not wl.get_fields(company_id, b8).status_code == "ACTIVE", "محلِ دارایِ سابقه غیرفعال شد")
check(raises(lambda: wl.transfer(company_id, user.user_id, g1, b7, b8, D(1))), "انتقال به محلِ غیرفعال رد شد")
check(wl.delete_location(company_id, z1) == "DEACTIVATED", "محلِ دارایِ فرزند حذف نمی‌شود")

# --- ۹) فرمِ کالا و گزارش: نمایش رویِ نقشه -----------------------------------------
from peecha.ui.screens.inventory_item_panel import ItemDetailPanel
panel = ItemDetailPanel(); panel.refresh(company_id)
panel.load(next(i for i in catalog_service.list_items(company_id) if i.item_id == g1))
check(panel.locations_table.rowCount() >= 2, "زبانهٔ «محل‌هایِ انبار» در فرمِ کالا")
from peecha import nav_catalog
check("INV_WAREHOUSE_MAP" in str(nav_catalog.NAV_ITEMS) and wl.FORM_CODE in roles_service.FORM_LABELS, "منو و فرمِ دسترسیِ نقشهٔ انبار")

# --- ۱۰) دسترسی (RBAC) و API -------------------------------------------------------
clerk = users_service.create_user("clerk", "انباردار", "secret123", None, lang_id, False, [company_id], company_id)
check(screen.allowed("EDIT"), "مدیرِ ارشد دسترسیِ ویرایشِ نقشه دارد")
check(not wl.can(clerk.user_id, company_id, "VIEW"), "کاربرِ بی‌نقش دسترسی ندارد")
from fastapi.testclient import TestClient
import peecha_api.main as api_main
client = TestClient(api_main.app)
tok = lambda u: client.post("/auth/login", json={"username": u, "password": "secret123"}).json()["access_token"]  # noqa: E731
H = lambda t: {"Authorization": f"Bearer {t}"}  # noqa: E731
clerk_t, admin_t = tok("clerk"), tok("admin")
check(client.get(f"/locations/{b7}", headers=H(clerk_t)).status_code == 403, "API: بدونِ دسترسی ۴۰۳")
roles_service.ensure_catalog()
role = roles_service.create_role(company_id, "WH_VIEW", None)
form_id = next(fo.form_id for fo in roles_service.list_forms() if fo.code == wl.FORM_CODE)
roles_service.set_role_permission(role.role_id, form_id, "VIEW", True)
roles_service.set_user_role(clerk.user_id, role.role_id, company_id, True)
check(wl.can(clerk.user_id, company_id, "VIEW") and not wl.can(clerk.user_id, company_id, "EDIT"), "نقش: مشاهده بله، ویرایش نه")
resp = client.get(f"/locations/{b7}", headers=H(clerk_t))
check(resp.status_code == 200 and resp.json()["code"] == "WH01-Z01-A03-R02-L04-B07" and len(resp.json()["contents"]) == 2, "API: جزئیات و محتوایِ محل")
check(client.post("/locations/transfer", headers=H(clerk_t), json={"item_id": g1, "from_location_id": b7, "to_location_id": general,
      "quantity": "1"}).status_code == 403, "API: انتقال بدونِ EDIT ۴۰۳")
check(client.get("/locations/scan", params={"payload": payload}, headers=H(clerk_t)).json()["location_id"] == b7, "API: اسکنِ QR")
check(client.get("/locations/scan", params={"payload": "bad"}, headers=H(clerk_t)).status_code == 400, "API: QRِ نامعتبر ۴۰۰")
s_ = client.get("/locations/search", params={"q": "G-1"}, headers=H(clerk_t)).json()
check(s_["kind"] == "PRODUCT" and s_["item_ids"] == [g1], "API: جستجویِ کالا")
check(len(client.get(f"/locations/items/{g1}", headers=H(clerk_t)).json()) >= 2, "API: محل‌هایِ کالا")
mp = client.get(f"/locations/warehouses/{wh}/map", headers=H(clerk_t)).json()
check(any(n["location_id"] == r2 and n["map"]["z"] == 1.5 for n in mp), "API: نقشهٔ انبار با Z")
check(client.get("/locations/putaway-suggestions", params={"warehouse_id": wh, "item_id": g2, "quantity": "1"},
                 headers=H(clerk_t)).status_code == 200, "API: پیشنهادِ جانمایی")
resp = client.post("/locations/transfer", headers=H(admin_t), json={"item_id": g1, "from_location_id": b7, "to_location_id": general, "quantity": "5"})
check(resp.status_code == 200 and resp.json()["stock_document_id"], "API: انتقال توسطِ مدیر")
check(client.post("/locations/transfer", headers=H(admin_t), json={"item_id": g1, "from_location_id": b7, "to_location_id": b8,
      "quantity": "1"}).status_code == 400, "API: انتقال به محلِ غیرفعال ۴۰۰")

print("RESULT:", "ALL PASS" if not FAIL else "SOME FAILED")
sys.exit(1 if FAIL else 0)
