"""R329: فرایندی که از همان تعریف معلوم است سند را گیر می‌اندازد منتشر نمی‌شود (قفل تایید با رویداد «تصویب»، قفل بدون
پایان «تایید شد»، تاییدکننده فقط خود درخواست‌کننده)، و فرایندهای قدیمی همین‌طوری دیگر سند را نمی‌بندند."""
import os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r329"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prd_fixture import *  # noqa: F401,F403

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox
from sqlalchemy import text

app = QApplication.instance() or QApplication([])
WARN = []
QMessageBox.warning = staticmethod(lambda *a, **k: WARN.append(a[2] if len(a) > 2 else ""))
QMessageBox.information = staticmethod(lambda *a, **k: None)

from peecha.db.models.security import User
from peecha.services import purchase_requests as prs, roles as roles_service, users as users_service
from peecha.services.workflow import builder, definitions as defs, inbox, registry, runtime, tasks
from peecha.services.workflow.common import save_settings
from peecha.ui.screens.purchase_requests import PurchaseRequestScreen

registry.ensure_loaded()
servin = users_service.create_user("servin", "سروین", "secret123", None, lang_id, False, [company_id], company_id).user_id
mgr = users_service.create_user("mgr1", "مدیر بازرگانی", "secret123", None, lang_id, False, [company_id], company_id).user_id
roles_service.set_user_role(mgr, roles_service.create_role(company_id, "MANAGER", None).role_id, company_id, True)


def login(u):
    with new_session() as s:
        sess.current_user = s.get(User, u)
        s.expunge_all()


def spec(code, events, *, gate=True, approvers=None, levels=True, actions=("entity.approve",), notify=True):
    trigger = {"type": "EVENT", "events": events, **({"gate": True} if gate else {})}
    lv = [builder.ApprovalLevel("تایید مدیر", approvers or [{"kind": "USER", "user_id": mgr}])] if levels else []
    return builder.WizardSpec(code, code, "PURCHASE_REQUEST", "", trigger, None, lv, list(actions),
                              notify_on_approve=notify, reject_actions=["entity.reject"] if levels else [])


def draft(s):
    did = defs.create_definition(company_id, uid, code=s.code, name=s.name, entity_type="PURCHASE_REQUEST")
    defs.save_draft(company_id, uid, did, builder.build_graph(s))
    return did


def new_request():
    login(servin)
    r = prs.create_request(company_id, servin, prs.RequestFields(request_date=today, warehouse_id=wh_rm))
    prs.add_line(r, company_id, r1, kg, D(4), None, supplier, D(1000))
    return r


def status(r):
    return prs.get_request(r, company_id)[0].status_code


# --- ۱: تعریف‌های بن‌بست منتشر نمی‌شوند ---------------------------------------------------------------------------
bad = draft(spec("bad_trigger", ["PURCHASE_REQUEST_APPROVED"]))
check(raises(lambda: defs.publish(company_id, uid, bad), "ارسال درخواست خرید"),
      "a locked approval that starts on «approval» is refused, suggesting «submit»")
no_end = draft(spec("no_end", ["PURCHASE_REQUEST_SUBMITTED"], levels=False, actions=("add_comment",)))
check(raises(lambda: defs.publish(company_id, uid, no_end), "تایید شد"), "a lock that never ends «approved» is refused")
self_only = draft(spec("self_only", ["PURCHASE_REQUEST_SUBMITTED"], approvers=[{"kind": "STARTER"}]))
check(raises(lambda: defs.publish(company_id, uid, self_only), "خود درخواست‌کننده"),
      "an approval only the requester could give is refused")
save_settings(company_id, uid, allow_self_approval=True)
check(not defs.errors(defs.validate_graph(company_id, defs.get_graph(company_id, self_only), "PURCHASE_REQUEST")),
      "allowed once self-approval is allowed")
save_settings(company_id, uid, allow_self_approval=False)
after = draft(spec("after_note", ["PURCHASE_REQUEST_APPROVED"], gate=False, levels=False, actions=("add_comment",)))
check(defs.publish(company_id, uid, after) is not None, "a notification after approval (no lock) is fine")
defs.set_status(company_id, uid, after, "PAUSED")

# ویزارد همان‌جا می‌گوید
from peecha.ui.screens.workflow_studio import WizardDialog  # noqa: E402

w = WizardDialog(None)
w.entity.setCurrentIndex(w.entity.findData("PURCHASE_REQUEST"))
w.ttype.setCurrentIndex(w.ttype.findData("EVENT"))
for i in range(w.events.count()):
    item = w.events.item(i)
    item.setCheckState(Qt.Checked if item.data(Qt.UserRole) == "PURCHASE_REQUEST_APPROVED" else Qt.Unchecked)
problem = w._step_problem(1)
check(problem and "ارسال درخواست خرید" in problem and "قفل تایید" in problem, f"the wizard stops at the trigger step ({problem})")
w.gate.setChecked(False)
check(w._step_problem(1) is None, "without the lock the same trigger is accepted")

# --- ۲: فرایند قدیمی‌ای که پیش از این قاعده منتشر شده (رویداد شروع «تصویب» + قفل) --------------------------------------
old = draft(spec("old_flow", ["PURCHASE_REQUEST_SUBMITTED"]))
defs.publish(company_id, uid, old)
with new_session() as s:  # همان تعریف شما: رویداد شروع «تصویب درخواست خرید»
    s.execute(text("UPDATE wf.definition_triggers SET event_type = 'PURCHASE_REQUEST_APPROVED' WHERE definition_id = :d"), {"d": old})
    s.execute(text("UPDATE wf.definition_versions SET graph = jsonb_set(graph, '{trigger,events}', '[\"PURCHASE_REQUEST_APPROVED\"]') "
                   "WHERE definition_id = :d"), {"d": old})
    s.commit()
runtime._GRAPH_CACHE.clear()
check(old in defs.problems(company_id) and "ارسال درخواست خرید" in defs.problems(company_id)[old][0],
      "the old process is flagged «needs fixing» with the reason")

# درخواست سروین که پیش از این گیر کرده بود: «تصویب» مدیر یک‌بار، درخواست تصویب می‌شود
stuck = new_request()
prs.submit_request(stuck, company_id)
login(mgr)
cards = [w for w in inbox.my_work(company_id, mgr) if w.extra.get("document_id") == stuck]
check(len(cards) == 1, "the manager has the request in the cartable")
scr = PurchaseRequestScreen()
scr.refresh()
scr.edit_document(stuck)
check(scr.buttons["approve"].isEnabled(), "approve enabled")
WARN.clear()
scr.buttons["approve"].click()
check(status(stuck) == "APPROVED" and not WARN, f"one click on «approve» approves it through the process ({WARN})")
check(len(runtime.list_instances(company_id, entity_type="PURCHASE_REQUEST", entity_id=stuck)) == 1,
      "the process does not start a second time on the approval event")

# درخواست تازه: «ارسال برای تصویب» خود فرم آن را به فرایند می‌فرستد
fresh = new_request()
scr = PurchaseRequestScreen()
scr.refresh()
scr.edit_document(fresh)
scr.submit()
check(any(t.entity_id == fresh for t in tasks.list_my_tasks(company_id, mgr)), "submitting sends it to the manager's cartable")
login(mgr)
tasks.decide(company_id, next(t for t in tasks.list_my_tasks(company_id, mgr) if t.entity_id == fresh).task_id, mgr,
             "APPROVE", "")
check(status(fresh) == "APPROVED", "approved from the cartable")

# --- ۳: خبرِ پس از تصویب با قفل (قدیمی) دیگر جلوی تصویب را نمی‌گیرد ------------------------------------------------
defs.set_status(company_id, uid, old, "PAUSED")
note = draft(spec("old_note", ["PURCHASE_REQUEST_SUBMITTED"], gate=True))
defs.publish(company_id, uid, note)
with new_session() as s:
    s.execute(text("UPDATE wf.definition_triggers SET event_type = 'PURCHASE_REQUEST_APPROVED' WHERE definition_id = :d"), {"d": note})
    s.execute(text("UPDATE wf.definition_versions SET graph = jsonb_set(jsonb_set(graph, '{trigger,events}', "
                   "'[\"PURCHASE_REQUEST_APPROVED\"]'), '{nodes}', (SELECT jsonb_agg(n) FROM jsonb_array_elements(graph->'nodes') n "
                   "WHERE n->>'type' NOT IN ('APPROVAL', 'ACTION'))) WHERE definition_id = :d"), {"d": note})
    s.commit()
runtime._GRAPH_CACHE.clear()
plain = new_request()
prs.submit_request(plain, company_id)
login(mgr)
prs.approve_request(plain, company_id, mgr)
check(status(plain) == "APPROVED", "a lock on a notification-only process no longer blocks the manager")

finish()
