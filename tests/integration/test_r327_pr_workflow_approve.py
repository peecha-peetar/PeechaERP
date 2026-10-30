"""R327: درخواست خرید هماهنگ با گردش کار: تاییدکنندهٔ بی‌نقش «مدیر» واقعاً تصویب می‌کند، «تصویب/رد» خود فرم برای
تاییدکننده کار می‌کند، اقدام شکست‌خورده از خود سند دوباره اجرا می‌شود، درخواست بی‌فرایند به گردش کار فرستاده می‌شود،
و دکمه‌های فرم در پنجرهٔ کوچک دیده می‌شوند."""
import os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r327"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prd_fixture import *  # noqa: F401,F403

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication, QInputDialog, QMessageBox

app = QApplication.instance() or QApplication([])
WARN = []
QMessageBox.warning = staticmethod(lambda *a, **k: WARN.append(a[2] if len(a) > 2 else ""))
QMessageBox.information = staticmethod(lambda *a, **k: None)
QInputDialog.getText = staticmethod(lambda *a, **k: ("مبلغ بالاست", True))

from peecha.db.models.security import User
from peecha.services import purchase_requests as prs, roles as roles_service, users as users_service
from peecha.services.workflow import builder, definitions as defs, model_events, registry, runtime, tasks
from peecha.ui.screens.purchase_requests import PurchaseRequestScreen

registry.ensure_loaded()
staff = users_service.create_user("staff1", "کارمند خرید", "secret123", None, lang_id, False, [company_id], company_id).user_id
appr = users_service.create_user("appr1", "سارا تاییدی", "secret123", None, lang_id, False, [company_id], company_id).user_id
mgr = users_service.create_user("mgr1", "مدیر بازرگانی", "secret123", None, lang_id, False, [company_id], company_id).user_id
roles_service.set_user_role(mgr, roles_service.create_role(company_id, "MANAGER", None).role_id, company_id, True)


def login(u):
    with new_session() as s:
        sess.current_user = s.get(User, u)
        s.expunge_all()


def new_request():
    login(staff)
    r = prs.create_request(company_id, staff, prs.RequestFields(request_date=today, warehouse_id=wh_rm))
    prs.add_line(r, company_id, r1, kg, D(4), None, supplier, D(1000))
    prs.submit_request(r, company_id)
    return r


def form(req, user):
    login(user)
    scr = PurchaseRequestScreen()
    scr.refresh()
    scr.edit_document(req)
    return scr


def status(req):
    return prs.get_request(req, company_id)[0].status_code


def my_task(user, req):
    return next(t for t in tasks.list_my_tasks(company_id, user) if t.entity_id == req)


early = new_request()  # پیش از تعریف فرایند فرستاده شده

# همان فرایند کاربر: تایید ← «تصویب درخواست خرید» ← «افزودن یادداشت» ← خبر؛ رد ← «رد درخواست خرید»
spec = builder.WizardSpec("تایید درخواست", "pr_flow", "PURCHASE_REQUEST", "",
                          {"type": "EVENT", "events": ["PURCHASE_REQUEST_SUBMITTED"], "gate": True}, None,
                          [builder.ApprovalLevel("تایید درخواست", [{"kind": "USER", "user_id": appr}])],
                          ["entity.approve", "add_comment"], reject_actions=["entity.reject"])
did = defs.create_definition(company_id, uid, code="pr_flow", name="تایید درخواست", entity_type="PURCHASE_REQUEST")
defs.save_draft(company_id, uid, did, builder.build_graph(spec))
defs.publish(company_id, uid, did)

# --- ۱: تاییدکنندهٔ بی‌نقش «مدیر» در کارتابل تایید می‌کند و درخواست واقعاً تصویب می‌شود ---------------------------
req = new_request()
check(not roles_service.is_manager(appr, company_id), "the approver has no manager role")
login(appr)
tasks.decide(company_id, my_task(appr, req).task_id, appr, "APPROVE", "موافقم")
row = prs.get_request(req, company_id)[0]
inst = runtime.list_instances(company_id, entity_type="PURCHASE_REQUEST", entity_id=req)[0]
check(row.status_code == "APPROVED" and row.approved_by_user_id == appr, f"approved by the workflow's approver ({row.status_code})")
check(inst.status_code == "COMPLETED" and inst.outcome_code == "APPROVED",
      f"process finished; the note step without text no longer fails ({inst.status_code})")
check(not model_events.busy(company_id, "PURCHASE_REQUEST", req), "nothing blocks the next step")
check(form(req, staff).buttons["convert"].isEnabled(), "the request is ready to become a purchase order")
check(raises(lambda: prs.approve_request(early, company_id, appr), "فقط برای مدیر"),
      "outside the workflow, a non-manager still cannot approve")

# --- ۲: «تصویب» و «رد» در خود فرم درخواست ----------------------------------------------------------------------
req2 = new_request()
scr = form(req2, staff)
check(not scr.buttons["approve"].isEnabled() and "سارا تاییدی" in scr.buttons["approve"].toolTip(),
      f"requester: approve disabled and says who decides ({scr.buttons['approve'].toolTip()})")
check("سارا تاییدی" in scr.workflow_bar.path.text(), "workflow bar names who it is waiting for")
scr = form(req2, mgr)
check(not scr.buttons["approve"].isEnabled() and "منتظر تصمیم" in scr.buttons["approve"].toolTip(),
      "a manager who is not this step's approver sees who must decide")
scr = form(req2, appr)
check(scr.buttons["approve"].isEnabled() and scr.buttons["reject"].isEnabled()
      and "منتظر شماست" in scr.buttons["approve"].toolTip(), "approver: approve and reject work in the request form")
scr.buttons["approve"].click()
check(status(req2) == "APPROVED" and "تصویب شد" in scr.status_label.text(), f"approved from the form ({scr.status_label.text()})")

req3 = new_request()
scr = form(req3, appr)
scr.buttons["reject"].click()
row = prs.get_request(req3, company_id)[0]
check(row.status_code == "REJECTED" and "مبلغ بالاست" in (row.rejected_reason or ""), "rejected from the form through the workflow")

# --- ۳: اقدام «تصویب درخواست خرید» شکست بخورد ← پیام روشن و «اجرای دوباره» از خود سند ----------------------------
real = prs.approve_request


def broken(*_a, **_k):
    raise ValueError("بودجهٔ این مرکز هزینه بسته است.")


prs.approve_request = broken
req4 = new_request()
login(appr)
tasks.decide(company_id, my_task(appr, req4).task_id, appr, "APPROVE", "")
prs.approve_request = real
check(status(req4) == "SUBMITTED", "the failed approval left the request submitted")
msg = model_events.busy(company_id, "PURCHASE_REQUEST", req4)
check(msg and "تصویب درخواست خرید" in msg and "اجرای دوباره" in msg and "بودجه" in msg, f"the lock says which step failed ({msg})")
scr = form(req4, staff)
check(not scr.workflow_bar.warning.isHidden() and scr.workflow_bar.retry_button.isHidden()
      and not scr.buttons["approve"].isEnabled(), "the requester sees the problem but cannot retry")
scr = form(req4, mgr)
bar = scr.workflow_bar
check(not bar.warning.isHidden() and "تصویب درخواست خرید" in bar.warning.text() and not bar.retry_button.isHidden(),
      "the manager sees the failure and a retry button in the request form")
check(scr.buttons["approve"].isEnabled() and "دوباره اجرا" in scr.buttons["approve"].toolTip(), "the manager's approve re-runs it")
scr.buttons["approve"].click()
check(status(req4) == "APPROVED" and bar.retry_button.isHidden() and bar.warning.isHidden(), "approved after the retry")

# --- ۴: درخواستی که پیش از تعریف فرایند فرستاده شده: «تصویب» مدیر آن را به گردش کار می‌فرستد -------------------------
check(model_events.unsent_gate(company_id, "PURCHASE_REQUEST", early) == [did], "the early request has not been through the process")
scr = form(early, mgr)
check(scr.buttons["approve"].isEnabled() and "فرستاده می‌شود" in scr.buttons["approve"].toolTip()
      and scr.workflow_bar.send_button.isEnabled(), "manager: approve (and the bar) send it to the process")
WARN.clear()
scr.buttons["approve"].click()
check(not any("ابتدا آن را" in w for w in WARN), f"no dead-end «send it first» message ({WARN})")
check(any(t.entity_id == early for t in tasks.list_my_tasks(company_id, appr)), "now waiting in the approver's cartable")
check("سارا تاییدی" in scr.status_label.text(), f"the form says who decides next ({scr.status_label.text()})")
check(not model_events.unsent_gate(company_id, "PURCHASE_REQUEST", early), "not offered again while running")

# --- ۵: دکمه‌های فرم در پنجرهٔ کوچک دیده می‌شوند --------------------------------------------------------------------
check(not getattr(PurchaseRequestScreen, "scroll_in_mdi", False), "the window does not scroll the whole form (buttons included)")
scr = form(req2, staff)
scr.resize(1100, 420)
scr.show()
app.processEvents()
btn = scr.buttons["save"]
y = btn.mapTo(scr, QPoint(0, 0)).y()
check(btn.isVisible() and 0 <= y and y + btn.height() <= scr.height(), f"footer buttons stay inside a small window ({y}, {scr.height()})")
check(not scr.body_scroll.isAncestorOf(btn) and scr.body_scroll.isAncestorOf(scr.lines_table)
      and not scr.body_scroll.isAncestorOf(scr.workflow_bar), "only the form body scrolls")
check(scr.lines_table.height() >= 130 and scr.body_scroll.verticalScrollBar().maximum() > 0,
      "fields keep their height and the body scrolls instead")

finish()
