import os, sys, datetime, decimal, io
os.environ["PEECHA_DB_NAME"] = "peecha_test_r241_1"
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
from peecha.services import procurement_masters as masters
F = pr.PurchaseFilters(today - dt.timedelta(days=60), today)
def rows(code, **kw):
    return pr.run_report(company_id, code, dataclasses.replace(F, **kw)).rows
doc_of = lambda d: documents_service.get_document(d, company_id)
uid = user.user_id
emergency = next(t.purchase_type_id for t in masters.list_purchase_types(company_id) if t.code == "EMERGENCY")
RF = lambda **kw: prs.RequestFields(request_date=today, required_date=today + dt.timedelta(days=10), warehouse_id=wh, **kw)

# --- ۱) ثبت و اعتبارسنجی
req = prs.create_request(company_id, uid, RF(priority_code="URGENT", purchase_type_id=emergency, description="نیازِ کارگاه"))
check(raises(lambda: prs.submit_request(req, company_id)), "ارسالِ درخواستِ بدونِ ردیف رد شد")
check(raises(lambda: prs.create_request(company_id, uid, prs.RequestFields(request_date=today, required_date=today - dt.timedelta(days=1)))),
      "تاریخِ نیازِ پیش از تاریخِ درخواست رد شد")
l1 = prs.add_line(req, company_id, bolt, pcs, D(50), today + dt.timedelta(days=5), s1, D(100))
l2 = prs.add_line(req, company_id, plain, pcs, D(8), None, s2, D(40))
check(raises(lambda: prs.add_line(req, company_id, bolt, pcs, D(0))), "مقدارِ صفر رد شد")
prs.update_line(l2, req, company_id, D(10), None, s2, D(40))
row, lines = prs.get_request(req, company_id)
check(row.request_no == 1 and len(lines) == 2 and lines[1].quantity_base == 10, "درخواست با دو ردیف")
prs.submit_request(req, company_id)
check(raises(lambda: prs.add_line(req, company_id, bolt, pcs, D(1))), "درخواستِ ارسال‌شده قابلِ‌ویرایش نیست")
check(raises(lambda: prs.convert_to_orders(req, company_id, uid)), "درخواستِ تصویب‌نشده به سفارش تبدیل نمی‌شود")
r = rows("PR_PENDING")
check(len(r) == 1 and r[0][0] == 1 and r[0][5] == 50 * 100 + 10 * 40, f"منتظرِ تصویب با ارزشِ برآوردی (got {r})")
prs.approve_request(req, company_id, uid)
check(prs.get_request(req, company_id)[0].approved_by_user_id == uid, "تصویب‌کننده ثبت شد")

# --- ۲) تبدیلِ بخشی و کامل
po_a = prs.convert_to_orders(req, company_id, uid, quantities={l1: D(30)})
check(len(po_a) == 1, "سفارشِ بخشی: یک سفارش")
d, ls = doc_of(po_a[0])
check(d.counterparty_detail_account_id == s1 and ls[0].quantity == 30 and ls[0].purchase_request_line_id == l1
      and ls[0].expected_delivery_date == today + dt.timedelta(days=5) and d.purchase_type_id == emergency
      and d.requested_delivery_date == today + dt.timedelta(days=10) and ls[0].unit_price == 100,
      "سفارش: تامین‌کننده، مقدار، پیوند، تاریخِ تحویل، نوعِ خرید و فی از درخواست")
check(raises(lambda: prs.convert_to_orders(req, company_id, uid, quantities={l1: D(25)})), "سفارش بیش از مانده رد شد")
ordered = prs.ordered_quantities([l1, l2])
check(prs.fulfilment(lines, ordered) == "PARTIAL", "وضعیتِ سفارش: ناقص")
r = {x[2]: x for x in rows("PR_NOT_ORDERED")}
check(len(r) == 2 and r["B-1 — پیچ"][6] == 20, f"ماندهٔ سفارش‌نشده (got {r})")
po_b = prs.convert_to_orders(req, company_id, uid)
check(len(po_b) == 2 and {doc_of(x)[0].counterparty_detail_account_id for x in po_b} == {s1, s2}, "تبدیلِ مانده: یک سفارش برایِ هر تامین‌کننده")
ordered = prs.ordered_quantities([l1, l2])
check(prs.fulfilment(lines, ordered) == "FULL" and ordered[l1] == 50, "کاملاً سفارش شده")
check(raises(lambda: prs.convert_to_orders(req, company_id, uid)), "ماندهٔ قابلِ‌سفارش وجود ندارد")
check(raises(lambda: prs.cancel_request(req, company_id)), "لغوِ درخواستِ دارایِ سفارش رد شد")
documents_service.cancel_document(po_b[0], company_id)
ordered = prs.ordered_quantities([l1, l2])
check(prs.fulfilment(lines, ordered) == "PARTIAL", "با لغوِ سفارش، مانده برمی‌گردد")
check(len(prs.linked_orders(req)) == 3, "سفارش‌هایِ مرتبط")

# --- ۳) رد و لغو
req2 = prs.create_request(company_id, uid, RF())
prs.add_line(req2, company_id, bolt, pcs, D(3), None, None, D(90))
prs.submit_request(req2, company_id)
check(raises(lambda: prs.reject_request(req2, company_id, " ")), "ردِ بدونِ علت رد شد")
prs.reject_request(req2, company_id, "بودجه نداریم")
prs.update_request(req2, company_id, RF(description="اصلاح‌شده"))
req3 = prs.create_request(company_id, uid, RF())
prs.add_line(req3, company_id, bolt, pcs, D(1))
prs.cancel_request(req3, company_id, next(r_.reason_id for r_ in masters.list_cancellation_reasons(company_id) if r_.code == "NO_NEED"))
r = {x[0]: x for x in rows("PR_REJECTED")}
check(r[2][4] == "بودجه نداریم" and r[3][4] == "رفعِ نیاز", f"درخواست‌هایِ ردشده/لغوشده با علت (got {r})")

# --- ۴) گزارش‌ها
r = {x[0]: x for x in rows("PR_REGISTER")}
check(len(r) == 3 and r[1][5] == "تصویب‌شده" and r[1][8] == "سفارشِ ناقص" and r[1][3] == "فوری", f"دفترِ درخواست‌ها (got {r[1]})")
check(r[1][9] == D(40) * 100 / 60, f"درصدِ سفارش‌شده ۴۰ از ۶۰ (got {r[1][9]})")
r = rows("PR_CYCLE")
c1 = next(x for x in r if x[0] == 1)
check(c1[6] == today and c1[10] == 0, f"چرخهٔ درخواست تا سفارش (got {c1})")
r = rows("PR_BY_REQUESTER")
check(r[0][1] == 3 and r[0][3] == 1, f"به تفکیکِ درخواست‌کننده (got {r})")
r = rows("PO_WITHOUT_PR")
check(len(r) == 3 and all(x[0] not in (doc_of(po_a[0])[0].document_no,) for x in r), f"سفارشِ بدونِ درخواست: فقط سفارش‌هایِ قبلی (got {len(r)})")
check(len(rows("PR_REGISTER", item_id=plain)) == 1, "فیلترِ کالا در درخواست‌ها")

# --- ۵) UI
from peecha import nav_catalog
menu_codes = [e[0] for _g, _l, entries in nav_catalog.PURCHASE_REPORT_MENU for e in entries if not isinstance(e, dict)]
check(sorted(menu_codes) == sorted(x.code for x in pr.REPORTS), "منویِ گزارش‌ها هم‌خوان")
from peecha.ui.shell_window import MainWindow
mw = MainWindow(); mw.resize(1400, 900); mw.show(); app.processEvents()
mw.open_screen("PURCH_REQUESTS"); app.processEvents()
scr = mw._screens["purchase_requests"]
check(scr.list_table.rowCount() == 3, "فهرستِ درخواست‌ها")
scr.new_request()
scr.description_field.setText("از فرم")
scr.item_combo.setCurrentIndex(scr.item_combo.findData(bolt)); app.processEvents()
scr.qty_field.setText("۱۲"); scr.price_field.setText("۹۵")
scr.supplier_combo.setCurrentIndex(scr.supplier_combo.findData(s2))
scr.add_line(); app.processEvents()
check(scr._request_id is not None and scr.lines_table.rowCount() == 1, "ثبتِ درخواست و ردیف از فرم")
scr.submit(); scr.approve(); app.processEvents()
check(scr._status == "APPROVED" and scr.buttons["convert"].isEnabled(), "ارسال و تصویب از فرم")
created = scr.convert(ask=False); app.processEvents()
check(len(created) == 1 and mw._screens["commercial_document_purchase_order"]._document_id == created[0], "تبدیل به سفارش و بازشدنِ سفارش")
check("سفارش‌ها" in scr.info_label.text(), "سفارش‌هایِ مرتبط در فرم")
from peecha.ui.screens.purchase_requests import ConvertToOrderDialog
for code in ("PR_REGISTER", "PR_PENDING", "PR_NOT_ORDERED", "PR_CYCLE", "PR_BY_REQUESTER", "PR_REJECTED", "PO_WITHOUT_PR"):
    mw.open_screen(f"PURCH_RPT_{code}"); app.processEvents()
    rs = mw._screens[f"purchase_report_{code.lower()}"]
    rs.date_from.setDate(today - dt.timedelta(days=60)); rs._reload()
    check(rs.table.columnCount() > 0, f"گزارشِ {code} از منو")
rs = mw._screens["purchase_report_pr_register"]; rs._reload()
rs._open_row(0, 0); app.processEvents()
first_no = int(numerals.to_ascii_digits(rs.table.item(0, 0).text()))
check(prs.get_request(scr._request_id, company_id)[0].request_no == first_no, "دابل‌کلیکِ گزارش، همان درخواست را باز کرد")

print("RESULT:", "ALL PASS" if not FAIL else "SOME FAILED")
sys.exit(1 if FAIL else 0)
