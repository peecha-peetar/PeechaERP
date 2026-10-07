import os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r269"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prd_fixture import *  # noqa: F401,F403
import prd_fixture as fx

from peecha.services.production import common as pc, master as pm, orders as po, planning as pp
from peecha.services import commercial_documents as documents_service, purchase_requests as pr_service
check = fx.check

pc.update_settings(company_id, uid, default_material_warehouse_id=wh_rm, default_fg_warehouse_id=wh_fg)
BF, BL, WCF, RO = pm.BomFields, pm.BomLineFields, pm.WorkCenterFields, pm.RoutingOpFields
wc = pm.save_work_center(company_id, WCF(code="L1", name="خط ۱", shifts_per_day=1, hours_per_shift=D(8), working_days_per_week=7))
rt = pm.create_routing(company_id, fg, "مسیر", [RO(10, "مونتاژ", wc, run_minutes=D(30))])
bom_semi = pm.create_bom_version(company_id, semi, BF(batch_size_qty=D(1)))
pm.add_bom_component(company_id, bom_semi, BL(r3, D(1)))
bom = pm.create_bom_version(company_id, fg, BF(batch_size_qty=D(1), routing_id=rt))
pm.add_bom_component(company_id, bom, BL(r1, D(2)))
pm.add_bom_component(company_id, bom, BL(semi, D(1), component_type="SEMI_FINISHED"))
pm.add_bom_component(company_id, bom, BL(pk, D(1), component_type="PACKAGING"))
pm.save_item_profile(company_id, fg, uid, lead_time_days=3, lot_multiple_qty=D(10))
pm.save_item_profile(company_id, r1, uid, make_or_buy="BUY", lead_time_days=7)
receive(r1, 100, 10000)
receive(pk, 20, 1000)
receive(fg, 10, 300000, wh=wh_fg)
from peecha.db.models.inventory import ReorderPolicy
with new_session() as s:
    s.add(ReorderPolicy(company_id=company_id, item_id=pk, warehouse_id=wh_rm, min_qty=D(50), max_qty=D(100)))
    s.commit()

customer = dimensions_service.create_customer(company_id, "C1", "مشتری")
wh_sales = locations_service.create_warehouse(company_id, "SALE", "انبار فروش", WF(allow_negative_stock=True))
so = documents_service.create_document(company_id, uid, "SALES_ORDER", today, documents_service.DocumentHeaderFields(
    counterparty_detail_account_id=customer, currency_id=company.base_currency_id, warehouse_id=wh_sales))
documents_service.add_line(so, company_id, item_id=fg, uom_id=pcs, quantity=D(100), quantity_base=D(100), unit_price=D(500000))
documents_service.confirm_document(so, company_id, uid)
pord = documents_service.create_document(company_id, uid, "PURCHASE_ORDER", today, documents_service.DocumentHeaderFields(
    counterparty_detail_account_id=supplier, currency_id=company.base_currency_id, warehouse_id=wh_rm))
documents_service.add_line(pord, company_id, item_id=r3, uom_id=kg, quantity=D(30), quantity_base=D(30), unit_price=D(5000))
documents_service.confirm_document(pord, company_id, uid)

check([d.quantity for d in pp.open_sales_demand(company_id)] == [D(100)], "open sales order demand read from commercial module")
check(pp.open_purchase_supply(company_id).get(r3) == D(30), "open purchase order supply read from commercial module")

# ===== برنامهٔ تولید ==================================================================================
from peecha.services.fixed_assets.common import period_of
_c, mstart, mend = period_of(today)
plan = pp.create_plan(company_id, uid, "P-1", "برنامهٔ ماه", today, mend, "WEEK")
added = pp.generate_from_sales_orders(company_id, plan)
lines = pp.plan_lines(company_id, plan)
check(added == 1 and lines[0].quantity == D(90) and lines[0].source_type == "SALES_ORDER", "plan from sales order: 100 - 10 free = 90")
check(lines[0].work_center_id == wc, "plan line gets routing work center")
check(pp.generate_from_sales_orders(company_id, plan) == 0, "sales-order plan lines not duplicated")
with new_session() as s:
    s.add(ReorderPolicy(company_id=company_id, item_id=fg, warehouse_id=wh_fg, min_qty=D(20), max_qty=D(40)))
    s.commit()
check(pp.generate_from_min_stock(company_id, plan) == 1, "plan from minimum stock (made items only)")
check(raises(lambda: pp.add_plan_line(company_id, plan, fg, mend + datetime.timedelta(days=40), D(1)), "بازه"), "plan line outside plan range")
summ = pp.plan_summary(company_id, plan)
check(sum(x.quantity for x in summ) == D(90) + D(30), f"plan weekly summary ({[(x.period_start, x.quantity) for x in summ]})")
check(raises(lambda: pp.convert_plan_to_orders(company_id, uid, plan), "تایید"), "unapproved plan cannot convert")
pp.approve_plan(company_id, uid, plan)

# ===== MRP ======================================================================================
run = pp.run_mrp(company_id, uid)
mrp = {r.item_id: r for r in pp.mrp_lines(company_id, run)}
f = mrp[fg]
check(f.independent_demand == D(220) and f.available == D(10), f"FG gross = SO 100 + approved plan 120 ({f.independent_demand})")
check(f.min_stock == D(20) and f.suggested_action == "PRODUCE" and f.suggested_qty == D(230), f"FG produce 220 + min 20 - 10 = 230 ({f.suggested_qty})")
check(mrp[semi].suggested_action == "PRODUCE" and mrp[semi].dependent_demand == D(230) and mrp[semi].level == 1,
      "multi-level: semi-finished dependent demand 230 at level 1")
check(mrp[r3].suggested_action == "PURCHASE" and mrp[r3].scheduled_receipts == D(30) and mrp[r3].suggested_qty == D(200),
      f"level 2 raw material: 230 - open PO 30 = buy 200 ({mrp[r3].suggested_qty})")
check(mrp[r1].suggested_qty == D(360) and mrp[r1].release_date == mrp[r1].need_date - datetime.timedelta(days=7),
      "RM-1 buy 460-100 = 360, release = need - 7 days lead time")
check(mrp[pk].min_stock == D(50) and mrp[pk].suggested_qty == D(230 + 50 - 20), "packaging includes minimum stock")

# مثالِ مشخصات: نیاز ۱۰۰۰، موجود ۶۰۰، رزرو ۲۰۰ → کمبود ۶۰۰
fg2 = item("FG-B", "محصول B", "FINISHED_GOOD")
b2 = pm.create_bom_version(company_id, fg2, BF(batch_size_qty=D(1)))
pm.add_bom_component(company_id, b2, BL(r2, D(1)))
receive(r2, 600, 20000)
fg3 = item("FG-C", "محصول C", "FINISHED_GOOD")
b3 = pm.create_bom_version(company_id, fg3, BF(batch_size_qty=D(1)))
pm.add_bom_component(company_id, b3, BL(r2, D(1)))
oy = po.create_order(company_id, uid, po.OrderFields(item_id=fg3, planned_qty=D(200)))
po.release_order(company_id, uid, oy)          # ۲۰۰ رزرو
po.create_order(company_id, uid, po.OrderFields(item_id=fg2, planned_qty=D(1000)))  # نیازِ ۱۰۰۰ (پیش‌نویس)
run2 = pp.run_mrp(company_id, uid, include_sales=False, include_plans=False, include_min_stock=False)
x = {r.item_id: r for r in pp.mrp_lines(company_id, run2)}[r2]
check((x.gross_requirement, x.on_hand, x.reserved, x.available, x.net_requirement) == (D(1000), D(600), D(200), D(400), D(600)),
      f"spec example: required 1000, on hand 600, reserved 200 -> shortage 600 ({x.net_requirement})")

# تبدیلِ پیشنهادها
res = pp.convert_mrp(company_id, uid, [mrp[fg].mrp_line_id, mrp[r1].mrp_line_id, mrp[pk].mrp_line_id])
check(len(res.order_ids) == 1 and po.get_order(company_id, res.order_ids[0]).planned_qty == D(230), "MRP PRODUCE -> draft production order")
_req, req_lines = pr_service.get_request(res.purchase_request_id, company_id)
check({ln.item_id: ln.quantity for ln in req_lines} == {r1: D(360), pk: D(260)}, "MRP PURCHASE -> existing purchase request module")
again = pp.convert_mrp(company_id, uid, [mrp[fg].mrp_line_id])
check(again.order_ids == [] and again.purchase_request_id is None, "converted MRP lines are not converted twice")
check({r.item_id: r.converted_ref for r in pp.mrp_lines(company_id, run)}[fg].startswith("PO-"), "MRP line keeps conversion reference")

# تبدیلِ برنامه
created = pp.convert_plan_to_orders(company_id, uid, plan)
check(len(created) == 2 and all(l.order_code for l in pp.plan_lines(company_id, plan)), "approved plan lines -> production orders")
o = po.get_order(company_id, created[0])
check(o.due_date - o.start_date == datetime.timedelta(days=3), "order dates from plan date and lead time")
check(pp.convert_plan_to_orders(company_id, uid, plan) == [], "plan conversion idempotent")

# ===== ظرفیت و تقویم ===============================================================================
for oid in created:
    po.release_order(company_id, uid, oid)
week_end = today + datetime.timedelta(days=6)
cap = {x.work_center_id: x for x in pp.capacity_load(company_id, today - datetime.timedelta(days=10), week_end + datetime.timedelta(days=60))}[wc]
check(cap.capacity_hours > 0 and cap.load_hours > 0 and cap.orders, f"capacity load computed ({cap.load_hours} / {cap.capacity_hours})")
o_big = po.create_order(company_id, uid, po.OrderFields(item_id=fg, planned_qty=D(1000), start_date=today, due_date=today))
po.release_order(company_id, uid, o_big)
cap2 = {x.work_center_id: x for x in pp.capacity_load(company_id, today, today)}[wc]
check(cap2.overloaded and cap2.utilization > 100, f"one-day 500h load on 8h line is overloaded ({cap2.utilization}%)")
cal = pp.calendar(company_id, today, week_end)
mine = [e for e in cal if e.order_id == o_big]
check(len(mine) == 1 and mine[0].quantity == D(1000) and mine[0].work_center == "خط ۱", "calendar: what/how much/which day/which line")
check(any(e.kind == "ORDER" for e in cal) and all(today <= e.date <= week_end for e in cal), "calendar limited to range")

from peecha.services import data_reset
data_reset.wipe_documents(company_id)
with new_session() as s:
    check(s.scalar(text("SELECT count(*) FROM prd.production_plans")) + s.scalar(text("SELECT count(*) FROM prd.mrp_runs")) == 0,
          "data reset wipes plans and MRP runs")

fx.finish()
