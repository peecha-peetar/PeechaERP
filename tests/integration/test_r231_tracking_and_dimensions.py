import os, sys, datetime, decimal, io
os.environ["PEECHA_DB_NAME"] = "peecha_test_r231_1"
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

from peecha.services import unit_conversion as uc
var_gl = A("597", "مغایرت بهای استاندارد", "DEBIT", "EXPENSE", "TEMPORARY", True, k6.account_id)
engine_service.set_account_mapping(company_id, "INVENTORY_COST_VARIANCE", var_gl.account_id)
cc_dim = dimensions_service.get_specialized_dimension_type_id(company_id, dimensions_service.COST_CENTER_CODE)
pj_dim = dimensions_service.get_specialized_dimension_type_id(company_id, dimensions_service.PROJECT_CODE)
cc = dimensions_service.create_detail_account(company_id, cc_dim, "CC-1", "مرکز هزینهٔ انبار")
pj = dimensions_service.create_detail_account(company_id, pj_dim, "PJ-1", "پروژهٔ عمومی")
cc = getattr(cc, "detail_account_id", cc); pj = getattr(pj, "detail_account_id", pj)

def post_doc(doc_type, item_id, qty, cp, price):
    d, line = doc_with_line(doc_type, item_id, qty, cp, price)
    documents_service.confirm_document(d, company_id, user.user_id)
    if doc_type in ("SALES_INVOICE", "PURCHASE_INVOICE"):
        settlements_service.auto_approve_settlement_plan(d, company_id, user.user_id, [])
    documents_service.post_document(d, company_id, user.user_id)
    return d, line

def je_lines(je_id):
    with new_session() as s:
        return list(s.scalars(select(JournalEntryLine).where(JournalEntryLine.journal_entry_id == je_id)))

# ===== ۵: اصلاحِ فاکتورِ خرید با «کالا» الزامی رویِ مغایرتِ بها =====
dimensions_service.set_account_dimension_types(var_gl.account_id, company_id, [item_dim])
csettings_service.set_feature_enabled(company_id, "ALLOW_EDIT_POSTED_INVOICE", True)
pi, _ = post_doc("PURCHASE_INVOICE", plain, 10, s1, 1000)
post_doc("SALES_INVOICE", plain, 4, customer, 3000)
corr = documents_service.start_invoice_correction(pi, company_id, user.user_id)
corr_line = documents_service.get_document(corr, company_id)[1][0]
documents_service.update_line(corr_line.line_id, corr, company_id, D(10), D(1200))
documents_service.confirm_document(corr, company_id, user.user_id)
try:
    res = documents_service.post_invoice_correction(corr, company_id, user.user_id)
    err = None
except ValueError as exc:
    res, err = None, str(exc)
check(err is None, f"اصلاح فاکتور ثبت‌شده با «کالا» الزامی روی مغایرت ثبت شد (err={err})")
if res is not None:
    from peecha.db.models.accounting import JournalEntryLineDetail
    lines_ = je_lines(res.journal_entry_id)
    var_amount = sum(l.debit_amount_base - l.credit_amount_base for l in lines_ if l.account_id == var_gl.account_id)
    inv_amount = sum(l.debit_amount_base - l.credit_amount_base for l in lines_ if l.account_id == inv_gl.account_id)
    check(var_amount == 800 and inv_amount == 1200, f"۶ عدد مانده ۱۲۰۰ به موجودی، ۴ عدد فروخته ۸۰۰ به مغایرت (got inv={inv_amount}, var={var_amount})")
    with new_session() as s:
        ap_line = next(l for l in lines_ if l.account_id == ap_gl.account_id)
        ap_details = {d.detail_account_id for d in s.scalars(select(JournalEntryLineDetail).where(JournalEntryLineDetail.line_id == ap_line.line_id))}
    check(s1 in ap_details, "ردیف پرداختنی اصلاحیه به حساب همان تامین‌کننده نشست")

# ===== ۱: سندِ تسعیر وقتی حسابِ مقابل مرکزِ هزینه و پروژه می‌خواهد =====
dimensions_service.set_account_dimension_types(reval_gl.account_id, company_id, [cc_dim, pj_dim])
engine_service.set_account_mapping(company_id, "INVENTORY_REVALUATION", reval_gl.account_id)
zero_item = catalog_service.create_item(company_id, "Z-1", "کالای صفر", catalog_service.ItemFields(item_kind_code="GOOD", base_uom_id=pcs))
z_detail = next(i.item_detail_account_id for i in catalog_service.list_items(company_id) if i.item_id == zero_item)
je_service.create_journal_entry(company_id, user.user_id, today, "انحراف آزمایشی", [
    je_service.LineInput(account_id=inv_gl.account_id, description="x", debit=D(300), credit=D(0), details={item_dim: z_detail}),
    je_service.LineInput(account_id=adj_gl.account_id, description="x", debit=D(0), credit=D(300), details={}),
])
dims = {d.dimension_type_id for d in residual_service.required_extra_dimensions(company_id)}
check(dims == {cc_dim, pj_dim}, f"فرم تسعیر مرکز هزینه و پروژه را می‌خواهد (got {dims})")
from peecha.ui.screens.inventory_residual import InventoryResidualScreen
scr = InventoryResidualScreen(); scr.refresh()
check(set(scr._dim_combos) == {cc_dim, pj_dim}, "انتخابگر مرکز هزینه/پروژه در فرم تسعیر")
scr._dim_combos[cc_dim].setCurrentIndex(scr._dim_combos[cc_dim].findData(cc))
scr._dim_combos[pj_dim].setCurrentIndex(scr._dim_combos[pj_dim].findData(pj))
scr.table.selectAll(); scr._post_selected()
check(not [r for r in residual_service.list_residuals(company_id) if r.item_id == zero_item], "سند تسعیر با مرکز هزینه/پروژه صادر شد")

# ===== ۲/۳: سفارشِ خرید بدونِ سریال -> ثبتِ نهایی -> ورودِ سریال توسطِ انباردار =====
csettings_service.set_feature_enabled(company_id, "PURCHASE_ORDER_GOODS_RECEIPT", True)
csettings_service.set_feature_enabled(company_id, "PURCHASE_ORDER_SKIP_APPROVAL", True)
phone = catalog_service.create_item(company_id, "PH-1", "گوشی", catalog_service.ItemFields(item_kind_code="GOOD", base_uom_id=pcs, track_serial=True))
po, po_line = post_doc("PURCHASE_ORDER", phone, 2, s1, 5000)
check(status(po).status_code == "POSTED", "سفارش بدون سریال ثبت نهایی شد")
check(raises(lambda: documents_service.approve_warehouse(po, company_id, user.user_id, warehouse_id=wh)), "رسید بدون سریال هنوز ممکن نیست")
lt.set_line_tracking(company_id, [TE(D(1), serial_no="IMEI-1"), TE(D(1), serial_no="IMEI-2")], commercial_line_id=po_line)
check(len(lt.get_line_tracking(commercial_line_id=po_line)) == 2, "انباردار پس از ثبت نهایی سفارش سریال را وارد کرد")
documents_service.approve_warehouse(po, company_id, user.user_id, warehouse_id=wh)
check(status(po).warehouse_approved_at is not None, "تایید رسید با سریال‌ها انجام شد")
check(raises(lambda: lt.set_line_tracking(company_id, [TE(D(2), serial_no="X")], commercial_line_id=po_line)),
      "پس از تایید رسید، سریال قفل است")
from peecha.ui.screens.purchase_goods_receipt import PurchaseGoodsReceiptScreen

# ===== ۴: Enter رویِ مقدار -> واحد -> قیمت؛ سفارش بدونِ پنجرهٔ اجباریِ سریال =====
from peecha.ui.shell_window import MainWindow
mw = MainWindow(); mw.resize(1300, 850); mw.show(); app.processEvents()
box = catalog_service.create_uom(company_id, "BOX", "جعبه", "COUNT", decimal_places=0)
uc.set_item_unit(plain, box, D(12))
po_screen = mw._screens["commercial_document_purchase_order"]
rows_ = {i.item_id: i for i in catalog_service.list_items(company_id)}
check(not po_screen._entry_row_needs_tracking(rows_[phone]), "در سفارش، ورود سریال/بچ هنگام ثبت ردیف اجباری نیست")
inv_screen = mw._screens["commercial_document_purchase_invoice"]
check(inv_screen._entry_row_needs_tracking(rows_[phone]), "در فاکتور همچنان پنجرهٔ سریال باز می‌شود")
mw.open_screen("PURCH_INVOICE"); app.processEvents()
inv_screen.refresh(); app.processEvents()
w = getattr(inv_screen, "_entry_row_widgets", None)
if w is None and hasattr(inv_screen, "_new_document"):
    inv_screen._new_document(); app.processEvents(); w = getattr(inv_screen, "_entry_row_widgets", None)
check(w is not None, "ردیف ورود فاکتور موجود است")
if w is not None:
    combo = w["item_combo"]
    combo.setCurrentIndex(combo.findData(plain)); app.processEvents()
    w = inv_screen._entry_row_widgets
    w["qty"].setValue(3)
    w["qty"].setFocus(); app.processEvents()
    inv_screen._on_entry_qty_enter(); app.processEvents()
    check(w["uom"].hasFocus() or w["uom"].view().isVisible(), "Enter روی مقدار به انتخاب واحد می‌رود")
    w["uom"].hidePopup()
    w["uom"].enterPressed.emit(); app.processEvents()
    check(w["price"].hasFocus(), "Enter روی واحد به قیمت می‌رود")

print("RESULT:", "ALL PASS" if not FAIL else "SOME FAILED")
sys.exit(1 if FAIL else 0)
