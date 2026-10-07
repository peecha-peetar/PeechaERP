import os, sys, datetime, decimal, io
os.environ["PEECHA_DB_NAME"] = "peecha_test_r240_1"
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
from peecha import numerals
from peecha.services import procurement_masters as masters
from peecha.db.models.commercial import CommercialDocument as CD, DocumentChangeLog
from sqlalchemy import text
F = pr.PurchaseFilters(today - dt.timedelta(days=60), today)
def run(code, **kw):
    return pr.run_report(company_id, code, dataclasses.replace(F, **kw))
def rows(code, **kw):
    return run(code, **kw).rows
no = lambda d: documents_service.get_document(d, company_id)[0].document_no
doc_of = lambda d: documents_service.get_document(d, company_id)[0]

# --- ۰) migration فقط افزایشی: ستون‌هایِ تازه nullable، دادهٔ قبلی دست‌نخورده
with new_session() as s_:
    cols = {r[0]: r[1] for r in s_.execute(text(
        "SELECT column_name, is_nullable FROM information_schema.columns WHERE table_schema='comm' "
        "AND table_name IN ('commercial_documents','commercial_document_lines') AND column_name IN "
        "('expected_delivery_date','purchase_type_id','cancellation_reason_id','approved_by_user_id','cancelled_at')"))}
check(len(cols) == 5 and set(cols.values()) == {"YES"}, f"ستون‌های تازه nullable (got {cols})")
check(doc_of(po1).purchase_type_id is None and doc_of(po1).status_code == "POSTED", "اسناد قبلی بدون تغییر")

# --- ۱) اطلاعاتِ پایه
types = {t.code: t for t in masters.list_purchase_types(company_id)}
check(set(types) == {"PLANNED", "EMERGENCY"} and types["EMERGENCY"].is_emergency, "انواع خرید پیش‌فرض")
reasons = {r.code: r for r in masters.list_cancellation_reasons(company_id)}
check(len(reasons) == 6 and "PRICE" in reasons, "علت‌های لغو پیش‌فرض")
masters.save_purchase_type(company_id, "project", "خرید پروژه")
check(raises(lambda: masters.save_purchase_type(company_id, "PROJECT", "تکراری")), "کد تکراری نوع خرید رد شد")
check(raises(lambda: masters.save_cancellation_reason(company_id, "", "بی‌کد")), "علت بدون کد رد شد")

# --- ۲) نوعِ خرید رویِ سند و انتقال به فاکتور
emergency = types["EMERGENCY"].purchase_type_id
hf = dataclasses.replace(HF(s2), purchase_type_id=emergency)
po_e = documents_service.create_document(company_id, user.user_id, "PURCHASE_ORDER", today, hf)
po_e_line = documents_service.add_line(po_e, company_id, bolt, pcs, D(10), D(10), unit_price=D(90),
                                       expected_delivery_date=today - dt.timedelta(days=2))
documents_service.confirm_document(po_e, company_id, user.user_id)
check(doc_of(po_e).purchase_type_id == emergency, "نوع خرید روی سفارش ذخیره شد")
r = rows("EMERGENCY")
check(len(r) == 1 and r[0][1] == no(po_e), f"گزارش خریدهای اضطراری (got {r})")

# --- ۳) تاریخچه: تایید → بازگشت → ویرایش → تایید → تصویب
documents_service.revert_to_draft(po_e, company_id)
documents_service.update_line(po_e_line, po_e, company_id, D(12), D(95))
documents_service.update_document_header(po_e, company_id, today, dataclasses.replace(hf, requested_delivery_date=today + dt.timedelta(days=3)))
documents_service.confirm_document(po_e, company_id, user.user_id)
documents_service.approve_document(po_e, company_id, user.user_id)
d = doc_of(po_e)
check(d.approved_by_user_id == user.user_id and d.approved_at is not None, "تصویب‌کننده و زمان تصویب ثبت شد")
logs = documents_service.list_document_changes(po_e)
statuses = [(l.old_value, l.new_value) for l in logs if l.action == "STATUS"]
check(statuses == [("DRAFT", "CONFIRMED"), ("CONFIRMED", "DRAFT"), ("DRAFT", "CONFIRMED"), ("CONFIRMED", "APPROVED")],
      f"رویدادهای وضعیت (got {statuses})")
check(all(l.user_id == user.user_id for l in logs), "کاربر هر رویداد ثبت شد")
r = rows("CHANGED_AFTER_APPROVAL")
fields_ = sorted((x[6], x[7], x[8]) for x in r)
check(len(r) == 2 and fields_ == sorted([("مقدار", "10.000000", "12"), ("فی", "90.000000", "95")]),
      f"تغییر قیمت/مقدار پس از تایید (got {fields_})")
check(len(rows("CHANGED_AFTER_APPROVAL", options={"scope": "ALL"})) == 3, "همهٔ تغییرات (شامل تاریخ تحویل سر سند)")
r = rows("MODIFIED_DOCS")
check(len(r) == 1 and r[0][1] == no(po_e) and r[0][5] == 1 and r[0][6] == 3, f"اسناد اصلاح‌شده (got {r})")
r = {x[1]: x for x in rows("APPROVAL_HISTORY") if x[0] == "سفارش خرید"}
check("مدیر سیستم" in r[no(po_e)][7] and r[no(po_e)][9] == 1, f"تاریخچهٔ تایید و تصویب (got {r[no(po_e)]})")
r = rows("SOD_VIOLATIONS")
check(any(x[1] == no(po_e) and "ایجاد و تصویب" in x[6] for x in r), f"تخلف تفکیک وظایف: ایجاد و تصویب توسط یک نفر (got {r})")
# ویرایشِ سندِ هرگز تاییدنشده ثبت نمی‌شود
draft_po, draft_line = dated("PURCHASE_ORDER", bolt, 5, s1, 100, today)
documents_service.update_line(draft_line, draft_po, company_id, D(6), D(100))
check(documents_service.list_document_changes(draft_po) == [], "ویرایش پیش‌نویس اولیه در تاریخچه نمی‌آید")

# --- ۴) لغو با علت
documents_service.cancel_document(draft_po, company_id, reason_id=reasons["PRICE"].reason_id, note="گران بود",
                                  cancelled_by_user_id=user.user_id)
d = doc_of(draft_po)
check(d.cancellation_reason_id == reasons["PRICE"].reason_id and d.cancelled_at is not None and d.cancellation_note == "گران بود",
      "علت/زمان/توضیح لغو ثبت شد")
old_style, _ = dated("PURCHASE_ORDER", bolt, 1, s1, 100, today)
documents_service.cancel_document(old_style, company_id)
check(doc_of(old_style).status_code == "CANCELLED", "فراخوانی قدیمی cancel_document بدون علت هم کار می‌کند")
r = {x[1]: x for x in rows("CANCELLED")}
check(r[no(draft_po)][6] == "قیمت نامناسب" and r[no(old_style)][6] == "— ثبت‌نشده —", "گزارش لغوشده‌ها با علت")
r = {x[0]: x for x in rows("CANCEL_ANALYSIS")}
check(r["قیمت نامناسب"][1] == 1 and r["— ثبت‌نشده —"][1] == 1, f"تحلیل علت‌های لغو (got {r})")

# --- ۵) تاریخِ تحویلِ ردیف (حتی رویِ سفارشِ ثبت‌شده)
documents_service.set_line_expected_delivery_date(po1_line, po1, company_id, d10 + dt.timedelta(days=2))
check(any(l.field_name == "expected_delivery_date" for l in documents_service.list_document_changes(po1)), "تغییر تاریخ ردیف ثبت شد")
check(raises(lambda: documents_service.set_line_expected_delivery_date(po_e_line, draft_po, company_id, today)), "ردیف نامعتبر رد شد")
r = {x[0]: x for x in rows("LINE_DELIVERY")}
p1 = r[no(po1)]
check(p1[5] == "ردیف" and p1[7] == 8 and p1[8] == "با تاخیر", f"تحویل ردیفی: ۸ روز تاخیر (got {p1})")
check(r[no(po_e)][5] == "ردیف" and r[no(po_e)][8] == "دیرکرد — نرسیده", f"ردیف نرسیدهٔ دیرکرد (got {r[no(po_e)]})")
late = {x[0]: x for x in rows("LATE_ORDERS")}
check(late[no(po1)][3] == d10 + dt.timedelta(days=2) and late[no(po1)][5] == 8, f"سفارش دیرکرد با تاریخ ردیف (got {late.get(no(po1))})")

# --- ۶) نوعِ خرید در تحلیل + فاکتورِ تبدیل‌شده
r = {x[0]: x for x in rows("BY_DIMENSION", options={"dimension": "PURCHASE_TYPE"})}
check(set(r) == {"— تعیین‌نشده —"}, f"بُعد نوع خرید (فاکتورهای قبلی بدون نوع) (got {list(r)})")
direct_e = documents_service.create_document(company_id, user.user_id, "PURCHASE_INVOICE", today, hf)
documents_service.add_line(direct_e, company_id, bolt, pcs, D(2), D(2), unit_price=D(100))
post_invoice(direct_e)
r = {x[0]: x for x in rows("BY_DIMENSION", options={"dimension": "PURCHASE_TYPE"})}
check(r["اضطراری"][3] == 200, f"خرید اضطراری در تحلیل (got {r})")

# --- ۷) سیاستِ سفارشِ کالا
check(raises(lambda: masters.save_reorder_policy(company_id, masters.PolicyFields(bolt, wh, min_qty=D(50), reorder_point_qty=D(40)))), "نقطهٔ سفارش < حداقل رد شد")
check(raises(lambda: masters.save_reorder_policy(company_id, masters.PolicyFields(bolt, wh, reorder_point_qty=D(100), max_qty=D(100)))), "حداکثر ≤ نقطهٔ سفارش رد شد")
pid = masters.save_reorder_policy(company_id, masters.PolicyFields(bolt, wh, min_qty=D(20), reorder_point_qty=D(200), max_qty=D(500), lead_time_days=6))
check(raises(lambda: masters.save_reorder_policy(company_id, masters.PolicyFields(bolt, wh, min_qty=D(1)))), "سیاست تکراری رد شد")
r = rows("STOCK_POLICY", options={"view": "BELOW_ROP"})
check(len(r) == 1 and r[0][8] == "سیاست کالا" and r[0][4] == 200, f"وضعیت موجودی با سیاست تعریف‌شده (got {r})")
check(rows("REORDER_POLICIES")[0][6] == 6, "گزارش سیاست‌های سفارش")
masters.save_reorder_policy(company_id, masters.PolicyFields(bolt, wh, min_qty=D(20), reorder_point_qty=D(100), max_qty=D(500)), pid)
check(rows("REORDER_POLICIES")[0][3] == 100, "ویرایش سیاست")
check(len(rows("PURCHASE_TYPES")) == 3 and rows("CANCEL_REASONS")[0][3] >= 0, "گزارش‌های اطلاعات پایه")

# --- ۸) UI
from peecha import nav_catalog
menu_codes = [e[0] for _g, _l, entries in nav_catalog.PURCHASE_REPORT_MENU for e in entries if not isinstance(e, dict)]
check(sorted(menu_codes) == sorted(x.code for x in pr.REPORTS), "منوی گزارش‌ها هم‌خوان با سرویس")
from peecha.ui.shell_window import MainWindow
from peecha.ui.screens.procurement_dialogs import CancellationReasonDialog
mw = MainWindow(); mw.resize(1400, 900); mw.show(); app.processEvents()
mw.open_screen("PURCH_MASTERS"); app.processEvents()
ms = mw._screens["procurement_masters"]
check(ms.purchase_types_tab.table.rowCount() == 3 and ms.cancel_reasons_tab.table.rowCount() == 6 and ms.policies_tab.table.rowCount() == 1,
      "فرم اطلاعات پایه: سه جدول")
t = ms.purchase_types_tab
t.code_field.setText("IMPORT"); t.name_field.setText("وارداتی"); t.save()
check(t.table.rowCount() == 4, "افزودن نوع خرید از فرم")
pt = ms.policies_tab
pt.table.selectRow(0); app.processEvents()
check(pt._editing_id == pid and pt.rop_field.text() == "۱۰۰", f"بارگذاری سیاست در فرم (got {pt.rop_field.text()})")
pt.max_field.setText("۵۰"); pt.save()
check(masters.list_reorder_policies(company_id)[0].max_qty == 500, "سیاست نامعتبر از فرم ذخیره نشد")
pt.table.selectRow(0); pt.max_field.setText("۶۰۰"); pt.save()
check(masters.list_reorder_policies(company_id)[0].max_qty == 600, "ویرایش سیاست از فرم")
for code in ("CHANGED_AFTER_APPROVAL", "MODIFIED_DOCS", "APPROVAL_HISTORY", "SOD_VIOLATIONS", "CANCEL_ANALYSIS", "EMERGENCY",
             "LINE_DELIVERY", "PURCHASE_TYPES", "CANCEL_REASONS", "REORDER_POLICIES"):
    mw.open_screen(f"PURCH_RPT_{code}"); app.processEvents()
    scr = mw._screens[f"purchase_report_{code.lower()}"]
    scr.date_from.setDate(today - dt.timedelta(days=60)); scr._reload()
    check(scr.table.columnCount() > 0, f"گزارش {code} از منو اجرا شد")

mw.open_screen("PURCH_ORDER", then=lambda s_: s_.edit_document(po_e)); app.processEvents()
form = mw._screens["commercial_document_purchase_order"]
check(form.purchase_type_combo.currentData() == emergency and form.purchase_type_box.isVisibleTo(form), "نوع خرید در فرم سفارش")
hist = form._show_history(); app.processEvents()
check(hist is not None and hist.table.rowCount() == len(documents_service.list_document_changes(po_e)), "دیالوگ تاریخچه")
hist.close()
dlg = form._edit_line_dates(); app.processEvents()
dlg.date_edits[0].setDate(today + dt.timedelta(days=9)); dlg.save()
check(documents_service.get_document(po_e, company_id)[1][0].expected_delivery_date == today + dt.timedelta(days=9), "ذخیرهٔ تاریخ ردیف از دیالوگ (سند تصویب‌شده)")
# لغو از فرم با علت
ui_po, _ = dated("PURCHASE_ORDER", bolt, 1, s2, 100, today)
mw.open_screen("PURCH_ORDER", then=lambda s_: s_.edit_document(ui_po)); app.processEvents()
CancellationReasonDialog.auto_answer = (1, "از فرم")
form._cancel(); app.processEvents()
d = doc_of(ui_po)
check(d.status_code == "CANCELLED" and d.cancellation_reason_id is not None and d.cancellation_note == "از فرم", "لغو از فرم با انتخاب علت")
mw.open_screen("PURCH_INVOICE"); app.processEvents()
inv_form = mw._screens["commercial_document_purchase_invoice"]
check(inv_form.purchase_type_box.isVisibleTo(inv_form) and not inv_form.line_dates_button.isVisibleTo(inv_form), "نوع خرید در فاکتور خرید؛ تاریخ ردیف فقط در سفارش")
mw.open_screen("SALES_INVOICE"); app.processEvents()
check(not mw._screens["commercial_document_sales_invoice"].purchase_type_box.isVisibleTo(mw._screens["commercial_document_sales_invoice"]),
      "نوع خرید در فاکتور فروش نیست")

print("RESULT:", "ALL PASS" if not FAIL else "SOME FAILED")
sys.exit(1 if FAIL else 0)
