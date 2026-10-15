"""R314: صفحه‌های افتتاحیه (offscreen) — منو، ریبون و چرخ‌دندهٔ تنظیمات، تنظیم حساب واسط، تعریف فرایند و مسئولان، قالب و
بارگذاری فایل با پیش‌نمایش خطا، ورود/ویرایش/حذف دستی، ارسال/تأیید/رد با نقش‌های جدا، ثبت قطعی، تطبیق، قفل، کارتابل،
گزارش‌ها، هشدار تاریخ برش، دکمه‌های آیکونی و پاک‌سازی داده."""
import os, sys, tempfile
os.environ["PEECHA_DB_NAME"] = "peecha_test_r314_ui"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from opn_fixture import *  # noqa: F401,F403
import opn_fixture as fx
from PySide6.QtWidgets import QApplication, QDialog, QPushButton
from sqlalchemy import text as sql

check, raises = fx.check, fx.raises
app = QApplication.instance() or QApplication([])
from peecha import nav_catalog
from peecha import session as sess
from peecha.services import data_reset, operational_tasks
from peecha.services import purchase_reports as pr
from peecha.services import roles as roles_svc
from peecha.services.opening import finalize as ofin
from peecha.services.opening import reports as orep
from peecha.services.workflow import inbox
from peecha.ui import shell_window
from peecha.ui.screens import my_tasks
from peecha.ui.screens import opening as ui
from peecha.ui.screens.fixed_assets import set_combo

tmp = tempfile.mkdtemp(prefix="r314u_")

# ===== ۱) منو، ریبون، دسترسی و چرخ‌دنده =====
flat = {i["code"]: i for i in nav_catalog.flatten_nav_items()}
check({"OPN_CENTER", "OPN_DATA", "OPN_RECONCILE", "OPN_RPT_OPN_RECONCILE", "OPN_RPT_OPN_ROWS"} <= set(flat)
      and flat["OPN_SETTINGS"].get("hidden_from_sidebar") and shell_window._SETTINGS_TAB_BY_GROUP_CODE["OPN"] == 17,
      "opening module in the menu, settings behind the gear (tab 17)")
ribbon = nav_catalog.DEFAULT_QUICK_ACCESS_BY_MODULE.get("OPN", [])
check(len(ribbon) == 4 and all(code in flat for code, _ in ribbon), "opening ribbon shortcuts")
forms = {code for code, _m, _l in nav_catalog.build_form_catalog()}
check({"opn_setup", "opn_enter", "opn_approve", "opn_post", "opn_correct", "opn_settings", "opn_difference", "opn_center", "opn_data",
       "opn_reconcile", "opn_config"} <= forms, "RBAC forms for every opening step and screen")
check("OPN" in roles_svc.MODULE_LABELS and "OPN" in shell_window._NAV_ICONS, "module registered with its icon")

entry, approver = user("u_entry", "OPN_ENTRY"), user("u_appr", "OPN_APPROVER")
manager, viewer = user("u_mgr", "OPN_MANAGER"), user("u_view", "OPN_VIEWER")
admin_user = sess.current_user


def act_as(user_id):
    sess.current_user = admin_user if user_id == uid else type("U", (), {"user_id": user_id, "is_super_admin": False})()


class MainWindow:
    def __init__(self, screens=None):
        self.calls, self.screens = [], screens or {}

    def open_screen(self, code, then=None):
        self.calls.append(code)
        scr = self.screens.get(code)
        if then is not None and scr is not None:
            then(scr)


warnings = []

# ===== ۲) تنظیمات =====
act_as(viewer)
st = ui.OpeningSettingsScreen()
st.warn = warnings.append
st.refresh()
check(not st.save_btn.isEnabled() and not st.clearing.isEnabled(), "viewer cannot change opening settings")
act_as(uid)
st.refresh()
set_combo(st.clearing, clearing_gl.account_id)
set_combo(st.policy, "BLOCK")
check(st.save() and oc.clearing_account_id(company_id) == clearing_gl.account_id, "clearing account saved from the settings screen")
st.self_approval.setChecked(True)
check(oc.is_on(company_id, oc.OPN_SELF_APPROVAL), "self-approval toggle from the screen")
st.self_approval.setChecked(False)
check(len(st.make_roles()) == 5, "ready-made opening roles")

# ===== ۳) مرکز افتتاحیه: تعریف فرایند و مسئولان =====
act_as(entry)
center = ui.OpeningCenterScreen()
center.warn = warnings.append
center.confirm = lambda text: True
center.refresh()
check(not center.buttons["new"].isEnabled(), "data-entry role cannot create a run")
act_as(manager)
center.refresh()


def new_run(dlg):
    dlg.widgets["code"].setText("UI1")
    dlg.widgets["title"].setText("افتتاحیهٔ آزمایشی")
    set_combo(dlg.widgets["fy"], fy_id)
    dlg.widgets["balance"].setDate(balance_date)
    dlg.widgets["go_live"].setDate(go_live)
    for code in ("INVENTORY", "PAYABLES"):
        dlg.widgets[f"m_{code}"].setChecked(False)
    return True


center.dialog_runner = new_run
run = center.new_run()
check(run and center.run.run_id == run and [m.module_code for m in center.run.modules] == ["RECEIVABLES", "GL"]
      and center.t_mods.rowCount() == 2, "run created from the screen with the chosen modules (posting order)")
for row in range(center.t_mods.rowCount()):
    center.t_mods.selectRow(row)

    def people(dlg):
        set_combo(dlg.widgets["owner"], entry)
        set_combo(dlg.widgets["approver"], approver)
        return True
    center.dialog_runner = people
    center.set_people()
check(all(m.owner_user_id == entry and m.approver_user_id == approver for m in center.run.modules), "owners and approvers set")

# ===== ۴) ورود و بارگذاری =====
act_as(entry)
mw = MainWindow()
data = ui.OpeningDataScreen(mw)
data.warn = warnings.append
data.confirm = lambda text: True
data.save_file_picker = lambda name: os.path.join(tmp, "tpl.xlsx" if name.endswith(".xlsx") else "tpl.csv")
center._main_window = MainWindow({"OPN_DATA": data})
center.t_mods.selectRow(0)
center.open_data()
check(data.run_box.currentData() == run and data.module_box.currentData() == "RECEIVABLES" and data.t.columnCount() == 2 + 15 + 3,
      "data screen opened from the hub on the selected module, one column per template field")
check(os.path.exists(data.template(".xlsx")) and os.path.exists(data.template(".csv")), "templates downloaded (xlsx and csv)")
bd = oc.fmt_date
ar_file = write_csv(os.path.join(tmp, "ar.csv"), ["کد تفصیلی مشتری", "شمارهٔ سند در سیستم قبلی", "تاریخ سند", "مبلغ اصلی"], [
    ("C1", "F-1", bd(balance_date), "300000"), ("C9", "F-2", bd(balance_date), "100")])
data.open_file_picker = lambda: ar_file
res = data.upload()
check(res and res.valid == 1 and res.invalid == 1 and data.t.rowCount() == 2 and "۱ دارای خطا" in data.status_label.text(),
      "upload with preview: one valid, one with error, summary shown")
bad_row = next(i for i, r in enumerate(data.rows) if r.status == "INVALID")
check(data.t.item(bad_row, 0).foreground().color().name() == "#ef4444" and "پیدا نشد" in data.t.item(bad_row, data.t.columnCount() - 2).text(),
      "error row highlighted with the column message")
data.t.selectRow(bad_row)
data.dialog_runner = lambda dlg: (dlg.widgets["counterparty_code"].setText("C2"), True)[1]
check(data.edit_row() and all(r.status == "VALID" for r in data.rows), "row fixed from the edit form")


def add_form(dlg):
    dlg.widgets["counterparty_code"].setText("C1")
    dlg.widgets["legacy_no"].setText("F-3")
    dlg.widgets["doc_date"].setText(bd(balance_date))
    dlg.widgets["original_amount"].setText("۵۰٬۰۰۰")
    set_combo(dlg.widgets["disputed"], "بله")
    return True


data.dialog_runner = add_form
check(data.add_row() and len(data.rows) == 3, "manual row added with Persian digits")
added = next(i for i, r in enumerate(data.rows) if r.payload.get("legacy_no") == "F-3")
check("اختلاف" in (data.rows[added].warning_text or ""), "disputed flag carried as a warning")
data.t.selectRow(added)
check(data.delete_row() and len(data.rows) == 2, "row deleted")
check(data.revalidate().valid == 2, "revalidate from the screen")
out = data.export()
check(out and os.path.exists(out), "rows exported with error column")
set_combo(data.module_box, "GL")
gl_file = write_csv(os.path.join(tmp, "gl.csv"), ["کد حساب معین", "بدهکار", "بستانکار", "کد تفصیلی شخص"], [
    ("131", "300000", "", "C1"), ("131", "100", "", "C2"), ("311", "", "300100", "")])
data.open_file_picker = lambda: gl_file
check(data.upload().valid == 3, "trial balance uploaded")

# ===== ۵) گردش ماژول با نقش‌های جدا =====
act_as(entry)
center.refresh()
center.open_run(run)
for row in range(2):
    center.t_mods.selectRow(row)
    center.dialog_runner = lambda dlg: True
    center.submit()
check(all(m.status_code == "READY" for m in center.run.modules), "entry user submits both modules")
check(not center.buttons["approve"].isEnabled() and not center.buttons["post"].isEnabled(), "entry user cannot approve or post")
act_as(approver)
tasks = [t for t in operational_tasks.list_operational_tasks(company_id, approver) if t.kind.startswith("OPN_")]
check(sum(1 for t in tasks if t.kind == "OPN_APPROVE") == 2, "approver sees both modules in the cartable")
items = [i for i in inbox.my_work(company_id, approver) if i.title.startswith("افتتاحیهٔ")]
check(len(items) == 2 and all("تأیید" in i.action for i in items), f"unified cartable shows the opening steps with the action hint ({len(items)})")
center.refresh()
center.open_run(run)
center.t_mods.selectRow(0)
center.dialog_runner = lambda dlg: (dlg.widgets["comment"].setPlainText("مبلغ C2 را بررسی کنید"), True)[1]
check(center.reject() and center.run.modules[0].status_code == "ENTERING" and "C2" in center.run.modules[0].reject_reason,
      "approver rejects with a reason")
act_as(entry)
center.refresh()
center.open_run(run)
center.t_mods.selectRow(0)
center.dialog_runner = lambda dlg: True
center.submit()
act_as(approver)
center.refresh()
center.open_run(run)
for row in range(2):
    center.t_mods.selectRow(row)
    center.dialog_runner = lambda dlg: True
    center.approve()
check(all(m.status_code == "APPROVED" for m in center.run.modules), "approver approves both")

# ===== ۶) ثبت قطعی، تطبیق و قفل =====
act_as(manager)
mw_tasks = operational_tasks._opening_tasks(company_id, manager)
check({t.kind for t in mw_tasks} == {"OPN_POST"}, "manager's cartable: post")
center.refresh()
center.open_run(run)
center.t_mods.selectRow(1)   # GL
check(not center.post() and any("آخر از همه" in w for w in warnings), "GL refused before subledgers, message shown")
warnings.clear()
center.t_mods.selectRow(0)
check(center.post() and center.run.modules[0].status_code == "POSTED", "receivables posted from the hub")
center.t_mods.selectRow(1)
check(center.post() and center.run.status_code == "POSTED" and center.t_docs.rowCount() == 2, "GL posted; documents tab lists both steps")
rec = ui.OpeningReconcileScreen()
rec.select(run)
check(rec.t.rowCount() == 2 and rec.cards["clearing"].text() == "۰" and "کامل" in rec.problems.text(),
      "reconciliation screen: two counterparties, clearing zero")
check({t.kind for t in operational_tasks._opening_tasks(company_id, manager)} == {"OPN_LOCK"}, "cartable: lock is next")
mt = MainWindow({"OPN_CENTER": center})
check(my_tasks.open_operational_task(mt, "OPN_LOCK", "OPENING_RUN", run) and mt.calls == ["OPN_CENTER"] and center.run.run_id == run,
      "cartable opens the hub on the run")
check(center.buttons["lock"].isEnabled() and center.lock() and center.run.status_code == "LOCKED", "locked from the hub")
check(not center.buttons["correction"].isEnabled(), "manager has no correction permission (controller only)")

# ===== ۷) گزارش‌ها =====
f = pr.PurchaseFilters(go_live, go_live)
f.options = {}
for code, fn in (("runs", orep.runs_report), ("modules", orep.modules_report), ("reconcile", orep.reconcile_report),
                 ("rows", orep.rows_report), ("docs", orep.documents_report), ("imports", orep.imports_report),
                 ("items", orep.open_items_report)):
    result = fn(company_id, f)
    if not result.rows:
        check(False, f"report {code} has rows")
check(True, "all opening reports return rows")
f.date_from, f.date_to = fy_start, fy_end
check(len(orep.events_report(company_id, pr.PurchaseFilters(datetime.date(2000, 1, 1), datetime.date(2100, 1, 1))).rows) > 5,
      "event history report")
check(ofin.cutover_message(company_id, balance_date) is not None, "cutover warning active after posting")
from peecha.ui.screens.commercial_settlement import InvoiceSettlementScreen  # noqa: E402

act_as(uid)
settle = InvoiceSettlementScreen(None, "SALES_INVOICE")
settle.refresh()
labels = [settle.invoice_table.item(r, 0).text() for r in range(settle.invoice_table.rowCount())]
check(len(labels) == 2 and all(lbl.startswith("افتتاحیه") for lbl in labels),
      f"existing settlement screen lists the opening open items with their own label ({labels})")
ar = pr.PurchaseFilters(datetime.date(2000, 1, 1), datetime.date(2100, 1, 1), side="SALES")
aging = pr.ap_aging(company_id, ar)
check(sum(r[-2] for r in aging.rows) == 300100 and sum(r[1] for r in aging.rows) == 2,
      "receivables aging counts the opening open items")
fc = pr.payment_forecast(company_id, ar)
opening_refs = [ref for row, ref in zip(fc.rows, fc.refs) if "سند باز افتتاحیه" in row]
check(len(opening_refs) == 2 and all(ref and ref[1] == "JOURNAL_ENTRY" and ref[0] for ref in opening_refs),
      "collection forecast lists the opening open items and drills to their journal entry")

# ===== ۸) دکمه‌های آیکونی =====


def _parents(w):
    out = []
    while w is not None:
        w = w.parentWidget()
        out.append(w)
    return out


own = lambda b: not any(isinstance(w, QDialog) for w in _parents(b))  # noqa: E731
texts = [b.text() for scr in (center, data, rec, st) for b in scr.findChildren(QPushButton) if own(b) and len(b.text()) > 3]
check(not texts, f"icon buttons only (no text buttons) {texts[:5]}")
check(not warnings, f"no unexpected warnings ({warnings})")

# ===== ۹) پاک‌سازی داده =====


def opn_rows():
    with new_session() as s:
        return s.execute(sql("SELECT (SELECT count(*) FROM opn.runs WHERE company_id = :c), (SELECT count(*) FROM opn.staged_rows), "
                             "(SELECT count(*) FROM opn.settings WHERE company_id = :c)"), {"c": company_id}).one()


check(all(opn_rows()), f"fixture has opening data {opn_rows()}")
data_reset.wipe_documents(company_id)
check(opn_rows()[:2] == (0, 0), f"document wipe removes opening runs (posted rows included) {opn_rows()}")
data_reset.wipe_settings(company_id)
with new_session() as s:
    trig = s.execute(sql("SELECT tgenabled FROM pg_trigger WHERE tgname = 'tr_opn_rows_guard'")).scalar()
check(opn_rows()[2] == 0 and trig == "O", "settings wipe removes opening settings; row guard enabled again")
check("opn.runs" in data_reset.covered_tables() and "opn.settings" in data_reset.covered_tables(), "reset tool covers opening tables")

fx.finish()
sys.stdout.flush()
os._exit(0)
