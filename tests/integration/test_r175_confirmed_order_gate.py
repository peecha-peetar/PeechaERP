import os, sys, decimal, datetime
os.environ["PEECHA_DB_NAME"] = "peecha_test_r175_1"
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
from peecha.services import inventory_locations as locations_service
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import commercial_documents as documents_service
from peecha.services import commercial_pricing as pricing_service

uom_id = catalog_service.create_uom(company_id, "PCS", "عدد", "COUNT")
item_id = catalog_service.create_item(
    company_id, "7001", "کالایِ عادی",
    catalog_service.ItemFields(item_kind_code="GOOD", base_uom_id=uom_id, is_sellable=True),
)
warehouse_id = locations_service.create_warehouse(
    company_id, "WH-1", "انبارِ آزمایشی", locations_service.WarehouseFields(allow_negative_stock=True),
)
customer_id = dimensions_service.create_customer(company_id, "C-1", "مشتریِ آزمایشی")
channel_code = pricing_service.create_channel(company_id, "COLD-1", "پخشِ سردِ منطقه‌یِ ۱", "PRE_SALES")

order_id = documents_service.create_document(
    company_id, user.user_id, "SALES_ORDER", datetime.date.today(),
    documents_service.DocumentHeaderFields(
        counterparty_detail_account_id=customer_id, currency_id=company.base_currency_id,
        warehouse_id=warehouse_id, channel_code=channel_code,
    ),
)
documents_service.add_line(
    order_id, company_id, item_id=item_id, uom_id=uom_id, quantity=decimal.Decimal(2),
    quantity_base=decimal.Decimal(2), unit_price=decimal.Decimal(1000),
)
documents_service.confirm_document(order_id, company_id, user.user_id)

# طبقِ گزارشِ صریحِ کاربر: سفارش فقط تاییدِ کاربر (CONFIRMED) شده،
# دکمهٔ جداگانهٔ «تصویبِ مدیر» (APPROVED) هنوز زده نشده -- باید همین حالا
# در صفِ تاییدِ انبار ظاهر شود.
doc = documents_service.get_document(order_id, company_id)[0]
check(doc.status_code == "CONFIRMED", f"سفارش در وضعیتِ CONFIRMED است (got {doc.status_code})")

pending = documents_service.list_pre_sales_pending_warehouse_approval(company_id)
check(order_id in [d.document_id for d in pending], "سفارشِ فقط-تاییدشده (بدونِ تصویبِ مدیر) هم در صفِ تاییدِ انبار ظاهر شد")

documents_service.approve_warehouse(order_id, company_id, user.user_id)
doc = documents_service.get_document(order_id, company_id)[0]
check(doc.warehouse_approved_at is not None, "تاییدِ انبار رویِ سفارشِ CONFIRMED با موفقیت ثبت شد")

invoice_id = documents_service.convert_to_invoice(order_id, company_id, user.user_id, datetime.date.today())
check(invoice_id is not None, "تبدیل به فاکتور برایِ سفارشِ CONFIRMED (بدونِ نیازِ APPROVED) موفق شد")

print("RESULT:", "ALL PASS" if not FAIL else "SOME FAILED")
sys.exit(1 if FAIL else 0)
