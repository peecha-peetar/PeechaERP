"""Shared setup for R313 budgeting tests (on top of prd_fixture). Import after setting PEECHA_DB_NAME."""
import datetime

from prd_fixture import *  # noqa: F401,F403
import prd_fixture as _p

from peecha.services import commercial_documents as docs
from peecha.services import commercial_settings as csettings
from peecha.services import commercial_settlements as settlements
from peecha.services import purchase_requests as prs
from peecha.services import currencies as currencies_service
from peecha.services import stock_controls as sc
from peecha.services.budgeting import approval as bap
from peecha.services.budgeting import budgets as bud
from peecha.services.budgeting import common as bc
from peecha.services.budgeting import control as bctl
from peecha.services.budgeting import exceptions as bex
from peecha.services.budgeting import ledger as bl
from peecha.db.models.accounting import FiscalYear

check, raises, D = _p.check, _p.raises, _p.D
company_id, uid, today = _p.company_id, _p.uid, _p.today

csettings.set_feature_enabled(company_id, "PURCHASE_INVOICE_SKIP_APPROVAL", True)
csettings.set_feature_enabled(company_id, "PURCHASE_ORDER_SKIP_APPROVAL", True)
csettings.set_feature_enabled(company_id, "ALLOW_EDIT_POSTED_INVOICE", True)

k_ex = _p.A("61", "هزینه‌های اداری", "DEBIT", "EXPENSE", "TEMPORARY", False, _p.g3.account_id)
office_gl = _p.A("6101", "هزینهٔ ملزومات اداری", "DEBIT", "EXPENSE", "TEMPORARY", True, k_ex.account_id)
k_cash = _p.A("11", "موجودی نقد", "DEBIT", "ASSET", "PERMANENT", False, _p.g1.account_id)
cash_gl = _p.A("111", "صندوق", "DEBIT", "ASSET", "PERMANENT", True, k_cash.account_id)

cc_type = _p.dimensions_service.get_specialized_dimension_type_id(company_id, _p.dimensions_service.COST_CENTER_CODE)
pj_type = _p.dimensions_service.get_specialized_dimension_type_id(company_id, _p.dimensions_service.PROJECT_CODE)
cc_a = _p.dimensions_service.create_detail_account(company_id, cc_type, "CC-A", "واحد تولید").detail_account_id
cc_b = _p.dimensions_service.create_detail_account(company_id, cc_type, "CC-B", "واحد اداری").detail_account_id
pj_1 = _p.dimensions_service.create_detail_account(company_id, pj_type, "PJ-1", "پروژهٔ توسعه").detail_account_id
cat_raw = _p.catalog_service.create_category(company_id, "RAW", "مواد اولیه")
mat = _p.item("RM-B", "مادهٔ بودجه‌ای", category_id=cat_raw)
other = _p.item("RM-C", "قطعهٔ متفرقه")

with _p.new_session() as _s:
    fy = _s.scalar(_p.select(FiscalYear).where(FiscalYear.company_id == company_id))
    fy_id, fy_start, fy_end = fy.fiscal_year_id, fy.start_date, fy.end_date

usd = next(cur.currency_id for cur in currencies_service.list_all_currencies() if cur.iso_code == "USD")
currencies_service.set_company_currency(company_id, usd, True)


def toggle(code, on=True):
    _p.engine_service.set_feature_enabled(company_id, code, on)


def header(cc=None, pj=None, currency=None, rate=D(1)):
    return docs.DocumentHeaderFields(counterparty_detail_account_id=_p.supplier, currency_id=currency or _p.company.base_currency_id,
                                     warehouse_id=_p.wh_rm, cost_center_detail_account_id=cc, project_detail_account_id=pj,
                                     exchange_rate=rate)


def make_doc(doc_type, lines, cc=None, pj=None, date=None, currency=None, rate=D(1)):
    d = docs.create_document(company_id, uid, doc_type, date or today, header(cc, pj, currency, rate))
    for item_id, qty, price in lines:
        docs.add_line(d, company_id, item_id, _p.base_uom(item_id), D(qty), D(qty), unit_price=D(price))
    return d


def confirm(d, user=None):
    docs.confirm_document(d, company_id, user or uid)


def post(d, user=None):
    doc, _lines = docs.get_document(d, company_id)
    if doc.document_type_code in ("PURCHASE_INVOICE",):
        settlements.auto_approve_settlement_plan(d, company_id, user or uid, [])
    docs.post_document(d, company_id, user or uid)


def po(lines, **kw):
    d = make_doc("PURCHASE_ORDER", lines, **kw)
    confirm(d)
    return d


def invoice_from(order, qty=None, price=None):
    inv = docs.convert_to_invoice(order, company_id, uid, today)
    ln = docs.get_document(inv, company_id)[1][0]
    if qty is not None or price is not None:
        docs.update_line(ln.line_id, inv, company_id, D(qty if qty is not None else ln.quantity),
                         D(price if price is not None else ln.unit_price))
    return inv


def status(d):
    return docs.get_document(d, company_id)[0].status_code


def make_budget(lines, code="B1", period_type="MONTH", publish=True):
    """lines: [(Dims, amount)] — همهٔ گام‌ها با مدیر سیستم (کلید خودتأییدی برای این ساخت روشن و بعد خاموش)."""
    toggle(sc.BUD_SELF_APPROVAL, True)
    bid = bud.create_budget(company_id, uid, fy_id, code, "بودجهٔ " + code, period_type)
    vid = bud.list_budgets(company_id)[0].open_version_id
    vid = next(b.open_version_id for b in bud.list_budgets(company_id) if b.budget_id == bid)
    line_ids = [bud.add_line(company_id, uid, vid, dims, amount) for dims, amount in lines]
    if publish:
        bap.submit(company_id, uid, vid)
        bap.review(company_id, uid, vid)
        bap.approve(company_id, uid, vid)
        bap.publish(company_id, uid, vid)
    toggle(sc.BUD_SELF_APPROVAL, False)
    return bid, vid, line_ids


def key_of(line_id):
    from peecha.db.models.budgeting import BudgetLine
    with _p.new_session() as s:
        return s.get(BudgetLine, line_id).key_id


def totals(line_id):
    with _p.new_session() as s:
        t = bl.key_totals(s, [key_of(line_id)])[key_of(line_id)]
    return dict(t)


def P(**kw):
    return bud.Dims("PURCHASE", **kw)


def entries(doc_id):
    from peecha.db.models.budgeting import ConsumptionEntry
    with _p.new_session() as s:
        return list(s.scalars(_p.select(ConsumptionEntry).where(ConsumptionEntry.source_document_id == doc_id)
                              .order_by(ConsumptionEntry.entry_id)))


def finish():
    _p.finish()
