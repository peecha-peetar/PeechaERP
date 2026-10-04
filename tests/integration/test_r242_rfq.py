import os, sys, datetime, decimal, io
os.environ["PEECHA_DB_NAME"] = "peecha_test_r242_1"
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
from peecha.services import purchase_requests as prs
from peecha.services import rfqs
F = pr.PurchaseFilters(today - dt.timedelta(days=60), today)
def rows(code, **kw):
    return pr.run_report(company_id, code, dataclasses.replace(F, **kw)).rows
doc_of = lambda d: documents_service.get_document(d, company_id)
uid = user.user_id
s3 = dimensions_service.create_supplier(company_id, "S3", "تامین‌کنندهٔ سه")

# --- ۱) استعلام از درخواستِ خرید
req = prs.create_request(company_id, uid, prs.RequestFields(request_date=today, required_date=today + dt.timedelta(days=20), warehouse_id=wh))
l1 = prs.add_line(req, company_id, bolt, pcs, D(50), None, s1, D(100))
l2 = prs.add_line(req, company_id, plain, pcs, D(10), None, s2, D(50))
check(raises(lambda: rfqs.create_from_request(req, company_id, uid)), "استعلام از درخواستِ تصویب‌نشده رد شد")
prs.submit_request(req, company_id); prs.approve_request(req, company_id, uid)
rfq = rfqs.create_from_request(req, company_id, uid, today + dt.timedelta(days=3))
row, lines, sups, _q = rfqs.get_rfq(rfq, company_id)
check(len(lines) == 2 and {s.supplier_detail_account_id for s in sups} == {s1, s2} and lines[0].purchase_request_line_id == l1,
      "ردیف‌ها و تامین‌کنندگانِ پیشنهادی از درخواست")
rfqs.add_supplier(rfq, company_id, s3)
check(raises(lambda: rfqs.add_supplier(rfq, company_id, s3)), "دعوتِ تکراری رد شد")
check(raises(lambda: rfqs.record_quote(sups[0].rfq_supplier_id, lines[0].line_id, company_id, D(1))), "پیشنهاد پیش از ارسال رد شد")
rfqs.send_rfq(rfq, company_id)
check(raises(lambda: rfqs.add_line(rfq, company_id, bolt, pcs, D(1))), "ردیف به استعلامِ ارسال‌شده اضافه نمی‌شود")
sp = {s.supplier_detail_account_id: s.rfq_supplier_id for s in rfqs.get_rfq(rfq, company_id)[2]}
lb, lp = lines[0].line_id, lines[1].line_id

# --- ۲) پیشنهادها و مقایسه
rfqs.record_quote(sp[s1], lb, company_id, D(95), D(0), 5)
rfqs.record_quote(sp[s1], lp, company_id, D(45), D(0), 5)
rfqs.record_quote(sp[s2], lb, company_id, D(95), D(0), 10)
rfqs.record_quote(sp[s2], lp, company_id, D(40), D(10), 10, today + dt.timedelta(days=30))
rfqs.decline(sp[s3], company_id, "موجودی ندارد")
check(raises(lambda: rfqs.record_quote(sp[s1], lb, company_id, D(10), D(150))), "تخفیفِ بیش از ۱۰۰٪ رد شد")
cmp_ = rfqs.compare(rfq, company_id)
best = {c.line.line_id: c.supplier.supplier_detail_account_id for c in cmp_ if c.is_best}
check(best == {lb: s1, lp: s2}, f"بهترین: فیِ برابر → زمانِ تحویلِ کمتر؛ تخفیف در فیِ خالص (got {best})")
check(next(c.net for c in cmp_ if c.line.line_id == lp and c.is_best) == 36, "فیِ خالص = ۴۰ × ۹۰٪")

# --- ۳) انتخاب و سفارش
check(raises(lambda: rfqs.create_orders(rfq, company_id, uid)), "سفارش پیش از انتخابِ برنده رد شد")
q_bad = [c.quote.quote_id for c in cmp_ if c.line.line_id == lb]
check(raises(lambda: rfqs.award(rfq, company_id, uid, q_bad)), "دو برنده برایِ یک ردیف رد شد")
rfqs.award(rfq, company_id, uid)
orders = rfqs.create_orders(rfq, company_id, uid)
check(len(orders) == 2 and rfqs.get_rfq(rfq, company_id)[0].status_code == "ORDERED", "یک سفارش برایِ هر برنده")
po_s2 = next(o for o in orders if doc_of(o)[0].counterparty_detail_account_id == s2)
d, ls = doc_of(po_s2)
check(ls[0].unit_price == 40 and ls[0].discount_percent == 10 and ls[0].purchase_request_line_id == l2 and ls[0].rfq_quote_id is not None
      and d.warehouse_id == wh, "ردیفِ سفارش: فی، تخفیف، پیوند به درخواست و پیشنهاد")
_r, plines = prs.get_request(req, company_id)
check(prs.fulfilment(plines, prs.ordered_quantities([l1, l2])) == "FULL", "درخواستِ خرید کاملاً سفارش شد")
check(raises(lambda: rfqs.cancel_rfq(rfq, company_id)), "استعلامِ سفارش‌شده لغو نمی‌شود")

# استعلامِ دوم: پیشنهادِ منقضی و پاسخِ معوق
rfq2 = rfqs.create_rfq(company_id, uid, today, today + dt.timedelta(days=2), "دستی")
check(raises(lambda: rfqs.send_rfq(rfq2, company_id)), "ارسالِ استعلامِ بدونِ ردیف رد شد")
x1 = rfqs.add_line(rfq2, company_id, bolt, pcs, D(5))
rfqs.add_supplier(rfq2, company_id, s1); rfqs.add_supplier(rfq2, company_id, s2)
rfqs.send_rfq(rfq2, company_id)
sp2 = {s.supplier_detail_account_id: s.rfq_supplier_id for s in rfqs.get_rfq(rfq2, company_id)[2]}
qx = rfqs.record_quote(sp2[s1], x1, company_id, D(80), D(0), None, today - dt.timedelta(days=1))
check(raises(lambda: rfqs.award(rfq2, company_id, uid, [qx])), "انتخابِ پیشنهادِ منقضی رد شد")
check(raises(lambda: rfqs.create_rfq(company_id, uid, today, today - dt.timedelta(days=1))), "مهلتِ پاسخِ پیش از تاریخ رد شد")

# --- ۴) گزارش‌ها
r = {x[0]: x for x in rows("RFQ_REGISTER")}
check(r[1][5] == 3 and r[1][6] == 2 and r[1][7] == 1 and r[1][8] == 95 * 50 + 36 * 10, f"دفترِ استعلام‌ها (got {r[1]})")
check(len(rows("RFQ_COMPARISON")) == 5 and len(rows("RFQ_COMPARISON", options={"view": "AWARDED"})) == 2, "مقایسهٔ پیشنهادها")
r = {x[0][:2]: x for x in rows("RFQ_RESPONSE")}
check(r["S1"][1] == 2 and r["S1"][2] == 2 and r["S1"][6] == 1 and r["S3"][3] == 1 and r["S3"][4] == 0, f"پاسخ‌گوییِ تامین‌کنندگان (got {r})")
r = {x[1]: x for x in rows("RFQ_SAVINGS")}
pl = next(v for k, v in r.items() if "پارچه" in k)
check(pl[4] == 36 and pl[7] == 45 and pl[8] == 90, f"صرفه‌جوییِ استعلام (got {pl})")
r = rows("RFQ_PENDING")
check(len(r) == 1 and "دو" in r[0][4], f"پاسخِ معوق (got {r})")
check(len(rows("PO_WITHOUT_RFQ")) >= 1 and all(x[0] not in [doc_of(o)[0].document_no for o in orders] for x in rows("PO_WITHOUT_RFQ")),
      "خریدِ بدونِ استعلام")

# --- ۵) UI
from peecha import nav_catalog
menu_codes = [e[0] for _g, _l, entries in nav_catalog.PURCHASE_REPORT_MENU for e in entries if not isinstance(e, dict)]
check(sorted(menu_codes) == sorted(x.code for x in pr.REPORTS), "منویِ گزارش‌ها هم‌خوان")
from peecha.ui.shell_window import MainWindow
mw = MainWindow(); mw.resize(1400, 900); mw.show(); app.processEvents()
mw.open_screen("PURCH_RFQ"); app.processEvents()
scr = mw._screens["rfqs"]
check(scr.list_table.rowCount() == 2, "فهرستِ استعلام‌ها")
scr.new_rfq(); scr.description_field.setText("از فرم")
scr.item_combo.setCurrentIndex(scr.item_combo.findData(plain)); app.processEvents()
scr.qty_field.setText("۴"); scr.add_line()
for sid in (s1, s2):
    scr.supplier_combo.setCurrentIndex(scr.supplier_combo.findData(sid)); scr.add_supplier()
check(len(scr._lines) == 1 and len(scr._suppliers) == 2, "ردیف و دعوت از فرم")
scr.send()
line_id = scr._lines[0].line_id
scr.enter_quote([(line_id, D(30), D(0), 3, today + dt.timedelta(days=9))], scr._suppliers[0])
scr.enter_quote([(line_id, D(28), D(0), 7, today + dt.timedelta(days=9))], scr._suppliers[1])
check(scr.comparison_table.rowCount() == 2 and scr.comparison_table.item(0, 9).text() == "بهترین", "جدولِ مقایسه در فرم")
scr.award(None)
created = scr.create_orders(); app.processEvents()
check(len(created) == 1 and doc_of(created[0])[0].counterparty_detail_account_id == s2
      and mw._screens["commercial_document_purchase_order"]._document_id == created[0], "انتخابِ برنده و سفارش از فرم")
for code in ("RFQ_REGISTER", "RFQ_COMPARISON", "RFQ_RESPONSE", "RFQ_SAVINGS", "RFQ_PENDING", "PO_WITHOUT_RFQ"):
    mw.open_screen(f"PURCH_RPT_{code}"); app.processEvents()
    rs = mw._screens[f"purchase_report_{code.lower()}"]
    rs.date_from.setDate(today - dt.timedelta(days=60)); rs._reload()
    check(rs.table.columnCount() > 0, f"گزارشِ {code} از منو")
rs = mw._screens["purchase_report_rfq_register"]; rs._reload()
rs._open_row(0, 0); app.processEvents()
check(scr._rfq_id is not None and rfqs.get_rfq(scr._rfq_id, company_id)[0].rfq_no == int(numerals.to_ascii_digits(rs.table.item(0, 0).text())),
      "دابل‌کلیکِ گزارش، استعلام را باز کرد")

print("RESULT:", "ALL PASS" if not FAIL else "SOME FAILED")
sys.exit(1 if FAIL else 0)
