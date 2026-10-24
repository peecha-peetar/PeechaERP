import os, sys, threading
os.environ["PEECHA_DB_NAME"] = "peecha_test_r292"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crm_fixture import *  # noqa: F401,F403
import crm_fixture as fx
from sqlalchemy import func, select, text
from peecha.db.models.audit import ActivityLog
from peecha.db.models.security import Notification
from peecha.db.models.workflow import WfException, WfTask, WfTaskDecision
from peecha.services import hr as hr_service, roles as roles_service, users as users_service
from peecha.services.workflow import definitions as defs, registry, routing, runtime, scheduler, tasks
from peecha.services.workflow.registry import ActionSpec, EntityAdapter, FieldSpec
check, raises = fx.check, fx.raises
NOW = datetime.datetime.now(datetime.timezone.utc)


def mk_user(code, name):
    return users_service.create_user(code, name, "secret123", None, lang_id, False, [company_id], company_id).user_id


a1, a2, a3, d1 = mk_user("app1", "تاییدکنندهٔ یک"), mk_user("app2", "تاییدکنندهٔ دو"), mk_user("app3", "تاییدکنندهٔ سه"), \
    mk_user("dep1", "جانشین")
requester = visitor.user_id
role = roles_service.create_role(company_id, "FIN", None)
for u in (a1, a2, requester):  # درخواست‌کننده هم عضو نقش است ← تفکیک وظایف باید او را کنار بگذارد
    roles_service.set_user_role(u, role.role_id, company_id, True)

DOCS = {}
FINAL = {"n": 0}


def _finalize(ctx):
    FINAL["n"] += 1
    DOCS[ctx.entity_id]["status"] = "APPROVED"
    return {}


registry.register_adapter(EntityAdapter(
    "REQ", "درخواست آزمایشی", "SALES", lambda cid, eid: dict(DOCS[eid], doc_id=eid),
    fields=(FieldSpec("amount", "مبلغ", "money"), FieldSpec("requested_by", "درخواست‌کننده", "user"),
            FieldSpec("warehouse_id", "انبار", "number")),
    actions={"finalize": ActionSpec("finalize", "نهایی‌کردن", _finalize, risk="HIGH",
                                    is_done=lambda cid, eid: DOCS[eid]["status"] == "APPROVED")},
    title=lambda c: f"درخواست {c['doc_id']}", submitter_field="requested_by",
    approval_context=lambda cid, eid: [("مبلغ", str(DOCS[eid]["amount"])), ("وضعیت", DOCS[eid]["status"])]))


def doc(amount=1000):
    eid = len(DOCS) + 1
    DOCS[eid] = {"amount": amount, "requested_by": requester, "warehouse_id": warehouse_id, "status": "DRAFT"}
    return eid


def approval_flow(code, approvers, **opts):
    node = {"id": "ap", "type": "APPROVAL", "label": "تایید مالی", "approvers": approvers, **opts}
    nodes = [node, {"id": "fin", "type": "ACTION", "label": "نهایی‌کردن", "action": "entity.finalize"},
             {"id": "ok", "type": "END", "label": "تایید", "outcome": "APPROVED"},
             {"id": "no", "type": "END", "label": "رد", "outcome": "REJECTED"}]
    edges = [{"from": "start", "to": "ap"}, {"from": "ap", "to": "fin", "when": "approved"},
             {"from": "ap", "to": "no", "when": "rejected"}, {"from": "fin", "to": "ok"}]
    extra_nodes, extra_edges = opts.pop("extra", ([], []))
    node.pop("extra", None)
    d = defs.create_definition(company_id, uid, code=code, name=code, entity_type="REQ",
                               graph={"trigger": {"type": "MANUAL"}, "nodes": nodes + extra_nodes, "edges": edges + extra_edges})
    defs.publish(company_id, uid, d)
    return d


def start(d, eid):
    return runtime.start_instance(company_id, d, "REQ", eid, started_by=requester)


def open_task(iid):
    rows = tasks.list_tasks(company_id, instance_id=iid, status="OPEN")
    return rows[0] if rows else None


def status(iid):
    return runtime.get_instance(company_id, iid).status_code


ROLE = [{"kind": "ROLE", "role_id": role.role_id}]

# ===== ۱) تایید تک‌مرحله‌ای (اولین تصمیم) + تفکیک وظایف =====
d_any = approval_flow("any", ROLE)
e1 = doc()
i1 = start(d_any, e1)
t1 = open_task(i1)
detail = tasks.task_detail(company_id, t1.task_id, a1)
seat_names = [a[0] for a in detail.assignees]
check(status(i1) == "WAITING" and len(seat_names) == 2 and "ویزیتور یک" not in seat_names,
      f"approval waits; requester excluded from approvers ({seat_names})")
check([c for c, _ in detail.decisions] == ["APPROVE", "REJECT"] and ("مبلغ", "1000") in detail.context
      and detail.path[0] == ("ثبت و ارسال", "done") and ("تایید مالی", "current") in detail.path,
      f"task detail: decisions, context, path ({detail.path})")
with new_session() as s:
    notes = {n.user_id for n in s.scalars(select(Notification).where(Notification.type_code == "WF_APPROVAL_REQUIRED"))}
check(notes == {a1, a2}, "approvers notified")
check(t1.task_id in {t.task_id for t in tasks.list_my_tasks(company_id, a1)}, "task in approver's inbox")
check(raises(lambda: tasks.decide(company_id, t1.task_id, requester, "APPROVE"), "ارجاع نشده"), "requester cannot decide")
check(raises(lambda: tasks.decide(company_id, t1.task_id, a1, "APPROVE", row_version=t1.row_version + 5), "هم‌زمان"),
      "stale row_version rejected")
r = tasks.decide(company_id, t1.task_id, a1, "APPROVE", "مورد تایید", row_version=t1.row_version, client_ref="m-1")
check(r.closed and r.status_code == "APPROVED" and status(i1) == "COMPLETED" and DOCS[e1]["status"] == "APPROVED",
      "approved → high-risk action ran → completed")
again = tasks.decide(company_id, t1.task_id, a1, "APPROVE", client_ref="m-1")
with new_session() as s:
    n_dec = s.scalar(select(func.count()).select_from(WfTaskDecision).where(WfTaskDecision.task_id == t1.task_id,
                                                                            WfTaskDecision.decision == "APPROVE"))
check("قبلاً ثبت" in again.message and n_dec == 1 and FINAL["n"] == 1, "mobile retry with same client_ref is a no-op")
check(raises(lambda: tasks.decide(company_id, t1.task_id, a2, "APPROVE"), "قبلاً بسته"), "closed task cannot be decided")
check(t1.task_id not in {t.task_id for t in tasks.list_my_tasks(company_id, a2)}, "closed task leaves inboxes")
tl = runtime.timeline(company_id, i1)
check(any(r.kind == "DECISION" and r.actor == "تاییدکنندهٔ یک" and r.detail == "مورد تایید" for r in tl), "decision on timeline")

# ===== ۲) رد با توضیح اجباری =====
e2 = doc()
i2 = start(d_any, e2)
t2 = open_task(i2)
check(raises(lambda: tasks.decide(company_id, t2.task_id, a2, "REJECT", ""), "علت رد"), "reject needs a reason")
check(raises(lambda: tasks.decide(company_id, t2.task_id, a2, "CHANGES", "x"), "مجاز نیست"), "changes not allowed without path")
tasks.decide(company_id, t2.task_id, a2, "REJECT", "مدارک ناقص است")
inst2 = runtime.get_instance(company_id, i2)
with new_session() as s:
    rej_note = s.scalar(select(Notification).where(Notification.user_id == requester, Notification.title.like("%رد شد%")))
check(inst2.status_code == "COMPLETED" and inst2.outcome_code == "REJECTED" and DOCS[e2]["status"] == "DRAFT"
      and rej_note is not None and rej_note.body == "مدارک ناقص است", "rejected path + requester informed")

# ===== ۳) همه باید تایید کنند =====
d_all = approval_flow("all", ROLE, mode="ALL")
i3 = start(d_all, doc())
t3 = open_task(i3)
r = tasks.decide(company_id, t3.task_id, a1, "APPROVE")
check(not r.closed and "بقیه" in r.message and status(i3) == "WAITING", "ALL: one approval is not enough")
check(raises(lambda: tasks.decide(company_id, t3.task_id, a1, "APPROVE"), "قبلاً برای این کار تصمیم"), "no double vote")
tasks.decide(company_id, t3.task_id, a2, "APPROVE")
check(status(i3) == "COMPLETED", "ALL: everyone approved")
i3b = start(d_all, doc())
t3b = open_task(i3b)
tasks.decide(company_id, t3b.task_id, a1, "APPROVE")
tasks.decide(company_id, t3b.task_id, a2, "REJECT", "مبلغ زیاد است")
check(runtime.get_instance(company_id, i3b).outcome_code == "REJECTED", "ALL: one rejection rejects")

# ===== ۴) درصدی =====
USERS3 = [{"kind": "USER", "user_id": u} for u in (a1, a2, a3)]
d_pct = approval_flow("pct", USERS3, mode="PERCENT", percent=60)
i4 = start(d_pct, doc())
t4 = open_task(i4)
tasks.decide(company_id, t4.task_id, a1, "APPROVE")
tasks.decide(company_id, t4.task_id, a2, "REJECT", "نه")
check(status(i4) == "WAITING", "PERCENT: 1 of 3 approved, still reachable")
tasks.decide(company_id, t4.task_id, a3, "APPROVE")
check(status(i4) == "COMPLETED" and runtime.get_instance(company_id, i4).outcome_code == "APPROVED", "PERCENT: 2 of 3 ≥ 60%")
i4b = start(d_pct, doc())
t4b = open_task(i4b)
tasks.decide(company_id, t4b.task_id, a1, "REJECT", "نه")
tasks.decide(company_id, t4b.task_id, a2, "REJECT", "نه")
check(runtime.get_instance(company_id, i4b).outcome_code == "REJECTED", "PERCENT: unreachable → rejected early")

# ===== ۵) ترتیبی =====
d_seq = approval_flow("seq", [{"kind": "USER", "user_id": a1}, {"kind": "USER", "user_id": a3}], mode="SEQUENTIAL")
i5 = start(d_seq, doc())
t5 = open_task(i5)
check(raises(lambda: tasks.decide(company_id, t5.task_id, a3, "APPROVE"), "نوبت"), "SEQUENTIAL: second waits for turn")
check(t5.task_id not in {t.task_id for t in tasks.list_my_tasks(company_id, a3)}, "queued task hidden from inbox")
tasks.decide(company_id, t5.task_id, a1, "APPROVE")
check(t5.task_id in {t.task_id for t in tasks.list_my_tasks(company_id, a3)} and status(i5) == "WAITING", "next approver activated")
tasks.decide(company_id, t5.task_id, a3, "APPROVE")
check(status(i5) == "COMPLETED", "SEQUENTIAL: all levels approved")

# ===== ۶) برگشت برای اصلاح ← کار درخواست‌کننده ← تایید دوباره =====
fix_node = {"id": "fix", "type": "TASK", "label": "اصلاح درخواست", "assignees": [{"kind": "STARTER"}],
            "fields": [{"key": "note", "label": "توضیح اصلاح", "kind": "text", "required": True},
                       {"key": "new_amount", "label": "مبلغ جدید", "kind": "number"}]}
d_chg = approval_flow("chg", ROLE, extra=([fix_node], [{"from": "ap", "to": "fix", "when": "changes"},
                                                         {"from": "fix", "to": "ap", "when": "done"}]))
check(not defs.errors(defs.validate_graph(company_id, defs.get_graph(company_id, d_chg), "REQ")), "changes loop through a task is valid")
i6 = start(d_chg, doc())
t6 = open_task(i6)
check(raises(lambda: tasks.decide(company_id, t6.task_id, a1, "CHANGES"), "موارد اصلاحی"), "changes need a note")
tasks.decide(company_id, t6.task_id, a1, "CHANGES", "پیش‌فاکتور پیوست شود")
fix = open_task(i6)
check(fix.kind == "TASK" and fix.task_id in {t.task_id for t in tasks.list_my_tasks(company_id, requester)}, "fix task to requester")
check(raises(lambda: tasks.decide(company_id, fix.task_id, requester, "DONE", data={"new_amount": "۲۰۰"}), "«توضیح اصلاح» را وارد"),
      "required task field")
check(raises(lambda: tasks.decide(company_id, fix.task_id, requester, "DONE", data={"note": "x", "new_amount": "abc"}), "عدد"),
      "number field validated")
tasks.decide(company_id, fix.task_id, requester, "DONE", data={"note": "پیوست شد", "new_amount": "۱٬۲۰۰"})
again6 = open_task(i6)
with new_session() as s:
    vars6 = s.execute(text("SELECT variables FROM wf.instances WHERE instance_id = :i"), {"i": i6}).scalar()
check(again6.kind == "APPROVAL" and again6.task_id != t6.task_id and vars6["vars"]["fix"]["new_amount"] == "1200",
      f"resubmitted for approval with entered data ({vars6.get('vars')})")
tasks.decide(company_id, again6.task_id, a2, "APPROVE")
check(status(i6) == "COMPLETED", "approved after correction")

# ===== ۷) تصمیم هم‌زمان: فقط یکی برنده =====
i7 = start(d_any, doc())
t7 = open_task(i7)
results, before = [], FINAL["n"]


def _try(u):
    try:
        tasks.decide(company_id, t7.task_id, u, "APPROVE")
        results.append("ok")
    except ValueError as exc:
        results.append(str(exc))


threads = [threading.Thread(target=_try, args=(u,)) for u in (a1, a2)]
[t.start() for t in threads]
[t.join() for t in threads]
check(results.count("ok") == 1 and FINAL["n"] == before + 1 and status(i7) == "COMPLETED",
      f"concurrent decisions: exactly one wins, action runs once ({results})")

# ===== ۸) تفویض اختیار =====
check(raises(lambda: tasks.create_delegation(company_id, a2, a1, d1, today, today), "فقط خود کاربر"), "only self or manager delegates")
i8 = start(d_any, doc())  # کار باز پیش از تفویض
dl = tasks.create_delegation(company_id, a1, a1, d1, today, today + datetime.timedelta(days=3), reason="مرخصی")
check(raises(lambda: tasks.create_delegation(company_id, d1, d1, a1, today, today), "دوطرفه"), "two-way delegation blocked")
t8 = open_task(i8)
mine = {t.task_id: t for t in tasks.list_my_tasks(company_id, d1)}
check(t8.task_id in mine and mine[t8.task_id].on_behalf_of == "تاییدکنندهٔ یک" and
      t8.task_id not in {t.task_id for t in tasks.list_my_tasks(company_id, a1)}, "open task moved to deputy")
i8b = start(d_any, doc())  # کار تازه در دورهٔ تفویض
t8b = open_task(i8b)
check(t8b.task_id in {t.task_id for t in tasks.list_my_tasks(company_id, d1)}, "new task routed to deputy")
tasks.decide(company_id, t8b.task_id, d1, "APPROVE", "به جای همکار")
with new_session() as s:
    dec = s.scalar(select(WfTaskDecision).where(WfTaskDecision.task_id == t8b.task_id, WfTaskDecision.decision == "APPROVE"))
check(dec.user_id == d1 and dec.on_behalf_of_user_id == a1 and
      any("به جای تاییدکنندهٔ یک" in r.actor for r in runtime.timeline(company_id, i8b) if r.kind == "DECISION"),
      "deputy decision recorded on behalf of original")
check(any(r.is_current and r.to_name == "جانشین" for r in tasks.list_delegations(company_id, a1)), "delegation listed")
tasks.end_delegation(company_id, dl, a1)
i8c = start(d_any, doc())
check(open_task(i8c).task_id in {t.task_id for t in tasks.list_my_tasks(company_id, a1)},
      "after delegation ends tasks go to original again")

# ===== ۹) واگذاری دستی + منع واگذاری به درخواست‌کننده =====
t8c = open_task(i8c)
check(raises(lambda: tasks.delegate_task(company_id, t8c.task_id, a1, requester), "تفکیک وظایف"), "cannot hand approval to requester")
tasks.delegate_task(company_id, t8c.task_id, a1, a3, "شما بررسی کنید")
check(raises(lambda: tasks.decide(company_id, t8c.task_id, a1, "APPROVE"), "ارجاع نشده"), "delegator no longer decides")
tasks.decide(company_id, t8c.task_id, a3, "APPROVE")
check(status(i8c) == "COMPLETED", "delegate decided")

# ===== ۱۰) کسی پیدا نشد ← مورد بررسی ← ارجاع مدیر =====
empty_role = roles_service.create_role(company_id, "EMPTY", None)
d_none = approval_flow("none", [{"kind": "ROLE", "role_id": empty_role.role_id}])
i10 = start(d_none, doc())
t10 = open_task(i10)
with new_session() as s:
    ex10 = s.scalar(select(WfException).where(WfException.instance_id == i10))
check(t10 is not None and status(i10) == "WAITING" and ex10 is not None and ex10.status_code == "OPEN" and "کسی پیدا نشد" in ex10.title,
      "no approver → exception, instance keeps waiting")
check(raises(lambda: tasks.reassign_task(company_id, t10.task_id, a1, [a3]), "فقط مدیر"), "only managers reassign")
check(raises(lambda: tasks.reassign_task(company_id, t10.task_id, uid, [requester]), "تفکیک وظایف"), "reassign respects SoD")
tasks.reassign_task(company_id, t10.task_id, uid, [a3], "به جای مدیر مالی")
with new_session() as s:
    check(s.get(WfException, ex10.exception_id).status_code == "RESOLVED", "exception resolved by reassignment")
tasks.decide(company_id, t10.task_id, a3, "APPROVE")
check(status(i10) == "COMPLETED", "reassigned approver finished it")

# ===== ۱۱) پایان مهلت =====
d_to = approval_flow("timeout", ROLE, timeout_hours=24, extra=(
    [{"id": "late", "type": "NOTIFY", "label": "اعلام تاخیر", "to": [{"kind": "STARTER"}], "title": "مهلت تایید تمام شد"}],
    [{"from": "ap", "to": "late", "when": "timeout"}, {"from": "late", "to": "no"}]))
i11 = start(d_to, doc())
t11 = open_task(i11)
scheduler.fire_due_timers(company_id, NOW + datetime.timedelta(hours=25))
with new_session() as s:
    st11 = s.get(WfTask, t11.task_id).status_code
check(st11 == "EXPIRED" and status(i11) == "COMPLETED" and
      any(r.title == "اعلام تاخیر" for r in runtime.timeline(company_id, i11)), "timeout path + task expired")
check(raises(lambda: tasks.decide(company_id, t11.task_id, a1, "APPROVE"), "قبلاً بسته"), "expired task cannot be decided")

# ===== ۱۲) پس‌گرفتن درخواست =====
i12 = start(d_any, doc())
t12 = open_task(i12)
check(raises(lambda: tasks.withdraw_request(company_id, i12, a3), "فقط درخواست‌کننده"), "others cannot withdraw")
tasks.withdraw_request(company_id, i12, requester, "دیگر لازم نیست")
with new_session() as s:
    check(s.get(WfTask, t12.task_id).status_code == "CANCELLED" and status(i12) == "CANCELLED", "withdraw cancels open task")

# ===== ۱۳) مسیر سازمانی: مدیر مستقیم و مدیر واحد =====
unit_parent = hr_service.create_org_unit(company_id, "HQ", "مدیریت", None, None)
unit = hr_service.create_org_unit(company_id, "SALES", "فروش", unit_parent, None)
pos = hr_service.create_position(company_id, "P1", "کارشناس", unit, None, 5)
emp_req = hr_service.create_employee(company_id, "E1", "ویزیتور", "یک", None, today, unit, pos, D(1000), None)
emp_mgr = hr_service.create_employee(company_id, "E2", "مدیر", "فروش", None, today, unit, pos, D(1000), None)
emp_top = hr_service.create_employee(company_id, "E3", "مدیر", "ارشد", None, today, unit_parent, pos, D(1000), None)
hr_service.set_employee_user(company_id, emp_req, requester)
hr_service.set_employee_user(company_id, emp_mgr, a2)
hr_service.set_employee_user(company_id, emp_top, a3)
check(raises(lambda: hr_service.set_employee_user(company_id, emp_top, a2), "قبلاً به کارمند"), "one employee per user")
hr_service.set_org_unit_manager(company_id, unit, emp_mgr)
hr_service.set_org_unit_manager(company_id, unit_parent, emp_top)
rm = routing.resolve(company_id, [{"kind": "REPORTING_MANAGER"}], starter=requester)
rm_of_mgr = routing.resolve(company_id, [{"kind": "REPORTING_MANAGER"}], starter=a2)
om = routing.resolve(company_id, [{"kind": "ORG_MANAGER", "org_unit_id": unit_parent}])
check(rm == [a2] and rm_of_mgr == [a3] and om == [a3], f"reporting/org manager routing ({rm}, {rm_of_mgr}, {om})")
with new_session() as s:
    s.execute(text("INSERT INTO inv.warehouse_user_access (warehouse_id, user_id, can_view_balance, can_post_receipt, "
                   "can_post_issue, can_adjust) VALUES (:w, :u, true, true, false, false)"), {"w": warehouse_id, "u": a1})
    s.commit()
check(routing.resolve(company_id, [{"kind": "WAREHOUSE"}], context={"warehouse_id": warehouse_id}) == [a1] and
      routing.resolve(company_id, [{"kind": "WAREHOUSE", "can": "can_post_issue"}], context={"warehouse_id": warehouse_id}) == [],
      "warehouse users routing")
d_mgr = approval_flow("mgr", [{"kind": "REPORTING_MANAGER"}], distinct_approvers=True)
i13 = start(d_mgr, doc())
tasks.decide(company_id, open_task(i13).task_id, a2, "APPROVE")
check(status(i13) == "COMPLETED", "direct manager approved")

# ===== ۱۴) قطعی بین تصمیم و ادامهٔ فرایند ← ادامه در تیک بعدی =====
i14 = start(d_any, doc())
t14 = open_task(i14)
real = tasks.resume_task
tasks.resume_task = lambda *a, **k: False
tasks.decide(company_id, t14.task_id, a1, "APPROVE")
tasks.resume_task = real
check(status(i14) == "WAITING", "decision saved, process not yet resumed")
counts = scheduler.run_due(company_id)
check(counts.get("tasks") == 1 and status(i14) == "COMPLETED" and scheduler.run_due(company_id).get("tasks") == 0,
      f"scheduler resumes closed tasks exactly once ({counts})")

# ===== ۱۵) یادداشت، ثبت در گزارش فعالیت‌ها، اجرای آزمایشی =====
i15 = start(d_any, doc())
t15 = open_task(i15)
check(raises(lambda: tasks.add_comment(company_id, t15.task_id, a3, "سلام"), "فقط گیرندگان"), "outsider cannot comment")
tasks.add_comment(company_id, t15.task_id, requester, "لطفاً سریع‌تر")
check(any(h[2] == "یادداشت" and h[3] == "لطفاً سریع‌تر" for h in tasks.task_detail(company_id, t15.task_id, a1).history),
      "comment in task history")
with new_session() as s:
    audited = {(a.entity_type, a.action) for a in s.scalars(select(ActivityLog).where(ActivityLog.company_id == company_id))}
check({("WfTask", "APPROVE"), ("WfTask", "REJECT"), ("WfTask", "COMPLETE"), ("WfTask", "DELEGATE"), ("WfTask", "COMMENT"),
       ("WfDelegation", "DELEGATE")} <= audited, "approval actions audited")
from peecha.services.workflow import simulate
trace = simulate.simulate(company_id, defs.get_graph(company_id, d_any), "REQ", entity_id=1, starter=requester,
                          decisions={"ap": "rejected"})
check([t.node_type for t in trace] == ["START", "APPROVAL", "END"] and "رد شد" in trace[1].result, "dry run with assumed rejection")
check(not defs.errors(defs.validate_graph(company_id, defs.get_graph(company_id, d_pct), "REQ")), "percent definition valid")
bad = defs.get_graph(company_id, d_pct)
bad["nodes"][0]["mode"] = "PERCENT"
bad["nodes"][0]["percent"] = 0
check(any("درصد" in i.message for i in defs.validate_graph(company_id, bad, "REQ")), "invalid percent rejected by validation")

fx.finish()
