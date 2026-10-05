import os, sys, datetime, decimal, io
os.environ["PEECHA_DB_NAME"] = "peecha_test_r252_1"
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
# R252: نقشه با ابعادِ واقعی، حذفِ زیرشاخه، سریال به محل، شمارشِ سریال، کنترلِ بها،
#       گزارش‌ها، انتخابِ خودکارِ محلِ خروج، اثرِ رزرو بر موجودیِ آزاد، API
# =====================================================================
from peecha.services import location_counts as lc
from peecha.db.models.inventory import SerialNumber, StockBalance, StockDocumentLine as SDL
TE = lt.TrackingEntry

def bal(bin_id, item_id):
    with new_session() as s:
        b = s.scalar(select(StockBalance).where(StockBalance.bin_location_id == bin_id, StockBalance.item_id == item_id))
        return (b.quantity_on_hand, b.quantity_reserved, b.quantity_available) if b else (D(0), D(0), D(0))

# --- ۱) نقشه با ابعادِ واقعی ---------------------------------------------------------
w10 = locations_service.create_warehouse(company_id, "W10", "ده‌در‌پنج", locations_service.WarehouseFields(width_m=D(10), length_m=D(5)))
za = wl.create_location(company_id, w10, "AREA", "Z01")
zb_ = wl.create_location(company_id, w10, "AREA", "Z02", fields=LF(width_m=D(3), length_m=D(4)))
aa = wl.create_location(company_id, w10, "AISLE", "A01", za)
ra = wl.create_location(company_id, w10, "RACK", "R01", za)
geo = wl.geometry(company_id, w10)
inside = lambda g, box: g[0] >= box[0] - 0.01 and g[1] >= box[1] - 0.01 and g[0] + g[2] <= box[0] + box[2] + 0.01 and g[1] + g[3] <= box[1] + box[3] + 0.01  # noqa: E731
check(all(inside(geo[i], (0, 0, 200, 100)) for i in (za, zb_)), f"منطقه‌ها داخلِ انبارِ ۱۰×۵ متر ({geo[za]}, {geo[zb_]})")
check(geo[zb_][2:4] == (60.0, 80.0), "منطقه با ابعادِ واقعیِ ۳×۴ متر رسم می‌شود")
check(geo[zb_][0] >= geo[za][0] + geo[za][2], "منطقهٔ دوم کنارِ اولی است (بدونِ هم‌پوشانی)")
check(inside(geo[aa], geo[za]) and inside(geo[ra], geo[za]) and geo[ra][0] >= geo[aa][0] + geo[aa][2], "راهرو و قفسه داخلِ منطقه و کنارِ هم")
nodes = {n.location_id: n for n in wl.tree(company_id, w10)}
check(nodes[za].width_m and nodes[za].length_m, "ابعادِ متریِ پیش‌فرض ثبت شد")
f = wl.get_fields(company_id, za); f.width_m, f.length_m = D(6), D(4); wl.update_location(company_id, za, f)
check(wl.geometry(company_id, w10)[za][2:4] == (120.0, 80.0), "ویرایشِ ابعاد فوراً رویِ نقشه")
wl.save_geometry(company_id, zb_, 140, 10, 50, 60)
check(wl.get_fields(company_id, zb_).width_m == D("2.5") and wl.get_fields(company_id, zb_).length_m == 3, "تغییرِ اندازه در نقشه ابعادِ متری را به‌روز می‌کند")
from peecha.ui.screens.warehouse_map import WarehouseMapScreen
screen = WarehouseMapScreen(None); screen.refresh(); screen.load_warehouse(wh)
check(not any(i.node.level == "SHELF" for i in screen.items.values()), "طبقه لایهٔ نامرئیِ رویِ قفسه نمی‌سازد")
screen.fit()
check(all(not i.isVisible() for i in screen.items.values() if i.node.level == "BIN") or screen.view.transform().m11() >= 1.4,
      "Binها در زومِ کم کلیک را نمی‌گیرند")
screen.zoom(20)
check(all(i.isVisible() for i in screen.items.values() if i.node.level == "BIN"), "Binها با بزرگ‌نمایی دیده می‌شوند")
# حذف/غیرفعال‌سازیِ زیرشاخه
sh = wl.create_location(company_id, w10, "SHELF", "L01", ra)
wl.create_location(company_id, w10, "BIN", "B01", sh)
n_before = len(wl.tree(company_id, w10))
check(wl.delete_location(company_id, za) == "DELETED" and len(wl.tree(company_id, w10)) == n_before - 5, "حذفِ منطقه همراهِ همهٔ زیرمحل‌ها")
check(wl.delete_location(company_id, zb) == "DEACTIVATED" and all(not n.is_active for n in wl.tree(company_id, wh)
      if n.location_id in wl.descendants(wl.tree(company_id, wh), zb)), "منطقهٔ دارایِ موجودی: کلِ زیرشاخه غیرفعال")
screen.load_warehouse(wh)
check(zb not in screen.items and bulk1 not in screen.items, "محل‌هایِ غیرفعال از نقشه پنهان‌اند")
screen.show_inactive_check.setChecked(True)
check(zb in screen.items, "با «نمایشِ غیرفعال‌ها» دیده می‌شوند")
# بازگرداندن برایِ ادامهٔ تست
for lid in wl.descendants(wl.tree(company_id, wh), zb):
    wl.set_status(company_id, lid, "ACTIVE")

# --- ۲) سریال به تفکیکِ محل -------------------------------------------------------
phone = catalog_service.create_item(company_id, "P-1", "گوشی", catalog_service.ItemFields(item_kind_code="GOOD", base_uom_id=pcs, track_serial=True))
def serial_receipt(serials, bin_id):
    doc = draft("RECEIPT", phone, len(serials), bin_id=bin_id, dst=wh)
    with new_session() as s:
        line_id = s.scalar(select(SDL.line_id).where(SDL.stock_document_id == doc))
    lt.set_line_tracking(company_id, [TE(D(1), serial_no=x) for x in serials], stock_line_id=line_id)
    return post(doc)
serial_receipt(["S1", "S2"], pick1)
serial_receipt(["S3"], pick2)
check(lc.expected_serials(company_id, pick1, phone) == ["S1", "S2"] and lc.expected_serials(company_id, pick2, phone) == ["S3"],
      "سریال‌ها محلِ فعلیِ خود را دارند")
tr = draft("TRANSFER", phone, 1, bin_id=pick1, dst_bin=bulk2, src=wh, dst=wh)
with new_session() as s:
    tl = s.scalar(select(SDL.line_id).where(SDL.stock_document_id == tr))
lt.set_line_tracking(company_id, [TE(D(1), serial_no="S2")], stock_line_id=tl)
post(tr)
check(lc.expected_serials(company_id, bulk2, phone) == ["S2"] and lc.expected_serials(company_id, pick1, phone) == ["S1"],
      "انتقال محلِ سریال را جابه‌جا می‌کند")
check({c.item_id: c for c in wl.contents(company_id, bulk2)}[phone].serials == "S2", "محتوایِ محل سریال‌ها را نشان می‌دهد")
with new_session() as s:
    s.execute(text("UPDATE inv.serial_numbers SET current_bin_location_id = NULL WHERE item_id = :i"), {"i": phone}); s.commit()
sql = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "db", "schema", "189_wms_serial_bins_reserved.sql"), encoding="utf-8").read()
with new_session() as s:
    s.execute(text(sql[sql.index("UPDATE inv.serial_numbers"):sql.index("UPDATE inv.stock_balance")])); s.commit()
check(lc.expected_serials(company_id, bulk2, phone) == ["S2"] and lc.expected_serials(company_id, pick2, phone) == ["S3"],
      "پرکردنِ محلِ سریال‌هایِ قدیمی (migration 189)")

# --- ۳) شمارشِ سریال ---------------------------------------------------------------
sid = lc.create_location_count(company_id, wh, [rp], user.user_id)
check(any(l.serial and l.item_id == phone for l in lc.count_lines(company_id, sid)), "کالایِ سریال‌دار در شمارشِ محل")
check(raises(lambda: lc.record_location_count(company_id, sid, pick1, phone, D(1))), "سریال‌دار فقط با اسکنِ سریال")
lc.record_serial_count(company_id, sid, pick1, phone, ["S1", "S3", "NEW-9"], user.user_id)   # S3 از pick2 به این‌جا آمده
lc.record_serial_count(company_id, sid, pick2, phone, [], user.user_id)
docs = lc.finalize_location_count(company_id, sid, user.user_id)
check(lc.expected_serials(company_id, pick1, phone) == ["NEW-9", "S1", "S3"] and lc.expected_serials(company_id, pick2, phone) == [],
      f"سریال: جابه‌جاشده منتقل، ناشناخته مازاد ({lc.expected_serials(company_id, pick1, phone)})")
check(bal(pick1, phone)[0] == 3 and bal(pick2, phone)[0] == 0 and len(docs) == 2, "موجودیِ محل‌ها با سریال‌ها یکی است")
sid_b = lc.create_location_count(company_id, wh, [pick1], user.user_id)
lc.record_serial_count(company_id, sid_b, pick1, phone, ["S1", "S3"], user.user_id)
lc.finalize_location_count(company_id, sid_b, user.user_id)
with new_session() as s:
    check(s.scalar(select(SerialNumber.status_code).where(SerialNumber.serial_no == "NEW-9")) != "IN_STOCK"
          and bal(pick1, phone)[0] == 2, "سریالِ گم‌شده کسری خورد")

# --- ۴) بررسیِ بها هنگامِ ثبتِ شمارش -------------------------------------------------
nocost = catalog_service.create_item(company_id, "NC-1", "بی‌بها", catalog_service.ItemFields(item_kind_code="GOOD", base_uom_id=pcs))
sid2 = lc.create_location_count(company_id, wh, [bulk2], user.user_id)
try:
    lc.record_location_count(company_id, sid2, bulk2, nocost, D(5), user.user_id); msg = ""
except ValueError as exc:
    msg = str(exc)
check("بها" in msg and "بی‌بها" in msg, f"مازادِ کالایِ بی‌بها همان لحظهٔ ثبت رد شد ({msg})")
lc.cancel_location_count(company_id, sid2)

# --- ۵) گزارش‌ها -------------------------------------------------------------------
from peecha.services import purchase_reports as pr
import dataclasses
F = pr.PurchaseFilters(today - datetime.timedelta(days=30), today, side="INVENTORY")
run = lambda code, **o: pr.run_report(company_id, code, dataclasses.replace(F, options=o))  # noqa: E731
check(any(r[3] == "WH01-Z02-R02-L01-B01" for r in run("LOCATION_COUNTS").rows), "گزارشِ شمارش‌هایِ محل")
check(run("LOCATION_COUNTS", view="DIFF").rows and all(r[8] for r in run("LOCATION_COUNTS", view="DIFF").rows), "فقط ردیف‌هایِ دارایِ اختلاف")
waves_id = ops.create_wave(company_id, wh, user.user_id, ops.generate_tasks(company_id, "PICK", ("STOCK", draft("ISSUE", item, 1, src=wh)), user.user_id))
check(any(r[0].startswith("WAVE-") and r[4] == 1 for r in run("WAVES").rows), "گزارشِ موج‌ها")
ops.save_rule(company_id, ops.RuleFields(pick1, item, D(100), D(120)))
check(any(r[8] == "نیازِ بی‌وظیفه" for r in run("REPLENISH_TASKS").rows), "گزارشِ تأمینِ مجدد (نیازِ بی‌وظیفه)")
drug = catalog_service.create_item(company_id, "D-1", "شربت", catalog_service.ItemFields(item_kind_code="GOOD", base_uom_id=pcs, track_batch=True))
rd = draft("RECEIPT", drug, 4, bin_id=bulk1, dst=wh)
with new_session() as s:
    rl = s.scalar(select(SDL.line_id).where(SDL.stock_document_id == rd))
lt.set_line_tracking(company_id, [TE(D(4), batch_no="B-9", expiry_date=today + datetime.timedelta(days=5))], stock_line_id=rl)
post(rd)
bb = [r for r in run("BIN_BATCH_STOCK").rows if r[3] == "B-9"]
check(len(bb) == 1 and bb[0][1] == "WH01-Z01-R01-L01-B01" and bb[0][5] == 5 and bb[0][6] == 4, "گزارشِ بچ به تفکیکِ محل")
from peecha.ui.screens.purchase_reports import PurchaseReportScreen
rep = PurchaseReportScreen("BIN_BATCH_STOCK", None, side="INVENTORY"); rep.refresh()
check(rep._location_in_row(bb[0]) == bulk1, "«نمایش روی نقشه» محلِ ردیف را تشخیص می‌دهد")

# --- ۶) انتخابِ خودکارِ محلِ خروج --------------------------------------------------
with new_session() as s:
    gen_qty = s.scalar(select(sa_func.coalesce(sa_func.sum(StockBalance.quantity_on_hand), 0)).where(
        StockBalance.bin_location_id == general, StockBalance.item_id == drug))
check(gen_qty == 0, "شربت در محلِ پیش‌فرض موجودی ندارد")
iss = draft("ISSUE", drug, 2, src=wh)
check(wl.assign_outbound_bins(company_id, iss) == [(1, "WH01-Z01-R01-L01-B01")], "محلِ دارایِ موجودی برایِ ردیفِ بی‌محل انتخاب شد")
post(iss)
check(bal(bulk1, drug)[0] == 2 and wl.bin_batches(company_id, wh, drug)[(bulk1, drug)][0].quantity == 2, "خروج از همان محل و همان بچ")
iss2 = draft("ISSUE", item, 1, src=wh)
with new_session() as s:
    gq = s.scalar(select(sa_func.sum(StockBalance.quantity_on_hand)).where(StockBalance.bin_location_id == general, StockBalance.item_id == item)) or 0
check(gq < 1 or wl.assign_outbound_bins(company_id, iss2) == [], "محلِ پیش‌فرضِ دارایِ موجودی دست نمی‌خورد")
plain_wh = locations_service.create_warehouse(company_id, "WP", "ساده", locations_service.WarehouseFields(allow_negative_stock=True))
post(draft("RECEIPT", item, 5, dst=plain_wh))
check(wl.assign_outbound_bins(company_id, draft("ISSUE", item, 9, src=plain_wh)) == [], "انبارِ بی‌نقشه رفتارِ قبلی را دارد")

# --- ۷) رزروِ وظیفه و موجودیِ آزاد ----------------------------------------------------
before = bal(pick1, item)
pk = ops.generate_tasks(company_id, "PICK", ("STOCK", draft("ISSUE", item, 2, bin_id=pick1, src=wh)), user.user_id)
after = bal(pick1, item)
check(after[1] == before[1] + 2 and after[2] == before[2] - 2, f"رزروِ وظیفه موجودیِ آزاد را کم کرد ({before} → {after})")
from fastapi.testclient import TestClient
import peecha_api.main as api_main
client = TestClient(api_main.app)
H = {"Authorization": "Bearer " + client.post("/auth/login", json={"username": "admin", "password": "secret123"}).json()["access_token"]}
cat = client.get("/products/catalog", params={"warehouse_id": wh}, headers=H)
check(cat.status_code == 200, "کاتالوگِ موبایل (موجودیِ آزاد) پاسخ می‌دهد")
ops.cancel_task(pk[0], company_id)
check(bal(pick1, item) == before, "لغوِ وظیفه رزرو را از موجودیِ آزاد برداشت")
pk2 = ops.generate_tasks(company_id, "PICK", ("STOCK", draft("ISSUE", item, 1, bin_id=pick1, src=wh)), user.user_id)
ops.complete_pick(pk2[0], company_id, user.user_id, D(1))
check(bal(pick1, item)[1] == before[1], "تکمیلِ برداشت رزرو را آزاد کرد")

# --- ۸) API و صفحه‌ها -----------------------------------------------------------------
sid3 = client.post("/locations/counts", json={"warehouse_id": wh, "location_ids": [pick1]}, headers=H).json()["session_id"]
det = client.get(f"/locations/counts/{sid3}", headers=H).json()
check(any(d["serial"] and d["expected_serials"] is None for d in det), "API: شمارشِ کور سریال‌هایِ مورد انتظار را پنهان می‌کند")
KH = dict(H, **{"Idempotency-Key": "ser-1"})
body = {"location_id": pick1, "item_id": phone, "serial_nos": ["S1", "S3"]}
a = client.post(f"/locations/counts/{sid3}/serials", json=body, headers=KH); b = client.post(f"/locations/counts/{sid3}/serials", json=body, headers=KH)
check(a.status_code == 200 and a.json() == b.json(), "API: ثبتِ سریال‌ها idempotent")
r_ = post(draft("RECEIPT", item, 3, dst=wh))
srcs = client.get("/locations/putaway-sources", headers=H).json()
check(any(x["document_id"] == r_ for x in srcs), "API: رسیدهایِ بی‌وظیفه")
gen = client.post("/locations/tasks/generate", json={"document_id": r_}, headers=H).json()
check(len(gen["task_ids"]) == 1, "API: ساختِ وظیفهٔ جانمایی از موبایل")
labels = client.get(f"/locations/{rp}/labels", headers=H).json()
check(len(labels) == len(wl.descendants(wl.tree(company_id, wh), rp)) and all(l["qr_svg"].startswith("<svg") for l in labels),
      "API: برچسبِ همهٔ زیرمحل‌ها")
from peecha.ui.screens.warehouse_operations import WarehouseOperationsScreen
ops_screen = WarehouseOperationsScreen(); ops_screen.refresh()
ct = ops_screen.count_tab
ct.session_combo.setCurrentIndex(ct.session_combo.findData(sid3))
row = next(i for i, l in enumerate(ct._lines) if l.serial)
ct.table.selectRow(row)
check(ct.record_selected(["S1"]) and any(l.serial and l.counted == 1 for l in lc.count_lines(company_id, sid3)), "ثبتِ سریال از صفحهٔ دسکتاپ")

print("RESULT:", "ALL PASS" if not FAIL else "SOME FAILED")
sys.exit(1 if FAIL else 0)
