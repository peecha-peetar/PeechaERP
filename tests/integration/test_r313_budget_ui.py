"""R313: صفحه‌های بودجه (offscreen) — منو، ریبون و چرخ‌دندهٔ تنظیمات، پروندهٔ نسخه با تفکیک نقش (تهیه، بررسی، تأیید، انتشار)،
اصلاحیه و دورهٔ بسته، داشبورد کنترل با ریز مصرف تا سند، هزینهٔ واقعی از دفتر کل، مجوز تجاوز، بستن تعهد سفارش، تنظیمات،
کارتابل، هشدار فرم سند و پاک‌سازی داده؛ همه با دکمهٔ آیکونی."""
import os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r313_ui"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bud_fixture import *  # noqa: F401,F403
import bud_fixture as fx
from PySide6.QtWidgets import QApplication, QDialog
from sqlalchemy import text as sql

check, raises = fx.check, fx.raises
app = QApplication.instance() or QApplication([])
from peecha import nav_catalog
from peecha import session as sess
from peecha.ui import shell_window
from peecha.ui.screens import budgeting as ui
from peecha.ui.screens import my_tasks
from peecha.ui.screens.fixed_assets import set_combo
from peecha.services import data_reset, operational_tasks
from peecha.services import journal_entries as je
from peecha.services import roles as roles_service
from peecha.services import users as users_service
from peecha.services.budgeting import roles_setup
from peecha.services.workflow import inbox

# ===== ۱) منو، ریبون، دسترسی و چرخ‌دنده =====
flat = {i["code"]: i for i in nav_catalog.flatten_nav_items()}
check({"BUD_CENTER", "BUD_BUDGETS", "BUD_EXCEPTIONS", "BUD_COMMITMENTS", "BUD_RPT_BUD_VS_ACTUAL", "BUD_RPT_BUD_DETAIL"} <= set(flat)
      and flat["BUD_SETTINGS"].get("hidden_from_sidebar") and shell_window._SETTINGS_TAB_BY_GROUP_CODE["BUD"] == 16,
      "budget module in the menu, settings behind the gear")
ribbon = nav_catalog.DEFAULT_QUICK_ACCESS_BY_MODULE.get("BUD", [])
check(len(ribbon) == 6 and all(code in flat for code, _ in ribbon), "budget ribbon shortcuts")
forms = {code for code, _m, _l in nav_catalog.build_form_catalog()}
check({"bud_prepare", "bud_review", "bud_approve", "bud_publish", "bud_period", "bud_settings", "bud_exception", "bud_override",
       "bud_commitment", "bud_center", "bud_budgets", "bud_exceptions", "bud_commitments", "bud_config"} <= forms,
      "RBAC forms for every budget step and screen")

roles_service.ensure_catalog()
roles = roles_setup.ensure_role_templates(company_id)


def user(name, role):
    u = users_service.create_user(name, name, "secret123", None, None, False, [company_id], company_id).user_id
    roles_service.set_user_role(u, roles[role], company_id, True)
    return u


prep, officer, appr, buyer = user("prep", "BUD_PREPARER"), user("officer", "BUD_OFFICER"), user("appr", "BUD_APPROVER"), \
    user("buyer", "BUD_BUYER")
admin_user = sess.current_user


def act_as(user_id):
    sess.current_user = admin_user if user_id == uid else type("U", (), {"user_id": user_id, "is_super_admin": False})()


class MainWindow:
    """جای پنجرهٔ اصلی: کد منو را ثبت می‌کند و تابع then را روی صفحهٔ واقعی اجرا می‌کند."""

    def __init__(self, screens=None):
        self.calls, self.screens = [], screens or {}

    def open_screen(self, code, then=None):
        self.calls.append(code)
        scr = self.screens.get(code)
        if then is not None and scr is not None:
            then(scr)


warnings = []

# ===== ۲) بودجه و نسخه: تهیه‌کننده =====
act_as(prep)
bs = ui.BudgetsScreen()
bs.warn = warnings.append
bs.confirm = lambda text: True
bs.refresh()
check(bs.buttons["new_budget"].isEnabled() and not bs.buttons["submit"].isEnabled(), "preparer can create; nothing to submit yet")


def new_budget(dlg):
    set_combo(dlg.widgets["fy"], fy_id)
    dlg.widgets["code"].setText("OPEX")
    dlg.widgets["name"].setText("بودجهٔ عملیاتی")
    set_combo(dlg.widgets["period"], "MONTH")
    set_combo(dlg.widgets["owner"], officer)
    return True


bs.dialog_runner = new_budget
bid = bs.new_budget()
check(bid and bs.budget.budget_id == bid and bs.t_periods.rowCount() == 12 and bs.version_box.count() == 1
      and bs.cards["status"].text() == "پیش‌نویس", "new monthly budget from the screen: 12 periods, original draft")
vid = bs.version.version_id


def line_dialog(cc=None, pj=None, amount="", weights="", basis="PURCHASE", account=None):
    def run(dlg):
        if "basis" in dlg.widgets:
            set_combo(dlg.widgets["basis"], basis)
            set_combo(dlg.widgets["account"], account)
            set_combo(dlg.widgets["cc"], cc)
            set_combo(dlg.widgets["pj"], pj)
        dlg.widgets["amount"].setText(amount)
        dlg.widgets["weights"].setText(weights)
        set_combo(dlg.widgets["resp"], officer)
        return True
    return run


bs.dialog_runner = line_dialog(cc=cc_a, amount="۱٬۲۰۰٬۰۰۰")
l_cc = bs.add_line()
bs.dialog_runner = line_dialog(pj=pj_1, amount="1200000", weights="۲،۰،۰،۰،۰،۰،۰،۰،۰،۰،۰،۱")
l_pj = bs.add_line()
bs.dialog_runner = line_dialog(cc=cc_b, amount="400000", basis="ACCOUNT", account=office_gl.account_id)
l_gl = bs.add_line()
v = bs.version
check(l_cc and l_pj and l_gl and bs.t_lines.rowCount() == 3 and bs.t_lines.columnCount() == 9 + 12,
      "three lines (purchase by cost centre, purchase by project, GL monitoring) with a column per month")
by_id = {ln.line_id: ln for ln in v.lines}
check(set(by_id[l_cc].periods.values()) == {D(100_000)} and by_id[l_pj].periods[1] == D(800_000) and by_id[l_pj].periods[12] == D(400_000)
      and by_id[l_pj].periods[2] == 0, "equal spread and weights typed with Persian digits and comma")
bs.t_lines.selectRow(0)
bs.dialog_runner = lambda dlg: (dlg.widgets["p1"].setText("1"), True)[1]
check(not bs.distribute() and warnings and "برابر" in warnings[-1], "manual distribution that does not add up is refused with a message")
warnings.clear()
bs.t_lines.selectRow(0)
bs.dialog_runner = lambda dlg: (dlg.widgets["amount"].setText("1000000"), True)[1]
check(bs.edit_line() and bs.version.lines[0].proposed_amount == D(1_000_000), "edit the proposed amount")
bs.dialog_runner = lambda dlg: (dlg.widgets["note"].setPlainText("پیشنهاد سال"), True)[1]
check(bs.submit() and bs.version.status_code == "SUBMITTED", "submit for review")
check(not bs.buttons["add_line"].isEnabled() and not bs.buttons["review"].isEnabled() and not bs.buttons["approve"].isEnabled(),
      "after submission the preparer cannot edit, review or approve")

# ===== ۳) بررسی، تأیید و انتشار با نقش‌های جدا =====
act_as(officer)
bs.refresh()
bs.open_version(vid)
check(bs.buttons["review"].isEnabled() and bs.buttons["approved"].isEnabled() and not bs.buttons["approve"].isEnabled()
      and not bs.buttons["new_budget"].isEnabled(), "budget officer: review and adjust only")
bs.t_lines.selectRow(0)
bs.dialog_runner = lambda dlg: (dlg.widgets["amount"].setText("900000"), dlg.widgets["note"].setPlainText("سقف کل"), True)[2]
check(bs.set_approved() and bs.version.lines[0].approved_amount == D(900_000), "officer sets the approved amount")
bs.dialog_runner = lambda dlg: True
check(bs.review() and bs.version.status_code == "REVIEWED", "officer reviews")
act_as(appr)
bs.refresh()
bs.open_version(vid)
check(bs.buttons["approve"].isEnabled() and bs.buttons["reject"].isEnabled() and not bs.buttons["publish"].isEnabled(),
      "approver: approve or reject, not publish")
check(bs.approve() and bs.version.status_code == "APPROVED", "approver approves")
act_as(officer)
bs.refresh()
bs.open_version(vid)
check(bs.publish() and bs.version.status_code == "PUBLISHED" and bs.cards["status"].text() == "مصوب و منتشرشده", "officer publishes")
steps = [bs.t_hist.item(r, 1).text() for r in range(bs.t_hist.rowCount())]
check(["ارسال برای بررسی", "اصلاح مبلغ مصوب", "بررسی و تأیید مسئول بودجه", "تأیید مدیر مجاز", "انتشار نسخهٔ مصوب"]
      == [s for s in steps if s != "ایجاد"], f"decision history in the version file ({steps})")

# دورهٔ بسته و اصلاحیه
bs.tabs.setCurrentWidget(bs.t_periods)
bs.t_periods.selectRow(0)
bs.dialog_runner = lambda dlg: (dlg.widgets["note"].setPlainText("بستن فروردین"), True)[1]
check(bs.period(True) and bs.t_periods.item(0, 3).text() == "بسته", "officer closes the first month")
act_as(prep)
bs.refresh()
check(bs.buttons["amend"].isEnabled() and bs.buttons["supplement"].isEnabled(), "preparer can start an amendment after publication")
bs.dialog_runner = lambda dlg: (dlg.widgets["title"].setText("اصلاحیهٔ میان‌سال"), True)[1]
amend = bs.revision("AMENDMENT")
check(amend and bs.version.version_id == amend and bs.version.status_code == "DRAFT" and bs.version_box.count() == 2
      and not bs.buttons["amend"].isEnabled(), "amendment draft opens in the file; one open version at a time")
check(bs.cards["change"].text() == "۰", "amendment starts with no change against the published version")

# ===== ۴) داشبورد کنترل: تعهد سفارش و هزینهٔ واقعی دفتر کل =====
act_as(uid)
o1 = po([(mat, 10, 50_000)], cc=cc_a)
cc_type = fx.cc_type
je.create_journal_entry(company_id, uid, today, "خرید ملزومات اداری", [
    je.LineInput(account_id=office_gl.account_id, description="ملزومات", debit=D(150_000), credit=D(0), details={cc_type: cc_b}),
    je.LineInput(account_id=cash_gl.account_id, description="صندوق", debit=D(0), credit=D(150_000), details={}),
])
center = ui.BudgetCenterScreen()
center.warn = warnings.append
center.confirm = lambda text: True
center.refresh()
rows = {s.key.key_id: i for i, s in enumerate(center.rows)}
check(len(center.rows) == 3, f"dashboard lists the published lines ({len(center.rows)})")
r_cc = rows[key_of(l_cc)]
s_cc = center.rows[r_cc]
check(s_cc.commit == D(500_000) and s_cc.actual == 0 and center.t.item(r_cc, 10).text() in ("در محدوده", "نزدیک به سقف"),
      "order commitment counted on the cost-centre line")
s_gl = center.rows[rows[key_of(l_gl)]]
check(s_gl.actual == D(150_000) and s_gl.commit == 0, "GL monitoring line takes its actual from the journal (debit − credit)")
center.t.selectRow(r_cc)
check(center.t_detail.rowCount() == 1 and center._detail_refs[0] == (o1, "PURCHASE_ORDER"),
      "consumption detail of the selected line traces to the order")
mw = MainWindow()
center._main_window = mw
center._open_detail(0, 0)
center.open_detail_report()
check(mw.calls == ["PURCH_ORDER", "BUD_RPT_BUD_DETAIL"], f"double-click opens the order; full detail report opens ({mw.calls})")
center.t.selectRow(rows[key_of(l_gl)])
check(center.t_detail.rowCount() == 1 and center._detail_refs[0][1] == "JOURNAL_ENTRY", "GL actual drills to the journal entry")
check(center.resync() == 0, "resync from the dashboard finds no difference")

# ===== ۵) تنظیمات، مجوز تجاوز و کارتابل =====
st = ui.BudSettingsScreen()
st.warn = warnings.append
st.refresh()
set_combo(st.policy, "APPROVAL")
check(st.save() and fx.bc.settings(company_id).policy_code == "APPROVAL", "policy saved from the settings screen")
st.toggles[fx.sc.BUD_ENFORCE].setChecked(True)
check(fx.sc.is_on(company_id, fx.sc.BUD_ENFORCE), "enforcement toggle from the settings screen")
o2 = make_doc("PURCHASE_ORDER", [(mat, 20, 50_000)], cc=cc_a)
check(raises(lambda: confirm(o2), "مجوز"), "order over the remaining budget waits for approval")
check(status(o2) == "DRAFT", "the order stays draft")
tasks = operational_tasks.list_operational_tasks(company_id, appr)
check(any(t.kind == "BUD_EXCEPTION" for t in tasks) and not any(t.kind == "BUD_EXCEPTION"
                                                               for t in operational_tasks.list_operational_tasks(company_id, prep)),
      "pending approval reaches the approver's cartable only")
check(all(k in inbox.DOC_ACTIONS for k in ("BUD_REVIEW", "BUD_APPROVE", "BUD_PUBLISH", "BUD_REVISE", "BUD_EXCEPTION")),
      "cartable sentence for every budget task")
act_as(appr)
ex = ui.ExceptionsScreen()
ex.warn = warnings.append
ex.confirm = lambda text: True
ex.refresh()
check(ex.t.rowCount() == 1 and not ex.buttons["approve"].isEnabled(), "pending request listed; nothing selected yet")
task = next(t for t in tasks if t.kind == "BUD_EXCEPTION")
mw = MainWindow({"BUD_EXCEPTIONS": ex})
check(my_tasks.open_operational_task(mw, task.kind, task.document_type_code, task.document_id) and mw.calls == ["BUD_EXCEPTIONS"]
      and ex.buttons["approve"].isEnabled(), "cartable task opens the request selected and decidable")
ex.dialog_runner = lambda dlg: (dlg.widgets["note"].setPlainText("خرید ضروری"), True)[1]
check(ex.decide(True), "approver approves the overrun")
act_as(uid)
confirm(o2)
check(status(o2) == "CONFIRMED", "re-confirm passes with the approval")
ex.open_exception(task.document_id)
check(ex.rows[0].status_code == "USED" and ex.t.currentRow() == 0, "approval is used once and shown in the full list")
check(fx.bctl.document_messages(company_id, "PURCHASE_ORDER", o2), "control message kept for the document form warning")

# کارتابل نسخه: بررسی برای مسئول بودجه، با بازشدن پرونده
act_as(prep)
bs.refresh()
bs.open_version(amend)
bs.dialog_runner = lambda dlg: True
check(bs.submit(), "amendment submitted")
mine = [t for t in operational_tasks.list_operational_tasks(company_id, officer) if t.kind == "BUD_REVIEW"]
check(len(mine) == 1 and mine[0].document_id == amend and not [t for t in operational_tasks.list_operational_tasks(company_id, prep)
                                                                if t.kind == "BUD_REVIEW"], "review task for the officer, not the preparer")
act_as(officer)
bs2 = ui.BudgetsScreen()
bs2.warn = warnings.append
bs2.refresh()
mw = MainWindow({"BUD_BUDGETS": bs2})
check(my_tasks.open_operational_task(mw, "BUD_REVIEW", "BUDGET_VERSION", amend) and bs2.version.version_id == amend
      and bs2.buttons["review"].isEnabled(), "cartable opens the amendment file ready for review")
bs2.dialog_runner = lambda dlg: (dlg.widgets["note"].setPlainText("مستندات ناقص"), True)[1]
check(bs2.reject() and bs2.version.status_code == "REJECTED", "officer rejects with a reason")
check([t.kind for t in operational_tasks.list_operational_tasks(company_id, prep) if t.kind == "BUD_REVISE"] == ["BUD_REVISE"],
      "rejected version comes back to the preparer's cartable")

# ===== ۶) بستن تعهد سفارش =====
act_as(buyer)
cm = ui.CommitmentsScreen()
cm.warn = warnings.append
cm.confirm = lambda text: True
cm.refresh()
ids = [r.document_id for r in cm.rows]
check(set(ids) == {o1, o2} and cm.buttons["close"].isEnabled(), "open commitments listed for the buyer")
cm.t.selectRow(ids.index(o2))
check(cm.t_lines.rowCount() == 1 and fx.bex.open_order_lines(company_id, o2)[0].open_qty == 20, "order lines with open quantity")
cm.dialog_runner = lambda dlg: (dlg.widgets["reason"].setPlainText("تامین‌کننده تحویل نمی‌دهد"), True)[1]
check(cm.close_commitment(), "close the remaining commitment")
check(totals(l_cc)["COMMIT"] == D(500_000), "closing releases the order's commitment")
cm.t.selectRow([r.document_id for r in cm.rows].index(o2))
cm.dialog_runner = lambda dlg: (dlg.widgets["note"].setPlainText("تحویل دوباره ممکن شد"), True)[1]
check(not cm.reopen() and warnings and "مجوز" in warnings[-1], "reopening is checked against the budget again (needs approval)")
warnings.clear()
act_as(uid)
set_combo(st.policy, "WARN")
st.save()
act_as(buyer)
cm.t.selectRow([r.document_id for r in cm.rows].index(o2))
check(cm.reopen() and totals(l_cc)["COMMIT"] == D(1_500_000), "after switching to warn-only the commitment reopens")

# ===== ۷) گزارش و فرم سند =====
act_as(uid)
from peecha.ui.screens.purchase_reports import PurchaseReportScreen
rs = PurchaseReportScreen("BUD_VS_ACTUAL", None, side="INVENTORY")
rs.refresh()
check({"budget", "bud_version"} <= set(rs._filters_used) and rs.budget_combo.count() >= 2, "report screen offers the budget filters")
from peecha.ui.screens.system_settings import SystemSettingsScreen
ss = SystemSettingsScreen()
labels = [ss.tabs.tabText(i) for i in range(ss.tabs.count())]
check(labels[16] == "بودجه‌ریزی", f"budget tab at the gear index ({labels})")


def _parents(w):
    out = []
    while w is not None:
        w = w.parentWidget()
        out.append(w)
    return out


own = lambda b: not any(isinstance(w, QDialog) for w in _parents(b))  # noqa: E731
screens = [bs, bs2, center, ex, cm, st]
texts = [b.text() for scr in screens for b in scr.findChildren(ui.QPushButton) if own(b) and len(b.text()) > 3]
check(not texts, f"icon buttons only (no text buttons) {texts[:5]}")
check(not warnings, f"no warnings shown ({warnings})")

# ===== ۸) پاک‌سازی داده =====
fx.toggle(fx.sc.BUD_ENFORCE, False)


def bud_rows():
    with fx.new_session() as s:
        return {t: s.execute(sql(f"SELECT count(*) FROM bud.{t} WHERE company_id = :c"), {"c": company_id}).scalar()
                for t in ("budgets", "consumption_entries", "exceptions", "control_events", "commitment_closures", "settings")}


before = bud_rows()
check(all(before[t] for t in ("budgets", "consumption_entries", "exceptions", "control_events", "commitment_closures", "settings")),
      f"fixture has budget data everywhere ({before})")
data_reset.wipe_documents(company_id)
after_docs = bud_rows()
check(after_docs["budgets"] == 1 and not any(after_docs[t] for t in ("consumption_entries", "exceptions", "control_events",
                                                                       "commitment_closures")),
      f"document wipe clears the budget ledger, keeps the budget ({after_docs})")
data_reset.wipe_master_data(company_id)
data_reset.wipe_settings(company_id)
left = bud_rows()
with fx.new_session() as s:
    orphans = s.execute(sql("SELECT (SELECT count(*) FROM bud.budget_versions) + (SELECT count(*) FROM bud.budget_lines) + "
                            "(SELECT count(*) FROM bud.control_keys) + (SELECT count(*) FROM bud.budget_periods)")).scalar()
    triggers = s.execute(sql("SELECT count(*) FROM pg_trigger WHERE tgname LIKE 'tr_bud_%' AND tgenabled = 'O'")).scalar()
check(not any(left.values()) and orphans == 0, f"master and settings wipes leave no budget rows ({left}, {orphans})")
check(triggers == 4, f"budget guard triggers are enabled again after the wipe ({triggers})")

fx.finish()
sys.stdout.flush()
os._exit(0)
