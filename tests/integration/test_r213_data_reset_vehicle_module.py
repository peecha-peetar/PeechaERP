import os, sys, datetime, decimal
os.environ["PEECHA_DB_NAME"] = "peecha_test_r213_1"
os.environ["PEECHA_DB_USER"] = "peecha"
os.environ["PEECHA_DB_PASSWORD"] = "peecha"
os.environ["PEECHA_DB_HOST"] = "localhost"
os.environ["PEECHA_DB_PORT"] = "5432"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))

FAIL = False
def check(cond, msg):
    global FAIL
    if not cond:
        FAIL = True
        print("FAIL:", msg)
    else:
        print("OK:", msg)

from PySide6.QtWidgets import QApplication, QMessageBox
app_qt = QApplication.instance() or QApplication([])
QMessageBox.warning = staticmethod(lambda *a, **k: None)
QMessageBox.information = staticmethod(lambda *a, **k: None)
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)

from peecha.db.schema_bootstrap import apply_pending_schema_files
from peecha.db.base import get_engine, new_session
apply_pending_schema_files(get_engine())
from peecha.services.bootstrap import bootstrap_system
from peecha import session as sess
user = bootstrap_system("admin", "مدیر سیستم", "secret123", "شرکت آزمایشی")
sess.current_user = user
from sqlalchemy import select
from peecha.db.models.security import UserCompany
from peecha.db.models.core import Company
with new_session() as s:
    uc = s.scalar(select(UserCompany).where(UserCompany.user_id == user.user_id))
    company = s.get(Company, uc.company_id)
company_id = company.company_id
sess.current_company = company

from peecha.services import fiscal_years as fiscal_years_service
fiscal_years_service.create_fiscal_year_for_date(company_id, 1, 1, datetime.date.today())

from peecha.services import chart_of_accounts as coa_service
from peecha.services import inventory_catalog as catalog_service
from peecha.services import inventory_locations as locations_service
from peecha.services import users as users_service
from peecha.services import vehicle_team as vehicle_team_service
from peecha.services import vehicle_loading as vehicle_loading_service
from peecha.services import vehicle_settlement as settlement_service
from peecha.services import data_reset

lang_id = company.default_language_id
g1 = coa_service.create_account(company_id, "1", "دارایی‌ها", "DEBIT", "ASSET", "PERMANENT", False, lang_id)
k1 = coa_service.create_account(company_id, "11", "موجودیِ انبار", "DEBIT", "ASSET", "PERMANENT", False, lang_id, parent_account_id=g1.account_id)
inv_asset_gl = coa_service.create_account(company_id, "101", "موجودیِ کالا", "DEBIT", "ASSET", "PERMANENT", True, lang_id, parent_account_id=k1.account_id)
from peecha.services import inventory_engine as engine_service
engine_service.set_account_mapping(company_id, "INVENTORY_ASSET", inv_asset_gl.account_id)

central_warehouse_id = locations_service.create_warehouse(
    company_id, "WH-MAIN", "انبارِ مرکزی", locations_service.WarehouseFields(allow_negative_stock=True, is_default=True),
)
vehicle_warehouse_id = locations_service.create_warehouse(
    company_id, "VEH-1", "خودرویِ ۱", locations_service.WarehouseFields(warehouse_type_code="VEHICLE", allow_negative_stock=True),
)
uom_id = catalog_service.create_uom(company_id, "PCS", "عدد", "COUNT")
item_id = catalog_service.create_item(
    company_id, "9101", "کالایِ عادی", catalog_service.ItemFields(item_kind_code="GOOD", base_uom_id=uom_id, is_sellable=True),
)

driver = users_service.create_user("driver_r213", "راننده", "secret123", None, lang_id, False, [company_id], company_id)
vehicle_team_service.set_team_member(vehicle_warehouse_id, company_id, "DRIVER", driver.user_id)
vehicle_team_service.set_team_member(vehicle_warehouse_id, company_id, "VISITOR", driver.user_id)
vehicle_team_service.set_team_member(vehicle_warehouse_id, company_id, "DISTRIBUTOR", driver.user_id)
settlement_service.set_settlement_role(company_id, "DISTRIBUTOR")

today = datetime.date.today()
# طبقِ گزارشِ واقعیِ کاربر («خام‌کردنِ اطلاعات: نقضِ vehicle_loadings_
# stock_document_id_fkey») -- بارگیریِ تاییدشده خودش یک inv.stock_document
# می‌سازد (RECEIPT از انبارِ مرکزی به انبارِ خودرو).
loading_id = vehicle_loading_service.create_vehicle_loading(
    company_id, user.user_id, vehicle_warehouse_id, central_warehouse_id, today,
    [vehicle_loading_service.VehicleLoadingLineFields(item_id=item_id, uom_id=uom_id, planned_quantity=decimal.Decimal(10))],
)
vehicle_loading_service.confirm_vehicle_loading(loading_id, company_id, driver.user_id)
check(
    engine_service.list_balances(company_id, warehouse_id=vehicle_warehouse_id)[0].quantity_available == decimal.Decimal(10),
    "۱۰ عدد در انبارِ خودرو بعدِ بارگیری",
)

# --- خامِ اطلاعات: قبلِ رفعِ باگ همین‌جا با نقضِ FKِ vehicle_loadings متوقف می‌شد ---
try:
    data_reset.wipe_documents(company_id)
    check(True, "خام‌کردنِ اسناد بدونِ خطایِ FKِ بارگیریِ خودرو انجام شد")
except ValueError as exc:
    check(False, f"خام‌کردنِ اسناد رد شد (باگِ گزارش‌شده هنوز هست): {exc}")

from peecha.db.models.inventory import VehicleLoading, VehicleLoadingLine
with new_session() as s:
    remaining_loadings = s.scalar(select(VehicleLoading).where(VehicleLoading.company_id == company_id))
    remaining_loading_lines = s.scalars(
        select(VehicleLoadingLine).where(VehicleLoadingLine.vehicle_loading_id == loading_id)
    ).all()
check(remaining_loadings is None, "ردیفِ بارگیریِ خودرو واقعاً پاک شد")
check(len(remaining_loading_lines) == 0, "ردیف‌هایِ بارگیریِ خودرو واقعاً پاک شدند")

# --- اطلاعاتِ پایه: تیمِ خودرو نباید مانعِ حذفِ انبارِ خودرو شود ---
try:
    data_reset.wipe_master_data(company_id)
    check(True, "خام‌کردنِ اطلاعاتِ پایه بدونِ خطایِ FKِ تیمِ خودرو انجام شد")
except ValueError as exc:
    check(False, f"خام‌کردنِ اطلاعاتِ پایه رد شد (باگِ گزارش‌شده هنوز هست): {exc}")

from peecha.db.models.inventory import VehicleTeamAssignment, Warehouse
with new_session() as s:
    remaining_team = s.scalars(select(VehicleTeamAssignment).where(VehicleTeamAssignment.company_id == company_id)).all()
    remaining_warehouses = s.scalars(select(Warehouse).where(Warehouse.company_id == company_id)).all()
check(len(remaining_team) == 0, "ردیف‌هایِ تیمِ خودرو واقعاً پاک شدند")
check(len(remaining_warehouses) == 0, "انبارها (شاملِ انبارِ خودرو) واقعاً پاک شدند")

print("RESULT:", "ALL PASS" if not FAIL else "SOME FAILED")
sys.exit(1 if FAIL else 0)
