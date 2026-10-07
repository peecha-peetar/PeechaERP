import os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r285"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crm_fixture import *  # noqa: F401,F403
import crm_fixture as fx
from peecha.db.models.commercial import ServiceTicket
from peecha.services import commercial_aftersales as aftersales
from peecha.services.crm import analytics, common as cc, customer360 as c360, tasks, tickets as tk
check = fx.check
TF = tk.TicketFields
now = cc.now()
hours = datetime.timedelta(hours=1)

# ===== SLA =====
pols = tk.list_policies(company_id)
check(len(pols) == 4 and {p.priority_code for p in pols} == {"CRITICAL", "HIGH", "NORMAL", "LOW"}, "default SLA policies")
check(len(tk.list_policies(company_id)) == 4, "default policies seeded once")
complaint_pol = tk.save_policy(company_id, uid, name="شکایت فوری", ticket_type="COMPLAINT", priority_code="HIGH",
                               first_response_hours=1, resolution_hours=4, escalate_to_user_id=uid)
check(fx.raises(lambda: tk.save_policy(company_id, uid, name="x", first_response_hours=5, resolution_hours=2), "کمتر"),
      "resolution must be ≥ first response")
check(fx.raises(lambda: tk.save_policy(company_id, uid, name="x", first_response_hours=0, resolution_hours=2), "صفر"), "positive hours")

# ===== ثبت تیکت =====
t1 = tk.create_ticket(company_id, uid, TF(cust_a, "تأخیر در ارسال", "COMPLAINT", "HIGH", channel_code="PHONE",
                                         assigned_to_user_id=visitor.user_id, description="سفارش دیر رسید"))
r1 = tk.get_ticket(company_id, t1)
check(r1.ticket_no == 1 and r1.status_code == "OPEN" and not r1.is_billable, "complaint ticket is not billable")
with new_session() as s:
    row = s.get(ServiceTicket, t1)
check(row.sla_policy_id == complaint_pol and abs((row.resolution_due_at - row.opened_at) - 4 * hours) < datetime.timedelta(seconds=2),
      "most specific SLA (type + priority) applied")
t2 = tk.create_ticket(company_id, uid, TF(cust_b, "سؤال قیمت", "INQUIRY", "LOW"))
with new_session() as s:
    row2 = s.get(ServiceTicket, t2)
check(abs((row2.resolution_due_at - row2.opened_at) - 96 * hours) < datetime.timedelta(seconds=2), "priority SLA applied")
t3 = tk.create_ticket(company_id, uid, TF(cust_a, "تعمیر دستگاه", "SERVICE", "NORMAL", item_id=item_a))
check(tk.get_ticket(company_id, t3).is_billable, "service ticket uses after-sales billable rule")
check(fx.raises(lambda: tk.create_ticket(company_id, uid, TF(cust_a, "", "COMPLAINT")), "موضوع"), "subject required")
check(fx.raises(lambda: tk.create_ticket(company_id, uid, TF(cust_a, "x", "FAX")), "نوع"), "type validated")
check(fx.raises(lambda: tk.create_ticket(company_id, uid, TF(999999, "x")), "مشتری"), "customer validated")
check(tk.get_ticket(company_id, t2).ticket_no == 2, "ticket numbers per company")

# ===== پاسخ، حل، بستن، رضایت =====
aid = tk.add_reply(company_id, uid, t1, "با مشتری تماس گرفتیم", "CALL")
r1 = tk.get_ticket(company_id, t1)
check(r1.status_code == "IN_PROGRESS" and r1.first_responded_at is not None, "first reply moves ticket in progress")
conv = tk.conversation(company_id, t1)
check(len(conv) == 1 and conv[0].activity_id == aid and conv[0].status_code == "DONE", "reply stored as done activity")
check(fx.raises(lambda: tk.resolve_ticket(company_id, uid, t1, ""), "راه‌حل"), "resolution text required")
check(fx.raises(lambda: tk.rate_ticket(company_id, uid, t1, 5), "پس از حل"), "rating only after resolution")
tk.resolve_ticket(company_id, uid, t1, "ارسال فوری انجام شد")
r1 = tk.get_ticket(company_id, t1)
check(r1.status_code == "RESOLVED" and r1.resolved_at and not r1.sla_breached, "resolved within SLA")
check(fx.raises(lambda: tk.rate_ticket(company_id, uid, t1, 6), "۱ تا ۵"), "score range")
tk.rate_ticket(company_id, uid, t1, 4, "خوب بود")
tk.close_ticket(company_id, uid, t1)
check(tk.get_ticket(company_id, t1).status_code == "CLOSED", "complaint closed")
check(fx.raises(lambda: tk.add_reply(company_id, uid, t1, "x"), "بسته"), "no reply on closed ticket")
check(fx.raises(lambda: tk.close_ticket(company_id, uid, t3), "فاکتور"), "billable service ticket keeps after-sales close rule")
tk.reopen_ticket(company_id, uid, t1, "مشکل تکرار شد")
r1 = tk.get_ticket(company_id, t1)
check(r1.status_code == "OPEN" and r1.resolved_at is None and r1.resolution_due_at > now, "reopen restarts resolution SLA")
tk.resolve_ticket(company_id, uid, t1, "حل شد")
tk.close_ticket(company_id, uid, t1)

# ===== نقض SLA و ارجاع =====
with new_session() as s:
    row = s.get(ServiceTicket, t2)
    row.first_response_due_at, row.resolution_due_at = now - 2 * hours, now + 10 * hours
    s.commit()
check(tk.check_sla(company_id) == [t2], "first-response breach detected")
r2 = tk.get_ticket(company_id, t2)
check(r2.sla_breached and r2.escalation_level == 1 and r2.sla_state() == "BREACHED", "breach flag and level 1 escalation")
check(tk.check_sla(company_id) == [], "same level escalates once")
with new_session() as s:
    s.get(ServiceTicket, t2).resolution_due_at = now - hours
    s.commit()
check(tk.check_sla(company_id) == [t2] and tk.get_ticket(company_id, t2).escalation_level == 2, "resolution breach → level 2")
from peecha.services import notifications as notif
check(any("نقض SLA" in n.title for n in notif.list_notifications(uid, company_id)), "SLA breach notified to creator")

# ===== ویرایش، ارجاع و فهرست =====
tk.update_ticket(company_id, uid, t2, TF(cust_b, "سؤال قیمت عمده", "INQUIRY", "CRITICAL", category="قیمت"))
with new_session() as s:
    check(s.get(ServiceTicket, t2).sla_policy_id != row2.sla_policy_id, "priority change re-applies SLA")
check(fx.raises(lambda: tk.update_ticket(company_id, uid, t2, TF(cust_a, "x", "INQUIRY")), "مشتری"), "customer is fixed")
check(fx.raises(lambda: tk.update_ticket(company_id, uid, t2, TF(cust_b, "x", "SERVICE")), "خدماتی"), "service type is fixed")
tk.assign_ticket(company_id, uid, t2, visitor.user_id)
check([t.ticket_id for t in tk.list_tickets(company_id, assignee_user_id=visitor.user_id, open_only=True)] == [t2], "my open tickets")
check([t.ticket_id for t in tk.list_tickets(company_id, breached_only=True)] == [t2], "breached filter")
check(len(tk.list_tickets(company_id, search="عمده")) == 1, "search")
check(any(x["ticket_id"] == t2 for x in tasks.task_center(company_id, visitor.user_id).open_tickets), "task center shows open tickets")
legacy = aftersales.open_ticket(cust_b, "تیکت قدیمی خدمات")
check(any(t.ticket_id == legacy for t in tk.list_tickets(company_id)), "legacy after-sales tickets visible in CRM")
tk.add_reply(company_id, uid, legacy, "بررسی شد")
check(tk.get_ticket(company_id, legacy).ticket_no is not None, "legacy ticket numbered when touched")

st = tk.stats(company_id)
check(st["total"] == 4 and st["breached"] == 1 and st["csat"] == D("4.0") and st["by_type"]["COMPLAINT"] == 1, f"ticket stats ({st})")
check(st["avg_resolution_hours"] is not None and st["sla_compliance"] == D("75.0"), "resolution time and SLA compliance")

# اثر بر تحلیل مشتری و ۳۶۰
analytics.refresh_scores(company_id)
check(analytics.get_score(company_id, cust_b).open_complaints >= 2, "open tickets feed churn/health analytics")
d = c360.customer_360(company_id, cust_b)
check(d["counts"]["open_tickets"] >= 2, "360 counts open tickets")
check(any(e.kind == "TICKET" for e in c360.timeline(company_id, cust_a)), "ticket in timeline")

# ===== API =====
from fastapi.testclient import TestClient
from peecha_api.main import app
from peecha.services import roles as roles_service
from peecha.services.crm import roles_setup
client = TestClient(app)
login = lambda u: {"Authorization": "Bearer " + client.post("/auth/login", json={"username": u, "password": "secret123"}).json()["access_token"]}
hdr, vis = login("admin"), login("visitor1")
check(client.get("/crm/tickets", headers=vis).status_code == 403, "tickets need permission")
roles = roles_setup.ensure_role_templates(company_id)
roles_service.set_user_role(visitor.user_id, roles["CRM_USER"], company_id, True)
body = {"customer_detail_account_id": cust_a, "subject": "شکایت از موبایل", "ticket_type": "COMPLAINT", "channel_code": "MOBILE_APP"}
a1 = client.post("/crm/tickets", json=body, headers=dict(vis, **{"Idempotency-Key": "tk-1"}))
a2 = client.post("/crm/tickets", json=body, headers=dict(vis, **{"Idempotency-Key": "tk-1"}))
check(a1.status_code == 200 and a1.json() == a2.json(), "API create ticket idempotent")
api_t = a1.json()["ticket_id"]
check(client.post(f"/crm/tickets/{api_t}/reply", json={"text": "پیگیری شد", "kind": "CALL"}, headers=vis).status_code == 200, "API reply")
got = client.get(f"/crm/tickets/{api_t}", headers=vis).json()
check(got["status_code"] == "IN_PROGRESS" and len(got["conversation"]) == 1 and got["sla_state"] in ("OK", "AT_RISK"), "API ticket detail")
check(client.post(f"/crm/tickets/{api_t}/resolve", json={"text": "حل شد"}, headers=vis).status_code == 200, "API resolve")
check(client.post(f"/crm/tickets/{api_t}/rate", json={"score": 5}, headers=vis).status_code == 200, "API rate")
check(client.get("/crm/tickets", params={"mine": True, "open_only": True}, headers=vis).status_code == 200, "API my tickets")
check(client.get("/crm/tickets/stats", headers=vis).json()["total"] == 5, "API stats")
check(client.post("/crm/sla-policies", json={"name": "x", "first_response_hours": 1, "resolution_hours": 2}, headers=vis).status_code == 403,
      "SLA admin needs crm_settings")
sp = client.post("/crm/sla-policies", json={"name": "SLA API", "first_response_hours": 2, "resolution_hours": 6}, headers=hdr).json()
check(sp["sla_policy_id"] and client.delete(f"/crm/sla-policies/{sp['sla_policy_id']}", headers=hdr).status_code == 200, "API SLA CRUD")
check(client.post("/crm/tickets", json={**body, "ticket_type": "BAD"}, headers=vis).status_code == 400, "API validation 400")
check("open_tickets" in client.get("/crm/tasks", headers=vis).json(), "API task center includes tickets")

# ===== UI =====
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication
qapp = QApplication.instance() or QApplication([])
from peecha.ui.screens import crm as crm_ui
scr = crm_ui.TicketsScreen()
scr.dialog_runner = lambda dlg: True
scr.confirm = lambda text: True
scr.refresh()
check(scr.t.rowCount() == len(tk.list_tickets(company_id, open_only=True)), "tickets screen lists open tickets")
ui_t = scr.new_ticket(values={"customer_detail_account_id": cust_b, "subject": "شکایت فرم", "ticket_type": "COMPLAINT",
                              "priority_code": "NORMAL"})
check(ui_t is not None, "ticket created from screen")
row_idx = next(i for i in range(scr.t.rowCount()) if scr.t.item(i, 0).data(crm_ui.Qt.UserRole) == ui_t)
scr.t.selectRow(row_idx)
check(scr.reply(values={"kind": "NOTE", "text": "یادداشت"}) and scr.t_conv.rowCount() == 1, "reply from screen")
check(scr.resolve(values={"text": "حل شد"}), "resolve from screen")
scr.open_only.setChecked(False)
row_idx = next(i for i in range(scr.t.rowCount()) if scr.t.item(i, 0).data(crm_ui.Qt.UserRole) == ui_t)
scr.t.selectRow(row_idx)
check(scr.rate(values={"score": 3, "comment": ""}) and scr.close_ticket(), "rate and close from screen")
check(scr.t_sla.rowCount() >= 5, "SLA policies tab")
check(scr.edit_policy(new=True, values={"name": "SLA فرم", "first_response_hours": D(1), "resolution_hours": D(3)}) is not None,
      "SLA policy from screen")

fx.finish()
