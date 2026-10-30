"""R326: درخواست خرید ارسال‌شده توسط کاربر عادی (بدون دسترسی تصویب) جایی برای تصویب دارد: کارتابل مدیر؛ و «ارسال برای
تصویب» فرایند تایید دستی را هم شروع می‌کند."""
import os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r326"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prd_fixture import *  # noqa: F401,F403

from PySide6.QtWidgets import QApplication, QMessageBox

app = QApplication.instance() or QApplication([])
QMessageBox.warning = staticmethod(lambda *a, **k: None)
QMessageBox.information = staticmethod(lambda *a, **k: None)

from peecha.db.models.security import User
from peecha.services import purchase_requests as prs, roles as roles_service, users as users_service
from peecha.services.workflow import builder, definitions as defs, inbox, registry, runtime, tasks
from peecha.ui.screens import my_tasks
from peecha.ui.screens.purchase_requests import PurchaseRequestScreen

registry.ensure_loaded()
staff = users_service.create_user("staff1", "کارمند خرید", "secret123", None, lang_id, False, [company_id], company_id).user_id
mgr = users_service.create_user("mgr1", "مدیر بازرگانی", "secret123", None, lang_id, False, [company_id], company_id).user_id
role = roles_service.create_role(company_id, "MANAGER", None)
roles_service.set_user_role(mgr, role.role_id, company_id, True)


def login(u):
    with new_session() as s:
        sess.current_user = s.get(User, u)
        s.expunge_all()


def new_request():
    login(staff)
    r = prs.create_request(company_id, staff, prs.RequestFields(request_date=today, warehouse_id=wh_rm))
    prs.add_line(r, company_id, r1, kg, D(4), None, supplier, D(1000))
    return r


# --- بدون فرایند: کاربر عادی نمی‌تواند تصویب کند، مدیر در کارتابلش می‌بیند ------------------------------------
req = new_request()
scr = PurchaseRequestScreen()
scr.refresh()
scr.edit_document(req)
scr.submit()
check(prs.get_request(req, company_id)[0].status_code == "SUBMITTED", "requester submitted for approval")
check(not scr.buttons["approve"].isEnabled(), "the requester has no approve button (only a manager approves)")
items = [w for w in inbox.my_work(company_id, staff) if w.extra.get("kind") == "PR_APPROVAL"]
check(not items, "the requester's cartable has nothing to approve")
login(mgr)
items = [w for w in inbox.my_work(company_id, mgr) if w.extra.get("kind") == "PR_APPROVAL"]
check(len(items) == 1 and items[0].extra["document_id"] == req and "تصویب" in items[0].action and "درخواست خرید" in items[0].title,
      f"the manager's cartable lists it ({[(w.title, w.action) for w in items]})")

opened = {}


class MW:
    def open_screen(self, code, then=None):
        opened["code"] = code
        if then:
            then(PurchaseRequestScreen())


check(my_tasks.open_operational_task(MW(), "PR_APPROVAL", "PURCHASE_REQUEST", req) and opened["code"] == "PURCH_REQUESTS",
      "the cartable card opens the request screen")
scr2 = PurchaseRequestScreen()
scr2.refresh()
scr2.edit_document(req)
check(scr2.buttons["approve"].isEnabled(), "the manager sees the approve button on the request")
scr2.approve()
check(prs.get_request(req, company_id)[0].status_code == "APPROVED", "approved by the manager")
check(not [w for w in inbox.my_work(company_id, mgr) if w.extra.get("kind") == "PR_APPROVAL"], "gone from the cartable once approved")

# --- با فرایند تایید «دستی»: ارسال برای تصویب، فرایند را هم شروع می‌کند -------------------------------------------
spec = builder.WizardSpec("تایید دستی", "pr_manual", "PURCHASE_REQUEST", "", {"type": "MANUAL"}, None,
                          [builder.ApprovalLevel("تایید مدیر", [{"kind": "USER", "user_id": mgr}])], ["entity.approve"],
                          reject_actions=["entity.reject"])
did = defs.create_definition(company_id, uid, code="pr_manual", name="تایید دستی", entity_type="PURCHASE_REQUEST")
defs.save_draft(company_id, uid, did, builder.build_graph(spec))
defs.publish(company_id, uid, did)
req2 = new_request()
scr3 = PurchaseRequestScreen()
scr3.refresh()
scr3.edit_document(req2)
scr3.submit()
inst = runtime.list_instances(company_id, entity_type="PURCHASE_REQUEST", entity_id=req2)
check(len(inst) == 1 and inst[0].status_code == "WAITING", "«ارسال برای تصویب» also started the manual approval process")
login(mgr)
check(any(t.entity_id == req2 for t in tasks.list_my_tasks(company_id, mgr)), "the approver has the task in the cartable")
check(not [w for w in inbox.my_work(company_id, mgr) if w.extra.get("kind") == "PR_APPROVAL"],
      "no duplicate card: the process owns it")
t = next(t for t in tasks.list_my_tasks(company_id, mgr) if t.entity_id == req2)
tasks.decide(company_id, t.task_id, mgr, "APPROVE", "تایید")
check(prs.get_request(req2, company_id)[0].status_code == "APPROVED", "approved through the process")

finish()
