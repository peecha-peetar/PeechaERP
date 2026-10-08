import os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r293"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crm_fixture import *  # noqa: F401,F403
import crm_fixture as fx
from sqlalchemy import select, text
from peecha.db.models.security import Notification
from peecha.db.models.workflow import WfTask, WfTaskDecision
from peecha.services import cartable, hr as hr_service, roles as roles_service, users as users_service
from peecha.services.crm import activities as acts
from peecha.services.workflow import (calendar, definitions as defs, inbox, notify, registry, runtime, scheduler, sla,
                                      tasks)
from peecha import numerals
from peecha.services.workflow.common import save_settings
from peecha.services.workflow.registry import EntityAdapter, FieldSpec
check, raises = fx.check, fx.raises
TZ = datetime.datetime.now().astimezone().tzinfo


def at(y, m, d, hh=0, mm=0):
    return datetime.datetime(y, m, d, hh, mm, tzinfo=TZ)


def mk_user(code, name):
    return users_service.create_user(code, name, "secret123", None, lang_id, False, [company_id], company_id).user_id


a1, a2, boss = mk_user("app1", "تاییدکنندهٔ یک"), mk_user("app2", "تاییدکنندهٔ دو"), mk_user("boss", "مدیر بخش")
requester = visitor.user_id

# ===== ۱) تقویم کاری: جمعه تعطیل، پنجشنبه نیمه‌وقت، تعطیلی رسمی =====
thu = at(2026, 10, 8, 11, 0)  # پنجشنبه
check(thu.weekday() == 3, "fixture date is a Thursday")
check(calendar.add_business_hours(company_id, thu, 4) == at(2026, 10, 10, 11, 0),
      f"Thu 11:00 + 4 work hours → Sat 11:00 ({calendar.add_business_hours(company_id, thu, 4)})")
check(calendar.add_business_hours(company_id, at(2026, 10, 7, 7, 0), 1) == at(2026, 10, 7, 9, 0), "before office hours starts at 08:00")
hid = calendar.add_holiday(company_id, uid, datetime.date(2026, 10, 10), "تعطیل رسمی")
check(raises(lambda: calendar.add_holiday(company_id, uid, datetime.date(2026, 10, 10), "تکراری"), "قبلاً"), "duplicate holiday")
check(calendar.add_business_hours(company_id, thu, 4) == at(2026, 10, 11, 11, 0), "holiday skipped")
check(abs(calendar.business_hours_between(company_id, thu, at(2026, 10, 11, 11, 0)) - 4) < 0.01, "business hours between")
check(not calendar.is_working_time(company_id, at(2026, 10, 9, 10, 0)) and calendar.is_working_time(company_id, at(2026, 10, 7, 10, 0)),
      "Friday is off")
check(raises(lambda: calendar.save_work_hours(company_id, uid, {5: ("16:00", "08:00")}), "بعد از شروع"), "invalid work hours")
calendar.save_work_hours(company_id, uid, {5: ("08:00", "16:00"), 6: ("08:00", "16:00"), 0: ("08:00", "16:00"),
                                           1: ("08:00", "16:00"), 2: ("08:00", "16:00"), 3: ("08:00", "13:00")})
check(calendar.work_hours(company_id)[3][1] == datetime.time(13, 0), "work hours saved")
calendar.delete_holiday(company_id, uid, hid)
check(not calendar.list_holidays(company_id), "holiday deleted")

# ===== ۲) سیاست تعهد زمانی =====
check(raises(lambda: sla.save_policy(company_id, uid, None, code="x", name="x", due_hours=4, warn_before_hours=5), "یادآوری"),
      "warn must be inside due")
pol = sla.save_policy(company_id, uid, None, code="fast", name="تایید فوری", due_hours=8, warn_before_hours=2,
                      escalate_after_hours=4, repeat_every_hours=4, max_escalations=2, business_hours=False)
check(raises(lambda: sla.save_policy(company_id, uid, None, code="FAST", name="y", due_hours=1), "قبلاً"), "duplicate policy code")
check(sla.list_policies(company_id)[0].escalate_to_text == "مدیر مستقیم گیرنده", "default escalation target text")

# ===== ۳) کار با تعهد زمانی: یادآوری ← گذشتن از مهلت ← ارجاع به مدیر مستقیم =====
DOCS = {1: {"amount": 5, "requested_by": requester}}
registry.register_adapter(EntityAdapter("REQ3", "درخواست", "SALES", lambda cid, eid: dict(DOCS[eid]),
                                        fields=(FieldSpec("amount", "مبلغ", "money"),), submitter_field="requested_by",
                                        title=lambda c: "درخواست خرید لپ‌تاپ"))
unit = hr_service.create_org_unit(company_id, "U1", "مالی", None, None)
pos = hr_service.create_position(company_id, "P1", "کارشناس", unit, None, 5)
e_a1 = hr_service.create_employee(company_id, "E1", "تایید", "یک", None, today, unit, pos, D(1000), None, mobile="09120000011")
e_boss = hr_service.create_employee(company_id, "E2", "مدیر", "بخش", None, today, unit, pos, D(1000), None, mobile="09120000099")
hr_service.set_employee_user(company_id, e_a1, a1)
hr_service.set_employee_user(company_id, e_boss, boss)
hr_service.set_org_unit_manager(company_id, unit, e_boss)
graph = {"trigger": {"type": "MANUAL"},
         "nodes": [{"id": "ap", "type": "APPROVAL", "label": "تایید مالی", "approvers": [{"kind": "USER", "user_id": a1}],
                    "sla_policy_id": pol},
                   {"id": "ok", "type": "END", "label": "تایید", "outcome": "APPROVED"},
                   {"id": "no", "type": "END", "label": "رد", "outcome": "REJECTED"}],
         "edges": [{"from": "start", "to": "ap"}, {"from": "ap", "to": "ok", "when": "approved"},
                   {"from": "ap", "to": "no", "when": "rejected"}]}
d = defs.create_definition(company_id, uid, code="sla", name="تایید با مهلت", entity_type="REQ3", graph=graph)
defs.publish(company_id, uid, d)
i1 = runtime.start_instance(company_id, d, "REQ3", 1, started_by=requester)
t1 = tasks.list_tasks(company_id, instance_id=i1)[0]
with new_session() as s:
    row = s.get(WfTask, t1.task_id)
    created, due, warn, esc = row.created_at, row.due_at, row.warn_at, row.escalate_at
check(row.sla_status == "ON_TRACK" and abs((due - created).total_seconds() - 8 * 3600) < 120 and
      abs((due - warn).total_seconds() - 2 * 3600) < 5 and abs((esc - due).total_seconds() - 4 * 3600) < 5,
      "SLA dates computed from policy")
scheduler.fire_due_timers(company_id, warn + datetime.timedelta(minutes=1))
with new_session() as s:
    check(s.get(WfTask, t1.task_id).sla_status == "AT_RISK" and
          s.scalar(select(Notification).where(Notification.user_id == a1, Notification.type_code == "WF_TASK_DUE")) is not None,
          "reminder before due")
scheduler.fire_due_timers(company_id, due + datetime.timedelta(minutes=1))
with new_session() as s:
    r = s.get(WfTask, t1.task_id)
    check(r.sla_status == "BREACHED" and r.priority_code == "HIGH", "breached at due time")
scheduler.fire_due_timers(company_id, esc + datetime.timedelta(minutes=1))
mine_boss = {t.task_id: t for t in tasks.list_my_tasks(company_id, boss)}
with new_session() as s:
    r = s.get(WfTask, t1.task_id)
    esc_dec = s.scalar(select(WfTaskDecision).where(WfTaskDecision.task_id == t1.task_id, WfTaskDecision.decision == "ESCALATE"))
    boss_note = s.scalar(select(Notification).where(Notification.user_id == boss, Notification.type_code == "WF_ESCALATION"))
check(t1.task_id in mine_boss and r.escalation_level == 1 and r.priority_code == "HIGH" and esc_dec is not None
      and boss_note is not None and mine_boss[t1.task_id].sla_label == "گذشته از مهلت", "escalated to direct manager")
scheduler.fire_due_timers(company_id, esc + datetime.timedelta(hours=5))
with new_session() as s:
    check(s.get(WfTask, t1.task_id).escalation_level == 2 and s.get(WfTask, t1.task_id).priority_code == "CRITICAL",
          "repeat escalation level 2")
scheduler.fire_due_timers(company_id, esc + datetime.timedelta(hours=20))
with new_session() as s:
    check(s.get(WfTask, t1.task_id).escalation_level == 2, "stops at max escalations")
check(any(h[2] == "ارجاع به سطح بالاتر" for h in tasks.task_detail(company_id, t1.task_id, boss).history), "escalation in history")
tasks.decide(company_id, t1.task_id, boss, "APPROVE", "به جای کارشناس تایید شد")
with new_session() as s:
    check(s.get(WfTask, t1.task_id).sla_status == "BREACHED" and runtime.get_instance(company_id, i1).status_code == "COMPLETED",
          "manager decided escalated task")

i2 = runtime.start_instance(company_id, d, "REQ3", 1, started_by=requester)
t2 = tasks.list_tasks(company_id, instance_id=i2)[0]
check(raises(lambda: sla.remind_now(company_id, t2.task_id, a2), "فقط درخواست‌کننده"), "only requester/manager can nudge")
check(sla.remind_now(company_id, t2.task_id, requester, "لطفاً امروز") == 1, "manual reminder")
tasks.decide(company_id, t2.task_id, a1, "APPROVE")
with new_session() as s:
    check(s.get(WfTask, t2.task_id).sla_status == "MET" and
          not s.execute(text("SELECT 1 FROM wf.timers WHERE task_id = :t AND status_code = 'PENDING'"), {"t": t2.task_id}).first(),
          "on-time decision: SLA met, timers cancelled")

# ===== ۴) کانال‌های اعلان و ترجیحات =====
check(notify.effective_channels(company_id, a1, "WF_APPROVAL_REQUIRED") == notify.DEFAULT_CHANNELS, "default channels")
save_settings(company_id, uid, notification_defaults={"WF_ESCALATION": {"sms": True}})
check(notify.effective_channels(company_id, a1, "WF_ESCALATION")["sms"], "company default enables SMS for escalations")
notify.save_preference(company_id, a1, "WF_APPROVAL_REQUIRED", sms=True, desktop=False)
notify.save_preference(company_id, a2, "*", in_app=False, desktop=False)
check(raises(lambda: notify.save_preference(company_id, a1, "BAD", sms=True), "نامعتبر"), "unknown type rejected")
SENT = []
notify.register_sms_sender(lambda cid, u, title, body: SENT.append((u, title)) or ("SENT" if u == a1 else "NO_ADDRESS"))
notify.send(company_id, [a1, a2], "WF_APPROVAL_REQUIRED", "تایید فاکتور ۱۲", "مبلغ ۵ میلیون")
with new_session() as s:
    n_a1 = s.scalar(select(Notification).where(Notification.user_id == a1, Notification.title == "تایید فاکتور ۱۲"))
    n_a2 = s.scalar(select(Notification).where(Notification.user_id == a2, Notification.title == "تایید فاکتور ۱۲"))
check(n_a1.channels == {"desktop": False, "sms": "PENDING"} and n_a2 is None, f"per-user channels ({n_a1.channels})")
check(not notify.desktop_popups(company_id, a1, 0) or all(p.title != "تایید فاکتور ۱۲" for p in notify.desktop_popups(company_id, a1, 0)),
      "desktop popup respects preference")
check(scheduler.run_due(company_id).get("deliveries", 0) >= 1 and (a1, "تایید فاکتور ۱۲") in SENT, "SMS delivered by scheduler")
with new_session() as s:
    check(s.get(Notification, n_a1.notification_id).channels["sms"] == "SENT", "delivery status recorded")
check("پیامک: ارسال شد" in notify.list_notifications(company_id, a1)[0].delivery, "delivery shown in Persian")
notify.register_sms_sender(None)
check(notify._sms_sender(company_id, a1, "x", "y") == "NOT_CONFIGURED" and notify._sms_sender(company_id, a2, "x", "y") == "NO_ADDRESS",
      "real SMS sender: gateway not configured / user without mobile")
unread = notify.unread_count(company_id, a1)
check(unread >= 3 and notify.mark_read(company_id, a1, [n_a1.notification_id]) == 1 and notify.unread_count(company_id, a1) == unread - 1,
      "mark read")
notify.mark_read(company_id, a1)
check(notify.unread_count(company_id, a1) == 0, "mark all read")
last = notify.latest_id(company_id, boss)
notify.send(company_id, [boss], "WF_MESSAGE", "پیام آزمایشی")
check([p.title for p in notify.desktop_popups(company_id, boss, last)] == ["پیام آزمایشی"], "desktop popup for new notification")

# ===== ۵) کارهای من: همهٔ منابع در یک فهرست =====
role = roles_service.create_role(company_id, "ACC", None)
roles_service.set_user_role(a2, role.role_id, company_id, True)
cartable.register_handler("crm_leads", on_approved=lambda *a: None, on_rejected=lambda *a: None, describe=lambda c, r: f"سرنخ {r}")
cartable.save_workflow_steps(company_id, "crm_leads", True, [role.role_id])
item = cartable.submit_for_approval(company_id, "crm_leads", 5, "CREATE", requester)
i3 = runtime.start_instance(company_id, d, "REQ3", 1, started_by=requester)
graph_any = dict(graph, nodes=[dict(graph["nodes"][0], approvers=[{"kind": "USER", "user_id": a2}], sla_policy_id=None,
                                    due_hours=1, business_hours=False)] + graph["nodes"][1:])
d2 = defs.create_definition(company_id, uid, code="a2", name="تایید دوم", entity_type="REQ3", graph=graph_any)
defs.publish(company_id, uid, d2)
i4 = runtime.start_instance(company_id, d2, "REQ3", 1, started_by=requester)
acts.create_activity(company_id, uid, acts.ActivityFields("CALL", "تماس با مشتری الف", customer_detail_account_id=cust_a,
                                                          due_date=today - datetime.timedelta(days=1), assigned_to_user_id=a2))
work = inbox.my_work(company_id, a2)
sources = {w.source for w in work}
check({"WF", "CARTABLE", "CRM"} <= sources, f"all sources in one list ({sources})")
s2 = inbox.summarize(work)
check(s2.approvals == 2 and s2.overdue >= 1 and work[0].is_overdue, f"summary and overdue first ({s2})")
check([w.key for w in inbox.approvals(company_id, a2)] and all(w.kind == "APPROVAL" for w in inbox.approvals(company_id, a2)),
      "approval center lists only approvals")
det = inbox.detail(company_id, a2, f"WF:{tasks.list_tasks(company_id, instance_id=i4)[0].task_id}")
check(det["decisions"][0] == ("APPROVE", "تایید") and det["path"] and det["context"] == [("مبلغ", "۵")], f"detail for quick decision ({det['context']})")
check(raises(lambda: inbox.quick_decide(company_id, a2, f"CARTABLE:{item}", "REJECT", ""), "علت"), "legacy reject needs reason")
check(raises(lambda: inbox.detail(company_id, a2, "CRM:1"), "سند را باز کنید"), "follow-ups have no quick decision")
res = inbox.bulk_approve(company_id, a2, [w.key for w in inbox.approvals(company_id, a2)], "تایید گروهی")
check(all(ok for _k, ok, _m in res) and len(res) == 2 and runtime.get_instance(company_id, i4).status_code == "COMPLETED",
      f"bulk approve across engine and legacy inbox ({res})")
check(not inbox.approvals(company_id, a2), "approval inbox empty after bulk approve")
check(inbox.counts(company_id, a1)["approvals"] == 1, "badge counts")
check(inbox.quick_decide(company_id, a1, f"WF:{tasks.list_tasks(company_id, instance_id=i3)[0].task_id}", "REJECT", "نیازی نیست") == "رد شد.",
      "quick reject")

# ===== ۶) صفحه‌ها: هم‌شکل بقیهٔ ماژول‌ها، بدون دکمهٔ متنی =====
import re
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton, QScrollArea
qapp = QApplication.instance() or QApplication([])
from PySide6.QtCore import Qt
qapp.setLayoutDirection(Qt.RightToLeft)  # مثل برنامهٔ واقعی
WARN = []
QMessageBox.warning = staticmethod(lambda *a, **k: WARN.append(a[2] if len(a) > 2 else ""))
from peecha import nav_catalog, session as sess
from peecha.services import roles as roles_mod
from peecha.ui import shell_window
from peecha.ui.screens import workflow_center as ui
from peecha.ui.screens.system_settings import SystemSettingsScreen
from peecha.ui.widgets import SummaryCard
from peecha.db.models.security import User
from peecha.db.models.core import Company

flat = {i["code"]: i for i in nav_catalog.flatten_nav_items()}
ribbon = nav_catalog.DEFAULT_QUICK_ACCESS_BY_MODULE.get("WF", [])
check({"WF_MY_WORK", "WF_APPROVALS", "WF_NOTIFICATIONS", "WF_DELEGATIONS"} <= {c for c, _ in ribbon} and
      all(c in flat for c, _ in ribbon), "workflow ribbon")
check(flat["WF_SETTINGS"].get("hidden_from_sidebar") and shell_window._SETTINGS_TAB_BY_GROUP_CODE.get("WF") == 13,
      "settings gear → system settings tab 13")
check("WF" in roles_mod.MODULE_LABELS and any(f[0] == "wf_approvals" for f in nav_catalog.build_form_catalog()),
      "module and forms in permission catalog")


def login(u):
    with new_session() as s:
        sess.current_user = s.get(User, u)
        sess.current_company = s.get(Company, company_id)
        s.expunge_all()


LATIN = re.compile(r"[A-Za-z]")


def no_text_buttons(w, name):
    plain = [b.text() for b in w.findChildren(QPushButton) if len(b.text()) > 2]
    check(not plain, f"{name}: no text buttons {plain}")
    check(all(b.toolTip() and not LATIN.search(b.toolTip()) for b in w.findChildren(QPushButton)),
          f"{name}: Persian tooltips")


login(a1)
i5 = runtime.start_instance(company_id, d, "REQ3", 1, started_by=requester)
mw = ui.MyWorkScreen()
mw.refresh()
no_text_buttons(mw, "MyWork")
check(len(mw.findChildren(SummaryCard)) == 5 and mw.cards["approvals"].text() == "۱" and mw.table.rowCount() >= 1, "my work screen loads")
mw.kind.setCurrentIndex(mw.kind.findData("FOLLOWUP"))
check(mw.table.rowCount() == 0 and not mw.empty.isHidden(), "filter by kind")
mw.kind.setCurrentIndex(0)
key5 = f"WF:{tasks.list_tasks(company_id, instance_id=i5)[0].task_id}"
check(mw.select_key(key5) and mw.approve_selected() and runtime.get_instance(company_id, i5).status_code == "COMPLETED",
      "approve from my work")

login(a1)
i6 = runtime.start_instance(company_id, d, "REQ3", 1, started_by=requester)
i7 = runtime.start_instance(company_id, d, "REQ3", 1, started_by=requester)
ac = ui.ApprovalCenterScreen()
ac.refresh()
no_text_buttons(ac, "ApprovalCenter")
check(ac.table.rowCount() == 2 and ac.current is not None and "✔ ثبت و ارسال" in ac.d_path.text()
      and ac.d_context.rowCount() == 1, "approval center shows context and path")
check(not ac.buttons["changes"].isEnabled(), "changes button disabled when no correction path")
check(ac.add_note("لطفاً مدارک پیوست شود") and ac.d_history.rowCount() >= 1, "note from approval center")
WARN.clear()
check(not ac.decide("REJECT", "") and any("علت" in w for w in WARN), "reject without reason warns")
ac.select_key(f"WF:{tasks.list_tasks(company_id, instance_id=i6)[0].task_id}")
check(ac.decide("REJECT", "بودجه ندارد") and runtime.get_instance(company_id, i6).outcome_code == "REJECTED", "reject with reason")
check(ac.table.rowCount() == 1, "list refreshed")
ac.table.selectAll()
res = ac.bulk_approve()
check(res and all(ok for _k, ok, _m in res) and runtime.get_instance(company_id, i7).status_code == "COMPLETED", "bulk approve from UI")

login(a1)
nc = ui.NotificationCenterScreen()
nc.refresh()
no_text_buttons(nc, "Notifications")
n_unread = notify.unread_count(company_id, a1)
check(nc.table.rowCount() == n_unread and nc.cards["unread"].text() == numerals.to_persian_digits(str(n_unread)), "notification list")
nc.table.setCurrentCell(0, 0)
check(nc.mark_selected() == 1 and notify.unread_count(company_id, a1) == n_unread - 1, "mark one read from UI")
nc.mark_all()
check(notify.unread_count(company_id, a1) == 0 and nc.table.rowCount() == 0, "mark all read from UI")
dlg = ui.NotificationPrefsDialog()
dlg.set_channel("WF_TASK_DUE", "sms", True)
dlg.save()
check(notify.effective_channels(company_id, a1, "WF_TASK_DUE")["sms"], "user channel preferences from dialog")

ds = ui.DelegationsScreen()
ds.refresh()
no_text_buttons(ds, "Delegations")
did = ds.create({"from": a1, "to": boss, "starts_on": today, "ends_on": today + datetime.timedelta(days=2), "reason": "مرخصی"})
check(did and ds.table.rowCount() == 1 and ds.cards["mine"].text() == "۱", "delegation created from UI")
ds.table.setCurrentCell(0, 0)
check(ds.end_selected() and ds.table.rowCount() == 0, "delegation ended from UI")

login(uid)
settings_screen = SystemSettingsScreen()
check(settings_screen.tabs.tabText(13) == "گردش کار", "system settings has a workflow tab at 13")
wf_tab = settings_screen.tabs.widget(13)
pages = {wf_tab.tabText(i): wf_tab.widget(i) for i in range(wf_tab.count())}
page = lambda label: pages[label].widget() if isinstance(pages[label], QScrollArea) else pages[label]  # noqa: E731
check(set(pages) == {"قواعد عمومی", "تقویم کاری و تعطیلات", "تعهد زمانی و ارجاع", "پیش‌فرض اعلان‌ها", "کارکنان و مدیران"},
      f"workflow settings sub-tabs ({list(pages)})")
settings_screen.select_tab(13, "قواعد عمومی")
rules = page("قواعد عمومی")
rules.refresh()
rules.max_steps.setText("۳۰۰")
from peecha.services.workflow.common import settings as wf_settings
check(rules.save() and wf_settings(company_id)["max_steps"] == 300, "rules saved")
cal = page("تقویم کاری و تعطیلات")
cal.refresh()
cal.days[3][2].setText("۱۲:۰۰")
check(cal.save_hours() and calendar.work_hours(company_id)[3][1] == datetime.time(12, 0), "work hours from UI")
check(cal.add_holiday({"date": datetime.date(2026, 11, 1), "title": "تعطیلی آزمایشی"}) and cal.t_holidays.rowCount() == 1, "holiday from UI")
cal.t_holidays.setCurrentCell(0, 0)
check(cal.delete_holiday() and cal.t_holidays.rowCount() == 0, "holiday removed from UI")
sp = page("تعهد زمانی و ارجاع")
sp.refresh()
n_pol = sp.t_policies.rowCount()
check(sp.edit_policy(new=True, values={"code": "normal", "name": "تایید عادی", "due_hours": D(16), "warn_before_hours": D(4),
                                       "escalate_after_hours": D(8), "escalate_to": [{"kind": "MANAGERS"}]})
      and sp.t_policies.rowCount() == n_pol + 1, "SLA policy from UI")
nd = page("پیش‌فرض اعلان‌ها")
nd.refresh()
nd.set_channel("WF_SLA_BREACHED", "sms", True)
check(nd.save() and notify.effective_channels(company_id, boss, "WF_SLA_BREACHED")["sms"], "company notification defaults from UI")
ol = page("کارکنان و مدیران")
ol.refresh()
check(ol.t_emp.rowCount() == 2 and ol.t_emp.cellWidget(0, 2).currentData() == a1 and ol.t_unit.cellWidget(0, 1).currentData() == e_boss,
      "org links panel shows employee users and unit managers")
check(ol.save_employees() and ol.save_units(), "org links saved")
for name in ("WfRulesPanel", "CalendarPanel", "SlaPoliciesPanel", "NotificationDefaultsPanel", "OrgLinksPanel"):
    no_text_buttons(getattr(ui, name)(), name)

from peecha.ui.screens.hr_org_units import OrgUnitsScreen
ou = OrgUnitsScreen()
ou.refresh()
check(ou.table.item(0, 1).text() == "مدیر بخش", "org unit list shows manager")

# زنگوله و پیام کوتاه روی صفحه
login(boss)
win = shell_window.MainWindow() if hasattr(shell_window, "MainWindow") else None
if win is not None:
    win.load_context_switcher()
    base = win.update_notification_badge()
    win._show_new_notifications()
    notify.send(company_id, [boss], "WF_MESSAGE", "پیام تازه برای زنگوله")
    shown = win._show_new_notifications()
    check(win.update_notification_badge() == base + 1 and [r.title for r in shown] == ["پیام تازه برای زنگوله"]
          and win._toast.isVisible() is not None, "bell badge and desktop popup")

fx.finish()
sys.stdout.flush()
os._exit(0)
