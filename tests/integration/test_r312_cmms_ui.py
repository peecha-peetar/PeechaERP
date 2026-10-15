"""R312: صفحه‌های نگهداری (offscreen) — منو و ریبون، صف درخواست، پروندهٔ دستور کار از ثبت تا بستن، قطعه، نگهداری پیشگیرانه،
تجهیزات و کارت، توقف و ظرفیت، تنظیمات، گزارش‌ها و داشبورد؛ همه با دکمهٔ آیکونی و بدون پیام خطا."""
import os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r312_ui"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mnt_fixture import *  # noqa: F401,F403
import mnt_fixture as fx
from PySide6.QtWidgets import QApplication

check, raises = fx.check, fx.raises
app = QApplication.instance() or QApplication([])
from peecha import nav_catalog
from peecha.ui import shell_window
from peecha.ui.screens import maintenance as ui
from peecha.ui.screens.fixed_assets import set_combo

m1, m2 = machine("M-01"), machine("M-02")
flat = {i["code"]: i for i in nav_catalog.flatten_nav_items()}
check({"MNT_DASHBOARD", "MNT_REQUEST_QUEUE", "MNT_BOARD", "MNT_PM", "MNT_EQUIPMENT", "MNT_AVAILABILITY", "INV_RPT_MNT_RELIABILITY",
       "MNT_RPT_MNT_COST"} <= set(flat) and flat["MNT_SETTINGS"].get("hidden_from_sidebar")
      and shell_window._SETTINGS_TAB_BY_GROUP_CODE["MNT"] == 15, "maintenance module in the menu, settings behind the gear")
ribbon = nav_catalog.DEFAULT_QUICK_ACCESS_BY_MODULE.get("MNT", [])
check(len(ribbon) == 6 and all(code in flat for code, _ in ribbon), "maintenance ribbon shortcuts")
forms = {code for code, _m, _l in nav_catalog.build_form_catalog()}
check({"mnt_request", "mnt_plan", "mnt_execute", "mnt_verify", "mnt_parts", "mnt_cost", "mnt_approve", "mnt_manage",
       "mnt_requests", "mnt_work_orders"} <= forms, "RBAC forms for every maintenance step")

warnings = []

# ===== صف درخواست =====
rq = ui.RequestQueueScreen()
rq.warn = warnings.append
rq.refresh()


def new_req(dlg):
    set_combo(dlg.widgets["asset_id"], m1)
    dlg.widgets["title"].setText("نشت روغن هیدرولیک")
    dlg.widgets["stopped"].setChecked(True)
    set_combo(dlg.widgets["severity"], "HIGH")
    return True


rq.dialog_runner = new_req
rid = rq.new_request()
check(rid and rq.t.rowCount() == 1 and rq.cards["stopped"].text() == "۱" and asset_status(m1) == "UNDER_MAINTENANCE",
      "request from the queue: machine stopped, card counts it")
rq.t.selectRow(0)
rq.dialog_runner = lambda dlg: (set_combo(dlg.widgets["priority"], "URGENT"), True)[1]
check(rq.evaluate(), "evaluate from the queue")
rq.t.selectRow(0)
rq.dialog_runner = lambda dlg: (dlg.widgets["shutdown"].setChecked(True), True)[1]
wid = rq.convert()
check(wid and wos.get(company_id, wid).request_id == rid, "convert to work order from the queue")

# ===== تابلو و پروندهٔ دستور کار =====
board = ui.WorkOrderBoardScreen()
board.warn = warnings.append
board.refresh()
in_board = [board.lists[t].count() for t, _c in ui._BOARD_COLUMNS]
check(board.t.rowCount() == 1 and sum(in_board) == 1, f"board shows the job in its column ({in_board})")
board.dialog_runner = lambda dlg: True
dlg = board.open_order(wid)
dlg.warn = warnings.append
dlg.confirm = lambda text: True
dlg.dialog_runner = lambda d: (set_combo(d.widgets["item"], spare), set_combo(d.widgets["wh"], wh_rm), d.widgets["qty"].setText("2"),
                               True)[3]
check(dlg.add_part() and dlg.t_parts.rowCount() == 1, "add a part from the work-order file")
dlg.dialog_runner = lambda d: True
check(dlg.start() and wos.get(company_id, wid).status_code == "IN_PROGRESS", "start from the file")
dlg.t_parts.setCurrentCell(0, 0)
dlg.dialog_runner = lambda d: (d.widgets["qty"].setText("1"), True)[1]
before = on_hand(spare, wh_rm)
check(dlg.issue() and on_hand(spare, wh_rm) == before - 1, "issue a part from the file (stock document posted)")
dlg.dialog_runner = lambda d: (d.widgets["hours"].setText("2"), True)[1]
check(dlg.add_labor() and dlg.t_labor.rowCount() == 1, "labour hours from the file")
dlg.dialog_runner = lambda d: (d.widgets["note"].setPlainText("کاسه‌نمد تعویض شد"), True)[1]
check(dlg.complete() and dlg.d.status_code == "COMPLETED" and dlg.cards["machine"].text().startswith("متوقف"),
      "completed by technician; the file still shows the machine as stopped")
check(not dlg.buttons["close"].isEnabled() and dlg.buttons["verify"].isEnabled(), "close disabled until the test")
dlg.dialog_runner = lambda d: True
check(dlg.verify() and dlg.d.status_code == "VERIFIED", "verify (pass) from the file")
check(dlg.release() and asset_status(m1) == "IN_SERVICE", "ready-for-use from the file puts the machine back in service")
check(dlg.close_wo() and dlg.d.status_code == "CLOSED" and dlg.buttons["reopen"].isEnabled(), "close from the file")
check(dlg.t_hist.rowCount() >= 7, "history tab lists the steps")
board.reload()
check(board.t.rowCount() == 0, "closed job leaves the open board")
board.dialog_runner = lambda d: (set_combo(d.widgets["asset"], m2), d.widgets["title"].setText("بازدید"), True)[2]
check(board.new_order(), "new work order from the board")

# ===== نگهداری پیشگیرانه =====
pms = ui.PmScreen()
pms.warn = warnings.append
pms.refresh()


def plan_form(d):
    d.code.setText("PM-UI")
    d.title.setText("سرویس هفتگی")
    set_combo(d.asset, m2)
    d.interval.setText("7")
    d.add_task_row()
    d.t_tasks.item(0, 0).setText("بازدید تسمه")
    d.add_part_row()
    set_combo(d.t_parts.cellWidget(0, 0), belt)
    set_combo(d.t_parts.cellWidget(0, 1), wh_rm)
    d.t_parts.cellWidget(0, 2).setText("1")
    return True


pms.dialog_runner = plan_form
pid = pms.new_plan()
plan = mpm.get_plan(company_id, pid) if pid else None
check(plan and plan.data.tasks[0].description == "بازدید تسمه" and plan.data.parts[0][0] == belt and pms.t_plans.rowCount() == 1,
      "plan created from the plan form with checklist and parts")
ids = pms.generate()
check(len(ids) == 1 and pms.generate() == [], "generate from the screen, second run creates nothing")
check(pms.t_cal.rowCount() >= 1, "PM calendar tab lists dues")

# ===== تجهیزات =====
es = ui.EquipmentScreen()
es.warn = warnings.append
es.refresh()
es.find_box.setText(fa.qr_payload(fa.get_asset(company_id, m1)))
check(es.find() == m1 and es.card_data.code == "M-01" and es.card_data.serial_no == "SN-M-01" and "SN-M-" in es.ident.text(),
      "scan/QR text opens the equipment card")
es.dialog_runner = lambda d: (set_combo(d.widgets["crit"], "HIGH"), d.widgets["specs"].setPlainText("توان: ۱۵"), True)[2]
check(es.edit_profile() and es.card_data.criticality_label == "حیاتی" and ("توان", "۱۵") in es.card_data.technical_specs,
      "maintenance profile edited from the card")
check(es.t_wo.rowCount() >= 1 and es.tree.topLevelItemCount() >= 1, "card shows repair history; hierarchy tree is filled")

# ===== توقف و ظرفیت =====
avs = ui.AvailabilityScreen()
avs.warn = warnings.append
avs.refresh()
avs.dialog_runner = lambda d: (set_combo(d.widgets["asset"], m2), d.widgets["reason"].setText("سرویس"), True)[2]
win = avs.new_window()
avs.t_win.selectRow(0)
avs.dialog_runner = lambda d: True
check(win and avs.decide_window(True) and avs.windows[0].status_code == "APPROVED", "planned stoppage proposed and approved")

# ===== تنظیمات، داشبورد، گزارش =====
st = ui.MntSettingsScreen()
st.warn = warnings.append
st.refresh()
check(set(st.toggles) == set(sc.MNT_ALL) and not any(b.isChecked() for b in st.toggles.values()), "four toggles, all off by default")
st.toggles[sc.MNT_CAPACITY_PLANNED].setChecked(True)
check(sc.is_on(company_id, sc.MNT_CAPACITY_PLANNED), "toggle switched from the settings screen")
st.refresh()
check(len(st.toggles) == 4, "refresh does not duplicate the toggles")
check(st.make_roles() and len(st.make_roles()) == 6, "ready-made roles from the settings screen")
dash = ui.MntDashboardScreen()
dash.refresh()
check(dash.cards["MTTR"]._value_label.text() if hasattr(dash.cards["MTTR"], "_value_label") else True,
      "dashboard loads")
from peecha.services import purchase_reports as pr
from peecha.services import warehouse_reports as wr
f = pr.PurchaseFilters(today - days(30), today)
for code in ("MNT_WORK_ORDERS", "MNT_REQUESTS", "MNT_DOWNTIME", "MNT_PM_COMPLIANCE", "MNT_RELIABILITY", "MNT_COST", "MNT_PARTS",
             "MNT_FAILURES"):
    res = wr.WAREHOUSE_REPORTS_BY_CODE[code].func(company_id, f)
    check(res.columns, f"report {code} runs ({len(res.rows)} rows)")
check(len(wr.WAREHOUSE_REPORTS_BY_CODE["MNT_PARTS"].func(company_id, f).rows) == 1, "parts report shows the issued part")
from peecha.ui.screens.purchase_reports import PurchaseReportScreen
rs = PurchaseReportScreen("MNT_RELIABILITY", None, side="INVENTORY")
rs.refresh()
check("equipment" in rs._filters_used and rs.equipment_combo.count() >= 3, "report screen offers the equipment filter")
from peecha.ui.screens.system_settings import SystemSettingsScreen
ss = SystemSettingsScreen()
labels = [ss.tabs.tabText(i) for i in range(ss.tabs.count())]
check(labels[15] == "نگهداری و تعمیرات", f"maintenance tab at the gear index ({labels})")


def _parents(w):
    out = []
    while w is not None:
        w = w.parentWidget()
        out.append(w)
    return out


own = lambda b: not any(isinstance(w, ui.QDialog) for w in _parents(b))  # noqa: E731
screens = [rq, board, pms, es, avs, st]
texts = [b.text() for scr in screens for b in scr.findChildren(ui.QPushButton) if own(b) and len(b.text()) > 3]
check(not texts, f"icon buttons only (no text buttons) {texts[:5]}")
dlg_texts = [b.text() for b in dlg.findChildren(ui.QPushButton) if len(b.text()) > 3 and b.text() not in ("OK", "Cancel")]
check(not dlg_texts, f"work-order file uses icon buttons {dlg_texts[:5]}")
check(not warnings, f"no warnings shown ({warnings})")

fx.finish()
