import os, sys, datetime, decimal, io
os.environ["PEECHA_DB_NAME"] = "peecha_test_r236_1"
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

import dataclasses, datetime as dt
from peecha.services import purchase_reports as pr
from peecha.db.models.commercial import CommercialDocument as CD
customer2 = partners_service.create_customer(company_id, "C-2", "فروشگاهِ دو", fast_track=True)
rep_id = dimensions_service.create_supplier(company_id, "R-1", "ویزیتورِ یک")
customer_group_id = next(g.person_group_id for g in dimensions_service.list_person_groups(company_id) if g.code == "CUSTOMER")
treasury_service.create_counterparty_mapping(company_id, "RECEIPT", ar_gl.account_id, person_group_id=customer_group_id)
treasury_service.set_account_mapping(company_id, "RECEIPT_CASH", cash_gl.account_id)
d10 = today - dt.timedelta(days=10)

def make(doc_type, qty, cp, price, when=today):
    d = documents_service.create_document(company_id, user.user_id, doc_type, when, HF(cp))
    documents_service.add_line(d, company_id, plain, pcs, D(qty), D(qty), unit_price=D(price))
    return d
def post(d, plan=()):
    documents_service.confirm_document(d, company_id, user.user_id)
    if documents_service.get_document(d, company_id)[0].document_type_code.endswith("_INVOICE"):
        settlements_service.auto_approve_settlement_plan(d, company_id, user.user_id, list(plan))
    documents_service.post_document(d, company_id, user.user_id)

post(make("PURCHASE_INVOICE", 20, s1, 100))            # بهایِ تمام‌شده = ۱۰۰
so = make("SALES_ORDER", 10, customer, 300, d10)
with new_session() as s_:
    s_.get(CD, so).requested_delivery_date = d10 + dt.timedelta(days=5)
    s_.commit()
post(so)
inv1 = documents_service.convert_to_invoice(so, company_id, user.user_id, today)
post(inv1)
inv2 = make("SALES_INVOICE", 5, customer2, 280)
with new_session() as s_:
    s_.get(CD, inv2).sales_rep_detail_account_id = rep_id
    s_.commit()
post(inv2, [("CASH", D(1400))])
pos_service.post_invoice_settlement_plan(company_id, user.user_id, inv2)
post(make("SALES_RETURN", 2, customer, 300))
make("SALES_PROFORMA", 3, customer2, 290)

F = pr.PurchaseFilters(today - dt.timedelta(days=30), today, side="SALES")
def run(code, **kw):
    return pr.run_report(company_id, code, dataclasses.replace(F, **kw))
def rows(code, **kw):
    return run(code, **kw).rows

r = rows("REG_INVOICE")
by_no = {x[0]: x for x in r}
inv1_no = documents_service.get_document(inv1, company_id)[0].document_no
inv2_no = documents_service.get_document(inv2, company_id)[0].document_no
check(len(r) == 2 and by_no[inv1_no][12] == 3000 and by_no[inv2_no][11] == 1400 and by_no[inv2_no][12] == 0,
      f"دفترِ فاکتورهایِ فروش: مانده/وصول‌شده (got {r})")
r = rows("REG_ORDER")
check(len(r) == 1 and r[0][11] == 100, f"دفترِ سفارش‌هایِ فروش: ۱۰۰٪ تبدیل‌شده (got {r})")
r = rows("REG_PROFORMA")
check(len(r) == 1 and r[0][3] == "پیش‌نویس" and r[0][11] == 0, f"دفترِ پیش‌فاکتورهایِ فروش (got {r})")
r = rows("REG_INVOICE_LINES")
check(len(r) == 2, "ریزِ اقلامِ فاکتورهایِ فروش")
check(len(pr.run_report(company_id, "REG_INVOICE", dataclasses.replace(F, side="PURCHASE")).rows) == 1, "دفترِ فاکتورهایِ خرید")
check(rows("OPEN_ORDERS") == [], "سفارشِ فروشِ کامل‌فاکتورشده باز نیست")
r = rows("GP_ITEM")
# بهایِ برگشت از دفترِ انبار خوانده می‌شود (برگشتِ بدونِ ارجاع فعلاً با فیِ فروش وارد انبار می‌شود)
check(r[0][3] == 3000 + 1400 - 600 and r[0][5] == r[0][3] - r[0][4] and r[0][4] < 1500, f"سودِ ناخالصِ کالا (got {r})")
gp_c = {x[0]: x for x in rows("GP_CUSTOMER")}
c1 = next(v for k, v in gp_c.items() if "C-1" in k)
check(c1[3] == 2400 and c1[5] == c1[3] - c1[4], f"سودِ ناخالصِ مشتری (got {c1})")
reps = {x[0]: x for x in rows("BY_REP")}
check(any("ویزیتور" in k and v[5] == 1400 for k, v in reps.items()) and any("بدونِ فروشنده" in k and v[5] == 2400 for k, v in reps.items()),
      f"فروش به تفکیکِ فروشنده (got {reps})")
res = run("BY_CUSTOMER")
check(res.columns[0][0] == "مشتری" and len(res.rows) == 2, f"عنوانِ ستون‌ها برایِ فروش (got {res.columns[0]})")
bal = {x[0]: x for x in rows("BALANCES")}
b1 = next(v for k, v in bal.items() if "C-1" in k)
b2 = next(v for k, v in bal.items() if "C-2" in k)
check(b1[4] == 2400 and b1[5] == "بدهکار است" and b2[4] == 0, f"ماندهٔ مشتریان (got {b1}, {b2})")
ag = rows("AGING")
check(len(ag) == 1 and ag[0][7] == 3000, f"سنی‌کردنِ مطالبات (got {ag})")
st = rows("STATEMENT", supplier_id=customer)
check(st[-1][5] == 2400, f"صورت‌حسابِ مشتری: ماندهٔ ۲۴۰۰ (got {st[-1]})")
fc = rows("FORECAST")
check(len(fc) == 1 and fc[0][5] == 3000, f"پیش‌بینیِ وصول (got {fc})")
otd = rows("OTD")
check(len(otd) == 1 and otd[0][1] == 1, f"تحویل به مشتری (got {otd})")
check(len(rows("CUSTOMERS")) == 2, "فهرستِ مشتریان")
check(any(x[0] == "N-1" for x in rows("ITEMS")), "کالاهایِ قابلِ‌فروش")

from peecha import nav_catalog
sales_codes = [e[0] for _g, _l, entries in nav_catalog.SALES_REPORT_MENU for e in entries if not isinstance(e, dict)]
check(sorted(sales_codes) == sorted(r.code for r in pr.SALES_REPORTS), "منویِ فروش با سرویس هم‌خوان")
reports_menu = next(i for i in nav_catalog.NAV_ITEMS if i["code"] == "REPORTS")
check([c["code"] for c in reports_menu["children"]][-2:] == ["REPORTS_PURCHASE", "REPORTS_SALES"], "منویِ گزارش‌ها: خرید و فروش")
purch_menu = next(i for i in nav_catalog.NAV_ITEMS if i["code"] == "PURCH")
check(not any(c["code"] == "PURCH_REPORTS" for c in purch_menu["children"]), "گزارشاتِ خرید به منویِ گزارش‌ها منتقل شد")

from peecha.ui.shell_window import MainWindow
mw = MainWindow(); mw.resize(1300, 850); mw.show(); app.processEvents()
failed = []
for rep in pr.SALES_REPORTS:
    mw.open_screen(f"SALES_RPT_{rep.code}"); app.processEvents()
    scr = mw._screens[f"sales_report_{rep.code.lower()}"]
    scr.date_from.setDate(today - dt.timedelta(days=30)); scr._reload()
    if scr.table.columnCount() == 0:
        failed.append(rep.code)
for code in ("REPORTS_SALES_BY_ITEM", "REPORTS_CUSTOMER_PROFIT", "REPORTS_SALES_FORECAST", "REPORTS_SALES_BY_CHANNEL",
             "PURCH_RPT_REG_INVOICE", "PURCH_RPT_REG_ORDER", "PURCH_RPT_REG_PROFORMA", "PURCH_RPT_OPEN_PO"):
    mw.open_screen(code); app.processEvents()
check(not failed, f"همهٔ گزارش‌هایِ فروش از منو باز و اجرا شدند (failed {failed})")
scr = mw._screens["sales_report_reg_invoice"]; scr._reload()
check(scr.supplier_combo.count() == 3 and "مشتری" in [l.text() for l in scr.findChildren(type(scr.hint_label))][0:99].__str__(),
      "فیلترِ «مشتری» در گزارش‌هایِ فروش")
scr._open_row(0, 0); app.processEvents()
check(mw._screens["commercial_document_sales_invoice"]._document_id in (inv1, inv2), "دابل‌کلیک فاکتورِ فروش را باز کرد")

print("RESULT:", "ALL PASS" if not FAIL else "SOME FAILED")
sys.exit(1 if FAIL else 0)
