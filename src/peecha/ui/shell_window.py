"""پنجره‌ی اصلیِ برنامه (پوسته) — معادلِ Qt برایِ shell.py/shell.kv در Kivy.

تفاوتِ کلیدی با نسخه‌ی Kivy: هیچ تکنیکِ «ترتیبِ معکوسِ اعلامِ فرزندان»
لازم نیست — با `app.setLayoutDirection(Qt.RightToLeft)` (در main.py)،
خودِ Qt ترتیبِ افقیِ هر QHBoxLayout را آینه می‌کند، و QComboBox به‌طورِ
بومی راست‌چین و جهت‌دار می‌شود.

طبقِ بازخوردِ صریح (با دو تصویرِ مرجع از یک نرم‌افزارِ حسابداریِ قدیمی):
ناوبریِ اصلی سه لایه دارد —
۱) یک ساید‌بارِ دائمی و جمع‌شونده (Sidebar) با گروه‌هایِ آکاردئونی، سمتِ
   راستِ صفحه؛
۲) یک ریبونِ افقیِ میان‌برهایِ پرکاربرد (کاشی‌هایِ آیکون‌دار) زیرِ هدر؛
۳) صفحه‌ها به‌جایِ جایگزینیِ کاملِ محتوا، به‌صورتِ «فرمِ شناور» (MDI —
   قابلِ‌درگ/تغییرِاندازه/بستن، با تیتربارِ خودش) رویِ یک ناحیه‌یِ کاریِ
   مشترک باز می‌شوند — دقیقاً همان الگویِ عکسِ مرجع، فقط با ظاهرِ روشن و
   مدرنِ ۲۰۲۶ به‌جایِ رنگِ سرمه‌ایِ تخت/فونتِ ریزِ قدیمی. برایِ این لایه از
   ویجتِ بومیِ Qt به‌همین منظور (QMdiArea/QMdiSubWindow) استفاده شده —
   نه شبیه‌سازیِ دستی.

مگاپنلِ افقیِ قبلی (پاپ‌آپِ بازشونده‌یِ زیرِ منویِ بالا) طبقِ همین بازخورد
به‌طورِ کامل کنار گذاشته شد.
"""

from __future__ import annotations

import json

from PySide6.QtCore import QEasingCurve, QEvent, QPropertyAnimation, QRect, QSettings, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QScreen
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMdiArea,
    QMdiSubWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from peecha import numerals, session
from peecha.nav_catalog import DEFAULT_QUICK_ACCESS_BY_MODULE, NAV_ITEMS
from peecha.nav_catalog import flatten_nav_items as _flatten_nav_items
from peecha.services import companies as companies_service
from peecha.services import fiscal_years as fiscal_years_service
from peecha.services import languages as languages_service
from peecha.services import translations as translations_service
from peecha.ui import theme
from peecha.ui.widgets import HoverButton, field_help_is_enabled, set_field_help_enabled

_NAV_ICONS = {
    "dashboard": "🏠",
    "MY_TASKS": "📥",
    "GL": "💰",
    "TREASURY": "🏦",
    "INV": "📦",
    "SALES": "🛒",
    "PURCH": "🧺",
    "HR": "👥",
    "INVOICES": "🧾",
    "REPORTS": "📈",
    "SETTINGS": "⚙️",
}

_SETTINGS_TAB_BY_GROUP_CODE = {"GL": 0, "TREASURY": 1, "HR": 6, "INV": 7, "SALES": 8, "PURCH": 8}


def _leaf_nav_children(item: dict) -> list[dict]:
    leaves: list[dict] = []
    for child in item.get("children", []):
        if child.get("children"):
            leaves.extend(_leaf_nav_children(child))
        else:
            leaves.append(child)
    return leaves


def _leaf_nav_children_for_module(module_code: str) -> list[dict]:
    """همه‌یِ آیتم‌هایِ برگِ یک ماژولِ سطحِ‌بالا (برایِ فرمِ تنظیمِ ریبون) —
    ماژولی مثلِ dashboard که خودش برگ است، لیستِ خالی برمی‌گرداند (چیزی
    برایِ میان‌برزدن به خودش وجود ندارد)."""
    module_item = next((item for item in NAV_ITEMS if item["code"] == module_code), None)
    if module_item is None:
        return []
    return _leaf_nav_children(module_item)


class _QuickAccessTile(QFrame):
    """کاشیِ ریبونِ میان‌بر — طبقِ نمونه‌طراحیِ کارت‌رنگیِ ارسالیِ کاربر،
    هم‌زبان با widgets.SummaryCard شد: بجِ آیکونِ ته‌رنگ‌دار (شیشه‌ایِ رنگیِ
    اکسنت، نه فقط متنِ خام)، لبه/زمینه‌یِ کم‌رنگِ کارت در حالتِ استراحت
    (نه دیگر کاملاً شفاف) و همان سایه‌ای که رویِ هاور بلندتر می‌شود. چون
    این کاشی‌ها هر بار در `_set_quick_access_module` از نو ساخته می‌شوند
    (نه singleton مثلِ KpiCardِ داشبورد)، رنگ‌هایِ inline اینجا مشکلِ
    «منجمدشدن رویِ سوییچِ تم» ندارند — با هر بازسازی از رویِ توکن‌هایِ
    تازه ساخته می‌شوند."""

    def __init__(self, icon: str, label: str, on_click, color: str | None = None) -> None:
        super().__init__()
        self.setObjectName("quickTile")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(84, 78)
        self._on_click = on_click
        self._color = color or theme.ACCENT

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 10, 6, 8)
        layout.setSpacing(4)
        layout.setAlignment(Qt.AlignCenter)

        icon_label = QLabel(icon)
        icon_label.setFixedSize(30, 30)
        icon_label.setAlignment(Qt.AlignCenter)
        icon_label.setStyleSheet(
            f"background-color: {theme.rgba(self._color, 0.16)}; "
            f"border: 1px solid {theme.rgba(self._color, 0.30)}; "
            "border-radius: 9px; font-size: 20px;"
        )
        layout.addWidget(icon_label, alignment=Qt.AlignCenter)

        text_label = QLabel(label)
        text_label.setAlignment(Qt.AlignCenter)
        text_label.setWordWrap(True)
        text_label.setStyleSheet(f"font-size: 10px; font-weight: 600; color: {theme.TEXT_SECONDARY}; background: transparent;")
        layout.addWidget(text_label)

        self._rest_style = (
            f"QFrame#quickTile {{ background-color: {theme.rgba(self._color, 0.05)}; "
            f"border: 1px solid {theme.rgba(self._color, 0.14)}; border-radius: 14px; }}"
        )
        self._hover_style = (
            f"QFrame#quickTile {{ background-color: {theme.rgba(self._color, 0.14)}; "
            f"border: 1px solid {theme.rgba(self._color, 0.35)}; border-radius: 14px; }}"
        )
        self.setStyleSheet(self._rest_style)

        self._shadow = QGraphicsDropShadowEffect(self)
        self._shadow.setBlurRadius(0)
        self._shadow.setXOffset(0)
        self._shadow.setYOffset(0)
        self._shadow.setColor(QColor(0, 0, 0, 0))
        self.setGraphicsEffect(self._shadow)
        self._anim = QPropertyAnimation(self._shadow, b"blurRadius", self)
        self._anim.setDuration(150)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._on_click()
        super().mousePressEvent(event)

    def enterEvent(self, event) -> None:  # noqa: N802
        self.setStyleSheet(self._hover_style)
        self._anim.stop()
        self._anim.setStartValue(self._shadow.blurRadius())
        self._anim.setEndValue(22)
        self._anim.start()
        hover_glow = QColor(self._color)
        hover_glow.setAlpha(70)
        self._shadow.setColor(hover_glow)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self.setStyleSheet(self._rest_style)
        self._anim.stop()
        self._anim.setStartValue(self._shadow.blurRadius())
        self._anim.setEndValue(0)
        self._anim.start()
        super().leaveEvent(event)


class _SidebarGroup(QWidget):
    """یک گروهِ آکاردئونیِ ساید‌بار — سرتیترِ آیکون‌دار که با کلیک، بدنه‌ی
    زیرِ خودش (فهرستِ آیتم‌هایِ برگ) را با انیمیشنِ ارتفاع باز/بسته
    می‌کند. آیتم‌هایِ بدونِ فرزند مستقیم یک دکمه‌ی تک‌سطحی‌اند (بدونِ فلش)."""

    def __init__(self, item: dict, icon: str, on_leaf_click, gear_click=None) -> None:
        super().__init__()
        self._entries: dict[str, HoverButton] = {}
        self._has_children = bool(item.get("children"))
        self._item = item
        # طبقِ حسابرسیِ صریح («سوییچرِ زبانِ فعال هیچ اثری ندارد»): برایِ
        # این‌که با تغییرِ زبان بتوانیم متنِ همین ویجت‌ها را بدونِ بازسازیِ
        # کاملِ ساید‌بار عوض کنیم، نگاشتِ کد -> ویجت و کد -> متنِ فارسیِ اصلی
        # همین‌جا نگه داشته می‌شود.
        self._widgets_by_code: dict[str, QWidget] = {}
        self._source_by_code: dict[str, str] = {item["code"]: item["label"]}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(2)

        self.header = HoverButton(
            "",
            hover_color=theme.HOVER,
            active_color=theme.ACCENT_LIGHT,
            radius=10,
            text_align=Qt.AlignRight,
        )
        self.header.setObjectName("sidebarGroupHeader")
        self.header.setMinimumHeight(42)
        self._update_header_text(icon, item["label"], expanded=False)
        header_row.addWidget(self.header, stretch=1)

        if gear_click is not None:
            gear_button = HoverButton("⚙", hover_color=theme.HOVER, radius=8, margin=4)
            gear_button.setObjectName("sidebarGearButton")
            gear_button.setFixedSize(30, 30)
            gear_button.setToolTip(f"تنظیمات «{item['label']}»")
            gear_button.clicked.connect(gear_click)
            header_row.addWidget(gear_button)

        outer.addLayout(header_row)

        if self._has_children:
            self.body = QWidget()
            self.body.setObjectName("sidebarGroupBody")
            body_layout = QVBoxLayout(self.body)
            body_layout.setContentsMargins(0, 2, 0, 6)
            body_layout.setSpacing(1)
            self._populate_body(item, body_layout, on_leaf_click, depth=1)
            self.body.setMaximumHeight(0)
            outer.addWidget(self.body)

            self._expanded = False
            self._anim = QPropertyAnimation(self.body, b"maximumHeight", self)
            self._anim.setDuration(180)
            self._anim.setEasingCurve(QEasingCurve.OutCubic)
            self.header.clicked.connect(self.toggle)
        else:
            self.body = None
            self.header.clicked.connect(lambda _checked=False, c=item["code"]: on_leaf_click(c))
            self._entries[item["code"]] = self.header

        self._icon = icon
        self._label = item["label"]
        self._gear_click = gear_click

    def _update_header_text(self, icon: str, label: str, *, expanded: bool) -> None:
        chevron = "⌄" if expanded else "❯" if self._has_children_hint() else ""
        self.header.setText(f"{icon}  {label}" + (f"   {chevron}" if chevron else ""))

    def _has_children_hint(self) -> bool:
        return getattr(self, "_has_children", False)

    def _populate_body(self, item: dict, layout: QVBoxLayout, on_leaf_click, depth: int) -> None:
        for child in item.get("children", []):
            if child.get("children"):
                sub_title = QLabel(child["label"])
                sub_title.setObjectName("sidebarSubGroupTitle")
                sub_title.setContentsMargins(18 + depth * 10, 8, 12, 2)
                layout.addWidget(sub_title)
                self._widgets_by_code[child["code"]] = sub_title
                self._source_by_code[child["code"]] = child["label"]
                self._populate_body(child, layout, on_leaf_click, depth=depth + 1)
            else:
                code = child["code"]
                button = HoverButton(
                    child["label"],
                    hover_color=theme.HOVER,
                    active_color=theme.ACCENT_LIGHT,
                    radius=8,
                    text_align=Qt.AlignRight,
                    indent=depth * 14,
                )
                button.setObjectName("sidebarLeafItem")
                button.setProperty("depth", depth)
                button.setMinimumHeight(34)
                button.clicked.connect(lambda _checked=False, c=code: on_leaf_click(c))
                layout.addWidget(button)
                self._entries[code] = button
                self._widgets_by_code[code] = button
                self._source_by_code[code] = child["label"]

    def retranslate(self, translate_fn) -> None:
        """طبقِ حسابرسیِ صریح: با تغییرِ زبانِ فعال، متنِ سرتیترِ گروه،
        زیرتیترها، و آیتم‌هایِ برگ (بدونِ بازسازیِ کاملِ ساید‌بار، تا
        انیمیشن/حالتِ باز-بسته‌بودنِ گروه دست‌نخورده بماند) عوض می‌شود."""
        self._label = translate_fn(self._item["code"], self._item["label"])
        self._update_header_text(self._icon, self._label, expanded=getattr(self, "_expanded", False))
        for code, widget in self._widgets_by_code.items():
            widget.setText(translate_fn(code, self._source_by_code[code]))

    def toggle(self) -> None:
        if self.body is None:
            return
        self.set_expanded(not self._expanded)

    def set_expanded(self, expanded: bool) -> None:
        if self.body is None or expanded == self._expanded:
            return
        self._expanded = expanded
        self.body.setMaximumHeight(16777215 if not expanded else 0)  # اجازه‌ی محاسبه‌ی sizeHint واقعی
        target = self.body.sizeHint().height() if expanded else 0
        self._anim.stop()
        self._anim.setStartValue(self.body.maximumHeight() if not expanded else 0)
        self._anim.setEndValue(target)
        self._anim.start()
        self._update_header_text(self._icon, self._label, expanded=expanded)
        self.header.set_active(expanded)

    def set_active_leaf(self, code: str | None) -> bool:
        """اگر یکی از آیتم‌هایِ این گروه با کد مچ شود، آن را برجسته و
        گروه را باز می‌کند؛ برمی‌گرداند که آیا مچی پیدا شد یا نه."""
        found = code in self._entries
        for entry_code, button in self._entries.items():
            is_active = entry_code == code
            button.setProperty("active", is_active)
            button.style().unpolish(button)
            button.style().polish(button)
            button.set_active(is_active)
        if found and self.body is not None:
            self.set_expanded(True)
        return found


_RESIZE_MARGIN = 6
_MIN_SUBWINDOW_SIZE = QSize(420, 320)


def _clamp_rect_to_area(rect: QRect, area: QRect) -> QRect:
    """یک مستطیل (geometryِ زیرپنجره) را طوری به داخلِ area (مرزهایِ
    فعلیِ ناحیه‌یِ MDI) می‌کشد که هیچ بخشی از آن — به‌خصوص فوترِ دکمه‌ها
    در پایینِ فرم — بیرون از دیدِ کاربر نماند؛ ریاضیِ فیزیکیِ ساده،
    نه تکیه بر مکانیزمِ داخلیِ QMdiArea که تحتِ راست‌چین درست عمل
    نمی‌کند. هم در بازیابی/کدربندیِ اولیه‌یِ زیرپنجره استفاده می‌شود
    (MainWindow._clamp_to_mdi_area) و هم در هر resizeِ زنده‌یِ خودِ
    ناحیه‌یِ MDI (_ClampingMdiArea.resizeEvent) — یک منبعِ حقیقتِ واحد،
    به‌جایِ دو پیاده‌سازیِ جدا که ممکن بود از هم عقب بمانند."""
    width = min(rect.width(), max(area.width(), _MIN_SUBWINDOW_SIZE.width()))
    height = min(rect.height(), max(area.height(), _MIN_SUBWINDOW_SIZE.height()))
    max_x = max(0, area.width() - width)
    max_y = max(0, area.height() - height)
    x = min(max(rect.x(), 0), max_x)
    y = min(max(rect.y(), 0), max_y)
    return QRect(x, y, width, height)


class _MdiTitleBar(QWidget):
    """تیتربارِ کاملاً سفارشی برایِ فرم‌هایِ شناور — طبقِ درخواستِ صریح
    (تیتربارِ بومیِ Fusion با بقیه‌ی برنامه هم‌خوان نبود). قابلِ‌درگ (کلیک
    و کشیدن از هرجایِ نوار جز دکمه‌ها) برایِ جابه‌جاییِ پنجره، و
    دوبار-کلیک برایِ maximize/restore — دقیقاً رفتارِ متعارفِ تیتربار."""

    def __init__(self, title: str, icon: str, sub_window: "_FramelessMdiSubWindow") -> None:
        super().__init__()
        self.setObjectName("mdiTitleBar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedHeight(42)
        self._sub_window = sub_window
        self._drag_offset = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 0, 14, 0)
        layout.setSpacing(6)

        # طبقِ درخواستِ صریح: دکمه‌هایِ گوشه (بستن/بزرگ‌کردن/کوچک‌کردن) باید
        # سمتِ راستِ فرم باشند، نه چپ — چون چیدمانِ کلیِ برنامه راست‌چین است،
        # این‌ها *اول* به لایه اضافه می‌شوند تا Qt (با آینه‌کردنِ خودکارِ
        # QHBoxLayout در حالتِ RightToLeft) آن‌ها را در سمتِ راست بگذارد؛
        # آیکون/عنوان که آخر اضافه می‌شوند، سمتِ چپ می‌مانند. دکمه‌ی بستن
        # اول از همه اضافه می‌شود تا لبه‌یِ بیرونی (گوشه‌ی راست) باشد —
        # هم‌راستا با قراردادِ متعارفِ «بستن، دورترین دکمه از مرکز».
        self.close_btn = self._make_control_button("✕", theme.rgba(theme.DANGER, 0.16))
        self.close_btn.clicked.connect(sub_window.close)
        layout.addWidget(self.close_btn)

        self.maximize_btn = self._make_control_button("▢", theme.HOVER)
        self.maximize_btn.clicked.connect(self._toggle_maximize)
        layout.addWidget(self.maximize_btn)

        self.minimize_btn = self._make_control_button("—", theme.HOVER)
        self.minimize_btn.clicked.connect(sub_window.showMinimized)
        layout.addWidget(self.minimize_btn)

        layout.addStretch(1)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("mdiTitleLabel")
        layout.addWidget(self.title_label)

        icon_label = QLabel(icon)
        icon_label.setStyleSheet("font-size: 14px; background: transparent;")
        layout.addWidget(icon_label)

    def _make_control_button(self, glyph: str, hover_color: str) -> HoverButton:
        button = HoverButton(glyph, hover_color=hover_color, radius=8, margin=4)
        button.setObjectName("mdiTitleBarButton")
        button.setFixedSize(28, 28)
        return button

    def _toggle_maximize(self) -> None:
        if self._sub_window.isMaximized():
            self._sub_window.showNormal()
        else:
            self._sub_window.showMaximized()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._drag_offset = event.globalPosition().toPoint()
            self._sub_window.mdiArea().setActiveSubWindow(self._sub_window)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag_offset is not None and (event.buttons() & Qt.LeftButton) and not self._sub_window.isMaximized():
            current = event.globalPosition().toPoint()
            delta = current - self._drag_offset
            self._sub_window.move(self._sub_window.pos() + delta)
            self._drag_offset = current
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._drag_offset is not None:
            self._sub_window._save_geometry()
        self._drag_offset = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        self._toggle_maximize()


class _FramelessMdiSubWindow(QMdiSubWindow):
    """زیرپنجره‌یِ MDI بدونِ چارچومِ بومیِ Qt — تیتربارِ خودمان
    (_MdiTitleBar) استفاده می‌شود. نکته‌یِ فنیِ کشف‌شده حینِ توسعه:
    Qt.FramelessWindowHint هم‌زمان تشخیصِ resize-by-edge-drag بومیِ خودِ
    QMdiSubWindow را هم غیرفعال می‌کند (تأییدشده با تست: بعدِ حذفِ
    چارچوب، نشانگرِ ماوس نزدیکِ لبه دیگر به شکلِ تغییرِاندازه برنمی‌گشت)
    — پس این کلاس آن رفتار را دستی، رویِ خودِ زیرپنجره، بازسازی می‌کند.

    با دکمه‌ی × واقعاً بسته/نابود نمی‌شود — فقط مخفی می‌شود، تا نمونه‌یِ
    singletonِ صفحه (با هر state ای که دارد) زنده بماند و با بازکردنِ
    دوباره از ساید‌بار/ریبون همان‌جا که بود ادامه پیدا کند."""

    maximized_changed = Signal(bool)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint)
        self.setMouseTracking(True)
        self.setMinimumSize(_MIN_SUBWINDOW_SIZE)
        self._resize_dir: str | None = None
        self._resize_start_geo = None
        self._resize_start_pos = None
        # طبقِ درخواستِ صریح: جایگاه/اندازه/حالتِ maximize هر فرم به‌ازایِ
        # کدِ صفحه‌اش با QSettings ذخیره می‌شود تا در بازِ بعدیِ برنامه هم
        # (نه فقط همان اجرا) بازیابی شود — MainWindow.open_screen این
        # مقدار را بعدِ ساختِ زیرپنجره ست می‌کند.
        self._screen_name: str | None = None
        # باگِ واقعیِ کشف‌شده حینِ تست: changeEvent با هر WindowStateChange
        # صدا می‌خورَد — حتی وقتی خودِ _restore_or_size_subwindow برنامه‌ای
        # showNormal/showMaximized صدا می‌زند تا حالتِ ذخیره‌شده را برگرداند؛
        # بدونِ این پرچم، همان صدازدنِ بازیابی بلافاصله (با geometryِ هنوز
        # اصلاح‌نشده) دوباره ذخیره می‌شد و مقدارِ درستِ ذخیره‌شده را در هر
        # بازِ بعدی خراب می‌کرد. این پرچم فقط ذخیره‌یِ خودکارِ حینِ بازیابی را
        # خاموش می‌کند، نه امضایِ maximized_changed را (که ساید‌بار/ریبون
        # همچنان باید بر اساسش به‌روز شوند).
        self._restoring = False

    def _save_geometry(self) -> None:
        if self._screen_name is None or self._restoring:
            return
        main_window = getattr(self, "_main_window", None)
        if main_window is not None and getattr(main_window, "_suppressing_geometry_save", False):
            # باگِ واقعیِ کشف‌شده (با گزارشِ صریحِ کاربر): نمایش/بازیابیِ
            # یک زیرپنجره — به‌عنوانِ رفتارِ بومیِ QMdiArea (فقط یک
            # زیرپنجره هم‌زمان می‌تواند maximize نمایش داده شود) — می‌تواند
            # به‌طورِ جانبی حالتِ maximizeِ زیرپنجره‌هایِ *دیگر* را هم عوض
            # کند و همین changeEvent را رویِ آن‌ها هم بفرستد. بدونِ این
            # پرچم، آن تغییرِ ناخواسته این‌جا ذخیره می‌شد و ترجیحِ واقعیِ
            # کاربر برایِ آن فرم را رویِ دیسک خراب می‌کرد — دفعه‌ی بعد که
            # کاربر به همان فرم برمی‌گشت، دیگر maximize نبود.
            return
        settings = QSettings("Peecha", "PeechaERP")
        settings.setValue(f"mdiWindow/{self._screen_name}/maximized", self.isMaximized())
        if not self.isMaximized():
            settings.setValue(f"mdiWindow/{self._screen_name}/geometry", self.geometry())

    def _edge_at(self, pos) -> str | None:
        if self.isMaximized():
            return None
        rect = self.rect()
        left = pos.x() <= _RESIZE_MARGIN
        right = pos.x() >= rect.width() - _RESIZE_MARGIN
        top = pos.y() <= _RESIZE_MARGIN
        bottom = pos.y() >= rect.height() - _RESIZE_MARGIN
        if top and left:
            return "tl"
        if top and right:
            return "tr"
        if bottom and left:
            return "bl"
        if bottom and right:
            return "br"
        if left:
            return "l"
        if right:
            return "r"
        if top:
            return "t"
        if bottom:
            return "b"
        return None

    _CURSOR_BY_EDGE = {
        "l": Qt.SizeHorCursor,
        "r": Qt.SizeHorCursor,
        "t": Qt.SizeVerCursor,
        "b": Qt.SizeVerCursor,
        "tl": Qt.SizeFDiagCursor,
        "br": Qt.SizeFDiagCursor,
        "tr": Qt.SizeBDiagCursor,
        "bl": Qt.SizeBDiagCursor,
    }

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        pos = event.position().toPoint()
        if self._resize_dir is not None and (event.buttons() & Qt.LeftButton):
            self._perform_resize(event.globalPosition().toPoint())
            return
        edge = self._edge_at(pos)
        self.setCursor(self._CURSOR_BY_EDGE.get(edge, Qt.ArrowCursor))
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            edge = self._edge_at(event.position().toPoint())
            if edge is not None:
                self._resize_dir = edge
                self._resize_start_geo = self.geometry()
                self._resize_start_pos = event.globalPosition().toPoint()
                return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._resize_dir is not None:
            self._save_geometry()
        self._resize_dir = None
        super().mouseReleaseEvent(event)

    def _perform_resize(self, global_pos) -> None:
        delta = global_pos - self._resize_start_pos
        geo = QRect(self._resize_start_geo)
        min_w, min_h = _MIN_SUBWINDOW_SIZE.width(), _MIN_SUBWINDOW_SIZE.height()
        if "l" in self._resize_dir:
            new_left = geo.left() + delta.x()
            if geo.right() - new_left >= min_w:
                geo.setLeft(new_left)
        if "r" in self._resize_dir:
            new_right = geo.right() + delta.x()
            if new_right - geo.left() >= min_w:
                geo.setRight(new_right)
        if "t" in self._resize_dir:
            new_top = geo.top() + delta.y()
            if geo.bottom() - new_top >= min_h:
                geo.setTop(new_top)
        if "b" in self._resize_dir:
            new_bottom = geo.bottom() + delta.y()
            if new_bottom - geo.top() >= min_h:
                geo.setBottom(new_bottom)
        self.setGeometry(geo)

    def closeEvent(self, event) -> None:  # noqa: N802
        self._save_geometry()
        event.ignore()
        self.hide()
        self.maximized_changed.emit(False)

    def changeEvent(self, event) -> None:  # noqa: N802
        if event.type() == QEvent.WindowStateChange:
            self.maximized_changed.emit(self.isMaximized())
            self._save_geometry()
        super().changeEvent(event)


class _MdiFormWrapper(QFrame):
    """محتوایِ واقعیِ زیرپنجره — تیتربارِ سفارشی (بالا) + خودِ صفحه
    (پایین). این ویجت، نه خودِ صفحه، رویِ QMdiSubWindow.setWidget
    می‌نشیند.

    باگِ واقعیِ کشف‌شده (با گزارشِ عکسِ واقعیِ کاربر): وقتی این کلاس
    QWidgetِ ساده بود (نه QFrame)، پس‌زمینه‌ی سفیدش از QSS اصلاً رسم
    نمی‌شد — QWidgetِ خام برخلافِ QFrame، پس‌زمینه‌ی استایل‌شیت را بدونِ
    WA_StyledBackground صریح نقاشی نمی‌کند — نتیجه‌اش فرمِ «شفاف» بود که
    محتوایِ فرمِ پشتی (مثلِ نمودارِ دونات یا کارت‌هایِ KPI) از زیرش
    دیده می‌شد."""

    def __init__(self, title: str, icon: str, screen: QWidget, sub_window: _FramelessMdiSubWindow) -> None:
        super().__init__()
        self.setObjectName("mdiFormWrapper")
        self.setAttribute(Qt.WA_StyledBackground, True)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.title_bar = _MdiTitleBar(title, icon, sub_window)
        outer.addWidget(self.title_bar)
        outer.addWidget(screen, stretch=1)


class _ClampingMdiArea(QMdiArea):
    """QMdiAreaِ معمولی، وقتی خودش کوچک‌تر می‌شود (کوچک‌کردنِ پنجره‌یِ
    اصلی از حالتِ maximize، اسنپ‌کردنِ ویندوز به نیمِ صفحه، جمع‌شدنِ
    نوارِ کناری، تغییرِ اندازه‌یِ چندمانیتوره)، زیرپنجره‌هایی را که از
    قبل با اندازه‌یِ بزرگ‌تر باز شده‌اند خودش دوباره اندازه نمی‌دهد —
    آن‌ها همان اندازه‌یِ قبلی را نگه می‌دارند و فقط یک اسکرول‌بار رویِ
    خودِ ناحیه‌یِ MDI ظاهر می‌شود؛ از دیدِ کاربر این دقیقاً همان چیزی‌ست
    که به‌عنوانِ «دکمه‌هایِ پایینِ فرم زیرِ تسک‌بار/از دید رفتن» گزارش
    می‌شود — چون MainWindow خودش به‌درستی clamp می‌شود (ر.ک.
    _clamp_geometry_to_available_screen)، اما این clamp تا امروز فقط
    یک‌بار، در لحظه‌یِ بازشدن/بازیابیِ هر زیرپنجره اجرا می‌شد
    (_restore_or_size_subwindow)، نه در هر resizeِ بعدیِ خودِ ناحیه‌یِ
    MDI. این‌جا با override کردنِ resizeEvent، در *هر* تغییرِ اندازه‌ای
    همه‌یِ زیرپنجره‌هایِ غیرِmaximize/غیرِminimize را دوباره به داخلِ
    مرزهایِ تازه می‌کشیم — با همان تابعِ مشترکِ _clamp_rect_to_area که
    MainWindow._clamp_to_mdi_area هم استفاده می‌کند، تا دو پیاده‌سازیِ
    جدا از هم عقب نمانند."""

    def resizeEvent(self, event) -> None:  # noqa: N802 — نامِ متدِ Qt
        super().resizeEvent(event)
        area = self.viewport().rect()
        for sub_window in self.subWindowList():
            if sub_window.isMaximized() or sub_window.isMinimized():
                continue
            geo = sub_window.geometry()
            clamped = _clamp_rect_to_area(geo, area)
            if clamped != geo:
                sub_window.setGeometry(clamped)

    def minimumSizeHint(self):  # noqa: N802 — نامِ متدِ Qt
        # ریشه‌یِ واقعیِ باگِ تکرارشوندهٔ «حتی بعدِ ثابت‌کردنِ تسک‌بار،
        # بازهم فرمِ اصلی زیرش می‌رود»: به‌طورِ پیش‌فرض، QMdiArea مینیمم
        # سایزِ خودش را از رویِ بزرگ‌ترین زیرپنجره‌یِ بازِ داخلش (مثلاً
        # فرمی با فیلدهایِ زیاد که minimumSizeHintِ طبیعیِ بزرگی دارد)
        # محاسبه می‌کند و این عدد از طریقِ لایه‌هایِ تودرتو تا خودِ
        # MainWindow بالا می‌رود — یعنی هرچقدر هم کلمپِ availableGeometry
        # را صدا بزنیم، Qt خودش اجازه‌یِ کوچک‌ترشدنِ پنجره از این حدِ
        # مینیمم را نمی‌دهد و مازادش زیرِ تسک‌بار می‌ماند. چون این کلاس
        # از قبل دقیقاً برایِ همین حالت (زیرپنجره بزرگ‌تر از ناحیه‌یِ MDI)
        # اسکرول‌بار نشان می‌دهد، مینیمم‌سایزِ خودش را مستقل از
        # محتوایِ زیرپنجره‌ها نگه می‌داریم تا هیچ‌وقت این محدودیت به
        # MainWindow تحمیل نشود.
        return QSize(200, 150)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("پیچا")
        # باگِ واقعیِ گزارش‌شده: در حالتِ تمام‌صفحه، پایینِ فرم‌ها زیرِ
        # نوارِ وظیفه‌یِ ویندوز می‌رفت. اندازه‌یِ پیش‌فرضِ ۱۴۴۰×۹۰۰ روی
        # مانیتورهایی با ارتفاعِ نمایشیِ کمتر (مثلاً ۹۰۰pxِ کامل، که بعدِ
        # کسرِ نوارِ وظیفه چیزی حدودِ ۸۵۰px می‌ماند) از ابتدا از محدوده‌یِ
        # قابل‌مشاهده بزرگ‌تر بود؛ maximize کردنِ بعدی هم روی بعضی
        # پیکربندی‌هایِ ویندوز (DPI/چندمانیتوره) کاملاً به availableGeometry
        # (که نوارِ وظیفه را کم می‌کند) احترام نمی‌گذارد. هردو با کلمپ‌کردنِ
        # صریح به availableGeometry (به‌جایِ geometry/screenGeometریِ خام)
        # رفع می‌شوند.
        self._clamping_geometry = False
        self._watched_screen: QScreen | None = None
        self._screen_changed_connected = False
        self._last_known_available_geometry: QRect | None = None
        # طبقِ گزارشِ تکرارشوندهٔ کاربر («تسک‌بار را ثابت کردم، بازهم فرم
        # زیرش رفت»): QScreen.availableGeometryChanged رویِ ویندوز برایِ
        # toggleِ auto-hideِ نوارِ وظیفه به‌طورِ شناخته‌شده‌ای نامطمئن است —
        # گاهی اصلاً شلیک نمی‌شود، چون خودِ ویندوز پیامِ WM_SETTINGCHANGE
        # را همیشه به‌موقع/به‌طورِ کامل به Qt نمی‌رساند. برایِ همین، به‌جایِ
        # تکیه‌یِ صرف به آن سیگنال، یک تایمرِ pollingِ سبک هم اضافه شده که
        # مستقل از سیگنال، هر ۱ ثانیه availableGeometryِ واقعی را می‌خواند
        # و اگر با آخرین مقدارِ شناخته‌شده فرق داشت، بلافاصله کلمپ می‌کند —
        # این تنها راهِ قابل‌اطمینان برایِ گرفتنِ این حالتِ خاص است.
        self._geometry_poll_timer = QTimer(self)
        self._geometry_poll_timer.setInterval(1000)
        self._geometry_poll_timer.timeout.connect(self._poll_available_geometry)
        self._geometry_poll_timer.start()
        self.resize(1440, 900)
        self._clamp_geometry_to_available_screen()

        self._screens: dict[str, QWidget] = {}
        self._sidebar_groups: dict[str, _SidebarGroup] = {}
        self._mdi_subwindows: dict[str, _FramelessMdiSubWindow] = {}
        self._current_screen_code: str | None = None
        self._company_options: list[companies_service.CompanyRow] = []
        self._cascade_index = 0
        self._closing_for_logout = False
        # طبقِ گزارشِ صریح («فرمِ قبلی با بازشدنِ فرمِ تازه جمع می‌شود»):
        # نگاهِ کنید به توضیحِ کاملِ این پرچم در open_screen.
        self._suppressing_geometry_save = False

        central = QWidget()
        self._central = central
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        outer.addWidget(self._build_header())
        outer.addWidget(self._build_quick_access_bar())

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self._build_sidebar())
        body.addWidget(self._build_mdi_area(), stretch=1)
        outer.addLayout(body, stretch=1)
        self._outer_layout = outer
        self._body_layout = body

        self._register_screens()
        self.open_screen("dashboard")

        # طبقِ درخواستِ صریح: F2 در همه‌جایِ برنامه کلیدِ ذخیره/تایید باشد —
        # به‌جایِ افزودنِ یک QShortcutِ جدا به تک‌تکِ فرم‌ها، یک فیلترِ
        # رویدادِ سراسری رویِ QApplication نصب می‌شود که دکمه‌یِ اصلیِ
        # (objectName == "primaryButton") فرمِ زیرپنجره‌یِ فعال (یا دیالوگِ
        # مودالِ بازِ فعلی) را پیدا و کلیک می‌کند.
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

    def _clamp_geometry_to_available_screen(self) -> None:
        """پنجره را داخلِ availableGeometryِ صفحه‌یِ فعلی نگه می‌دارد —
        یعنی هیچ‌وقت زیرِ نوارِ وظیفه (یا هر ناحیه‌یِ رزروشده‌یِ دیگرِ
        سیستم‌عامل) نمی‌رود، برخلافِ geometry/screenGeometریِ خام."""
        screen = self.screen() or QApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        width = min(self.width(), available.width())
        height = min(self.height(), available.height())
        x = available.x() + max(0, (available.width() - width) // 2)
        y = available.y() + max(0, (available.height() - height) // 2)
        self.setGeometry(x, y, width, height)

    def _ensure_screen_geometry_watcher(self) -> None:
        """طبقِ گزارشِ صریح: اگر کاربر حالتِ auto-hideِ نوارِ وظیفه را در
        حینِ بازبودنِ برنامه خاموش کند (یا هر تغییرِ دیگری در
        availableGeometryِ صفحه رخ دهد)، هیچ‌کدام از رویدادهایِ خودِ
        پنجره (resizeEvent/changeEvent) شلیک نمی‌شوند — چون اندازه/حالتِ
        خودِ پنجره تغییر نکرده، فقط ناحیه‌یِ رزروشده‌یِ سیستم‌عامل عوض شده.
        برایِ همین باید مستقیماً به QScreen.availableGeometryChanged
        گوش داد. این‌جا وصل می‌شود (نه در __init__، چونِ self.screen()
        پیش از نمایشِ واقعیِ پنجره قابلِ‌اتکا نیست) و اگر پنجره به
        مانیتورِ دیگری منتقل شود هم خودش را دوباره به صفحه‌یِ تازه وصل
        می‌کند."""
        screen = self.screen() or QApplication.primaryScreen()
        if screen is None:
            return
        if screen is not self._watched_screen:
            if self._watched_screen is not None:
                try:
                    self._watched_screen.availableGeometryChanged.disconnect(
                        self._on_available_geometry_changed
                    )
                except (RuntimeError, TypeError):
                    pass
            screen.availableGeometryChanged.connect(self._on_available_geometry_changed)
            self._watched_screen = screen
        window_handle = self.windowHandle()
        if window_handle is not None and not self._screen_changed_connected:
            window_handle.screenChanged.connect(lambda _screen: self._ensure_screen_geometry_watcher())
            self._screen_changed_connected = True

    def _on_available_geometry_changed(self, _available: QRect) -> None:
        QTimer.singleShot(0, self._clamp_geometry_to_available_screen)

    def _poll_available_geometry(self) -> None:
        """پشتیبانِ سیگنالِ availableGeometryChanged (ر.ک. توضیحِ کاملِ
        دلیلِ نیاز به این تایمر در __init__)."""
        screen = self.screen() or QApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        if self._last_known_available_geometry is not None and available != self._last_known_available_geometry:
            self._clamp_geometry_to_available_screen()
        self._last_known_available_geometry = available

    def changeEvent(self, event) -> None:  # noqa: N802 — نامِ متدِ Qt
        # باگِ واقعیِ گزارش‌شده: رویِ بعضی پیکربندی‌هایِ ویندوز، maximize
        # بومیِ Qt کاملاً availableGeometry را رعایت نمی‌کند و پایینِ
        # پنجره زیرِ نوارِ وظیفه می‌رود؛ این‌جا به‌طورِ صریح آن را با
        # availableGeometry جایگزین می‌کنیم. طبقِ گزارشِ تکرارشوندهٔ
        # کاربر («هنوز هم زیرِ تسک‌بار می‌رود») حتی این تعویضِ صریح هم
        # وقتی showMaximized() رویِ پنجره‌ای که هنوز هیچ‌وقت show() نشده
        # صدا زده می‌شود (دقیقاً همان‌طور که login_window.py می‌کند) کافی
        # نبود — چونِ تکمیلِ maximizeِ بومیِ ویندوز برایِ چنین پنجره‌ای
        # می‌تواند بعد از این callback هم ادامه پیدا کند و geometryِ ما را
        # دوباره بازنویسی کند. برایِ همین، کلمپ را یک تیکِ رویداد به تعویق
        # می‌اندازیم (QTimer.singleShot(0, ...)) تا *بعدِ* تکمیلِ کاملِ
        # maximizeِ بومی اجرا شود، نه هم‌زمان با آن.
        if event.type() == QEvent.WindowStateChange and self.isMaximized():
            QTimer.singleShot(0, self._clamp_geometry_to_available_screen)
        super().changeEvent(event)

    def showEvent(self, event) -> None:  # noqa: N802 — نامِ متدِ Qt
        # self.screen() پیش از نمایشِ واقعیِ پنجره (در __init__) قابلِ‌اتکا
        # نیست — پس کلمپِ availableGeometry باید دوباره، این‌بار بعدِ
        # واقعاً نمایان‌شدن، انجام شود.
        super().showEvent(event)
        if not self.isMaximized():
            self._clamp_geometry_to_available_screen()
        self._ensure_screen_geometry_watcher()
        screen = self.screen() or QApplication.primaryScreen()
        if screen is not None:
            self._last_known_available_geometry = screen.availableGeometry()

    def resizeEvent(self, event) -> None:  # noqa: N802 — نامِ متدِ Qt
        # طبقِ گزارشِ تکرارشونده‌یِ کاربر («بازهم فرم‌ها زیرِ نوارِ وظیفه
        # می‌روند»): تکیه‌یِ صرف بر changeEvent/WindowStateChange کافی نبود
        # — چون بعضی مدیرهایِ پنجره (به‌خصوص در چندمانیتوره/تغییرِ DPI یا
        # snap-to-fill) اندازه‌یِ پنجره را مستقیماً به اندازه‌یِ کاملِ صفحه
        # (نه availableGeometry) تغییر می‌دهند بدونِ اینکه پرچمِ رسمیِ
        # Qt.WindowMaximized فعال شود؛ در آن حالت isMaximized() هنوز False
        # است و آن مسیرِ قبلی اصلاً اجرا نمی‌شد. این‌جا، مستقل از
        # isMaximized()، در *هر* تغییرِ اندازه‌ای بررسی می‌شود که آیا
        # geometryِ فعلی از availableGeometry فراتر رفته — اگر رفته باشد،
        # فوراً کلمپ می‌شود.
        super().resizeEvent(event)
        self._clamp_if_overflowing_available_screen()

    def _clamp_if_overflowing_available_screen(self) -> None:
        if self._clamping_geometry:
            return
        screen = self.screen() or QApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        geo = self.geometry()
        if available.contains(geo):
            return
        width = min(geo.width(), available.width())
        height = min(geo.height(), available.height())
        x = min(max(geo.x(), available.x()), available.x() + available.width() - width)
        y = min(max(geo.y(), available.y()), available.y() + available.height() - height)
        self._clamping_geometry = True
        try:
            self.setGeometry(x, y, width, height)
        finally:
            self._clamping_geometry = False

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 — نامِ متدِ Qt
        if event.type() == QEvent.KeyPress and event.key() == Qt.Key_F2:
            target = QApplication.activeModalWidget() or (
                self.mdi_area.activeSubWindow().widget() if self.mdi_area.activeSubWindow() else self
            )
            # طبقِ باگِ کشف‌شده («F2 دیگر کار نمی‌کند»): دورِ تبدیلِ دکمه‌ها به
            # آیکون+تولتیپ (بازرگانی/انبار/حسابداری/...)، objectNameِ دکمه‌ی
            # اصلی را از "primaryButton" به "primaryIconButton" تغییر داد،
            # بدونِ به‌روزرسانیِ همین فیلتر — یعنی F2 در تقریباً همه‌ی
            # فرم‌هایِ تراکنشی/تنظیماتِ اصلیِ برنامه (بیش از ۴۰ فایل) اثری
            # نداشت. حالا هر دو نامِ objectName پذیرفته می‌شوند.
            for button in target.findChildren(QPushButton):
                if button.objectName() in ("primaryButton", "primaryIconButton") and button.isVisible() and button.isEnabled():
                    button.click()
                    return True
            return False
        return super().eventFilter(obj, event)

    # --- سوییچِ زنده‌یِ تمِ روشن/تیره ---------------------------------------
    def _on_theme_toggled(self, light_checked: bool) -> None:
        """طبقِ خواسته‌یِ صریح: سوییچِ واقعیِ رفت‌وبرگشتی بینِ تمِ روشن/تیره،
        بدونِ نیاز به ری‌استارتِ برنامه. `theme.set_theme_mode` خودش
        QPalette/QSS/QSettings را هندل می‌کند و یک پاسِ repolish رویِ
        همه‌یِ ویجت‌هایِ زنده می‌زند (کافی برایِ اکثرِ سطحِ برنامه — جدول‌ها،
        فیلدها، دکمه‌ها، کارت‌ها، تب‌ها). آنچه repolish پوشش نمی‌دهد
        (HoverButtonِ سرتیترها/آیتم‌هایِ ساید‌بار که رنگِ هاورشان را در
        __init__ منجمد می‌کنند) با بازسازیِ درجایِ کرومِ هدر/ریبون/ساید‌بار
        در `_rebuild_chrome()` رفع می‌شود."""
        app = QApplication.instance()
        theme.set_theme_mode(app, dark=not light_checked)
        self._rebuild_chrome()
        for screen in self._screens.values():
            refresh = getattr(screen, "refresh", None)
            if callable(refresh):
                refresh()
        self.mdi_area.setBackground(QBrush(QColor(theme.BACKGROUND)))

    def _rebuild_chrome(self) -> None:
        """هدر/ریبون/ساید‌بار را با مقادیرِ تازه‌یِ theme.* دوباره می‌سازد
        و به‌جایِ نسخه‌هایِ قدیمی در همان جایگاهِ layout می‌نشاند — چون
        HoverButton (سرتیترها/آیتم‌هایِ ساید‌بار، دکمه‌یِ گیر) رنگِ
        پس‌زمینه‌یِ هاور/فعالش را در __init__ منجمد می‌کند."""
        old_header, old_quick_access, old_sidebar = (
            self._header_scroll, self._quick_access_scroll, self._sidebar_scroll,
        )
        active_leaf = self._current_screen_code
        active_module = self._quick_access_module_code

        new_header = self._build_header()
        self._outer_layout.replaceWidget(old_header, new_header)
        old_header.deleteLater()

        new_quick_access = self._build_quick_access_bar()
        self._outer_layout.replaceWidget(old_quick_access, new_quick_access)
        old_quick_access.deleteLater()

        new_sidebar = self._build_sidebar()
        self._body_layout.replaceWidget(old_sidebar, new_sidebar)
        old_sidebar.deleteLater()

        # طبقِ الگویِ خودِ open_screen: بازگردانیِ متن/گزینه‌هایِ کمبوهایِ
        # هدر (شرکت/سالِ مالی/زبان)، ریبونِ ماژولِ فعلی، و آیتمِ فعالِ
        # ساید‌بار — چون کمبو/ریبون/ساید‌بارِ تازه‌ساخته‌شده خالی یا رویِ
        # پیش‌فرضِ داشبورد شروع می‌شوند.
        self.load_context_switcher()
        if active_module and active_module != "dashboard":
            self._quick_access_module_code = None
            self._refresh_quick_access_bar(active_module)
        if active_leaf:
            for group in self._sidebar_groups.values():
                group.set_active_leaf(active_leaf)

    # --- هدر --------------------------------------------------------------
    def _build_header(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setObjectName("headerScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFixedHeight(72)

        header = QWidget()
        header.setObjectName("headerBar")
        layout = QHBoxLayout(header)
        layout.setContentsMargins(24, 8, 24, 8)
        layout.setSpacing(16)

        brand_row = QHBoxLayout()
        brand_row.setSpacing(10)
        brand_mark = QLabel()
        brand_mark.setFixedSize(34, 34)
        brand_mark.setAlignment(Qt.AlignCenter)
        brand_mark.setPixmap(theme.logo_pixmap(20, theme.PRIMARY))
        brand_mark.setStyleSheet(
            f"background-color: {theme.rgba(theme.ACCENT, 0.18)}; "
            f"border: 1px solid {theme.rgba(theme.ACCENT, 0.35)}; "
            f"border-radius: 11px;"
        )
        brand_row.addWidget(brand_mark)

        brand = QLabel("پیچا")
        brand_font = QFont()
        brand_font.setPointSize(15)
        brand_font.setBold(True)
        brand.setFont(brand_font)
        brand.setStyleSheet(f"color: {theme.TEXT_PRIMARY};")
        brand_row.addWidget(brand)
        layout.addLayout(brand_row)

        divider0 = QFrame()
        divider0.setFrameShape(QFrame.VLine)
        divider0.setFixedHeight(24)
        divider0.setStyleSheet(f"color: {theme.DIVIDER};")
        layout.addWidget(divider0)

        self.field_help_toggle = QToolButton()
        self.field_help_toggle.setObjectName("fieldHelpToggle")
        self.field_help_toggle.setCheckable(True)
        self.field_help_toggle.setChecked(field_help_is_enabled())
        self.field_help_toggle.setCursor(Qt.PointingHandCursor)
        self.field_help_toggle.setText("⚙")
        self.field_help_toggle.setToolTip("راهنمایِ فیلدها را نشان بده یا مخفی کن")
        self.field_help_toggle.setStyleSheet(
            "#fieldHelpToggle {"
            "   border: none; border-radius: 14px; padding: 4px 10px;"
            f"   font-size: 15px; color: {theme.TEXT_SECONDARY}; background: transparent;"
            "}"
            f"#fieldHelpToggle:checked {{ color: {theme.WARNING}; background: {theme.rgba(theme.WARNING, 0.16)}; }}"
            f"#fieldHelpToggle:hover {{ background: {theme.rgba(theme.WARNING, 0.10)}; }}"
        )
        self.field_help_toggle.toggled.connect(set_field_help_enabled)
        layout.addWidget(self.field_help_toggle)

        # طبقِ خواسته‌یِ صریح: سوییچِ زنده‌یِ روشن/تیره — گلیف نشان‌دهنده‌یِ
        # حالتِ *مقصد* است (اگر الان تیره‌ایم، آفتاب یعنی «برو روشن»),
        # هم‌الگو با field_help_toggle (همان objectName-styling).
        self.theme_toggle = QToolButton()
        self.theme_toggle.setObjectName("fieldHelpToggle")
        self.theme_toggle.setCheckable(True)
        self.theme_toggle.setChecked(not theme.is_dark_mode())
        self.theme_toggle.setCursor(Qt.PointingHandCursor)
        self.theme_toggle.setText("☀" if theme.is_dark_mode() else "🌙")
        self.theme_toggle.setToolTip("رفتن به حالتِ روشن" if theme.is_dark_mode() else "رفتن به حالتِ تیره")
        self.theme_toggle.setStyleSheet(
            "#fieldHelpToggle {"
            "   border: none; border-radius: 14px; padding: 4px 10px;"
            f"   font-size: 15px; color: {theme.TEXT_SECONDARY}; background: transparent;"
            "}"
            f"#fieldHelpToggle:hover {{ background: {theme.rgba(theme.PRIMARY, 0.10)}; }}"
        )
        self.theme_toggle.toggled.connect(self._on_theme_toggled)
        layout.addWidget(self.theme_toggle)

        self.search_field = QLineEdit()
        self.search_field.setPlaceholderText("⌕  جستجو در سیستم...")
        self.search_field.setFixedWidth(320)
        layout.addWidget(self.search_field)

        layout.addStretch(1)

        self.language_combo = QComboBox()
        self.language_combo.setFixedWidth(110)
        self.language_combo.currentIndexChanged.connect(self._on_language_changed)
        layout.addWidget(self.language_combo)

        self.fiscal_year_combo = QComboBox()
        self.fiscal_year_combo.setFixedWidth(140)
        layout.addWidget(self.fiscal_year_combo)

        self.company_combo = QComboBox()
        self.company_combo.setFixedWidth(180)
        self.company_combo.currentIndexChanged.connect(self._on_company_changed)
        layout.addWidget(self.company_combo)

        divider = QFrame()
        divider.setFrameShape(QFrame.VLine)
        divider.setFixedHeight(28)
        divider.setStyleSheet(f"color: {theme.DIVIDER};")
        layout.addWidget(divider)

        self.avatar_badge = QLabel("")
        self.avatar_badge.setObjectName("avatarBadge")
        self.avatar_badge.setFixedSize(32, 32)
        self.avatar_badge.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.avatar_badge)

        self.user_label = QLabel("")
        user_font = QFont()
        user_font.setBold(True)
        self.user_label.setFont(user_font)
        layout.addWidget(self.user_label)

        self.open_windows_button = QToolButton()
        self.open_windows_button.setObjectName("fieldHelpToggle")
        self.open_windows_button.setText("🗔")
        self.open_windows_button.setToolTip("فرم‌هایِ بازِ جاری")
        self.open_windows_button.setCursor(Qt.PointingHandCursor)
        self.open_windows_button.setPopupMode(QToolButton.InstantPopup)
        self.open_windows_menu = QMenu(self.open_windows_button)
        self.open_windows_menu.aboutToShow.connect(self._populate_open_windows_menu)
        self.open_windows_button.setMenu(self.open_windows_menu)
        layout.addWidget(self.open_windows_button)

        logout_button = QPushButton("خروج")
        logout_button.setObjectName("flatButton")
        logout_button.clicked.connect(self._logout)
        layout.addWidget(logout_button)

        scroll.setWidget(header)

        header_shadow = QGraphicsDropShadowEffect(scroll)
        header_shadow.setBlurRadius(24)
        header_shadow.setXOffset(0)
        header_shadow.setYOffset(4)
        header_shadow.setColor(QColor(0, 0, 0, 110))
        scroll.setGraphicsEffect(header_shadow)

        self._header_scroll = scroll
        return scroll

    # --- ریبونِ میان‌برهایِ پرکاربرد -------------------------------------------
    def _build_quick_access_bar(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setObjectName("quickAccessScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFixedHeight(96)

        bar = QWidget()
        bar.setObjectName("quickAccessBar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(20, 8, 20, 8)
        layout.setSpacing(10)

        scroll.setWidget(bar)
        self._quick_access_scroll = scroll
        self._quick_access_bar = bar
        self._quick_access_layout = layout
        self._quick_access_module_code: str | None = None
        self._refresh_quick_access_bar("dashboard")
        return scroll

    def _quick_access_settings_key(self, module_code: str) -> str:
        return f"quickAccess/{module_code}"

    def _quick_access_codes_for_module(self, module_code: str) -> list[str]:
        """کدهایِ میان‌برهایِ همین ماژول — شخصی‌سازیِ کاربر (اگر ذخیره شده)
        وگرنه فهرستِ پیش‌فرضِ همان ماژول."""
        settings = QSettings("Peecha", "PeechaERP")
        stored = settings.value(self._quick_access_settings_key(module_code), None)
        if stored is not None:
            try:
                return json.loads(stored)
            except (TypeError, ValueError):
                pass
        default_items = DEFAULT_QUICK_ACCESS_BY_MODULE.get(module_code, [])
        return [code for code, _icon in default_items]

    def _refresh_quick_access_bar(self, module_code: str) -> None:
        """ریبون را با میان‌برهایِ مربوط به ماژولِ فعلی دوباره می‌سازد —
        طبقِ درخواستِ صریح، ریبون باید مرتبط با ماژولی باشد که در ساید‌بار
        باز شده، نه یک فهرستِ ثابتِ سراسری."""
        if module_code == self._quick_access_module_code:
            return
        self._quick_access_module_code = module_code

        while self._quick_access_layout.count():
            child = self._quick_access_layout.takeAt(0)
            widget = child.widget()
            if widget is not None:
                # takeAt فقط از خودِ layout حذف می‌کند؛ ویجت هنوز فرزندِ bar
                # است و تا وقتی حلقه‌ی رویداد deleteLaterِ آن را واقعاً اجرا
                # نکند، ممکن است لحظه‌ای رویِ ریبونِ تازه هم دیده شود — پس
                # صراحتاً hide/بی‌والد هم می‌کنیم تا فوراً از صفحه برود.
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()

        flat_items_by_code = {i["code"]: i for i in _flatten_nav_items()}
        icon_by_code = dict(DEFAULT_QUICK_ACCESS_BY_MODULE.get(module_code, []))
        codes = self._quick_access_codes_for_module(module_code)
        for code in codes:
            item = flat_items_by_code.get(code)
            if item is None:
                continue
            icon = icon_by_code.get(code, "📄")
            tile = _QuickAccessTile(icon, item["label"], lambda c=code: self.open_screen(c))
            self._quick_access_layout.addWidget(tile)

        self._quick_access_layout.addStretch(1)

        if module_code in DEFAULT_QUICK_ACCESS_BY_MODULE and _leaf_nav_children_for_module(module_code):
            config_button = HoverButton("⚙", hover_color=theme.HOVER, radius=8, margin=4)
            config_button.setObjectName("quickAccessConfigButton")
            config_button.setFixedSize(30, 30)
            config_button.setToolTip("تنظیمِ میان‌برهایِ این ماژول")
            config_button.clicked.connect(lambda _checked=False, m=module_code: self._open_quick_access_config(m))
            self._quick_access_layout.addWidget(config_button)

    def _open_quick_access_config(self, module_code: str) -> None:
        """طبقِ درخواستِ صریح («قابلیتِ کم‌وزیادکردنِ دکمه‌هایِ ریبون»):
        همه‌یِ آیتم‌هایِ برگِ همین ماژول را با تیک نشان می‌دهد — کاربر
        هرکدام را می‌تواند اضافه/کم کند."""
        leaves = _leaf_nav_children_for_module(module_code)
        if not leaves:
            return
        current_codes = set(self._quick_access_codes_for_module(module_code))

        dialog = QDialog(self)
        dialog.setWindowTitle("تنظیمِ میان‌برهایِ ریبون")
        dialog.setLayoutDirection(Qt.RightToLeft)
        layout = QVBoxLayout(dialog)
        hint = QLabel("آیتم‌هایی که می‌خواهید در ریبونِ این ماژول به‌صورتِ میان‌بر دیده شوند را تیک بزنید.")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        checkboxes: list[tuple[str, QCheckBox]] = []
        for leaf in leaves:
            checkbox = QCheckBox(leaf["label"])
            checkbox.setChecked(leaf["code"] in current_codes)
            layout.addWidget(checkbox)
            checkboxes.append((leaf["code"], checkbox))

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec() != QDialog.Accepted:
            return

        selected_codes = [code for code, checkbox in checkboxes if checkbox.isChecked()]
        settings = QSettings("Peecha", "PeechaERP")
        settings.setValue(self._quick_access_settings_key(module_code), json.dumps(selected_codes))
        self._quick_access_module_code = None  # مجبور به بازسازی
        self._refresh_quick_access_bar(module_code)

    # --- ساید‌بار (ناوبریِ اصلی) ------------------------------------------------
    def _build_sidebar(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setObjectName("sidebarScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setFixedWidth(268)

        container = QWidget()
        container.setObjectName("sidebarContainer")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(10, 12, 10, 12)
        layout.setSpacing(2)

        for item in NAV_ITEMS:
            gear_click = None
            if item["code"] in _SETTINGS_TAB_BY_GROUP_CODE:
                idx = _SETTINGS_TAB_BY_GROUP_CODE[item["code"]]
                gear_click = lambda _checked=False, i=idx: self.open_screen(
                    "SETTINGS", then=lambda screen: screen.select_tab(i)
                )
            group = _SidebarGroup(item, _NAV_ICONS.get(item["code"], "•"), self.open_screen, gear_click)
            layout.addWidget(group)
            self._sidebar_groups[item["code"]] = group

        layout.addStretch(1)
        scroll.setWidget(container)
        self._sidebar_scroll = scroll
        return scroll

    # --- ناحیه‌ی کاریِ MDI (فرم‌هایِ شناور) --------------------------------------
    def _build_mdi_area(self) -> QWidget:
        self.mdi_area = _ClampingMdiArea()
        self.mdi_area.setObjectName("mdiArea")
        self.mdi_area.setActivationOrder(QMdiArea.ActivationHistoryOrder)
        self.mdi_area.setViewMode(QMdiArea.SubWindowView)
        # QMdiArea پس‌زمینه‌اش را از رویِ یک QBrushِ اختصاصی رسم می‌کند، نه
        # background-color در QSS (آن قانون بی‌اثر می‌ماند) — این‌جا صریحاً
        # ست می‌شود تا با پالتِ روشنِ برنامه هماهنگ باشد، نه خاکستریِ پیش‌فرضِ Fusion.
        self.mdi_area.setBackground(QBrush(QColor(theme.BACKGROUND)))
        self.mdi_area.subWindowActivated.connect(self._on_subwindow_activated)
        return self.mdi_area

    def _on_subwindow_activated(self, active_sub_window) -> None:
        """طبقِ نگرانیِ صریح («وقتی همه‌ی فرم‌ها روی هم بازِ می‌شوند به
        مشکل نمی‌خورد؟»): فرمِ درحالِ‌فعالیت با ته‌رنگِ اکسنت روی تیتربارش
        از بقیه‌ی فرم‌هایِ بازِ پشتِ‌سرش متمایز می‌شود — تا در انبوهِ
        پنجره‌هایِ روی‌هم، همیشه واضح باشد کدام فرم الان کارِ کاربر است."""
        for sub_window in self.mdi_area.subWindowList():
            wrapper = sub_window.widget()
            title_bar = getattr(wrapper, "title_bar", None)
            if title_bar is None:
                continue
            title_bar.setProperty("active", sub_window is active_sub_window)
            title_bar.style().unpolish(title_bar)
            title_bar.style().polish(title_bar)
        self._update_chrome_visibility()

    def _update_chrome_visibility(self, *_args) -> None:
        """طبقِ گزارشِ صریح («فرم‌ها وقتی تمام‌صفحه می‌شن، فقط تویِ یک
        کانتینرِ محدود جا می‌گیرن، چون هدرِ برنامه و ساید‌بار همچنان
        نمایش داده می‌شن»): وقتی حداقل یک فرمِ شناور maximize شده باشد،
        ریبونِ میان‌بر و ساید‌بار موقتاً مخفی می‌شوند تا ناحیه‌یِ MDI کلِ
        عرض/ارتفاعِ زیرِ هدرِ اصلی را در اختیارِ فرمِ maximize‌شده بگذارد؛
        با خارج‌شدن از حالتِ maximize (یا بستنِ فرم)، هردو دوباره
        نمایش داده می‌شوند."""
        any_maximized = any(
            sw.isVisible() and sw.isMaximized() for sw in self._mdi_subwindows.values()
        )
        self._quick_access_scroll.setVisible(not any_maximized)
        self._sidebar_scroll.setVisible(not any_maximized)

    def _populate_open_windows_menu(self) -> None:
        """طبقِ نگرانیِ صریح دربابِ انبوهِ فرم‌هایِ روی‌هم — فهرستِ همه‌ی
        فرم‌هایِ بازِ جاری (با امکانِ کلیک برایِ رفتنِ مستقیم به هرکدام)،
        بدونِ نیازِ کاربر به جابه‌جاکردنِ دستیِ پنجره‌ها برایِ پیداکردنِ
        فرمِ موردِنظر."""
        self.open_windows_menu.clear()
        visible_subs = [sw for sw in self.mdi_area.subWindowList() if sw.isVisible()]
        if not visible_subs:
            empty_action = self.open_windows_menu.addAction("هیچ فرمی باز نیست")
            empty_action.setEnabled(False)
            return

        active = self.mdi_area.activeSubWindow()
        for sub_window in visible_subs:
            marker = "◉ " if sub_window is active else "○ "
            action = self.open_windows_menu.addAction(marker + sub_window.windowTitle())
            action.triggered.connect(lambda _checked=False, sw=sub_window: self._focus_subwindow(sw))

        self.open_windows_menu.addSeparator()
        cascade_action = self.open_windows_menu.addAction("مرتب‌سازیِ آبشاری")
        cascade_action.triggered.connect(self.mdi_area.cascadeSubWindows)
        tile_action = self.open_windows_menu.addAction("مرتب‌سازیِ کاشی‌ای")
        tile_action.triggered.connect(self.mdi_area.tileSubWindows)

    def _focus_subwindow(self, sub_window: QMdiSubWindow) -> None:
        sub_window.show()
        sub_window.raise_()
        self.mdi_area.setActiveSubWindow(sub_window)
        # باگِ واقعیِ کشف‌شده (با گزارشِ عکسِ واقعیِ کاربر): برخلافِ
        # open_screen (که همیشه refresh را دوباره صدا می‌زند)، سوییچ به
        # یک زیرپنجره‌یِ *ازقبل‌بازِ* از طریقِ منویِ «پنجره‌های باز» هرگز
        # refresh نمی‌کرد — یعنی مثلاً اگر کاربر فرمِ سند را باز نگه دارد،
        # برود ارزِ تازه‌ای برایِ شرکت فعال کند، و با همین منو به فرمِ سند
        # برگردد (نه با کلیک دوباره روی نوارِ کناری)، کمبویِ «ارزِ سند»
        # همچنان دیتایِ کهنه/خالیِ لحظه‌یِ بازشدنِ اولیه را نشان می‌داد.
        screen_name = getattr(sub_window, "_screen_name", None)
        screen = self._screens.get(screen_name) if screen_name else None
        if screen is not None and hasattr(screen, "refresh"):
            screen.refresh()

    def _logout(self) -> None:
        from peecha.ui.login_window import LoginWindow
        from peecha.ui.main import get_font_family

        session.log_out()
        self._login_window = LoginWindow(get_font_family())
        self._login_window.show()
        # طبقِ درخواستِ صریح: پیغامِ تأییدِ خروج فقط برایِ خروجِ کاملِ از
        # برنامه (بستنِ پنجره‌ی اصلی) است، نه برایِ خروج از حساب (که خودش
        # یک اقدامِ آگاهانه با کلیکِ دکمه‌ی «خروج» است و صفحه‌ی ورود را
        # از قبل نشان داده) — این پرچم closeEvent را از نمایشِ دوباره‌یِ
        # تأیید در این حالت منصرف می‌کند.
        self._closing_for_logout = True
        self.close()

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._closing_for_logout:
            event.accept()
            return
        box = QMessageBox(self)
        box.setWindowTitle("خروج از برنامه")
        box.setText("آیا می‌خواهید از برنامه خارج شوید؟")
        box.setIcon(QMessageBox.Question)
        # طبقِ درخواستِ صریح: چون زبانِ انتخاب‌شده در برنامه فارسی است،
        # فرمِ پیام هم باید راست‌چین باشد (نه فقط چیدمانِ کلیِ برنامه).
        box.setLayoutDirection(Qt.RightToLeft)
        yes_button = box.addButton("بله", QMessageBox.YesRole)
        box.addButton("خیر", QMessageBox.NoRole)
        box.setDefaultButton(yes_button)
        box.exec()
        if box.clickedButton() is yes_button:
            event.accept()
        else:
            event.ignore()

    # --- ثبت‌نامِ صفحات -----------------------------------------------------
    def _register_screens(self) -> None:
        from peecha.ui.screens.chart_of_accounts import ChartOfAccountsScreen
        from peecha.ui.screens.dashboard import DashboardScreen
        from peecha.ui.screens.detail_accounts_list import DetailAccountsListScreen
        from peecha.ui.screens.detail_dimensions import DetailDimensionsScreen
        from peecha.ui.screens.dimension_group_config import DimensionGroupConfigScreen
        from peecha.ui.screens.hr_job_grades import JobGradesScreen
        from peecha.ui.screens.hr_org_units import OrgUnitsScreen
        from peecha.ui.screens.hr_positions import PositionsScreen
        from peecha.ui.screens.payroll_run import PayrollRunScreen
        from peecha.ui.screens.payroll_loans import PayrollLoansScreen
        from peecha.ui.screens.payroll_overtime_entries import PayrollOvertimeEntriesScreen
        from peecha.ui.screens.hr_attendance_entries import HrAttendanceEntriesScreen
        from peecha.ui.screens.hr_attendance_summary import HrAttendanceSummaryScreen
        from peecha.ui.screens.inventory_warehouses import InventoryWarehousesScreen
        from peecha.ui.screens.inventory_document import InventoryDocumentScreen
        from peecha.ui.screens.inventory_documents_list import InventoryDocumentsListScreen
        from peecha.ui.screens.commercial_document import CommercialDocumentScreen
        from peecha.ui.screens.commercial_documents_list import CommercialDocumentsListScreen
        from peecha.ui.screens.commercial_pricing import CommercialPricingScreen
        from peecha.ui.screens.commercial_pos_sessions import CommercialPosSessionsScreen
        from peecha.ui.screens.commercial_pos_sale import CommercialPosSaleScreen
        from peecha.ui.screens.commercial_ecommerce import CommercialEcommerceScreen
        from peecha.ui.screens.commercial_aftersales import CommercialAftersalesScreen
        from peecha.ui.screens.commercial_purchasing_extras import CommercialPurchasingExtrasScreen
        from peecha.ui.screens.commercial_settlement import InvoiceSettlementScreen
        from peecha.ui.screens.journal_entries_list import JournalEntriesListScreen
        from peecha.ui.screens.journal_entry import JournalEntryScreen
        from peecha.ui.screens.my_tasks import MyTasksScreen
        from peecha.ui.screens.placeholder import PlaceholderScreen
        from peecha.ui.screens.report_account_ledger import AccountLedgerScreen
        from peecha.ui.screens.report_anomalies import AnomaliesScreen
        from peecha.ui.screens.report_balance_sheet import BalanceSheetScreen
        from peecha.ui.screens.report_cash_flow import CashFlowScreen
        from peecha.ui.screens.report_cost_center_breakdown import CostCenterBreakdownScreen
        from peecha.ui.screens.report_custom_statement import CustomStatementScreen
        from peecha.ui.screens.report_equity_changes import EquityChangesScreen
        from peecha.ui.screens.report_financial_ratios import FinancialRatiosScreen
        from peecha.ui.screens.report_income_statement import IncomeStatementScreen
        from peecha.ui.screens.report_journal_book import JournalBookScreen
        from peecha.ui.screens.report_period_comparison import PeriodComparisonScreen
        from peecha.ui.screens.report_trial_balance import TrialBalanceScreen
        from peecha.ui.screens.statement_template_designer import (
            StatementTemplateDesignerScreen,
        )
        from peecha.ui.screens.my_tasks import register_open_handler
        from peecha.ui.screens.bank_reconciliation import BankReconciliationScreen
        from peecha.ui.screens.report_checks import ChecksReportScreen
        from peecha.ui.screens.system_settings import SystemSettingsScreen
        from peecha.ui.screens.system_backup import SystemBackupScreen
        from peecha.ui.screens.system_data_reset import SystemDataResetScreen
        from peecha.ui.screens.treasury_checks import IssuedChecksScreen, ReceivedChecksScreen
        from peecha.ui.screens.treasury_reports import TreasuryChecksDueScreen
        from peecha.ui.screens.treasury_voucher import TreasuryVoucherScreen
        from peecha.ui.screens.treasury_petty_cash import PettyCashScreen

        # طبقِ درخواستِ صریح («سیستمِ کارتابلِ قابلِ‌گسترش برایِ همه‌یِ ماژول‌ها»):
        # هر ماژولی که واردِ کارتابل می‌شود، فقط همین یک خط این‌جا اضافه
        # می‌کند — بازکردنِ سندِ حسابداری با دابل‌کلیک رویِ ردیفِ «کارتابلِ من».
        register_open_handler(
            "journal_entry",
            lambda main_window, source_record_id: main_window.open_screen(
                "GL_JE", then=lambda screen: screen.edit_journal_entry(source_record_id)
            ),
        )

        self.register_screen("dashboard", DashboardScreen())
        self.register_screen("my_tasks", MyTasksScreen(self))
        self.register_screen("placeholder", PlaceholderScreen())
        self.register_screen("chart_of_accounts", ChartOfAccountsScreen())
        self.register_screen("system_settings", SystemSettingsScreen())
        self.register_screen("system_backup", SystemBackupScreen())
        self.register_screen("system_data_reset", SystemDataResetScreen())
        self.register_screen("dimension_group_config", DimensionGroupConfigScreen())
        self.register_screen("detail_dimensions", DetailDimensionsScreen())
        self.register_screen("detail_accounts_list", DetailAccountsListScreen(self))
        self.register_screen("journal_entry", JournalEntryScreen())
        self.register_screen("journal_entries_list", JournalEntriesListScreen(self))
        self.register_screen("hr_org_units", OrgUnitsScreen())
        self.register_screen("hr_job_grades", JobGradesScreen())
        self.register_screen("hr_positions", PositionsScreen())
        self.register_screen("payroll_run", PayrollRunScreen())
        self.register_screen("payroll_loans", PayrollLoansScreen())
        self.register_screen("payroll_overtime_entries", PayrollOvertimeEntriesScreen())
        self.register_screen("hr_attendance_entries", HrAttendanceEntriesScreen())
        self.register_screen("hr_attendance_summary", HrAttendanceSummaryScreen())
        self.register_screen("inventory_warehouses", InventoryWarehousesScreen())
        self.register_screen("inventory_documents_list", InventoryDocumentsListScreen(self))
        self.register_screen("inventory_document_receipt", InventoryDocumentScreen("RECEIPT", self))
        self.register_screen("inventory_document_issue", InventoryDocumentScreen("ISSUE", self))
        self.register_screen("inventory_document_transfer", InventoryDocumentScreen("TRANSFER", self))
        self.register_screen("inventory_document_return_in", InventoryDocumentScreen("RETURN_IN", self))
        self.register_screen("inventory_document_return_out", InventoryDocumentScreen("RETURN_OUT", self))
        self.register_screen("inventory_document_adjustment", InventoryDocumentScreen("ADJUSTMENT", self))
        self.register_screen("commercial_document_sales_order", CommercialDocumentScreen("SALES_ORDER", self))
        self.register_screen("commercial_document_sales_proforma", CommercialDocumentScreen("SALES_PROFORMA", self))
        self.register_screen("commercial_document_sales_invoice", CommercialDocumentScreen("SALES_INVOICE", self))
        self.register_screen("commercial_document_sales_return", CommercialDocumentScreen("SALES_RETURN", self))
        self.register_screen("commercial_document_purchase_order", CommercialDocumentScreen("PURCHASE_ORDER", self))
        self.register_screen("commercial_document_purchase_proforma", CommercialDocumentScreen("PURCHASE_PROFORMA", self))
        self.register_screen("commercial_document_purchase_invoice", CommercialDocumentScreen("PURCHASE_INVOICE", self))
        self.register_screen("commercial_document_purchase_return", CommercialDocumentScreen("PURCHASE_RETURN", self))
        self.register_screen(
            "commercial_documents_list_sales",
            CommercialDocumentsListScreen(self, type_filter_codes=("SALES_ORDER", "SALES_PROFORMA", "SALES_INVOICE", "SALES_RETURN")),
        )
        self.register_screen(
            "commercial_documents_list_purchase",
            CommercialDocumentsListScreen(self, type_filter_codes=("PURCHASE_ORDER", "PURCHASE_PROFORMA", "PURCHASE_INVOICE", "PURCHASE_RETURN")),
        )
        self.register_screen("commercial_pricing", CommercialPricingScreen())
        self.register_screen("commercial_pos_sessions", CommercialPosSessionsScreen())
        self.register_screen("commercial_pos_sale", CommercialPosSaleScreen())
        self.register_screen("commercial_ecommerce", CommercialEcommerceScreen())
        self.register_screen("commercial_aftersales", CommercialAftersalesScreen())
        self.register_screen("commercial_purchasing_extras", CommercialPurchasingExtrasScreen())
        self.register_screen("commercial_invoice_settlement", InvoiceSettlementScreen(self))
        self.register_screen("treasury_voucher_receipt", TreasuryVoucherScreen("RECEIPT", self))
        self.register_screen("treasury_voucher_payment", TreasuryVoucherScreen("PAYMENT", self))
        self.register_screen(
            "treasury_vouchers_list",
            JournalEntriesListScreen(
                self,
                entry_type_codes=["RECEIPT", "PAYMENT"],
                title="اسنادِ خزانه‌داری",
                new_entry_options=[("+ سندِ دریافت", "TREASURY_RECEIPT"), ("+ سندِ پرداخت", "TREASURY_PAYMENT")],
                # ویرایشِ سندِ ازقبل‌ثبت‌شده همیشه از فرمِ عمومیِ GL_JE انجام
                # می‌شود (پیش‌فرضِ edit_screen_by_type={}) — فرمِ چندروشی فقط
                # برایِ صدورِ سندِ تازه است، نه بازسازیِ ردیف‌ها از رویِ یک
                # سندِ موجود.
            ),
        )
        # طبقِ ساختارِ واقعیِ تنخواه‌گردان (نه یک فرمِ پرداختِ سرپوش‌دار):
        # هر تنخواه‌دار (تفصیلیِ سطحِ آخرِ گروهِ «تنخواه») می‌تواند چند
        # تنخواهِ بازِ هم‌زمان داشته باشد، هرکدام با شماره‌یِ خودکارِ
        # مستقل؛ افتتاح = یک سندِ پرداختِ واقعی، ردیف‌هایِ ثبت‌شده در دورانِ
        # بازبودن هیچ سندی نمی‌سازند، بستن = یک سندِ موقتِ پیش‌نویس که
        # تنخواه‌دار را بستانکار می‌کند.
        self.register_screen("treasury_petty_cash", PettyCashScreen(self))
        self.register_screen(
            "treasury_petty_cash_list",
            JournalEntriesListScreen(
                self,
                entry_type_codes=["TANKHAH"],
                title="اسنادِ تنخواه‌گردان",
                new_entry_options=[("+ تنخواه‌گردان", "TREASURY_PETTY_CASH")],
            ),
        )
        self.register_screen("treasury_checks_received", ReceivedChecksScreen())
        self.register_screen("treasury_checks_issued", IssuedChecksScreen())
        self.register_screen("treasury_checks_due", TreasuryChecksDueScreen())
        self.register_screen("report_checks", ChecksReportScreen())
        self.register_screen("bank_reconciliation", BankReconciliationScreen())
        self.register_screen("report_trial_balance", TrialBalanceScreen())
        self.register_screen("report_journal_book", JournalBookScreen())
        self.register_screen("report_account_ledger", AccountLedgerScreen())
        self.register_screen("report_income_statement", IncomeStatementScreen())
        self.register_screen("report_balance_sheet", BalanceSheetScreen())
        self.register_screen("report_cash_flow", CashFlowScreen())
        self.register_screen("report_cost_center_breakdown", CostCenterBreakdownScreen())
        self.register_screen("report_equity_changes", EquityChangesScreen())
        self.register_screen("report_custom_statement", CustomStatementScreen())
        self.register_screen("statement_template_designer", StatementTemplateDesignerScreen())
        self.register_screen("report_financial_ratios", FinancialRatiosScreen())
        self.register_screen("report_period_comparison", PeriodComparisonScreen())
        self.register_screen("report_anomalies", AnomaliesScreen())

    def register_screen(self, name: str, widget: QWidget) -> None:
        self._screens[name] = widget
        theme.apply_card_shadows(widget)

    def get_screen(self, name: str) -> QWidget | None:
        return self._screens.get(name)

    # --- ناوبری -------------------------------------------------------------
    def open_screen(self, code: str, *, then=None) -> None:
        flat_items = _flatten_nav_items()
        item = next((i for i in flat_items if i["code"] == code), None)
        if item is None:
            return

        self._current_screen_code = code
        self._highlight_active_leaf(code)
        module_code = self._find_top_level_code(code) or code
        self._refresh_quick_access_bar(module_code)

        target_screen_name = item["screen"] or "placeholder"
        screen = self._screens.get(target_screen_name)
        if screen is None:
            screen = self._screens["placeholder"]
        if screen is self._screens["placeholder"]:
            screen.set_module_name(item["label"])

        sub_window = self._mdi_subwindows.get(target_screen_name)
        is_new_subwindow = sub_window is None
        if is_new_subwindow:
            sub_window = _FramelessMdiSubWindow()
            sub_window._screen_name = target_screen_name
            sub_window._main_window = self
            icon = _NAV_ICONS.get(self._find_top_level_code(code), "📄")
            wrapper = _MdiFormWrapper(item["label"], icon, screen, sub_window)
            sub_window.setWidget(wrapper)
            sub_window.setAttribute(Qt.WA_DeleteOnClose, False)
            sub_window.maximized_changed.connect(self._update_chrome_visibility)
            self.mdi_area.addSubWindow(sub_window)
            self._mdi_subwindows[target_screen_name] = sub_window
        sub_window.setWindowTitle(item["label"])
        # نکته‌یِ فنیِ کشف‌شده حینِ تست: خودِ show() (نه فقط
        # _restore_or_size_subwindow) هم می‌تواند برایِ زیرپنجره‌یِ تازه
        # رویدادِ WindowStateChange بفرستد؛ برایِ همین پرچمِ _restoring باید
        # از *پیش* از show() فعال شود، نه فقط دورِ _restore_or_size_subwindow —
        # وگرنه همان show() اولیه، جایگاهِ هنوز-اصلاح‌نشده را زودتر ذخیره
        # می‌کند و مقدارِ درستِ بعدی هرگز روی دیسک نمی‌نشیند.
        #
        # باگِ واقعیِ کشف‌شده (طبقِ گزارشِ صریحِ کاربر: «فرمِ قبلی با
        # بازشدنِ فرمِ تازه جمع می‌شود»): رفتارِ بومیِ خودِ QMdiArea این
        # است که فقط یک زیرپنجره هم‌زمان می‌تواند maximize نمایش داده
        # شود، پس نمایش/بازیابیِ *این* زیرپنجره می‌تواند به‌طورِ جانبی
        # حالتِ maximizeِ زیرپنجره‌هایِ *دیگر* را هم عوض کند و changeEvent
        # آن‌ها را هم صدا بزند. قبلاً این تغییرِ جانبی مستقیم در QSettings
        # ذخیره می‌شد و ترجیحِ واقعیِ کاربر برایِ آن فرمِ دیگر را خراب
        # می‌کرد — چون بازیابیِ حالتِ ذخیره‌شده فقط برایِ زیرپنجره‌یِ *تازه*
        # اجرا می‌شد، فرمِ قبلاً-بازشده با برگشتنِ کاربر به آن، دیگر هرگز
        # به حالتِ maximizeاش برنمی‌گشت. حالا: (۱) self._suppressing_geometry_save
        # حینِ این نمایش/بازیابی، ذخیره‌یِ خودکارِ *همه‌یِ* زیرپنجره‌ها را
        # موقتاً خاموش می‌کند (نه فقط همین یکی)، و (۲) بازیابیِ حالتِ
        # ذخیره‌شده برایِ *هر* بازکردنی اجرا می‌شود، نه فقط اولین‌بار —
        # پس هر فرمی که کاربر maximize کرده بود، با برگشتن به آن، دوباره
        # درست maximize نمایش داده می‌شود.
        self._suppressing_geometry_save = True
        try:
            if is_new_subwindow:
                sub_window._restoring = True
            sub_window.show()
            self._restore_or_size_subwindow(sub_window, target_screen_name)
            if is_new_subwindow:
                sub_window._restoring = False
        finally:
            self._suppressing_geometry_save = False
        sub_window.raise_()
        self.mdi_area.setActiveSubWindow(sub_window)

        if hasattr(screen, "refresh"):
            screen.refresh()
        if then is not None:
            then(screen)

    def _size_new_subwindow(self, sub_window: QMdiSubWindow) -> None:
        area_size = self.mdi_area.size()
        width = max(760, int(area_size.width() * 0.86))
        height = max(560, int(area_size.height() * 0.86))
        sub_window.resize(QSize(width, height))
        offset = (self._cascade_index % 6) * 26
        sub_window.move(offset, offset)
        self._cascade_index += 1

    def _restore_or_size_subwindow(self, sub_window: QMdiSubWindow, screen_name: str) -> None:
        """طبقِ درخواستِ صریح: جایگاه/اندازه/حالتِ maximize که کاربر آخرین
        بار برایِ این صفحه تنظیم کرده (با QSettings، در _save_geometryِ
        _FramelessMdiSubWindow) این‌جا بازیابی می‌شود — حتی بعدِ بستنِ
        کاملِ برنامه. اگر چیزی ذخیره نشده باشد (اولین بارِ بازکردنِ این
        صفحه)، همان چیدمانِ آبشاریِ پیش‌فرض به‌کار می‌رود."""
        settings = QSettings("Peecha", "PeechaERP")
        geometry = settings.value(f"mdiWindow/{screen_name}/geometry", None)
        was_maximized = settings.value(f"mdiWindow/{screen_name}/maximized", False, type=bool)
        # نکته‌یِ فنیِ کشف‌شده حینِ تست: QMdiArea وقتی از قبل یک زیرپنجره‌یِ
        # دیگر (مثلاً داشبورد، چون همیشه اول باز می‌شود) maximize باشد،
        # زیرپنجره‌یِ تازه را هم با اولین show()اش خودکار maximize نمایش
        # می‌دهد و جایگاه/اندازه‌اش را با چیدمانِ خودش عوض می‌کند — حتی اگر
        # حالتِ ذخیره‌شده‌یِ *همین* صفحه maximize نبوده باشد. برایِ همین،
        # اول باید صریحاً از آن حالت خارج شویم (showNormal)، و *بعد* جایگاهِ
        # درستِ ذخیره‌شده را ست کنیم — نه برعکس، وگرنه showNormal دوباره
        # آن را بازنویسی می‌کند.
        sub_window._restoring = True
        try:
            if was_maximized:
                sub_window.showMaximized()
            else:
                sub_window.showNormal()
                if isinstance(geometry, QRect):
                    sub_window.setGeometry(self._clamp_to_mdi_area(geometry))
                else:
                    self._size_new_subwindow(sub_window)
        finally:
            sub_window._restoring = False

    def _clamp_to_mdi_area(self, rect: QRect) -> QRect:
        """اگر جایگاهِ ذخیره‌شده (مثلاً از یک اجرایِ قبلی با پنجره‌یِ بزرگ‌تر)
        دیگر تویِ ناحیه‌یِ MDIِ فعلی جا نشود، آن را به داخلِ مرزها می‌کشیم
        — با همان تابعِ مشترکِ _clamp_rect_to_area که _ClampingMdiArea هم
        رویِ هر resizeِ زنده استفاده می‌کند."""
        return _clamp_rect_to_area(rect, self.mdi_area.rect())

    def _highlight_active_leaf(self, code: str) -> None:
        for group in self._sidebar_groups.values():
            group.set_active_leaf(code)

    def _find_top_level_code(self, leaf_code: str) -> str | None:
        for item in NAV_ITEMS:
            if item["code"] == leaf_code:
                return item["code"]
            if any(c["code"] == leaf_code for c in _leaf_nav_children(item)):
                return item["code"]
        return None


    # --- سوییچرِ زمینه -------------------------------------------------------
    def load_context_switcher(self) -> None:
        if session.current_user is None:
            return
        self._company_options = companies_service.list_companies_for_user(session.current_user.user_id)
        if session.current_company is None or not any(
            c.company_id == session.current_company.company_id for c in self._company_options
        ):
            first = self._company_options[0] if self._company_options else None
            session.current_company = companies_service.get_company_model(first.company_id) if first else None

        self.user_label.setText(session.current_user.full_name)
        initial = session.current_user.full_name.strip()[:1] or "؟"
        self.avatar_badge.setText(initial)
        avatar_color = theme.avatar_color_for(session.current_user.full_name)
        self.avatar_badge.setStyleSheet(
            f"background-color: {avatar_color}; color: white; font-weight: 700; border-radius: 16px;"
        )

        self.company_combo.blockSignals(True)
        self.company_combo.clear()
        for company in self._company_options:
            self.company_combo.addItem(company.display_name, company.company_id)
        if session.current_company is not None:
            index = self.company_combo.findData(session.current_company.company_id)
            if index >= 0:
                self.company_combo.setCurrentIndex(index)
        self.company_combo.blockSignals(False)

        languages = languages_service.list_languages()
        self.language_combo.blockSignals(True)
        self.language_combo.clear()
        for lang in languages:
            self.language_combo.addItem(lang.native_name, lang.language_id)
        current_language_id = session.current_language.language_id if session.current_language else None
        if current_language_id is not None:
            index = self.language_combo.findData(current_language_id)
            if index >= 0:
                self.language_combo.setCurrentIndex(index)
        self.language_combo.blockSignals(False)

        if session.current_company is not None:
            fiscal_years = fiscal_years_service.list_fiscal_years(session.current_company.company_id)
            self.fiscal_year_combo.clear()
            for fy in fiscal_years:
                self.fiscal_year_combo.addItem(numerals.to_persian_digits(fy.code), fy.fiscal_year_id)

        self._retranslate_sidebar()

    def _on_company_changed(self, index: int) -> None:
        if index < 0:
            return
        company_id = self.company_combo.itemData(index)
        if company_id is None:
            return
        if session.current_company is not None and session.current_company.company_id == company_id:
            return
        session.current_company = companies_service.get_company_model(company_id)
        active_sub = self.mdi_area.activeSubWindow()
        if active_sub is not None and hasattr(active_sub.widget(), "refresh"):
            active_sub.widget().refresh()

    def _on_language_changed(self, index: int) -> None:
        """طبقِ حسابرسیِ صریح: قبلاً این سوییچر هیچ signalای وصل نداشت —
        session.current_language هیچ‌وقت مقداردهی نمی‌شد و ساید‌بار همیشه
        فارسی می‌ماند، صرفِ‌نظر از انتخابِ کاربر. حالا با انتخاب، برچسبِ
        هرگروه/آیتم/زیرگروهِ ساید‌بار با ترجمه‌یِ ذخیره‌شده در
        services/translations.py (اگر موجود باشد) دوباره نوشته می‌شود."""
        language_id = self.language_combo.itemData(index)
        languages = languages_service.list_languages()
        session.current_language = next((lang for lang in languages if lang.language_id == language_id), None)
        self._retranslate_sidebar()

    def _retranslate_sidebar(self) -> None:
        language_id = session.current_language.language_id if session.current_language else None
        is_default = session.current_language.is_default if session.current_language else True

        def translate_fn(code: str, source_label: str) -> str:
            if is_default:
                return source_label
            return translations_service.translate_label(code, source_label, language_id)

        for group in self._sidebar_groups.values():
            group.retranslate(translate_fn)
