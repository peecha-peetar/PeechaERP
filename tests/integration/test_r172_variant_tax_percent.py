import os, sys, decimal, datetime
os.environ["PEECHA_DB_NAME"] = "peecha_test_r172_1"
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
app = QApplication.instance() or QApplication([])
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

from peecha.services import inventory_catalog as catalog_service
from peecha.services import item_variants as variants_service

uom_id = catalog_service.create_uom(company_id, "PCS", "عدد", "COUNT")

# ۱: کالایِ مادر با درصدِ مالیاتِ ۹٪ ساخته می‌شود.
parent_id = catalog_service.create_item(
    company_id, "4001", "پیراهن",
    catalog_service.ItemFields(item_kind_code="GOOD", base_uom_id=uom_id, is_sellable=True, default_tax_percent=decimal.Decimal(9)),
)

size_attr_id = variants_service.create_item_attribute(company_id, "SIZE", "سایز")
small_id = variants_service.add_item_attribute_value(size_attr_id, "S", "کوچک")
large_id = variants_service.add_item_attribute_value(size_attr_id, "L", "بزرگ")

# ۲: تولیدِ متغیرها -- طبقِ رفعِ باگ باید هر دو متغیر خودشان
#    default_tax_percent=9 را از همان لحظهٔ ساخت بگیرند.
created_ids = variants_service.generate_item_variants(company_id, parent_id, {size_attr_id: [small_id, large_id]})
check(len(created_ids) == 2, f"دو متغیر ساخته شد (got {len(created_ids)})")

for variant_id in created_ids:
    tax = catalog_service.resolve_default_tax_percent(company_id, variant_id)
    check(tax == decimal.Decimal(9), f"مالیاتِ متغیرِ تازه‌ساخته‌شده = مالیاتِ کالایِ مادر (got {tax})")

# ۳: تغییرِ بعدیِ درصدِ مالیات رویِ خودِ کالایِ مادر -- باید به متغیرهایِ
#    ازپیش‌موجود هم سرایت کند (طبقِ سازوکارِ همگام‌سازیِ update_item).
parent = catalog_service.get_item(parent_id)
new_fields = catalog_service.ItemFields(
    item_kind_code=parent.item_kind_code, base_uom_id=parent.base_uom_id,
    brand_id=parent.brand_id, manufacturer_id=parent.manufacturer_id,
    costing_method_code=parent.costing_method_code,
    is_sellable=parent.is_sellable, is_purchasable=parent.is_purchasable,
    is_stock_tracked=parent.is_stock_tracked, track_serial=parent.track_serial,
    track_batch=parent.track_batch, track_expiry=parent.track_expiry,
    default_tax_percent=decimal.Decimal(5),
)
catalog_service.update_item(parent_id, company_id, "4001", "پیراهن", True, "ACTIVE", new_fields)

for variant_id in created_ids:
    tax = catalog_service.resolve_default_tax_percent(company_id, variant_id)
    check(tax == decimal.Decimal(5), f"ویرایشِ مالیاتِ کالایِ مادر به متغیرهایِ ازپیش‌موجود سرایت کرد (got {tax})")

print("RESULT:", "ALL PASS" if not FAIL else "SOME FAILED")
sys.exit(1 if FAIL else 0)
