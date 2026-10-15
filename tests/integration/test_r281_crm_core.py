import os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r281"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crm_fixture import *  # noqa: F401,F403
import crm_fixture as fx
from peecha.services.crm import activities as act, customer360 as c360, leads, opportunities as opps, pipelines as pl, tasks
from peecha.db.models.audit import ActivityLog
from peecha.db.models.security import Notification
check = fx.check

# ===== قیف پیش‌فرض و منابع =====
stages = pl.list_stages(company_id)
check([s.code for s in stages][:3] == ["NEW", "CONTACTED", "QUALIFIED"] and stages[-1].stage_type == "LOST", "default pipeline stages")
src = {s.code: s.source_id for s in pl.list_lead_sources(company_id)}
check(len(src) >= 12 and "INSTAGRAM" in src, "seeded lead sources")
custom_src = pl.save_lead_source(company_id, "TV", "تلویزیون")
check(any(s.code == "TV" for s in pl.list_lead_sources(company_id)), "custom lead source")

# ===== سرنخ → مشتری و فرصت =====
LF = leads.LeadFields
lead1 = leads.create_lead(company_id, uid, LF("علی رضایی", company_name="شرکت نمونه", mobile="09121112233", source_id=src["REFERRAL"],
                                            estimated_value=D(300_000_000), interested_text="محصول الف", owner_user_id=visitor.user_id))
row = leads.get_lead(company_id, lead1)
check(row.lead_no == 1 and row.score > 0 and row.score_band in ("COLD", "WARM", "HOT", "VERY_HOT"), f"lead scored ({row.score}, {row.score_band})")
check(fx.raises(lambda: leads.create_lead(company_id, uid, LF("دیگری", mobile="09121112233")), "سرنخ باز"), "duplicate open lead blocked")
check(fx.raises(lambda: leads.create_lead(company_id, uid, LF("بی‌تماس")), "موبایل"), "contact info required")
with new_session() as s:
    check(s.scalar(select(Notification).where(Notification.user_id == visitor.user_id, Notification.type_code == "CRM_LEAD_ASSIGNED")) is not None,
          "assigned lead notifies owner")
call = act.create_activity(company_id, uid, act.ActivityFields("CALL", "تماس اول", lead_id=lead1, due_date=today))
check(leads.get_lead(company_id, lead1).status_code == "CONTACTED", "activity moves NEW lead to CONTACTED")
before = leads.get_lead(company_id, lead1).score
act.complete_activity(company_id, uid, call, "علاقه‌مند است")
check(leads.rescore_lead(company_id, lead1) >= before, "engagement raises score")
customer_id, opp_id = leads.convert_lead(company_id, uid, lead1)
lr = leads.get_lead(company_id, lead1)
check(lr.status_code == "CONVERTED" and lr.converted_customer_detail_account_id == customer_id and lr.converted_opportunity_id == opp_id,
      "lead converted to customer and opportunity")
prof = partners_service.get_customer_profile(customer_id)
check(prof is not None and prof.onboarding_source_code == "REFERRAL" and prof.status_code == "ACTIVE",
      "customer created through existing customer service (profile, source)")
check(call in [a.activity_id for a in act.list_activities(company_id, customer_detail_account_id=customer_id)], "lead activities move to customer")
check(fx.raises(lambda: leads.convert_lead(company_id, uid, lead1), "قبلاً"), "double conversion blocked")
lead2 = leads.create_lead(company_id, uid, LF("مریم", mobile="09125556677", source_id=src["INSTAGRAM"]))
c2, o2 = leads.convert_lead(company_id, uid, lead2, existing_customer_id=cust_b, create_opportunity=False)
check(c2 == cust_b and o2 is None, "lead linked to existing customer without opportunity")
lead3 = leads.create_lead(company_id, uid, LF("سرنخ حذفی", phone="0211234"))
check(fx.raises(lambda: leads.set_lead_status(company_id, uid, lead3, "LOST"), "دلیل"), "lost needs reason")
leads.delete_lead(company_id, uid, lead3)
check(not leads.list_leads(company_id, lead_ids=[lead3]), "delete lead")

# ===== فرصت و قیف =====
o = opps.get_opportunity(company_id, opp_id)
check(o.stage_name == "جدید" and o.amount == D(300_000_000) and o.probability_percent == D(10), "opportunity in first stage with probability")
check(any(a.activity_type_code == "CALL" and a.opportunity_id == opp_id for a in act.list_activities(company_id, opportunity_id=opp_id)),
      "stage automatic activity created")
st = {s.code: s.stage_id for s in stages}
check(fx.raises(lambda: opps.move_stage(company_id, uid, opp_id, st["PROPOSAL"]), "تاریخ پیش‌بینی"), "required field enforced on stage")
f = opps.OpportunityFields(o.title, customer_detail_account_id=customer_id, amount=D(0), expected_close_date=today + datetime.timedelta(days=20))
opps.update_opportunity(company_id, uid, opp_id, f)
opps.set_lines(company_id, uid, opp_id, [opps.LineFields(item_a, D(10), D(2_000_000), D(500_000)), opps.LineFields(None, D(1), D(1_000_000), description="نصب")])
check(opps.get_opportunity(company_id, opp_id).amount == D(20_500_000), "amount from lines (qty×price−discount)")
opps.move_stage(company_id, uid, opp_id, st["NEGOTIATION"])
o = opps.get_opportunity(company_id, opp_id)
check(o.probability_percent == D(80) and o.status_code == "OPEN", "stage probability applied")
check(any("مذاکره" in a.subject for a in act.list_activities(company_id, opportunity_id=opp_id)), "negotiation creates salesperson task")
cols = opps.kanban(company_id)
neg = next(col for col in cols if col.code == "NEGOTIATION")
check(len(neg.cards) == 1 and neg.weighted == D("16400000.00"), f"kanban column with weighted value ({neg.weighted})")
check(fx.raises(lambda: opps.mark_lost(company_id, uid, opp_id, ""), "دلیل"), "lost needs reason")
opps.mark_won(company_id, uid, opp_id)
o = opps.get_opportunity(company_id, opp_id)
check(o.status_code == "WON" and o.closed_at is not None and o.probability_percent == D(100), "won closes opportunity")
summary = opps.pipeline_summary(company_id)
check(summary["won_count"] == 1 and summary["conversion_rate"] == D(100), "pipeline summary")
lead4 = leads.create_lead(company_id, uid, LF("فقط سرنخ", mobile="09129998877"))
o4 = opps.create_opportunity(company_id, uid, opps.OpportunityFields("فرصت بدون مشتری", lead_id=lead4, amount=D(5_000_000),
                                                                      expected_close_date=today))
check(fx.raises(lambda: opps.mark_won(company_id, uid, o4), "مشتری"), "won requires customer (lead must be converted)")
opps.mark_lost(company_id, uid, o4, "قیمت بالا")
check(opps.get_opportunity(company_id, o4).status_code == "LOST", "mark lost with reason")
opps.delete_opportunity(company_id, uid, o4)
check(not opps.list_opportunities(company_id, opportunity_ids=[o4]), "delete opportunity without documents")
new_stage = pl.save_stage(company_id, uid, pl.ensure_default_pipeline(company_id), pl.StageFields("DEMO", "دمو", D(55), sla_hours=48))
check(any(s.code == "DEMO" for s in pl.list_stages(company_id)), "custom stage added")
check(fx.raises(lambda: pl.save_stage(company_id, uid, pl.ensure_default_pipeline(company_id), pl.StageFields("X", "x", D(5), required_fields=["foo"])), "نامعتبر"),
      "invalid required field rejected")
pl.delete_stage(company_id, uid, new_stage)

# ===== فعالیت و مرکز کارها =====
AF = act.ActivityFields
t_over = act.create_activity(company_id, uid, AF("FOLLOW_UP", "پیگیری معوق", customer_detail_account_id=cust_a, due_date=today - datetime.timedelta(days=2)))
t_today = act.create_activity(company_id, uid, AF("MEETING", "جلسهٔ امروز", customer_detail_account_id=cust_a, due_date=today, priority_code="HIGH"))
t_tom = act.create_activity(company_id, uid, AF("TASK", "فردا", customer_detail_account_id=cust_a, due_date=today + datetime.timedelta(days=1)))
note = act.create_activity(company_id, uid, AF("NOTE", "یادداشت", customer_detail_account_id=cust_a))
check(act.get_activity(company_id, note).status_code == "DONE", "note is closed on creation")
tc = tasks.task_center(company_id, uid)
check(t_over in [a.activity_id for a in tc.buckets["overdue"]] and t_today in [a.activity_id for a in tc.buckets["today"]]
      and t_tom in [a.activity_id for a in tc.buckets["tomorrow"]], "task center buckets (overdue/today/tomorrow)")
check(note not in [a.activity_id for b in tc.buckets.values() for a in b], "closed activities not in task center")
follow = act.complete_activity(company_id, uid, t_today, "جلسه برگزار شد", follow_up_date=today + datetime.timedelta(days=3))
check(follow and act.get_activity(company_id, follow).activity_type_code == "FOLLOW_UP", "completing creates follow-up")
check(fx.raises(lambda: act.create_activity(company_id, uid, AF("CALL", "بی‌طرف")), "مشتری یا سرنخ"), "activity needs a party")
check(fx.raises(lambda: act.complete_activity(company_id, uid, t_today), "قبلاً"), "cannot close twice")
vt = tasks.task_center(company_id, visitor.user_id)
check(any(p["customer_detail_account_id"] == cust_a for p in vt.planned_visits), "today's planned visits from visit plans")

# ===== Customer 360 روی دادهٔ واقعی ERP =====
inv1 = fx.invoice(cust_a, 1_000_000, today - datetime.timedelta(days=40), due_date=today - datetime.timedelta(days=10))
inv2 = fx.invoice(cust_a, 2_000_000, today - datetime.timedelta(days=10), due_date=today + datetime.timedelta(days=20))
fx.receipt(cust_a, 500_000, today - datetime.timedelta(days=5))
v = c360.customer_360(company_id, cust_a)
fin, sal = v["financial"], v["sales"]
bal, nature = treasury_service.get_counterparty_balance(company_id, cust_a)
check(fin["balance"] == bal == D(2_500_000) and fin["balance_nature"] == nature, "balance read from accounting")
check(fin["debit_total"] == D(3_000_000) and fin["credit_total"] == D(500_000), "debit/credit totals")
check(fin["last_payment_amount"] == D(500_000) and fin["last_payment_date"] == today - datetime.timedelta(days=5), "last payment from treasury receipt")
check(fin["overdue_count"] == 1 and fin["overdue_amount"] == D(1_000_000), "overdue invoices from settlements")
check(sal["invoice_count"] == 2 and sal["total_sales"] == D(3_000_000) and sal["avg_invoice"] == D(1_500_000), "sales totals from invoices")
check(sal["days_since_last"] == 10 and sal["avg_days_between"] == 30, "purchase recency and frequency")
check(sal["top_items"][0]["item_id"] == item_a, "top items")
check(any(a["code"] == "COLLECTION" for a in v["smart_actions"]), "smart action: collection follow-up")
check("فاکتور معوق" in v["summary"], f"rule-based summary ({v['summary']})")
check(v["identity"]["visitors"] == "ویزیتور یک", "visitor from visit plan")
tl = c360.timeline(company_id, cust_a)
kinds = {e.kind for e in tl}
check({"INVOICE", "PAYMENT", "FOLLOW_UP", "MEETING", "NOTE"} <= kinds, f"timeline merges ERP and CRM events ({sorted(kinds)})")
check(tl == sorted(tl, key=lambda e: e.at, reverse=True), "timeline newest first")
check({e.kind for e in c360.timeline(company_id, cust_a, kinds=["INVOICE"])} == {"INVOICE"}, "timeline type filter")
check(len(c360.timeline(company_id, cust_a, limit=2)) == 2 and len(c360.timeline(company_id, cust_a, limit=2, offset=2)) == 2, "timeline paging")
check(all(e.at.date() >= today - datetime.timedelta(days=7) for e in c360.timeline(company_id, cust_a, date_from=today - datetime.timedelta(days=7))),
      "timeline date range")
check([e.kind for e in c360.timeline(company_id, cust_a, search="معوق")] == ["FOLLOW_UP"], "timeline search")
check(c360.search_customers(company_id, "0912000000")[0]["customer_detail_account_id"] in (cust_a, cust_b), "customer search by mobile")

# ===== Audit =====
with new_session() as s:
    kinds = set(s.scalars(select(ActivityLog.entity_type).where(ActivityLog.entity_type.like("Crm%"))).all())
check({"CrmLead", "CrmOpportunity", "CrmActivity"} <= kinds, f"audit log for CRM entities {sorted(kinds)}")

# ===== دسترسی و API =====
from peecha.services import roles as roles_service
from peecha.services.crm import roles_setup
from fastapi.testclient import TestClient
from peecha_api.main import app
roles_service.ensure_catalog()
client = TestClient(app)
login = lambda u: {"Authorization": "Bearer " + client.post("/auth/login", json={"username": u, "password": "secret123"}).json()["access_token"]}
vis = login("visitor1")
check(client.get("/crm/leads", headers=vis).status_code == 403, "user without CRM role is forbidden")
roles = roles_setup.ensure_role_templates(company_id)
check(set(roles) == {"CRM_USER", "CRM_MANAGER", "CRM_ADMIN"} and roles_setup.ensure_role_templates(company_id) == roles, "CRM role templates idempotent")
roles_service.set_user_role(visitor.user_id, roles["CRM_USER"], company_id, True)
check(client.get("/crm/leads", headers=vis).status_code == 200, "CRM_USER can list leads")
check(client.post(f"/crm/leads/{lead4}/assign", json={"owner_user_id": uid}, headers=vis).status_code == 403, "assign needs crm_assign")
check(client.delete(f"/crm/leads/{lead4}", headers=vis).status_code == 403, "CRM_USER cannot delete leads")
hdr = dict(vis, **{"Idempotency-Key": "lead-k1"})
r1 = client.post("/crm/leads", json={"full_name": "سرنخ موبایل", "mobile": "09351112222", "source_id": src["VISITOR"]}, headers=hdr)
r2 = client.post("/crm/leads", json={"full_name": "سرنخ موبایل", "mobile": "09351112222", "source_id": src["VISITOR"]}, headers=hdr)
check(r1.status_code == 200 and r1.json() == r2.json(), "lead create via API is idempotent")
api_lead = r1.json()["lead_id"]
detail = client.get(f"/crm/leads/{api_lead}", headers=vis).json()
check(detail["owner_user_id"] == visitor.user_id and "score_breakdown" in detail, "lead detail with score breakdown")
bad = client.post("/crm/leads", json={"full_name": "بی‌تماس"}, headers=vis)
check(bad.status_code == 400 and "موبایل" in bad.json()["detail"], "validation error is 400 with Persian message")
act_r = client.post("/crm/activities", json={"activity_type_code": "VISIT", "subject": "ویزیت از موبایل", "customer_detail_account_id": cust_a,
                                             "due_date": str(today)}, headers=dict(vis, **{"Idempotency-Key": "act-1"}))
check(act_r.status_code == 200, "activity from mobile")
done = client.post(f"/crm/activities/{act_r.json()['activity_id']}/complete",
                   json={"result_text": "سفارش گرفت", "follow_up_date": str(today + datetime.timedelta(days=7))}, headers=vis)
check(done.status_code == 200 and done.json()["follow_up_activity_id"], "complete with follow-up via API")
t = client.get("/crm/tasks", headers=vis).json()
check("today" in t["counts"] and isinstance(t["planned_visits"], list), "task center API")
conv = client.post(f"/crm/leads/{api_lead}/convert", json={"create_opportunity": True, "opportunity_amount": "7000000"}, headers=vis)
check(conv.status_code == 200 and conv.json()["opportunity_id"], "convert lead via API")
pipes = client.get("/crm/pipelines", headers=vis).json()
board = client.get(f"/crm/pipelines/{pipes[0]['pipeline_id']}/kanban", headers=vis).json()
check(board["columns"] and "weighted" in board["columns"][0], "kanban API")
neg_stage = next(st["stage_id"] for st in pipes[0]["stages"] if st["code"] == "CONTACTED")
mv = client.post(f"/crm/opportunities/{conv.json()['opportunity_id']}/stage", json={"stage_id": neg_stage}, headers=vis)
check(mv.status_code == 200 and mv.json()["stage_name"] == "تماس گرفته‌شده", "move stage via API")
c3 = client.get(f"/crm/customers/{cust_a}/360", headers=vis)
check(c3.status_code == 200 and c3.json()["financial"]["balance"] == "2500000.00", "customer 360 API reads accounting balance")
tl_api = client.get(f"/crm/customers/{cust_a}/timeline?kinds=INVOICE,PAYMENT&limit=10", headers=vis).json()
check(tl_api and {e["kind"] for e in tl_api} <= {"INVOICE", "PAYMENT"}, "timeline API with kind filter")
legacy = client.get(f"/customers/{cust_a}/activities", headers=vis)
check(legacy.status_code == 200 and any(a["activity_type_code"] == "VISIT" for a in legacy.json()), "legacy mobile activities API still works")

# ===== رابط دسکتاپ =====
from PySide6.QtWidgets import QApplication, QMessageBox
app_qt = QApplication.instance() or QApplication([])
warnings = []
QMessageBox.warning = staticmethod(lambda *a, **k: warnings.append(a[2] if len(a) > 2 else a))
QMessageBox.information = staticmethod(lambda *a, **k: None)
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
from peecha.ui.screens import crm as ui
from peecha import nav_catalog
labels = {i["screen"] for i in nav_catalog.flatten_nav_items()}
check({"crm_customer360", "crm_tasks", "crm_leads", "crm_pipeline", "crm_settings"} <= labels, "CRM menu entries")
scr = ui.Customer360Screen()
scr.dialog_runner = lambda dlg: True
scr.refresh()
scr.load_customer(cust_a)
check("فروشگاه الف" in scr.ident_label.text() and scr.cards["balance"].text(), "360 header filled")
scr.tabs.setCurrentIndex(1)
check(scr.t_timeline.rowCount() > 0, "timeline tab lazy-loaded")
for i in range(scr.tabs.count()):
    scr.tabs.setCurrentIndex(i)
check(scr.t_activities.rowCount() > 0 and scr.t_sales.rowCount() == 2, "all tabs load (activities, sales)")
aid = scr.quick_activity("CALL", {"activity_type_code": "CALL", "subject": "تماس سریع", "due_date": today, "duration_minutes": None,
                                  "priority_code": "NORMAL", "assigned_to_user_id": None, "next_action": None, "description": None})
check(aid and act.get_activity(company_id, aid).customer_detail_account_id == cust_a, "quick action creates activity for customer")
tc_scr = ui.TaskCenterScreen()
tc_scr.dialog_runner = lambda dlg: True
tc_scr.refresh()
check(tc_scr.tables["overdue"].rowCount() >= 1 and tc_scr.cards["overdue"].text() != "—", "task center screen buckets")
tc_scr.tabs.setCurrentIndex(0)
tc_scr.tables["overdue"].selectRow(0)
check(tc_scr.postpone(today + datetime.timedelta(days=2)), "postpone overdue activity")
leads_scr = ui.LeadsScreen()
leads_scr.dialog_runner = lambda dlg: True
leads_scr.refresh()
new_id = leads_scr.new_lead({"full_name": "سرنخ دسکتاپ", "mobile": "09370000000", "estimated_value": D(0)})
check(new_id and leads_scr.t.rowCount() >= 1, "leads screen create")
leads_scr.t.selectRow([r.lead_id for r in leads_scr.rows].index(new_id))
res = leads_scr.convert({"existing": None, "opportunity": True, "title": "فرصت دسکتاپ", "amount": D(1_000_000)})
check(res and res[1], "leads screen convert")
pipe = ui.PipelineScreen()
pipe.dialog_runner = lambda dlg: True
pipe.refresh()
check(len(pipe.columns) >= 8, "kanban columns")
pipe.select(res[1])
check(pipe.move_card(res[1], st["QUALIFIED"]) and opps.get_opportunity(company_id, res[1]).stage_id == st["QUALIFIED"], "drag card to stage")
pipe.select(res[1])
check(pipe.edit_lines([opps.LineFields(item_b, D(3), D(400_000))]) and opps.get_opportunity(company_id, res[1]).amount == D(1_200_000),
      "opportunity lines from kanban")
settings_scr = ui.CrmSettingsScreen()
settings_scr.dialog_runner = lambda dlg: True
settings_scr.refresh()
check(settings_scr.t_stages.rowCount() >= 8 and settings_scr.t_sources.rowCount() >= 13, "settings screen lists stages and sources")
check(not [w for w in warnings if "نامعتبر" in str(w)], f"no unexpected warnings {warnings}")

fx.finish()
