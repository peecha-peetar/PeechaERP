import os, sys, datetime, decimal, io
os.environ["PEECHA_DB_NAME"] = "peecha_test_r234_1"
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

import dataclasses
from peecha.services import commercial_purchasing as purchasing_service
from peecha.services import inventory_extended as extended_service
from peecha.services import commercial_pos as pos_service
F = pr.PurchaseFilters(today - dt.timedelta(days=60), today)
def run(code, **kw):
    return pr.run_report(company_id, code, dataclasses.replace(F, **kw))
def rows(code, **kw):
    return run(code, **kw).rows

# --- دادهٔ تکمیلیِ فاز ۲
po1_doc = documents_service.get_document(po1, company_id)[0]
with new_session() as s_:
    from peecha.db.models.commercial import CommercialDocument as CD
    for doc_id, req in ((po1, d10 + dt.timedelta(days=3)), (po3, today), (po2, today - dt.timedelta(days=2))):
        s_.get(CD, doc_id).requested_delivery_date = req
    s_.commit()
cat_a = catalog_service.create_category(company_id, "CAT-A", "قطعات")
nut = catalog_service.create_item(company_id, "N-2", "مهره", catalog_service.ItemFields(item_kind_code="GOOD", base_uom_id=pcs, category_id=cat_a))
cc_dim = dimensions_service.get_specialized_dimension_type_id(company_id, dimensions_service.COST_CENTER_CODE)
cc = dimensions_service.create_detail_account(company_id, cc_dim, "CC-1", "تولید")
cc = getattr(cc, "detail_account_id", cc)
ni, _ = dated("PURCHASE_INVOICE", nut, 10, s1, 50, today)
with new_session() as s_:
    s_.get(CD, ni).cost_center_detail_account_id = cc
    s_.commit()
purchasing_service.add_landed_cost_line(ni, D(100), cash_gl.account_id, notes="کرایه")
ag = purchasing_service.create_rebate_agreement(s1, "FLAT_PERCENT", today - dt.timedelta(days=30))
purchasing_service.add_rebate_tier(ag, D(0), D(2))
post_invoice(ni)
purchasing_service.accrue_rebate_for_invoice(ni, company_id, today.replace(day=1), today)
cin, _ = dated("CONSIGNMENT_IN", nut, 8, s2, 40, today)
documents_service.confirm_document(cin, company_id, user.user_id)
documents_service.post_document(cin, company_id, user.user_id)
extended_service.add_item_supplier(nut, s1, supplier_sku="SKU-N", lead_time_days=4, is_preferred=True)
csettings_service.set_feature_enabled(company_id, "ALLOW_EDIT_POSTED_INVOICE", True)
engine_service.set_account_mapping(company_id, "INVENTORY_COST_VARIANCE", adj_gl.account_id)
corr = documents_service.start_invoice_correction(direct, company_id, user.user_id)
corr_line = documents_service.get_document(corr, company_id)[1][0]
documents_service.update_line(corr_line.line_id, corr, company_id, D(30), D(97))
documents_service.confirm_document(corr, company_id, user.user_id)
documents_service.post_invoice_correction(corr, company_id, user.user_id)

# --- بررسی‌ها
r = rows("OVERDUE")
po2_no = documents_service.get_document(po2, company_id)[0].document_no
o = next(x for x in r if x[0] == po2_no)
check(o[8] == 20 and o[10] == 2 and o[11] == "معوق", f"۲) سفارش ۲: ۲۰ عدد، ۲ روز معوق (got {o[8:12]})")
r = rows("CONSIGNMENTS")
check(len(r) == 1 and r[0][8] == 8, f"۶) امانی تسویه‌نشده ۸ عدد (got {r})")
r = rows("RETURNS")
check(len(r) == 1 and r[0][5] == 5, "۷) برگشت به تامین‌کننده")
r = rows("BY_CATEGORY")
check(any("قطعات" in x[0] and x[5] == 500 for x in r) and any(x[0] == "بدون گروه" for x in r), f"۱۰) خرید به تفکیک گروه (got {r})")
r = rows("BY_COST_CENTER")
check(any("تولید" in x[0] and x[4] == 500 for x in r), "۱۱) خرید به تفکیک مرکز هزینه")
r = rows("MONTHLY")
check(len(r) >= 1 and sum(x[5] for x in r) > 0, "۱۲) روند ماهانه")
r = rows("ABC")
check(r[0][5] == "A" and r[0][4] <= 100 and abs(r[-1][4] - 100) < D("0.01"), f"۱۳) ABC با سهم تجمعی ۱۰۰٪ (got {r})")
r = rows("CONCENTRATION")
check(any("مهره" in x[0] and x[6] == "تک‌منبعی" and x[2] == 1 for x in r), "۱۴) مهره تک‌منبعی است")
r = rows("CORRECTIONS")
check(len(r) == 1 and r[0][6] == 30 * 2, f"۱۸) اصلاحیه: اختلاف ۶۰ (got {r})")
r = rows("LANDED_COST")
check(len(r) == 1 and r[0][4] == 100 and r[0][6] == 20, f"۱۹) هزینهٔ جانبی ۱۰۰ = ۲۰٪ کالا (got {r})")
r = rows("SAVINGS")
s1_row = next(x for x in r if "یک" in x[0])
check(s1_row[4] == 10, f"۲۰) تخفیف حجمی معوق ۲٪ روی ۵۰۰ (got {s1_row})")
r = rows("OTD")
s1_otd = next(x for x in r if "یک" in x[0])
check(s1_otd[1] == 2 and s1_otd[2] == 1 and s1_otd[3] == 1, f"۲۲) S1: یک به‌موقع و یک با تاخیر (got {s1_otd})")
r = rows("QUALITY")
q1 = next(x for x in r if "یک" in x[0])
check(q1[2] == 5 and q1[3] > 0, "۲۴) نرخ برگشت S1")
r = rows("SCORECARD")
check(all(x[7] for x in r if x[6] is not None) and len(r) == 2, f"۲۱) کارنامه برای دو تامین‌کننده (got {r})")
r = rows("FORECAST")
check(len(r) >= 3 and r[-1][6] == sum(x[5] for x in r), "۲۸) پیش‌بینی پرداخت با جمع تجمعی")
r = rows("PREPAYMENTS")
check(isinstance(r, list), "۳۰) پیش‌پرداخت‌ها اجرا شد")
r = rows("ITEMS")
nut_row = next(x for x in r if x[0] == "N-2")
check(nut_row[2] == "قطعات" and "یک" in nut_row[8] and nut_row[9] == 50, f"۳۲) کالای قابل‌خرید (got {nut_row})")
r = rows("PRICE_LISTS")
check(any(x[8] == "SKU-N" and x[10] == "★" for x in r), "۳۳) تامین‌کنندهٔ ترجیحی کالا")
r = rows("REBATES")
check(len(r) == 1 and r[0][7] == 10, f"۳۴) قرارداد تخفیف حجمی با ۱۰ معوق (got {r})")
r = rows("WAREHOUSES")
check(len(r) >= 1 and r[0][7] >= 1, f"۳۵) انبار با رسید در انتظار (got {r})")

# --- منو و UI
from peecha import nav_catalog
menu_codes = [e[0] for _g, _l, items in nav_catalog.PURCHASE_REPORT_MENU for e in items if not isinstance(e, dict)]
check(sorted(menu_codes) == sorted(r.code for r in pr.REPORTS), "منو و سرویس هم‌خوان")
from peecha.ui.shell_window import MainWindow
mw = MainWindow(); mw.resize(1300, 850); mw.show(); app.processEvents()
failed = []
for rep in pr.REPORTS:
    mw.open_screen(f"PURCH_RPT_{rep.code}"); app.processEvents()
    scr = mw._screens[f"purchase_report_{rep.code.lower()}"]
    scr.date_from.setDate(today - dt.timedelta(days=60)); scr._reload()
    if scr.table.columnCount() == 0:
        failed.append(rep.code)
check(not failed, f"همهٔ ۳۵ گزارش از منو باز و اجرا شدند (failed {failed})")
od = mw._screens["purchase_report_overdue"]
check(not od.date_from.isVisibleTo(od) and od.date_to.isVisibleTo(od), "گزارش «تا تاریخ»: فقط فیلد تا تاریخ")
po_screen = mw._screens["commercial_document_purchase_order"]
po_screen.refresh(); po_screen.edit_document(po2); app.processEvents()
check(po_screen.delivery_date_box.isVisibleTo(po_screen) and po_screen.delivery_date_field.date() == today - dt.timedelta(days=2),
      "فیلد «تاریخ تحویل مورد انتظار» در فرم سفارش خرید")

print("RESULT:", "ALL PASS" if not FAIL else "SOME FAILED")
sys.exit(1 if FAIL else 0)
