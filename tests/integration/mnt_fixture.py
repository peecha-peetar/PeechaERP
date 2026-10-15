"""Shared setup for maintenance (mnt) integration tests. Import after setting PEECHA_DB_NAME."""
from prd_fixture import *  # noqa: F401,F403
import prd_fixture as _pf
from peecha.services.fixed_assets import assets as fa, common as fac, events as fe
from peecha.services.production import master as pm, planning as pp
from peecha.services import stock_controls as sc
from peecha.services.maintenance import (
    availability as av, common as mc, costs as mcost, equipment as eq, parts as mparts, pm as mpm, reliability as rel,
    requests as mreq, work_orders as wos,
)

days = datetime.timedelta
check, raises, finish = _pf.check, _pf.raises, _pf.finish

k_fa = A("14", "دارایی‌های ثابت", "DEBIT", "ASSET", "PERMANENT", False, g1.account_id)
fa_asset = A("1401", "ماشین‌آلات", "DEBIT", "ASSET", "PERMANENT", True, k_fa.account_id)
fa_accum = A("1409", "استهلاک انباشته", "CREDIT", "ASSET", "PERMANENT", True, k_fa.account_id)
k_ex = A("62", "هزینه‌های نگهداری", "DEBIT", "EXPENSE", "TEMPORARY", False, g3.account_id)
dep_exp = A("6204", "هزینهٔ استهلاک", "DEBIT", "EXPENSE", "TEMPORARY", True, k_ex.account_id)
repair_gl = A("6210", "هزینهٔ تعمیرات", "DEBIT", "EXPENSE", "TEMPORARY", True, k_ex.account_id)
parts_gl = A("6211", "هزینهٔ قطعات تعمیر", "DEBIT", "EXPENSE", "TEMPORARY", True, k_ex.account_id)
engine_service.set_account_mapping(company_id, "MAINTENANCE_EXPENSE", parts_gl.account_id)

mach = fac.save_category(company_id, fac.CategoryFields("MACH", "ماشین‌آلات", "STRAIGHT_LINE", 120, accounts=dict(
    asset_account_id=fa_asset.account_id, accumulated_depreciation_account_id=fa_accum.account_id,
    depreciation_expense_account_id=dep_exp.account_id, maintenance_expense_account_id=repair_gl.account_id)))
seller = dimensions_service.create_supplier(company_id, "S-FA", "فروشندهٔ ماشین")
contractor = dimensions_service.create_supplier(company_id, "S-SRV", "پیمانکار تعمیرات")
cc_type = dimensions_service.get_specialized_dimension_type_id(company_id, dimensions_service.COST_CENTER_CODE)
cc_line = dimensions_service.create_detail_account(company_id, cc_type, "CC-L1", "خط تولید ۱").detail_account_id

site = fac.save_location(company_id, "SITE-1", "سایت مرکزی", "SITE")
plant = fac.save_location(company_id, "PL-1", "کارخانهٔ ۱", "PLANT", site)
area = fac.save_location(company_id, "AR-1", "سالن برش", "AREA", plant)
line = fac.save_location(company_id, "LN-1", "خط ۱", "LINE", area)

wc = pm.save_work_center(company_id, pm.WorkCenterFields(code="CUT", name="برش"), user_id=uid)


def machine(code, parent=None, production=True, serial=None):
    aid = fa.create_asset(company_id, uid, fa.AssetFields(
        asset_code=code, name="دستگاه " + code, category_id=mach, asset_type_code="MACHINE", brand="سازندهٔ الف", model="M-100",
        serial_no=serial or f"SN-{code}", parent_asset_id=parent, location_id=line, cost_center_detail_account_id=cc_line,
        supplier_detail_account_id=seller, is_production_machine=production, work_center_code="CUT" if production else None))
    fa.acquire(company_id, uid, aid, today - days(400), [fa.CostItem("PURCHASE", D(120_000_000), ap_gl.account_id, seller)])
    fa.capitalize(company_id, uid, aid, today - days(400), in_service_date=today - days(365))
    return aid


def asset_status(aid):
    return fa.get_asset(company_id, aid).status_code


def cap(d0, d1):
    return next(x for x in pp.capacity_load(company_id, d0, d1) if x.work_center_id == wc)


def toggle(code, on=True):
    engine_service.set_feature_enabled(company_id, code, on)


spare = item("SP-1", "بلبرینگ ۶۲۰۵", "GOOD")
belt = item("SP-2", "تسمهٔ انتقال", "GOOD")
receive(spare, 10, 500_000)
receive(belt, 2, 1_000_000)
