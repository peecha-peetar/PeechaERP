import os, sys, datetime, decimal
os.environ["PEECHA_DB_NAME"] = "peecha_test_r162_1"
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

from peecha.services import chart_of_accounts as coa_service
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import inventory_catalog as catalog_service
from peecha.services import inventory_locations as locations_service
from peecha.services import inventory_engine as engine_service
from peecha.services import inventory_documents as inv_documents_service
from peecha.services import commercial_settings as csettings_service
from peecha.services import commercial_documents as documents_service
from peecha.services import commercial_pos as pos_service
from peecha.services import treasury as treasury_service
from peecha.services import data_reset

lang_id = company.default_language_id
g1 = coa_service.create_account(company_id, "1", "دارایی‌ها", "DEBIT", "ASSET", "PERMANENT", False, lang_id)
k1 = coa_service.create_account(company_id, "11", "موجودیِ انبار", "DEBIT", "ASSET", "PERMANENT", False, lang_id, parent_account_id=g1.account_id)
inv_asset_gl = coa_service.create_account(company_id, "101", "موجودیِ کالا", "DEBIT", "ASSET", "PERMANENT", True, lang_id, parent_account_id=k1.account_id)
k2 = coa_service.create_account(company_id, "13", "حساب‌هایِ دریافتنی", "DEBIT", "ASSET", "PERMANENT", False, lang_id, parent_account_id=g1.account_id)
ar_gl = coa_service.create_account(company_id, "1304", "حساب‌هایِ دریافتنیِ مشتریان", "DEBIT", "ASSET", "PERMANENT", True, lang_id, parent_account_id=k2.account_id)
k3 = coa_service.create_account(company_id, "12", "موجودیِ نقد", "DEBIT", "ASSET", "PERMANENT", False, lang_id, parent_account_id=g1.account_id)
cash_gl = coa_service.create_account(company_id, "1201", "صندوق", "DEBIT", "ASSET", "PERMANENT", True, lang_id, parent_account_id=k3.account_id)
g2 = coa_service.create_account(company_id, "4", "درآمدها", "CREDIT", "REVENUE", "TEMPORARY", False, lang_id)
k4 = coa_service.create_account(company_id, "41", "درآمدِ عملیاتی", "CREDIT", "REVENUE", "TEMPORARY", False, lang_id, parent_account_id=g2.account_id)
revenue_gl = coa_service.create_account(company_id, "411", "درآمدِ فروش", "CREDIT", "REVENUE", "TEMPORARY", True, lang_id, parent_account_id=k4.account_id)
g3 = coa_service.create_account(company_id, "5", "هزینه‌ها", "DEBIT", "EXPENSE", "TEMPORARY", False, lang_id)
k5 = coa_service.create_account(company_id, "51", "بهایِ تمام‌شده", "DEBIT", "EXPENSE", "TEMPORARY", False, lang_id, parent_account_id=g3.account_id)
cogs_gl = coa_service.create_account(company_id, "511", "بهایِ تمام‌شده", "DEBIT", "EXPENSE", "TEMPORARY", True, lang_id, parent_account_id=k5.account_id)
g4 = coa_service.create_account(company_id, "2", "بدهی‌ها", "CREDIT", "LIABILITY", "PERMANENT", False, lang_id)
k6 = coa_service.create_account(company_id, "21", "سایرِ بدهی‌ها", "CREDIT", "LIABILITY", "PERMANENT", False, lang_id, parent_account_id=g4.account_id)
ap_gl = coa_service.create_account(company_id, "211", "پرداختنیِ تامین‌کنندگان", "CREDIT", "LIABILITY", "PERMANENT", True, lang_id, parent_account_id=k6.account_id)

engine_service.set_account_mapping(company_id, "INVENTORY_ASSET", inv_asset_gl.account_id)
engine_service.set_account_mapping(company_id, "CUSTOMER_RECEIVABLE", ar_gl.account_id)
engine_service.set_account_mapping(company_id, "SUPPLIER_PAYABLE", ap_gl.account_id)
engine_service.set_account_mapping(company_id, "COGS", cogs_gl.account_id)
csettings_service.set_account_mapping(company_id, "SALES_REVENUE", revenue_gl.account_id)

customer_id = dimensions_service.create_customer(company_id, "1", "مشتریِ آزمایشی")
from peecha.db.models.accounting import DetailAccount
with new_session() as s:
    cust_account = s.get(DetailAccount, customer_id)
    customer_group_id = cust_account.person_group_id

treasury_service.create_counterparty_mapping(company_id, "RECEIPT", cash_gl.account_id, person_group_id=customer_group_id)
treasury_service.set_account_mapping(company_id, "RECEIPT_CASH", cash_gl.account_id)

supplier_id = dimensions_service.create_supplier(company_id, "9", "تامین‌کننده")
uom_id = catalog_service.create_uom(company_id, "PCS", "عدد", "COUNT")
item_id = catalog_service.create_item(
    company_id, "3001", "کالایِ آزمایشی", catalog_service.ItemFields(item_kind_code="GOOD", base_uom_id=uom_id, is_sellable=True),
)
warehouse_id = locations_service.create_warehouse(company_id, "WH-1", "انبارِ آزمایشی", locations_service.WarehouseFields())

receipt_id = inv_documents_service.create_stock_document(
    company_id, user.user_id, "RECEIPT", datetime.date.today(),
    inv_documents_service.DocumentHeaderFields(destination_warehouse_id=warehouse_id, counterparty_detail_account_id=supplier_id),
)
inv_documents_service.add_line(receipt_id, company_id, inv_documents_service.LineFields(
    item_id=item_id, uom_id=uom_id, quantity=decimal.Decimal(10), quantity_base=decimal.Decimal(10), unit_cost=decimal.Decimal(1000),
))
inv_documents_service.confirm_stock_document(receipt_id, company_id)
inv_documents_service.post_stock_document(receipt_id, company_id, user.user_id)

terminal_id = pos_service.create_terminal(company_id, warehouse_id, "T1", "صندوقِ آزمایشی")
session_id = pos_service.open_session(terminal_id, user.user_id, decimal.Decimal(0))

doc_id = documents_service.create_document(
    company_id, user.user_id, "SALES_INVOICE", datetime.date.today(),
    documents_service.DocumentHeaderFields(
        counterparty_detail_account_id=customer_id, currency_id=company.base_currency_id,
        warehouse_id=warehouse_id, pos_session_id=session_id,
    ),
)
documents_service.add_line(doc_id, company_id, item_id, uom_id, decimal.Decimal(2), decimal.Decimal(2), unit_price=decimal.Decimal(2000))
documents_service.confirm_document(doc_id, company_id, user.user_id)
documents_service.approve_document(doc_id, company_id)
documents_service.post_document(doc_id, company_id, user.user_id)
pos_service.record_payment_and_settle(company_id, user.user_id, doc_id, "CASH", decimal.Decimal(4000))

from peecha.db.models.commercial import PosPayment
with new_session() as s:
    payment_count = s.scalar(select(PosPayment).where(PosPayment.document_id == doc_id))
check(payment_count is not None, "پیش‌شرط: ردیفِ pos_payments واقعاً برایِ این فاکتور ثبت شده است")

# =========================================================================
# طبقِ گزارشِ صریحِ کاربر (اسکرین‌شاتِ خطا): خام‌کردنِ اسناد قبلاً دقیقاً
# همین‌جا با نقضِ pos_payments_document_id_fkey متوقف می‌شد.
# =========================================================================
try:
    data_reset.wipe_documents(company_id)
    check(True, "خام‌کردنِ اسناد بدونِ خطا انجام شد (قبلاً همین‌جا با نقضِ pos_payments_document_id_fkey متوقف می‌شد)")
except ValueError as exc:
    check(False, f"خام‌کردنِ اسناد هنوز شکست می‌خورد: {exc}")

with new_session() as s:
    from peecha.db.models.commercial import CommercialDocument
    remaining_docs = s.scalar(select(CommercialDocument).where(CommercialDocument.company_id == company_id))
    remaining_payments = s.scalar(select(PosPayment).where(PosPayment.document_id == doc_id))
check(remaining_docs is None, "سندِ فروش واقعاً حذف شد")
check(remaining_payments is None, "ردیفِ pos_payments هم واقعاً حذف شد")

print("FAIL" if FAIL else "RESULT: ALL PASS")
sys.exit(1 if FAIL else 0)
