import os, sys, datetime, decimal, io
os.environ["PEECHA_DB_NAME"] = "peecha_test_r257_1"
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
# R257: هستهٔ بهایِ تمام‌شده -- لایه، تخصیص، FIFO/LIFO/HIFO/LOFO/میانگین، موجودیِ منفی، لایهٔ آغازین، هم‌زمانی
# =====================================================================
import threading
from types import SimpleNamespace as NS
from peecha.db.models.inventory import CostLayer, CostAllocation, StockLedger, StockDocumentLine as SDL, StockBalance, Item
from peecha.services.costing import strategies as cs, engine as ce

# --- ۱) راهبردها (بدونِ دیتابیس) -------------------------------------------------
def L(i, cost, qty=100, d=None):
    return NS(cost_layer_id=i, unit_cost=D(cost), remaining_quantity=D(qty), receipt_date=d or datetime.date(2026, 1, i))
def picked(code, layers, qty):
    picks, short = cs.get_strategy(code).pick(layers, D(qty))
    return [(p.quantity, p.layer.unit_cost) for p in picks], short
check(picked("FIFO", [L(1, 100), L(2, 200)], 150) == ([(100, 100), (50, 200)], 0), "FIFO: 100@100 + 50@200")
check(picked("LIFO", [L(1, 100), L(2, 200)], 150) == ([(100, 200), (50, 100)], 0), "LIFO: 100@200 + 50@100")
check(picked("HIFO", [L(1, 100), L(2, 200), L(3, 150)], 150) == ([(100, 200), (50, 150)], 0), "HIFO: 100@200 + 50@150")
check(picked("LOFO", [L(1, 100), L(2, 200), L(3, 150)], 150) == ([(100, 100), (50, 150)], 0), "LOFO: 100@100 + 50@150")
check(picked("FIFO", [L(1, 100)], 130)[1] == 30, "کمبود: مقدارِ تأمین‌نشده برگشت داده می‌شود")
check(cs.moving_average(D(100), D(100), D(100), D(200)) == 150, "میانگینِ متحرک: ۱۰۰@۱۰۰ + ۱۰۰@۲۰۰ = ۱۵۰")
check(cs.is_layer_method("LIFO") and not cs.is_layer_method("WEIGHTED_AVERAGE") and not cs.is_layer_method("NIFO"),
      "تشخیصِ روش‌هایِ لایه‌ای")

# --- کمک‌ها -----------------------------------------------------------------------
def new_item(code, method, **kw):
    return catalog_service.create_item(company_id, code, code, catalog_service.ItemFields(
        item_kind_code="GOOD", base_uom_id=pcs, costing_method_code=method, **kw))
def mk(doc_type, item_id, qty, cost=None, src=None, dst=None, source_line=None, qty_base=None, date=None, post_it=True):
    doc = inv_documents_service.create_stock_document(company_id, user.user_id, doc_type, date or today, inv_documents_service.DocumentHeaderFields(
        source_warehouse_id=src, destination_warehouse_id=dst,
        counterparty_detail_account_id=supplier if doc_type in ("RECEIPT", "RETURN_OUT") else None))
    line = inv_documents_service.add_line(doc, company_id, inv_documents_service.LineFields(
        item_id=item_id, uom_id=pcs, quantity=D(qty), quantity_base=D(qty_base if qty_base is not None else qty),
        unit_cost=D(cost) if cost is not None else None, source_line_id=source_line,
        reason_code_id=documents_service._ensure_return_reason_code(company_id, doc_type) if doc_type in ("RETURN_IN", "RETURN_OUT") else None))
    if post_it:
        post(doc)
    return doc, line
def out_costs(line_id):
    with new_session() as s:
        return [(r.quantity_base.normalize(), r.unit_cost.normalize()) for r in s.scalars(
            select(StockLedger).where(StockLedger.stock_document_line_id == line_id, StockLedger.movement_direction == "OUT")
            .order_by(StockLedger.ledger_id))]
def allocs(line_id):
    with new_session() as s:
        return [(a.quantity_base.normalize(), a.unit_cost.normalize(), a.cost_layer_id, a.costing_status_code, a.costing_method_code)
                for a in s.scalars(select(CostAllocation).where(CostAllocation.stock_document_line_id == line_id)
                                   .order_by(CostAllocation.allocation_id))]
def layers(item_id, warehouse_id=None):
    with new_session() as s:
        q = select(CostLayer).where(CostLayer.item_id == item_id).order_by(CostLayer.cost_layer_id)
        if warehouse_id:
            q = q.where(CostLayer.warehouse_id == warehouse_id)
        return list(s.scalars(q))
def bal(item_id, warehouse_id):
    with new_session() as s:
        q, v = s.execute(select(sa_func.sum(StockBalance.quantity_on_hand), sa_func.sum(StockBalance.total_value)).where(
            StockBalance.item_id == item_id, StockBalance.warehouse_id == warehouse_id)).one()
        return (q or 0), (v or 0)

# --- ۲) چهار روشِ لایه‌ای رویِ سندِ واقعی ------------------------------------------------
expected = {"FIFO": [(100, 100), (50, 200)], "LIFO": [(100, 200), (50, 100)],
            "HIFO": [(100, 200), (50, 150)], "LOFO": [(100, 100), (50, 150)]}
for code, exp in expected.items():
    it = new_item(f"C-{code}", code)
    mk("RECEIPT", it, 100, 100, dst=wh)
    mk("RECEIPT", it, 100, 200, dst=wh)
    if code in ("HIFO", "LOFO"):
        mk("RECEIPT", it, 100, 150, dst=wh)
    _, ln = mk("ISSUE", it, 150, src=wh)
    got = out_costs(ln)
    check(got == [(D(q), D(c)) for q, c in exp], f"{code}: خروجِ ۱۵۰ → {exp} (got {got})")
    al = allocs(ln)
    check(len(al) == 2 and all(a[2] is not None and a[3] == "CALCULATED" and a[4] == code for a in al),
          f"{code}: تخصیص به دو لایه ثبت شد")
    lyr = layers(it)
    check(all(l.original_quantity == 100 for l in lyr) and sum(l.remaining_quantity for l in lyr) == D(50 if code in ("FIFO", "LIFO") else 150),
          f"{code}: لایه حذف نمی‌شود، فقط مانده کم می‌شود")
    if code == "FIFO":
        check(lyr[0].remaining_quantity == 0 and lyr[0].status_code == "CONSUMED" and lyr[1].remaining_quantity == 50,
              "FIFO: مصرفِ کاملِ لایهٔ اول و جزئیِ لایهٔ دوم")
        fifo_item = it
check(all(l.receipt_date == today and l.source_type_code == "RECEIPT" and l.company_id == company_id for l in layers(fifo_item)),
      "لایه: تاریخِ دریافت = تاریخِ سند، منبع و شرکت ثبت شد")

# --- ۳) میانگینِ متحرک ------------------------------------------------------------
ma = new_item("C-MA", "WEIGHTED_AVERAGE")
mk("RECEIPT", ma, 100, 100, dst=wh)
mk("RECEIPT", ma, 100, 200, dst=wh)
_, ln = mk("ISSUE", ma, 50, src=wh)
check(out_costs(ln) == [(D(50), D(150))], "میانگین: خروجِ ۵۰ به بهایِ ۱۵۰")
q, v = bal(ma, wh)
check(q == 150 and v == D(22500), "میانگین: مانده ۱۵۰ با بهایِ ۱۵۰")
check(allocs(ln) == [(D(50), D(150), None, "CALCULATED", "WEIGHTED_AVERAGE")], "میانگین: تخصیصِ بدونِ لایه ثبت شد")
check(not layers(ma), "میانگین لایه نمی‌سازد")

# --- ۴) چند انبار، انتقال، برگشت ------------------------------------------------------
wh2 = locations_service.create_warehouse(company_id, "WH02", "فرعی", locations_service.WarehouseFields(allow_negative_stock=False))
mw = new_item("C-MW", "FIFO")
mk("RECEIPT", mw, 10, 50, dst=wh, date=today - datetime.timedelta(days=5))
mk("RECEIPT", mw, 10, 70, dst=wh2)
_, ln = mk("ISSUE", mw, 4, src=wh2)
check(out_costs(ln) == [(D(4), D(70))], "چند انبار: خروج از انبارِ ۲ فقط لایهٔ همان انبار را مصرف می‌کند")
_, tl = mk("TRANSFER", mw, 3, src=wh, dst=wh2)
dest = [l for l in layers(mw, wh2) if l.source_type_code == "TRANSFER"]
check(len(dest) == 1 and dest[0].unit_cost == 50 and dest[0].receipt_date == today - datetime.timedelta(days=5),
      "انتقال: لایهٔ مقصد با همان بها و تاریخِ دریافتِ مبدأ")
_, ln = mk("ISSUE", mw, 3, src=wh2)
check(out_costs(ln) == [(D(3), D(50))], "انتقال: FIFOِ انبارِ مقصد لایهٔ قدیمی‌ترِ منتقل‌شده را اول مصرف کرد")
pr = new_item("C-PR", "FIFO")
mk("RECEIPT", pr, 100, 100, dst=wh)
_, rl2 = mk("RECEIPT", pr, 100, 120, dst=wh)
_, ln = mk("RETURN_OUT", pr, 20, 120, src=wh, source_line=rl2)
check(out_costs(ln) == [(D(20), D(120))], "برگشت به تامین‌کننده: از لایهٔ همان رسید (نه قدیمی‌ترین)")
check([l.remaining_quantity for l in layers(pr)] == [100, 80], "برگشت به تامین‌کننده: ماندهٔ لایهٔ همان رسید ۸۰")
_, sl = mk("ISSUE", pr, 150, src=wh)
check(out_costs(sl) == [(D(100), D(100)), (D(50), D(120))], "فروش پس از برگشت")
_, rin = mk("RETURN_IN", pr, 10, dst=wh, source_line=sl)
with new_session() as s:
    rin_cost = s.scalar(select(StockLedger.unit_cost).where(StockLedger.stock_document_line_id == rin))
expected_avg = (D(100) * 100 + D(50) * 120) / 150
check(abs(rin_cost - expected_avg) < D("0.000001"), f"برگشت از فروش: بهایِ همان فروش ({rin_cost})")
check(any(l.source_type_code == "RETURN_IN" and abs(l.unit_cost - expected_avg) < D("0.000001") for l in layers(pr)),
      "برگشت از فروش: لایهٔ تازه با بهایِ فروش")

# --- ۵) تبدیلِ واحد و دقتِ اعشاری ------------------------------------------------------
uc_item = new_item("C-UC", "FIFO")
mk("RECEIPT", uc_item, 2, D("100"), dst=wh, qty_base=24)  # ۲ کارتن = ۲۴ عدد، بهایِ هر عدد ۱۰۰
check(layers(uc_item)[0].original_quantity == 24 and layers(uc_item)[0].unit_cost == 100, "تبدیلِ واحد: لایه به واحدِ پایه")
dp = new_item("C-DP", "FIFO")
mk("RECEIPT", dp, 3, D("10.333333"), dst=wh)
_, ln = mk("ISSUE", dp, D("1.5"), src=wh)
check(out_costs(ln) == [(D("1.5"), D("10.333333"))] and isinstance(allocs(ln)[0][1], decimal.Decimal), "دقتِ اعشاری با Decimal")

# --- ۶) سیاستِ موجودیِ منفی -----------------------------------------------------------
ng = new_item("C-NG", "FIFO")
mk("RECEIPT", ng, 5, 100, dst=wh)              # انبارِ ۱ موجودیِ منفی را مجاز می‌داند
_, ln = mk("ISSUE", ng, 7, src=wh)            # پیش‌فرض WAREHOUSE: مثلِ قبل
check(out_costs(ln)[0] == (D(5), D(100)) and allocs(ln)[-1][3] == "CALCULATED", "سیاستِ پیش‌فرض: رفتارِ قبلی (تنظیمِ انبار)")
engine_service.set_costing_settings(company_id, "WEIGHTED_AVERAGE", True, negative_stock_policy="BLOCK", user_id=user.user_id, reason="آزمون")
doc, _ = mk("ISSUE", ng, 1, src=wh, post_it=False)
check(raises(lambda: post(doc)), "BLOCK: خروجِ بیش از موجودی رد شد (حتی در انبارِ مجاز به منفی)")
engine_service.set_costing_settings(company_id, "WEIGHTED_AVERAGE", True, negative_stock_policy="PENDING", user_id=user.user_id)
_, ln = mk("ISSUE", ng, 1, src=wh)
check(allocs(ln)[-1][3] == "PENDING", "PENDING: خروج مجاز، بهایِ کمبود «در انتظار»")
engine_service.set_costing_settings(company_id, "WEIGHTED_AVERAGE", True, negative_stock_policy="FALLBACK", user_id=user.user_id)
fb = new_item("C-FB", "FIFO")
mk("RECEIPT", fb, 1, 80, dst=wh2)
_, ln = mk("ISSUE", fb, 3, src=wh2)          # انبارِ ۲ منفی را مجاز نمی‌داند ولی سیاستِ شرکت FALLBACK است
check(out_costs(ln) == [(D(1), D(80)), (D(2), D(80))] and allocs(ln)[-1][3] == "CALCULATED", "FALLBACK: با آخرین بهایِ معتبر")
engine_service.set_costing_settings(company_id, "WEIGHTED_AVERAGE", True, negative_stock_policy="WAREHOUSE", user_id=user.user_id)
doc, _ = mk("ISSUE", fb, 1, src=wh2, post_it=False)
check(raises(lambda: post(doc)), "WAREHOUSE: انبارِ غیرمجاز به منفی، مثلِ قبل رد می‌کند")
with new_session() as s:
    logs = s.scalars(select(ActivityLog).where(ActivityLog.entity_type == "CostingSettings")).all()
check(len(logs) >= 3 and any("آزمون" in str(l.changes) for l in logs), "تغییرِ تنظیمات با علت در Audit ثبت شد")
check(raises(lambda: engine_service.set_costing_settings(company_id, "XYZ", True)), "روشِ ناشناخته رد شد")
check({"FIFO", "LIFO", "HIFO", "LOFO", "WEIGHTED_AVERAGE", "SPECIFIC", "NIFO", "STANDARD"} <= {m.code for m in catalog_service.list_costing_methods()},
      "همهٔ روش‌ها در فهرست (R258: NIFO هم)")

# --- ۷) لایهٔ آغازین برایِ موجودیِ قبلی ---------------------------------------------------
# item (G-1) با میانگین ۸۵ عدد موجودی دارد؛ به FIFO تغییر می‌کند
on_hand_before, value_before = bal(item, wh)
with new_session() as s:
    s.get(Item, item).costing_method_code = "FIFO"
    s.commit()
_, ln = mk("ISSUE", item, 10, src=wh)
op = [l for l in layers(item, wh) if l.source_type_code == "OPENING_BALANCE"]
check(len(op) == 1 and op[0].original_quantity == on_hand_before, f"لایهٔ آغازین با کلِ موجودیِ قبلی ({on_hand_before})")
check(abs(op[0].unit_cost - value_before / on_hand_before) < D("0.01") and op[0].remaining_quantity == on_hand_before - 10,
      "لایهٔ آغازین با میانگینِ قبلی، و خروج از آن")
_, ln = mk("ISSUE", item, 1, src=wh)
check(len([l for l in layers(item, wh) if l.source_type_code == "OPENING_BALANCE"]) == 1, "لایهٔ آغازین تکرار نمی‌شود")

# --- ۸) بهایِ تمام‌شده در سندِ حسابداری = جمعِ تخصیص‌ها -----------------------------------------
from peecha.db.models.accounting import JournalEntryLine
cg = new_item("C-CG", "LIFO")
mk("RECEIPT", cg, 10, 100, dst=wh)
mk("RECEIPT", cg, 10, 130, dst=wh)
d, ln = mk("ISSUE", cg, 15, src=wh)
with new_session() as s:
    je_id = s.get(SD, d).journal_entry_id
    cogs_debit = s.scalar(select(sa_func.sum(JournalEntryLine.debit_amount_base)).where(
        JournalEntryLine.journal_entry_id == je_id, JournalEntryLine.account_id == cogs_gl.account_id))
check(cogs_debit == sum(D(q) * D(c) for q, c, *_ in allocs(ln)) == D(10 * 130 + 5 * 100), f"بهایِ تمام‌شدهٔ سند = جمعِ تخصیص‌ها ({cogs_debit})")

# --- ۹) هم‌زمانی: دو خروجِ هم‌زمان از یک لایه -------------------------------------------------
engine_service.set_costing_settings(company_id, "WEIGHTED_AVERAGE", True, negative_stock_policy="BLOCK", user_id=user.user_id)
cc = new_item("C-CC", "FIFO")
mk("RECEIPT", cc, 100, 10, dst=wh)
docs = [mk("ISSUE", cc, 60, src=wh, post_it=False)[0] for _ in range(2)]
errors, ok = [], []
def worker(doc_id):
    try:
        post(doc_id)
        ok.append(doc_id)
    except Exception as exc:  # noqa: BLE001
        errors.append(exc)
threads = [threading.Thread(target=worker, args=(d,)) for d in docs]
[t.start() for t in threads]
[t.join() for t in threads]
check(len(ok) == 1 and len(errors) == 1, f"هم‌زمانی: فقط یکی از دو خروجِ ۶۰تایی موفق شد (ok={len(ok)})")
check(layers(cc)[0].remaining_quantity == 40, "هم‌زمانی: لایه بیش از موجودی مصرف نشد")
engine_service.set_costing_settings(company_id, "WEIGHTED_AVERAGE", True, negative_stock_policy="WAREHOUSE", user_id=user.user_id)

print("RESULT:", "ALL PASS" if not FAIL else "SOME FAILED")
sys.exit(1 if FAIL else 0)
