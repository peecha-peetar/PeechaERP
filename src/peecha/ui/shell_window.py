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

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QRect, QSize, Qt
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMdiArea,
    QMdiSubWindow,
    QMenu,
    QPushButton,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from peecha import numerals, session
from peecha.nav_catalog import NAV_ITEMS, QUICK_ACCESS_ITEMS
from peecha.nav_catalog import flatten_nav_items as _flatten_nav_items
from peecha.services import companies as companies_service
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import fiscal_years as fiscal_years_service
from peecha.services import languages as languages_service
from peecha.ui import theme
from peecha.ui.widgets import HoverButton, field_help_is_enabled, set_field_help_enabled

_PERSON_GROUP_NAV_CODE_TO_GROUP_CODE = {
    "GL_CUSTOMERS": dimensions_service.CUSTOMER_GROUP_CODE,
    "GL_SUPPLIERS": dimensions_service.SUPPLIER_GROUP_CODE,
    "GL_PERSONNEL": dimensions_service.PERSONNEL_GROUP_CODE,
}

_NAV_ICONS = {
    "dashboard": "🏠",
    "GL": "💰",
    "INV": "📦",
    "SALES": "🛒",
    "PURCH": "🧺",
    "HR": "👥",
    "INVOICES": "🧾",
    "REPORTS": "📈",
    "SETTINGS": "⚙️",
}

_SETTINGS_TAB_BY_GROUP_CODE = {"GL": 0}


def _leaf_nav_children(item: dict) -> list[dict]:
    leaves: list[dict] = []
    for child in item.get("children", []):
        if child.get("children"):
            leaves.extend(_leaf_nav_children(child))
        else:
            leaves.append(child)
    return leaves


class _QuickAccessTile(QFrame):
    """کاشیِ ریبونِ میان‌بر — آیکون + برچسب، با سایه‌ای که رویِ هاور
    بلندتر می‌شود (همان الگویِ widgets.KpiCard، مقیاسِ کوچک‌تر)."""

    def __init__(self, icon: str, label: str, on_click) -> None:
        super().__init__()
        self.setObjectName("quickTile")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(84, 74)
        self._on_click = on_click

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 10, 6, 8)
        layout.setSpacing(4)
        layout.setAlignment(Qt.AlignCenter)

        icon_label = QLabel(icon)
        icon_label.setAlignment(Qt.AlignCenter)
        icon_label.setStyleSheet("font-size: 20px; background: transparent;")
        layout.addWidget(icon_label)

        text_label = QLabel(label)
        text_label.setAlignment(Qt.AlignCenter)
        text_label.setWordWrap(True)
        text_label.setStyleSheet(f"font-size: 10px; font-weight: 600; color: {theme.TEXT_SECONDARY}; background: transparent;")
        layout.addWidget(text_label)

        self._shadow = QGraphicsDropShadowEffect(self)
        self._shadow.setBlurRadius(0)
        self._shadow.setXOffset(0)
        self._shadow.setYOffset(0)
        self._shadow.setColor(QColor(79, 70, 229, 0))
        self.setGraphicsEffect(self._shadow)
        self._anim = QPropertyAnimation(self._shadow, b"blurRadius", self)
        self._anim.setDuration(150)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._on_click()
        super().mousePressEvent(event)

    def enterEvent(self, event) -> None:  # noqa: N802
        self.setStyleSheet(f"QFrame#quickTile {{ background-color: {theme.ACCENT_LIGHT}; border-radius: 14px; }}")
        self._anim.stop()
        self._anim.setStartValue(self._shadow.blurRadius())
        self._anim.setEndValue(22)
        self._anim.start()
        self._shadow.setColor(QColor(79, 70, 229, 60))
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self.setStyleSheet("QFrame#quickTile { background-color: transparent; border-radius: 14px; }")
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


class _MdiTitleBar(QWidget):
    """تیتربارِ کاملاً سفارشی برایِ فرم‌هایِ شناور — طبقِ درخواستِ صریح
    (تیتربارِ بومیِ Fusion با بقیه‌ی برنامه هم‌خوان نبود). قابلِ‌درگ (کلیک
    و کشیدن از هرجایِ نوار جز دکمه‌ها) برایِ جابه‌جاییِ پنجره، و
    دوبار-کلیک برایِ maximize/restore — دقیقاً رفتارِ متعارفِ تیتربار."""

    def __init__(self, title: str, icon: str, sub_window: "_FramelessMdiSubWindow") -> None:
        super().__init__()
        self.setObjectName("mdiTitleBar")
        self.setFixedHeight(42)
        self._sub_window = sub_window
        self._drag_offset = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 0, 8, 0)
        layout.setSpacing(6)

        icon_label = QLabel(icon)
        icon_label.setStyleSheet("font-size: 14px; background: transparent;")
        layout.addWidget(icon_label)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("mdiTitleLabel")
        layout.addWidget(self.title_label)
        layout.addStretch(1)

        self.minimize_btn = self._make_control_button("—", theme.HOVER)
        self.minimize_btn.clicked.connect(sub_window.showMinimized)
        layout.addWidget(self.minimize_btn)

        self.maximize_btn = self._make_control_button("▢", theme.HOVER)
        self.maximize_btn.clicked.connect(self._toggle_maximize)
        layout.addWidget(self.maximize_btn)

        self.close_btn = self._make_control_button("✕", "#FDECEC")
        self.close_btn.clicked.connect(sub_window.close)
        layout.addWidget(self.close_btn)

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

    def __init__(self) -> None:
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint)
        self.setMouseTracking(True)
        self.setMinimumSize(_MIN_SUBWINDOW_SIZE)
        self._resize_dir: str | None = None
        self._resize_start_geo = None
        self._resize_start_pos = None

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
        event.ignore()
        self.hide()


class _MdiFormWrapper(QWidget):
    """محتوایِ واقعیِ زیرپنجره — تیتربارِ سفارشی (بالا) + خودِ صفحه
    (پایین). این ویجت، نه خودِ صفحه، رویِ QMdiSubWindow.setWidget
    می‌نشیند."""

    def __init__(self, title: str, icon: str, screen: QWidget, sub_window: _FramelessMdiSubWindow) -> None:
        super().__init__()
        self.setObjectName("mdiFormWrapper")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.title_bar = _MdiTitleBar(title, icon, sub_window)
        outer.addWidget(self.title_bar)
        outer.addWidget(screen, stretch=1)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("پیچا")
        self.resize(1440, 900)

        self._screens: dict[str, QWidget] = {}
        self._sidebar_groups: dict[str, _SidebarGroup] = {}
        self._mdi_subwindows: dict[str, _FramelessMdiSubWindow] = {}
        self._current_screen_code: str | None = None
        self._company_options: list[companies_service.CompanyRow] = []
        self._cascade_index = 0

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

        self._register_screens()
        self.open_screen("dashboard")

    # --- هدر --------------------------------------------------------------
    def _build_header(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setObjectName("headerScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFixedHeight(68)

        header = QWidget()
        header.setObjectName("headerBar")
        layout = QHBoxLayout(header)
        layout.setContentsMargins(24, 8, 24, 8)
        layout.setSpacing(16)

        brand = QLabel("پیچا")
        brand_font = QFont()
        brand_font.setPointSize(15)
        brand_font.setBold(True)
        brand.setFont(brand_font)
        brand.setStyleSheet(f"color: {theme.ACCENT};")
        layout.addWidget(brand)

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
            "   font-size: 15px; color: #8a93a6; background: transparent;"
            "}"
            "#fieldHelpToggle:checked { color: #f5a524; background: rgba(245, 165, 36, 40); }"
            "#fieldHelpToggle:hover { background: rgba(245, 165, 36, 25); }"
        )
        self.field_help_toggle.toggled.connect(set_field_help_enabled)
        layout.addWidget(self.field_help_toggle)

        self.search_field = QLineEdit()
        self.search_field.setPlaceholderText("⌕  جستجو در سیستم...")
        self.search_field.setFixedWidth(320)
        layout.addWidget(self.search_field)

        layout.addStretch(1)

        self.language_combo = QComboBox()
        self.language_combo.setFixedWidth(110)
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
        header_shadow.setBlurRadius(18)
        header_shadow.setXOffset(0)
        header_shadow.setYOffset(3)
        header_shadow.setColor(QColor(21, 22, 43, 20))
        scroll.setGraphicsEffect(header_shadow)

        return scroll

    # --- ریبونِ میان‌برهایِ پرکاربرد -------------------------------------------
    def _build_quick_access_bar(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setObjectName("quickAccessScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFixedHeight(92)

        bar = QWidget()
        bar.setObjectName("quickAccessBar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(20, 8, 20, 8)
        layout.setSpacing(10)

        flat_items_by_code = {i["code"]: i for i in _flatten_nav_items()}
        for code, icon in QUICK_ACCESS_ITEMS:
            if code == "SETTINGS":
                label = "تنظیمات"
            else:
                item = flat_items_by_code.get(code)
                if item is None:
                    continue
                label = item["label"]
            tile = _QuickAccessTile(icon, label, lambda c=code: self.open_screen(c))
            layout.addWidget(tile)

        layout.addStretch(1)
        scroll.setWidget(bar)
        return scroll

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

    def refresh_sidebar_dynamic_labels(self) -> None:
        """عنوانِ نمایشیِ گروه‌هایِ اشخاص (مشتری/تامین‌کننده/پرسنل) را —
        اگر شرکتِ جاری آن‌ها را تغییرِنام داده باشد — در دکمه‌هایِ ساید‌بار
        به‌روز می‌کند."""
        company_id = session.current_company.company_id if session.current_company else None
        if company_id is None:
            return
        names_by_group_code = {g.code: g.name for g in dimensions_service.list_person_groups(company_id)}
        gl_group = self._sidebar_groups.get("GL")
        if gl_group is None:
            return
        for nav_code, group_code in _PERSON_GROUP_NAV_CODE_TO_GROUP_CODE.items():
            button = gl_group._entries.get(nav_code)
            new_name = names_by_group_code.get(group_code)
            if button is not None and new_name:
                button.setText(new_name)

    # --- ناحیه‌ی کاریِ MDI (فرم‌هایِ شناور) --------------------------------------
    def _build_mdi_area(self) -> QWidget:
        self.mdi_area = QMdiArea()
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

    def _logout(self) -> None:
        from peecha.ui.login_window import LoginWindow
        from peecha.ui.main import get_font_family

        session.log_out()
        self._login_window = LoginWindow(get_font_family())
        self._login_window.show()
        self.close()

    # --- ثبت‌نامِ صفحات -----------------------------------------------------
    def _register_screens(self) -> None:
        from peecha.ui.screens.chart_of_accounts import ChartOfAccountsScreen
        from peecha.ui.screens.dashboard import DashboardScreen
        from peecha.ui.screens.detail_accounts_list import DetailAccountsListScreen
        from peecha.ui.screens.detail_dimensions import DetailDimensionsScreen
        from peecha.ui.screens.dimension_group_config import DimensionGroupConfigScreen
        from peecha.ui.screens.journal_entries_list import JournalEntriesListScreen
        from peecha.ui.screens.journal_entry import JournalEntryScreen
        from peecha.ui.screens.person_group_screens import (
            CustomersScreen,
            PersonnelScreen,
            SuppliersScreen,
        )
        from peecha.ui.screens.placeholder import PlaceholderScreen
        from peecha.ui.screens.report_account_ledger import AccountLedgerScreen
        from peecha.ui.screens.report_anomalies import AnomaliesScreen
        from peecha.ui.screens.report_balance_sheet import BalanceSheetScreen
        from peecha.ui.screens.report_cash_flow import CashFlowScreen
        from peecha.ui.screens.report_custom_statement import CustomStatementScreen
        from peecha.ui.screens.report_equity_changes import EquityChangesScreen
        from peecha.ui.screens.report_financial_ratios import FinancialRatiosScreen
        from peecha.ui.screens.report_income_statement import IncomeStatementScreen
        from peecha.ui.screens.report_journal_book import JournalBookScreen
        from peecha.ui.screens.report_period_comparison import PeriodComparisonScreen
        from peecha.ui.screens.report_trial_balance import TrialBalanceScreen
        from peecha.ui.screens.specialized_dimensions import (
            BankAccountsScreen,
            CashBoxesScreen,
            CostCentersScreen,
            FixedAssetsScreen,
            InventoryItemsScreen,
            PettyCashesScreen,
            ProjectsScreen,
        )
        from peecha.ui.screens.statement_template_designer import (
            StatementTemplateDesignerScreen,
        )
        from peecha.ui.screens.system_settings import SystemSettingsScreen

        self.register_screen("dashboard", DashboardScreen())
        self.register_screen("placeholder", PlaceholderScreen())
        self.register_screen("chart_of_accounts", ChartOfAccountsScreen())
        self.register_screen("system_settings", SystemSettingsScreen())
        self.register_screen("customers", CustomersScreen())
        self.register_screen("suppliers", SuppliersScreen())
        self.register_screen("personnel", PersonnelScreen())
        self.register_screen("inventory_items", InventoryItemsScreen())
        self.register_screen("fixed_assets", FixedAssetsScreen())
        self.register_screen("bank_accounts", BankAccountsScreen())
        self.register_screen("cash_boxes", CashBoxesScreen())
        self.register_screen("petty_cashes", PettyCashesScreen())
        self.register_screen("cost_centers", CostCentersScreen())
        self.register_screen("projects", ProjectsScreen())
        self.register_screen("dimension_group_config", DimensionGroupConfigScreen())
        self.register_screen("detail_dimensions", DetailDimensionsScreen())
        self.register_screen("detail_accounts_list", DetailAccountsListScreen(self))
        self.register_screen("journal_entry", JournalEntryScreen())
        self.register_screen("journal_entries_list", JournalEntriesListScreen(self))
        self.register_screen("report_trial_balance", TrialBalanceScreen())
        self.register_screen("report_journal_book", JournalBookScreen())
        self.register_screen("report_account_ledger", AccountLedgerScreen())
        self.register_screen("report_income_statement", IncomeStatementScreen())
        self.register_screen("report_balance_sheet", BalanceSheetScreen())
        self.register_screen("report_cash_flow", CashFlowScreen())
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

        target_screen_name = item["screen"] or "placeholder"
        screen = self._screens.get(target_screen_name)
        if screen is None:
            screen = self._screens["placeholder"]
        if screen is self._screens["placeholder"]:
            screen.set_module_name(item["label"])

        sub_window = self._mdi_subwindows.get(target_screen_name)
        if sub_window is None:
            sub_window = _FramelessMdiSubWindow()
            icon = _NAV_ICONS.get(self._find_top_level_code(code), "📄")
            wrapper = _MdiFormWrapper(item["label"], icon, screen, sub_window)
            sub_window.setWidget(wrapper)
            sub_window.setAttribute(Qt.WA_DeleteOnClose, False)
            self.mdi_area.addSubWindow(sub_window)
            self._size_new_subwindow(sub_window)
            self._mdi_subwindows[target_screen_name] = sub_window
        sub_window.setWindowTitle(item["label"])
        sub_window.show()
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
        self.language_combo.clear()
        for lang in languages:
            self.language_combo.addItem(lang.native_name, lang.language_id)

        if session.current_company is not None:
            fiscal_years = fiscal_years_service.list_fiscal_years(session.current_company.company_id)
            self.fiscal_year_combo.clear()
            for fy in fiscal_years:
                self.fiscal_year_combo.addItem(numerals.to_persian_digits(fy.code), fy.fiscal_year_id)

        self.refresh_sidebar_dynamic_labels()

    def _on_company_changed(self, index: int) -> None:
        if index < 0:
            return
        company_id = self.company_combo.itemData(index)
        if company_id is None:
            return
        if session.current_company is not None and session.current_company.company_id == company_id:
            return
        session.current_company = companies_service.get_company_model(company_id)
        self.refresh_sidebar_dynamic_labels()
        active_sub = self.mdi_area.activeSubWindow()
        if active_sub is not None and hasattr(active_sub.widget(), "refresh"):
            active_sub.widget().refresh()
