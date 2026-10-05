import os, sys, datetime, decimal, io
os.environ["PEECHA_DB_NAME"] = "peecha_test_r249_1"
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

# --- ۱) قیدِ جدول‌ها --------------------------------------------------------------
with new_session() as s:
    raised = False
    try:
        s.execute(text("INSERT INTO inv.item_storage_profiles (item_id, company_id, hazard_class_code) VALUES (:i, :c, 'BAD')"),
                  {"i": item, "c": company_id}); s.commit()
    except Exception:
        raised = True
check(raised, "قیدِ پایگاه‌داده کلاسِ خطرِ نامعتبر را رد می‌کند")

# --- ۲) بررسیِ وضعیتِ محل در اسنادِ انبار -----------------------------------------
wl.set_status(company_id, bulk2, "BLOCKED")
doc_blocked_in = draft("RECEIPT", item, 3, bin_id=bulk2, dst=wh)
chk = wl.check_document_locations(company_id, doc_blocked_in)
check(chk.errors and "B02" in chk.errors[0] and "مسدود" in chk.errors[0], f"ورود به محلِ مسدود خطاست ({chk.errors})")
check(not wl.check_document_locations(company_id, draft("RECEIPT", item, 3, dst=wh)).errors, "ردیفِ بی‌محل (محلِ پیش‌فرض) بررسی نمی‌شود")
wl.set_status(company_id, pick2, "INACTIVE")
tr_from_inactive = draft("TRANSFER", item, 1, bin_id=pick2, dst_bin=pick1, src=wh, dst=wh)
check(not wl.check_document_locations(company_id, tr_from_inactive).errors, "خروج از محلِ غیرفعال (برایِ تخلیه) مجاز است")
tr_into_inactive = draft("TRANSFER", item, 1, bin_id=bulk1, dst_bin=pick2, src=wh, dst=wh)
check(any("غیرفعال" in e for e in wl.check_document_locations(company_id, tr_into_inactive).errors), "ورود به محلِ غیرفعال خطاست")
wl.set_status(company_id, bulk2, "MAINTENANCE")
issue_from_maint = draft("ISSUE", item, 1, bin_id=bulk2, src=wh)
check(any("تعمیر" in e for e in wl.check_document_locations(company_id, issue_from_maint).errors), "خروج از محلِ در حالِ تعمیر خطاست")
wl.set_status(company_id, pick2, "ACTIVE")
over = draft("RECEIPT", item, 150, bin_id=pick2, dst=wh)
check(any("ظرفیت" in w for w in wl.check_document_locations(company_id, over).warnings), "عبور از ظرفیت فقط هشدار است")
from peecha.ui.screens.inventory_document import InventoryDocumentScreen
wl.set_status(company_id, bulk2, "BLOCKED")
inv_screen = InventoryDocumentScreen("RECEIPT", None)
inv_screen.edit_document(doc_blocked_in)
inv_screen._confirm()
with new_session() as s:
    check(s.get(SD, doc_blocked_in).status_code == "DRAFT", "صفحهٔ سندِ انبار تاییدِ ورود به محلِ مسدود را متوقف کرد")
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.No)
inv_screen.edit_document(over); inv_screen._confirm()
with new_session() as s:
    check(s.get(SD, over).status_code == "DRAFT", "با «خیر» به هشدارِ ظرفیت، سند تایید نشد")
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
inv_screen._confirm()
with new_session() as s:
    check(s.get(SD, over).status_code == "CONFIRMED", "با تاییدِ هشدار، سند تایید شد")
inv_documents_service.cancel_stock_document(over, company_id)
wl.set_status(company_id, bulk2, "ACTIVE")

# --- ۳) سازگاریِ کالا با محل --------------------------------------------------------
SP = wl.StorageProfile
check(raises(lambda: wl.save_storage_profile(company_id, milk, SP(temperature_min_c=D(8), temperature_max_c=D(2)))), "دمایِ حداقل > حداکثر رد شد")
check(raises(lambda: wl.save_storage_profile(company_id, milk, SP(hazard_class_code="XX"))), "کلاسِ خطرِ نامعتبر رد شد")
wl.save_storage_profile(company_id, milk, SP(temperature_min_c=D(1), temperature_max_c=D(8)), user.user_id)
wl.save_storage_profile(company_id, acid, SP(hazard_class_code="CORROSIVE", is_fragile=True), user.user_id)
check(wl.get_storage_profile(company_id, milk).temperature_max_c == 8, "شرایطِ نگهداری ذخیره شد")
check(wl.compatibility_issues(company_id, milk, cold1) == [], "شیر در سردخانه (۲ تا ۶) سازگار است")
check(any("دما" in i for i in wl.compatibility_issues(company_id, milk, bulk1)), "شیر در محلِ بی‌دما (محیط) ناسازگار است")
check(wl.compatibility_issues(company_id, acid, haz1) == [], "کالایِ خطرناک در منطقهٔ مجاز (ارث از منطقه)")
check(any("خطرناک" in i for i in wl.compatibility_issues(company_id, acid, bulk1)), "کالایِ خطرناک خارج از منطقهٔ مجاز رد شد")
check(wl.compatibility_issues(company_id, item, bulk1) == [], "کالایِ بی‌شرط با همه‌جا سازگار است")
cold_set = wl.descendants(wl.tree(company_id, wh), zc)
sug = wl.putaway_suggestions(company_id, wh, milk, D(1), limit=50)
check(sug and all(s.location_id in cold_set for s in sug), f"پیشنهادِ جانمایی فقط محل‌هایِ سازگار ({[s.location_code for s in sug]})")
check(raises(lambda: wl.transfer(company_id, user.user_id, milk, general, bulk1, D(1))), "انتقالِ شیر به محلِ ناسازگار رد شد")
check(wl.transfer(company_id, user.user_id, milk, general, cold1, D(2)), "انتقالِ شیر به سردخانه")
receipt_acid = post(draft("RECEIPT", acid, 2, dst=wh))
pa = ops.generate_tasks(company_id, "PUTAWAY", ("STOCK", receipt_acid), user.user_id)
check(raises(lambda: ops.complete_putaway(pa[0], company_id, user.user_id, bulk1)), "جانماییِ اسید در محلِ ناسازگار رد شد")
check(ops.complete_putaway(pa[0], company_id, user.user_id, haz1), "جانماییِ اسید در منطقهٔ مجاز")
check(any("خطرناک" in w for w in wl.check_document_locations(company_id, draft("RECEIPT", acid, 1, bin_id=bulk1, dst=wh)).warnings),
      "ناسازگاری در سندِ انبار هشدار می‌دهد")
wl.save_storage_profile(company_id, item, SP(required_location_type_code="PICK_FACE"))
check(wl.compatibility_issues(company_id, item, pick1) == [] and wl.compatibility_issues(company_id, item, bulk1), "نوعِ محلِ الزامی")
wl.save_storage_profile(company_id, item, SP())
check(wl.get_storage_profile(company_id, item).is_empty(), "پروفایلِ خالی حذف شد")
with new_session() as s:
    check(s.scalar(select(sa_func.count()).select_from(ActivityLog).where(ActivityLog.entity_type == "ItemStorageProfile")) >= 3,
          "تغییرِ شرایطِ نگهداری در audit ثبت شد")

# --- ۴) رزروِ وظیفهٔ برداشت ----------------------------------------------------------
issue = draft("ISSUE", item, 4, src=wh)
picks = ops.generate_tasks(company_id, "PICK", ("STOCK", issue), user.user_id)
with new_session() as s:
    check(s.get(WarehouseTask, picks[0]).from_bin_location_id == pick1, "محلِ برداشت = جبههٔ برداشتِ دارایِ موجودی (نه محلِ پیش‌فرض)")
res = ops.task_reservations(company_id, picks[0])
check(len(res) == 1 and res[0].status_code == "ACTIVE" and res[0].quantity == 4 and res[0].bin_location_id == pick1, "رزروِ قطعیِ وظیفه")
cont = {c.item_id: c for c in wl.contents(company_id, pick1)}
check(cont[item].reserved == 4, "محتوایِ محل رزرو را نشان می‌دهد")
check(raises(lambda: wl.transfer(company_id, user.user_id, item, pick1, pick2, D(3))), "انتقالِ موجودیِ رزروشده رد شد")
check(wl.transfer(company_id, user.user_id, item, pick1, pick2, D(1)), "انتقالِ موجودیِ آزاد")
from peecha.services import purchase_reports as pr
F = pr.PurchaseFilters(today - datetime.timedelta(days=30), today, side="INVENTORY")
rows = pr.run_report(company_id, "RESERVED_STOCK", F).rows
check(any(r[5] == "WMS_PICK_TASK" and r[3] == 4 for r in rows), f"گزارشِ موجودیِ رزروشده رزروِ وظیفه را نشان می‌دهد ({rows})")
ops.complete_pick(picks[0], company_id, user.user_id, D(3))
res = ops.task_reservations(company_id, picks[0])
check(res[0].status_code == "FULFILLED" and res[0].fulfilled_quantity_base == 3, "تکمیلِ برداشت رزرو را آزاد کرد")
issue2 = draft("ISSUE", item, 2, src=wh)
p2 = ops.generate_tasks(company_id, "PICK", ("STOCK", issue2), user.user_id)
ops.cancel_task(p2[0], company_id)
check(ops.task_reservations(company_id, p2[0])[0].status_code == "CANCELLED", "لغوِ وظیفه رزرو را لغو کرد")

# --- ۵) تأمینِ مجدد -----------------------------------------------------------------
RF = ops.RuleFields
check(raises(lambda: ops.save_rule(company_id, RF(pick1, item, D(10), D(5)))), "حداکثر ≤ حداقل رد شد")
f = wl.get_fields(company_id, pick2); f.allow_replenishment = False; wl.update_location(company_id, pick2, f)
check(raises(lambda: ops.save_rule(company_id, RF(pick2, item, D(1), D(5)))), "محلِ بدونِ اجازهٔ تأمین رد شد")
rule = ops.save_rule(company_id, RF(pick1, item, D(10), D(30)))
check(raises(lambda: ops.save_rule(company_id, RF(pick1, item, D(1), D(5)))), "قاعدهٔ تکراری رد شد")
need = ops.replenishment_needs(company_id)
on_pick = sum(c.quantity for c in wl.contents(company_id, pick1) if c.item_id == item)
check(len(need) == 1 and need[0].on_hand == on_pick and need[0].need == 30 - on_pick and need[0].sources[0].location_id == bulk1,
      f"نیازِ تأمین تا حداکثر از منطقهٔ ذخیره (got {[(n.on_hand, n.need, [s.location_code for s in n.sources]) for n in need]})")
rep = ops.generate_replenishment_tasks(company_id, user.user_id)
check(len(rep) == 1 and ops.task_reservations(company_id, rep[0])[0].status_code == "ACTIVE", "وظیفهٔ تأمین با رزروِ منبع")
check(ops.generate_replenishment_tasks(company_id, user.user_id) == [] and ops.replenishment_needs(company_id) == [],
      "وظیفهٔ بازِ تأمین دوباره ساخته نمی‌شود")
bulk_before = sum(c.quantity for c in wl.contents(company_id, bulk1) if c.item_id == item)
check(raises(lambda: ops.complete_replenishment(rep[0], company_id, user.user_id, D(999))), "مقدارِ بیش از وظیفه رد شد")
check(ops.task_reservations(company_id, rep[0])[0].status_code == "ACTIVE", "پس از خطا رزرو برقرار ماند")
doc_rep = ops.complete_replenishment(rep[0], company_id, user.user_id)
check(doc_rep and sum(c.quantity for c in wl.contents(company_id, pick1) if c.item_id == item) == 30
      and sum(c.quantity for c in wl.contents(company_id, bulk1) if c.item_id == item) == bulk_before - (30 - on_pick),
      "تأمینِ مجدد با سندِ انتقال: جبههٔ برداشت به حداکثر رسید")
check(ops.task_reservations(company_id, rep[0])[0].status_code == "FULFILLED", "رزروِ تأمین برآورده شد")
ops.delete_rule(company_id, rule)
check(ops.list_rules(company_id)[0].is_active is False, "قاعدهٔ دارایِ سابقه فقط غیرفعال شد")
r2 = ops.save_rule(company_id, RF(bulk2, milk, D(0), D(3)))
ops.delete_rule(company_id, r2)
check(len(ops.list_rules(company_id)) == 1, "قاعدهٔ بی‌سابقه حذف شد")

# --- ۶) سه‌بعدی ---------------------------------------------------------------------
boxes = {b.location_id: b for b in wl.scene_3d(company_id, wh)}
rb_set = wl.descendants(wl.tree(company_id, wh), rb)
shelves = sorted((b for b in boxes.values() if b.level == "SHELF" and b.location_id in rb_set), key=lambda b: b.z)
check(boxes[rb].h == 50 and len(shelves) == 2 and shelves[0].z == 0 and shelves[1].z == 25 and shelves[0].h == 25, "قفسهٔ ۲٫۵ متری با دو طبقهٔ رویِ هم")
check(boxes[bulk1].z == shelves[0].z and boxes[bulk1].h == 25 and boxes[zb].h == 1, "Bin هم‌ارتفاعِ طبقه؛ منطقه کف است")
f = wl.get_fields(company_id, rc); f.height_m = D(4); f.map_z = D(1); wl.update_location(company_id, rc, f)
wl.save_geometry(company_id, rc, 100, 100, 40, 200, 90)
b = {x.location_id: x for x in wl.scene_3d(company_id, wh)}[rc]
check(b.h == 80 and b.z == 20 and (b.w, b.d) == (200, 40) and (b.x, b.y) == (20, 180), f"ارتفاع/Z/چرخش در نمایِ سه‌بعدی ({b})")
from peecha.ui.screens.warehouse_map import WarehouseMapScreen
screen = WarehouseMapScreen(None); screen.refresh(); screen.load_warehouse(wh)
screen.view3d_check.setChecked(True)
n_boxes = len(wl.scene_3d(company_id, wh))
check(screen.view_stack.currentWidget() is screen.view3d and len(screen.view3d.polygons) == n_boxes, "نمایِ سه‌بعدی در صفحهٔ نقشه")
screen.mode_combo.setCurrentIndex(screen.mode_combo.findData("OCCUPANCY"))
check(screen.view3d.colors, "رنگِ حالتِ اشغال در نمایِ سه‌بعدی")
screen.view3d.azimuth_slider.setValue(200); screen.view3d.elevation_slider.setValue(70)
check(len(screen.view3d.polygons) == n_boxes, "چرخشِ نمایِ سه‌بعدی")
screen.view3d.location_clicked.emit(pick1)
check(screen.selected_id == pick1, "کلیک در نمایِ سه‌بعدی محل را انتخاب می‌کند")
screen.search("WH01-Z02-R02-L01-B01")
check(pick1 in screen.view3d.highlighted, "جستجو در نمایِ سه‌بعدی هم برجسته می‌شود")

# --- ۷) صفحه‌هایِ دسکتاپ -------------------------------------------------------------
from peecha.ui.screens.warehouse_operations import WarehouseOperationsScreen
f = wl.get_fields(company_id, pick2); f.allow_replenishment = True; wl.update_location(company_id, pick2, f)
ops.save_rule(company_id, RF(pick2, item, D(5), D(8)))
ops_screen = WarehouseOperationsScreen(); ops_screen.refresh()
check(ops_screen.replenish_tab.table.rowCount() == 2, "زبانهٔ قاعده‌هایِ تأمین")
ids = ops_screen.replenish_tab.generate()
check(len(ids) == 1, "ایجادِ وظیفهٔ تأمین از صفحه")
ops_screen.tasks_tab.type_combo.setCurrentIndex(ops_screen.tasks_tab.type_combo.findData("REPLENISH"))
check(ops_screen.tasks_tab.table.rowCount() == 2, "وظایفِ تأمین در فهرستِ وظایف")
from peecha.ui.screens.inventory_item_panel import ItemDetailPanel
panel = ItemDetailPanel(); panel.refresh(company_id)
panel.load(next(i for i in catalog_service.list_items(company_id) if i.item_id == milk))
check(panel.storage_temp_max.value() == 8 and panel.storage_temp_min.value() == 1, "شرایطِ نگهداری در فرمِ کالا")
panel.storage_fragile_checkbox.setChecked(True)
check(panel.save_storage_profile() and wl.get_storage_profile(company_id, milk).is_fragile, "ذخیرهٔ شرایطِ نگهداری از فرمِ کالا")

# --- ۸) API ---------------------------------------------------------------------------
from fastapi.testclient import TestClient
import peecha_api.main as api_main
client = TestClient(api_main.app)
H = {"Authorization": "Bearer " + client.post("/auth/login", json={"username": "admin", "password": "secret123"}).json()["access_token"]}
check(len(client.get(f"/locations/warehouses/{wh}/scene3d", headers=H).json()) == n_boxes, "API: صحنهٔ سه‌بعدی")
c = client.get("/locations/compatibility", params={"item_id": milk, "location_id": bulk1}, headers=H).json()
check(c["compatible"] is False and c["issues"], "API: سازگاری")
check(client.get(f"/locations/items/{acid}/storage-profile", headers=H).json()["hazard_class"] == "CORROSIVE", "API: شرایطِ نگهداری")
tasks = client.get("/locations/tasks", params={"task_type": "REPLENISH"}, headers=H).json()
check(len(tasks) == 1 and tasks[0]["task_id"] == ids[0] and tasks[0]["to_location_code"] == "WH01-Z02-R02-L01-B02", "API: فهرستِ وظایفِ باز")
check(client.post(f"/locations/tasks/{ids[0]}/start", headers=H).json()["status"] == "IN_PROGRESS", "API: شروعِ وظیفه")
KH = dict(H, **{"Idempotency-Key": "rep-1"})
r1 = client.post(f"/locations/tasks/{ids[0]}/replenish", json={}, headers=KH)
r2_ = client.post(f"/locations/tasks/{ids[0]}/replenish", json={}, headers=KH)
check(r1.status_code == 200 and r1.json() == r2_.json(), "API: تکرارِ همان کلید پاسخِ قبلی را برمی‌گرداند (بدونِ انتقالِ دوباره)")
check(client.post(f"/locations/tasks/{ids[0]}/replenish", json={}, headers=dict(H, **{"Idempotency-Key": "rep-2"})).status_code == 400,
      "API: وظیفهٔ انجام‌شده با کلیدِ تازه رد شد")
TK = dict(H, **{"Idempotency-Key": "tr-1"})
before = sum(c.quantity for c in wl.contents(company_id, bulk2) if c.item_id == item)
body = {"item_id": item, "from_location_id": bulk1, "to_location_id": bulk2, "quantity": "2"}
t1 = client.post("/locations/transfer", json=body, headers=TK); t2 = client.post("/locations/transfer", json=body, headers=TK)
check(t1.status_code == 200 and t1.json() == t2.json()
      and sum(c.quantity for c in wl.contents(company_id, bulk2) if c.item_id == item) == before + 2, "API: انتقالِ idempotent")
check(client.post("/locations/transfer", json={"item_id": milk, "from_location_id": cold1, "to_location_id": bulk1, "quantity": "1"},
                  headers=H).status_code == 400, "API: انتقالِ ناسازگار ۴۰۰")

print("RESULT:", "ALL PASS" if not FAIL else "SOME FAILED")
sys.exit(1 if FAIL else 0)
