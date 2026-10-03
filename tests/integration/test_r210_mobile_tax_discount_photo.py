import os, sys, datetime, decimal, io
os.environ["PEECHA_DB_NAME"] = "peecha_test_r210_1"
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

central = locations_service.create_warehouse(company_id, "WH", "مرکزی", locations_service.WarehouseFields(is_default=True, allow_negative_stock=True))
# طبقِ باگِ واقعیِ کشف‌شده (R210): انبار درصدِ مالياتِ خودش را override
# می‌کند (اولویتِ شرکت→انبار→کالا) -- برایِ آزمودنِ همین اولویت.
vehicle = locations_service.create_warehouse(company_id, "N01", "نیسان", locations_service.WarehouseFields(
    warehouse_type_code="VEHICLE", allow_negative_stock=True, default_tax_percent=decimal.Decimal("5"),
))
van = pricing_service.create_channel(company_id, "VAN-1", "پخشِ گرم", "VAN_SALES")

price_list = pricing_service.create_price_list(company_id, "PL1", "فهرستِ عمومی", "SALES", company.base_currency_id, datetime.date.today())
customer = partners_service.create_customer(
    company_id, "C-1", "فروشگاهِ نمونه",
    fields=partners_service.CustomerProfileFields(default_price_list_id=price_list), fast_track=True,
)

uom_id = catalog_service.create_uom(company_id, "PCS", "عدد", "COUNT")
item_id = catalog_service.create_item(company_id, "9101", "آب‌معدنی", catalog_service.ItemFields(
    item_kind_code="GOOD", base_uom_id=uom_id, default_tax_percent=decimal.Decimal("9")))
item_no_photo_id = catalog_service.create_item(company_id, "9102", "چای", catalog_service.ItemFields(
    item_kind_code="GOOD", base_uom_id=uom_id))

pricing_service.set_price_list_item(price_list, item_id, uom_id, decimal.Decimal("10000"))
pricing_service.set_price_list_item(price_list, item_no_photo_id, uom_id, decimal.Decimal("2000"))
pricing_service.create_discount_rule(company_id, "D1", "تخفیفِ همگانی", "PERCENT", "ALL", discount_value=decimal.Decimal("10"))

doc = inv_documents_service.create_stock_document(company_id, user.user_id, "RECEIPT", datetime.date.today(),
    inv_documents_service.DocumentHeaderFields(destination_warehouse_id=vehicle))
inv_documents_service.add_line(doc, company_id, inv_documents_service.LineFields(item_id=item_id, uom_id=uom_id, quantity=decimal.Decimal(10), quantity_base=decimal.Decimal(10), unit_cost=decimal.Decimal(1000)))
inv_documents_service.confirm_stock_document(doc, company_id)
inv_documents_service.post_stock_document(doc, company_id, user.user_id)

from fastapi.testclient import TestClient
from peecha_api.main import app
client = TestClient(app)
token = client.post("/auth/login", json={"username": "admin", "password": "secret123"}).json()["access_token"]
H = {"Authorization": f"Bearer {token}"}

# ---------- ۱. GET /pricing/resolve: تخفیف + مالياتِ پیش‌نمایش ----------
r = client.get("/pricing/resolve", headers=H, params={
    "counterparty_detail_account_id": customer, "item_id": item_id, "uom_id": uom_id,
    "quantity": "1", "document_type_code": "SALES_INVOICE", "warehouse_id": vehicle,
})
check(r.status_code == 200, f"resolve ۲۰۰ (body={r.text[:200]})")
resolved = r.json()
check(decimal.Decimal(resolved["unit_price"]) == decimal.Decimal("10000"), f"قیمتِ ناخالص از فهرستِ قیمت (got {resolved})")
check(decimal.Decimal(resolved["discount_amount"]) == decimal.Decimal("1000"), f"تخفیفِ ۱۰٪ (got {resolved})")
check(decimal.Decimal(resolved["tax_percent"]) == decimal.Decimal("5"), f"درصدِ مالياتِ انبار (۵٪) روی درصدِ خودِ کالا (۹٪) اولویت دارد (got {resolved})")

# ---------- ۲. POST /orders: تخفیف واقعاً ثبت می‌شود، مالیات خودِ سرور تعیین می‌کند ----------
payload = {
    "document_type_code": "SALES_INVOICE", "counterparty_detail_account_id": customer,
    "warehouse_id": vehicle, "channel_code": van, "currency_id": company.base_currency_id,
    "post_immediately": True, "settlement_lines": [],
    "lines": [{"item_id": item_id, "uom_id": uom_id, "quantity": "1", "unit_price": "10000", "discount_amount": "1000"}],
}
r = client.post("/orders", headers=H, json=payload)
check(r.status_code == 200, f"فاکتورِ پخشِ گرم ثبت شد (body={r.text})")
doc_id = r.json()["document_id"]
_, lines = documents_service.get_document(doc_id, company_id)
check(len(lines) == 1, f"یک ردیف ثبت شد (got {len(lines)})")
line = lines[0]
# خالص = ۱۰۰۰۰ − ۱۰۰۰ = ۹۰۰۰ -- مالیات = ۹۰۰۰×۵٪ = ۴۵۰ (نه ۹٪ِ خودِ کالا، چونِ انبار override کرده)
check(line.discount_amount == decimal.Decimal("1000"), f"تخفیف در سندِ ثبت‌شده (got {line.discount_amount})")
check(line.tax_percent == decimal.Decimal("5.00") or line.tax_percent == decimal.Decimal("5"), f"درصدِ مالیاتِ انبار در سند (got {line.tax_percent})")
check(line.tax_amount == decimal.Decimal("450.00") or line.tax_amount == decimal.Decimal("450"), f"مالياتِ محاسبه‌شده رویِ خالص (got {line.tax_amount})")

# اگر کلاینت هیچ discount_amountای نفرستد (سازگاریِ عقب‌رو با موبایلِ آپدیت‌نشده) -- صفر می‌ماند، نه خطا
payload2 = dict(payload, lines=[{"item_id": item_id, "uom_id": uom_id, "quantity": "1", "unit_price": "10000"}])
r2 = client.post("/orders", headers=H, json=payload2)
check(r2.status_code == 200, f"بدونِ discount_amount هم ۲۰۰ (body={r2.text})")
_, lines2 = documents_service.get_document(r2.json()["document_id"], company_id)
check(lines2[0].discount_amount == decimal.Decimal("0"), f"بدونِ تخفیف یعنی صفر (got {lines2[0].discount_amount})")

# ---------- ۳. عکسِ کالا در کاتالوگِ موبایل ----------
r = client.get(f"/products/catalog?warehouse_id={vehicle}", headers=H)
cat = {i["item_id"]: i for i in r.json()["items"]}
check(cat[item_id]["photo_base64"] is None, f"پیش از فعال‌سازیِ گروهِ عکس، عکس نیست (got {cat[item_id]['photo_base64']})")

item_dim_type_id = dimensions_service.get_specialized_dimension_type_id(company_id, dimensions_service.INVENTORY_ITEM_CODE)
dimensions_service.set_dimension_type_photo_enabled(item_dim_type_id, company_id, True)

from PIL import Image as PILImage
photo_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_r210_tmp_item_photo.png")
PILImage.new("RGB", (400, 400), color=(10, 120, 200)).save(photo_path)
try:
    item = catalog_service.get_item(item_id)
    attachment_id = dimensions_service.attach_detail_account_file(company_id, item.item_detail_account_id, user.user_id, photo_path)
    dimensions_service.set_primary_detail_account_photo(attachment_id, company_id)
finally:
    os.remove(photo_path)

r = client.get(f"/products/catalog?warehouse_id={vehicle}", headers=H)
cat = {i["item_id"]: i for i in r.json()["items"]}
photo_b64 = cat[item_id]["photo_base64"]
check(photo_b64 is not None, f"عکسِ اصلیِ کالا بعدِ آپلود در کاتالوگ هست (got {cat[item_id]})")
check(cat[item_no_photo_id]["photo_base64"] is None, f"کالایِ بی‌عکس همچنان null است (got {cat[item_no_photo_id]['photo_base64']})")
if photo_b64 is not None:
    import base64
    raw = base64.b64decode(photo_b64)
    with PILImage.open(io.BytesIO(raw)) as thumb:
        check(max(thumb.size) <= 96, f"عکس کوچک شده (got {thumb.size})")
    check(len(raw) < 20000, f"حجمِ بندانگشتی معقول است (got {len(raw)} bytes)")

print("RESULT:", "ALL PASS" if not FAIL else "SOME FAILED")
sys.exit(1 if FAIL else 0)
