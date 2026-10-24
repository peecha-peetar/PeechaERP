"""R331: فرایندی که از ترتیب اقدام‌هایش معلوم است گیر می‌کند (مثل «رد» پس از «تصویب» در فرایند کاربر) تعریف نمی‌شود؛
تعریف قدیمی همین‌طوری سند را قفل نمی‌کند؛ مسیر سند می‌گوید هر کار با کیست و کجا انجام می‌شود."""
import os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r331"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prd_fixture import *  # noqa: F401,F403

import dataclasses

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox
from sqlalchemy import text

app = QApplication.instance() or QApplication([])
QMessageBox.warning = staticmethod(lambda *a, **k: None)
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
# همان فرایند تصویر کاربر: پس از تایید، همهٔ اقدام‌ها تیک خورده بود (از جمله «رد درخواست خرید»)
USER_ACTIONS = ["entity.approve", "entity.reject", "emit_event", "set_variable", "add_comment", "create_followup", "call_api",
                "send_message"]


def login(u):
    with new_session() as s:
        sess.current_user = s.get(User, u)
        s.expunge_all()


def spec(code, actions, levels=None, entity_type="PURCHASE_REQUEST", events=("PURCHASE_REQUEST_SUBMITTED",)):
    levels = [builder.ApprovalLevel("تایید درخواست", MGR)] if levels is None else levels
    return builder.WizardSpec(code, code, entity_type, "", {"type": "EVENT", "events": list(events), "gate": True}, None,
                              levels, list(actions), reject_actions=["entity.reject"])


def graph_of(actions, entity_type="PURCHASE_REQUEST", events=("PURCHASE_REQUEST_SUBMITTED",)):
    # builder همهٔ کدها را می‌پذیرد؛ مثل ویزارد قدیمی که «رد» را هم در فهرست پس از تایید داشت
    return builder.build_graph(spec("g", actions, entity_type=entity_type, events=events))


def errors(graph, entity_type="PURCHASE_REQUEST"):
    return [i.message for i in defs.errors(defs.validate_graph(company_id, graph, entity_type))]


def new_request():
    login(servin)
    r = prs.create_request(company_id, servin, prs.RequestFields(request_date=today, warehouse_id=wh_rm))
    prs.add_line(r, company_id, r1, kg, D(4), None, supplier, D(1000))
    prs.submit_request(r, company_id)
    return r


def status(r):
    return prs.get_request(r, company_id)[0].status_code


def instance(r):
    return runtime.list_instances(company_id, entity_type="PURCHASE_REQUEST", entity_id=r)[0]


def my_task(user, r):
    return next(t for t in tasks.list_my_tasks(company_id, user) if t.entity_id == r)


# --- ۱: ترتیب متناقض اقدام‌ها از همان ابتدا تعریف نمی‌شود -------------------------------------------------------
msgs = errors(graph_of(USER_ACTIONS))
check(any("رد درخواست خرید" in m and "پس از «تصویب درخواست خرید»" in m for m in msgs),
      f"«reject» after «approve» is refused with the reason ({msgs})")
check(any("ارسال پیام" in m and "الگوی پیام" in m for m in msgs), "a message without template or text is refused")
did = defs.create_definition(company_id, uid, code="user_flow", name="تایید درخواست و تبدیل به سفارش", entity_type="PURCHASE_REQUEST")
defs.save_draft(company_id, uid, did, graph_of(USER_ACTIONS))
check(raises(lambda: defs.publish(company_id, uid, did), "پس از «تصویب درخواست خرید»"), "and cannot be published")
check(not errors(graph_of(["entity.approve", "add_comment"])), "approve then note is fine")
check(not errors(builder.build_graph(spec("ok", ["entity.approve"]))), "the reject path keeps «reject» (on the sent request)")

so = ("SALES_ORDER_CONFIRMED",)
check(any("پس از «تصویب سند»" in m for m in errors(graph_of(["entity.approve", "entity.reject"], "SALES_ORDER", so),
                                                    "SALES_ORDER")), "sales order: reject after approve refused")
check(not errors(graph_of(["entity.approve", "entity.post"], "SALES_ORDER", so), "SALES_ORDER"), "sales order: approve then post is fine")
check(any("پس از «ثبت نهایی سند»" in m for m in errors(graph_of(["entity.post", "entity.approve"], "SALES_ORDER", so),
                                                       "SALES_ORDER")), "sales order: approve after post refused")
st = ("STOCK_ISSUE_CONFIRMED",) if "STOCK_ISSUE_CONFIRMED" in dict(registry.event_choices("STOCK_ISSUE")) else None
if st:
    check(any("پس از" in m for m in errors(graph_of(["entity.post", "entity.reject"], "STOCK_ISSUE", st), "STOCK_ISSUE")),
          "stock document: reject after post refused")

# --- ۲: ویزارد: «رد» جای خودش، «تصویب» پیش‌فرض، پیام بی‌الگو پنهان؛ خلاصه با چه کسی/کجا ---------------------------
from peecha.ui.screens.workflow_studio import WizardDialog  # noqa: E402

login(uid)
w = WizardDialog(None)
w.entity.setCurrentIndex(w.entity.findData("PURCHASE_REQUEST"))
listed = {w.actions.item(i).data(Qt.UserRole): w.actions.item(i).checkState() for i in range(w.actions.count())}
check("entity.reject" not in listed and "send_message" not in listed and listed.get("entity.approve") == Qt.Checked,
      f"after-approval list: no «reject», no empty message, «approve» ticked ({listed})")
w.name.setText("تایید درخواست")
w.code.setText("wiz_pr")
w.check_item(w.events, "PURCHASE_REQUEST_SUBMITTED")
w.dialog_runner = lambda dlg: True
w.edit_level(new=True, level=builder.ApprovalLevel("تایید مدیر", MGR))
w.edit_level(new=True, level=builder.ApprovalLevel("تبدیل به سفارش", [{"kind": "USER", "user_id": buyer}], kind="TASK"))
w.go(7)
lines = [w.summary.item(i).text() for i in range(w.summary.count())]
check(any("مدیر بازرگانی" in x and "کارتابل من" in x and "تایید یا رد" in x for x in lines)
      and any("کارشناس خرید" in x and "انجام شد" in x for x in lines)
      and any("خودکار" in x and "تصویب درخواست خرید" in x for x in lines) and any(x.startswith("اگر رد شود") for x in lines),
      f"the review says who does what and where ({lines})")
check(w.issues.item(0).text().startswith("✔"), f"no issues ({w.issues.item(0).text()})")

# --- ۳: فرایند قدیمی کاربر (منتشرشده پیش از این قاعده) دیگر سند را قفل نمی‌کند --------------------------------------
legacy = defs.create_definition(company_id, uid, code="legacy", name="تایید درخواست و تبدیل به سفارش", entity_type="PURCHASE_REQUEST")
defs.save_draft(company_id, uid, legacy, builder.build_graph(spec("legacy", ["entity.approve", "add_comment"])))
defs.publish(company_id, uid, legacy)
old_graph = graph_of(USER_ACTIONS)
with new_session() as s:
    s.execute(text("UPDATE wf.definition_versions SET graph = CAST(:g AS jsonb) WHERE definition_id = :d"),
              {"g": __import__("json").dumps(old_graph), "d": legacy})
    s.commit()
runtime._GRAPH_CACHE.clear()
check(legacy in defs.problems(company_id), "the old process is flagged «needs fixing»")
req = new_request()
login(mgr)
tasks.decide(company_id, my_task(mgr, req).task_id, mgr, "APPROVE", "")
inst = instance(req)
check(status(req) == "APPROVED" and inst.status_code == "COMPLETED" and inst.outcome_code == "APPROVED",
      f"approved and finished, nothing locked ({status(req)}, {inst.status_code})")
check(model_events.busy(company_id, "PURCHASE_REQUEST", req) is None, "the request is free to convert")
log = {x.step: x for x in monitor.execution_log(company_id, inst.instance_id)}
check(log["رد درخواست خرید"].status == "کنار گذاشته شد" and "کنار گذاشته شد" in log["رد درخواست خرید"].detail,
      f"«reject» was set aside, not failed ({log['رد درخواست خرید'].status}: {log['رد درخواست خرید'].detail})")
check(log["افزودن یادداشت"].status == "انجام شد", "the note still ran")
check(all(log[k].status == "کنار گذاشته شد" for k in ("انتشار رویداد برای فرایند دیگر", "ثبت مقدار در فرایند",
                                                       "فراخوانی سرویس بیرونی مجاز")), "unconfigured actions set aside")
with new_session() as s:
    noisy = s.scalar(select(func.count()).select_from(Notification).where(Notification.title.like("%انجام نشد%")))
check(noisy == 0, f"no failure notices for set-aside steps ({noisy})")

# --- ۴: سندی که با نسخهٔ قبل در همین فرایند قفل شده بود، با یک «اجرای دوباره» باز می‌شود --------------------------------
adapter = registry.get_adapter("PURCHASE_REQUEST")
real_reject = adapter.actions["reject"]
adapter.actions["reject"] = dataclasses.replace(real_reject, requires_status=())  # رفتار قبلی: بی‌بررسی اجرا می‌شد
stuck = new_request()
login(mgr)
tasks.decide(company_id, my_task(mgr, stuck).task_id, mgr, "APPROVE", "")
adapter.actions["reject"] = real_reject
failure = model_events.failed(company_id, "PURCHASE_REQUEST", stuck)
check(failure and "رد درخواست خرید" in failure[1] and status(stuck) == "APPROVED", f"reproduced the lock ({failure})")
path = runtime.path_steps(company_id, instance(stuck).instance_id)
auto = next(p for p in path if p.kind == "AUTO")
check(auto.state == "failed" and "کارهای خودکار سیستم" in auto.label and "رد درخواست خرید" in auto.members,
      f"the path shows the automatic steps as one failed step ({auto})")
login(uid)
scr = PurchaseRequestScreen()
scr.refresh()
scr.edit_document(stuck)
check(scr.workflow_bar.retry_failed(), "one «run again» from the request")
check(instance(stuck).status_code == "COMPLETED" and model_events.busy(company_id, "PURCHASE_REQUEST", stuck) is None
      and status(stuck) == "APPROVED", "unlocked; the request stays approved")
path = runtime.path_steps(company_id, instance(stuck).instance_id)
check(all(p.state == "done" for p in path), f"after the retry every step shows done ({[(p.label, p.state) for p in path]})")
defs.set_status(company_id, uid, legacy, "PAUSED")

# --- ۵: مسیر سند: هر کار با کیست و کجا؛ کارهای خودکار جدا ------------------------------------------------------------
flow = defs.create_definition(company_id, uid, code="clear", name="تایید و تبدیل", entity_type="PURCHASE_REQUEST")
defs.save_draft(company_id, uid, flow, builder.build_graph(spec("clear", ["entity.approve", "add_comment"], levels=[
    builder.ApprovalLevel("تایید مدیر", MGR),
    builder.ApprovalLevel("تبدیل به سفارش", [{"kind": "USER", "user_id": buyer}], kind="TASK")])))
defs.publish(company_id, uid, flow)
req = new_request()
path = runtime.path_steps(company_id, instance(req).instance_id)
human = [p for p in path if p.kind == "HUMAN"]
check([p.text for p in human] == ["تایید مدیر (مدیر بازرگانی)", "تبدیل به سفارش (کارشناس خرید)"]
      and [p.state for p in human] == ["current", "pending"], f"each human step names who ({[(p.text, p.state) for p in human]})")
check(any(p.kind == "AUTO" and p.label == "کارهای خودکار سیستم (۲)" and p.state == "pending" for p in path),
      "automatic steps grouped and not shown as someone's job")
login(servin)
scr = PurchaseRequestScreen()
scr.refresh()
scr.edit_document(req)
tip = scr.workflow_bar.path.toolTip()
text_ = scr.workflow_bar.path.text()
check("مدیر بازرگانی" in text_ and "اکنون نوبت مدیر بازرگانی در «کارتابل من»" in text_, f"the bar says whose turn it is ({text_})")
check("تایید مدیر: مدیر بازرگانی — در «کارتابل من»" in tip and "خودکار، بدون دخالت کسی" in tip
      and "تبدیل به سفارش: کارشناس خرید" in tip, f"the tooltip explains every step ({tip})")
login(mgr)
tasks.decide(company_id, my_task(mgr, req).task_id, mgr, "APPROVE", "")
human = [p for p in runtime.path_steps(company_id, instance(req).instance_id) if p.kind == "HUMAN"]
check(human[0].state == "done" and human[0].who == "مدیر بازرگانی" and human[1].state == "current"
      and human[1].who == "کارشناس خرید", f"after approval it is the buyer's turn ({[(p.text, p.state) for p in human]})")

finish()
