import os, sys, decimal, datetime
os.environ["PEECHA_DB_NAME"] = "peecha_test_r186_1"
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
app_qt = QApplication.instance() or QApplication([])
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
g1 = coa_service.create_account(company_id, "1", "دارایی‌ها", "DEBIT", "ASSET", "PERMANENT", False, lang_id)
k1 = coa_service.create_account(company_id, "11", "صندوق", "DEBIT", "ASSET", "PERMANENT", False, lang_id, parent_account_id=g1.account_id)
cash_gl = coa_service.create_account(company_id, "101", "صندوقِ اصلی", "DEBIT", "ASSET", "PERMANENT", True, lang_id, parent_account_id=k1.account_id)
k2 = coa_service.create_account(company_id, "13", "حساب‌هایِ دریافتنی", "DEBIT", "ASSET", "PERMANENT", False, lang_id, parent_account_id=g1.account_id)
ar_gl = coa_service.create_account(company_id, "1304", "حساب‌هایِ دریافتنیِ مشتریان", "DEBIT", "ASSET", "PERMANENT", True, lang_id, parent_account_id=k2.account_id)
k3 = coa_service.create_account(company_id, "11b", "موجودیِ انبار", "DEBIT", "ASSET", "PERMANENT", False, lang_id, parent_account_id=g1.account_id)
inv_asset_gl = coa_service.create_account(company_id, "102", "موجودیِ کالا", "DEBIT", "ASSET", "PERMANENT", True, lang_id, parent_account_id=k3.account_id)
g2 = coa_service.create_account(company_id, "4", "درآمدها", "CREDIT", "REVENUE", "TEMPORARY", False, lang_id)
k4 = coa_service.create_account(company_id, "41", "درآمدِ عملیاتی", "CREDIT", "REVENUE", "TEMPORARY", False, lang_id, parent_account_id=g2.account_id)
revenue_gl = coa_service.create_account(company_id, "411", "درآمدِ فروش", "CREDIT", "REVENUE", "TEMPORARY", True, lang_id, parent_account_id=k4.account_id)
g3 = coa_service.create_account(company_id, "5", "هزینه‌ها", "DEBIT", "EXPENSE", "TEMPORARY", False, lang_id)
k5 = coa_service.create_account(company_id, "51", "بهایِ تمام‌شده", "DEBIT", "EXPENSE", "TEMPORARY", False, lang_id, parent_account_id=g3.account_id)
cogs_gl = coa_service.create_account(company_id, "511", "بهایِ تمام‌شده", "DEBIT", "EXPENSE", "TEMPORARY", True, lang_id, parent_account_id=k5.account_id)

from peecha.services import inventory_engine as engine_service
engine_service.set_account_mapping(company_id, "INVENTORY_ASSET", inv_asset_gl.account_id)
engine_service.set_account_mapping(company_id, "CUSTOMER_RECEIVABLE", ar_gl.account_id)
engine_service.set_account_mapping(company_id, "COGS", cogs_gl.account_id)
csettings_service.set_account_mapping(company_id, "SALES_REVENUE", revenue_gl.account_id)

customer_group_id = dimensions_service.get_person_group_id(company_id, dimensions_service.CUSTOMER_GROUP_CODE)
treasury_service.create_counterparty_mapping(company_id, "RECEIPT", ar_gl.account_id, person_group_id=customer_group_id)
treasury_service.set_account_mapping(company_id, "RECEIPT_CASH", cash_gl.account_id)

uom_id = catalog_service.create_uom(company_id, "PCS", "عدد", "COUNT")
item_id = catalog_service.create_item(
    company_id, "9101", "کالایِ عادی",
    catalog_service.ItemFields(item_kind_code="GOOD", base_uom_id=uom_id, is_sellable=True),
)
warehouse_id = locations_service.create_warehouse(
    company_id, "WH-1", "انبارِ آزمایشی", locations_service.WarehouseFields(allow_negative_stock=True),
)
channel_code = pricing_service.create_channel(company_id, "VAN-1", "پخشِ گرمِ آزمایشی", "VAN_SALES")

customer_debtor = partners_service.create_customer(company_id, "C-1", "فروشگاهِ بدهکار", fast_track=True)
customer_paid = partners_service.create_customer(company_id, "C-2", "فروشگاهِ تسویه‌شده", fast_track=True)
customer_no_plan = partners_service.create_customer(company_id, "C-3", "فروشگاهِ بی‌ربط", fast_track=True)

visitor = users_service.create_user("visitor1", "ویزیتورِ یک", "secret123", None, lang_id, False, [company_id], company_id)

field_sales_service.create_visit_plan(company_id, customer_debtor, 0, 1, visitor.user_id)
field_sales_service.create_visit_plan(company_id, customer_paid, 0, 2, visitor.user_id)
# customer_no_plan عمداً به این ویزیتور assign نشده -- نباید در فهرستِ بدهکارانش بیاید.

today = datetime.date.today()


def _invoice_and_pay(customer_id, pay_full):
    invoice_id = documents_service.create_document(
        company_id, visitor.user_id, "SALES_INVOICE", today,
        documents_service.DocumentHeaderFields(
            counterparty_detail_account_id=customer_id, currency_id=company.base_currency_id,
            warehouse_id=warehouse_id, channel_code=channel_code,
        ),
    )
    documents_service.add_line(
        invoice_id, company_id, item_id=item_id, uom_id=uom_id, quantity=decimal.Decimal(2),
        quantity_base=decimal.Decimal(2), unit_price=decimal.Decimal(150000),
    )
    documents_service.confirm_document(invoice_id, company_id, visitor.user_id)
    settlements_service.auto_approve_full_cash_settlement_plan(invoice_id, company_id, visitor.user_id)
    documents_service.post_document(invoice_id, company_id, visitor.user_id)
    if pay_full:
        treasury_service.create_treasury_voucher(
            company_id, visitor.user_id, "RECEIPT", ar_gl.account_id,
            {dimensions_service.get_person_dimension_type_id(company_id): customer_id},
            today, "تسویهٔ کامل", [treasury_service.MethodLine(method="CASH", amount=decimal.Decimal(300000))],
        )
    return invoice_id


_invoice_and_pay(customer_debtor, pay_full=False)
_invoice_and_pay(customer_paid, pay_full=True)

from fastapi.testclient import TestClient
from peecha_api.main import app
client = TestClient(app)

resp = client.post("/auth/login", json={"username": "visitor1", "password": "secret123"})
token = resp.json()["access_token"]
auth = {"Authorization": f"Bearer {token}"}

resp = client.get("/collection/debtors", headers=auth)
check(resp.status_code == 200, f"فهرستِ بدهکاران موفق بود (status={resp.status_code}, body={resp.text})")
debtors = resp.json()
debtor_ids = {d["detail_account_id"] for d in debtors}
check(customer_debtor in debtor_ids, f"مشتریِ بدهکار در فهرست است (got {debtors})")
check(customer_paid not in debtor_ids, "مشتریِ تسویه‌شده در فهرستِ بدهکاران نیست")
check(customer_no_plan not in debtor_ids, "مشتریِ بدونِ برنامهٔ ویزیت در فهرستِ این ویزیتور نیست")
check(
    any(d["detail_account_id"] == customer_debtor and decimal.Decimal(d["balance_amount"]) == decimal.Decimal(300000) for d in debtors),
    f"ماندهٔ مشتریِ بدهکار درست است (got {debtors})",
)

# ---------- رفعِ گزارشِ گمراه‌کننده‌یِ Aging (R222): «عقب‌افتاده» باید
# واقعاً از رویِ سررسیدِ فاکتور (document_date + payment_term_days)
# محاسبه شود، نه یک پرچمِ ثابت رویِ همه‌یِ بدهکاران. ----------
customer_overdue = partners_service.create_customer(
    company_id, "C-4", "فروشگاهِ عقب‌افتاده", fields=partners_service.CustomerProfileFields(payment_term_days=30), fast_track=True,
)
customer_not_due_yet = partners_service.create_customer(
    company_id, "C-5", "فروشگاهِ درمهلت", fields=partners_service.CustomerProfileFields(payment_term_days=30), fast_track=True,
)
field_sales_service.create_visit_plan(company_id, customer_overdue, 0, 3, visitor.user_id)
field_sales_service.create_visit_plan(company_id, customer_not_due_yet, 0, 4, visitor.user_id)


def _invoice_on_date(customer_id, document_date):
    invoice_id = documents_service.create_document(
        company_id, visitor.user_id, "SALES_INVOICE", document_date,
        documents_service.DocumentHeaderFields(
            counterparty_detail_account_id=customer_id, currency_id=company.base_currency_id,
            warehouse_id=warehouse_id, channel_code=channel_code,
        ),
    )
    documents_service.add_line(
        invoice_id, company_id, item_id=item_id, uom_id=uom_id, quantity=decimal.Decimal(1),
        quantity_base=decimal.Decimal(1), unit_price=decimal.Decimal(100000),
    )
    documents_service.confirm_document(invoice_id, company_id, visitor.user_id)
    settlements_service.auto_approve_full_cash_settlement_plan(invoice_id, company_id, visitor.user_id)
    documents_service.post_document(invoice_id, company_id, visitor.user_id)
    return invoice_id


# سررسید = ۴۰ روزِ پیش + ۳۰ روزِ مهلت = ۱۰ روزِ گذشته -- عقب‌افتاده.
_invoice_on_date(customer_overdue, today - datetime.timedelta(days=40))
# سررسید = امروز + ۳۰ روزِ مهلت = آینده -- هنوز در مهلت.
_invoice_on_date(customer_not_due_yet, today)

resp = client.get("/collection/debtors", headers=auth)
check(resp.status_code == 200, f"فهرستِ بدهکاران بعدِ افزودنِ سناریوهایِ Aging موفق بود (status={resp.status_code})")
debtors2 = {d["detail_account_id"]: d for d in resp.json()}
check(
    customer_overdue in debtors2 and debtors2[customer_overdue]["is_overdue"] is True,
    f"مشتریِ با سررسیدِ گذشته عقب‌افتاده است (got {debtors2.get(customer_overdue)})",
)
check(
    customer_not_due_yet in debtors2 and debtors2[customer_not_due_yet]["is_overdue"] is False,
    f"مشتریِ با سررسیدِ آینده عقب‌افتاده نیست (got {debtors2.get(customer_not_due_yet)})",
)
check(
    debtors2[customer_overdue]["earliest_due_date"] == (today - datetime.timedelta(days=10)).isoformat(),
    f"سررسیدِ واقعی محاسبه شد (got {debtors2[customer_overdue]['earliest_due_date']})",
)

resp = client.get("/collection/today", headers=auth)
check(resp.status_code == 200, f"وصولِ امروز موفق بود (status={resp.status_code})")
today_collections = resp.json()
check(len(today_collections) == 1 and today_collections[0]["customer_name"] == "فروشگاهِ تسویه‌شده", f"وصولِ امروز درست است (got {today_collections})")
check(decimal.Decimal(today_collections[0]["amount"]) == decimal.Decimal(300000), "مبلغِ وصولِ امروز درست است")

print("RESULT:", "ALL PASS" if not FAIL else "SOME FAILED")
sys.exit(1 if FAIL else 0)
