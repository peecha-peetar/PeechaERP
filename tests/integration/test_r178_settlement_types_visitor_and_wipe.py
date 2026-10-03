import os, sys, decimal, datetime
os.environ["PEECHA_DB_NAME"] = "peecha_test_r178_1"
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
from peecha.services import distribution_runs as distribution_service
from peecha.services import data_reset as data_reset_service
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


# ==========================================================================
# ۱: انواعِ تسویهٔ پخش -- مفهومی مستقل از روشِ دریافت/پرداختِ خزانه‌داری.
# ==========================================================================
types = pricing_service.list_distribution_settlement_types(company_id)
codes = {t.code for t in types}
check(
    {"CASH_ON_TRUCK", "CHECK", "RECEIPT", "WEEKLY", "ON_TRUCK"}.issubset(codes),
    f"انواعِ پیش‌فرضِ تسویهٔ پخش خودکار ساخته شدند (got {codes})",
)
pricing_service.create_distribution_settlement_type(company_id, "CUSTOM1", "تسویهٔ سفارشیِ آزمایشی")
types_after = {t.code: t.name for t in pricing_service.list_distribution_settlement_types(company_id)}
check(types_after.get("CUSTOM1") == "تسویهٔ سفارشیِ آزمایشی", "نوعِ تسویهٔ سفارشی با موفقیت اضافه شد")

# نوعِ تسویهٔ پخش باید از جدولِ مستقلِ خودش (comm.distribution_settlement_types)
# بیاید، نه از تابعِ روشِ دریافتِ خزانه‌داری -- ولو کدهایی مثلِ "CHECK"
# تصادفاً در هردو فهرستِ کاملاً مستقل تکرار شده باشند.
check(
    "CASH_ON_TRUCK" not in set(settlements_service.settlement_plan_method_codes("SALES_INVOICE", company_id)),
    "نوعِ تسویهٔ پخش از جدولِ مستقلِ خودش می‌آید، نه از روشِ دریافتِ خزانه‌داری",
)

# ==========================================================================
# ۲: فیلترِ ویزیتور رویِ تیمِ پخش.
# ==========================================================================
uom_id = catalog_service.create_uom(company_id, "PCS", "عدد", "COUNT")
item_id = catalog_service.create_item(
    company_id, "9101", "کالایِ عادی",
    catalog_service.ItemFields(item_kind_code="GOOD", base_uom_id=uom_id, is_sellable=True),
)
warehouse_id = locations_service.create_warehouse(
    company_id, "WH-1", "انبارِ آزمایشی", locations_service.WarehouseFields(allow_negative_stock=True),
)
channel_code = pricing_service.create_channel(company_id, "COLD-1", "پخشِ سردِ منطقه‌یِ ۱", "PRE_SALES")
customer_id = dimensions_service.create_customer(company_id, "C-1", "مشتریِ آزمایشی")

from peecha.services import users as users_service
visitor_user = users_service.create_user(
    "visitor1", "ویزیتورِ یک", "secret123", None, company.default_language_id, False, [company_id], company_id,
)
visitor_user_id = visitor_user.user_id


def _make_invoice(created_by_user_id, settlement_type):
    order_id = documents_service.create_document(
        company_id, created_by_user_id, "SALES_ORDER", datetime.date.today(),
        documents_service.DocumentHeaderFields(
            counterparty_detail_account_id=customer_id, currency_id=company.base_currency_id,
            warehouse_id=warehouse_id, channel_code=channel_code, settlement_type_code=settlement_type,
        ),
    )
    documents_service.add_line(
        order_id, company_id, item_id=item_id, uom_id=uom_id, quantity=decimal.Decimal(2),
        quantity_base=decimal.Decimal(2), unit_price=decimal.Decimal(1000),
    )
    documents_service.confirm_document(order_id, company_id, created_by_user_id)
    _release_holds(order_id)
    documents_service.approve_warehouse(order_id, company_id, user.user_id)
    invoice_id = documents_service.convert_to_invoice(order_id, company_id, user.user_id, datetime.date.today())
    documents_service.confirm_document(invoice_id, company_id, user.user_id)
    settlements_service.auto_approve_full_cash_settlement_plan(invoice_id, company_id, user.user_id)
    documents_service.post_document(invoice_id, company_id, user.user_id)
    return order_id, invoice_id


order_by_visitor, invoice_by_visitor = _make_invoice(visitor_user_id, "WEEKLY")
order_by_admin, invoice_by_admin = _make_invoice(user.user_id, "CASH_ON_TRUCK")

eligible_by_visitor = distribution_service.list_eligible_invoices(company_id, visitor_user_id=visitor_user_id)
check(
    invoice_by_visitor in [e.document_id for e in eligible_by_visitor]
    and invoice_by_admin not in [e.document_id for e in eligible_by_visitor],
    "فیلترِ ویزیتور فقط فاکتورِ سفارشِ ثبت‌شده توسطِ همان ویزیتور را برمی‌گرداند",
)

visitors = distribution_service.list_order_visitors(company_id)
check(visitor_user_id in [v[0] for v in visitors], "ویزیتورِ تازه‌ساخته در فهرستِ list_order_visitors ظاهر شد")

# ==========================================================================
# ۳: رفعِ باگِ گزارش‌شده -- خام‌کردنِ اسناد نباید با نقضِ FKِ
#    distribution_run_documents متوقف شود.
# ==========================================================================
vehicle_id = locations_service.create_warehouse(
    company_id, "VEH-1", "وانتِ ۱", locations_service.WarehouseFields(warehouse_type_code="VEHICLE"),
)
run_id = distribution_service.create_distribution_run(company_id, user.user_id, datetime.date.today(), vehicle_id)
distribution_service.add_document_to_run(run_id, company_id, invoice_by_admin)

try:
    data_reset_service.wipe_documents(company_id)
    check(True, "خام‌کردنِ اسناد با وجودِ تیمِ پخشِ فعال، بدونِ خطا انجام شد")
except ValueError as exc:
    check(False, f"خام‌کردنِ اسناد هنوز با خطا متوقف می‌شود: {exc}")

with new_session() as s:
    from peecha.db.models.commercial import DistributionRun, DistributionRunDocument
    remaining_runs = s.scalar(select(DistributionRun).where(DistributionRun.company_id == company_id))
    remaining_links = s.scalar(select(DistributionRunDocument))
check(remaining_runs is None, "تیمِ پخش هم واقعاً پاک شد")
check(remaining_links is None, "الصاقِ فاکتور به تیمِ پخش هم واقعاً پاک شد")

print("RESULT:", "ALL PASS" if not FAIL else "SOME FAILED")
sys.exit(1 if FAIL else 0)
