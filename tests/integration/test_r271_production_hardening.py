import os, sys, threading, time
os.environ["PEECHA_DB_NAME"] = "peecha_test_r271"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prd_fixture import *  # noqa: F401,F403
import prd_fixture as fx

from peecha.services.production import common as pc, master as pm, orders as po, costing as pcost, planning as pp
from peecha.db.models.production import OrderTransaction, ProductionOrder
from peecha.db.models.inventory import StockDocument, StockLedger
check = fx.check

pc.update_settings(company_id, uid, default_material_warehouse_id=wh_rm, default_fg_warehouse_id=wh_fg, default_scrap_warehouse_id=wh_scrap)
BF, BL, WCF, RO = pm.BomFields, pm.BomLineFields, pm.WorkCenterFields, pm.RoutingOpFields
wc = pm.save_work_center(company_id, WCF(code="L1", name="خط", labor_rate=D(500000), machine_rate=D(800000), overhead_rate=D(100000)))
rt = pm.create_routing(company_id, fg, "مسیر", [RO(10, "برش", wc, run_minutes=D(6), machine_minutes=D(12))])
bom_semi = pm.create_bom_version(company_id, semi, BF(batch_size_qty=D(1)))
pm.add_bom_component(company_id, bom_semi, BL(r3, D(1)))
bom = pm.create_bom_version(company_id, fg, BF(batch_size_qty=D(1), routing_id=rt))
pm.add_bom_component(company_id, bom, BL(r1, D(1), scrap_percent=D(3)))
pm.add_bom_component(company_id, bom, BL(semi, D(1), component_type="SEMI_FINISHED"))
pm.add_bom_component(company_id, bom, BL(pk, D(1), component_type="PACKAGING"))
pm.save_bom_output(company_id, bom, pm.BomOutputFields(byp, "BY_PRODUCT", D("0.1"), recovery_value_per_unit=D(2000)))
receive(r1, 5000, 10000)
receive(r3, 5000, 4000)
receive(pk, 5000, 1000)
OF = po.OrderFields


def wip_matches_gl():
    with new_session() as s:
        sub = D(s.scalar(select(func.coalesce(func.sum(OrderTransaction.wip_delta), 0))))
    return sub == gl_balance(wip_gl.account_id)


def balanced_journals():
    with new_session() as s:
        bad = s.execute(text("SELECT journal_entry_id FROM acc.journal_entry_lines GROUP BY journal_entry_id "
                             "HAVING sum(debit_amount_base) <> sum(credit_amount_base)")).all()
    return not bad


def ledger_matches_balance():
    with new_session() as s:
        bad = s.execute(text(
            "SELECT b.item_id FROM (SELECT item_id, warehouse_id, sum(quantity_on_hand) q FROM inv.stock_balance GROUP BY 1,2) b "
            "LEFT JOIN (SELECT item_id, warehouse_id, sum(CASE WHEN movement_direction='IN' THEN quantity_base ELSE -quantity_base END) q "
            "FROM inv.stock_ledger GROUP BY 1,2) l USING (item_id, warehouse_id) WHERE b.q <> coalesce(l.q, 0)")).all()
    return not bad


# ===== Scenario 1 + 7: تولیدِ ۱۰۰ عدد با BOMِ چندسطحی (نیمه‌ساخته مرحله‌به‌مرحله) ==========================
o1 = po.create_order(company_id, uid, OF(item_id=fg, planned_qty=D(100)))
kids = po.create_child_orders(company_id, uid, o1)
check(len(kids) == 1, "S7 child order for semi-finished")
po.release_order(company_id, uid, kids[0])
po.issue_all_remaining(company_id, uid, kids[0])
po.complete_order(company_id, uid, kids[0], po.ReceiptInput(D(100)))
po.close_order(company_id, uid, kids[0])
po.release_order(company_id, uid, o1)
po.start_order(company_id, uid, o1)
po.issue_all_remaining(company_id, uid, o1)
po.complete_order(company_id, uid, o1, po.ReceiptInput(D(100), {byp: D(10)}))
check(on_hand(fg, wh_fg) == D(100) and on_hand(semi, wh_rm) == 0, "S1 100 units produced from semi-finished stage")
k = pcost.get_order_costs(company_id, o1)
check(k.material == D(103 * 10000 + 100 * 4000 + 100 * 1000), f"S7 multi-level material cost 1,530,000 ({k.material})")

# ===== Scenario 2: کمبودِ مواد ==========================================================================
o2 = po.create_order(company_id, uid, OF(item_id=fg, planned_qty=D(10000)))
pc.update_settings(company_id, uid, shortage_policy="BLOCK")
check(raises(lambda: po.release_order(company_id, uid, o2), "کمبود"), "S2 shortage blocks release (BLOCK policy)")
pc.update_settings(company_id, uid, shortage_policy="WARN")
po.cancel_order(company_id, uid, o2, "کمبود")

# ===== Scenario 3 + 4 + 5 + 6 + 8 + 9 + 10 + 11 روی یک دستور ===============================================
o3 = po.create_order(company_id, uid, OF(item_id=fg, planned_qty=D(50)))
receive(semi, 60, 4000)
po.release_order(company_id, uid, o3)
v = po.order_view(company_id, o3)
m = {x.item_id: x.material_id for x in v.materials}
po.issue_materials(company_id, uid, o3, [po.IssueLine(m[r1], D(56)), po.IssueLine(m[semi], D(50)), po.IssueLine(m[pk], D(50))])
check({x.item_id: x.consumed for x in po.order_view(company_id, o3).materials}[r1] == D(56), "S3 actual 56 > standard 51.5")
po.return_materials(company_id, uid, o3, [po.IssueLine(m[r1], D(2))])
check({x.item_id: x.consumed for x in po.order_view(company_id, o3).materials}[r1] == D(54), "S4 return: net consumption 54")
po.report_production(company_id, uid, o3, po.ReceiptInput(D(20), {byp: D(2)}))
check(po.order_view(company_id, o3).wip > 0, "S8 partial production leaves WIP")
po.report_scrap(company_id, uid, o3, D(5), "ترک", scrap_item_id=scrap_item, recovery_value_per_unit=D(500))
pcost.record_labor(company_id, uid, o3, pcost.LaborInput(hours=D(6), rate=D(550000), order_operation_id=v.operations[0].order_operation_id))
pcost.record_machine(company_id, uid, o3, pcost.MachineInput(hours=D(10), order_operation_id=v.operations[0].order_operation_id))
from peecha.services.fixed_assets.common import period_of
pool = pcost.save_pool(company_id, "FOH", "سربار", period_of(today)[0], D(300000), "MACHINE_HOURS")
pcost.allocate_pool(company_id, uid, pool)
check(pcost.get_order_costs(company_id, o3).overhead > D(300000), "S10 overhead allocated from pool (+ rate overhead)")
po.complete_order(company_id, uid, o3, po.ReceiptInput(D(25), {byp: D(3)}))
k3 = pcost.get_order_costs(company_id, o3)
check(k3.byproduct_credit == D(10000) and k3.scrap_recovery == D(2500), "S5/S6 scrap recovery and by-product value deducted")
check(k3.variance != 0 and k3.actual_unit_cost != k3.standard_unit_cost, f"S9 actual {k3.actual_unit_cost} != standard {k3.standard_unit_cost}")
var = {x.code: x.amount for x in pcost.get_variances(company_id, o3)}
check(var["MATERIAL_USAGE"] > 0 and var["LABOR_RATE"] > 0 and var["SCRAP"] >= 0, "S9 variance analysis populated")
res = po.close_order(company_id, uid, o3)
check(po.get_order(company_id, o3).status_code == "CLOSED" and po.order_view(company_id, o3).wip == 0, "S11 close: WIP zero, order locked")
check(raises(lambda: po.report_production(company_id, uid, o3, po.ReceiptInput(D(1))), "مجاز نیست"), "S11 closed order cannot be edited")

# ===== Scenario 12 + 13: همخوانیِ حسابداری و انبار ===========================================================
check(wip_matches_gl(), "S12 WIP sub-ledger equals WIP GL account")
check(balanced_journals(), "S12 every journal entry balanced")
with new_session() as s:
    txns = list(s.scalars(select(OrderTransaction).where(OrderTransaction.stock_document_id.is_not(None))))
    docs = {d.stock_document_id: d for d in s.scalars(select(StockDocument).where(
        StockDocument.stock_document_id.in_([t.stock_document_id for t in txns])))}
check(all(docs[t.stock_document_id].status_code == "POSTED" and docs[t.stock_document_id].journal_entry_id for t in txns),
      "S13 every production movement is a posted stock document with journal entry")
check(all(docs[t.stock_document_id].document_type_code in ("ISSUE", "RECEIPT") for t in txns), "S13 only existing stock document types used")
check(ledger_matches_balance(), "S13 stock ledger equals stock balance")
check(gl_balance(cogs_gl.account_id) == 0, "production never posts to COGS")

# ===== Scenario 14: Rollback ==============================================================================
o14 = po.create_order(company_id, uid, OF(item_id=fg, planned_qty=D(10)))
po.release_order(company_id, uid, o14)
po.issue_all_remaining(company_id, uid, o14)
with new_session() as s:
    n_docs, n_txn, n_je = (s.scalar(select(func.count()).select_from(StockDocument)), s.scalar(select(func.count()).select_from(OrderTransaction)),
                           s.scalar(text("SELECT count(*) FROM acc.journal_entries")))
fgs = item("FG-S", "سریال‌دار", "FINISHED_GOOD", track_serial=True)
bs = pm.quick_bom(company_id, fgs, [(r1, D(1))])
o14b = po.create_order(company_id, uid, OF(item_id=fgs, planned_qty=D(3)))
po.release_order(company_id, uid, o14b)
po.issue_all_remaining(company_id, uid, o14b)
with new_session() as s:
    n_docs, n_txn, n_je = (s.scalar(select(func.count()).select_from(StockDocument)), s.scalar(select(func.count()).select_from(OrderTransaction)),
                           s.scalar(text("SELECT count(*) FROM acc.journal_entries")))
check(raises(lambda: po.complete_order(company_id, uid, o14b, po.ReceiptInput(D(3), serial_nos=["A", "B"])), "سریال"),
      "S14 failing completion (serial count mismatch)")
with new_session() as s:
    after = (s.scalar(select(func.count()).select_from(StockDocument)), s.scalar(select(func.count()).select_from(OrderTransaction)),
             s.scalar(text("SELECT count(*) FROM acc.journal_entries")))
check(after == (n_docs, n_txn, n_je) and po.get_order(company_id, o14b).status_code == "IN_PROGRESS" and on_hand(fgs, wh_fg) == 0,
      "S14 rollback: no stock doc, no journal, no order change")
po.complete_order(company_id, uid, o14b, po.ReceiptInput(D(3)))
from peecha.db.models.inventory import SerialNumber
with new_session() as s:
    serials = list(s.scalars(select(SerialNumber.serial_no).where(SerialNumber.item_id == fgs)))
check(len(serials) == 3 and all(x.startswith(po.get_order(company_id, o14b).order_code) for x in serials), "auto serial numbers per order")

# ===== Scenario 15: درخواستِ تکراری / هم‌زمان ================================================================
o15 = po.create_order(company_id, uid, OF(item_id=fg, planned_qty=D(10)))
po.release_order(company_id, uid, o15)
mid = po.order_view(company_id, o15).materials[0].material_id
results, errors = [], []


def worker():
    try:
        results.append(tuple(po.issue_materials(company_id, uid, o15, [po.IssueLine(mid, D(3))], idempotency_key="dup-15")))
    except Exception as exc:  # noqa: BLE001
        errors.append(str(exc))


threads = [threading.Thread(target=worker) for _ in range(4)]
for t in threads:
    t.start()
for t in threads:
    t.join()
consumed = po.order_view(company_id, o15).materials[0].consumed
check(consumed == D(3), f"S15 four concurrent duplicate requests -> one consumption ({consumed}; errors {len(errors)})")
check(len(set(results)) <= 1, "S15 duplicates return the same transaction")
po.report_production(company_id, uid, o15, po.ReceiptInput(D(2)), idempotency_key="rcv-15")
po.report_production(company_id, uid, o15, po.ReceiptInput(D(2)), idempotency_key="rcv-15")
check(po.get_order(company_id, o15).produced_qty == D(2), "S15 duplicate receipt ignored")
check(wip_matches_gl() and balanced_journals() and ledger_matches_balance(), "integrity after concurrency")

# ===== یکپارچگیِ پایگاه‌داده ==========================================================================
def db_rejects(sql):
    with new_session() as s:
        try:
            s.execute(text(sql))
            s.commit()
            return False
        except Exception:  # noqa: BLE001
            return True


check(db_rejects(f"INSERT INTO prd.production_orders (company_id, order_no, order_code, item_id, planned_qty, uom_id, start_date, due_date, "
                 f"created_by_user_id) VALUES ({company_id}, 1, 'X', {fg}, 0, {pcs}, now(), now(), {uid})"), "DB: zero planned qty rejected")
check(db_rejects(f"INSERT INTO prd.production_orders (company_id, order_no, order_code, item_id, planned_qty, uom_id, start_date, due_date, "
                 f"created_by_user_id) VALUES ({company_id}, 1, 'X', {fg}, 5, {pcs}, now(), now(), {uid})"), "DB: duplicate order number rejected")
check(db_rejects("UPDATE prd.order_materials SET returned_qty = issued_qty + 1"), "DB: returned > issued rejected")
check(db_rejects("DELETE FROM prd.order_transactions"), "DB: transaction ledger immutable")
check(db_rejects(f"INSERT INTO prd.production_orders (company_id, order_no, order_code, item_id, planned_qty, uom_id, start_date, due_date, "
                 f"created_by_user_id, status_code) VALUES ({company_id}, 999, 'Y', {fg}, 5, {pcs}, now(), now(), {uid}, 'BOGUS')"),
      "DB: invalid status rejected")

# ===== کارایی =====================================================================================
t0 = time.time()
ids = [po.create_order(company_id, uid, OF(item_id=fg, planned_qty=D(5))) for _ in range(40)]
for oid in ids[:20]:
    po.release_order(company_id, uid, oid, reserve=False)
create_time = time.time() - t0
t0 = time.time()
pp.run_mrp(company_id, uid)
mrp_time = time.time() - t0
t0 = time.time()
from peecha.services import warehouse_reports as wr
from peecha.services.purchase_reports import PurchaseFilters
f = PurchaseFilters(today - datetime.timedelta(days=30), today, side="INVENTORY")
for code in ("PRD_ORDERS", "PRD_COST", "PRD_COST_VARIANCE", "PRD_WIP", "PRD_EFFICIENCY", "PRD_MATERIAL_REQUIREMENT"):
    wr.WAREHOUSE_REPORTS_BY_CODE[code].func(company_id, f)
report_time = time.time() - t0
print(f"perf: 40 orders+20 releases {create_time:.1f}s, MRP {mrp_time:.1f}s, 6 reports {report_time:.1f}s")
check(create_time < 60 and mrp_time < 20 and report_time < 60, "performance within bounds")
check(len(po.list_orders(company_id)) >= 45, "order list")

fx.finish()
