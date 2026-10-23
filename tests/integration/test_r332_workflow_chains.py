"""R332: زنجیرهٔ فرایندهای خودکار: درخواست خرید تاییدشده خودکار سفارش می‌شود و برای تصویب می‌رود، فرایند سفارش
شروع می‌شود، پس از تصویب و رسید کالا فاکتور خودکار صادر می‌شود؛ فهرست فرایندها و بازبینی ویزارد زنجیره را نشان می‌دهند."""
import os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r332"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prd_fixture import *  # noqa: F401,F403

from PySide6.QtWidgets import QApplication, QMessageBox

app = QApplication.instance() or QApplication([])
QMessageBox.warning = staticmethod(lambda *a, **k: None)
QMessageBox.information = staticmethod(lambda *a, **k: None)

from peecha.db.models.commercial import CommercialDocument
from peecha.db.models.security import Notification, User
from peecha.db.models.workflow import WfEvent
from peecha.services import commercial_documents as docs, purchase_requests as prs, roles as roles_service
from peecha.services import commercial_settings as csettings, users as users_service
from peecha.services.workflow import builder, definitions as defs, registry, runtime, tasks, templates

registry.ensure_loaded()
servin = users_service.create_user("servin", "سروین", "secret123", None, lang_id, False, [company_id], company_id).user_id
mgr = users_service.create_user("mgr1", "مدیر بازرگانی", "secret123", None, lang_id, False, [company_id], company_id).user_id
keeper = users_service.create_user("keeper1", "انباردار", "secret123", None, lang_id, False, [company_id], company_id).user_id
roles_service.set_user_role(mgr, roles_service.create_role(company_id, "MANAGER", None).role_id, company_id, True)
MGR = [{"kind": "USER", "user_id": mgr}]


def login(u):
    with new_session() as s:
        sess.current_user = s.get(User, u)
        s.expunge_all()


def publish(spec):
    did = defs.create_definition(company_id, uid, code=spec.code, name=spec.name, entity_type=spec.entity_type)
    defs.save_draft(company_id, uid, did, builder.build_graph(spec))
    defs.publish(company_id, uid, did)
    return did


def new_request(with_supplier=True):
    login(servin)
    r = prs.create_request(company_id, servin, prs.RequestFields(request_date=today, warehouse_id=wh_rm))
    prs.add_line(r, company_id, r1, kg, D(4), None, supplier if with_supplier else None, D(1000))
    prs.submit_request(r, company_id)
    return r


def orders_of(r):
    with new_session() as s:
        return list(s.scalars(select(CommercialDocument).where(CommercialDocument.document_type_code == "PURCHASE_ORDER",
                                                               CommercialDocument.description.like(f"%{prs.get_request(r, company_id)[0].request_no}"))))


def instances(et, eid):
    return runtime.list_instances(company_id, entity_type=et, entity_id=eid)


def my_task(user, et, eid):
    return next(t for t in tasks.list_my_tasks(company_id, user) if t.entity_type == et and t.entity_id == eid)


# --- ۱: اقدام‌ها و رویدادهای زنجیره، و سنجش ترتیب --------------------------------------------------------------------
codes = [c for c, _l, _r in registry.action_choices("PURCHASE_REQUEST")]
check("entity.convert" in codes, "purchase request offers «convert to order»")
check({"entity.confirm", "entity.to_invoice"} <= {c for c, _l, _r in registry.action_choices("PURCHASE_ORDER")},
      "purchase order offers «send for approval» and «issue invoice»")
check("PURCHASE_ORDER_FROM_REQUEST" in dict(registry.event_choices("PURCHASE_ORDER")), "event «order made from request»")


def pr_spec(code, actions):
    return builder.WizardSpec(code, code, "PURCHASE_REQUEST", "", {"type": "EVENT", "events": ["PURCHASE_REQUEST_SUBMITTED"],
                                                                   "gate": True}, None,
                              [builder.ApprovalLevel("تایید مدیر", MGR)], list(actions), reject_actions=["entity.reject"])


msgs = [i.message for i in defs.errors(defs.validate_graph(company_id, builder.build_graph(pr_spec("x", ["entity.convert"])),
                                                         "PURCHASE_REQUEST"))]
check(any("تبدیل خودکار به سفارش خرید" in m for m in msgs), f"converting before the request is approved is refused ({msgs})")
check(not defs.errors(defs.validate_graph(company_id, builder.build_graph(pr_spec("x", ["entity.approve", "entity.convert"])),
                                          "PURCHASE_REQUEST")), "approve then convert is valid")
po_from_req = builder.WizardSpec("p", "p", "PURCHASE_ORDER", "", {"type": "EVENT", "events": ["PURCHASE_ORDER_FROM_REQUEST"]}, None,
                                 [builder.ApprovalLevel("تایید", MGR)], ["entity.approve"])
check(any("تصویب سند" in i.message for i in defs.errors(defs.validate_graph(company_id, builder.build_graph(po_from_req),
                                                                            "PURCHASE_ORDER"))),
      "an order made from a request is a draft: approving it without «send for approval» is refused")
po_from_req.actions = ["entity.confirm", "entity.approve"]
check(not defs.errors(defs.validate_graph(company_id, builder.build_graph(po_from_req), "PURCHASE_ORDER")),
      "«send for approval» then «approve» is valid")

# --- ۲: زنجیره: قالب درخواست ← تایید سفارش ← فاکتور پس از رسید --------------------------------------------------------
pr_flow = templates.install(company_id, uid, "PURCHASE_REQUEST_TO_ORDER")
defs.publish(company_id, uid, pr_flow)
po_flow = publish(builder.WizardSpec("تایید سفارش خرید", "po_ok", "PURCHASE_ORDER", "",
                                     {"type": "EVENT", "events": ["PURCHASE_ORDER_CONFIRMED"], "gate": True}, None,
                                     [builder.ApprovalLevel("تایید مدیر", MGR)], ["entity.approve"], reject_actions=["entity.reject"]))
inv_flow = templates.install(company_id, uid, "PURCHASE_ORDER_TO_INVOICE")
graph = defs.get_graph(company_id, inv_flow)
for n in graph["nodes"]:
    if n["type"] == "TASK":
        n["assignees"] = [{"kind": "USER", "user_id": keeper}]
defs.save_draft(company_id, uid, inv_flow, graph)
defs.publish(company_id, uid, inv_flow)
note_flow = publish(builder.WizardSpec("خبر سفارش از درخواست", "po_note", "PURCHASE_ORDER", "",
                                       {"type": "EVENT", "events": ["PURCHASE_ORDER_FROM_REQUEST"]}, None, [],
                                       ["add_comment"], notify_on_approve=False))

chain = defs.chains(company_id)
check(chain.get(pr_flow) == ["تایید سفارش خرید", "خبر سفارش از درخواست"] and chain.get(po_flow) ==
      ["صدور خودکار فاکتور خرید پس از رسید کالا"], f"the process list shows what starts after each process ({chain})")
lines = builder.plan_lines(defs.get_graph(company_id, pr_flow), "PURCHASE_REQUEST", company_id)
check(any(x.startswith("سپس خودکار") and "تایید سفارش خرید" in x for x in lines), f"the wizard review shows the chain ({lines})")

req = new_request()
login(mgr)
tasks.decide(company_id, my_task(mgr, "PURCHASE_REQUEST", req).task_id, mgr, "APPROVE", "")
check(prs.get_request(req, company_id)[0].status_code == "APPROVED", "the request is approved")
po = orders_of(req)
check(len(po) == 1 and po[0].status_code == "CONFIRMED", f"one order was made and sent for approval ({[(o.document_id, o.status_code) for o in po]})")
po_id = po[0].document_id
pr_inst = instances("PURCHASE_REQUEST", req)[0]
check(pr_inst.status_code == "COMPLETED", "the request's process finished")
check(any("سفارش خرید ساخته شد" in r.detail for r in runtime.timeline(company_id, pr_inst.instance_id)),
      "the request's history says an order was made")
po_insts = {i.definition_id: i for i in instances("PURCHASE_ORDER", po_id)}
check(po_flow in po_insts and po_insts[po_flow].status_code == "WAITING", "the order's approval process started by itself")
check(note_flow in po_insts and po_insts[note_flow].status_code == "COMPLETED", "the «made from request» event started its process")
with new_session() as s:
    ev = s.scalar(select(WfEvent).where(WfEvent.event_type == "PURCHASE_ORDER_FROM_REQUEST", WfEvent.entity_id == po_id))
    ev_cause, ev_depth = ev.causation_instance_id, ev.depth
check(ev_cause == pr_inst.instance_id and ev_depth == 1, "the chained event knows which process caused it (loop guard)")

tasks.decide(company_id, my_task(mgr, "PURCHASE_ORDER", po_id).task_id, mgr, "APPROVE", "")
check(docs.get_document(po_id, company_id)[0].status_code == "APPROVED", "the manager approves the order in the cartable")
inv_inst = next(i for i in instances("PURCHASE_ORDER", po_id) if i.definition_id == inv_flow)
check(inv_inst.status_code == "WAITING" and my_task(keeper, "PURCHASE_ORDER", po_id), "the warehouse keeper gets «confirm receipt»")
if csettings.is_feature_enabled(company_id, "PURCHASE_ORDER_GOODS_RECEIPT"):
    docs.approve_warehouse(po_id, company_id, keeper)
login(keeper)
tasks.decide(company_id, my_task(keeper, "PURCHASE_ORDER", po_id).task_id, keeper, "DONE", "")
with new_session() as s:
    invoices = list(s.scalars(select(CommercialDocument).where(CommercialDocument.document_type_code == "PURCHASE_INVOICE")))
check(len(invoices) == 1 and runtime.get_instance(company_id, inv_inst.instance_id).status_code == "COMPLETED",
      f"the purchase invoice was issued automatically ({len(invoices)})")
check(docs.get_document(invoices[0].document_id, company_id)[1], "the invoice has the order's lines")

# --- ۳: تبدیل ناموفق (ردیف بی‌تامین‌کننده) سند را قفل نمی‌کند --------------------------------------------------------
bad = new_request(with_supplier=False)
login(mgr)
tasks.decide(company_id, my_task(mgr, "PURCHASE_REQUEST", bad).task_id, mgr, "APPROVE", "")
inst = instances("PURCHASE_REQUEST", bad)[0]
check(prs.get_request(bad, company_id)[0].status_code == "APPROVED" and inst.status_code == "COMPLETED" and not orders_of(bad),
      "no supplier: the request stays approved, the process finishes, nothing is locked")
with new_session() as s:
    told = s.scalar(select(Notification).where(Notification.title.like("%تبدیل خودکار به سفارش خرید%انجام نشد%")))
check(told is not None, "and someone is told to convert it by hand")
orders = prs.convert_to_orders(bad, company_id, mgr, supplier_id=supplier)
check(len(orders) == 1 and any(i.definition_id == note_flow for i in instances("PURCHASE_ORDER", orders[0])),
      "a manual conversion continues the chain too")
ctx = runtime.load_context(company_id, "PURCHASE_ORDER", orders[0])
check(ctx["line_count"] == 1, "the chained process sees the complete order (with its lines)")

finish()
