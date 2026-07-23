"""فرمِ یکپارچه‌ی «تنظیماتِ سیستم» — همه‌ی فرم‌هایی که قبلاً آیتم‌هایِ
جداگانه‌ی زیرمجموعه‌ی «مدیریتِ سیستم» در نوارِ کناری بودند، این‌جا به‌صورتِ
تب‌هایِ سازمان‌یافته (و در هر تب، زیرتب‌هایِ مرتبط) کنار هم قرار گرفته‌اند."""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QTabWidget, QVBoxLayout, QWidget

from peecha.ui.screens.audit_log import AuditLogScreen
from peecha.ui.screens.companies import CompaniesScreen
from peecha.ui.screens.currencies import CurrenciesScreen
from peecha.ui.screens.field_labels import FieldLabelsScreen
from peecha.ui.screens.fiscal_years import FiscalYearsScreen
from peecha.ui.screens.languages import LanguagesScreen
from peecha.ui.screens.placeholder import PlaceholderScreen
from peecha.ui.screens.roles import RolesScreen
from peecha.ui.screens.users import UsersScreen


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

        tabs = QTabWidget()
        tabs.addTab(self._build_general_tab(), "عمومی")
        tabs.addTab(self._build_users_tab(), "کاربران و دسترسی‌ها")
        tabs.addTab(self._build_accounting_data_tab(), "داده‌های حسابداری")
        tabs.addTab(self._build_security_tab(), "امنیت")
        outer.addWidget(tabs, stretch=1)

    def _sub_tabs(self, pages: list[tuple[str, QWidget]]) -> QTabWidget:
        inner = QTabWidget()
        inner.setDocumentMode(True)
        for label, widget in pages:
            self._sub_screens.append(widget)
            inner.addTab(widget, label)
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
            ]
        )

    def _build_accounting_data_tab(self) -> QWidget:
        # نکته: «ترجمه‌ها»یِ Kivy مخصوصِ کاتالوگِ رشته‌هایِ ثابتِ KV بود —
        # مخصوصِ همان معماریِ بازنشسته‌شده، بدونِ معادلِ Qt، عمداً Placeholder.
        translations = PlaceholderScreen()
        translations.set_module_name("ترجمه‌ها")
        return self._sub_tabs(
            [
                ("عنوانِ فیلدها", FieldLabelsScreen()),
                ("ترجمه‌ها", translations),
            ]
        )

    def _build_security_tab(self) -> QWidget:
        screen = AuditLogScreen()
        self._sub_screens.append(screen)
        return screen

    def refresh(self) -> None:
        for widget in self._sub_screens:
            if hasattr(widget, "refresh"):
                widget.refresh()
