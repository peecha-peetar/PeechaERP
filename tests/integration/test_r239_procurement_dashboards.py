import os, sys, datetime, decimal, io
os.environ["PEECHA_DB_NAME"] = "peecha_test_r239_1"
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
import tempfile
from PySide6.QtCore import QSettings
QSettings.setPath(QSettings.NativeFormat, QSettings.UserScope, tempfile.mkdtemp())
QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, tempfile.mkdtemp())
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

pos_service_jid = None
from peecha.services import commercial_pos as pos_service
plan_inv, _ = dated("PURCHASE_INVOICE", bolt, 10, s2, 100, today - dt.timedelta(days=45))
post_invoice(plan_inv, [("CASH", D(400))])
pos_service.post_invoice_settlement_plan(company_id, user.user_id, plan_inv)
import dataclasses
from peecha.services import purchase_reports_ext as ext
from peecha.db.models.inventory import ReorderPolicy
from peecha.db.models.commercial import CommercialDocument as CD
# سفارشِ لغوشده، سفارشِ فروشِ باز (تقاضا)، سیاستِ سفارش برایِ پیچ
po_x, _ = dated("PURCHASE_ORDER", bolt, 7, s2, 90, today)
documents_service.cancel_document(po_x, company_id)
so, _ = dated("SALES_ORDER", bolt, 400, customer, 300, today)
documents_service.confirm_document(so, company_id, user.user_id)
with new_session() as s_:
    s_.add(ReorderPolicy(company_id=company_id, item_id=bolt, warehouse_id=wh, min_qty=D(50), max_qty=D(500),
                         reorder_point_qty=D(100), reorder_qty=D(200), lead_time_days=7, is_active=True))
    s_.get(CD, po2).requested_delivery_date = today - dt.timedelta(days=3)
    s_.commit()

F = pr.PurchaseFilters(today - dt.timedelta(days=30), today)
def run(code, **kw):
    return pr.run_report(company_id, code, dataclasses.replace(F, **kw))
def rows(code, **kw):
    return run(code, **kw).rows
from peecha.services import purchase_dashboard as dash
from peecha import numerals
no = lambda d: documents_service.get_document(d, company_id)[0].document_no
A, B = today - dt.timedelta(days=60), today

# --- ۱) شاخص‌هایِ داشبوردِ مدیریتی = جمعِ گزارشِ مبدا
k = {x.code: x for x in dash.executive_kpis(company_id, A, B)}
def foot(code, header, **options):
    res = pr.run_report(company_id, code, dash.filters_for(code, A, B, options=options))
    return dash.total(res, header)
check(k["NET"].value == foot("BY_SUPPLIER", "خالص خرید") == 80 * 110 + 30 * 95 + 1000 - 550, f"خالص خرید (got {k['NET'].value})")
check(k["OPEN_PO"].value == foot("OPEN_PO", "ارزش مانده") == 6800, f"ارزش سفارش‌های باز (got {k['OPEN_PO'].value})")
check(k["GRIR"].value == 3000 and k["OVERDUE"].value == 600 and k["PPV"].value == 350, f"GR/IR، معوق، PPV (got {k['GRIR'].value}, {k['OVERDUE'].value}, {k['PPV'].value})")
check(k["RETURN_RATE"].value == D(550) * 100 / (80 * 110 + 30 * 95 + 1000) and k["CYCLE"].value == 10, "نرخ برگشت و زمان سفارش→رسید")
check(k["OTD"].value is None and k["SUPPLIERS"].value == 2 and k["INVOICES"].value == 3, "OTD بدون داده، تامین‌کنندگان/فاکتورها")
check(all(x.formula and x.report_code in pr.REPORTS_BY_CODE for x in k.values()), "هر شاخص فرمول و گزارش مبدا دارد")
ch = dash.executive_charts(company_id, A, B)
check(len(ch["monthly"]) == 2 and ch["suppliers"][0][1] >= ch["suppliers"][-1][1] and len(ch["aging"]) == 5, f"دادهٔ نمودارها (got {ch['monthly']})")

# --- ۲) داشبوردِ استثناها
ex = {x.code: x for x in dash.exceptions(company_id, A, B)}
check(ex["THREE_WAY"].count == 3 and ex["THREE_WAY"].amount == 800, f"استثنا: مغایرت سه‌طرفه (got {ex['THREE_WAY']})")
check(ex["OVERDUE"].count == 1 and ex["OVERDUE"].amount == 600 and ex["LATE_ORDERS"].count == 1, "استثنا: معوق و دیرکرد")
check(ex["DEMAND_NO_PO"].count == 1 and ex["CANCELLED"].count == 1 and ex["PRICE_ABOVE"].amount == 800, "استثنا: تقاضا، لغو، قیمت بالاتر")
check(ex["BELOW_ROP"].count == 0 and ex["INVOICE_NO_RECEIPT"].count == 0, "استثنا‌های بدون مورد")

# --- ۳) Drill-down از ردیفِ تجمیعی
res = pr.run_report(company_id, "BY_SUPPLIER", dash.filters_for("BY_SUPPLIER", A, B))
s1_row = next(r_ for r_ in res.rows if r_[0].startswith("S1"))
check(dash.drill_target(company_id, "BY_SUPPLIER", "PURCHASE", s1_row) == ("REG_INVOICE_LINES", {"supplier_id": s1}), "Drill: تامین‌کننده → ریز اقلام")
check(dash.drill_target(company_id, "BALANCES", "PURCHASE", s1_row) == ("STATEMENT", {"supplier_id": s1}), "Drill: گزارش مالی → صورت‌حساب")
res = pr.run_report(company_id, "BY_ITEM", dash.filters_for("BY_ITEM", A, B))
check(dash.drill_target(company_id, "BY_ITEM", "PURCHASE", res.rows[0]) == ("REG_INVOICE_LINES", {"item_id": bolt}), "Drill: کالا → ریز اقلام")

# --- ۴) UI: داشبوردها از منو
from peecha import nav_catalog
from peecha.ui.shell_window import MainWindow
mw = MainWindow(); mw.resize(1400, 900); mw.show(); app.processEvents()
mw.open_screen("PURCH_RPT_DASH_EXEC"); app.processEvents()
de = mw._screens["purchase_dashboard_exec"]
de.date_from.setDate(A); de.reload(); app.processEvents()
check(de.cards["OVERDUE"].value_label.text() == numerals.format_money(D(600), 0, None),
      f"کارت بدهی معوق (got {de.cards['OVERDUE'].value_label.text()})")
check(de.cards["NET"]._title_label.text() == "خالص خرید" and "فرمول" in de.cards["NET"].toolTip(), "عنوان و فرمول کارت")
de._open_kpi("OVERDUE"); app.processEvents()
un = mw._screens["purchase_report_unpaid"]
check(un._option_combos["view"][1].currentData() == "OVERDUE" and un.table.rowCount() == 2, f"کلیک کارت: فاکتورهای معوق (rows {un.table.rowCount()})")
mw.open_screen("PURCH_RPT_DASH_EXCEPTIONS"); app.processEvents()
dx = mw._screens["purchase_dashboard_exceptions"]
dx.date_from.setDate(A); dx.reload(); app.processEvents()
check(dx.table.rowCount() == len(ex) and dx.table.item(0, 0).text() == "بالا", "جدول استثناها، مرتب بر اساس شدت")
first = dx._rows[0]
dx.open_exception(0); app.processEvents()
scr = mw._screens[f"purchase_report_{first.report_code.lower()}"]
check(scr.table.rowCount() >= first.count, f"دابل‌کلیک استثنا، گزارش مبدا را باز کرد ({first.report_code})")

# --- ۵) مرتب‌سازی، گروه‌بندی، ستون‌ها، CSV/کپی، نما، نمودار
mw.open_screen("PURCH_RPT_OPEN_PO"); app.processEvents()
op = mw._screens["purchase_report_open_po"]
op.date_from.setDate(A); op._reload()
value_col = [h for h, _k in op._result.columns].index("ارزش مانده")
op.sort_by(value_col, descending=True)
vals = [op._result.rows[op._row_raw[id(r_)]][value_col] for r_ in op._rows]
check(vals == sorted(vals, reverse=True) and op.table.horizontalHeader().isSortIndicatorShown(), f"مرتب‌سازی نزولی (got {vals})")
op._on_header_clicked(value_col)
vals = [op._result.rows[op._row_raw[id(r_)]][value_col] for r_ in op._rows]
check(vals == sorted(vals), "کلیک دوباره: صعودی")
op.group_combo.setCurrentIndex(op.group_combo.findText("تامین‌کننده")); app.processEvents()
subtotals = [r_ for r_, b in zip(op._rows, op._row_bold) if b]
check(len(subtotals) == 2 and op.table.rowCount() == 3 + 2 + 1 and all(r_[0].startswith("جمع") for r_ in subtotals), f"گروه‌بندی با جمع هر تامین‌کننده (rows {op.table.rowCount()})")
s1_sub = next(r_ for r_ in subtotals if "یک" in r_[0])
check(s1_sub[value_col] == numerals.format_money(D(5000), 0, None), f"جمع گروه S1 = ۵۰۰۰ (got {s1_sub[value_col]})")
op._open_row(op._rows.index(s1_sub), 0)
op.group_combo.setCurrentIndex(0)
op.set_hidden_columns({"واحد", "وضعیت"})
headers, rows_, footer_ = op._export_data()
check("واحد" not in headers and len(headers) == len(op._headers) - 2 and op.table.isColumnHidden(op._headers.index("واحد")), "پنهان‌کردن ستون در جدول و خروجی")
csv_ = op.csv_text()
check(csv_.splitlines()[0].split(",")[0] == "شمارهٔ سفارش" and ",6800," in csv_ and "واحد" not in csv_.splitlines()[0].split(","), f"CSV با اعداد ساده (got {csv_.splitlines()[-1]})")
op.table.selectRow(0)
cp = op.copy_text().split("\n")
check(len(cp) == 2 and "\t" in cp[0], "کپی ردیف انتخاب‌شده با سرستون")
op.group_combo.setCurrentIndex(op.group_combo.findText("تامین‌کننده"))
op.save_view("بدهی‌ها")
op.set_hidden_columns(set()); op.group_combo.setCurrentIndex(0); op.sort_by(None)
op.load_view("بدهی‌ها"); app.processEvents()
check(op.group_combo.currentText() == "تامین‌کننده" and op.hidden_columns() == {"واحد", "وضعیت"} and op._sort_col == value_col,
      "نمای ذخیره‌شده: گروه، ستون‌ها و مرتب‌سازی بازگردانی شد")
check(op.view_combo.findData("بدهی‌ها") > 0, "نما در فهرست نماها")
op.delete_view("بدهی‌ها"); op.set_hidden_columns(set())
check(op.view_combo.findData("بدهی‌ها") < 0, "حذف نما")
dlg = op.open_chart(); app.processEvents()
check(dlg is not None and len(dlg.series()) >= 1, f"نمودار گزارش (got {dlg and dlg.series()})")
dlg.type_combo.setCurrentIndex(1); app.processEvents(); dlg.close()

# --- ۶) Drill-down در UI: خرید به تفکیکِ تامین‌کننده → ریزِ اقلامِ همان تامین‌کننده
mw.open_screen("PURCH_RPT_BY_SUPPLIER"); app.processEvents()
bs = mw._screens["purchase_report_by_supplier"]
bs.date_from.setDate(A); bs._reload()
row = next(i for i, r_ in enumerate(bs._rows) if "دو" in r_[0])
bs._open_row(row, 0); app.processEvents()
il = mw._screens["purchase_report_reg_invoice_lines"]
check(il.supplier_combo.currentData() == s2 and il.table.rowCount() == 2 + 1, f"ریزنمایی: ریز اقلام S2 (rows {il.table.rowCount()})")
# ستون‌ها/CSV در گزارش‌هایِ دیگر (پایهٔ مشترک)
mw.open_screen("REPORTS_TRIAL_BALANCE"); app.processEvents()
tb = mw._screens["report_trial_balance"]
check(tb.columns_button.isVisibleTo(tb) and tb.csv_text().splitlines()[0] == ",".join(tb._export_data()[0]),
      "CSV و انتخاب ستون در گزارش‌های دیگر (تراز آزمایشی) هم هست")

print("RESULT:", "ALL PASS" if not FAIL else "SOME FAILED")
sys.exit(1 if FAIL else 0)
