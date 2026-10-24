"""R325: نام فارسی نقش‌های آماده، فرم درخواست خرید در پنجرهٔ کوچک (اسکرول به‌جای له‌شدن فیلدها)، آیکن جدا برای ساخت هر
سند در «اسناد خرید»، و مرحلهٔ گردش کار بی‌گیرنده که سند را بی‌صدا گیر می‌انداخت."""
import os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r325"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prd_fixture import *  # noqa: F401,F403

from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton

app = QApplication.instance() or QApplication([])
WARN = []
QMessageBox.warning = staticmethod(lambda *a, **k: WARN.append(a[2] if len(a) > 2 else ""))
QMessageBox.information = staticmethod(lambda *a, **k: None)

from peecha.services import purchase_requests as prs, roles as roles_service, users as users_service
from peecha.services.production import roles_setup as prd_roles
from peecha.services.workflow import builder, definitions as defs, inbox, model_events, registry, runtime, tasks
from peecha.services.workflow.common import save_settings

registry.ensure_loaded()

# --- ۱: نام فارسی نقش‌ها ---------------------------------------------------------------------------------
prd_roles.ensure_role_templates(company_id)
manager_role = roles_service.create_role(company_id, "MANAGER", None)
labels = {r.code: r.label for r in roles_service.list_roles(company_id)}
check(labels["PRD_MANAGER"] == "مدیر تولید" and labels["PRD_COST_ACCOUNTANT"] == "حسابدار بهای تمام‌شده"
      and labels["MANAGER"] == "مدیر", f"ready-made roles show Persian names ({labels})")
from peecha.ui.screens.roles import RolesScreen

rs = RolesScreen()
rs.refresh()
shown = [rs.role_list.item(i).text() for i in range(rs.role_list.count())]
check("مدیر تولید" in shown and not any(t.startswith("PRD_") for t in shown), f"roles screen lists Persian names ({shown})")
from peecha.services.workflow import routing
from peecha.db.base import new_session

with new_session() as s:
    names = routing.role_names(s, [manager_role.role_id])
check(names[manager_role.role_id] == "مدیر", "workflow approver descriptions use the Persian name")

# --- ۲: فرم درخواست خرید در پنجرهٔ کوچک ------------------------------------------------------------------------
from peecha.ui.screens.purchase_requests import PurchaseRequestScreen
from peecha.ui.screens.rfqs import RfqScreen

pr_scr = PurchaseRequestScreen()
# R327: بدنهٔ فرم درخواست خودش اسکرول می‌شود تا دکمه‌های پایین فرم همیشه دیده شوند
check(pr_scr.body_scroll is not None and RfqScreen.scroll_in_mdi,
      "request/RFQ forms scroll inside a small window instead of squeezing the fields")
check(pr_scr.lines_table.minimumHeight() >= 130 and pr_scr.list_table.minimumHeight() >= 110, "tables keep a usable height")

# --- ۳: آیکن جدا برای ساخت هر سند --------------------------------------------------------------------------------
from peecha.ui.screens.commercial_documents_list import CommercialDocumentsListScreen

lst = CommercialDocumentsListScreen(None, type_filter_codes=("PURCHASE_ORDER", "PURCHASE_PROFORMA", "PURCHASE_INVOICE",
                                                             "PURCHASE_RETURN"))
lst.show()
app.processEvents()
app.processEvents()
new = {b.toolTip(): b.text() for b in lst.findChildren(QPushButton) if b.toolTip().startswith("درخواست خرید")
       or "جدید" in b.toolTip()}
glyphs = list(new.values())
check(len(glyphs) >= 5 and len(set(glyphs)) == len(glyphs) and "➕" not in glyphs, f"each new-document button has its own icon ({new})")

# --- ۴: مرحلهٔ بی‌گیرنده ------------------------------------------------------------------------------------------
spec = builder.WizardSpec("تایید درخواست", "pr_self", "PURCHASE_REQUEST", "",
                          {"type": "EVENT", "events": ["PURCHASE_REQUEST_SUBMITTED"]}, None,
                          [builder.ApprovalLevel("تایید درخواست", [{"kind": "USER", "user_id": uid}])], ["entity.approve"],
                          reject_actions=["entity.reject"])
did = defs.create_definition(company_id, uid, code="pr_self", name="تایید درخواست", entity_type="PURCHASE_REQUEST")
defs.save_draft(company_id, uid, did, builder.build_graph(spec))
defs.publish(company_id, uid, did)

req = prs.create_request(company_id, uid, prs.RequestFields(request_date=today, warehouse_id=wh_rm))
prs.add_line(req, company_id, r1, kg, D(5), None, supplier, D(1000))
prs.submit_request(req, company_id)
stuck = [w for w in inbox.my_work(company_id, uid) if w.source == "STUCK"]
check(len(stuck) == 1 and "خود درخواست‌کننده" in stuck[0].status_note and stuck[0].action.startswith("این مرحله گیرنده ندارد"),
      f"the stuck step appears in the manager's cartable with the reason ({[(w.title, w.status_note) for w in stuck]})")
busy = model_events.busy(company_id, "PURCHASE_REQUEST", req)
check(busy and "گیرنده ندارد" in busy and "ارجاع" in busy, f"the lock message says what to do ({busy})")

scr = PurchaseRequestScreen()
scr.refresh()
scr.edit_document(req)
bar = scr.workflow_bar
check(not bar.warning.isHidden() and "گیرنده ندارد" in bar.warning.text() and not bar.reassign_button.isHidden(),
      "the request form shows the problem and a reassign button")
check(not bar.reassign(uid) and any("تفکیک وظایف" in w and "قواعد" in w for w in WARN),
      "self-reassignment explains how to allow it")
save_settings(company_id, uid, allow_self_approval=True)
from peecha.ui.screens import my_tasks

mt = my_tasks.MyTasksScreen(None)
mt.refresh()
check(mt.select_key(stuck[0].key) and mt.buttons["delegate"].isEnabled(), "stuck card selectable; reassign available")
check(mt.reassign_stuck(uid), "reassigned from the cartable")
mine = [t for t in tasks.list_my_tasks(company_id, uid) if t.entity_id == req]
check(len(mine) == 1 and not tasks.list_unassigned(company_id, entity_type="PURCHASE_REQUEST", entity_id=req),
      "the step now waits for the chosen person")
tasks.decide(company_id, mine[0].task_id, uid, "APPROVE", "تایید")
check(prs.get_request(req, company_id)[0].status_code == "APPROVED", "approved through the workflow")

# مدیر مستقیم تعریف نشده ← به مدیر دیگری ارجاع می‌شود
save_settings(company_id, uid, allow_self_approval=False)
boss = users_service.create_user("boss1", "مدیر خرید", "secret123", None, lang_id, False, [company_id], company_id).user_id
spec2 = builder.WizardSpec("مدیر مستقیم", "pr_mgr", "PURCHASE_REQUEST", "",
                           {"type": "EVENT", "events": ["PURCHASE_REQUEST_SUBMITTED"]}, None,
                           [builder.ApprovalLevel("تایید مدیر مستقیم", [{"kind": "DIRECT_MANAGER"}])], ["entity.approve"])
defs.set_status(company_id, uid, did, "PAUSED")
d2 = defs.create_definition(company_id, uid, code="pr_mgr", name="مدیر مستقیم", entity_type="PURCHASE_REQUEST")
defs.save_draft(company_id, uid, d2, builder.build_graph(spec2))
defs.publish(company_id, uid, d2)
req2 = prs.create_request(company_id, uid, prs.RequestFields(request_date=today, warehouse_id=wh_rm))
prs.add_line(req2, company_id, r1, kg, D(2), None, supplier, D(1000))
prs.submit_request(req2, company_id)
w2 = next(w for w in inbox.my_work(company_id, uid) if w.source == "STUCK")
check("مدیر مستقیم" in w2.status_note, f"reason names the missing direct manager ({w2.status_note})")
roles_service.set_user_role(boss, manager_role.role_id, company_id, True)
mt.reload()
check(mt.select_key(w2.key) and mt.reassign_stuck(boss), "reassigned to another manager")
check(any(t.entity_id == req2 for t in tasks.list_my_tasks(company_id, boss)), "the other manager now has it in the cartable")

finish()
