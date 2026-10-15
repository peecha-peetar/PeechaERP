import os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r284"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crm_fixture import *  # noqa: F401,F403
import crm_fixture as fx
from sqlalchemy import func
from peecha.db.models.commercial import CustomerActivity, CustomerProfile, SmsCampaign, SmsCampaignRecipient
from peecha.db.models.crm import Campaign, CampaignMember, Lead, Opportunity
from peecha.services import sms_marketing
from peecha.services.crm import (analytics, campaigns as camps, customer360 as c360, leads, loyalty, pipelines as pl,
                                 segments as seg)
check = fx.check
CF = camps.CampaignFields
src = {s.code: s.source_id for s in pl.list_lead_sources(company_id)}
with new_session() as s:
    n_profiles = s.scalar(select(func.count()).where(CustomerProfile.company_id == company_id))

# ===== امتیاز سرنخ قابل تنظیم =====
lead1 = leads.create_lead(company_id, uid, leads.LeadFields("سرنخ معرفی", mobile="09131111111", source_id=src["REFERRAL"]))
base = leads.score_breakdown(company_id, lead1)
check(base["source"] == 15, "default source points")
cfg = leads.save_scoring_config(company_id, uid, factor_max={"profile": 0}, source_points={"REFERRAL": 30}, bands={"WARM": 20})
after = leads.score_breakdown(company_id, lead1)
check(after["source"] == 30 and after["profile"] == 0, f"configured weights applied ({after})")
check(dict(cfg["bands"])["WARM"] == 20 and leads.get_lead(company_id, lead1).score == sum(after.values()), "open leads rescored")
check(fx.raises(lambda: leads.save_scoring_config(company_id, uid, factor_max={"value": 80}), "۵۰"), "factor cap validated")
check(fx.raises(lambda: leads.save_scoring_config(company_id, uid, bands={"HOT": 90}), "ترتیب"), "band order validated")

# ===== کمپین پیامکی از سگمنت =====
analytics.refresh_scores(company_id)
all_seg = seg.save_segment(company_id, uid, code="ALL", name="همه", rule={"all": []})
camp = camps.create_campaign(company_id, uid, CF("جشنواره پاییز", "SMS", segment_id=all_seg, lead_source_id=src["ADVERTISING"],
                                                 start_date=today, end_date=today + datetime.timedelta(days=10),
                                                 actual_cost=D(2_000_000), budget_amount=D(5_000_000)))
check(camps.get_campaign(company_id, camp).status_code == "DRAFT", "campaign created as draft")
check(fx.raises(lambda: camps.create_campaign(company_id, uid, CF("x", start_date=today, end_date=today - datetime.timedelta(days=1))), "پایان"),
      "date range validated")
check(fx.raises(lambda: camps.launch(company_id, uid, camp), "مخاطب"), "launch needs members")
check(camps.build_members(company_id, uid, camp) == n_profiles, "members built from segment")
check(camps.build_members(company_id, uid, camp) == n_profiles, "rebuild replaces targeted members (no duplicates)")
check(fx.raises(lambda: camps.launch(company_id, uid, camp), "متن"), "SMS campaign needs message")
camps.update_campaign(company_id, uid, camp, CF("جشنواره پاییز", "SMS", segment_id=all_seg, lead_source_id=src["ADVERTISING"],
                                                start_date=today, end_date=today + datetime.timedelta(days=10), actual_cost=D(2_000_000),
                                                budget_amount=D(5_000_000), message_text="تخفیف ویژهٔ پاییز"))
res = camps.launch(company_id, uid, camp)
c1 = camps.get_campaign(company_id, camp)
check(c1.status_code == "ACTIVE" and res["sms_recipients"] == 2, f"launch queues SMS for members with phone ({res})")
with new_session() as s:
    sms_id = s.get(Campaign, camp).sms_campaign_id
    recips = list(s.scalars(select(SmsCampaignRecipient).where(SmsCampaignRecipient.campaign_id == sms_id)))
check(sms_id and {r.customer_detail_account_id for r in recips} == {cust_a, cust_b}, "existing SMS queue used (comm.sms_campaigns)")
check(fx.raises(lambda: camps.launch(company_id, uid, camp), "قبلاً"), "campaign launches once")
check(fx.raises(lambda: camps.delete_campaign(company_id, uid, camp), "پیش‌نویس"), "launched campaign cannot be deleted")
check(fx.raises(lambda: camps.update_campaign(company_id, uid, camp, CF("x", "CALL", segment_id=all_seg)), "نوع"),
      "type locked after launch")
sms_marketing.run_due_campaigns(company_id)  # بدون درگاه پیامک ← ناموفق
check(camps.sync_delivery(company_id) == 2, "delivery status synced from SMS queue")
statuses = {m["customer_detail_account_id"]: m["status_code"] for m in camps.list_members(company_id, camp)}
check(statuses[cust_a] == "FAILED", "failed delivery reflected on member")

# سرنخ پاسخ‌دهنده ← مشتری ← فرصت؛ فروش در بازهٔ کمپین
lead2 = leads.create_lead(company_id, uid, leads.LeadFields("پاسخ کمپین", mobile="09132222222"), campaign_id=camp)
with new_session() as s:
    lr = s.get(Lead, lead2)
    member = s.scalar(select(CampaignMember).where(CampaignMember.lead_id == lead2))
check(lr.campaign_id == camp and lr.source_id == src["ADVERTISING"] and member.status_code == "RESPONDED",
      "lead attributed to campaign and member responded")
new_cust, opp = leads.convert_lead(company_id, uid, lead2)
with new_session() as s:
    check(s.get(Opportunity, opp).campaign_id == camp, "opportunity inherits campaign")
    check(s.scalar(select(CampaignMember.status_code).where(CampaignMember.lead_id == lead2)) == "CONVERTED", "member converted")
fx.invoice(cust_a, 3_000_000, due_date=today + datetime.timedelta(days=30))
fx.invoice(new_cust, 1_000_000, due_date=today + datetime.timedelta(days=30))
fx.invoice(cust_a, 9_000_000, date=today - datetime.timedelta(days=5), due_date=today + datetime.timedelta(days=30))
camps.set_member_status(company_id, uid, next(m["member_id"] for m in camps.list_members(company_id, camp)
                                              if m["customer_detail_account_id"] == cust_b), "RESPONDED")
a = camps.campaign_analytics(company_id, camp)
check(a["revenue"] == D(4_000_000) and a["buyers"] == 2 and a["invoices"] == 2, f"revenue only inside campaign window ({a['revenue']})")
check(a["leads"] == 1 and a["leads_converted"] == 1 and a["opportunities"] == 1, "leads and opportunities attributed")
check(a["roi_percent"] == D("100.0") and a["cost_per_lead"] == D(2_000_000), f"ROI and cost per lead ({a['roi_percent']})")
check(a["responded"] == 2 and a["members"] == n_profiles + 1, "response counts include lead responder")
camps.set_status(company_id, uid, camp, "COMPLETED")
check(camps.get_campaign(company_id, camp).status_code == "COMPLETED", "campaign completed")
check(fx.raises(lambda: camps.add_customers(company_id, uid, camp, [cust_a]), "بسته"), "closed campaign is read-only")

# کمپین تماس ← فعالیت در مرکز کارها؛ لغو کمپین پیامکی زمان‌بندی‌شده
call = camps.create_campaign(company_id, uid, CF("تماس با مشتریان", "CALL", owner_user_id=visitor.user_id))
camps.add_customers(company_id, uid, call, [cust_a, cust_b, 999999])
check(len(camps.list_members(company_id, call)) == 2, "only company customers added")
check(camps.launch(company_id, uid, call)["activities"] == 2, "call campaign creates activities")
with new_session() as s:
    acts = list(s.scalars(select(CustomerActivity).where(CustomerActivity.subject.like("کمپین%"))))
check(len(acts) == 2 and all(x.assigned_to_user_id == visitor.user_id and x.activity_type_code == "CALL" for x in acts),
      "activities assigned to campaign owner")
later = camps.create_campaign(company_id, uid, CF("پیامک بعدی", "SMS", message_text="سلام"))
camps.add_customers(company_id, uid, later, [cust_a])
camps.launch(company_id, uid, later, scheduled_at=datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=3))
check(camps.get_campaign(company_id, later).status_code == "SCHEDULED", "future launch is scheduled")
camps.set_status(company_id, uid, later, "CANCELLED")
with new_session() as s:
    check(s.get(SmsCampaign, s.get(Campaign, later).sms_campaign_id).status_code == "FAILED", "cancel removes pending SMS from queue")
draft = camps.create_campaign(company_id, uid, CF("پیش‌نویس"))
camps.delete_campaign(company_id, uid, draft)
check(all(r.campaign_id != draft for r in camps.list_campaigns(company_id)), "draft deleted")

# ===== باشگاه مشتریان =====
check(loyalty.award_for_invoices(company_id) == {"invoices": 0, "points": 0}, "disabled loyalty awards nothing")
check(fx.raises(lambda: loyalty.save_rules(company_id, uid, tiers={"SILVER": 900, "GOLD": 100}), "ترتیب"), "tier order validated")
loyalty.save_rules(company_id, uid, enabled=True, amount_per_point=1_000_000, first_purchase_bonus=50, repeat_every=2, repeat_bonus=10,
                   referral_points=100, tiers={"SILVER": 60, "GOLD": 150, "PLATINUM": 1000})
r1 = loyalty.award_for_invoices(company_id)
s_a = loyalty.summary(company_id, cust_a)
# الف: ۹م (اولین) = ۹+۵۰ ، ۳م (دومین) = ۳+۱۰
check(s_a["points"] == 72 and s_a["tier"] == "SILVER", f"invoice points with first/repeat bonus ({s_a['points']}, {s_a['tier']})")
check(loyalty.award_for_invoices(company_id)["invoices"] == 0, "each invoice awarded once")
check(loyalty.adjust_points(company_id, uid, cust_a, -2, "اصلاح خطا") == 70, "manual adjustment")
check(fx.raises(lambda: loyalty.adjust_points(company_id, uid, cust_a, -1000, "x"), "کافی"), "cannot go negative")
check(fx.raises(lambda: loyalty.adjust_points(company_id, uid, cust_a, 5, ""), "علت"), "adjustment needs reason")
check(loyalty.award_referral(company_id, uid, cust_a, new_cust) == 100, "referral points")
check(fx.raises(lambda: loyalty.award_referral(company_id, uid, cust_b, new_cust), "قبلاً"), "referral awarded once")
check(loyalty.summary(company_id, cust_a)["tier"] == "GOLD", "tier upgraded by lifetime points")
check(c360.customer_360(company_id, cust_a)["loyalty"]["points"] == 170, "360 shows loyalty")

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
check(client.get("/crm/campaigns", headers=vis).status_code == 200, "CRM_USER can view campaigns")
check(client.post("/crm/campaigns", json={"name": "x"}, headers=vis).status_code == 403, "CRM_USER cannot create campaigns")
api_camp = client.post("/crm/campaigns", json={"name": "کمپین API", "campaign_type": "WHATSAPP", "segment_id": all_seg}, headers=hdr).json()["campaign_id"]
check(client.post(f"/crm/campaigns/{api_camp}/members", json={"from_segment": True}, headers=hdr).json()["added"] == n_profiles + 1,
      "API members from segment")
check(client.post(f"/crm/campaigns/{api_camp}/launch", json={}, headers=hdr).status_code == 200, "API launch")
got = client.get(f"/crm/campaigns/{api_camp}", headers=hdr).json()
check(got["status_code"] == "ACTIVE" and got["analytics"]["members"] == n_profiles + 1, "API campaign with analytics")
check(client.post("/crm/campaigns", json={"name": "bad", "campaign_type": "FAX"}, headers=hdr).status_code == 400, "API invalid type 400")
r = client.post("/crm/leads", json={"full_name": "سرنخ موبایل", "mobile": "09133333333", "campaign_id": 987654}, headers=vis)
check(r.status_code == 200, "invalid campaign does not reject a mobile lead")
r = client.post("/crm/leads", json={"full_name": "سرنخ موبایل ۲", "mobile": "09134444444", "campaign_id": api_camp}, headers=vis)
with new_session() as s:
    check(s.get(Lead, r.json()["lead_id"]).campaign_id == api_camp, "API lead attributed to campaign")
lo = client.get(f"/crm/customers/{cust_a}/loyalty", headers=vis).json()
check(lo["points"] == 170 and lo["tier"] == "GOLD", "API loyalty summary")
check(client.post(f"/crm/customers/{cust_a}/loyalty/adjust", json={"points": 5, "reason": "هدیه"}, headers=hdr).json()["points"] == 175,
      "API loyalty adjust")
ms_ = client.get("/crm/settings/marketing", headers=hdr).json()
check(ms_["loyalty"]["enabled"] is True and ms_["lead_scoring"]["source_points"]["REFERRAL"] == 30, "API marketing settings")
check(client.put("/crm/settings/marketing", json={"loyalty": {"repeat_every": -1}}, headers=hdr).status_code == 400, "API settings validated")

# ===== UI =====
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication
qapp = QApplication.instance() or QApplication([])
from peecha.ui.screens import crm as crm_ui
scr = crm_ui.CampaignsScreen()
scr.dialog_runner = lambda dlg: True
scr.confirm = lambda text: True
scr.refresh()
check(scr.t.rowCount() == len(camps.list_campaigns(company_id)), "campaign screen lists campaigns")
ui_camp = scr.new_campaign(values={"name": "کمپین فرم", "campaign_type": "SMS", "segment_id": all_seg, "message_text": "سلام",
                                   "start_date": today, "end_date": today, "attribution_days": 7, "actual_cost": D(100)})
check(ui_camp is not None, "campaign created from screen")
scr._after(ui_camp)
check(scr.build_members() == n_profiles + 1, "members built from screen")
check(scr.launch(confirm=False)["sms_recipients"] >= 2, "campaign launched from screen")
check(scr.new_lead(values={"full_name": "سرنخ فرم", "mobile": "09135555555"}) is not None, "lead from campaign screen")
check(scr.cards["leads"].text() != "—", "campaign analytics cards")
scr.l_fields["referral_points"].setText("150")
check(scr.save_loyalty() and loyalty.get_rules(company_id)["referral_points"] == 150, "loyalty rules saved from screen")
check(scr.award() is not None, "award from screen")
scr.s_factors["profile"].setText("10")
check(scr.save_scoring(), "lead scoring saved from screen")

fx.finish()
