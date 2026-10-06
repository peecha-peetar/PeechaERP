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
    _DistributionSettlementTypesTab,
    _FeatureToggleTab,
    _IndustryProfileTab,
    _MobileSettlementMethodsTab,
    _NumberingSequencesTab,
    _PricingPolicyTab,
    _SettlementAlarmTab,
    _SmsGatewaySettingsTab,
    _VoipSettingsTab,
)
from peecha.ui.screens.commercial_ecommerce import CommercialEcommerceScreen
from peecha.ui.screens.commercial_pos_sessions import CommercialPosSessionsScreen
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
    _BarcodeManagerTab,
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
from peecha.ui.widgets import FieldHelpMixin


# R272: دسترسیِ هر تب/زیرتب جداگانه از جدولِ نقش‌ها (VIEW). مدیرِ کل یا دارندهٔ دسترسیِ کلِ
# «تنظیمات سیستم» (system_settings) همه را می‌بیند؛ بقیه فقط تب‌هایی که فرمشان را دارند.
_TAB_FORMS: dict[str, tuple[str, ...]] = {
    "کدینگِ حسابداری": ("accounting_coding",),
    "خزانه‌داری": ("treasury_settings",),
    "عمومی": ("companies",),
    "کاربران و دسترسی‌ها": ("users",),
    "داده‌های حسابداری": ("field_labels",),
    "امنیت": ("audit_log",),
    "حقوق و دستمزد": ("payroll_settings",),
    "انبار و موجودی": ("inventory_settings",),
    "مدیریتِ بازرگانی": ("commercial_settings",),
    "چاپ و گزارش‌ها": ("report_settings",),
    "دارایی‌هایِ ثابت": ("fa_setup",),
    "تولید": ("prd_settings",),
}
_SUBTAB_FORMS: dict[tuple[str, str], tuple[str, ...]] = {
    ("کدینگِ حسابداری", "تعدادِ رقمِ سطوحِ تفصیلی"): ("detail_level_digits",),
    ("کدینگِ حسابداری", "تنظیماتِ صورت‌هایِ مالی"): ("financial_statement_mapping",),
    ("عمومی", "زبان‌ها"): ("languages",),
    ("عمومی", "ارزها"): ("currencies",),
    ("عمومی", "سال‌های مالی"): ("fiscal_years",),
    ("کاربران و دسترسی‌ها", "نقش‌ها و دسترسی‌ها"): ("roles",),
    ("کاربران و دسترسی‌ها", "طراحیِ گردشِ کار"): ("workflow_designer",),
    ("داده‌های حسابداری", "ترجمه‌ها"): ("translations",),
    ("انبار و موجودی", "قیمت‌گذاری"): ("inventory_settings", "costing_settings"),
}


def _user_can_view(form_codes: tuple[str, ...], cache: dict[str, bool]) -> bool:
    from peecha import session as app_session
    from peecha.services import roles as roles_service

    user, company = app_session.current_user, app_session.current_company
    if user is None or company is None:
        return True  # بیرون از ورود (ابزار/آزمون): بدونِ فیلتر
    if getattr(user, "is_super_admin", False):
        return True
    for code in ("system_settings", *form_codes):
        if code not in cache:
            cache[code] = roles_service.user_has_permission(user.user_id, company.company_id, code, "VIEW")
        if cache[code]:
            return True
    return False


class SystemSettingsScreen(FieldHelpMixin, QWidget):
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
        self._add_outer_tab("چاپ و گزارش‌ها", self._build_reports_tab())
        # R272: تنظیماتِ دارایی و تولید هم مثلِ بقیهٔ ماژول‌ها این‌جاست (چرخ‌دندهٔ کنارِ منو)؛
        # تنظیماتِ بهایِ تمام‌شده همان «انبار و موجودی › قیمت‌گذاری» است.
        self._add_outer_tab("دارایی‌هایِ ثابت", self._build_fixed_assets_tab())
        self._add_outer_tab("تولید", self._build_production_tab())
        self.tabs.currentChanged.connect(self._on_outer_tab_changed)
        outer.addWidget(self.tabs, stretch=1)
        self.no_access_label = QLabel("به هیچ بخشی از تنظیمات دسترسی ندارید؛ از مدیرِ سیستم بخواهید در «نقش‌ها و دسترسی‌ها» فعال کند.")
        self.no_access_label.setObjectName("sectionHint")
        self.no_access_label.setWordWrap(True)
        self.no_access_label.hide()
        outer.addWidget(self.no_access_label)

        search_items = [self.settings_search.itemText(i) for i in range(self.settings_search.count())]
        completer = QCompleter(search_items)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains)
        completer.activated.connect(self._on_search_return)
        self.settings_search.setCompleter(completer)
        self.settings_search.setCurrentIndex(-1)
        self.settings_search.activated.connect(self._on_search_activated)
        self.settings_search.lineEdit().returnPressed.connect(self._on_search_return)

        self.set_field_help([
            (self.settings_search, "بخشی از تنظیمات را تایپ کنید (مثلاً «بانک‌ها») تا مستقیم به همان تب/زیرتب بروید."),
        ])

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
        if not self._target_visible(outer_index, inner_widget, inner_index):
            return
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
                # طبقِ درخواستِ صریح («تمامیِ تنظیماتِ POS از منوها برداشته
                # شود و در تنظیماتِ اصلی، زیرِ خزانه‌داری بیاید»).
                ("ترمینال‌ها، شیفت‌ها و تنظیماتِ تک‌فروشی", CommercialPosSessionsScreen()),
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
                ("مدیریتِ بارکد", _BarcodeManagerTab()),
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
                ("انواعِ تسویهٔ پخش", _DistributionSettlementTypesTab()),
                ("روش‌هایِ تسویهٔ موبایل", _MobileSettlementMethodsTab()),
                ("هشدارِ موعدِ تسویه", _SettlementAlarmTab()),
                ("حاشیهٔ سود و پیشنهادِ قیمت", _PricingPolicyTab()),
                ("سانترال / وویپ", _VoipSettingsTab()),
                ("درگاهِ پیامک", _SmsGatewaySettingsTab()),
                # طبقِ درخواستِ صریح («در منویِ فروشِ اینترنتی فقط
                # سفارش‌هایِ فروشِ مشتری بیاید، و تنظیمات به تبِ تنظیماتِ
                # فروشِ اینترنتی برود»): اتصالات/نگاشتِ کالا-مشتری/سینکِ
                # خودکار/مسیریابیِ سفارش -- همان صفحه‌ای که قبلاً خودش یک
                # آیتمِ مستقلِ ناوبری بود، حالا این‌جاست.
                ("تنظیماتِ فروشِ اینترنتی", CommercialEcommerceScreen()),
            ]
        )

    def _build_reports_tab(self):
        # R245: لوگو و سربرگِ گزارش‌ها + قالب‌هایِ گزارشِ حرفه‌ای
        from peecha.ui.screens.report_branding import ReportBrandingScreen

        self.report_branding = ReportBrandingScreen()
        return self._sub_tabs([("لوگو و سربرگ", self.report_branding), ("قالب‌هایِ حرفه‌ای (Jasper)", _ReportTemplatesTab())])

    def _build_fixed_assets_tab(self):
        from peecha.ui.screens.fixed_assets import SetupScreen

        return self._sub_tabs([("طبقه‌ها، حساب‌ها، محل‌ها و سیاست‌ها", SetupScreen())])

    def _build_production_tab(self):
        from peecha.ui.screens.production import PrdSettingsScreen

        return self._sub_tabs([("تنظیماتِ کلیِ تولید", PrdSettingsScreen())])

    def apply_permissions(self) -> None:
        cache: dict[str, bool] = {}
        any_visible = False
        for outer_index in range(self.tabs.count()):
            outer_label = self.tabs.tabText(outer_index)
            outer_forms = _TAB_FORMS.get(outer_label, ())
            inner = self.tabs.widget(outer_index)
            if isinstance(inner, QTabWidget):
                visible = False
                for i in range(inner.count()):
                    forms = _SUBTAB_FORMS.get((outer_label, inner.tabText(i)), outer_forms)
                    ok = _user_can_view(forms, cache)
                    inner.setTabVisible(i, ok)
                    visible = visible or ok
                if visible and not inner.isTabVisible(inner.currentIndex()):
                    inner.setCurrentIndex(next(i for i in range(inner.count()) if inner.isTabVisible(i)))
            else:
                visible = _user_can_view(outer_forms, cache)
            self.tabs.setTabVisible(outer_index, visible)
            any_visible = any_visible or visible
        if any_visible and not self.tabs.isTabVisible(self.tabs.currentIndex()):
            self.tabs.setCurrentIndex(next(i for i in range(self.tabs.count()) if self.tabs.isTabVisible(i)))
        self.tabs.setVisible(any_visible)
        self.no_access_label.setVisible(not any_visible)

    def _target_visible(self, outer_index: int, inner_widget, inner_index) -> bool:
        if not self.tabs.isTabVisible(outer_index):
            return False
        return inner_widget is None or inner_index is None or inner_widget.isTabVisible(inner_index)

    def refresh(self) -> None:
        self.apply_permissions()
        # فقط زیرصفحه‌یِ *فعلاً قابلِ‌مشاهده* رفرش می‌شود، نه هر ~۴۰ زیرصفحه —
        # ر.ک. توضیحِ رفعِ باگِ کندیِ ۱۰-۱۵ ثانیه‌ای در docstringِ بالایِ کلاس.
        self._on_outer_tab_changed(self.tabs.currentIndex())

    def select_tab(self, index: int, inner_label: str | None = None) -> None:
        """برایِ دکمه‌ی چرخ‌دنده‌یِ ریبون — پرش مستقیم به تبِ تنظیماتِ همان
        بخش (مثلاً «کدینگِ حسابداری» برایِ بخشِ «مالی و حسابداری»)."""
        self.apply_permissions()
        if not self.tabs.isTabVisible(index):
            return
        self.tabs.setCurrentIndex(index)
        inner = self.tabs.widget(index)
        if inner_label and isinstance(inner, QTabWidget):
            for i in range(inner.count()):
                if inner.tabText(i) == inner_label and inner.isTabVisible(i):
                    inner.setCurrentIndex(i)
        # setCurrentIndex اگر ایندکس از قبل همان بود، currentChanged را صدا
        # نمی‌زند — پس صراحتاً هم رفرش می‌کنیم تا کلیکِ دوباره‌ی همان
        # چرخ‌دنده همیشه داده‌یِ تازه نشان بدهد.
        self._on_outer_tab_changed(index)
