import os, sys, decimal, datetime
os.environ["PEECHA_DB_NAME"] = "peecha_test_r173_1"
os.environ["PEECHA_DB_USER"] = "peecha"
os.environ["PEECHA_DB_PASSWORD"] = "peecha"
os.environ["PEECHA_DB_HOST"] = "localhost"
os.environ["PEECHA_DB_PORT"] = "5432"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))

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
    company_id, "5001", "کالایِ آزمایشی",
    catalog_service.ItemFields(item_kind_code="GOOD", base_uom_id=uom_id, is_sellable=True),
)
warehouse_id = locations_service.create_warehouse(
    company_id, "WH-1", "انبارِ آزمایشی", locations_service.WarehouseFields(allow_negative_stock=True),
)
customer_id = dimensions_service.create_customer(company_id, "C-1", "مشتریِ آزمایشی")

# سفارشِ فروش بدونِ انتخابِ کانال -- دقیقاً رفتارِ پیش‌فرضِ فرم (channel_combo
# پیش‌فرض روی «(بدونِ کانال)» است).
order_id = documents_service.create_document(
    company_id, user.user_id, "SALES_ORDER", datetime.date.today(),
    documents_service.DocumentHeaderFields(
        counterparty_detail_account_id=customer_id, currency_id=company.base_currency_id, warehouse_id=warehouse_id,
    ),
)
documents_service.add_line(
    order_id, company_id, item_id=item_id, uom_id=uom_id, quantity=decimal.Decimal(5),
    quantity_base=decimal.Decimal(5), unit_price=decimal.Decimal(1000),
)
documents_service.confirm_document(order_id, company_id, user.user_id)
from peecha.db.models.commercial import CreditHold
with new_session() as s:
    hold = s.scalar(select(CreditHold).where(CreditHold.related_document_id == order_id, CreditHold.released_at.is_(None)))
    if hold is not None:
        from peecha.services import commercial_credit as credit_service
        credit_service.release_credit_hold(hold.hold_id, user.user_id)
documents_service.approve_document(order_id, company_id)

print("وضعیتِ سفارش بعدِ تایید:", documents_service.get_document(order_id, company_id)[0].status_code)
print("channel_code رویِ سفارش:", documents_service.get_document(order_id, company_id)[0].channel_code)

rows_no_channel_filter = documents_service.list_documents(company_id, document_type_code="SALES_ORDER")
print("بدونِ فیلترِ کانال، تعدادِ سفارش‌هایِ یافت‌شده:", len(rows_no_channel_filter))

rows_pre_sales = documents_service.list_documents(company_id, document_type_code="SALES_ORDER", channel_type_code="PRE_SALES")
print("با فیلترِ channel_type_code=PRE_SALES، تعدادِ سفارش‌هایِ یافت‌شده:", len(rows_pre_sales))

# حالا یک کانالِ پخشِ سرد تعریف و رویِ همان سفارش تنظیم می‌کنیم.
channel_id = pricing_service.create_channel(company_id, "COLD-1", "پخشِ سردِ منطقه‌یِ ۱", "PRE_SALES")
documents_service.update_document_header(
    order_id, company_id, datetime.date.today(),
    documents_service.DocumentHeaderFields(
        counterparty_detail_account_id=customer_id, currency_id=company.base_currency_id,
        warehouse_id=warehouse_id, channel_code="COLD-1",
    ),
)
rows_pre_sales_after = documents_service.list_documents(company_id, document_type_code="SALES_ORDER", channel_type_code="PRE_SALES")
print("بعدِ تنظیمِ کانال، تعدادِ سفارش‌هایِ یافت‌شده در فیلترِ PRE_SALES:", len(rows_pre_sales_after))
