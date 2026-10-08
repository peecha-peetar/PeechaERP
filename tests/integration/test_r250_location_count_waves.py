import os, sys, datetime, decimal, io
os.environ["PEECHA_DB_NAME"] = "peecha_test_r250_1"
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
# R250: شمارشِ محل، موجِ برداشت، تأمینِ خودکار، API
# =====================================================================
from peecha.services import location_counts as lc
from peecha.services import stock_count as count_service
from peecha.db.models.inventory import PickWave, StockBalance

def bin_qty(bin_id, item_id):
    with new_session() as s:
        return s.scalar(select(sa_func.coalesce(sa_func.sum(StockBalance.quantity_on_hand), 0)).where(
            StockBalance.bin_location_id == bin_id, StockBalance.item_id == item_id))

post(draft("RECEIPT", milk, 7, bin_id=bulk2, dst=wh))
med = catalog_service.create_item(company_id, "T-1", "دارو", catalog_service.ItemFields(item_kind_code="GOOD", base_uom_id=pcs, track_batch=True))

# --- ۱) شمارشِ محل -------------------------------------------------------------
sid = lc.create_location_count(company_id, wh, [rb], user.user_id)
lines = {(l.location_id, l.item_id): l for l in lc.count_lines(company_id, sid)}
check(set(lines) == {(bulk1, item), (bulk2, milk)} and lines[(bulk1, item)].expected == 80 and lines[(bulk1, item)].blind,
      f"شمارش کور قفسه با موجودی دفتری هر محل ({sorted(lines)})")
check(raises(lambda: lc.create_location_count(company_id, wh, [bulk1], user.user_id)), "محل در شمارش باز دوباره شمرده نمی‌شود")
check(raises(lambda: lc.record_location_count(company_id, sid, pick1, item, D(1))), "محل خارج از دامنه رد شد")
check(raises(lambda: lc.record_location_count(company_id, sid, bulk1, med, D(1))), "کالای بچ‌دار بدون شمارهٔ بچ در شمارش محل رد شد")
check(raises(lambda: lc.record_location_count(company_id, sid, bulk1, item, D(-1))), "مقدار منفی رد شد")
check(raises(lambda: count_service.record_count(sid, company_id, item, pcs, D(1))), "انبارگردانی عادی روی شمارش محل ثبت نمی‌کند")
check(raises(lambda: count_service.finalize_count_session(sid, company_id, user.user_id)), "انبارگردانی عادی شمارش محل را نهایی نمی‌کند")
lc.record_location_count(company_id, sid, bulk1, item, D(75), user.user_id)
lc.record_location_count(company_id, sid, bulk1, item, D(77), user.user_id)  # جایگزینی
lc.record_location_count(company_id, sid, bulk1, acid, D(2), user.user_id)   # کالایِ پیدا‌شدهٔ بی‌سابقه
check(lc.mark_location_empty(company_id, sid, bulk2, user.user_id) == 1, "«محل خالی است»")
lines = {(l.location_id, l.item_id): l for l in lc.count_lines(company_id, sid)}
check(lines[(bulk1, item)].variance == -3 and lines[(bulk1, acid)].variance == 2 and lines[(bulk2, milk)].variance == -7, "اختلاف‌ها")
docs = lc.finalize_location_count(company_id, sid, user.user_id)
check(len(docs) == 2 and bin_qty(bulk1, item) == 77 and bin_qty(bulk1, acid) == 2 and bin_qty(bulk2, milk) == 0,
      "نهایی‌سازی: سند اصلاح روی همان محل‌ها")
with new_session() as s:
    from peecha.db.models.inventory import CycleCountSession
    check(s.get(CycleCountSession, sid).status_code == "POSTED", "شمارش بسته شد")
check(raises(lambda: lc.record_location_count(company_id, sid, bulk1, item, D(1))), "شمارش بسته ثبت نمی‌گیرد")
sid2 = lc.create_location_count(company_id, wh, [bulk2], user.user_id, blind=False)
lc.cancel_location_count(company_id, sid2)
check(lc.list_location_counts(company_id, open_only=True) == [], "لغو شمارش")

# --- ۲) موجِ برداشت -------------------------------------------------------------
post(draft("RECEIPT", milk, 5, bin_id=cold1, dst=wh))
issues = [draft("ISSUE", item, 1, src=wh), draft("ISSUE", milk, 1, src=wh), draft("ISSUE", acid, 1, src=wh)]
pick_ids = [ops.generate_tasks(company_id, "PICK", ("STOCK", d), user.user_id)[0] for d in issues]
wave = ops.create_wave(company_id, wh, user.user_id)
wt = ops.wave_tasks(company_id, wave)
route = wl.picking_path(company_id, wh, [t.from_bin_location_id for t in wt])
on_map = [t.from_bin_location_id for t in wt if t.from_bin_location_id in route.order]
check(sorted(t.task_id for t in wt) == sorted(pick_ids) and [t.wave_sequence for t in wt] == [1, 2, 3]
      and on_map == route.order and [t.from_bin_location_id for t in wt][:len(on_map)] == on_map,
      f"ترتیب موج = مسیر بهینه؛ محل بی‌مختصات آخر ({[t.from_bin_location_id for t in wt]} / {route.order})")
check(raises(lambda: ops.create_wave(company_id, wh, user.user_id)), "وظیفهٔ بی‌موجی نمانده")
for t in wt:
    ops.complete_pick(t.task_id, company_id, user.user_id, D(1))
with new_session() as s:
    check(s.get(PickWave, wave).status_code == "DONE", "موج با انجام همهٔ وظایف بسته شد")
extra = ops.generate_tasks(company_id, "PICK", ("STOCK", draft("ISSUE", item, 1, src=wh)), user.user_id)
w2 = ops.create_wave(company_id, wh, user.user_id, extra)
ops.release_wave(company_id, w2)
with new_session() as s:
    check(s.get(PickWave, w2).status_code == "CANCELLED" and s.get(WarehouseTask, extra[0]).wave_id is None, "لغو موج وظایف را آزاد کرد")

# --- ۳) تأمینِ خودکار پس از برداشت -----------------------------------------------
f = wl.get_fields(company_id, pick1); f.allow_replenishment = True; wl.update_location(company_id, pick1, f)
on_pick = bin_qty(pick1, item)
ops.save_rule(company_id, ops.RuleFields(pick1, item, on_pick, on_pick + 10))
before = len(ops.list_tasks(company_id, "REPLENISH"))
ops.complete_pick(extra[0], company_id, user.user_id, D(1))
check(len(ops.list_tasks(company_id, "REPLENISH")) == before + 1, "پس از برداشت، وظیفهٔ تامین خودکار ساخته شد")

# --- ۴) صفحه‌هایِ دسکتاپ -------------------------------------------------------------
from peecha.ui.screens.warehouse_operations import WarehouseOperationsScreen
screen = WarehouseOperationsScreen(); screen.refresh()
check(screen.waves_tab.waves_table.rowCount() == 2, "زبانهٔ موج‌ها")
screen.waves_tab.waves_table.selectRow([w.wave_id for w in screen.waves_tab._waves].index(wave))
check(screen.waves_tab.tasks_table.rowCount() == 3, "وظایف موج به ترتیب")
ct = screen.count_tab
ct.warehouse_combo.setCurrentIndex(ct.warehouse_combo.findData(wh))
ct.location_combo.setCurrentIndex(ct.location_combo.findData(rc))
sid3 = ct.create()
check(sid3 and ct.table.rowCount() == 1 and ct.table.item(0, 2).text() == "—", "شمارش از صفحه (کور: مقدار دفتری پنهان)")
ct.table.selectRow(0)
check(ct.record_selected(D(5)) and len(ct.finalize()) == 0, "ثبت و نهایی‌سازی بدون اختلاف از صفحه")
from peecha.ui.screens.warehouse_map import WarehouseMapScreen
mscreen = WarehouseMapScreen(None); mscreen.refresh(); mscreen.load_warehouse(wh)
mscreen.select_location(rb); mscreen.run_operation("COUNT")
check(len(lc.list_location_counts(company_id, open_only=True)) == 1, "شروع شمارش محل از نقشه")

# --- ۵) API ---------------------------------------------------------------------------
from fastapi.testclient import TestClient
import peecha_api.main as api_main
client = TestClient(api_main.app)
H = {"Authorization": "Bearer " + client.post("/auth/login", json={"username": "admin", "password": "secret123"}).json()["access_token"]}
waves = client.get("/locations/waves", params={"open_only": False}, headers=H).json()
check(any(w["wave_id"] == wave and w["done"] == 3 and w["tasks"] == 3 for w in waves), "API: موج‌ها")
api_tasks = ops.generate_tasks(company_id, "PICK", ("STOCK", draft("ISSUE", milk, 1, src=wh)), user.user_id)
r = client.post("/locations/waves", json={"warehouse_id": wh}, headers=H)
check(r.status_code == 200 and any(t["wave_id"] == r.json()["wave_id"] and t["wave_sequence"] == 1
                                   for t in client.get("/locations/tasks", params={"task_type": "PICK"}, headers=H).json()), "API: ساخت موج")
open_counts = client.get("/locations/counts", headers=H).json()
cid = open_counts[0]["session_id"]
detail = client.get(f"/locations/counts/{cid}", headers=H).json()
check(detail and all(d["expected"] is None for d in detail), "API: شمارش کور مقدار دفتری را پنهان می‌کند")
line = detail[0]
KH = dict(H, **{"Idempotency-Key": "cnt-1"})
body = {"location_id": line["location_id"], "item_id": line["item_id"], "quantity": "1"}
a = client.post(f"/locations/counts/{cid}/record", json=body, headers=KH); b = client.post(f"/locations/counts/{cid}/record", json=body, headers=KH)
check(a.status_code == 200 and a.json() == b.json(), "API: ثبت شمارش idempotent")
after = client.get(f"/locations/counts/{cid}", headers=H).json()
check(any(d["counted"] is not None and d["expected"] is not None for d in after), "API: پس از شمارش مقدار دفتری و اختلاف نمایش داده می‌شود")
check(client.post(f"/locations/counts/{cid}/record", json={**body, "quantity": "-1"}, headers=H).status_code == 400, "API: شمارش منفی ۴۰۰")
r = client.post("/locations/counts", json={"warehouse_id": wh, "location_ids": [rp]}, headers=H)
check(r.status_code == 200 and r.json()["session_id"], "API: شروع شمارش")
check(client.post("/locations/replenishment/generate", headers=H).status_code == 200, "API: تولید وظایف تامین")

print("RESULT:", "ALL PASS" if not FAIL else "SOME FAILED")
sys.exit(1 if FAIL else 0)
