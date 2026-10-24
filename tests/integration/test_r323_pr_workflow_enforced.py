"""R323: گردش کار درخواست خرید رعایت می‌شود (تصویب/رد/تبدیل دستی تا پایان مراحل ممکن نیست)، یادداشت روی مراحل،
و هر مرحله (تایید یا انجام کار) فرم کامل و مشخص خودش را دارد."""
import os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r323"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prd_fixture import *  # noqa: F401,F403

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton

app = QApplication.instance() or QApplication([])
WARN = []
QMessageBox.warning = staticmethod(lambda *a, **k: WARN.append(a[2] if len(a) > 2 else ""))
QMessageBox.information = staticmethod(lambda *a, **k: None)

from peecha.db.models.security import User
from peecha.services import purchase_requests as prs, roles as roles_service, users as users_service
from peecha.services.workflow import builder, definitions as defs, model_events, registry, runtime, tasks
from peecha.services.workflow.common import WorkflowError, save_settings, settings as wf_settings

registry.ensure_loaded()


def new_user(login, name, role_code=None):
    u = users_service.create_user(login, name, "secret123", None, lang_id, False, [company_id], company_id).user_id
    if role_code:
        role = roles_service.create_role(company_id, role_code, None)
        roles_service.set_user_role(u, role.role_id, company_id, True)
    return u


def login(u):
    with new_session() as s:
        sess.current_user = s.get(User, u)
        s.expunge_all()


staff = new_user("staff1", "درخواست‌کنندهٔ انبار")
buyer = new_user("buyer1", "کارشناس خرید")
mgr = new_user("mgr1", "مدیر بازرگانی", "MANAGER")
check(wf_settings(company_id)["lock_while_running"] is True, "lock while running is on by default")

# --- فرایندی شبیه آنچه کاربر با ویزارد ساخته بود: بدون «قفل تایید» ---------------------------------------
FIELDS = [{"key": "vendor", "label": "تامین‌کنندهٔ برنده", "kind": "text", "required": True},
          {"key": "price", "label": "قیمت پیشنهادی", "kind": "money", "required": True},
          {"key": "delivery", "label": "تاریخ تحویل", "kind": "date", "required": False},
          {"key": "method", "label": "روش خرید", "kind": "choice", "choices": ["نقدی", "اعتباری"], "required": True}]
spec = builder.WizardSpec(
    "تایید درخواست خرید با استعلام", "pr_rfq", "PURCHASE_REQUEST", "", {"type": "EVENT", "events": ["PURCHASE_REQUEST_SUBMITTED"]},
    None, [builder.ApprovalLevel("استعلام قیمت", [{"kind": "USER", "user_id": buyer}], kind="TASK", fields=FIELDS,
                                 instructions="از دست‌کم سه تامین‌کننده قیمت بگیرید."),
           builder.ApprovalLevel("تایید مدیر", [{"kind": "USER", "user_id": mgr}],
                                 fields=[{"key": "budget_ok", "label": "بودجه کافی است", "kind": "bool"},
                                         {"key": "note", "label": "شرط تایید", "kind": "text", "required": True}])],
    ["entity.approve"], reject_actions=["entity.reject"])
graph = builder.build_graph(spec)
nodes = defs.nodes_by_id(graph)
check(nodes["tk1"]["type"] == "TASK" and nodes["tk1"]["fields"] == FIELDS and nodes["ap2"]["fields"][1]["required"],
      "wizard builds a task step with its form and an approval step with its own form")
check(not defs.errors(defs.validate_graph(company_id, graph, "PURCHASE_REQUEST")), "graph is valid")
bad = builder.build_graph(builder.WizardSpec("x", "x", "PURCHASE_REQUEST", "", {"type": "MANUAL"}, None, [builder.ApprovalLevel(
    "x", [{"kind": "USER", "user_id": buyer}], kind="TASK", fields=[{"key": "c", "label": "گزینه", "kind": "choice"}])]))
check(any("گزینه‌ای" in i.message for i in defs.errors(defs.validate_graph(company_id, bad, "PURCHASE_REQUEST"))),
      "choice field without options is reported")
did = defs.create_definition(company_id, uid, code="pr_rfq", name="تایید درخواست خرید با استعلام", entity_type="PURCHASE_REQUEST")
defs.save_draft(company_id, uid, did, graph)
defs.publish(company_id, uid, did)


def new_request(qty=D(5)):
    login(staff)
    req = prs.create_request(company_id, staff, prs.RequestFields(request_date=today, warehouse_id=wh_rm))
    prs.add_line(req, company_id, r1, kg, qty, None, supplier, D(1000))
    prs.submit_request(req, company_id)
    return req


def open_task(req):
    rows = tasks.list_tasks(company_id, entity_type="PURCHASE_REQUEST", entity_id=req, status="OPEN")
    return rows[0] if rows else None


# --- ۱۳: بدون تایید گردش کار، تصویب/رد/تبدیل دستی ممکن نیست -------------------------------------------------
req = new_request()
t1 = open_task(req)
check(t1 is not None and t1.title.startswith("استعلام قیمت"), "submitting starts the workflow at the price inquiry task")
busy = model_events.busy(company_id, "PURCHASE_REQUEST", req)
check(busy and "استعلام قیمت" in busy, f"busy message names the current step ({busy})")
check(raises(lambda: prs.approve_request(req, company_id, mgr), "در جریان تایید"), "manager cannot approve directly")
check(raises(lambda: prs.reject_request(req, company_id, "گران است"), "در جریان تایید"), "manager cannot reject directly")
check(prs.get_request(req, company_id)[0].status_code == "SUBMITTED", "request stays submitted")

from peecha.ui.screens.purchase_requests import PurchaseRequestScreen

login(mgr)
scr = PurchaseRequestScreen()
scr.refresh()
scr.edit_document(req)
check(not scr.buttons["approve"].isEnabled() and not scr.buttons["reject"].isEnabled()
      and "در جریان تایید" in scr.buttons["approve"].toolTip(), "approve/reject buttons disabled with the reason")
bar = scr.workflow_bar
check(bar.isVisible() or not bar.isHidden(), "workflow bar shown on the request")
check(bar.step_button.isEnabled() and bar.note_button.isEnabled() and not bar.my_task_ids, "step/note buttons; not manager's step")

# --- ۱۴: یادداشت روی مرحله --------------------------------------------------------------------------------
check(bar.add_note("لطفاً از تامین‌کنندهٔ همیشگی هم قیمت بگیرید"), "manager adds a note from the request form")
login(staff)
tasks.add_comment(company_id, t1.task_id, staff, "فوری است")
rows = runtime.timeline(company_id, t1.instance_id)
check(any("همیشگی" in r.detail for r in rows) and any("فوری" in r.detail for r in rows), "notes appear in the workflow history")
check(raises(lambda: tasks.add_comment(company_id, t1.task_id, new_user("x1", "بی‌ربط"), "سلام"), "فقط"),
      "unrelated users cannot add notes")

# --- ۱۵: فرم کامل مرحلهٔ «انجام کار» ---------------------------------------------------------------------
from peecha.ui.screens.workflow_task_form import TaskFormDialog

login(buyer)
form = TaskFormDialog(t1.task_id)
check(set(form.field_widgets) == {"vendor", "price", "delivery", "method"} and form.buttons["DONE"].isVisibleTo(form)
      and not form.buttons["APPROVE"].isVisibleTo(form), "task form: its fields and only the «done» decision")
check("سه تامین‌کننده" in form.instructions.text() and form.context.rowCount() >= 3 and form.history.rowCount() >= 3,
      "form shows what to do, the document data and the history with notes")
check(not form.decide("DONE") and form.field_widgets["vendor"].property("invalid") and "تامین‌کنندهٔ برنده" in form.status.text(),
      "required fields are checked before completing")
form.set_value("vendor", "بازرگانی نمونه")
form.set_value("price", "۱۲۰۰۰۰۰")
form.field_widgets["price"].editingFinished.emit()
form.set_value("method", "اعتباری")
form.set_value("delivery", today)
check(not form.field_widgets["vendor"].property("invalid") or form.problems() == [], "flags clear once filled")
form.note.setPlainText("سه استعلام گرفته شد")
check(form.decide("DONE") and form.decided == "DONE", f"task completed from its form ({form.status.text()})")
done = tasks.task_detail(company_id, t1.task_id)
check(any("قیمت پیشنهادی: ۱,۲۰۰,۰۰۰" in h[3] and "روش خرید: اعتباری" in h[3] for h in done.history),
      f"filled form saved and shown readable ({[h[3] for h in done.history]})")
check(prs.get_request(req, company_id)[0].status_code == "SUBMITTED", "still not approved after the first step")
t2 = open_task(req)
check(t2 is not None and t2.kind == "APPROVAL", "next: manager approval")
check(raises(lambda: prs.convert_to_orders(req, company_id, uid), "تصویب‌شده"), "no conversion before approval")

# --- فرم مرحلهٔ تایید: خانهٔ لازم پیش از تایید؛ رد علت می‌خواهد --------------------------------------------
check(raises(lambda: tasks.decide(company_id, t2.task_id, mgr, "APPROVE", "ok"), "شرط تایید"),
      "approval with a required form field cannot be quick-approved empty")
login(mgr)
from peecha.ui.screens.workflow_task_form import run_task_form

bar.refresh()
check(bar.my_task_ids == [t2.task_id], "the bar knows this step is the manager's")
captured = {}


def runner(dlg):
    captured["dlg"] = dlg
    hist = [dlg.history.item(r, 2).text() for r in range(dlg.history.rowCount())]
    captured["hist"] = hist
    check(not dlg.decide("REJECT") and dlg.note.property("invalid"), "reject needs a reason in the note")
    dlg.set_value("note", "خرید اعتباری با چک ۳۰ روزه")
    dlg.set_value("budget_ok", True)
    return dlg.decide("APPROVE")


bar.dialog_runner = runner
check(bar.open_step(), "manager approves from the request form's workflow bar")
check(any("قیمت پیشنهادی" in h for h in captured["hist"]), "approver sees the previous step's results")
inst = runtime.get_instance(company_id, t2.instance_id)
check(inst.status_code == "COMPLETED" and prs.get_request(req, company_id)[0].status_code == "APPROVED",
      "after all steps the workflow approves the request itself")
check(model_events.busy(company_id, "PURCHASE_REQUEST", req) is None, "no longer busy")
orders = prs.convert_to_orders(req, company_id, uid)
check(len(orders) == 1, "conversion works once the workflow is complete")

# --- رد در گردش کار، خود درخواست را هم رد می‌کند ----------------------------------------------------------
req2 = new_request(D(2))
login(buyer)
t = open_task(req2)
tasks.decide(company_id, t.task_id, buyer, "DONE", "", data={"vendor": "الف", "price": "500", "method": "نقدی"})
t = open_task(req2)
tasks.decide(company_id, t.task_id, mgr, "REJECT", "بودجه ندارد")
check(prs.get_request(req2, company_id)[0].status_code == "REJECTED", "rejected in the workflow → request rejected")

# --- کلید تنظیمات: خاموش = رفتار قبلی -----------------------------------------------------------------------
save_settings(company_id, uid, lock_while_running=False)
req3 = new_request(D(1))
check(open_task(req3) is not None and model_events.busy(company_id, "PURCHASE_REQUEST", req3) is None, "toggle off: not busy")
prs.approve_request(req3, company_id, mgr)
check(prs.get_request(req3, company_id)[0].status_code == "APPROVED", "toggle off: manual approval allowed as before")
save_settings(company_id, uid, lock_while_running=True)

# --- کارتابل من: دکمهٔ فرم کامل مرحله ---------------------------------------------------------------------
from peecha.ui.screens import my_tasks

req4 = new_request(D(3))
login(buyer)
mt = my_tasks.MyTasksScreen(None)
opened = {}
mt.dialog_runner = lambda dlg: opened.setdefault("title", dlg.windowTitle()) and False
mt.refresh()
key = f"WF:{open_task(req4).task_id}"
check(mt.select_key(key) and mt.buttons["form"].isEnabled() and mt.buttons["form"].text() == "📋", "«full step form» icon button")
mt.approve_selected()
check(opened.get("title", "").startswith("کار: استعلام قیمت"), "doing a task opens its full form")
plain = [b.text() for b in mt.findChildren(QPushButton) if len(b.text()) > 2]
check(not plain, f"no text buttons ({plain})")

# --- ویزارد در رابط کاربری ----------------------------------------------------------------------------------
from peecha.ui.screens import workflow_studio as st
from peecha.ui.screens.workflow_center import WfRulesPanel

login(uid)
w = st.WizardDialog()
w.entity.setCurrentIndex(w.entity.findData("PURCHASE_REQUEST"))
w.ttype.setCurrentIndex(w.ttype.findData("EVENT"))
check(not w.gate.isHidden() and w.gate.isChecked() and not w.reject_doc.isHidden(), "gate on by default for documents that have it")
w.name.setText("آزمون")
w.code.setText("t_wiz")
w.check_item(w.events, "PURCHASE_REQUEST_SUBMITTED")
lv = st.LevelDialog("PURCHASE_REQUEST", None, w, kind="TASK")
check(lv.kind.currentData() == "TASK" and lv.percent.isHidden(), "task step dialog hides approval-only options")
lv.label.setText("استعلام")
lv.approvers.set_specs([{"kind": "USER", "user_id": buyer}])
r = lv.fields.add({"label": "قیمت", "kind": "money", "required": True})
r2 = lv.fields.add({"label": "روش", "kind": "choice"})
lv.fields.table.item(r2, 3).setText("نقدی، اعتباری")
level = lv.level()
check(level.kind == "TASK" and [f["key"] for f in level.fields] == ["f1", "f2"] and level.fields[1]["choices"] == ["نقدی", "اعتباری"],
      f"fields get automatic keys and options ({level.fields})")
w.dialog_runner = lambda dlg: True
check(w.edit_level(new=True, level=level) and w.t_levels.item(0, 0).text().startswith("کار: استعلام"), "task step listed")
sp = w.spec()
check(sp.trigger.get("gate") is True and sp.reject_actions == ["entity.reject"], "wizard spec carries the gate and reject action")
g = builder.build_graph(sp)
check(any(n["type"] == "TASK" and n.get("fields") for n in g["nodes"]), "wizard graph has the task with its form")
w.entity.setCurrentIndex(0)
check(w.gate.isHidden(), "no gate option for a general process")
panel = WfRulesPanel()
panel.refresh()
check(panel.lock_running.isChecked(), "settings panel shows the lock")
panel.lock_running.setChecked(False)
panel.save()
check(wf_settings(company_id)["lock_while_running"] is False, "lock toggle saved")
panel.lock_running.setChecked(True)
panel.save()

finish()
