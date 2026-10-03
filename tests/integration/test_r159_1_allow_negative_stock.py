import os, sys, datetime, decimal
os.environ["PEECHA_DB_NAME"] = "peecha_test_r159_1"
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

from PySide6.QtWidgets import QApplication, QMessageBox, QWidget, QVBoxLayout
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
g4 = coa_service.create_account(company_id, "2", "بدهی‌ها", "CREDIT", "LIABILITY", "PERMANENT", False, lang_id)
k6 = coa_service.create_account(company_id, "21", "سایرِ بدهی‌ها", "CREDIT", "LIABILITY", "PERMANENT", False, lang_id, parent_account_id=g4.account_id)
ap_gl = coa_service.create_account(company_id, "211", "پرداختنیِ تامین‌کنندگان", "CREDIT", "LIABILITY", "PERMANENT", True, lang_id, parent_account_id=k6.account_id)

engine_service.set_account_mapping(company_id, "INVENTORY_ASSET", inv_asset_gl.account_id)
engine_service.set_account_mapping(company_id, "CUSTOMER_RECEIVABLE", ar_gl.account_id)
engine_service.set_account_mapping(company_id, "SUPPLIER_PAYABLE", ap_gl.account_id)
engine_service.set_account_mapping(company_id, "COGS", cogs_gl.account_id)
csettings_service.set_account_mapping(company_id, "SALES_REVENUE", revenue_gl.account_id)

uom_id = catalog_service.create_uom(company_id, "PCS", "عدد", "COUNT")
# انبارِ فروشگاه با «امکانِ فروشِ منفی» صراحتاً فعال است.
neg_warehouse_id = locations_service.create_warehouse(
    company_id, "WH-NEG", "انبارِ فروشگاهِ منفی‌پذیر",
    locations_service.WarehouseFields(allow_negative_stock=True),
)
# انبارِ عادی (بدونِ اجازهٔ منفی) برایِ مقایسه.
strict_warehouse_id = locations_service.create_warehouse(company_id, "WH-STRICT", "انبارِ عادی", locations_service.WarehouseFields())
customer_id = dimensions_service.create_customer(company_id, "1", "مشتریِ آزمایشی")
supplier_id = dimensions_service.create_supplier(company_id, "9", "تامین‌کننده")

item_id = catalog_service.create_item(
    company_id, "3001", "کالایِ آزمایشی", catalog_service.ItemFields(item_kind_code="GOOD", base_uom_id=uom_id, is_sellable=True),
)

# فقط ۲ عدد در هرکدام از دو انبار موجود است.
for wh_id in (neg_warehouse_id, strict_warehouse_id):
    receipt_id = inv_documents_service.create_stock_document(
        company_id, user.user_id, "RECEIPT", datetime.date.today(),
        inv_documents_service.DocumentHeaderFields(destination_warehouse_id=wh_id, counterparty_detail_account_id=supplier_id),
    )
    inv_documents_service.add_line(receipt_id, company_id, inv_documents_service.LineFields(
        item_id=item_id, uom_id=uom_id, quantity=decimal.Decimal(2), quantity_base=decimal.Decimal(2), unit_cost=decimal.Decimal(1000),
    ))
    inv_documents_service.confirm_stock_document(receipt_id, company_id)
    inv_documents_service.post_stock_document(receipt_id, company_id, user.user_id)

terminal_id = pos_service.create_terminal(company_id, neg_warehouse_id, "T1", "صندوقِ منفی‌پذیر")
session_id = pos_service.open_session(terminal_id, user.user_id, decimal.Decimal(500000))

# =========================================================================
# ۱: فاکتوری در انبارِ منفی‌پذیر با درخواستِ ۱۰ عدد (بیش از موجودی) --
#    طبقِ درخواستِ صریح، این دیگر «کمبود» محسوب نمی‌شود چون خودِ انبار
#    صراحتاً موجودیِ منفی را مجاز کرده.
# =========================================================================
doc_id = documents_service.create_document(
    company_id, user.user_id, "SALES_INVOICE", datetime.date.today(),
    documents_service.DocumentHeaderFields(
        counterparty_detail_account_id=customer_id, currency_id=company.base_currency_id,
        warehouse_id=neg_warehouse_id, pos_session_id=session_id,
    ),
)
documents_service.add_line(doc_id, company_id, item_id, uom_id, decimal.Decimal(10), decimal.Decimal(10), unit_price=decimal.Decimal(2000))
documents_service.confirm_document(doc_id, company_id, user.user_id)

shortages = documents_service.get_stock_shortages(doc_id, company_id)
check(shortages == [], f"no shortage is reported for a warehouse that explicitly allows negative stock (got {shortages})")

documents_service.approve_document(doc_id, company_id)
result = documents_service.post_document(doc_id, company_id, user.user_id)
check(result.stock_document_id is not None, "post_document succeeds directly (no compensating transfer needed) when negative stock is allowed")
doc_final, _ = documents_service.get_document(doc_id, company_id)
check(doc_final.status_code == "POSTED", f"the invoice reaches POSTED directly (got {doc_final.status_code})")

with new_session() as s:
    from peecha.db.models.inventory import StockBalance
    bal = s.scalar(select(StockBalance).where(StockBalance.item_id == item_id, StockBalance.warehouse_id == neg_warehouse_id))
check(bal is not None and bal.quantity_on_hand == decimal.Decimal("-8"), f"stock actually went negative as intended (got {bal.quantity_on_hand if bal else None})")

# =========================================================================
# ۲: هم‌زمان، همان سناریو در انبارِ عادی (بدونِ اجازهٔ منفی) هنوز
#    به‌عنوانِ کمبود تشخیص داده می‌شود -- رفتارِ قبلی/موردِ R158 دست‌نخورده
#    می‌ماند.
# =========================================================================
strict_doc_id = documents_service.create_document(
    company_id, user.user_id, "SALES_INVOICE", datetime.date.today(),
    documents_service.DocumentHeaderFields(
        counterparty_detail_account_id=customer_id, currency_id=company.base_currency_id,
        warehouse_id=strict_warehouse_id,
    ),
)
documents_service.add_line(strict_doc_id, company_id, item_id, uom_id, decimal.Decimal(10), decimal.Decimal(10), unit_price=decimal.Decimal(2000))
documents_service.confirm_document(strict_doc_id, company_id, user.user_id)
strict_shortages = documents_service.get_stock_shortages(strict_doc_id, company_id)
check(len(strict_shortages) == 1, f"a normal (non-negative-allowed) warehouse still reports the shortage as before (got {len(strict_shortages)})")

# =========================================================================
# ۳: UIِ زنده -- صفحه‌یِ تاییدِ سرپرست برایِ همین انبارِ منفی‌پذیر باید
#    یک‌راست approve/post کند، بدونِ هیچ پیامِ کمبود/سندِ انتقالِ
#    غیرِلازم.
# =========================================================================
from peecha.ui.screens.commercial_pos_approval import CommercialPosApprovalScreen

ui_doc_id = documents_service.create_document(
    company_id, user.user_id, "SALES_INVOICE", datetime.date.today(),
    documents_service.DocumentHeaderFields(
        counterparty_detail_account_id=customer_id, currency_id=company.base_currency_id,
        warehouse_id=neg_warehouse_id, pos_session_id=session_id,
    ),
)
documents_service.add_line(ui_doc_id, company_id, item_id, uom_id, decimal.Decimal(5), decimal.Decimal(5), unit_price=decimal.Decimal(2000))
documents_service.confirm_document(ui_doc_id, company_id, user.user_id)
pos_service.set_intended_payment_type(ui_doc_id, company_id, "CASH")

screen = CommercialPosApprovalScreen()
host = QWidget(); QVBoxLayout(host).addWidget(screen); host.show()
screen.refresh()
app.processEvents()

target_row = next(i for i, d in enumerate(screen._documents) if d.document_id == ui_doc_id)
screen._row_checkbox(target_row).setChecked(True)
screen._approve_selected()
app.processEvents()

ui_doc_final, _ = documents_service.get_document(ui_doc_id, company_id)
check(ui_doc_final.status_code == "POSTED", f"the UI posts the negative-stock-allowed invoice in one click (got {ui_doc_final.status_code})")
check("سندِ انتقالِ انبار" not in screen.status_label.text(), f"no unnecessary transfer message is shown (got: {screen.status_label.text()!r})")

print("RESULT:", "FAIL" if FAIL else "ALL PASS")
os._exit(1 if FAIL else 0)
