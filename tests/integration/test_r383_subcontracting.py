"""R383: پیمانکاری فرعی: سپردن فقط دستور صادرشده، انبار نزد پیمانکار برای مواد دستور، ارسال کمبود مواد با سند انتقال، رسید
محصول با دستمزد پیمانکار (بدهکار WIP / بستانکار نقش جذب پیمانکاری)، مصرف مواد از انبار پیمانکار، بهای محصول = مواد + دستمزد،
کمبود مواد نزد پیمانکار، گزارش بهای دستور؛ و فرم."""
import os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r383"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prd_fixture import *  # noqa: F401,F403

from peecha.db.models.production import OrderTransaction
from peecha.services.production import common as pc, costing as pcost, master as pm, orders as po, subcontracting as sc

pc.update_settings(company_id, uid, default_material_warehouse_id=wh_rm, default_fg_warehouse_id=wh_fg,
                   default_scrap_warehouse_id=wh_scrap)
BF, BL = pm.BomFields, pm.BomLineFields
bom = pm.create_bom_version(company_id, fg, BF(batch_size_qty=D(1)), user_id=uid)
pm.add_bom_component(company_id, bom, BL(r1, D(2)), uid)
pm.add_bom_component(company_id, bom, BL(pk, D(1), component_type="PACKAGING"), uid)
receive(r1, 500, 10_000)
receive(pk, 300, 1_000)
wh_sub = locations_service.create_warehouse(company_id, "SUB1", "انبار نزد پیمانکار ریخته‌گری", WF())
subcon = dimensions_service.create_supplier(company_id, "S9", "ریخته‌گری البرز")
sub_gl = A("526", "دستمزد پیمانکاری جذب‌شده", "DEBIT", "EXPENSE", "TEMPORARY", True, k6.account_id)

o1 = po.create_order(company_id, uid, po.OrderFields(item_id=fg, planned_qty=D(100)))
check(raises(lambda: sc.assign(company_id, uid, o1, subcon, wh_sub, D(5_000)), "صادر"), "only a released order is subcontracted")
po.release_order(company_id, uid, o1, reserve=False)
check([o.order_id for o in sc.assignable_orders(company_id)] == [o1], "released orders can be assigned")
check(raises(lambda: sc.assign(company_id, uid, o1, subcon, wh_fg, D(5_000)), "انبار محصول"), "the subcontractor store is not the product store")
sc.assign(company_id, uid, o1, subcon, wh_sub, D(5_000), "ریخته‌گری و پرداخت")
check(po.get_order(company_id, o1).material_warehouse_id == wh_sub and sc.assignable_orders(company_id) == [],
      "the order's materials now come from the subcontractor store")

# ارسال مواد
check(raises(lambda: sc.send_materials(company_id, uid, o1, wh_sub), "همان انبار"), "the source cannot be the subcontractor store")
doc = sc.send_materials(company_id, uid, o1, wh_rm)
check(on_hand(r1, wh_sub) == D(200) and on_hand(pk, wh_sub) == D(100) and on_hand(r1, wh_rm) == D(300),
      f"the shortage of each material is transferred ({on_hand(r1, wh_sub)}, {on_hand(pk, wh_sub)})")
check(raises(lambda: sc.send_materials(company_id, uid, o1, wh_rm), "کافی"), "nothing more to send")
mats = {m.item_id: m for m in sc.materials(company_id, o1)}
check(mats[r1].at_subcontractor == D(200) and mats[r1].planned_qty == D(200) and mats[r1].consumed_qty == 0, "materials at the subcontractor")

# رسید
check(raises(lambda: sc.receive(company_id, uid, o1, D(40)), "تنظیم حساب تولید"), "the subcontract applied account must be mapped")
engine_service.set_account_mapping(company_id, "PRODUCTION_SUBCONTRACT_APPLIED", sub_gl.account_id)
wip0, sub0, fg0 = gl_balance(wip_gl.account_id), gl_balance(sub_gl.account_id), gl_balance(inv_gl.account_id)
sc.receive(company_id, uid, o1, D(40))
with new_session() as s:
    fee_txn = s.scalar(select(OrderTransaction).where(OrderTransaction.order_id == o1, OrderTransaction.txn_type == "SUBCONTRACT"))
check(fee_txn is not None and fee_txn.amount == D(200_000) and fee_txn.wip_delta == D(200_000), "fee = 40 × 5,000 into WIP")
check(gl_balance(sub_gl.account_id) - sub0 == D(-200_000), "credited to the subcontract applied account")
check(on_hand(r1, wh_sub) == D(120) and on_hand(pk, wh_sub) == D(60) and on_hand(fg, wh_fg) == D(40),
      f"materials for 40 units consumed at the subcontractor, product received ({on_hand(r1, wh_sub)}, {on_hand(fg, wh_fg)})")
with new_session() as s:
    from peecha.db.models.production import ProductionOrder
    costs = pcost.order_costs(s, s.get(ProductionOrder, o1))
check(costs.subcontract == D(200_000) and costs.material == D(40 * 2 * 10_000 + 40 * 1_000)
      and costs.gross == costs.material + costs.subcontract, f"order cost = materials + subcontract ({costs.material}, {costs.gross})")
row = sc.list_subcontracts(company_id)[0]
check(row.produced_qty == D(40) and row.fee_total == D(200_000) and "البرز" in row.subcontractor, "the subcontract list")

# کمبود نزد پیمانکار
sc.send_materials(company_id, uid, o1, wh_rm, {mats[r1].material_id: D(10)})
check(raises(lambda: sc.receive(company_id, uid, o1, D(70)), "کافی نیست"), "cannot receive more than the materials sent allow")
check(raises(lambda: sc.assign(company_id, uid, o1, subcon, wh_rm, D(5_000)), "عوض نمی‌شود"), "the store is fixed after a receipt")
sc.receive(company_id, uid, o1, D(60), final=True)
check(po.get_order(company_id, o1).remaining_qty == 0 and on_hand(fg, wh_fg) == D(100), "the final receipt takes the rest of the order")
check(on_hand(r1, wh_sub) == D(10), "the extra material stays at the subcontractor")

# فرم
from PySide6.QtWidgets import QApplication, QPushButton
qapp = QApplication.instance() or QApplication([])
from peecha.ui.screens.prd_subcontracting import SubcontractingScreen

o2 = po.create_order(company_id, uid, po.OrderFields(item_id=fg, planned_qty=D(10)))
po.release_order(company_id, uid, o2, reserve=False)
screen = SubcontractingScreen()
screen.refresh()
check(screen.table.rowCount() == 1 and screen.order_combo.count() == 1, "the list and the assignable order")
from peecha.ui.screens.fixed_assets import selected_data, set_combo
set_combo(screen.party_combo, subcon)
set_combo(screen.warehouse_combo, wh_sub)
screen.fee_field.setText("۴٬۰۰۰")
check(screen.assign() and screen.table.rowCount() == 2, "assigned from the form")
set_combo(screen.source_combo, wh_rm)
check(screen.send() and on_hand(r1, wh_sub) == D(20), f"materials sent from the form (only the shortage) ({on_hand(r1, wh_sub)}, {screen.status_label.text()}, {selected_data(screen.table)})")
screen.quantity_field.setText("۱۰")
check(screen.receive() and po.get_order(company_id, o2).produced_qty == D(10), "received from the form")
check(all(len(b.text()) <= 2 for b in screen.findChildren(QPushButton) if b.text()), "icon buttons only")

finish()
