"""R317: حداقل اندازهٔ معقول برای جدول‌ها و فهرست‌های کشویی — تا در صفحه‌های پر (داشبورد، تنظیمات)
هیچ جدولی به یکی‌دو ردیف له نشود و فهرست کشویی چند حرف بیشتر نشان دهد. فقط اندازهٔ حداقل؛ منطق دست نمی‌خورد."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QCalendarWidget, QComboBox, QHeaderView, QWidget

TABLE_MIN_HEIGHT = 120
COMBO_MIN_WIDTH = 96


def _inside(widget: QWidget, kinds) -> bool:
    p = widget.parentWidget()
    while p is not None:
        if isinstance(p, kinds):
            return True
        p = p.parentWidget()
    return False


def _in_popup(widget: QWidget) -> bool:
    window = widget.window()
    return window is not None and window.windowType() in (Qt.Popup, Qt.ToolTip)


def guard(widget: QWidget) -> None:
    if widget.property("layout_guarded"):
        return
    if isinstance(widget, QAbstractItemView) and not isinstance(widget, QHeaderView):
        widget.setProperty("layout_guarded", True)
        if widget.minimumHeight() == 0 and not _in_popup(widget) and not _inside(widget, (QComboBox, QCalendarWidget)):
            widget.setMinimumHeight(min(TABLE_MIN_HEIGHT, widget.maximumHeight()))
    elif isinstance(widget, QComboBox):
        widget.setProperty("layout_guarded", True)
        if widget.minimumWidth() == 0 and not _inside(widget, (QAbstractItemView,)):
            widget.setMinimumWidth(min(COMBO_MIN_WIDTH, widget.maximumWidth()))
