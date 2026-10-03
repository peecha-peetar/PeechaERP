import os, sys, datetime, decimal, io
os.environ["PEECHA_DB_NAME"] = "peecha_test_r232_1"
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
k1 = A("11", "موجودیِ نقد", "DEBIT", "ASSET", "PERMANENT", False, g1.account_id)
cash_gl = A("101", "صندوق", "DEBIT", "ASSET", "PERMANENT", True, k1.account_id)
k2 = A("13", "دریافتنی‌ها", "DEBIT", "ASSET", "PERMANENT", False, g1.account_id)
ar_gl = A("1304", "دریافتنیِ مشتریان", "DEBIT", "ASSET", "PERMANENT", True, k2.account_id)
k3 = A("12", "موجودیِ انبار", "DEBIT", "ASSET", "PERMANENT", False, g1.account_id)
inv_gl = A("121", "موجودیِ کالا", "DEBIT", "ASSET", "PERMANENT", True, k3.account_id)
g2 = A("4", "درآمدها", "CREDIT", "REVENUE", "TEMPORARY", False)
k4 = A("41", "درآمدِ عملیاتی", "CREDIT", "REVENUE", "TEMPORARY", False, g2.account_id)
rev_gl = A("411", "فروش", "CREDIT", "REVENUE", "TEMPORARY", True, k4.account_id)
discount_gl = A("412", "تخفیفِ فروش", "DEBIT", "REVENUE", "TEMPORARY", True, k4.account_id)
g4 = A("2", "بدهی‌ها", "CREDIT", "LIABILITY", "PERMANENT", False)
k7 = A("21", "بدهیِ مالياتی", "CREDIT", "LIABILITY", "PERMANENT", False, g4.account_id)
tax_gl = A("2101", "مالياتِ ارزش‌افزودهٔ فروش", "CREDIT", "LIABILITY", "PERMANENT", True, k7.account_id)
g3 = A("5", "هزینه‌ها", "DEBIT", "EXPENSE", "TEMPORARY", False)
k5 = A("51", "بهایِ تمام‌شده", "DEBIT", "EXPENSE", "TEMPORARY", False, g3.account_id)
cogs_gl = A("511", "بهایِ تمام‌شده", "DEBIT", "EXPENSE", "TEMPORARY", True, k5.account_id)
k6 = A("59", "سایر", "DEBIT", "EXPENSE", "TEMPORARY", False, g3.account_id)
adj_gl = A("599", "اصلاحِ موجودی", "DEBIT", "EXPENSE", "TEMPORARY", True, k6.account_id)
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
ap_gl = A("3201", "پرداختنیِ تامین‌کنندگان", "CREDIT", "LIABILITY", "PERMANENT", True, k8.account_id)
reval_gl = A("598", "تسعیرِ موجودی", "DEBIT", "EXPENSE", "TEMPORARY", True, k6.account_id)
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


def post_doc(doc_type, item_id, qty, cp, price, entries=None, approve=False):
    d, line = doc_with_line(doc_type, item_id, qty, cp, price)
    if entries:
        lt.set_line_tracking(company_id, entries, commercial_line_id=line)
    documents_service.confirm_document(d, company_id, user.user_id)
    if approve:
        documents_service.approve_document(d, company_id)
    if doc_type in ("SALES_INVOICE", "PURCHASE_INVOICE"):
        settlements_service.auto_approve_settlement_plan(d, company_id, user.user_id, [])
    documents_service.post_document(d, company_id, user.user_id)
    return d, line

phone = catalog_service.create_item(company_id, "PH-1", "گوشی", catalog_service.ItemFields(item_kind_code="GOOD", base_uom_id=pcs, track_serial=True))
post_doc("PURCHASE_INVOICE", phone, 3, s1, 5000, [TE(D(1), serial_no=f"SN-{i}") for i in range(1, 4)])
post_doc("PURCHASE_INVOICE", plain, 20, s1, 1000)

# ===== ۱: حوالهٔ انبارِ سفارشِ فروش (هم‌تراز با رسیدِ سفارشِ خرید) =====
csettings_service.set_feature_enabled(company_id, "SALES_ORDER_WAREHOUSE_ISSUE", True)
so, so_line = doc_with_line("SALES_ORDER", phone, 2, customer, 9000)
documents_service.confirm_document(so, company_id, user.user_id)
queue = lambda: [d.document_id for d in documents_service.list_purchase_order_goods_receipt_queue(company_id)]
check(so not in queue(), "سفارشِ فروشِ فقط تاییدشده هنوز به حوالهٔ انبار نمی‌رسد")
check(("POST_ORDER", so) in {(t.kind, t.document_id) for t in op_service.list_operational_tasks(company_id, user.user_id)},
      "کارتابل: «ثبتِ نهاییِ سفارش» برایِ سفارشِ فروش")
check(raises(lambda: documents_service.approve_warehouse(so, company_id, user.user_id, warehouse_id=wh)), "حوالهٔ سفارشِ ثبتِ‌نهایی‌نشده رد می‌شود")
documents_service.post_document(so, company_id, user.user_id)
check(so in queue(), "سفارشِ فروشِ ثبتِ نهایی‌شده در صفِ تاییدِ انبار")
check(("GOODS_RECEIPT", so) in {(t.kind, t.document_id) for t in op_service.list_operational_tasks(company_id, user.user_id)},
      "کارتابل: تاییدِ حوالهٔ انبار")
check(raises(lambda: documents_service.convert_to_invoice(so, company_id, user.user_id, today)), "پیش از حوالهٔ انبار تبدیل به فاکتور ممکن نیست")
check(raises(lambda: documents_service.approve_warehouse(so, company_id, user.user_id, warehouse_id=wh)), "حواله بدونِ انتخابِ سریال رد می‌شود")
lt.set_line_tracking(company_id, [TE(D(1), serial_no="SN-3"), TE(D(1), serial_no="SN-1")], commercial_line_id=so_line)
documents_service.approve_warehouse(so, company_id, user.user_id, warehouse_id=wh)
check(status(so).warehouse_approved_at is not None, "انباردار حواله را با سریال‌هایِ انتخابی تایید کرد")
check(("CONVERT_TO_INVOICE", so) in {(t.kind, t.document_id) for t in op_service.list_operational_tasks(company_id, user.user_id)},
      "کارتابل: تبدیلِ سفارشِ فروشِ حواله‌شده به فاکتور")
inv = documents_service.convert_to_invoice(so, company_id, user.user_id, today)
check(documents_service.get_quantity_locked_line_ids(inv, company_id), "مقدارِ فاکتور پس از حوالهٔ انبار قفل است")
documents_service.confirm_document(inv, company_id, user.user_id)
settlements_service.auto_approve_settlement_plan(inv, company_id, user.user_id, [])
documents_service.post_document(inv, company_id, user.user_id)
left = sorted(r.serial_no for r in lt.list_lot_balances(company_id, item_id=phone))
check(left == ["SN-2"], f"دقیقاً سریال‌هایِ انتخابیِ انباردار فروخته شد (got {left})")

csettings_service.set_feature_enabled(company_id, "SALES_ORDER_SKIP_POST", True)
so2, _ = doc_with_line("SALES_ORDER", plain, 2, customer, 3000)
documents_service.confirm_document(so2, company_id, user.user_id)
check(so2 in queue(), "با حذفِ «ثبتِ نهایی پیش از حواله»، سفارشِ تاییدشده مستقیم به انبار می‌رسد")
csettings_service.set_feature_enabled(company_id, "SALES_ORDER_SKIP_POST", False)
csettings_service.set_feature_enabled(company_id, "SALES_ORDER_WAREHOUSE_ISSUE", False)
check(so2 not in queue(), "با خاموش‌بودنِ تنظیم، رفتارِ قبلیِ فروش بدونِ تغییر است")
documents_service.convert_to_invoice(so2, company_id, user.user_id, today)

# ===== ۲: تصویبِ مدیر برایِ فاکتور/سفارشِ فروش (اختیاری) =====
csettings_service.set_feature_enabled(company_id, "SALES_INVOICE_MANAGER_APPROVAL", True)
csettings_service.set_feature_enabled(company_id, "SALES_ORDER_MANAGER_APPROVAL", True)
si, _ = doc_with_line("SALES_INVOICE", plain, 1, customer, 3000)
documents_service.confirm_document(si, company_id, user.user_id)
settlements_service.auto_approve_settlement_plan(si, company_id, user.user_id, [])
check(raises(lambda: documents_service.post_document(si, company_id, user.user_id)), "فاکتورِ فروش بدونِ تصویبِ مدیر ثبتِ نهایی نمی‌شود")
check(("MANAGER_APPROVAL", si) in {(t.kind, t.document_id) for t in op_service.list_operational_tasks(company_id, user.user_id)},
      "کارتابل: تصویبِ مدیرِ فاکتورِ فروش")
documents_service.approve_document(si, company_id)
documents_service.post_document(si, company_id, user.user_id)
check(status(si).status_code == "POSTED", "پس از تصویب، فاکتورِ فروش ثبت شد")
so3, _ = doc_with_line("SALES_ORDER", plain, 1, customer, 3000)
documents_service.confirm_document(so3, company_id, user.user_id)
check(raises(lambda: documents_service.post_document(so3, company_id, user.user_id)), "سفارشِ فروش بدونِ تصویبِ مدیر ثبتِ نهایی نمی‌شود")
mobile, _ = doc_with_line("SALES_INVOICE", plain, 1, customer, 3000)
documents_service.confirm_document(mobile, company_id, user.user_id)
settlements_service.auto_approve_settlement_plan(mobile, company_id, user.user_id, [])
documents_service.post_document(mobile, company_id, user.user_id, from_field_sales=True)
check(status(mobile).status_code == "POSTED", "فروشِ موبایل (کالا تحویل‌شده) به‌خاطرِ تصویب رد نمی‌شود")

# ===== ۳: UI =====
from peecha.ui.shell_window import MainWindow
mw = MainWindow(); mw.resize(1300, 850); mw.show(); app.processEvents()
si_screen = mw._screens["commercial_document_sales_invoice"]
si2, _ = doc_with_line("SALES_INVOICE", plain, 1, customer, 3000)
documents_service.confirm_document(si2, company_id, user.user_id)
settlements_service.auto_approve_settlement_plan(si2, company_id, user.user_id, [])
si_screen.refresh(); si_screen.edit_document(si2); app.processEvents()
check(si_screen.approve_button.isVisibleTo(si_screen) and si_screen.approve_button.isEnabled(), "دکمهٔ تصویب در فاکتورِ فروش")
check(not si_screen.post_button.isEnabled(), "ثبتِ نهاییِ فاکتورِ فروش تا تصویب غیرفعال است")
csettings_service.set_feature_enabled(company_id, "SALES_INVOICE_MANAGER_APPROVAL", False)
si_screen.refresh(); si_screen.edit_document(si2); app.processEvents()
check(not si_screen.approve_button.isVisibleTo(si_screen) and si_screen.post_button.isEnabled(), "بدونِ تنظیم، فاکتورِ فروش مثلِ قبل")

csettings_service.set_feature_enabled(company_id, "SALES_ORDER_WAREHOUSE_ISSUE", True)
so4, so4_line = doc_with_line("SALES_ORDER", plain, 3, customer, 3000)
documents_service.confirm_document(so4, company_id, user.user_id)
documents_service.approve_document(so4, company_id)
documents_service.post_document(so4, company_id, user.user_id)
from peecha.ui.screens.purchase_goods_receipt import PurchaseGoodsReceiptScreen, _GoodsReceiptDialog, _status_label
rec = mw._screens["purchase_goods_receipt"]; rec.refresh()
check(any(d.document_id == so4 for d in rec._queue), "سفارشِ فروش در فرمِ تاییدِ انبار")
dlg = _GoodsReceiptDialog(rec, so4, company_id)
check("حوالهٔ انبار" in dlg.receipt_button.text(), f"دکمهٔ «تاییدِ حوالهٔ انبار» (got {dlg.receipt_button.text()})")
dlg._qty_fields[so4_line].setValue(2); dlg._save_quantities()
dlg._toggle_receipt()
check(status(so4).warehouse_approved_at is not None, "حواله از فرم تایید شد")
inv4 = documents_service.convert_to_invoice(so4, company_id, user.user_id, today)
check(documents_service.get_document(inv4, company_id)[1][0].quantity == 2, "فاکتور با مقدارِ تحویلیِ انباردار (۲) ساخته شد")
lst = mw._screens["commercial_documents_list_sales"]
so5, _ = doc_with_line("SALES_ORDER", plain, 1, customer, 3000)
documents_service.confirm_document(so5, company_id, user.user_id)
documents_service.approve_document(so5, company_id)
documents_service.post_document(so5, company_id, user.user_id)
row = next(d for d in documents_service.list_documents(company_id, document_type_code="SALES_ORDER") if d.document_id == so5)
step = lst._next_step(row, lst._fulfillment_summary(row, company_id), None)
check(step is not None and step[0] == "حوالهٔ انبار", f"فهرستِ اسنادِ فروش: مرحلهٔ بعد «حوالهٔ انبار» (got {step and step[0]})")
mw.open_screen("SALES_WAREHOUSE_ISSUE"); app.processEvents()
check(any(sw.isVisible() and sw.widget() is not None for sw in mw.mdi_area.subWindowList()), "منویِ فروش ‹ تاییدِ حوالهٔ انبار باز می‌شود")

print("RESULT:", "ALL PASS" if not FAIL else "SOME FAILED")
sys.exit(1 if FAIL else 0)
