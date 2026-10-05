import os, sys, datetime, decimal, io
os.environ["PEECHA_DB_NAME"] = "peecha_test_r264_1"
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
ap_gl = A("3201", "پرداختنیِ تامین‌کنندگان", "CREDIT", "LIABILITY", "PERMANENT", True, k8.account_id)
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
# R264: شمارشِ فیزیکی/QR، گارانتی/بیمه و هشدارها، اتصالِ تولید (ساعتِ ماشین ← بهایِ تولید)، گزارش‌ها، داشبورد
# =====================================================================
import jdatetime
from peecha.db.models.accounting import ChartOfAccount
from peecha.services.fixed_assets import common as fac, assets as fa, depreciation as fd, events as fe
from peecha.services.fixed_assets import physical as fp, production as fprod, reports as frep, dashboard as fdash
from peecha.services.purchase_reports import PurchaseFilters
from peecha.services import warehouse_reports as wr

with new_session() as _s:
    r1 = _s.scalar(select(ChartOfAccount.account_id).where(ChartOfAccount.company_id == company_id, ChartOfAccount.full_code == "1"))
    r5 = _s.scalar(select(ChartOfAccount.account_id).where(ChartOfAccount.company_id == company_id, ChartOfAccount.full_code == "5"))
k9 = A("14", "دارایی‌هایِ ثابت", "DEBIT", "ASSET", "PERMANENT", False, r1)
fa_asset = A("1401", "ماشین‌آلات", "DEBIT", "ASSET", "PERMANENT", True, k9.account_id)
fa_accum = A("1409", "استهلاکِ انباشته", "CREDIT", "ASSET", "PERMANENT", True, k9.account_id)
k12 = A("62", "سایر هزینه‌ها", "DEBIT", "EXPENSE", "TEMPORARY", False, r5)
dep_exp = A("6204", "هزینهٔ استهلاک", "DEBIT", "EXPENSE", "TEMPORARY", True, k12.account_id)
loss_gl = A("6201", "زیانِ واگذاری", "DEBIT", "EXPENSE", "TEMPORARY", True, k12.account_id)
mach = fac.save_category(company_id, fac.CategoryFields("MACH", "ماشین‌آلات", "STRAIGHT_LINE", 12, accounts=dict(
    asset_account_id=fa_asset.account_id, accumulated_depreciation_account_id=fa_accum.account_id,
    depreciation_expense_account_id=dep_exp.account_id, disposal_loss_account_id=loss_gl.account_id)))
cc_type = dimensions_service.get_specialized_dimension_type_id(company_id, dimensions_service.COST_CENTER_CODE)
cc_line = dimensions_service.create_detail_account(company_id, cc_type, "CC-L1", "خطِ تولیدِ ۱").detail_account_id
today = datetime.date.today()
def jd(m, d=1):
    return jdatetime.date(1405, m, d).togregorian()
F = lambda code, **kw: fa.AssetFields(asset_code=code, name=kw.pop("name", "دارایی " + code), category_id=mach, **kw)
def ready(code, cost, month=1, **kw):
    aid = fa.create_asset(company_id, user.user_id, F(code, **kw))
    fa.acquire(company_id, user.user_id, aid, jd(month), [fa.CostItem("PURCHASE", D(cost), ap_gl.account_id, supplier)])
    fa.capitalize(company_id, user.user_id, aid, jd(month), in_service_date=jd(month))
    return aid
def run(code):
    rid = fd.calculate_run(company_id, user.user_id, code)
    fd.approve_run(company_id, user.user_id, rid)
    fd.post_run(company_id, user.user_id, rid)

site = fac.save_location(company_id, "SITE-1", "کارخانه", "SITE")
hall = fac.save_location(company_id, "HALL-1", "سالنِ ۱", "ROOM", parent_location_id=site)
store = fac.save_location(company_id, "STORE", "انبارِ تجهیزات", "ROOM")
a1 = ready("PC-1", 100_000, location_id=hall, cost_center_detail_account_id=cc_line)
a2 = ready("PC-2", 100_000, location_id=hall, cost_center_detail_account_id=cc_line)
a3 = ready("PC-3", 100_000, location_id=hall, cost_center_detail_account_id=cc_line)
a4 = ready("PC-4", 100_000, location_id=store, cost_center_detail_account_id=cc_line)
a5 = ready("PC-5", 100_000, location_id=hall, cost_center_detail_account_id=cc_line)

# --- ۱) QR/بارکد ---------------------------------------------------------------------------------------------
asset1 = fa.get_asset(company_id, a1)
check(fa.qr_payload(asset1) == f"PEECHA-FA:{a1}:PC-1" and asset1.barcode == "PC-1", "QR یکتا و بارکد = کدِ دارایی")
check(fa.find_by_code(company_id, fa.qr_payload(asset1)).asset_id == a1 and fa.find_by_code(company_id, "PC-1").asset_id == a1,
      "یافتنِ دارایی با QR و بارکد")
check(fa.find_by_code(company_id, "NOPE") is None, "کدِ ناشناخته")

# --- ۲) شمارشِ فیزیکی: یافت، مفقود، محلِ نادرست، جابه‌جاشده، آسیب‌دیده -------------------------------------------------
cnt = fp.create_count(company_id, user.user_id, "CNT-1", today, location_id=site)
items = {i.asset_code: i for i in fp.count_items(company_id, cnt)}
check(set(items) == {"PC-1", "PC-2", "PC-3", "PC-5"}, "فهرستِ مورد انتظار = دارایی‌هایِ کارخانه و زیرمحل‌ها")
check(fp.scan(company_id, cnt, fa.qr_payload(asset1), hall, method="QR").result == "FOUND", "اسکنِ QR: یافت شد")
check(fp.scan(company_id, cnt, "PC-2", site, method="BARCODE").result == "WRONG_LOCATION", "محلِ نادرست")
check(fp.scan(company_id, cnt, "PC-4", hall, method="MOBILE").result == "MOVED", "داراییِ محلِ دیگر اینجا: جابه‌جاشده")
check(fp.scan(company_id, cnt, "PC-5", hall, damaged=True, method="MANUAL").result == "DAMAGED", "آسیب‌دیده")
summary = fp.close_count(company_id, user.user_id, cnt, apply_moves=True)
check(summary.get("MISSING") == 1 and summary.get("FOUND") == 1, f"بستنِ شمارش: PC-3 مفقود ({summary})")
check(fa.get_asset(company_id, a4).location_id == hall and fa.get_asset(company_id, a2).location_id == site,
      "اعمالِ جابه‌جایی‌ها با «انتقال»")
check(raises(lambda: fp.scan(company_id, cnt, "PC-3")), "اسکن در شمارشِ بسته: رد")
diffs = fp.count_items(company_id, cnt, discrepancies_only=True)
check({d.asset_code for d in diffs} == {"PC-2", "PC-3", "PC-4", "PC-5"}, "گزارشِ مغایرت")

# --- ۳) گارانتی/بیمه و هشدارها -------------------------------------------------------------------------------
fp.add_warranty(company_id, a1, today - datetime.timedelta(days=300), today + datetime.timedelta(days=20), "گارانتیِ سازنده",
                supplier, "W-1")
fp.add_warranty(company_id, a2, today - datetime.timedelta(days=300), today + datetime.timedelta(days=5))
fp.add_insurance(company_id, a5, "بیمهٔ ایران", today - datetime.timedelta(days=400), today - datetime.timedelta(days=2),
                 "P-9", D(1_000), "آتش‌سوزی", D(100_000))
check(raises(lambda: fp.add_warranty(company_id, a1, today, today - datetime.timedelta(days=1))), "تاریخِ نادرستِ گارانتی: رد")
al = fp.alerts(company_id, today)
kinds = {(x.kind, x.level, x.asset_id) for x in al}
check(("WARRANTY", "DAYS_30", a1) in kinds and ("WARRANTY", "DAYS_7", a2) in kinds and ("INSURANCE", "EXPIRED", a5) in kinds,
      "هشدارِ گارانتی (۳۰ و ۷ روز) و بیمهٔ منقضی")
check(("MISSING", "DANGER", a3) in kinds, "هشدارِ داراییِ مفقود")

# --- ۴) ماشینِ تولید: ساعت ← استهلاک ← نرخ ← سفارشِ تولید (مثالِ مشخصات) ------------------------------------------------
cnc = ready("CNC-1", 1_200_000_000, month=2, is_production_machine=True, work_center_code="WC-1", production_line="خطِ ۱",
            capacity_per_hour=D(20), standard_hours=D(12_000), cost_center_detail_account_id=cc_line)
fd.record_usage(company_id, user.user_id, cnc, jd(2, 10), D(600), "PRODUCTION", "PO-1")
fd.record_usage(company_id, user.user_id, cnc, jd(2, 20), D(400), "PRODUCTION", "PO-2")
run("1405/01"); run("1405/02")
info = fprod.machine_rate(company_id, cnc, "1405/02")
check(info.depreciation == 100_000_000 and info.hours == 1000 and info.rate == 100_000,
      f"نرخِ ماشین = ۱۰۰٬۰۰۰٬۰۰۰ ÷ ۱٬۰۰۰ ساعت = ۱۰۰٬۰۰۰ ({info.rate})")
alloc = fprod.allocate_to_order(company_id, user.user_id, cnc, "1405/02", "PO-1", D(250))
check(alloc.amount == 25_000_000 and fprod.order_machine_cost(company_id, "PO-1") == 25_000_000,
      "سفارشِ تولید با ۲۵۰ ساعت: بهایِ ماشین ۲۵٬۰۰۰٬۰۰۰")
check(raises(lambda: fprod.allocate_to_order(company_id, user.user_id, cnc, "1405/02", "PO-3", D(800))), "تخصیصِ بیش از کارکرد: رد")
check(raises(lambda: fprod.allocate_to_order(company_id, user.user_id, a1, "1405/02", "PO-1", D(1))), "داراییِ غیرِتولیدی: رد")
m = fprod.machines(company_id, "WC-1")
check(len(m) == 1 and m[0].actual_hours == 1000 and m[0].standard_hours == 12_000, "ماشین ← مرکزِ کار ← ساعتِ استاندارد/واقعی")

# --- ۵) همهٔ گزارش‌ها در موتورِ عمومی ---------------------------------------------------------------------------
check(all(r.code in wr.WAREHOUSE_REPORTS_BY_CODE for r in frep.FA_REPORTS) and len(frep.FA_REPORTS) == 15, "۱۵ گزارشِ دارایی ثبت شد")
fe.scrap(company_id, user.user_id, a3, today, "مفقودی")
f = PurchaseFilters(jd(1), today, side="INVENTORY")
res = {}
for rdef in frep.FA_REPORTS:
    try:
        res[rdef.code] = rdef.func(company_id, PurchaseFilters(jd(1), today, side="INVENTORY", options={}))
        ok = True
    except Exception as exc:  # noqa: BLE001
        ok = False
        print("   ", rdef.code, repr(exc))
    check(ok, f"گزارشِ {rdef.code} اجرا شد")
reg = res["FA_REGISTER"]
check(len(reg.rows) == 5 and all(ref and ref[1] == "FA_ASSET" for ref in reg.refs), "دفترِ دارایی‌ها: ۵ داراییِ فعال، دابل‌کلیک به دارایی")
check(len(res["FA_DEPRECIATION"].rows) >= 6 and res["FA_DISPOSALS"].rows[0][3] == "اسقاط", "گزارشِ استهلاک و واگذاری")
mc = frep.machine_cost(company_id, PurchaseFilters(jd(2), jd(2, 28), side="INVENTORY"))
check(mc.rows[0][6] == 100_000 and mc.rows[0][7] == 25_000_000, "گزارشِ بهایِ ماشین‌آلاتِ تولید")
check(any("خطِ تولیدِ ۱" in r[0] for r in res["FA_BY_COST_CENTER"].rows), "دارایی به تفکیکِ مرکزِ هزینه")
check(sum(r[1] for r in res["FA_FORECAST"].rows) > 0, "پیش‌بینیِ استهلاک")
check(res["FA_PHYSICAL"].rows and res["FA_GAIN_LOSS"].rows[0][6] < 0, "شمارش و سود/زیان")

# --- ۶) داشبورد ----------------------------------------------------------------------------------------------
kpis, charts, alert_rows, alerts = fdash.dashboard(company_id, jd(1), today)
k = {x.code: x for x in kpis}
check(k["COUNT"].value == 5 and k["GROSS"].value == 1_200_400_000 and k["NBV"].value == k["GROSS"].value - k["ACCUM"].value,
      f"داشبورد: تعداد/بها/ارزشِ دفتری ({k['GROSS'].value})")
check(k["DISPOSED"].value == 1 and set(charts) == {c[0] for c in fdash.CHART_TITLES} and alert_rows, "داشبورد: واگذاری، نمودارها، هشدارها")
check(all(x.report_code in wr.WAREHOUSE_REPORTS_BY_CODE for x in kpis), "هر شاخص به گزارشِ مبدأ وصل است")

print("RESULT:", "ALL PASS" if not FAIL else "SOME FAILED")
sys.exit(1 if FAIL else 0)
