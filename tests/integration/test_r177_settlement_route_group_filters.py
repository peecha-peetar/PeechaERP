import os, sys, decimal, datetime
os.environ["PEECHA_DB_NAME"] = "peecha_test_r177_1"
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
from peecha.services import commercial_partners as partners_service
from peecha.services import commercial_settlements as settlements_service
from peecha.services import distribution_runs as distribution_service
from peecha.db.models.commercial import CreditHold
from peecha.services import commercial_credit as credit_service

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


def _release_holds(order_id):
    with new_session() as s:
        hold = s.scalar(select(CreditHold).where(CreditHold.related_document_id == order_id, CreditHold.released_at.is_(None)))
        if hold is not None:
            credit_service.release_credit_hold(hold.hold_id, user.user_id)


uom_id = catalog_service.create_uom(company_id, "PCS", "عدد", "COUNT")
item_id = catalog_service.create_item(
    company_id, "9001", "کالایِ عادی",
    catalog_service.ItemFields(item_kind_code="GOOD", base_uom_id=uom_id, is_sellable=True),
)
warehouse_id = locations_service.create_warehouse(
    company_id, "WH-1", "انبارِ آزمایشی", locations_service.WarehouseFields(allow_negative_stock=True),
)
channel_code = pricing_service.create_channel(company_id, "COLD-1", "پخشِ سردِ منطقه‌یِ ۱", "PRE_SALES")

# --- گروهِ مشتریان و مسیرِ توزیع (منطقه > مسیر) ---
group_a = partners_service.create_customer_group(company_id, "VIP", "مشتریانِ ویژه")
group_b = partners_service.create_customer_group(company_id, "REG", "مشتریانِ عادی")
route_dim_id = dimensions_service.get_specialized_dimension_type_id(company_id, dimensions_service.DISTRIBUTION_ROUTE_CODE)
region_north = dimensions_service.create_detail_account(company_id, route_dim_id, "N", "شمال").detail_account_id
route_north_1 = dimensions_service.create_detail_account(company_id, route_dim_id, "N1", "مسیرِ شمالِ ۱", parent_detail_account_id=region_north).detail_account_id
region_south = dimensions_service.create_detail_account(company_id, route_dim_id, "S", "جنوب").detail_account_id

customer_vip_north = partners_service.create_customer_detail_account(
    company_id, "C-VIP-N", "مشتریِ ویژه شمالی", customer_group_id=group_a, distribution_route_detail_account_id=route_north_1,
)
customer_reg_south = partners_service.create_customer_detail_account(
    company_id, "C-REG-S", "مشتریِ عادیِ جنوبی", customer_group_id=group_b, distribution_route_detail_account_id=region_south,
)


def _make_invoice(customer_id, settlement_type):
    order_id = documents_service.create_document(
        company_id, user.user_id, "SALES_ORDER", datetime.date.today(),
        documents_service.DocumentHeaderFields(
            counterparty_detail_account_id=customer_id, currency_id=company.base_currency_id,
            warehouse_id=warehouse_id, channel_code=channel_code, settlement_type_code=settlement_type,
        ),
    )
    documents_service.add_line(
        order_id, company_id, item_id=item_id, uom_id=uom_id, quantity=decimal.Decimal(2),
        quantity_base=decimal.Decimal(2), unit_price=decimal.Decimal(1000),
    )
    documents_service.confirm_document(order_id, company_id, user.user_id)
    _release_holds(order_id)
    documents_service.approve_warehouse(order_id, company_id, user.user_id)
    invoice_id = documents_service.convert_to_invoice(order_id, company_id, user.user_id, datetime.date.today())
    documents_service.confirm_document(invoice_id, company_id, user.user_id)
    settlements_service.auto_approve_full_cash_settlement_plan(invoice_id, company_id, user.user_id)
    documents_service.post_document(invoice_id, company_id, user.user_id)
    return order_id, invoice_id


order_vip, invoice_vip = _make_invoice(customer_vip_north, "CASH")
order_reg, invoice_reg = _make_invoice(customer_reg_south, "CHECK")

# ۱: نوعِ تسویه از سفارش به فاکتور منتقل شده باشد.
doc, _ = documents_service.get_document(invoice_vip, company_id)
check(doc.settlement_type_code == "CASH", f"نوعِ تسویه از سفارش به فاکتورِ VIP منتقل شد (got {doc.settlement_type_code})")
doc, _ = documents_service.get_document(invoice_reg, company_id)
check(doc.settlement_type_code == "CHECK", f"نوعِ تسویه از سفارش به فاکتورِ REG منتقل شد (got {doc.settlement_type_code})")

# ۲: فیلترِ گروهِ مشتریان.
eligible_vip_group = distribution_service.list_eligible_invoices(company_id, customer_group_id=group_a)
check(
    invoice_vip in [e.document_id for e in eligible_vip_group] and invoice_reg not in [e.document_id for e in eligible_vip_group],
    "فیلترِ گروهِ مشتریان فقط فاکتورِ همان گروه را برمی‌گرداند",
)

# ۳: فیلترِ مسیر/منطقه -- انتخابِ سطحِ منطقه باید زیرمسیرهایش را هم بگیرد.
eligible_region_north = distribution_service.list_eligible_invoices(company_id, route_detail_account_id=region_north)
check(
    invoice_vip in [e.document_id for e in eligible_region_north] and invoice_reg not in [e.document_id for e in eligible_region_north],
    "فیلترِ سطحِ «منطقه» زیرمسیرهایش را هم شامل می‌شود",
)
eligible_region_south = distribution_service.list_eligible_invoices(company_id, route_detail_account_id=region_south)
check(
    invoice_reg in [e.document_id for e in eligible_region_south] and invoice_vip not in [e.document_id for e in eligible_region_south],
    "فیلترِ منطقهٔ جنوب فقط فاکتورِ همان منطقه را برمی‌گرداند",
)

# ۴: بدونِ فیلتر، هر دو فاکتور دیده می‌شوند.
eligible_all = distribution_service.list_eligible_invoices(company_id)
check(
    invoice_vip in [e.document_id for e in eligible_all] and invoice_reg in [e.document_id for e in eligible_all],
    "بدونِ فیلتر، هر دو فاکتور در فهرستِ واجدِ شرایط هستند",
)

# ۵: نوعِ تسویه رویِ ردیفِ فاکتورِ برگردانده‌شده هم موجود است.
row = next(e for e in eligible_all if e.document_id == invoice_vip)
check(row.settlement_type_code == "CASH", f"نوعِ تسویه رویِ ردیفِ فاکتورِ واجدِ شرایط درست است (got {row.settlement_type_code})")

print("RESULT:", "ALL PASS" if not FAIL else "SOME FAILED")
sys.exit(1 if FAIL else 0)
