import os, sys, re, ast, pathlib
os.environ["PEECHA_DB_NAME"] = "peecha_test_r277"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (QApplication, QDialog, QDoubleSpinBox, QFormLayout, QLineEdit, QMainWindow, QMdiArea,
                               QVBoxLayout, QWidget, QComboBox)
app = QApplication.instance() or QApplication([])
from prd_fixture import *  # noqa: F401,F403
import prd_fixture as fx
from sqlalchemy import text
from peecha import nav_catalog
from peecha.ui import field_help_glossary as glossary
from peecha.ui.widgets import (FieldGrid, FieldHelpMixin, FieldHelpPanel, FieldSpec, JalaliDateEdit, resolve_field_help,
                               FIELD_HELP_PROPERTY)
check = fx.check
SRC = pathlib.Path(__file__).resolve().parents[2] / "src" / "peecha"

# ۱) نگارش: متن‌های برنامه بدون کسرهٔ اضافه، واژه‌های فارسی به‌جای انگلیسی
kasra = []
for p in SRC.rglob("*.py"):
    for node in ast.walk(ast.parse(p.read_text())):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and chr(0x650) in node.value and node.value != chr(0x650):
            kasra.append(f"{p.name}:{node.lineno}")
check(not kasra, f"no ezafe kasra left in UI strings {kasra[:5]}")
labels = [i["label"] for i in nav_catalog.flatten_nav_items()]
check("سنی‌بندی مطالبات" in labels and "سابقهٔ تغییرات اسناد خرید" in labels, "menu uses plain Persian terms")
check(not [l for l in labels if re.search(r"ریبیت|Aging|Audit|Feature|Dead Stock|\(BOM", l)], "no English/transliterated terms in menu")
check("گروه کالا" in " ".join(labels) and "گروهٔ" not in " ".join(labels), "no hamza on words ending with pronounced h")
with new_session() as s:
    names = s.execute(text("SELECT name FROM inv.feature_definitions UNION ALL SELECT name FROM comm.feature_definitions")).scalars().all()
check(names and not [n for n in names if chr(0x650) in n or "ریبیت" in n], "seeded feature names normalized by migration")

# ۲) راهنمای فیلد: دو صفحه در MDI + دیالوگ؛ فقط با کلیک/کلید کاربر باز می‌شود
class Screen(FieldHelpMixin, QWidget):
    def __init__(self, tag):
        super().__init__()
        self.a, self.code, self.combo, self.amount, self.date = QLineEdit(), QLineEdit(), QComboBox(), QDoubleSpinBox(), JalaliDateEdit()
        self.combo.setEditable(True)
        QVBoxLayout(self).addWidget(FieldGrid([FieldSpec("a", "الف", self.a), FieldSpec("c", "کد", self.code),
                                               FieldSpec("b", "انتخاب", self.combo), FieldSpec("m", "مبلغ", self.amount),
                                               FieldSpec("d", "تاریخ سند", self.date)]))
        self.set_field_help([(self.a, f"a-{tag}")])
        self.set_field_help([(self.combo, f"combo-{tag}")])  # فراخوانی دوم جایگزین اولی نمی‌شود

win = QMainWindow(); mdi = QMdiArea(); win.setCentralWidget(mdi); win.resize(1200, 800)
s1, s2 = Screen(1), Screen(2)
mdi.addSubWindow(s1).show(); mdi.addSubWindow(s2).show(); win.show(); app.processEvents()

def click(w):
    QTest.mouseClick(w, Qt.LeftButton); app.processEvents(); app.processEvents()

def shown():
    p = FieldHelpPanel._instance
    return (p.title_label.text(), p.text_label.text(), p.parentWidget()) if p is not None and p.isVisible() else None

s1.a.setFocus(); app.processEvents(); app.processEvents()
check(shown() is None, "programmatic focus does not pop the help")
click(s2.a)
check(shown() == ("الف", "a-2", win), f"help in second MDI screen {shown()}")
click(s1.combo.lineEdit())
check(shown() and shown()[1] == "combo-1", "help of inner line edit of an editable combo, second set_field_help call")
click(s1.code)
check(shown() and shown()[1] == glossary.GLOSSARY["کد"], "glossary fallback by FieldGrid label")
click(s2.amount)
check(shown() and shown()[0] == "مبلغ", "glossary fallback for spin box")
click(s2.date)
check(shown() and "دورهٔ مالی" in shown()[1], "glossary fallback for date field")
dlg = QDialog(win); form = QFormLayout(dlg); cust = QLineEdit(); form.addRow("مشتری:", cust); dlg.show(); app.processEvents()
click(cust)
check(shown() and shown()[2] is dlg and shown()[0] == "مشتری", "help works inside dialogs (form layout label)")
dlg.close(); dlg.deleteLater(); app.processEvents()
check(glossary.lookup("پیشوند فاکتور فروش").startswith("متنی که پیش از شمارهٔ فاکتور فروش"), "glossary patterns")
check(resolve_field_help(QLineEdit()) is None, "unlabeled free field without help shows nothing")

# ۳) صفحهٔ واقعی تنظیمات سیستم: تقریباً همهٔ فیلدها راهنما دارند
from peecha.ui.screens.system_settings import SystemSettingsScreen
settings = SystemSettingsScreen()
settings.ensure_all_built()  # R301: زیرتب‌ها تنبل ساخته می‌شوند
inputs = [w for w in settings.findChildren(QWidget) if isinstance(w, (QLineEdit, QComboBox, QDoubleSpinBox))
          and not isinstance(w.parentWidget(), (QComboBox, QDoubleSpinBox)) and not (isinstance(w, QLineEdit) and w.isReadOnly())]
covered = sum(1 for w in inputs if resolve_field_help(w))
check(inputs and covered / len(inputs) >= 0.9, f"system settings field help coverage {covered}/{len(inputs)}")

fx.finish()
