import os, sys, datetime, decimal, io
os.environ["PEECHA_DB_NAME"] = "peecha_test_r225_1"
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
app_qt = QApplication.instance() or QApplication([])
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

wh = locations_service.create_warehouse(company_id, "WH", "مرکزی", locations_service.WarehouseFields(is_default=True))
wh2 = locations_service.create_warehouse(company_id, "WH2", "شعبه", locations_service.WarehouseFields())
van = pricing_service.create_channel(company_id, "VAN-1", "پخشِ گرم", "VAN_SALES")
price_list = pricing_service.create_price_list(company_id, "PL1", "فهرستِ عمومی", "SALES", company.base_currency_id, datetime.date.today())
customer = partners_service.create_customer(
    company_id, "C-1", "فروشگاهِ نمونه",
    fields=partners_service.CustomerProfileFields(default_price_list_id=price_list), fast_track=True,
)
supplier = dimensions_service.create_supplier(company_id, "S1", "تامین‌کننده")

uoms = {u.code: u.uom_id for u in catalog_service.list_uoms(company_id)}
def uom(code, name, typ="COUNT", dp=0):
    if code not in uoms:
        uoms[code] = catalog_service.create_uom(company_id, code, name, typ, decimal_places=dp)
    return uoms[code]
pcs, pack, ctn = uom("PCS", "عدد"), uom("PACK", "بسته"), uom("CTN", "کارتن")
kg = uom("KG", "کیلوگرم", "WEIGHT", 3)

item_id = catalog_service.create_item(company_id, "D-1", "نوشابه", catalog_service.ItemFields(item_kind_code="GOOD", base_uom_id=pcs))
uc.set_item_unit(item_id, pack, D(6))
uc.set_item_unit(item_id, ctn, D(24), is_default_sales=True, is_default_purchase=True)

# ---------- ۱. تبدیل ----------
check(uc.convert_to_base(item_id, D(10), ctn)[0] == 240, "۱۰ کارتن = ۲۴۰ عدد")
check(uc.convert_to_base(item_id, D(3), pack)[0] == 18, "۳ بسته = ۱۸ عدد")
check(uc.convert_from_base(item_id, D(72), ctn) == 3, "۷۲ عدد = ۳ کارتن")
units = uc.get_item_units(item_id)
check([u.code for u in units][0] == "PCS" and units[0].is_base, "واحدِ پایه اولین ردیفِ واحدهایِ کالاست")

def commercial(doc_type, lines, counterparty, warehouse_id=wh, post=True):
    doc_id = documents_service.create_document(company_id, user.user_id, doc_type, datetime.date.today(),
        documents_service.DocumentHeaderFields(counterparty_detail_account_id=counterparty, currency_id=company.base_currency_id, warehouse_id=warehouse_id))
    for u, q, p in lines:
        documents_service.add_line(doc_id, company_id, item_id, u, D(q), D(q), unit_price=D(p))
    if post:
        documents_service.confirm_document(doc_id, company_id, user.user_id)
        try:
            documents_service.approve_document(doc_id, company_id)
        except ValueError:
            pass
        if doc_type in ("SALES_INVOICE", "PURCHASE_INVOICE"):
            settlements_service.auto_approve_settlement_plan(doc_id, company_id, user.user_id, [])
        documents_service.post_document(doc_id, company_id, user.user_id)
    return doc_id

def on_hand(warehouse_id=wh):
    return sum((r.quantity_on_hand for r in engine_service.get_item_stock_by_warehouse(company_id, item_id) if r.warehouse_id == warehouse_id), D(0))

# ---------- ۲. خرید ۱۰ کارتن ----------
po = commercial("PURCHASE_INVOICE", [(ctn, 10, 240000)], supplier)
_, lines = documents_service.get_document(po, company_id)
check(lines[0].quantity == 10 and lines[0].quantity_base == 240 and lines[0].conversion_factor == 24,
      f"ردیفِ خرید: مقدارِ تراکنش ۱۰ کارتن، پایه ۲۴۰، ضریبِ snapshot ۲۴ (got {lines[0].quantity_base}, {lines[0].conversion_factor})")
check(on_hand() == 240, f"موجودی +۲۴۰ عدد (got {on_hand()})")
ledger = engine_service.list_item_ledger(company_id, item_id)
check(any(l.unit_cost == 10000 for l in ledger), f"بهایِ لجر به ازایِ واحدِ پایه (۲۴۰۰۰۰ ÷ ۲۴ = ۱۰۰۰۰) (got {[l.unit_cost for l in ledger]})")

# ---------- ۳. فروش ۳ کارتن ----------
so = commercial("SALES_INVOICE", [(ctn, 3, 250000)], customer)
check(on_hand() == 168, f"فروشِ ۳ کارتن: موجودی −۷۲ (got {on_hand()})")

# ---------- ۴/۵. بارکدِ کارتن و بسته ----------
uc.add_barcode(company_id, item_id, ctn, "6260000000017", is_primary=True)
uc.add_barcode(company_id, item_id, pack, "6260000000024")
m = uc.resolve_barcode(company_id, "6260000000017")
check(m is not None and m.item_id == item_id and m.uom_id == ctn and m.factor == 24, "اسکنِ بارکدِ کارتن: کالا + واحدِ کارتن + ضریبِ ۲۴")
m = uc.resolve_barcode(company_id, "6260000000024")
check(m is not None and m.uom_id == pack and m.factor == 6, "اسکنِ بارکدِ بسته: واحدِ بسته + ضریبِ ۶")
check(uc.resolve_barcode(company_id, "0000") is None, "بارکدِ ناشناخته None")

# ---------- ۶. بارکدِ تکراری ----------
item2 = catalog_service.create_item(company_id, "D-2", "دوغ", catalog_service.ItemFields(item_kind_code="GOOD", base_uom_id=pcs))
check(raises(lambda: uc.add_barcode(company_id, item2, pcs, "6260000000017")), "بارکدِ فعالِ تکراری (حتی رویِ کالایِ دیگر) رد می‌شود")
check(raises(lambda: uc.add_barcode(company_id, item_id, pcs, "6260000000018", barcode_type="EAN13")), "بارکدِ EAN-13 با رقمِ کنترلِ غلط رد می‌شود")
check(uc.detect_barcode_type("6260000000019") == "EAN13", "تشخیصِ خودکارِ EAN-13 معتبر")
check(raises(lambda: uc.add_barcode(company_id, item_id, pcs, "ABC 123", barcode_type="EAN8")), "EAN-8 غیرعددی رد می‌شود")

# ---------- ۷. واحدِ غیرفعال ----------
box = uom("BOX", "جعبه")
box_unit_id = uc.set_item_unit(item_id, box, D(12))
uc.set_item_unit(item_id, box, D(12), is_active=False)
check(raises(lambda: commercial("SALES_INVOICE", [(box, 1, 1000)], customer, post=False)), "واحدِ غیرفعال در سندِ تازه رد می‌شود")

# ---------- ۸. تغییرِ ضریب اسنادِ قبلی را عوض نمی‌کند ----------
uc.set_item_unit(item_id, ctn, D(20), is_default_sales=True, is_default_purchase=True)
_, lines = documents_service.get_document(so, company_id)
check(lines[0].conversion_factor == 24 and lines[0].quantity_base == 72, "فاکتورِ قبلی همچنان ضریبِ ۲۴ و پایهٔ ۷۲ دارد")
check(on_hand() == 168, "موجودی با تغییرِ ضریب عوض نشد")
uc.set_item_unit(item_id, ctn, D(24), is_default_sales=True, is_default_purchase=True)

# ---------- ۹. اعشار ----------
check(raises(lambda: uc.validate_quantity(item_id, ctn, D("1.5"))), "کارتن (بدونِ اعشار) ۱٫۵ نمی‌پذیرد")
rice = catalog_service.create_item(company_id, "R-1", "برنج", catalog_service.ItemFields(item_kind_code="GOOD", base_uom_id=kg))
check(not raises(lambda: uc.validate_quantity(rice, kg, D("2.125"))), "کیلوگرم ۳ رقمِ اعشار می‌پذیرد")
check(raises(lambda: uc.validate_quantity(rice, kg, D("2.1255"))), "کیلوگرم ۴ رقمِ اعشار نمی‌پذیرد")

# ---------- ۱۵. قیمتِ واحد ----------
pricing_service.set_price_list_item(price_list, item_id, pcs, D(11000))
check(uc.get_price_for_unit(company_id, item_id, pack, price_list) == 66000, "بدونِ قیمتِ مستقل: قیمتِ بسته = قیمتِ عدد × ۶")
pricing_service.set_price_list_item(price_list, item_id, ctn, D(250000))
check(uc.get_price_for_unit(company_id, item_id, ctn, price_list) == 250000, "قیمتِ مستقلِ کارتن بر ضریب (۲۶۴۰۰۰) اولویت دارد")

# ---------- ۱۰. سفارشِ موبایل با واحد ----------
from fastapi.testclient import TestClient
from peecha_api.main import app
client = TestClient(app)
token = client.post("/auth/login", json={"username": "admin", "password": "secret123"}).json()["access_token"]
H = {"Authorization": f"Bearer {token}"}
r = client.get(f"/products/catalog?warehouse_id={wh}&price_list_id={price_list}", headers=H)
cat = {i["item_id"]: i for i in r.json()["items"]}
unit_codes = {u["code"]: u for u in cat[item_id]["units"]}
check({"PCS", "PACK", "CTN"} <= set(unit_codes) and "BOX" not in unit_codes, f"کاتالوگِ موبایل واحدهایِ فعال را دارد (got {list(unit_codes)})")
check(unit_codes["CTN"]["factor"] == "24" and unit_codes["CTN"]["price"] == "250000.00" or D(unit_codes["CTN"]["price"]) == 250000,
      f"ضریب و قیمتِ کارتن در کاتالوگ (got {unit_codes['CTN']})")
check("6260000000017" in unit_codes["CTN"]["barcodes"], "بارکدِ کارتن در کاتالوگ")
check(cat[item_id]["stock_quantity"] is not None and D(cat[item_id]["stock_quantity"]) == 168, "موجودیِ کاتالوگ به واحدِ پایه")
r = client.get("/sync/pull", headers=H)
pull_item = next((i for i in r.json()["items"] if i["item_id"] == item_id), None)
check(pull_item is not None and {u["code"] for u in pull_item["units"]} >= {"PCS", "PACK", "CTN"}, "/sync/pull واحدهایِ فروش را هم برایِ پخشِ سرد دارد")
r = client.get("/products/barcode/6260000000024", headers=H)
check(r.status_code == 200 and r.json()["uom_id"] == pack and r.json()["factor"] == "6", f"GET /products/barcode (got {r.text[:200]})")
r = client.get("/pricing/resolve", headers=H, params={
    "counterparty_detail_account_id": customer, "item_id": item_id, "uom_id": pack, "quantity": "1", "document_type_code": "SALES_INVOICE",
})
check(r.status_code == 200 and D(r.json()["unit_price"]) == 66000, f"/pricing/resolve قیمتِ بسته (got {r.text[:200]})")
payload = {
    "document_type_code": "SALES_INVOICE", "counterparty_detail_account_id": customer,
    "warehouse_id": wh, "channel_code": van, "currency_id": company.base_currency_id,
    "post_immediately": True, "settlement_lines": [],
    "lines": [
        {"item_id": item_id, "uom_id": ctn, "quantity": "2", "unit_price": "250000"},
        {"item_id": item_id, "uom_id": pack, "quantity": "1", "unit_price": "66000"},
    ],
}
r = client.post("/orders", headers=H, json=payload)
check(r.status_code == 200, f"سفارشِ موبایل با کارتن و بسته (body={r.text[:300]})")
_, lines = documents_service.get_document(r.json()["document_id"], company_id)
check(sorted(l.quantity_base for l in lines) == [6, 48], f"مقدارِ پایه سمتِ سرور محاسبه شد (got {[l.quantity_base for l in lines]})")
check(on_hand() == 168 - 54, f"موجودی −۵۴ (got {on_hand()})")
# واحدِ غیرفعال از موبایل: فروشِ واقعی رد نمی‌شود، هشدار می‌گیرد
payload_bad = dict(payload, lines=[{"item_id": item_id, "uom_id": box, "quantity": "1", "unit_price": "1000"}])
r = client.post("/orders", headers=H, json=payload_bad)
check(r.status_code == 200, f"واحدِ غیرفعال از موبایل ۴xx نمی‌دهد (body={r.text[:300]})")
check("هشدار" in (r.json().get("settlement_warning") or ""), f"هشدارِ واحد برگشت (got {r.json().get('settlement_warning')})")
stock_before_returns = on_hand()

# ---------- ۱۱. برگشت به تامین‌کننده ----------
commercial("PURCHASE_RETURN", [(ctn, 1, 240000)], supplier)
check(on_hand() == stock_before_returns - 24, f"برگشتِ ۱ کارتن به تامین‌کننده −۲۴ (got {on_hand()})")

# ---------- ۱۲. برگشت از فروش ----------
commercial("SALES_RETURN", [(pack, 2, 66000)], customer)
check(on_hand() == stock_before_returns - 24 + 12, f"برگشتِ ۲ بسته از مشتری +۱۲ (got {on_hand()})")

# ---------- ۱۳. انتقالِ بین‌انبار ----------
before = on_hand()
t = inv_documents_service.create_stock_document(company_id, user.user_id, "TRANSFER", datetime.date.today(),
    inv_documents_service.DocumentHeaderFields(source_warehouse_id=wh, destination_warehouse_id=wh2))
inv_documents_service.add_line(t, company_id, inv_documents_service.LineFields(item_id=item_id, uom_id=ctn, quantity=D(2), quantity_base=D(2)))
inv_documents_service.confirm_stock_document(t, company_id)
inv_documents_service.post_stock_document(t, company_id, user.user_id)
check(on_hand() == before - 48 and on_hand(wh2) == 48, f"انتقالِ ۲ کارتن = ۴۸ عدد (got {on_hand()}, {on_hand(wh2)})")

# ---------- ۱۴. انبارگردانی ----------
session_id = stock_count_service.create_count_session(company_id, wh2, user.user_id)
stock_count_service.record_count(session_id, company_id, item_id, ctn, D(1))
stock_count_service.record_count(session_id, company_id, item_id, ctn, D(2))
data = stock_count_service.get_count_session(session_id, company_id)
check(len(data.lines) == 1 and data.lines[0].counted_quantity_base == 48 and data.lines[0].variance_quantity_base == 0,
      "شمارشِ ۲ کارتن = ۴۸ (جایگزینیِ شمارشِ قبلی)، اختلاف صفر")
stock_count_service.record_count(session_id, company_id, item_id, pack, D(7))
docs = stock_count_service.finalize_count_session(session_id, company_id, user.user_id)
check(on_hand(wh2) == 42 and len(docs) == 1, f"شمارشِ ۷ بسته = ۴۲ عدد؛ کسریِ ۶ با سندِ اصلاح (got {on_hand(wh2)}, docs={docs})")
check(raises(lambda: stock_count_service.record_count(session_id, company_id, item_id, pcs, D(1))), "جلسهٔ بسته‌شده شمارش نمی‌پذیرد")

# ---------- ۱۶. POS: اسکنِ بارکدِ بسته ----------
from peecha.ui.screens.commercial_pos_sale import CommercialPosSaleScreen
from peecha.services import commercial_pos as pos_service
terminal_id = pos_service.create_terminal(company_id, wh, "T1", "صندوقِ اصلی")
pos_service.open_session(terminal_id, user.user_id, D(0))
pos = CommercialPosSaleScreen()
pos.refresh()
pos.terminal_combo.setCurrentIndex(pos.terminal_combo.findData(terminal_id))
pos.customer_combo.setCurrentIndex(pos.customer_combo.findData(customer))
pos.price_list_combo.setCurrentIndex(pos.price_list_combo.findData(price_list))
pos.scan_field.setText("6260000000024")
pos._scan_or_search()
pos_lines = documents_service.get_document(pos._document_id, company_id)[1] if pos._document_id else []
check(len(pos_lines) == 1 and pos_lines[0].uom_id == pack and pos_lines[0].quantity_base == 6 and pos_lines[0].unit_price == 66000,
      f"POS: اسکنِ بارکدِ بسته ردیفِ ۱ بسته (= ۶ عدد) با قیمتِ بسته می‌سازد (got {[(l.uom_id, l.quantity_base) for l in pos_lines]}, status={pos.status_label.text()})")
if pos._document_id:
    documents_service.delete_document(pos._document_id, company_id) if hasattr(documents_service, "delete_document") else None

# ---------- ۱۷. گزارش: مقدارِ پایه و مقدارِ تراکنش ----------
rows = documents_service.compute_sales_report_by_item(company_id, datetime.date.today(), datetime.date.today())
row = next((r for r in rows if r.item_id == item_id), None)
# ۷۲ (۳ کارتن) + ۵۴ (موبایل) + ۱۲ (فروشِ موبایل با واحدِ غیرفعال که با هشدار ثبت شد)
check(row is not None and row.quantity_sold == 72 + 54 + 12, f"گزارشِ فروش به واحدِ پایه (got {row and row.quantity_sold})")
check(row is not None and row.transaction_quantities.get("کارتن") == 5 and row.transaction_quantities.get("بسته") == 1,
      f"گزارشِ فروش مقدارِ تراکنش به تفکیکِ واحد (got {row and row.transaction_quantities})")

# ---------- قوانینِ حذف/تغییرِ پایه ----------
ctn_unit = uc.get_item_unit(item_id, ctn)
check(uc.remove_item_unit(ctn_unit.item_unit_id, item_id) == "DEACTIVATED", "واحدِ استفاده‌شده حذف نمی‌شود، غیرفعال می‌شود")
unused = uom("ROLL", "رول")
roll_id = uc.set_item_unit(item_id, unused, D(10))
check(uc.remove_item_unit(roll_id, item_id) == "DELETED", "واحدِ استفاده‌نشده واقعاً حذف می‌شود")
item_row = next(r for r in catalog_service.list_items(company_id) if r.item_id == item_id)
check(raises(lambda: catalog_service.update_item(item_id, company_id, item_row.code, item_row.name, True, item_row.lifecycle_status_code,
                                                  catalog_service.ItemFields(item_kind_code="GOOD", base_uom_id=pack))),
      "تغییرِ واحدِ پایهٔ کالایِ دارایِ سابقه ممنوع است")

print("RESULT:", "ALL PASS" if not FAIL else "SOME FAILED")
sys.exit(1 if FAIL else 0)
