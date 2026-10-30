"""R300: کارتابل یکپارچه و گرافیکی — یک جا برای همهٔ کارها، یک مسیر تایید برای هر سند.

کارتابل قبلی + گردش کار + مشتری تازه + پیگیری + درخواست‌های من در «کارتابل من»؛ کارت‌ها جملهٔ کار، رنگ و مرحله دارند؛
با انتشار فرایند، کارتابل قبلی همان سند خاموش می‌شود و موارد در جریانش بدون گیر کردن در قفل تازه تمام می‌شوند.
"""
import os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r300"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crm_fixture import *  # noqa: F401,F403
import crm_fixture as fx
import re
from fastapi.testclient import TestClient
from sqlalchemy import select
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton
from peecha.db.models.accounting import JournalEntry
from peecha.db.models.commercial import CustomerProfile
from peecha.db.models.security import Form, Notification
from peecha.services import cartable, journal_entries as je_service, operational_tasks, roles as roles_service
from peecha.services.crm import activities as acts
from peecha.services.workflow import definitions as defs, inbox, registry, runtime, tasks, templates
check, raises = fx.check, fx.raises

app = QApplication.instance() or QApplication([])
WARN = []
QMessageBox.warning = staticmethod(lambda *a, **k: WARN.append(a[2] if len(a) > 2 else ""))
QMessageBox.information = staticmethod(lambda *a, **k: None)
registry.ensure_loaded()
roles_service.ensure_catalog()


def user(login, name, role_code=None, perms=()):
    u = users_service.create_user(login, name, "secret123", None, lang_id, False, [company_id], company_id).user_id
    role_id = None
    if role_code:
        role = roles_service.create_role(company_id, role_code, None)
        role_id = role.role_id
        roles_service.set_user_role(u, role.role_id, company_id, True)
        with new_session() as s:
            for form, action in perms:
                fid = s.scalar(select(Form.form_id).where(Form.code == form))
                roles_service.set_role_permission(role.role_id, fid, action, True)
    return u, role_id


fin, fin_role = user("fin1", "کارشناس مالی", "FIN", [("journal_entry", "APPROVE"), ("detail_dimensions", "EDIT")])
staff, _ = user("staff1", "کارمند ساده")


def je(desc, by=uid):
    a = cash_gl.account_id if hasattr(cash_gl, "account_id") else cash_gl
    b = discount_gl.account_id if hasattr(discount_gl, "account_id") else discount_gl
    return je_service.create_journal_entry(company_id, by, today, desc, [
        je_service.LineInput(a, "ب", D(10), D(0)), je_service.LineInput(b, "ب", D(0), D(10))]).journal_entry_id


def permanent(je_id):
    with new_session() as s:
        return s.get(JournalEntry, je_id).permanent_no is not None


def keys(items):
    return {w.key for w in items}


# ===== ۱) کارتابل قبلی هم در کارتابل یکپارچه است، با جملهٔ کار و مرحله =====
cartable.save_workflow_steps(company_id, "journal_entry", True, [fin_role])
je1 = je("سند پیش از فرایند تازه")
item1 = cartable.submit_for_approval(company_id, "journal_entry", je1, "CREATE", uid, amount=D(10))
w1 = next((w for w in inbox.my_work(company_id, fin) if w.key == f"CARTABLE:{item1}"), None)
check(w1 is not None and w1.action == "تایید یا رد کنید" and w1.tone == "approve" and (w1.step_no, w1.step_total) == (1, 1)
      and w1.path == [("مرحلهٔ ۱", "current")] and w1.extra["request_type"], "legacy cartable item with action, step and path")
check(w1.created_at is not None and w1.subtitle == "مدیر سیستم", "submitter and submit time kept (old cartable columns)")

# ===== ۲) انتشار فرایند تازه ← کارتابل قبلی همان سند خاموش می‌شود =====
check(templates.active_legacy_for(company_id, "JOURNAL_ENTRY") == ["سند حسابداری"] or
      len(templates.active_legacy_for(company_id, "JOURNAL_ENTRY")) == 1, "legacy rule detected before publish")
jd = templates.install(company_id, uid, "JOURNAL_APPROVAL")
defs.publish(company_id, uid, jd)
active, steps = cartable.get_workflow_steps(company_id, "journal_entry")
check(not active and [s.approver_role_id for s in steps] == [fin_role], "legacy rule switched off on publish (steps kept)")
check(templates.active_legacy_for(company_id, "JOURNAL_ENTRY") == [], "no active legacy rule left")
check(templates.governing_process(company_id, "journal_entry") == "تایید سند حسابداری", "governing process found for the form")

# مورد در جریان کارتابل قبلی تا پایان همان‌جا تایید می‌شود و قفل فرایند تازه متوقفش نمی‌کند
check(raises(lambda: je_service.approve_journal_entry(je1, company_id, uid), "تایید"), "new lock blocks direct approval")
check(inbox.quick_decide(company_id, fin, f"CARTABLE:{item1}", "APPROVE") == "تایید شد." and permanent(je1),
      "in-flight legacy item finishes despite the new lock")

# ===== ۳) سند تازه فقط از مسیر تازه؛ کارت مرحله دارد؛ درخواست‌های من =====
je2 = je("سند تازه")
w2 = next((w for w in inbox.my_work(company_id, fin) if w.source == "WF" and w.extra.get("entity_id") == je2), None)
check(w2 is not None and w2.tone == "approve" and w2.step_no and w2.step_total and w2.step_no <= w2.step_total
      and any(s == "current" for _l, s in w2.path), "workflow item with progress dots")
check(not any(w.source == "CARTABLE" for w in inbox.my_work(company_id, fin)), "no second (legacy) path for the new document")
mine = inbox.my_requests(company_id, uid)
m2 = next((m for m in mine if m.extra["entity_id"] == je2), None)
check(m2 is not None and m2.tone == "mine" and "کارشناس مالی" in m2.subtitle and m2.action == "منتظر کارشناس مالی",
      "my request shows who it is waiting on")
d_m2 = inbox.detail(company_id, uid, m2.key)
check(d_m2["path"] and dict(d_m2["context"])["منتظر"] == "کارشناس مالی", "my request detail with path and waiting-on")
with new_session() as s:
    before = len(list(s.scalars(select(Notification).where(Notification.user_id == fin))))
check(inbox.remind(company_id, uid, m2.key, "لطفاً بررسی کنید") >= 1, "remind the approver")
with new_session() as s:
    check(len(list(s.scalars(select(Notification).where(Notification.user_id == fin)))) > before, "reminder notification sent")
check(raises(lambda: inbox.remind(company_id, staff, m2.key), "کار بازی"), "others cannot remind someone else's request")

# ===== ۴) مشتری تازهٔ منتظر تایید (صندوق تایید قبلی موبایل) =====
c3 = partners_service.create_customer(company_id, "C-3", "فروشگاه پ", fast_track=False, submitted_by_user_id=visitor.user_id)
ckey = f"CUSTOMER:{c3}"
cw = next((w for w in inbox.my_work(company_id, fin) if w.key == ckey), None)
check(cw is not None and cw.tone == "customer" and cw.can_quick_decide and cw.subtitle == "ویزیتور یک", "pending customer in cartable")
check(ckey not in keys(inbox.my_work(company_id, staff)), "only users allowed to edit customers see it")
check(dict(inbox.detail(company_id, fin, ckey)["context"]).get("مشتری") == "فروشگاه پ", "customer detail")
check(raises(lambda: inbox.quick_decide(company_id, fin, ckey, "REJECT", ""), "علت"), "reject customer needs a reason")
inbox.quick_decide(company_id, fin, ckey, "APPROVE")
with new_session() as s:
    check(s.get(CustomerProfile, c3).status_code == "ACTIVE", "customer approved from the cartable")
check(raises(lambda: inbox.quick_decide(company_id, staff, f"CUSTOMER:{cust_a}", "APPROVE"), "دسترسی"), "no permission no approve")

# ===== ۵) پیگیری مشتری و مراحل اسناد هم جملهٔ کار دارند =====
acts.create_activity(company_id, uid, acts.ActivityFields("CALL", "تماس برای سفارش تازه", customer_detail_account_id=cust_a,
                                                          assigned_to_user_id=fin, due_date=today))
fw = next((w for w in inbox.my_work(company_id, fin) if w.source == "CRM"), None)
check(fw is not None and fw.tone == "followup" and fw.action.startswith("پیگیری کنید"), "follow-up with action text")
check(set(operational_tasks.KIND_LABELS) <= set(inbox.DOC_ACTIONS), "every document step has an action sentence")

# ===== ۶) صفحهٔ «کارتابل من»: کارت‌های گرافیکی و همهٔ کارها از یک جا =====
from peecha import numerals, session as sess, nav_catalog
from peecha.db.models.security import User
from peecha.db.models.core import Company
from peecha.ui import shell_window
from peecha.ui.screens import my_tasks
from peecha.ui.widgets import SummaryCard

LATIN = re.compile(r"[A-Za-z]")


def login(u):
    with new_session() as s:
        sess.current_user = s.get(User, u)
        sess.current_company = s.get(Company, company_id)
        s.expunge_all()


login(fin)
c4 = partners_service.create_customer(company_id, "C-4", "فروشگاه ت", fast_track=False, submitted_by_user_id=visitor.user_id)
scr = my_tasks.MyTasksScreen(None)
scr.dialog_runner = lambda dlg: True
scr.refresh()
plain = [b.text() for b in scr.findChildren(QPushButton) if len(b.text()) > 2]
check(not plain, f"no text buttons ({plain})")
check(all(b.toolTip() and not LATIN.search(b.toolTip()) for b in scr.findChildren(QPushButton)), "Persian tooltips")
check(len(scr.findChildren(SummaryCard)) == 6 and scr.cards["approvals"].text() == numerals.to_persian_digits("2"),
      f"six summary cards ({scr.cards['approvals'].text()})")
check({f"CUSTOMER:{c4}", w2.key} <= set(scr.cards_by_key) and any(k.startswith("CRM:") for k in scr.cards_by_key),
      "workflow, customer and follow-up cards together")
card = scr.cards_by_key[w2.key]
check(card.action_label.text() == "تایید یا رد کنید" and not card.check.isHidden(), "card says what to do and can be bulk-selected")
check(scr.cards_by_key[fw.key].check.isHidden(), "follow-up card has no bulk checkbox")
check(scr.current is not None and scr.current["key"] in scr.cards_by_key, "first card selected with details")
scr.set_view("APPROVAL")
check(all(w.kind == "APPROVAL" for w in scr.shown) and fw.key not in scr.cards_by_key, "approvals view")
scr.set_view("ALL")
check(scr.select_key(w2.key) and "✔ ثبت و ارسال" in scr.d_path.text() and scr.d_context.rowCount() >= 1, "detail with path")
check(scr.buttons["approve"].isEnabled() and scr.buttons["delegate"].isEnabled() and not scr.buttons["withdraw"].isEnabled(),
      "buttons follow the selected card")
WARN.clear()
check(scr.decide("APPROVE", "") and permanent(je2), "approve from the cartable runs the process action")
check(w2.key not in scr.cards_by_key, "approved card leaves the list")
WARN.clear()
scr.select_key(f"CUSTOMER:{c4}")
check(not scr.decide("REJECT", "") and any("علت" in w for w in WARN), "reject without reason warns")
je3, je4 = je("سند سوم"), je("سند چهارم")
scr.reload()
k3 = next(k for k, c in scr.cards_by_key.items() if c.item.extra.get("entity_id") == je3)
k4 = next(k for k, c in scr.cards_by_key.items() if c.item.extra.get("entity_id") == je4)
scr.cards_by_key[k3].check.setChecked(True)
scr.cards_by_key[k4].check.setChecked(True)
res = scr.bulk_approve()
check(len(res) == 2 and all(ok for _k, ok, _m in res) and permanent(je3) and permanent(je4), "bulk approve checked cards")

# درخواست‌های من: یادآوری و پس‌گرفتن از همان صفحه
login(uid)
je5 = je("سند پنجم")
mine_scr = my_tasks.MyTasksScreen(None)
mine_scr.dialog_runner = lambda dlg: True
mine_scr.refresh()
m5 = next(m for m in inbox.my_requests(company_id, uid) if m.extra["entity_id"] == je5)
check(mine_scr.cards["mine"].text() != "۰" and mine_scr.select_key(m5.key) and mine_scr.view.currentData() == "MINE",
      "selecting my request switches to «درخواست‌های من»")
card5 = mine_scr.cards_by_key[m5.key]
check(card5.action_label.text().startswith("منتظر") and mine_scr.buttons["remind"].isEnabled()
      and mine_scr.buttons["withdraw"].isEnabled() and not mine_scr.buttons["approve"].isEnabled(), "my request card and buttons")
check(mine_scr.remind("") >= 1, "remind from the screen")
check(mine_scr.withdraw("دیگر لازم نیست") and runtime.get_instance(company_id, m5.ref_id).status_code == "CANCELLED",
      "withdraw my request from the screen")

# ===== ۷) یک منو: «کارهای من» و «مرکز تایید» در «کارتابل من» یکی شدند =====
flat = {i["code"]: i for i in nav_catalog.flatten_nav_items()}
check(flat["WF_MY_WORK"].get("hidden_from_sidebar") and flat["WF_APPROVALS"].get("hidden_from_sidebar")
      and not flat["MY_TASKS"].get("hidden_from_sidebar"), "only «کارتابل من» in the sidebar")
check(shell_window._NAV_ALIASES == {"WF_MY_WORK": "MY_TASKS", "WF_APPROVALS": "MY_TASKS"}, "old menu codes open the cartable")
ribbon = [c for c, _ in nav_catalog.DEFAULT_QUICK_ACCESS_BY_MODULE["WF"]]
check(ribbon[0] == "MY_TASKS" and "WF_MY_WORK" not in ribbon and "WF_APPROVALS" not in ribbon, "workflow ribbon points to the cartable")
from peecha.ui.screens import workflow_center as wfc
check(not hasattr(wfc, "MyWorkScreen") and not hasattr(wfc, "ApprovalCenterScreen"), "duplicate screens removed")

# ===== ۸) کارتابل قبلی را نمی‌شود کنار فرایند فعال دوباره روشن کرد =====
from peecha.ui.screens.workflow_designer import WorkflowDesignerScreen
login(uid)
wd = WorkflowDesignerScreen()
wd.refresh()
wd.form_combo.setCurrentIndex(wd.form_combo.findData("journal_entry"))
check("تایید سند حسابداری" in wd.status_label.text(), "old settings page says which process handles the form")
wd.active_checkbox.setChecked(True)
WARN.clear()
wd._save()
check(any("دو مسیر" in w or "متوقف" in w for w in WARN) and not cartable.get_workflow_steps(company_id, "journal_entry")[0],
      "cannot re-enable the old cartable while the process runs")
defs.set_status(company_id, uid, jd, "PAUSED")
check(templates.governing_process(company_id, "journal_entry") is None, "paused process no longer governs")
cartable.save_workflow_steps(company_id, "journal_entry", True, [fin_role])
defs.set_status(company_id, uid, jd, "ACTIVE")
check(not cartable.get_workflow_steps(company_id, "journal_entry")[0], "reactivating the process switches the old cartable off again")

# ===== ۹) موبایل: همان کارتابل با جملهٔ کار، رنگ، مرحله و درخواست‌های من =====
from peecha_api.main import app as api
client = TestClient(api)
H = lambda u: {"Authorization": "Bearer " + client.post("/auth/login", json={"username": u, "password": "secret123"}).json()["access_token"]}
c5 = partners_service.create_customer(company_id, "C-5", "فروشگاه ث", fast_track=False, submitted_by_user_id=visitor.user_id)
je6 = je("سند ششم")
r = client.get("/workflow/inbox", headers=H("fin1")).json()
cust = next(i for i in r["items"] if i["key"] == f"CUSTOMER:{c5}")
wf = next(i for i in r["items"] if i["source"] == "WF")
check(cust["quick"] and cust["tone"] == "customer" and cust["customer_id"] == c5 and cust["action"], "mobile customer card data")
check(wf["action"] == "تایید یا رد کنید" and wf["path"] and wf["step_total"] and r["approvals"] >= 2, "mobile workflow card data")
r_admin = client.get("/workflow/inbox", headers=H("admin")).json()
check(any(q["tone"] == "mine" and q["action"].startswith("منتظر") for q in r_admin["requests"]), "mobile «درخواست‌های من»")

fx.finish()
