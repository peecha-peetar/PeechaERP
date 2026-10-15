import os, sys, datetime, decimal, io
os.environ["PEECHA_DB_NAME"] = "peecha_test_r263_1"
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
# R263: رویدادهایِ دارایی -- بهسازی/تعمیر، کاهشِ ارزش، تجدیدِ ارزیابی، فروش با سود/زیان، اسقاط، تقسیم، ادغام، جزء، CIP
# =====================================================================
import jdatetime
from peecha.db.models.accounting import JournalEntryLine, ChartOfAccount
from peecha.db.models.fixed_assets import Asset, AssetTransaction, CipProject
from peecha.services.fixed_assets import common as fac, assets as fa, depreciation as fd, events as fe

with new_session() as _s:
    root = lambda code: _s.scalar(select(ChartOfAccount.account_id).where(ChartOfAccount.company_id == company_id, ChartOfAccount.full_code == code))
    r1, r4, r5 = root("1"), root("4"), root("5")
k9 = A("14", "دارایی‌های ثابت", "DEBIT", "ASSET", "PERMANENT", False, r1)
fa_asset = A("1401", "ماشین‌آلات", "DEBIT", "ASSET", "PERMANENT", True, k9.account_id)
fa_line = A("1403", "خطوط تولید", "DEBIT", "ASSET", "PERMANENT", True, k9.account_id)
fa_cip = A("1407", "دارایی در جریان تکمیل", "DEBIT", "ASSET", "PERMANENT", True, k9.account_id)
fa_accum = A("1409", "استهلاک انباشته", "CREDIT", "ASSET", "PERMANENT", True, k9.account_id)
g9 = A("3", "حقوق مالکانه", "CREDIT", "EQUITY", "PERMANENT", False)
k13 = A("31", "مازادها", "CREDIT", "EQUITY", "PERMANENT", False, g9.account_id)
reval_gl = A("3101", "مازاد تجدید ارزیابی", "CREDIT", "EQUITY", "PERMANENT", True, k13.account_id)
k11 = A("42", "سایر درآمدها", "CREDIT", "REVENUE", "TEMPORARY", False, r4)
gain_gl = A("4201", "سود فروش دارایی", "CREDIT", "REVENUE", "TEMPORARY", True, k11.account_id)
k12 = A("62", "سایر هزینه‌ها", "DEBIT", "EXPENSE", "TEMPORARY", False, r5)
loss_gl = A("6201", "زیان فروش دارایی", "DEBIT", "EXPENSE", "TEMPORARY", True, k12.account_id)
imp_gl = A("6202", "زیان کاهش ارزش", "DEBIT", "EXPENSE", "TEMPORARY", True, k12.account_id)
maint_gl = A("6203", "تعمیر و نگهداری", "DEBIT", "EXPENSE", "TEMPORARY", True, k12.account_id)
dep_exp = A("6204", "هزینهٔ استهلاک", "DEBIT", "EXPENSE", "TEMPORARY", True, k12.account_id)
labor_gl = A("3203", "حقوق پرداختنی", "CREDIT", "LIABILITY", "PERMANENT", True, k8.account_id)

def jd(m, d=1):
    return jdatetime.date(1405, m, d).togregorian()
def balance(account_id):
    with new_session() as s:
        return s.scalar(select(sa_func.coalesce(sa_func.sum(JournalEntryLine.debit_amount_base - JournalEntryLine.credit_amount_base), 0))
                        .where(JournalEntryLine.account_id == account_id))
def asset(asset_id):
    return fa.get_asset(company_id, asset_id)
ALL = dict(asset_account_id=fa_asset.account_id, accumulated_depreciation_account_id=fa_accum.account_id,
           depreciation_expense_account_id=dep_exp.account_id, disposal_gain_account_id=gain_gl.account_id,
           disposal_loss_account_id=loss_gl.account_id, impairment_account_id=imp_gl.account_id,
           revaluation_account_id=reval_gl.account_id, cip_account_id=fa_cip.account_id, maintenance_expense_account_id=maint_gl.account_id)
mach = fac.save_category(company_id, fac.CategoryFields("MACH", "ماشین‌آلات", "STRAIGHT_LINE", 10, accounts=ALL))
line_cat = fac.save_category(company_id, fac.CategoryFields("LINE", "خطوط تولید", "STRAIGHT_LINE", 10, accounts={**ALL, "asset_account_id": fa_line.account_id}))
F = lambda code, **kw: fa.AssetFields(asset_code=code, name=kw.pop("name", "دارایی " + code), category_id=kw.pop("category_id", mach), **kw)
def ready(code, cost, month=1, **kw):
    """دارایی با بها، سرمایه‌ای و در بهره‌برداری از ماه month."""
    aid = fa.create_asset(company_id, user.user_id, F(code, **kw))
    fa.acquire(company_id, user.user_id, aid, jd(month), [fa.CostItem("PURCHASE", D(cost), ap_gl.account_id, supplier)])
    fa.capitalize(company_id, user.user_id, aid, jd(month), in_service_date=jd(month))
    return aid
def run(code):
    rid = fd.calculate_run(company_id, user.user_id, code)
    fd.approve_run(company_id, user.user_id, rid)
    fd.post_run(company_id, user.user_id, rid)

# --- ۱) فروش با سود و با زیان (مثال‌هایِ مشخصات: دفتری ۸، فروش ۹ → سود ۱؛ فروش ۶ → زیان ۲) -------------------------
s1 = ready("S-1", 10_000_000)
s2 = ready("S-2", 10_000_000)
run("1405/01"); run("1405/02")     # ۲ ماه × ۱٬۰۰۰٬۰۰۰ → ارزشِ دفتری ۸٬۰۰۰٬۰۰۰
check(asset(s1).book_value == 8_000_000, "ارزش دفتری پیش از فروش = ۸٬۰۰۰٬۰۰۰")
gain_before, loss_before = balance(gain_gl.account_id), balance(loss_gl.account_id)
ev = fe.sell(company_id, user.user_id, s1, jd(3, 5), D(9_000_000), ar_gl.account_id, reason="فروش", idempotency_key="SELL-S1")
check(ev.gain_loss == 1_000_000 and ev.previous_book_value == 8_000_000 and asset(s1).status_code == "SOLD", "فروش با سود ۱٬۰۰۰٬۰۰۰")
check(balance(gain_gl.account_id) - gain_before == -1_000_000, "سود فروش در حساب")
check(asset(s1).gross_cost == 0 and asset(s1).accumulated_depreciation == 0, "بها و استهلاک انباشته از دفاتر خارج شد")
check(fe.sell(company_id, user.user_id, s1, jd(3, 5), D(9_000_000), ar_gl.account_id, idempotency_key="SELL-S1").event_id == ev.event_id,
      "فروش دوباره با همان کلید: بدون سند دوم")
check(raises(lambda: fe.sell(company_id, user.user_id, s1, jd(3, 6), D(1), ar_gl.account_id)), "فروش دارایی فروخته‌شده: رد")
check(raises(lambda: fa.transfer(company_id, user.user_id, s1, jd(3, 6), location_id=None, branch_id=None) or
              fe.improve(company_id, user.user_id, s1, jd(3, 6), D(10), ap_gl.account_id)), "عملیات روی دارایی واگذارشده: رد")
ev2 = fe.sell(company_id, user.user_id, s2, jd(3, 5), D(6_000_000), ar_gl.account_id)
check(ev2.gain_loss == -2_000_000 and balance(loss_gl.account_id) - loss_before == 2_000_000, "فروش با زیان ۲٬۰۰۰٬۰۰۰")

# --- ۲) اسقاط --------------------------------------------------------------------------------------------------
sc = ready("SC-1", 1_000_000)
check(raises(lambda: fe.scrap(company_id, user.user_id, sc, jd(3, 1), "")), "اسقاط بدون علت: رد")
ev = fe.scrap(company_id, user.user_id, sc, jd(3, 1), "خرابی غیرقابل‌تعمیر", "سوخته", D(50_000), cash_gl.account_id)
check(asset(sc).status_code == "SCRAPPED" and ev.gain_loss == -(1_000_000 - 50_000) and ev.condition_note == "سوخته",
      f"اسقاط: ارزش ضایعات ۵۰٬۰۰۰، زیان ({ev.gain_loss})")

# --- ۳) بهسازی (سرمایه‌ای) در برابرِ تعمیر (هزینه) طبقِ سیاست ------------------------------------------------------------
m = ready("M-1", 10_000_000, month=3)
fac.update_settings(company_id, user.user_id, improvement_capitalize_min=D(500_000))
fe.improve(company_id, user.user_id, m, jd(3, 10), D(2_000_000), ap_gl.account_id, supplier, "ارتقای کنترلر", extend_life_months=2)
check(asset(m).gross_cost == 12_000_000 and asset(m).useful_life == 12, "افزایش سرمایه‌ای: بها ۱۲ میلیارد (مثال: ۱۰+۲)، عمر +۲ ماه")
maint_before = balance(maint_gl.account_id)
ev = fe.improve(company_id, user.user_id, m, jd(3, 11), D(100_000), ap_gl.account_id, supplier, "تعویض روغن")
check(ev.event_type == "MAINTENANCE" and asset(m).gross_cost == 12_000_000 and balance(maint_gl.account_id) - maint_before == 100_000,
      "تعمیر زیر حد سیاست: هزینه، نه افزایش بها")

# --- ۴) کاهشِ ارزش ---------------------------------------------------------------------------------------------
run("1405/03")
nbv = asset(m).book_value
check(raises(lambda: fe.impair(company_id, user.user_id, m, jd(4, 1), nbv + 1, "x")), "مبلغ بازیافتنی بیشتر از دفتری: رد")
imp_before = balance(imp_gl.account_id)
ev = fe.impair(company_id, user.user_id, m, jd(4, 1), nbv - 300_000, "افت قیمت بازار")
check(ev.amount == 300_000 and asset(m).accumulated_impairment == 300_000 and asset(m).status_code == "IMPAIRED"
      and balance(imp_gl.account_id) - imp_before == 300_000, "کاهش ارزش ۳۰۰٬۰۰۰")
run("1405/04")
check(asset(m).status_code == "IMPAIRED" and asset(m).accumulated_depreciation > 0, "دارایی کاهش‌ارزش‌یافته استهلاک می‌خورد")

# --- ۵) تجدیدِ ارزیابی (افزایش و سپس کاهش) -------------------------------------------------------------------------
before = asset(m).book_value
ev = fe.revalue(company_id, user.user_id, m, jd(5, 1), before + 800_000, "ارزیابی کارشناس")
a = asset(m)
check(a.book_value == before + 800_000 and a.accumulated_depreciation == 0 and a.accumulated_impairment == 0
      and a.gross_cost == before + 800_000 and a.revaluation_surplus == 800_000, "تجدید ارزیابی: حذف استهلاک و بها = ارزش جدید")
check(balance(reval_gl.account_id) == -800_000 and a.status_code == "IN_SERVICE", "مازاد در حقوق مالکانه")
loss_before = balance(imp_gl.account_id)
fe.revalue(company_id, user.user_id, m, jd(5, 2), a.book_value - 1_000_000, "کاهش ارزش بازار")
check(balance(reval_gl.account_id) == 0 and balance(imp_gl.account_id) - loss_before == 200_000 and asset(m).revaluation_surplus == 0,
      "کاهش: ۸۰۰٬۰۰۰ از مازاد، ۲۰۰٬۰۰۰ زیان")
nbv_m = asset(m).book_value
run("1405/05")
check(asset(m).accumulated_depreciation > 0 and asset(m).book_value < nbv_m, "استهلاک از ارزش تجدیدارزیابی‌شده")

# --- ۶) تقسیم -------------------------------------------------------------------------------------------------
sp = ready("SP-1", 10_000_000, month=5)
run_code = "1405/06"; run(run_code)
dep_sp = asset(sp).accumulated_depreciation
check(raises(lambda: fe.split(company_id, user.user_id, sp, jd(6, 15), [("SP-A", "A", D(6_000_000)), ("SP-B", "B", D(3_000_000))])),
      "تقسیم با جمع نابرابر: رد")
ids = fe.split(company_id, user.user_id, sp, jd(6, 15), [("SP-A", "بخش A", D(6_000_000)), ("SP-B", "بخش B", D(4_000_000))])
pa, pb = asset(ids[0]), asset(ids[1])
check(pa.gross_cost == 6_000_000 and pb.gross_cost == 4_000_000 and pa.accumulated_depreciation + pb.accumulated_depreciation == dep_sp,
      "تقسیم ۱۰ میلیارد ← ۶ + ۴ با استهلاک متناسب")
check(asset(sp).status_code == "SPLIT" and asset(sp).gross_cost == 0 and pa.depreciated_months_offset == 2,
      "مبدأ «تقسیم‌شده»، عمر گذشته منتقل شد")
run("1405/07")
check(asset(ids[0]).accumulated_depreciation - pa.accumulated_depreciation == 600_000, "استهلاک بخش A ادامه با عمر باقی‌مانده (۶۰۰٬۰۰۰)")

# --- ۷) ادغام (ماشین + تجهیزاتِ جانبی ← خطِ تولید؛ طبقهٔ متفاوت → سندِ جابه‌جایی) ---------------------------------------
ln = ready("LN-1", 5_000_000, month=7, category_id=line_cat)
ex = ready("EX-1", 1_000_000, month=7)
line_before, mach_before = balance(fa_line.account_id), balance(fa_asset.account_id)
fe.merge(company_id, user.user_id, ln, [ex], jd(7, 20), reason="یکپارچه‌سازی خط")
check(asset(ln).gross_cost == 6_000_000 and asset(ex).status_code == "MERGED" and asset(ex).gross_cost == 0, "ادغام: بها به خط تولید")
check(balance(fa_line.account_id) - line_before == 1_000_000 and balance(fa_asset.account_id) - mach_before == -1_000_000,
      "ادغام بین طبقه‌ها: بها بین حساب‌ها جابه‌جا شد")
check(any(t.txn_type == "MERGE_OUT" for t in fa.ledger(company_id, ex)), "تاریخچهٔ دارایی ادغام‌شده حفظ شد")

# --- ۸) جزء (Component) با عمرِ مستقل ---------------------------------------------------------------------------
cnc = ready("CNC-9", 12_000_000, month=7)
motor = fe.carve_component(company_id, user.user_id, cnc, F("CNC-9-MTR", name="موتور CNC", useful_life=D(4)), D(2_000_000), jd(7, 5))
check(asset(motor).parent_asset_id == cnc and asset(cnc).gross_cost == 10_000_000 and asset(motor).gross_cost == 2_000_000,
      "جزء موتور با بهای مستقل")
check([r.asset_id for r in fe.components(company_id, cnc)] == [motor], "فهرست اجزای دارایی")
check(raises(lambda: fe.sell(company_id, user.user_id, cnc, jd(7, 9), D(1), ar_gl.account_id)), "فروش دارایی دارای جزء فعال: رد")

# --- ۹) دارایی در جریانِ تکمیل → دارایی ------------------------------------------------------------------------------
cip = fe.create_cip(company_id, user.user_id, "CIP-1", "ساخت خط تولید", line_cat, jd(6, 1))
part = catalog_service.create_item(company_id, "PART-1", "قطعهٔ ساخت", catalog_service.ItemFields(item_kind_code="GOOD", base_uom_id=pcs))
rdoc = inv_documents_service.create_stock_document(company_id, user.user_id, "RECEIPT", jd(6, 1), inv_documents_service.DocumentHeaderFields(
    destination_warehouse_id=wh, counterparty_detail_account_id=supplier))
inv_documents_service.add_line(rdoc, company_id, inv_documents_service.LineFields(item_id=part, uom_id=pcs, quantity=D(10), quantity_base=D(10), unit_cost=D(30_000)))
post(rdoc)
fe.add_cip_material(company_id, user.user_id, cip, jd(6, 2), part, wh, D(10), pcs)
fe.add_cip_cost(company_id, user.user_id, cip, jd(6, 3), "LABOR", D(200_000), labor_gl.account_id)
fe.add_cip_cost(company_id, user.user_id, cip, jd(6, 4), "INSTALLATION", D(100_000), ap_gl.account_id, supplier)
check(balance(fa_cip.account_id) == 600_000 and fe.list_cip(company_id)[0].total == 600_000, "CIP: مواد ۳۰۰٬۰۰۰ + دستمزد + نصب")
new_asset = fe.capitalize_cip(company_id, user.user_id, cip, jd(7, 1), F("LN-NEW", name="خط تولید جدید", category_id=line_cat),
                              in_service_date=jd(7, 1))
check(asset(new_asset).gross_cost == 600_000 and asset(new_asset).status_code == "IN_SERVICE" and asset(new_asset).source_code == "CONSTRUCTION",
      "CIP ← دارایی با جمع بهای سرمایه‌ای")
check(balance(fa_cip.account_id) == 0 and fe.list_cip(company_id)[0].status == "CAPITALIZED", "حساب CIP بسته شد")
check(raises(lambda: fe.add_cip_cost(company_id, user.user_id, cip, jd(7, 2), "LABOR", D(1), labor_gl.account_id)), "هزینه روی CIP بسته: رد")
check(len(fd.forecast(company_id, new_asset)) == 10, "برنامهٔ استهلاک دارایی جدید")

# --- ۱۰) جمع‌بندیِ حساب‌ها ----------------------------------------------------------------------------------------
with new_session() as s:
    gross = s.scalar(select(sa_func.coalesce(sa_func.sum(Asset.gross_cost), 0)).where(Asset.company_id == company_id))
    accum = s.scalar(select(sa_func.coalesce(sa_func.sum(Asset.accumulated_depreciation + Asset.accumulated_impairment), 0))
                     .where(Asset.company_id == company_id))
check(balance(fa_asset.account_id) + balance(fa_line.account_id) == gross, f"حساب‌های دارایی = جمع بهای دارایی‌ها ({gross})")
check(-balance(fa_accum.account_id) == accum, "استهلاک انباشته = جمع دفتر دارایی‌ها")

print("RESULT:", "ALL PASS" if not FAIL else "SOME FAILED")
sys.exit(1 if FAIL else 0)
