import os, sys, decimal, datetime
os.environ["PEECHA_DB_NAME"] = "peecha_test_r176_1"
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
from peecha.services import commercial_settlements as settlements_service

lang_id = company.default_language_id
g1 = coa_service.create_account(company_id, "1", "دارایی‌ها", "DEBIT", "ASSET", "PERMANENT", False, lang_id)
k1 = coa_service.create_account(company_id, "11", "موجودیِ انبار", "DEBIT", "ASSET", "PERMANENT", False, lang_id, parent_account_id=g1.account_id)
inv_asset_gl = coa_service.create_account(company_id, "101", "موجودیِ کالا", "DEBIT", "ASSET", "PERMANENT", True, lang_id, parent_account_id=k1.account_id)
k2 = coa_service.create_account(company_id, "13", "حساب‌هایِ دریافتنی", "DEBIT", "ASSET", "PERMANENT", False, lang_id, parent_account_id=g1.account_id)
ar_gl = coa_service.create_account(company_id, "1304", "حساب‌هایِ دریافتنیِ مشتریان", "DEBIT", "ASSET", "PERMANENT", True, lang_id, parent_account_id=k2.account_id)
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

from peecha.db.models.commercial import CreditHold
from peecha.services import commercial_credit as credit_service


def _release_holds(order_id):
    with new_session() as s:
        hold = s.scalar(select(CreditHold).where(CreditHold.related_document_id == order_id, CreditHold.released_at.is_(None)))
        if hold is not None:
            credit_service.release_credit_hold(hold.hold_id, user.user_id)


uom_id = catalog_service.create_uom(company_id, "PCS", "عدد", "COUNT")
item_id = catalog_service.create_item(
    company_id, "8001", "کالایِ ترازویی",
    catalog_service.ItemFields(item_kind_code="GOOD", base_uom_id=uom_id, is_sellable=True, pos_requires_weight=True),
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
_, doc_before = documents_service.get_document(order_id, company_id), None
documents_service.add_line(
    order_id, company_id, item_id=item_id, uom_id=uom_id, quantity=decimal.Decimal(10),
    quantity_base=decimal.Decimal(10), unit_price=decimal.Decimal(1000),
)
documents_service.confirm_document(order_id, company_id, user.user_id)
_release_holds(order_id)

# ۱: سفارش باید در صفِ واحدِ «تاییدِ انبار و توزین» ظاهر شود.
queue = documents_service.list_pre_sales_fulfillment_queue(company_id)
check(order_id in [d.document_id for d in queue], "سفارش در صفِ واحدِ تاییدِ انبار/توزین ظاهر شد")

doc, lines = documents_service.get_document(order_id, company_id)
line_id = lines[0].line_id

# ۲: انباردار مقدارِ واقعیِ تحویلی (کمتر از سفارش، به‌خاطرِ کسری/وزن) را ثبت می‌کند.
documents_service.set_warehouse_delivered_quantities(order_id, company_id, {line_id: decimal.Decimal("8.5")})
doc, lines = documents_service.get_document(order_id, company_id)
check(lines[0].warehouse_delivered_quantity == decimal.Decimal("8.5"), f"مقدارِ تحویلی ثبت شد (got {lines[0].warehouse_delivered_quantity})")

documents_service.approve_warehouse(order_id, company_id, user.user_id)
status = documents_service.describe_pre_sales_fulfillment_status(order_id, company_id)
check(status == "در انتظارِ توزین", f"بعدِ تاییدِ انبار، وضعیت به‌درستی «در انتظارِ توزین» شد (got {status})")

# ۳: امکانِ بازگشت و ادیتِ مجدد پیش از تبدیل به فاکتور.
documents_service.revert_warehouse_approval(order_id, company_id)
doc, _ = documents_service.get_document(order_id, company_id)
check(doc.warehouse_approved_at is None, "بازگشتِ تاییدِ انبار موفق شد")
documents_service.set_warehouse_delivered_quantities(order_id, company_id, {line_id: decimal.Decimal("9")})
documents_service.approve_warehouse(order_id, company_id, user.user_id)
documents_service.approve_weighing(order_id, company_id, user.user_id)

status = documents_service.describe_pre_sales_fulfillment_status(order_id, company_id)
check(status == "آمادهٔ تبدیل به فاکتور", f"بعدِ هردو تایید، وضعیت «آماده» شد (got {status})")

# ۴: تبدیل به فاکتور باید از رویِ مقدارِ تحویلی (۹) باشد، نه مقدارِ سفارش (۱۰).
invoice_id = documents_service.convert_to_invoice(order_id, company_id, user.user_id, datetime.date.today())
_, invoice_lines = documents_service.get_document(invoice_id, company_id)
check(invoice_lines[0].quantity == decimal.Decimal(9), f"فاکتور با مقدارِ تحویلی (۹) ساخته شد، نه مقدارِ سفارش (got {invoice_lines[0].quantity})")

# ۵: بعدِ تبدیل، دیگر نه ویرایش نه بازگشت مجاز است («تاییدِ نهایی»).
check(documents_service.document_has_been_converted(order_id, company_id), "document_has_been_converted درست شناسایی کرد")
try:
    documents_service.set_warehouse_delivered_quantities(order_id, company_id, {line_id: decimal.Decimal("5")})
    check(False, "ویرایشِ مقدارِ تحویلی بعدِ تبدیل باید رد می‌شد")
except ValueError as exc:
    check("تبدیل" in str(exc), f"ویرایشِ بعدِ تبدیل درست رد شد ({exc})")
try:
    documents_service.revert_weighing_approval(order_id, company_id)
    check(False, "بازگشتِ تاییدِ توزین بعدِ تبدیل باید رد می‌شد")
except ValueError as exc:
    check("تبدیل" in str(exc), f"بازگشتِ توزین بعدِ تبدیل درست رد شد ({exc})")
try:
    documents_service.revert_warehouse_approval(order_id, company_id)
    check(False, "بازگشتِ تاییدِ انبار بعدِ تبدیل باید رد می‌شد")
except ValueError as exc:
    check(True, f"بازگشتِ انبار بعدِ تبدیل هم رد شد ({exc})")

queue_after = documents_service.list_pre_sales_fulfillment_queue(company_id)
check(order_id not in [d.document_id for d in queue_after], "بعدِ تبدیلِ کامل، سفارش دیگر در صفِ فعال نیست")

print("RESULT:", "ALL PASS" if not FAIL else "SOME FAILED")
sys.exit(1 if FAIL else 0)
