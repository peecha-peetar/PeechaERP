"""R330: اقدامی که به ماژول ربط ندارد (پیگیری مشتری روی درخواست خرید) نه پیشنهاد می‌شود نه منتشر؛ شکست اقدام فرعی سند را
قفل نمی‌کند؛ اقدام سند پیش از وضعیتی که لازم دارد رد می‌شود؛ «انجام کار» پس از تایید روی سند تصویب‌شده انجام می‌شود؛ ریز
اجرا خلاصه و بی‌نام فنی خطاست."""
import os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r330"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prd_fixture import *  # noqa: F401,F403

import dataclasses

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox
from sqlalchemy import text

app = QApplication.instance() or QApplication([])
WARN = []
QMessageBox.warning = staticmethod(lambda *a, **k: WARN.append(a[2] if len(a) > 2 else ""))
QMessageBox.information = staticmethod(lambda *a, **k: None)

from peecha.db.models.security import Notification, User
from peecha.services import purchase_requests as prs, roles as roles_service, users as users_service
from peecha.services.workflow import (
    builder, definitions as defs, exceptions as wf_exceptions, model_events, monitor, registry, runtime, tasks,
)
from peecha.ui.screens.purchase_requests import PurchaseRequestScreen

registry.ensure_loaded()
servin = users_service.create_user("servin", "سروین", "secret123", None, lang_id, False, [company_id], company_id).user_id
mgr = users_service.create_user("mgr1", "مدیر بازرگانی", "secret123", None, lang_id, False, [company_id], company_id).user_id
buyer = users_service.create_user("buyer1", "کارشناس خرید", "secret123", None, lang_id, False, [company_id], company_id).user_id
roles_service.set_user_role(mgr, roles_service.create_role(company_id, "MANAGER", None).role_id, company_id, True)
MGR = [{"kind": "USER", "user_id": mgr}]


def login(u):
    with new_session() as s:
        sess.current_user = s.get(User, u)
        s.expunge_all()


def spec(code, *, events=("PURCHASE_REQUEST_SUBMITTED",), levels=None, actions=("entity.approve",)):
    levels = [builder.ApprovalLevel("تایید مدیر", MGR)] if levels is None else levels
    return builder.WizardSpec(code, code, "PURCHASE_REQUEST", "", {"type": "EVENT", "events": list(events), "gate": True}, None,
                              levels, list(actions), reject_actions=["entity.reject"])


def draft(s, graph=None):
    did = defs.create_definition(company_id, uid, code=s.code, name=s.name, entity_type="PURCHASE_REQUEST")
    defs.save_draft(company_id, uid, did, graph or builder.build_graph(s))
    return did


def new_request(submit=True):
    login(servin)
    r = prs.create_request(company_id, servin, prs.RequestFields(request_date=today, warehouse_id=wh_rm))
    prs.add_line(r, company_id, r1, kg, D(4), None, supplier, D(1000))
    if submit:
        prs.submit_request(r, company_id)
    return r


def status(r):
    return prs.get_request(r, company_id)[0].status_code


def instance(r):
    return runtime.list_instances(company_id, entity_type="PURCHASE_REQUEST", entity_id=r)[0]


def my_task(user, r):
    return next(t for t in tasks.list_my_tasks(company_id, user) if t.entity_id == r)


# --- ۱: فقط اقدام‌های مربوط به همان ماژول پیشنهاد می‌شوند -----------------------------------------------------------
pr_codes = [c for c, _l, _r in registry.action_choices("PURCHASE_REQUEST")]
check("create_followup" not in pr_codes and "entity.approve" in pr_codes and "add_comment" in pr_codes,
      f"purchase request: no customer follow-up offered ({pr_codes})")
check("create_followup" in [c for c, _l, _r in registry.action_choices("SALES_INVOICE")], "sales invoice: follow-up offered")
check(registry.find_action(None, "create_followup").applies("CUSTOMER")
      and registry.find_action(None, "create_followup").applies("TEST_DOC"), "customer module and generic processes keep it")

from peecha.ui.screens.workflow_studio import WizardDialog  # noqa: E402

w = WizardDialog(None)
w.entity.setCurrentIndex(w.entity.findData("PURCHASE_REQUEST"))
listed = [w.actions.item(i).data(Qt.UserRole) for i in range(w.actions.count())]
check("create_followup" not in listed and "call_api" not in listed and "emit_event" not in listed
      and "entity.approve" in listed and "add_comment" in listed, f"the wizard lists only actions that work here ({listed})")

# --- ۲: انتشار فرایندی که اقدام نامربوط یا وضعیت نادرست دارد ممکن نیست ------------------------------------------------
g = builder.build_graph(spec("followup_on_pr", actions=("entity.approve", "add_comment")))
for n in g["nodes"]:
    if n.get("action") == "add_comment":
        n.update(action="create_followup", label="ثبت پیگیری یا وظیفه")
bad_fu = draft(spec("followup_on_pr"), g)
check(raises(lambda: defs.publish(company_id, uid, bad_fu), "مربوط نیست"), "customer follow-up on a purchase request is refused")
early = draft(spec("approve_on_create", events=("PURCHASE_REQUEST_CREATED",)))
problem = next((i.message for i in defs.errors(defs.validate_graph(company_id, defs.get_graph(company_id, early),
                                                                  "PURCHASE_REQUEST")) if "رویداد شروع" in i.message), "")
check("تصویب درخواست خرید" in problem and "ارسال" in problem, f"approving a request before it is sent is refused ({problem})")
check(raises(lambda: defs.publish(company_id, uid, early), "رویداد شروع"), "and cannot be published")
api = draft(spec("api_no_url", actions=("entity.approve", "call_api")))
check(raises(lambda: defs.publish(company_id, uid, api), "نشانی سرویس"), "an external call without an allowed address is refused")

# --- ۳: شکست اقدام فرعی (یادداشت) سند را قفل نمی‌کند ------------------------------------------------------------------
note_flow = draft(spec("note_flow", actions=("entity.approve", "add_comment")))
defs.publish(company_id, uid, note_flow)
real_note = registry._GLOBAL_ACTIONS["add_comment"]


def boom(_ctx):
    raise ValueError("یادداشت ثبت نشد.")


registry._GLOBAL_ACTIONS["add_comment"] = dataclasses.replace(real_note, func=boom)
req = new_request()
login(mgr)
tasks.decide(company_id, my_task(mgr, req).task_id, mgr, "APPROVE", "")
registry._GLOBAL_ACTIONS["add_comment"] = real_note
inst = instance(req)
check(status(req) == "APPROVED" and inst.status_code == "COMPLETED" and inst.outcome_code == "APPROVED",
      f"approved and finished although the note failed ({status(req)}, {inst.status_code})")
check(model_events.busy(company_id, "PURCHASE_REQUEST", req) is None and not model_events.failed(company_id, "PURCHASE_REQUEST", req),
      "nothing is locked afterwards")
log = monitor.execution_log(company_id, inst.instance_id)
note_rows = [x for x in log if x.step == "افزودن یادداشت"]
check(len(note_rows) == 1 and note_rows[0].kind == "اجرای اقدام" and note_rows[0].status == "ناموفق"
      and "یادداشت ثبت نشد" in note_rows[0].detail, f"one log row with the plain reason ({[(x.kind, x.detail) for x in note_rows]})")
check(not any("Error" in x.detail for x in log), "no technical error names in the log")
with new_session() as s:
    told = s.scalar(select(Notification).where(Notification.user_id == servin, Notification.title.like("%انجام نشد%")))
check(told is not None, "the requester is told that the note failed")
defs.set_status(company_id, uid, note_flow, "PAUSED")

# --- ۴: فرایند قدیمی که پیگیری مشتری روی درخواست خرید داشت (مثل تعریف کاربر) دیگر سند را قفل نمی‌کند --------------
legacy = draft(spec("legacy_followup", actions=("entity.approve", "add_comment")))
defs.publish(company_id, uid, legacy)
with new_session() as s:
    s.execute(text("UPDATE wf.definition_versions SET graph = jsonb_set(graph, '{nodes}', (SELECT jsonb_agg(CASE WHEN "
                   "n->>'action' = 'add_comment' THEN n || '{\"action\": \"create_followup\", \"label\": \"ثبت پیگیری یا وظیفه\"}' "
                   "ELSE n END) FROM jsonb_array_elements(graph->'nodes') n)) WHERE definition_id = :d"), {"d": legacy})
    s.commit()
runtime._GRAPH_CACHE.clear()
check(legacy in defs.problems(company_id) and "مربوط نیست" in defs.problems(company_id)[legacy][0],
      "the old process is flagged «needs fixing» with the reason")
req = new_request()
login(mgr)
tasks.decide(company_id, my_task(mgr, req).task_id, mgr, "APPROVE", "")
inst = instance(req)
check(status(req) == "APPROVED" and inst.status_code == "COMPLETED", f"the request is approved, not locked ({inst.status_code})")
row = next((x for x in monitor.execution_log(company_id, inst.instance_id) if x.step == "ثبت پیگیری یا وظیفه"), None)
check(row is not None and row.status == "کنار گذاشته شد" and "مربوط نیست" in row.detail and "مشتری یا سرنخ" not in row.detail,
      f"the step says it does not belong here ({row and row.status}: {row and row.detail})")

# سندی که پیش از این نسخه همین‌طور قفل شده بود: یک «اجرای دوباره» از نوار گردش کار همان سند بازش می‌کند
real_fu = registry._GLOBAL_ACTIONS["create_followup"]
registry._GLOBAL_ACTIONS["create_followup"] = dataclasses.replace(real_fu, blocking=True, modules=None)  # رفتار قبلی
stuck = new_request()
login(mgr)
tasks.decide(company_id, my_task(mgr, stuck).task_id, mgr, "APPROVE", "")
registry._GLOBAL_ACTIONS["create_followup"] = real_fu
check(model_events.busy(company_id, "PURCHASE_REQUEST", stuck) and instance(stuck).status_code == "WAITING",
      "the old behaviour locked the request")
login(uid)
scr = PurchaseRequestScreen()
scr.refresh()
scr.edit_document(stuck)
bar = scr.workflow_bar
check(not bar.retry_button.isHidden() and bar.retry_failed(), "one «run again» from the request's workflow bar")
check(instance(stuck).status_code == "COMPLETED" and model_events.busy(company_id, "PURCHASE_REQUEST", stuck) is None,
      "the request is free afterwards")
defs.set_status(company_id, uid, legacy, "PAUSED")

# --- ۵: شکست تکراری اقدام اصلی: یک ردیف با شمار، بی‌نام فنی -------------------------------------------------------
plain_flow = draft(spec("plain_flow"))
defs.publish(company_id, uid, plain_flow)
real_approve = prs.approve_request


def broken(*_a, **_k):
    raise ValueError("بودجهٔ این مرکز هزینه بسته است.")


prs.approve_request = broken
req = new_request()
login(mgr)
tasks.decide(company_id, my_task(mgr, req).task_id, mgr, "APPROVE", "")
for _ in range(2):
    found = model_events.failed(company_id, "PURCHASE_REQUEST", req)
    wf_exceptions.retry(company_id, found[0], uid)
msg = model_events.busy(company_id, "PURCHASE_REQUEST", req)
check(msg and "اجرای دوباره" in msg and "بودجه" in msg and len(msg) < 140, f"a short lock message ({msg})")
prs.approve_request = real_approve
wf_exceptions.retry(company_id, model_events.failed(company_id, "PURCHASE_REQUEST", req)[0], uid)
inst = instance(req)
check(status(req) == "APPROVED" and inst.status_code == "COMPLETED", "approved after the cause was fixed")
rows = [x for x in monitor.execution_log(company_id, inst.instance_id) if x.step == "تصویب درخواست خرید"]
check([x.status for x in rows] == ["ناموفق", "انجام شد"] and "3 بار" in rows[0].detail and "Error" not in rows[0].detail,
      f"three identical failures shown as one row ({[(x.status, x.detail) for x in rows]})")
tl = [r for r in runtime.timeline(company_id, inst.instance_id) if r.title == "تصویب درخواست خرید"]
check(len(tl) == 2 and "3 بار" in tl[0].detail, f"the workflow history is summarised too ({[(r.status, r.detail) for r in tl]})")
defs.set_status(company_id, uid, plain_flow, "PAUSED")

# --- ۶: «انجام کار» پس از تایید (تبدیل به سفارش) روی درخواست تصویب‌شده و فقط به دست مسئولش ------------------------
convert_spec = spec("convert_flow", levels=[builder.ApprovalLevel("تایید مدیر", MGR),
                                            builder.ApprovalLevel("تبدیل به سفارش", [{"kind": "USER", "user_id": buyer}], kind="TASK")])
graph = builder.build_graph(convert_spec)
order = [e["to"] for e in graph["edges"] if e["from"] == "ap1" and e.get("when") == "approved"]
check(order == ["act1"] and any(e["from"] == "act1" and e["to"] == "tk2" for e in graph["edges"]),
      f"the wizard approves right after the approval, then the work step ({order})")
convert_flow = draft(convert_spec)
defs.publish(company_id, uid, convert_flow)
req = new_request()
login(mgr)
tasks.decide(company_id, my_task(mgr, req).task_id, mgr, "APPROVE", "")
check(status(req) == "APPROVED" and instance(req).status_code == "WAITING", "approved; the work step is waiting")
check(model_events.busy(company_id, "PURCHASE_REQUEST", req, servin) is not None, "others still cannot convert it")
check(raises(lambda: prs.convert_to_orders(req, company_id, servin), "در جریان تایید"), "the requester cannot convert")
check(model_events.busy(company_id, "PURCHASE_REQUEST", req, buyer) is None, "the person of the work step is free to do it")
login(buyer)
scr = PurchaseRequestScreen()
scr.refresh()
scr.edit_document(req)
check(scr.buttons["convert"].isEnabled(), "the buyer's «convert» button is enabled during the step")
orders = prs.convert_to_orders(req, company_id, buyer)
check(len(orders) == 1 and status(req) == "APPROVED", "the buyer converts the request")
tasks.decide(company_id, my_task(buyer, req).task_id, buyer, "DONE", "")
check(instance(req).status_code == "COMPLETED", "the process finishes when the step is done")
defs.set_status(company_id, uid, convert_flow, "PAUSED")

# --- ۷: «تصویب» فرم برای مرحلهٔ «انجام کار» به کار نمی‌رود ------------------------------------------------------------
rfq_spec = spec("rfq_flow", levels=[builder.ApprovalLevel("استعلام قیمت", [{"kind": "USER", "user_id": buyer}], kind="TASK"),
                                    builder.ApprovalLevel("تایید مدیر", MGR)])
rfq = draft(rfq_spec)
defs.publish(company_id, uid, rfq)
req = new_request()
login(buyer)
scr = PurchaseRequestScreen()
scr.refresh()
scr.edit_document(req)
check(not scr.buttons["approve"].isEnabled() and "انجام کار" in scr.buttons["approve"].toolTip(),
      f"the approve button points to the work step ({scr.buttons['approve'].toolTip()})")
tasks.decide(company_id, my_task(buyer, req).task_id, buyer, "DONE", "")
login(mgr)
scr = PurchaseRequestScreen()
scr.refresh()
scr.edit_document(req)
WARN.clear()
scr.buttons["approve"].click()
check(status(req) == "APPROVED" and not WARN, f"the manager approves from the form ({WARN})")

finish()
