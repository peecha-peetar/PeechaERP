"""پنجره‌ی اصلیِ برنامه (پوسته) — معادلِ Qt برایِ shell.py/shell.kv در Kivy.

تفاوتِ کلیدی با نسخه‌ی Kivy: هیچ تکنیکِ «ترتیبِ معکوسِ اعلامِ فرزندان»
لازم نیست — با `app.setLayoutDirection(Qt.RightToLeft)` (در main.py)،
خودِ Qt ترتیبِ افقیِ هر QHBoxLayout را آینه می‌کند، و QComboBox به‌طورِ
بومی راست‌چین و جهت‌دار می‌شود.

ناوبریِ اصلی یک منویِ افقی (مگامنو) زیرِ هدر است —
_build_menu_bar آیتم‌هایِ سطحِ‌بالا را نشان می‌دهد و _build_mega_panel
با کلیک رویِ هرکدام، زیرمجموعه‌هایش را در یک پنلِ شناور (دسته‌بندی‌شده
به ستون) نمایش می‌دهد.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QTimer, Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QGraphicsDropShadowEffect,
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

from peecha import numerals, session
from peecha.nav_catalog import NAV_ITEMS
from peecha.nav_catalog import flatten_nav_items as _flatten_nav_items
from peecha.services import companies as companies_service
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import fiscal_years as fiscal_years_service
from peecha.services import languages as languages_service
from peecha.ui import theme
from peecha.ui.widgets import field_help_is_enabled, set_field_help_enabled

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


class FloatingMegaPanel(QWidget):
    """پنل مگامنوی شناور واقعی با چیدمان وسط‌چین و راست‌به‌چپ (RTL)."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)

        self.container = QFrame(self)
        self.container.setObjectName("megaPanelContainer")
        self.container.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.container.setStyleSheet(f"""
            QFrame#megaPanelContainer {{
                background-color: #FFFFFF;
                border: 1px solid {theme.BORDER};
                border-radius: 12px;
            }}
            QLabel#megaPanelColumnTitle {{
                color: {theme.TEXT_SECONDARY};
                font-size: 11px;
                font-weight: bold;
                padding-bottom: 6px;
            }}
            QPushButton#megaPanelItem {{
                background-color: #F8FAFC;
                color: {theme.TEXT_PRIMARY};
                border: 1px solid {theme.BORDER};
                border-radius: 6px;
                padding: 8px 14px;
                text-align: center;
                font-size: 12px;
                min-width: 170px;
            }}
            QPushButton#megaPanelItem:hover {{
                background-color: #E0F2FE;
                color: #0369A1;
                border-color: #38BDF8;
            }}
            QPushButton#megaPanelItem[active="true"] {{
                background-color: #2563EB;
                color: #FFFFFF;
                border-color: #1D4ED8;
            }}
            QPushButton#ribbonGearButton {{
                background-color: #F1F5F9;
                border: 1px solid {theme.BORDER};
                border-radius: 8px;
                padding: 6px 10px;
                font-size: 14px;
            }}
            QPushButton#ribbonGearButton:hover {{
                background-color: #E2E8F0;
            }}
        """)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(20)
        shadow.setXOffset(0)
        shadow.setYOffset(6)
        shadow.setColor(QColor(0, 0, 0, 40))
        self.container.setGraphicsEffect(shadow)

        self.root_layout = QVBoxLayout(self)
        self.root_layout.setContentsMargins(0, 0, 0, 0)

        self.scroll_area = QScrollArea()
        self.scroll_area.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll_area.setStyleSheet("background: transparent;")

        self.content_widget = QWidget()
        self.content_widget.setLayoutDirection(Qt.LayoutDirection.RightToLeft)

        self.content_layout = QHBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(16, 16, 16, 16)
        self.content_layout.setSpacing(20)

        self.scroll_area.setWidget(self.content_widget)

        container_layout = QVBoxLayout(self.container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.addWidget(self.scroll_area)

        self.root_layout.addWidget(self.container)

    def show_below(self, target_button: QWidget) -> None:
        self.content_widget.adjustSize()
        self.container.adjustSize()

        needed_width = self.content_widget.sizeHint().width() + 10
        needed_height = self.content_widget.sizeHint().height() + 10

        max_h = 450
        final_h = min(needed_height, max_h)

        self.setFixedSize(needed_width, final_h)

        # محاسبه مرکز افقی دکمه در مختصات مانیتور
        btn_top_left = target_button.mapToGlobal(QPoint(0, 0))
        btn_center_x = btn_top_left.x() + (target_button.width() // 2)

        # قرار دادن مرکز پنل دقیقاً روی مرکز افقی دکمه (وسط‌چین کامل)
        x_pos = btn_center_x - (needed_width // 2)
        y_pos = btn_top_left.y() + target_button.height() + 4

        # تنظیم پوزیشن و نمایش
        self.move(int(x_pos), int(y_pos))
        self.show()
        self.raise_()


class _CurrentOnlyStackedWidget(QStackedWidget):
    def sizeHint(self):
        current = self.currentWidget()
        return current.sizeHint() if current is not None else super().sizeHint()

    def minimumSizeHint(self):
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

        self._mega_panel_popup = FloatingMegaPanel(self)
        self._mega_panel_layout = self._mega_panel_popup.content_layout

        self._register_screens()
        self.open_screen("dashboard")
        self._did_initial_relayout = False

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

        logout_button = QPushButton("خروج")
        logout_button.setObjectName("flatButton")
        logout_button.clicked.connect(self._logout)
        layout.addWidget(logout_button)

        scroll.setWidget(header)
        return scroll

    # --- منویِ افقیِ اصلی (مگامنو) ---------------------------------------------
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

    def _on_menu_button_clicked(self, code: str) -> None:
        item = next((i for i in NAV_ITEMS if i["code"] == code), None)
        if item is None:
            return
        if not item.get("children"):
            self._close_mega_panel()
            self.open_screen(code)
            return
        if self._mega_panel_open_code == code and self._mega_panel_popup.isVisible():
            self._close_mega_panel()
            return

        self._populate_mega_panel(item)
        self._mega_panel_open_code = code

        target_btn = self._menu_buttons.get(code)
        if target_btn:
            self._mega_panel_popup.show_below(target_btn)
        self._set_active_menu_button(code)

    def _close_mega_panel(self) -> None:
        if self._mega_panel_popup.isVisible():
            self._mega_panel_popup.close()
        self._mega_panel_open_code = None

    def _build_mega_panel_column(self, title: str, entries: list[dict]) -> QWidget:
        column = QWidget()
        column.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        column_layout = QVBoxLayout(column)
        column_layout.setContentsMargins(0, 0, 0, 0)
        column_layout.setSpacing(6)

        if title:
            title_label = QLabel(title)
            title_label.setObjectName("megaPanelColumnTitle")
            title_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
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
        # پاکسازی آیتم‌های قبلی
        while self._mega_panel_layout.count():
            taken = self._mega_panel_layout.takeAt(0)
            if taken.widget():
                taken.widget().hide()
                taken.widget().deleteLater()

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
                self._build_mega_panel_column("میان‌برهای اصلی", _leaf_entries(primary_leaves))
            )

        for subgroup in subgroups:
            self._mega_panel_layout.addWidget(
                self._build_mega_panel_column(subgroup["label"], _leaf_entries(_leaf_nav_children(subgroup)))
            )

        hidden_entries = _leaf_entries(hidden_leaves)
        if group["code"] == "GL" and company_id is not None:
            custom_groups = [
                t
                for t in dimensions_service.list_dimension_types(company_id)
                if t.code not in dimensions_service.SPECIALIZED_DIMENSION_LABELS
            ]
            for t in custom_groups:
                dimension_type_id = t.dimension_type_id
                hidden_entries.append(
                    {
                        "label": t.code,
                        "active": False,
                        "on_click": lambda _checked=False, tid=dimension_type_id: self.open_screen(
                            "GL_DIM",
                            then=lambda screen, target_tid=tid: screen.group_combo.setCurrentIndex(
                                screen.group_combo.findData(target_tid)
                            ),
                        ),
                    }
                )
        if hidden_entries:
            self._mega_panel_layout.addWidget(self._build_mega_panel_column("گروه‌های تفصیلی", hidden_entries))

        settings_tab_index = _SETTINGS_TAB_BY_GROUP_CODE.get(group["code"])
        if settings_tab_index is not None:
            gear_button = QPushButton("⚙")
            gear_button.setObjectName("ribbonGearButton")
            gear_button.setCursor(Qt.PointingHandCursor)
            gear_button.setToolTip(f"تنظیمات «{group['label']}»")
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
        self.stack.updateGeometry()
        if hasattr(screen, "refresh"):
            screen.refresh()

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
