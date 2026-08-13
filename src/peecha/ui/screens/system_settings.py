"""فرمِ یکپارچه‌ی «تنظیماتِ سیستم» — همه‌ی فرم‌هایی که قبلاً آیتم‌هایِ
جداگانه‌ی زیرمجموعه‌ی «مدیریتِ سیستم» در نوارِ کناری بودند، این‌جا به‌صورتِ
تب‌هایِ سازمان‌یافته (و در هر تب، زیرتب‌هایِ مرتبط) کنار هم قرار گرفته‌اند."""

from __future__ import annotations

from PySide6.QtWidgets import QFrame, QLabel, QScrollArea, QTabWidget, QVBoxLayout, QWidget

from peecha.ui.screens.accounting_coding import AccountingCodingSettingsScreen, DetailLevelDigitSettingsScreen
from peecha.ui.screens.audit_log import AuditLogScreen
from peecha.ui.screens.commercial_settings import (
    _AccountMappingsTab as _CommercialAccountMappingsTab,
    _ChannelsTab as _CommercialChannelsTab,
    _FeatureToggleTab,
    _IndustryProfileTab,
    _NumberingSequencesTab,
)
from peecha.ui.screens.companies import CompaniesScreen
from peecha.ui.screens.currencies import CurrenciesScreen
from peecha.ui.screens.field_labels import FieldLabelsScreen
from peecha.ui.screens.financial_statement_mapping import FinancialStatementMappingScreen
from peecha.ui.screens.fiscal_years import FiscalYearsScreen
from peecha.ui.screens.inventory_settings import (
    _AccountMappingsTab,
    _BrandManufacturerTab,
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
from peecha.ui.screens.roles import RolesScreen
from peecha.ui.screens.translations import TranslationsScreen
from peecha.ui.screens.treasury_banks import TreasuryBanksScreen
from peecha.ui.screens.treasury_counterparty_settings import TreasuryCounterpartySettingsScreen
from peecha.ui.screens.users import UsersScreen
from peecha.ui.screens.workflow_designer import WorkflowDesignerScreen


class SystemSettingsScreen(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._sub_screens: list[QWidget] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(12)

        title = QLabel("تنظیمات سیستم")
        title.setObjectName("pageTitle")
        outer.addWidget(title)

        self.tabs = QTabWidget()
        # طبقِ درخواستِ صریح: کدینگِ حسابداری باید اولین کاری باشد که در
        # تنظیماتِ حسابداری انجام می‌شود — به همین دلیل اولین تب است.
        self.tabs.addTab(self._build_coding_tab(), "کدینگِ حسابداری")
        self.tabs.addTab(self._build_treasury_tab(), "خزانه‌داری")
        self.tabs.addTab(self._build_general_tab(), "عمومی")
        self.tabs.addTab(self._build_users_tab(), "کاربران و دسترسی‌ها")
        self.tabs.addTab(self._build_accounting_data_tab(), "داده‌های حسابداری")
        self.tabs.addTab(self._build_security_tab(), "امنیت")
        # طبقِ درخواستِ صریح: تنظیماتِ حقوق‌ودستمزد از یک صفحه‌یِ مستقل به
        # این‌جا منتقل شد — دسترسی هم از این تب و هم از آیکونِ چرخ‌دنده‌یِ
        # کنارِ گروهِ «منابعِ انسانی» (shell_window.py).
        self.tabs.addTab(self._build_payroll_tab(), "حقوق و دستمزد")
        # طبقِ همان الگوی حقوق‌ودستمزد: تنظیماتِ ماژولِ انبار هم این‌جا و
        # هم از آیکونِ چرخ‌دنده‌یِ کنارِ گروهِ «انبار و موجودی» در دسترس است.
        self.tabs.addTab(self._build_inventory_tab(), "انبار و موجودی")
        # طبقِ همان الگو: تنظیماتِ مدیریتِ بازرگانی هم این‌جا و هم از
        # آیکونِ چرخ‌دنده‌یِ کنارِ گروه‌هایِ «فروش»/«خرید» در دسترس است.
        self.tabs.addTab(self._build_commercial_tab(), "مدیریتِ بازرگانی")
        outer.addWidget(self.tabs, stretch=1)

    def _build_coding_tab(self) -> QWidget:
        # طبقِ درخواستِ صریح: زیرفرم‌هایِ این بخش (کدینگِ حساب‌ها + تعدادِ
        # رقمِ سطوحِ تفصیلی) در زیرتب‌هایِ جداگانه باز شوند، نه رویِ هم
        # در یک صفحه‌ی اسکرول‌شونده.
        return self._sub_tabs(
            [
                ("کدینگِ حساب‌ها", AccountingCodingSettingsScreen()),
                ("تعدادِ رقمِ سطوحِ تفصیلی", DetailLevelDigitSettingsScreen()),
                ("نگاشتِ صورت‌هایِ مالی", FinancialStatementMappingScreen()),
            ]
        )

    def _build_treasury_tab(self) -> QWidget:
        return self._sub_tabs(
            [
                ("انواعِ سندِ دریافت/پرداخت", TreasuryCounterpartySettingsScreen()),
                ("بانک‌ها", TreasuryBanksScreen()),
            ]
        )

    def _sub_tabs(self, pages: list[tuple[str, QWidget]]) -> QTabWidget:
        # طبقِ گزارشِ صریح («فرم‌هایِ تنظیماتِ سیستم اصلاً اسکرول ندارند»):
        # وقتی این زیرپنجره کوچک می‌شود، محتوایِ زیرتب‌ها (که هرکدام یک
        # صفحه‌یِ کاملِ مستقل‌اند، با حداقل‌ارتفاعِ خودشان) به‌سادگی از
        # دیدرس خارج می‌شد و هیچ راهی برایِ رسیدن به فیلدها/دکمه‌هایِ
        # پایینی نبود — همان الگویِ QScrollArea که در dimension_group_config.py
        # برایِ همین مشکل استفاده شده، این‌جا هم به‌کار می‌رود.
        inner = QTabWidget()
        inner.setDocumentMode(True)
        for label, widget in pages:
            self._sub_screens.append(widget)
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
        return inner

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

    def _build_security_tab(self) -> QWidget:
        screen = AuditLogScreen()
        self._sub_screens.append(screen)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(screen)
        return scroll

    def _build_inventory_tab(self) -> QWidget:
        return self._sub_tabs(
            [
                ("واحدهایِ اندازه‌گیری", _UomTab()),
                ("برند و تولیدکننده", _BrandManufacturerTab()),
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
            ]
        )

    def refresh(self) -> None:
        for widget in self._sub_screens:
            if hasattr(widget, "refresh"):
                widget.refresh()

    def select_tab(self, index: int) -> None:
        """برایِ دکمه‌ی چرخ‌دنده‌یِ ریبون — پرش مستقیم به تبِ تنظیماتِ همان
        بخش (مثلاً «کدینگِ حسابداری» برایِ بخشِ «مالی و حسابداری»)."""
        self.tabs.setCurrentIndex(index)
