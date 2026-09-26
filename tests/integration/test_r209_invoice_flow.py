import os, sys, datetime
os.environ["PEECHA_DB_NAME"] = "peecha_test_r209_1"
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
import decimal
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
from peecha.services import treasury as treasury_service
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import commercial_settlements as settlements_service

lang_id = company.default_language_id
A = lambda code, name, nature, typ, perm, post, parent=None: coa_service.create_account(company_id, code, name, nature, typ, perm, post, lang_id, parent_account_id=parent)
g1 = A("1", "دارایی‌ها", "DEBIT", "ASSET", "PERMANENT", False)
k1 = A("11", "موجودیِ نقد", "DEBIT", "ASSET", "PERMANENT", False, g1.account_id)
cash_gl = A("101", "صندوق", "DEBIT", "ASSET", "PERMANENT", True, k1.account_id)
checks_gl = A("102", "اسنادِ دریافتنی", "DEBIT", "ASSET", "PERMANENT", True, k1.account_id)
k2 = A("13", "دریافتنی‌ها", "DEBIT", "ASSET", "PERMANENT", False, g1.account_id)
ar_gl = A("1304", "دریافتنیِ مشتریان", "DEBIT", "ASSET", "PERMANENT", True, k2.account_id)
k3 = A("12", "موجودیِ انبار", "DEBIT", "ASSET", "PERMANENT", False, g1.account_id)
inv_gl = A("121", "موجودیِ کالا", "DEBIT", "ASSET", "PERMANENT", True, k3.account_id)
g2 = A("4", "درآمدها", "CREDIT", "REVENUE", "TEMPORARY", False)
k4 = A("41", "درآمدِ عملیاتی", "CREDIT", "REVENUE", "TEMPORARY", False, g2.account_id)
rev_gl = A("411", "فروش", "CREDIT", "REVENUE", "TEMPORARY", True, k4.account_id)
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

central = locations_service.create_warehouse(company_id, "WH", "مرکزی", locations_service.WarehouseFields(is_default=True, allow_negative_stock=True))
vehicle = locations_service.create_warehouse(company_id, "N01", "نیسان", locations_service.WarehouseFields(warehouse_type_code="VEHICLE"))
van = pricing_service.create_channel(company_id, "VAN-1", "پخشِ گرم", "VAN_SALES")
pre = pricing_service.create_channel(company_id, "PRE-1", "پخشِ سرد", "PRE_SALES")
customer = partners_service.create_customer(company_id, "C-1", "فروشگاهِ نمونه", fast_track=True)
uom_id = catalog_service.create_uom(company_id, "PCS", "عدد", "COUNT")
brand_id = catalog_service.create_brand(company_id, "B1", "برندِ الف") if hasattr(catalog_service, "create_brand") else None
cat_id = catalog_service.create_category(company_id, "CAT1", "نوشیدنی") if hasattr(catalog_service, "create_category") else None
item_id = catalog_service.create_item(company_id, "9101", "آب‌معدنی", catalog_service.ItemFields(
    item_kind_code="GOOD", base_uom_id=uom_id, barcode="6260000000011", brand_id=brand_id, category_id=cat_id))
parent_id = catalog_service.create_item(company_id, "9200", "نوشابه (اصلی)", catalog_service.ItemFields(item_kind_code="GOOD", base_uom_id=uom_id))
child_id = catalog_service.create_item(company_id, "9200-1", "نوشابه قرمز", catalog_service.ItemFields(item_kind_code="GOOD", base_uom_id=uom_id, variant_parent_item_id=parent_id))

# ۱۰ عدد در خودرو
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

# ---------- ۲. کاتالوگ ----------
r = client.get(f"/products/catalog?warehouse_id={vehicle}", headers=H)
check(r.status_code == 200, f"کاتالوگ ۲۰۰ (body={r.text[:200]})")
cat = r.json()
ids = {i["item_id"]: i for i in cat["items"]}
check(item_id in ids and decimal.Decimal(ids[item_id]["stock_quantity"]) == 10, f"موجودیِ خودرو ۱۰ است (got {ids.get(item_id)})")
check(ids[item_id]["barcode"] == "6260000000011", "بارکد در کاتالوگ هست")
check(parent_id not in ids and child_id in ids, "کالای اصلیِ متغیردار حذف، متغیرش هست")
if brand_id: check(any(b["brand_id"] == brand_id for b in cat["brands"]), "برند در فیلترها هست")
if cat_id: check(any(c["category_id"] == cat_id for c in cat["categories"]), "دسته‌بندی در فیلترها هست")
check(client.get("/products/catalog?warehouse_id=99999", headers=H).status_code == 400, "انبارِ نامعتبر ۴۰۰")

# ---------- ۱. جداسازیِ گرم/سرد ----------
base = {"counterparty_detail_account_id": customer, "currency_id": company.base_currency_id,
        "lines": [{"item_id": item_id, "uom_id": uom_id, "quantity": "1", "unit_price": "10000"}]}
r = client.post("/orders", headers=H, json=dict(base, document_type_code="SALES_ORDER", warehouse_id=central, channel_code=pre))
check(r.status_code == 200, f"سفارشِ پخشِ سرد ثبت شد (body={r.text})")
cold_doc = r.json()["document_id"]
r = client.post("/orders", headers=H, json=dict(base, document_type_code="SALES_INVOICE", warehouse_id=vehicle, channel_code=van, post_immediately=True, settlement_lines=[]))
check(r.status_code == 200, f"فاکتورِ نسیهٔ پخشِ گرم ثبت شد (body={r.text})")
hot_credit_doc = r.json()["document_id"]
check(isinstance(r.json().get("document_no"), int), f"پاسخ document_no دارد (got {r.json()})")

hot = client.get("/dashboard/today?mode=VAN_SALES", headers=H).json()
cold = client.get("/dashboard/today?mode=PRE_SALES", headers=H).json()
legacy = client.get("/dashboard/today", headers=H).json()
check(hot["order_count"] == 1 and decimal.Decimal(hot["sales_amount"]) == 10000, f"داشبوردِ گرم فقط فاکتورِ گرم (got {hot['order_count']}, {hot['sales_amount']})")
check(cold["order_count"] == 1, f"داشبوردِ سرد فقط سفارشِ سرد (got {cold['order_count']})")
check(legacy["order_count"] == 2, f"بدونِ mode رفتارِ قبلی (got {legacy['order_count']})")
hot_docs = {d["document_id"] for d in client.get(f"/customers/{customer}?mode=VAN_SALES", headers=H).json()["recent_documents"]}
cold_docs = {d["document_id"] for d in client.get(f"/customers/{customer}?mode=PRE_SALES", headers=H).json()["recent_documents"]}
check(hot_docs == {hot_credit_doc}, f"سوابقِ مشتری در گرم فقط گرم (got {hot_docs})")
check(cold_docs == {cold_doc}, f"سوابقِ مشتری در سرد فقط سرد (got {cold_docs})")

# ---------- ۳. تسویهٔ واقعی ----------
# بدونِ تنظیماتِ خزانه: فاکتور حفظ شود و هشدار برگردد (نه ۴۰۰ که فروش را از صف حذف کند)
r = client.post("/orders", headers=H, json=dict(base, document_type_code="SALES_INVOICE", warehouse_id=vehicle, channel_code=van, post_immediately=True,
    settlement_lines=[{"method_code": "CASH", "amount": "10000"}]))
check(r.status_code == 200 and r.json()["settlement_warning"], f"بدونِ نگاشتِ خزانه: ۲۰۰ + هشدار (body={r.text})")

customer_group_id = dimensions_service.get_person_group_id(company_id, dimensions_service.CUSTOMER_GROUP_CODE)
treasury_service.create_counterparty_mapping(company_id, "RECEIPT", ar_gl.account_id, person_group_id=customer_group_id)
treasury_service.set_account_mapping(company_id, "RECEIPT_CASH", cash_gl.account_id)
treasury_service.set_account_mapping(company_id, "RECEIPT_CHECK", checks_gl.account_id)
bank = treasury_service.create_bank(company_id, "بانکِ ملت", "MLT")

r = client.get("/pricing/settlement-methods", headers=H)
methods = {m["method_code"]: m for m in r.json()}
check("CHECK" in methods and "requires_detail" in methods["CHECK"], f"روش‌ها با requires_detail (got {list(methods)})")
r = client.get("/pricing/banks", headers=H)
check(any(b["bank_id"] == bank.bank_id for b in r.json()), f"فهرستِ بانک‌ها (got {r.text})")

bad = client.post("/orders", headers=H, json=dict(base, document_type_code="SALES_INVOICE", warehouse_id=vehicle, channel_code=van, post_immediately=True,
    settlement_lines=[{"method_code": "CHECK", "amount": "5000", "checks": [{"check_no": "111", "due_date": "2026-12-01", "amount": "4000"}]}]))
check(bad.status_code == 400, f"جمعِ چک‌ها نابرابر -> ۴۰۰ (body={bad.text})")

lines3 = [{"item_id": item_id, "uom_id": uom_id, "quantity": "3", "unit_price": "10000"}]
payload = dict(base, lines=lines3, document_type_code="SALES_INVOICE", warehouse_id=vehicle, channel_code=van, post_immediately=True,
    settlement_lines=[
        {"method_code": "CASH", "amount": "8000", "note": "نقدِ دستِ راننده"},
        {"method_code": "CHECK", "amount": "15000", "checks": [
            {"check_no": "123456", "check_serial": "A1", "bank_id": bank.bank_id, "due_date": "2026-11-01", "amount": "10000",
             "party_name": "آقای نمونه", "national_id": "0012345678", "phone": "09120000000", "iban": "IR000000000000000000000001", "bank_account_no": "55"},
            {"check_no": "123457", "check_bank_name": "بانکِ ملی", "due_date": "2026-12-01", "amount": "5000"},
        ]},
    ])
r = client.post("/orders", headers=H, json=payload)
check(r.status_code == 200 and not r.json()["settlement_warning"], f"فاکتور با نقد+۲چک، بدونِ هشدار (body={r.text})")
paid_doc = r.json()["document_id"]
status_ = settlements_service.get_invoice_settlement_status(paid_doc, company_id)
check(status_.settled_amount == 23000 and status_.remaining_amount == 7000, f"۲۳۰۰۰ تسویه، ۷۰۰۰ نسیه (got {status_.settled_amount}/{status_.remaining_amount})")
from peecha.db.models.treasury import ReceivedCheck
with new_session() as s:
    rc = s.scalars(select(ReceivedCheck).where(ReceivedCheck.check_no.in_(["123456", "123457"])).order_by(ReceivedCheck.check_no)).all()
    check(len(rc) == 2, f"دو چکِ دریافتی در خزانه ثبت شد (got {len(rc)})")
    if len(rc) == 2:
        c1, c2 = rc
        check((c1.drawee_bank_name, c1.check_serial, c1.drawer_national_id, c1.drawer_phone, c1.iban, c1.bank_account_no, c1.bank_id, c1.due_date, c1.amount, c1.drawer_name)
              == ("بانکِ ملت", "A1", "0012345678", "09120000000", "IR000000000000000000000001", "55", bank.bank_id, datetime.date(2026, 11, 1), 10000, "آقای نمونه"),
              f"همهٔ فیلدهایِ چکِ اول ذخیره شد")
        check(c2.drawee_bank_name == "بانکِ ملی" and c2.amount == 5000, "چکِ دوم درست")
        check(c1.counterparty_detail_account_id == customer, "چک به نامِ همان مشتری")

# ---------- ۴. دادهٔ چاپ ----------
r = client.get(f"/orders/{paid_doc}/print-data", headers=H)
check(r.status_code == 200, f"print-data ۲۰۰ (body={r.text[:200]})")
pdata = r.json()
check(pdata["customer"]["name"] == "فروشگاهِ نمونه" and pdata["company"]["name"], "سرِبرگ و مشتری")
check(len(pdata["lines"]) == 1 and pdata["lines"][0]["item_name"] == "آب‌معدنی" and decimal.Decimal(pdata["total_amount"]) == 30000, f"ردیف و جمع (got {pdata['lines']}, {pdata['total_amount']})")
check({l["method_code"] for l in pdata["settlement_lines"]} == {"CASH", "CHECK"}, f"ردیف‌هایِ تسویه (got {pdata['settlement_lines']})")
check(len(pdata["checks"]) == 2 and decimal.Decimal(pdata["remaining_amount"]) == 7000, f"چک‌ها و مانده در چاپ (got {pdata['checks']}, {pdata['remaining_amount']})")
check(client.get("/orders/99999/print-data", headers=H).status_code == 404, "سندِ نامعتبر ۴۰۴")

# ---------- ۵. باگِ واقعیِ رفع‌شده («چاپِ فاکتور کار نمی‌کند»): چکِ
# مجوزِ print-data باید بر اساسِ نوعِ سند باشد (COLD برایِ SALES_ORDER،
# HOT برایِ SALES_INVOICE)، نه همیشه HOT -- وگرنه کاربری که فقط دسترسیِ
# پخشِ سرد دارد هرگز نمی‌توانست سفارشِ پخشِ سردِ دیگری را چاپ کند.
from peecha.services import roles as roles_service
from peecha.services import users as users_service

cold_form_id = next(f.form_id for f in roles_service.list_forms() if f.code == "cold_distribution")
hot_form_id = next(f.form_id for f in roles_service.list_forms() if f.code == "commercial_distribution_hub")

rep_cold = users_service.create_user("repcold", "ویزیتورِ سرد", "secret123", None, lang_id, False, [company_id], company_id)
role_cold = roles_service.create_role(company_id, "COLD_VIEWER", None)
roles_service.set_role_permission(role_cold.role_id, cold_form_id, "VIEW", True)
roles_service.set_user_role(rep_cold.user_id, role_cold.role_id, company_id, True)

rep_hot = users_service.create_user("rephot", "ویزیتورِ گرم", "secret123", None, lang_id, False, [company_id], company_id)
role_hot = roles_service.create_role(company_id, "HOT_VIEWER", None)
roles_service.set_role_permission(role_hot.role_id, hot_form_id, "VIEW", True)
roles_service.set_user_role(rep_hot.user_id, role_hot.role_id, company_id, True)

token_cold = client.post("/auth/login", json={"username": "repcold", "password": "secret123"}).json()["access_token"]
H_cold = {"Authorization": f"Bearer {token_cold}"}
token_hot = client.post("/auth/login", json={"username": "rephot", "password": "secret123"}).json()["access_token"]
H_hot = {"Authorization": f"Bearer {token_hot}"}

check(client.get(f"/orders/{cold_doc}/print-data", headers=H_cold).status_code == 200,
      "کاربرِ فقط-پخشِ‌سرد می‌تواند سفارشِ پخشِ‌سردِ دیگری را چاپ کند (باگِ اصلی)")
check(client.get(f"/orders/{paid_doc}/print-data", headers=H_cold).status_code == 404,
      "همان کاربر نمی‌تواند فاکتورِ پخشِ‌گرم را چاپ کند (بدونِ مجوزِ HOT)")
check(client.get(f"/orders/{paid_doc}/print-data", headers=H_hot).status_code == 200,
      "کاربرِ فقط-پخشِ‌گرم می‌تواند فاکتورِ پخشِ‌گرمِ دیگری را چاپ کند")
check(client.get(f"/orders/{cold_doc}/print-data", headers=H_hot).status_code == 404,
      "همان کاربر نمی‌تواند سفارشِ پخشِ‌سرد را چاپ کند (بدونِ مجوزِ COLD)")

print("RESULT:", "ALL PASS" if not FAIL else "SOME FAILED")
sys.exit(1 if FAIL else 0)
