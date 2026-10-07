import os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r266"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prd_fixture import *  # noqa: F401,F403
import prd_fixture as fx

from peecha.services.production import common as pc, master as pm
from peecha.services import inventory_extended as ext
from peecha.db.models.audit import ActivityLog
from peecha.db.models.inventory import BomLine

check = fx.check

# --- تنظیمات ---------------------------------------------------------------------
st = pc.get_settings(company_id)
check(st.shortage_policy == "WARN" and st.auto_reservation and st.order_prefix == "PO", "default production settings")
pc.update_settings(company_id, uid, default_material_warehouse_id=wh_rm, default_fg_warehouse_id=wh_fg,
                   default_production_warehouse_id=wh_line, default_scrap_warehouse_id=wh_scrap, shortage_policy="BLOCK")
st = pc.get_settings(company_id)
check(st.default_fg_warehouse_id == wh_fg and st.shortage_policy == "BLOCK", "settings updated")
check(raises(lambda: pc.update_settings(company_id, uid, shortage_policy="X"), "نامعتبر"), "invalid setting rejected")
check(raises(lambda: pc.update_settings(company_id, uid, foo=1), "نامعتبر"), "unknown setting rejected")
check(pc.missing_roles(company_id, (pc.WIP, pc.LABOR_APPLIED)) == [], "production account roles configured")
check("PRODUCTION_WIP" in engine_service.MAPPING_LABELS, "production roles visible in inventory mapping settings")

# --- مرکزِ کاری ------------------------------------------------------------------
WCF = pm.WorkCenterFields
wc_cut = pm.save_work_center(company_id, WCF(code="CUT", name="برش", center_type="MACHINING", labor_rate=D(500000),
                                             machine_rate=D(800000), overhead_rate=D(200000), shifts_per_day=2), user_id=uid)
wc_asm = pm.save_work_center(company_id, WCF(code="ASM", name="مونتاژ", center_type="ASSEMBLY", labor_rate=D(400000)), user_id=uid)
wc_pack = pm.save_work_center(company_id, WCF(code="PACK", name="بسته‌بندی", center_type="PACKING", labor_rate=D(300000)), user_id=uid)
check(raises(lambda: pm.save_work_center(company_id, WCF(code="CUT", name="x")), "قبلاً"), "duplicate work center code")
check(raises(lambda: pm.save_work_center(company_id, WCF(code="Z", name="x", labor_rate=D(-1))), "منفی"), "negative rate rejected")
wc = pm.get_work_center(company_id, wc_cut)
check(wc.daily_hours == D(16), "daily hours = shifts x hours")
cap = pm.capacity_hours(wc, today, today + datetime.timedelta(days=6))
check(cap == D("96.00"), f"weekly capacity 6 days x 16h = 96 ({cap})")

# ماشین = داراییِ ثابت
from peecha.services.fixed_assets import assets as fa_assets, common as fa_common
fa_common.ensure_default_categories(company_id)
cat = [x for x in fa_common.list_categories(company_id) if x.code == "MACHINERY"][0]
m1 = fa_assets.create_asset(company_id, uid, fa_assets.AssetFields(asset_code="M-01", name="دستگاه برش", category_id=cat.category_id,
                                                                   is_production_machine=True, work_center_code="CUT"))
m2 = fa_assets.create_asset(company_id, uid, fa_assets.AssetFields(asset_code="M-02", name="میز", category_id=cat.category_id))
check(raises(lambda: pm.link_machine(company_id, wc_asm, m2), "ماشین تولیدی"), "non-machine asset cannot be linked")
pm.link_machine(company_id, wc_asm, m1, uid)
check({m.asset_id for m in pm.work_center_machines(company_id, wc_cut)} == {m1}, "machine found by FA work_center_code")
check([m.linked for m in pm.work_center_machines(company_id, wc_asm)] == [True], "explicitly linked machine")

# دستمزد
emp_rate = pm.save_labor_rate(company_id, "L1", "اپراتور ارشد", D(600000), user_id=uid)
check(len(pm.list_labor_rates(company_id)) == 1, "labor rate saved")
with new_session() as s:
    check(pm.labor_rate_for(s, company_id, None, wc_cut)[0] == D(500000), "labor rate falls back to work center")
    check(pm.labor_rate_for(s, company_id, None, wc_cut, D(700000))[0] == D(700000), "operation rate overrides work center")

op_cut = pm.save_operation(company_id, "OP-CUT", "برش", wc_cut, D(30), D(2))
check(len(pm.list_operations(company_id)) == 1, "operation catalog")

# --- مشخصاتِ تولیدیِ کالا ------------------------------------------------------------
pm.save_item_profile(company_id, fg, uid, min_lot_qty=D(10), max_lot_qty=D(5000), lead_time_days=3, standard_scrap_percent=D(2))
prof = pm.get_item_profile(company_id, fg)
check(prof.lead_time_days == 3 and prof.make_or_buy == "MAKE", "item production profile")
check(raises(lambda: pm.save_item_profile(company_id, fg, uid, min_lot_qty=D(100), max_lot_qty=D(5)), "حداکثر"), "min>max rejected")
with new_session() as s:
    check(raises(lambda: pm.check_lot_size(s, fg, D(5)), "حداقل"), "lot below minimum blocked")
pm.save_item_profile(company_id, r1, uid, make_or_buy="BUY", lead_time_days=7)

# --- مسیرِ تولید -------------------------------------------------------------------
RO = pm.RoutingOpFields
rt = pm.create_routing(company_id, fg, "مسیر استاندارد", [
    RO(10, "برش", wc_cut, operation_id=op_cut, setup_minutes=D(30), run_minutes=D(2), asset_id=m1),
    RO(20, "مونتاژ", wc_asm, run_minutes=D(3)),
    RO(30, "بسته‌بندی", wc_pack, run_minutes=D(1)),
], user_id=uid)
ops = pm.routing_operations(company_id, rt)
check([o.seq for o in ops] == [10, 20, 30], "routing operations ordered")
check(pm.list_routings(company_id, fg)[0].is_default, "first routing is default")
check(raises(lambda: pm.add_routing_operation(company_id, rt, RO(20, "تکراری")), "تکراری"), "duplicate sequence")
h = pm.op_hours(ops[0], D(100))
check(h.labor_hours == D("3.8333") and h.machine_hours == D("3.8333"), f"op hours (30+200 min)/60 ({h.labor_hours})")
rt2 = pm.create_routing(company_id, fg, "نسخهٔ ۲", copy_from_routing_id=rt, user_id=uid)
check(len(pm.routing_operations(company_id, rt2)) == 3 and not [r for r in pm.list_routings(company_id, fg) if r.routing_id == rt2][0].is_default,
      "routing copied as new non-default version")
pm.set_default_routing(company_id, rt2)
check([r.routing_id for r in pm.list_routings(company_id, fg) if r.is_default] == [rt2], "single default routing")
pm.set_default_routing(company_id, rt)

# --- BOM (روی جدولِ موجود) ----------------------------------------------------------
BF, BL = pm.BomFields, pm.BomLineFields
# نیمه‌ساخته: ۲ کیلو RM-3 به‌ازایِ هر عدد
bom_semi = pm.create_bom_version(company_id, semi, BF(batch_size_qty=D(1)), user_id=uid)
pm.add_bom_component(company_id, bom_semi, BL(r3, D(2)), uid)
# محصول: دستهٔ ۱۰۰تایی -> ۲۰۰ کیلو RM-1 (۳٪ ضایعات)، ۱۰۰ کیلو RM-2، ۱۰۰ عدد نیمه‌ساخته، ۱۰۰ کارتن، ۵ کیلو مصرفیِ ثابت
bom_v1 = pm.create_bom_version(company_id, fg, BF(batch_size_qty=D(100), name="فرمول اصلی", routing_id=rt), user_id=uid)
l1 = pm.add_bom_component(company_id, bom_v1, BL(r1, D(200), uom_id=kg, scrap_percent=D(3), operation_seq=10), uid)
pm.add_bom_component(company_id, bom_v1, BL(r2, D(100), uom_id=kg), uid)
pm.add_bom_component(company_id, bom_v1, BL(semi, D(100), component_type="SEMI_FINISHED", operation_seq=20), uid)
pm.add_bom_component(company_id, bom_v1, BL(pk, D(100), component_type="PACKAGING", operation_seq=30), uid)
pm.add_bom_component(company_id, bom_v1, BL(r2, D(5), uom_id=kg, quantity_type="FIXED", component_type="CONSUMABLE"), uid)
pm.save_bom_output(company_id, bom_v1, pm.BomOutputFields(byp, "BY_PRODUCT", D(10), recovery_value_per_unit=D(5000)), uid)
check(raises(lambda: pm.save_bom_output(company_id, bom_v1, pm.BomOutputFields(fg, "BY_PRODUCT", D(1))), "اصلی"), "main product not an output")
vers = pm.list_bom_versions(company_id, fg)
check(len(vers) == 1 and vers[0].is_default and vers[0].component_count == 5 and vers[0].routing_id == rt, "BOM v1 default with 5 components")
check(vers[0].code == f"BOM-{fg}-V1", "BOM code")
check(raises(lambda: pm.add_bom_component(company_id, bom_v1, BL(fg, D(1))), "خودش"), "self component rejected")
check(raises(lambda: pm.add_bom_component(company_id, bom_semi, BL(fg, D(1))), "حلقه"), "multi-level cycle rejected")
check(raises(lambda: pm.add_bom_component(company_id, bom_v1, BL(r1, D(0))), "بزرگ‌تر"), "zero qty rejected")
check(pm.validate_bom(company_id, bom_v1) == [], "BOM validates clean")

# نیاز: ۱۰۰ کیلو با ۳٪ = ۱۰۳
net, gross = pm.line_requirement(D(100), "VARIABLE", D(3), D(50), D(50))
check((net, gross) == (D(100), D(103)), "scrap: 100kg + 3% = 103kg")
net, gross = pm.line_requirement(D(5), "FIXED", D(0), D(1000), D(100))
check(net == D(5), "fixed quantity independent of order qty")

# انفجارِ چندسطحی برایِ ۵۰ عدد
rows = pm.explode(company_id, fg, D(50))
by = {(r.level, r.item_id): r for r in rows}
check(by[(1, r1)].gross_qty == D(103), f"level1 RM-1 50 units -> 103kg ({by[(1, r1)].gross_qty})")
check(by[(1, semi)].is_made and by[(2, r3)].gross_qty == D(100), "level2 semi-finished exploded: 50 x 2kg = 100kg")
check(by[(1, pk)].component_type == "PACKAGING", "packaging component type")
check([w.item_id for w in pm.where_used(company_id, r3)] == [semi], "where-used")

# نسخه‌بندی: نسخهٔ ۲ کپیِ ۱، پیش‌فرض نمی‌شود
bom_v2 = pm.create_bom_version(company_id, fg, BF(batch_size_qty=D(100)), copy_from_bom_id=bom_v1, user_id=uid)
check(len(pm.bom_components(company_id, bom_v2)) == 5 and len(pm.bom_outputs(company_id, bom_v2)) == 1, "v2 copies lines and outputs")
check([v.version_no for v in pm.list_bom_versions(company_id, fg) if v.is_default] == [1], "v1 stays default")
with new_session() as s:
    check(pm.effective_bom_id(s, fg) == bom_v1, "effective BOM = default")
pm.update_bom(company_id, bom_v1, BF(batch_size_qty=D(100), name="فرمول اصلی", routing_id=rt,
                                    valid_to=today - datetime.timedelta(days=1)), uid, reason="پایان اعتبار")
with new_session() as s:
    check(pm.effective_bom_id(s, fg) == bom_v2, "expired default -> latest valid version")
pm.update_bom(company_id, bom_v1, BF(batch_size_qty=D(100), name="فرمول اصلی", routing_id=rt), uid)

# قفل: نسخهٔ استفاده‌شده تغییر نمی‌کند (نه از سرویسِ جدید نه از تبِ قدیمیِ فرمِ کالا)
with new_session() as s:
    pm.lock_bom(s, bom_v1)
    s.commit()
check(raises(lambda: pm.add_bom_component(company_id, bom_v1, BL(r3, D(1))), "قفل"), "locked BOM rejects new component")
check(raises(lambda: pm.remove_bom_component(company_id, l1), "قفل"), "locked BOM rejects removal")
check(raises(lambda: ext.add_bom_line(bom_v1, r3, D(1)), "قفل"), "legacy item-panel add blocked on locked BOM")
check(raises(lambda: ext.remove_bom_line(l1, bom_v1), "قفل"), "legacy item-panel remove blocked on locked BOM")
check(raises(lambda: pm.update_bom(company_id, bom_v1, BF(batch_size_qty=D(50), routing_id=rt)), "قفل"), "locked header qty")
pm.update_bom(company_id, bom_v1, BF(batch_size_qty=D(100), name="فرمول اصلی", routing_id=rt, notes="یادداشت"), uid)
check(True, "locked BOM accepts notes change")
# BOMِ قدیمیِ فرمِ کالا هنوز کار می‌کند
legacy = ext.create_bom(r1 if False else semi)
check(len(ext.list_boms(semi)) == 2 and ext.add_bom_line(legacy, r3, D(1)) > 0, "legacy item-panel BOM API unchanged")

# Audit
with new_session() as s:
    n = s.scalar(select(func.count()).select_from(ActivityLog).where(ActivityLog.entity_type == "BOM"))
check(n >= 8, f"BOM changes audited ({n})")

# quick BOM (کاربرِ ساده)
qb = pm.quick_bom(company_id, byp, [(r1, D(1))], user_id=uid)
check(pm.list_bom_versions(company_id, byp)[0].is_default and len(pm.bom_components(company_id, qb)) == 1, "quick BOM")

# موتورِ انبار: رفتارِ بدونِ پارامترِ جدید عوض نشده
doc = receive(r1, 10, 10000)
from peecha.db.models.inventory import StockDocument
with new_session() as s:
    d = s.get(StockDocument, doc)
    check(d.status_code == "POSTED" and d.journal_entry_id is not None, "plain stock posting unchanged (separate JE)")

fx.finish()
