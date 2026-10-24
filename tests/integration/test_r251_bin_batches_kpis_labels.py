import os, sys, datetime, decimal, io
os.environ["PEECHA_DB_NAME"] = "peecha_test_r251_1"
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
# R251: بچ به تفکیکِ محل، شمارشِ محلِ بچ‌دار، داشبوردِ عملیات، برچسب
# =====================================================================
from peecha.services import location_counts as lc
from peecha.services import wms_kpis
from peecha.db.models.inventory import LotMovement
TE = lt.TrackingEntry
drug = catalog_service.create_item(company_id, "D-1", "شربت", catalog_service.ItemFields(
    item_kind_code="GOOD", base_uom_id=pcs, track_batch=True, track_expiry=True))
early, late = today + datetime.timedelta(days=10), today + datetime.timedelta(days=100)

def tracked_receipt(qty, bin_id, batch_no, expiry):
    doc = draft("RECEIPT", drug, qty, bin_id=bin_id, dst=wh)
    with new_session() as s:
        from peecha.db.models.inventory import StockDocumentLine as SDL
        line_id = s.scalar(select(SDL.line_id).where(SDL.stock_document_id == doc))
    lt.set_line_tracking(company_id, [TE(D(qty), batch_no=batch_no, expiry_date=expiry)], stock_line_id=line_id)
    return post(doc)
tracked_receipt(10, bulk1, "B-EARLY", early)
tracked_receipt(10, pick1, "B-LATE", late)

# --- ۱) بچ به تفکیکِ محل ---------------------------------------------------------
bb = wl.bin_batches(company_id, wh, drug)
check([(x.batch_no, x.quantity) for x in bb[(bulk1, drug)]] == [("B-EARLY", 10)] and
      [(x.batch_no, x.quantity) for x in bb[(pick1, drug)]] == [("B-LATE", 10)], "ورود بچ با محل همان ردیف ثبت شد")
issue = post(draft("ISSUE", drug, 4, bin_id=pick1, src=wh))
with new_session() as s:
    from peecha.db.models.inventory import StockDocumentLine as SDL
    moves = list(s.scalars(select(LotMovement).join(SDL, SDL.line_id == LotMovement.stock_document_line_id)
                           .where(SDL.stock_document_id == issue)))
check(len(moves) == 1 and moves[0].bin_location_id == pick1 and moves[0].batch_id ==
      next(x.batch_id for x in bb[(pick1, drug)]), "خروج از محل، بچ همان محل را برداشت (نه زودانقضای محل دیگر)")
check(wl.bin_batches(company_id, wh, drug)[(pick1, drug)][0].quantity == 6, "ماندهٔ بچ در محل")
cont = {c.item_id: c for c in wl.contents(company_id, bulk1)}
check(cont[drug].batches == "B-EARLY" and cont[drug].expiry == early, "محتوای محل: بچ و انقضای همان محل")
cont = {c.item_id: c for c in wl.contents(company_id, pick1)}
check(cont[drug].batches == "B-LATE" and cont[drug].expiry == late, "محتوای محل دیگر: بچ خودش")
wl.transfer(company_id, user.user_id, drug, bulk1, bulk2, D(5))
bb = wl.bin_batches(company_id, wh, drug)
check(bb[(bulk2, drug)][0].batch_no == "B-EARLY" and bb[(bulk2, drug)][0].quantity == 5 and bb[(bulk1, drug)][0].quantity == 5,
      "انتقال بین محل‌ها بچ را با خود می‌برد")
exp = wl.heatmap(company_id, wh, "EXPIRY")
check(exp[bulk2] == 10 and exp[pick1] == 100, f"نقشهٔ انقضا به تفکیک محل ({exp.get(bulk2)}, {exp.get(pick1)})")
# پرکردنِ سوابق از دفترِ انبار (همان دستورِ migration)
with new_session() as s:
    s.execute(text("UPDATE inv.lot_movements SET bin_location_id = NULL WHERE item_id = :i"), {"i": drug}); s.commit()
check(wl.bin_batches(company_id, wh, drug) == {}, "بدون ستون محل، بچ به محل نسبت داده نمی‌شود")
sql = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "db", "schema", "188_lot_movements_bin.sql"), encoding="utf-8").read()
update_sql = sql[sql.index("UPDATE inv.lot_movements"):sql.index("CREATE INDEX")]
with new_session() as s:
    s.execute(text(update_sql)); s.commit()
check({k: [(x.batch_no, x.quantity) for x in v] for k, v in wl.bin_batches(company_id, wh, drug).items()} ==
      {k: [(x.batch_no, x.quantity) for x in v] for k, v in bb.items()}, "پرکردن سوابق از دفتر انبار همان نتیجه را می‌دهد")

# --- ۲) شمارشِ محلِ بچ‌دار ---------------------------------------------------------
sid = lc.create_location_count(company_id, wh, [rb], user.user_id)
lines = {(l.location_id, l.item_id, l.batch_no): l for l in lc.count_lines(company_id, sid)}
check(lines[(bulk1, drug, "B-EARLY")].expected == 5 and lines[(bulk2, drug, "B-EARLY")].expected == 5 and (bulk1, item, None) in lines,
      "ردیف شمارش به تفکیک بچ در هر محل")
check(raises(lambda: lc.record_location_count(company_id, sid, bulk1, drug, D(5))), "کالای بچ‌دار بدون شمارهٔ بچ رد شد")
check(raises(lambda: lc.record_location_count(company_id, sid, bulk1, drug, D(5), batch_no="NOPE")), "بچ ناشناخته رد شد")
lc.record_location_count(company_id, sid, bulk1, drug, D(3), user.user_id, "B-EARLY")
lc.record_location_count(company_id, sid, bulk2, drug, D(1), user.user_id, "B-LATE")  # بچِ پیدا‌شده در محلِ دیگر
lc.record_location_count(company_id, sid, bulk2, drug, D(5), user.user_id, "B-EARLY")
docs = lc.finalize_location_count(company_id, sid, user.user_id)
bb = wl.bin_batches(company_id, wh, drug)
check(len(docs) == 2 and [(x.batch_no, x.quantity) for x in bb[(bulk1, drug)]] == [("B-EARLY", 3)]
      and sorted((x.batch_no, x.quantity) for x in bb[(bulk2, drug)]) == [("B-EARLY", 5), ("B-LATE", 1)],
      "اصلاح اختلاف به تفکیک بچ و محل")

# --- ۳) داشبوردِ عملیات ------------------------------------------------------------
ids = ops.generate_tasks(company_id, "PICK", ("STOCK", draft("ISSUE", item, 2, src=wh)), user.user_id)
ops.start_task(ids[0], company_id, user.user_id)
ops.complete_pick(ids[0], company_id, user.user_id, D(2))
ids2 = ops.generate_tasks(company_id, "PICK", ("STOCK", draft("ISSUE", item, 3, src=wh)), user.user_id)
ops.complete_pick(ids2[0], company_id, user.user_id, D(2))
ops.generate_tasks(company_id, "PICK", ("STOCK", draft("ISSUE", item, 1, src=wh)), user.user_id)
r = wms_kpis.dashboard(company_id, today - datetime.timedelta(days=30), today, wh)
k = {c: v for c, _t, v, _u in r.kpis}
check(len(r.kpis) == 12 and k["TASKS_DONE"] == 2 and k["TASKS_OPEN"] == 1 and k["PICK_ACCURACY"] == 50, f"شاخص‌های وظایف ({k})")
check(k["COUNT_LINES"] == 3 and k["COUNT_ACCURACY"] == 33.3 and k["LOCATION_USE"] is not None and k["FULL_LOCATIONS"] >= 0,
      f"شاخص‌های شمارش و محل ({k['COUNT_LINES']}, {k['COUNT_ACCURACY']})")
check(r.by_type["PICK"].done == 2 and r.by_type["PICK"].open == 1 and r.operators[user.user_id].picks == 2, "به تفکیک نوع و اپراتور")
from peecha.ui.screens.warehouse_operations import WarehouseOperationsScreen
screen = WarehouseOperationsScreen(); screen.refresh()
check(len(screen.kpi_tab.card_labels) == 12 and screen.kpi_tab.operator_table.rowCount() == 1, "زبانهٔ داشبورد عملیات")
screen.count_tab.refresh()

# --- ۴) API: شاخص‌ها، برچسب، شمارشِ بچ ------------------------------------------------
from fastapi.testclient import TestClient
import peecha_api.main as api_main
client = TestClient(api_main.app)
H = {"Authorization": "Bearer " + client.post("/auth/login", json={"username": "admin", "password": "secret123"}).json()["access_token"]}
kp = client.get("/locations/kpis", params={"days": 30}, headers=H).json()
check(len(kp["kpis"]) == 12 and any(t["type"] == "PICK" for t in kp["by_type"]), "API: داشبورد عملیات")
lab = client.get(f"/locations/{bulk1}/label", headers=H).json()
check(lab["code"] == "WH01-Z01-R01-L01-B01" and lab["qr_svg"].startswith("<svg") and lab["barcode_svg"].count("<rect") > 20
      and lab["qr_payload"] == wl.qr_payload(bulk1, lab["code"]), "API: برچسب محل (QR و بارکد)")
check(client.get("/locations/999999/label", headers=H).status_code == 400, "API: برچسب محل نامعتبر")
sid2 = lc.create_location_count(company_id, wh, [bulk1], user.user_id)
det = client.get(f"/locations/counts/{sid2}", headers=H).json()
check(any(d["batch_no"] == "B-EARLY" for d in det), "API: شمارهٔ بچ در ردیف شمارش")
r = client.post(f"/locations/counts/{sid2}/record", json={"location_id": bulk1, "item_id": drug, "quantity": "3", "batch_no": "B-EARLY"}, headers=H)
check(r.status_code == 200 and any(l.batch_no == "B-EARLY" and l.counted == 3 for l in lc.count_lines(company_id, sid2)), "API: ثبت شمارش بچ")

print("RESULT:", "ALL PASS" if not FAIL else "SOME FAILED")
sys.exit(1 if FAIL else 0)
