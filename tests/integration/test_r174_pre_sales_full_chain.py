import os, sys, decimal, datetime
os.environ["PEECHA_DB_NAME"] = "peecha_test_r174_1"
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
from peecha.services import inventory_catalog as catalog_service
from peecha.services import inventory_locations as locations_service
from peecha.services import inventory_engine as engine_service
from peecha.services import commercial_settings as csettings_service
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import commercial_documents as documents_service
from peecha.services import commercial_pricing as pricing_service
from peecha.services import commercial_credit as credit_service
from peecha.services import distribution_runs as distribution_service
from peecha.db.models.commercial import CreditHold

lang_id = company.default_language_id
g1 = coa_service.create_account(company_id, "1", "دارایی‌ها", "DEBIT", "ASSET", "PERMANENT", False, lang_id)
k1 = coa_service.create_account(company_id, "11", "موجودیِ انبار", "DEBIT", "ASSET", "PERMANENT", False, lang_id, parent_account_id=g1.account_id)
inv_asset_gl = coa_service.create_account(company_id, "101", "موجودیِ کالا", "DEBIT", "ASSET", "PERMANENT", True, lang_id, parent_account_id=k1.account_id)
k2 = coa_service.create_account(company_id, "13", "حساب‌هایِ دریافتنی", "DEBIT", "ASSET", "PERMANENT", False, lang_id, parent_account_id=g1.account_id)
ar_gl = coa_service.create_account(company_id, "1304", "حساب‌هایِ دریافتنیِ مشتریان", "DEBIT", "ASSET", "PERMANENT", True, lang_id, parent_account_id=k2.account_id)
k7 = coa_service.create_account(company_id, "12", "موجودیِ نقد و بانک", "DEBIT", "ASSET", "PERMANENT", False, lang_id, parent_account_id=g1.account_id)
cash_gl = coa_service.create_account(company_id, "1201", "صندوق", "DEBIT", "ASSET", "PERMANENT", True, lang_id, parent_account_id=k7.account_id)
g2 = coa_service.create_account(company_id, "4", "درآمدها", "CREDIT", "REVENUE", "TEMPORARY", False, lang_id)
k4 = coa_service.create_account(company_id, "41", "درآمدِ عملیاتی", "CREDIT", "REVENUE", "TEMPORARY", False, lang_id, parent_account_id=g2.account_id)
revenue_gl = coa_service.create_account(company_id, "411", "درآمدِ فروش", "CREDIT", "REVENUE", "TEMPORARY", True, lang_id, parent_account_id=k4.account_id)
g3 = coa_service.create_account(company_id, "5", "هزینه‌ها", "DEBIT", "EXPENSE", "TEMPORARY", False, lang_id)
k5 = coa_service.create_account(company_id, "51", "بهایِ تمام‌شده", "DEBIT", "EXPENSE", "TEMPORARY", False, lang_id, parent_account_id=g3.account_id)
cogs_gl = coa_service.create_account(company_id, "511", "بهایِ تمام‌شده", "DEBIT", "EXPENSE", "TEMPORARY", True, lang_id, parent_account_id=k5.account_id)

engine_service.set_account_mapping(company_id, "INVENTORY_ASSET", inv_asset_gl.account_id)
engine_service.set_account_mapping(company_id, "CUSTOMER_RECEIVABLE", ar_gl.account_id)
engine_service.set_account_mapping(company_id, "COGS", cogs_gl.account_id)
csettings_service.set_account_mapping(company_id, "SALES_REVENUE", revenue_gl.account_id)

uom_id = catalog_service.create_uom(company_id, "PCS", "عدد", "COUNT")
normal_item_id = catalog_service.create_item(
    company_id, "6001", "کالایِ عادی",
    catalog_service.ItemFields(item_kind_code="GOOD", base_uom_id=uom_id, is_sellable=True),
)
weighed_item_id = catalog_service.create_item(
    company_id, "6002", "کالایِ ترازویی",
    catalog_service.ItemFields(item_kind_code="GOOD", base_uom_id=uom_id, is_sellable=True, pos_requires_weight=True),
)
warehouse_id = locations_service.create_warehouse(
    company_id, "WH-1", "انبارِ آزمایشی", locations_service.WarehouseFields(allow_negative_stock=True),
)
vehicle_id = locations_service.create_warehouse(
    company_id, "VEH-1", "وانتِ ۱", locations_service.WarehouseFields(
        warehouse_type_code="VEHICLE", vehicle_plate_number="12ط345-67",
    ),
)
customer_id = dimensions_service.create_customer(company_id, "C-1", "مشتریِ آزمایشی")
channel_code = pricing_service.create_channel(company_id, "COLD-1", "پخشِ سردِ منطقه‌یِ ۱", "PRE_SALES")


def _release_holds(order_id):
    with new_session() as s:
        hold = s.scalar(select(CreditHold).where(CreditHold.related_document_id == order_id, CreditHold.released_at.is_(None)))
        if hold is not None:
            credit_service.release_credit_hold(hold.hold_id, user.user_id)


order_id = documents_service.create_document(
    company_id, user.user_id, "SALES_ORDER", datetime.date.today(),
    documents_service.DocumentHeaderFields(
        counterparty_detail_account_id=customer_id, currency_id=company.base_currency_id,
        warehouse_id=warehouse_id, channel_code=channel_code,
    ),
)
documents_service.add_line(
    order_id, company_id, item_id=normal_item_id, uom_id=uom_id, quantity=decimal.Decimal(5),
    quantity_base=decimal.Decimal(5), unit_price=decimal.Decimal(1000),
)
documents_service.add_line(
    order_id, company_id, item_id=weighed_item_id, uom_id=uom_id, quantity=decimal.Decimal(3),
    quantity_base=decimal.Decimal(3), unit_price=decimal.Decimal(2000),
)
documents_service.confirm_document(order_id, company_id, user.user_id)
_release_holds(order_id)
documents_service.approve_document(order_id, company_id)

check(documents_service.document_requires_weighing(order_id, company_id), "سفارش به‌درستی نیازمندِ توزین تشخیص داده شد (کالایِ ترازویی دارد)")

pending_warehouse = documents_service.list_pre_sales_pending_warehouse_approval(company_id)
check(order_id in [d.document_id for d in pending_warehouse], "سفارش در صفِ انتظارِ تاییدِ انبار ظاهر شد")

try:
    documents_service.convert_to_invoice(order_id, company_id, user.user_id, datetime.date.today())
    check(False, "تبدیل به فاکتور بدونِ تاییدِ انبار باید رد می‌شد")
except ValueError as exc:
    check("انبار" in str(exc), f"تبدیل به فاکتور بدونِ تاییدِ انبار درست رد شد ({exc})")

documents_service.approve_warehouse(order_id, company_id, user.user_id)

pending_weighing = documents_service.list_pre_sales_pending_weighing_approval(company_id)
check(order_id in [d.document_id for d in pending_weighing], "سفارش بعدِ تاییدِ انبار در صفِ انتظارِ توزین ظاهر شد")

try:
    documents_service.convert_to_invoice(order_id, company_id, user.user_id, datetime.date.today())
    check(False, "تبدیل به فاکتور بدونِ توزین باید رد می‌شد")
except ValueError as exc:
    check("توزین" in str(exc), f"تبدیل به فاکتور بدونِ توزین درست رد شد ({exc})")

documents_service.approve_weighing(order_id, company_id, user.user_id)

invoice_id = documents_service.convert_to_invoice(order_id, company_id, user.user_id, datetime.date.today())
check(invoice_id is not None, "تبدیل به فاکتور بعدِ هردو تایید موفق شد")

documents_service.confirm_document(invoice_id, company_id, user.user_id)
from peecha.services import commercial_settlements as settlements_service
settlements_service.auto_approve_full_cash_settlement_plan(invoice_id, company_id, user.user_id)
documents_service.post_document(invoice_id, company_id, user.user_id)
check(documents_service.get_document(invoice_id, company_id)[0].status_code == "POSTED", "فاکتور ثبتِ‌نهایی شد")

eligible = distribution_service.list_eligible_invoices(company_id)
check(invoice_id in [i.document_id for i in eligible], "فاکتور در فهرستِ واجدِ شرایطِ تیمِ پخش ظاهر شد")

run_id = distribution_service.create_distribution_run(company_id, user.user_id, datetime.date.today(), vehicle_id)
distribution_service.add_document_to_run(run_id, company_id, invoice_id)

eligible_after = distribution_service.list_eligible_invoices(company_id)
check(invoice_id not in [i.document_id for i in eligible_after], "بعدِ الصاق، فاکتور دیگر در فهرستِ واجدِ شرایط نیست")

run = distribution_service.get_distribution_run(run_id, company_id)
check(len(run.invoices) == 1, f"تیمِ پخش دقیقاً یک فاکتور دارد (got {len(run.invoices)})")
summary_by_item = {s.item_id: s.total_quantity for s in run.item_summary}
check(summary_by_item.get(normal_item_id) == decimal.Decimal(5), f"جمعِ کالایِ عادی درست است (got {summary_by_item.get(normal_item_id)})")
check(summary_by_item.get(weighed_item_id) == decimal.Decimal(3), f"جمعِ کالایِ ترازویی درست است (got {summary_by_item.get(weighed_item_id)})")

distribution_service.confirm_distribution_run(run_id, company_id, user.user_id)
run_after = distribution_service.get_distribution_run(run_id, company_id)
check(run_after.status_code == "CONFIRMED", "تیمِ پخش با موفقیت تحویل‌شده علامت خورد")

print("RESULT:", "ALL PASS" if not FAIL else "SOME FAILED")
sys.exit(1 if FAIL else 0)
