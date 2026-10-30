import os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r282"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crm_fixture import *  # noqa: F401,F403
import crm_fixture as fx
from peecha.services.crm import leads, opportunities as opps, opportunity_sales as osales, customer360 as c360, pipelines as pl
from peecha.db.models.commercial import CommercialDocument, CommercialDocumentLine
check = fx.check

st = {s.code: s.stage_id for s in pl.list_stages(company_id)}
OF, LF = opps.OpportunityFields, opps.LineFields

# ===== سرنخ → فرصت → پیش‌فاکتور (سرویس فروش موجود) =====
lead = leads.create_lead(company_id, uid, leads.LeadFields("خریدار تازه", mobile="09130000001", estimated_value=D(5_000_000)))
check(fx.raises(lambda: osales.create_sales_document(company_id, uid, opps.create_opportunity(
    company_id, uid, OF("فرصت سرنخ", lead_id=lead)), "SALES_PROFORMA"), "مشتری"), "no sales document before lead becomes customer")
customer_id, opp = leads.convert_lead(company_id, uid, lead, opportunity_title="قرارداد سالانه")
check(fx.raises(lambda: osales.create_sales_document(company_id, uid, opp), "اقلام"), "sales document needs item lines")
opps.update_opportunity(company_id, uid, opp, OF("قرارداد سالانه", customer_detail_account_id=customer_id, amount=D(0),
                                                    expected_close_date=today + datetime.timedelta(days=10)))
opps.set_lines(company_id, uid, opp, [LF(item_a, D(4), D(250_000)), LF(item_b, D(2), D(100_000), D(20_000)),
                                      LF(None, D(1), D(50_000), description="خدمات نصب")])
proforma = osales.create_sales_document(company_id, uid, opp, "SALES_PROFORMA")
with new_session() as s:
    doc = s.get(CommercialDocument, proforma)
    lines = list(s.scalars(select(CommercialDocumentLine).where(CommercialDocumentLine.document_id == proforma)))
check(doc.document_type_code == "SALES_PROFORMA" and doc.counterparty_detail_account_id == customer_id and doc.status_code == "DRAFT"
      and doc.warehouse_id == warehouse_id, "proforma created by commercial_documents for the customer")
check(len(lines) == 2 and sorted(l.quantity for l in lines) == [D(2), D(4)], "only item lines copied (service line stays in CRM)")
check(doc.total_amount == D(1_180_000), f"amounts computed by ERP (4×250k + 2×100k − 20k) ({doc.total_amount})")
o = opps.get_opportunity(company_id, opp)
check(o.stage_id == st["PROPOSAL"] and proforma in o.document_ids, "proforma links document and advances to proposal")

# ===== سفارش → برنده؛ تبدیل به فاکتور و دریافت فقط با سرویس‌های موجود =====
order = osales.create_sales_document(company_id, uid, opp, "SALES_ORDER")
o = opps.get_opportunity(company_id, opp)
check(o.status_code == "WON", "sales order marks opportunity won")
check(fx.raises(lambda: opps.delete_opportunity(company_id, uid, opp), "سند فروش"), "opportunity with documents cannot be deleted")
documents_service.confirm_document(order, company_id, uid)
documents_service.approve_document(order, company_id, uid)
invoice_id = documents_service.convert_to_invoice(order, company_id, uid, today)
documents_service.confirm_document(invoice_id, company_id, uid)
settlements_service.auto_approve_full_cash_settlement_plan(invoice_id, company_id, uid)
documents_service.post_document(invoice_id, company_id, uid)
chain = osales.sales_chain(company_id, opp)
types = [d["document_type_code"] for d in chain]
check(types.count("SALES_INVOICE") == 1 and "SALES_ORDER" in types and "SALES_PROFORMA" in types, f"sales chain follows conversion ({types})")
inv = next(d for d in chain if d["document_type_code"] == "SALES_INVOICE")
check(inv["remaining_amount"] == inv["total_amount"] and not inv["paid"], "invoice remaining from settlements")
jid = fx.receipt(customer_id, inv["total_amount"])
settlements_service.allocate_settlement(company_id, invoice_id, None, today, inv["total_amount"], uid)
inv = next(d for d in osales.sales_chain(company_id, opp) if d["document_type_code"] == "SALES_INVOICE")
check(inv["paid"] and inv["remaining_amount"] == 0, "payment closes the chain")
v = c360.customer_360(company_id, customer_id)
check(v["sales"]["invoice_count"] == 1 and v["financial"]["balance"] == 0, "customer 360 sees the sale and payment from ERP")
check(osales.documents_for_customer_lookup(company_id, invoice_id) == opp, "invoice traces back to its opportunity")

# ===== هم‌گام‌سازی برنده از سفارش ثبت‌شده در فرم فروش =====
opp2 = opps.create_opportunity(company_id, uid, OF("فرصت دوم", customer_detail_account_id=cust_a, amount=D(1_000_000),
                                                    expected_close_date=today))
opps.set_lines(company_id, uid, opp2, [LF(item_a, D(1), D(1_000_000))])
pf2 = osales.create_sales_document(company_id, uid, opp2, "SALES_PROFORMA")
check(opps.get_opportunity(company_id, opp2).status_code == "OPEN", "proforma alone keeps opportunity open")
documents_service.confirm_document(pf2, company_id, uid)
inv2 = documents_service.convert_to_invoice(pf2, company_id, uid, today)
documents_service.confirm_document(inv2, company_id, uid)
settlements_service.auto_approve_full_cash_settlement_plan(inv2, company_id, uid)
documents_service.post_document(inv2, company_id, uid)
check(osales.sync_won_from_sales(company_id) == [opp2] and opps.get_opportunity(company_id, opp2).status_code == "WON",
      "posted invoice converted from proforma marks opportunity won")
draft = osales.create_customer_document(company_id, uid, cust_b)
with new_session() as s:
    d = s.get(CommercialDocument, draft)
check(d.document_type_code == "SALES_ORDER" and d.counterparty_detail_account_id == cust_b and d.status_code == "DRAFT",
      "quick order from customer 360 is a normal draft sales order")

# ===== API =====
from fastapi.testclient import TestClient
from peecha_api.main import app
client = TestClient(app)
auth = {"Authorization": "Bearer " + client.post("/auth/login", json={"username": "admin", "password": "secret123"}).json()["access_token"]}
opp3 = opps.create_opportunity(company_id, uid, OF("فرصت API", customer_detail_account_id=cust_b, amount=D(0), expected_close_date=today))
r = client.put(f"/crm/opportunities/{opp3}/lines", json=[{"item_id": item_b, "quantity": "3", "unit_price": "90000"}], headers=auth)
check(r.status_code == 200 and r.json()["amount"] == "270000.00", "lines via API")
r = client.post(f"/crm/opportunities/{opp3}/documents", json={"document_type_code": "SALES_ORDER"}, headers=auth)
check(r.status_code == 200 and r.json()["document_id"], "sales order from opportunity via API")
ch = client.get(f"/crm/opportunities/{opp3}/sales-chain", headers=auth)
check(ch.status_code == 200 and ch.json()[0]["document_type_code"] == "SALES_ORDER", "sales chain via API")
r = client.post(f"/crm/customers/{cust_a}/orders", headers=auth)
check(r.status_code == 200 and r.json()["document_id"], "draft order for customer via API")

# ===== رابط دسکتاپ =====
from PySide6.QtWidgets import QApplication, QMessageBox
app_qt = QApplication.instance() or QApplication([])
QMessageBox.warning = staticmethod(lambda *a, **k: print("WARN", a[2] if len(a) > 2 else a))
QMessageBox.information = staticmethod(lambda *a, **k: None)
from peecha.ui.screens import crm as ui


class FakeMain:
    def __init__(self):
        self.opened = []

    def open_screen(self, code, then=None):
        class S:
            def edit_document(self_inner, doc_id):
                self.opened.append((code, doc_id))

            def preselect_counterparty(self_inner, cid):
                self.opened.append((code, cid))
        if then:
            then(S())


main = FakeMain()
pipe = ui.PipelineScreen(main)
pipe.dialog_runner = lambda dlg: True
pipe.refresh()
opp4 = opps.create_opportunity(company_id, uid, OF("فرصت دسکتاپ", customer_detail_account_id=cust_a, amount=D(0), expected_close_date=today))
opps.set_lines(company_id, uid, opp4, [LF(item_a, D(2), D(300_000))])
pipe.reload()
pipe.select(opp4)
doc4 = pipe.issue_proforma()
check(doc4 and main.opened[-1] == ("SALES_PROFORMA", doc4), "kanban issues proforma and opens it in the sales form")
pipe.select(opp4)
check(len(pipe.show_chain()) == 1, "chain dialog lists documents")
scr = ui.Customer360Screen(main)
scr.dialog_runner = lambda dlg: True
scr.refresh()
scr.load_customer(cust_a)
new_doc = scr.new_order()
check(new_doc and main.opened[-1] == ("SALES_ORDER", new_doc), "360 quick order opens a draft sales order")
scr.open_erp("TREASURY_RECEIPT")
check(main.opened[-1] == ("TREASURY_RECEIPT", cust_a), "360 quick payment opens receipt with customer preselected")

fx.finish()
