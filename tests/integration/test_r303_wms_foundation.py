"""R303: انبار پیشرفته فاز ۱ — ثبت یک‌تراکنشی، کلیدهای کنترل انبار (رزرو، رزرو سفارش، وضعیت محل، انقضا،
دسترسی انبار، دسترسی موبایل)، ایندکس یکتای وظایف، ثبت رویداد و صفحهٔ تنظیمات."""
import os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r303"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crm_fixture import *  # noqa: F401,F403
import crm_fixture as fx
from sqlalchemy import func
from fastapi.testclient import TestClient
from peecha.services import inventory_documents as inv_docs
from peecha.services import lot_tracking as lt
from peecha.services import roles as roles_service
from peecha.services import stock_controls as sc
from peecha.services import stock_reservations as sr
from peecha.services import warehouse_locations as wl
from peecha.services import warehouse_operations as ops
from peecha.db.models.audit import ActivityLog
from peecha.db.models.inventory import Batch, LotMovement, StockBalance, StockDocument, StockDocumentLine, StockLedger, \
    StockReservation, WarehouseTask
check, raises = fx.check, fx.raises
TE = lt.TrackingEntry

g_l = A("2", "بدهی‌ها", "CREDIT", "LIABILITY", "PERMANENT", False)
k_l = A("21", "پرداختنی‌ها", "CREDIT", "LIABILITY", "PERMANENT", False, g_l.account_id)
ap_gl = A("2101", "پرداختنی تامین‌کنندگان", "CREDIT", "LIABILITY", "PERMANENT", True, k_l.account_id)
adj_gl = A("512", "کسری و اضافی انبار", "DEBIT", "EXPENSE", "TEMPORARY", True, k5.account_id)
engine_service.set_account_mapping(company_id, "SUPPLIER_PAYABLE", ap_gl.account_id)
engine_service.set_account_mapping(company_id, "INVENTORY_ADJUSTMENT_LOSS", adj_gl.account_id)
engine_service.set_account_mapping(company_id, "INVENTORY_ADJUSTMENT_GAIN", adj_gl.account_id)
supplier = dimensions_service.create_supplier(company_id, "S1", "تامین‌کننده")
WF = locations_service.WarehouseFields
whn = locations_service.create_warehouse(company_id, "WH-N", "انبار اصلی", WF(allow_negative_stock=False))
scrap = locations_service.create_warehouse(company_id, "WH-S", "انبار ضایعات", WF(warehouse_type_code="SCRAP"))
zone = wl.create_location(company_id, whn, "AREA", "Z01")
rack = wl.create_location(company_id, whn, "RACK", "R01", zone)
shelf = wl.create_location(company_id, whn, "SHELF", "L01", rack)
b1, b2, b3, b4, b5 = [wl.create_location(company_id, whn, "BIN", f"B0{i}", shelf) for i in range(1, 6)]
adj_reason = inv_docs.create_reason_code(company_id, "ADJUSTMENT", "CNT", "شمارش")


def doc(doc_type, item, qty, bin_id=None, dst_bin=None, src=None, dst=None, user=uid, tracking=None, reason=None):
    d = inv_docs.create_stock_document(company_id, user, doc_type, today, inv_docs.DocumentHeaderFields(
        source_warehouse_id=src, destination_warehouse_id=dst,
        counterparty_detail_account_id=supplier if doc_type == "RECEIPT" else None))
    line = inv_docs.add_line(d, company_id, inv_docs.LineFields(
        item_id=item, uom_id=pcs, quantity=D(qty), quantity_base=D(qty), unit_cost=D(1000) if doc_type == "RECEIPT" else None,
        bin_location_id=bin_id, destination_bin_location_id=dst_bin, reason_code_id=reason))
    if tracking:
        lt.set_line_tracking(company_id, tracking, stock_line_id=line)
    inv_docs.confirm_stock_document(d, company_id)
    return d


def post(d, user=uid, **kw):
    return inv_docs.post_stock_document(d, company_id, user, **kw)


def qty(column, item, bin_id):
    with new_session() as s:
        return s.scalar(select(func.coalesce(func.sum(column), 0)).where(
            StockBalance.item_id == item, StockBalance.bin_location_id == bin_id)) or D(0)


on_hand = lambda item, bin_id: qty(StockBalance.quantity_on_hand, item, bin_id)  # noqa: E731
reserved = lambda item, bin_id: qty(StockBalance.quantity_reserved, item, bin_id)  # noqa: E731


def switch(code, on=True):
    engine_service.set_feature_enabled(company_id, code, on)


def audit_rows(entity_type, entity_id):
    with new_session() as s:
        return list(s.scalars(select(ActivityLog).where(ActivityLog.entity_type == entity_type, ActivityLog.entity_id == entity_id)
                              .order_by(ActivityLog.log_id)))


# ===== ۱) کلیدها در تنظیمات، همه خاموش =====
feats = {f.feature_code: f for f in engine_service.list_features(company_id)}
check(all(c in feats and feats[c].category == "WMS" and not feats[c].is_enabled for c in sc.ALL), "six WMS switches exist, all off")
desc = engine_service.feature_descriptions()
check(all(desc[c] for c in sc.ALL) and "FEFO" not in feats["FEFO_ALLOCATION"].name and "Bin" not in feats["BIN_LOCATIONS"].name,
      "every switch has a plain Persian description")
check(raises(lambda: switch(sc.WAREHOUSE_ACCESS), "ابتدا باید"), "warehouse access enforcement needs the access tab feature first")

# ===== ۲) ثبت یک‌تراکنشی =====
post(doc("RECEIPT", item_a, 10, bin_id=b1, dst=whn))
d = doc("ISSUE", item_a, 4, bin_id=b1, src=whn)
original = lt.apply_after_post_in
lt.apply_after_post_in = lambda *a, **k: (_ for _ in ()).throw(ValueError("خطای آزمایشی"))
check(raises(lambda: post(d), "خطای آزمایشی"), "a failure after the engine step is reported")
lt.apply_after_post_in = original
with new_session() as s:
    ledger = s.scalar(select(func.count()).select_from(StockLedger).join(
        StockDocumentLine, StockDocumentLine.line_id == StockLedger.stock_document_line_id).where(StockDocumentLine.stock_document_id == d))
    sd = s.get(StockDocument, d)
    check(sd.status_code == "CONFIRMED" and sd.journal_entry_id is None and ledger == 0 and on_hand(item_a, b1) == 10,
          "nothing half-posted: document, ledger, balance and journal all rolled back")
post(d)
check(on_hand(item_a, b1) == 6, "same document posts normally afterwards")
rows = audit_rows("StockDocument", d)
check(len(rows) == 1 and rows[0].action == "EXECUTE" and rows[0].changes["operation"] == "POST", "posting is in the audit log once")

# ===== ۳) خروج فقط از موجودی آزاد (رزرو) =====
post(doc("RECEIPT", item_a, 7, bin_id=b1, dst=whn))  # 13
pick_doc = doc("ISSUE", item_a, 5, bin_id=b1, src=whn)
task_ids = ops.generate_tasks(company_id, "PICK", ("STOCK", pick_doc), uid)
check(len(task_ids) == 1 and reserved(item_a, b1) == 5, "pick task reserves 5 in the bin")
post(doc("ISSUE", item_a, 3, bin_id=b1, src=whn))
check(on_hand(item_a, b1) == 10, "switch off: reserved stock can still be issued (previous behaviour)")
switch(sc.RESERVATION)
blocked = doc("ISSUE", item_a, 6, bin_id=b1, src=whn)
check(raises(lambda: post(blocked), "رزرو شده"), "switch on: issuing into another's reservation is refused")
check(on_hand(item_a, b1) == 10, "refused issue changed nothing")
post(doc("ISSUE", item_a, 5, bin_id=b1, src=whn))
check(on_hand(item_a, b1) == 5, "free stock (10 - 5 reserved) can be issued")
post(pick_doc)
with new_session() as s:
    res = s.scalar(select(StockReservation).where(StockReservation.source_record_id == task_ids[0],
                                                  StockReservation.source_type_code == "WMS_PICK_TASK"))
check(on_hand(item_a, b1) == 0 and reserved(item_a, b1) == 0 and res.status_code == "FULFILLED",
      "the pick's own document consumes its reservation")
ops.complete_pick(task_ids[0], company_id, uid, D(5))
check(reserved(item_a, b1) == 0 and audit_rows("WarehouseTask", task_ids[0])[-1].action == "COMPLETE",
      "completing the pick afterwards releases nothing twice and is logged")
inv_docs.cancel_stock_document(blocked, company_id, uid)
check(audit_rows("StockDocument", blocked)[-1].action == "CANCEL", "cancelling a stock document is logged")
# اصلاح موجودی (شمارش) مستثناست
post(doc("RECEIPT", item_a, 4, bin_id=b1, dst=whn))
pick2 = doc("ISSUE", item_a, 4, bin_id=b1, src=whn)
t2 = ops.generate_tasks(company_id, "PICK", ("STOCK", pick2), uid)
post(doc("ADJUSTMENT", item_a, 2, bin_id=b1, src=whn, reason=adj_reason))
check(on_hand(item_a, b1) == 2, "stock count adjustment is not blocked by reservations")
ops.cancel_task(t2[0], company_id, uid)
check(reserved(item_a, b1) == 0 and audit_rows("WarehouseTask", t2[0])[-1].action == "CANCEL", "cancelled task frees its hold")

# ===== ۴) ایندکس یکتای وظیفه =====
with new_session() as s:
    t = s.get(WarehouseTask, task_ids[0])
    s.add(WarehouseTask(company_id=company_id, warehouse_id=t.warehouse_id, task_type_code="PICK", item_id=t.item_id,
                        quantity_base=t.quantity_base, source_stock_document_id=t.source_stock_document_id,
                        source_stock_line_id=t.source_stock_line_id, created_by_user_id=uid))
    try:
        s.commit()
        dup_blocked = False
    except Exception:
        s.rollback()
        dup_blocked = True
check(dup_blocked, "database refuses a second task for the same source line")
pick3 = doc("ISSUE", item_a, 1, bin_id=b1, src=whn)
t3 = ops.generate_tasks(company_id, "PICK", ("STOCK", pick3), uid)
check(len(t3) == 1 and ops.generate_tasks(company_id, "PICK", ("STOCK", pick3), uid) == [], "generating again creates nothing")
ops.cancel_task(t3[0], company_id, uid)
inv_docs.cancel_stock_document(pick3, company_id, uid)

# ===== ۵) رزرو سفارش فروش + فروش موبایل =====
post(doc("RECEIPT", item_b, 10, bin_id=b2, dst=whn))


def order(q, wh=whn):
    o = documents_service.create_document(company_id, uid, "SALES_ORDER", today, documents_service.DocumentHeaderFields(
        counterparty_detail_account_id=cust_a, currency_id=company.base_currency_id, warehouse_id=wh, channel_code=channel_code))
    documents_service.add_line(o, company_id, item_id=item_b, uom_id=pcs, quantity=D(q), quantity_base=D(q), unit_price=D(10))
    documents_service.confirm_document(o, company_id, uid)
    return o


def sell(source=None, q=None, mobile=False):
    if source:
        inv = documents_service.convert_to_invoice(source, company_id, uid, today)
    else:
        inv = documents_service.create_document(company_id, uid, "SALES_INVOICE", today, documents_service.DocumentHeaderFields(
            counterparty_detail_account_id=cust_a, currency_id=company.base_currency_id, warehouse_id=whn, channel_code=channel_code))
        documents_service.add_line(inv, company_id, item_id=item_b, uom_id=pcs, quantity=D(q), quantity_base=D(q), unit_price=D(10))
    documents_service.confirm_document(inv, company_id, uid)
    settlements_service.auto_approve_full_cash_settlement_plan(inv, company_id, uid)
    documents_service.post_document(inv, company_id, uid, from_field_sales=mobile)
    return inv


so0 = order(2)
check(reserved(item_b, b2) == 0, "switch off: confirming an order reserves nothing")
documents_service.cancel_document(so0, company_id, cancelled_by_user_id=uid)
switch(sc.SALES_ORDER_RESERVATION)
so1 = order(6)
check(reserved(item_b, b2) == 6, "confirmed order reserves 6 in the bin")
so2 = order(7)
summary = sr.order_reservation_summary(company_id, so2)
with new_session() as s:
    so2_status = s.get(documents_service.CommercialDocument, so2).status_code
check(list(summary.values()) == [D(4)] and so2_status == "CONFIRMED", "short order is still confirmed, only 4 reserved")
check(raises(lambda: sell(q=1), "رزرو شده"), "desktop invoice cannot take stock reserved for orders")
sell(source=so1)
check(on_hand(item_b, b2) == 4 and reserved(item_b, b2) == 4, "invoice from the order uses the order's own reservation")
documents_service.cancel_document(so2, company_id, cancelled_by_user_id=uid)
check(reserved(item_b, b2) == 0 and any(r.changes.get("operation") == "STOCK_RELEASE" for r in audit_rows("CommercialDocument", so2)),
      "cancelling the order releases its reservation (logged)")
so3 = order(3)
documents_service.revert_to_draft(so3, company_id)
check(reserved(item_b, b2) == 0, "back to draft releases the reservation")
so4 = order(4)
mobile_inv = sell(q=2, mobile=True)
with new_session() as s:
    mdoc = s.get(documents_service.CommercialDocument, mobile_inv)
    warn_rows = audit_rows("StockDocument", mdoc.stock_document_id)
check(mdoc.status_code == "POSTED" and on_hand(item_b, b2) == 2 and "رزرو" in " ".join(warn_rows[-1].changes.get("warnings", [])),
      "mobile van sale is never rejected; the reservation conflict is kept as a warning")
documents_service.cancel_document(so4, company_id, cancelled_by_user_id=uid)

# ===== ۶) وضعیت محل =====
post(doc("RECEIPT", item_a, 5, bin_id=b3, dst=whn))
wl.set_status(company_id, b3, "QUARANTINE")
post(doc("ISSUE", item_a, 1, bin_id=b3, src=whn))
check(on_hand(item_a, b3) == 4, "switch off: quarantine bin can still issue (previous behaviour)")
switch(sc.LOCATION_STATUS)
q_issue = doc("ISSUE", item_a, 1, bin_id=b3, src=whn)
check(raises(lambda: post(q_issue), "قرنطینه"), "switch on: issue from quarantine is refused in the service")
check(any("قرنطینه" in e for e in wl.check_document_locations(company_id, q_issue).errors), "desktop pre-check shows the same rule")
post(doc("TRANSFER", item_a, 2, bin_id=b3, src=whn, dst=scrap))
check(on_hand(item_a, b3) == 2, "moving quarantined goods to the scrap warehouse is allowed")
wl.set_status(company_id, b4, "BLOCKED")
check(raises(lambda: post(doc("RECEIPT", item_a, 1, bin_id=b4, dst=whn)), "مسدود"), "receipt into a blocked bin refused in the service")
post(doc("ADJUSTMENT", item_a, 1, bin_id=b3, src=whn, reason=adj_reason))
check(on_hand(item_a, b3) == 1, "stock count adjustment on a quarantine bin is allowed")
switch(sc.LOCATION_STATUS, False)

# ===== ۷) کالای منقضی =====
med = catalog_service.create_item(company_id, "E1", "دارو", IF(item_kind_code="GOOD", base_uom_id=pcs, track_batch=True, track_expiry=True))
old_day, new_day = today - datetime.timedelta(days=1), today + datetime.timedelta(days=365)
post(doc("RECEIPT", med, 10, bin_id=b5, dst=whn, tracking=[TE(D(5), batch_no="OLD", expiry_date=old_day),
                                                            TE(D(5), batch_no="NEW", expiry_date=new_day)]))


def batches_of(stock_doc):
    with new_session() as s:
        return {s.get(Batch, m.batch_id).batch_no: -m.quantity_base for m in s.scalars(select(LotMovement).join(
            StockDocumentLine, StockDocumentLine.line_id == LotMovement.stock_document_line_id).where(
            StockDocumentLine.stock_document_id == stock_doc, LotMovement.quantity_base < 0))}


i1 = doc("ISSUE", med, 1, bin_id=b5, src=whn)
post(i1)
check(batches_of(i1) == {"OLD": D(1)}, "switch off: the earliest (expired) batch is still picked (previous behaviour)")
switch(sc.EXPIRED)
i2 = doc("ISSUE", med, 2, bin_id=b5, src=whn)
post(i2)
check(batches_of(i2) == {"NEW": D(2)}, "switch on: expired batch skipped, fresh batch used")
check(raises(lambda: post(doc("ISSUE", med, 1, bin_id=b5, src=whn, tracking=[TE(D(1), batch_no="OLD", expiry_date=old_day)])),
             "منقضی"), "choosing the expired batch by hand is refused")
check(raises(lambda: post(doc("ISSUE", med, 4, bin_id=b5, src=whn)), "غیرمنقضی"), "not enough fresh stock is refused")
t_scrap = doc("TRANSFER", med, 4, bin_id=b5, src=whn, dst=scrap, tracking=[TE(D(4), batch_no="OLD", expiry_date=old_day)])
post(t_scrap)
check(batches_of(t_scrap).get("OLD") == D(4), "expired batch may go to the scrap warehouse")
switch(sc.EXPIRED, False)

# ===== ۸) دسترسی کاربران به انبار =====
visitor_id = visitor.user_id
switch("WAREHOUSE_ACCESS_CONTROL")
switch(sc.WAREHOUSE_ACCESS)
locations_service.set_warehouse_user_access(whn, visitor_id, can_view_balance=False, can_post_issue=False)
check(raises(lambda: post(doc("ISSUE", item_a, 1, bin_id=b1, src=whn, user=visitor_id), user=visitor_id), "اجازهٔ ثبت حواله"),
      "listed user without issue permission is refused")
post(doc("ISSUE", item_a, 1, bin_id=b1, src=whn))
check(on_hand(item_a, b1) == 1, "system administrator is always allowed")
post(doc("RECEIPT", item_a, 1, dst=warehouse_id, user=visitor_id), user=visitor_id)
check(True, "warehouse without a user list stays open")
locations_service.set_warehouse_user_access(whn, visitor_id, can_view_balance=False, can_post_issue=True)
post(doc("ISSUE", item_a, 1, bin_id=b1, src=whn, user=visitor_id), user=visitor_id)
check(on_hand(item_a, b1) == 0, "after granting issue permission the user can post")

from peecha_api.main import app as api
client = TestClient(api)
token = lambda u: client.post("/auth/login", json={"username": u, "password": "secret123"}).json()["access_token"]  # noqa: E731
H = lambda u: {"Authorization": "Bearer " + token(u)}  # noqa: E731
admin_rows = client.get(f"/inventory/{item_b}", headers=H("admin")).json()
row = next(r for r in admin_rows if r["warehouse_id"] == whn)
check(row["quantity_available"] == str(D(row["quantity_on_hand"]) - D(row["quantity_reserved"])), "mobile stock shows reserved and free")
visitor_rows = client.get(f"/inventory/{item_b}", headers=H("visitor1")).json()
check(all(r["warehouse_id"] != whn for r in visitor_rows), "user without view permission does not see that warehouse's stock")
switch(sc.WAREHOUSE_ACCESS, False)

# ===== ۹) دسترسی جداگانهٔ موبایل =====
forms = {f.code: f.form_id for f in roles_service.list_forms()}
role = roles_service.create_role(company_id, "WMS_MAP", None)
roles_service.set_role_permission(role.role_id, forms["warehouse_map"], "VIEW", True)
roles_service.set_user_role(visitor_id, role.role_id, company_id, True)
check(client.get("/locations/tasks", headers=H("visitor1")).status_code == 200, "switch off: map permission is enough")
switch(sc.MOBILE_PERMISSIONS)
r = client.get("/locations/tasks", headers=H("visitor1"))
check(r.status_code == 403 and "warehouse_operations" in r.text, "switch on: task list needs the operations permission")
roles_service.set_role_permission(role.role_id, forms["warehouse_operations"], "VIEW", True)
check(client.get("/locations/tasks", headers=H("visitor1")).status_code == 200, "granting the operations permission opens it")
check(client.get("/locations/tasks", headers=H("admin")).status_code == 200, "administrator unaffected")

# ===== ۱۰) صفحهٔ تنظیمات و وقایع =====
from PySide6.QtWidgets import QApplication, QCheckBox, QLabel
qapp = QApplication.instance() or QApplication([])
from peecha.ui.screens.inventory_settings import _FeatureToggleTab
from peecha.ui.screens.audit_log import _ACTION_LABELS, _ENTITY_TYPE_LABELS
tab = _FeatureToggleTab()
tab.refresh()
labels = [w.text() for w in tab.findChildren(QLabel)]
check("کنترل‌های انبار پیشرفته" in labels and all(c in tab._checkboxes for c in sc.ALL), "settings tab: WMS group with all switches")
check(any(desc[sc.RESERVATION] == t for t in labels), "settings tab: description under each switch")
tab._checkboxes[sc.RESERVATION].setChecked(False)
check(not sc.is_on(company_id, sc.RESERVATION), "unticking a switch turns the control off")
tab._checkboxes[sc.RESERVATION].setChecked(True)
check(sc.is_on(company_id, sc.RESERVATION), "ticking turns it on again")
check(_ACTION_LABELS["EXECUTE"] == "ثبت نهایی" and _ENTITY_TYPE_LABELS["StockDocument"] == "سند انبار", "audit screen shows Persian labels")

fx.finish()
