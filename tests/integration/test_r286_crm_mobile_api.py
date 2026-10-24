import os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r286"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crm_fixture import *  # noqa: F401,F403
import crm_fixture as fx
from fastapi.testclient import TestClient
from peecha.db.models.commercial import CustomerActivity
from peecha.db.models.crm import Lead
from peecha.services import roles as roles_service
from peecha.services.crm import analytics, roles_setup
from peecha_api.main import app
check = fx.check

# قرارداد API که اپ موبایل (R286) استفاده می‌کند: ویزیتور با نقش «کارشناس فروش (CRM)»
client = TestClient(app)
roles_service.ensure_catalog()
roles = roles_setup.ensure_role_templates(company_id)
roles_service.set_user_role(visitor.user_id, roles["CRM_USER"], company_id, True)
login = lambda u: {"Authorization": "Bearer " + client.post("/auth/login", json={"username": u, "password": "secret123"}).json()["access_token"]}
vis = login("visitor1")
idem = lambda k: dict(vis, **{"Idempotency-Key": k})
fx.invoice(cust_a, 2_000_000, due_date=today + datetime.timedelta(days=30))
analytics.refresh_scores(company_id)

# ثبت سرنخ میدانی (صف آفلاین: کلید یکتا، تکراری رد نمی‌شود)
sources = client.get("/crm/lead-sources", headers=vis).json()
visitor_src = next(s["source_id"] for s in sources if s["code"] == "VISITOR")
body = {"full_name": "سرنخ مسیر", "mobile": "09121112233", "source_id": visitor_src, "estimated_value": "5000000", "allow_duplicate": True}
r1 = client.post("/crm/leads", json=body, headers=idem("lead-1"))
r2 = client.post("/crm/leads", json=body, headers=idem("lead-1"))
check(r1.status_code == 200 and r1.json() == r2.json(), "lead replay returns same id")
r3 = client.post("/crm/leads", json=body, headers=idem("lead-2"))
check(r3.status_code == 200 and r3.json()["lead_id"] != r1.json()["lead_id"], "duplicate allowed from field (no 4xx drop)")
with new_session() as s:
    check(s.get(Lead, r1.json()["lead_id"]).owner_user_id == visitor.user_id, "lead owned by field user")
mine = client.get("/crm/leads", params={"open_only": True, "mine": True}, headers=vis).json()
check(len(mine) == 2, "my open leads")

# پیگیری پس از ویزیت با شناسهٔ ویزیت
visit_id = field_sales_service.start_visit(company_id, cust_a, visitor.user_id)
due = str(today + datetime.timedelta(days=2))
act = client.post("/crm/activities", json={"activity_type_code": "FOLLOW_UP", "subject": "پیگیری ویزیت", "customer_detail_account_id": cust_a,
                                           "customer_visit_id": visit_id, "due_date": due}, headers=idem("act-1"))
check(act.status_code == 200, "follow-up after visit created")
aid = act.json()["activity_id"]
with new_session() as s:
    row = s.get(CustomerActivity, aid)
check(row.customer_visit_id == visit_id and row.created_by_user_id == visitor.user_id, "activity linked to visit, owned by creator")

# کارهای من (موبایل)
tasks = client.get("/crm/tasks", headers=vis).json()
check(any(a["activity_id"] == aid for a in tasks["buckets"]["week"] + tasks["buckets"]["tomorrow"]), "follow-up in my tasks")
check("open_tickets" in tasks and isinstance(tasks["counts"], dict), "tasks payload shape for mobile")

# انجام کار با پیگیری بعدی (تکرار امن)
payload = {"result_text": "سفارش گرفته شد", "follow_up_date": str(today + datetime.timedelta(days=7))}
c1 = client.post(f"/crm/activities/{aid}/complete", json=payload, headers=idem("done-1"))
c2 = client.post(f"/crm/activities/{aid}/complete", json=payload, headers=idem("done-1"))
check(c1.status_code == 200 and c1.json() == c2.json() and c1.json()["follow_up_activity_id"], "complete replay-safe with follow-up")

# شکایت از موبایل
t = client.post("/crm/tickets", json={"customer_detail_account_id": cust_a, "subject": "کالای آسیب‌دیده", "ticket_type": "COMPLAINT",
                                      "priority_code": "HIGH", "channel_code": "MOBILE_APP"}, headers=idem("tk-1"))
check(t.status_code == 200, "ticket from mobile")

# پروندهٔ ۳۶۰ برای کارت بینش موبایل
d = client.get(f"/crm/customers/{cust_a}/360", headers=vis).json()
check(all(k in d for k in ("summary", "smart_actions", "counts", "analytics", "loyalty")), "360 payload keys used by mobile")
check(d["analytics"]["health_label"] and isinstance(d["analytics"]["segments"], list), "analytics block for mobile")
check(d["counts"]["open_tickets"] >= 1 and d["counts"]["open_activities"] >= 1, "counts reflect mobile actions")

# کاربر بدون نقش CRM: ۴۰۳ (اپ کارت را پنهان می‌کند)
other = users_service.create_user("visitor2", "ویزیتور دو", "secret123", None, lang_id, False, [company_id], company_id)
check(client.get(f"/crm/customers/{cust_a}/360", headers=login("visitor2")).status_code == 403, "no CRM role → 403")

fx.finish()
