"""R305: انبار پیشرفته فاز ۴ — کنترل برداشت: بیش‌برداشت ممنوع، کم‌برداشت با علت، محل برداشت با موجودی آزاد و
زودانقضاتر (محل رزرو سفارش اول)، و موج برداشت خودکار از سفارش‌های فروش رزروشده."""
import os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r305"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crm_fixture import *  # noqa: F401,F403
import crm_fixture as fx
from fastapi.testclient import TestClient
from sqlalchemy import func
from peecha.services import inventory_documents as inv_docs
from peecha.services import lot_tracking as lt
from peecha.services import stock_controls as sc
from peecha.services import warehouse_locations as wl
from peecha.services import warehouse_operations as ops
from peecha.db.models.audit import ActivityLog
from peecha.db.models.inventory import StockBalance, WarehouseTask
check, raises = fx.check, fx.raises
TE = lt.TrackingEntry

g_l = A("2", "بدهی‌ها", "CREDIT", "LIABILITY", "PERMANENT", False)
k_l = A("21", "پرداختنی‌ها", "CREDIT", "LIABILITY", "PERMANENT", False, g_l.account_id)
ap_gl = A("2101", "پرداختنی تامین‌کنندگان", "CREDIT", "LIABILITY", "PERMANENT", True, k_l.account_id)
engine_service.set_account_mapping(company_id, "SUPPLIER_PAYABLE", ap_gl.account_id)
supplier = dimensions_service.create_supplier(company_id, "S1", "تامین‌کننده")
whn = locations_service.create_warehouse(company_id, "WH-N", "انبار اصلی", locations_service.WarehouseFields())
zone = wl.create_location(company_id, whn, "AREA", "Z01")
rack = wl.create_location(company_id, whn, "RACK", "R01", zone)
shelf = wl.create_location(company_id, whn, "SHELF", "L01", rack)
b1, b2, b3, b4 = [wl.create_location(company_id, whn, "BIN", f"B0{i}", shelf) for i in range(1, 5)]
today = datetime.date.today()


def receipt(item, qty, bin_id, tracking=None):
    d = inv_docs.create_stock_document(company_id, uid, "RECEIPT", today, inv_docs.DocumentHeaderFields(
        destination_warehouse_id=whn, counterparty_detail_account_id=supplier))
    line = inv_docs.add_line(d, company_id, inv_docs.LineFields(item_id=item, uom_id=pcs, quantity=D(qty), quantity_base=D(qty),
                                                                unit_cost=D(1000), bin_location_id=bin_id))
    if tracking:
        lt.set_line_tracking(company_id, tracking, stock_line_id=line)
    inv_docs.confirm_stock_document(d, company_id)
    inv_docs.post_stock_document(d, company_id, uid)


def issue_draft(item, qty, bin_id=None):
    d = inv_docs.create_stock_document(company_id, uid, "ISSUE", today, inv_docs.DocumentHeaderFields(source_warehouse_id=whn))
    inv_docs.add_line(d, company_id, inv_docs.LineFields(item_id=item, uom_id=pcs, quantity=D(qty), quantity_base=D(qty),
                                                         bin_location_id=bin_id))
    return d


def task_of(task_id):
    with new_session() as s:
        return s.get(WarehouseTask, task_id)


switch = lambda code, on=True: engine_service.set_feature_enabled(company_id, code, on)  # noqa: E731
client = TestClient(__import__("peecha_api.main", fromlist=["app"]).app)
H = {"Authorization": "Bearer " + client.post("/auth/login", json={"username": "admin", "password": "secret123"}).json()["access_token"]}

# ===== ۱) کلید =====
check(not sc.is_on(company_id, sc.PICK_CONTROL) and client.get("/locations/settings", headers=H).json()["pick_control"] is False,
      "pick control switch exists and is off")

# ===== ۲) کنترل مقدار برداشت =====
receipt(item_a, 20, b1)
t_over = ops.generate_tasks(company_id, "PICK", ("STOCK", issue_draft(item_a, 5, b1)), uid)[0]
ops.complete_pick(t_over, company_id, uid, D(7))
check(task_of(t_over).done_quantity_base == 7, "switch off: over-pick accepted (previous behaviour)")
switch(sc.PICK_CONTROL)
check(client.get("/locations/settings", headers=H).json()["pick_control"] is True, "mobile sees the pick control switch")
t1 = ops.generate_tasks(company_id, "PICK", ("STOCK", issue_draft(item_a, 5, b1)), uid)[0]
check(raises(lambda: ops.complete_pick(t1, company_id, uid, D(6)), "بیش‌برداشت"), "over-pick refused")
check(raises(lambda: ops.complete_pick(t1, company_id, uid, D(3)), "علت کسری"), "short pick without a reason refused")
r = client.post(f"/locations/tasks/{t1}/pick", headers=H, json={"quantity": "3", "short_reason": "کارتن آسیب‌دیده"})
check(r.status_code == 200 and task_of(t1).notes == "کسری برداشت: کارتن آسیب‌دیده", "short pick with a reason is saved on the task")
with new_session() as s:
    log = s.scalars(select(ActivityLog).where(ActivityLog.entity_type == "WarehouseTask", ActivityLog.entity_id == t1)
                    .order_by(ActivityLog.log_id.desc())).first()
check(log.changes.get("short_reason") == "کارتن آسیب‌دیده", "short reason is in the audit log")
t2 = ops.generate_tasks(company_id, "PICK", ("STOCK", issue_draft(item_a, 2, b1)), uid)[0]
ops.complete_pick(t2, company_id, uid, D(2))
check(task_of(t2).status_code == "DONE", "exact pick needs no reason")

# ===== ۳) انتخاب محل برداشت: موجودی آزاد و زودانقضا =====
med = catalog_service.create_item(company_id, "E1", "دارو", IF(item_kind_code="GOOD", base_uom_id=pcs, track_batch=True, track_expiry=True))
receipt(med, 5, b2, [TE(D(5), batch_no="LATE", expiry_date=today + datetime.timedelta(days=300))])
receipt(med, 5, b3, [TE(D(5), batch_no="SOON", expiry_date=today + datetime.timedelta(days=20))])
receipt(med, 5, b4, [TE(D(5), batch_no="DEAD", expiry_date=today - datetime.timedelta(days=1))])
t3 = ops.generate_tasks(company_id, "PICK", ("STOCK", issue_draft(med, 2)), uid)[0]
check(task_of(t3).from_bin_location_id == b3, "pick bin = earliest non-expired batch (expired bin skipped)")
ops.cancel_task(t3, company_id, uid)
t_res = ops.generate_tasks(company_id, "PICK", ("STOCK", issue_draft(med, 5, b3)), uid)[0]  # کل محل b3 رزرو شد
t4 = ops.generate_tasks(company_id, "PICK", ("STOCK", issue_draft(med, 2)), uid)[0]
check(task_of(t4).from_bin_location_id == b2, "a fully reserved bin is skipped; next free bin chosen")
for t in (t_res, t4):
    ops.cancel_task(t, company_id, uid)

# ===== ۴) موج از سفارش‌های رزروشده =====
switch(sc.SALES_ORDER_RESERVATION)
receipt(item_b, 10, b4)


def order(q):
    o = documents_service.create_document(company_id, uid, "SALES_ORDER", today, documents_service.DocumentHeaderFields(
        counterparty_detail_account_id=cust_a, currency_id=company.base_currency_id, warehouse_id=whn, channel_code=channel_code))
    documents_service.add_line(o, company_id, item_id=item_b, uom_id=pcs, quantity=D(q), quantity_base=D(q), unit_price=D(10))
    documents_service.confirm_document(o, company_id, uid)
    return o


so1, so2 = order(3), order(4)
with new_session() as s:
    reserved_b4 = s.scalar(select(func.sum(StockBalance.quantity_reserved)).where(StockBalance.item_id == item_b,
                                                                                   StockBalance.bin_location_id == b4))
check(reserved_b4 == 7, "two confirmed orders reserve 7 in bin B04")
wave = ops.create_wave(company_id, whn, uid)
tasks = ops.wave_tasks(company_id, wave)
comm = {t.source_commercial_document_id for t in tasks if t.source_commercial_document_id}
check(comm == {so1, so2} and all(t.from_bin_location_id == b4 for t in tasks if t.source_commercial_document_id),
      "creating a wave builds pick tasks for reserved orders, from the reserved bin")
with new_session() as s:
    reserved_b4 = s.scalar(select(func.sum(StockBalance.quantity_reserved)).where(StockBalance.item_id == item_b,
                                                                                   StockBalance.bin_location_id == b4))
check(reserved_b4 == 7, "order picks do not double-reserve the stock")
check(ops.generate_picks_for_reserved_orders(company_id, uid, whn) == [], "no duplicate pick tasks on the next wave")

fx.finish()
