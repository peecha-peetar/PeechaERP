import os, sys, datetime, decimal, io
os.environ["PEECHA_DB_NAME"] = "peecha_test_r258_1"
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
# R258: شناساییِ ویژه (سریال/بچ)، NIFO و بهایِ جایگزینی
# =====================================================================
from peecha.db.models.inventory import CostLayer, CostAllocation, StockLedger, ReplacementCost, Batch, SerialNumber
from peecha.db.models.accounting import JournalEntryLine
from peecha.db.models.commercial import PriceList, PriceListItem
from peecha.services.costing import replacement as rc
TE = lt.TrackingEntry
M = D(1_000_000)

def new_item(code, method, **kw):
    return catalog_service.create_item(company_id, code, code, catalog_service.ItemFields(
        item_kind_code="GOOD", base_uom_id=pcs, costing_method_code=method, **kw))
def mk(doc_type, item_id, qty, cost=None, src=None, dst=None, source_line=None, entries=None, post_it=True):
    doc = inv_documents_service.create_stock_document(company_id, user.user_id, doc_type, today, inv_documents_service.DocumentHeaderFields(
        source_warehouse_id=src, destination_warehouse_id=dst,
        counterparty_detail_account_id=supplier if doc_type in ("RECEIPT", "RETURN_OUT") else None))
    line = inv_documents_service.add_line(doc, company_id, inv_documents_service.LineFields(
        item_id=item_id, uom_id=pcs, quantity=D(qty), quantity_base=D(qty), unit_cost=D(cost) if cost is not None else None,
        source_line_id=source_line,
        reason_code_id=documents_service._ensure_return_reason_code(company_id, doc_type) if doc_type in ("RETURN_IN", "RETURN_OUT") else None))
    if entries:
        lt.set_line_tracking(company_id, entries, stock_line_id=line)
    if post_it:
        post(doc)
    return doc, line
def out_costs(line_id):
    with new_session() as s:
        return [(r.quantity_base.normalize(), r.unit_cost.normalize()) for r in s.scalars(
            select(StockLedger).where(StockLedger.stock_document_line_id == line_id, StockLedger.movement_direction == "OUT")
            .order_by(StockLedger.ledger_id))]
def alloc_costs(line_id):
    with new_session() as s:
        return [(a.quantity_base.normalize(), a.unit_cost.normalize()) for a in s.scalars(
            select(CostAllocation).where(CostAllocation.stock_document_line_id == line_id).order_by(CostAllocation.allocation_id))]
def layers(item_id, warehouse_id=None):
    with new_session() as s:
        q = select(CostLayer).where(CostLayer.item_id == item_id).order_by(CostLayer.cost_layer_id)
        if warehouse_id:
            q = q.where(CostLayer.warehouse_id == warehouse_id)
        return list(s.scalars(q))
def serial_id(item_id, no):
    with new_session() as s:
        return s.scalar(select(SerialNumber.serial_id).where(SerialNumber.item_id == item_id, SerialNumber.serial_no == no))
def batch_id(item_id, no):
    with new_session() as s:
        return s.scalar(select(Batch.batch_id).where(Batch.item_id == item_id, Batch.batch_no == no))

# --- ۱) سریال با شناساییِ ویژه -----------------------------------------------------------
ph = new_item("SP-SER", "SPECIFIC", track_serial=True)
mk("RECEIPT", ph, 1, 10 * M, dst=wh, entries=[TE(D(1), serial_no="SN001")])
mk("RECEIPT", ph, 1, 12 * M, dst=wh, entries=[TE(D(1), serial_no="SN002")])
mk("RECEIPT", ph, 2, 11 * M, dst=wh, entries=[TE(D(1), serial_no="SN003"), TE(D(1), serial_no="SN004")])
lyr = layers(ph)
check(len(lyr) == 4 and all(l.serial_id is not None and l.original_quantity == 1 for l in lyr),
      "هر سریال لایهٔ خودش را دارد (رسیدِ دوسریالی به دو لایه شکست)")
check({l.serial_id: l.unit_cost for l in lyr}[serial_id(ph, "SN002")] == 12 * M, "بهایِ SN002 = ۱۲٬۰۰۰٬۰۰۰")
_, issue_line = mk("ISSUE", ph, 1, src=wh, entries=[TE(D(1), serial_no="SN002")])
check(out_costs(issue_line) == [(D(1), (12 * M).normalize())], f"خروجِ SN002 با بهایِ خودش، نه FIFO (got {out_costs(issue_line)})")
check({l.serial_id: l.remaining_quantity for l in layers(ph)}[serial_id(ph, "SN002")] == 0, "لایهٔ SN002 مصرف شد")
_, rin = mk("RETURN_IN", ph, 1, dst=wh, source_line=issue_line, entries=[TE(D(1), serial_no="SN002")])
with new_session() as s:
    rcost = s.scalar(select(StockLedger.unit_cost).where(StockLedger.stock_document_line_id == rin))
check(rcost == 12 * M, f"برگشت از فروشِ SN002 با بهایِ همان سریال ({rcost})")
check(any(l.serial_id == serial_id(ph, "SN002") and l.source_type_code == "RETURN_IN" and l.remaining_quantity == 1 for l in layers(ph)),
      "لایهٔ برگشتی دوباره به همان سریال وصل شد")
wh2 = locations_service.create_warehouse(company_id, "WH02", "فرعی", locations_service.WarehouseFields(allow_negative_stock=False))
_, tl = mk("TRANSFER", ph, 1, src=wh, dst=wh2, entries=[TE(D(1), serial_no="SN004")])
moved = [l for l in layers(ph, wh2)]
check(len(moved) == 1 and moved[0].serial_id == serial_id(ph, "SN004") and moved[0].unit_cost == 11 * M,
      "انتقال: سریال و بهایش در انبارِ مقصد حفظ شد")

# --- ۲) بچ: شناساییِ ویژه در برابرِ FIFO ---------------------------------------------------
exp = today + datetime.timedelta(days=300)
def batch_item(code, method):
    it = new_item(code, method, track_batch=True)
    mk("RECEIPT", it, 100, 100_000, dst=wh, entries=[TE(D(100), batch_no="A", expiry_date=exp)])
    mk("RECEIPT", it, 100, 130_000, dst=wh, entries=[TE(D(100), batch_no="B", expiry_date=exp)])
    return it
bs = batch_item("SP-BAT", "SPECIFIC")
check(sorted(l.unit_cost for l in layers(bs)) == [100_000, 130_000] and all(l.batch_id for l in layers(bs)),
      "هر بچ لایه/بهایِ مخصوصِ خودش را دارد")
_, ln = mk("ISSUE", bs, 50, src=wh, entries=[TE(D(50), batch_no="B")])
check(out_costs(ln) == [(D(50), D(130000))], "شناساییِ ویژه: خروج از بچِ B با بهایِ B")
bf = batch_item("FI-BAT", "FIFO")
_, ln = mk("ISSUE", bf, 50, src=wh, entries=[TE(D(50), batch_no="B")])
check(out_costs(ln) == [(D(50), D(100000))], "FIFO: بهایِ خروج طبقِ روشِ سیستم (قدیمی‌ترین)، نه بچِ فیزیکی")

# --- ۳) NIFO و بهایِ جایگزینی ---------------------------------------------------------------
check(any(m.code == "NIFO" for m in catalog_service.list_costing_methods()), "NIFO قابلِ‌انتخاب است")
nf = new_item("NI-1", "NIFO")
mk("RECEIPT", nf, 100, 100, dst=wh)
rid = rc.set_replacement_cost(company_id, nf, D(150), today, note="قیمتِ روز", user_id=user.user_id)
check(rc.get_replacement_cost(company_id, nf, wh) == (D(150), "MANUAL"), "بهایِ جایگزینیِ دستی معتبرترین منبع است")
d, ln = mk("ISSUE", nf, 10, src=wh)
check(alloc_costs(ln) == [(D(10), D(150))], f"NIFO: بهایِ خروج = بهایِ جایگزینی ۱۵۰ (got {alloc_costs(ln)})")
check(out_costs(ln) == [(D(10), D(100))], "NIFO با لایهٔ واقعی مخلوط نمی‌شود: موجودی با بهایِ دفتری ۱۰۰ کم شد")
check(not layers(nf), "NIFO لایه نمی‌سازد")
with new_session() as s:
    je = s.get(SD, d).journal_entry_id
    lines = s.execute(select(JournalEntryLine.account_id, JournalEntryLine.debit_amount_base, JournalEntryLine.credit_amount_base)
                      .where(JournalEntryLine.journal_entry_id == je)).all()
debit = {a: dbt for a, dbt, _c in lines if dbt}
credit = {a: cr for a, _d, cr in lines if cr}
check(debit.get(cogs_gl.account_id) == 1500 and credit.get(inv_gl.account_id) == 1000 and credit.get(adj_gl.account_id) == 500,
      f"سندِ NIFO: بهایِ تمام‌شده ۱۵۰۰، موجودی ۱۰۰۰، مغایرت ۵۰۰ ({debit}, {credit})")
with new_session() as s:
    logged = s.scalar(select(sa_func.count()).select_from(ActivityLog).where(ActivityLog.entity_type == "ReplacementCost"))
check(logged >= 1, "ثبتِ بهایِ جایگزینی در Audit")
# ترتیبِ منابع قابلِ‌تنظیم: بدونِ «دستی» → آخرین رسید
engine_service.set_costing_settings(company_id, "WEIGHTED_AVERAGE", True, user_id=user.user_id,
                                    nifo_price_sources=["LAST_RECEIPT", "MANUAL"])
_, ln = mk("ISSUE", nf, 5, src=wh)
check(alloc_costs(ln) == [(D(5), D(100))], "ترتیبِ منبع: آخرین رسید (۱۰۰) پیش از قیمتِ دستی")
check(raises(lambda: engine_service.set_costing_settings(company_id, "WEIGHTED_AVERAGE", True, nifo_price_sources=["XYZ"])),
      "منبعِ نامعتبر رد شد")
# فهرستِ قیمتِ تامین‌کننده (واحدِ کارتن = ۱۲ عدد)
carton = catalog_service.create_uom(company_id, "CTN", "کارتن", "COUNT", decimal_places=0)
nf2 = new_item("NI-2", "NIFO")
from peecha.services import unit_conversion as uc
uc.set_item_unit(nf2, carton, D(12))
with new_session() as s:
    pl = PriceList(company_id=company_id, code="PL-P", name="خرید", price_list_type_code="PURCHASE",
                   currency_id=company.base_currency_id, valid_from=today - datetime.timedelta(days=1), is_active=True)
    s.add(pl); s.flush()
    s.add(PriceListItem(price_list_id=pl.price_list_id, item_id=nf2, uom_id=carton, unit_price=D(1_200_000)))
    s.commit()
check(rc.replacement_cost(new_session(), company_id, nf2, wh, today, ["SUPPLIER_PRICE"]) == (D(100_000), "SUPPLIER_PRICE"),
      "قیمتِ تامین‌کننده به واحدِ پایه: کارتنِ ۱٬۲۰۰٬۰۰۰ → هر عدد ۱۰۰٬۰۰۰")
rc.set_replacement_cost(company_id, nf2, D(2_400_000), today, uom_id=carton, user_id=user.user_id)
check(rc.get_replacement_cost(company_id, nf2) is not None and
      rc.replacement_cost(new_session(), company_id, nf2, wh, today, ["MANUAL"]) == (D(200_000), "MANUAL"),
      "بهایِ جایگزینیِ واحدِ کارتن به واحدِ پایه تبدیل شد")
check(raises(lambda: rc.set_replacement_cost(company_id, nf2, D(0), today)), "بهایِ جایگزینیِ صفر رد شد")

print("RESULT:", "ALL PASS" if not FAIL else "SOME FAILED")
sys.exit(1 if FAIL else 0)
