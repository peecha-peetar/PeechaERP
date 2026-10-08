import os, sys, datetime, decimal, io
os.environ["PEECHA_DB_NAME"] = "peecha_test_r233_1"
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


from peecha.services import purchase_reports as pr
import datetime as dt
D = decimal.Decimal
s2 = dimensions_service.create_supplier(company_id, "S2", "تامین‌کنندهٔ دو")
bolt = catalog_service.create_item(company_id, "B-1", "پیچ", catalog_service.ItemFields(item_kind_code="GOOD", base_uom_id=pcs, purchase_lead_time_days=5))
supplier_group_id = next(g.person_group_id for g in dimensions_service.list_person_groups(company_id) if g.code == "SUPPLIER")
treasury_service.create_counterparty_mapping(company_id, "PAYMENT", ap_gl.account_id, person_group_id=supplier_group_id)
treasury_service.set_account_mapping(company_id, "PAYMENT_CASH", cash_gl.account_id)
csettings_service.set_feature_enabled(company_id, "PURCHASE_ORDER_GOODS_RECEIPT", True)
csettings_service.set_feature_enabled(company_id, "PURCHASE_ORDER_SKIP_APPROVAL", True)

def dated(doc_type, item_id, qty, cp, price, when):
    d = documents_service.create_document(company_id, user.user_id, doc_type, when, HF(cp))
    line = documents_service.add_line(d, company_id, item_id, pcs, D(qty), D(qty), unit_price=D(price))
    return d, line

def post_invoice(d, plan=()):
    documents_service.confirm_document(d, company_id, user.user_id)
    settlements_service.auto_approve_settlement_plan(d, company_id, user.user_id, list(plan))
    documents_service.post_document(d, company_id, user.user_id)

d10 = today - dt.timedelta(days=10)
# سفارشِ ۱: ۱۰۰ عدد پیچ از S1 به فیِ ۱۰۰ -- رسید ۸۰، فاکتور ۵۰ به فیِ ۱۱۰
po1, po1_line = dated("PURCHASE_ORDER", bolt, 100, s1, 100, d10)
documents_service.confirm_document(po1, company_id, user.user_id)
documents_service.post_document(po1, company_id, user.user_id)
documents_service.set_warehouse_delivered_quantities(po1, company_id, {po1_line: D(80)})
documents_service.approve_warehouse(po1, company_id, user.user_id, warehouse_id=wh)
inv1 = documents_service.convert_to_invoice(po1, company_id, user.user_id, today)
inv1_line = documents_service.get_document(inv1, company_id)[1][0]
documents_service.update_line(inv1_line.line_id, inv1, company_id, D(80), D(110))
post_invoice(inv1)
# سفارشِ ۳: ۳۰ عدد رسیده ولی فاکتورنشده
po3, po3_line = dated("PURCHASE_ORDER", bolt, 30, s1, 100, d10)
documents_service.confirm_document(po3, company_id, user.user_id)
documents_service.post_document(po3, company_id, user.user_id)
documents_service.approve_warehouse(po3, company_id, user.user_id, warehouse_id=wh)
# سفارشِ ۲: هنوز رسید نخورده
po2, _ = dated("PURCHASE_ORDER", bolt, 20, s2, 90, today)
documents_service.confirm_document(po2, company_id, user.user_id)
documents_service.post_document(po2, company_id, user.user_id)
# خریدِ مستقیم از S2 به فیِ ۹۵ (بدونِ سفارش) و یک فاکتورِ پیش‌نویس
direct, _ = dated("PURCHASE_INVOICE", bolt, 30, s2, 95, today)
post_invoice(direct)
draft, _ = dated("PURCHASE_INVOICE", bolt, 1, s1, 100, today)
# برگشتِ ۵ عدد به S1
ret, _ = dated("PURCHASE_RETURN", bolt, 5, s1, 110, today)
documents_service.confirm_document(ret, company_id, user.user_id)
documents_service.post_document(ret, company_id, user.user_id)

F = pr.PurchaseFilters(today - dt.timedelta(days=30), today)
def rows(code, **kw):
    return pr.run_report(company_id, code, dataclasses.replace(F, **kw)).rows
import dataclasses

r = rows("OPEN_PO")
o1 = next(x for x in r if x[0] == documents_service.get_document(po1, company_id)[0].document_no)
check(o1[6] == 100 and o1[7] == 80 and o1[8] == 80 and o1[9] == 20, f"۱) سفارش باز: ۱۰۰/رسید ۸۰/فاکتور ۸۰/مانده ۲۰ (got {o1[6:10]})")
check(len(r) == 3, f"۱) سه سفارش باز (got {len(r)})")
r = rows("PENDING_RECEIPTS")
check(len(r) == 1 and r[0][1] == documents_service.get_document(po2, company_id)[0].document_no, "۳) فقط سفارش ۲ منتظر رسید است")
r = rows("GRIR")
check(len(r) == 1 and r[0][7] == 30 and r[0][9] == 3000, f"۴) GR/IR: ۳۰ عدد رسیده و فاکتورنشده = ۳۰۰۰ (got {r and r[0][5:10]})")
r = rows("PENDING_INVOICES")
check(len(r) == 1 and "پیش‌نویس" in r[0][4], "۵) فاکتور پیش‌نویس در انتظار")
r = rows("BY_ITEM")
b = r[0]
check(b[2] == 110 and b[3] == 80 * 110 + 30 * 95 and b[4] == 5 and b[6] == 105, f"۸) خرید به تفکیک کالا (got {b[2:8]})")
check(b[9] == 95 and b[10] == 110 and b[12] == 2 and b[13] == 2, f"۸) کمترین/بیشترین فی، تعداد فاکتور/تامین‌کننده (got {b[8:14]})")
r = rows("BY_SUPPLIER")
check(len(r) == 2 and abs(sum(x[8] for x in r) - 100) < D("0.01"), "۹) سهم‌ها جمعاً ۱۰۰٪")
r = rows("PRICE_HISTORY")
check(len(r) == 2, f"۱۵) دو خرید در تاریخچه (got {len(r)})")
r = rows("PRICE_COMPARE")
cheap = [x for x in r if x[9] == "★"]
check(len(cheap) == 1 and cheap[0][2] == 95, "۱۶) ارزان‌ترین تامین‌کننده (S2، فی ۹۵)")
r = rows("PPV")
ppv_po = [x for x in r if "سفارش" in x[4]]
check(len(ppv_po) == 1 and ppv_po[0][7] == 10 and ppv_po[0][10] == 800, f"۱۷) PPV: ۱۱۰ در برابر سفارش ۱۰۰ -> اثر ۸۰۰ (got {ppv_po and ppv_po[0][4:]})")
r = rows("FILL_RATE")
f1 = next(x for x in r if "یک" in x[0])
check(f1[3] == 130 and f1[4] == 110 and f1[6] == 1, f"۲۳) دقت مقدار: ۱۱۰ از ۱۳۰، یک ردیف کامل (got {f1[3:7]})")
r = rows("LEAD_TIME")
check(len(r) == 1 and r[0][2] == 2 and r[0][3] == 10 and r[0][6] == "5 روز", f"۲۵) زمان تحویل ۱۰ روز (got {r})")
r = rows("BALANCES")
b1 = next(x for x in r if "یک" in x[0])
check(b1[3] == 80 * 110 and b1[2] > 0 and b1[4] == b1[3] - b1[2], f"۲۶) بدهی به S1 = خرید − برگشت (got {b1[2:5]})")
# پرداختِ ۱۰۰۰ به S2 و سنی‌کردن
pos_service_jid = None
from peecha.services import commercial_pos as pos_service
plan_inv, _ = dated("PURCHASE_INVOICE", bolt, 10, s2, 100, today - dt.timedelta(days=45))
post_invoice(plan_inv, [("CASH", D(400))])
pos_service.post_invoice_settlement_plan(company_id, user.user_id, plan_inv)
r = rows("AGING", supplier_id=s2)
check(len(r) == 1 and r[0][1] == 2 and r[0][7] == 30 * 95 + 600, f"۲۷) سنی‌کردن: ۲ فاکتور باز، ماندهٔ ۳۴۵۰ (got {r})")
r = rows("STATEMENT", supplier_id=s2, date_from=today - dt.timedelta(days=60))
check(r[-1][5] == 30 * 95 + 1000 - 400, f"۲۹) صورت‌حساب: ماندهٔ نهایی ۳۴۵۰ (got {r[-1]})")
check(pr.run_report(company_id, "STATEMENT", F).note != "", "۲۹) بدون انتخاب تامین‌کننده، راهنما")
r = rows("SUPPLIERS")
check(len(r) == 2 and next(x for x in r if x[0] == "S2")[11] == 3450, f"۳۱) فهرست تامین‌کنندگان با مانده (got {r})")
r = rows("BY_ITEM", supplier_id=s2)
check(r[0][2] == 30, "فیلتر تامین‌کننده")

# UI: همهٔ گزارش‌ها از منو باز و اجرا می‌شوند
from peecha.ui.shell_window import MainWindow
mw = MainWindow(); mw.resize(1300, 850); mw.show(); app.processEvents()
ok = True
for rep in pr.REPORTS:
    mw.open_screen(f"PURCH_RPT_{rep.code}"); app.processEvents()
    scr = mw._screens[f"purchase_report_{rep.code.lower()}"]
    scr.date_from.setDate(today - dt.timedelta(days=60)); scr._reload()
    if scr.table.columnCount() == 0:
        ok = False; print("empty", rep.code)
check(ok, "همهٔ ۱۵ گزارش از منوی «گزارشات تدارکات» باز و اجرا شدند")
scr = mw._screens["purchase_report_open_po"]; scr._reload()
check(scr.table.rowCount() == 4 and "جمع کل" in scr.table.item(3, 0).text(), "جدول با ردیف جمع کل")
scr._open_row(0, 0); app.processEvents()
po_screen = mw._screens["commercial_document_purchase_order"]
check(po_screen._document_id in (po1, po2), "دابل‌کلیک، سفارش را باز کرد")

print("RESULT:", "ALL PASS" if not FAIL else "SOME FAILED")
sys.exit(1 if FAIL else 0)
