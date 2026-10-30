"""R317: حالت لمسی — برنامه روی صفحه‌های لمسی هم راحت کار کند.

- پیمایش با کشیدن انگشت (QScroller) در همهٔ جدول‌ها، فهرست‌ها و ناحیه‌های اسکرول‌شونده؛ ماوس دست نمی‌خورد.
- لمس طولانی = راست‌کلیک (منوی میان‌بر جدول‌ها و فیلدها) و روی دکمهٔ آیکونی، نمایش عنوانش.
- اندازهٔ بزرگ‌تر دکمه، فیلد، ردیف جدول، تیک و نوار اسکرول برای انگشت.
حالت «خودکار» با وجود صفحهٔ لمسی روشن می‌شود؛ کاربر می‌تواند آن را همیشه روشن یا خاموش کند."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPoint, QSettings, Qt, QTimer
from PySide6.QtGui import QContextMenuEvent, QInputDevice
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractItemView,
    QAbstractScrollArea,
    QApplication,
    QLineEdit,
    QPushButton,
    QScroller,
    QScrollerProperties,
    QTableView,
    QTapAndHoldGesture,
    QToolTip,
    QWidget,
)

_ORG, _APP, _KEY = "Peecha", "PeechaERP", "ui/touch_mode"
MODES = {"auto": "خودکار (اگر صفحهٔ لمسی باشد)", "on": "همیشه روشن", "off": "خاموش"}
ROW_HEIGHT = 44
_state = {"enabled": False}

TOUCH_QSS = """
/* R317: حالت لمسی */
QPushButton, QToolButton { min-height: 40px; }
QPushButton#iconButton, QPushButton#primaryIconButton, QPushButton#dangerIconButton { min-width: 48px; min-height: 42px; }
QLineEdit, QComboBox, QAbstractSpinBox, QDateEdit, QTimeEdit { min-height: 38px; }
QComboBox QAbstractItemView::item { min-height: 40px; }
QListView::item, QListWidget::item, QTreeView::item, QTreeWidget::item { min-height: 38px; }
QCheckBox::indicator, QRadioButton::indicator, QTableView::indicator, QTreeView::indicator, QListView::indicator {
    width: 24px; height: 24px;
}
QCheckBox, QRadioButton { min-height: 36px; spacing: 10px; }
QTabBar::tab { min-height: 40px; padding-left: 16px; padding-right: 16px; }
QMenu::item { padding: 10px 28px 10px 18px; }
QHeaderView::section { min-height: 34px; }
QScrollBar:vertical { width: 18px; }
QScrollBar:horizontal { height: 18px; }
QScrollBar::handle:vertical { min-height: 48px; }
QScrollBar::handle:horizontal { min-width: 48px; }
"""


def has_touchscreen() -> bool:
    try:
        return any(d.type() == QInputDevice.DeviceType.TouchScreen for d in QInputDevice.devices())
    except Exception:  # noqa: BLE001 -- نبود پشتیبانی سکو یعنی صفحهٔ لمسی تشخیص داده نشد
        return False


def saved_mode() -> str:
    value = QSettings(_ORG, _APP).value(_KEY, "auto")
    return value if value in MODES else "auto"


def save_mode(mode: str) -> None:
    QSettings(_ORG, _APP).setValue(_KEY, mode if mode in MODES else "auto")


def resolve(mode: str | None = None) -> bool:
    mode = mode or saved_mode()
    return mode == "on" or (mode == "auto" and has_touchscreen())


def is_enabled() -> bool:
    return _state["enabled"]


class _TouchFilter(QObject):
    """لمس طولانی روی ویجت‌های ثبت‌شده: راست‌کلیک یا نمایش عنوان دکمه."""

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 — نام متد Qt
        if event.type() != QEvent.Gesture or not _state["enabled"]:
            return False
        gesture = event.gesture(Qt.TapAndHoldGesture)
        if gesture is None or gesture.state() != Qt.GestureFinished:
            return False
        long_press(obj, obj.mapFromGlobal(gesture.position().toPoint()))
        event.accept()
        return True


_FILTER = _TouchFilter()


def long_press(widget: QWidget, pos: QPoint) -> None:
    """رفتار لمس طولانی: دکمه ← عنوانش؛ بقیه ← همان راست‌کلیک."""
    if isinstance(widget, QAbstractButton):
        label = widget.toolTip() or widget.accessibleName()
        if label:
            QToolTip.showText(widget.mapToGlobal(pos), label, widget)
        return
    if widget.contextMenuPolicy() in (Qt.NoContextMenu, Qt.PreventContextMenu):
        return
    menu_event = QContextMenuEvent(QContextMenuEvent.Mouse, pos, widget.mapToGlobal(pos))
    QApplication.sendEvent(widget, menu_event)


def _scroller_target(widget: QWidget):
    if isinstance(widget, QAbstractScrollArea):
        return widget.viewport()
    return None


def prepare(widget: QWidget) -> None:
    """هنگام polish هر ویجت (app_style) صدا زده می‌شود."""
    if not _state["enabled"] or widget.property("touch_ready"):
        return
    target = _scroller_target(widget)
    if target is not None or isinstance(widget, (QLineEdit, QPushButton)):
        widget.setProperty("touch_ready", True)
    if target is not None:
        QScroller.grabGesture(target, QScroller.TouchGesture)
        scroller = QScroller.scroller(target)
        props = scroller.scrollerProperties()
        props.setScrollMetric(QScrollerProperties.OvershootDragResistanceFactor, 0.3)
        props.setScrollMetric(QScrollerProperties.OvershootScrollDistanceFactor, 0.1)
        props.setScrollMetric(QScrollerProperties.DragStartDistance, 0.004)
        scroller.setScrollerProperties(props)
        if isinstance(widget, QAbstractItemView):
            widget.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
            widget.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
            _grab_long_press(target)
        if isinstance(widget, QTableView):
            header = widget.verticalHeader()
            if header.defaultSectionSize() < ROW_HEIGHT:
                header.setDefaultSectionSize(ROW_HEIGHT)
    elif isinstance(widget, (QLineEdit, QPushButton)):
        _grab_long_press(widget)


def _grab_long_press(widget: QWidget) -> None:
    widget.grabGesture(Qt.TapAndHoldGesture)
    widget.installEventFilter(_FILTER)


def _ungrab(widget: QWidget) -> None:
    target = _scroller_target(widget)
    if target is not None:
        QScroller.ungrabGesture(target)
        target.ungrabGesture(Qt.TapAndHoldGesture)
    widget.ungrabGesture(Qt.TapAndHoldGesture)
    widget.setProperty("touch_ready", None)


def apply(app, enabled: bool) -> None:
    """روشن/خاموش کردن زنده؛ استایل‌شیت دوباره ساخته و همهٔ ویجت‌های باز به‌روز می‌شوند."""
    from peecha.ui import theme

    _state["enabled"] = bool(enabled)
    QTapAndHoldGesture.setTimeout(650)
    theme.TOUCH_QSS = TOUCH_QSS if enabled else ""
    theme.set_theme_mode(app, theme.is_dark_mode())
    for widget in app.allWidgets():
        if enabled:
            prepare(widget)
        elif widget.property("touch_ready"):
            _ungrab(widget)


def install(app) -> bool:
    """در ui.main پس از تم صدا زده می‌شود؛ خروجی: حالت لمسی روشن شد یا نه."""
    enabled = resolve()
    if enabled:
        # بعد از ساخت اولیه، تا تشخیص دستگاه و تم آماده باشد
        QTimer.singleShot(0, lambda: apply(app, True))
        _state["enabled"] = True
    return enabled
