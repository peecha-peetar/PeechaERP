import os, sys, datetime, decimal, io
os.environ["PEECHA_DB_NAME"] = "peecha_test_r244_1"
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
from peecha import numerals
from peecha.services import procurement_masters as masters
from peecha.services import purchase_requests as prs
from peecha.services import purchase_budgets as budgets
from peecha.services import report_views as views
from peecha.services import hr as hr_service
from peecha.services import users as users_service
from sqlalchemy import text
F = pr.PurchaseFilters(today - dt.timedelta(days=60), today)
def rows(code, **kw):
    return pr.run_report(company_id, code, dataclasses.replace(F, **kw)).rows
doc_of = lambda d: documents_service.get_document(d, company_id)[0]
uid = user.user_id

# --- ۰) migration افزایشی
with new_session() as s_:
    cols = s_.execute(text("SELECT table_name, column_name, is_nullable FROM information_schema.columns WHERE column_name IN "
                           "('branch_id','org_unit_id') AND table_schema IN ('comm','inv')")).all()
new_cols = [c for c in cols if c[0] != "branches" and not (c[0] == "warehouses" and c[1] == "org_unit_id")]
check(len(new_cols) == 7 and all(c[2] == "YES" for c in new_cols), f"ستون‌های تازهٔ شعبه/دپارتمان nullable (got {new_cols})")
check(doc_of(po1).branch_id is None, "اسناد قبلی بدون شعبه")

# --- ۱) شعبه و دپارتمان
b_t = masters.save_branch(company_id, "thr", "شعبهٔ تهران")
b_s = masters.save_branch(company_id, "SHZ", "شعبهٔ شیراز")
check(raises(lambda: masters.save_branch(company_id, "THR", "تکراری")), "کد تکراری شعبه رد شد")
masters.set_warehouse_branch(company_id, wh, b_t)
dep = hr_service.create_org_unit(company_id, "PRD", "تولید", None, None)
check([d.org_unit_id for d in masters.list_departments(company_id)] == [dep], "دپارتمان از واحدهای سازمانی")
po_a, _ = dated("PURCHASE_ORDER", bolt, 4, s1, 100, today)
check(doc_of(po_a).branch_id == b_t, "سند بدون شعبه، شعبهٔ انبار را گرفت")
hf = dataclasses.replace(HF(s2), branch_id=b_s, org_unit_id=dep)
po_b = documents_service.create_document(company_id, uid, "PURCHASE_ORDER", today, hf)
documents_service.add_line(po_b, company_id, bolt, pcs, D(3), D(3), unit_price=D(90))
check(doc_of(po_b).branch_id == b_s and doc_of(po_b).org_unit_id == dep, "شعبه و دپارتمان صریح")
documents_service.confirm_document(po_b, company_id, uid)
documents_service.post_document(po_b, company_id, uid)
documents_service.approve_warehouse(po_b, company_id, uid, warehouse_id=wh)
inv_b = documents_service.convert_to_invoice(po_b, company_id, uid, today)
check(doc_of(inv_b).branch_id == b_s and doc_of(inv_b).org_unit_id == dep, "شعبه/دپارتمان به فاکتور منتقل شد")
post_invoice(inv_b)

# درخواستِ خرید → سفارش
req = prs.create_request(company_id, uid, prs.RequestFields(request_date=today, branch_id=b_s, org_unit_id=dep))
prs.add_line(req, company_id, bolt, pcs, D(2), None, s1, D(100))
prs.submit_request(req, company_id); prs.approve_request(req, company_id, uid)
po_r = prs.convert_to_orders(req, company_id, uid)[0]
check(doc_of(po_r).branch_id == b_s and doc_of(po_r).org_unit_id == dep, "شعبه/دپارتمان درخواست به سفارش")

# --- ۲) بودجه به تفکیکِ شعبه/دپارتمان
bud = budgets.save_budget(company_id, budgets.BudgetFields("SHZ", "بودجهٔ شیراز", today - dt.timedelta(days=5), today + dt.timedelta(days=30),
                                                           D(1000), branch_id=b_s))
u = budgets.usages(company_id)[0]
check(u.actual == 270 and u.commitment == 0 and u.pipeline == 200, f"بودجهٔ شعبه: فقط اسناد شیراز؛ سفارش پیش‌نویس هنوز «در جریان» (got {u.actual}, {u.commitment}, {u.pipeline})")
documents_service.confirm_document(po_r, company_id, uid)
u = budgets.usages(company_id)[0]
check(u.commitment == 200 and u.pipeline == 0, "پس از تایید سفارش: تعهد")
bd = budgets.save_budget(company_id, budgets.BudgetFields("PRD", "بودجهٔ تولید", today - dt.timedelta(days=5), today + dt.timedelta(days=30),
                                                          D(100), org_unit_id=dep))
check(any("تولید" in w for w in budgets.warnings_for_document(po_r, company_id)), "هشدار بودجهٔ دپارتمان")
r = {x[0]: x for x in rows("BUDGET_BY_DIMENSION", options={"dimension": "BRANCH"})}
check(r["SHZ — شعبهٔ شیراز"][2] == 1000, f"بودجه به تفکیک شعبه (got {r})")
check(any("شیراز" in x[1] for x in rows("BUDGET_VS_ACTUAL")), "دامنهٔ بودجه شامل شعبه")

# --- ۳) گزارش‌ها
r = {x[0]: x for x in rows("BY_DIMENSION", options={"dimension": "BRANCH"})}
check(r["SHZ — شعبهٔ شیراز"][3] == 270 and "— بدون شعبه —" in r, f"خرید به تفکیک شعبه (got {list(r)})")
r = {x[0]: x for x in rows("BY_DIMENSION", options={"dimension": "DEPARTMENT"})}
check(r["PRD — تولید"][3] == 270, "خرید به تفکیک دپارتمان")
r = rows("PR_BY_REQUESTER", options={"group": "DEPARTMENT"})
check(r[0][0] == "PRD — تولید" and r[0][1] == 1, f"درخواست‌ها به تفکیک دپارتمان (got {r})")

# --- ۴) نماهایِ مشترک
other = users_service.create_user("buyer2", "خریدار دوم", "secret123", None, None, False, [company_id], company_id)
vid = views.save_view(company_id, "PURCHASE/OPEN_PO", uid, "نمای عمومی", {"group": 2}, is_shared=True)
views.save_view(company_id, "PURCHASE/OPEN_PO", uid, "نمای شخصی", {"group": None})
seen = {v.name: v for v in views.list_views(company_id, "PURCHASE/OPEN_PO", other.user_id)}
check(set(seen) == {"نمای عمومی"} and not seen["نمای عمومی"].is_mine, "کاربر دیگر فقط نمای اشتراکی را می‌بیند")
check(raises(lambda: views.delete_view(company_id, vid, other.user_id)), "حذف نمای دیگران رد شد")
views.save_view(company_id, "PURCHASE/OPEN_PO", uid, "نمای عمومی", {"group": 3}, is_shared=True)
check(len(views.list_views(company_id, "PURCHASE/OPEN_PO", uid)) == 2, "ذخیرهٔ دوباره، نما را به‌روز می‌کند")

# --- ۵) UI
from peecha import nav_catalog
menu_codes = [e[0] for _g, _l, entries in nav_catalog.PURCHASE_REPORT_MENU for e in entries if not isinstance(e, dict)]
check(sorted(menu_codes) == sorted(x.code for x in pr.REPORTS), "منوی گزارش‌ها هم‌خوان")
from peecha.ui.shell_window import MainWindow
mw = MainWindow(); mw.resize(1400, 900); mw.show(); app.processEvents()
mw.open_screen("PURCH_MASTERS"); app.processEvents()
bt = mw._screens["procurement_masters"].branches_tab
check(bt.table.rowCount() == 2 and "مرکزی" in bt.table.item(0, 3).text() + bt.table.item(1, 3).text(), "تب شعبه‌ها با انبارهای هر شعبه")
bt.warehouse_combo.setCurrentIndex(bt.warehouse_combo.findData(wh)); bt.assign_branch_combo.setCurrentIndex(bt.assign_branch_combo.findData(b_s))
bt.assign_warehouse()
with new_session() as s_:
    from peecha.db.models.inventory import Warehouse
    check(s_.get(Warehouse, wh).branch_id == b_s, "اختصاص انبار به شعبه از فرم")
mw.open_screen("PURCH_ORDER", then=lambda s_: s_.edit_document(po_b)); app.processEvents()
form = mw._screens["commercial_document_purchase_order"]
check(form.org_box.isVisibleTo(form) and form.branch_combo.currentData() == b_s and form.department_combo.currentData() == dep,
      "شعبه/دپارتمان در فرم سفارش")
mw.open_screen("SALES_INVOICE"); app.processEvents()
si = mw._screens["commercial_document_sales_invoice"]
check(not si.org_box.isVisibleTo(si), "شعبه/دپارتمان در فرم فروش نیست")
mw.open_screen("PURCH_REQUESTS", then=lambda s_: s_.edit_document(req)); app.processEvents()
pf = mw._screens["purchase_requests"]
check(pf.branch_combo.currentData() == b_s and pf.department_combo.currentData() == dep, "شعبه/دپارتمان در فرم درخواست")
mw.open_screen("PURCH_RPT_OPEN_PO"); app.processEvents()
op = mw._screens["purchase_report_open_po"]
check(op.view_combo.findData("نمای عمومی") > 0, "نماهای پایگاه‌داده در صفحهٔ گزارش")
op.shared_check.setChecked(False); op.save_view("از صفحه")
check(any(v.name == "از صفحه" and not v.is_shared for v in views.list_views(company_id, "PURCHASE/OPEN_PO", uid)), "ذخیرهٔ نما از صفحه")
sess.current_user = other
op._reload_views()
labels = [op.view_combo.itemData(i) for i in range(op.view_combo.count())]
check(any(l and l.startswith("نمای عمومی (اشتراکی") for l in labels) and "از صفحه" not in labels, f"نمای اشتراکی برای کاربر دیگر (got {labels})")
shared_label = next(l for l in labels if l and l.startswith("نمای عمومی"))
op.delete_view(shared_label)
check(any(v.name == "نمای عمومی" for v in views.list_views(company_id, "PURCHASE/OPEN_PO", uid)), "کاربر دیگر نتوانست نمای اشتراکی را حذف کند")
sess.current_user = user
op._reload_views(); op.delete_view("از صفحه")
check(op.view_combo.findData("از صفحه") < 0, "حذف نمای خود")

print("RESULT:", "ALL PASS" if not FAIL else "SOME FAILED")
sys.exit(1 if FAIL else 0)
