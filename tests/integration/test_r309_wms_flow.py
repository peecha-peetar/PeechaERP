"""R309: انبار پیشرفته فاز ۸ — انتقال دومرحله‌ای از راه انبار ترانزیت، پیشنهاد چیدمان (کلاس ABC دفعات خروج)
و ارسال مستقیم از رسید برای سفارش‌های فروش منتظر."""
import os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r309"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crm_fixture import *  # noqa: F401,F403
import crm_fixture as fx
from sqlalchemy import func
from peecha.services import cross_dock
from peecha.services import inventory_documents as inv_docs
from peecha.services import lot_tracking as lt
from peecha.services import operational_tasks
from peecha.services import slotting
from peecha.services import stock_controls as sc
from peecha.services import stock_reservations
from peecha.services import transit_transfer
from peecha.services import warehouse_locations as wl
from peecha.services import warehouse_operations as ops
from peecha.db.models.inventory import LotMovement, Batch, StockBalance, StockDocument, StockDocumentLine, WarehouseTask
check, raises = fx.check, fx.raises
TE = lt.TrackingEntry
LF = wl.LocationFields

g_l = A("2", "بدهی‌ها", "CREDIT", "LIABILITY", "PERMANENT", False)
k_l = A("21", "پرداختنی‌ها", "CREDIT", "LIABILITY", "PERMANENT", False, g_l.account_id)
ap_gl = A("2101", "پرداختنی تامین‌کنندگان", "CREDIT", "LIABILITY", "PERMANENT", True, k_l.account_id)
engine_service.set_account_mapping(company_id, "SUPPLIER_PAYABLE", ap_gl.account_id)
supplier = dimensions_service.create_supplier(company_id, "S1", "تامین‌کننده")
keeper = visitor.user_id
WF = locations_service.WarehouseFields
wha = locations_service.create_warehouse(company_id, "WH-A", "انبار مرکزی", WF())
whb = locations_service.create_warehouse(company_id, "WH-B", "انبار شعبه", WF(manager_user_id=keeper, allow_negative_stock=True))


def receipt(item, qty, warehouse, bin_id=None, tracking=None):
    d = inv_docs.create_stock_document(company_id, uid, "RECEIPT", today, inv_docs.DocumentHeaderFields(
        destination_warehouse_id=warehouse, counterparty_detail_account_id=supplier))
    line = inv_docs.add_line(d, company_id, inv_docs.LineFields(item_id=item, uom_id=pcs, quantity=D(qty), quantity_base=D(qty),
                                                                unit_cost=D(1000), bin_location_id=bin_id))
    if tracking:
        lt.set_line_tracking(company_id, tracking, stock_line_id=line)
    inv_docs.confirm_stock_document(d, company_id)
    inv_docs.post_stock_document(d, company_id, uid)
    return d, line


def stock(item, warehouse, bin_id=None):
    with new_session() as s:
        q = select(func.coalesce(func.sum(StockBalance.quantity_on_hand), 0)).where(
            StockBalance.item_id == item, StockBalance.warehouse_id == warehouse)
        if bin_id is not None:
            q = q.where(StockBalance.bin_location_id == bin_id)
        return s.scalar(q) or D(0)


switch = lambda code, on=True: engine_service.set_feature_enabled(company_id, code, on)  # noqa: E731
kinds = lambda user: {t.kind: t for t in operational_tasks.list_operational_tasks(company_id, user)}  # noqa: E731

# ===== ۱) کلیدها =====
feats = {f.feature_code: f for f in engine_service.list_features(company_id)}
check(all(feats[c].category == "WMS" and not feats[c].is_enabled for c in (sc.TWO_STEP_TRANSFER, sc.SLOTTING, sc.CROSS_DOCK)),
      "three new switches in the WMS group, all off")
check(raises(lambda: switch(sc.CROSS_DOCK), "ابتدا"), "cross-dock needs sales-order reservation first")

# ===== ۲) انتقال دومرحله‌ای =====
med = catalog_service.create_item(company_id, "M1", "دارو", IF(item_kind_code="GOOD", base_uom_id=pcs, track_batch=True))
receipt(item_a, 20, wha)
receipt(med, 5, wha, tracking=[TE(D(3), batch_no="L1"), TE(D(2), batch_no="L2")])
draft = inv_docs.create_stock_document(company_id, uid, "TRANSFER", today, inv_docs.DocumentHeaderFields(
    source_warehouse_id=wha, destination_warehouse_id=whb))
inv_docs.add_line(draft, company_id, inv_docs.LineFields(item_id=item_a, uom_id=pcs, quantity=D(10), quantity_base=D(10)))
med_line = inv_docs.add_line(draft, company_id, inv_docs.LineFields(item_id=med, uom_id=pcs, quantity=D(5), quantity_base=D(5)))
lt.set_line_tracking(company_id, [TE(D(3), batch_no="L1"), TE(D(2), batch_no="L2")], stock_line_id=med_line)
check(raises(lambda: transit_transfer.send(company_id, uid, draft), "خاموش"), "switch off: two-step send refused")
switch(sc.TWO_STEP_TRANSFER)
check(raises(lambda: transit_transfer.send(company_id, uid, draft), "ترانزیت"), "needs a transit warehouse")
wht = locations_service.create_warehouse(company_id, "WH-T", "در راه", WF(warehouse_type_code="TRANSIT"))
transit_transfer.send(company_id, uid, draft)
with new_session() as s:
    d = s.get(StockDocument, draft)
check(d.status_code == "POSTED" and d.destination_warehouse_id == wht and stock(item_a, wha) == 10 and stock(item_a, wht) == 10
      and stock(item_a, whb) == 0, "step 1: goods left the source and are in transit")
ship = transit_transfer.in_transit(company_id)
check(len(ship) == 1 and ship[0].destination_warehouse_id == whb and {ln.item_id: ln.remaining for ln in ship[0].lines} == {item_a: 10, med: 5},
      "the shipment is listed as in transit to the branch")
check("TRANSIT_ARRIVING" in kinds(keeper) and "انبار شعبه" in kinds(keeper)["TRANSIT_ARRIVING"].title,
      "destination keeper sees the arriving shipment")
check(raises(lambda: transit_transfer.receive(company_id, uid, draft, {item_a: D(11)}), "بین"), "cannot receive more than in transit")
transit_transfer.receive(company_id, uid, draft, {item_a: D(7)})
check(stock(item_a, whb) == 7 and stock(item_a, wht) == 3, "step 2: partial receipt, the rest stays in transit")
left = {ln.item_id: ln.remaining for ln in transit_transfer.in_transit(company_id)[0].lines}
check(left == {item_a: 3, med: 5}, f"remaining in transit tracked per item ({left})")
transit_transfer.receive(company_id, uid, draft)
with new_session() as s:
    lots = dict(s.execute(select(Batch.batch_no, func.sum(LotMovement.quantity_base)).join(Batch, Batch.batch_id == LotMovement.batch_id)
                          .where(LotMovement.item_id == med, LotMovement.warehouse_id == whb).group_by(Batch.batch_no)).all())
check(stock(item_a, whb) == 10 and stock(med, whb) == 5 and lots == {"L1": 3, "L2": 2}, "rest received with the same batches")
check(transit_transfer.in_transit(company_id) == [] and "TRANSIT_ARRIVING" not in kinds(keeper), "nothing left in transit")

# ===== ۳) پیشنهاد چیدمان =====
whs = locations_service.create_warehouse(company_id, "WH-S", "انبار فروشگاه", WF())
pick_zone = wl.create_location(company_id, whs, "AREA", "PZ", fields=LF(location_type_code="PICK_FACE"))
res_zone = wl.create_location(company_id, whs, "AREA", "RZ", fields=LF(location_type_code="RESERVE"))
p_shelf = wl.create_location(company_id, whs, "SHELF", "L1", wl.create_location(company_id, whs, "RACK", "K1", pick_zone))
r_shelf = wl.create_location(company_id, whs, "SHELF", "L1", wl.create_location(company_id, whs, "RACK", "K1", res_zone))
p1, p2 = [wl.create_location(company_id, whs, "BIN", c, p_shelf) for c in ("P1", "P2")]
r1, r2 = [wl.create_location(company_id, whs, "BIN", c, r_shelf) for c in ("R1", "R2")]
fast = catalog_service.create_item(company_id, "F1", "پرگردش", IF(item_kind_code="GOOD", base_uom_id=pcs))
mid = catalog_service.create_item(company_id, "F2", "متوسط", IF(item_kind_code="GOOD", base_uom_id=pcs))
slow = catalog_service.create_item(company_id, "F3", "کم‌گردش", IF(item_kind_code="GOOD", base_uom_id=pcs))
receipt(fast, 100, whs, r1)
receipt(mid, 10, whs, r2)
receipt(slow, 10, whs, p1)
iss = inv_docs.create_stock_document(company_id, uid, "ISSUE", today, inv_docs.DocumentHeaderFields(source_warehouse_id=whs))
for _ in range(18):
    inv_docs.add_line(iss, company_id, inv_docs.LineFields(item_id=fast, uom_id=pcs, quantity=D(1), quantity_base=D(1), bin_location_id=r1))
for item, b in ((mid, r2), (slow, p1)):
    inv_docs.add_line(iss, company_id, inv_docs.LineFields(item_id=item, uom_id=pcs, quantity=D(1), quantity_base=D(1), bin_location_id=b))
inv_docs.confirm_stock_document(iss, company_id)
inv_docs.post_stock_document(iss, company_id, uid)
sug = {s_.item_id: s_ for s_ in slotting.suggestions(company_id, whs)}
check(set(sug) == {fast, slow}, f"suggestions only for the misplaced items ({set(sug)})")
check(sug[fast].abc_class == "A" and sug[fast].to_location_id in (p1, p2) and sug[fast].from_location_id == r1,
      "fast item stored in reserve -> move to a pick face")
check(sug[slow].abc_class == "C" and sug[slow].to_location_id in (r1, r2) and sug[slow].from_location_id == p1,
      "slow item in a pick face -> move to reserve")
move = slotting.create_move_draft(company_id, uid, whs, sug[fast])
with new_session() as s:
    md = s.get(StockDocument, move)
    ml = s.scalars(select(StockDocumentLine).where(StockDocumentLine.stock_document_id == move)).one()
check(md.status_code == "DRAFT" and ml.bin_location_id == r1 and ml.destination_bin_location_id == sug[fast].to_location_id
      and ml.quantity_base == 82 and stock(fast, whs, r1) == 82, "a draft move is prepared; nothing moves until the user posts")

# ===== ۴) ارسال مستقیم از رسید =====
switch(sc.SALES_ORDER_RESERVATION)
switch(sc.CROSS_DOCK)
so = documents_service.create_document(company_id, uid, "SALES_ORDER", today, documents_service.DocumentHeaderFields(
    counterparty_detail_account_id=cust_a, currency_id=company.base_currency_id, warehouse_id=whb, channel_code=channel_code))
documents_service.add_line(so, company_id, item_id=item_b, uom_id=pcs, quantity=D(6), quantity_base=D(6), unit_price=D(10))
documents_service.confirm_document(so, company_id, uid)                     # بدون موجودی: رزرو نشد
rcv, rcv_line = receipt(item_b, 10, whb)
opps = cross_dock.opportunities(company_id)
check(len(opps) == 1 and opps[0].line_id == rcv_line and opps[0].free == 10 and opps[0].demand == 6 and opps[0].quantity == 6,
      "the new receipt matches the waiting sales order")
check("CROSS_DOCK" in kinds(keeper), "keeper sees the cross-dock chance in the cartable")
tasks = cross_dock.execute(company_id, uid, rcv_line)
with new_session() as s:
    t = s.get(WarehouseTask, tasks[0])
    bin_in = t.from_bin_location_id
    reserved = stock_reservations.order_line_reserved(s, t.source_commercial_line_id)
check(len(tasks) == 1 and t.source_commercial_document_id == so and reserved == 6, "order reserved from the receiving bin with a pick task")
put = ops.generate_tasks(company_id, "PUTAWAY", ("STOCK", rcv), uid)
with new_session() as s:
    pq = s.get(WarehouseTask, put[0]).quantity_base
check(pq == 4, f"putaway only for the 4 not going straight out ({pq})")
check(cross_dock.opportunities(company_id) == [] and "CROSS_DOCK" not in kinds(keeper), "no more cross-dock chance")

# ===== ۵) دسکتاپ =====
from PySide6.QtWidgets import QApplication, QPushButton
qapp = QApplication.instance() or QApplication([])
from peecha.ui.screens.warehouse_operations import WarehouseOperationsScreen
switch(sc.SLOTTING)
screen = WarehouseOperationsScreen()
screen.refresh()
check(screen.tabs.isTabVisible(screen.tabs.indexOf(screen.transit_tab)) and screen.tabs.isTabVisible(screen.tabs.indexOf(screen.flow_tab)),
      "transit and flow tabs visible when their switches are on")
ft = screen.flow_tab
ft.warehouse_combo.setCurrentIndex(ft.warehouse_combo.findData(whs))
check(ft.slot_table.rowCount() == 2, "desktop lists the slotting suggestions")
check(all(len(b.text()) <= 2 for b in screen.transit_tab.findChildren(QPushButton) + ft.findChildren(QPushButton)),
      "new tabs use icon buttons")
switch(sc.TWO_STEP_TRANSFER, False)
screen.refresh()
check(not screen.tabs.isTabVisible(screen.tabs.indexOf(screen.transit_tab)), "transit tab hidden when its switch is off")

fx.finish()
