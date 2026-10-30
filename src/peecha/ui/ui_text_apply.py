"""R316: اعمال عنوان دلخواه/ترجمهٔ متن‌ها روی ویجت‌ها، و برداشت متن‌های یک فرم برای صفحهٔ «عنوان فیلدها».

اعمال یک‌بار هنگام polish هر ویجت انجام می‌شود (app_style)؛ نام زبانه‌ها عمداً عوض نمی‌شود
چون برنامه با نام زبانه دسترسی زیرتب‌های تنظیمات را پیدا می‌کند."""

from __future__ import annotations

import re

from PySide6.QtCore import QObject, Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractButton,
    QCheckBox,
    QGroupBox,
    QHeaderView,
    QLabel,
    QPushButton,
    QRadioButton,
    QTableWidget,
    QTreeWidget,
    QWidget,
)

from peecha.services import ui_texts

_LETTERS = re.compile(r"[A-Za-z؀-ۿ]{2,}")
_TAG = re.compile(r"<[A-Za-z/!][^>]*>")
_SOURCE_ROLE = Qt.UserRole + 77
KIND_LABEL, KIND_OPTION, KIND_SECTION, KIND_BUTTON, KIND_COLUMN = "برچسب", "گزینه", "عنوان بخش", "دکمه", "سرستون"


def _language() -> int | None:
    try:
        return ui_texts.active_language_id()
    except Exception:  # noqa: BLE001 -- پیش از اتصال پایگاه داده (صفحهٔ ورود) چیزی عوض نمی‌شود
        return None


def _has_overrides(language_id) -> bool:
    try:
        return bool(ui_texts.overrides(language_id))
    except Exception:  # noqa: BLE001
        return False


def _replace(text: str, language_id) -> str | None:
    if not text or not _LETTERS.search(text) or _TAG.search(text):
        return None
    return ui_texts.lookup(text, language_id)


def _apply_headers(view, language_id) -> None:
    if view.property("ui_text_busy"):
        return
    view.setProperty("ui_text_busy", True)
    try:
        if isinstance(view, QTableWidget):
            for col in range(view.columnCount()):
                item = view.horizontalHeaderItem(col)
                new = _replace(item.text(), language_id) if item is not None else None
                if new and new != item.text():
                    item.setData(_SOURCE_ROLE, item.text())
                    item.setText(new)
        elif isinstance(view, QTreeWidget):
            head = view.headerItem()
            for col in range(view.columnCount()):
                new = _replace(head.text(col), language_id)
                if new and new != head.text(col):
                    head.setData(col, _SOURCE_ROLE, head.text(col))
                    head.setText(col, new)
    finally:
        view.setProperty("ui_text_busy", False)


def apply(widget: QWidget) -> None:
    """عنوان دلخواه زبان فعال را روی همین ویجت می‌گذارد (اگر برای متنش تعریف شده باشد).
    هرگز خطا بیرون نمی‌دهد: این تابع داخل polish اجرا می‌شود."""
    try:
        _apply(widget)
    except Exception:  # noqa: BLE001
        return



def _apply(widget: QWidget) -> None:
    language_id = _language()
    if language_id is None or not _has_overrides(language_id):
        return
    if isinstance(widget, QLabel):
        new = _replace(widget.text(), language_id)
        if new:
            widget.setProperty("ui_source", widget.text())
            widget.setText(new)
    elif isinstance(widget, QPushButton) and widget.property("label"):
        label = widget.property("label")
        new = _replace(label, language_id)
        if new:
            tip = widget.toolTip()
            widget.setToolTip(new + tip[len(label):] if tip.startswith(label) else new)
            widget.setAccessibleName(new)
    elif isinstance(widget, QAbstractButton):
        new = _replace(widget.text(), language_id)
        if new:
            widget.setProperty("ui_source", widget.text())
            widget.setText(new)
    elif isinstance(widget, QGroupBox):
        new = _replace(widget.title(), language_id)
        if new:
            widget.setProperty("ui_source", widget.title())
            widget.setTitle(new)
    elif isinstance(widget, QHeaderView) and widget.orientation() == Qt.Horizontal and not widget.property("ui_text_hook"):
        # سرستون وسط ساخت جدول polish می‌شود؛ اتصال بعد از ساخت، با یک شیء فرزند سرستون (بدون نگه‌داشتن ارجاع پایتونی)
        widget.setProperty("ui_text_hook", True)
        _HeaderHook(widget, language_id)


class _HeaderHook(QObject):
    def __init__(self, header, language_id) -> None:
        super().__init__(header)
        self.language_id = language_id
        QTimer.singleShot(0, self, self.attach)

    def _view(self):
        header = self.parent()
        view = header.parentWidget() if header is not None else None
        return view if isinstance(view, (QTableWidget, QTreeWidget)) else None

    def attach(self) -> None:
        view = self._view()
        if view is None:
            return
        _apply_headers(view, self.language_id)
        view.model().headerDataChanged.connect(self.reapply)
        view.model().columnsInserted.connect(self.reapply)

    def reapply(self, *_args) -> None:
        view = self._view()
        if view is not None:
            _apply_headers(view, self.language_id)


def _build_lazy(root: QWidget) -> None:
    for holder in root.findChildren(QWidget):
        if type(holder).__name__ == "_LazyPage" and callable(getattr(holder, "page", None)):
            try:
                holder.page()
            except Exception:  # noqa: BLE001 -- زیرتبی که ساخته نشد فقط از فهرست جا می‌ماند
                continue


def harvest(root: QWidget) -> list[tuple[str, str]]:
    """(نوع، متن اصلی) همهٔ عنوان‌های یک فرم، بی‌تکرار و به ترتیب ظاهرشدن."""
    _build_lazy(root)
    seen: set[str] = set()
    out: list[tuple[str, str]] = []

    def add(kind: str, text) -> None:
        text = ui_texts.normalize(text if isinstance(text, str) else "")
        if not text or len(text) > 120 or not _LETTERS.search(text) or _TAG.search(text) or text in seen:
            return
        seen.add(text)
        out.append((kind, text))

    for w in [root] + root.findChildren(QWidget):
        source = w.property("ui_source")
        if isinstance(w, QLabel):
            add(KIND_LABEL, source or w.text())
        elif isinstance(w, (QCheckBox, QRadioButton)):
            add(KIND_OPTION, source or w.text())
        elif isinstance(w, QGroupBox):
            add(KIND_SECTION, source or w.title())
        elif isinstance(w, QPushButton):
            add(KIND_BUTTON, w.property("label") or source or w.text())
        elif isinstance(w, QTableWidget):
            for col in range(w.columnCount()):
                item = w.horizontalHeaderItem(col)
                if item is not None:
                    add(KIND_COLUMN, item.data(_SOURCE_ROLE) or item.text())
        elif isinstance(w, QTreeWidget):
            for col in range(w.columnCount()):
                add(KIND_COLUMN, w.headerItem().data(col, _SOURCE_ROLE) or w.headerItem().text(col))
    return out
