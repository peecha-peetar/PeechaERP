import os, sys, datetime, decimal, io
os.environ["PEECHA_DB_NAME"] = "peecha_test_r228_1"
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

from peecha.services import unit_conversion as uc
from peecha.services import stock_count as stock_count_service
from peecha.services import commercial_settlements as settlements_service

D = decimal.Decimal
def raises(fn):
    try:
        fn()
    except ValueError:
        return True
    return False

k8 = A("32", "پرداختنی‌ها", "CREDIT", "LIABILITY", "PERMANENT", False, g4.account_id)
ap_gl = A("3201", "پرداختنیِ تامین‌کنندگان", "CREDIT", "LIABILITY", "PERMANENT", True, k8.account_id)
engine_service.set_account_mapping(company_id, "SUPPLIER_PAYABLE", ap_gl.account_id)
engine_service.set_account_mapping(company_id, "INVENTORY_ADJUSTMENT_LOSS", adj_gl.account_id)

from peecha.services import lot_tracking as lt
from peecha.services import stock_count as count_service
from peecha.services import commercial_settlements as settlements_service
from peecha.services import commercial_pos as pos_service
from peecha.services import field_sales as field_sales_service
from peecha.services import data_reset
from peecha.services import unit_conversion as uc
D = decimal.Decimal
TE = lt.TrackingEntry
today = datetime.date.today()
def raises(fn):
    try:
        fn()
    except ValueError:
        return True
    return False

wh = locations_service.create_warehouse(company_id, "WH", "مرکزی", locations_service.WarehouseFields(is_default=True, allow_negative_stock=True))
customer = partners_service.create_customer(company_id, "C-1", "فروشگاه", fast_track=True)
s1 = dimensions_service.create_supplier(company_id, "S1", "تامین‌کنندهٔ یک")
s2 = dimensions_service.create_supplier(company_id, "S2", "تامین‌کنندهٔ دو")
pcs = catalog_service.create_uom(company_id, "PCS", "عدد", "COUNT", decimal_places=0)
phone = catalog_service.create_item(company_id, "P-1", "گوشی", catalog_service.ItemFields(item_kind_code="GOOD", base_uom_id=pcs, track_serial=True))
med = catalog_service.create_item(company_id, "M-1", "دارو", catalog_service.ItemFields(item_kind_code="GOOD", base_uom_id=pcs, track_batch=True, track_expiry=True))
csettings_service.set_feature_enabled(company_id, "PURCHASE_INVOICE_SKIP_APPROVAL", True)

def receipt(item_id, entries, supplier):
    doc = inv_documents_service.create_stock_document(company_id, user.user_id, "RECEIPT", today,
        inv_documents_service.DocumentHeaderFields(destination_warehouse_id=wh, counterparty_detail_account_id=supplier))
    qty = sum(e.quantity for e in entries)
    line = inv_documents_service.add_line(doc, company_id, inv_documents_service.LineFields(item_id=item_id, uom_id=pcs, quantity=qty, quantity_base=qty, unit_cost=D(1000)))
    lt.set_line_tracking(company_id, entries, stock_line_id=line)
    inv_documents_service.confirm_stock_document(doc, company_id)
    inv_documents_service.post_stock_document(doc, company_id, user.user_id)

def commercial(doc_type, item_id, qty, counterparty, entries=None):
    doc = documents_service.create_document(company_id, user.user_id, doc_type, today,
        documents_service.DocumentHeaderFields(counterparty_detail_account_id=counterparty, currency_id=company.base_currency_id, warehouse_id=wh))
    line = documents_service.add_line(doc, company_id, item_id, pcs, D(qty), D(qty), unit_price=D(1000))
    if entries is not None:
        lt.set_line_tracking(company_id, entries, commercial_line_id=line)
    documents_service.confirm_document(doc, company_id, user.user_id)
    if doc_type in ("SALES_INVOICE", "PURCHASE_INVOICE"):
        settlements_service.auto_approve_settlement_plan(doc, company_id, user.user_id, [])
    documents_service.post_document(doc, company_id, user.user_id)
    return doc, line

# ===== ۲: فروشِ امانیِ یک تامین‌کنندهٔ خاص با سریالِ خاص =====
receipt(phone, [TE(D(1), serial_no="OWN-1"), TE(D(1), serial_no="OWN-2")], s1)          # خریداری‌شده از S1
commercial("CONSIGNMENT_IN", phone, 2, s2, [TE(D(1), serial_no="CNS-1"), TE(D(1), serial_no="CNS-2")])  # امانیِ S2
available = lt.list_lot_balances(company_id, item_id=phone, warehouse_id=wh)
check(sorted((r.serial_no, r.supplier_name, r.is_consignment) for r in available) == [
    ("CNS-1", "تامین‌کنندهٔ دو", True), ("CNS-2", "تامین‌کنندهٔ دو", True),
    ("OWN-1", "تامین‌کنندهٔ یک", False), ("OWN-2", "تامین‌کنندهٔ یک", False),
], f"موجودیِ قابلِ‌انتخاب: سریال + تامین‌کننده + امانی/خریداری‌شده (got {available})")

from peecha.ui.screens.lot_tracking_dialog import LotTrackingDialog
sale = documents_service.create_document(company_id, user.user_id, "SALES_INVOICE", today,
    documents_service.DocumentHeaderFields(counterparty_detail_account_id=customer, currency_id=company.base_currency_id, warehouse_id=wh))
sale_line = documents_service.add_line(sale, company_id, phone, pcs, D(1), D(1), unit_price=D(9000))
dlg = LotTrackingDialog(None, company_id, phone, "گوشی", D(1), commercial_line_id=sale_line, direction="OUT", warehouse_id=wh)
check(dlg.available_table.rowCount() == 4, "پنجرهٔ فروش موجودیِ قابلِ‌انتخاب را نشان می‌دهد")
pick_row = next(i for i, r in enumerate(dlg._available) if r.serial_no == "CNS-2")
dlg.available_table.selectRow(pick_row)
dlg._add_selected_available()
picked = dlg.entries()
check(len(picked) == 1 and picked[0].serial_no == "CNS-2" and picked[0].supplier_detail_account_id == s2 and picked[0].is_consignment,
      f"انتخاب از جدول: سریال + تامین‌کننده + امانی در ردیف آمد (got {picked})")
dlg._save()
documents_service.confirm_document(sale, company_id, user.user_id)
settlements_service.auto_approve_settlement_plan(sale, company_id, user.user_id, [])
documents_service.post_document(sale, company_id, user.user_id)
left = sorted(r.serial_no for r in lt.list_lot_balances(company_id, item_id=phone, warehouse_id=wh))
check(left == ["CNS-1", "OWN-1", "OWN-2"], f"دقیقاً سریالِ امانیِ S2 فروخته شد (got {left})")

# بدونِ سریال/بچ: فقط «امانیِ تامین‌کنندهٔ دو» انتخاب شود
plain = catalog_service.create_item(company_id, "N-1", "پارچه", catalog_service.ItemFields(item_kind_code="GOOD", base_uom_id=pcs))
commercial("CONSIGNMENT_IN", plain, 5, s1)
commercial("CONSIGNMENT_IN", plain, 5, s2)
commercial("SALES_INVOICE", plain, 3, customer, [TE(D(3), supplier_detail_account_id=s2, is_consignment=True)])
cons = {r.supplier_name: r.quantity for r in lt.list_lot_balances(company_id, item_id=plain, consignment_only=True)}
check(cons == {"تامین‌کنندهٔ یک": 5, "تامین‌کنندهٔ دو": 2}, f"فروشِ امانیِ تامین‌کنندهٔ دو بدونِ بچ/سریال (got {cons})")

# ===== ۱: انبارگردانی به تفکیکِ بچ =====
receipt(med, [TE(D(10), batch_no="B1", expiry_date=today + datetime.timedelta(days=100)),
              TE(D(5), batch_no="B2", expiry_date=today + datetime.timedelta(days=200))], s1)
session_id = count_service.create_count_session(company_id, wh, user.user_id)
expected = {e.batch_no: e.quantity for e in lt.expected_tracking(company_id, med, wh)}
check(expected == {"B1": 10, "B2": 5}, f"موجودیِ دفتریِ هر بچ برایِ انبارگردانی (got {expected})")
count_service.record_count_tracking(session_id, company_id, med, [
    TE(D(8), batch_no="B1", expiry_date=today + datetime.timedelta(days=100)),
    TE(D(5), batch_no="B2", expiry_date=today + datetime.timedelta(days=200)),
    TE(D(2), batch_no="B3", expiry_date=today + datetime.timedelta(days=300)),
])
data = count_service.get_count_session(session_id, company_id)
check(data.lines[0].counted_quantity_base == 15 and data.lines[0].variance_quantity_base == 0,
      "جمعِ شمارش ۱۵ = دفتری (اختلافِ کل صفر) ولی بچ‌ها جابه‌جا هستند")
docs = count_service.finalize_count_session(session_id, company_id, user.user_id)
after = {r.batch_no: r.quantity for r in lt.list_lot_balances(company_id, item_id=med, warehouse_id=wh)}
check(len(docs) == 2 and after == {"B1": 8, "B2": 5, "B3": 2}, f"اختلافِ هر بچ با سندِ اصلاح ثبت شد (got {after}, docs={docs})")
on_hand = sum((r.quantity_on_hand for r in engine_service.get_item_stock_by_warehouse(company_id, med) if r.warehouse_id == wh), D(0))
check(on_hand == 15, f"موجودیِ کمّی تغییری نکرد (got {on_hand})")

# انبارگردانیِ سریال: یک سریال پیدا نشد
s2_session = count_service.create_count_session(company_id, wh, user.user_id)
count_service.record_count_tracking(s2_session, company_id, phone, [TE(D(1), serial_no="OWN-1"), TE(D(1), serial_no="CNS-1")])
count_service.finalize_count_session(s2_session, company_id, user.user_id)
left = sorted(r.serial_no for r in lt.list_lot_balances(company_id, item_id=phone, warehouse_id=wh))
check(left == ["CNS-1", "OWN-1"], f"سریالِ پیدانشده (OWN-2) با کسری خارج شد (got {left})")

from peecha.ui.screens.stock_count import StockCountScreen
sc = StockCountScreen(); sc.refresh()
sc.session_combo.setCurrentIndex(sc.session_combo.findData(session_id))
check(sc.table.cellWidget(0, 6) is not None, "دکمهٔ «بچ/سریال» رویِ ردیفِ انبارگردانی")

# ===== ۳: خام‌کردنِ اطلاعات با داده‌هایِ ردیابی/POS/تاریخچهٔ قیمت/ویزیت =====
price_list = pricing_service.create_price_list(company_id, "PL1", "عمومی", "SALES", company.base_currency_id, today)
pricing_service.set_price_list_item(price_list, plain, pcs, D(1000))
pricing_service.set_price_list_item(price_list, plain, pcs, D(1200))
uc.add_barcode(company_id, plain, pcs, "6260000000019")
terminal = pos_service.create_terminal(company_id, wh, "T1", "صندوق")
field_sales_service.create_visit_plan(company_id, customer, 1)
data_reset.wipe_documents(company_id)
data_reset.wipe_master_data(company_id)
data_reset.wipe_settings(company_id)
check(lt.list_lot_balances(company_id) == [] and catalog_service.list_items(company_id) == [],
      "خام‌کردنِ اسناد/اطلاعاتِ پایه/تنظیمات بدونِ خطا انجام شد")

print("RESULT:", "ALL PASS" if not FAIL else "SOME FAILED")
sys.exit(1 if FAIL else 0)
