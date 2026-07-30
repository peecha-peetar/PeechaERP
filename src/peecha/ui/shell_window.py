"""پنجره‌ی اصلیِ برنامه (پوسته) — معادلِ Qt برایِ shell.py/shell.kv در Kivy.

تفاوتِ کلیدی با نسخه‌ی Kivy: هیچ تکنیکِ «ترتیبِ معکوسِ اعلامِ فرزندان»
لازم نیست — با `app.setLayoutDirection(Qt.RightToLeft)` (در main.py)،
خودِ Qt ترتیبِ افقیِ هر QHBoxLayout را آینه می‌کند، و QComboBox به‌طورِ
بومی راست‌چین و جهت‌دار می‌شود.

ناوبریِ اصلی یک منویِ افقی (مگامنو) زیرِ هدر است، نه ساید‌بارِ عمودی —
_build_menu_bar آیتم‌هایِ سطحِ‌بالا را نشان می‌دهد و _build_mega_panel
با کلیک رویِ هرکدام، زیرمجموعه‌هایش را در یک پنلِ بازشونده (دسته‌بندی‌شده
به ستون) نمایش می‌دهد."""

from __future__ import annotations

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from peecha import session
from peecha.services import companies as companies_service
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import fiscal_years as fiscal_years_service
from peecha.services import languages as languages_service
from peecha import numerals
from peecha.ui import theme
from peecha.ui.widgets import field_help_is_enabled, set_field_help_enabled

# طبقِ درخواستِ صریح: عنوانِ نمایشیِ گروه‌هایِ اشخاص (مشتری/تامین‌کننده/
# پرسنل) در ریبون باید بعدِ تغییرِ نامشان (dimension_group_config.py) به‌روز
# بماند، نه برچسبِ ثابتِ قدیمیِ NAV_ITEMS — نگاشتِ کدِ آیتمِ ناوبری به کدِ
# گروهِ اشخاصِ متناظر برایِ خواندنِ نامِ زنده از دیتابیس.
_PERSON_GROUP_NAV_CODE_TO_GROUP_CODE = {
    "GL_CUSTOMERS": dimensions_service.CUSTOMER_GROUP_CODE,
    "GL_SUPPLIERS": dimensions_service.SUPPLIER_GROUP_CODE,
    "GL_PERSONNEL": dimensions_service.PERSONNEL_GROUP_CODE,
}

# NAV_ITEMS حالا در peecha/nav_catalog.py متمرکز شده — طبقِ بازخوردِ صریح
# (نقش‌ها/دسترسی‌ها با اضافه‌شدنِ صفحه‌یِ تازه در جدول به‌روز نمی‌شد)، همان
# فهرست حالا تکِ منبعِ حقیقتِ هم برایِ این ناوبری و هم برایِ کاتالوگِ
# فرم‌هایِ services/roles.py است.
from peecha.nav_catalog import NAV_ITEMS
from peecha.nav_catalog import flatten_nav_items as _flatten_nav_items

# گلیفِ آیکونِ هر آیتمِ سطحِ بالا — برایِ حالتِ جمع‌شده‌ی نوارِ کناری (فقط
# آیکون) که rendered می‌شود؛ فایلِ آیکونِ خارجی لازم نیست (theme.emoji_icon).
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

# طبقِ درخواستِ صریح: دکمه‌ی چرخ‌دنده‌ی گوشه‌ی ریبون، تنظیماتِ مخصوصِ همان
# بخش را مستقیم (به‌جایِ تبِ پیش‌فرض) در «تنظیماتِ سیستم» باز می‌کند —
# نگاشتِ کدِ گروه به ایندکسِ تبِ مربوطه (فقط بخش‌هایی که واقعاً تنظیماتِ
# اختصاصی دارند نگاشته می‌شوند؛ بقیه هنوز صفحه ندارند).
_SETTINGS_TAB_BY_GROUP_CODE = {"GL": 0}


def _leaf_nav_children(item: dict) -> list[dict]:
    """همه‌یِ فرزندانِ برگِ یک آیتمِ ناوبری را، در هر عمقی از زیرمنوهایِ
    تودرتو (مثلِ «گزارش‌ها ← حسابداری ← تراز آزمایشی»)، برمی‌گرداند —
    برایِ ریبون که هنوز یک ردیفِ تختِ دکمه است، صرفِ‌نظر از این‌که ساید‌بار
    آن‌ها را زیرِ چند لایه زیرمنو نشان می‌دهد."""
    leaves: list[dict] = []
    for child in item.get("children", []):
        if child.get("children"):
            leaves.extend(_leaf_nav_children(child))
        else:
            leaves.append(child)
    return leaves


class _CurrentOnlyStackedWidget(QStackedWidget):
    """QStackedWidgِ معمولی، اندازه‌ی خودش را از رویِ بزرگ‌ترینِ صفحه‌یِ
    ثبت‌شده (نه لزوماً همانی که الان نمایش داده می‌شود) محاسبه می‌کند —
    طبقِ گزارشِ صریح (با اعدادِ واقعی تأیید شد): همین رفتار باعث می‌شد
    پنجره‌یِ اصلی همیشه به‌اندازه‌یِ بزرگ‌ترین صفحه (مثلاً «پیکربندیِ
    گروه‌هایِ تفصیلی» یا «تنظیماتِ سیستم»، ۱۳۴۶×۸۵۷) مجبور به رشد شود —
    حتی وقتی صفحه‌یِ کوچکی مثلِ «صدورِ سند» بازِ است — و چون این عددِ
    بزرگ‌شده گاهی از ارتفاعِ واقعیِ صفحه‌نمایشِ کاربر بیشتر می‌شد، پنجره
    (و هرچه ته‌اش بود، مثلِ فوترِ دکمه‌ها) از دیدرس خارج می‌ماند. این
    زیرکلاس sizeHint/minimumSizeHint را فقط از رویِ صفحه‌یِ درحالِ‌نمایش
    برمی‌گرداند تا اندازه‌یِ پنجره با نیازِ واقعیِ همان صفحه هماهنگ بماند."""

    def sizeHint(self):  # noqa: N802 — نامِ متدِ Qt
        current = self.currentWidget()
        return current.sizeHint() if current is not None else super().sizeHint()

    def minimumSizeHint(self):  # noqa: N802
        current = self.currentWidget()
        return current.minimumSizeHint() if current is not None else super().minimumSizeHint()


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("پیچا")
        self.resize(1440, 900)

        self._screens: dict[str, QWidget] = {}
        self._menu_buttons: dict[str, QPushButton] = {}
        self._mega_panel_open_code: str | None = None
        self._current_screen_code: str | None = None
        self._company_options: list[companies_service.CompanyRow] = []

        central = QWidget()
        self._central = central
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        outer.addWidget(self._build_header())
        outer.addWidget(self._build_menu_bar())

        self.breadcrumb_label = QLabel("")
        self.breadcrumb_label.setObjectName("breadcrumbLabel")
        outer.addWidget(self.breadcrumb_label)

        self.stack = _CurrentOnlyStackedWidget()
        outer.addWidget(self.stack, stretch=1)

        # طبقِ درخواستِ صریح: مگاپنل نباید در چیدمانِ عمودی جا بگیرد (که
        # باعث می‌شد بازشدنش فرمِ زیرش را به‌پایین هل بدهد و اندازه‌اش
        # به‌هم بریزد) — به‌جایش یک ویجتِ شناور و بدونِ مدیریتِ layout است،
        # با geometryِ دستی رویِ خودِ ناحیه‌یِ محتوا (self.stack) قرار
        # می‌گیرد و رویش می‌نشیند، بدونِ اینکه فضایی از آن بگیرد یا اندازه‌اش
        # را تغییر دهد.
        self._build_mega_panel()

        self._register_screens()
        self.open_screen("dashboard")
        self._did_initial_relayout = False

    # طبقِ گزارشِ صریح (با عکسِ واقعیِ کاربر روی ویندوزِ واقعی تأیید شد):
    # فوترِ فرم‌ها (مثلاً «ثبتِ سند») اصلاً رسم نمی‌شد و حتی یک‌بار
    # ماکسیمایزکردنِ واقعی هم کافی نبود — فقط خروجِ کاملِ از تمام‌صفحه و
    # بازگشتِ دوباره درستش می‌کرد. این یعنی مشکل از رویدادِ resizeِ خودِ
    # پنجره نبود (نوکِ resize یا حتی ماکسیمایزِ واقعی امتحان و رد شد)،
    # بلکه از خودِ صفحه است: هر صفحه (مثلِ journal_entry.py) کلِ محتوایش
    # را در یک QScrollArea می‌گذارد؛ sizeHintِ ویجتِ داخلیِ آن اسکرول‌اِریا
    # گاهی پیش از polishِ کاملِ فرزندانش محاسبه و کش می‌شود و دیگر خودکار
    # دوباره محاسبه نمی‌شود — نتیجه: ارتفاعِ محتوایِ محاسبه‌شده کوتاه‌تر از
    # واقعی است و فوتر از پایینِ همان ارتفاعِ کش‌شده قطع می‌شود. ترفندِ
    # شناخته‌شده برایِ اجبارِ Qt به بازمحاسبه: خاموش/روشن‌کردنِ
    # setWidgetResizable — این‌جا رویِ خودِ صفحه‌یِ درحالِ‌نمایش (نه کلِ
    # پنجره) اعمال می‌شود، هم بعدِ اولین نمایش و هم بعدِ هر سوییچِ صفحه.
    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._did_initial_relayout:
            self._did_initial_relayout = True
            QTimer.singleShot(60, self._force_relayout)

    def _force_relayout(self) -> None:
        screen = self.stack.currentWidget()
        if screen is None:
            return
        app = QApplication.instance()
        for scroll_area in screen.findChildren(QScrollArea):
            scroll_area.setWidgetResizable(False)
            scroll_area.setWidgetResizable(True)
            inner = scroll_area.widget()
            if inner is not None:
                inner.updateGeometry()
        screen.updateGeometry()
        if app is not None:
            app.processEvents()

    def resizeEvent(self, event) -> None:  # noqa: N802 — نامِ متدِ Qt
        super().resizeEvent(event)
        # مگاپنل چون بیرونِ چیدمانِ عمودی است (geometryِ دستی)، با تغییرِ
        # اندازه‌یِ پنجره خودش را جا به‌جا نمی‌کند — اگر همین الان باز است
        # باید دوباره روی ناحیه‌یِ تازه‌یِ self.stack جا بگیرد.
        if hasattr(self, "_mega_panel_scroll") and self._mega_panel_scroll.isVisible():
            self._position_mega_panel()

    # --- هدر --------------------------------------------------------------
    # طبقِ بازخوردِ صریح: در پنجره‌هایِ کم‌عرض (مثلاً بعدِ تمام‌صفحه‌کردن رویِ
    # مانیتورهایِ کوچک‌تر از عرضِ طراحی‌شده‌ی برنامه)، چون هدر عناصرِ
    # عرض‌ثابتِ زیادی دارد (جستجو/زبان/سالِ‌مالی/شرکت/آواتار/خروج) و درونِ
    # QScrollArea نبود، این عناصر به‌جایِ اسکرول‌شدن از کادرِ هدر بیرون
    # می‌زدند و انگار «ناپدید» می‌شدند — دقیقاً همان مشکلی که ریبونِ زیرِ
    # هدر قبلاً با همین راه‌حل (QScrollAreaِ افقی) حل شده بود؛ همان الگو
    # این‌جا هم اعمال می‌شود.
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

        # طبقِ درخواستِ صریح: کلیدِ روشن/خاموش‌کردنِ کادرِ راهنمایِ فیلدها
        # (widgets.FieldHelpPanel) این‌جا، بالایِ صفحه، کنارِ نشانِ برند —
        # نه دیگر داخلِ خودِ کادر — تا همیشه در دسترس باشد، صرفِ‌نظر از
        # اینکه کدام صفحه باز است.
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

        logout_button = QPushButton("خروج")
        logout_button.setObjectName("flatButton")
        logout_button.clicked.connect(self._logout)
        layout.addWidget(logout_button)

        scroll.setWidget(header)
        return scroll

    # --- منویِ افقیِ اصلی (مگامنو) ---------------------------------------------
    # طبقِ درخواستِ صریح: ساید‌بارِ درختیِ عمودی (که فضایِ ثابتی از عرضِ صفحه
    # می‌گرفت و جابجایی/انتخاب در آن سخت بود) حذف شد و به‌جایش یک منویِ
    # افقیِ سطحِ‌بالا (این‌جا) + یک «مگاپنل»یِ بازشونده (_build_mega_panel)
    # نشسته: با کلیک رویِ هر آیتمِ سطحِ‌بالا که زیرمجموعه دارد، همه‌یِ
    # زیرمجموعه‌هایش (در هر عمقی از زیرمنو) یک‌جا و دسته‌بندی‌شده در پنلِ
    # پایینِ منو ظاهر می‌شوند؛ با انتخابِ یکی، پنل بسته می‌شود و کارِ اصلی
    # کلِ عرضِ صفحه را در اختیار می‌گیرد.
    def _build_menu_bar(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setObjectName("menuBarScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFixedHeight(48)

        bar = QWidget()
        bar.setObjectName("menuBar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(20, 4, 20, 4)
        layout.setSpacing(4)

        for item in NAV_ITEMS:
            button = QPushButton(f"{_NAV_ICONS.get(item['code'], '•')}  {item['label']}")
            button.setObjectName("menuButton")
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, c=item["code"]: self._on_menu_button_clicked(c))
            layout.addWidget(button)
            self._menu_buttons[item["code"]] = button

        layout.addStretch(1)
        scroll.setWidget(bar)
        self._menu_bar_scroll = scroll
        return scroll

    def _build_mega_panel(self) -> None:
        # طبقِ درخواستِ صریح: مگاپنل، ویجتِ فرزندِ خودِ central است اما در
        # هیچ layoutِ آن مدیریت نمی‌شود — با setGeometryِ دستی (نگاهِ
        # _position_mega_panel) دقیقاً رویِ ناحیه‌یِ self.stack می‌نشیند و
        # با raise_ رویِ آن رسم می‌شود، بدونِ اینکه فضایی از چیدمانِ عمودی
        # بگیرد یا اندازه‌یِ فرمِ زیرش را تغییر دهد.
        scroll = QScrollArea(self._central)
        scroll.setObjectName("megaPanelScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        panel = QWidget()
        panel.setObjectName("megaPanel")
        layout = QHBoxLayout(panel)
        layout.setContentsMargins(24, 16, 24, 16)
        layout.setSpacing(32)
        # طبقِ درخواستِ صریح: ستون‌ها باید چیدمانِ مرتب و چسبیده‌به‌سمتِ‌راست
        # داشته باشند، نه پخش‌شده با یک فاصله‌یِ بزرگِ خالی تا دکمه‌یِ
        # چرخ‌دنده در سمتِ چپ.
        layout.setAlignment(Qt.AlignRight | Qt.AlignTop)
        scroll.setWidget(panel)
        scroll.setVisible(False)

        self._mega_panel_layout = layout
        self._mega_panel_scroll = scroll

    def _position_mega_panel(self) -> None:
        y = self._menu_bar_scroll.y() + self._menu_bar_scroll.height()
        width = self._central.width()
        available_height = max(0, self._central.height() - y)
        height = min(360, available_height)
        self._mega_panel_scroll.setGeometry(0, y, width, height)
        self._mega_panel_scroll.raise_()

    def _on_menu_button_clicked(self, code: str) -> None:
        item = next((i for i in NAV_ITEMS if i["code"] == code), None)
        if item is None:
            return
        if not item.get("children"):
            # آیتمِ سطحِ‌بالایِ بدونِ زیرمجموعه (داشبورد/تنظیمات/ماژول‌هایِ
            # هنوز نساخته): مستقیم باز شود، مگاپنل بسته بماند.
            self._close_mega_panel()
            self.open_screen(code)
            return
        if self._mega_panel_open_code == code and self._mega_panel_scroll.isVisible():
            self._close_mega_panel()
            return
        self._populate_mega_panel(item)
        self._mega_panel_open_code = code
        self._position_mega_panel()
        self._mega_panel_scroll.setVisible(True)
        self._set_active_menu_button(code)

    def _close_mega_panel(self) -> None:
        self._mega_panel_scroll.setVisible(False)
        self._mega_panel_open_code = None

    def _build_mega_panel_column(self, title: str, entries: list[dict]) -> QWidget:
        column = QWidget()
        column_layout = QVBoxLayout(column)
        column_layout.setContentsMargins(0, 0, 0, 0)
        column_layout.setSpacing(2)
        if title:
            title_label = QLabel(title)
            title_label.setObjectName("megaPanelColumnTitle")
            column_layout.addWidget(title_label)
        for entry in entries:
            button = QPushButton(entry["label"])
            button.setObjectName("megaPanelItem")
            button.setProperty("active", entry.get("active", False))
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(entry["on_click"])
            column_layout.addWidget(button)
        column_layout.addStretch(1)
        return column

    def _populate_mega_panel(self, group: dict) -> None:
        # نکته‌یِ مهم: takeAt فقط ویجت را از مدیریتِ layout خارج می‌کند،
        # نه از دیدرس — بدونِ hide صریح، ویجتِ قدیمی تا لحظه‌یِ واقعیِ
        # حذف‌شدن (deleteLater، که معوق است) سرِ جایِ قبلی‌اش «باقی‌مانده و
        # قابلِ‌دیدن» می‌ماند و با ستون‌هایِ تازه هم‌پوشانی پیدا می‌کند.
        while self._mega_panel_layout.count():
            taken = self._mega_panel_layout.takeAt(0)
            if taken.widget():
                taken.widget().hide()
                taken.widget().deleteLater()

        # طبقِ درخواستِ صریح: عنوانِ نمایشیِ گروه‌هایِ اشخاص (مشتری/
        # تامین‌کننده/پرسنل) اگر تغییرِ نام داده باشند، باید همین‌جا زنده
        # خوانده شود — نه برچسبِ ثابتِ NAV_ITEMS.
        company_id = session.current_company.company_id if session.current_company else None
        dynamic_labels: dict[str, str] = {}
        if company_id is not None:
            names_by_group_code = {g.code: g.name for g in dimensions_service.list_person_groups(company_id)}
            for nav_code, group_code in _PERSON_GROUP_NAV_CODE_TO_GROUP_CODE.items():
                if group_code in names_by_group_code:
                    dynamic_labels[nav_code] = names_by_group_code[group_code]

        def _leaf_entries(leaves: list[dict]) -> list[dict]:
            entries = []
            for child in leaves:
                code = child["code"]
                label = dynamic_labels.get(code, child["label"])
                entries.append(
                    {
                        "label": label,
                        "active": code == self._current_screen_code,
                        "on_click": lambda _checked=False, c=code: self.open_screen(c),
                    }
                )
            return entries

        primary_leaves = [c for c in group.get("children", []) if not c.get("children") and c.get("in_ribbon", True)]
        subgroups = [c for c in group.get("children", []) if c.get("children")]
        hidden_leaves = [
            c for c in group.get("children", []) if not c.get("children") and not c.get("in_ribbon", True)
        ]

        if primary_leaves:
            self._mega_panel_layout.addWidget(
                self._build_mega_panel_column("میان‌برهایِ اصلی", _leaf_entries(primary_leaves))
            )

        for subgroup in subgroups:
            self._mega_panel_layout.addWidget(
                self._build_mega_panel_column(subgroup["label"], _leaf_entries(_leaf_nav_children(subgroup)))
            )

        # طبقِ گزارشِ صریح: گروه‌هایِ سادهِ کاربرساخته (که خودشان صفحه‌ی
        # اختصاصی ندارند و فقط درونِ «تفصیلی‌هایِ گروه‌هایِ ساده» قابلِ‌
        # مشاهده‌اند) هم باید در همین ستون ظاهر شوند — وگرنه بعدِ ساختنِ
        # گروهِ تازه، هیچ میان‌بری برایش نبود.
        hidden_entries = _leaf_entries(hidden_leaves)
        if group["code"] == "GL" and company_id is not None:
            custom_groups = [
                t
                for t in dimensions_service.list_dimension_types(company_id)
                if t.code not in dimensions_service.SPECIALIZED_DIMENSION_LABELS
            ]
            for t in custom_groups:
                hidden_entries.append(
                    {
                        "label": t.code,
                        "active": False,
                        "on_click": lambda _checked=False, tid=t.dimension_type_id: self.open_screen(
                            "GL_DIM",
                            then=lambda screen, tid=tid: screen.group_combo.setCurrentIndex(
                                screen.group_combo.findData(tid)
                            ),
                        ),
                    }
                )
        if hidden_entries:
            self._mega_panel_layout.addWidget(self._build_mega_panel_column("گروه‌هایِ تفصیلی", hidden_entries))

        # طبقِ درخواستِ صریح: دکمه‌ی چرخ‌دنده — تنظیماتِ مخصوصِ همین بخش را
        # مستقیم (تبِ مربوطه در «تنظیماتِ سیستم») باز می‌کند. فقط بخش‌هایی
        # که واقعاً نگاشته شده‌اند این دکمه را دارند.
        settings_tab_index = _SETTINGS_TAB_BY_GROUP_CODE.get(group["code"])
        if settings_tab_index is not None:
            gear_button = QPushButton("⚙")
            gear_button.setObjectName("ribbonGearButton")
            gear_button.setCursor(Qt.PointingHandCursor)
            gear_button.setToolTip(f"تنظیماتِ «{group['label']}»")
            gear_button.clicked.connect(
                lambda _checked=False, idx=settings_tab_index: self.open_screen(
                    "SETTINGS", then=lambda screen: screen.select_tab(idx)
                )
            )
            self._mega_panel_layout.addWidget(gear_button)

    def _set_active_menu_button(self, top_level_code: str | None) -> None:
        for code, button in self._menu_buttons.items():
            button.setProperty("active", code == top_level_code)
            button.style().unpolish(button)
            button.style().polish(button)

    def _find_top_level_code(self, leaf_code: str) -> str | None:
        for item in NAV_ITEMS:
            if item["code"] == leaf_code:
                return item["code"]
            if any(c["code"] == leaf_code for c in _leaf_nav_children(item)):
                return item["code"]
        return None

    def _breadcrumb_text(self, code: str) -> str:
        def _walk(items: list[dict], path: list[str]) -> list[str] | None:
            for it in items:
                new_path = path + [it["label"]]
                if it["code"] == code:
                    return new_path
                if it.get("children"):
                    found = _walk(it["children"], new_path)
                    if found:
                        return found
            return None

        path = _walk(NAV_ITEMS, []) or []
        return " / ".join(path)

    def _logout(self) -> None:
        from peecha.ui.login_window import LoginWindow  # noqa: PLC0415
        from peecha.ui.main import get_font_family  # noqa: PLC0415

        session.log_out()
        self._login_window = LoginWindow(get_font_family())
        self._login_window.show()
        self.close()

    # --- ثبت‌نامِ صفحات -----------------------------------------------------
    def _register_screens(self) -> None:
        from peecha.ui.screens.chart_of_accounts import ChartOfAccountsScreen  # noqa: PLC0415
        from peecha.ui.screens.dashboard import DashboardScreen  # noqa: PLC0415
        from peecha.ui.screens.detail_accounts_list import DetailAccountsListScreen  # noqa: PLC0415
        from peecha.ui.screens.detail_dimensions import DetailDimensionsScreen  # noqa: PLC0415
        from peecha.ui.screens.dimension_group_config import DimensionGroupConfigScreen  # noqa: PLC0415
        from peecha.ui.screens.journal_entries_list import JournalEntriesListScreen  # noqa: PLC0415
        from peecha.ui.screens.journal_entry import JournalEntryScreen  # noqa: PLC0415
        from peecha.ui.screens.person_group_screens import (  # noqa: PLC0415
            CustomersScreen,
            PersonnelScreen,
            SuppliersScreen,
        )
        from peecha.ui.screens.placeholder import PlaceholderScreen  # noqa: PLC0415
        from peecha.ui.screens.report_account_ledger import AccountLedgerScreen  # noqa: PLC0415
        from peecha.ui.screens.report_anomalies import AnomaliesScreen  # noqa: PLC0415
        from peecha.ui.screens.report_balance_sheet import BalanceSheetScreen  # noqa: PLC0415
        from peecha.ui.screens.report_cash_flow import CashFlowScreen  # noqa: PLC0415
        from peecha.ui.screens.report_custom_statement import CustomStatementScreen  # noqa: PLC0415
        from peecha.ui.screens.report_equity_changes import EquityChangesScreen  # noqa: PLC0415
        from peecha.ui.screens.report_financial_ratios import FinancialRatiosScreen  # noqa: PLC0415
        from peecha.ui.screens.report_income_statement import IncomeStatementScreen  # noqa: PLC0415
        from peecha.ui.screens.report_journal_book import JournalBookScreen  # noqa: PLC0415
        from peecha.ui.screens.report_period_comparison import PeriodComparisonScreen  # noqa: PLC0415
        from peecha.ui.screens.report_trial_balance import TrialBalanceScreen  # noqa: PLC0415
        from peecha.ui.screens.statement_template_designer import (  # noqa: PLC0415
            StatementTemplateDesignerScreen,
        )
        from peecha.ui.screens.specialized_dimensions import (  # noqa: PLC0415
            BankAccountsScreen,
            CashBoxesScreen,
            CostCentersScreen,
            FixedAssetsScreen,
            InventoryItemsScreen,
            PettyCashesScreen,
            ProjectsScreen,
        )
        from peecha.ui.screens.system_settings import SystemSettingsScreen  # noqa: PLC0415

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
        # همه‌ی فرم‌هایِ قبلاً جداگانه‌ی «مدیریتِ سیستم» (زبان‌ها/ارزها/شرکت‌ها/
        # سال‌های مالی/کاربران/نقش‌ها/عنوانِ فیلدها/ردِ حسابرسی) اکنون به‌صورتِ
        # تب درونِ system_settings.SystemSettingsScreen زندگی می‌کنند — نکته‌ی
        # «ترجمه‌ها»یِ بدونِ معادلِ Qt هم همان‌جا (به‌عنوانِ یک تبِ Placeholder)
        # مستند شده، نه اینجا.

    def register_screen(self, name: str, widget: QWidget) -> None:
        self._screens[name] = widget
        self.stack.addWidget(widget)
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
        self._close_mega_panel()
        self._set_active_menu_button(self._find_top_level_code(code))
        self.breadcrumb_label.setText(self._breadcrumb_text(code))

        target_screen_name = item["screen"] or "placeholder"
        screen = self._screens.get(target_screen_name)
        if screen is None:
            screen = self._screens["placeholder"]
        if screen is self._screens["placeholder"]:
            screen.set_module_name(item["label"])

        self.stack.setCurrentWidget(screen)
        # _CurrentOnlyStackedWidget فقط اندازه‌ی همین صفحه را برمی‌گرداند —
        # updateGeometry مطمئن می‌شود چیدمانِ بیرونی بلافاصله با آن هماهنگ شود.
        self.stack.updateGeometry()
        if hasattr(screen, "refresh"):
            screen.refresh()
        # طبقِ گزارشِ صریح: هر بار با ساید‌بار به منویِ تازه‌ای سوییچ می‌شد،
        # چیدمانِ فرمِ بازشده به‌هم می‌ریخت و آیتم‌هایِ فوتر در دسترس
        # نبودند — همان دلیلِ _force_relayout در showEvent، این‌جا هم بعدِ
        # هر سوییچ لازم است (نه فقط بارِ اول). تأخیرِ کوتاه تا محتوایِ
        # refresh (که ممکن است خودش رویدادها را صف کند) پیش از نوکِ
        # resize کامل بنشیند.
        QTimer.singleShot(30, self._force_relayout)
        if then is not None:
            then(screen)

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

    def _on_company_changed(self, index: int) -> None:
        if index < 0:
            return
        company_id = self.company_combo.itemData(index)
        if company_id is None:
            return
        if session.current_company is not None and session.current_company.company_id == company_id:
            return
        session.current_company = companies_service.get_company_model(company_id)
        current = self.stack.currentWidget()
        if hasattr(current, "refresh"):
            current.refresh()
