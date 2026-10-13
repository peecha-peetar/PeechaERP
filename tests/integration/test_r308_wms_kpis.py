"""R308: انبار پیشرفته فاز ۷ — شاخص‌های تکمیلی عملیات انبار از داده‌های ثبت‌شده (اسکن، کسری برداشت و علت،
رسید تا جانمایی، کنترل کیفیت، انقضا) و پرس‌وجوی پنجره‌دار داشبورد."""
import os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r308"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crm_fixture import *  # noqa: F401,F403
import crm_fixture as fx
from fastapi.testclient import TestClient
from sqlalchemy import update
from peecha.services import inventory_documents as inv_docs
from peecha.services import lot_tracking as lt
from peecha.services import quality_control as qc
from peecha.services import stock_controls as sc
from peecha.services import warehouse_locations as wl
from peecha.services import warehouse_operations as ops
from peecha.services import wms_kpis
from peecha.db.models.inventory import BinLocation, Item, WarehouseTask
check, raises = fx.check, fx.raises
TE = lt.TrackingEntry

g_l = A("2", "بدهی‌ها", "CREDIT", "LIABILITY", "PERMANENT", False)
k_l = A("21", "پرداختنی‌ها", "CREDIT", "LIABILITY", "PERMANENT", False, g_l.account_id)
ap_gl = A("2101", "پرداختنی تامین‌کنندگان", "CREDIT", "LIABILITY", "PERMANENT", True, k_l.account_id)
engine_service.set_account_mapping(company_id, "SUPPLIER_PAYABLE", ap_gl.account_id)
supplier = dimensions_service.create_supplier(company_id, "S1", "تامین‌کننده")
WF = locations_service.WarehouseFields
whq = locations_service.create_warehouse(company_id, "WH-Q", "قرنطینه", WF(warehouse_type_code="QUARANTINE"))
whn = locations_service.create_warehouse(company_id, "WH-N", "انبار اصلی", WF(default_quarantine_warehouse_id=whq))
zone = wl.create_location(company_id, whn, "AREA", "Z01")
rack = wl.create_location(company_id, whn, "RACK", "R01", zone)
shelf = wl.create_location(company_id, whn, "SHELF", "L01", rack)
b1, b2 = [wl.create_location(company_id, whn, "BIN", f"B0{i}", shelf) for i in range(1, 3)]


def code_of(location_id):
    with new_session() as s:
        return s.get(BinLocation, location_id).location_code


def receipt(item, qty, bin_id, tracking=None):
    d = inv_docs.create_stock_document(company_id, uid, "RECEIPT", today, inv_docs.DocumentHeaderFields(
        destination_warehouse_id=whn, counterparty_detail_account_id=supplier))
    line = inv_docs.add_line(d, company_id, inv_docs.LineFields(item_id=item, uom_id=pcs, quantity=D(qty), quantity_base=D(qty),
                                                                unit_cost=D(1000), bin_location_id=bin_id))
    if tracking:
        lt.set_line_tracking(company_id, tracking, stock_line_id=line)
    inv_docs.confirm_stock_document(d, company_id)
    inv_docs.post_stock_document(d, company_id, uid)
    return d, line


def pick_task(item, qty, bin_id):
    d = inv_docs.create_stock_document(company_id, uid, "ISSUE", today, inv_docs.DocumentHeaderFields(source_warehouse_id=whn))
    inv_docs.add_line(d, company_id, inv_docs.LineFields(item_id=item, uom_id=pcs, quantity=D(qty), quantity_base=D(qty),
                                                         bin_location_id=bin_id))
    return ops.generate_tasks(company_id, "PICK", ("STOCK", d), uid)[0]


switch = lambda code, on=True: engine_service.set_feature_enabled(company_id, code, on)  # noqa: E731
client = TestClient(__import__("peecha_api.main", fromlist=["app"]).app)
H = {"Authorization": "Bearer " + client.post("/auth/login", json={"username": "admin", "password": "secret123"}).json()["access_token"]}
period = lambda: wms_kpis.dashboard(company_id, today - datetime.timedelta(days=30), today, whn)  # noqa: E731
value = lambda r, code: next((v for c, _t, v, _u in r.kpis if c == code), "missing")  # noqa: E731

# ===== ۱) کلید =====
check(not sc.is_on(company_id, sc.ADVANCED_KPIS), "advanced KPI switch exists and is off")

# ===== ۲) دادهٔ واقعی عملیات =====
switch(sc.SCAN_CONFIRMATION)
switch(sc.PICK_CONTROL)
r1, _l = receipt(item_a, 20, b2)
put = ops.generate_tasks(company_id, "PUTAWAY", ("STOCK", r1), uid)[0]
check(client.post(f"/locations/tasks/{put}/putaway", headers=H,
                  json={"to_location_id": b1, "scanned_location": code_of(b1)}).status_code == 200, "putaway confirmed by scan")
t_exact = pick_task(item_a, 2, b1)
ops.complete_pick(t_exact, company_id, uid, D(2))                                     # بدون اسکن (دسکتاپ)
t_short1 = pick_task(item_a, 5, b1)
ops.complete_pick(t_short1, company_id, uid, D(3), short_reason="کارتن آسیب‌دیده")
t_short2 = pick_task(item_a, 4, b1)
ops.complete_pick(t_short2, company_id, uid, D(1), short_reason="کارتن آسیب‌دیده")
t_old = pick_task(item_a, 1, b1)
ops.complete_pick(t_old, company_id, uid, D(1))
with new_session() as s:   # وظیفهٔ قدیمی بیرون از بازهٔ ۳۰ روزه
    s.execute(update(WarehouseTask).where(WarehouseTask.task_id == t_old).values(
        completed_at=datetime.datetime.now() - datetime.timedelta(days=60)))
    s.commit()
switch(sc.RESERVATION)
switch(sc.QC_HOLD)
with new_session() as s:
    s.execute(update(Item).where(Item.item_id == item_b).values(requires_qc=True))
    s.commit()
_r2, l2 = receipt(item_b, 10, b2)
qc.inspect(company_id, l2, uid, D(4))
receipt(item_b, 3, b2)                                                                # هنوز منتظر کنترل کیفیت
med = catalog_service.create_item(company_id, "M1", "دارو", IF(item_kind_code="GOOD", base_uom_id=pcs, track_batch=True, track_expiry=True))
receipt(med, 2, b2, [TE(D(2), batch_no="OLD", expiry_date=today - datetime.timedelta(days=1))])
receipt(med, 2, b2, [TE(D(2), batch_no="SOON", expiry_date=today + datetime.timedelta(days=7))])

# ===== ۳) کلید خاموش: همان شاخص‌های قبلی =====
base = period()
check(len(base.kpis) == 12 and base.short_reasons == [], "switch off: the same 12 KPIs as before")
check(value(base, "TASKS_DONE") == 4, "windowed query: a task finished 60 days ago is not counted")
check(value(base, "PICK_ACCURACY") == 33.3, "pick accuracy unchanged (1 of 3 picks exact)")

# ===== ۴) کلید روشن =====
switch(sc.ADVANCED_KPIS)
r = period()
check(len(r.kpis) == 22, "switch on: ten more KPIs")
check(value(r, "SCAN_RATE") == 25.0, f"1 of 4 tasks confirmed by scan ({value(r, 'SCAN_RATE')})")
check(value(r, "SHORT_PICKS") == 2 and value(r, "SHORT_RATE") == 66.7, "two short picks out of three")
check(r.short_reasons == [("کارتن آسیب‌دیده", 2)], "short-pick reasons grouped")
check(value(r, "DOCK_TO_STOCK") is not None and value(r, "DOCK_TO_STOCK") >= 0, "receipt-to-putaway time measured")
check(value(r, "QC_INSPECTED") == 1 and value(r, "QC_REJECT_RATE") == 40.0 and value(r, "QC_WAIT") is not None,
      "quality control: one inspection, 4 of 10 rejected")
check(value(r, "QC_PENDING") == 1, "one receipt line still waiting for quality control")
check(value(r, "EXPIRED_LOTS") == 1 and value(r, "NEAR_EXPIRY_LOTS") == 1, "expired and near-expiry batches counted")

# ===== ۵) موبایل و دسکتاپ =====
api = client.get("/locations/kpis", params={"warehouse_id": whn}, headers=H).json()
check(any(k["code"] == "SCAN_RATE" for k in api["kpis"]) and api["short_reasons"] == [{"reason": "کارتن آسیب‌دیده", "count": 2}],
      "mobile receives the new KPIs and short-pick reasons")
from PySide6.QtWidgets import QApplication
qapp = QApplication.instance() or QApplication([])
from peecha.ui.screens.warehouse_operations import WarehouseOperationsScreen
screen = WarehouseOperationsScreen()
screen.refresh()
kt = screen.kpi_tab
kt.warehouse_combo.setCurrentIndex(kt.warehouse_combo.findData(whn))
check(not kt.reason_table.isHidden() and kt.reason_table.rowCount() == 1 and "SCAN_RATE" in kt.card_labels,
      "desktop dashboard shows the new cards and the short-pick reasons table")
switch(sc.ADVANCED_KPIS, False)
kt._load()
check(kt.reason_table.isHidden(), "reasons table hidden when the switch is off")

fx.finish()
