import os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r287"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crm_fixture import *  # noqa: F401,F403
import crm_fixture as fx
from peecha.db.models.commercial import CustomerActivity
from peecha.db.models.crm import Lead, Message
from peecha.services import notifications as notif
from peecha.services.crm import (analytics, automation as auto, common as cc, communication as comm, leads,
                                 opportunities as opps, segments as seg)
check = fx.check
ago = lambda n: today - datetime.timedelta(days=n)

fx.invoice(cust_a, 1_000_000, date=ago(100), due_date=ago(70))  # قدیمی و معوق
fx.invoice(cust_b, 2_000_000, date=ago(5), due_date=today + datetime.timedelta(days=30))
analytics.refresh_scores(company_id)

# ===== مرکز ارتباطات =====
check(comm.render("سلام {name}، بدهی {overdue}", {"name": "علی"}) == "سلام علی، بدهی {overdue}", "unknown placeholders kept")
tpl = comm.save_template(company_id, uid, code="remind", name="یادآوری", channel="SMS", body="{name} عزیز، از {company} منتظر شما هستیم")
check(fx.raises(lambda: comm.save_template(company_id, uid, code="REMIND", name="x", channel="SMS", body="x"), "تکراری"), "template code unique")
mid = comm.send_message(company_id, uid, "SMS", "", customer_id=cust_a, template_id=tpl)
with new_session() as s:
    m = s.get(Message, mid)
    act = s.get(CustomerActivity, m.activity_id)
check(m.status_code == "FAILED" and "درگاه" in m.error_message and m.recipient == "09120000001", "SMS without gateway logged as failed")
check(m.body.startswith("فروشگاه الف عزیز"), f"template rendered ({m.body})")
check(act.activity_type_code == "MESSAGE" and act.status_code == "DONE" and act.customer_detail_account_id == cust_a,
      "message recorded in customer timeline")


class FakeEmail:
    code = "FAKE_SMTP"
    sent = []

    def send(self, company_id, recipient, subject, body):
        FakeEmail.sent.append((recipient, subject, body))
        return comm.SendResult(True)


comm.register_provider("EMAIL", FakeEmail())
lead = leads.create_lead(company_id, uid, leads.LeadFields("سرنخ ایمیلی", email="a@b.ir"))
mid2 = comm.send_message(company_id, uid, "EMAIL", "پیشنهاد ویژه برای {name}", lead_id=lead, subject="پیشنهاد")
with new_session() as s:
    check(s.get(Message, mid2).status_code == "SENT" and FakeEmail.sent == [("a@b.ir", "پیشنهاد", "پیشنهاد ویژه برای سرنخ ایمیلی")],
          "pluggable provider used")
comm.register_provider("EMAIL", None)
check(comm.get_provider("EMAIL").code == "EMAIL_NONE", "provider reset")
mid3 = comm.send_message(company_id, uid, "EMAIL", "x", customer_id=cust_b)
with new_session() as s:
    check(s.get(Message, mid3).status_code == "FAILED", "customer without email → failed, not error")
check(fx.raises(lambda: comm.retry_message(company_id, uid, mid2), "ناموفق"), "only failed messages retried")
check(comm.retry_message(company_id, uid, mid) != mid, "retry creates new message")
check(len(comm.list_messages(company_id, customer_id=cust_a)) == 2, "message log per customer")

# ===== قاعده‌ها =====
rules = auto.list_rules(company_id)
check(len(rules) == 5 and not any(r.is_active for r in rules), "default rules seeded inactive")
check(len(auto.list_rules(company_id)) == 5, "defaults seeded once")
check(fx.raises(lambda: auto.save_rule(company_id, uid, name="x", trigger_code="NOPE", conditions={}, action_code="NOTIFY",
                                       action_params={}), "رویداد"), "trigger validated")
check(fx.raises(lambda: auto.save_rule(company_id, uid, name="x", trigger_code="SEGMENT_MEMBER", conditions={}, action_code="NOTIFY",
                                       action_params={}), "بخش مشتری"), "segment required")
check(fx.raises(lambda: auto.save_rule(company_id, uid, name="x", trigger_code="CHURN_HIGH", conditions={}, action_code="SEND_MESSAGE",
                                       action_params={"channel": "SMS"}), "الگو یا متن"), "message action needs body")

inactive = auto.save_rule(company_id, uid, name="غیرفعال ۶۰", trigger_code="CUSTOMER_INACTIVE", conditions={"days": 60},
                          action_code="CREATE_ACTIVITY", action_params={"activity_type": "FOLLOW_UP", "subject": "پیگیری {name} ({days} روز)",
                                                                        "assign_to": "OWNER"}, cooldown_days=30)
check(auto.preview(company_id, "CUSTOMER_INACTIVE", {"days": 60}) == 1, "preview counts matches")
check(auto.run_rule(company_id, inactive) == 1, "inactive customer rule acted once")
with new_session() as s:
    a = s.scalar(select(CustomerActivity).where(CustomerActivity.subject.like("پیگیری فروشگاه الف%")))
check(a is not None and a.assigned_to_user_id == visitor.user_id and "100 روز" in a.subject,
      "activity assigned to visit-plan owner with rendered subject")
check(auto.run_rule(company_id, inactive) == 0, "cooldown prevents duplicate action")

overdue = auto.save_rule(company_id, uid, name="معوق", trigger_code="INVOICE_OVERDUE", conditions={"days": 1, "min_amount": 500000},
                         action_code="SEND_MESSAGE", action_params={"channel": "SMS", "body": "{name}، بدهی معوق شما {overdue} است"},
                         cooldown_days=7)
check(auto.run_rule(company_id, overdue) == 1, "overdue rule sends message")
with new_session() as s:
    last = s.scalar(select(Message).where(Message.rule_id == overdue))
check(last.body == "فروشگاه الف، بدهی معوق شما 1,000,000 است", f"overdue amount in message ({last.body})")

old_lead = leads.create_lead(company_id, uid, leads.LeadFields("سرنخ فراموش‌شده", mobile="09135550000", owner_user_id=visitor.user_id))
with new_session() as s:
    s.get(Lead, old_lead).created_at = cc.now() - datetime.timedelta(days=2)
    s.commit()
notify_rule = auto.save_rule(company_id, uid, name="سرنخ", trigger_code="LEAD_NOT_CONTACTED", conditions={"hours": 24}, action_code="NOTIFY",
                             action_params={"title": "سرنخ {name} بی‌پاسخ مانده", "user_id": "OWNER"}, cooldown_days=0)
check(auto.run_rule(company_id, notify_rule) == 1, "lead not contacted rule")
check(any("سرنخ فراموش‌شده" in n.title for n in notif.list_notifications(visitor.user_id, company_id)), "owner notified")
check(auto.run_rule(company_id, notify_rule) == 0, "cooldown 0 = once per entity")

opp = opps.create_opportunity(company_id, uid, opps.OpportunityFields("قرارداد راکد", customer_detail_account_id=cust_b, amount=D(9_000_000)))
from peecha.db.models.crm import Opportunity
with new_session() as s:
    s.get(Opportunity, opp).stage_entered_at = cc.now() - datetime.timedelta(days=20)
    s.commit()
stale = auto.save_rule(company_id, uid, name="راکد", trigger_code="OPPORTUNITY_STALE", conditions={"days": 14, "stage_code": "new"},
                       action_code="CREATE_ACTIVITY", action_params={"activity_type": "TASK", "subject": "{name} {amount}", "assign_to": str(uid)})
check(auto.run_rule(company_id, stale) == 1, "stale opportunity (stage filter)")
with new_session() as s:
    t = s.scalar(select(CustomerActivity).where(CustomerActivity.opportunity_id == opp, CustomerActivity.activity_type_code == "TASK"))
check(t is not None and t.subject == "قرارداد راکد 9,000,000", "activity linked to opportunity")

segid = seg.save_segment(company_id, uid, code="BUYERS", name="خریداران", rule={"all": [{"field": "invoice_count_total", "op": ">=", "value": 1}]})
seg_rule = auto.save_rule(company_id, uid, name="سگمنت", trigger_code="SEGMENT_MEMBER", conditions={"segment_id": segid},
                          action_code="CREATE_ACTIVITY", action_params={"activity_type": "CALL", "subject": "تماس با {name}"}, is_active=True)
res = auto.run_all(company_id, uid)
check(res[seg_rule] == 2 and res[inactive] == 0 and not any(r.rule_id in res for r in rules), "run_all: only active rules, cooldown kept")
check(next(r for r in auto.list_rules(company_id) if r.rule_id == seg_rule).run_count == 2, "rule run count")
log = auto.list_log(company_id, seg_rule)
check(len(log) == 2 and {x["customer_name"] for x in log} == {"فروشگاه الف", "فروشگاه ب"}, "automation log")
auto.delete_rule(company_id, uid, stale)
check(all(r.rule_id != stale for r in auto.list_rules(company_id)), "rule deleted")

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
cat = client.get("/crm/automation/catalog", headers=vis).json()
check("CUSTOMER_INACTIVE" in cat["triggers"] and "SEND_MESSAGE" in cat["actions"], "API catalog")
check(client.post("/crm/automation/run", headers=vis).status_code == 403, "CRM_USER cannot run automation")
r = client.post("/crm/automation/rules", json={"name": "API", "trigger_code": "CHURN_HIGH", "action_code": "NOTIFY",
                                               "action_params": {"user_id": "OWNER"}}, headers=hdr)
check(r.status_code == 200, "API create rule")
check(client.post("/crm/automation/rules", json={"name": "bad", "trigger_code": "X", "action_code": "NOTIFY"}, headers=hdr).status_code == 400,
      "API invalid rule 400")
check(client.post("/crm/automation/preview", json={"trigger_code": "CUSTOMER_INACTIVE", "conditions": {"days": 60}}, headers=hdr).json()["count"] == 1,
      "API preview")
check(client.post("/crm/automation/run", headers=hdr).status_code == 200, "API run all")
check(len(client.get("/crm/automation/log", headers=hdr).json()) >= 5, "API log")
sent = client.post("/crm/messages", json={"channel": "SMS", "body": "سلام {name}", "customer_id": cust_b}, headers=dict(vis, **{"Idempotency-Key": "m1"}))
check(sent.status_code == 200 and sent.json()["status_code"] == "FAILED", "API send message (no gateway → failed status)")
check(client.post("/crm/messages", json={"channel": "INTERNAL", "body": "x"}, headers=vis).status_code == 400, "internal channel blocked")
check(len(client.get("/crm/messages", params={"customer_id": cust_b}, headers=vis).json()) >= 2, "API message log")
check(client.get("/crm/message-templates", headers=vis).json()[0]["code"] == "REMIND", "API templates")

# ===== UI =====
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication
qapp = QApplication.instance() or QApplication([])
from peecha.ui.screens import crm as crm_ui
scr = crm_ui.AutomationScreen()
scr.dialog_runner = lambda dlg: True
scr.confirm = lambda text: True
scr.refresh()
check(scr.t_rules.rowCount() == len(auto.list_rules(company_id)) and scr.t_msgs.rowCount() >= 4, "automation screen lists rules and messages")
dlg = crm_ui.RuleDialog(next(r for r in auto.list_rules(company_id) if r.rule_id == inactive), [], [])
v = dlg.values()
check(v["trigger_code"] == "CUSTOMER_INACTIVE" and v["conditions"] == {"days": 60} and v["action_params"]["assign_to"] == "OWNER",
      f"rule dialog round-trip ({v})")
rid = scr.edit_rule(new=True, values={"name": "فرم", "trigger_code": "CHURN_HIGH", "conditions": {}, "action_code": "NOTIFY",
                                      "action_params": {"user_id": "OWNER"}, "cooldown_days": 7, "is_active": False})
check(rid is not None, "rule created from screen")
scr.t_rules.selectRow(next(i for i in range(scr.t_rules.rowCount()) if scr.t_rules.item(i, 0).data(crm_ui.Qt.UserRole) == rid))
check(scr.toggle_rule() and next(r for r in auto.list_rules(company_id) if r.rule_id == rid).is_active, "toggle rule")
check(scr.run_all() is not None, "run all from screen")
check(scr.edit_template(new=True, values={"code": "T2", "name": "الگو ۲", "channel": "SMS", "subject": None, "body": "x", "is_active": True}),
      "template from screen")
c360 = crm_ui.Customer360Screen()
c360.dialog_runner = lambda dlg: True
c360.refresh()
c360.load_customer(cust_a)
check(c360.send_message(values={"channel": "SMS", "template_id": tpl, "body": ""}) is not None, "send message from 360")
check(c360.new_ticket(values={"subject": "شکایت از ۳۶۰", "ticket_type": "COMPLAINT", "priority_code": "HIGH"}) is not None,
      "ticket from 360")

fx.finish()
