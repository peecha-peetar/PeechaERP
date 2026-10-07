import os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r288"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crm_fixture import *  # noqa: F401,F403
import crm_fixture as fx
from peecha.db.models.commercial import CommercialDocument
from peecha.services.crm import (activities as acts, analytics, automation as auto, campaigns as camps, common as cc,
                                 customer360 as c360, leads, opportunities as opps, opportunity_sales as osales, pipelines as pl,
                                 reports as rpt, segments as seg, tickets as tk)
from peecha.services.purchase_reports import PurchaseFilters
check = fx.check
OF, LF = opps.OpportunityFields, opps.LineFields
month_start = today.replace(day=1)

# ===== ماتریس یکپارچگی: کمپین ← سرنخ ← مشتری ← فرصت ← پیش‌فاکتور ← سفارش ← فاکتور ← دریافت ← ۳۶۰ ← تحلیل ← اتوماسیون =====
analytics.refresh_scores(company_id)
camp = camps.create_campaign(company_id, uid, camps.CampaignFields("نمایشگاه", "EVENT", start_date=month_start, actual_cost=D(1_000_000)))
lead = leads.create_lead(company_id, uid, leads.LeadFields("خریدار نمایشگاه", company_name="فروشگاه ج", mobile="09137770000",
                                                         estimated_value=D(3_000_000)), campaign_id=camp)
customer, opp = leads.convert_lead(company_id, uid, lead, opportunity_title="قرارداد نمایشگاه")
check(opps.get_opportunity(company_id, opp).customer_detail_account_id == customer, "lead → customer → opportunity")
opps.set_lines(company_id, uid, opp, [LF(item_a, D(3), D(1_000_000))])
proforma = osales.create_sales_document(company_id, uid, opp, "SALES_PROFORMA")
order = osales.create_sales_document(company_id, uid, opp, "SALES_ORDER")
check(opps.get_opportunity(company_id, opp).status_code == "WON", "order marks opportunity won")
documents_service.confirm_document(order, company_id, uid)
documents_service.approve_document(order, company_id, uid)
invoice = documents_service.convert_to_invoice(order, company_id, uid, today)
documents_service.confirm_document(invoice, company_id, uid)
settlements_service.auto_approve_full_cash_settlement_plan(invoice, company_id, uid)
documents_service.post_document(invoice, company_id, uid)
with new_session() as s:
    inv_total = s.get(CommercialDocument, invoice).total_amount
fx.receipt(customer, inv_total)
chain = osales.sales_chain(company_id, opp)
check([d["document_type_code"] for d in chain] == ["SALES_PROFORMA", "SALES_ORDER", "SALES_INVOICE"], "sales chain proforma→order→invoice")
d360 = c360.customer_360(company_id, customer)
check(d360["sales"]["invoice_count"] == 1 and d360["financial"]["balance"] == 0, "360 reads posted invoice and receipt from ERP")
check({"INVOICE", "ORDER", "PAYMENT"} <= {e.kind for e in c360.timeline(company_id, customer)}, "timeline has invoice, order and payment")
a = camps.campaign_analytics(company_id, camp)
check(a["revenue"] == D(3_000_000) and a["opportunities_won"] == 1 and a["roi_percent"] == D("200.0"), "campaign ROI from real sales")
t = tk.create_ticket(company_id, uid, tk.TicketFields(customer, "تأخیر ارسال", "COMPLAINT", "HIGH"))
tk.add_reply(company_id, uid, t, "پیگیری شد", "CALL")
tk.resolve_ticket(company_id, uid, t, "ارسال شد")
tk.rate_ticket(company_id, uid, t, 5)
analytics.refresh_scores(company_id)
check(analytics.get_score(company_id, customer).invoice_count_total == 1, "analytics include new customer")
rule = auto.save_rule(company_id, uid, name="خریدار", trigger_code="SEGMENT_MEMBER",
                      conditions={"segment_id": seg.save_segment(company_id, uid, code="NEWB", name="خریدار تازه",
                                                                 rule={"all": [{"field": "invoice_count_total", "op": ">=", "value": 1}]})},
                      action_code="CREATE_ACTIVITY", action_params={"activity_type": "CALL", "subject": "تشکر از {name}", "due_in_days": 2})
check(auto.run_rule(company_id, rule) == 1, "automation acts on segment built from ERP sales")
fx.invoice(cust_a, 2_000_000, due_date=today + datetime.timedelta(days=30))
opps.create_opportunity(company_id, uid, OF("فرصت ماه بعد", customer_detail_account_id=cust_b, amount=D(10_000_000),
                                            expected_close_date=today + datetime.timedelta(days=35)))
lost = opps.create_opportunity(company_id, uid, OF("فرصت ازدست‌رفته", customer_detail_account_id=cust_b, amount=D(4_000_000)))
st = {s.code: s.stage_id for s in pl.list_stages(company_id)}
opps.move_stage(company_id, uid, lost, st["LOST"], lost_reason="قیمت بالا")
acts.create_activity(company_id, uid, acts.ActivityFields("FOLLOW_UP", "پیگیری دیروز", customer_detail_account_id=cust_a,
                                                          due_date=today - datetime.timedelta(days=1)))

# ===== داشبورد =====
d = rpt.dashboard(company_id, month_start, today)
check(d["new_leads"] == 1 and d["converted_leads"] == 1 and d["lead_conversion"] == D("100.0"), "dashboard leads")
check(d["won"] == 1 and d["won_amount"] == D(3_000_000) and d["lost"] == 1 and d["win_rate"] == D("50.0"), "dashboard won/lost")
check(d["pipeline_amount"] == D(10_000_000) and d["weighted_pipeline"] == D(1_000_000), f"pipeline and weighted ({d['weighted_pipeline']})")
check(d["sales"] == D(5_000_000) and d["buyers"] == 2, "dashboard sales from posted invoices")
check(d["overdue_activities"] >= 1 and d["csat"] == D("5.0"), "activities and CSAT")
check(rpt.dashboard(company_id, month_start, today, visitor.user_id)["won"] == 0, "dashboard filtered by owner")
fc = rpt.forecast(company_id, 3)
check(len(fc) == 3 and sum(x["opportunities"] for x in fc) == 1 and sum(x["weighted"] for x in fc) == D(1_000_000), "forecast places opportunity")
perf = rpt.performance(company_id, month_start, today)
admin_p = next(p for p in perf if p["user_id"] == uid)
check(admin_p["won"] == 1 and admin_p["lost"] == 1 and admin_p["sales"] == D(5_000_000) and admin_p["tickets"] == 0, "performance per user")

# ===== جستجو و تقویم =====
kinds = {r["kind"] for r in rpt.search(company_id, "نمایشگاه")}
check({"LEAD", "OPPORTUNITY", "CAMPAIGN"} <= kinds, f"global search across entities ({kinds})")
with new_session() as s:
    inv_no = s.get(CommercialDocument, invoice).document_no
check(any(r["kind"] == "DOCUMENT" and r["id"] == invoice for r in rpt.search(company_id, str(inv_no))), "search by document number")
check(rpt.search(company_id, "ف") == [], "too short query")
cal = rpt.calendar(company_id, None, today, today + datetime.timedelta(days=7))
check({"ACTIVITY", "VISIT"} <= {e["kind"] for e in cal} and cal == sorted(cal, key=lambda e: e["date"]), "calendar events")
check(all(e["kind"] != "VISIT" for e in rpt.calendar(company_id, uid, today, today + datetime.timedelta(days=7))), "calendar per user")

# ===== ۱۶ گزارش =====
check(len(rpt.CRM_REPORTS) == 16 and len({r.code for r in rpt.CRM_REPORTS}) == 16, "16 CRM reports")
results = {}
for r in rpt.CRM_REPORTS:
    opts = {k: ch[0][0] for k, _l, ch in r.options}
    res = r.func(company_id, PurchaseFilters(month_start, today, side="INVENTORY", options=opts))
    results[r.code] = res
    check(all(len(row) == len(res.columns) for row in res.rows), f"report {r.code} shape")
check(results["CRM_WON_LOST"].rows[0][2] == 1 and any("قیمت بالا" in row for row in results["CRM_WON_LOST"].rows), "won/lost reasons")
check(any(row[3] == 1 for row in results["CRM_PIPELINE"].rows), "pipeline by stage")
check(results["CRM_CAMPAIGNS"].rows[0][9] == D(3_000_000), "campaign report revenue")
check(results["CRM_SATISFACTION"].rows[0][5] == 5 and "۵" in results["CRM_SATISFACTION"].note or "5" in results["CRM_SATISFACTION"].note,
      "satisfaction report")
check(len(results["CRM_OVERDUE"].rows) >= 1 and results["CRM_OVERDUE"].refs[0] == (cust_a, "CRM_CUSTOMER"), "overdue drill-down to 360")
check(sum(row[1] for row in results["CRM_RFM"].rows) >= 3, "RFM report")
from peecha.services.warehouse_reports import WAREHOUSE_REPORTS_BY_CODE
check(all(r.code in WAREHOUSE_REPORTS_BY_CODE for r in rpt.CRM_REPORTS), "reports registered on the shared report engine")

# ===== API =====
from fastapi.testclient import TestClient
from peecha_api.main import app
from peecha.services import roles as roles_service
from peecha.services.crm import roles_setup
client = TestClient(app)
login = lambda u: {"Authorization": "Bearer " + client.post("/auth/login", json={"username": u, "password": "secret123"}).json()["access_token"]}
hdr, vis = login("admin"), login("visitor1")
roles = roles_setup.ensure_role_templates(company_id)
roles_service.set_user_role(visitor.user_id, roles["CRM_USER"], company_id, True)
check(client.get("/crm/dashboard", headers=hdr).json()["won"] == 1, "API dashboard")
check(client.get("/crm/dashboard", params={"mine": True}, headers=vis).status_code == 200, "API dashboard for CRM_USER")
check(len(client.get("/crm/forecast", params={"months": 6}, headers=hdr).json()) == 6, "API forecast")
check(len(client.get("/crm/reports", headers=hdr).json()) == 16, "API report list")
rr = client.get("/crm/reports/crm_won_lost", headers=hdr).json()
check(rr["title"] == "تحلیل برد و باخت" and len(rr["rows"]) == 2, "API run report")
check(client.get("/crm/reports/CRM_CLV", headers=vis).status_code == 403, "report permission per menu form")
check(client.get("/crm/reports/CRM_OVERDUE", headers=vis).status_code == 200, "CRM_USER sees overdue report")
check(client.get("/crm/reports/NOPE", headers=hdr).status_code == 404, "unknown report 404")
check(any(r["kind"] == "LEAD" for r in client.get("/crm/search", params={"q": "نمایشگاه"}, headers=vis).json()), "API search")
check(client.get("/crm/calendar", params={"date_from": str(today), "date_to": str(today + datetime.timedelta(days=120))},
                 headers=vis).status_code == 400, "calendar range limited")
check(isinstance(client.get("/crm/calendar", params={"date_from": str(today), "date_to": str(today + datetime.timedelta(days=7))},
                            headers=vis).json(), list), "API calendar")
check(len(client.get("/crm/performance", headers=hdr).json()) >= 1, "API performance")

# ===== UI =====
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication
qapp = QApplication.instance() or QApplication([])
from peecha.ui.screens import crm as crm_ui
from peecha.ui.screens.purchase_reports import PurchaseReportScreen
scr = crm_ui.CrmDashboardScreen()
scr.refresh()
check(scr.cards["won"].text() != "" and scr.t_forecast.rowCount() == 6 and scr.t_perf.rowCount() >= 1, "dashboard screen")
check(len(scr.run_search("نمایشگاه")) >= 3 and scr.t_search.rowCount() >= 3, "search from dashboard")
check(scr.t_cal.rowCount() >= 1 and scr.report_list.count() == 16, "calendar and report list")
rs = PurchaseReportScreen("CRM_PERFORMANCE", None, side="INVENTORY")
rs.refresh()
check(rs is not None, "CRM report opens in shared report screen")

fx.finish()
