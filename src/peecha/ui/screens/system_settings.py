"""فرمِ یکپارچه‌ی «تنظیماتِ سیستم» — همه‌ی فرم‌هایی که قبلاً آیتم‌هایِ
جداگانه‌ی زیرمجموعه‌ی «مدیریتِ سیستم» در نوارِ کناری بودند، این‌جا به‌صورتِ
تب‌هایِ سازمان‌یافته (و در هر تب، زیرتب‌هایِ مرتبط) کنار هم قرار گرفته‌اند."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QCompleter, QFrame, QHBoxLayout, QLabel, QScrollArea, QTabWidget, QVBoxLayout, QWidget

from peecha.ui.screens.accounting_coding import AccountingCodingSettingsScreen, DetailLevelDigitSettingsScreen
from peecha.ui.screens.audit_log import AuditLogScreen
from peecha.ui.screens.commercial_settings import (
    _AccountMappingsTab as _CommercialAccountMappingsTab,
    _ChannelsTab as _CommercialChannelsTab,
    _FeatureToggleTab,
    _IndustryProfileTab,
    _NumberingSequencesTab,
    _SettlementAlarmTab,
)
from peecha.ui.screens.companies import CompaniesScreen
from peecha.ui.screens.currencies import CurrenciesScreen
from peecha.ui.screens.field_labels import FieldLabelsScreen
from peecha.ui.screens.financial_statement_mapping import FinancialStatementMappingScreen
from peecha.ui.screens.fiscal_years import FiscalYearsScreen
from peecha.ui.screens.inventory_settings import (
    _AccountMappingsTab,
    _BrandManufacturerTab,
    _CategoriesTab,
    _CostingSettingsTab,
    _FeatureToggleTab as _InventoryFeatureToggleTab,
    _ReasonCodesTab,
    _UomTab,
)
from peecha.ui.screens.languages import LanguagesScreen
from peecha.ui.screens.payroll_settings import (
    _AttendanceTemplatesTab,
    _GeneralSettingsTab,
    _InsuranceTab,
    _MinimumWageTab,
    _OvertimeRulesTab,
    _PayItemsTab,
    _PoliciesTab,
    _TaxTab,
)
from peecha.ui.screens.report_template_settings import _ReportTemplatesTab
from peecha.ui.screens.roles import RolesScreen
from peecha.ui.screens.translations import TranslationsScreen
from peecha.ui.screens.treasury_banks import TreasuryBanksScreen
from peecha.ui.screens.treasury_counterparty_settings import TreasuryCounterpartySettingsScreen
from peecha.ui.screens.users import UsersScreen
from peecha.ui.screens.workflow_designer import WorkflowDesignerScreen


class SystemSettingsScreen(QWidget):
    # طبقِ رفعِ باگِ صریح («بازکردنِ تنظیماتِ حسابداری/ماژول‌ها ۱۰ تا ۱۵
    # ثانیه طول می‌کشد»): این صفحه یک singletonِ سنگین است که ~۴۰ زیرصفحه‌یِ
    # مستقل (کدینگ/خزانه‌داری/عمومی/کاربران/حقوق‌ودستمزد/انبار/بازرگانی و...)
    # را همه با هم می‌سازد. علتِ اصلیِ کندی ساختِ ویجت‌ها نبود، بلکه
    # refresh() قبلی بود که هر بار (نه فقط بارِ اول) رویِ *هر ۴۰ زیرصفحه*
    # کوئریِ دیتابیس می‌زد — درحالی‌که فقط یکی از آن‌ها هم‌زمان دیده
    # می‌شود. حالا refresh فقط برایِ زیرصفحه‌ی *فعلاً قابلِ‌مشاهده* اجرا
    # می‌شود، و بقیه فقط وقتی که کاربر واقعاً به آن تب/زیرتب سوییچ کند
    # (currentChanged) به‌روزرسانی می‌شوند — تنبل (lazy)، نه همه‌باهم.
    def __init__(self) -> None:
        super().__init__()
        self._sub_screens: list[QWidget] = []
        # برایِ هر تبِ سطحِ‌بالا، یک تابعِ بدونِ‌آرگومان که فقط زیرصفحه‌ی
        # *فعلاً قابلِ‌مشاهده‌ی همان تب* را رفرش می‌کند.
        self._outer_tab_refreshers: list = []
        # طبقِ رفعِ باگِ صریح («ارتفاعِ صفحات زیاد است، پیدا کردنِ تنظیمِ
        # خاص زمان‌بر است»): نمایه‌یِ مسطحِ همه‌یِ تب/زیرتب‌ها برایِ
        # جستجوی زنده — هر آیتم یک تاپلِ (outer_index, inner_widget_or_None,
        # inner_index_or_None) دارد تا با انتخاب، مستقیم به همان‌جا پرید.
        self._search_targets: list[tuple[int, QTabWidget | None, int | None]] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 14, 20, 14)
        outer.setSpacing(12)

        title = QLabel("تنظیمات سیستم")
        title.setObjectName("pageTitle")
        outer.addWidget(title)

        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("جستجو در تنظیمات:"))
        self.settings_search = QComboBox()
        self.settings_search.setEditable(True)
        self.settings_search.setInsertPolicy(QComboBox.NoInsert)
        self.settings_search.lineEdit().setPlaceholderText("مثلاً «بانک‌ها»، «ارزها»، «کاربران»…")
        self.settings_search.setMinimumWidth(320)
        search_row.addWidget(self.settings_search)
        search_row.addStretch(1)
        outer.addLayout(search_row)

        self.tabs = QTabWidget()
        # طبقِ درخواستِ صریح: کدینگِ حسابداری باید اولین کاری باشد که در
        # تنظیماتِ حسابداری انجام می‌شود — به همین دلیل اولین تب است.
        self._add_outer_tab("کدینگِ حسابداری", self._build_coding_tab())
        self._add_outer_tab("خزانه‌داری", self._build_treasury_tab())
        self._add_outer_tab("عمومی", self._build_general_tab())
        self._add_outer_tab("کاربران و دسترسی‌ها", self._build_users_tab())
        self._add_outer_tab("داده‌های حسابداری", self._build_accounting_data_tab())
        self._add_outer_tab("امنیت", self._build_security_tab())
        # طبقِ درخواستِ صریح: تنظیماتِ حقوق‌ودستمزد از یک صفحه‌یِ مستقل به
        # این‌جا منتقل شد — دسترسی هم از این تب و هم از آیکونِ چرخ‌دنده‌یِ
        # کنارِ گروهِ «منابعِ انسانی» (shell_window.py).
        self._add_outer_tab("حقوق و دستمزد", self._build_payroll_tab())
        # طبقِ همان الگوی حقوق‌ودستمزد: تنظیماتِ ماژولِ انبار هم این‌جا و
        # هم از آیکونِ چرخ‌دنده‌یِ کنارِ گروهِ «انبار و موجودی» در دسترس است.
        self._add_outer_tab("انبار و موجودی", self._build_inventory_tab())
        # طبقِ همان الگو: تنظیماتِ مدیریتِ بازرگانی هم این‌جا و هم از
        # آیکونِ چرخ‌دنده‌یِ کنارِ گروه‌هایِ «فروش»/«خرید» در دسترس است.
        self._add_outer_tab("مدیریتِ بازرگانی", self._build_commercial_tab())
        # طبقِ درخواستِ صریح («برایِ هر فرم بتوان چند گزارشِ نام‌گذاری‌شده
        # تعریف/ویرایش/اجرا کرد»): رجیستریِ گزارش‌هایِ حرفه‌ای (Jasper) --
        # هر فرمِ پشتیبانی‌شده (کاردکس، فاکتور) یک پنلِ مستقل این‌جا دارد.
        self._add_outer_tab("گزارش‌هایِ حرفه‌ای", self._build_reports_tab())
        self.tabs.currentChanged.connect(self._on_outer_tab_changed)
        outer.addWidget(self.tabs, stretch=1)

        search_items = [self.settings_search.itemText(i) for i in range(self.settings_search.count())]
        completer = QCompleter(search_items)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains)
        completer.activated.connect(self._on_search_return)
        self.settings_search.setCompleter(completer)
        self.settings_search.setCurrentIndex(-1)
        self.settings_search.activated.connect(self._on_search_activated)
        self.settings_search.lineEdit().returnPressed.connect(self._on_search_return)

    def _add_outer_tab(self, label: str, built: tuple[QWidget, "callable"]) -> None:
        widget, refresher = built
        outer_index = self.tabs.count()
        self.tabs.addTab(widget, label)
        self._outer_tab_refreshers.append(refresher)
        if isinstance(widget, QTabWidget):
            for inner_index in range(widget.count()):
                search_label = f"{label} ›  {widget.tabText(inner_index)}"
                self.settings_search.addItem(search_label, (outer_index, widget, inner_index))
                self._search_targets.append((outer_index, widget, inner_index))
        else:
            self.settings_search.addItem(label, (outer_index, None, None))
            self._search_targets.append((outer_index, None, None))

    def _on_outer_tab_changed(self, index: int) -> None:
        if 0 <= index < len(self._outer_tab_refreshers):
            self._outer_tab_refreshers[index]()

    def _jump_to(self, target: tuple[int, QTabWidget | None, int | None]) -> None:
        outer_index, inner_widget, inner_index = target
        self.tabs.setCurrentIndex(outer_index)
        if inner_widget is not None and inner_index is not None:
            inner_widget.setCurrentIndex(inner_index)
        # setCurrentIndex ممکن است چون ایندکس از قبل همان بود currentChanged
        # را صدا نزند — پس صراحتاً هم رفرش می‌کنیم تا همیشه داده‌یِ تازه ببینیم.
        self._on_outer_tab_changed(outer_index)

    def _on_search_activated(self, index: int) -> None:
        target = self.settings_search.itemData(index)
        if target is not None:
            self._jump_to(target)

    def _on_search_return(self) -> None:
        text = self.settings_search.currentText().strip()
        if not text:
            return
        match_index = self.settings_search.findText(text, Qt.MatchContains)
        if match_index < 0:
            return
        self.settings_search.setCurrentIndex(match_index)
        self._jump_to(self.settings_search.itemData(match_index))

    def _build_coding_tab(self) -> QWidget:
        # طبقِ درخواستِ صریح: زیرفرم‌هایِ این بخش (کدینگِ حساب‌ها + تعدادِ
        # رقمِ سطوحِ تفصیلی) در زیرتب‌هایِ جداگانه باز شوند، نه رویِ هم
        # در یک صفحه‌ی اسکرول‌شونده.
        return self._sub_tabs(
            [
                ("کدینگِ حساب‌ها", AccountingCodingSettingsScreen()),
                ("تعدادِ رقمِ سطوحِ تفصیلی", DetailLevelDigitSettingsScreen()),
                ("تنظیماتِ صورت‌هایِ مالی", FinancialStatementMappingScreen()),
            ]
        )

    def _build_treasury_tab(self) -> QWidget:
        return self._sub_tabs(
            [
                ("انواعِ سندِ دریافت/پرداخت", TreasuryCounterpartySettingsScreen()),
                ("بانک‌ها", TreasuryBanksScreen()),
            ]
        )

    def _sub_tabs(self, pages: list[tuple[str, QWidget]]):
        # طبقِ گزارشِ صریح («فرم‌هایِ تنظیماتِ سیستم اصلاً اسکرول ندارند»):
        # وقتی این زیرپنجره کوچک می‌شود، محتوایِ زیرتب‌ها (که هرکدام یک
        # صفحه‌یِ کاملِ مستقل‌اند، با حداقل‌ارتفاعِ خودشان) به‌سادگی از
        # دیدرس خارج می‌شد و هیچ راهی برایِ رسیدن به فیلدها/دکمه‌هایِ
        # پایینی نبود — همان الگویِ QScrollArea که در dimension_group_config.py
        # برایِ همین مشکل استفاده شده، این‌جا هم به‌کار می‌رود.
        inner = QTabWidget()
        inner.setDocumentMode(True)
        widgets: list[QWidget] = []
        for label, widget in pages:
            self._sub_screens.append(widget)
            widgets.append(widget)
            # باگِ واقعیِ گزارش‌شده («پایینِ همه‌یِ فرم‌ها زیرِ تسک‌بار
            # می‌ماند»): صفحه‌هایی که خودشان اسکرول+نوارِ ثابتِ دکمه دارند
            # (manages_own_scroll) نباید دوباره در این QScrollAreaِ بیرونی
            # بپیچند — وگرنه دقیقاً همان نوارِ دکمه‌یِ «ثابت»شان هم دوباره
            # قابلِ‌اسکرول‌شدن و گم‌شدن می‌شود.
            if getattr(widget, "manages_own_scroll", False):
                inner.addTab(widget, label)
                continue
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.NoFrame)
            scroll.setWidget(widget)
            inner.addTab(scroll, label)

        def refresh_current(index: int | None = None) -> None:
            idx = inner.currentIndex() if index is None else index
            if 0 <= idx < len(widgets) and hasattr(widgets[idx], "refresh"):
                widgets[idx].refresh()

        inner.currentChanged.connect(refresh_current)
        return inner, refresh_current

    def _build_general_tab(self) -> QWidget:
        return self._sub_tabs(
            [
                ("شرکت‌ها", CompaniesScreen()),
                ("زبان‌ها", LanguagesScreen()),
                ("ارزها", CurrenciesScreen()),
                ("سال‌های مالی", FiscalYearsScreen()),
            ]
        )

    def _build_users_tab(self) -> QWidget:
        return self._sub_tabs(
            [
                ("کاربران", UsersScreen()),
                ("نقش‌ها و دسترسی‌ها", RolesScreen()),
                ("طراحیِ گردشِ کار", WorkflowDesignerScreen()),
            ]
        )

    def _build_accounting_data_tab(self) -> QWidget:
        return self._sub_tabs(
            [
                ("عنوانِ فیلدها", FieldLabelsScreen()),
                ("ترجمه‌ها", TranslationsScreen()),
            ]
        )

    def _build_security_tab(self):
        screen = AuditLogScreen()
        self._sub_screens.append(screen)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(screen)
        refresher = screen.refresh if hasattr(screen, "refresh") else (lambda: None)
        return scroll, refresher

    def _build_inventory_tab(self) -> QWidget:
        return self._sub_tabs(
            [
                ("واحدهایِ اندازه‌گیری", _UomTab()),
                ("برند و تولیدکننده", _BrandManufacturerTab()),
                ("دسته‌بندیِ کالا", _CategoriesTab()),
                ("قیمت‌گذاری", _CostingSettingsTab()),
                ("نگاشتِ حساب‌ها", _AccountMappingsTab()),
                ("دلیل‌هایِ اصلاح/برگشت", _ReasonCodesTab()),
                ("قابلیت‌هایِ فعال", _InventoryFeatureToggleTab()),
            ]
        )

    def _build_payroll_tab(self) -> QWidget:
        return self._sub_tabs(
            [
                ("تنظیماتِ کلی", _GeneralSettingsTab()),
                ("حداقلِ دستمزد", _MinimumWageTab()),
                ("قوانینِ حقوق و دستمزد", _PoliciesTab()),
                ("آیتم‌هایِ حقوقی", _PayItemsTab()),
                ("بیمه", _InsuranceTab()),
                ("مالیات", _TaxTab()),
                ("قوانینِ اضافه‌کاری", _OvertimeRulesTab()),
                ("الگوهایِ ایمپورتِ حضوروغیاب", _AttendanceTemplatesTab()),
            ]
        )

    def _build_commercial_tab(self) -> QWidget:
        return self._sub_tabs(
            [
                ("نگاشتِ حساب‌ها", _CommercialAccountMappingsTab()),
                ("قابلیت‌هایِ فعال", _FeatureToggleTab()),
                ("نمایهٔ صنعتی", _IndustryProfileTab()),
                ("شماره‌گذاریِ اسناد", _NumberingSequencesTab()),
                ("کانال‌ها", _CommercialChannelsTab()),
                ("هشدارِ موعدِ تسویه", _SettlementAlarmTab()),
            ]
        )

    def _build_reports_tab(self):
        screen = _ReportTemplatesTab()
        self._sub_screens.append(screen)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(screen)
        return scroll, screen.refresh

    def refresh(self) -> None:
        # فقط زیرصفحه‌یِ *فعلاً قابلِ‌مشاهده* رفرش می‌شود، نه هر ~۴۰ زیرصفحه —
        # ر.ک. توضیحِ رفعِ باگِ کندیِ ۱۰-۱۵ ثانیه‌ای در docstringِ بالایِ کلاس.
        self._on_outer_tab_changed(self.tabs.currentIndex())

    def select_tab(self, index: int) -> None:
        """برایِ دکمه‌ی چرخ‌دنده‌یِ ریبون — پرش مستقیم به تبِ تنظیماتِ همان
        بخش (مثلاً «کدینگِ حسابداری» برایِ بخشِ «مالی و حسابداری»)."""
        self.tabs.setCurrentIndex(index)
        # setCurrentIndex اگر ایندکس از قبل همان بود، currentChanged را صدا
        # نمی‌زند — پس صراحتاً هم رفرش می‌کنیم تا کلیکِ دوباره‌ی همان
        # چرخ‌دنده همیشه داده‌یِ تازه نشان بدهد.
        self._on_outer_tab_changed(index)
