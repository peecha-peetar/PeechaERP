import os, sys, datetime, decimal, io
os.environ["PEECHA_DB_NAME"] = "peecha_test_r227_1"
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
from peecha.services import commercial_consignment as consignment_service
from peecha.services import commercial_settlements as settlements_service
D = decimal.Decimal
TE = lt.TrackingEntry
def raises(fn):
    try:
        fn()
    except ValueError:
        return True
    return False

wh = locations_service.create_warehouse(company_id, "WH", "مرکزی", locations_service.WarehouseFields(is_default=True, allow_negative_stock=True))
wh2 = locations_service.create_warehouse(company_id, "WH2", "شعبه", locations_service.WarehouseFields(allow_negative_stock=True))
customer = partners_service.create_customer(company_id, "C-1", "فروشگاه", fast_track=True)
supplier = dimensions_service.create_supplier(company_id, "S1", "تامین‌کنندهٔ یک")
supplier2 = dimensions_service.create_supplier(company_id, "S2", "تامین‌کنندهٔ دو")
pcs = catalog_service.create_uom(company_id, "PCS", "عدد", "COUNT", decimal_places=0)
med = catalog_service.create_item(company_id, "M-1", "دارو", catalog_service.ItemFields(
    item_kind_code="GOOD", base_uom_id=pcs, track_batch=True, track_expiry=True))
phone = catalog_service.create_item(company_id, "P-1", "گوشی", catalog_service.ItemFields(
    item_kind_code="GOOD", base_uom_id=pcs, track_serial=True))
plain = catalog_service.create_item(company_id, "N-1", "پارچه", catalog_service.ItemFields(item_kind_code="GOOD", base_uom_id=pcs))
today = datetime.date.today()

def bal(item_id, warehouse_id=None, **kw):
    return lt.list_lot_balances(company_id, item_id=item_id, warehouse_id=warehouse_id, **kw)

# ===== ۱: چیدمانِ یکسانِ فرم‌ها =====
from peecha.ui.shell_window import MainWindow
from PySide6.QtCore import QSettings
QSettings("Peecha", "PeechaERP").setValue("mdiWindow/chart_of_accounts/maximized", True)
mw = MainWindow(); mw.resize(1300, 850); mw.show(); app.processEvents()
for code in ("GL_COA", "PURCH_ORDER", "INV_LOT_TRACE"):
    mw.open_screen(code); app.processEvents()
vis = [sw for sw in mw.mdi_area.subWindowList() if sw.isVisible()]
check(all(not sw.isMaximized() and sw.geometry() == mw.mdi_area.viewport().rect() for sw in vis),
      "همهٔ فرم‌ها یکسان کلِ ناحیه را پر می‌کنند (حتی با حالتِ maximizeِ ذخیره‌شدهٔ قدیمی)")
vis[0].showMaximized(); app.processEvents(); app.processEvents()
check(not vis[0].isMaximized() and vis[0].geometry() == mw.mdi_area.viewport().rect(), "maximizeِ بومی به همان چیدمانِ یکسان برمی‌گردد")
vis[0].widget().title_bar._toggle_maximize(); app.processEvents()
check(not mw._sidebar_scroll.isVisibleTo(mw) and all(sw.geometry() == mw.mdi_area.viewport().rect() for sw in vis),
      "دکمهٔ بزرگ‌کردن = حالتِ تمرکز (ساید‌بار پنهان، همهٔ فرم‌ها هنوز تمام‌ناحیه)")
vis[0].widget().title_bar._toggle_maximize(); app.processEvents()
check(mw._sidebar_scroll.isVisibleTo(mw), "خروج از حالتِ تمرکز")

# ===== ۲: رسیدِ انبار با بچ/انقضا =====
def receipt(item_id, qty, warehouse_id=wh, counterparty=supplier):
    doc = inv_documents_service.create_stock_document(company_id, user.user_id, "RECEIPT", today,
        inv_documents_service.DocumentHeaderFields(destination_warehouse_id=warehouse_id, counterparty_detail_account_id=counterparty))
    line = inv_documents_service.add_line(doc, company_id, inv_documents_service.LineFields(
        item_id=item_id, uom_id=pcs, quantity=D(qty), quantity_base=D(qty), unit_cost=D(1000)))
    inv_documents_service.confirm_stock_document(doc, company_id)
    return doc, line

r1, r1_line = receipt(med, 30)
check(raises(lambda: inv_documents_service.post_stock_document(r1, company_id, user.user_id)),
      "رسیدِ کالایِ بچ‌دار بدونِ اطلاعاتِ بچ/انقضا ثبت نمی‌شود")
check(raises(lambda: lt.set_line_tracking(company_id, [TE(D(30), batch_no="B1")], stock_line_id=r1_line)),
      "تاریخِ انقضا برایِ کالایِ دارایِ انقضا الزامی است")
check(raises(lambda: lt.set_line_tracking(company_id, [TE(D(31), batch_no="B1", expiry_date=today)], stock_line_id=r1_line)),
      "جمعِ ردیابی بیشتر از مقدارِ ردیف رد می‌شود")
lt.set_line_tracking(company_id, [
    TE(D(10), batch_no="B-LATE", expiry_date=today + datetime.timedelta(days=300)),
    TE(D(20), batch_no="B-EARLY", manufacture_date=today - datetime.timedelta(days=30), expiry_date=today + datetime.timedelta(days=60)),
], stock_line_id=r1_line)
inv_documents_service.post_stock_document(r1, company_id, user.user_id)
b = {r.batch_no: r for r in bal(med)}
check(b["B-LATE"].quantity == 10 and b["B-EARLY"].quantity == 20 and b["B-EARLY"].supplier_name == "تامین‌کنندهٔ یک",
      "موجودیِ هر بچ با تامین‌کننده ثبت شد")
check(len(bal(med, expiring_before=today + datetime.timedelta(days=90))) == 1, "فیلترِ «انقضا تا ۹۰ روز» فقط بچِ زودانقضا را نشان می‌دهد")

# ===== ۳: حواله/فروش بدونِ انتخابِ بچ -> FEFO =====
iss = inv_documents_service.create_stock_document(company_id, user.user_id, "ISSUE", today,
    inv_documents_service.DocumentHeaderFields(source_warehouse_id=wh))
inv_documents_service.add_line(iss, company_id, inv_documents_service.LineFields(item_id=med, uom_id=pcs, quantity=D(25), quantity_base=D(25)))
reason = inv_documents_service.list_reason_codes(company_id, "ISSUE")
inv_documents_service.confirm_stock_document(iss, company_id)
inv_documents_service.post_stock_document(iss, company_id, user.user_id)
b = {r.batch_no: r.quantity for r in bal(med)}
check("B-EARLY" not in b and b.get("B-LATE") == 5, f"خروج اول از زودانقضاترین بچ (FEFO) (got {b})")

# ===== ۴: انتقال بچ را حفظ می‌کند =====
tr = inv_documents_service.create_stock_document(company_id, user.user_id, "TRANSFER", today,
    inv_documents_service.DocumentHeaderFields(source_warehouse_id=wh, destination_warehouse_id=wh2))
inv_documents_service.add_line(tr, company_id, inv_documents_service.LineFields(item_id=med, uom_id=pcs, quantity=D(3), quantity_base=D(3)))
inv_documents_service.confirm_stock_document(tr, company_id)
inv_documents_service.post_stock_document(tr, company_id, user.user_id)
check([(r.batch_no, r.quantity) for r in bal(med, wh2)] == [("B-LATE", 3)], "انتقال همان بچ را به انبارِ مقصد برد")

# ===== ۵: سریال در تاییدِ رسیدِ سفارشِ خرید تا فروش =====
csettings_service.set_feature_enabled(company_id, "PURCHASE_ORDER_GOODS_RECEIPT", True)
csettings_service.set_feature_enabled(company_id, "PURCHASE_ORDER_SKIP_POST", True)  # R230: رفتارِ پیشین
csettings_service.set_feature_enabled(company_id, "PURCHASE_ORDER_SKIP_APPROVAL", True)
csettings_service.set_feature_enabled(company_id, "PURCHASE_INVOICE_SKIP_APPROVAL", True)
po = documents_service.create_document(company_id, user.user_id, "PURCHASE_ORDER", today,
    documents_service.DocumentHeaderFields(counterparty_detail_account_id=supplier, currency_id=company.base_currency_id, warehouse_id=wh))
po_line = documents_service.add_line(po, company_id, phone, pcs, D(3), D(3), unit_price=D(5000000))
documents_service.confirm_document(po, company_id, user.user_id)
check(raises(lambda: documents_service.approve_warehouse(po, company_id, user.user_id)), "تاییدِ رسید بدونِ سریال‌ها رد می‌شود")
check(raises(lambda: lt.set_line_tracking(company_id, [TE(D(1), serial_no="SN1"), TE(D(1), serial_no="SN1")], commercial_line_id=po_line)),
      "سریالِ تکراری رد می‌شود")
lt.set_line_tracking(company_id, [TE(D(1), serial_no=s) for s in ("SN1", "SN2", "SN3")], commercial_line_id=po_line)
documents_service.approve_warehouse(po, company_id, user.user_id)
check(True, "رسید با سریال‌ها تایید شد")
inv = documents_service.convert_to_invoice(po, company_id, user.user_id, today)
_, inv_lines = documents_service.get_document(inv, company_id)
check(len(lt.get_effective_commercial_tracking(inv_lines[0].line_id)) == 3, "فاکتور سریال‌هایِ رسید را از سفارش به ارث برد")
documents_service.confirm_document(inv, company_id, user.user_id)
settlements_service.auto_approve_settlement_plan(inv, company_id, user.user_id, [])
documents_service.post_document(inv, company_id, user.user_id)
check(sorted(r.serial_no for r in bal(phone)) == ["SN1", "SN2", "SN3"], "سه سریال در انبار")

sale = documents_service.create_document(company_id, user.user_id, "SALES_INVOICE", today,
    documents_service.DocumentHeaderFields(counterparty_detail_account_id=customer, currency_id=company.base_currency_id, warehouse_id=wh))
sale_line = documents_service.add_line(sale, company_id, phone, pcs, D(1), D(1), unit_price=D(6000000))
lt.set_line_tracking(company_id, [TE(D(1), serial_no="SN2")], commercial_line_id=sale_line)
documents_service.confirm_document(sale, company_id, user.user_id)
settlements_service.auto_approve_settlement_plan(sale, company_id, user.user_id, [])
documents_service.post_document(sale, company_id, user.user_id)
check(sorted(r.serial_no for r in bal(phone)) == ["SN1", "SN3"], "فروشِ سریالِ انتخاب‌شده (SN2)")
trace = lt.trace(company_id, serial_no="SN2")
check(len(trace) == 2 and trace[0].quantity == 1 and trace[1].quantity == -1 and "فاکتور" not in trace[0].document_label,
      f"تاریخچهٔ کاملِ سریال: ورود و خروج (got {[(t.document_label, t.quantity) for t in trace]})")
r_dup, r_dup_line = receipt(phone, 1)
lt.set_line_tracking(company_id, [TE(D(1), serial_no="SN1")], stock_line_id=r_dup_line)
check(raises(lambda: inv_documents_service.post_stock_document(r_dup, company_id, user.user_id)), "ورودِ سریالی که در انبار هست رد می‌شود")

# ===== ۶: امانیِ ورودی بر اساسِ تامین‌کننده =====
def consignment_in(counterparty, qty):
    doc = documents_service.create_document(company_id, user.user_id, "CONSIGNMENT_IN", today,
        documents_service.DocumentHeaderFields(counterparty_detail_account_id=counterparty, currency_id=company.base_currency_id, warehouse_id=wh))
    line = documents_service.add_line(doc, company_id, plain, pcs, D(qty), D(qty), unit_price=D(100))
    documents_service.confirm_document(doc, company_id, user.user_id)
    documents_service.post_document(doc, company_id, user.user_id)
    return doc, line
c1, c1_line = consignment_in(supplier, 10)
c2, c2_line = consignment_in(supplier2, 6)
cons = {r.supplier_name: r.quantity for r in bal(plain, consignment_only=True)}
check(cons == {"تامین‌کنندهٔ یک": 10, "تامین‌کنندهٔ دو": 6}, f"کالایِ امانی به تفکیکِ تامین‌کننده (got {cons})")
consignment_service.return_unused_consignment_in(c2, company_id, user.user_id, {c2_line: D(2)}, today)
cons = {r.supplier_name: r.quantity for r in bal(plain, consignment_only=True)}
check(cons.get("تامین‌کنندهٔ دو") == 4 and cons.get("تامین‌کنندهٔ یک") == 10, f"بازگشت از امانیِ همان تامین‌کننده کم شد (got {cons})")
settle = documents_service.convert_to_invoice(c1, company_id, user.user_id, today, {c1_line: D(4)})
documents_service.confirm_document(settle, company_id, user.user_id)
settlements_service.auto_approve_settlement_plan(settle, company_id, user.user_id, [])
documents_service.post_document(settle, company_id, user.user_id)
rows = bal(plain, supplier_detail_account_id=supplier)
owned = sum(r.quantity for r in rows if not r.is_consignment)
consigned = sum(r.quantity for r in rows if r.is_consignment)
check(owned == 4 and consigned == 6, f"تسویهٔ امانی: ۴ عدد خریداری‌شده، ۶ عدد هنوز امانی (got {owned}, {consigned})")
check(any("تسویهٔ امانی" in t.document_label for t in lt.trace(company_id, supplier_detail_account_id=supplier, item_id=plain)),
      "تسویه در تاریخچهٔ تامین‌کننده دیده می‌شود")

# ===== ۷: UI =====
from peecha.ui.screens.lot_tracking_dialog import LotTrackingDialog
r3, r3_line = receipt(med, 5)
dlg = LotTrackingDialog(None, company_id, med, "دارو", D(5), stock_line_id=r3_line)
dlg.table.cellWidget(0, 0).setText("B-UI")
dlg.table.cellWidget(0, 2).setDate(today + datetime.timedelta(days=100))
check(dlg.table.rowHeight(0) >= 42, f"ردیف‌هایِ فرمِ ردیابی ارتفاعِ کافی دارند (got {dlg.table.rowHeight(0)})")
dlg._save()
check([e.batch_no for e in lt.get_line_tracking(stock_line_id=r3_line)] == ["B-UI"], "دیالوگِ ردیابی بچ/انقضا را ذخیره کرد")
from peecha.ui.screens.inventory_document import InventoryDocumentScreen
inv_screen = InventoryDocumentScreen("RECEIPT", None)
inv_screen.edit_document(r3)
btn = inv_screen.lines_table.cellWidget(0, inv_screen.lines_table.columnCount() - 1)
check(btn is not None and "ردیابی" in btn.text(), "دکمهٔ «ردیابی» رویِ ردیفِ رسیدِ انبار")
trace_screen = mw._screens["lot_trace"]
trace_screen.refresh()
check(trace_screen.balance_table.rowCount() >= 4, f"صفحهٔ ردیابی موجودیِ بچ/سریال/امانی را نشان می‌دهد (got {trace_screen.balance_table.rowCount()})")
trace_screen.serial_field.setText("SN2"); trace_screen._load_trace()
check(trace_screen.trace_table.rowCount() == 2, "جستجویِ سریال در صفحهٔ ردیابی")

print("RESULT:", "ALL PASS" if not FAIL else "SOME FAILED")
sys.exit(1 if FAIL else 0)
