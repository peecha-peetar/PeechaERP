import os, sys, threading
os.environ["PEECHA_DB_NAME"] = "peecha_test_r291"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crm_fixture import *  # noqa: F401,F403
import crm_fixture as fx
from sqlalchemy import func, select, text
from peecha import numerals
from peecha.db.models.audit import ActivityLog
from peecha.db.models.security import Notification
from peecha.db.models.workflow import WfEvent, WfException, WfInstance, WfTimer
from peecha.services import roles as roles_service
from peecha.services.crm import activities as acts
from peecha.services.workflow import (conditions, definitions as defs, events, exceptions as wfx, registry, runtime,
                                      scheduler, simulate)
from peecha.services.workflow.common import WorkflowError, save_settings
from peecha.services.workflow.registry import ActionSpec, EntityAdapter, FieldSpec
check, raises = fx.check, fx.raises
NOW = datetime.datetime.now(datetime.timezone.utc)

# ===== Adapter آزمایشی (در عمل هر ماژول Adapter خودش را ثبت می‌کند) =====
DOCS = {1: {"amount": 750_000_000, "credit_available": 200_000_000, "due_date": today - datetime.timedelta(days=3),
            "customer_id": cust_a, "owner_user_id": visitor.user_id, "status": "DRAFT"},
        2: {"amount": 90_000_000, "credit_available": 500_000_000, "due_date": today + datetime.timedelta(days=5),
            "customer_id": cust_b, "owner_user_id": visitor.user_id, "status": "DRAFT"}}
CALLS = {"approve": 0, "flaky": 0, "bad": 0}
FLAKY = {"fail_times": 3}


def _approve(ctx):
    CALLS["approve"] += 1
    DOCS[ctx.entity_id]["status"] = "APPROVED"
    return {"approved": ctx.entity_id}


def _flaky(ctx):
    CALLS["flaky"] += 1
    if FLAKY["fail_times"] > 0:
        FLAKY["fail_times"] -= 1
        raise ConnectionError("bank api down")
    return {"ok": True}


def _bad(ctx):
    CALLS["bad"] += 1
    raise ValueError("ثبت پرداخت انجام نشد زیرا حساب تفصیلی مشتری معتبر نیست.")


registry.register_adapter(EntityAdapter(
    "TEST_DOC", "سند آزمایشی", "SALES", lambda cid, eid: dict(DOCS[eid], doc_id=eid),
    fields=(FieldSpec("amount", "مبلغ", "money"), FieldSpec("credit_available", "اعتبار آزاد", "money"),
            FieldSpec("due_date", "سررسید", "date"), FieldSpec("status", "وضعیت", "text"),
            FieldSpec("owner_user_id", "مسئول", "user")),
    events={"TEST_CREATED": "ثبت سند آزمایشی", "TEST_PAID": "دریافت وجه"},
    actions={"approve": ActionSpec("approve", "تایید سند", _approve, risk="HIGH",
                                   is_done=lambda cid, eid: DOCS[eid]["status"] == "APPROVED"),
             "flaky": ActionSpec("flaky", "پرداخت بانکی", _flaky),
             "bad": ActionSpec("bad", "ثبت پرداخت", _bad)},
    title=lambda c: f"سند آزمایشی {c.get('doc_id')}", form_code="crm_leads"))

# ===== ۱) شرط =====
ctx1 = dict(DOCS[1])
rule = {"all": [{"field": "amount", "op": ">", "value": "500,000,000"},
                {"field": "credit_available", "op": "<", "value_field": "amount"}]}
check(conditions.evaluate(rule, ctx1) and not conditions.evaluate(rule, DOCS[2]), "AND + field-to-field")
check(conditions.evaluate({"any": [{"field": "amount", "op": "<", "value": 1}, {"field": "status", "op": "=", "value": "DRAFT"}]}, ctx1), "OR")
check(not conditions.evaluate({"not": rule}, ctx1), "NOT")
check(conditions.evaluate({"field": "due_date", "op": "<", "value": {"days_from_today": 0}}, ctx1)
      and not conditions.evaluate({"field": "due_date", "op": "<", "value": {"days_from_today": 0}}, DOCS[2]), "date relative to today")
check(conditions.evaluate({"field": "amount", "op": "between", "value": ["۵۰۰٬۰۰۰٬۰۰۰", 800_000_000]}, ctx1), "between with Persian digits")
labels = {"amount": "مبلغ", "credit_available": "اعتبار آزاد"}
check(conditions.describe(rule, labels).startswith(f"(مبلغ بیشتر از {numerals.format_amount(500_000_000)} و اعتبار آزاد کمتر از «مبلغ»"),
      f"Persian description ({conditions.describe(rule, labels)})")
fmap = registry.require_adapter("TEST_DOC").field_map()
check(conditions.validate({"field": "nope", "op": ">", "value": 1}, fmap) and
      conditions.validate({"field": "amount", "op": "contains", "value": 1}, fmap) and
      not conditions.validate(rule, fmap), "condition validation")

# ===== ۲) تعریف، اعتبارسنجی، چرخهٔ عمر و نسخه =====
role = roles_service.create_role(company_id, "FIN_MGR", None)
bad_graph = {"trigger": {"type": "EVENT", "events": []},
             "nodes": [{"id": "a", "type": "ACTION", "label": "تایید خودکار", "action": "entity.approve"},
                       {"id": "lonely", "type": "NOTIFY", "label": "اعلان بی‌مسیر", "to": [{"kind": "ROLE", "role_id": 99999}], "title": "x"},
                       {"id": "w", "type": "CONDITION", "label": "حلقه", "rule": {"field": "amount", "op": ">", "value": 1}}],
             "edges": [{"from": "start", "to": "a"}, {"from": "a", "to": "w"}, {"from": "w", "to": "a", "when": "yes"},
                       {"from": "w", "to": "a", "when": "no"}]}
issues = [i.message for i in defs.validate_graph(company_id, bad_graph, "TEST_DOC")]
for needle, name in (("رویداد شروع", "missing trigger"), ("پایان ندارد", "missing end"), ("قابل دسترسی نیست", "unreachable"),
                     ("حلقهٔ بی‌پایان", "infinite loop"), ("بدون تایید انسانی", "high-risk without approval"),
                     ("وجود ندارد", "invalid role")):
    check(any(needle in m for m in issues), f"validation: {name}")

good = {"trigger": {"type": "EVENT", "events": ["TEST_CREATED"]},
        "nodes": [{"id": "c", "type": "CONDITION", "label": "مبلغ بالا؟", "rule": rule},
                  {"id": "n", "type": "NOTIFY", "label": "خبر به مسئول", "to": [{"kind": "OWNER"}], "title": "{عنوان}: مبلغ {مبلغ}"},
                  {"id": "f", "type": "ACTION", "label": "پیگیری", "action": "create_followup",
                   "params": {"subject": "بررسی {doc_id}", "customer_field": "customer_id", "assign_to": visitor.user_id}},
                  {"id": "e1", "type": "END", "label": "پایان", "outcome": "DONE"},
                  {"id": "e2", "type": "END", "label": "بدون اقدام", "outcome": "DONE"}],
        "edges": [{"from": "start", "to": "c"}, {"from": "c", "to": "n", "when": "yes"}, {"from": "c", "to": "e2", "when": "no"},
                  {"from": "n", "to": "f"}, {"from": "f", "to": "e1"}]}
d1 = defs.create_definition(company_id, uid, code="big_doc", name="سند مبلغ بالا", entity_type="TEST_DOC", graph=bad_graph)
check(raises(lambda: defs.publish(company_id, uid, d1), "پیش از انتشار"), "invalid graph cannot be published")
check(raises(lambda: defs.set_status(company_id, uid, d1, "ACTIVE"), "مجاز نیست"), "invalid lifecycle transition")
defs.save_draft(company_id, uid, d1, good)
defs.set_status(company_id, uid, d1, "TESTING")
v1 = defs.publish(company_id, uid, d1)
check(defs.get_definition(company_id, d1).status_code == "PUBLISHED", "published after validation")
defs.set_status(company_id, uid, d1, "ACTIVE")

# ===== ۳) رویداد ← شروع خودکار، بدون تکرار =====
n_acts = len(acts.list_activities(company_id, customer_detail_account_id=cust_a))
with new_session() as s:
    eid = events.publish(s, company_id, "TEST_CREATED", "TEST_DOC", 1, {"by": "test"}, actor_user_id=uid, dedupe_key="doc1-created")
    s.commit()
inst_rows = runtime.list_instances(company_id, entity_type="TEST_DOC", entity_id=1)
check(len(inst_rows) == 1 and inst_rows[0].status_code == "COMPLETED", f"event started workflow after commit ({[r.status_code for r in inst_rows]})")
check(len(acts.list_activities(company_id, customer_detail_account_id=cust_a)) == n_acts + 1, "action created real CRM follow-up")
with new_session() as s:
    dup = events.publish(s, company_id, "TEST_CREATED", "TEST_DOC", 1, {}, dedupe_key="doc1-created")
    s.commit()
    s.execute(text("UPDATE wf.events SET status_code = 'PENDING' WHERE event_id = :e"), {"e": eid})
    s.commit()
events.dispatch_pending(company_id)
check(dup is None and len(runtime.list_instances(company_id, entity_type="TEST_DOC", entity_id=1)) == 1
      and len(acts.list_activities(company_id, customer_detail_account_id=cust_a)) == n_acts + 1,
      "duplicate event / re-dispatch creates no duplicate transaction")
with new_session() as s:
    note = s.scalar(select(Notification).where(Notification.user_id == visitor.user_id, Notification.type_code == "WF_MESSAGE"))
check(note is not None and numerals.format_amount(750_000_000) in note.title, f"notify with Persian placeholders ({note and note.title})")
tl = runtime.timeline(company_id, inst_rows[0].instance_id)
check([r.kind for r in tl][:2] == ["START", "CONDITION"] and tl[-1].kind == "END", "timeline")
path = runtime.status_path(company_id, inst_rows[0].instance_id)
check(path[0] == ("ثبت و ارسال", "done") and all(st == "done" for _l, st in path), f"status path ({path})")
events.emit(company_id, "TEST_CREATED", "TEST_DOC", 2, {}, dedupe_key="doc2-created")
r2 = runtime.list_instances(company_id, entity_type="TEST_DOC", entity_id=2)[0]
check(r2.status_code == "COMPLETED" and next(r.detail for r in runtime.timeline(company_id, r2.instance_id) if r.kind == "CONDITION") == "خیر",
      "condition NO branch")

# نسخهٔ تازه نمونه‌های قبلی را تغییر نمی‌دهد
good2 = defs.get_graph(company_id, d1)
good2["nodes"][1]["title"] = "نسخهٔ دوم"
v2_id = defs.save_draft(company_id, uid, d1, good2)
check(v2_id != v1 and defs.get_graph(company_id, d1, v1)["nodes"][1]["title"] != "نسخهٔ دوم", "published version immutable")
defs.publish(company_id, uid, d1)
check(runtime.get_instance(company_id, inst_rows[0].instance_id).version_no == 1, "old instance keeps its version")
defs.set_status(company_id, uid, d1, "PAUSED")
events.emit(company_id, "TEST_CREATED", "TEST_DOC", 1, {}, dedupe_key="doc1-again")
check(len(runtime.list_instances(company_id, entity_type="TEST_DOC", entity_id=1)) == 1, "paused workflow does not start")
defs.set_status(company_id, uid, d1, "ARCHIVED")


def make(code, graph, entity="TEST_DOC"):
    d = defs.create_definition(company_id, uid, code=code, name=code, entity_type=entity, graph=graph)
    defs.publish(company_id, uid, d)
    return d


def manual(nodes, edges, settings=None):
    return {"trigger": {"type": "MANUAL"}, "nodes": nodes, "edges": edges, "settings": settings or {}}


END = {"id": "end", "type": "END", "label": "پایان", "outcome": "DONE"}
NOTE = lambda i: {"id": i, "type": "NOTIFY", "label": f"اعلان {i}", "to": [{"kind": "STARTER"}], "title": f"اعلان {i}"}

# ===== ۴) انتظار زمانی + ری‌استارت =====
d_wait = make("wait", manual([{"id": "w", "type": "WAIT", "label": "یک ساعت صبر", "hours": 1}, NOTE("n"), END],
                             [{"from": "start", "to": "w"}, {"from": "w", "to": "n"}, {"from": "n", "to": "end"}]))
iw = runtime.start_instance(company_id, d_wait, "TEST_DOC", 1, started_by=uid)
check(runtime.get_instance(company_id, iw).status_code == "WAITING", "waits on timer")
from peecha.db import base as db_base
db_base.reset_engine()
runtime._GRAPH_CACHE.clear()  # «ری‌استارت»: همهٔ حالت حافظه از بین می‌رود
scheduler.fire_due_timers(company_id, NOW + datetime.timedelta(minutes=30))
check(runtime.get_instance(company_id, iw).status_code == "WAITING", "timer not due yet")
scheduler.fire_due_timers(company_id, NOW + datetime.timedelta(hours=2))
check(runtime.get_instance(company_id, iw).status_code == "COMPLETED", "after restart waiting workflow continues on time")

# ===== ۵) انتظار تا رویداد =====
d_ev = make("wait_event", manual([{"id": "w", "type": "WAIT", "label": "تا دریافت وجه", "until_event": "TEST_PAID", "timeout_hours": 48},
                                  NOTE("paid"), NOTE("late"), END],
                                 [{"from": "start", "to": "w"}, {"from": "w", "to": "paid"}, {"from": "w", "to": "late", "when": "timeout"},
                                  {"from": "paid", "to": "end"}, {"from": "late", "to": "end"}]))
ie = runtime.start_instance(company_id, d_ev, "TEST_DOC", 2, started_by=uid)
events.emit(company_id, "TEST_PAID", "TEST_DOC", 1, {})
check(runtime.get_instance(company_id, ie).status_code == "WAITING", "other document's event does not resume")
events.emit(company_id, "TEST_PAID", "TEST_DOC", 2, {})
check(runtime.get_instance(company_id, ie).status_code == "COMPLETED" and
      any(r.title == "اعلان paid" for r in runtime.timeline(company_id, ie)), "resumed by event")
with new_session() as s:
    check(s.scalar(select(func.count()).select_from(WfTimer).where(WfTimer.instance_id == ie, WfTimer.status_code == "PENDING")) == 0,
          "timeout timer cancelled")

# ===== ۶) شاخهٔ هم‌زمان =====
d_par = make("parallel", manual([{"id": "p", "type": "PARALLEL", "label": "هم‌زمان"}, NOTE("a"), NOTE("b"),
                                 {"id": "j", "type": "JOIN", "label": "پیوستن"}, END],
                                [{"from": "start", "to": "p"}, {"from": "p", "to": "a"}, {"from": "p", "to": "b"},
                                 {"from": "a", "to": "j"}, {"from": "b", "to": "j"}, {"from": "j", "to": "end"}]))
ip = runtime.start_instance(company_id, d_par, "TEST_DOC", 1, started_by=uid)
kinds = [r.kind for r in runtime.timeline(company_id, ip)]
check(runtime.get_instance(company_id, ip).status_code == "COMPLETED" and kinds.count("NOTIFY") == 2 and kinds.count("JOIN") == 2
      and kinds.count("END") == 2, f"parallel branches join once ({kinds})")

# ===== ۷) Retry ← Exception ← حل انسانی (سناریوی ۸) =====
APPROVE_NODE = {"id": "ap", "type": "APPROVAL", "label": "تایید", "approvers": [{"kind": "ROLE", "role_id": role.role_id}]}
d_flaky = make("flaky", manual([{"id": "x", "type": "ACTION", "label": "پرداخت بانکی", "action": "entity.flaky",
                                 "retry": {"max": 3, "backoff_minutes": 1}}, END],
                               [{"from": "start", "to": "x"}, {"from": "x", "to": "end"}]))
ix = runtime.start_instance(company_id, d_flaky, "TEST_DOC", 1, started_by=uid)
check(runtime.get_instance(company_id, ix).status_code == "WAITING" and CALLS["flaky"] == 1, "transient failure → retry scheduled")
scheduler.fire_due_timers(company_id, NOW + datetime.timedelta(minutes=5))
scheduler.fire_due_timers(company_id, NOW + datetime.timedelta(minutes=30))
exs = wfx.list_exceptions(company_id, instance_id=ix)
check(CALLS["flaky"] == 3 and len(exs) == 1 and "ارتباط" in exs[0].reason and "bank api" in (exs[0].technical_detail or ""),
      f"3 attempts → exception with friendly reason ({CALLS['flaky']})")
check(wfx.retry(company_id, exs[0].exception_id, uid, "بانک وصل شد") and runtime.get_instance(company_id, ix).status_code == "COMPLETED"
      and CALLS["flaky"] == 4, "human retry resolves")
d_bad = make("bad", manual([{"id": "x", "type": "ACTION", "label": "ثبت پرداخت", "action": "entity.bad"}, END],
                           [{"from": "start", "to": "x"}, {"from": "x", "to": "end"}]))
ib = runtime.start_instance(company_id, d_bad, "TEST_DOC", 1, started_by=uid)
exb = wfx.list_exceptions(company_id, instance_id=ib)
check(CALLS["bad"] == 1 and exb and exb[0].reason.startswith("ثبت پرداخت انجام نشد"), "business error → no blind retry, clear message")
check(raises(lambda: wfx.resolve(company_id, exb[0].exception_id, uid, ""), "الزامی"), "resolution needs a note")
wfx.resolve(company_id, exb[0].exception_id, uid, "دستی ثبت شد")
check(runtime.get_instance(company_id, ib).status_code == "COMPLETED" and CALLS["bad"] == 1, "manual resolution continues without re-running")

# ===== ۸) Idempotency اقدام =====
with new_session() as s:
    s.execute(text("UPDATE wf.events SET status_code = 'PENDING' WHERE event_id = :e"), {"e": eid})
    s.commit()
events.dispatch_pending(company_id)
check(len(acts.list_activities(company_id, customer_detail_account_id=cust_a)) == n_acts + 1, "re-processing old event is a no-op")
DOCS[2]["status"] = "APPROVED"
before = CALLS["approve"]
d_appr = make("approve_flow", manual([{**APPROVE_NODE}, {"id": "x", "type": "ACTION", "label": "تایید سند", "action": "entity.approve"},
                                      END, {"id": "rej", "type": "END", "label": "رد", "outcome": "REJECTED"}],
                                     [{"from": "start", "to": "ap"}, {"from": "ap", "to": "x", "when": "approved"},
                                      {"from": "ap", "to": "rej", "when": "rejected"}, {"from": "x", "to": "end"}]))
ia = runtime.start_instance(company_id, d_appr, "TEST_DOC", 2, started_by=uid)
check(runtime.get_instance(company_id, ia).status_code == "WAITING", "approval node waits for a human decision")

# ===== ۹) محافظت از حلقه =====
d_loop = make("loop", {"trigger": {"type": "MANUAL"}, "settings": {"max_steps": 12},
                       "nodes": [{"id": "w", "type": "WAIT", "label": "انتظار صفر", "minutes": 0.0001}, NOTE("n"), END,
                                 {"id": "c", "type": "CONDITION", "label": "باز هم؟", "rule": {"field": "amount", "op": ">", "value": 0}}],
                       "edges": [{"from": "start", "to": "w"}, {"from": "w", "to": "n"}, {"from": "n", "to": "c"},
                                 {"from": "c", "to": "w", "when": "yes"}, {"from": "c", "to": "end", "when": "no"}]})
il = runtime.start_instance(company_id, d_loop, "TEST_DOC", 1, started_by=uid)
for _ in range(10):
    scheduler.fire_due_timers(company_id, NOW + datetime.timedelta(hours=1))
loop_row = runtime.get_instance(company_id, il)
check(loop_row.status_code == "FAILED" and "حد مجاز" in (loop_row.last_error or ""), "execution limit stops loops")

# زنجیرهٔ رویداد: الف ← ب ← الف ...
chain_a = make("chain_a", {"trigger": {"type": "EVENT", "events": ["TEST_CREATED"]},
                           "nodes": [{"id": "x", "type": "ACTION", "label": "انتشار", "action": "emit_event", "params": {"event": "TEST_PAID"}}, END],
                           "edges": [{"from": "start", "to": "x"}, {"from": "x", "to": "end"}]})
chain_b = make("chain_b", {"trigger": {"type": "EVENT", "events": ["TEST_PAID"]},
                           "nodes": [{"id": "x", "type": "ACTION", "label": "انتشار", "action": "emit_event", "params": {"event": "TEST_CREATED"}}, END],
                           "edges": [{"from": "start", "to": "x"}, {"from": "x", "to": "end"}]})
events.emit(company_id, "TEST_CREATED", "TEST_DOC", 1, {}, dedupe_key="chain-start")
with new_session() as s:
    chained = s.scalar(select(func.count()).select_from(WfInstance).where(WfInstance.definition_id.in_((chain_a, chain_b))))
check(chained == 2, f"event chain A → B → A stopped ({chained} instances)")
circ = {"trigger": {"type": "EVENT", "events": ["TEST_CREATED"]},
        "nodes": [{"id": "x", "type": "ACTION", "label": "انتشار", "action": "emit_event", "params": {"event": "TEST_CREATED"}}, END],
        "edges": [{"from": "start", "to": "x"}, {"from": "x", "to": "end"}]}
check(any("وابستگی دوری" in i.message for i in defs.validate_graph(company_id, circ, "TEST_DOC")), "circular dependency detected")
for d in (chain_a, chain_b):
    defs.set_status(company_id, uid, d, "ARCHIVED")

# ===== ۱۰) بازیابی اقدام رهاشده (قطعی وسط اجرا) =====
FLAKY["fail_times"] = 0
d_rec = make("recover", manual([{"id": "x", "type": "ACTION", "label": "پرداخت", "action": "entity.flaky"}, END],
                               [{"from": "start", "to": "x"}, {"from": "x", "to": "end"}]))
ir = runtime.start_instance(company_id, d_rec, "TEST_DOC", 1, started_by=uid, run=False)
runtime._step_once(ir)  # گره شروع
pending = runtime._step_once(ir)  # «در حال اجرا» ثبت شد و برنامه همین‌جا بسته شد
check(isinstance(pending, dict) and runtime.get_instance(company_id, ir).status_code == "RUNNING", "action marked running")
with new_session() as s:
    s.execute(text("UPDATE wf.instances SET tokens = jsonb_set(tokens, '{0,since}', to_jsonb(CAST(:t AS text))) WHERE instance_id = :i"),
              {"t": (NOW - datetime.timedelta(hours=1)).isoformat(), "i": ir})
    s.commit()
calls = CALLS["flaky"]
check(runtime.recover_stuck(company_id) == 1 and runtime.get_instance(company_id, ir).status_code == "COMPLETED"
      and CALLS["flaky"] == calls + 1, "stuck action recovered after restart")

# ===== ۱۱) آزمون/اجرای آزمایشی بدون تغییر =====
with new_session() as s:
    inst_before = s.scalar(select(func.count()).select_from(WfInstance))
trace = simulate.simulate(company_id, good, "TEST_DOC", context={"amount": 750_000_000, "credit_available": 200_000_000})
with new_session() as s:
    inst_after = s.scalar(select(func.count()).select_from(WfInstance))
check([t.node_type for t in trace] == ["START", "CONDITION", "NOTIFY", "ACTION", "END"] and all(t.ok for t in trace)
      and inst_after == inst_before, f"dry run traces without data changes ({[t.node_type for t in trace]})")
low = simulate.simulate(company_id, good, "TEST_DOC", context={"amount": 1, "credit_available": 5})
check(low[1].result.endswith("خیر") and low[-1].node_type == "END", "dry run NO branch")

# ===== ۱۲) کارتابل قدیمی: قفل، تفکیک وظایف، اتمیک =====
from peecha.services import cartable, users as users_service
approver = users_service.create_user("approver1", "تاییدکننده", "secret123", None, lang_id, False, [company_id], company_id)
roles_service.set_user_role(approver.user_id, role.role_id, company_id, True)
roles_service.set_user_role(uid, role.role_id, company_id, True)
HANDLED = {"ok": 0, "fail": True}


def _on_approved(cid, rid, by):
    if HANDLED["fail"]:
        raise ValueError("سند قابل نهایی‌شدن نیست.")
    HANDLED["ok"] += 1


cartable.register_handler("crm_leads", on_approved=_on_approved, on_rejected=lambda *a: None, describe=lambda c, r: f"سرنخ {r}")
cartable.save_workflow_steps(company_id, "crm_leads", True, [role.role_id])
item = cartable.submit_for_approval(company_id, "crm_leads", 77, "CREATE", uid)
check(raises(lambda: cartable.approve_item(item, uid), "تفکیک وظایف"), "submitter cannot approve own request")
check(raises(lambda: cartable.approve_item(item, approver.user_id), "نهایی‌شدن"), "handler failure keeps item pending")
check(any(t.cartable_item_id == item for t in cartable.list_my_tasks(approver.user_id, company_id)), "still pending after failure")
HANDLED["fail"] = False
results = []


def _try():
    try:
        cartable.approve_item(item, approver.user_id)
        results.append("ok")
    except ValueError as exc:
        results.append(str(exc))


threads = [threading.Thread(target=_try) for _ in range(2)]
[t.start() for t in threads]
[t.join() for t in threads]
check(results.count("ok") == 1 and HANDLED["ok"] == 1, f"concurrent approvals: exactly one wins ({results})")
save_settings(company_id, uid, allow_self_approval=True)
item2 = cartable.submit_for_approval(company_id, "crm_leads", 78, "CREATE", uid)
cartable.approve_item(item2, uid)
check(HANDLED["ok"] == 2, "self approval allowed when company policy permits")
save_settings(company_id, uid, allow_self_approval=False)
with new_session() as s:
    audited = {(a.entity_type, a.action) for a in s.scalars(select(ActivityLog).where(ActivityLog.company_id == company_id))}
check({("CartableItem", "APPROVE"), ("WfInstance", "START"), ("WfInstance", "COMPLETE"), ("WfDefinition", "PUBLISH")} <= audited,
      "approvals and workflow steps audited")

# ===== ۱۳) زمان‌بند کامل و اجرای دوره‌ای =====
counts = scheduler.run_due(company_id)
check(set(counts) >= {"recovered", "timers", "schedules", "scans", "events"}, f"scheduler tick ({counts})")
d_sched = make("daily", {"trigger": {"type": "SCHEDULE", "every": "DAY", "at": "00:00"}, "nodes": [NOTE("n"), END],
                         "edges": [{"from": "start", "to": "n"}, {"from": "n", "to": "end"}]}, entity=None)
scheduler.run_schedules(company_id)
scheduler.run_schedules(company_id)
check(len(runtime.list_instances(company_id, definition_id=d_sched)) == 1, "scheduled workflow once per period")
with new_session() as s:
    open_ex = s.scalar(select(func.count()).select_from(WfException).where(WfException.company_id == company_id,
                                                                           WfException.status_code == "OPEN"))
check(open_ex >= 1, "loop failure left an open exception for review")

fx.finish()
