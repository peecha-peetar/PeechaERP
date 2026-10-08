import os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r267"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prd_fixture import *  # noqa: F401,F403
import prd_fixture as fx

from peecha.services.production import common as pc, master as pm, orders as po
from peecha.db.models.production import OrderTransaction, ProductionOrder
from peecha.db.models.inventory import StockDocument, StockReservation, StockBalance, LotMovement, Batch, Item
check = fx.check

pc.update_settings(company_id, uid, default_material_warehouse_id=wh_rm, default_fg_warehouse_id=wh_fg,
                   default_scrap_warehouse_id=wh_scrap, auto_cost_calculation=True)
BF, BL = pm.BomFields, pm.BomLineFields
bom = pm.create_bom_version(company_id, fg, BF(batch_size_qty=D(100)), user_id=uid)
pm.add_bom_component(company_id, bom, BL(r1, D(200), scrap_percent=D(3)), uid)
pm.add_bom_component(company_id, bom, BL(r2, D(100)), uid)
pm.add_bom_component(company_id, bom, BL(pk, D(100), component_type="PACKAGING"), uid)
pm.save_bom_output(company_id, bom, pm.BomOutputFields(byp, "BY_PRODUCT", D(10), recovery_value_per_unit=D(5000)), uid)
receive(r1, 1000, 10000)
receive(r2, 500, 20000)
receive(pk, 1000, 1000)
inv0, wip0, cogs0 = gl_balance(inv_gl.account_id), gl_balance(wip_gl.account_id), gl_balance(cogs_gl.account_id)

# ===== Scenario 1: تولیدِ ۱۰۰ عدد =====================================================================
OF = po.OrderFields
o1 = po.create_order(company_id, uid, OF(item_id=fg, planned_qty=D(100)), idempotency_key="ord-1")
check(po.create_order(company_id, uid, OF(item_id=fg, planned_qty=D(100)), idempotency_key="ord-1") == o1, "S15 order creation idempotent")
ordr = po.get_order(company_id, o1)
check(ordr.order_code == "PO-1" and ordr.bom_id == bom and ordr.material_warehouse_id == wh_rm and ordr.fg_warehouse_id == wh_fg,
      "S1 order defaults: code, effective BOM, warehouses from settings")
av = {a.item_id: a for a in po.availability(company_id, o1)}
check(av[r1].required == D(206) and av[r1].status == "GREEN", "S1 availability before release: RM-1 206kg green (200 + 3%)")
po.plan_order(company_id, uid, o1)
check(po.release_order(company_id, uid, o1) == [], "S1 released without shortage")
ordr = po.get_order(company_id, o1)
check(ordr.status_code == "RELEASED" and ordr.planned_unit_cost == D("41100"), f"planned unit cost 41,100 ({ordr.planned_unit_cost})")
from peecha.db.models.inventory import BomHeader
with new_session() as s:
    check(s.get(BomHeader, bom).is_locked, "released BOM version locked")
    res = s.scalar(select(func.sum(StockReservation.quantity)).where(StockReservation.source_type_code == "PRODUCTION_ORDER",
                                                                     StockReservation.status_code == "ACTIVE"))
    reserved = s.scalar(select(func.sum(StockBalance.quantity_reserved)).where(StockBalance.item_id == r1))
check(res == D(406) and reserved == D(206), f"S1 materials reserved in inv.stock_reservations ({res}) and balance ({reserved})")
check(raises(lambda: po.update_order(company_id, uid, o1, OF(item_id=fg, planned_qty=D(5))), "ویرایش"), "released order not editable")

po.start_order(company_id, uid, o1)
txns = po.issue_all_remaining(company_id, uid, o1, idempotency_key="iss-1")
check(po.issue_all_remaining(company_id, uid, o1, idempotency_key="iss-1") == txns[:1], "S15 issue idempotent (same key -> same txn)")
check(on_hand(r1, wh_rm) == D(794) and on_hand(r2, wh_rm) == D(400), "S13 stock reduced once by inventory engine")
view = po.order_view(company_id, o1)
check(view.wip == D(4160000), f"S8 WIP = materials 4,160,000 ({view.wip})")
check(gl_balance(wip_gl.account_id) - wip0 == D(4160000), "S12 WIP GL debited by issue (COGS→WIP override)")
check(gl_balance(cogs_gl.account_id) == cogs0, "S12 production issue does not hit COGS")
with new_session() as s:
    reserved = s.scalar(select(func.sum(StockBalance.quantity_reserved)).where(StockBalance.item_id == r1))
    docs = s.scalars(select(OrderTransaction.stock_document_id).where(OrderTransaction.order_id == o1).distinct()).all()
    sd = s.get(StockDocument, docs[0])
check(reserved == 0, "reservations fulfilled by issue")
check(sd.document_type_code == "ISSUE" and sd.status_code == "POSTED" and sd.reference_no == "PO-1" and sd.journal_entry_id,
      "S13 existing ISSUE stock document, posted with JE and order reference")

# ===== Scenario 4: برگشتِ مواد =====================================================================
m_r1 = [m for m in view.materials if m.item_id == r1][0]
po.return_materials(company_id, uid, o1, [po.IssueLine(m_r1.material_id, D(6))], reason="مازاد", idempotency_key="ret-1")
po.return_materials(company_id, uid, o1, [po.IssueLine(m_r1.material_id, D(6))], reason="مازاد", idempotency_key="ret-1")
view = po.order_view(company_id, o1)
m_r1 = [m for m in view.materials if m.item_id == r1][0]
check(m_r1.issued == D(206) and m_r1.returned == D(6) and m_r1.consumed == D(200), "S4 issued 206, returned 6, consumed 200")
check(on_hand(r1, wh_rm) == D(800), "S4 returned stock back once (no double count)")
check(view.wip == D(4100000), "S4 WIP reduced by return at issue cost")
check(raises(lambda: po.return_materials(company_id, uid, o1, [po.IssueLine(m_r1.material_id, D(500))]), "بیشتر"), "return > net issued rejected")

# ===== Scenario 6 + 8: تولیدِ جزئی + محصولِ جانبی ========================================================
po.report_production(company_id, uid, o1, po.ReceiptInput(D(40), {byp: D(4)}), idempotency_key="rcv-1")
po.report_production(company_id, uid, o1, po.ReceiptInput(D(40), {byp: D(4)}), idempotency_key="rcv-1")
view = po.order_view(company_id, o1)
check(view.order.produced_qty == D(40) and on_hand(fg, wh_fg) == D(40), "S8 partial receipt 40 (idempotent)")
check(view.wip == D(4100000 - 1644000 - 20000), f"S8 WIP after partial = 2,436,000 ({view.wip})")
check(on_hand(byp, wh_fg) == D(4), "S6 by-product received")
check(view.order.progress == D(40), "progress 40%")

# ===== Scenario 5: ضایعات ========================================================================
po.report_scrap(company_id, uid, o1, D(3), "شکستگی", scrap_item_id=scrap_item, recovery_value_per_unit=D(2000), idempotency_key="scr-1")
view = po.order_view(company_id, o1)
check(view.order.scrapped_qty == D(3) and on_hand(scrap_item, wh_scrap) == D(3), "S5 product scrap recorded + recoverable scrap to scrap warehouse")
check(view.wip == D(2436000 - 6000), "S5 scrap recovery credits WIP")
po.report_scrap(company_id, uid, o1, D(4), "ضایعات ماده", material_id=m_r1.material_id)
check(len([t for t in view.transactions if t.txn_type == "SCRAP"]) == 1, "material scrap recorded separately")

# اتمام با رسیدِ نهایی: کلِ ماندهٔ WIP به محصول
po.hold_order(company_id, uid, o1, "خرابی دستگاه")
check(raises(lambda: po.complete_order(company_id, uid, o1), "متوقف"), "on-hold order cannot complete")
po.resume_order(company_id, uid, o1)
po.complete_order(company_id, uid, o1, po.ReceiptInput(D(60), {byp: D(6)}), idempotency_key="cmp-1")
po.complete_order(company_id, uid, o1, po.ReceiptInput(D(60), {byp: D(6)}), idempotency_key="cmp-1")
view = po.order_view(company_id, o1)
check(view.order.status_code == "COMPLETED" and view.order.produced_qty == D(100), "complete with final receipt (idempotent)")
check(view.wip == 0, f"final receipt absorbs all WIP ({view.wip})")
check(on_hand(fg, wh_fg) == D(100) and on_hand(byp, wh_fg) == D(10), "S1 100 units produced, 10 by-products")
main_amount = [o for o in view.outputs if o.output_type == "MAIN"][0].produced_amount
check(main_amount == D(4100000 - 50000 - 6000), f"S6 product cost = materials - by-product value - scrap recovery ({main_amount})")
check(gl_balance(wip_gl.account_id) == wip0, "S12 WIP GL fully relieved")
check(gl_balance(inv_gl.account_id) - inv0 == D(0), "S12 inventory GL net unchanged (materials became products)")

# ===== Scenario 11: بستن =========================================================================
chk = {x.key: x.ok for x in po.closing_checklist(company_id, o1)}
check(all(chk[k] for k in po.BLOCKING_CHECKS), "S11 closing checklist passes")
res = po.close_order(company_id, uid, o1)
check(res.residual == 0 and po.get_order(company_id, o1).status_code == "CLOSED", "S11 order closed")
check(res.summary.actual_unit_cost == D(40440), f"actual unit cost 40,440 ({res.summary.actual_unit_cost})")
check(raises(lambda: po.issue_materials(company_id, uid, o1, [po.IssueLine(m_r1.material_id, D(1))]), "مجاز نیست"), "closed order rejects issue")
check(raises(lambda: po.close_order(company_id, uid, o1), "قبلاً"), "close twice rejected")
po.reopen_order(company_id, uid, o1, "اصلاح ضایعات")
check(po.get_order(company_id, o1).status_code == "IN_PROGRESS", "reopen with reason")
po.complete_order(company_id, uid, o1)
po.close_order(company_id, uid, o1)

# ===== Scenario 2: کمبودِ مواد ======================================================================
o2 = po.create_order(company_id, uid, OF(item_id=fg, planned_qty=D(1000)))
av = {a.item_id: a for a in po.availability(company_id, o2)}
check(av[r1].status == "YELLOW" and av[r1].shortage == D(2060 - 800), f"S2 partial availability yellow, shortage {av[r1].shortage}")
pc.update_settings(company_id, uid, shortage_policy="BLOCK")
check(raises(lambda: po.release_order(company_id, uid, o2), "کمبود"), "S2 BLOCK policy prevents release")
pc.update_settings(company_id, uid, shortage_policy="WARN")
short = po.release_order(company_id, uid, o2, reserve=True)
check({s.item_id for s in short} >= {r1, r2}, "S2 WARN policy releases with shortage list")
check(raises(lambda: po.issue_all_remaining(company_id, uid, o2), "کافی نیست"), "S2 issue beyond stock blocked")
po.unreserve_materials(company_id, uid, o2)
po.cancel_order(company_id, uid, o2, "کمبود")
check(po.get_order(company_id, o2).status_code == "CANCELLED", "order with no activity cancelled")
with new_session() as s:
    check(not s.scalar(select(func.sum(StockBalance.quantity_reserved)).where(StockBalance.item_id == r1)), "cancel released reservations")

# ===== Scenario 3: مصرفِ بیش از BOM =================================================================
o3 = po.create_order(company_id, uid, OF(item_id=fg, planned_qty=D(50)))
po.release_order(company_id, uid, o3)
mats = {m.item_id: m for m in po.order_view(company_id, o3).materials}
po.issue_materials(company_id, uid, o3, [po.IssueLine(mats[r1].material_id, D(108)), po.IssueLine(mats[r2].material_id, D(50)),
                                         po.IssueLine(mats[pk].material_id, D(50))])
mats = {m.item_id: m for m in po.order_view(company_id, o3).materials}
check(mats[r1].consumed == D(108) and mats[r1].required == D(103), "S3 actual 108kg vs standard 103kg")
pc.update_settings(company_id, uid, allow_over_consumption=False)
check(raises(lambda: po.issue_materials(company_id, uid, o3, [po.IssueLine(mats[r2].material_id, D(1))]), "بیشتر"),
      "over-consumption blocked when disallowed")
pc.update_settings(company_id, uid, allow_over_consumption=True)

# ===== Scenario 14: Rollback =========================================================================
before_r2, before_docs = on_hand(r2, wh_rm), None
with new_session() as s:
    before_docs = s.scalar(select(func.count()).select_from(StockDocument))
    before_txn = s.scalar(select(func.count()).select_from(OrderTransaction))
engine_service.set_account_mapping(company_id, "PRODUCTION_WIP", wip_gl.account_id)
from peecha.db.models.inventory import InventoryAccountMapping
with new_session() as s:
    s.delete(s.get(InventoryAccountMapping, (company_id, "PRODUCTION_WIP")))
    s.commit()
check(raises(lambda: po.issue_materials(company_id, uid, o3, [po.IssueLine(mats[r2].material_id, D(5))])), "S14 failure inside operation")
with new_session() as s:
    after_docs = s.scalar(select(func.count()).select_from(StockDocument))
    after_txn = s.scalar(select(func.count()).select_from(OrderTransaction))
check(after_docs == before_docs and after_txn == before_txn and on_hand(r2, wh_rm) == before_r2,
      "S14 full rollback: no stock document, no order transaction, stock unchanged")
engine_service.set_account_mapping(company_id, "PRODUCTION_WIP", wip_gl.account_id)
check(raises(lambda: po.report_production(company_id, uid, o3, po.ReceiptInput(D(0))), "صفر"), "zero production blocked")
check(raises(lambda: po.complete_order(company_id, uid, o3), "صفر"), "complete with zero production blocked")

# برگشتِ تولید
t = po.report_production(company_id, uid, o3, po.ReceiptInput(D(20)))
po.reverse_production(company_id, uid, t, "اشتباه ثبت")
check(po.get_order(company_id, o3).produced_qty == 0, "reverse production restores produced qty")
check(raises(lambda: po.reverse_production(company_id, uid, t, "دوباره"), "قبلاً"), "double reversal rejected")
with new_session() as s:
    try:
        s.execute(text("UPDATE prd.order_transactions SET amount = 0 WHERE txn_id = :t"), {"t": t})
        s.commit()
        immutable = False
    except Exception:
        immutable = True
check(immutable, "order transactions are immutable (DB trigger)")

# ===== Scenario 7: Multi-level BOM ====================================================================
fg2 = item("FG-B", "محصول B", "FINISHED_GOOD")
bom_semi = pm.create_bom_version(company_id, semi, BF(batch_size_qty=D(1)), user_id=uid)
pm.add_bom_component(company_id, bom_semi, BL(r3, D(2)), uid)
bom2 = pm.create_bom_version(company_id, fg2, BF(batch_size_qty=D(1)), user_id=uid)
pm.add_bom_component(company_id, bom2, BL(semi, D(1), component_type="SEMI_FINISHED"), uid)
pm.add_bom_component(company_id, bom2, BL(pk, D(1)), uid)
receive(r3, 100, 5000)
parent = po.create_order(company_id, uid, OF(item_id=fg2, planned_qty=D(30)))
children = po.create_child_orders(company_id, uid, parent)
child = po.get_order(company_id, children[0])
check(len(children) == 1 and child.item_id == semi and child.planned_qty == D(30) and child.parent_order_id == parent
      and child.fg_warehouse_id == wh_rm, "S7 child order for semi-finished shortage, delivering to parent's material warehouse")
po.release_order(company_id, uid, children[0])
po.issue_all_remaining(company_id, uid, children[0])
po.complete_order(company_id, uid, children[0], po.ReceiptInput(D(30)))
check(on_hand(semi, wh_rm) == D(30), "S7 semi-finished received into material warehouse")
semi_cost = [o for o in po.order_view(company_id, children[0]).outputs][0].produced_amount
check(semi_cost == D(300000), f"semi cost = 60kg x 5000 ({semi_cost})")
po.release_order(company_id, uid, parent)
po.issue_all_remaining(company_id, uid, parent)
po.complete_order(company_id, uid, parent, po.ReceiptInput(D(30)))
pv = po.order_view(company_id, parent)
check(pv.order.produced_qty == D(30) and pv.outputs[0].produced_amount == D(330000), "S7 parent consumes semi at its production cost (+packaging)")

# بچ/سریال و ردیابی
fgl = item("FG-L", "محصول بچ‌دار", "FINISHED_GOOD", track_batch=True)
bl = pm.quick_bom(company_id, fgl, [(r3, D(1))], user_id=uid)
ol = po.create_order(company_id, uid, OF(item_id=fgl, planned_qty=D(5)))
po.release_order(company_id, uid, ol)
po.complete_order(company_id, uid, ol, po.ReceiptInput(D(5)))
with new_session() as s:
    b = s.scalar(select(Batch).where(Batch.item_id == fgl))
    lm = s.scalar(select(func.sum(LotMovement.quantity_base)).where(LotMovement.item_id == fgl))
check(b is not None and b.batch_no == po.get_order(company_id, ol).order_code and lm == D(5), "batch-tracked product gets order-code batch (lot traceability)")
check(po.get_order(company_id, ol).status_code == "COMPLETED", "backflush-free order with auto-consumption off completes")
v = po.order_view(company_id, ol)
check(v.wip == 0 and v.outputs[0].produced_amount == 0, "no material issued -> zero cost (warns via checklist)")
check(not {x.key: x.ok for x in po.closing_checklist(company_id, ol)}["CONSUMPTION"], "checklist flags missing consumption")
check(raises(lambda: po.close_order(company_id, uid, ol), "مصرف مواد"), "close blocked without consumption")

# backflush
pc.update_settings(company_id, uid, auto_consumption=True)
ob = po.create_order(company_id, uid, OF(item_id=fg2, planned_qty=D(5)))
receive(semi, 5, 10000)
po.release_order(company_id, uid, ob)
po.report_production(company_id, uid, ob, po.ReceiptInput(D(5)))
bv = po.order_view(company_id, ob)
check(all(m.consumed == m.required for m in bv.materials), "backflush consumes BOM standard on receipt")
pc.update_settings(company_id, uid, auto_consumption=False)

# همخوانیِ کلِ WIP با دفترِ کل
with new_session() as s:
    wip_sub = s.scalar(select(func.coalesce(func.sum(OrderTransaction.wip_delta), 0)))
check(D(wip_sub) == gl_balance(wip_gl.account_id) - wip0, f"WIP sub-ledger == WIP GL ({wip_sub})")

fx.finish()
