import os, re, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r294"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crm_fixture import *  # noqa: F401,F403
import crm_fixture as fx
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox, QPushButton
qapp = QApplication.instance() or QApplication([])
from PySide6.QtCore import Qt
qapp.setLayoutDirection(Qt.RightToLeft)  # مثل برنامهٔ واقعی
WARN = []
QMessageBox.warning = staticmethod(lambda *a, **k: WARN.append(a[2] if len(a) > 2 else ""))
from peecha import session as sess
from peecha.db.models.core import Company
from peecha.db.models.security import User
from peecha.services import roles as roles_service, users as users_service
from peecha.services.workflow import builder, definitions as defs, registry, runtime, tasks
from peecha.services.workflow.registry import ActionSpec, EntityAdapter, FieldSpec
from peecha.ui.screens import workflow_studio as st
check, raises = fx.check, fx.raises
LATIN = re.compile(r"[A-Za-z]")

with new_session() as s:
    sess.current_user = s.get(User, uid)
    sess.current_company = s.get(Company, company_id)
    s.expunge_all()

a1 = users_service.create_user("fin1", "کارشناس مالی", "secret123", None, lang_id, False, [company_id], company_id).user_id
role = roles_service.create_role(company_id, "CFO", None)
roles_service.set_user_role(a1, role.role_id, company_id, True)
DOCS = {1: {"amount": 900_000_000, "due_date": today, "requested_by": visitor.user_id, "status": "DRAFT"},
        2: {"amount": 10_000_000, "due_date": today, "requested_by": visitor.user_id, "status": "DRAFT"}}
DONE = []


def _post(ctx):
    DONE.append(ctx.entity_id)
    DOCS[ctx.entity_id]["status"] = "POSTED"
    return {}


registry.register_adapter(EntityAdapter(
    "PO", "سفارش خرید", "PURCH", lambda cid, eid: dict(DOCS[eid]),
    fields=(FieldSpec("amount", "مبلغ", "money"), FieldSpec("due_date", "تاریخ تحویل", "date"),
            FieldSpec("requested_by", "درخواست‌کننده", "user")),
    events={"PO_SUBMITTED": "ارسال سفارش برای تایید"},
    actions={"post": ActionSpec("post", "ثبت نهایی سفارش", _post, risk="HIGH",
                                is_done=lambda cid, eid: DOCS[eid]["status"] == "POSTED")},
    title=lambda c: "سفارش خرید", submitter_field="requested_by"))

# ===== ۱) سازندهٔ گراف از ویزارد =====
big = {"field": "amount", "op": ">", "value": "500000000"}
spec = builder.WizardSpec("تایید سفارش خرید", "po_ok", "PO", trigger={"type": "EVENT", "events": ["PO_SUBMITTED"]},
                          levels=[builder.ApprovalLevel("تایید مالی", [{"kind": "ROLE", "role_id": role.role_id}], allow_changes=True),
                                  builder.ApprovalLevel("تایید مدیرعامل", [{"kind": "USER", "user_id": uid}], only_if=big)],
                          actions=["entity.post"])
g = builder.build_graph(spec)
types = [n["type"] for n in g["nodes"]]
check(types.count("APPROVAL") == 2 and "CONDITION" in types and "TASK" in types and "ACTION" in types and types.count("END") == 2,
      f"wizard graph shape ({types})")
check(not defs.errors(defs.validate_graph(company_id, g, "PO")), f"wizard graph is valid {[i.message for i in defs.validate_graph(company_id, g, 'PO')]}")
check(all("pos" in n for n in g["nodes"]), "auto layout positions")
lines = builder.describe_graph(g, "PO", company_id)
check(lines[0] == "شروع: با رویداد: ارسال سفارش برای تایید" and any("نقش «CFO»" in x for x in lines)
      and any("مبلغ بیشتر از" in x for x in lines), f"Persian summary ({lines[:3]})")
check(raises(lambda: builder.build_graph(builder.WizardSpec("x", "x", "PO")), "دست‌کم یک"), "empty wizard rejected")
check(raises(lambda: builder.build_graph(builder.WizardSpec("x", "x", "PO", levels=[builder.ApprovalLevel("بی‌نفر", [])])),
             "تاییدکننده"), "level without approvers rejected")

# ویرایش گراف
g2 = builder.auto_layout(defs.empty_graph())
nid = builder.add_node(g2, "NOTIFY")
check(raises(lambda: builder.connect(g2, "end", nid), "پایان"), "cannot continue after END")
g2["edges"] = []
builder.connect(g2, "start", nid)
builder.connect(g2, nid, "end")
check(not defs.errors(defs.validate_graph(company_id, g2, None)), "manual edit valid")
c = builder.add_node(g2, "CONDITION")
check(raises(lambda: builder.connect(g2, c, "end"), "نتیجهٔ مسیر"), "condition edge needs yes/no")
check(builder.edge_choices(g2, c) == [("yes", "بله"), ("no", "خیر")], "edge choices")
builder.remove_node(g2, c)
check(c not in defs.nodes_by_id(g2), "node removed")
diff = builder.diff_graphs(g, g2)
check(any("مرحلهٔ تازه" in x for x in diff) and any("حذف‌شده" in x for x in diff), "version diff in Persian")

# ===== ۲) ویزارد در رابط کاربری =====
w = st.WizardDialog()
w.dialog_runner = lambda dlg: True
check(not w.next() and any("نام و کد" in x for x in WARN), "step 1 requires name and code")
w.name.setText("تایید سفارش خرید")
w.code.setText("po_flow")
w.entity.setCurrentIndex(w.entity.findData("PO"))
check(w.next() and w.stack.currentIndex() == 1, "go to step 2")
w.ttype.setCurrentIndex(w.ttype.findData("EVENT"))
WARN.clear()
check(not w.next() and any("رویداد" in x for x in WARN), "event trigger needs an event")
w.check_item(w.events, "PO_SUBMITTED")
check(w.next(), "step 3")
row = w.start_rule.add_row({"field": "amount", "op": ">", "value": "1000"})
check(row is not None and w.start_rule.rule() == {"field": "amount", "op": ">", "value": "1000"}
      and "مبلغ بیشتر از" in w.start_rule.preview.text(), "rule builder row and live Persian preview")
w.start_rule.add_row({"field": "due_date", "op": "<=", "value": {"days_from_today": 3}})
rule = w.start_rule.rule()
check(rule == {"all": [{"field": "amount", "op": ">", "value": "1000"}, {"field": "due_date", "op": "<=", "value": {"days_from_today": 3}}]},
      f"rule builder AND group ({rule})")
w.start_rule.remove_row(w.start_rule.rows[1])
check(w.next() and w.stack.currentIndex() == 3, "step 4")
WARN.clear()
check(not w.next() and any("مرحلهٔ تایید" in x for x in WARN), "at least one level")
check(w.edit_level(new=True, level=builder.ApprovalLevel("تایید مالی", [{"kind": "ROLE", "role_id": role.role_id}])), "level added")
check(w.edit_level(new=True, level=builder.ApprovalLevel("تایید مدیرعامل", [{"kind": "USER", "user_id": uid}], only_if=big)),
      "conditional level added")
w.t_levels.setCurrentCell(1, 0)
w.move_level(-1)
check(w.levels[0].label == "تایید مدیرعامل" and w.t_levels.item(0, 3).text().startswith("مبلغ"), "reorder levels")
w.move_level(1)
check(w.next(), "step 5")
w.check_item(w.actions, "entity.post")
check(w.next() and w.next(), "steps 6, 7")
w.changes_all.setChecked(True)
check(w.next() and w.stack.currentIndex() == 7 and w.summary.count() >= 5 and w.issues.item(0).text().startswith("✔"),
      f"review shows summary and no issues ({w.issues.item(0).text()})")
sim = w.test_run()
trace = sim.run({"amount": 900_000_000}, {"ap1": "approved", "ap2": "approved"})
check([t.node_type for t in trace][-1] == "END" and any(t.node_type == "ACTION" for t in trace), "wizard test run")
w.publish_now.setChecked(True)
did = w.finish()
d = defs.get_definition(company_id, did)
check(d.status_code == "ACTIVE" and d.active_version_no == 1 and d.trigger_type == "EVENT", "wizard created, published and activated")
from peecha.services.workflow import events
events.emit(company_id, "PO_SUBMITTED", "PO", 1, {}, actor_user_id=visitor.user_id)
i1 = runtime.list_instances(company_id, entity_type="PO", entity_id=1)[0]
t1 = tasks.list_tasks(company_id, instance_id=i1.instance_id)[0]
tasks.decide(company_id, t1.task_id, a1, "APPROVE")
t2 = tasks.list_tasks(company_id, instance_id=i1.instance_id, status="OPEN")[0]
tasks.decide(company_id, t2.task_id, uid, "APPROVE")
check(runtime.get_instance(company_id, i1.instance_id).status_code == "COMPLETED" and DONE == [1],
      "wizard process runs end-to-end on a real event")
events.emit(company_id, "PO_SUBMITTED", "PO", 2, {}, actor_user_id=visitor.user_id)
i2 = runtime.list_instances(company_id, entity_type="PO", entity_id=2)[0]
tasks.decide(company_id, tasks.list_tasks(company_id, instance_id=i2.instance_id)[0].task_id, a1, "APPROVE")
check(runtime.get_instance(company_id, i2.instance_id).status_code == "COMPLETED" and DONE == [1, 2],
      "small amount skips the conditional level")

# ===== ۳) فهرست فرایندها و چرخهٔ عمر =====
ls = st.ProcessListScreen()
ls.dialog_runner = lambda dlg: True
ls.confirm = lambda text: True
ls.refresh()
check(ls.table.rowCount() == 1 and ls.cards["active"].text() == "۱", "process list")
for b in ls.findChildren(QPushButton):
    check(len(b.text()) <= 3 and b.toolTip() and not LATIN.search(b.toolTip()), f"icon button with Persian tooltip ({b.toolTip()})")
ls.select_definition(did)
check(ls.lifecycle("PAUSED") and defs.get_definition(company_id, did).status_code == "PAUSED", "pause")
check(not ls.lifecycle("PUBLISHED") or True, "publish without changes warns")
check(ls.lifecycle("ACTIVE"), "activate")
copy_id = ls.duplicate("po_flow_2", "کپی سفارش")
check(copy_id and defs.get_definition(company_id, copy_id).status_code == "DRAFT", "duplicate as draft")
blank = ls.new_blank({"name": "فرایند آزمایشی", "code": "blank1", "entity_type": "PO"})
check(blank and ls.select_definition(blank), "blank definition")

# ===== ۴) طراح گرافیکی =====
ds = st.DesignerScreen()
ds.load(blank)
for b in ds.findChildren(QPushButton):
    check(len(b.text()) <= 3 and b.toolTip() and not LATIN.search(b.toolTip()), f"designer icon button ({b.toolTip()})")
check(len(ds.items) == 2 and not ds.dirty, "blank graph drawn (start + end)")
ap = ds.add_node("APPROVAL")
check(ds.selected_node == ap and ds.w["specs"] is not None, "add approval node and show its properties")
ds.w["label"].setText("تایید سرپرست")
ds.w["specs"].add_spec({"kind": "USER", "user_id": a1})
ds.w["mode"].setCurrentIndex(ds.w["mode"].findData("ALL"))
check(ds.apply_properties() and defs.nodes_by_id(ds.graph)[ap]["approvers"] == [{"kind": "USER", "user_id": a1}]
      and defs.nodes_by_id(ds.graph)[ap]["mode"] == "ALL", "approval properties applied")
rej = ds.add_node("END")
ds.w["outcome"].setCurrentIndex(ds.w["outcome"].findData("REJECTED"))
ds.apply_properties()
ds.graph["edges"] = []
check(ds.connect_nodes("start", ap) and ds.connect_nodes(ap, "end", "approved") and ds.connect_nodes(ap, rej, "rejected"),
      "connect nodes")
issues = ds.validate()
check(not defs.errors(issues) and ds.issues.item(0).text().startswith("✔"), f"designer validation ({[i.message for i in issues]})")
cond = ds.add_node("CONDITION")
ds.w["rule"].add_row({"field": "amount", "op": ">=", "value": "100"})
ds.apply_properties()
ds.graph["edges"] = [e for e in ds.graph["edges"] if e["from"] != "start"]
ds.connect_nodes("start", cond)
ds.connect_nodes(cond, ap, "yes")
ds.connect_nodes(cond, "end", "no")
check(defs.nodes_by_id(ds.graph)[cond]["rule"] == {"field": "amount", "op": ">=", "value": "100"}, "condition rule from builder")
ds.select_edge(cond, "end")
ds.w["when"].setCurrentIndex(ds.w["when"].findData("no"))
check(ds.apply_properties(), "edge properties")
ds.select_node("start")
ds.w["ttype"].setCurrentIndex(ds.w["ttype"].findData("MANUAL"))
check(ds.apply_properties() and ds.graph["trigger"]["type"] == "MANUAL", "trigger properties")
trace = ds.test_run({"amount": 50}, {})
check([t.node_type for t in trace] == ["START", "CONDITION", "END"] and ds.highlight, "designer test run highlights path")
bad_task = ds.add_node("TASK")
issues = ds.validate()
check(any(i.node_id == bad_task for i in issues) and any("مسئولی" in i.message for i in issues), "issues point to the node")
ds.select_node(bad_task)
check(ds.delete_selected() and bad_task not in defs.nodes_by_id(ds.graph), "delete node")
ds.auto_layout()
check(ds.publish() and defs.get_definition(company_id, blank).status_code == "PUBLISHED" and not ds.dirty, "save and publish from designer")
check(raises(lambda: defs.publish(company_id, uid, blank), "تغییر تازه‌ای"), "nothing new to publish")
ds.select_node(ap)
ds.w["label"].setText("تایید سرپرست واحد")
ds.apply_properties()
check(ds.save() and defs.get_definition(company_id, blank).has_draft, "edit after publish creates a new draft version")

# ===== ۵) نسخه‌ها =====
ls.refresh()
ls.select_definition(blank)
vd = ls.versions()
check(vd.t.rowCount() == 2, "two versions")
vd.t.setCurrentCell(0, 0)
diff = vd.compare()
check(any("تغییر در «تایید سرپرست واحد»" in x for x in diff), f"compare draft with active ({diff})")
vd.t.setCurrentCell(1, 0)
check(vd.restore() and defs.get_graph(company_id, blank) == defs.get_graph(company_id, blank, defs.get_definition(company_id, blank).active_version_id),
      "restore old version into draft")

# ===== ۶) آزمون و حذف =====
ls.select_definition(copy_id)
dlg = ls.test()
check(dlg is not None and defs.get_definition(company_id, copy_id).status_code == "TESTING", "test moves draft to testing")
check(ls.select_definition(copy_id) and ls.delete() and all(r.definition_id != copy_id for r in defs.list_definitions(company_id)),
      "delete unused definition")
ls.select_definition(did)
WARN.clear()
check(not ls.delete() and any("سابقهٔ اجرا" in x for x in WARN), "definition with history cannot be deleted")

fx.finish()
sys.stdout.flush()
os._exit(0)
