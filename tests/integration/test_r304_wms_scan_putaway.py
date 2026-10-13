"""R304: انبار پیشرفته فاز ۲ و ۳ — تایید عملیات انبار موبایل با اسکن (جانمایی، برداشت، تامین مجدد، انتقال)
و رسیدهای جانمایی‌نشده در کارتابل انباردار."""
import os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r304"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crm_fixture import *  # noqa: F401,F403
import crm_fixture as fx
from fastapi.testclient import TestClient
from sqlalchemy import func
from peecha.services import inventory_documents as inv_docs
from peecha.services import operational_tasks
from peecha.services import stock_controls as sc
from peecha.services import unit_conversion as uc
from peecha.services import warehouse_locations as wl
from peecha.services import warehouse_operations as ops
from peecha.services.workflow import inbox
from peecha.db.models.audit import ActivityLog
from peecha.db.models.inventory import BinLocation, StockBalance
check, raises = fx.check, fx.raises

g_l = A("2", "بدهی‌ها", "CREDIT", "LIABILITY", "PERMANENT", False)
k_l = A("21", "پرداختنی‌ها", "CREDIT", "LIABILITY", "PERMANENT", False, g_l.account_id)
ap_gl = A("2101", "پرداختنی تامین‌کنندگان", "CREDIT", "LIABILITY", "PERMANENT", True, k_l.account_id)
engine_service.set_account_mapping(company_id, "SUPPLIER_PAYABLE", ap_gl.account_id)
supplier = dimensions_service.create_supplier(company_id, "S1", "تامین‌کننده")
keeper = visitor.user_id
whn = locations_service.create_warehouse(company_id, "WH-N", "انبار اصلی",
                                         locations_service.WarehouseFields(manager_user_id=keeper))
zone = wl.create_location(company_id, whn, "AREA", "Z01")
rack = wl.create_location(company_id, whn, "RACK", "R01", zone)
shelf = wl.create_location(company_id, whn, "SHELF", "L01", rack)
b1, b2, b3 = [wl.create_location(company_id, whn, "BIN", f"B0{i}", shelf) for i in range(1, 4)]
carton = catalog_service.create_uom(company_id, "CTN", "کارتن", "COUNT", decimal_places=0)
uc.set_item_unit(item_a, carton, D(12))
uc.add_barcode(company_id, item_a, carton, "6260000000028")


def code_of(location_id):
    with new_session() as s:
        return s.get(BinLocation, location_id).location_code


def receipt(item, qty, bin_id=None):
    d = inv_docs.create_stock_document(company_id, uid, "RECEIPT", today, inv_docs.DocumentHeaderFields(
        destination_warehouse_id=whn, counterparty_detail_account_id=supplier))
    inv_docs.add_line(d, company_id, inv_docs.LineFields(item_id=item, uom_id=pcs, quantity=D(qty), quantity_base=D(qty),
                                                         unit_cost=D(1000), bin_location_id=bin_id))
    inv_docs.confirm_stock_document(d, company_id)
    inv_docs.post_stock_document(d, company_id, uid)
    return d


def on_hand(item, bin_id):
    with new_session() as s:
        return s.scalar(select(func.coalesce(func.sum(StockBalance.quantity_on_hand), 0)).where(
            StockBalance.item_id == item, StockBalance.bin_location_id == bin_id)) or D(0)


client = TestClient(__import__("peecha_api.main", fromlist=["app"]).app)
H = {"Authorization": "Bearer " + client.post("/auth/login", json={"username": "admin", "password": "secret123"}).json()["access_token"]}

# ===== ۱) کلیدها =====
feats = {f.feature_code: f for f in engine_service.list_features(company_id)}
check(all(feats[c].category == "WMS" and not feats[c].is_enabled for c in (sc.SCAN_CONFIRMATION, sc.PUTAWAY_IN_CARTABLE)),
      "two new switches in the WMS group, both off")
check(client.get("/locations/settings", headers=H).json() == {"scan_confirmation": False}, "mobile reads the scan switch (off)")

# ===== ۲) تطبیق برچسب =====
qr = wl.qr_payload(b1, code_of(b1))
check(wl.scan_matches_location(company_id, qr, b1) and wl.scan_matches_location(company_id, code_of(b1), b1)
      and not wl.scan_matches_location(company_id, code_of(b2), b1), "location label matches by QR or full code only for that bin")
check(wl.scan_matches_item(company_id, "6260000000028", item_a) and wl.scan_matches_item(company_id, "A1", item_a)
      and not wl.scan_matches_item(company_id, "B1", item_a) and not wl.scan_matches_item(company_id, "", item_a),
      "item label matches by code, carton barcode; another item does not")

# ===== ۳) جانمایی =====
r1 = receipt(item_a, 10, bin_id=b3)
put = ops.generate_tasks(company_id, "PUTAWAY", ("STOCK", r1), uid)
check(client.post(f"/locations/tasks/{put[0]}/putaway", headers=H, json={"to_location_id": b1}).status_code == 200,
      "switch off: putaway without scanning works (previous behaviour)")
check(on_hand(item_a, b1) == 10, "putaway moved stock")
engine_service.set_feature_enabled(company_id, sc.SCAN_CONFIRMATION, True)
check(client.get("/locations/settings", headers=H).json() == {"scan_confirmation": True}, "mobile sees the switch on")
r2 = receipt(item_a, 4, bin_id=b3)
put2 = ops.generate_tasks(company_id, "PUTAWAY", ("STOCK", r2), uid)[0]
r = client.post(f"/locations/tasks/{put2}/putaway", headers=H, json={"to_location_id": b2})
check(r.status_code == 400 and "اسکن" in r.json()["detail"], "switch on: putaway without scan is refused")
r = client.post(f"/locations/tasks/{put2}/putaway", headers=H, json={"to_location_id": b2, "scanned_location": code_of(b1)})
check(r.status_code == 400 and "نمی‌خواند" in r.json()["detail"], "scanning the wrong bin is refused")
r = client.post(f"/locations/tasks/{put2}/putaway", headers=H,
                json={"to_location_id": b2, "scanned_location": wl.qr_payload(b2, code_of(b2))})
check(r.status_code == 200 and on_hand(item_a, b2) == 4, "scanning the target bin's QR confirms the putaway")
with new_session() as s:
    log = s.scalars(select(ActivityLog).where(ActivityLog.entity_type == "WarehouseTask", ActivityLog.entity_id == put2)
                    .order_by(ActivityLog.log_id.desc())).first()
check(log.changes.get("scanned") == "True", "audit log records that the task was confirmed by scan")

# ===== ۴) برداشت =====
iss = inv_docs.create_stock_document(company_id, uid, "ISSUE", today, inv_docs.DocumentHeaderFields(source_warehouse_id=whn))
inv_docs.add_line(iss, company_id, inv_docs.LineFields(item_id=item_a, uom_id=pcs, quantity=D(3), quantity_base=D(3), bin_location_id=b1))
pick = ops.generate_tasks(company_id, "PICK", ("STOCK", iss), uid)[0]
r = client.post(f"/locations/tasks/{pick}/pick", headers=H, json={"quantity": "3", "scanned_location": code_of(b1)})
check(r.status_code == 400 and "کالا" in r.json()["detail"], "pick needs the item scan too")
r = client.post(f"/locations/tasks/{pick}/pick", headers=H,
                json={"quantity": "3", "scanned_location": code_of(b1), "scanned_item": "B1"})
check(r.status_code == 400 and "نمی‌خواند" in r.json()["detail"], "wrong item scan is refused")
r = client.post(f"/locations/tasks/{pick}/pick", headers=H,
                json={"quantity": "3", "scanned_location": code_of(b1), "scanned_item": "6260000000028"})
check(r.status_code == 200, "location + carton barcode confirm the pick")
d_put = ops.generate_tasks(company_id, "PUTAWAY", ("STOCK", receipt(item_b, 2, bin_id=b3)), uid)[0]
ops.complete_putaway(d_put, company_id, uid, b2)
check(on_hand(item_b, b2) == 2, "desktop (no scans) is not affected by the mobile switch")

# ===== ۵) تامین مجدد =====
rule = ops.save_rule(company_id, ops.RuleFields(bin_location_id=b3, item_id=item_a, min_quantity=D(1), max_quantity=D(5)))
rep = ops.generate_replenishment_tasks(company_id, uid, whn)
check(len(rep) >= 1, "replenishment task created")
r = client.post(f"/locations/tasks/{rep[0]}/replenish", headers=H, json={"scanned_from": code_of(b1)})
check(r.status_code == 400 and "مقصد" in r.json()["detail"], "replenish needs both bins scanned")
with new_session() as s:
    from peecha.db.models.inventory import WarehouseTask
    t = s.get(WarehouseTask, rep[0])
    src, dst = t.from_bin_location_id, t.to_bin_location_id
r = client.post(f"/locations/tasks/{rep[0]}/replenish", headers=H, json={"scanned_from": code_of(src), "scanned_to": code_of(dst)})
check(r.status_code == 200, "replenishment confirmed with both scans")

# ===== ۶) انتقال =====
body = {"item_id": item_a, "from_location_id": b1, "to_location_id": b2, "quantity": "1"}
r = client.post("/locations/transfer", headers=H, json={**body, "scanned_from": code_of(b1), "scanned_to": code_of(b2)})
check(r.status_code == 400 and "کالا" in r.json()["detail"], "transfer needs the item scan")
before = on_hand(item_a, b2)
r = client.post("/locations/transfer", headers=H,
                json={**body, "scanned_from": code_of(b1), "scanned_to": code_of(b2), "scanned_item": "A1"})
check(r.status_code == 200 and on_hand(item_a, b2) == before + 1, "transfer confirmed with all three scans")
engine_service.set_feature_enabled(company_id, sc.SCAN_CONFIRMATION, False)

# ===== ۷) رسیدهای جانمایی‌نشده در کارتابل انباردار =====
pending_receipt = receipt(item_b, 5, bin_id=b3)
kinds = lambda user: [t for t in operational_tasks.list_operational_tasks(company_id, user) if t.kind == "PUTAWAY_PENDING"]  # noqa: E731
check(kinds(keeper) == [] and kinds(uid) == [], "switch off: nothing in the cartable")
engine_service.set_feature_enabled(company_id, sc.PUTAWAY_IN_CARTABLE, True)
mine = kinds(keeper)
check(len(mine) == 1 and "انبار اصلی" in mine[0].title and mine[0].kind_label == "جانمایی رسیدهای انبار",
      f"warehouse keeper sees the unlocated receipts ({[t.title for t in mine]})")
check(len(kinds(uid)) == 1, "manager sees it too")
other = users_service.create_user("keeper2", "انباردار دیگر", "secret123", None, lang_id, False, [company_id], company_id)
check(kinds(other.user_id) == [], "a user who is not this warehouse's keeper does not see it")
work = [w for w in inbox.my_work(company_id, keeper) if w.source == "DOC" and w.extra.get("kind") == "PUTAWAY_PENDING"]
check(len(work) == 1 and work[0].action == "برای رسیدها وظیفهٔ جانمایی بسازید", "unified cartable shows the task with a clear action")
for src in ops.putaway_sources(company_id):
    ops.generate_tasks(company_id, "PUTAWAY", src.key, uid)
check(kinds(keeper) == [], "once putaway tasks exist it leaves the cartable")


class _MW:
    def __init__(self):
        self.opened = []

    def open_screen(self, code, then=None):
        self.opened.append(code)


from PySide6.QtWidgets import QApplication
qapp = QApplication.instance() or QApplication([])
from peecha.ui.screens.my_tasks import open_operational_task
mw = _MW()
check(open_operational_task(mw, "PUTAWAY_PENDING", "", 0) and mw.opened == ["INV_WMS_TASKS"], "opening it shows the warehouse tasks screen")

fx.finish()
