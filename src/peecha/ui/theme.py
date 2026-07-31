"""پالتِ رنگی + QSSِ سراسریِ برنامه — بازطراحیِ «مدرنِ ۲۰۲۶»: پالتِ نیلی/
بنفشِ نرم (به‌جایِ سرمه‌ایِ تخت/تیره‌یِ قبلی)، پس‌زمینه‌یِ روشن و هوادار،
گوشه‌هایِ گردترِ کارت/دکمه/فیلد، سایه‌هایِ لطیف، و هدر/منویِ افقیِ روشن
(به‌جایِ نوارِ تیره‌یِ قدیمی که حسِ برنامه‌هایِ enterprise کهنه می‌داد).

نکته‌یِ سازگاری: تمامِ نام‌هایی که بیرون از این فایل استفاده می‌شوند
(ACCENT، BORDER، DIVIDER، PRIMARY، SUCCESS، TEXT_PRIMARY، TEXT_SECONDARY،
DONUT_COLORS، LEVEL_*، apply_card_shadows، avatar_color_for،
set_status_label، GLOBAL_QSS) دست‌نخورده مانده‌اند — فقط مقدار/محتوایشان
تازه شده."""

from __future__ import annotations

import hashlib

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QWidget

# --- پالتِ نیلی/بنفشِ مدرن -------------------------------------------------
PRIMARY = "#1E1B4B"          # نیلیِ خیلی تیره — فقط برایِ تولتیپ/متن‌هایِ تأکیدی
PRIMARY_HOVER = "#312E81"
PRIMARY_LIGHT = "#EEF2FF"
ACCENT = "#4F46E5"           # نیلیِ اصلی (indigo-600) — جایگزینِ سرمه‌ایِ #020025
ACCENT_HOVER = "#4338CA"
ACCENT_PRESSED = "#3730A3"
ACCENT_LIGHT = "#EEF2FF"     # ته‌رنگِ خیلی کم‌رنگِ اکسنت — برایِ هاورِ نرم/پیل‌هایِ غیرفعال
ACCENT_LIGHT_HOVER = "#E0E0FC"
SUCCESS = "#16A672"
WARNING = "#F5A524"
DANGER = "#EF4444"
INFO = "#0EA5E9"

CHART_PURPLE = "#9333EA"
CHART_ORANGE = "#F97316"
CHART_TEAL = "#14B8A6"

BACKGROUND = "#F7F7FC"
SURFACE = "#FFFFFF"
HOVER = "#F1F1F8"
SELECTED = "#E6E4FB"
BORDER = "#E4E4EE"
DIVIDER = "#EDEDF4"
# هاورِ ریبون/منو: ته‌رنگِ بسیار کم‌رنگِ نیلی (متناسب با اکسنتِ تازه).
RIBBON_HOVER = "rgba(79, 70, 229, 16)"

TEXT_PRIMARY = "#15162B"
TEXT_SECONDARY = "#6B6F85"
TEXT_DISABLED = "#A0A3B4"

GRID_HEADER_BG = "#F5F5FA"
GRID_BORDER = "#ECECF3"
GRID_ROW_ALT = "#FAFAFD"
LEVEL_GROUP = "#7C3AED"
LEVEL_KOL = "#0D9488"
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


def set_status_label(label, text: str, *, ok: bool) -> None:
    """رنگِ سبز/قرمزِ پیامِ موفقیت/خطا را مستقیماً رویِ خودِ ویجت اعمال
    می‌کند — نه با تغییرِ objectName به «statusOk»/«statusError» (که Qt
    بعدِ نمایشِ اولیه‌ی ویجت، خودکار رفرش/repolish نمی‌کند)."""
    color = SUCCESS if ok else DANGER
    label.setStyleSheet(f"color: {color}; font-weight: 600;")
    label.setText(text)


DONUT_COLORS = [ACCENT, SUCCESS, CHART_PURPLE, CHART_ORANGE, WARNING]

# رنگ‌های چرخشیِ آواتار/نشان — برایِ حروفِ اول (کاربر/گروه/...)
AVATAR_COLORS = [ACCENT, SUCCESS, CHART_ORANGE, INFO, CHART_PURPLE, CHART_TEAL]


def apply_card_shadows(root: QWidget) -> None:
    """سایه‌ی ملایمِ زیرِ هر ویجتِ «کارت» (objectName == "card") را — رویِ
    خودِ آن ویجت و همه‌ی فرزندانش — اعمال می‌کند؛ کارت‌هایی که خودشان از
    قبل یک QGraphicsEffect دارند (مثلِ widgets.KpiCard، که سایه‌اش را با
    هاور متحرک می‌کند) نادیده گرفته می‌شوند — وگرنه این افکتِ ثابت
    جایگزینِ افکتِ متحرکشان می‌شد و انیمیشنِ هاور را (بی‌صدا، چون افکتِ
    قدیمی از ویجت جدا می‌شد نه حذف) از کار می‌انداخت."""
    candidates = [root, *root.findChildren(QWidget)]
    for widget in candidates:
        if widget.objectName() != "card" or widget.graphicsEffect() is not None:
            continue
        effect = QGraphicsDropShadowEffect(widget)
        effect.setBlurRadius(32)
        effect.setXOffset(0)
        effect.setYOffset(8)
        effect.setColor(QColor(79, 70, 229, 22))
        widget.setGraphicsEffect(effect)


def avatar_color_for(text: str) -> str:
    if not text:
        return ACCENT
    digest = hashlib.md5(text.encode("utf-8")).hexdigest()
    return AVATAR_COLORS[int(digest, 16) % len(AVATAR_COLORS)]


def emoji_icon(glyph: str, size: int = 22) -> QIcon:
    """رندرِ یک ایموجی/گلیف به QIcon — بدونِ نیازِ به فایلِ آیکونِ خارجی."""
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
    border-radius: 16px;
    border: 1px solid {DIVIDER};
}}
QLabel#pageTitle {{
    font-size: 24px;
    font-weight: 800;
    color: {TEXT_PRIMARY};
    letter-spacing: 0.2px;
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
    background-color: {SURFACE};
    border: 1.5px solid {BORDER};
    border-radius: 10px;
    padding: 8px 12px;
    font-size: 13px;
    color: {TEXT_PRIMARY};
    selection-background-color: {ACCENT};
}}
QLineEdit:hover, QComboBox:hover, QDateEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover {{
    border: 1.5px solid #C7C9E0;
}}
QLineEdit:focus, QComboBox:focus, QDateEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
    border: 1.5px solid {ACCENT};
    background-color: {SURFACE};
}}
QLineEdit:disabled, QComboBox:disabled {{
    color: {TEXT_DISABLED};
    background-color: {HOVER};
}}
QSpinBox:disabled, QDoubleSpinBox:disabled {{
    color: {TEXT_DISABLED};
    background-color: {HOVER};
}}
QComboBox::drop-down {{
    border: none;
    width: 28px;
}}
QComboBox QAbstractItemView {{
    background-color: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 12px;
    padding: 4px;
    selection-background-color: {SELECTED};
    selection-color: {ACCENT_PRESSED};
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

/* --- دکمه‌ها (گردتر و نرم‌تر از نسخه‌ی قبل) -------------------------------- */
QPushButton {{
    border-radius: 10px;
    padding: 9px 18px;
    font-size: 13px;
    font-weight: 600;
    border: none;
}}
QPushButton:disabled {{
    background-color: {HOVER};
    color: {TEXT_DISABLED};
}}
QPushButton:checked {{
    background-color: {ACCENT_HOVER};
    color: white;
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
    background-color: #FDECEC;
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

/* --- تب/لیست/گروه‌بندی ---------------------------------------------------- */
QTabWidget::pane {{
    border: 1px solid {BORDER};
    border-radius: 10px;
    top: 4px;
    background-color: {SURFACE};
}}
QTabBar::tab {{
    background-color: {HOVER};
    color: {TEXT_SECONDARY};
    border: none;
    padding: 9px 20px;
    margin-left: 4px;
    border-top-left-radius: 10px;
    border-top-right-radius: 10px;
    font-weight: 600;
}}
QTabBar::tab:hover {{
    color: {TEXT_PRIMARY};
    background-color: {ACCENT_LIGHT};
}}
QTabBar::tab:selected {{
    background-color: {ACCENT};
    color: white;
}}
QGroupBox {{
    border: 1px solid {BORDER};
    border-radius: 10px;
    margin-top: 10px;
    background-color: {SURFACE};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top right;
    padding: 0 3px;
    font-weight: bold;
    color: {TEXT_PRIMARY};
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

/* --- منویِ افقیِ اصلی (مگامنو) — روشن و هوادار، به‌جایِ نوارِ تیره‌یِ قبلی --- */
QScrollArea#menuBarScroll {{
    background-color: {SURFACE};
    border: none;
    border-bottom: 1px solid {DIVIDER};
}}
QWidget#menuBar {{
    background-color: {SURFACE};
}}
QPushButton#menuButton {{
    background-color: transparent;
    color: {TEXT_SECONDARY};
    border-radius: 10px;
    padding: 10px 18px;
    font-weight: 600;
    font-size: 13px;
    border: none;
}}
QPushButton#menuButton:hover {{
    background-color: {ACCENT_LIGHT};
    color: {ACCENT_PRESSED};
}}
QPushButton#menuButton[active="true"] {{
    background-color: {ACCENT};
    color: white;
}}
QScrollArea#megaPanelScroll {{
    background-color: rgba(255, 255, 255, 235);
    border-bottom: 1px solid {DIVIDER};
}}
QWidget#megaPanel {{
    background-color: rgba(255, 255, 255, 235);
}}
QLabel#megaPanelColumnTitle {{
    color: {TEXT_SECONDARY};
    font-weight: 700;
    font-size: 11px;
}}
QPushButton#megaPanelItem {{
    background-color: transparent;
    color: {TEXT_PRIMARY};
    border-radius: 9px;
    padding: 7px 12px;
    font-weight: 500;
    font-size: 13px;
    border: none;
    text-align: right;
}}
QPushButton#megaPanelItem:hover {{
    background-color: {ACCENT_LIGHT};
    color: {ACCENT_PRESSED};
}}
QPushButton#megaPanelItem[active="true"] {{
    background-color: {SELECTED};
    color: {ACCENT};
    font-weight: 600;
}}
QLabel#breadcrumbLabel {{
    color: {TEXT_SECONDARY};
    font-size: 12px;
    padding: 6px 24px;
    background-color: {SURFACE};
    border-bottom: 1px solid {DIVIDER};
}}

/* --- هدر --------------------------------------------------------------- */
QWidget#headerBar {{
    background-color: {SURFACE};
    border-bottom: 1px solid {DIVIDER};
}}

/* --- ریبون (میان‌برهایِ گروهِ فعال، زیرِ هدر) ------------------------------- */
QScrollArea#ribbonScroll {{
    background-color: {SURFACE};
    border-bottom: 1px solid {DIVIDER};
}}
QWidget#ribbonBar {{
    background-color: {SURFACE};
}}
QPushButton#ribbonButton, QToolButton#ribbonButton {{
    background-color: transparent;
    color: {TEXT_SECONDARY};
    border-radius: 10px;
    padding: 10px 26px;
    font-weight: 600;
    font-size: 13px;
    border: none;
}}
QPushButton#ribbonButton:hover, QToolButton#ribbonButton:hover {{
    background-color: {RIBBON_HOVER};
    color: {ACCENT_PRESSED};
}}
QPushButton#ribbonButton[active="true"] {{
    background-color: {SELECTED};
    color: {ACCENT};
}}
QToolButton#ribbonButton::menu-indicator {{
    image: none;
    width: 0;
}}
QPushButton#ribbonGearButton {{
    background-color: transparent;
    color: {TEXT_SECONDARY};
    border-radius: 10px;
    padding: 4px 16px;
    font-size: 26px;
    border: none;
}}
QPushButton#ribbonGearButton:hover {{
    background-color: {RIBBON_HOVER};
    color: {ACCENT};
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
