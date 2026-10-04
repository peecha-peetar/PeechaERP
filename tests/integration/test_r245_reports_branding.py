import os, sys, datetime, decimal, io
os.environ["PEECHA_DB_NAME"] = "peecha_test_r245_1"
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

from peecha.services import commercial_pos as pos_service
plan_inv, _ = dated("PURCHASE_INVOICE", bolt, 10, s2, 100, today - dt.timedelta(days=45))
post_invoice(plan_inv, [("CASH", D(400))])
pos_service.post_invoice_settlement_plan(company_id, user.user_id, plan_inv)

pos_service_jid = None
import dataclasses
from peecha.services import accounting_reports as ar
from peecha.services import companies as companies_service
from peecha import nav_catalog
F = pr.PurchaseFilters(today - dt.timedelta(days=60), today)
FA = pr.PurchaseFilters(today - dt.timedelta(days=60), today, side="ACCOUNTING")
def rows(code, **kw):
    return pr.run_report(company_id, code, dataclasses.replace(F, **kw)).rows
def arun(code, **kw):
    return pr.run_report(company_id, code, dataclasses.replace(FA, **kw))

# --- ۱) منو: گزارش‌هایِ حسابداری در زیرگروه‌ها، «فاکتورها» حذف -----------------
check("INVOICES" not in [x["code"] for x in nav_catalog.NAV_ITEMS], "آیتمِ بی‌کاربردِ «فاکتورها» از منو حذف شد")
acc_codes = [e[0] for _g, _l, es in nav_catalog.ACCOUNTING_REPORT_MENU for e in es if not isinstance(e, dict)]
check(sorted(acc_codes) == sorted(r.code for r in ar.ACCOUNTING_REPORTS) and len(acc_codes) == 22, "۲۲ گزارشِ تازهٔ حسابداری در منو")
old_codes = {e["code"] for _g, _l, es in nav_catalog.ACCOUNTING_REPORT_MENU for e in es if isinstance(e, dict)}
check({"REPORTS_TRIAL_BALANCE", "REPORTS_BALANCE_SHEET", "REPORTS_ANOMALIES", "REPORTS_COST_CENTER"} <= old_codes and len(old_codes) == 13,
      "۱۳ گزارشِ قبلیِ حسابداری با همان کد در زیرگروه‌ها")
menu_codes = [e[0] for _g, _l, es in nav_catalog.PURCHASE_REPORT_MENU for e in es if not isinstance(e, dict)]
check(sorted(menu_codes) == sorted(r.code for r in pr.REPORTS) and len(pr.REPORTS) == 116, f"منویِ خرید هم‌خوان با ۱۱۶ گزارش (got {len(pr.REPORTS)})")

# --- ۲) گزارش‌هایِ حسابداری -----------------------------------------------------
reg = arun("VOUCHER_REGISTER")
check(len(reg.rows) >= 4 and all(r[6] == r[7] for r in reg.rows), f"دفترِ ثبتِ اسناد: همه تراز (got {len(reg.rows)})")
check(reg.footer()[1] == "" and reg.footer()[2] == "", "شمارهٔ سند در ردیفِ جمع جمع زده نمی‌شود")
by_type = arun("VOUCHERS_BY", options={"by": "TYPE"})
check(sum(r[1] for r in by_type.rows) == len(reg.rows), "اسناد به تفکیکِ نوع = تعدادِ دفترِ ثبت")
check(not arun("UNBALANCED").rows, "سندِ نامتوازنی نیست")
check(all(r[2] != "شمارهٔ تکراری" for r in arun("NUMBER_GAPS").rows), "شمارهٔ تکراری نیست")
abnormal = {r[0]: r for r in arun("ABNORMAL_BALANCES").rows}
check(abnormal.get("1-11-101 — صندوق", [0] * 5)[4] == 400, f"صندوقِ بستانکار = ماندهٔ خلافِ ماهیت (got {list(abnormal)})")
check(raises(lambda: arun("CONTRA_ACCOUNTS")), "تحلیلِ طرف‌حساب بدونِ حساب خطایِ راهنما می‌دهد")
contra = arun("CONTRA_ACCOUNTS", account_id=cash_gl.account_id).rows
check(len(contra) == 1 and contra[0][0].endswith("پرداختنیِ تامین‌کنندگان") and contra[0][1] == 400, f"طرف‌حسابِ صندوق (got {contra})")
mb = arun("MONTHLY_BALANCE", account_id=k1.account_id).rows
check(mb and mb[-1][4] == -400, f"ماندهٔ ماهانهٔ حسابِ کل با زیرحساب‌ها (got {mb})")
matrix = arun("ACCOUNT_PERIOD_MATRIX", options={"period": "YEAR", "level": "3", "measure": "DEBIT"})
inv_row = next(r for r in matrix.rows if r[0].endswith("موجودیِ کالا"))
check(inv_row[-2] == sum(v for v in inv_row[1:-2]), "ماتریسِ دوره‌ای: جمعِ ردیف = جمعِ دوره‌ها")
det = arun("DETAIL_BY_ACCOUNT").rows
check(any(r[0].endswith("پیچ") and r[1].endswith("موجودیِ کالا") for r in det), "گردشِ تفصیلیِ کالا رویِ حسابِ موجودی")
dormant = {r[0]: r for r in arun("DORMANT_ACCOUNTS").rows}
check(dormant.get("1-13-1304 — دریافتنیِ مشتریان", [0] * 5)[4] == "هرگز گردش نداشته", "حسابِ راکد")
ctb = arun("COMPARATIVE_TB", options={"level": "3"}).rows
check(all(r[2] == 0 for r in ctb) and ctb, "ترازِ مقایسه‌ای: سالِ قبل صفر")
large = arun("LARGE_LINES").rows
check(large and max(large[0][4], large[0][5]) == max(max(r[4], r[5]) for r in large), "بزرگ‌ترین ردیف اول")
check(any(r[4] == 400 or r[5] == 400 for r in arun("ROUND_AMOUNTS", options={"unit": "100"}).rows), "مبلغِ رُند")
back = arun("BACKDATED", options={"lag": "30"}).rows
check(len(back) == 2 and all(r[9] >= 45 and r[10] == "عطف به ماسبق" for r in back), f"فاکتور و پرداختِ ۴۵روزِ قبل: عطف به ماسبق (got {back})")
check(not arun("SELF_APPROVED").rows, "سندِ خودتاییدی نیست")
isa = arun("IS_ANALYSIS")
check(isa.footer() is None and isa.rows[-1][1] == "سود (زیان) خالص", "تحلیلِ سود و زیان بدونِ ردیفِ جمعِ خالی")
bsa = arun("BS_ANALYSIS").rows
check(bsa[-1][1] == "جمعِ دارایی‌ها", "تحلیلِ ترازنامه")
for r in ar.ACCOUNTING_REPORTS:
    try:
        arun(r.code, account_id=cash_gl.account_id)
    except Exception as exc:  # noqa: BLE001
        check(False, f"گزارشِ {r.code} خطا داد: {exc}")
check(len(arun("VOUCHER_REGISTER", account_id=cash_gl.account_id).rows) == 1, "فیلترِ حساب رویِ دفترِ ثبت")

# --- ۳) گزارش‌هایِ تازهٔ خرید ----------------------------------------------------
vat = rows("VAT")
check(sum(r[2] for r in vat) == 8800 + 2850 + 1000 - 550, f"مالیات بر ارزش افزوده: خالصِ خرید پس از برگشت (got {sum(r[2] for r in vat)})")
cmp_ = rows("PERIOD_COMPARE")
check(sum(r[1] for r in cmp_) == 12100 and all(r[2] == 0 for r in cmp_), "مقایسه با سالِ قبل")
last = rows("LAST_PURCHASE")
check(len(last) == 1 and last[0][4] == "S2 — تامین‌کنندهٔ دو" and last[0][6] == 95, f"آخرین خرید (got {last})")
share = rows("SUPPLIER_SHARE")
check(abs(sum(r[5] for r in share) - 100) <= D("0.2") and [r[6] for r in share] == [1, 2], f"سهمِ تامین‌کنندگان (got {share})")
dup, _ = dated("PURCHASE_INVOICE", bolt, 1, s1, 100, today)
check(len(rows("DUPLICATE_INVOICES")) == 2, "دو فاکتورِ هم‌مبلغِ یک تامین‌کننده مشکوک به تکرار")
cur = rows("BY_CURRENCY")
check(len(cur) == 1 and cur[0][2] == cur[0][3], "خرید به تفکیکِ ارز (فقط ارزِ پایه)")
dpo = {r[0]: r for r in rows("DPO")}
check(dpo["S1 — تامین‌کنندهٔ یک"][4] == 8250 and dpo["S1 — تامین‌کنندهٔ یک"][5] == int(D(8250) / 8800 * 61), f"DPO (got {dpo})")
check(rows("EXPIRING_CONTRACTS") == [], "قراردادِ در آستانهٔ انقضا نیست")
pvs = rows("PURCHASE_VS_SALE")
check(pvs and pvs[0][5] is None, "قیمتِ خرید در برابرِ فروش (بدونِ فروش)")

# --- ۴) لوگو ----------------------------------------------------------------------
from PySide6.QtGui import QImage, QColor
from PySide6.QtCore import QBuffer, QByteArray, QIODevice
img = QImage(120, 60, QImage.Format_ARGB32)
img.fill(QColor("#3366cc"))
ba = QByteArray(); buf = QBuffer(ba); buf.open(QIODevice.WriteOnly); img.save(buf, "PNG")
png = bytes(ba)
check(companies_service.get_report_logo(company_id) == (None, "RIGHT"), "پیش‌فرض: بدونِ لوگو، محل راست")
check(raises(lambda: companies_service.set_company_logo(company_id, b"not an image", "image/png")), "فایلِ غیرِتصویر رد شد")
check(raises(lambda: companies_service.set_company_logo(company_id, b"x" * (2 * 1024 * 1024 + 1), "image/png")), "لوگویِ بزرگ‌تر از ۲ مگ رد شد")
companies_service.set_company_logo(company_id, png, "image/png")
check(companies_service.get_report_logo(company_id) == (png, "RIGHT"), "لوگو ذخیره شد")
check(raises(lambda: companies_service.set_report_logo_position(company_id, "TOP")), "محلِ نامعتبر رد شد")
companies_service.set_report_logo_position(company_id, "LEFT")
check(companies_service.get_report_logo(company_id)[1] == "LEFT", "محلِ لوگو: چپ")
from peecha.ui import report_export
check(report_export.company_logo() == (png, "LEFT"), "لوگویِ شرکتِ جاری برایِ چاپ")
html = report_export.logo_header_html("<b>شرکت</b>")
check(html.index("<b>شرکت</b>") < html.index("peecha-logo://"), "سربرگِ HTML: لوگو در سمتِ چپ (بعد از متن در جهتِ rtl)")
import tempfile as _tf, openpyxl
xlsx = os.path.join(_tf.mkdtemp(), "r.xlsx")
from PySide6.QtWidgets import QFileDialog, QWidget
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (xlsx, ""))
report_export.export_report_excel(QWidget(), "آزمون", ["الف", "ب"], [["۱", "۲"]], company_name="شرکت")
check(len(openpyxl.load_workbook(xlsx).active._images) == 1, "لوگو در خروجیِ اکسل")
from peecha.reporting import jasper_bridge
p = jasper_bridge._logo_params(_tf.mkdtemp())
check(p["companyLogoPosition"] == "LEFT" and open(p["companyLogoPath"], "rb").read() == png, "پارامترِ لوگو برایِ قالبِ Jasper")
import glob
jrxmls = glob.glob(os.path.join(os.path.dirname(jasper_bridge.__file__), "templates", "*.jrxml"))
check(jrxmls and all("companyLogoPath" in open(j, encoding="utf-8").read() for j in jrxmls), "همهٔ قالب‌هایِ Jasper پارامترِ لوگو دارند")
companies_service.set_report_logo_position(company_id, "NONE")
check(report_export.company_logo()[0] is None and jasper_bridge._logo_params(_tf.mkdtemp())["companyLogoPosition"] == "NONE",
      "«بدونِ لوگو»: لوگو در گزارش نمی‌آید")
companies_service.set_report_logo_position(company_id, "RIGHT")
from peecha.ui.screens.report_branding import ReportBrandingScreen
png_path = os.path.join(_tf.mkdtemp(), "logo.png"); img.save(png_path)
rb = ReportBrandingScreen(); rb.refresh()
check(rb.position_combo.currentData() == "RIGHT" and rb.preview.pixmap() is not None and not rb.preview.pixmap().isNull(), "صفحهٔ لوگو: پیش‌نمایش و محل")
rb.position_combo.setCurrentIndex(rb.position_combo.findData("LEFT"))
check(companies_service.get_report_logo_position(company_id) == "LEFT", "تغییرِ محل از صفحه ذخیره شد")
rb.remove_logo()
check(companies_service.get_report_logo(company_id)[0] is None and not rb.remove_button.isEnabled(), "حذفِ لوگو")
check(rb.set_logo_file(png_path) and companies_service.has_logo(company_id), "بارگذاریِ لوگو از فایل")
from peecha.ui.screens.system_settings import SystemSettingsScreen
ss = SystemSettingsScreen()
check(ss.tabs.tabText(9) == "چاپ و گزارش‌ها", f"تبِ «چاپ و گزارش‌ها» در تنظیمات (got {ss.tabs.tabText(9)})")

# --- ۵) صفحهٔ گزارشِ حسابداری و پوستهٔ برنامه --------------------------------------
from peecha.ui.screens.purchase_reports import PurchaseReportScreen
scr = PurchaseReportScreen("ACCOUNT_PERIOD_MATRIX", None, side="ACCOUNTING")
scr.refresh()
check(scr.account_combo.count() > 5 and scr.options_row.count() >= 8, "صفحهٔ گزارشِ حسابداری: فیلترِ حساب و ردیفِ جدایِ گزینه‌ها")
scr = PurchaseReportScreen("VOUCHER_REGISTER", None, side="ACCOUNTING"); scr.refresh()
check(scr.table.rowCount() >= len(reg.rows), "دفترِ ثبتِ اسناد در صفحه")
from peecha.ui import shell_window
check(shell_window._SETTINGS_TAB_BY_GROUP_CODE.get("REPORTS") == 9, "چرخ‌دندهٔ گزارش‌ها به تبِ چاپ و گزارش‌ها")
mw = shell_window.MainWindow(); mw.show(); app.processEvents()
grp = mw._sidebar_groups["REPORTS"]
check(len(grp._subgroups) >= 25, f"زیرمنوهایِ جمع‌شونده (got {len(grp._subgroups)})")
check(all(s.body.isHidden() for s in grp._subgroups), "زیرمنوها در ابتدا بسته‌اند")
mw.open_screen("ACC_RPT_CONTRA_ACCOUNTS"); app.processEvents()
parents = grp._subgroups_of["ACC_RPT_CONTRA_ACCOUNTS"]
check(parents and all(not s.body.isHidden() for s in parents), "بازکردنِ گزارش، زیرمنوهایِ والد را باز می‌کند")
tiles = mw.findChildren(shell_window._QuickAccessTile)
check(tiles and all(t.width() == 96 and t.height() == 88 for t in tiles), "کاشی‌هایِ ریبونِ بزرگ‌تر و یکسان")

print("RESULT:", "ALL PASS" if not FAIL else "SOME FAILED")
sys.exit(1 if FAIL else 0)
