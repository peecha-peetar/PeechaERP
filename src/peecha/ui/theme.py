"""پالتِ رنگی + QSSِ سراسریِ برنامه — «Peecha ERP 2026»: معماریِ دوتاییِ
تمِ روشن/تیره (سوییچِ واقعیِ رفت‌وبرگشتی، نه فقط یک تمِ ثابت)، سطوحِ
لایه‌ای برایِ عمق (BACKGROUND تیره‌ترین/روشن‌ترین، SURFACE یک پله
متفاوت‌تر، HOVER/SELECTED یک پله بیشتر)، گوشه‌هایِ گردِ ۱۲–۱۶px، لبه‌هایِ
نیمه‌شفافِ نازک به‌جایِ بردرِ توپر، و سایه‌هایِ نرم برایِ حسِ شناوربودنِ
کارت‌ها.

نکته‌یِ سازگاری: تمامِ نام‌هایی که بیرون از این فایل استفاده می‌شوند
(ACCENT، BORDER، DIVIDER، PRIMARY، SUCCESS، TEXT_PRIMARY، TEXT_SECONDARY،
DONUT_COLORS، LEVEL_*، apply_card_shadows، avatar_color_for،
set_status_label، GLOBAL_QSS) دست‌نخورده مانده‌اند — این‌ها همه به
ماژول‌سطح متصل‌اند و با `set_theme_mode()` مقدارشان زنده عوض می‌شود (نه
فقط یک‌بار در import). کدِ مصرف‌کننده همیشه باید با
`from peecha.ui import theme` + `theme.NAME` باشد (نه
`from peecha.ui.theme import NAME`) — وگرنه مقدارِ منجمدشده‌یِ لحظه‌یِ
import می‌ماند و با سوییچِ تم به‌روز نمی‌شود.

معماری: دو دیکشنریِ ثابتِ توکن (`_DARK_TOKENS`/`_LIGHT_TOKENS`) + تابعِ
`_apply_tokens()` که مقادیرِ ماژول‌سطح را از رویِ یکی از این دو
بازمی‌نویسد و `GLOBAL_QSS` را دوباره می‌سازد. `set_theme_mode(app, dark)`
این را صدا می‌زند، `QPalette` را هم دوباره اعمال می‌کند، ترجیح را در
`QSettings` ذخیره می‌کند، و یک پاسِ repolish رویِ همه‌یِ ویجت‌هایِ زنده
می‌زند تا سوییچ بدونِ ری‌استارت اثر کند."""

from __future__ import annotations

import hashlib

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPalette, QPixmap
from PySide6.QtWidgets import QApplication, QGraphicsDropShadowEffect, QWidget

_SETTINGS_ORG = "Peecha"
_SETTINGS_APP = "PeechaERP"
_THEME_MODE_KEY = "appearance/dark_mode"

# --- جدولِ توکن‌هایِ تمِ تیره (پیش‌فرض) --------------------------------------
_DARK_TOKENS: dict[str, str] = {
    "BACKGROUND": "#0B0D18",        # پس‌زمینه‌یِ صفحه — navy تقریباً سیاه
    "SURFACE": "#151830",           # کارت/پنلِ شیشه‌ای — یک پله روشن‌تر از BACKGROUND
    "HOVER": "#1C2040",             # حالتِ هاور
    "SELECTED": "#262A52",          # حالتِ انتخاب‌شده (نرم، نه اکسنتِ کامل)
    "BORDER": "#262A4C",            # لبه‌یِ نازکِ کارت/فیلد
    "BORDER_HOVER": "#3A3E68",      # لبه‌یِ فیلد در حالتِ هاور
    "DIVIDER": "#1D2140",           # خط‌جداکننده — کم‌رنگ‌تر از BORDER
    "TEXT_PRIMARY": "#EEF0FA",      # سفیدِ نرم — خوانایی بدونِ خیرگی
    "TEXT_SECONDARY": "#9599BD",    # خاکستری‌-یاسیِ کم‌رنگ
    "TEXT_DISABLED": "#565A7C",
    "PRIMARY": "#9EA0FF",           # نیلیِ روشن — متنِ تاکیدی رویِ زمینه‌یِ تیره
    "PRIMARY_HOVER": "#B4B6FF",
    "PRIMARY_LIGHT": "#20223F",
    "ACCENT": "#5B5CF0",            # اکسنتِ اصلیِ برند — یکسان در هر دو تم
    "ACCENT_HOVER": "#7274FF",
    "ACCENT_PRESSED": "#4547CC",
    "ACCENT_LIGHT": "#23244F",
    "ACCENT_LIGHT_HOVER": "#2B2D63",
    "SUCCESS": "#34D399",
    "WARNING": "#E8A23D",
    "DANGER": "#F0616B",
    "INFO": "#5AA9F2",
    "CHART_PURPLE": "#B79CFA",
    "CHART_ORANGE": "#FB9B5D",
    "CHART_TEAL": "#3FD9C7",
    "GRID_HEADER_BG": "#171A33",
    "GRID_BORDER": "#242847",
    "GRID_ROW_ALT": "#10121F",
    "TOOLTIP_BG": "#1E2142",
}

# --- جدولِ توکن‌هایِ تمِ روشن — طراحیِ تازه، نه اینورسِ ساده‌یِ تمِ تیره ---------
_LIGHT_TOKENS: dict[str, str] = {
    "BACKGROUND": "#F7F7FB",        # سفیدِ خیلی کم‌رنگِ یاسی — نه سفیدِ خام
    "SURFACE": "#FFFFFF",           # کارتِ سفیدِ خالص — یک پله روشن‌تر از BACKGROUND
    "HOVER": "#F0F1F8",
    "SELECTED": "#E7E8FA",
    "BORDER": "#E3E4F0",
    "BORDER_HOVER": "#C7C9DC",
    "DIVIDER": "#ECEDF5",
    "TEXT_PRIMARY": "#1A1B2E",      # تقریباً مشکی — نه مشکیِ خالص
    "TEXT_SECONDARY": "#6B6E8C",
    "TEXT_DISABLED": "#A6A8C0",
    "PRIMARY": "#4C4DE0",           # نیلیِ عمیق‌تر — رویِ زمینه‌یِ روشن باید تیره‌تر از ACCENT باشد
    "PRIMARY_HOVER": "#3F40C4",
    "PRIMARY_LIGHT": "#EEEEFF",
    "ACCENT": "#5B5CF0",            # همان اکسنتِ برند — هویتِ یکسان در هر دو تم
    "ACCENT_HOVER": "#4A4BDB",
    "ACCENT_PRESSED": "#3A3BB8",
    "ACCENT_LIGHT": "#EEEEFF",
    "ACCENT_LIGHT_HOVER": "#E2E3FC",
    "SUCCESS": "#16A34A",
    "WARNING": "#D97706",
    "DANGER": "#DC2626",
    "INFO": "#2563EB",
    "CHART_PURPLE": "#8B5CF6",
    "CHART_ORANGE": "#F97316",
    "CHART_TEAL": "#0D9488",
    "GRID_HEADER_BG": "#F5F5FA",
    "GRID_BORDER": "#E7E8F2",
    "GRID_ROW_ALT": "#FAFAFD",
    "TOOLTIP_BG": "#2A2B45",         # تولتیپ عمداً در هر دو تم تیره می‌ماند (مثلِ VSCode)
}

STATUS_COLOR_ROLE: dict[str, str] = {
    "TEMPORARY": "warning",
    "PERMANENT": "success",
    "REVERSED": "danger",
    "CANCELLED": "danger",
    "PENDING": "warning",
    "APPROVED": "success",
    "REJECTED": "danger",
}


def status_color(status_code: str) -> str:
    role = STATUS_COLOR_ROLE.get(status_code, "info")
    return {"success": SUCCESS, "warning": WARNING, "danger": DANGER, "info": INFO}[role]


def set_status_label(label, text: str, *, ok: bool) -> None:
    """رنگِ سبز/قرمزِ پیامِ موفقیت/خطا را مستقیماً رویِ خودِ ویجت اعمال
    می‌کند — نه با تغییرِ objectName به «statusOk»/«statusError» (که Qt
    بعدِ نمایشِ اولیه‌ی ویجت، خودکار رفرش/repolish نمی‌کند)."""
    color = SUCCESS if ok else DANGER
    label.setStyleSheet(f"color: {color}; font-weight: 600;")
    label.setText(text)


def rgba(color: str, alpha: float) -> str:
    """کدِ هگز را به رشته‌یِ rgba() برایِ QSS تبدیل می‌کند — برایِ ته‌رنگ/
    شیشه‌ای‌کردنِ واقعی (آلفایِ ترکیبی رویِ SURFACE زیرین)، به‌جایِ شبیه‌سازیِ
    دستیِ ترکیبِ رنگ با یک رنگِ پایه‌یِ ثابت."""
    c = QColor(color)
    return f"rgba({c.red()}, {c.green()}, {c.blue()}, {max(0.0, min(1.0, alpha))})"


def apply_card_shadows(root: QWidget) -> None:
    """سایه‌ی نرمِ زیرِ هر ویجتِ «کارت» (objectName == "card") را — رویِ
    خودِ آن ویجت و همه‌ی فرزندانش — اعمال می‌کند؛ کارت‌هایی که خودشان از
    قبل یک QGraphicsEffect دارند (مثلِ widgets.KpiCard) نادیده گرفته
    می‌شوند. سایه‌یِ سیاهِ خنثی (نه رنگیِ اکسنت) رویِ هر دو تم به‌درستی
    حسِ «شناوربودن» می‌دهد — نیازی به دو مقدارِ جدا برایِ روشن/تیره نیست."""
    candidates = [root, *root.findChildren(QWidget)]
    for widget in candidates:
        if widget.objectName() != "card" or widget.graphicsEffect() is not None:
            continue
        effect = QGraphicsDropShadowEffect(widget)
        effect.setBlurRadius(36)
        effect.setXOffset(0)
        effect.setYOffset(10)
        effect.setColor(QColor(0, 0, 0, 130))
        widget.setGraphicsEffect(effect)


def apply_palette(app: QApplication) -> None:
    """کنارِ GLOBAL_QSS، خودِ QPalette را هم با توکن‌هایِ *جاری* هماهنگ
    می‌کند — چون Fusion برایِ بخشی از اجزایِ بومی‌رسم‌شده (فریم/فلشِ
    QComboBoxِ غیرقابل‌ویرایش، پس‌زمینه‌یِ پاپ‌آپ‌ها، اسکرول‌بار، حالتِ
    غیرفعال) رویِ QPalette تکیه می‌کند، نه QSS. با فراخوانیِ دوباره‌یِ این
    تابع بعدِ `set_theme_mode`، این اجزا هم بدونِ ری‌استارت عوض می‌شوند."""
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(BACKGROUND))
    palette.setColor(QPalette.WindowText, QColor(TEXT_PRIMARY))
    palette.setColor(QPalette.Base, QColor(SURFACE))
    palette.setColor(QPalette.AlternateBase, QColor(GRID_ROW_ALT))
    # طبقِ طراحی، TOOLTIP_BG در هر دو تم تیره می‌ماند (مثلِ VSCode) — پس
    # متنِ تولتیپ هم ثابت روشن است، نه TEXT_PRIMARY (که در تمِ روشن
    # تقریباً مشکی می‌شود و رویِ زمینه‌یِ تیره‌یِ تولتیپ ناخوانا می‌شود).
    palette.setColor(QPalette.ToolTipBase, QColor(TOOLTIP_BG))
    palette.setColor(QPalette.ToolTipText, QColor("#EEF0FA"))
    palette.setColor(QPalette.Text, QColor(TEXT_PRIMARY))
    palette.setColor(QPalette.Button, QColor(SURFACE))
    palette.setColor(QPalette.ButtonText, QColor(TEXT_PRIMARY))
    palette.setColor(QPalette.BrightText, QColor(DANGER))
    palette.setColor(QPalette.Link, QColor(PRIMARY))
    palette.setColor(QPalette.Highlight, QColor(ACCENT))
    palette.setColor(QPalette.HighlightedText, QColor("#FFFFFF"))
    palette.setColor(QPalette.PlaceholderText, QColor(TEXT_DISABLED))
    palette.setColor(QPalette.Disabled, QPalette.Text, QColor(TEXT_DISABLED))
    palette.setColor(QPalette.Disabled, QPalette.WindowText, QColor(TEXT_DISABLED))
    palette.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(TEXT_DISABLED))
    app.setPalette(palette)


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


# --- مدیریتِ حالتِ تم (روشن/تیره) --------------------------------------------
_dark_mode = True
_font_family: str | None = None


def set_font_family(name: str) -> None:
    """`main.py` این را یک‌بار بعدِ ثبتِ فونت صدا می‌زند تا `set_theme_mode`
    همیشه بداند QSS را با کدام font-family دوباره اعمال کند."""
    global _font_family
    _font_family = name


def is_dark_mode() -> bool:
    return _dark_mode


def load_saved_theme_mode() -> bool:
    """ترجیحِ ذخیره‌شده در QSettings را می‌خواند — پیش‌فرض تیره (True)
    اگر کاربر هنوز هیچ‌وقت سوییچ نکرده باشد."""
    settings = QSettings(_SETTINGS_ORG, _SETTINGS_APP)
    return bool(settings.value(_THEME_MODE_KEY, True, type=bool))


def set_theme_mode(app: QApplication, dark: bool) -> None:
    """سوییچِ زنده‌یِ تم — بدونِ نیاز به ری‌استارتِ برنامه. توکن‌هایِ
    ماژول‌سطح را عوض می‌کند، QPalette و QSSِ سراسری را دوباره اعمال
    می‌کند، ترجیح را ذخیره می‌کند، و یک پاسِ repolish رویِ همه‌یِ ویجت‌هایِ
    زنده می‌زند تا کنترل‌هایِ استانداردِ QSS (کارت/جدول/دکمه/فیلد/تب/…)
    فوراً رنگِ تازه بگیرند. ویجت‌هایِ سفارشیِ رسم‌شونده (HoverButton و
    مشابه‌ها، فقط در کرومِ ساید‌بار/هدر/تیتربارِ MDI) رنگِ پس‌زمینه‌یِ
    هاورشان را در __init__ منجمد می‌کنند — مسئولِ بازسازیِ آن‌ها
    `MainWindow._rebuild_chrome()` است، نه این تابع."""
    global _dark_mode
    _dark_mode = dark
    _apply_tokens(_DARK_TOKENS if dark else _LIGHT_TOKENS)
    apply_palette(app)
    font_prefix = f'* {{ font-family: "{_font_family}"; }}\n' if _font_family else ""
    app.setStyleSheet(font_prefix + GLOBAL_QSS)
    settings = QSettings(_SETTINGS_ORG, _SETTINGS_APP)
    settings.setValue(_THEME_MODE_KEY, dark)
    for widget in app.allWidgets():
        widget.style().unpolish(widget)
        widget.style().polish(widget)
        widget.update()


def _apply_tokens(tokens: dict[str, str]) -> None:
    g = globals()
    g.update(tokens)
    g["LEVEL_GROUP"] = tokens["CHART_PURPLE"]
    g["LEVEL_KOL"] = tokens["CHART_TEAL"]
    g["LEVEL_MOEIN"] = tokens["TEXT_PRIMARY"]
    g["DONUT_COLORS"] = [
        tokens["ACCENT"], tokens["SUCCESS"], tokens["CHART_PURPLE"],
        tokens["CHART_ORANGE"], tokens["WARNING"],
    ]
    g["AVATAR_COLORS"] = [
        tokens["ACCENT"], tokens["SUCCESS"], tokens["CHART_ORANGE"],
        tokens["INFO"], tokens["CHART_PURPLE"], tokens["CHART_TEAL"],
    ]
    g["GLOBAL_QSS"] = _build_global_qss()


def _build_global_qss() -> str:
    return f"""
* {{
    outline: none;
}}
QWidget {{
    background-color: {BACKGROUND};
    color: {TEXT_PRIMARY};
    font-size: 14px;
}}
/* طبقِ یک باگِ واقعاً کشف‌شده: همین قاعده‌ی بالا (background-colorِ
   سراسری رویِ QWidget) باعث می‌شود Qt هر QLabelِ ساده هم WA_StyledBackground
   بگیرد و یک مستطیلِ توپرِ هم‌رنگِ BACKGROUND پشتِ خودش رسم کند — حتی
   وقتی آن لیبل درونِ یک کارت/هدرِ SURFACE-رنگ نشسته باشد. راه‌حل:
   پیش‌فرضِ لیبل‌ها شفاف باشد — لیبل‌هایی که واقعاً پس‌زمینه می‌خواهند
   (avatarBadge و…) با selectorِ اختصاصیِ خودشان (اولویتِ بالاتر)
   همچنان کار می‌کنند. */
QLabel {{
    background: transparent;
}}
QWidget#card, QFrame#card {{
    background-color: {SURFACE};
    border-radius: 16px;
    border: 1px solid {BORDER};
}}
QLabel#pageTitle {{
    font-size: 26px;
    font-weight: 800;
    color: {TEXT_PRIMARY};
    letter-spacing: 0.2px;
}}
QLabel#sectionHint {{
    color: {TEXT_SECONDARY};
    font-size: 13px;
}}
QLabel#cardTitle {{
    color: {TEXT_PRIMARY};
    font-size: 15px;
    font-weight: 700;
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
    background-color: {rgba(SURFACE, 0.7)};
    border: 1.5px solid {BORDER};
    border-radius: 10px;
    padding: 8px 12px;
    font-size: 14px;
    color: {TEXT_PRIMARY};
    selection-background-color: {ACCENT};
}}
QLineEdit:hover, QComboBox:hover, QDateEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover {{
    border: 1.5px solid {BORDER_HOVER};
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
    background-color: {GRID_HEADER_BG};
    border: 1px solid {BORDER};
    border-radius: 12px;
    padding: 4px;
    selection-background-color: {SELECTED};
    selection-color: {PRIMARY};
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

/* --- دکمه‌ها -------------------------------------------------------- */
QPushButton {{
    border-radius: 10px;
    padding: 9px 18px;
    font-size: 14px;
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
    color: {PRIMARY};
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
    background-color: {rgba(DANGER, 0.14)};
}}

/* --- جدول‌ها ------------------------------------------------------------ */
QTableWidget {{
    background-color: {SURFACE};
    border: none;
    gridline-color: {GRID_BORDER};
    font-size: 14px;
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
    font-size: 13px;
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

/* --- هدر --------------------------------------------------------------- */
QWidget#headerBar {{
    background-color: {SURFACE};
    border-bottom: 1px solid {DIVIDER};
}}

/* --- ریبونِ میان‌برهایِ پرکاربرد (کاشی‌هایِ آیکون‌دار، زیرِ هدر) --------------- */
QScrollArea#quickAccessScroll {{
    background-color: {SURFACE};
    border: none;
    border-bottom: 1px solid {DIVIDER};
}}
QWidget#quickAccessBar {{
    background-color: {SURFACE};
}}

/* --- ساید‌بار (ناوبریِ اصلی، دائمی و جمع‌شونده) ------------------------------ */
QScrollArea#sidebarScroll {{
    background-color: {SURFACE};
    border: none;
    border-left: 1px solid {DIVIDER};
}}
QWidget#sidebarContainer {{
    background-color: {SURFACE};
}}
QPushButton#sidebarGroupHeader {{
    color: {TEXT_PRIMARY};
    font-weight: 700;
    font-size: 14px;
}}
QPushButton#sidebarGroupHeader:hover {{
    color: {PRIMARY};
}}
QPushButton#sidebarGroupHeader[active="true"] {{
    color: {ACCENT};
}}
QPushButton#sidebarGearButton {{
    color: {TEXT_SECONDARY};
    font-size: 14px;
}}
QPushButton#sidebarGearButton:hover {{
    color: {PRIMARY};
}}
QLabel#sidebarSubGroupTitle {{
    color: {TEXT_SECONDARY};
    font-size: 12px;
    font-weight: 700;
}}
QPushButton#sidebarLeafItem {{
    color: {TEXT_SECONDARY};
    font-size: 13.5px;
    font-weight: 500;
}}
QPushButton#sidebarLeafItem:hover {{
    color: {PRIMARY};
}}
QPushButton#sidebarLeafItem[active="true"] {{
    color: {ACCENT};
    font-weight: 700;
}}

/* --- ناحیه‌ی کاریِ MDI (فرم‌هایِ شناور) --------------------------------------- */
QMdiArea#mdiArea {{
    background-color: {BACKGROUND};
    border: none;
}}
QMdiSubWindow {{
    background-color: {SURFACE};
}}
QFrame#mdiFormWrapper {{
    background-color: {SURFACE};
    border: 1px solid {DIVIDER};
}}
QWidget#mdiTitleBar {{
    background-color: {HOVER};
    border-bottom: 1px solid {DIVIDER};
}}
QWidget#mdiTitleBar[active="true"] {{
    background-color: {ACCENT_LIGHT};
}}
QLabel#mdiTitleLabel {{
    color: {TEXT_PRIMARY};
    font-weight: 700;
    font-size: 13px;
    background: transparent;
}}
QPushButton#mdiTitleBarButton {{
    color: {TEXT_SECONDARY};
    font-size: 12px;
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
    background-color: {TOOLTIP_BG};
    color: #EEF0FA;
    border: 1px solid {BORDER};
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


_apply_tokens(_DARK_TOKENS)
