import os, re, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r289"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crm_fixture import *  # noqa: F401,F403
import crm_fixture as fx
from peecha import nav_catalog
from peecha.services.crm import analytics, automation as auto, common as cc, communication as comm, loyalty, reports as rpt, segments as seg
from peecha.services.crm import tickets as tk
from peecha.services.purchase_reports import PurchaseFilters
check = fx.check
LATIN = re.compile(r"[A-Za-z]")

# ===== ۴) ریبون ماژول ارتباط با مشتری =====
flat = {i["code"]: i for i in nav_catalog.flatten_nav_items()}
ribbon = nav_catalog.DEFAULT_QUICK_ACCESS_BY_MODULE.get("CRM", [])
check(len(ribbon) >= 8 and all(code in flat for code, _ in ribbon), "CRM ribbon shortcuts point to real menu items")
check({"CRM_DASHBOARD", "CRM_CUSTOMER360", "CRM_LEADS", "CRM_PIPELINE", "CRM_TICKETS", "CRM_CAMPAIGNS"} <= {c for c, _ in ribbon},
      "ribbon covers main CRM forms")

# ===== ۳) چرخ‌دندهٔ تنظیمات کنار منو =====
from PySide6.QtWidgets import (QApplication, QCheckBox, QDialogButtonBox, QLabel, QLineEdit, QListWidget, QMessageBox, QPushButton,
                               QScrollArea, QTableWidget, QTabWidget)
qapp = QApplication.instance() or QApplication([])
QMessageBox.information = staticmethod(lambda *a, **k: None)
QMessageBox.warning = staticmethod(lambda *a, **k: None)
from peecha.ui import shell_window
from peecha.ui.screens import crm as ui
from peecha.ui.screens.system_settings import SystemSettingsScreen
check(shell_window._SETTINGS_TAB_BY_GROUP_CODE.get("CRM") == 12, "CRM gear opens settings tab 12")
check(flat["CRM_SETTINGS"].get("hidden_from_sidebar"), "CRM settings form moved under the gear (not a sidebar item)")
settings = SystemSettingsScreen()
check(settings.tabs.tabText(12) == "ارتباط با مشتری", "system settings has a CRM tab at index 12")
crm_tab = settings.tabs.widget(12)
pages = {crm_tab.tabText(i): crm_tab.widget(i) for i in range(crm_tab.count())}


def page(label: str):
    w = pages[label]
    return w.widget() if isinstance(w, QScrollArea) else w


check(set(pages) == {"قیف فروش و منابع سرنخ", "باشگاه مشتریان", "امتیازدهی سرنخ", "تعهد زمانی تیکت‌ها", "الگوهای پیام", "تحلیل مشتری"},
      f"CRM settings sub-tabs ({list(pages)})")
settings.select_tab(12, "تعهد زمانی تیکت‌ها")
sla = page("تعهد زمانی تیکت‌ها")
check(isinstance(sla, ui.SlaPoliciesPanel) and sla.t_sla.rowCount() == 4, "gear jumps to SLA policies and loads them")
check(all(sla.t_sla.item(r, 0).text().startswith("اولویت ") for r in range(4)), "default policy names are Persian")
check(sla.edit_policy(new=True, values={"name": "مشتریان کلیدی", "first_response_hours": D(1), "resolution_hours": D(4)}) is not None
      and sla.t_sla.rowCount() == 5, "policy added from system settings")
settings.select_tab(12, "باشگاه مشتریان")
lp = page("باشگاه مشتریان")
lp.l_fields["referral_points"].setText("۱۲۰")
check(lp.save() and loyalty.get_rules(company_id)["referral_points"] == 120, "loyalty rules saved from system settings")
settings.select_tab(12, "امتیازدهی سرنخ")
sp = page("امتیازدهی سرنخ")
sp.s_factors["profile"].setText("12")
check(sp.save(), "lead scoring saved from system settings")
settings.select_tab(12, "تحلیل مشتری")
ap = page("تحلیل مشتری")
ap.dialog_runner = lambda dlg: True
check(ap.fields["rfm_window_days"].text() in ("365", "۳۶۵"), "analytics settings loaded")
ap.fields["rfm_window_days"].setText("180")
check(ap.save() and analytics.settings(company_id)["rfm_window_days"] == 180, "analytics window saved")
ap.fields["clv_horizon_months"].setText("0")
check(not ap.save() and analytics.settings(company_id)["clv_horizon_months"] == 24, "zero horizon rejected")
settings.select_tab(12, "الگوهای پیام")
tp = page("الگوهای پیام")
check(tp.edit_template(new=True, values={"code": "BDAY", "name": "تبریک", "channel": "SMS", "subject": None,
                                         "body": "{نام} عزیز، تولدت مبارک", "is_active": True}) and tp.t_tpl.rowCount() == 1,
      "template added from system settings")
settings.select_tab(12, "قیف فروش و منابع سرنخ")
check(isinstance(page("قیف فروش و منابع سرنخ"), ui.CrmSettingsScreen) and page("قیف فروش و منابع سرنخ").t_stages.rowCount() >= 5,
      "pipeline settings embedded")

# ===== جای‌نگهدار فارسی =====
check(comm.render("سلام {نام}، ماندهٔ شما {مانده}", {"name": "علی", "balance": 5}) == "سلام علی، ماندهٔ شما 5", "Persian placeholders")
check(comm.render("Hi {name} {x}", {"name": "علی"}) == "Hi علی {x}", "old English placeholders still work")
check("{نام}" in comm.fields_hint() and not re.search(r"\{[a-z]+\}", comm.fields_hint()), "hint shows Persian placeholders")

# ===== قاعده با انتخاب کاربر به‌جای OWNER =====
users = [(name, u) for u, name in cc.list_company_users(company_id)]
dlg = ui.RuleDialog(None, [], [], None, users)
dlg.name.setText("پیگیری سرنخ")
from peecha.ui.screens.fixed_assets import set_combo
set_combo(dlg.trigger, "LEAD_NOT_CONTACTED")
set_combo(dlg.action, "CREATE_ACTIVITY")
owner_box = dlg.act_fields["assign_to"][1]
check(owner_box.currentData() == "OWNER" and LATIN.search(owner_box.currentText()) is None, "assignee defaults to record owner (Persian)")
set_combo(owner_box, uid)
vals = dlg.values()
check(vals["action_params"]["assign_to"] == uid and "{نام}" in vals["action_params"]["subject"], "assignee picked from users")
rid = auto.save_rule(company_id, uid, **vals)
check(rid and next(r for r in auto.list_rules(company_id) if r.rule_id == rid).action_params["assign_to"] == uid, "rule saved with user")
check(fx.raises(lambda: auto.save_rule(company_id, uid, **{**vals, "action_params": {**vals["action_params"], "assign_to": "x"}}), "کاربران"),
      "bad assignee message is Persian")

# ===== مهاجرت نام‌های قدیمی =====
from sqlalchemy import func, text
from peecha.db.models.crm import AutomationRule, Segment, SlaPolicy
seg.list_segments(company_id)
with new_session() as s:
    s.execute(text("UPDATE crm.sla_policies SET name = 'SLA بالا' WHERE name = 'اولویت بالا'"))
    s.execute(text("UPDATE crm.segments SET name = 'مشتریان ویژه (VIP)' WHERE code = 'VIP'"))
    s.execute(text("UPDATE crm.automation_rules SET action_params = jsonb_set(action_params, '{subject}', '\"پیگیری {name}\"') "
                   "WHERE rule_id = :r"), {"r": rid})
    s.commit()
sql = open(os.path.join(os.path.dirname(__file__), "..", "..", "db", "schema", "209_crm_persian_labels.sql"), encoding="utf-8").read()
with get_engine().begin() as conn:
    conn.execute(text(sql))
with new_session() as s:
    check(s.scalar(select(func.count()).select_from(SlaPolicy).where(SlaPolicy.name == "اولویت بالا")) == 1, "migration renames SLA names")
    check(s.scalar(select(Segment.name).where(Segment.company_id == company_id, Segment.code == "VIP")) == "مشتریان ویژه",
          "migration renames VIP segment")
    check(s.get(AutomationRule, rid).action_params["subject"] == "پیگیری {نام}", "migration converts placeholders")

# ===== ۲) فارسی روان: برچسب‌های سرویس، منو و گزارش‌ها =====
labels = list(analytics.RFM_SEGMENTS.values()) + [f.label for f in seg.FIELDS.values()] + list(seg.OPERATORS.values())
labels += [n for _c, n, _r in seg.SYSTEM_SEGMENTS] + [n for n, *_ in tk.DEFAULT_POLICIES]
labels += [v[0] for v in auto.TRIGGERS.values()] + [p.label for v in auto.TRIGGERS.values() for p in v[2]]
labels += [v[0] for v in auto.ACTIONS.values()] + [p.label for v in auto.ACTIONS.values() for p in v[1]] + [r[0] for r in auto.DEFAULT_RULES]
labels += list(comm.CHANNELS.values()) + list(comm.TEMPLATE_FIELDS.values())
labels += [r.title for r in rpt.CRM_REPORTS] + [r.hint for r in rpt.CRM_REPORTS]
labels += [lbl for r in rpt.CRM_REPORTS for _k, lbl, ch in r.options] + [lbl for r in rpt.CRM_REPORTS for _k, _l, ch in r.options for _v, lbl in ch]
for r in rpt.CRM_REPORTS:
    res = r.func(company_id, PurchaseFilters(today.replace(day=1), today, side="INVENTORY", options={k: ch[0][0] for k, _l, ch in r.options}))
    labels += [c for c, _t in res.columns] + [res.note]


def crm_nav_labels(items, inside=False):
    out = []
    for i in items:
        here = inside or i["code"] in ("CRM", "REPORTS_CRM")
        if here:
            out.append(i["label"])
        out += crm_nav_labels(i.get("children", []), here)
    return out


nav_labels = crm_nav_labels(nav_catalog.NAV_ITEMS)
check(len(nav_labels) > 30, "CRM menu labels collected")
bad = [x for x in labels + nav_labels if x and LATIN.search(x)]
check(not bad, f"CRM service/menu/report labels are fully Persian {bad[:8]}")

# ===== ۱ و ۲) دکمه‌های آیکونی و متن فارسی در همهٔ فرم‌ها =====
ICON = ("iconButton", "primaryIconButton", "dangerIconButton")


def visible_texts(w) -> list[str]:
    out = [w.windowTitle()]
    out += [x.text() for x in w.findChildren(QLabel)] + [x.text() for x in w.findChildren(QCheckBox)]
    out += [x.placeholderText() for x in w.findChildren(QLineEdit)]
    for b in w.findChildren(QPushButton):
        if not isinstance(b.parent(), QDialogButtonBox):
            out += [b.property("label") or b.text(), b.toolTip()]
    for t in w.findChildren(QTabWidget):
        out += [t.tabText(i) for i in range(t.count())]
    for t in w.findChildren(QTableWidget):
        out += [t.horizontalHeaderItem(i).text() for i in range(t.columnCount()) if t.horizontalHeaderItem(i)]
    for lw in w.findChildren(QListWidget):
        out += [lw.item(i).text() for i in range(lw.count())]
    return [x for x in out if x and LATIN.search(x)]


forms = [ui.Customer360Screen(), ui.TaskCenterScreen(), ui.LeadsScreen(), ui.PipelineScreen(), ui.CrmSettingsScreen(), ui.AnalyticsScreen(),
         ui.CampaignsScreen(), ui.TicketsScreen(), ui.AutomationScreen(), ui.CrmDashboardScreen()]
for scr in forms:
    scr.dialog_runner = lambda dlg: True
    scr.refresh()
dialogs = [ui.SegmentDialog(), ui.RuleDialog(None, [], [], None, users)]
for w in forms + dialogs + [crm_tab]:
    name = type(w).__name__
    buttons = [b for b in w.findChildren(QPushButton) if not isinstance(b.parent(), QDialogButtonBox)]
    text_buttons = [b.text() for b in buttons if b.objectName() not in ICON]
    check(not text_buttons, f"{name}: every button is an icon button {text_buttons}")
    check(all(b.toolTip() and b.property("label") for b in buttons), f"{name}: icon buttons keep their label as tooltip")
    latin = visible_texts(w)
    check(not latin, f"{name}: no English abbreviations or raw codes in visible text {latin[:6]}")
check(all(isinstance(d.findChild(QDialogButtonBox), QDialogButtonBox) for d in dialogs), "dialogs use standard OK/Cancel like other forms")
c360 = forms[0]
c360.load_customer(cust_a)
check(c360.quick["call"].objectName() == "iconButton" and c360.quick["call"].property("label") == "تماس تازه", "360 quick bar is iconized")
auto_scr = forms[8]
everyone = seg.save_segment(company_id, uid, code="ALL", name="همهٔ مشتریان",
                            rule={"all": [{"field": "invoice_count_total", "op": ">=", "value": 0}]})
seg_rule = auto.save_rule(company_id, uid, name="تماس با همه", trigger_code="SEGMENT_MEMBER", conditions={"segment_id": everyone},
                          action_code="CREATE_ACTIVITY", action_params={"activity_type": "CALL", "subject": "تماس با {نام}"})
check(auto.run_rule(company_id, seg_rule) >= 2, "segment rule acts on customers")
from peecha.services.crm import activities as acts
check(any(a.subject == "تماس با فروشگاه الف" for a in acts.list_activities(company_id, customer_detail_account_id=cust_a)),
      "Persian placeholder rendered in automated activity")
auto_scr.reload()
kinds = {auto_scr.t_log.item(r, 2).text() for r in range(auto_scr.t_log.rowCount())}
check(kinds and not any(LATIN.search(k) for k in kinds), f"automation log shows Persian record type ({kinds})")

# ===== ۳ و ۴ در پوستهٔ اصلی: چرخ‌دندهٔ کنار منو و ریبون =====
from PySide6.QtWidgets import QFrame, QWidget
from peecha.ui.shell_window import MainWindow
mw = MainWindow(); mw.resize(1300, 850); mw.show(); qapp.processEvents()
gear = mw._sidebar_groups["CRM"].findChild(QWidget, "sidebarGearButton")
check(gear is not None, "gear button next to the CRM sidebar menu")
mw.open_screen("CRM_LEADS"); qapp.processEvents()
tiles = [t for t in mw.findChildren(QFrame, "quickTile") if t.isVisible()]
check(mw._quick_access_module_code == "CRM" and len(tiles) >= 8, f"CRM ribbon shown for CRM forms ({len(tiles)} tiles)")
gear.click(); qapp.processEvents()
opened = [w for w in mw.findChildren(SystemSettingsScreen)]
check(opened and opened[0].tabs.currentIndex() == 12, "gear opens system settings on the CRM tab")

fx.finish()
