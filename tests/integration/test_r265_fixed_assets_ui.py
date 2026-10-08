import os, sys, datetime, decimal, io
os.environ["PEECHA_DB_NAME"] = "peecha_test_r265_1"
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
# R265: دارایی‌هایِ ثابت -- صفحه‌ها (ویزارد، مرکزِ عملیات، استهلاک، CIP، شمارش، تنظیمات)، تأییدِ کارتابل، دسترسی، انتقالِ قبلی‌ها
# =====================================================================
import tempfile, pathlib, jdatetime
from peecha.db.models.accounting import ChartOfAccount
from peecha.db.models.fixed_assets import Asset, AssetEvent
from peecha.services.fixed_assets import common as fac, assets as fa, depreciation as fd, events as fe, approval
from peecha.services import cartable, inventory_extended
from peecha.ui.screens import fixed_assets as ui
from peecha import nav_catalog

with new_session() as _s:
    r1 = _s.scalar(select(ChartOfAccount.account_id).where(ChartOfAccount.company_id == company_id, ChartOfAccount.full_code == "1"))
    r4 = _s.scalar(select(ChartOfAccount.account_id).where(ChartOfAccount.company_id == company_id, ChartOfAccount.full_code == "4"))
    r5 = _s.scalar(select(ChartOfAccount.account_id).where(ChartOfAccount.company_id == company_id, ChartOfAccount.full_code == "5"))
k9 = A("14", "دارایی‌های ثابت", "DEBIT", "ASSET", "PERMANENT", False, r1)
fa_asset = A("1401", "ماشین‌آلات", "DEBIT", "ASSET", "PERMANENT", True, k9.account_id)
fa_cip = A("1407", "دارایی در جریان تکمیل", "DEBIT", "ASSET", "PERMANENT", True, k9.account_id)
fa_accum = A("1409", "استهلاک انباشته", "CREDIT", "ASSET", "PERMANENT", True, k9.account_id)
k11 = A("42", "سایر درآمدها", "CREDIT", "REVENUE", "TEMPORARY", False, r4)
gain_gl = A("4201", "سود فروش دارایی", "CREDIT", "REVENUE", "TEMPORARY", True, k11.account_id)
k12 = A("62", "سایر هزینه‌ها", "DEBIT", "EXPENSE", "TEMPORARY", False, r5)
loss_gl = A("6201", "زیان واگذاری", "DEBIT", "EXPENSE", "TEMPORARY", True, k12.account_id)
imp_gl = A("6202", "زیان کاهش ارزش", "DEBIT", "EXPENSE", "TEMPORARY", True, k12.account_id)
maint_gl = A("6203", "تعمیرات", "DEBIT", "EXPENSE", "TEMPORARY", True, k12.account_id)
dep_exp = A("6204", "هزینهٔ استهلاک", "DEBIT", "EXPENSE", "TEMPORARY", True, k12.account_id)
today = datetime.date.today()
def jd(m, d=1):
    return jdatetime.date(1405, m, d).togregorian()
sess.current_user = user
fac.ensure_default_categories(company_id)
cat_id = {c.code: c.category_id for c in fac.list_categories(company_id)}["MACHINERY"]

# --- ۱) منو، فرم‌ها و ماژول --------------------------------------------------------------------------------
codes = [i["code"] for i in nav_catalog.NAV_ITEMS]
check("FA" in codes, "«دارایی‌های ثابت» در منوی اصلی")
forms = {fo.code: fo for fo in roles_service.list_forms()}
need = {"fa_dashboard", "fa_assets", "fa_depreciation", "fa_cip", "fa_physical_count", "fa_setup", "fa_capitalize", "fa_transfer",
        "fa_reclassify", "fa_improve", "fa_impair", "fa_revalue", "fa_sell", "fa_scrap", "fa_dispose", "fa_cost_view", "fa_cost_adjust"}
check(need <= set(forms) and all(forms[f].module_code == "FA" for f in need), "دسترسی‌های جداگانهٔ دارایی در ماژول FA")

# --- ۲) تنظیمات: طبقه با حساب‌ها، محل، گروه، سیاست ----------------------------------------------------------------
setup = ui.SetupScreen(); setup.refresh()
setup.cat_table.selectRow(next(r for r in range(setup.cat_table.rowCount()) if setup.cat_table.item(r, 0).data(ui.Qt.UserRole) == cat_id))
for key, acc in (("asset_account_id", fa_asset), ("accumulated_depreciation_account_id", fa_accum), ("depreciation_expense_account_id", dep_exp),
                 ("disposal_gain_account_id", gain_gl), ("disposal_loss_account_id", loss_gl), ("impairment_account_id", imp_gl),
                 ("cip_account_id", fa_cip), ("maintenance_expense_account_id", maint_gl)):
    ui.set_combo(setup.cat_accounts[key], acc.account_id)
setup.cat_life.setText("۱۲")
check(setup.save_category(), "ذخیرهٔ طبقه با حساب‌ها از صفحهٔ تنظیمات")
check(not fac.missing_accounts(next(c for c in fac.list_categories(company_id) if c.category_id == cat_id),
                                ("asset_account_id", "accumulated_depreciation_account_id", "depreciation_expense_account_id")),
      "حساب‌های طبقه کامل")
setup.loc_code.setText("F1"); setup.loc_name.setText("کارخانهٔ ۱"); ui.set_combo(setup.loc_type, "SITE")
check(setup.save_location(), "افزودن محل")
setup.grp_code.setText("G1"); setup.grp_name.setText("خط ۱")
check(setup.save_group(), "افزودن گروه")
setup.improve_min.setText("۵۰۰٬۰۰۰"); setup.save_settings()
check(fac.get_settings(company_id).improvement_capitalize_min == 500_000, "سیاست حد سرمایه‌ای‌شدن")
loc_id = fac.list_locations(company_id)[0].location_id

# --- ۳) ویزاردِ هفت‌مرحله‌ای ---------------------------------------------------------------------------------
scr = ui.AssetsScreen(); scr.refresh()
scr.confirm = lambda text: True
wiz = ui.AssetWizard(ui.Lookups(company_id))
w = wiz.w
w["asset_code"].setText("CNC-01"); w["name"].setText("ماشین CNC"); ui.set_combo(w["asset_type_code"], "MACHINE")
w["purchase"].setText("۱٬۰۰۰٬۰۰۰"); w["transport"].setText("۱۰۰٬۰۰۰"); w["installation"].setText("۱۰۰٬۰۰۰")
ui.set_combo(w["offset_account"], ap_gl.account_id); ui.set_combo(w["supplier"], supplier)
w["acquisition_date"].setDate(jd(1)); w["in_service_date"].setDate(jd(1))
ui.set_combo(w["category_id"], cat_id); ui.set_combo(w["location_id"], loc_id)
for i in range(5):
    wiz._next()
check(wiz.stack.currentIndex() == 5 and ui.money(D(1_200_000)) in wiz.review.text(), "مرحلهٔ بررسی با جمع بها")
wiz._next()
cnc = wiz.created_asset_id
a = fa.get_asset(company_id, cnc)
check(cnc and a.gross_cost == 1_200_000 and a.status_code == "IN_SERVICE" and a.location_id == loc_id, "ثبت با ویزارد: بها، سرمایه‌ای و در بهره‌برداری")
wiz2 = ui.AssetWizard(ui.Lookups(company_id))
wiz2._next()
check(wiz2.stack.currentIndex() == 0, "ویزارد بدون کد/نام جلو نمی‌رود")

# --- ۴) مرکزِ عملیات: صفحهٔ دارایی و تب‌ها --------------------------------------------------------------------
scr.reload_list(); scr.open_asset(cnc)
check(scr.asset.asset_id == cnc and ui.P("CNC-01") in scr.header_title.text() and scr.tabs.count() == 8, "صفحهٔ دارایی با ۸ تب")
check(scr.t_ledger.rowCount() >= 2 and scr.t_financial.rowCount() == 3 and scr.t_depr.rowCount() == 12, "تب‌های دفتر، مالی و استهلاک")
check(ui.money(D(1_200_000)) in scr.cards["gross"].text() and "بهره‌برداری" in scr.cards["status"].text(), "کارت‌های ارزش و وضعیت")
img = scr.print_label()
check(not img.isNull() and img.width() > 500, "برچسب QR/بارکد")
scr.search.setText(fa.qr_payload(a)); scr.reload_list()
check(scr.list_table.rowCount() == 1, "جستجو با QR")
scr.search.clear(); scr.reload_list(); scr.open_asset(cnc)
tmp = pathlib.Path(tempfile.mkdtemp()) / "invoice.pdf"; tmp.write_bytes(b"%PDF-1.4 test")
ui.set_combo(scr.doc_type, "INVOICE")
check(scr.add_document(str(tmp)) and scr.t_docs.rowCount() == 1, "پیوست مدرک (فاکتور) با سیستم پیوست موجود")
check(scr.run_operation("transfer", {"date": jd(2), "location_id": None, "cost_center_detail_account_id": None,
                                      "custodian_employee_id": None, "branch_id": None, "department_id": None, "reason": "x"}) is None,
      "انتقال بدون تغییر: پیام خطا")
loc2 = fac.save_location(company_id, "F2", "کارخانهٔ ۲", "SITE")
scr.run_operation("transfer", {"date": jd(2), "location_id": loc2, "reason": "جابه‌جایی"})
check(fa.get_asset(company_id, cnc).location_id == loc2 and scr.t_transfers.rowCount() == 1, "انتقال از صفحه و تب انتقال‌ها")
scr.run_operation("improve", {"date": jd(2), "amount": D(100_000), "offset_account_id": ap_gl.account_id, "capital": None,
                              "extend_life_months": 0, "description": "سرویس"})
check(scr.t_maint.rowCount() == 1 and fa.get_asset(company_id, cnc).gross_cost == 1_200_000, "تعمیر زیر حد: هزینه، در تب تعمیرات")
scr.run_operation("usage", {"date": jd(2, 5), "units": D(40), "production_order_ref": "PO-9"})

# --- ۵) اجرایِ استهلاک از صفحه --------------------------------------------------------------------------------
dep = ui.DepreciationScreen(); dep.confirm = lambda text: True; dep.refresh()
dep.period.addItem("1405/01", "1405/01"); dep.period.setCurrentIndex(dep.period.count() - 1)
check(dep.do("calculate") and dep.do("review") and dep.do("approve") and dep.do("post"), "محاسبه ← بررسی ← تایید ← ثبت از صفحه")
check(fa.get_asset(company_id, cnc).accumulated_depreciation == 100_000, "استهلاک ماه اول")
check(not dep.do("calculate") and "ثبت شده" in dep.status_label.text(), "دورهٔ ثبت‌شده: محاسبهٔ دوباره رد")
check(dep.lines.rowCount() == 1, "ردیف‌های اجرا")

# --- ۶) تأیید با کارتابلِ موجود (فروش) و ردِ درخواست (اسقاط) ----------------------------------------------------------
approver = users_service.create_user("fa_mgr", "مدیر مالی", "secret123", None, company.default_language_id, False, [company_id], company_id)
role = roles_service.create_role(company_id, "FA_APPROVER", None)
roles_service.set_user_role(approver.user_id, role.role_id, company_id, True)
cartable.save_workflow_steps(company_id, "fa_sell", True, [role.role_id])
cartable.save_workflow_steps(company_id, "fa_scrap", True, [role.role_id])
res = scr.run_operation("sell", {"date": jd(3), "price": D(1_300_000), "receivable_account_id": ar_gl.account_id, "reason": "فروش"})
check(getattr(res, "status_code", None) == "PENDING_APPROVAL" and fa.get_asset(company_id, cnc).status_code != "SOLD",
      "فروش با گردش کار: در انتظار تایید، هنوز فروخته نشده")
check(any(x.kind == "APPROVAL" for x in __import__("peecha.services.fixed_assets.physical", fromlist=["x"]).alerts(company_id)),
      "هشدار «در انتظار تایید» در داشبورد")
check(raises(lambda: approval.request(company_id, user.user_id, "SELL", cnc, date=jd(3), price=D(1), receivable_account_id=ar_gl.account_id)),
      "درخواست دوم هم‌زمان: رد")
task = next(t for t in cartable.list_my_tasks(approver.user_id, company_id) if t.form_code == "fa_sell")
cartable.approve_item(task.cartable_item_id, approver.user_id)
a = fa.get_asset(company_id, cnc)
with new_session() as s:
    req = s.get(AssetEvent, res.event_id)
check(a.status_code == "SOLD" and req.status_code == "APPROVED" and req.approved_by_user_id == approver.user_id,
      "پس از تایید کارتابل، فروش ثبت شد")
x2 = fa.create_asset(company_id, user.user_id, fa.AssetFields("X-2", "دستگاه دوم", cat_id))
fa.acquire(company_id, user.user_id, x2, jd(1), [fa.CostItem("PURCHASE", D(500_000), ap_gl.account_id, supplier)])
fa.capitalize(company_id, user.user_id, x2, jd(1), in_service_date=jd(1))
pending = approval.request(company_id, user.user_id, "SCRAP", x2, date=jd(3), reason="خرابی")
task = next(t for t in cartable.list_my_tasks(approver.user_id, company_id) if t.form_code == "fa_scrap")
cartable.reject_item(task.cartable_item_id, approver.user_id, "قابل تعمیر است")
with new_session() as s:
    rej = s.get(AssetEvent, pending.event_id)
check(rej.status_code == "REJECTED" and fa.get_asset(company_id, x2).status_code == "IN_SERVICE", "رد درخواست: اسقاط انجام نشد")
cartable.save_workflow_steps(company_id, "fa_scrap", False, [])

# --- ۷) CIP و شمارش از صفحه --------------------------------------------------------------------------------------
cip_scr = ui.CipScreen(); cip_scr.refresh()
cip_scr.action("new", {"code": "CIP-1", "name": "ساخت خط", "category_id": cat_id, "start_date": jd(1)})
cip_scr.projects.selectRow(0)
cip_scr.action("cost", {"date": jd(2), "cost_type": "LABOR", "amount": D(300_000), "offset_account_id": ap_gl.account_id})
cip_scr.projects.selectRow(0)
new_id = cip_scr.action("capitalize", {"asset_code": "LINE-1", "name": "خط جدید", "date": jd(3), "in_service_date": jd(3)})
check(new_id and fa.get_asset(company_id, new_id).gross_cost == 300_000 and "سرمایه‌ای" in cip_scr.projects.item(0, 3).text(),
      "CIP از صفحه ← دارایی")
pc = ui.PhysicalCountScreen(); pc.refresh()
pc.code.setText("CNT-1")
count_id = pc.new_count()
check(count_id and pc.items.rowCount() >= 2, "شمارش جدید از صفحه")
res = pc.scan(fa.qr_payload(fa.get_asset(company_id, x2)))
check(res and res.asset_id == x2, "اسکن QR در صفحهٔ شمارش")
summary = pc.close_count()
check(summary and summary.get("MISSING", 0) >= 1, "بستن شمارش: مفقودها")

# --- ۸) دسترسی‌ها ------------------------------------------------------------------------------------------------
clerk = users_service.create_user("fa_clerk", "کاربر محدود", "secret123", None, company.default_language_id, False, [company_id], company_id)
viewer = roles_service.create_role(company_id, "FA_VIEW", None)
roles_service.set_role_permission(viewer.role_id, forms["fa_assets"].form_id, "VIEW", True)
roles_service.set_user_role(clerk.user_id, viewer.role_id, company_id, True)
sess.current_user = clerk
scr2 = ui.AssetsScreen(); scr2.refresh(); scr2.open_asset(x2)
check(not scr2.new_button.isEnabled(), "بدون CREATE: ثبت دارایی غیرفعال")
check(not any(scr2.actions[k].isEnabled() for k in ("transfer", "sell", "scrap", "impair", "revalue", "improve")),
      "بدون دسترسی عملیات: دکمه‌ها غیرفعال")
check(scr2.cards["gross"].text() == "—" and scr2.list_table.item(0, 4).text() == "—", "بدون «مشاهدهٔ بها»: ارقام پنهان")
roles_service.set_role_permission(viewer.role_id, forms["fa_cost_view"].form_id, "VIEW", True)
roles_service.set_role_permission(viewer.role_id, forms["fa_transfer"].form_id, "CREATE", True)
scr2.refresh(); scr2.open_asset(x2)
check(scr2.actions["transfer"].isEnabled() and not scr2.actions["sell"].isEnabled() and scr2.cards["gross"].text() != "—",
      "با دسترسی انتقال و مشاهدهٔ بها")
dep2 = ui.DepreciationScreen(); dep2.refresh()
check(not any(b.isEnabled() for b in dep2.buttons.values()), "بدون دسترسی استهلاک: دکمه‌ها غیرفعال")
sess.current_user = user

# --- ۹) داشبورد -------------------------------------------------------------------------------------------------
dash = ui.FaDashboard(); dash.refresh()
check(dash.cards["COUNT"]._title_label.text() == "تعداد دارایی‌ها" and dash.alerts_table.rowCount() >= 1, "داشبورد دارایی")

# --- ۱۰) انتقالِ دارایی‌هایِ قبلی (inv.asset_details) ------------------------------------------------------------------
old_item = catalog_service.create_item(company_id, "OLD-1", "دارایی قدیمی", catalog_service.ItemFields(item_kind_code="ASSET", base_uom_id=pcs))
inventory_extended.set_asset_detail(old_item, 10, jd(1), D(1_000_000), "STRAIGHT_LINE", "TAG-9", None, D(0))
inventory_extended.post_monthly_depreciation(old_item, company_id, user.user_id, jd(1, 28), dep_exp.account_id, fa_accum.account_id)
inventory_extended.post_monthly_depreciation(old_item, company_id, user.user_id, jd(2, 28), dep_exp.account_id, fa_accum.account_id)
sql = (pathlib.Path(__file__).resolve().parents[2] / "db/schema/197_fixed_assets_docs_legacy.sql").read_text(encoding="utf-8")
with get_engine().begin() as conn:
    conn.exec_driver_sql(sql)
    conn.exec_driver_sql(sql)   # اجرایِ دوباره بی‌اثر
with new_session() as s:
    legacy = s.scalars(select(Asset).where(Asset.legacy_item_id == old_item)).all()
check(len(legacy) == 1 and legacy[0].gross_cost == 1_000_000 and legacy[0].accumulated_depreciation == 200_000
      and legacy[0].depreciated_months_offset == 2 and legacy[0].barcode == "TAG-9", "دارایی قبلی با بها و استهلاک ثبت‌شده منتقل شد")
lg = legacy[0]
check([t.txn_type for t in fa.ledger(company_id, lg.asset_id)] == ["OPENING", "DEPRECIATION", "DEPRECIATION"], "دفتر دارایی منتقل‌شده")
legacy_cat = next(c for c in fac.list_categories(company_id) if c.code == "LEGACY")
fac.save_category(company_id, fac.CategoryFields("LEGACY", "دارایی‌های قبلی", accounts=dict(
    asset_account_id=fa_asset.account_id, accumulated_depreciation_account_id=fa_accum.account_id,
    depreciation_expense_account_id=dep_exp.account_id)), category_id=legacy_cat.category_id)
rid = fd.calculate_run(company_id, user.user_id, "1405/03")
line = next(l for l in fd.run_lines(rid) if l.asset_id == lg.asset_id)
check(line.amount == 100_000, f"ادامهٔ استهلاک دارایی قبلی از ماه سوم، بدون تکرار ({line.amount})")

# --- ۱۱) API موبایل: اسکنِ QR و شمارش ------------------------------------------------------------------------------
from fastapi.testclient import TestClient
import peecha_api.main as api_main
client = TestClient(api_main.app)
H = {"Authorization": "Bearer " + client.post("/auth/login", json={"username": "admin", "password": "secret123"}).json()["access_token"]}
x2_asset = fa.get_asset(company_id, x2)
r = client.get("/fixed-assets/lookup", params={"code": fa.qr_payload(x2_asset)}, headers=H)
check(r.status_code == 200 and r.json()["code"] == "X-2" and r.json()["book_value"] is not None, "API: اسکن QR دارایی")
check(client.get("/fixed-assets/lookup", params={"code": "NOPE"}, headers=H).status_code == 404, "API: کد ناشناخته 404")
cnt2 = __import__("peecha.services.fixed_assets.physical", fromlist=["x"]).create_count(company_id, user.user_id, "CNT-M", today)
check(any(c["count_id"] == cnt2 for c in client.get("/fixed-assets/counts", headers=H).json()), "API: شمارش‌های باز")
hk = {**H, "Idempotency-Key": "scan-1"}
r1 = client.post(f"/fixed-assets/counts/{cnt2}/scan", json={"code": "X-2"}, headers=hk)
r2 = client.post(f"/fixed-assets/counts/{cnt2}/scan", json={"code": "X-2"}, headers=hk)
check(r1.status_code == 200 and r1.json()["result"] in ("FOUND", "WRONG_LOCATION") and r2.json() == r1.json(), "API: ثبت یافتن از موبایل (تکرار بی‌اثر)")
clerk_token = client.post("/auth/login", json={"username": "fa_clerk", "password": "secret123"}).json()["access_token"]
r3 = client.post(f"/fixed-assets/counts/{cnt2}/scan", json={"code": "X-2"}, headers={"Authorization": "Bearer " + clerk_token})
check(r3.status_code == 403, "API: بدون دسترسی شمارش 403")

print("RESULT:", "ALL PASS" if not FAIL else "SOME FAILED")
sys.exit(1 if FAIL else 0)
