"""R296: پایش فرایندها، ریز اجرا، گلوگاه‌ها، تحلیل مهلت/خطا و گزارش‌ها روی موتور مشترک گزارش."""
import os, sys, datetime
os.environ["PEECHA_DB_NAME"] = "peecha_test_r296"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crm_fixture import *  # noqa: F401,F403
import crm_fixture as fx
from types import SimpleNamespace
from sqlalchemy import select
from peecha.db.models.workflow import WfTask
from peecha.services import roles as roles_service, users as users_service
from peecha.services.workflow import (
    definitions as defs, exceptions as wf_exc, monitor, registry, runtime, scheduler, sla, tasks,
)
from peecha.services.workflow.registry import ActionSpec, EntityAdapter, FieldSpec
check, raises = fx.check, fx.raises


def mk_user(code, name):
    return users_service.create_user(code, name, "secret123", None, lang_id, False, [company_id], company_id).user_id


a1, a2 = mk_user("mon1", "تاییدکنندهٔ یک"), mk_user("mon2", "تاییدکنندهٔ دو")
requester = visitor.user_id
DOCS = {}
STATE = {"fail": True}


def _book(ctx):
    if STATE["fail"]:
        raise ValueError("حساب هزینه برای این درخواست تعریف نشده است.")
    DOCS[ctx.entity_id]["status"] = "BOOKED"
    return {}


registry.register_adapter(EntityAdapter(
    "REQ6", "درخواست هزینه", "FINANCE", lambda cid, eid: dict(DOCS[eid], doc_id=eid),
    fields=(FieldSpec("amount", "مبلغ", "money"), FieldSpec("requested_by", "درخواست‌کننده", "user")),
    actions={"book": ActionSpec("book", "ثبت هزینه", _book)},
    title=lambda c: f"درخواست هزینه {c['doc_id']}", submitter_field="requested_by"))
pol = sla.save_policy(company_id, uid, None, code="mon", name="مهلت یک‌روزه", due_hours=8, warn_before_hours=2,
                      escalate_after_hours=2, max_escalations=1, business_hours=False)
graph = {"trigger": {"type": "MANUAL"},
         "nodes": [{"id": "ap", "type": "APPROVAL", "label": "تایید مدیر", "approvers": [{"kind": "USER", "user_id": a1}],
                    "sla_policy_id": pol},
                   {"id": "fin", "type": "APPROVAL", "label": "تایید مالی", "approvers": [{"kind": "USER", "user_id": a2}]},
                   {"id": "ok", "type": "END", "label": "تایید", "outcome": "APPROVED"},
                   {"id": "no", "type": "END", "label": "رد", "outcome": "REJECTED"}],
         "edges": [{"from": "start", "to": "ap"}, {"from": "ap", "to": "fin", "when": "approved"}, {"from": "ap", "to": "no", "when": "rejected"},
                   {"from": "fin", "to": "ok", "when": "approved"}, {"from": "fin", "to": "no", "when": "rejected"}]}
d_appr = defs.create_definition(company_id, uid, code="EXP", name="تایید هزینه", entity_type="REQ6", graph=graph)
defs.publish(company_id, uid, d_appr)
g2 = {"trigger": {"type": "MANUAL"},
      "nodes": [{"id": "act", "type": "ACTION", "label": "ثبت هزینه", "action": "entity.book", "retry": {"max": 1}},
                {"id": "ok", "type": "END", "label": "پایان", "outcome": "DONE"}],
      "edges": [{"from": "start", "to": "act"}, {"from": "act", "to": "ok"}]}
d_book = defs.create_definition(company_id, uid, code="BOOK", name="ثبت خودکار هزینه", entity_type="REQ6", graph=g2)
defs.publish(company_id, uid, d_book)


def new_doc(amount):
    eid = len(DOCS) + 1
    DOCS[eid] = {"amount": amount, "requested_by": requester, "status": "NEW"}
    return eid


def start(d, eid):
    return runtime.start_instance(company_id, d, "REQ6", eid, started_by=requester)


def decide(iid, who, decision, comment=""):
    t = tasks.list_tasks(company_id, instance_id=iid, status="OPEN")[0]
    return tasks.decide(company_id, t.task_id, who, decision, comment or decision)


approved = start(d_appr, new_doc(100))
decide(approved, a1, "APPROVE")
decide(approved, a2, "APPROVE")
rejected = start(d_appr, new_doc(200))
decide(rejected, a1, "REJECT", "مدرک ناقص است")
waiting = start(d_appr, new_doc(300))  # منتظر مدیر و بعد گذشته از مهلت
decide_later = start(d_appr, new_doc(400))
decide(decide_later, a1, "APPROVE")  # منتظر مالی
cancelled = start(d_appr, new_doc(500))
runtime.cancel_instance(company_id, cancelled, uid, "تکراری")
failing = start(d_book, new_doc(600))

# مهلت: گذشتن از زمان ارجاع برای کار منتظر
with new_session() as s:
    t_wait = s.scalar(select(WfTask).where(WfTask.instance_id == waiting, WfTask.status_code == "OPEN"))
    esc_at = t_wait.escalate_at
scheduler.fire_due_timers(company_id, esc_at + datetime.timedelta(minutes=1))

# ===== خلاصه =====
o = monitor.overview(company_id)
check(o.completed == 2 and o.cancelled == 1 and o.waiting == 3 and o.failed == 0, f"overview counts by status ({o})")
check(o.escalated == 1, "escalated count")
check(o.open_exceptions == 1, "open exception from failed action counted")
check(o.approval_rate == D(50), "approval rate: one approved, one rejected")
check(o.avg_hours is not None and o.avg_hours >= 0, "average duration of completed runs")
check(monitor.overview(company_id, definition_id=d_book).completed == 0, "overview filtered by process")

# ===== فهرست اجراها و فیلترها =====
all_runs = monitor.runs(company_id)
check(len(all_runs) == 6, "all runs listed")
check([r.instance_id for r in monitor.runs(company_id, status="ESCALATED")] == [waiting], "filter: escalated")
check([r.instance_id for r in monitor.runs(company_id, status="EXCEPTION")] == [failing], "filter: needs attention")
check({r.instance_id for r in monitor.runs(company_id, status="COMPLETED")} == {approved, rejected}, "filter: completed")
check([r.instance_id for r in monitor.runs(company_id, search="درخواست هزینه 4")] == [decide_later], "search by title")
w = next(r for r in all_runs if r.instance_id == decide_later)
check(w.waiting_on == "تایید مالی" and w.entity_label == "درخواست هزینه", "waiting step and document label")
future = datetime.date.today() + datetime.timedelta(days=5)
check(monitor.runs(company_id, date_from=future) == [], "date filter")

# ===== ریز اجرا =====
log = monitor.execution_log(company_id, rejected)
check(any(x.kind == "تصمیم" and x.status == "رد" and "ناقص" in x.detail for x in log), "log shows decision with comment")
check(any(x.step == "تایید مدیر" and x.hours is not None for x in log), "log shows step durations")
flog = monitor.execution_log(company_id, failing)
check(any(x.kind == "اجرای اقدام" and x.status == "ناموفق" and "حساب هزینه" in x.detail for x in flog),
      "log shows failed action with its error")
check(monitor.execution_log(company_id + 999, failing) == [], "log of another company is empty")

# ===== گلوگاه‌ها و گزارش‌ها =====
b = monitor.bottleneck_rows(company_id)
check(b and b[0]["step"] == "تایید مدیر" and b[0]["tasks"] == 5 and b[0]["escalated"] == 1, "bottleneck: manager step slowest")
F = SimpleNamespace(date_from=datetime.date.today() - datetime.timedelta(days=1), date_to=datetime.date.today(), options={})
r = monitor.report_process_summary(company_id, F)
row = next(x for x in r.rows if x[0] == "تایید هزینه")
check(row[2] == 5 and row[4] == 1 and row[5] == 1 and row[7] == 1 and row[8] == D(50), "process summary report")
r = monitor.report_sla(company_id, F)
check(any(x[1] == "تایید مدیر" and x[2] == 5 and x[3] == 4 and x[4] == 0 and x[7] == 1 for x in r.rows), "SLA report: on-time and escalated per step")
r = monitor.report_approvers(company_id, F)
a1_row = next(x for x in r.rows if x[0] == "تاییدکنندهٔ یک")
check(a1_row[1] == 3 and a1_row[2] == 2 and a1_row[3] == 1, "approver report counts decisions")
r = monitor.report_failures(company_id, F)
check(r.rows and r.rows[0][1] == "ثبت هزینه" and r.rows[0][4] == 1 and "حساب هزینه" in r.rows[0][7], "failure report")
r = monitor.report_exceptions(company_id, F)
check(len(r.rows) == 1 and r.rows[0][3] == "باز" and r.refs[0] == (failing, "WF_INSTANCE"), "exceptions report with drill")
r = monitor.report_escalations(company_id, F)
check(len(r.rows) == 1 and r.rows[0][2] == 1, "escalations report")
r = monitor.report_runs(company_id, SimpleNamespace(date_from=F.date_from, date_to=F.date_to, options={"status": "FAILED"}))
check(r.rows == [], "runs report status option")
r = monitor.report_runs(company_id, F)
check(len(r.rows) == 6 and all(ref[1] == "WF_INSTANCE" for ref in r.refs), "runs report drills to instance")
from peecha.services.warehouse_reports import WAREHOUSE_REPORTS_BY_CODE  # noqa: E402
check(all(c in WAREHOUSE_REPORTS_BY_CODE for c in ("WF_RUNS", "WF_SUMMARY", "WF_BOTTLENECKS", "WF_SLA", "WF_APPROVERS",
                                                   "WF_FAILURES", "WF_EXCEPTIONS", "WF_ESCALATIONS")),
      "reports registered on the shared report engine")
from peecha import nav_catalog  # noqa: E402
codes = set()


def walk(items):
    for it in items:
        codes.add(it.get("code"))
        walk(it.get("children") or [])


walk(nav_catalog.NAV_ITEMS)
check({"WF_MONITOR", "REPORTS_WF", "WF_REPORTS", "WF_RPT_WF_RUNS"} <= codes, "menu items for monitor and reports")

# ===== صفحهٔ پایش =====
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
qapp = QApplication.instance() or QApplication([])
qapp.setLayoutDirection(Qt.RightToLeft)
WARN = []
QMessageBox.warning = staticmethod(lambda *a, **k: WARN.append(a[2] if len(a) > 2 else ""))
from peecha import session as sess  # noqa: E402
from peecha.db.models.core import Company  # noqa: E402
from peecha.db.models.security import User  # noqa: E402
with new_session() as s:
    sess.current_user = s.get(User, uid)
    sess.current_company = s.get(Company, company_id)
    s.expunge_all()
from peecha.ui.screens import workflow_monitor as wm  # noqa: E402
scr = wm.WorkflowMonitorScreen()
scr.refresh()
check(scr.table.rowCount() == 6 and scr.cards["escalated"].text() != "—" and scr.bottlenecks.rowCount() >= 1,
      "monitor screen lists runs, cards and bottlenecks")
check(all(len(b.text()) <= 2 for b in scr.buttons.values()), "monitor uses icon buttons only")
check(scr.open_instance(failing) and scr.log.rowCount() >= 1 and scr.tabs.currentIndex() == 2, "open_instance shows execution log")
check(scr.buttons["retry"].isEnabled() and not scr.buttons["cancel"].isEnabled() is False, "retry enabled for exception")
STATE["fail"] = False
check(scr.retry() and runtime.get_instance(company_id, failing).status_code == "COMPLETED", "retry from monitor completes the run")
scr.open_instance(decide_later)
check(scr.cancel("دیگر لازم نیست") and runtime.get_instance(company_id, decide_later).status_code == "CANCELLED",
      "cancel from monitor with reason")
check(tasks.list_tasks(company_id, instance_id=decide_later, status="OPEN") == [], "open tasks closed on cancel")
scr.open_instance(waiting)
WARN.clear()
check(scr.cancel("") is False and WARN, "cancel needs a reason")
scr.status_filter.setCurrentIndex(scr.status_filter.findData("CANCELLED"))
scr.reload()
check(scr.table.rowCount() == 2, "status filter on screen")
from peecha.ui.screens.purchase_reports import PurchaseReportScreen  # noqa: E402
rs = PurchaseReportScreen("WF_SUMMARY", None, side="INVENTORY")
rs.refresh()
check(rs is not None, "workflow report opens in the shared report screen")

fx.finish()
