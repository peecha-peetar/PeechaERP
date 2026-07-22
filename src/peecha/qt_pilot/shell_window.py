"""پنجره‌ی اصلیِ برنامه (پوسته) — معادلِ Qt برایِ shell.py/shell.kv در Kivy.

تفاوتِ کلیدی با نسخه‌ی Kivy: هیچ تکنیکِ «ترتیبِ معکوسِ اعلامِ فرزندان»
لازم نیست — با `app.setLayoutDirection(Qt.RightToLeft)` (در main.py)،
خودِ Qt ترتیبِ افقیِ هر QHBoxLayout/QSplitter را آینه می‌کند، و
QTreeWidget/QComboBox به‌طورِ بومی راست‌چین و جهت‌دار می‌شوند."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QSizePolicy,
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
    {
        "code": "SETTINGS",
        "label": "مدیریت سیستم",
        "children": [
            {"code": "SET_LANG", "label": "زبان‌ها", "screen": "languages"},
            {"code": "SET_CURRENCY", "label": "ارزها", "screen": "currencies"},
            {"code": "SET_COMPANY", "label": "شرکت‌ها", "screen": "companies"},
            {"code": "SET_FY", "label": "سال‌های مالی", "screen": "fiscal_years"},
            {"code": "SET_USERS", "label": "کاربران", "screen": "users"},
            {"code": "SET_ROLES", "label": "نقش‌ها و دسترسی‌ها", "screen": "roles"},
            {"code": "SET_FIELD_LABELS", "label": "عنوانِ فیلدها", "screen": "field_labels"},
            {"code": "SET_TRANSLATIONS", "label": "ترجمه‌ها", "screen": "translations"},
            {"code": "SET_AUDIT_LOG", "label": "ردِ حسابرسی", "screen": "audit_log"},
        ],
    },
]


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
        header.setFixedHeight(64)
        layout = QHBoxLayout(header)
        layout.setContentsMargins(20, 8, 20, 8)
        layout.setSpacing(16)

        search = QLineEdit()
        search.setPlaceholderText("جستجو در سیستم...")
        search.setFixedWidth(320)
        layout.addWidget(search)

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
        layout.addWidget(divider)

        self.user_label = QLabel("")
        layout.addWidget(self.user_label)

        logout_button = QPushButton("خروج")
        logout_button.setObjectName("flatButton")
        logout_button.clicked.connect(self._logout)
        layout.addWidget(logout_button)

        return header

    def _logout(self) -> None:
        from peecha.qt_pilot.login_window import LoginWindow  # noqa: PLC0415
        from peecha.qt_pilot.main import get_font_family  # noqa: PLC0415

        session.log_out()
        self._login_window = LoginWindow(get_font_family())
        self._login_window.show()
        self.close()

    # --- نوارِ کناری --------------------------------------------------------
    def _build_sidebar(self) -> QTreeWidget:
        tree = QTreeWidget()
        tree.setHeaderHidden(True)
        tree.setFixedWidth(260)
        tree.itemClicked.connect(self._on_tree_item_clicked)

        for item in NAV_ITEMS:
            node = QTreeWidgetItem([item["label"]])
            node.setData(0, Qt.UserRole, item["code"])
            tree.addTopLevelItem(node)
            self._tree_items_by_code[item["code"]] = node
            for child in item.get("children", []):
                child_node = QTreeWidgetItem([child["label"]])
                child_node.setData(0, Qt.UserRole, child["code"])
                node.addChild(child_node)
                self._tree_items_by_code[child["code"]] = child_node

        tree.expandAll()
        self.sidebar = tree
        return tree

    def _on_tree_item_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        code = item.data(0, Qt.UserRole)
        flat = {i["code"]: i for i in _flatten_nav_items()}
        if code in flat:
            self.open_screen(code)

    # --- ثبت‌نامِ صفحات -----------------------------------------------------
    def _register_screens(self) -> None:
        from peecha.qt_pilot.screens.chart_of_accounts import ChartOfAccountsScreen  # noqa: PLC0415
        from peecha.qt_pilot.screens.companies import CompaniesScreen  # noqa: PLC0415
        from peecha.qt_pilot.screens.currencies import CurrenciesScreen  # noqa: PLC0415
        from peecha.qt_pilot.screens.dashboard import DashboardScreen  # noqa: PLC0415
        from peecha.qt_pilot.screens.fiscal_years import FiscalYearsScreen  # noqa: PLC0415
        from peecha.qt_pilot.screens.audit_log import AuditLogScreen  # noqa: PLC0415
        from peecha.qt_pilot.screens.detail_accounts_list import DetailAccountsListScreen  # noqa: PLC0415
        from peecha.qt_pilot.screens.detail_dimensions import DetailDimensionsScreen  # noqa: PLC0415
        from peecha.qt_pilot.screens.field_labels import FieldLabelsScreen  # noqa: PLC0415
        from peecha.qt_pilot.screens.journal_entries_list import JournalEntriesListScreen  # noqa: PLC0415
        from peecha.qt_pilot.screens.journal_entry import JournalEntryScreen  # noqa: PLC0415
        from peecha.qt_pilot.screens.languages import LanguagesScreen  # noqa: PLC0415
        from peecha.qt_pilot.screens.person_group_screens import (  # noqa: PLC0415
            CustomersScreen,
            PersonnelScreen,
            SuppliersScreen,
        )
        from peecha.qt_pilot.screens.placeholder import PlaceholderScreen  # noqa: PLC0415
        from peecha.qt_pilot.screens.roles import RolesScreen  # noqa: PLC0415
        from peecha.qt_pilot.screens.users import UsersScreen  # noqa: PLC0415

        self.register_screen("dashboard", DashboardScreen())
        self.register_screen("placeholder", PlaceholderScreen())
        self.register_screen("chart_of_accounts", ChartOfAccountsScreen())
        self.register_screen("languages", LanguagesScreen())
        self.register_screen("currencies", CurrenciesScreen())
        self.register_screen("companies", CompaniesScreen())
        self.register_screen("fiscal_years", FiscalYearsScreen())
        self.register_screen("users", UsersScreen())
        self.register_screen("roles", RolesScreen())
        self.register_screen("customers", CustomersScreen())
        self.register_screen("suppliers", SuppliersScreen())
        self.register_screen("personnel", PersonnelScreen())
        self.register_screen("detail_dimensions", DetailDimensionsScreen())
        self.register_screen("detail_accounts_list", DetailAccountsListScreen(self))
        self.register_screen("journal_entry", JournalEntryScreen())
        self.register_screen("journal_entries_list", JournalEntriesListScreen(self))
        self.register_screen("field_labels", FieldLabelsScreen())
        self.register_screen("audit_log", AuditLogScreen())
        # نکته: صفحه‌ی «ترجمه‌ها»‌یِ Kivy مخصوصِ کاتالوگِ رشته‌هایِ ثابتِ
        # KV (فایل‌هایِ src/peecha/locales/*.json) بود — این مکانیزم کاملاً
        # مخصوصِ همان معماریِ Kivyِ بازنشسته‌شده است (رشته‌های تایپ‌شده در
        # کدِ پایتونیِ Qt نیازی به چنین کاتالوگی ندارند)، پس عمداً بدونِ
        # جایگزین مانده — کلیک روی «ترجمه‌ها» به‌طورِ خودکار Placeholder
        # نشان می‌دهد.

    def register_screen(self, name: str, widget: QWidget) -> None:
        self._screens[name] = widget
        self.stack.addWidget(widget)

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
                self.fiscal_year_combo.addItem(fy.code, fy.fiscal_year_id)

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
