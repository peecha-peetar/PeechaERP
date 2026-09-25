import os, sys, datetime, decimal
os.environ["PEECHA_DB_NAME"] = "peecha_test_r161_1"
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

from peecha.db.base import get_engine, new_session
from peecha import session as sess
from sqlalchemy import select
from peecha.db.models.security import UserCompany
from peecha.db.models.core import Company
# از دیتابیسِ test_r161_tax_policy.py (همان PEECHA_DB_NAME) استفاده می‌کند --
# bootstrap_system دوباره صدا زده نمی‌شود چون کدِ شرکتِ پیش‌فرض (C1) تکراری می‌شد.
from peecha.db.models.security import User
with new_session() as s:
    user = s.scalar(select(User).where(User.username == "admin"))
    s.expunge(user)
    uc = s.scalar(select(UserCompany).where(UserCompany.user_id == user.user_id))
    company = s.get(Company, uc.company_id)
sess.current_user = user
company_id = company.company_id
sess.current_company = company

from peecha.services import inventory_locations as locations_service

# ذخیره‌یِ مستقیمِ سرویس با مقداری واقعی.
wh_id = locations_service.create_warehouse(
    company_id, "WH-TAX", "انبارِ تستِ مالیات",
    locations_service.WarehouseFields(default_tax_percent=decimal.Decimal("7.5")),
)
row = locations_service.get_warehouse(wh_id, company_id)
check(row.fields.default_tax_percent == decimal.Decimal("7.5"), f"مالیاتِ انبار در سرویس ذخیره/بازخوانی شد (got {row.fields.default_tax_percent})")

# حالا از طریقِ خودِ فرم -- بارگذاری و ذخیره دوباره، مقدار باید حفظ شود.
from peecha.ui.screens.inventory_warehouses import InventoryWarehousesScreen
screen = InventoryWarehousesScreen()
screen.refresh()
idx = next(i for i in range(screen.table.rowCount()) if screen._rows[i].warehouse_id == wh_id)
screen._on_row_clicked(idx, 0)
check(screen.default_tax_percent_field.text() == "7.50", f"فیلدِ درصدِ مالیات در فرم با مقدارِ ذخیره‌شده پر شده (got {screen.default_tax_percent_field.text()!r})")

screen.default_tax_percent_field.setText("")
screen._save()
row = locations_service.get_warehouse(wh_id, company_id)
check(row.fields.default_tax_percent is None, f"خالی‌کردنِ فیلد و ذخیره، مالیاتِ انبار را None می‌کند (got {row.fields.default_tax_percent})")

print("FAIL" if FAIL else "RESULT: ALL PASS")
sys.exit(1 if FAIL else 0)
