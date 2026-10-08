import os, sys, datetime, decimal, io
os.environ["PEECHA_DB_NAME"] = "peecha_test_r237_1"
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
from peecha.services import commercial_pricing as pricing_service
from peecha.services import commercial_settings as csettings_service
from peecha.services import commercial_partners as partners_service
from peecha.services import inventory_engine as engine_service
from peecha.services import inventory_documents as inv_documents_service
from peecha.services import commercial_documents as documents_service
from peecha.services import detail_dimensions as dimensions_service

lang_id = company.default_language_id
A = lambda code, name, nature, typ, perm, post, parent=None: coa_service.create_account(company_id, code, name, nature, typ, perm, post, lang_id, parent_account_id=parent)
g1 = A("1", "دارایی‌ها", "DEBIT", "ASSET", "PERMANENT", False)
k1 = A("11", "موجودی نقد", "DEBIT", "ASSET", "PERMANENT", False, g1.account_id)
cash_gl = A("101", "صندوق", "DEBIT", "ASSET", "PERMANENT", True, k1.account_id)
k2 = A("13", "دریافتنی‌ها", "DEBIT", "ASSET", "PERMANENT", False, g1.account_id)
ar_gl = A("1304", "دریافتنی مشتریان", "DEBIT", "ASSET", "PERMANENT", True, k2.account_id)
k3 = A("12", "موجودی انبار", "DEBIT", "ASSET", "PERMANENT", False, g1.account_id)
inv_gl = A("121", "موجودی کالا", "DEBIT", "ASSET", "PERMANENT", True, k3.account_id)
g2 = A("4", "درآمدها", "CREDIT", "REVENUE", "TEMPORARY", False)
k4 = A("41", "درآمد عملیاتی", "CREDIT", "REVENUE", "TEMPORARY", False, g2.account_id)
rev_gl = A("411", "فروش", "CREDIT", "REVENUE", "TEMPORARY", True, k4.account_id)
discount_gl = A("412", "تخفیف فروش", "DEBIT", "REVENUE", "TEMPORARY", True, k4.account_id)
g4 = A("2", "بدهی‌ها", "CREDIT", "LIABILITY", "PERMANENT", False)
k7 = A("21", "بدهی مالیاتی", "CREDIT", "LIABILITY", "PERMANENT", False, g4.account_id)
tax_gl = A("2101", "مالیات ارزش‌افزودهٔ فروش", "CREDIT", "LIABILITY", "PERMANENT", True, k7.account_id)
g3 = A("5", "هزینه‌ها", "DEBIT", "EXPENSE", "TEMPORARY", False)
k5 = A("51", "بهای تمام‌شده", "DEBIT", "EXPENSE", "TEMPORARY", False, g3.account_id)
cogs_gl = A("511", "بهای تمام‌شده", "DEBIT", "EXPENSE", "TEMPORARY", True, k5.account_id)
k6 = A("59", "سایر", "DEBIT", "EXPENSE", "TEMPORARY", False, g3.account_id)
adj_gl = A("599", "اصلاح موجودی", "DEBIT", "EXPENSE", "TEMPORARY", True, k6.account_id)
engine_service.set_account_mapping(company_id, "INVENTORY_ASSET", inv_gl.account_id)
engine_service.set_account_mapping(company_id, "CUSTOMER_RECEIVABLE", ar_gl.account_id)
engine_service.set_account_mapping(company_id, "COGS", cogs_gl.account_id)
engine_service.set_account_mapping(company_id, "INVENTORY_ADJUSTMENT_GAIN", adj_gl.account_id)
csettings_service.set_account_mapping(company_id, "SALES_REVENUE", rev_gl.account_id)
csettings_service.set_account_mapping(company_id, "SALES_DISCOUNT", discount_gl.account_id)
csettings_service.set_account_mapping(company_id, "SALES_TAX_PAYABLE", tax_gl.account_id)


from peecha.services import commercial_settlements as settlements_service
from peecha.services import commercial_pos as pos_service
from peecha.services import treasury as treasury_service
from peecha.services import lot_tracking as lt
from peecha.services import operational_tasks as op_service
from peecha.services import inventory_residual as residual_service
from peecha.services import journal_entries as je_service
from peecha.db.models.accounting import JournalEntry, JournalEntryLine
from peecha.db.models.commercial import CommercialDocument
D = decimal.Decimal
TE = lt.TrackingEntry
today = datetime.date.today()
def raises(fn):
    try:
        fn()
    except ValueError:
        return True
    return False

k8 = A("32", "پرداختنی‌ها", "CREDIT", "LIABILITY", "PERMANENT", False, g4.account_id)
ap_gl = A("3201", "پرداختنی تامین‌کنندگان", "CREDIT", "LIABILITY", "PERMANENT", True, k8.account_id)
reval_gl = A("598", "تسعیر موجودی", "DEBIT", "EXPENSE", "TEMPORARY", True, k6.account_id)
engine_service.set_account_mapping(company_id, "SUPPLIER_PAYABLE", ap_gl.account_id)
engine_service.set_account_mapping(company_id, "INVENTORY_ADJUSTMENT_LOSS", adj_gl.account_id)
item_dim = dimensions_service.get_specialized_dimension_type_id(company_id, dimensions_service.INVENTORY_ITEM_CODE)
dimensions_service.set_account_dimension_types(inv_gl.account_id, company_id, [item_dim])

wh = locations_service.create_warehouse(company_id, "WH", "مرکزی", locations_service.WarehouseFields(is_default=True, allow_negative_stock=True))
customer = partners_service.create_customer(company_id, "C-1", "فروشگاه", fast_track=True)
s1 = dimensions_service.create_supplier(company_id, "S1", "تامین‌کنندهٔ یک")
pcs = catalog_service.create_uom(company_id, "PCS", "عدد", "COUNT", decimal_places=0)
plain = catalog_service.create_item(company_id, "N-1", "پارچه", catalog_service.ItemFields(item_kind_code="GOOD", base_uom_id=pcs))
csettings_service.set_feature_enabled(company_id, "PURCHASE_INVOICE_SKIP_APPROVAL", True)
HF = lambda cp: documents_service.DocumentHeaderFields(counterparty_detail_account_id=cp, currency_id=company.base_currency_id, warehouse_id=wh)

def doc_with_line(doc_type, item_id, qty, cp, price):
    doc = documents_service.create_document(company_id, user.user_id, doc_type, today, HF(cp))
    line = documents_service.add_line(doc, company_id, item_id, pcs, D(qty), D(qty), unit_price=D(price))
    return doc, line

def status(doc_id):
    return documents_service.get_document(doc_id, company_id)[0]


from peecha.db.models.commercial import CommercialDocument as CD
ret_gl = A("413", "برگشت از فروش", "DEBIT", "REVENUE", "TEMPORARY", True, k4.account_id)
def je(doc_id):
    out = {}
    with new_session() as s_:
        je_id = s_.get(CD, doc_id).journal_entry_id
        for l in s_.scalars(select(JournalEntryLine).where(JournalEntryLine.journal_entry_id == je_id)):
            out[l.account_id] = out.get(l.account_id, D(0)) + l.debit_amount_base - l.credit_amount_base
    return out
def doc(doc_type, cp, qty, price, discount=D(0), tax=D(0), source_line=None):
    d = documents_service.create_document(company_id, user.user_id, doc_type, today, HF(cp))
    ln = documents_service.add_line(d, company_id, plain, pcs, D(qty), D(qty), unit_price=D(price),
                                    discount_amount=discount, tax_percent=tax, source_line_id=source_line)
    documents_service.confirm_document(d, company_id, user.user_id)
    if doc_type.endswith("_INVOICE"):
        settlements_service.auto_approve_settlement_plan(d, company_id, user.user_id, [])
    documents_service.post_document(d, company_id, user.user_id)
    return d, ln
def stock_value():
    from peecha.db.models.inventory import StockBalance
    with new_session() as s_:
        return sum(s_.scalars(select(StockBalance.total_value).where(StockBalance.item_id == plain)), D(0))

doc("PURCHASE_INVOICE", s1, 10, 100)
doc("PURCHASE_INVOICE", s1, 10, 200)          # میانگین = ۱۵۰
inv, inv_line = doc("SALES_INVOICE", customer, 4, 400)   # بهایِ فروش = ۴×۱۵۰ = ۶۰۰
doc("PURCHASE_INVOICE", s1, 4, 300)           # میانگینِ تازه = (۱۶×۱۵۰+۱۲۰۰)/۲۰ = ۱۸۰

# ۱) برگشتِ بدونِ ارجاع، بدونِ حسابِ «برگشت از فروش» -> از درآمدِ فروش کم می‌شود؛ کالا با میانگینِ فعلی (۱۸۰)
before = stock_value()
r1, _ = doc("SALES_RETURN", customer, 2, 400)
j = je(r1)
check(j.get(ar_gl.account_id) == -800, f"مشتری با مبلغ برگشت (۲×۴۰۰=۸۰۰) بستانکار شد (got {j.get(ar_gl.account_id)})")
check(j.get(rev_gl.account_id) == 800, f"درآمد فروش ۸۰۰ بدهکار شد (got {j.get(rev_gl.account_id)})")
check(j.get(inv_gl.account_id) == 360 and j.get(cogs_gl.account_id) == -360, f"موجودی/بهای تمام‌شده با بها (۲×۱۸۰=۳۶۰) (got {j})")
check(stock_value() - before == 360, f"ارزش انبار با بها بالا رفت، نه با فی فروش (got {stock_value() - before})")
check(sum(j.values()) == 0, "سند تراز است")

# ۲) با حسابِ «برگشت از فروش» + ارجاع به فاکتور -> بهایِ همان فروش (۱۵۰)، با تخفیف و مالیات
engine_service.set_account_mapping(company_id, "SALES_RETURNS", ret_gl.account_id)
engine_service.set_account_mapping(company_id, "SALES_TAX_PAYABLE", tax_gl.account_id)
r2, _ = doc("SALES_RETURN", customer, 2, 400, discount=D(100), tax=D(10), source_line=inv_line)
j = je(r2)
check(j.get(ret_gl.account_id) == 700, f"برگشت از فروش با مبلغ خالص از تخفیف (۸۰۰−۱۰۰=۷۰۰) (got {j.get(ret_gl.account_id)})")
check(j.get(tax_gl.account_id) == 70 and j.get(ar_gl.account_id) == -770, f"مالیات ۷۰ و مشتری ۷۷۰ (got {j})")
check(j.get(inv_gl.account_id) == 300 and j.get(cogs_gl.account_id) == -300, f"بهای همان فروش (۲×۱۵۰=۳۰۰) (got {j})")
check(j.get(rev_gl.account_id, D(0)) == 0 and sum(j.values()) == 0, "درآمد فروش دست نخورد و سند تراز است")

# ۳) گزارشِ سودِ ناخالص با بهایِ درست
from peecha.services import purchase_reports as pr
gp = pr.run_report(company_id, "GP_ITEM", pr.PurchaseFilters(today, today, side="SALES")).rows[0]
check(gp[3] == 1600 - 800 - 700 and gp[4] == 600 - 360 - 300, f"سود ناخالص: فروش خالص ۱۰۰، بها −۶۰ (got {gp[3:6]})")

print("RESULT:", "ALL PASS" if not FAIL else "SOME FAILED")
sys.exit(1 if FAIL else 0)
