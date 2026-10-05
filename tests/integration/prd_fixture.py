"""Shared setup for production (prd) integration tests. Import after setting PEECHA_DB_NAME."""
import datetime, decimal, os, sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))
os.environ.setdefault("PEECHA_DB_USER", "peecha")
os.environ.setdefault("PEECHA_DB_PASSWORD", "peecha")
os.environ.setdefault("PEECHA_DB_HOST", "localhost")
os.environ.setdefault("PEECHA_DB_PORT", "5432")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

D = decimal.Decimal
FAIL = False


def check(cond, msg):
    global FAIL
    if not cond:
        FAIL = True
        print("FAIL:", msg)
    else:
        print("OK:", msg)


def raises(fn, needle=""):
    try:
        fn()
    except ValueError as e:
        return needle in str(e)
    return False


def finish():
    print("ALL PASS" if not FAIL else "SOME FAILED")


from peecha.db.schema_bootstrap import apply_pending_schema_files
from peecha.db.base import get_engine, new_session

apply_pending_schema_files(get_engine())
from sqlalchemy import select, func, text
from peecha.services.bootstrap import bootstrap_system
from peecha import session as sess
from peecha.db.models.security import UserCompany
from peecha.db.models.core import Company

user = bootstrap_system("admin", "مدیر سیستم", "secret123", "شرکت تولیدی")
sess.current_user = user
with new_session() as s:
    uc = s.scalar(select(UserCompany).where(UserCompany.user_id == user.user_id))
    company = s.get(Company, uc.company_id)
company_id = company.company_id
sess.current_company = company
uid = user.user_id
today = datetime.date.today()

from peecha.services import fiscal_years as fiscal_years_service
from peecha.services import chart_of_accounts as coa_service
from peecha.services import inventory_catalog as catalog_service
from peecha.services import inventory_locations as locations_service
from peecha.services import inventory_engine as engine_service
from peecha.services import inventory_documents as inv_documents_service
from peecha.services import detail_dimensions as dimensions_service

fiscal_years_service.create_fiscal_year_for_date(company_id, 1, 1, today)
lang_id = company.default_language_id
A = lambda code, name, nature, typ, perm, post, parent=None: coa_service.create_account(
    company_id, code, name, nature, typ, perm, post, lang_id, parent_account_id=parent)
g1 = A("1", "دارایی‌ها", "DEBIT", "ASSET", "PERMANENT", False)
k3 = A("12", "موجودی‌ها", "DEBIT", "ASSET", "PERMANENT", False, g1.account_id)
inv_gl = A("121", "موجودیِ کالا", "DEBIT", "ASSET", "PERMANENT", True, k3.account_id)
wip_gl = A("122", "کالایِ در جریانِ ساخت", "DEBIT", "ASSET", "PERMANENT", True, k3.account_id)
g4 = A("2", "بدهی‌ها", "CREDIT", "LIABILITY", "PERMANENT", False)
k7 = A("21", "پرداختنی‌ها", "CREDIT", "LIABILITY", "PERMANENT", False, g4.account_id)
ap_gl = A("211", "پرداختنیِ تامین‌کنندگان", "CREDIT", "LIABILITY", "PERMANENT", True, k7.account_id)
g3 = A("5", "هزینه‌ها", "DEBIT", "EXPENSE", "TEMPORARY", False)
k5 = A("51", "بهایِ تمام‌شده", "DEBIT", "EXPENSE", "TEMPORARY", False, g3.account_id)
cogs_gl = A("511", "بهایِ تمام‌شده", "DEBIT", "EXPENSE", "TEMPORARY", True, k5.account_id)
k6 = A("52", "هزینه‌هایِ تولید", "DEBIT", "EXPENSE", "TEMPORARY", False, g3.account_id)
labor_gl = A("521", "دستمزدِ جذب‌شده", "DEBIT", "EXPENSE", "TEMPORARY", True, k6.account_id)
machine_gl = A("522", "ماشینِ جذب‌شده", "DEBIT", "EXPENSE", "TEMPORARY", True, k6.account_id)
overhead_gl = A("523", "سربارِ جذب‌شده", "DEBIT", "EXPENSE", "TEMPORARY", True, k6.account_id)
variance_gl = A("524", "انحرافِ تولید", "DEBIT", "EXPENSE", "TEMPORARY", True, k6.account_id)
scrap_gl = A("525", "زیانِ ضایعات", "DEBIT", "EXPENSE", "TEMPORARY", True, k6.account_id)
adj_gl = A("599", "اصلاحِ موجودی", "DEBIT", "EXPENSE", "TEMPORARY", True, k6.account_id)
for key, acc in (("INVENTORY_ASSET", inv_gl), ("COGS", cogs_gl), ("INVENTORY_ADJUSTMENT_GAIN", adj_gl),
                 ("INVENTORY_ADJUSTMENT_LOSS", adj_gl), ("SUPPLIER_PAYABLE", ap_gl), ("INVENTORY_COST_VARIANCE", variance_gl),
                 ("PRODUCTION_WIP", wip_gl), ("PRODUCTION_LABOR_APPLIED", labor_gl),
                 ("PRODUCTION_MACHINE_APPLIED", machine_gl), ("PRODUCTION_OVERHEAD_APPLIED", overhead_gl),
                 ("PRODUCTION_VARIANCE", variance_gl), ("PRODUCTION_SCRAP_LOSS", scrap_gl)):
    engine_service.set_account_mapping(company_id, key, acc.account_id)

pcs = catalog_service.create_uom(company_id, "PCS", "عدد", "COUNT", decimal_places=0)
kg = catalog_service.create_uom(company_id, "KG", "کیلوگرم", "WEIGHT", decimal_places=3)
supplier = dimensions_service.create_supplier(company_id, "S1", "تامین‌کنندهٔ مواد")

WF = locations_service.WarehouseFields
wh_rm = locations_service.create_warehouse(company_id, "RM", "انبارِ مواد", WF(is_default=True))
wh_line = locations_service.create_warehouse(company_id, "LINE", "خطِ تولید", WF())
wh_fg = locations_service.create_warehouse(company_id, "FG", "انبارِ محصول", WF())
wh_scrap = locations_service.create_warehouse(company_id, "SCR", "انبارِ ضایعات", WF())


def item(code, name, kind="RAW_MATERIAL", uom=None, **kw):
    return catalog_service.create_item(company_id, code, name, catalog_service.ItemFields(
        item_kind_code=kind, base_uom_id=uom or pcs, **kw))


fg = item("FG-A", "محصولِ A", "FINISHED_GOOD")
semi = item("SF-1", "نیمه‌ساختهٔ ۱", "SEMI_FINISHED")
r1 = item("RM-1", "مادهٔ اولیهٔ ۱", uom=kg)
r2 = item("RM-2", "مادهٔ اولیهٔ ۲", uom=kg)
r3 = item("RM-3", "مادهٔ اولیهٔ ۳", uom=kg)
pk = item("PK-1", "کارتن")
byp = item("BY-1", "محصولِ جانبی", "GOOD")
scrap_item = item("SC-1", "ضایعاتِ قابلِ فروش", "GOOD", uom=kg)


def base_uom(item_id):
    from peecha.db.models.inventory import Item
    with new_session() as s:
        return s.get(Item, item_id).base_uom_id


def receive(item_id, qty, cost, wh=None, uom=None, date=None):
    uom = uom or base_uom(item_id)
    doc = inv_documents_service.create_stock_document(
        company_id, uid, "RECEIPT", date or today,
        inv_documents_service.DocumentHeaderFields(destination_warehouse_id=wh or wh_rm, counterparty_detail_account_id=supplier))
    inv_documents_service.add_line(doc, company_id, inv_documents_service.LineFields(
        item_id=item_id, uom_id=uom, quantity=D(qty), quantity_base=D(qty), unit_cost=D(cost)))
    inv_documents_service.confirm_stock_document(doc, company_id)
    inv_documents_service.post_stock_document(doc, company_id, uid)
    return doc


def on_hand(item_id, wh):
    from peecha.db.models.inventory import StockBalance
    with new_session() as s:
        return D(s.scalar(select(func.coalesce(func.sum(StockBalance.quantity_on_hand), 0)).where(
            StockBalance.item_id == item_id, StockBalance.warehouse_id == wh)) or 0)


def gl_balance(account_id):
    from peecha.db.models.accounting import JournalEntryLine
    with new_session() as s:
        d, c_ = s.execute(select(func.coalesce(func.sum(JournalEntryLine.debit_amount_base), 0), func.coalesce(func.sum(JournalEntryLine.credit_amount_base), 0))
                          .where(JournalEntryLine.account_id == account_id)).one()
        return D(d) - D(c_)
