"""R345: پورسانت فروشنده هنگام ثبت فاکتور فروش: درصد فروش، درصد سود (فروش خالص منهای بهای کالا، نه کل فروش)، و مبلغ
ثابت هر واحد."""
import os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r345_commission"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prd_fixture import *  # noqa: F401,F403

from peecha.db.models.commercial import CommissionEntry
from peecha.services import commercial_contracts as contracts, commercial_documents as docs, commercial_partners as partners, \
    commercial_settings as csettings, commercial_settlements as settlements

k13 = A("13", "دریافتنی‌ها", "DEBIT", "ASSET", "PERMANENT", False, g1.account_id)
ar_gl = A("131", "دریافتنی مشتریان", "DEBIT", "ASSET", "PERMANENT", True, k13.account_id)
g_rev = A("4", "درآمدها", "CREDIT", "REVENUE", "TEMPORARY", False)
k41 = A("41", "درآمد عملیاتی", "CREDIT", "REVENUE", "TEMPORARY", False, g_rev.account_id)
rev_gl = A("411", "فروش", "CREDIT", "REVENUE", "TEMPORARY", True, k41.account_id)
disc_gl = A("412", "تخفیف فروش", "DEBIT", "REVENUE", "TEMPORARY", True, k41.account_id)
tax_gl = A("212", "مالیات ارزش‌افزودهٔ فروش", "CREDIT", "LIABILITY", "PERMANENT", True, k7.account_id)
engine_service.set_account_mapping(company_id, "CUSTOMER_RECEIVABLE", ar_gl.account_id)
csettings.set_account_mapping(company_id, "SALES_REVENUE", rev_gl.account_id)
csettings.set_account_mapping(company_id, "SALES_DISCOUNT", disc_gl.account_id)
csettings.set_account_mapping(company_id, "SALES_TAX_PAYABLE", tax_gl.account_id)

customer = partners.create_customer(company_id, "C1", "فروشگاه", fast_track=True)
rules = {
    "total": contracts.create_commission_rule(company_id, "T", "دو درصد فروش", "PERCENT_OF_TOTAL", D(2)),
    "margin": contracts.create_commission_rule(company_id, "M", "ده درصد سود", "PERCENT_OF_MARGIN", D(10)),
    "flat": contracts.create_commission_rule(company_id, "F", "ثابت هر واحد", "FLAT_PER_UNIT", D(50_000)),
}
reps = {}
for code, rule in rules.items():
    rep = partners.create_customer(company_id, f"REP-{code}", f"بازاریاب {code}", fast_track=True)
    partners.create_sales_representative(rep, rule)
    reps[code] = rep

receive(byp, 100, 600_000)  # بهای هر واحد ۶۰۰ هزار


def invoice(rep, qty=10, price=1_000_000, doc_type="SALES_INVOICE"):
    d = docs.create_document(company_id, uid, doc_type, today, docs.DocumentHeaderFields(
        counterparty_detail_account_id=customer, currency_id=company.base_currency_id, warehouse_id=wh_rm,
        sales_rep_detail_account_id=rep))
    docs.add_line(d, company_id, byp, pcs, D(qty), D(qty), unit_price=D(price))
    docs.confirm_document(d, company_id, uid)
    settlements.auto_approve_settlement_plan(d, company_id, uid, [])
    docs.post_document(d, company_id, uid)
    return d


def entries(rep):
    with new_session() as s:
        return [(e.base_amount, e.commission_amount, getattr(e, "status_code", None) or getattr(e, "status", None))
                for e in s.scalars(select(CommissionEntry).where(CommissionEntry.rep_detail_account_id == rep))]


inv_total = invoice(reps["total"])
invoice(reps["margin"])
invoice(reps["flat"])
check([(b, c) for b, c, _ in entries(reps["total"])] == [(D(10_000_000), D(200_000))], f"2% of sales ({entries(reps['total'])})")
check([(b, c) for b, c, _ in entries(reps["margin"])] == [(D(4_000_000), D(400_000))],
      f"10% of the margin: 10M sales − 6M cost = 4M ({entries(reps['margin'])})")
check([c for _, c, _ in entries(reps["flat"])] == [D(500_000)], "a flat amount per unit sold")

finish()
