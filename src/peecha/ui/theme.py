"""پالتِ رنگی + QSSِ سراسریِ برنامه («آئورا») — طراحیِ مدرن، تخت، با
کارت‌هایِ سایه‌دار، فیلدهایِ گردِ fill-style، و دکمه‌هایِ pill."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QWidget

PRIMARY = "#14173A"
PRIMARY_HOVER = "#1F234E"
PRIMARY_LIGHT = "#EEECFC"
ACCENT = "#6D5CE6"
ACCENT_HOVER = "#5B4CD6"
ACCENT_PRESSED = "#4C3DC4"
SUCCESS = "#15A672"
WARNING = "#F5A524"
DANGER = "#E5484D"
INFO = "#0EA5E9"

CHART_PURPLE = "#9333EA"
CHART_ORANGE = "#F97316"
CHART_TEAL = "#14B8A6"

BACKGROUND = "#F3F2FA"
SURFACE = "#FFFFFF"
HOVER = "#F4F3FA"
SELECTED = "#EEECFC"
BORDER = "#E6E4F0"
DIVIDER = "#ECEAF3"

TEXT_PRIMARY = "#18162B"
TEXT_SECONDARY = "#6B6B85"
TEXT_DISABLED = "#A3A2B8"

GRID_HEADER_BG = "#F7F6FC"
GRID_BORDER = "#EDEBF7"
GRID_ROW_ALT = "#FBFAFE"
LEVEL_GROUP = "#4C1D95"
LEVEL_KOL = "#0F766E"
LEVEL_MOEIN = TEXT_PRIMARY

STATUS_COLOR_ROLE: dict[str, str] = {
    "TEMPORARY": "warning",
    "PERMANENT": "success",
    "REVERSED": "danger",
    "CANCELLED": "danger",
    "PENDING": "warning",
    "APPROVED": "success",
    "REJECTED": "danger",
}

_ROLE_COLORS = {
    "success": SUCCESS,
    "warning": WARNING,
    "danger": DANGER,
    "info": INFO,
}


def status_color(status_code: str) -> str:
    role = STATUS_COLOR_ROLE.get(status_code, "info")
    return _ROLE_COLORS[role]


DONUT_COLORS = [ACCENT, SUCCESS, CHART_PURPLE, CHART_ORANGE, WARNING]

# رنگ‌های چرخشیِ آواتار/نشان — برایِ حروفِ اول (کاربر/گروه/...)
AVATAR_COLORS = [ACCENT, SUCCESS, CHART_ORANGE, INFO, CHART_PURPLE, CHART_TEAL]


def apply_card_shadows(root: QWidget) -> None:
    """سایه‌ی ملایمِ زیرِ هر ویجتِ «کارت» (objectName == "card") را — رویِ
    خودِ آن ویجت و همه‌ی فرزندانش — اعمال می‌کند. یک نقطه‌ی مرکزی (به‌جایِ
    تکرار در هر صفحه) که با هر صفحه‌ی تازه‌ای که ساخته می‌شود صدا زده
    می‌شود (در shell_window.register_screen)."""
    candidates = [root, *root.findChildren(QWidget)]
    for widget in candidates:
        if widget.objectName() != "card":
            continue
        effect = QGraphicsDropShadowEffect(widget)
        effect.setBlurRadius(28)
        effect.setXOffset(0)
        effect.setYOffset(6)
        effect.setColor(QColor(20, 23, 58, 28))
        widget.setGraphicsEffect(effect)


def avatar_color_for(text: str) -> str:
    if not text:
        return ACCENT
    return AVATAR_COLORS[sum(ord(ch) for ch in text) % len(AVATAR_COLORS)]


def emoji_icon(glyph: str, size: int = 22) -> QIcon:
    """رندرِ یک ایموجی/گلیف به QIcon — بدونِ نیازِ به فایلِ آیکونِ خارجی؛
    برایِ نوارِ کناری در حالتِ جمع‌شده (فقط-آیکون) استفاده می‌شود."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    font = painter.font()
    font.setPixelSize(int(size * 0.72))
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, glyph)
    painter.end()
    return QIcon(pixmap)


GLOBAL_QSS = f"""
* {{
    outline: none;
}}
QWidget {{
    background-color: {BACKGROUND};
    color: {TEXT_PRIMARY};
    font-size: 13px;
}}
QWidget#card, QFrame#card {{
    background-color: {SURFACE};
    border-radius: 18px;
    border: 1px solid {DIVIDER};
}}
QLabel#pageTitle {{
    font-size: 23px;
    font-weight: 700;
    color: {TEXT_PRIMARY};
}}
QLabel#sectionHint {{
    color: {TEXT_SECONDARY};
    font-size: 12px;
}}
QLabel#statusError {{
    color: {DANGER};
    font-weight: 600;
}}
QLabel#statusOk {{
    color: {SUCCESS};
    font-weight: 600;
}}
QLabel#avatarBadge {{
    background-color: {ACCENT};
    color: white;
    font-weight: 700;
    border-radius: 16px;
}}

/* --- فیلدهایِ ورودی -------------------------------------------------- */
QLineEdit, QComboBox, QDateEdit, QSpinBox, QDoubleSpinBox {{
    background-color: {HOVER};
    border: 1.5px solid {BORDER};
    border-radius: 11px;
    padding: 9px 14px;
    font-size: 13px;
    color: {TEXT_PRIMARY};
    selection-background-color: {ACCENT};
}}
QLineEdit:hover, QComboBox:hover, QDateEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover {{
    border: 1.5px solid {TEXT_SECONDARY};
}}
QLineEdit:focus, QComboBox:focus, QDateEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
    border: 1.5px solid {ACCENT};
    background-color: {SURFACE};
}}
QLineEdit:disabled, QComboBox:disabled {{
    color: {TEXT_DISABLED};
}}
QComboBox::drop-down {{
    border: none;
    width: 26px;
}}
QComboBox QAbstractItemView {{
    background-color: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 10px;
    padding: 4px;
    selection-background-color: {SELECTED};
    selection-color: {TEXT_PRIMARY};
    outline: none;
}}
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
    width: 18px;
    border: none;
}}
QDateEdit::drop-down {{
    border: none;
    width: 24px;
}}
QCalendarWidget QWidget {{
    background-color: {SURFACE};
}}
QCalendarWidget QToolButton {{
    color: {TEXT_PRIMARY};
    background-color: transparent;
}}
QCalendarWidget QAbstractItemView:enabled {{
    selection-background-color: {ACCENT};
    selection-color: white;
}}

/* --- دکمه‌ها ----------------------------------------------------------- */
QPushButton {{
    border-radius: 18px;
    padding: 9px 20px;
    font-size: 13px;
    font-weight: 600;
    border: none;
}}
QPushButton#primaryButton {{
    background-color: {ACCENT};
    color: white;
}}
QPushButton#primaryButton:hover {{
    background-color: {ACCENT_HOVER};
}}
QPushButton#primaryButton:pressed {{
    background-color: {ACCENT_PRESSED};
}}
QPushButton#flatButton {{
    background-color: transparent;
    color: {ACCENT};
    font-weight: 600;
}}
QPushButton#flatButton:hover {{
    background-color: {SELECTED};
}}
QPushButton#dangerButton {{
    background-color: transparent;
    color: {DANGER};
    font-weight: 600;
}}
QPushButton#dangerButton:hover {{
    background-color: #FDEBEC;
}}

/* --- جدول‌ها ------------------------------------------------------------ */
QTableWidget {{
    background-color: {SURFACE};
    border: none;
    gridline-color: {GRID_BORDER};
    font-size: 13px;
    selection-background-color: {SELECTED};
    selection-color: {TEXT_PRIMARY};
    alternate-background-color: {GRID_ROW_ALT};
}}
QTableWidget::item {{
    padding: 6px 4px;
    border-bottom: 1px solid {GRID_BORDER};
}}
QTableWidget::item:selected {{
    background-color: {SELECTED};
    color: {TEXT_PRIMARY};
}}
QHeaderView::section {{
    background-color: {GRID_HEADER_BG};
    color: {TEXT_SECONDARY};
    padding: 10px 8px;
    border: none;
    border-bottom: 2px solid {GRID_BORDER};
    font-weight: 700;
    font-size: 12px;
}}
QTableCornerButton::section {{
    background-color: {GRID_HEADER_BG};
    border: none;
}}

/* --- تب/لیست ------------------------------------------------------------ */
QTabWidget::pane {{
    border: 1px solid {DIVIDER};
    border-radius: 12px;
    top: 4px;
}}
QTabBar::tab {{
    background-color: {HOVER};
    color: {TEXT_SECONDARY};
    padding: 8px 18px;
    margin-left: 4px;
    border-top-left-radius: 10px;
    border-top-right-radius: 10px;
    font-weight: 600;
}}
QTabBar::tab:selected {{
    background-color: {ACCENT};
    color: white;
}}
QListWidget {{
    background-color: {SURFACE};
    border: 1px solid {DIVIDER};
    border-radius: 12px;
    padding: 4px;
    outline: none;
}}
QListWidget::item {{
    padding: 8px 10px;
    border-radius: 8px;
}}
QListWidget::item:selected {{
    background-color: {SELECTED};
    color: {TEXT_PRIMARY};
}}
QListWidget::item:hover {{
    background-color: {HOVER};
}}

/* --- نوارِ کناری (درختِ ناوبری) ------------------------------------------- */
QWidget#sidebarContainer {{
    background-color: {PRIMARY};
}}
QPushButton#sidebarToggle {{
    background-color: transparent;
    color: rgba(255, 255, 255, 0.85);
    border-radius: 8px;
    font-size: 15px;
    padding: 0px;
}}
QPushButton#sidebarToggle:hover {{
    background-color: {PRIMARY_HOVER};
}}
QTreeWidget#sidebar {{
    background-color: {PRIMARY};
    color: rgba(255, 255, 255, 0.78);
    border: none;
    font-size: 13px;
    padding: 10px 8px;
    outline: none;
}}
QTreeWidget#sidebar::item {{
    padding: 10px 12px;
    margin: 2px 0px;
    border-radius: 10px;
}}
QTreeWidget#sidebar::item:has-children {{
    color: rgba(255, 255, 255, 0.5);
    font-weight: 700;
    font-size: 11px;
    margin-top: 10px;
}}
QTreeWidget#sidebar::item:selected {{
    background-color: {ACCENT};
    color: white;
    font-weight: 600;
}}
QTreeWidget#sidebar::item:hover:!selected {{
    background-color: {PRIMARY_HOVER};
}}
QTreeWidget#sidebar::branch {{
    background-color: transparent;
}}

/* --- هدر --------------------------------------------------------------- */
QWidget#headerBar {{
    background-color: {SURFACE};
    border-bottom: 1px solid {DIVIDER};
}}

QCheckBox {{
    spacing: 8px;
}}
QCheckBox::indicator {{
    width: 18px;
    height: 18px;
    border-radius: 5px;
    border: 1.5px solid {BORDER};
    background-color: {SURFACE};
}}
QCheckBox::indicator:checked {{
    background-color: {ACCENT};
    border: 1.5px solid {ACCENT};
}}

QToolTip {{
    background-color: {PRIMARY};
    color: white;
    border: none;
    padding: 6px 10px;
    border-radius: 8px;
}}

QMessageBox {{
    background-color: {SURFACE};
}}

/* --- اسکرول‌بارِ باریکِ مدرن ------------------------------------------------ */
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {BORDER};
    border-radius: 5px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{
    background: {ACCENT};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 2px;
}}
QScrollBar::handle:horizontal {{
    background: {BORDER};
    border-radius: 5px;
    min-width: 30px;
}}
QScrollBar::handle:horizontal:hover {{
    background: {ACCENT};
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0px;
}}
"""
