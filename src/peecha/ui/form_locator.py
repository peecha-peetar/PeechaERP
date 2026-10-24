"""R334: کلید مخفی Ctrl+Shift+F12 (فقط مدیر سیستم): نام و پوشهٔ فایل پایتون فرمی که باز است، بخشی که نشانگر ماوس
روی آن است و فایل‌های منطق (سرویس) همان فرم را با شمارهٔ خط نشان می‌دهد؛ چیزی را باز نمی‌کند."""

from __future__ import annotations

import inspect
import os
import re
import types
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QDialog, QHBoxLayout, QHeaderView, QLabel, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from peecha import session

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
HOTKEY_TEXT = "Ctrl+Shift+F12"


@dataclass
class Place:
    role: str  # فرم | بخش زیر نشانگر | خانهٔ زیر نشانگر | منطق
    name: str
    path: str  # نسبت به ریشهٔ پروژه
    line: int | None
    abs_path: str

    @property
    def location(self) -> str:
        return f"{self.path}:{self.line}" if self.line else self.path

    @property
    def file_name(self) -> str:
        return self.path.rsplit("/", 1)[-1]

    @property
    def folder(self) -> str:
        return self.path.rsplit("/", 1)[0] if "/" in self.path else ""


def is_hotkey(event) -> bool:
    mods = event.modifiers() & (Qt.ControlModifier | Qt.ShiftModifier | Qt.AltModifier | Qt.MetaModifier)
    return event.key() == Qt.Key_F12 and mods == (Qt.ControlModifier | Qt.ShiftModifier) and not event.isAutoRepeat()


def allowed() -> bool:
    return bool(getattr(session.current_user, "is_super_admin", False))


def _own_class(obj) -> type | None:
    """نخستین کلاس خود برنامه (نه کلاس Qt) در زنجیرهٔ ارث‌بری."""
    return next((c for c in type(obj).__mro__ if c.__module__.startswith("peecha.")), None)


def _place(role: str, obj, name: str | None = None, line: int | None = None) -> Place | None:
    try:
        path = inspect.getsourcefile(obj)
        if line is None and inspect.isclass(obj):
            line = inspect.getsourcelines(obj)[1]
    except (OSError, TypeError):
        return None
    if not path:
        return None
    rel = os.path.relpath(path, PROJECT_ROOT).replace(os.sep, "/")
    return Place(role, name or getattr(obj, "__qualname__", getattr(obj, "__name__", "")), rel, line, path)


def _attribute_line(cls: type, attr: str, key=None) -> int | None:
    """خطی که خانه ساخته می‌شود: «self.<attr> = …»، یا برای خانهٔ داخل دیکشنری، جایی که کلیدش داده می‌شود."""
    try:
        lines, start = inspect.getsourcelines(cls)
    except (OSError, TypeError):
        return None
    patterns = [rf"\(\s*[\"']{re.escape(key)}[\"']\s*,", rf"self\.{re.escape(attr)}\[\s*[\"']{re.escape(key)}[\"']\s*\]\s*=(?!=)"] \
        if isinstance(key, str) else []
    patterns.append(rf"self\.{re.escape(attr)}\b[^=\n]*=(?!=)")
    for pattern in map(re.compile, patterns):
        found = next((start + i for i, text in enumerate(lines) if pattern.search(text)), None)
        if found:
            return found
    return None


def _attribute_of(owner, widget) -> tuple[str, object] | None:
    """(نام ویژگی، کلید دیکشنری) در owner که همین ویجت است؛ مستقیم یا داخل دیکشنری‌ای مثل self.buttons."""
    try:
        items = list(vars(owner).items())
    except TypeError:
        return None
    for key, value in items:
        if value is widget:
            return key, None
        if isinstance(value, dict):
            inner = next((k for k, v in value.items() if v is widget), None)
            if inner is not None:
                return key, inner
    return None


def _holder(target: QWidget, form: QWidget) -> tuple[type, tuple[str, object]] | None:
    owner = target.parentWidget()
    while owner is not None:
        owner_cls = _own_class(owner)
        attr = _attribute_of(owner, target) if owner_cls is not None else None
        if attr:
            return owner_cls, attr
        if owner is form:
            return None
        owner = owner.parentWidget()
    return None


def locate(form: QWidget, under_cursor: QWidget | None = None) -> list[Place]:
    out: list[Place] = []
    form_cls = _own_class(form)
    if form_cls is not None:
        p = _place("فرم", form_cls)
        if p:
            out.append(p)
    if isinstance(form, QDialog):  # دیالوگ‌های عمومی (مثل فرم کوچک پرسش) را فرم بازکننده می‌سازد
        opener = form.parentWidget()
        while opener is not None and _own_class(opener) is None:
            opener = opener.parentWidget()
        p = _place("فرم بازکنندهٔ این پنجره", _own_class(opener)) if opener is not None else None
        if p and _own_class(opener) is not form_cls:
            out.append(p)
    seen = {form_cls}
    chain = []
    widget = under_cursor
    while widget is not None and widget is not form:
        chain.append(widget)
        widget = widget.parentWidget()
    for widget in chain:
        cls = _own_class(widget)
        if cls is not None and cls not in seen:
            seen.add(cls)
            p = _place("بخش زیر نشانگر", cls)
            if p:
                out.append(p)
    for target in chain:  # نزدیک‌ترین خانه‌ای که در کد با نام نگه داشته شده (self.name یا self.w["…"])
        hit = _holder(target, form)
        if hit:
            owner_cls, (attr, key) = hit
            name = f"{owner_cls.__qualname__}.{attr}" + (f"[{key!r}]" if key is not None else "")
            p = _place("خانهٔ زیر نشانگر", owner_cls, name, _attribute_line(owner_cls, attr, key))
            if p:
                out.append(p)
            break
    module = inspect.getmodule(form_cls) if form_cls is not None else None
    logic: dict[str, types.ModuleType] = {}
    for value in vars(module).values() if module else ():
        mod = value if isinstance(value, types.ModuleType) else inspect.getmodule(value)
        if mod is not None and mod.__name__.startswith("peecha.services"):
            logic.setdefault(mod.__name__, mod)
    for name in sorted(logic):
        p = _place("منطق", logic[name], name)
        if p:
            out.append(p)
    return out


def current_form(main_window) -> QWidget:
    """فرمی که کاربر می‌بیند: دیالوگ باز، وگرنه صفحهٔ زیرپنجرهٔ فعال."""
    active = QApplication.activeModalWidget() or QApplication.activeWindow()
    if active is not None and active is not main_window:
        return active
    sub = main_window.mdi_area.activeSubWindow() if hasattr(main_window, "mdi_area") else None
    screens = getattr(main_window, "_screens", {})
    return screens.get(getattr(sub, "_screen_name", None)) or main_window


def _icon(glyph: str, tip: str, slot) -> QPushButton:
    b = QPushButton(glyph)
    b.setObjectName("iconButton")
    b.setToolTip(tip)
    b.setFixedWidth(44)
    b.setCursor(Qt.PointingHandCursor)
    b.clicked.connect(lambda _c=False: slot())
    return b


class FormLocatorDialog(QDialog):
    def __init__(self, places: list[Place], screen_code: str | None = None, parent=None) -> None:
        super().__init__(parent)
        self.places = places
        self.setWindowTitle("جای این فرم در کد")
        self.setLayoutDirection(Qt.RightToLeft)
        self.resize(820, 360)
        layout = QVBoxLayout(self)
        hint = QLabel("این فایل‌ها را اصلاح کنید؛ تغییر پس از بستن و باز کردن دوبارهٔ برنامه دیده می‌شود. «منطق» "
                      "یعنی حساب‌وکتاب و ثبت؛ ظاهر فرم در فایل «فرم» است." +
                      (f"  کد صفحه در منو: {screen_code}" if screen_code else ""))
        hint.setWordWrap(True)
        hint.setObjectName("sectionHint")
        layout.addWidget(hint)
        self.table = QTableWidget(len(places), 5)
        self.table.setHorizontalHeaderLabels(["بخش", "نام در کد", "نام فایل", "پوشه", "خط"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        for r, p in enumerate(places):
            for c, text in enumerate((p.role, p.name, p.file_name, p.folder, str(p.line or ""))):
                item = QTableWidgetItem(text)
                if c:
                    item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)  # مسیر لاتین چپ‌چین خواناتر است
                self.table.setItem(r, c, item)
        self.table.resizeColumnsToContents()
        if places:
            self.table.selectRow(0)
        self.table.cellDoubleClicked.connect(lambda _r, _c: self.copy())
        layout.addWidget(self.table, stretch=1)
        row = QHBoxLayout()
        row.addWidget(_icon("📋", "کپی پوشه، نام فایل و شمارهٔ خط ردیف انتخاب‌شده", self.copy))
        row.addWidget(_icon("📑", "کپی همهٔ ردیف‌ها", self.copy_all))
        row.addStretch(1)
        layout.addLayout(row)

    def selected(self) -> Place | None:
        rows = self.table.selectionModel().selectedRows()
        return self.places[rows[0].row()] if rows else (self.places[0] if self.places else None)

    def copy(self) -> str:
        p = self.selected()
        text = p.location if p else ""
        QApplication.clipboard().setText(text)
        return text

    def copy_all(self) -> str:
        text = "\n".join(f"{p.role}: {p.name} — {p.location}" for p in self.places)
        QApplication.clipboard().setText(text)
        return text


def show_for(main_window) -> FormLocatorDialog:
    form = current_form(main_window)
    under = QApplication.widgetAt(QCursor.pos())
    if under is not None and under is not form and not form.isAncestorOf(under):
        under = None
    is_screen = form is not main_window and form.window() is main_window
    code = getattr(main_window, "_current_screen_code", None) if is_screen else None
    dlg = FormLocatorDialog(locate(form, under), code, main_window)
    dlg.show()
    return dlg
