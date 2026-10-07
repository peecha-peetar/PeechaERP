import os, sys, datetime, decimal, io
os.environ["PEECHA_DB_NAME"] = "peecha_test_r238_1"
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
no = lambda d: documents_service.get_document(d, company_id)[0].document_no
po1_no, po2_no, po3_no = no(po1), no(po2), no(po3)

# --- کنترل و حسابرسی (تطبیقِ سه‌طرفه)
r = rows("THREE_WAY")
tw = {x[0]: x for x in r}
check(len(r) == 3 and "رسید ناقص" in tw[po1_no][12] and "اختلاف فی" in tw[po1_no][12] and tw[po1_no][11] == 800,
      f"تطبیق سه‌طرفه: سفارش ۱ رسید ناقص + اختلاف فی ۸۰۰ (got {tw.get(po1_no)})")
check(tw[po3_no][12] == "فاکتورنشده" and tw[po2_no][12] == "منتظر رسید", "تطبیق سه‌طرفه: فاکتورنشده / منتظر رسید")
check(len(rows("THREE_WAY", options={"view": "ALL"})) == 3, "تطبیق سه‌طرفه: نمایش همه")
r = rows("NO_PO")
check(len(r) == 1 and r[0][5] == 30 * 95, f"خرید بدون سفارش: فقط فاکتور مستقیم S2 (got {r})")
check([x[0] for x in rows("INVOICE_OVER_PO")] == [po1_no], "فاکتور بیش از سفارش (فی ۱۱۰ > ۱۰۰)")
check(rows("INVOICE_NO_RECEIPT") == [] and rows("RECEIPT_OVER_PO") == [], "بدون فاکتور بی‌رسید / رسید مازاد")
check([x[0] for x in rows("PARTIAL_RECEIPT")] == [po1_no] and [x[0] for x in rows("RECEIPT_MISMATCH")] == [po1_no], "دریافت ناقص")
check([x[0] for x in rows("NO_RECEIPT")] == [po2_no], "سفارش بدون رسید")
check(sorted(x[0] for x in rows("NO_INVOICE")) == sorted([po2_no, po3_no]), "سفارش بدون فاکتور")
r = rows("CANCELLED")
check(len(r) == 1 and r[0][1] == no(po_x), f"اسناد لغوشده (got {r})")
r = rows("DOC_TRAIL")
inv1_row = next(x for x in r if x[0] == "فاکتور خرید" and x[1] == no(inv1))
check("مدیر سیستم" in inv1_row[7] and inv1_row[9] == str(po1_no) and inv1_row[10] != "", f"رد سند: ثبت‌کننده، سند مبدا، سند حسابداری (got {inv1_row})")
r = rows("USER_ACTIVITY")
check(len(r) == 1 and r[0][1] == 4 and r[0][8] == 1, f"فعالیت کاربر: ۴ سفارش، ۱ لغو (got {r})")
csettings_service.set_feature_enabled(company_id, "PURCHASE_ORDER_SKIP_APPROVAL", False)
po_w, _ = dated("PURCHASE_ORDER", bolt, 1, s1, 100, today)
documents_service.confirm_document(po_w, company_id, user.user_id)
r = rows("APPROVAL_PENDING")
check(len(r) == 1 and r[0][1] == no(po_w), f"منتظر تصویب مدیر (got {r})")
documents_service.cancel_document(po_w, company_id)
csettings_service.set_feature_enabled(company_id, "PURCHASE_ORDER_SKIP_APPROVAL", True)

# --- فرآیند
r = {x[0]: x for x in rows("PO_FLOW")}
check(r[po1_no][11] == 10 and r[po1_no][12] == 0 and r[po2_no][7] is None, f"گردش سفارش: سفارش→رسید ۱۰ روز (got {r[po1_no]})")
r = rows("CYCLE_TIME")
check(r[-1][0].startswith("—") and r[-1][2] == 10, f"زمان چرخه (got {r})")

# --- تحلیلی / قیمت
r = rows("BY_DIMENSION", options={"dimension": "WAREHOUSE"})
check(len(r) == 1 and r[0][5] == 80 * 110 + 30 * 95 - 550, f"خرید به تفکیک انبار (got {r})")
r = rows("BY_DIMENSION", options={"dimension": "PAYMENT"})
check(len(r) == 1 and r[0][0] == "نسیه", f"نقدی/نسیه (got {r})")
r = rows("PRICE_MOVERS", options={"direction": "DOWN"})
check(len(r) == 1 and r[0][3] == 95 and r[0][5] == -15, f"بیشترین کاهش قیمت (got {r})")
r = rows("PRICE_VS_REFERENCE")
check(len(r) == 1 and r[0][10] == 800, f"مرجع سفارش: اثر ۸۰۰ (got {r})")
r = rows("PRICE_VS_REFERENCE", options={"reference": "PREVIOUS", "direction": "BELOW"})
check(len(r) == 1 and r[0][10] == -450, f"مرجع خرید قبلی، پایین‌تر: ۹۵ در برابر ۱۱۰ × ۳۰ (got {r})")
r = rows("ACTUAL_COST")
check(len(r) == 1 and r[0][4] == r[0][2], f"بهای واقعی تامین = فاکتور (بدون هزینهٔ جانبی) (got {r})")

# --- تامین‌کننده
r = rows("LATE_ORDERS")
check(len(r) == 1 and r[0][0] == po2_no and r[0][5] == 3, f"سفارش دیرکرد: ۳ روز (got {r})")
check(len(rows("PRICE_STABILITY")) == 2, "ثبات قیمت")
r = rows("INACTIVE_SUPPLIERS", options={"days": "30"}, date_to=today + dt.timedelta(days=40))
check(len(r) == 2, f"تامین‌کنندگان غیرفعال پس از ۴۰ روز (got {r})")

# --- مالی
r = rows("UNPAID", options={"view": "OVERDUE"})
check(len(r) == 1 and r[0][6] == 600 and r[0][7] == 45, f"فاکتور معوق: ماندهٔ ۶۰۰، ۴۵ روز (got {r})")
check(len(rows("UNPAID", options={"view": "NOT_DUE"})) == 2, "فاکتورهای سررسیدنشده")
r = rows("PAYMENTS")
check(len(r) == 1 and r[0][3] == 400, f"پرداخت‌های خرید (got {r})")
cm = {x[0][:2]: x for x in rows("COMMITMENTS")}
check(cm["S1"][1] == 2000 and cm["S1"][2] == 3000 and cm["S1"][3] == 8800 and cm["S2"][1] == 1800 and cm["S2"][3] == 3450,
      f"تعهدات: نرسیده/فاکتورنشده/پرداخت‌نشده (got {cm})")

# --- انبار و تدارکات
r = rows("STOCK_POLICY", options={"view": "ALL"})
check(len(r) == 1 and r[0][2] == 115 and r[0][6] == 40 and r[0][8] == "سیاست کالا", f"وضعیت موجودی/سیاست (got {r})")
r = rows("DEMAND_NO_PO")
check(len(r) == 1 and r[0][4] == 400 - 115 - 40, f"تقاضای بدون پوشش: ۲۴۵ (got {r})")
r = rows("SUGGESTED")
check(len(r) == 1 and r[0][4] == 115 + 40 - 400 and r[0][7] == 500 - (115 + 40 - 400), f"پیشنهاد خرید: ۷۴۵ تا سقف ۵۰۰ (got {r})")
check(len(rows("REORDER_ANALYSIS")) == 1, "تحلیل نقطهٔ سفارش")
r = rows("SLOW_DEAD")
check(len(r) == 1 and r[0][7] == "راکد" and r[0][3] is None, f"کالای راکد (بدون فروش؛ برگشت به تامین‌کننده مصرف نیست) (got {r})")
with new_session() as s_:
    s_.query(ReorderPolicy).delete()
    from peecha.db.models.inventory import Warehouse
    s_.get(Warehouse, wh).default_reorder_point_qty = D(200)
    s_.commit()
r = rows("STOCK_POLICY")
check(len(r) == 2 and all(x[8] == "پیش‌فرض انبار" and x[4] == 200 for x in r), f"بدون سیاست کالا، پیش‌فرض انبار (got {r})")

# --- اطلاعاتِ پایه
check(len(rows("SUPPLIER_TERMS")) == 2, "شرایط تامین‌کنندگان")
check(rows("RETURN_REASONS")[0][4] == 1, "علت برگشت با تعداد استفاده")
r = {x[1]: x[2] for x in rows("APPROVAL_RULES")}
check(r["PURCHASE_ORDER_GOODS_RECEIPT"] == "روشن" and r["PURCHASE_ORDER_SKIP_POST"] == "خاموش", "قواعد تایید")
for code in ("CONTRACTS", "DISCOUNT_RULES", "LANDED_BY_TYPE"):
    run(code)

# بدونِ هیچ تغییری در داده: گزارش‌ها فقط می‌خوانند
from peecha.db.models.accounting import JournalEntry
with new_session() as s_:
    before = (s_.query(CD).count(), s_.query(JournalEntry).count())
for rep in ext.PURCHASE_EXT_REPORTS:
    run(rep.code)
with new_session() as s_:
    check((s_.query(CD).count(), s_.query(JournalEntry).count()) == before, "گزارش‌ها هیچ سند/سند حسابداری نمی‌سازند")

# --- منو و UI
from peecha import nav_catalog
menu_codes = [e[0] for _g, _l, entries in nav_catalog.PURCHASE_REPORT_MENU for e in entries if not isinstance(e, dict)]
check(sorted(menu_codes) == sorted(r_.code for r_ in pr.REPORTS) and len(menu_codes) == len(set(menu_codes)), "منوی خرید با سرویس هم‌خوان")
from peecha.ui.shell_window import MainWindow
mw = MainWindow(); mw.resize(1300, 850); mw.show(); app.processEvents()
failed = []
for rep in ext.PURCHASE_EXT_REPORTS:
    mw.open_screen(f"PURCH_RPT_{rep.code}"); app.processEvents()
    scr = mw._screens[f"purchase_report_{rep.code.lower()}"]
    scr.date_from.setDate(today - dt.timedelta(days=60)); scr._reload()
    if scr.table.columnCount() == 0:
        failed.append(rep.code)
    for _key, (_label, combo) in scr._option_combos.items():
        for i in range(combo.count()):
            combo.setCurrentIndex(i); app.processEvents()
            if scr.table.columnCount() == 0:
                failed.append(f"{rep.code}:{combo.itemData(i)}")
check(not failed, f"همهٔ گزارش‌های جدید با همهٔ گزینه‌ها از منو اجرا شدند (failed {failed})")
scr = mw._screens["purchase_report_price_vs_reference"]
for _key, (_label, c_) in scr._option_combos.items():
    c_.setCurrentIndex(0)
combo = scr._option_combos["reference"][1]
combo.setCurrentIndex(combo.findData("PREVIOUS")); app.processEvents()
check(scr.table.rowCount() == 3 and ("مرجع قیمت", "آخرین خرید قبلی") in scr.extra_filters_summary(),
      f"گزینهٔ مرجع قیمت در جدول و خلاصهٔ چاپ (rows {scr.table.rowCount()})")
scr = mw._screens["purchase_report_three_way"]; scr._reload()
scr._open_row(0, 0); app.processEvents()
check(mw._screens["commercial_document_purchase_order"]._document_id in (po1, po2, po3), "دابل‌کلیک، سفارش را باز کرد")

print("RESULT:", "ALL PASS" if not FAIL else "SOME FAILED")
sys.exit(1 if FAIL else 0)
