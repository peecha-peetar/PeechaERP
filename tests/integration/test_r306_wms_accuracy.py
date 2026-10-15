"""R306: انبار پیشرفته فاز ۵ — دقت موجودی: تطبیق شمارش محل با حرکت‌های حین شمارش، و نگه‌داشت رسید تامین‌کننده
تا تایید کنترل کیفیت (مقدار ردشده با سند انتقال به قرنطینه)."""
import os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r306"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crm_fixture import *  # noqa: F401,F403
import crm_fixture as fx
from sqlalchemy import func, update
from peecha.services import inventory_documents as inv_docs
from peecha.services import location_counts as lc
from peecha.services import lot_tracking as lt
from peecha.services import operational_tasks
from peecha.services import quality_control as qc
from peecha.services import stock_controls as sc
from peecha.services import warehouse_locations as wl
from peecha.services import warehouse_operations as ops
from peecha.services.workflow import inbox
from peecha.db.models.audit import ActivityLog
from peecha.db.models.inventory import Batch, Item, LotMovement, QcInspection, StockBalance, StockDocument, StockDocumentLine
check, raises = fx.check, fx.raises
TE = lt.TrackingEntry

g_l = A("2", "بدهی‌ها", "CREDIT", "LIABILITY", "PERMANENT", False)
k_l = A("21", "پرداختنی‌ها", "CREDIT", "LIABILITY", "PERMANENT", False, g_l.account_id)
ap_gl = A("2101", "پرداختنی تامین‌کنندگان", "CREDIT", "LIABILITY", "PERMANENT", True, k_l.account_id)
engine_service.set_account_mapping(company_id, "SUPPLIER_PAYABLE", ap_gl.account_id)
adj_gl = A("512", "اختلاف انبار", "DEBIT", "EXPENSE", "TEMPORARY", True, k5.account_id)
engine_service.set_account_mapping(company_id, "INVENTORY_ADJUSTMENT_GAIN", adj_gl.account_id)
engine_service.set_account_mapping(company_id, "INVENTORY_ADJUSTMENT_LOSS", adj_gl.account_id)
supplier = dimensions_service.create_supplier(company_id, "S1", "تامین‌کننده")
keeper = visitor.user_id
WF = locations_service.WarehouseFields
whn = locations_service.create_warehouse(company_id, "WH-N", "انبار اصلی", WF(manager_user_id=keeper))
whq = locations_service.create_warehouse(company_id, "WH-Q", "انبار قرنطینه", WF(warehouse_type_code="QUARANTINE"))
whc = locations_service.create_warehouse(company_id, "WH-C", "انبار دارو", WF(requires_qc=True))
zone = wl.create_location(company_id, whn, "AREA", "Z01")
rack = wl.create_location(company_id, whn, "RACK", "R01", zone)
shelf = wl.create_location(company_id, whn, "SHELF", "L01", rack)
b1, b2 = [wl.create_location(company_id, whn, "BIN", f"B0{i}", shelf) for i in range(1, 3)]


def receipt(item, qty, bin_id=None, tracking=None, warehouse=None, from_supplier=True):
    d = inv_docs.create_stock_document(company_id, uid, "RECEIPT", today, inv_docs.DocumentHeaderFields(
        destination_warehouse_id=warehouse or whn, counterparty_detail_account_id=supplier if from_supplier else None))
    line = inv_docs.add_line(d, company_id, inv_docs.LineFields(item_id=item, uom_id=pcs, quantity=D(qty), quantity_base=D(qty),
                                                                unit_cost=D(1000), bin_location_id=bin_id))
    if tracking:
        lt.set_line_tracking(company_id, tracking, stock_line_id=line)
    inv_docs.confirm_stock_document(d, company_id)
    inv_docs.post_stock_document(d, company_id, uid)
    return d, line


def issue(item, qty, bin_id=None, warehouse=None):
    d = inv_docs.create_stock_document(company_id, uid, "ISSUE", today,
                                       inv_docs.DocumentHeaderFields(source_warehouse_id=warehouse or whn))
    inv_docs.add_line(d, company_id, inv_docs.LineFields(item_id=item, uom_id=pcs, quantity=D(qty), quantity_base=D(qty),
                                                         bin_location_id=bin_id))
    inv_docs.confirm_stock_document(d, company_id)
    inv_docs.post_stock_document(d, company_id, uid)
    return d


def stock(item, warehouse, field="quantity_on_hand"):
    with new_session() as s:
        return s.scalar(select(func.coalesce(func.sum(getattr(StockBalance, field)), 0)).where(
            StockBalance.item_id == item, StockBalance.warehouse_id == warehouse)) or D(0)


def set_requires_qc(item):
    with new_session() as s:
        s.execute(update(Item).where(Item.item_id == item).values(requires_qc=True))
        s.commit()


switch = lambda code, on=True: engine_service.set_feature_enabled(company_id, code, on)  # noqa: E731

# ===== ۱) کلیدها =====
feats = {f.feature_code: f for f in engine_service.list_features(company_id)}
check(all(feats[c].category == "WMS" and not feats[c].is_enabled for c in (sc.COUNT_RECONCILE, sc.QC_HOLD)),
      "two new switches in the WMS group, both off")
check(raises(lambda: switch(sc.QC_HOLD), "ابتدا"), "QC hold needs the reservation control first")

# ===== ۲) تطبیق شمارش محل با حرکت‌های حین شمارش =====
receipt(item_a, 10, b1)
receipt(item_b, 6, b2)
count = lc.create_location_count(company_id, whn, [shelf], uid, blind=False)
issue(item_a, 3, b1)        # حین شمارش از محل B01 خارج شد
lc.record_location_count(company_id, count, b1, item_a, D(7), uid)
lc.record_location_count(company_id, count, b2, item_b, D(5), uid)   # کسری واقعی
line_a = lambda: next(ln for ln in lc.count_lines(company_id, count) if ln.item_id == item_a)  # noqa: E731
check(line_a().variance == -3, "switch off: the issue during counting looks like a shortage (previous behaviour)")
switch(sc.COUNT_RECONCILE)
la = line_a()
check(la.variance == 0 and la.moved == -3, f"switch on: issue during counting is reconciled (moved {la.moved}, variance {la.variance})")
lb = next(ln for ln in lc.count_lines(company_id, count) if ln.item_id == item_b)
check(lb.variance == -1 and lb.moved == 0, "a real shortage is still found")
docs = lc.finalize_location_count(company_id, count, uid)
check(len(docs) == 1 and stock(item_a, whn) == 7 and stock(item_b, whn) == 5,
      "finalize posts only the real shortage; book stock matches the shelf")
with new_session() as s:
    desc = s.scalar(select(StockDocumentLine.description).where(StockDocumentLine.stock_document_id == docs[0]))
check("حرکت حین شمارش" not in (desc or "") and "دفتری 6" in (desc or ""), "adjustment line explains the count")
count2 = lc.create_location_count(company_id, whn, [b1], uid, blind=False)
receipt(item_a, 4, b1)
lc.record_location_count(company_id, count2, b1, item_a, D(11), uid)
docs2 = lc.finalize_location_count(company_id, count2, uid)
check(docs2 == [] and stock(item_a, whn) == 11, "a receipt during counting does not create a fake surplus")

# ===== ۳) نگه‌داشت رسید تا تایید کیفیت =====
med = catalog_service.create_item(company_id, "M1", "داروی الف", IF(item_kind_code="GOOD", base_uom_id=pcs, is_sellable=True))
set_requires_qc(med)
receipt(med, 5, b1)
check(qc.list_pending(company_id) == [] and stock(med, whn, "quantity_reserved") == 0, "switch off: receipt is free (previous behaviour)")
issue(med, 5, b1)
switch(sc.RESERVATION)
switch(sc.QC_HOLD)
r1, l1 = receipt(med, 10, b1)
pend = qc.list_pending(company_id)
check(len(pend) == 1 and pend[0].line_id == l1 and pend[0].quantity == 10 and pend[0].supplier_name == "تامین‌کننده",
      "supplier receipt of a QC item waits for quality control")
check(stock(med, whn) == 10 and stock(med, whn, "quantity_reserved") == 10, "stock is on hand but fully held")
check(raises(lambda: issue(med, 1, b1), "رزرو"), "held stock cannot be issued")
check(all(src.doc.stock_document_id != r1 for src in ops.putaway_sources(company_id))
      and ops.generate_tasks(company_id, "PUTAWAY", ("STOCK", r1), uid) == [], "no putaway before quality control")
receipt(med, 2, b2, from_supplier=False)
check(len(qc.list_pending(company_id)) == 1, "a receipt without a supplier is not held")
receipt(item_b, 3, warehouse=whc)
check(any(p.item_id == item_b and p.warehouse_id == whc for p in qc.list_pending(company_id)),
      "a warehouse marked 'needs quality control' holds every supplier receipt")

# کارتابل
mine = [t for t in operational_tasks.list_operational_tasks(company_id, keeper) if t.kind == "QC_PENDING"]
check(len(mine) == 1 and "انبار اصلی" in mine[0].title, "keeper of the warehouse sees the QC task in the cartable")
work = [w for w in inbox.my_work(company_id, keeper) if w.source == "DOC" and w.extra.get("kind") == "QC_PENDING"]
check(len(work) == 1 and work[0].action == "نتیجهٔ کنترل کیفیت رسیدها را ثبت کنید", "unified cartable shows a clear action")

# بازرسی با رد بخشی
check(raises(lambda: qc.inspect(company_id, l1, uid, D(11), whq), "بیشتر"), "cannot reject more than held")
check(raises(lambda: qc.inspect(company_id, l1, uid, D(4)), "قرنطینه"), "rejecting needs a quarantine/scrap warehouse")
check(raises(lambda: qc.inspect(company_id, l1, uid, D(4), whc), "قرنطینه یا ضایعات نیست"), "target must be quarantine or scrap")
res = qc.inspect(company_id, l1, uid, D(4), whq, D(2), "بسته‌بندی آسیب‌دیده")
check(res.result_code == "PARTIAL" and res.transfer_stock_document_id, "partial acceptance with a transfer document")
check(stock(med, whn) == 8 and stock(med, whq) == 4 and stock(med, whn, "quantity_reserved") == 0,
      "rejected 4 moved to quarantine, accepted 6 (+2 earlier) free in the main warehouse")
with new_session() as s:
    ins = s.scalar(select(QcInspection).where(QcInspection.stock_document_line_id == l1))
    tr = s.get(StockDocument, res.transfer_stock_document_id)
    status = s.get(StockDocumentLine, l1).quality_status_code
    log = s.scalars(select(ActivityLog).where(ActivityLog.entity_type == "QcInspection")).first()
check(ins.result_code == "PARTIAL" and ins.rejected_quantity == 4 and ins.sampled_quantity == 2 and ins.notes == "بسته‌بندی آسیب‌دیده",
      "inspection result is recorded (source for the purchase quality report)")
check(tr.document_type_code == "TRANSFER" and tr.status_code == "POSTED" and tr.destination_warehouse_id == whq,
      "rejected stock left with a normal posted transfer")
check(status == "APPROVED" and log is not None and log.changes.get("operation") == "QC_INSPECT", "line status and audit log updated")
issue(med, 6, b1)
check(stock(med, whn) == 2, "accepted stock can be issued")
check(any(src.doc.stock_document_id == r1 for src in ops.putaway_sources(company_id)), "after quality control the receipt can be put away")
check(raises(lambda: qc.inspect(company_id, l1, uid), "منتظر"), "an inspected line cannot be inspected twice")

# بچ‌دار: بچ‌های ردشده همان بچ‌های رسید
lot_item = catalog_service.create_item(company_id, "M2", "داروی بچ‌دار", IF(item_kind_code="GOOD", base_uom_id=pcs, track_batch=True,
                                                                            track_expiry=True))
set_requires_qc(lot_item)
exp = today + datetime.timedelta(days=200)
_r, l2 = receipt(lot_item, 5, b2, [TE(D(3), batch_no="L1", expiry_date=exp), TE(D(2), batch_no="L2", expiry_date=exp)])
qc.inspect(company_id, l2, uid, D(4), whq)
with new_session() as s:
    q_lots = dict(s.execute(select(Batch.batch_no, func.sum(LotMovement.quantity_base)).join(Batch, Batch.batch_id == LotMovement.batch_id)
                            .where(LotMovement.item_id == lot_item, LotMovement.warehouse_id == whq).group_by(Batch.batch_no)).all())
check(q_lots == {"L1": 3, "L2": 1}, f"rejected batches go to quarantine in receipt order ({q_lots})")

# برگشت رسید منتظر کیفیت
r3, l3 = receipt(med, 3, b1)
inv_docs.reverse_and_cancel_stock_document(r3, company_id, uid)
check(all(p.line_id != l3 for p in qc.list_pending(company_id)) and stock(med, whn, "quantity_reserved") == 0,
      "cancelling a held receipt releases its hold")

# دسکتاپ
from PySide6.QtWidgets import QApplication
qapp = QApplication.instance() or QApplication([])
from peecha.ui.screens.warehouse_operations import WarehouseOperationsScreen
screen = WarehouseOperationsScreen()
screen.refresh()
tab = screen.quality_tab
check(screen.tabs.isTabVisible(screen.tabs.indexOf(tab)) and tab.table.rowCount() == 1, "desktop quality tab lists the waiting line")
check(all(b.text() not in ("پذیرش کامل", "ثبت نتیجهٔ بازرسی") for b in tab.findChildren(__import__("PySide6.QtWidgets", fromlist=["QPushButton"]).QPushButton)),
      "quality tab buttons are icons")
tab.table.selectRow(0)
check(tab.approve_selected() and tab.table.rowCount() == 0 and stock(item_b, whc, "quantity_reserved") == 0,
      "full approval from the desktop frees the stock")
count_headers = [screen.count_tab.table.horizontalHeaderItem(i).text() for i in range(screen.count_tab.table.columnCount())]
check("حرکت حین شمارش" in count_headers, "location count shows the movement-during-count column")

fx.finish()
