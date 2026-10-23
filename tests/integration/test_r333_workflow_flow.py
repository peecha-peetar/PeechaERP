"""R333: روند کلی: چند فرایند پشت‌سرهم یا هم‌زمان («فرایند فرعی»)، رد که روند را متوقف می‌کند، پیوستن به فرایندی که
در جریان است، سنجش مرحلهٔ فرعی، و طراح گرافیکی (خانه‌ها با ارتفاع کامل، انتخاب نوع سند و رویداد در شروع فرایند)."""
import os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r333"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prd_fixture import *  # noqa: F401,F403

from PySide6.QtWidgets import QApplication, QLineEdit, QMessageBox

app = QApplication.instance() or QApplication([])
QMessageBox.warning = staticmethod(lambda *a, **k: None)
QMessageBox.information = staticmethod(lambda *a, **k: None)

from peecha.db.models.commercial import CommercialDocument
from peecha.db.models.security import User
from peecha.db.models.workflow import WfInstance
from peecha.services import purchase_requests as prs, roles as roles_service, users as users_service
from peecha.services import commercial_documents as docs
from peecha.services.workflow import builder, definitions as defs, registry, runtime, simulate, tasks
from peecha.ui.screens import workflow_bar, workflow_studio as studio

registry.ensure_loaded()
servin = users_service.create_user("servin", "سروین", "secret123", None, lang_id, False, [company_id], company_id).user_id
mgr = users_service.create_user("mgr1", "مدیر بازرگانی", "secret123", None, lang_id, False, [company_id], company_id).user_id
keeper = users_service.create_user("keeper1", "انباردار", "secret123", None, lang_id, False, [company_id], company_id).user_id
roles_service.set_user_role(mgr, roles_service.create_role(company_id, "MANAGER", None).role_id, company_id, True)
MGR = [{"kind": "USER", "user_id": mgr}]
KEEPER = [{"kind": "USER", "user_id": keeper}]
SUBMITTED = {"type": "EVENT", "events": ["PURCHASE_REQUEST_SUBMITTED"]}


def login(u):
    with new_session() as s:
        sess.current_user = s.get(User, u)
        s.expunge_all()


def publish(spec):
    did = defs.create_definition(company_id, uid, code=spec.code, name=spec.name, entity_type=spec.entity_type)
    defs.save_draft(company_id, uid, did, builder.build_graph(spec))
    defs.publish(company_id, uid, did)
    return did


def new_request(submit=True):
    login(servin)
    r = prs.create_request(company_id, servin, prs.RequestFields(request_date=today, warehouse_id=wh_rm))
    prs.add_line(r, company_id, r1, kg, D(4), None, supplier, D(1000))
    if submit:
        prs.submit_request(r, company_id)
    return r


def orders_of(r):
    with new_session() as s:
        return list(s.scalars(select(CommercialDocument).where(CommercialDocument.document_type_code == "PURCHASE_ORDER",
                                                               CommercialDocument.description.like(f"%{prs.get_request(r, company_id)[0].request_no}"))))


def inst_of(definition_id, et, eid):
    return [i for i in runtime.list_instances(company_id, entity_type=et, entity_id=eid) if i.definition_id == definition_id]


def my_task(user, et, eid):
    return next((t for t in tasks.list_my_tasks(company_id, user) if t.entity_type == et and t.entity_id == eid), None)


def messages(graph, et="PURCHASE_REQUEST", definition_id=None):
    return [i.message for i in defs.validate_graph(company_id, graph, et, definition_id)]


# --- فرایندهای سازندهٔ روند: تایید درخواست، تایید سفارش، هماهنگی انبار (هر سه بدون شروع خودکار) -----------------------
pr_ok = publish(builder.WizardSpec("تایید درخواست", "r333_pr", "PURCHASE_REQUEST", "", {"type": "MANUAL"}, None,
                                   [builder.ApprovalLevel("تایید مدیر", MGR)], ["entity.approve"],
                                   reject_actions=["entity.reject"], notify_on_approve=False, notify_on_reject=False))
po_ok = publish(builder.WizardSpec("تایید سفارش", "r333_po", "PURCHASE_ORDER", "", {"type": "MANUAL"}, None,
                                   [builder.ApprovalLevel("تایید مدیر", MGR)], ["entity.approve"], notify_on_approve=False))
pr_task = publish(builder.WizardSpec("هماهنگی انبار", "r333_wh", "PURCHASE_REQUEST", "", {"type": "MANUAL"}, None,
                                     [builder.ApprovalLevel("جای کالا را آماده کن", KEEPER, kind="TASK")], [],
                                     notify_on_approve=False))
draft_only = defs.create_definition(company_id, uid, code="r333_draft", name="هنوز منتشرنشده", entity_type="PURCHASE_REQUEST")

# --- ۱: ساخت روند کلی در «ساخت روند کلی» ----------------------------------------------------------------------------
login(uid)
dlg = studio.FlowDialog()
dlg.name.setText("روند کامل خرید")
dlg.code.setText("r333_flow")
studio.set_combo(dlg.entity, "PURCHASE_REQUEST")
studio.set_combo(dlg.ttype, "EVENT")
check(dlg.events.count() > 0 and not dlg.events.isHidden(), "choosing the document type fills the start events")
studio.WizardDialog().check_item(dlg.events, "PURCHASE_REQUEST_SUBMITTED")
dlg.add_process(pr_ok)
dlg.add_action("entity.convert")
dlg.add_process(po_ok, "CREATED")
dlg.add_process(pr_task, together=True)
dlg.add_action("add_comment")
check([dlg.t_steps.item(r, 3).text() for r in range(dlg.t_steps.rowCount())] ==
      ["پس از پایان قبلی", "پس از پایان قبلی", "پس از پایان قبلی", "هم‌زمان با قبلی", "پس از پایان قبلی"],
      "the steps table shows which step runs together with the previous one")
plan = [dlg.summary.item(i).text() for i in range(dlg.summary.count())]
check(any("تایید درخواست" in x and "منتظر می‌ماند" in x for x in plan) and
      any(x.startswith("۳. هم‌زمان") and "تایید سفارش" in x and "هماهنگی انبار" in x for x in plan),
      f"the review explains the flow in plain words ({plan})")
check(dlg.problem() is None, f"the flow is valid ({[dlg.issues.item(i).text() for i in range(dlg.issues.count())]})")
dlg.publish_now.setChecked(True)
flow = dlg.finish()
check(flow and defs.get_definition(company_id, flow).status_code == "ACTIVE", "the flow is created, published and active")
graph = defs.get_graph(company_id, flow)
types = [n["type"] for n in graph["nodes"]]
check(types.count("SUBPROCESS") == 3 and "PARALLEL" in types and "JOIN" in types, f"three sub-process steps and one parallel stage ({types})")
check(not defs.errors(defs.validate_graph(company_id, graph, "PURCHASE_REQUEST", flow)), "the published flow has no errors")
trace = simulate.simulate(company_id, graph, "PURCHASE_REQUEST")
check(any(t.node_type == "SUBPROCESS" and "اجرا می‌شد" in t.result for t in trace) and trace[-1].node_type == "END",
      "the test run walks through the sub-processes to the end")

# --- ۲: اجرای کامل: تایید درخواست ← سفارش ← (تایید سفارش | هماهنگی انبار) ← پایان ------------------------------------------
req = new_request()
flow_inst = inst_of(flow, "PURCHASE_REQUEST", req)
child = inst_of(pr_ok, "PURCHASE_REQUEST", req)
check(len(flow_inst) == 1 and flow_inst[0].status_code == "WAITING", "submitting the request starts the overall flow")
check(len(child) == 1 and child[0].status_code == "WAITING" and my_task(mgr, "PURCHASE_REQUEST", req),
      "its first step started «تایید درخواست» and the manager got the approval")
steps = runtime.path_steps(company_id, flow_inst[0].instance_id)
check(any(st.kind == "SUB" and st.label == "تایید درخواست" and st.state == "current" for st in steps) and
      any(st.kind == "PARALLEL" and st.state == "pending" for st in steps), f"the flow path shows the waiting sub-process ({[(s.label, s.state) for s in steps]})")
tip = workflow_bar.path_tooltip("روند کامل خرید", steps)
check("منتظر می‌ماند" in tip and "هم‌زمان:" in tip, f"the tooltip says what runs and what waits ({tip})")

login(mgr)
tasks.decide(company_id, my_task(mgr, "PURCHASE_REQUEST", req).task_id, mgr, "APPROVE", "")
check(prs.get_request(req, company_id)[0].status_code == "APPROVED", "the request is approved in its own process")
po = orders_of(req)
check(len(po) == 1, f"the flow went on by itself and made the purchase order ({len(po)})")
po_id = po[0].document_id
po_child = inst_of(po_ok, "PURCHASE_ORDER", po_id)
wh_child = inst_of(pr_task, "PURCHASE_REQUEST", req)
check(len(po_child) == 1 and len(wh_child) == 1 and po_child[0].status_code == "WAITING" and wh_child[0].status_code == "WAITING",
      "the order approval (on the new order) and the warehouse task (on the request) run together")
check(my_task(mgr, "PURCHASE_ORDER", po_id) and my_task(keeper, "PURCHASE_REQUEST", req), "each one is in its owner's cartable")
tasks.decide(company_id, my_task(mgr, "PURCHASE_ORDER", po_id).task_id, mgr, "APPROVE", "")
check(docs.get_document(po_id, company_id)[0].status_code == "APPROVED", "the order is approved")
check(runtime.get_instance(company_id, flow_inst[0].instance_id).status_code == "WAITING",
      "the flow still waits for the parallel warehouse task")
login(keeper)
tasks.decide(company_id, my_task(keeper, "PURCHASE_REQUEST", req).task_id, keeper, "DONE", "")
done = runtime.get_instance(company_id, flow_inst[0].instance_id)
check(done.status_code == "COMPLETED" and done.outcome_code == "DONE", f"after both, the flow finished ({done.status_code}, {done.outcome_code})")
steps = runtime.path_steps(company_id, flow_inst[0].instance_id)
check(all(st.state == "done" for st in steps), f"every step of the flow path is done ({[(s.label, s.state) for s in steps]})")

# --- ۳: رد در فرایند فرعی روند را متوقف می‌کند --------------------------------------------------------------------------
bad = new_request()
login(mgr)
tasks.decide(company_id, my_task(mgr, "PURCHASE_REQUEST", bad).task_id, mgr, "REJECT", "بودجه ندارد")
stopped = inst_of(flow, "PURCHASE_REQUEST", bad)[0]
check(stopped.status_code == "COMPLETED" and stopped.outcome_code == "REJECTED" and not orders_of(bad),
      f"a rejection ends the flow as «rejected» and nothing else runs ({stopped.status_code}, {stopped.outcome_code})")

# --- ۴: فرایندی که از قبل روی همان سند در جریان است، دوباره شروع نمی‌شود؛ روند به آن می‌پیوندد -----------------------------
early = new_request(submit=False)
login(servin)
first = runtime.start_instance(company_id, pr_ok, "PURCHASE_REQUEST", early, started_by=servin)
prs.submit_request(early, company_id)
check(len(inst_of(pr_ok, "PURCHASE_REQUEST", early)) == 1, "the running «تایید درخواست» is not started twice")
with new_session() as s:
    parents = (s.get(WfInstance, first).variables or {}).get("parents") or []
joined = inst_of(flow, "PURCHASE_REQUEST", early)
check(joined and any(p.get("instance_id") == joined[0].instance_id for p in parents), "the flow joined the running process")
login(mgr)
tasks.decide(company_id, my_task(mgr, "PURCHASE_REQUEST", early).task_id, mgr, "APPROVE", "")
check(len(orders_of(early)) == 1, "approving it moves the joined flow on as well")

# --- ۵: سنجش مرحلهٔ فرعی ------------------------------------------------------------------------------------------------
lonely = builder.build_flow("PURCHASE_REQUEST", SUBMITTED, [builder.FlowStep("PROCESS", pr_ok)])
for n in lonely["nodes"]:
    if n["type"] == "SUBPROCESS":
        n.pop("definition_id")
check(any("فرایندی انتخاب نشده" in m for m in messages(lonely)), "a sub-process step without a process is refused")
wrong = builder.build_flow("PURCHASE_REQUEST", SUBMITTED, [builder.FlowStep("PROCESS", po_ok)])
check(any("«اجرا روی»" in m for m in messages(wrong)), "running an order process on the request itself is refused")
nothing = builder.build_flow("PURCHASE_REQUEST", SUBMITTED, [builder.FlowStep("PROCESS", po_ok, target="CREATED")])
check(any("هیچ مرحله‌ای" in m for m in messages(nothing)), "«made in earlier steps» without a step that makes one is refused")
loop = builder.build_flow("PURCHASE_REQUEST", SUBMITTED, [builder.FlowStep("PROCESS", flow)])
check(any("حلقهٔ بی‌پایان" in m for m in messages(loop, definition_id=flow)), "a flow that runs itself is refused")
no_default = builder.build_flow("PURCHASE_REQUEST", SUBMITTED, [builder.FlowStep("PROCESS", pr_ok)])
no_default["edges"] = [e for e in no_default["edges"] if not (e["from"].startswith("sub") and not e.get("when"))]
check(any("باید مسیر «ادامه»" in m for m in messages(no_default)), "a sub-process step needs its «continue» path")
idle = builder.build_flow("PURCHASE_REQUEST", SUBMITTED, [builder.FlowStep("PROCESS", draft_only),
                                                          builder.FlowStep("ACTION", "add_comment")])
check(any("هنوز فعال نیست" in i.message for i in defs.validate_graph(company_id, idle, "PURCHASE_REQUEST") if i.level == "warning")
      and not defs.errors(defs.validate_graph(company_id, idle, "PURCHASE_REQUEST")), "an inactive process is only a warning")
idle_flow = defs.create_definition(company_id, uid, code="r333_idle", name="روند با مرحلهٔ غیرفعال", entity_type="PURCHASE_REQUEST",
                                   graph={**idle, "trigger": {"type": "MANUAL"}})
defs.publish(company_id, uid, idle_flow)
idle_req = new_request(submit=False)
idle_inst = runtime.start_instance(company_id, idle_flow, "PURCHASE_REQUEST", idle_req, started_by=uid)
check(runtime.get_instance(company_id, idle_inst).status_code == "COMPLETED", "at run time the inactive step is set aside and the flow ends")

# --- ۶: طراح گرافیکی: نوع سند و رویداد در شروع، خانه‌ها با ارتفاع کامل، مرحلهٔ فرعی ---------------------------------------
login(uid)
blank = defs.create_definition(company_id, uid, code="r333_blank", name="فرایند تازه")
screen = studio.DesignerScreen()
screen.resize(1100, 420)
screen.show()
screen.load(blank)
screen.select_node(defs.START)
check("entity_type" in screen.w and screen.w["events"].count() == 0 and "events_hint" in screen.w,
      "a process without a document type shows «نوع سند» and says why there are no events")
studio.set_combo(screen.w["entity_type"], "PURCHASE_REQUEST")
check(screen.entity_type == "PURCHASE_REQUEST" and screen.w["events"].count() > 0, "choosing the document type fills the events")
studio.set_combo(screen.w["ttype"], "EVENT")
studio.WizardDialog().check_item(screen.w["events"], "PURCHASE_REQUEST_SUBMITTED")
screen.apply_properties()
check(screen.graph["trigger"] == {"type": "EVENT", "events": ["PURCHASE_REQUEST_SUBMITTED"]}, "the chosen event is saved in the start step")
check(screen.save() and defs.get_definition(company_id, blank).entity_type == "PURCHASE_REQUEST",
      "saving stores the document type of the process")
studio.set_combo(screen.w["ttype"], "SCHEDULE")
check(screen.w["events"].isHidden() and not screen.w["every"].isHidden(), "only the fields of the chosen start type are shown")
check(screen.props_scroll.widget() is screen.props_host, "the properties are in a scrolling panel")
nid = screen.add_node("APPROVAL")
for _ in range(3):
    app.processEvents()
edits = [w for w in screen.w.values() if isinstance(w, QLineEdit)]
check(screen.props_scroll.viewport().height() < screen.props_host.height() and edits and
      all(w.height() >= w.sizeHint().height() for w in edits),
      f"approval fields keep their full height in a short window ({[(w.height(), w.sizeHint().height()) for w in edits]})")
sub = screen.add_node("SUBPROCESS")
check({"definition_id", "target"} <= set(screen.w), "the sub-process step asks which process and on which document")
studio.set_combo(screen.w["definition_id"], pr_ok)
screen.apply_properties()
node = defs.nodes_by_id(screen.graph)[sub]
check(node.get("definition_id") == pr_ok and node.get("label") == "تایید درخواست" and node.get("target") == "SAME",
      "the chosen process is saved and names the step")
published = studio.DesignerScreen()
published.load(flow)
published.select_node(defs.START)
check("entity_type" not in published.w and published.w["events"].count() > 0, "a published process keeps its document type")
check(raises(lambda: defs.set_entity_type(company_id, uid, flow, "PURCHASE_ORDER"), "عوض نمی‌شود"),
      "the service refuses to change the document type of a published process")

finish()
