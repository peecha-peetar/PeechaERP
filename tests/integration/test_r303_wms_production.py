"""R303: کلید «خروج فقط از موجودی آزاد» در تولید — رزرو خود دستور مانع مصرفش نیست، رزرو دستور دیگر هست."""
import os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r303_prd"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prd_fixture import *  # noqa: F401,F403
import prd_fixture as fx

from peecha.services import inventory_engine as engine_service
from peecha.services import stock_controls as sc
from peecha.services.production import common as pc, master as pm, orders as po
from peecha.db.models.inventory import StockBalance, StockReservation
check, raises = fx.check, fx.raises

pc.update_settings(company_id, uid, default_material_warehouse_id=wh_rm, default_fg_warehouse_id=wh_fg,
                   default_scrap_warehouse_id=wh_scrap)
bom = pm.create_bom_version(company_id, fg, pm.BomFields(batch_size_qty=D(1)), user_id=uid)
pm.add_bom_component(company_id, bom, pm.BomLineFields(r1, D(1)), uid)
receive(r1, 10, 1000)
engine_service.set_feature_enabled(company_id, sc.RESERVATION, True)


def reserved_r1():
    with new_session() as s:
        return s.scalar(select(func.coalesce(func.sum(StockBalance.quantity_reserved), 0)).where(StockBalance.item_id == r1)) or D(0)


OF = po.OrderFields
o1 = po.create_order(company_id, uid, OF(item_id=fg, planned_qty=D(6)))
po.release_order(company_id, uid, o1, reserve=True)
check(reserved_r1() == 6, "order 1 reserves 6 of 10")
o2 = po.create_order(company_id, uid, OF(item_id=fg, planned_qty=D(6)))
po.release_order(company_id, uid, o2)
material = lambda order_id: next(m for m in po.order_view(company_id, order_id).materials if m.item_id == r1)  # noqa: E731
m2 = material(o2)
check(raises(lambda: po.issue_materials(company_id, uid, o2, [po.IssueLine(m2.material_id, D(5))]), "رزرو"),
      "order 2 cannot consume stock reserved for order 1")
po.issue_materials(company_id, uid, o2, [po.IssueLine(m2.material_id, D(4))])
check(on_hand(r1, wh_rm) == 6 and reserved_r1() == 6, "order 2 takes only the free 4")
m1 = material(o1)
po.issue_materials(company_id, uid, o1, [po.IssueLine(m1.material_id, D(6))])
with new_session() as s:
    open_res = s.scalar(select(func.count()).select_from(StockReservation).where(StockReservation.status_code == "ACTIVE"))
check(on_hand(r1, wh_rm) == 0 and reserved_r1() == 0 and open_res == 0, "order 1 consumes its own reservation in full")

fx.finish()
