"""R357: ناوگان پخش ↔ نگهداری: خودرو به تجهیز وصل می‌شود (یک تجهیز فقط یک خودرو)، کیلومتر سوخت‌گیری کارکرد تجهیز
را پر می‌کند و نگهداری کیلومتری سررسید می‌شود، کیلومتر خارج از ترتیب پذیرفته نمی‌شود، حذف فقط آخرین کیلومتر و برگشت
کارکردش؛ هزینهٔ هر خودرو (سوخت + دستور کار نگهداری) در برابر فروش خالص همان خودرو؛ فرم انبار و فرم سوخت و هزینه."""
import os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r357"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mnt_fixture import *  # noqa: F401,F403

from peecha.services import commercial_partners as partners, commercial_pricing as pricing, commercial_settings as csettings, \
    fleet

van_asset = fa.create_asset(company_id, uid, fa.AssetFields(asset_code="VAN-1", name="وانت پخش ۱", category_id=mach,
                                                            asset_type_code="VEHICLE", is_production_machine=False))
fa.acquire(company_id, uid, van_asset, today - days(400), [fa.CostItem("PURCHASE", D(900_000_000), ap_gl.account_id, seller)])
fa.capitalize(company_id, uid, van_asset, today - days(400), in_service_date=today - days(365))

van = locations_service.create_warehouse(company_id, "V1", "خودروی پخش ۱", WF(
    warehouse_type_code="VEHICLE", vehicle_plate_number="12B345", vehicle_asset_id=van_asset))
check(locations_service.get_warehouse(van, company_id).fields.vehicle_asset_id == van_asset, "the van is linked to its equipment")
check(raises(lambda: locations_service.create_warehouse(company_id, "V2", "خودروی دوم", WF(
    warehouse_type_code="VEHICLE", vehicle_asset_id=van_asset)), "قبلاً"), "one equipment cannot be two vans")
plain = locations_service.create_warehouse(company_id, "G2", "انبار دوم", WF(vehicle_asset_id=van_asset))
check(locations_service.get_warehouse(plain, company_id).fields.vehicle_asset_id is None, "a normal warehouse never keeps an equipment link")

plan = mpm.save_plan(company_id, uid, mpm.PlanInput(code="PM-KM", asset_id=van_asset, title="تعویض روغن هر ۱۰۰۰ کیلومتر",
                                                    trigger_code="METER", meter_interval=D(1000)))


def due():
    return next(p.due for p in mpm.list_plans(company_id, van_asset) if p.plan_id == plan)


F = fleet.FuelFields
first, note = fleet.add_fuel_log(company_id, uid, F(van, today - days(10), D(40), D(2_000_000), D(10_000)))
check(not note and due().meter_state == "NO_DATA", "the first odometer reading is only the starting point")
second, note = fleet.add_fuel_log(company_id, uid, F(van, today - days(6), D(45), D(2_250_000), D(10_600)))
check(not note and due().meter_used == D(600) and due().meter_state == "OK", f"600 km reach the equipment meter ({due().meter_used})")
check(raises(lambda: fleet.add_fuel_log(company_id, uid, F(van, today - days(5), D(10), D(0), D(10_500))), "کمتر"),
      "a lower odometer is refused")
check(raises(lambda: fleet.add_fuel_log(company_id, uid, F(van, today - days(8), D(10), D(0), D(10_300))), "ترتیب"),
      "a back-dated odometer between two readings is refused")
fleet.add_fuel_log(company_id, uid, F(van, today - days(8), D(10), D(500_000), note="بدون کیلومتر"))
third, _n = fleet.add_fuel_log(company_id, uid, F(van, today - days(2), D(50), D(2_500_000), D(11_200), fuel_type_code="DIESEL"))
check(due().meter_used == D(1200) and due().state in ("DUE", "OVERDUE"), f"after 1,200 km the oil change is due ({due().state})")
check(raises(lambda: fleet.delete_fuel_log(company_id, second), "آخرین"), "a middle reading cannot be deleted")
fleet.delete_fuel_log(company_id, third)
check(due().meter_used == D(600), "deleting the last reading takes its kilometres back off the meter")
third, _n = fleet.add_fuel_log(company_id, uid, F(van, today - days(2), D(50), D(2_500_000), D(11_200), fuel_type_code="DIESEL"))
logs = fleet.list_fuel_logs(company_id, van)
check(len(logs) == 4 and logs[0].distance_km == D(600) and logs[0].per_100km == D("8.33") and logs[0].fuel_type_label == "گازوئیل",
      f"the log shows distance and consumption ({[(l.distance_km, l.per_100km) for l in logs]})")

# نگهداری و فروش همان خودرو
wo = wos.create(company_id, uid, wos.WorkOrderInput(asset_id=van_asset, work_type_code="CORRECTIVE", title="تعویض لنت"))
mcost.add_cost(company_id, uid, wo, "SERVICE", "تعمیرگاه مجاز", D(3_000_000), contractor)
k13 = A("13", "دریافتنی‌ها", "DEBIT", "ASSET", "PERMANENT", False, g1.account_id)
ar_gl = A("131", "دریافتنی مشتریان", "DEBIT", "ASSET", "PERMANENT", True, k13.account_id)
g_rev = A("4", "درآمدها", "CREDIT", "REVENUE", "TEMPORARY", False)
k41 = A("41", "درآمد عملیاتی", "CREDIT", "REVENUE", "TEMPORARY", False, g_rev.account_id)
rev_gl = A("411", "فروش", "CREDIT", "REVENUE", "TEMPORARY", True, k41.account_id)
disc_gl = A("412", "تخفیف فروش", "DEBIT", "REVENUE", "TEMPORARY", True, k41.account_id)
engine_service.set_account_mapping(company_id, "CUSTOMER_RECEIVABLE", ar_gl.account_id)
for key, account in (("SALES_REVENUE", rev_gl), ("SALES_DISCOUNT", disc_gl)):
    csettings.set_account_mapping(company_id, key, account.account_id)
receive(byp, 50, 100_000, wh=van)
customer = partners.create_customer(company_id, "C1", "فروشگاه", fast_track=True)
channel = pricing.create_channel(company_id, "VS", "پخش گرم", "VAN_SALES")
from fastapi.testclient import TestClient
from peecha_api.main import app
client = TestClient(app)
token = client.post("/auth/login", json={"username": "admin", "password": "secret123"}).json()["access_token"]
resp = client.post("/orders", headers={"Authorization": f"Bearer {token}"}, json={
    "document_type_code": "SALES_INVOICE", "counterparty_detail_account_id": customer, "currency_id": company.base_currency_id,
    "warehouse_id": van, "channel_code": channel, "post_immediately": True,
    "lines": [{"item_id": byp, "uom_id": pcs, "quantity": "20", "unit_price": "500000"}]})
check(resp.status_code == 200, f"a van-sales invoice is posted from the van ({resp.text[:200]})")

costs = {r.vehicle_warehouse_id: r for r in fleet.vehicle_costs(company_id, today - days(30), today)}
c = costs[van]
check(c.km == D(1200) and c.liters == D(145) and c.fuel_amount == D(7_250_000) and c.work_orders == 1
      and c.maintenance_amount == D(3_000_000) and c.total_cost == D(10_250_000),
      f"van cost = fuel 7.25M + maintenance 3M over 1,200 km ({c})")
check(c.per_km == D("8541.67") and c.net_sales == D(10_000_000) and c.cost_percent == D("102.50") and "VAN-1" in c.asset_label,
      f"cost per km and share of the van's own net sales ({c.per_km} {c.net_sales} {c.cost_percent})")
check(fleet.vehicle_costs(company_id, today + days(1), today + days(5))[0].total_cost == 0, "nothing outside the date range")

# فرم‌ها
from PySide6.QtWidgets import QApplication
qapp = QApplication.instance() or QApplication([])
from peecha.ui.screens.fleet import FleetScreen
from peecha.ui.screens.inventory_warehouses import InventoryWarehousesScreen

tab = FleetScreen()
tab.refresh()
check(tab.log_table.rowCount() == 4 and tab.cost_table.rowCount() == 1 and tab.vehicle_combo.findData(van) >= 0,
      "the fuel and vehicle-cost form lists logs, costs and vans")
tab.vehicle_combo.setCurrentIndex(tab.vehicle_combo.findData(van))
tab.date_field.setDate(today)
tab.liters_field.setText("۳۰")
tab.amount_field.setText("۱٬۵۰۰٬۰۰۰")
tab.odometer_field.setText("۱۱۵۰۰")
check(tab.add_log() is not None and tab.log_table.rowCount() == 5 and due().meter_used == D(1500), "fuel is logged from the tab")
screen = InventoryWarehousesScreen()
screen.refresh()
check(screen.vehicle_asset_combo.findData(van_asset) >= 0, "the warehouse form lists vehicle equipment")

finish()
