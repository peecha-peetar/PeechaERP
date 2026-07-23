"""پالتِ رنگیِ Qt — عیناً همان مقادیرِ هگزِ `peecha.ui.theme` (پالتِ «آئورا»)،
اینجا مستقیم به‌صورتِ رشته‌ی هگز (نه RGBA کسری) چون QSS/Qt رنگ‌ها را با
`#RRGGBB` می‌خواهد."""

from __future__ import annotations

PRIMARY = "#14173A"
PRIMARY_HOVER = "#1F234E"
PRIMARY_LIGHT = "#EEECFC"
ACCENT = "#6D5CE6"
ACCENT_HOVER = "#5B4CD6"
SUCCESS = "#15A672"
WARNING = "#F5A524"
DANGER = "#E5484D"
INFO = "#0EA5E9"

CHART_PURPLE = "#9333EA"
CHART_ORANGE = "#F97316"
CHART_TEAL = "#14B8A6"

BACKGROUND = "#F6F5FB"
SURFACE = "#FFFFFF"
HOVER = "#F4F3FA"
SELECTED = "#EEECFC"
BORDER = "#E6E4F0"
DIVIDER = "#ECEAF3"

TEXT_PRIMARY = "#18162B"
TEXT_SECONDARY = "#6B6B85"
TEXT_DISABLED = "#A3A2B8"

GRID_HEADER_BG = "#EFEDF9"
GRID_BORDER = "#E1DEEF"
GRID_ROW_ALT = "#FAF9FD"
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

# استایلِ سراسری — طبقِ همان زبانِ بصریِ Kivy (کارت‌های گرد، فیلدهایِ
# fill-style، دکمه‌هایِ pill) اما با ابزارِ QSS.
GLOBAL_QSS = f"""
QWidget {{
    background-color: {BACKGROUND};
    color: {TEXT_PRIMARY};
}}
QWidget#card, QFrame#card {{
    background-color: {SURFACE};
    border-radius: 16px;
}}
QLabel#pageTitle {{
    font-size: 22px;
    font-weight: bold;
    color: {TEXT_PRIMARY};
}}
QLabel#sectionHint {{
    color: {TEXT_SECONDARY};
    font-size: 12px;
}}
QLabel#statusError {{
    color: {DANGER};
}}
QLabel#statusOk {{
    color: {SUCCESS};
}}
QLineEdit, QComboBox, QDateEdit, QSpinBox, QDoubleSpinBox {{
    background-color: {HOVER};
    border: 1px solid {BORDER};
    border-radius: 10px;
    padding: 8px 12px;
    font-size: 13px;
    color: {TEXT_PRIMARY};
}}
QLineEdit:focus, QComboBox:focus, QDateEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
    border: 1px solid {ACCENT};
}}
QPushButton {{
    border-radius: 16px;
    padding: 8px 18px;
    font-size: 13px;
}}
QPushButton#primaryButton {{
    background-color: {ACCENT};
    color: white;
}}
QPushButton#primaryButton:hover {{
    background-color: {ACCENT_HOVER};
}}
QPushButton#flatButton {{
    background-color: transparent;
    color: {ACCENT};
}}
QPushButton#flatButton:hover {{
    background-color: {HOVER};
}}
QPushButton#dangerButton {{
    background-color: transparent;
    color: {DANGER};
}}
QTableWidget {{
    background-color: {SURFACE};
    border: none;
    gridline-color: {GRID_BORDER};
    font-size: 13px;
}}
QHeaderView::section {{
    background-color: {GRID_HEADER_BG};
    color: {TEXT_SECONDARY};
    padding: 8px;
    border: none;
    font-weight: bold;
}}
QTreeWidget {{
    background-color: {PRIMARY};
    color: rgba(255, 255, 255, 0.75);
    border: none;
    font-size: 13px;
    outline: none;
}}
QTreeWidget::item {{
    padding: 8px 6px;
    border-radius: 8px;
}}
QTreeWidget::item:selected {{
    background-color: {ACCENT};
    color: white;
}}
QTreeWidget::item:hover:!selected {{
    background-color: {PRIMARY_HOVER};
}}
QWidget#headerBar {{
    background-color: {SURFACE};
    border-bottom: 1px solid {DIVIDER};
}}
QCheckBox {{
    spacing: 6px;
}}
"""
