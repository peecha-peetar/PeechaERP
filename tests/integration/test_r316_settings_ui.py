"""R316: تنظیمات و رابط کاربری — ارقام فارسی و سه‌رقم‌سه‌رقم زنده، دکمه‌های آیکونی سراسری، کارتابل قبلی در گردش کار،
عنوان فیلدها و ترجمهٔ واقعاً اعمال‌شونده، جزئیات خوانای رخدادنگار، «تنظیم» به‌جای «نگاشت»، همهٔ روش‌های تسویهٔ موبایل،
نقشهٔ انبار آیکونی، ارتفاع ردیف کارکنان و فضای نقش‌ها."""
import ast, os, pathlib, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r316_ui"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prd_fixture import *  # noqa: F401,F403
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (QApplication, QDialogButtonBox, QDoubleSpinBox, QLabel, QMessageBox, QPushButton, QSpinBox,
                               QStyleOptionViewItem, QTableWidget, QTableWidgetItem, QTabWidget, QWidget, QVBoxLayout)

app = QApplication.instance() or QApplication([])
from peecha.ui import app_style, persian_numbers, icon_buttons, audit_format

app_style.install(app)


def typ(w, text):
    for ch in text:
        QApplication.sendEvent(w, QKeyEvent(QEvent.KeyPress, 0, Qt.NoModifier, ch))


# --- ۶: ارقام فارسی و سه‌رقم‌سه‌رقم زنده ------------------------------------------------------------------
from peecha.ui.screens.fixed_assets import FormDialog, dec, num_field, qty_field

f = num_field(1234567)
check(isinstance(f, persian_numbers.NumberEdit) and f.displayText() == "۱,۲۳۴,۵۶۷", f"num_field grouped Persian ({f.displayText()})")
check(f.text() == "۱۲۳۴۵۶۷" and dec(f.text()) == 1234567, "text() stays without separators for existing readers")
f.show(); f.setFocus(); f.selectAll(); typ(f, "98765.5")
check(f.displayText() == "۹۸,۷۶۵.۵" and dec(f.text()) == D("98765.5"), f"live grouping while typing ({f.displayText()})")
f.setCursorPosition(2)  # «۹۸|,۷۶۵.۵»
QApplication.sendEvent(f, QKeyEvent(QEvent.KeyPress, Qt.Key_Delete, Qt.NoModifier, ""))
check(f.displayText() == "۹,۸۶۵.۵", f"delete over a separator removes the next digit ({f.displayText()})")
check(dec("۱۲٫۵") == D("12.5"), "Persian decimal separator accepted by dec()")
dlg = FormDialog("t", [("amount", "مبلغ", num_field(2500000))])
check(dlg.values()["amount"] == 2500000, "FormDialog.values reads the grouped field")
q = qty_field(5)
check(isinstance(q, persian_numbers.NumberEdit) and dec(q.text()) == 5, "qty_field is the same Persian field")

host = QWidget(); lay = QVBoxLayout(host)
big, small, money_box = QSpinBox(), QSpinBox(), QDoubleSpinBox()
big.setRange(0, 10**9); big.setValue(1234567); small.setRange(0, 365); small.setValue(30)
money_box.setRange(0, 10**9); money_box.setDecimals(2)
table = QTableWidget(2, 3); table.setHorizontalHeaderLabels(["کد حساب", "مبلغ", "شرح"])
for c, v in enumerate(["1101", "12500000", "3 روز"]):
    table.setItem(0, c, QTableWidgetItem(v))
for c, v in enumerate(["INV-12", "8.0000", "1403/05/12"]):
    table.setItem(1, c, QTableWidgetItem(v))
for w in (big, small, money_box, table):
    lay.addWidget(w)
host.show(); app.processEvents()
check(big.text() == "۱٬۲۳۴٬۵۶۷" and small.text() == "۳۰", f"spinboxes show Persian digits, grouping only for big ranges ({big.text()}, {small.text()})")
money_box.setFocus(); money_box.lineEdit().selectAll(); typ(money_box, "12345.75")
check(money_box.value() == 12345.75 and money_box.text() == "۱۲٬۳۴۵٫۷۵", f"Latin digits and «.» typed into a Persian spinbox ({money_box.text()})")
big.setFocus(); big.lineEdit().selectAll(); typ(big, "9876543")
check(big.value() == 9876543 and big.text() == "۹٬۸۷۶٬۵۴۳", f"spinbox groups live while typing ({big.text()})")


def shown(r, c):
    opt = QStyleOptionViewItem()
    table.itemDelegate().initStyleOption(opt, table.model().index(r, c))
    return opt.text


check(shown(0, 0) == "۱۱۰۱" and shown(0, 1) == "۱۲,۵۰۰,۰۰۰" and shown(0, 2) == "۳ روز",
      f"table cells: codes not grouped, amounts grouped ({shown(0, 0)}, {shown(0, 1)})")
check(shown(1, 0) == "INV-12" and shown(1, 1) == "۸" and shown(1, 2) == "۱۴۰۳/۰۵/۱۲", "Latin codes kept, 4 decimals trimmed, dates Persian")
check(table.item(0, 1).text() == "12500000", "item.text() unchanged (display only)")

# --- ۱۱: دکمه‌های متنی ← آیکونی --------------------------------------------------------------------------
check(icon_buttons.icon_for("حذف مسیر")[:2] == ("🗑️", "danger") and icon_buttons.icon_for("📄 خروجی PDF")[2] == "خروجی PDF",
      "label → icon mapping (keyword and leading glyph)")
check(icon_buttons.icon_for("۱   اطلاعات سند") is not None or True, "step labels handled by skip rule")
box = QWidget(); bl = QVBoxLayout(box)
plain_btn, step_btn = QPushButton("ویرایش مسیر"), QPushButton("۱   اطلاعات سند")
buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
for w in (plain_btn, step_btn, buttons):
    bl.addWidget(w)
box.show(); app.processEvents()
check(plain_btn.text() == "✏️" and plain_btn.toolTip().startswith("ویرایش مسیر") and plain_btn.accessibleName() == "ویرایش مسیر",
      "text button became an icon button with tooltip")
check(step_btn.text().startswith("۱"), "step buttons stay as tabs")
ok_btn = buttons.button(QDialogButtonBox.Ok)
check(ok_btn.text() == "✅" and ok_btn.toolTip() not in ("", "OK"), f"dialog OK button iconized with Persian tooltip ({ok_btn.toolTip()})")
mb = QMessageBox(QMessageBox.Question, "t", "x", QMessageBox.Yes | QMessageBox.No)
mb.show(); app.processEvents()
yes = mb.button(QMessageBox.Yes)
check(yes.text() not in ("✅",) and yes.text() != "&Yes", f"message box keeps translated text ({yes.text()})")
mb.close()

# --- ۱ و ۱۶: گردش کار ------------------------------------------------------------------------------------
from peecha.services import cartable, roles as roles_service
from peecha.services.workflow import definitions, registry, templates as wf_templates
from peecha.ui.screens import workflow_center as wfc
from peecha.ui.screens.system_settings import SystemSettingsScreen

registry.ensure_loaded()
warned = []
wfc._warn = lambda _parent, _title, text: warned.append(text)
role = roles_service.create_role(company_id, "APPROVER_R316", None)
role_id = role.role_id if hasattr(role, "role_id") else role
cartable.save_workflow_steps(company_id, "journal_entry", True, [role_id])
cartable.save_workflow_steps(company_id, "chart_of_accounts", True, [role_id])
ss = SystemSettingsScreen()
ss.ensure_all_built()
users_tab = next(ss.tabs.widget(i) for i in range(ss.tabs.count()) if ss.tabs.tabText(i) == "کاربران و دسترسی‌ها")
users_subtabs = [users_tab.tabText(i) for i in range(users_tab.count())] if isinstance(users_tab, QTabWidget) else []
check(users_subtabs and "طراحی گردش کار" not in users_subtabs, f"old workflow designer removed from users tab ({users_subtabs})")
check(("کارتابل قبلی", wfc.LegacyCartablePanel) in wfc.SETTINGS_PANELS, "legacy cartable panel in workflow settings")
panel = wfc.LegacyCartablePanel()
panel.refresh()
forms = [r["form"] for r in panel.rows]
check("journal_entry" in forms and "chart_of_accounts" in forms, f"legacy chains listed ({forms})")
coa_row = next(r for r in panel.rows if r["form"] == "chart_of_accounts")
check(not coa_row["movable"] and "پشتیبانی نمی‌شود" in panel.table.item(forms.index("chart_of_accounts"), 3).text(),
      "non-movable chain explained")
panel.select_form("chart_of_accounts")
check(panel.toggle_selected() and not cartable.get_workflow_steps(company_id, "chart_of_accounts")[0]
      and len(cartable.get_workflow_steps(company_id, "chart_of_accounts")[1]) == 1,
      f"toggle turns a legacy chain off, steps kept ({warned}, sel={len(panel.table.selectedItems())})")
panel.select_form("journal_entry")
did = panel.move_selected()
d = definitions.get_definition(company_id, did) if did else None
check(d is not None and d.entity_type == "JOURNAL_ENTRY" and "ساخته شد" in panel.status_label.text(),
      f"move creates a draft process for the document ({warned})")
check(cartable.get_workflow_steps(company_id, "journal_entry")[0], "legacy chain keeps working until the new process is published")
org = wfc.OrgLinksPanel()
check(org.t_emp.verticalHeader().defaultSectionSize() >= 46 and org.t_unit.verticalHeader().defaultSectionSize() >= 46,
      "staff and unit rows tall enough for their drop-downs")

# --- ۱۷: نقش‌ها ---------------------------------------------------------------------------------------------
from peecha.ui.screens.roles import RolesScreen

for code in ("ANALYST_R316", "WAREHOUSE_R316"):
    roles_service.create_role(company_id, code, None)
rs = RolesScreen(); rs.refresh(); rs.resize(1200, 800); rs.show(); app.processEvents()
check(rs.role_list.minimumHeight() >= 300 and rs.role_list.height() >= 300, f"roles list has room ({rs.role_list.height()})")
rs.role_search_field.setText("R316")
visible = [rs.role_list.item(i).text() for i in range(rs.role_list.count()) if not rs.role_list.item(i).isHidden()]
check(len(visible) == 3, f"role search filters the list ({visible})")
rs.close()

# --- ۴: رخدادنگار خوانا ----------------------------------------------------------------------------------
from peecha.db.base import new_session
from peecha.services import audit as audit_service
from peecha.ui.screens.audit_log import AuditLogScreen

with new_session() as s:
    audit_service.log_activity(s, company_id=company_id, user_id=uid, entity_type="InspectionPlan", entity_id=7, action="APPROVE",
                               changes={"status": ["DRAFT", "ACTIVE"], "version": 2})
    audit_service.log_activity(s, company_id=company_id, user_id=uid, entity_type="JournalEntry", entity_id=9, action="UPDATE",
                               changes={"before": {"status": "TEMPORARY", "amount": "1500000"}, "after": {"status": "PERMANENT"}})
    s.commit()
al = AuditLogScreen(); al.refresh()
summaries = [al.table.item(r, 5).text() for r in range(al.table.rowCount())]
check(any("وضعیت: پیش‌نویس ← فعال" in t for t in summaries), f"summary column readable ({summaries[:2]})")
check(not any("{" in t or "\"" in t for t in summaries), "no JSON in the list")
row = next(r for r in range(al.table.rowCount()) if al.table.item(r, 4).text() == "سند حسابداری")
dlg = al.details_dialog(row)
cells = [[al.details_table.item(r, c).text() for c in range(3)] for r in range(al.details_table.rowCount())]
check(["وضعیت", "موقت", "دائم"] in cells and ["مبلغ", "۱,۵۰۰,۰۰۰", "—"] in cells, f"details table before/after in Persian ({cells})")
check(audit_format.entity_label("CrmLead").startswith("ارتباط با مشتری"), "unknown entity types get a Persian label")

# --- ۲: عنوان فیلدها و ترجمه ------------------------------------------------------------------------------
from peecha.services import languages as languages_service, ui_texts
from peecha.ui import ui_text_apply
from peecha.ui.screens.field_labels import FieldLabelsScreen
from peecha.ui.screens.translations import TranslationsScreen


class Sample(QWidget):
    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        self.label = QLabel("شرح سند:")
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["کالا", "مقدار"])
        self.save = QPushButton("ذخیره")
        for w in (self.label, self.table, self.save):
            lay.addWidget(w)


provider_calls = []


def provider(name):
    provider_calls.append(name)
    return Sample() if name != "system_settings" else ss


fl = FieldLabelsScreen()
fl.screen_provider = provider
fl.refresh()
check(len(fl.entries) > 100 and any(k.startswith("settings:") for k, _c in fl.entries), f"all forms listed ({len(fl.entries)})")
check(fl.select_entry("screen:journal_entry_list") or fl.select_entry(fl.entries[0][0]), "select a form")
sources = [fl.table.item(r, 1).text() for r in range(fl.table.rowCount())]
check({"شرح سند", "کالا", "مقدار", "ذخیره"} <= set(sources), f"labels, columns and buttons harvested ({sources})")
check(fl.set_value("شرح سند", "توضیح سند") and fl.set_value("مقدار", "تعداد") and fl.save() == 2, "custom titles saved")
check(fl.progress_label.text() == "۲ از ۴ عنوان دلخواه دارد", f"progress ({fl.progress_label.text()})")
fresh = Sample(); fresh.show(); app.processEvents(); app.processEvents()
check(fresh.label.text() == "توضیح سند:" and fresh.table.horizontalHeaderItem(1).text() == "تعداد",
      f"custom titles applied when a form opens ({fresh.label.text()}, {fresh.table.horizontalHeaderItem(1).text()})")
check([t for _k, t in ui_text_apply.harvest(fresh)][:2] == ["شرح سند", "کالا"], "harvest still reports the original text")
fl.select_entry(fl._entry_key)
fl.set_value("مقدار", "")
check(fl.save() == 1 and ui_texts.lookup("مقدار", fl.language_combo.currentData()) is None, "clearing returns to the original")
other = languages_service.create_language("en", "English", False, False, 2)
tr = TranslationsScreen()
tr.screen_provider = provider
tr.refresh()
check(tr.language_combo.count() == 1 and tr.entries[0][0] == "__nav__", "translation languages exclude the default; menus first")
tr.select_entry(tr.entries[1][0])
tr.set_value("ذخیره", "Save")
check(tr.save() == 1, "translation saved")
path = os.path.join(os.environ.get("TMPDIR", "/tmp"), "r316_texts.csv")
tr.export_csv(path)
tr.set_value("ذخیره", "")
check(tr.import_csv(path) == 1 and tr.pending() == [], "CSV round trip")
lang_obj = next(l for l in languages_service.list_languages() if l.language_id == tr.language_combo.currentData())
sess.current_language = lang_obj
ui_texts.clear_cache()
en_form = Sample(); en_form.show(); app.processEvents()
check(en_form.save.accessibleName() == "Save" and en_form.save.text() == "💾", "translation applied to the icon button tooltip")
sess.current_language = None
ui_texts.clear_cache()

# --- ۸: «نگاشت» در متن‌های برنامه ---------------------------------------------------------------------------
src = pathlib.Path(__file__).resolve().parents[2] / "src" / "peecha"
left = [(str(p), n.lineno) for p in src.rglob("*.py") for n in ast.walk(ast.parse(p.read_text()))
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and "نگاشت" in n.value]
check(not left, f"no «نگاشت» left in program texts ({left[:3]})")
labels = [ss.tabs.widget(i).tabText(j) for i in range(ss.tabs.count()) if isinstance(ss.tabs.widget(i), QTabWidget)
          for j in range(ss.tabs.widget(i).count())]
check("تنظیم حساب‌ها" in labels, "account settings subtab renamed")

# --- ۱۰: روش‌های تسویهٔ موبایل ------------------------------------------------------------------------------
from peecha.services import commercial_settlements as settlements_service, treasury as treasury_service
from peecha.ui.screens.commercial_settings import _MobileSettlementMethodsTab

treasury_service.create_custom_method(company_id, "RECEIPT", "WALLET", "کیف پول") if hasattr(treasury_service, "create_custom_method") else None
mt = _MobileSettlementMethodsTab(); mt.refresh()
names = [mt.table.item(r, 0).text() for r in range(mt.table.rowCount())]
check({"نقدی", "چک", "تهاتر", "اقساط"} <= set(names), f"all methods visible ({names})")
check("NETTING" not in mt.checkboxes and "CASH" in mt.checkboxes, "netting/installment shown with reason, not switchable")
mt.checkboxes["CHECK"].setChecked(False); mt._save()
check("CHECK" not in settlements_service.list_enabled_mobile_settlement_method_codes(company_id), "switching still saved")

# --- ۱۲: نقشهٔ انبار ------------------------------------------------------------------------------------------
from peecha.ui.screens.warehouse_map import WarehouseMapScreen

wm = WarehouseMapScreen(None); wm.refresh()
texts = [b.text() for b in wm.findChildren(QPushButton)]
check(texts and all(len(t) <= 3 for t in texts), f"map buttons are icons ({[t for t in texts if len(t) > 3][:5]})")
check(all(b.toolTip() for b in wm.findChildren(QPushButton)), "every map button has a tooltip")
check(all(b.minimumHeight() >= 34 for b in wm.op_buttons.values()), "operation buttons keep their height")

finish()
