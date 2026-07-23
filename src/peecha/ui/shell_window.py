"""پنجره‌ی اصلیِ برنامه (پوسته) — معادلِ Qt برایِ shell.py/shell.kv در Kivy.

تفاوتِ کلیدی با نسخه‌ی Kivy: هیچ تکنیکِ «ترتیبِ معکوسِ اعلامِ فرزندان»
لازم نیست — با `app.setLayoutDirection(Qt.RightToLeft)` (در main.py)،
خودِ Qt ترتیبِ افقیِ هر QHBoxLayout/QSplitter را آینه می‌کند، و
QTreeWidget/QComboBox به‌طورِ بومی راست‌چین و جهت‌دار می‌شوند."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from peecha import session
from peecha.services import companies as companies_service
from peecha.services import fiscal_years as fiscal_years_service
from peecha.services import languages as languages_service
from peecha.ui import numerals, theme

# همان NAV_ITEMS طبقِ shell.py (نسخه‌ی Kivy) — عمداً اینجا هم تکرار شده
# تا این ماژول به‌هیچ‌وجه کیویی import نکند (هدفِ کلِ این مهاجرت).
NAV_ITEMS = [
    {"code": "dashboard", "label": "داشبورد", "screen": "dashboard"},
    {
        "code": "GL",
        "label": "مالی و حسابداری",
        "children": [
            {"code": "GL_COA", "label": "کدینگ حسابداری", "screen": "chart_of_accounts"},
            {"code": "GL_TAFSILI", "label": "تفصیلی‌ها", "screen": "detail_accounts_list"},
            {"code": "GL_CUSTOMERS", "label": "مشتریان", "screen": "customers"},
            {"code": "GL_SUPPLIERS", "label": "تامین‌کنندگان", "screen": "suppliers"},
            {"code": "GL_PERSONNEL", "label": "پرسنل", "screen": "personnel"},
            {"code": "GL_JE_LIST", "label": "اسناد حسابداری", "screen": "journal_entries_list"},
            {"code": "GL_JE", "label": "صدور سند جدید", "screen": "journal_entry"},
            {"code": "GL_DIM", "label": "مراکز هزینه و ابعادِ تفصیلی", "screen": "detail_dimensions"},
        ],
    },
    {"code": "INV", "label": "انبار و موجودی", "screen": None},
    {"code": "SALES", "label": "فروش و بازاریابی", "screen": None},
    {"code": "PURCH", "label": "خرید و تدارکات", "screen": None},
    {"code": "HR", "label": "منابع انسانی", "screen": None},
    {"code": "INVOICES", "label": "فاکتورها", "screen": None},
    {"code": "REPORTS", "label": "گزارش‌ها", "screen": None},
    # این آیتم قبلاً یک گروهِ ۹-فرزندی بود؛ حالا همه‌ی آن فرم‌ها به‌صورتِ
    # تب‌هایِ سازمان‌یافته درونِ یک صفحه‌ی واحد («system_settings») جمع شده‌اند.
    {"code": "SETTINGS", "label": "تنظیمات سیستم", "screen": "system_settings"},
]

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


def _flatten_nav_items() -> list[dict]:
    flat: list[dict] = []
    for item in NAV_ITEMS:
        if "children" in item:
            flat.extend(item["children"])
        else:
            flat.append(item)
    return flat


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("پیچا")
        self.resize(1440, 900)

        self._screens: dict[str, QWidget] = {}
        self._tree_items_by_code: dict[str, QTreeWidgetItem] = {}
        self._company_options: list[companies_service.CompanyRow] = []

        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        outer.addWidget(self._build_header())

        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)

        body_layout.addWidget(self._build_sidebar())

        self.stack = QStackedWidget()
        body_layout.addWidget(self.stack, stretch=1)

        outer.addWidget(body, stretch=1)

        self._register_screens()
        self.open_screen("dashboard")

    # --- هدر --------------------------------------------------------------
    def _build_header(self) -> QWidget:
        header = QWidget()
        header.setObjectName("headerBar")
        header.setFixedHeight(68)
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

        return header

    def _logout(self) -> None:
        from peecha.ui.login_window import LoginWindow  # noqa: PLC0415
        from peecha.ui.main import get_font_family  # noqa: PLC0415

        session.log_out()
        self._login_window = LoginWindow(get_font_family())
        self._login_window.show()
        self.close()

    # --- نوارِ کناری --------------------------------------------------------
    _SIDEBAR_WIDTH_EXPANDED = 272
    _SIDEBAR_WIDTH_COLLAPSED = 64

    def _build_sidebar(self) -> QWidget:
        container = QWidget()
        container.setObjectName("sidebarContainer")
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)

        toggle_row = QHBoxLayout()
        toggle_row.setContentsMargins(10, 10, 10, 6)
        self.sidebar_toggle_button = QPushButton("☰")
        self.sidebar_toggle_button.setObjectName("sidebarToggle")
        self.sidebar_toggle_button.setFixedSize(32, 32)
        self.sidebar_toggle_button.setCursor(Qt.PointingHandCursor)
        self.sidebar_toggle_button.setToolTip("جمع‌کردنِ نوارِ کناری")
        self.sidebar_toggle_button.clicked.connect(
            lambda: self._set_sidebar_collapsed(not self._sidebar_collapsed)
        )
        toggle_row.addWidget(self.sidebar_toggle_button)
        toggle_row.addStretch(1)
        container_layout.addLayout(toggle_row)

        tree = QTreeWidget()
        tree.setObjectName("sidebar")
        tree.setHeaderHidden(True)
        tree.setIndentation(14)
        tree.setUniformRowHeights(True)
        tree.itemClicked.connect(self._on_tree_item_clicked)

        for item in NAV_ITEMS:
            node = QTreeWidgetItem([item["label"]])
            node.setData(0, Qt.UserRole, item["code"])
            node.setData(0, Qt.UserRole + 1, item["label"])
            node.setIcon(0, theme.emoji_icon(_NAV_ICONS.get(item["code"], "•")))
            tree.addTopLevelItem(node)
            self._tree_items_by_code[item["code"]] = node
            for child in item.get("children", []):
                child_node = QTreeWidgetItem([child["label"]])
                child_node.setData(0, Qt.UserRole, child["code"])
                child_node.setData(0, Qt.UserRole + 1, child["label"])
                node.addChild(child_node)
                self._tree_items_by_code[child["code"]] = child_node

        tree.expandAll()
        self.sidebar = tree
        container_layout.addWidget(tree, stretch=1)

        self._sidebar_collapsed = False
        self.sidebar_container = container
        container.setFixedWidth(self._SIDEBAR_WIDTH_EXPANDED)
        return container

    def _set_sidebar_collapsed(self, collapsed: bool) -> None:
        self._sidebar_collapsed = collapsed
        self.sidebar_container.setFixedWidth(
            self._SIDEBAR_WIDTH_COLLAPSED if collapsed else self._SIDEBAR_WIDTH_EXPANDED
        )
        self.sidebar.setRootIsDecorated(not collapsed)
        self.sidebar.setIndentation(0 if collapsed else 14)
        for item in self._tree_items_by_code.values():
            label = item.data(0, Qt.UserRole + 1)
            item.setText(0, "" if collapsed else label)
        if collapsed:
            self.sidebar.collapseAll()
        self.sidebar_toggle_button.setToolTip(
            "بازکردنِ نوارِ کناری" if collapsed else "جمع‌کردنِ نوارِ کناری"
        )

    def _on_tree_item_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        code = item.data(0, Qt.UserRole)
        if item.childCount() > 0:
            # آیتمِ گروه (مثلِ «مالی و حسابداری»): آکاردئونی باز/بسته می‌شود
            # (فقط یک گروه هم‌زمان باز می‌ماند) — اگر ساید‌بار جمع بود، اول
            # برایِ نشان‌دادنِ فرزندها باز می‌شود.
            if self._sidebar_collapsed:
                self._set_sidebar_collapsed(False)
            expand = not item.isExpanded()
            for i in range(self.sidebar.topLevelItemCount()):
                top = self.sidebar.topLevelItem(i)
                if top.childCount() > 0:
                    top.setExpanded(top is item and expand)
            return
        flat = {i["code"]: i for i in _flatten_nav_items()}
        if code in flat:
            self.open_screen(code)

    # --- ثبت‌نامِ صفحات -----------------------------------------------------
    def _register_screens(self) -> None:
        from peecha.ui.screens.chart_of_accounts import ChartOfAccountsScreen  # noqa: PLC0415
        from peecha.ui.screens.dashboard import DashboardScreen  # noqa: PLC0415
        from peecha.ui.screens.detail_accounts_list import DetailAccountsListScreen  # noqa: PLC0415
        from peecha.ui.screens.detail_dimensions import DetailDimensionsScreen  # noqa: PLC0415
        from peecha.ui.screens.journal_entries_list import JournalEntriesListScreen  # noqa: PLC0415
        from peecha.ui.screens.journal_entry import JournalEntryScreen  # noqa: PLC0415
        from peecha.ui.screens.person_group_screens import (  # noqa: PLC0415
            CustomersScreen,
            PersonnelScreen,
            SuppliersScreen,
        )
        from peecha.ui.screens.placeholder import PlaceholderScreen  # noqa: PLC0415
        from peecha.ui.screens.system_settings import SystemSettingsScreen  # noqa: PLC0415

        self.register_screen("dashboard", DashboardScreen())
        self.register_screen("placeholder", PlaceholderScreen())
        self.register_screen("chart_of_accounts", ChartOfAccountsScreen())
        self.register_screen("system_settings", SystemSettingsScreen())
        self.register_screen("customers", CustomersScreen())
        self.register_screen("suppliers", SuppliersScreen())
        self.register_screen("personnel", PersonnelScreen())
        self.register_screen("detail_dimensions", DetailDimensionsScreen())
        self.register_screen("detail_accounts_list", DetailAccountsListScreen(self))
        self.register_screen("journal_entry", JournalEntryScreen())
        self.register_screen("journal_entries_list", JournalEntriesListScreen(self))
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

        tree_item = self._tree_items_by_code.get(code)
        if tree_item is not None:
            self.sidebar.setCurrentItem(tree_item)

        target_screen_name = item["screen"] or "placeholder"
        screen = self._screens.get(target_screen_name)
        if screen is None:
            screen = self._screens["placeholder"]
        if screen is self._screens["placeholder"]:
            screen.set_module_name(item["label"])

        self.stack.setCurrentWidget(screen)
        if hasattr(screen, "refresh"):
            screen.refresh()
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
