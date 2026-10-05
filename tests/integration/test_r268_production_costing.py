import os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r268"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prd_fixture import *  # noqa: F401,F403
import prd_fixture as fx

from peecha.services.production import common as pc, master as pm, orders as po, costing as pk_
from peecha.db.models.production import OrderTransaction, CostAllocationRow
from peecha.db.models.fixed_assets import MachineCostAllocation
from peecha.db.models.inventory import StandardCost
check = fx.check

pc.update_settings(company_id, uid, default_material_warehouse_id=wh_rm, default_fg_warehouse_id=wh_fg,
                   default_scrap_warehouse_id=wh_scrap, auto_cost_calculation=True)
receive(r1, 5000, 10000)

# مرکزِ کاری و مسیر: هر واحد ۰٫۱ ساعت کار (۶ دقیقه) و ۰٫۲ ساعت ماشین
WCF, RO, BF, BL = pm.WorkCenterFields, pm.RoutingOpFields, pm.BomFields, pm.BomLineFields
wc = pm.save_work_center(company_id, WCF(code="CUT", name="برش", labor_rate=D(500000), machine_rate=D(800000), overhead_rate=D(200000)))
px = item("PX", "محصولِ X", "FINISHED_GOOD")
rt = pm.create_routing(company_id, px, "مسیر", [RO(10, "برش", wc, run_minutes=D(6), machine_minutes=D(12))])
bom = pm.create_bom_version(company_id, px, BF(batch_size_qty=D(1), routing_id=rt))
pm.add_bom_component(company_id, bom, BL(r1, D(1)))

# ===== Standard Cost (Roll-up) =========================================================================
roll = pk_.rollup_standard_cost(company_id, px)
top = [r for r in roll if r.item_id == px][0]
check((top.material, top.labor, top.machine, top.overhead, top.total) == (D(10000), D(50000), D(160000), D(20000), D(240000)),
      f"standard cost roll-up 10k+50k+160k+20k = 240,000 ({top.total})")
pk_.rollup_standard_cost(company_id, px, write=True, user_id=uid)
with new_session() as s:
    check(s.get(StandardCost, (px, today)).standard_unit_cost == D(240000), "standard written to existing inv.standard_costs")
check(len(pk_.standard_cost_cards(company_id, px)) == 1, "standard cost card stored")

# ===== Scenario 9 + Labor + Machine: Actual ≠ Standard ==================================================
OF = po.OrderFields
oa = po.create_order(company_id, uid, OF(item_id=px, planned_qty=D(100)))
po.release_order(company_id, uid, oa)
a = po.get_order(company_id, oa)
check(a.planned_unit_cost == D(240000) and a.standard_unit_cost == D(240000), "order planned/standard unit cost 240,000")
op_a = po.order_view(company_id, oa).operations[0].order_operation_id
mat_a = po.order_view(company_id, oa).materials[0].material_id
po.issue_materials(company_id, uid, oa, [po.IssueLine(mat_a, D(105))])
# دستمزد ۱۰ ساعت × ۵۰۰٬۰۰۰ = ۵٬۰۰۰٬۰۰۰ (مثالِ مشخصات) + ۲ ساعت اضافه‌کار
le = pk_.record_labor(company_id, uid, oa, pk_.LaborInput(hours=D(10), order_operation_id=op_a), idempotency_key="lab-1")
check(pk_.record_labor(company_id, uid, oa, pk_.LaborInput(hours=D(10), order_operation_id=op_a), idempotency_key="lab-1") == le,
      "labor entry idempotent")
check(pk_.list_labor(company_id, oa)[0].amount == D(5000000), "Direct labor: 10h x 500,000 = 5,000,000")
pk_.record_labor(company_id, uid, oa, pk_.LaborInput(hours=D(2), rate=D(800000), order_operation_id=op_a))
# ماشین ۲۰ ساعت × ۸۰۰٬۰۰۰ = ۱۶٬۰۰۰٬۰۰۰ + تخصیص در ماژولِ دارایی
from peecha.services.fixed_assets import assets as fa_assets, common as fa_common
fa_common.ensure_default_categories(company_id)
cat = [x for x in fa_common.list_categories(company_id) if x.code == "MACHINERY"][0]
mach = fa_assets.create_asset(company_id, uid, fa_assets.AssetFields(asset_code="M-1", name="برش", category_id=cat.category_id,
                                                                     is_production_machine=True))
pk_.record_machine(company_id, uid, oa, pk_.MachineInput(hours=D(20), order_operation_id=op_a, asset_id=mach))
check(pk_.list_machine(company_id, oa)[0].amount == D(16000000), "Machine cost: 20h x 800,000 = 16,000,000")
with new_session() as s:
    fa_alloc = s.scalar(select(MachineCostAllocation).where(MachineCostAllocation.production_order_ref == "PO-1"))
check(fa_alloc is not None and fa_alloc.amount == D(16000000), "machine hours linked to FA machine_cost_allocations by order code")
costs = pk_.get_order_costs(company_id, oa)
check((costs.material, costs.labor, costs.machine, costs.overhead) == (D(1050000), D(6600000), D(16000000), D(2400000)),
      f"actual elements: material/labor/machine/overhead ({costs.material},{costs.labor},{costs.machine},{costs.overhead})")
check(gl_balance(labor_gl.account_id) == D(-6600000) and gl_balance(machine_gl.account_id) == D(-16000000)
      and gl_balance(overhead_gl.account_id) == D(-2400000), "applied labor/machine/overhead credited in GL")
po.complete_order(company_id, uid, oa, po.ReceiptInput(D(100)))
costs = pk_.get_order_costs(company_id, oa)
check(costs.total == D(26050000) and costs.actual_unit_cost == D(260500), f"Actual cost per unit 260,500 ({costs.actual_unit_cost})")
check(costs.std_total == D(24000000) and costs.variance == D(2050000), f"Standard 24,000,000 / variance +2,050,000 ({costs.variance})")
var = {v.code: v.amount for v in pk_.get_variances(company_id, oa)}
check(var["MATERIAL_PRICE"] == 0 and var["MATERIAL_USAGE"] == D(50000), "material price 0 / usage +50,000 (105 vs 100 kg)")
check(var["LABOR_RATE"] == D(600000) and var["LABOR_EFFICIENCY"] == D(1000000), "labor rate +600,000 / efficiency +1,000,000")
check(var["MACHINE_RATE"] == 0 and var["MACHINE_EFFICIENCY"] == 0, "machine variances 0")
check(var["OVERHEAD"] == D(400000), "overhead variance +400,000")
check(sum(v for k, v in var.items() if k in ("MATERIAL_PRICE", "MATERIAL_USAGE", "LABOR_RATE", "LABOR_EFFICIENCY", "MACHINE_RATE",
                                              "MACHINE_EFFICIENCY", "OVERHEAD")) == var["TOTAL"] == D(2050000),
      "element variances reconcile to total production variance")
res = po.close_order(company_id, uid, oa)
check(res.residual == 0, "no residual WIP at close")
from peecha.db.models.production import OrderCostSummary, OrderVariance
with new_session() as s:
    summ = s.get(OrderCostSummary, oa)
    nvar = s.scalar(select(func.count()).select_from(OrderVariance).where(OrderVariance.order_id == oa))
check(summ.actual_unit_cost == D(260500) and summ.total_std == D(24000000) and nvar == 10, "cost summary + 10 variance rows stored at close")

# ===== محاسبهٔ خودکارِ بها (بدونِ ساعتِ واقعی) =============================================================
pc.update_settings(company_id, uid, auto_consumption=True)
ob = po.create_order(company_id, uid, OF(item_id=px, planned_qty=D(50)))
po.release_order(company_id, uid, ob)
po.complete_order(company_id, uid, ob, po.ReceiptInput(D(50)))
cb = pk_.get_order_costs(company_id, ob)
check((cb.labor, cb.machine, cb.overhead) == (D(2500000), D(8000000), D(1000000)), "auto standard labor/machine/overhead for 50 units")
check(cb.actual_unit_cost == D(240000) and cb.variance == 0, "on-standard production: actual = standard, variance 0")
po.close_order(company_id, uid, ob)
pc.update_settings(company_id, uid, auto_consumption=False, auto_cost_calculation=False)

# ===== Scenario 10: Overhead pool allocation (Cost Allocation Engine) ======================================
check(pk_.allocate(D(100), {1: D(1), 2: D(2)}) == {1: D("33.33"), 2: D("66.67")}, "generic allocation engine rounds on largest share")
oc = po.create_order(company_id, uid, OF(item_id=px, planned_qty=D(10)))
od = po.create_order(company_id, uid, OF(item_id=px, planned_qty=D(10)))
for o in (oc, od):
    po.release_order(company_id, uid, o)
    po.issue_all_remaining(company_id, uid, o)
pk_.record_machine(company_id, uid, oc, pk_.MachineInput(hours=D(20)))
pk_.record_machine(company_id, uid, od, pk_.MachineInput(hours=D(30)))
period = fa_common.period_of(today)[0]
pool = pk_.save_pool(company_id, "FOH", "سربارِ کارخانه", period, D(500000000), "MACHINE_HOURS", category="OVERHEAD", user_id=uid)
prev = {p.order_id: p.amount for p in pk_.preview_pool(company_id, pool)}
check(prev == {oc: D(200000000), od: D(300000000)}, "pool preview: 500M by machine hours 20/30")
out = pk_.allocate_pool(company_id, uid, pool)
check(sum(x.amount for x in out) == D(500000000), "overhead pool allocated")
check(raises(lambda: pk_.allocate_pool(company_id, uid, pool), "قبلاً"), "pool cannot be allocated twice")
check(pk_.get_order_costs(company_id, oc).overhead == D(200000000), "order C overhead 200M")
pool2 = pk_.save_pool(company_id, "ELEC", "برق", period, D(1000), "PERCENTAGE", category="ELECTRICITY")
check(raises(lambda: pk_.allocate_pool(company_id, uid, pool2, {oc: D(50), od: D(40)}), "۱۰۰"), "percentage must total 100")
pk_.allocate_pool(company_id, uid, pool2, {oc: D(60), od: D(40)})
with new_session() as s:
    check(s.scalar(select(func.count()).select_from(CostAllocationRow)) == 4, "allocation rows recorded per order")
check(gl_balance(overhead_gl.account_id) == D(-2400000 - 1000000 - 500001000), "overhead applied credited")

# ===== Scenario: Co-Products ============================================================================
ca = item("CO-A", "محصولِ مشترکِ A", "FINISHED_GOOD")
cb_ = item("CO-B", "محصولِ مشترکِ B", "FINISHED_GOOD")
cc = item("CO-C", "محصولِ مشترکِ C", "FINISHED_GOOD")
bj = pm.create_bom_version(company_id, ca, BF(batch_size_qty=D(500)))
pm.add_bom_component(company_id, bj, BL(r1, D(1000)))
pm.save_bom_output(company_id, bj, pm.BomOutputFields(cb_, "CO_PRODUCT", D(300)))
pm.save_bom_output(company_id, bj, pm.BomOutputFields(cc, "CO_PRODUCT", D(200)))
oj = po.create_order(company_id, uid, OF(item_id=ca, planned_qty=D(500)))
po.release_order(company_id, uid, oj)
po.issue_all_remaining(company_id, uid, oj)
po.complete_order(company_id, uid, oj, po.ReceiptInput(D(500), {cb_: D(300), cc: D(200)}, joint_method="QUANTITY"))
outs = {o.item_id: o.produced_amount for o in po.order_view(company_id, oj).outputs}
check(outs == {ca: D(5000000), cb_: D(3000000), cc: D(2000000)}, f"joint cost 10M by quantity 500/300/200 ({outs})")
oj2 = po.create_order(company_id, uid, OF(item_id=ca, planned_qty=D(500)))
po.release_order(company_id, uid, oj2)
po.issue_all_remaining(company_id, uid, oj2)
check(raises(lambda: po.complete_order(company_id, uid, oj2, po.ReceiptInput(D(500), {cb_: D(300), cc: D(200)}, joint_method="PERCENTAGE",
                                                                                 manual_shares={ca: D(50), cb_: D(30), cc: D(10)})), "۱۰۰"),
      "percentage shares must total 100 (and nothing posted)")
po.complete_order(company_id, uid, oj2, po.ReceiptInput(D(500), {cb_: D(300), cc: D(200)}, joint_method="SALES_VALUE",
                                                        sales_values={ca: D(40000), cb_: D(30000), cc: D(20000)}))
outs = {o.item_id: o.produced_amount for o in po.order_view(company_id, oj2).outputs}
check(sum(outs.values()) == D(10000000) and outs[cb_] == D("2727272.73"), f"joint cost by sales value 20M/9M/4M ({outs})")
check(po.get_order(company_id, oj2).joint_cost_method == "SALES_VALUE", "joint method chosen at completion stored on order")
check(po.allocate_joint(D(1000), [D(1), D(1), D(1)]) == [D("333.33"), D("333.33"), D("333.34")], "joint rounding")
check(po.allocate_joint(D(1000), [D(600), D(400)], "MANUAL") == [D(600), D(400)], "manual joint amounts")

# ===== کالایِ با روشِ STANDARD: انحرافِ رسید به حسابِ انحرافِ تولید ======================================
ps = catalog_service.create_item(company_id, "PS", "محصولِ استاندارد", catalog_service.ItemFields(
    item_kind_code="FINISHED_GOOD", base_uom_id=pcs, costing_method_code="STANDARD"))
bs = pm.create_bom_version(company_id, ps, BF(batch_size_qty=D(1)))
pm.add_bom_component(company_id, bs, BL(r1, D(1)))
pk_.rollup_standard_cost(company_id, ps, write=True)
var_before = gl_balance(variance_gl.account_id)
os_ = po.create_order(company_id, uid, OF(item_id=ps, planned_qty=D(10)))
po.release_order(company_id, uid, os_)
po.issue_materials(company_id, uid, os_, [po.IssueLine(po.order_view(company_id, os_).materials[0].material_id, D(12))])
po.complete_order(company_id, uid, os_, po.ReceiptInput(D(10)))
check(gl_balance(variance_gl.account_id) - var_before == D(20000), "standard-costed product: receipt at standard, +20,000 to production variance")
from peecha.db.models.inventory import StockBalance
with new_session() as s:
    avg = s.scalar(select(StockBalance.average_unit_cost).where(StockBalance.item_id == ps))
check(avg == D(10000), "standard-costed product valued at standard 10,000")

# ===== Scenario 12: همخوانیِ WIP و دفترِ کل ================================================================
with new_session() as s:
    wip_sub = D(s.scalar(select(func.coalesce(func.sum(OrderTransaction.wip_delta), 0))))
check(wip_sub == gl_balance(wip_gl.account_id), f"WIP sub-ledger == GL ({wip_sub})")

# ===== Cost Closing ======================================================================================
pv = pk_.period_preview(company_id, period)
check(pv.orders_count >= 6 and pv.overhead_applied > 0 and pv.wip_balance == wip_sub, "period preview numbers")
pool3 = pk_.save_pool(company_id, "RENT", "اجاره", period, D(1000), "MACHINE_HOURS", category="RENT")
check(raises(lambda: pk_.close_period(company_id, uid, period), "سرشکن‌نشده"), "period close blocked by unallocated pool")
pk_.allocate_pool(company_id, uid, pool3)
pc.update_settings(company_id, uid, require_cost_closing=True)
check(raises(lambda: pk_.close_period(company_id, uid, period), "بسته‌نشده"), "require_cost_closing blocks while completed orders open")
pc.update_settings(company_id, uid, require_cost_closing=False)
cid = pk_.close_period(company_id, uid, period)
check(cid > 0 and pk_.list_closings(company_id)[0].status_code == "FINALIZED", "period finalized")
check(raises(lambda: pk_.record_labor(company_id, uid, oc, pk_.LaborInput(hours=D(1))), "بسته"), "closed period blocks new production postings")
check(raises(lambda: pk_.close_period(company_id, uid, period), "قبلاً"), "period cannot close twice")
pk_.reopen_period(company_id, uid, period, "اصلاحِ سربار")
pk_.record_labor(company_id, uid, oc, pk_.LaborInput(hours=D(1), rate=D(100)))
check(True, "reopened period accepts postings")

# Audit
from peecha.db.models.audit import ActivityLog
with new_session() as s:
    ops = {r.changes.get("operation") for r in s.scalars(select(ActivityLog).where(ActivityLog.entity_type.in_(
        ("ProductionOrder", "CostPool", "CostClosing", "StandardCost"))))}
check({"LABOR", "ISSUE", "RECEIPT", "CLOSE", "ALLOCATE", "PERIOD_CLOSE", "PERIOD_REOPEN", "COST_UPDATE"} <= ops,
      "audit trail for consumption, receipt, close, cost changes, allocation and period close")

# خام‌کردنِ اطلاعات با دادهٔ تولید
from peecha.services import data_reset
data_reset.wipe_documents(company_id)
with new_session() as s:
    left = s.scalar(text("SELECT count(*) FROM prd.production_orders")) + s.scalar(text("SELECT count(*) FROM prd.order_transactions"))
check(left == 0, "data reset wipes production orders/transactions")
data_reset.wipe_master_data(company_id)
with new_session() as s:
    left = s.scalar(text("SELECT count(*) FROM prd.work_centers")) + s.scalar(text("SELECT count(*) FROM prd.routings"))
check(left == 0, "data reset wipes production master data")

fx.finish()
