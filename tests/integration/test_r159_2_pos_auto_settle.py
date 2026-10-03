import os, sys, datetime, decimal
os.environ["PEECHA_DB_NAME"] = "peecha_test_r159_2"
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
from peecha.services import treasury as treasury_service

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
g4 = coa_service.create_account(company_id, "2", "بدهی‌ها", "CREDIT", "LIABILITY", "PERMANENT", False, lang_id)
k6 = coa_service.create_account(company_id, "21", "سایرِ بدهی‌ها", "CREDIT", "LIABILITY", "PERMANENT", False, lang_id, parent_account_id=g4.account_id)
ap_gl = coa_service.create_account(company_id, "211", "پرداختنیِ تامین‌کنندگان", "CREDIT", "LIABILITY", "PERMANENT", True, lang_id, parent_account_id=k6.account_id)

engine_service.set_account_mapping(company_id, "INVENTORY_ASSET", inv_asset_gl.account_id)
engine_service.set_account_mapping(company_id, "CUSTOMER_RECEIVABLE", ar_gl.account_id)
engine_service.set_account_mapping(company_id, "SUPPLIER_PAYABLE", ap_gl.account_id)
engine_service.set_account_mapping(company_id, "COGS", cogs_gl.account_id)
csettings_service.set_account_mapping(company_id, "SALES_REVENUE", revenue_gl.account_id)

customer_group_id = next(g.person_group_id for g in dimensions_service.list_person_groups(company_id) if g.code == "CUSTOMER")
treasury_service.create_counterparty_mapping(company_id, "RECEIPT", cash_gl.account_id, person_group_id=customer_group_id)
treasury_service.set_account_mapping(company_id, "RECEIPT_CASH", cash_gl.account_id)

uom_id = catalog_service.create_uom(company_id, "PCS", "عدد", "COUNT")
warehouse_id = locations_service.create_warehouse(company_id, "WH1", "انبارِ اصلی", locations_service.WarehouseFields())
customer_id = dimensions_service.create_customer(company_id, "1", "مشتریِ آزمایشی")
supplier_id = dimensions_service.create_supplier(company_id, "9", "تامین‌کننده")

item_id = catalog_service.create_item(
    company_id, "3001", "کالایِ آزمایشی", catalog_service.ItemFields(item_kind_code="GOOD", base_uom_id=uom_id, is_sellable=True),
)
receipt_id = inv_documents_service.create_stock_document(
    company_id, user.user_id, "RECEIPT", datetime.date.today(),
    inv_documents_service.DocumentHeaderFields(destination_warehouse_id=warehouse_id, counterparty_detail_account_id=supplier_id),
)
inv_documents_service.add_line(receipt_id, company_id, inv_documents_service.LineFields(
    item_id=item_id, uom_id=uom_id, quantity=decimal.Decimal(100), quantity_base=decimal.Decimal(100), unit_cost=decimal.Decimal(1000),
))
inv_documents_service.confirm_stock_document(receipt_id, company_id)
inv_documents_service.post_stock_document(receipt_id, company_id, user.user_id)

terminal_id = pos_service.create_terminal(company_id, warehouse_id, "T1", "صندوقِ اصلی")
session_id = pos_service.open_session(terminal_id, user.user_id, decimal.Decimal(500000))

from peecha.ui.screens.commercial_pos_sale import CommercialPosSaleScreen
from peecha.ui.screens.commercial_pos_approval import CommercialPosApprovalScreen

# =========================================================================
# ۱: فروشِ حضوریِ «نقدی» -- صندوق‌دار دقیقاً دکمهٔ نقدی را می‌زند.
# =========================================================================
sale_screen = CommercialPosSaleScreen()
host1 = QWidget(); QVBoxLayout(host1).addWidget(sale_screen); host1.show()
sale_screen.refresh()
app.processEvents()
sale_screen.terminal_combo.setCurrentIndex(sale_screen.terminal_combo.findData(terminal_id))
sale_screen.customer_combo.setCurrentIndex(sale_screen.customer_combo.findData(customer_id))
app.processEvents()
item_row = next(it for it in sale_screen._items if it.item_id == item_id)
sale_screen._add_item_to_cart(item_row, decimal.Decimal(1), decimal.Decimal(1000))
app.processEvents()
sale_screen._confirm_sale("CASH", print_receipt=False)
app.processEvents()
cash_doc_id = sale_screen._document_id if sale_screen._document_id else None

# سندِ تاییدشدهٔ همین فروش را از فهرستِ اسنادِ شرکت پیدا می‌کنیم (چون
# بعدِ تاییدِ اولیه، فرم پاک/ریست می‌شود).
cash_docs_confirmed = [
    d for d in documents_service.list_documents(company_id, "SALES_INVOICE", "CONFIRMED")
    if d.pos_session_id == session_id and d.pos_intended_payment_type == "CASH"
]
check(len(cash_docs_confirmed) == 1, f"exactly one CASH-confirmed invoice exists (got {len(cash_docs_confirmed)})")
cash_doc = cash_docs_confirmed[0]

# =========================================================================
# ۲: فروشِ حضوریِ «نسیه» -- صندوق‌دار دکمهٔ نسیه را می‌زند.
# =========================================================================
sale_screen._add_item_to_cart(item_row, decimal.Decimal(1), decimal.Decimal(1000))
app.processEvents()
sale_screen._confirm_sale("CREDIT", print_receipt=False)
app.processEvents()

credit_docs_confirmed = [
    d for d in documents_service.list_documents(company_id, "SALES_INVOICE", "CONFIRMED")
    if d.pos_session_id == session_id and d.pos_intended_payment_type == "CREDIT"
]
check(len(credit_docs_confirmed) == 1, f"exactly one CREDIT-confirmed invoice exists (got {len(credit_docs_confirmed)})")
credit_doc = credit_docs_confirmed[0]

# =========================================================================
# ۳: صفحهٔ تاییدِ سرپرست -- دیگر هیچ کمبویِ «روشِ پرداخت» ندارد.
# =========================================================================
screen = CommercialPosApprovalScreen()
host2 = QWidget(); QVBoxLayout(host2).addWidget(screen); host2.show()
screen.refresh()
app.processEvents()
check(not hasattr(screen, "method_combo"), "the global payment-method combo no longer exists on the approval screen")

cash_row = next(i for i, d in enumerate(screen._documents) if d.document_id == cash_doc.document_id)
credit_row = next(i for i, d in enumerate(screen._documents) if d.document_id == credit_doc.document_id)
screen._row_checkbox(cash_row).setChecked(True)
screen._row_checkbox(credit_row).setChecked(True)
screen._approve_selected()
app.processEvents()
print('STATUS LABEL:', repr(screen.status_label.text()))

# =========================================================================
# ۴: بدونِ هیچ انتخابِ دستی‌ای، فاکتورِ نقدی باید واقعاً تسویه‌شده باشد
#    (نه نسیه) -- دقیقاً رفعِ باگِ گزارش‌شده -- و فاکتورِ نسیه هنوز
#    مانده‌یِ کاملِ خودش را (بدونِ هیچ تسویه‌ای) داشته باشد.
# =========================================================================
from peecha.services import commercial_settlements as settlements_service

cash_doc_final, _ = documents_service.get_document(cash_doc.document_id, company_id)
check(cash_doc_final.status_code == "POSTED", f"the CASH invoice reaches POSTED (got {cash_doc_final.status_code})")
cash_settlements = settlements_service.list_settlements_for_invoice(cash_doc.document_id, company_id)
check(len(cash_settlements) >= 1, f"the CASH invoice actually got a settlement recorded (got {len(cash_settlements)} rows) -- this is the reported bug")
cash_settled_total = sum((s.amount for s in cash_settlements), decimal.Decimal("0"))
check(cash_settled_total == cash_doc_final.total_amount, f"the CASH invoice is settled in full (settled {cash_settled_total}, total {cash_doc_final.total_amount})")

credit_doc_final, _ = documents_service.get_document(credit_doc.document_id, company_id)
check(credit_doc_final.status_code == "POSTED", f"the CREDIT invoice also reaches POSTED (got {credit_doc_final.status_code})")
credit_settlements = settlements_service.list_settlements_for_invoice(credit_doc.document_id, company_id)
check(len(credit_settlements) == 0, f"the CREDIT invoice correctly received no settlement at all (got {len(credit_settlements)} rows)")

print("RESULT:", "FAIL" if FAIL else "ALL PASS")
os._exit(1 if FAIL else 0)
