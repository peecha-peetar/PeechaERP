"""R334: کلید مخفی Ctrl+Shift+F12 فقط برای مدیر سیستم: فایل پایتون فرم باز، بخش و خانهٔ زیر نشانگر و فایل‌های
منطق همان فرم را با شمارهٔ خط نشان می‌دهد؛ برای کاربر عادی هیچ اتفاقی نمی‌افتد."""
import inspect, os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r334"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prd_fixture import *  # noqa: F401,F403

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QMessageBox

app = QApplication.instance() or QApplication([])
QMessageBox.warning = staticmethod(lambda *a, **k: None)

from peecha.db.models.security import User
from peecha.services import users as users_service
from peecha.services.workflow import registry
from peecha.ui import form_locator
from peecha.ui.screens import workflow_studio as studio
from peecha.ui.shell_window import MainWindow

registry.ensure_loaded()


def key(k, mods):
    return QKeyEvent(QEvent.KeyPress, k, mods)


CS = Qt.ControlModifier | Qt.ShiftModifier
check(form_locator.is_hotkey(key(Qt.Key_F12, CS)), "Ctrl+Shift+F12 is the hidden key")
check(not form_locator.is_hotkey(key(Qt.Key_F12, Qt.ControlModifier)) and
      not form_locator.is_hotkey(key(Qt.Key_F12, CS | Qt.AltModifier)) and not form_locator.is_hotkey(key(Qt.Key_F11, CS)),
      "other combinations do nothing")
check(form_locator.allowed(), "the system admin may use it")

# --- فرم باز در پنجرهٔ اصلی ------------------------------------------------------------------------------------------
mw = MainWindow()
mw.resize(1300, 850)
mw.show()
app.processEvents()
mw.open_screen("WF_DESIGNER")
app.processEvents()
form = form_locator.current_form(mw)
check(isinstance(form, studio.DesignerScreen), f"the open screen is found ({type(form).__name__})")
places = form_locator.locate(form)
first = places[0]
check(first.role == "فرم" and first.path == "src/peecha/ui/screens/workflow_studio.py" and
      first.line == inspect.getsourcelines(studio.DesignerScreen)[1], f"the form's file and line ({first.location})")
check(any(p.role == "منطق" and p.name == "peecha.services.workflow.definitions" and
          p.path == "src/peecha/services/workflow/definitions.py" for p in places), "the form's logic files are listed")

# --- بخش و خانهٔ زیر نشانگر ----------------------------------------------------------------------------------------------
nid = form.add_node("APPROVAL")
app.processEvents()
editor = form.w["fields"]
cell = editor.table.viewport()
places = form_locator.locate(form, cell)
part = next((p for p in places if p.role == "بخش زیر نشانگر"), None)
check(part and part.name == "FieldsEditor" and part.line == inspect.getsourcelines(studio.FieldsEditor)[1],
      f"the part under the mouse is named with its line ({part and part.location})")
field = next((p for p in places if p.role == "خانهٔ زیر نشانگر"), None)
src = open(studio.__file__, encoding="utf-8").read().splitlines()
check(field and field.name == "FieldsEditor.table" and "self.table" in src[field.line - 1],
      f"the field under the mouse points to the line that builds it ({field and field.location})")
label = form.w["label"]
field = next((p for p in form_locator.locate(form, label) if p.role == "خانهٔ زیر نشانگر"), None)
check(field and field.name == "DesignerScreen.w['label']" and 'self._row("label"' in src[field.line - 1],
      f"fields kept in a dictionary are found too ({field and field.location})")

# --- دیالوگ باز و دیالوگ عمومی ---------------------------------------------------------------------------------------------
dlg = studio.FlowDialog(form)
dlg.show()
app.processEvents()
dlg.activateWindow()
places = form_locator.locate(dlg, dlg.name)
check(places[0].name == "FlowDialog" and places[0].path.endswith("workflow_studio.py"), "a dialog shows its own file")
check(any(p.role == "خانهٔ زیر نشانگر" and p.name == "FlowDialog.name" for p in places), "and the field under the mouse")
from peecha.ui.screens.fixed_assets import FormDialog

ask = FormDialog("پرسش", [], "", form)
places = form_locator.locate(ask)
check(any(p.role == "فرم بازکنندهٔ این پنجره" and p.name == "DesignerScreen" for p in places),
      "a general question box also names the form that opened it")
ask.close()
dlg.close()

# --- پنجرهٔ نتیجه ---------------------------------------------------------------------------------------------------------
shown = form_locator.FormLocatorDialog(form_locator.locate(form), "WF_DESIGNER")
check(shown.table.rowCount() >= 2 and [shown.table.item(0, c).text() for c in (2, 3)] ==
      ["workflow_studio.py", "src/peecha/ui/screens"] and shown.table.item(0, 4).text() == str(first.line),
      "the result window shows file name, folder and line")
check(shown.copy() == QApplication.clipboard().text() and ":" in shown.copy(), "the copy button copies file and line")
check("فرم: DesignerScreen" in shown.copy_all(), "copy all copies every row")
from PySide6.QtWidgets import QPushButton

buttons = shown.findChildren(QPushButton)
check(buttons and all(len(b.text()) <= 2 and b.toolTip() for b in buttons) and
      not any("باز" in b.toolTip() for b in buttons), "only copy buttons (icons with tooltips); nothing is opened")

# --- کلید از راه پنجرهٔ اصلی؛ کاربر عادی چیزی نمی‌بیند -----------------------------------------------------------------------
mw.activateWindow()
app.processEvents()
handled = mw.eventFilter(form, key(Qt.Key_F12, CS))
check(handled and isinstance(getattr(mw, "_form_locator_dialog", None), form_locator.FormLocatorDialog) and
      mw._form_locator_dialog.places[0].name == "DesignerScreen", "the key opens the window for the open form")
mw._form_locator_dialog.close()
plain = users_service.create_user("clerk", "کاربر عادی", "secret123", None, lang_id, False, [company_id], company_id).user_id
with new_session() as s:
    sess.current_user = s.get(User, plain)
    s.expunge_all()
mw._form_locator_dialog = None
check(not mw.eventFilter(form, key(Qt.Key_F12, CS)) and mw._form_locator_dialog is None,
      "for an ordinary user the key does nothing")

finish()
