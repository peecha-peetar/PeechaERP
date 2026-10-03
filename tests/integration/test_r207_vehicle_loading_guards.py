import os, sys, datetime, decimal
os.environ["PEECHA_DB_NAME"] = "peecha_test_r207_1"
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
from peecha.services import inventory_engine as engine_service
from peecha.services import inventory_documents as inv_documents_service
from peecha.services import vehicle_loading as vehicle_loading_service

lang_id = company.default_language_id
g1 = coa_service.create_account(company_id, "1", "دارایی‌ها", "DEBIT", "ASSET", "PERMANENT", False, lang_id)
k3 = coa_service.create_account(company_id, "11b", "موجودیِ انبار", "DEBIT", "ASSET", "PERMANENT", False, lang_id, parent_account_id=g1.account_id)
inv_asset_gl = coa_service.create_account(company_id, "102", "موجودیِ کالا", "DEBIT", "ASSET", "PERMANENT", True, lang_id, parent_account_id=k3.account_id)
g3 = coa_service.create_account(company_id, "5", "هزینه‌ها", "DEBIT", "EXPENSE", "TEMPORARY", False, lang_id)
k6 = coa_service.create_account(company_id, "59", "سایرِ هزینه‌ها", "DEBIT", "EXPENSE", "TEMPORARY", False, lang_id, parent_account_id=g3.account_id)
adj_gl = coa_service.create_account(company_id, "599", "مازادِ اصلاحِ موجودی", "DEBIT", "EXPENSE", "TEMPORARY", True, lang_id, parent_account_id=k6.account_id)
engine_service.set_account_mapping(company_id, "INVENTORY_ASSET", inv_asset_gl.account_id)
engine_service.set_account_mapping(company_id, "INVENTORY_ADJUSTMENT_LOSS", adj_gl.account_id)
engine_service.set_account_mapping(company_id, "INVENTORY_ADJUSTMENT_GAIN", adj_gl.account_id)

uom_id = catalog_service.create_uom(company_id, "PCS", "عدد", "COUNT")

# انبارِ مرکزی -- اجازهٔ موجودیِ منفی ندارد (پیش‌فرض)
central_wh = locations_service.create_warehouse(
    company_id, "WH-CENTRAL", "انبارِ مرکزی", locations_service.WarehouseFields(allow_negative_stock=False),
)
vehicle_wh = locations_service.create_warehouse(
    company_id, "WH-VAN1", "خودرویِ ۱", locations_service.WarehouseFields(warehouse_type_code="VEHICLE"),
)

item_id = catalog_service.create_item(
    company_id, "9201", "کالایِ معمولی",
    catalog_service.ItemFields(item_kind_code="GOOD", base_uom_id=uom_id, is_sellable=True),
)

# ۱۰ عدد موجودیِ اولیه در انبارِ مرکزی
doc_id = inv_documents_service.create_stock_document(
    company_id, user.user_id, "RECEIPT", datetime.date.today(),
    inv_documents_service.DocumentHeaderFields(destination_warehouse_id=central_wh),
)
inv_documents_service.add_line(
    doc_id, company_id,
    inv_documents_service.LineFields(item_id=item_id, uom_id=uom_id, quantity=decimal.Decimal(10), quantity_base=decimal.Decimal(10), unit_cost=decimal.Decimal(1000)),
)
inv_documents_service.confirm_stock_document(doc_id, company_id)
inv_documents_service.post_stock_document(doc_id, company_id, user.user_id)

# --- ۱. درخواستِ بیش از موجودی باید همان لحظهٔ برنامه‌ریزی رد شود ---
try:
    vehicle_loading_service.create_vehicle_loading(
        company_id, user.user_id, vehicle_wh, central_wh, datetime.date.today(),
        [vehicle_loading_service.VehicleLoadingLineFields(item_id, uom_id, decimal.Decimal(15))],
    )
    check(False, "درخواستِ بیش از موجودی (۱۵ از ۱۰) باید رد شود")
except ValueError as exc:
    check("موجودیِ انبارِ مبدا" in str(exc), f"درخواستِ بیش از موجودی رد شد: {exc}")

# --- ۲. درخواستِ درست باید کار کند و واقعاً منتقل شود ---
loading_id = vehicle_loading_service.create_vehicle_loading(
    company_id, user.user_id, vehicle_wh, central_wh, datetime.date.today(),
    [vehicle_loading_service.VehicleLoadingLineFields(item_id, uom_id, decimal.Decimal(4))],
)
vehicle_loading_service.confirm_vehicle_loading(loading_id, company_id, user.user_id)
balances = {b.item_id: b.quantity_available for b in engine_service.list_balances(company_id, warehouse_id=vehicle_wh)}
check(balances.get(item_id) == decimal.Decimal(4), f"۴ عدد واقعاً به خودرو منتقل شد (got {balances.get(item_id)})")
central_balances = {b.item_id: b.quantity_available for b in engine_service.list_balances(company_id, warehouse_id=central_wh)}
check(central_balances.get(item_id) == decimal.Decimal(6), f"۶ عدد در انبارِ مرکزی باقی ماند (got {central_balances.get(item_id)})")

# --- ۳. کالای اصلیِ دارایِ متغیر هرگز قابلِ‌انتخاب نباشد ---
parent_item_id = catalog_service.create_item(
    company_id, "9202", "کالایِ اصلیِ رنگی",
    catalog_service.ItemFields(item_kind_code="GOOD", base_uom_id=uom_id, is_sellable=False),
)
child_item_id = catalog_service.create_item(
    company_id, "9202-R", "کالایِ اصلیِ رنگی -- قرمز",
    catalog_service.ItemFields(item_kind_code="GOOD", base_uom_id=uom_id, is_sellable=True, variant_parent_item_id=parent_item_id),
)

items = catalog_service.list_items(company_id, transactable_only=True)
item_ids_transactable = {it.item_id for it in items}
check(parent_item_id not in item_ids_transactable, "کالای اصلیِ متغیردار در list_items(transactable_only=True) نیست")
check(child_item_id in item_ids_transactable, "متغیرِ فرزند در list_items(transactable_only=True) هست")

all_items = {it.item_id: it for it in catalog_service.list_items(company_id)}
check(all_items[parent_item_id].has_variants is True, "has_variants برایِ اصلی True است")
check(all_items[child_item_id].has_variants is False, "has_variants برایِ فرزند False است")

try:
    vehicle_loading_service.create_vehicle_loading(
        company_id, user.user_id, vehicle_wh, central_wh, datetime.date.today(),
        [vehicle_loading_service.VehicleLoadingLineFields(parent_item_id, uom_id, decimal.Decimal(1))],
    )
    check(False, "بارگیریِ کالای اصلیِ متغیردار باید در همان ساختِ برنامه رد شود")
except ValueError as exc:
    check("متغیر" in str(exc), f"بارگیریِ کالای اصلیِ متغیردار رد شد: {exc}")

# گیتِ سختِ سمتِ engine هم مستقلاً باید همین کالا را رد کند -- حتی اگر
# کسی از مسیرِ دیگری (نه vehicle_loading.py) امتحان کند.
doc2_id = inv_documents_service.create_stock_document(
    company_id, user.user_id, "TRANSFER", datetime.date.today(),
    inv_documents_service.DocumentHeaderFields(source_warehouse_id=central_wh, destination_warehouse_id=vehicle_wh),
)
# برایِ همین تست، مقداری موجودیِ اولیه برایِ فرزند هم می‌سازیم که چکِ
# موجودی مانعِ رسیدن به چکِ متغیر نشود -- ولی این‌جا مستقیماً خودِ
# کالای اصلی (parent_item_id) را می‌فرستیم که موجودی هم ندارد؛ اگر
# چکِ متغیر درست کار نکند، خطا به‌جایش چکِ «موجودیِ کافی نیست» خواهد
# بود -- که باز هم رد می‌شود ولی برایِ دلیلِ دیگر. برایِ رد شدن دقیقاً
# به‌خاطرِ «متغیر»، ابتدا کمی موجودی برایِ parent می‌سازیم که چکِ
# منفی رد نکند.
recv2_id = inv_documents_service.create_stock_document(
    company_id, user.user_id, "RECEIPT", datetime.date.today(),
    inv_documents_service.DocumentHeaderFields(destination_warehouse_id=central_wh),
)
inv_documents_service.add_line(
    recv2_id, company_id,
    inv_documents_service.LineFields(item_id=parent_item_id, uom_id=uom_id, quantity=decimal.Decimal(5), quantity_base=decimal.Decimal(5), unit_cost=decimal.Decimal(1000)),
)
inv_documents_service.confirm_stock_document(recv2_id, company_id)
try:
    inv_documents_service.post_stock_document(recv2_id, company_id, user.user_id)
    check(False, "خودِ RECEIPTِ کالای اصلیِ متغیردار هم باید در engine رد شود")
except ValueError as exc:
    check("متغیر" in str(exc), f"گیتِ سختِ engine هم کالای اصلیِ متغیردار را رد کرد: {exc}")

print("RESULT:", "ALL PASS" if not FAIL else "SOME FAILED")
sys.exit(1 if FAIL else 0)
