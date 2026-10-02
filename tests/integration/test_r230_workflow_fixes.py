import os, sys, datetime, decimal, io
os.environ["PEECHA_DB_NAME"] = "peecha_test_r230_1"
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

# ===== ۵/۶: رسیدِ انبار فقط برایِ سفارشِ ثبتِ نهایی‌شده =====
csettings_service.set_feature_enabled(company_id, "PURCHASE_ORDER_GOODS_RECEIPT", True)
csettings_service.set_feature_enabled(company_id, "PURCHASE_ORDER_SKIP_APPROVAL", True)
po, _ = doc_with_line("PURCHASE_ORDER", plain, 5, s1, 1000)
documents_service.confirm_document(po, company_id, user.user_id)
queue = [d.document_id for d in documents_service.list_purchase_order_goods_receipt_queue(company_id)]
check(po not in queue, "سفارشِ فقط تاییدشده در صفِ تاییدِ انبار نیست")
check(raises(lambda: documents_service.approve_warehouse(po, company_id, user.user_id, warehouse_id=wh)), "رسیدِ سفارشِ ثبتِ‌نهایی‌نشده رد می‌شود")
kinds = {(t.kind, t.document_id) for t in op_service.list_operational_tasks(company_id, user.user_id)}
check(("POST_ORDER", po) in kinds, "کارتابل: «ثبتِ نهاییِ سفارش» به مدیر پیشنهاد می‌شود")
documents_service.post_document(po, company_id, user.user_id)
queue = [d.document_id for d in documents_service.list_purchase_order_goods_receipt_queue(company_id)]
check(po in queue, "سفارشِ ثبتِ نهایی‌شده در صفِ تاییدِ انبار دیده می‌شود")
documents_service.approve_warehouse(po, company_id, user.user_id, warehouse_id=wh)
check(status(po).warehouse_approved_at is not None, "رسیدِ سفارشِ ثبتِ نهایی‌شده انجام شد")

csettings_service.set_feature_enabled(company_id, "PURCHASE_ORDER_SKIP_POST", True)
po2, _ = doc_with_line("PURCHASE_ORDER", plain, 1, s1, 1000)
documents_service.confirm_document(po2, company_id, user.user_id)
check(po2 in [d.document_id for d in documents_service.list_purchase_order_goods_receipt_queue(company_id)],
      "با حذفِ مرحلهٔ «ثبتِ نهایی پیش از رسید»، سفارشِ تاییدشده مستقیم به انبار می‌رسد")
csettings_service.set_feature_enabled(company_id, "PURCHASE_ORDER_SKIP_POST", False)
csettings_service.set_feature_enabled(company_id, "PURCHASE_ORDER_GOODS_RECEIPT", False)

# ===== ۸: امانیِ ورودی/خروجی با تاییدِ انباردار =====
csettings_service.set_feature_enabled(company_id, "CONSIGNMENT_WAREHOUSE_APPROVAL", True)
cons_item = catalog_service.create_item(company_id, "K-1", "کالایِ امانی", catalog_service.ItemFields(item_kind_code="GOOD", base_uom_id=pcs))
cin, cin_line = doc_with_line("CONSIGNMENT_IN", cons_item, 10, s1, 0)
documents_service.confirm_document(cin, company_id, user.user_id)
check(raises(lambda: documents_service.post_document(cin, company_id, user.user_id)), "امانیِ ورودی پیش از تاییدِ انباردار ثبت نمی‌شود")
check(cin in [d.document_id for d in documents_service.list_purchase_order_goods_receipt_queue(company_id)], "امانیِ ورودی در صفِ تاییدِ انبار")
documents_service.approve_warehouse(cin, company_id, user.user_id, warehouse_id=wh)
documents_service.post_document(cin, company_id, user.user_id)
check(status(cin).status_code == "POSTED", "پس از تاییدِ انباردار، امانی ثبت شد")
csettings_service.set_feature_enabled(company_id, "CONSIGNMENT_WAREHOUSE_APPROVAL", False)

# ===== ۷: ثبتِ خودکارِ سندِ دریافت بعد از ثبتِ فاکتور =====
customer_group_id = next(g.person_group_id for g in dimensions_service.list_person_groups(company_id) if g.code == "CUSTOMER")
treasury_service.create_counterparty_mapping(company_id, "RECEIPT", ar_gl.account_id, person_group_id=customer_group_id)
treasury_service.set_account_mapping(company_id, "RECEIPT_CASH", cash_gl.account_id)
sale, _ = doc_with_line("SALES_INVOICE", plain, 4, customer, 5000)
documents_service.confirm_document(sale, company_id, user.user_id)
settlements_service.auto_approve_settlement_plan(sale, company_id, user.user_id, [("CASH", D(20000))])
documents_service.post_document(sale, company_id, user.user_id)
je_id, cheque = pos_service.post_invoice_settlement_plan(company_id, user.user_id, sale)
check(je_id is not None and cheque == 0, f"سندِ دریافت خودکار صادر شد (je={je_id})")
with new_session() as s:
    je = s.get(JournalEntry, je_id)
    cash_debit = sum(l.debit_amount_base for l in s.scalars(select(JournalEntryLine).where(
        JournalEntryLine.journal_entry_id == je_id, JournalEntryLine.account_id == cash_gl.account_id)))
check(je is not None and cash_debit == 20000, f"سند در دفترِ روزنامه با بدهکاریِ صندوق ۲۰٬۰۰۰ (got {cash_debit})")
settled = sum((x.amount for x in settlements_service.list_settlements_for_invoice(sale, company_id)), D(0))
check(settled == 20000, f"فاکتور تسویه شد (got {settled})")

# ===== ۳: امانیِ بدونِ قیمت -> فاکتورِ خرید: تفکیکِ موجودی/بهایِ تمام‌شده =====
def sell(item_id, qty, price=5000):
    d, _ = doc_with_line("SALES_INVOICE", item_id, qty, customer, price)
    documents_service.confirm_document(d, company_id, user.user_id)
    settlements_service.auto_approve_settlement_plan(d, company_id, user.user_id, [])
    documents_service.post_document(d, company_id, user.user_id)
    return d
sell(cons_item, 4)  # ۴ عدد از ۱۰ عددِ امانیِ صفرقیمت فروخته شد (بهایِ تمام‌شده صفر)
settle = documents_service.convert_to_invoice(cin, company_id, user.user_id, today, {cin_line: D(10)})
settle_line = documents_service.get_document(settle, company_id)[1][0]
documents_service.update_line(settle_line.line_id, settle, company_id, D(10), D(1000))
documents_service.confirm_document(settle, company_id, user.user_id)
settlements_service.auto_approve_settlement_plan(settle, company_id, user.user_id, [])
documents_service.post_document(settle, company_id, user.user_id)
settle_je = status(settle).journal_entry_id
def je_by_account(je_id):
    with new_session() as s:
        out = {}
        for l in s.scalars(select(JournalEntryLine).where(JournalEntryLine.journal_entry_id == je_id)):
            out[l.account_id] = out.get(l.account_id, D(0)) + l.debit_amount_base - l.credit_amount_base
    return out
by_acc = je_by_account(settle_je)
check(by_acc.get(inv_gl.account_id) == 6000 and by_acc.get(cogs_gl.account_id) == 4000 and by_acc.get(ap_gl.account_id) == -10000,
      f"تسویهٔ امانی: موجودیِ ماندهٔ ۶ عدد ۶۰۰۰، بهایِ تمام‌شدهٔ ۴ عددِ فروخته‌شده ۴۰۰۰، پرداختنی ۱۰۰۰۰ (got {by_acc})")
from peecha.db.models.inventory import StockBalance
with new_session() as s_:
    stock_value = sum(s_.scalars(select(StockBalance.total_value).where(StockBalance.item_id == cons_item)), D(0))
check(stock_value == 6000, f"ارزشِ انبارِ ۶ عددِ باقی‌مانده ۶۰۰۰ شد (got {stock_value})")
sell(cons_item, 6)
check(residual_service.list_residuals(company_id) == [], "با فروشِ باقی‌مانده، ماندهٔ ریالیِ اضافه‌ای نمی‌ماند")

# ===== ۱۰: موجودیِ صفر با ماندهٔ ریالی -> سندِ تسعیر =====
item_detail = next(i.item_detail_account_id for i in catalog_service.list_items(company_id) if i.item_id == cons_item)
je_service.create_journal_entry(company_id, user.user_id, today, "انحرافِ آزمایشی", [
    je_service.LineInput(account_id=inv_gl.account_id, description="x", debit=D(750), credit=D(0), details={item_dim: item_detail}),
    je_service.LineInput(account_id=adj_gl.account_id, description="x", debit=D(0), credit=D(750), details={}),
])
rows = residual_service.list_residuals(company_id)
check(len(rows) == 1 and rows[0].item_id == cons_item and rows[0].residual == 750, f"کالایِ با موجودیِ صفر و ماندهٔ ۷۵۰ شناسایی شد (got {rows})")
check(residual_service.counter_account_id(company_id)[1] == "COGS", "بدونِ نگاشتِ تسعیر، بهایِ تمام‌شده جایگزین است")
check("INVENTORY_REVALUATION" in engine_service.MAPPING_LABELS, "حسابِ تسعیر در تنظیماتِ انبار ‹ نگاشتِ حساب‌ها قابلِ‌تعریف است")
engine_service.set_account_mapping(company_id, "INVENTORY_REVALUATION", reval_gl.account_id)
kinds = {t.kind for t in op_service.list_operational_tasks(company_id, user.user_id)}
check("INVENTORY_RESIDUAL" in kinds, "کارتابل: پیشنهادِ صدورِ سندِ تسعیر")
from peecha.ui.screens.inventory_residual import InventoryResidualScreen
scr = InventoryResidualScreen(); scr.refresh()
check(scr.table.rowCount() == 1, "صفحهٔ تسعیر ردیف را نشان می‌دهد")
scr.table.selectAll(); scr._post_selected()
check(residual_service.list_residuals(company_id) == [], "پس از صدورِ سند، انحراف صفر شد")
with new_session() as s:
    reval = sum(l.debit_amount_base - l.credit_amount_base for l in s.scalars(select(JournalEntryLine).where(JournalEntryLine.account_id == reval_gl.account_id)))
check(reval == 750, f"حسابِ تسعیر ۷۵۰ بدهکار شد (got {reval})")

# ===== ۱/۲/۴/۹: UI =====
from peecha.ui.shell_window import MainWindow
mw = MainWindow(); mw.resize(1300, 850); mw.show(); app.processEvents()
mw.open_screen("PURCH_ORDER"); app.processEvents()
sw = next(sw for sw in mw.mdi_area.subWindowList() if sw.isVisible())
mw.toggle_focus_mode(); app.processEvents()
check(not mw._sidebar_scroll.isVisibleTo(mw), "حالتِ تمام‌صفحه: ساید‌بار پنهان")
sw.close(); app.processEvents()
check(mw._sidebar_scroll.isVisibleTo(mw) and mw._quick_access_scroll.isVisibleTo(mw), "با بستنِ فرمِ تمام‌صفحه، منو و ریبون برمی‌گردند")

from PySide6.QtCore import QSettings
from peecha.ui.screens.commercial_document import CommercialDocumentScreen
screen = mw._screens["commercial_document_sales_invoice"]
screen.refresh()
check(screen.lines_table.columnWidth(2) >= 150, f"ستونِ واحد پهن‌تر شد (got {screen.lines_table.columnWidth(2)})")
screen.lines_table.horizontalHeader().resizeSection(3, 222); app.processEvents()
saved = QSettings("Peecha", "PeechaERP").value("linesTable/column_3/width", None, type=int)
check(saved == 222, f"عرضِ دستیِ ستون ذخیره شد (got {saved})")
from peecha.ui.widgets import persist_column_widths
from PySide6.QtWidgets import QTableWidget
t1 = QTableWidget(0, 3); persist_column_widths(t1, "r230test"); t1.horizontalHeader().resizeSection(1, 177)
t2 = QTableWidget(0, 3); persist_column_widths(t2, "r230test")
check(t2.columnWidth(1) == 177, f"عرضِ ستونِ فهرست‌ها/رسیدِ انبار هم ذخیره و بازیابی می‌شود (got {t2.columnWidth(1)})")
screen._show_entry_stock(next(i for i in catalog_service.list_items(company_id) if i.item_id == plain))
check("موجودی" in screen.entry_stock_label.text(), f"نمایشِ موجودیِ کالا پس از انتخاب (got {screen.entry_stock_label.text()})")

serial_item = catalog_service.create_item(company_id, "SR-1", "سریالی", catalog_service.ItemFields(item_kind_code="GOOD", base_uom_id=pcs, track_serial=True))
rows_ = {i.item_id: i for i in catalog_service.list_items(company_id)}
check(screen._entry_row_needs_tracking(rows_[serial_item]) and not screen._entry_row_needs_tracking(rows_[plain]),
      "پس از ورودِ مقدار/واحد، فرمِ سریال/بچ فقط برایِ کالایِ ردیابی‌شونده باز می‌شود")

print("RESULT:", "ALL PASS" if not FAIL else "SOME FAILED")
sys.exit(1 if FAIL else 0)
