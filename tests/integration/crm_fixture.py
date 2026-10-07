"""فیکسچر مشترک تست‌های CRM (R281+): شرکت، کدینگ و نگاشت حساب‌های فروش/دریافت، کالا، انبار، کانال، مشتری‌ها و
ویزیتور. نام دیتابیس را فایل تست پیش از import تنظیم می‌کند."""
import os, sys, decimal, datetime
for k, v in (("PEECHA_DB_USER", "peecha"), ("PEECHA_DB_PASSWORD", "peecha"), ("PEECHA_DB_HOST", "localhost"), ("PEECHA_DB_PORT", "5432")):
    os.environ.setdefault(k, v)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))

D = decimal.Decimal
FAILED = []


def check(cond, msg):
    if not cond:
        FAILED.append(msg)
        print("FAIL:", msg)
    else:
        print("OK:", msg)


def raises(fn, needle=""):
    try:
        fn()
    except ValueError as exc:
        return needle in str(exc)
    return False


def finish():
    print("ALL PASS" if not FAILED else "SOME FAILED")


from peecha.db.schema_bootstrap import apply_pending_schema_files
from peecha.db.base import get_engine, new_session
apply_pending_schema_files(get_engine())
from peecha.services.bootstrap import bootstrap_system
from peecha import session as sess
from sqlalchemy import select
from peecha.db.models.security import UserCompany
from peecha.db.models.core import Company

user = bootstrap_system("admin", "مدیر سیستم", "secret123", "شرکت پخش")
sess.current_user = user
uid = user.user_id
with new_session() as s:
    company = s.get(Company, s.scalar(select(UserCompany.company_id).where(UserCompany.user_id == uid)))
company_id = company.company_id
sess.current_company = company
today = datetime.date.today()

from peecha.services import fiscal_years as fiscal_years_service
fiscal_years_service.create_fiscal_year_for_date(company_id, 1, 1, today)

from peecha.services import chart_of_accounts as coa_service
from peecha.services import inventory_catalog as catalog_service
from peecha.services import inventory_locations as locations_service
from peecha.services import inventory_engine as engine_service
from peecha.services import commercial_pricing as pricing_service
from peecha.services import commercial_settings as csettings_service
from peecha.services import commercial_documents as documents_service
from peecha.services import commercial_settlements as settlements_service
from peecha.services import commercial_partners as partners_service
from peecha.services import treasury as treasury_service
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import field_sales as field_sales_service
from peecha.services import users as users_service

lang_id = company.default_language_id
A = lambda code, name, nat, typ, per, leaf, parent=None: coa_service.create_account(
    company_id, code, name, nat, typ, per, leaf, lang_id, parent_account_id=parent)
g1 = A("1", "دارایی‌ها", "DEBIT", "ASSET", "PERMANENT", False)
k1 = A("11", "صندوق", "DEBIT", "ASSET", "PERMANENT", False, g1.account_id)
cash_gl = A("101", "صندوق اصلی", "DEBIT", "ASSET", "PERMANENT", True, k1.account_id)
k2 = A("13", "حساب‌های دریافتنی", "DEBIT", "ASSET", "PERMANENT", False, g1.account_id)
ar_gl = A("1304", "دریافتنی مشتریان", "DEBIT", "ASSET", "PERMANENT", True, k2.account_id)
k3 = A("12", "موجودی", "DEBIT", "ASSET", "PERMANENT", False, g1.account_id)
inv_gl = A("102", "موجودی کالا", "DEBIT", "ASSET", "PERMANENT", True, k3.account_id)
g2 = A("4", "درآمدها", "CREDIT", "REVENUE", "TEMPORARY", False)
k4 = A("41", "درآمد عملیاتی", "CREDIT", "REVENUE", "TEMPORARY", False, g2.account_id)
revenue_gl = A("411", "درآمد فروش", "CREDIT", "REVENUE", "TEMPORARY", True, k4.account_id)
g3 = A("5", "هزینه‌ها", "DEBIT", "EXPENSE", "TEMPORARY", False)
k5 = A("51", "بهای تمام‌شده", "DEBIT", "EXPENSE", "TEMPORARY", False, g3.account_id)
cogs_gl = A("511", "بهای تمام‌شده", "DEBIT", "EXPENSE", "TEMPORARY", True, k5.account_id)
discount_gl = A("412", "تخفیفات فروش", "DEBIT", "REVENUE", "TEMPORARY", True, k4.account_id)
engine_service.set_account_mapping(company_id, "INVENTORY_ASSET", inv_gl.account_id)
engine_service.set_account_mapping(company_id, "CUSTOMER_RECEIVABLE", ar_gl.account_id)
engine_service.set_account_mapping(company_id, "COGS", cogs_gl.account_id)
csettings_service.set_account_mapping(company_id, "SALES_REVENUE", revenue_gl.account_id)
csettings_service.set_account_mapping(company_id, "SALES_DISCOUNT", discount_gl.account_id)
customer_group_id = dimensions_service.get_person_group_id(company_id, dimensions_service.CUSTOMER_GROUP_CODE)
treasury_service.create_counterparty_mapping(company_id, "RECEIPT", ar_gl.account_id, person_group_id=customer_group_id)
treasury_service.set_account_mapping(company_id, "RECEIPT_CASH", cash_gl.account_id)

pcs = catalog_service.create_uom(company_id, "PCS", "عدد", "COUNT", decimal_places=0)
IF = catalog_service.ItemFields
item_a = catalog_service.create_item(company_id, "A1", "کالای الف", IF(item_kind_code="GOOD", base_uom_id=pcs, is_sellable=True))
item_b = catalog_service.create_item(company_id, "B1", "کالای ب", IF(item_kind_code="GOOD", base_uom_id=pcs, is_sellable=True))
warehouse_id = locations_service.create_warehouse(company_id, "WH-1", "انبار مرکزی",
                                                  locations_service.WarehouseFields(allow_negative_stock=True, is_default=True))
channel_code = pricing_service.create_channel(company_id, "VAN-1", "پخش گرم", "VAN_SALES")

cust_a = partners_service.create_customer(company_id, "C-1", "فروشگاه الف", fast_track=True, mobile="09120000001")
cust_b = partners_service.create_customer(company_id, "C-2", "فروشگاه ب", fast_track=True, mobile="09120000002")
visitor = users_service.create_user("visitor1", "ویزیتور یک", "secret123", None, lang_id, False, [company_id], company_id)
field_sales_service.create_visit_plan(company_id, cust_a, today.weekday(), 1, visitor.user_id)


def invoice(customer_id, amount, date=None, pay=None, item=None, user_id=None, due_date=None):
    """فاکتور فروش ثبت‌شده با سرویس فروش موجود؛ pay = مبلغ دریافت نقدی با سند خزانه."""
    date = date or today
    doc = documents_service.create_document(company_id, user_id or uid, "SALES_INVOICE", date, documents_service.DocumentHeaderFields(
        counterparty_detail_account_id=customer_id, currency_id=company.base_currency_id, warehouse_id=warehouse_id,
        channel_code=channel_code, due_date=due_date))
    documents_service.add_line(doc, company_id, item_id=item or item_a, uom_id=pcs, quantity=D(1), quantity_base=D(1),
                               unit_price=D(amount))
    documents_service.confirm_document(doc, company_id, user_id or uid)
    settlements_service.auto_approve_full_cash_settlement_plan(doc, company_id, user_id or uid)
    documents_service.post_document(doc, company_id, user_id or uid)
    if pay:
        receipt(customer_id, pay, date)
    return doc


def receipt(customer_id, amount, date=None):
    return treasury_service.create_treasury_voucher(
        company_id, uid, "RECEIPT", ar_gl.account_id, {dimensions_service.get_person_dimension_type_id(company_id): customer_id},
        date or today, "دریافت وجه", [treasury_service.MethodLine(method="CASH", amount=D(amount))])
