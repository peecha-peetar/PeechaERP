"""R379: قفل پرداخت فاکتور خرید با تطبیق سه‌طرفه: خاموش بی‌اثر، روشن مانع تسویه و پرداخت فاکتور دارای مغایرت (فی، بیش از رسید)،
خرید بدون سفارش و فاکتور سالم آزاد، حد مجاز، آزادسازی با مجوز و دلیل، کارتابل و ردپا؛ و فرم."""
import os, sys, datetime, decimal, io
os.environ["PEECHA_DB_NAME"] = "peecha_test_r379"
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


from peecha.services import commercial_settlements as settlements_service
from peecha.services import commercial_pos as pos_service
from peecha.services import treasury as treasury_service
from peecha.services import lot_tracking as lt
from peecha.services import operational_tasks as op_service
from peecha.services import inventory_residual as residual_service
from peecha.services import journal_entries as je_service
from peecha.db.models.accounting import JournalEntry, JournalEntryLine
from peecha.db.models.commercial import CommercialDocument
D = decimal.Decimal
TE = lt.TrackingEntry
today = datetime.date.today()
def raises(fn):
    try:
        fn()
    except ValueError:
        return True
    return False

k8 = A("32", "پرداختنی‌ها", "CREDIT", "LIABILITY", "PERMANENT", False, g4.account_id)
ap_gl = A("3201", "پرداختنی تامین‌کنندگان", "CREDIT", "LIABILITY", "PERMANENT", True, k8.account_id)
reval_gl = A("598", "تسعیر موجودی", "DEBIT", "EXPENSE", "TEMPORARY", True, k6.account_id)
engine_service.set_account_mapping(company_id, "SUPPLIER_PAYABLE", ap_gl.account_id)
engine_service.set_account_mapping(company_id, "INVENTORY_ADJUSTMENT_LOSS", adj_gl.account_id)
item_dim = dimensions_service.get_specialized_dimension_type_id(company_id, dimensions_service.INVENTORY_ITEM_CODE)
dimensions_service.set_account_dimension_types(inv_gl.account_id, company_id, [item_dim])

wh = locations_service.create_warehouse(company_id, "WH", "مرکزی", locations_service.WarehouseFields(is_default=True, allow_negative_stock=True))
customer = partners_service.create_customer(company_id, "C-1", "فروشگاه", fast_track=True)
s1 = dimensions_service.create_supplier(company_id, "S1", "تامین‌کنندهٔ یک")
pcs = catalog_service.create_uom(company_id, "PCS", "عدد", "COUNT", decimal_places=0)
plain = catalog_service.create_item(company_id, "N-1", "پارچه", catalog_service.ItemFields(item_kind_code="GOOD", base_uom_id=pcs))
csettings_service.set_feature_enabled(company_id, "PURCHASE_INVOICE_SKIP_APPROVAL", True)
HF = lambda cp: documents_service.DocumentHeaderFields(counterparty_detail_account_id=cp, currency_id=company.base_currency_id, warehouse_id=wh)

def doc_with_line(doc_type, item_id, qty, cp, price):
    doc = documents_service.create_document(company_id, user.user_id, doc_type, today, HF(cp))
    line = documents_service.add_line(doc, company_id, item_id, pcs, D(qty), D(qty), unit_price=D(price))
    return doc, line

def status(doc_id):
    return documents_service.get_document(doc_id, company_id)[0]


from peecha.services import purchase_reports as pr
import datetime as dt
D = decimal.Decimal
s2 = dimensions_service.create_supplier(company_id, "S2", "تامین‌کنندهٔ دو")
bolt = catalog_service.create_item(company_id, "B-1", "پیچ", catalog_service.ItemFields(item_kind_code="GOOD", base_uom_id=pcs, purchase_lead_time_days=5))
supplier_group_id = next(g.person_group_id for g in dimensions_service.list_person_groups(company_id) if g.code == "SUPPLIER")
treasury_service.create_counterparty_mapping(company_id, "PAYMENT", ap_gl.account_id, person_group_id=supplier_group_id)
treasury_service.set_account_mapping(company_id, "PAYMENT_CASH", cash_gl.account_id)

from peecha.services import three_way_lock as twl, users as users_service, roles as roles_service
from peecha.db.models.audit import ActivityLog
csettings_service.set_feature_enabled(company_id, "PURCHASE_ORDER_GOODS_RECEIPT", True)
csettings_service.set_feature_enabled(company_id, "PURCHASE_ORDER_SKIP_APPROVAL", True)


def post_invoice(d):
    documents_service.confirm_document(d, company_id, user.user_id)
    settlements_service.auto_approve_settlement_plan(d, company_id, user.user_id, [])
    documents_service.post_document(d, company_id, user.user_id)


po_lines = {}


def order(qty, price, received):
    po, line = doc_with_line("PURCHASE_ORDER", bolt, qty, s1, price)
    documents_service.confirm_document(po, company_id, user.user_id)
    documents_service.post_document(po, company_id, user.user_id)
    documents_service.set_warehouse_delivered_quantities(po, company_id, {line: D(received)})
    documents_service.approve_warehouse(po, company_id, user.user_id, warehouse_id=wh)
    po_lines[po] = line
    return po


def invoice_from(po, qty, price):
    inv = documents_service.convert_to_invoice(po, company_id, user.user_id, today)
    ln = documents_service.get_document(inv, company_id)[1][0]
    documents_service.update_line(ln.line_id, inv, company_id, D(qty), D(price))
    post_invoice(inv)
    return inv


inv_price = invoice_from(order(100, 100, 80), 80, 110)      # فی ۱۰٪ بیشتر از سفارش
inv_ok = invoice_from(order(30, 100, 30), 30, 100)          # سالم
po_over = order(50, 100, 40)
inv_first = invoice_from(po_over, 40, 100)
# فاکتور دوم دستی با ارجاع به همان ردیف سفارش: جمع فاکتورها بیش از رسید
inv_over = documents_service.create_document(company_id, user.user_id, "PURCHASE_INVOICE", today, HF(s1))
documents_service.add_line(inv_over, company_id, bolt, pcs, D(10), D(10), unit_price=D(100), source_line_id=po_lines[po_over])
post_invoice(inv_over)
direct, _ = doc_with_line("PURCHASE_INVOICE", bolt, 5, s1, 300)   # خرید بدون سفارش
post_invoice(direct)

pay = lambda inv, amount=1000: settlements_service.allocate_settlement(company_id, inv, None, today, D(amount), user.user_id)  # noqa: E731
sid = pay(inv_price)
check(sid and twl.block_reason(company_id, inv_price) is None, "switched off: payments work as before")
settlements_service.remove_settlement(sid, company_id)
issues = {i: [x.text for x in twl.invoice_issues(company_id, i)] for i in (inv_price, inv_ok, inv_over, direct)}
check(issues == {inv_price: ["اختلاف فی با سفارش"], inv_ok: [], inv_over: ["فاکتور بیش از رسید"], direct: []}, f"issues ({issues})")

engine_service.set_feature_enabled(company_id, twl.FEATURE, True)
def refused(fn, needle):
    try:
        fn()
    except ValueError as exc:
        return needle in str(exc)
    return False
check(refused(lambda: pay(inv_price), "تطبیق سه‌طرفه") and refused(lambda: pay(inv_over), "بیش از رسید"), "mismatched invoices cannot be paid")
check(pay(inv_ok) and pay(direct), "clean invoices and purchases without an order are paid")
twl.save_settings(company_id, user.user_id, D(10), D(0))
check(twl.block_reason(company_id, inv_price) is None and twl.block_reason(company_id, inv_over), "a 10% price tolerance frees the price gap only")
twl.save_settings(company_id, user.user_id, D(5), D(30))
check(twl.block_reason(company_id, inv_price) and twl.block_reason(company_id, inv_over) is None, "quantity tolerance")
twl.save_settings(company_id, user.user_id, D(5), D(0))

staff = users_service.create_user("staff", "کارشناس", "secret123", None, lang_id, False, [company_id], company_id).user_id
check(refused(lambda: twl.release(company_id, staff, inv_over, "تایید شفاهی"), "مدیر") and not twl.can_release(company_id, staff),
      "release needs the right")
check(refused(lambda: twl.release(company_id, user.user_id, inv_over, " "), "دلیل"), "release needs a reason")
twl.release(company_id, user.user_id, inv_over, "کسری رسید در انبار دوم ثبت می‌شود")
check(pay(inv_over, 500) and refused(lambda: twl.release(company_id, user.user_id, inv_over, "x"), "قبلاً"), "released once, then paid")
with new_session() as s_:
    logged = s_.scalar(select(ActivityLog).where(ActivityLog.entity_id == inv_over, ActivityLog.action == "APPROVE")
                       .order_by(ActivityLog.log_id.desc()).limit(1))
check(logged is not None and logged.changes.get("operation") == "THREE_WAY_RELEASE", "the release is audited")
check({r.document_id for r in twl.list_invoices(company_id)} == {inv_price, inv_first}
      and len(twl.list_invoices(company_id, include_released=True)) == 3,
      "blocked and released lists (every unpaid invoice of a mismatched order line stays blocked)")
kinds = lambda u: [t.kind for t in op_service.list_operational_tasks(company_id, u)]  # noqa: E731
check("PUR_THREE_WAY" in kinds(user.user_id) and "PUR_THREE_WAY" not in kinds(staff), "in the approver's inbox only")

from peecha.ui.screens.purchase_three_way_lock import PurchaseThreeWayLockScreen
from PySide6.QtWidgets import QPushButton
screen = PurchaseThreeWayLockScreen()
screen.refresh()
check(screen.table.rowCount() == 2 and "روشن" in screen.state_label.text() and screen.price_field.text() == "۵", "the form lists blocked invoices")
from PySide6.QtCore import Qt
screen.table.setCurrentCell(next(i for i in range(2) if screen.table.item(i, 0).data(Qt.UserRole) == inv_price), 0)
screen.ask_reason = lambda: "قیمت جدید با تامین‌کننده توافق شده"
check(screen.release() and screen.table.rowCount() == 1 and pay(inv_price, 100), "released from the form")
screen.released_box.setChecked(True)
check(screen.table.rowCount() == 3 and sorted(screen.table.item(i, 5).text() for i in range(3)) == ["آزاد", "آزاد", "بسته"],
      "released ones on request")
screen.price_field.setText("۱۰۰")
check(not screen.save_settings() and "۱۰۰" in screen.status_label.text(), "tolerance range is checked")
check(all(len(b.text()) <= 2 for b in screen.findChildren(QPushButton) if b.text()), "icon buttons only")

print("RESULT:", "ALL PASS" if not FAIL else "SOME FAILED")
sys.exit(1 if FAIL else 0)
