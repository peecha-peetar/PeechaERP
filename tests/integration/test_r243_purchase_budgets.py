import os, sys, datetime, decimal, io
os.environ["PEECHA_DB_NAME"] = "peecha_test_r243_1"
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
from peecha import numerals
from peecha.services import purchase_budgets as budgets
from peecha.services import purchase_requests as prs
F = pr.PurchaseFilters(today - dt.timedelta(days=60), today)
def rows(code, **kw):
    return pr.run_report(company_id, code, dataclasses.replace(F, **kw)).rows
uid = user.user_id
BF = budgets.BudgetFields

# --- ۱) تعریف و اعتبارسنجی
check(raises(lambda: budgets.save_budget(company_id, BF("X", "x", today, today - dt.timedelta(days=1), D(1)))), "دورهٔ معکوس رد شد")
check(raises(lambda: budgets.save_budget(company_id, BF("X", "x", today, today, D(-5)))), "مبلغِ منفی رد شد")
cat = catalog_service.create_category(company_id, "RAW", "مواد اولیه")
raw = catalog_service.create_item(company_id, "R-1", "مادهٔ اولیه", catalog_service.ItemFields(item_kind_code="GOOD", base_uom_id=pcs, category_id=cat))
a_id = budgets.save_budget(company_id, BF("ALL", "بودجهٔ کلِ خرید", today - dt.timedelta(days=30), today + dt.timedelta(days=300), D(20000),
                                          warn_percent=D(85)))
c_id = budgets.save_budget(company_id, BF("RAW", "بودجهٔ مواد اولیه", today - dt.timedelta(days=30), today + dt.timedelta(days=300), D(1000),
                                          category_id=cat))
check(raises(lambda: budgets.save_budget(company_id, BF("all", "تکراری", today, today, D(1)))), "کدِ تکراری رد شد")

# --- ۲) مصرف: واقعی، تعهد، در جریان
u = {x.budget.budget_id: x for x in budgets.usages(company_id)}
A = u[a_id]
check(A.actual == 80 * 110 + 30 * 95 - 550 and A.commitment == 2000 + 3000 + 1800, f"بودجهٔ کل: واقعی ۱۱۱۰۰، تعهد ۶۸۰۰ (got {A.actual}, {A.commitment})")
check(A.state == "WARN" and u[c_id].consumed == 0, f"وضعیتِ هشدار (۸۹.۵٪ ≥ ۸۵٪) (got {A.used_percent})")
po_raw, _ = dated("PURCHASE_ORDER", raw, 10, s1, 150, today)
documents_service.confirm_document(po_raw, company_id, uid)
req = prs.create_request(company_id, uid, prs.RequestFields(request_date=today))
prs.add_line(req, company_id, raw, pcs, D(5), None, s1, D(100))
prs.submit_request(req, company_id); prs.approve_request(req, company_id, uid)
u = {x.budget.budget_id: x for x in budgets.usages(company_id)}
check(u[c_id].commitment == 1500 and u[c_id].state == "OVER" and u[c_id].pipeline == 500, f"بودجهٔ گروهِ کالا: عبور (got {u[c_id].commitment}, {u[c_id].state})")
check(u[a_id].consumed == 11100 + 6800 + 1500, "بودجهٔ کل شاملِ سفارشِ جدید")
w = budgets.warnings_for_document(po_raw, company_id)
check(len(w) == 2 and any("عبور از بودجه" in x for x in w), f"هشدارِ بودجه برایِ سند (got {w})")
check(budgets.warnings_for_document(po1, company_id) and len(budgets.warnings_for_document(po1, company_id)) == 1, "سندِ خارج از گروه فقط بودجهٔ کل")

# --- ۳) گزارش‌ها
r = {x[0][:3]: x for x in rows("BUDGET_VS_ACTUAL")}
check(r["ALL"][5] == 11100 and r["ALL"][6] == 8300 and r["RAW"][12] == "عبور از بودجه" and r["RAW"][10] == 500 and r["RAW"][11] == 1000 - 1500 - 500,
      f"بودجه در برابرِ واقعی (got {r['RAW']})")
check(len(rows("BUDGET_OVERRUN")) == 2 and len(rows("BUDGET_OVERRUN", options={"view": "OVER"})) == 1, "بودجه‌هایِ عبورکرده")
r = {x[0]: x for x in rows("BUDGET_BY_DIMENSION", options={"dimension": "CATEGORY"})}
check(r["RAW — مواد اولیه"][2] == 1000 and r["— بدونِ این بُعد —"][2] == 20000, f"بودجه به تفکیکِ گروه (got {r})")
m = [x for x in rows("BUDGET_MONTHLY") if x[0].startswith("ALL")]
check(abs(sum(x[2] for x in m) - 20000) <= 1 and m[-1][6] == 11100, f"روندِ ماهانه: جمعِ بودجهٔ ماه‌ها = بودجه (got {sum(x[2] for x in m)})")
check(len(rows("BUDGET_COMMITMENTS")) == 3 + 2 and len(rows("BUDGET_PIPELINE")) == 2, "تعهدات و درخواست‌هایِ در جریان")
check(sum(x[6] for x in rows("BUDGET_ACTUALS") if x[0] == "بودجهٔ کلِ خرید") == 11100, "ریزِ مصرفِ واقعی")
fc = {x[0][:3]: x for x in rows("BUDGET_FORECAST")}
check(fc["ALL"][3] == 31 and fc["ALL"][4] == 331 and fc["ALL"][6] == (D(11100) * 331 / 31).quantize(D("0.01")), f"پیش‌بینیِ بودجه (got {fc['ALL']})")
r = rows("UNBUDGETED")
check(len(r) == 1 and r[0][2] == today - dt.timedelta(days=45), f"خریدِ خارج از بودجه: فقط فاکتورِ پیش از دوره (got {r})")

# --- ۴) UI
from peecha import nav_catalog
menu_codes = [e[0] for _g, _l, entries in nav_catalog.PURCHASE_REPORT_MENU for e in entries if not isinstance(e, dict)]
check(sorted(menu_codes) == sorted(x.code for x in pr.REPORTS), "منویِ گزارش‌ها هم‌خوان")
from peecha.ui.shell_window import MainWindow
mw = MainWindow(); mw.resize(1400, 900); mw.show(); app.processEvents()
mw.open_screen("PURCH_MASTERS"); app.processEvents()
bt = mw._screens["procurement_masters"].budgets_tab
check(bt.table.rowCount() == 2, "جدولِ بودجه‌ها")
bt.clear_form(); bt.code_field.setText("Q1"); bt.name_field.setText("فصلِ اول"); bt.amount_field.setText("۵۰۰۰")
bt.to_field.setDate(today - dt.timedelta(days=400)); bt.save()
check(bt.table.rowCount() == 2, "بودجهٔ نامعتبر از فرم ذخیره نشد")
bt.to_field.setDate(today + dt.timedelta(days=90)); bt.save()
check(bt.table.rowCount() == 3, "ثبتِ بودجه از فرم")
bt.table.selectRow(2); app.processEvents()
check(bt.name_field.text() == "فصلِ اول" and bt.amount_field.text() == "۵۰۰۰", "بارگذاریِ بودجه در فرم")
mw.open_screen("PURCH_ORDER", then=lambda s_: s_.edit_document(po_raw)); app.processEvents()
form = mw._screens["commercial_document_purchase_order"]
check(len(form._budget_warnings()) == 3, "هشدارِ بودجه در فرمِ سفارش")
for code in ("BUDGET_VS_ACTUAL", "BUDGET_OVERRUN", "BUDGET_BY_DIMENSION", "BUDGET_MONTHLY", "BUDGET_ACTUALS", "BUDGET_COMMITMENTS",
             "BUDGET_PIPELINE", "BUDGET_FORECAST", "UNBUDGETED"):
    mw.open_screen(f"PURCH_RPT_{code}"); app.processEvents()
    rs = mw._screens[f"purchase_report_{code.lower()}"]
    rs.date_from.setDate(today - dt.timedelta(days=60)); rs._reload()
    check(rs.table.columnCount() > 0, f"گزارشِ {code} از منو")

print("RESULT:", "ALL PASS" if not FAIL else "SOME FAILED")
sys.exit(1 if FAIL else 0)
