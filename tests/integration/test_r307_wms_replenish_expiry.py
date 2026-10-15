"""R307: انبار پیشرفته فاز ۶ — تامین مجدد با در نظر گرفتن رزرو و برداشت باز، هشدار انقضا در کارتابل و سند پیش‌نویس
انتقال کالای منقضی به انبار ضایعات."""
import os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r307"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crm_fixture import *  # noqa: F401,F403
import crm_fixture as fx
from sqlalchemy import func
from peecha import numerals
from peecha.services import data_reset
from peecha.services import expiry_watch
from peecha.services import inventory_documents as inv_docs
from peecha.services import lot_tracking as lt
from peecha.services import operational_tasks
from peecha.services import stock_controls as sc
from peecha.services import warehouse_locations as wl
from peecha.services import warehouse_operations as ops
from peecha.services.workflow import inbox
from peecha.db.models.inventory import StockBalance, StockDocument, StockDocumentLine
check, raises = fx.check, fx.raises
TE = lt.TrackingEntry

g_l = A("2", "بدهی‌ها", "CREDIT", "LIABILITY", "PERMANENT", False)
k_l = A("21", "پرداختنی‌ها", "CREDIT", "LIABILITY", "PERMANENT", False, g_l.account_id)
ap_gl = A("2101", "پرداختنی تامین‌کنندگان", "CREDIT", "LIABILITY", "PERMANENT", True, k_l.account_id)
engine_service.set_account_mapping(company_id, "SUPPLIER_PAYABLE", ap_gl.account_id)
supplier = dimensions_service.create_supplier(company_id, "S1", "تامین‌کننده")
keeper = visitor.user_id
WF = locations_service.WarehouseFields
whn = locations_service.create_warehouse(company_id, "WH-N", "انبار اصلی", WF(manager_user_id=keeper))
zone = wl.create_location(company_id, whn, "AREA", "Z01")
rack = wl.create_location(company_id, whn, "RACK", "R01", zone)
shelf = wl.create_location(company_id, whn, "SHELF", "L01", rack)
pf, rs, b3 = [wl.create_location(company_id, whn, "BIN", code, shelf) for code in ("PF", "RS", "B3")]


def receipt(item, qty, bin_id, tracking=None):
    d = inv_docs.create_stock_document(company_id, uid, "RECEIPT", today, inv_docs.DocumentHeaderFields(
        destination_warehouse_id=whn, counterparty_detail_account_id=supplier))
    line = inv_docs.add_line(d, company_id, inv_docs.LineFields(item_id=item, uom_id=pcs, quantity=D(qty), quantity_base=D(qty),
                                                                unit_cost=D(1000), bin_location_id=bin_id))
    if tracking:
        lt.set_line_tracking(company_id, tracking, stock_line_id=line)
    inv_docs.confirm_stock_document(d, company_id)
    inv_docs.post_stock_document(d, company_id, uid)


def issue_draft(item, qty, bin_id):
    d = inv_docs.create_stock_document(company_id, uid, "ISSUE", today, inv_docs.DocumentHeaderFields(source_warehouse_id=whn))
    inv_docs.add_line(d, company_id, inv_docs.LineFields(item_id=item, uom_id=pcs, quantity=D(qty), quantity_base=D(qty),
                                                         bin_location_id=bin_id))
    return d


def stock(item, warehouse):
    with new_session() as s:
        return s.scalar(select(func.coalesce(func.sum(StockBalance.quantity_on_hand), 0)).where(
            StockBalance.item_id == item, StockBalance.warehouse_id == warehouse)) or D(0)


switch = lambda code, on=True: engine_service.set_feature_enabled(company_id, code, on)  # noqa: E731

# ===== ۱) کلیدها و تنظیم روزها =====
feats = {f.feature_code: f for f in engine_service.list_features(company_id)}
check(all(feats[c].category == "WMS" and not feats[c].is_enabled for c in (sc.SMART_REPLENISH, sc.EXPIRY_ALERTS)),
      "two new switches in the WMS group, both off")
check(sc.expiry_alert_days(company_id) == 30, "expiry alert window defaults to 30 days")
sc.set_expiry_alert_days(company_id, 10)
check(sc.expiry_alert_days(company_id) == 10 and raises(lambda: sc.set_expiry_alert_days(company_id, 0), "بین"),
      "alert window is saved and validated")
check("inv.wms_settings" in data_reset.covered_tables(), "the reset tool covers the new settings table")

# ===== ۲) تامین مجدد با در نظر گرفتن رزرو و برداشت باز =====
receipt(item_a, 8, pf)
receipt(item_a, 50, rs)
rule = ops.save_rule(company_id, ops.RuleFields(bin_location_id=pf, item_id=item_a, min_quantity=D(5), max_quantity=D(10)))
need_of = lambda: next((n for n in ops.replenishment_needs(company_id, whn) if n.rule.rule_id == rule), None)  # noqa: E731
ops.generate_tasks(company_id, "PICK", ("STOCK", issue_draft(item_a, 6, pf)), uid)   # برداشت باز ۶ از محل برداشت
switch(sc.SALES_ORDER_RESERVATION)
so = documents_service.create_document(company_id, uid, "SALES_ORDER", today, documents_service.DocumentHeaderFields(
    counterparty_detail_account_id=cust_a, currency_id=company.base_currency_id, warehouse_id=whn, channel_code=channel_code))
documents_service.add_line(so, company_id, item_id=item_a, uom_id=pcs, quantity=D(48), quantity_base=D(48), unit_price=D(10))
documents_service.confirm_document(so, company_id, uid)
check(need_of() is None, "switch off: 8 on the shelf > minimum 5, no replenishment (previous behaviour)")
switch(sc.SMART_REPLENISH)
n = need_of()
check(n is not None and n.reserved == 6 and n.need == 2, f"switch on: only 2 free on the shelf -> refill the 2 empty places "
      f"({n and (n.reserved, n.need)})")
check(n is not None and len(n.sources) == 1 and n.sources[0].location_id == rs and n.sources[0].free == 2,
      "source counts the sales-order reservation too (50 - 48 = 2 free)")
tasks = ops.generate_replenishment_tasks(company_id, uid, whn)
check(len(tasks) == 1 and ops.task_reservations(company_id, tasks[0])[0].quantity == 2, "replenishment task for 2 from the reserve")
check(need_of() is None, "pending task counts: no duplicate need")

# ===== ۳) هشدار انقضا =====
med = catalog_service.create_item(company_id, "M1", "دارو", IF(item_kind_code="GOOD", base_uom_id=pcs, track_batch=True, track_expiry=True))
receipt(med, 3, b3, [TE(D(3), batch_no="OLD", expiry_date=today - datetime.timedelta(days=2))])
receipt(med, 4, b3, [TE(D(4), batch_no="SOON", expiry_date=today + datetime.timedelta(days=5))])
receipt(med, 5, b3, [TE(D(5), batch_no="FAR", expiry_date=today + datetime.timedelta(days=100))])
kinds = lambda user: {t.kind: t for t in operational_tasks.list_operational_tasks(company_id, user)  # noqa: E731
                      if t.kind in ("EXPIRY_NEAR", "EXPIRED_STOCK")}
check(kinds(keeper) == {}, "switch off: no expiry tasks")
switch(sc.EXPIRY_ALERTS)
rows = expiry_watch.near_expiry(company_id)
check([(r.batch_no, r.expired) for r in rows] == [("OLD", True), ("SOON", False)] and rows[1].days_left == 5,
      "expired and within-10-days batches listed; far batch not")
mine = kinds(keeper)
check(set(mine) == {"EXPIRY_NEAR", "EXPIRED_STOCK"} and "انبار اصلی" in mine["EXPIRED_STOCK"].title
      and "۱۰" in numerals.to_persian_digits(mine["EXPIRY_NEAR"].title), "warehouse keeper sees both expiry tasks")
other = users_service.create_user("keeper2", "انباردار دیگر", "secret123", None, lang_id, False, [company_id], company_id)
check(kinds(other.user_id) == {}, "another user does not see them")
work = {w.extra.get("kind"): w for w in inbox.my_work(company_id, keeper) if w.source == "DOC"}
check(work.get("EXPIRED_STOCK") and work["EXPIRED_STOCK"].action == "سند انتقال کالای منقضی به ضایعات را بسازید و ثبت کنید",
      "unified cartable shows a clear action")

# سند پیش‌نویس انتقال کالای منقضی
check(raises(lambda: expiry_watch.create_disposal_draft(company_id, uid, whn), "ضایعات"), "needs a scrap or quarantine warehouse")
whs = locations_service.create_warehouse(company_id, "WH-S", "انبار ضایعات", WF(warehouse_type_code="SCRAP"))
doc = expiry_watch.create_disposal_draft(company_id, uid, whn)
with new_session() as s:
    d = s.get(StockDocument, doc)
    lines = list(s.scalars(select(StockDocumentLine).where(StockDocumentLine.stock_document_id == doc)))
check(d.status_code == "DRAFT" and d.document_type_code == "TRANSFER" and d.destination_warehouse_id == whs
      and len(lines) == 1 and lines[0].quantity_base == 3 and lines[0].bin_location_id == b3,
      "a draft transfer of the expired batch to scrap is prepared (not posted)")
check([e.batch_no for e in lt.get_line_tracking(stock_line_id=lines[0].line_id)] == ["OLD"], "the draft carries the expired batch")
check(stock(med, whn) == 12 and expiry_watch.create_disposal_draft(company_id, uid, whn) == doc,
      "nothing moves until the user posts; asking again returns the same draft")
switch(sc.EXPIRED)
inv_docs.confirm_stock_document(doc, company_id)
inv_docs.post_stock_document(doc, company_id, uid)
check(stock(med, whn) == 9 and stock(med, whs) == 3, "after the user posts it, the expired stock is in the scrap warehouse")
check("EXPIRED_STOCK" not in kinds(keeper) and "EXPIRY_NEAR" in kinds(keeper), "expired task leaves the cartable")
check(raises(lambda: expiry_watch.create_disposal_draft(company_id, uid, whn), "منقضی نیست"), "nothing expired left")

# دسکتاپ
from PySide6.QtWidgets import QApplication, QPushButton
qapp = QApplication.instance() or QApplication([])
from peecha.ui.screens.warehouse_operations import WarehouseOperationsScreen
from peecha.ui.screens.inventory_settings import _FeatureToggleTab
screen = WarehouseOperationsScreen()
screen.refresh()
tab = screen.expiry_tab
check(screen.tabs.isTabVisible(screen.tabs.indexOf(tab)) and tab.table.rowCount() == 1, "desktop expiry tab lists the near-expiry batch")
check(all(len(b.text()) <= 2 for b in tab.findChildren(QPushButton)), "expiry tab buttons are icons")
settings_tab = _FeatureToggleTab()
settings_tab.refresh()
check(settings_tab.expiry_days_spin.value() == 10, "settings shows the alert window under its switch")
settings_tab.expiry_days_spin.setValue(20)
settings_tab._save_expiry_days()
check(sc.expiry_alert_days(company_id) == 20, "alert window saved from settings")

fx.finish()
