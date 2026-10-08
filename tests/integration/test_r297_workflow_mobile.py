"""R297: API گردش کار موبایل -- کارتابل یکپارچه، جزئیات، تصمیم تکرارناپذیر، یادداشت، سپردن، تایید دوباره با رمز."""
import os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r297"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crm_fixture import *  # noqa: F401,F403
import crm_fixture as fx
from fastapi.testclient import TestClient
from sqlalchemy import select, func
from peecha.db.models.audit import ActivityLog
from peecha.services import users as users_service
from peecha.services.workflow import definitions as defs, registry, runtime, tasks
from peecha.services.workflow.common import save_settings
from peecha.services.workflow.registry import ActionSpec, EntityAdapter, FieldSpec
from peecha_api.main import app
check, raises = fx.check, fx.raises

client = TestClient(app)


def mk_user(code, name):
    return users_service.create_user(code, name, "secret123", None, lang_id, False, [company_id], company_id).user_id


a1, a2, outsider = mk_user("mob1", "تاییدکنندهٔ یک"), mk_user("mob2", "تاییدکنندهٔ دو"), mk_user("mob3", "کاربر بی‌ربط")
requester = visitor.user_id
login = lambda u: {"Authorization": "Bearer " + client.post("/auth/login", json={"username": u, "password": "secret123"}).json()["access_token"]}
H1, H2, HO, HR = login("mob1"), login("mob2"), login("mob3"), login("visitor1")
idem = lambda h, k: {**h, "Idempotency-Key": k}

DOCS = {}
DONE = []


def _post(ctx):
    DONE.append(ctx.entity_id)
    return {}


registry.register_adapter(EntityAdapter(
    "REQ7", "درخواست خرید تجهیزات", "PURCHASE", lambda cid, eid: dict(DOCS[eid], doc_id=eid),
    fields=(FieldSpec("amount", "مبلغ", "money"), FieldSpec("requested_by", "درخواست‌کننده", "user")),
    actions={"post": ActionSpec("post", "ثبت نهایی", _post, risk="HIGH"), "note": ActionSpec("note", "یادداشت", lambda c: {})},
    title=lambda c: f"خرید تجهیزات {c['doc_id']}", submitter_field="requested_by",
    approval_context=lambda cid, eid: [("مبلغ", f"{DOCS[eid]['amount']:,}"), ("شرح", "لپ‌تاپ")]))


def graph(after, step_up=False):
    return {"trigger": {"type": "MANUAL"},
            "nodes": [{"id": "ap", "type": "APPROVAL", "label": "تایید مدیر", "approvers": [{"kind": "USER", "user_id": a1}],
                       **({"step_up": True} if step_up else {})},
                      {"id": "act", "type": "ACTION", "label": "اقدام", "action": after},
                      {"id": "ok", "type": "END", "label": "تایید", "outcome": "APPROVED"},
                      {"id": "no", "type": "END", "label": "رد", "outcome": "REJECTED"}],
            "edges": [{"from": "start", "to": "ap"}, {"from": "ap", "to": "act", "when": "approved"}, {"from": "act", "to": "ok"},
                      {"from": "ap", "to": "no", "when": "rejected"}]}


d_low = defs.create_definition(company_id, uid, code="LOW", name="تایید ساده", entity_type="REQ7", graph=graph("entity.note"))
d_high = defs.create_definition(company_id, uid, code="HIGH", name="تایید با ثبت", entity_type="REQ7", graph=graph("entity.post"))
for d in (d_low, d_high):
    defs.publish(company_id, uid, d)


def new(d, amount=1000):
    eid = len(DOCS) + 1
    DOCS[eid] = {"amount": amount, "requested_by": requester}
    iid = runtime.start_instance(company_id, d, "REQ7", eid, started_by=requester)
    return iid, tasks.list_tasks(company_id, instance_id=iid, status="OPEN")[0].task_id


i_low, t_low = new(d_low)
i_high, t_high = new(d_high)

# ===== کارتابل =====
box = client.get("/workflow/inbox", headers=H1).json()
wf = [x for x in box["items"] if x["source"] == "WF"]
check({x["ref_id"] for x in wf} == {t_low, t_high} and all(x["can_decide"] for x in wf), "inbox lists my workflow tasks")
check(client.get("/workflow/inbox", headers=HO).json()["count"] == 0, "outsider's inbox is empty")
check(client.get("/workflow/inbox", params={"source": "WF"}, headers=H1).json()["count"] == 2, "inbox filter by source")
check(client.get("/workflow/inbox").status_code == 401, "inbox needs login")

# ===== جزئیات و دسترسی =====
det = client.get(f"/workflow/tasks/{t_low}", headers=H1).json()
check(det["title"].startswith("تایید مدیر") and {"label": "شرح", "value": "لپ‌تاپ"} in det["context"], "detail has document context")
check([d["code"] for d in det["decisions"]][:2] == ["APPROVE", "REJECT"] and det["requires_step_up"] is False, "allowed decisions")
check(det["path"] and det["path"][0]["state"] == "done", "approval path")
check(client.get(f"/workflow/tasks/{t_low}", headers=HO).status_code == 404, "outsider cannot see task details")
check(client.get(f"/workflow/tasks/{t_low}", headers=HR).status_code == 200, "requester can follow own request")
check(client.get(f"/workflow/tasks/{t_low}", headers=HR).json()["decisions"] == [], "requester has no decisions")
check(client.get(f"/workflow/tasks/{t_high}", headers=H1).json()["requires_step_up"] is True,
      "approval leading to a high-risk action needs step-up")

# ===== یادداشت و تصمیم تکرارناپذیر =====
r = client.post(f"/workflow/tasks/{t_low}/comment", json={"text": "فاکتور پیوست شود"}, headers=idem(H1, "c-1"))
check(r.status_code == 200, "comment from mobile")
r1 = client.post(f"/workflow/tasks/{t_low}/decide", json={"decision": "APPROVE", "comment": "", "row_version": det["row_version"]},
                 headers=idem(H1, "d-1"))
r2 = client.post(f"/workflow/tasks/{t_low}/decide", json={"decision": "APPROVE", "comment": ""}, headers=idem(H1, "d-1"))
check(r1.status_code == 200 and r1.json()["closed"] and r2.json() == r1.json(), "same key replayed returns same answer")
check(runtime.get_instance(company_id, i_low).status_code == "COMPLETED", "process continued after mobile approval")
r3 = client.post(f"/workflow/tasks/{t_low}/decide", json={"decision": "APPROVE"}, headers=idem(H1, "d-2"))
check(r3.status_code == 400, "deciding a closed task again is refused (4xx: dropped from queue)")
with fx.new_session() as s:
    check(s.scalar(select(func.count()).select_from(ActivityLog).where(
        ActivityLog.entity_type == "WfTask", ActivityLog.entity_id == t_low, ActivityLog.action == "APPROVE",
        ActivityLog.changes["source"].astext == "mobile")) == 1,
        "mobile decision audited once")

# ===== تایید دوباره با رمز =====
r = client.post(f"/workflow/tasks/{t_high}/decide", json={"decision": "APPROVE"}, headers=idem(H1, "h-1"))
check(r.status_code == 403 and "رمز" in r.json()["detail"], "sensitive approval without password refused")
r = client.post(f"/workflow/tasks/{t_high}/decide", json={"decision": "APPROVE", "password": "wrong"}, headers=idem(H1, "h-2"))
check(r.status_code == 403 and DONE == [], "wrong password refused, nothing executed")
r = client.post(f"/workflow/tasks/{t_high}/decide", json={"decision": "APPROVE", "password": "secret123"}, headers=idem(H1, "h-3"))
check(r.status_code == 200 and DONE == [2], "correct password approves and runs the high-risk action")
i_rej, t_rej = new(d_high)
r = client.post(f"/workflow/tasks/{t_rej}/decide", json={"decision": "REJECT", "comment": "بودجه نداریم"}, headers=idem(H1, "h-4"))
check(r.status_code == 200 and runtime.get_instance(company_id, i_rej).outcome_code == "REJECTED", "rejection needs no password")
r = client.post(f"/workflow/tasks/{t_rej}/decide", json={"decision": "REJECT"}, headers=idem(H1, "h-5"))
check(r.status_code == 400, "closed task refused")

# سقف مبلغ از تنظیمات
save_settings(company_id, uid, mobile_step_up_amount=5000)
i_big, t_big = new(d_low, amount=9000)
i_small, t_small = new(d_low, amount=10)
check(client.get(f"/workflow/tasks/{t_big}", headers=H1).json()["requires_step_up"] is True and
      client.get(f"/workflow/tasks/{t_small}", headers=H1).json()["requires_step_up"] is False, "amount threshold from settings")

# ===== سپردن به همکار =====
cols = client.get("/workflow/colleagues", headers=H1).json()
check(any(c["user_id"] == a2 for c in cols) and all(c["user_id"] != a1 for c in cols), "colleagues list excludes me")
r = client.post(f"/workflow/tasks/{t_small}/delegate", json={"to_user_id": a2, "comment": "در مرخصی‌ام"}, headers=idem(H1, "g-1"))
check(r.status_code == 200 and any(x["ref_id"] == t_small for x in client.get("/workflow/inbox", headers=H2).json()["items"]),
      "delegated task appears in colleague's inbox")
check(client.post(f"/workflow/tasks/{t_small}/decide", json={"decision": "APPROVE"}, headers=idem(HO, "o-1")).status_code == 404,
      "outsider cannot decide")
r = client.post(f"/workflow/tasks/{t_small}/decide", json={"decision": "APPROVE"}, headers=idem(H2, "g-2"))
check(r.status_code == 200 and runtime.get_instance(company_id, i_small).status_code == "COMPLETED", "delegate decides from mobile")

fx.finish()
