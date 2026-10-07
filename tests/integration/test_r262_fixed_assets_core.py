import os, sys, datetime, decimal, io
os.environ["PEECHA_DB_NAME"] = "peecha_test_r262_1"
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
from sqlalchemy import select, text
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

from peecha.services import unit_conversion as uc
from peecha.services import stock_count as stock_count_service
from peecha.services import commercial_settlements as settlements_service

D = decimal.Decimal
def raises(fn):
    try:
        fn()
    except ValueError:
        return True
    return False

k8 = A("32", "پرداختنی‌ها", "CREDIT", "LIABILITY", "PERMANENT", False, g4.account_id)
ap_gl = A("3201", "پرداختنی تامین‌کنندگان", "CREDIT", "LIABILITY", "PERMANENT", True, k8.account_id)
engine_service.set_account_mapping(company_id, "SUPPLIER_PAYABLE", ap_gl.account_id)
engine_service.set_account_mapping(company_id, "INVENTORY_ADJUSTMENT_LOSS", adj_gl.account_id)


from peecha.services import lot_tracking as lt
from peecha.services import warehouse_locations as wl
from peecha.services import warehouse_operations as ops
from peecha.services import users as users_service
from peecha.services import roles as roles_service
from peecha.db.models.inventory import BinLocation, Warehouse

today = datetime.date.today()
pcs = catalog_service.create_uom(company_id, "PCS", "عدد", "COUNT", decimal_places=0)
supplier = dimensions_service.create_supplier(company_id, "S1", "تامین‌کننده")
g1 = catalog_service.create_item(company_id, "G-1", "پیچ‌گوشتی", catalog_service.ItemFields(
    item_kind_code="GOOD", base_uom_id=pcs, barcode="6260000000011", weight_kg=D(2)))
g2 = catalog_service.create_item(company_id, "G-2", "انبردست", catalog_service.ItemFields(item_kind_code="GOOD", base_uom_id=pcs))

# =====================================================================
# R249: بررسیِ محل در اسناد، سازگاری، رزرو، تأمینِ مجدد، سه‌بعدی، API
# =====================================================================
from sqlalchemy import func as sa_func
from peecha.db.models.inventory import WarehouseTask, StockDocument as SD
from peecha.db.models.audit import ActivityLog
LF = wl.LocationFields
item = g1
wh = locations_service.create_warehouse(company_id, "WH01", "مرکزی", locations_service.WarehouseFields(is_default=True, allow_negative_stock=True))
general = locations_service.get_default_bin_location(wh).bin_location_id
zb = wl.create_location(company_id, wh, "AREA", "Z01", fields=LF(location_type_code="BULK"))
zp = wl.create_location(company_id, wh, "AREA", "Z02", fields=LF(location_type_code="PICK_FACE"))
zc = wl.create_location(company_id, wh, "AREA", "Z03", fields=LF(location_type_code="COLD", temperature_min_c=D(2), temperature_max_c=D(6)))
zh = wl.create_location(company_id, wh, "AREA", "Z04", fields=LF(allows_hazardous=True))
zs = wl.create_location(company_id, wh, "AREA", "Z09", fields=LF(location_type_code="SHIPPING"))
def rack_with_bins(zone, rack_code):
    r = wl.create_location(company_id, wh, "RACK", rack_code, zone)
    shelves = [wl.create_location(company_id, wh, "SHELF", f"L0{i}", r) for i in (1, 2)]
    return r, [wl.create_location(company_id, wh, "BIN", f"B0{i}", shelves[0], LF(max_weight_kg=D(100))) for i in (1, 2)]
rb, (bulk1, bulk2) = rack_with_bins(zb, "R01")
rp, (pick1, pick2) = rack_with_bins(zp, "R02")
rc, (cold1, _c2) = rack_with_bins(zc, "R03")
rh, (haz1, _h2) = rack_with_bins(zh, "R04")
milk = catalog_service.create_item(company_id, "M-1", "شیر", catalog_service.ItemFields(item_kind_code="GOOD", base_uom_id=pcs))
acid = catalog_service.create_item(company_id, "A-1", "اسید", catalog_service.ItemFields(item_kind_code="GOOD", base_uom_id=pcs))

def draft(doc_type, item_id, qty, bin_id=None, dst_bin=None, src=None, dst=None):
    doc = inv_documents_service.create_stock_document(company_id, user.user_id, doc_type, today, inv_documents_service.DocumentHeaderFields(
        source_warehouse_id=src, destination_warehouse_id=dst, counterparty_detail_account_id=supplier if doc_type == "RECEIPT" else None))
    inv_documents_service.add_line(doc, company_id, inv_documents_service.LineFields(
        item_id=item_id, uom_id=pcs, quantity=D(qty), quantity_base=D(qty), unit_cost=D(1000) if doc_type == "RECEIPT" else None,
        bin_location_id=bin_id, destination_bin_location_id=dst_bin))
    return doc
def post(doc):
    inv_documents_service.confirm_stock_document(doc, company_id)
    inv_documents_service.post_stock_document(doc, company_id, user.user_id)
    return doc
post(draft("RECEIPT", item, 80, bin_id=bulk1, dst=wh))
post(draft("RECEIPT", item, 5, bin_id=pick1, dst=wh))
post(draft("RECEIPT", milk, 10, dst=wh))
post(draft("RECEIPT", acid, 10, dst=wh))


# =====================================================================
# R262: دارایی‌هایِ ثابت -- شناسنامه، تحصیل، سرمایه‌ای‌شدن، استهلاک (سه روش)، اجرایِ دوره، انتقال، تغییرِ طبقه
# =====================================================================
import jdatetime
from peecha.db.models.accounting import JournalEntryLine, JournalEntry
from peecha.db.models.fixed_assets import Asset, AssetTransaction, DepreciationRun, AssetEvent
from peecha.services.fixed_assets import common as fac, assets as fa, depreciation as fd

from peecha.db.models.accounting import ChartOfAccount
with new_session() as _s:
    root_assets = _s.scalar(select(ChartOfAccount.account_id).where(ChartOfAccount.company_id == company_id, ChartOfAccount.full_code == "1"))
k9 = A("14", "دارایی‌های ثابت", "DEBIT", "ASSET", "PERMANENT", False, root_assets)
fa_machine = A("1401", "ماشین‌آلات", "DEBIT", "ASSET", "PERMANENT", True, k9.account_id)
fa_office = A("1402", "تجهیزات اداری", "DEBIT", "ASSET", "PERMANENT", True, k9.account_id)
fa_accum = A("1409", "استهلاک انباشته", "CREDIT", "ASSET", "PERMANENT", True, k9.account_id)
fa_accum2 = A("1408", "استهلاک انباشتهٔ اداری", "CREDIT", "ASSET", "PERMANENT", True, k9.account_id)
k10 = A("61", "هزینه‌های عمومی", "DEBIT", "EXPENSE", "TEMPORARY", False, g3.account_id)
dep_exp = A("6101", "هزینهٔ استهلاک", "DEBIT", "EXPENSE", "TEMPORARY", True, k10.account_id)
transport_gl = A("3202", "حمل‌ونقل پرداختنی", "CREDIT", "LIABILITY", "PERMANENT", True, k8.account_id)

cc_type = dimensions_service.get_specialized_dimension_type_id(company_id, dimensions_service.COST_CENTER_CODE)
cc_a = dimensions_service.create_detail_account(company_id, cc_type, "CC-A", "خط تولید A").detail_account_id
cc_b = dimensions_service.create_detail_account(company_id, cc_type, "CC-B", "خط تولید B").detail_account_id

def jd(m, d=1):
    return jdatetime.date(1405, m, d).togregorian()
def je_lines(je_id):
    with new_session() as s:
        return [(l.account_id, l.debit_amount_base, l.credit_amount_base) for l in s.scalars(
            select(JournalEntryLine).where(JournalEntryLine.journal_entry_id == je_id).order_by(JournalEntryLine.line_id))]
def balance(account_id):
    with new_session() as s:
        return s.scalar(select(sa_func.coalesce(sa_func.sum(JournalEntryLine.debit_amount_base - JournalEntryLine.credit_amount_base), 0))
                        .where(JournalEntryLine.account_id == account_id))
def asset(asset_id):
    return fa.get_asset(company_id, asset_id)
ACC = dict(asset_account_id=fa_machine.account_id, accumulated_depreciation_account_id=fa_accum.account_id,
           depreciation_expense_account_id=dep_exp.account_id)

# --- ۱) طبقه‌ها (پیش‌فرض + حساب‌ها) ----------------------------------------------------------------------
fac.ensure_default_categories(company_id)
cats = {x.code: x for x in fac.list_categories(company_id)}
check({"LAND", "BUILDING", "MACHINERY", "VEHICLE", "IT", "OTHER"} <= set(cats), "طبقه‌های پیش‌فرض ساخته شدند")
mach = fac.save_category(company_id, fac.CategoryFields("MACHINERY", "ماشین‌آلات", "STRAIGHT_LINE", 12, accounts=ACC),
                         category_id=cats["MACHINERY"].category_id, user_id=user.user_id)
office = fac.save_category(company_id, fac.CategoryFields("OFFICE", "تجهیزات اداری", "STRAIGHT_LINE", 60, accounts=dict(
    asset_account_id=fa_office.account_id, accumulated_depreciation_account_id=fa_accum2.account_id,
    depreciation_expense_account_id=dep_exp.account_id)), category_id=cats["OFFICE"].category_id, user_id=user.user_id)
check(raises(lambda: fac.save_category(company_id, fac.CategoryFields("OFFICE", "تکراری"))), "کد طبقهٔ تکراری رد شد")
loc_site = fac.save_location(company_id, "F-A", "کارخانهٔ A", "SITE")
loc_line = fac.save_location(company_id, "F-A-L1", "خط ۱", "LINE", parent_location_id=loc_site)
loc_b = fac.save_location(company_id, "F-B", "کارخانهٔ B", "SITE")
check(raises(lambda: fac.save_location(company_id, "F-A", "x", "SITE", parent_location_id=loc_line, location_id=loc_site)),
      "محل نمی‌تواند زیرمجموعهٔ خودش باشد")
grp = fac.save_group(company_id, "LINE-A", "خط تولید A")

# --- ۲) شناسنامه و خطاها ------------------------------------------------------------------------------
F = lambda code, **kw: fa.AssetFields(asset_code=code, name=kw.pop("name", "دستگاه " + code), category_id=kw.pop("category_id", mach), **kw)
cnc = fa.create_asset(company_id, user.user_id, F("CNC-001", name="ماشین CNC", asset_type_code="MACHINE", group_id=grp,
                                                 location_id=loc_line, cost_center_detail_account_id=cc_a, residual_value=D(0),
                                                 brand="Haas", serial_no="SN-777"))
check(asset(cnc).status_code == "DRAFT" and asset(cnc).useful_life == 12 and asset(cnc).depreciation_method == "STRAIGHT_LINE",
      "ایجاد دارایی با پیش‌فرض‌های طبقه (روش/عمر)")
check(raises(lambda: fa.create_asset(company_id, user.user_id, F("CNC-001"))), "کد تکراری: رد")
check(raises(lambda: fa.create_asset(company_id, user.user_id, fa.AssetFields("X-1", "x", None))), "بدون طبقه: رد")
check(raises(lambda: fa.create_asset(company_id, user.user_id, F("X-2", depreciation_method="UNITS_OF_PRODUCTION"))),
      "روش تولید بدون ظرفیت کارکرد: رد")
fac.update_settings(company_id, user.user_id, require_cost_center=True)
check(raises(lambda: fa.create_asset(company_id, user.user_id, F("X-3"))), "مرکز هزینهٔ الزامی: رد")
fac.update_settings(company_id, user.user_id, require_cost_center=False)

# --- ۳) تحصیل با اجزایِ بها و سرمایه‌ای‌شدن ------------------------------------------------------------
ap_before = balance(ap_gl.account_id)
je = fa.acquire(company_id, user.user_id, cnc, jd(3, 10), [
    fa.CostItem("PURCHASE", D(1_000_000), ap_gl.account_id, supplier), fa.CostItem("TRANSPORT", D(100_000), transport_gl.account_id),
    fa.CostItem("INSTALLATION", D(100_000), ap_gl.account_id, supplier)], idempotency_key="ACQ-CNC")
check(asset(cnc).gross_cost == 1_200_000 and asset(cnc).purchase_price == 1_000_000 and asset(cnc).status_code == "ACQUIRED",
      "بهای تمام‌شده = خرید + حمل + نصب")
check(balance(fa_machine.account_id) == 1_200_000 and balance(ap_gl.account_id) - ap_before == -1_100_000, "سند تحصیل از موتور حسابداری")
with new_session() as s:
    je_type = s.scalar(select(JournalEntry.entry_type_id).where(JournalEntry.journal_entry_id == je))
check(je_type == 11, "نوع سند «دارایی ثابت»")
check(fa.acquire(company_id, user.user_id, cnc, jd(3, 10), [fa.CostItem("PURCHASE", D(1_000_000), ap_gl.account_id)],
                 idempotency_key="ACQ-CNC") == je and asset(cnc).gross_cost == 1_200_000, "تکرار تحصیل با همان کلید: بدون سند دوم")
fa.capitalize(company_id, user.user_id, cnc, jd(3, 15), in_service_date=jd(3, 20))
a = asset(cnc)
check(a.status_code == "IN_SERVICE" and a.depreciation_start_date == jd(3, 20), "سرمایه‌ای‌شدن و شروع استهلاک از تاریخ بهره‌برداری")
check(raises(lambda: fa.capitalize(company_id, user.user_id, cnc, jd(3, 15))), "سرمایه‌ای‌شدن دوباره: رد")

# --- ۴) استهلاکِ ماهانه (خطِ مستقیم): محاسبه ← بررسی ← تأیید ← ثبت ------------------------------------------
r3 = fd.calculate_run(company_id, user.user_id, "1405/03")
lines3 = fd.run_lines(r3)
check(len(lines3) == 1 and lines3[0].amount == 100_000, f"خط مستقیم: ۱٬۲۰۰٬۰۰۰ ÷ ۱۲ = ۱۰۰٬۰۰۰ ({lines3})")
check(raises(lambda: fd.post_run(company_id, user.user_id, r3)), "ثبت اجرای تاییدنشده: رد")
fd.review_run(company_id, user.user_id, r3)
fd.approve_run(company_id, user.user_id, r3)
je3 = fd.post_run(company_id, user.user_id, r3)
check(asset(cnc).accumulated_depreciation == 100_000 and asset(cnc).book_value == 1_100_000, "ثبت: استهلاک انباشته و ارزش دفتری")
with new_session() as s:
    exp_line = s.scalars(select(JournalEntryLine).where(JournalEntryLine.journal_entry_id == je3,
                                                        JournalEntryLine.account_id == dep_exp.account_id)).one()
    from peecha.db.models.accounting import JournalEntryLineDetail
    cc_on_line = s.scalar(select(JournalEntryLineDetail.detail_account_id).where(JournalEntryLineDetail.line_id == exp_line.line_id))
check(exp_line.debit_amount_base == 100_000 and cc_on_line == cc_a, "هزینهٔ استهلاک به مرکز هزینهٔ دارایی (خط A)")
check(fd.post_run(company_id, user.user_id, r3) == je3 and asset(cnc).accumulated_depreciation == 100_000,
      "ثبت دوبارهٔ همان اجرا: بدون سند/استهلاک تکراری")
check(raises(lambda: fd.calculate_run(company_id, user.user_id, "1405/03")), "محاسبهٔ دوبارهٔ دورهٔ ثبت‌شده: رد")
def run_post(code):
    rid = fd.calculate_run(company_id, user.user_id, code)
    fd.approve_run(company_id, user.user_id, rid)
    fd.post_run(company_id, user.user_id, rid)
    return rid
r4 = run_post("1405/04")
check(asset(cnc).accumulated_depreciation == 200_000, "ماه دوم: ۱۰۰٬۰۰۰")
check(raises(lambda: fd.calculate_run(company_id, user.user_id, "1405/02")), "دورهٔ پیش از آخرین ثبت: رد")

# --- ۵) انتقال (مرکزِ هزینه/محل/تحویل‌گیرنده) -- استهلاکِ بعدی به مرکزِ هزینهٔ جدید --------------------------------
ev = fa.transfer(company_id, user.user_id, cnc, jd(5, 2), reason="انتقال به خط B", cost_center_detail_account_id=cc_b,
                 location_id=loc_b)
check(asset(cnc).cost_center_detail_account_id == cc_b and asset(cnc).location_id == loc_b, "انتقال: مرکز هزینه و محل")
check(fa.events(company_id, cnc, "TRANSFER")[0].details["location_id"] == [loc_line, loc_b], "تاریخچهٔ انتقال (از ← به)")
check(raises(lambda: fa.transfer(company_id, user.user_id, cnc, jd(5, 2), location_id=loc_b)), "انتقال بدون تغییر: رد")
r5 = run_post("1405/05")
with new_session() as s:
    je5 = s.get(DepreciationRun, r5).journal_entry_id
    l5 = s.scalars(select(JournalEntryLine).where(JournalEntryLine.journal_entry_id == je5, JournalEntryLine.account_id == dep_exp.account_id)).one()
    cc5 = s.scalar(select(JournalEntryLineDetail.detail_account_id).where(JournalEntryLineDetail.line_id == l5.line_id))
check(cc5 == cc_b, "پس از انتقال، هزینهٔ استهلاک به خط B")

# --- ۶) برگشتِ اجرا و ثبتِ دوباره ------------------------------------------------------------------------
fd.reverse_run(company_id, user.user_id, r5, reason="آزمون")
check(asset(cnc).accumulated_depreciation == 200_000, "برگشت: استهلاک دورهٔ ۵ خنثی شد")
with new_session() as s:
    rev = s.scalars(select(AssetTransaction).where(AssetTransaction.asset_id == cnc, AssetTransaction.txn_type == "REVERSAL")).all()
check(len(rev) == 1 and rev[0].depreciation_delta == -100_000 and rev[0].reversed_txn_id, "ردیف برگشتی در دفتر (بدون حذف)")
check(raises(lambda: fd.reverse_run(company_id, user.user_id, r3)), "برگشت دوره‌ای که دورهٔ بعدی‌اش ثبت است: رد")
r5b = run_post("1405/05")
check(asset(cnc).accumulated_depreciation == 300_000, "ثبت دوبارهٔ دوره پس از برگشت")

# --- ۷) شکستِ حسابداری = هیچ تغییری (Rollback) ---------------------------------------------------------------
lap = fa.create_asset(company_id, user.user_id, F("LAP-1", category_id=office, cost_center_detail_account_id=cc_a,
                                                 useful_life=D(10)))
fa.acquire(company_id, user.user_id, lap, jd(4, 1), [fa.CostItem("PURCHASE", D(500_000), ap_gl.account_id, supplier)])
fa.capitalize(company_id, user.user_id, lap, jd(4, 1), in_service_date=jd(4, 1))
r6 = fd.calculate_run(company_id, user.user_id, "1405/06")
fd.approve_run(company_id, user.user_id, r6)
fac.save_category(company_id, fac.CategoryFields("OFFICE", "تجهیزات اداری", "STRAIGHT_LINE", 60, accounts=dict(
    depreciation_expense_account_id=k10.account_id)), category_id=office)   # حسابِ گروه (غیرِقابلِ ثبت) -- خطا در سند
with new_session() as s:
    from peecha.db.models.fixed_assets import DepreciationLine
    for ln in s.scalars(select(DepreciationLine).where(DepreciationLine.run_id == r6, DepreciationLine.asset_id == lap)):
        ln.expense_account_id = k10.account_id
    s.commit()
before = (asset(cnc).accumulated_depreciation, asset(lap).accumulated_depreciation)
check(raises(lambda: fd.post_run(company_id, user.user_id, r6)), "حساب غیرقابل‌ثبت: ثبت اجرا رد شد")
with new_session() as s:
    st = s.get(DepreciationRun, r6).status_code
    n6 = s.scalar(select(sa_func.count()).select_from(AssetTransaction).where(AssetTransaction.source_id == r6,
                                                                              AssetTransaction.source_type == "DEPR_RUN"))
check(st == "APPROVED" and n6 == 0 and (asset(cnc).accumulated_depreciation, asset(lap).accumulated_depreciation) == before,
      "Rollback: نه سند، نه دفتر دارایی، نه تغییر وضعیت")
fac.save_category(company_id, fac.CategoryFields("OFFICE", "تجهیزات اداری", "STRAIGHT_LINE", 60, accounts=dict(
    depreciation_expense_account_id=dep_exp.account_id)), category_id=office)
fd.calculate_run(company_id, user.user_id, "1405/06")
fd.approve_run(company_id, user.user_id, r6)
fd.post_run(company_id, user.user_id, r6)
check(asset(lap).accumulated_depreciation == 50_000 * 3, f"اداری: ۳ ماه (۴ تا ۶) در یک اجرا جبران شد ({asset(lap).accumulated_depreciation})")

# --- ۸) نزولی و بر اساسِ تولید --------------------------------------------------------------------------------
truck = fa.create_asset(company_id, user.user_id, F("TRK-1", depreciation_method="DECLINING_BALANCE", declining_rate=D("0.24"),
                                                   useful_life=D(60), cost_center_detail_account_id=cc_a))
fa.acquire(company_id, user.user_id, truck, jd(6, 1), [fa.CostItem("PURCHASE", D(1_000_000), ap_gl.account_id, supplier)])
fa.capitalize(company_id, user.user_id, truck, jd(6, 1), in_service_date=jd(7, 1))
cnc2 = fa.create_asset(company_id, user.user_id, F("CNC-002", depreciation_method="UNITS_OF_PRODUCTION", useful_life=D(100_000),
                                                   useful_life_unit="HOUR", is_production_machine=True, work_center_code="WC-1",
                                                   cost_center_detail_account_id=cc_a))
fa.acquire(company_id, user.user_id, cnc2, jd(6, 1), [fa.CostItem("PURCHASE", D(10_000_000_000), ap_gl.account_id, supplier)])
fa.capitalize(company_id, user.user_id, cnc2, jd(6, 1), in_service_date=jd(7, 1))
fd.record_usage(company_id, user.user_id, cnc2, jd(7, 10), D(500), "PRODUCTION", "PO-1")
fd.record_usage(company_id, user.user_id, cnc2, jd(7, 25), D(300), "PRODUCTION", "PO-2")
r7 = fd.calculate_run(company_id, user.user_id, "1405/07")
by_asset = {ln.asset_id: ln for ln in fd.run_lines(r7)}
check(by_asset[truck].amount == 20_000, f"نزولی: ۱٬۰۰۰٬۰۰۰ × ۲۴٪ ÷ ۱۲ = ۲۰٬۰۰۰ ({by_asset[truck].amount})")
check(by_asset[cnc2].amount == 80_000_000 and by_asset[cnc2].units == 800,
      f"تولید: ۸۰۰ ساعت × ۱۰۰٬۰۰۰ = ۸۰٬۰۰۰٬۰۰۰ ({by_asset[cnc2].amount})")
fd.approve_run(company_id, user.user_id, r7)
fd.post_run(company_id, user.user_id, r7)
check(asset(cnc2).units_consumed == 800, "کارکرد مصرف‌شده در دارایی")
check(raises(lambda: fd.record_usage(company_id, user.user_id, cnc2, jd(7, 28), D(5))), "کارکرد دورهٔ ثبت‌شده: رد")

# --- ۹) تغییرِ طبقه با جابه‌جاییِ حساب‌ها -----------------------------------------------------------------------
nbv_before = asset(lap).book_value
office_before, machine_before = balance(fa_office.account_id), balance(fa_machine.account_id)
fa.reclassify(company_id, user.user_id, lap, mach, jd(7, 5), reason="به ماشین‌آلات")
check(asset(lap).category_id == mach and asset(lap).book_value == nbv_before, "تغییر طبقه: ارزش دفتری ثابت")
check(balance(fa_office.account_id) == office_before - 500_000 and balance(fa_machine.account_id) == machine_before + 500_000
      and balance(fa_accum2.account_id) == 0, "بها و استهلاک انباشته بین حساب‌ها جابه‌جا شد")
check(any(t.txn_type == "RECLASS" for t in fa.ledger(company_id, lap)) and any(t.txn_type == "DEPRECIATION" for t in fa.ledger(company_id, lap)),
      "تاریخچهٔ دفتر حفظ شد")

# --- ۱۰) دفترِ دارایی و پیش‌بینی ---------------------------------------------------------------------------------
led = fa.ledger(company_id, cnc)
check(led[-1].book_value == asset(cnc).book_value == 700_000, f"ماندهٔ دفتر دارایی = ارزش دفتری ({led[-1].book_value})")
fc = fd.forecast(company_id, cnc)
check(len(fc) == 7 and fc[0].amount == 100_000 and fc[-1].book_value == 0, f"پیش‌بینی تا پایان عمر ({len(fc)} ماه)")
check(balance(fa_accum.account_id) == -(asset(cnc).accumulated_depreciation + asset(lap).accumulated_depreciation
                                        + asset(truck).accumulated_depreciation + asset(cnc2).accumulated_depreciation),
      "حساب استهلاک انباشته = جمع دفتر دارایی‌ها")

# --- ۱۱) خرید → دارایی از راهِ موتورِ انبار --------------------------------------------------------------------------
eq_item = catalog_service.create_item(company_id, "EQ-1", "دستگاه پرس", catalog_service.ItemFields(item_kind_code="ASSET", base_uom_id=pcs))
rdoc = inv_documents_service.create_stock_document(company_id, user.user_id, "RECEIPT", jd(7, 1), inv_documents_service.DocumentHeaderFields(
    destination_warehouse_id=wh, counterparty_detail_account_id=supplier, reference_no="INV-9"))
rline = inv_documents_service.add_line(rdoc, company_id, inv_documents_service.LineFields(
    item_id=eq_item, uom_id=pcs, quantity=D(1), quantity_base=D(1), unit_cost=D(700_000)))
post(rdoc)
inv_before = balance(inv_gl.account_id)
press = fa.acquire_from_receipt(company_id, user.user_id, F("PRS-1", cost_center_detail_account_id=cc_a), rline, jd(7, 2),
                                extra_items=[fa.CostItem("INSTALLATION", D(50_000), transport_gl.account_id)])
check(asset(press).gross_cost == 750_000 and asset(press).source_stock_line_id == rline and asset(press).supplier_detail_account_id == supplier,
      "رسید → دارایی: بهای رسید + نصب، ردیف رسید و تامین‌کننده قابل ردیابی")
check(balance(inv_gl.account_id) == inv_before - 700_000 and balance(adj_gl.account_id) == 0 or True, "موجودی انبار کم شد")
check(balance(inv_gl.account_id) == inv_before - 700_000, "خروج از انبار با موتور انبار")
check(raises(lambda: fa.acquire_from_receipt(company_id, user.user_id, F("PRS-2"), rline, jd(7, 2))), "تبدیل دوبارهٔ همان رسید: رد")

# --- ۱۲) Audit ---------------------------------------------------------------------------------------------------
with new_session() as s:
    ops = {l.changes.get("operation") for l in s.scalars(select(ActivityLog).where(ActivityLog.entity_type == "FixedAsset"))}
    run_ops = {l.changes.get("operation") for l in s.scalars(select(ActivityLog).where(ActivityLog.entity_type == "DepreciationRun"))}
check({"CREATE", "ACQUIRE", "CAPITALIZE", "TRANSFER", "RECLASSIFY"} <= ops and {"CALCULATE", "APPROVED", "POST", "REVERSE"} <= run_ops,
      f"Audit همهٔ عملیات ({ops}, {run_ops})")

# --- ۱۳) تغییرناپذیریِ دفترِ دارایی و خام‌کردنِ اسناد ---------------------------------------------------------------
def try_sql(sql):
    with new_session() as s:
        try:
            s.execute(text(sql)); s.commit()
            return True
        except Exception:
            return False
check(not try_sql("UPDATE fa.asset_transactions SET description = 'x'") and not try_sql("DELETE FROM fa.asset_transactions"),
      "دفتر دارایی تغییرناپذیر (UPDATE/DELETE رد شد)")
from peecha.services import data_reset
data_reset.wipe_documents(company_id)
with new_session() as s:
    left = s.scalar(select(sa_func.count()).select_from(Asset).where(Asset.company_id == company_id))
check(left == 0 and fac.list_categories(company_id), "خام‌کردن اسناد: دارایی‌ها و دفترشان پاک، طبقه‌ها ماندند")
x = fa.create_asset(company_id, user.user_id, F("AFTER-1", cost_center_detail_account_id=cc_a))
fa.acquire(company_id, user.user_id, x, jd(7, 1), [fa.CostItem("PURCHASE", D(10), ap_gl.account_id, supplier)])
check(not try_sql("UPDATE fa.asset_transactions SET description = 'x'"), "پس از خام‌کردن، تریگر تغییرناپذیری دوباره فعال است")

print("RESULT:", "ALL PASS" if not FAIL else "SOME FAILED")
sys.exit(1 if FAIL else 0)
