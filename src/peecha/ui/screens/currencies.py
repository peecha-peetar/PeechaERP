"""مدیریتِ ارزها — معادلِ Qt برایِ currencies.py/.kv در Kivy.

طبقِ درخواستِ صریح («در جدولِ ارزها بتوان نرخِ تبدیل را هم دستی وارد کرد
و هم اتوماتیک از صرافی/بانکِ مرکزی گرفت»)، علاوه‌بر فهرستِ سراسریِ ارزها
(core.currencies)، برایِ ارزهایِ غیرِپایه یک بخشِ «فعال‌سازی برایِ این
شرکت + تاریخچه‌یِ نرخِ روزانه» هم اضافه شده — چون نرخِ تبدیل، مفهومی
مخصوصِ هر شرکت است (نه سراسری)."""

from __future__ import annotations

import datetime
import decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from peecha import numerals, session
from peecha.services import currencies as currencies_service
from peecha.ui.widgets import FieldHelpMixin, JalaliDateEdit

_COLUMNS = ["فعال", "رقمِ اعشار", "نماد", "کدِ ارز"]
_RATE_COLUMNS = ["تاریخ", "نرخ به ارزِ پایه"]


class CurrenciesScreen(FieldHelpMixin, QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._rows: list[currencies_service.CurrencyRow] = []
        self._editing_id: int | None = None

        self._selected_currency: currencies_service.CurrencyRow | None = None

        outer = QHBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(16)
        outer.addWidget(self._build_list_panel(), stretch=3)
        outer.addWidget(self._build_form_panel(), stretch=1)
        outer.addWidget(self._build_rate_panel(), stretch=2)

        self.set_field_help([
            (
                self.iso_code_field,
                "کدِ استانداردِ سه‌حرفیِ ارز — مثلاً IRR برایِ ریال یا USD برایِ دلار. "
                "همین کد در فهرستِ «ارزِ پایه»یِ هر شرکت و همه‌جایِ برنامه استفاده می‌شود.",
            ),
            (self.symbol_field, "نمادِ نمایشیِ ارز، مثلاً ﷼ یا $. فقط ظاهری است و در محاسبات اثر ندارد."),
            (
                self.decimal_places_field,
                "چند رقمِ اعشار برایِ مبالغِ این ارز نشان داده شود. برایِ ریال معمولاً صفر است. "
                "برایِ دلار معمولاً ۲. تغییرِ این عدد فقط نمایش را عوض می‌کند، نه مبالغِ ذخیره‌شده را.",
            ),
            (
                self.is_active_checkbox,
                "ارزهایِ غیرِفعال دیگر در فهرستِ «ارزِ پایه» هنگامِ ساختنِ شرکتِ تازه نشان داده نمی‌شوند. "
                "شرکت‌هایی که از قبل با این ارز کار می‌کنند مشکلی پیدا نمی‌کنند.",
            ),
        ])

    def _build_list_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("card")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        title = QLabel("ارزها")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.cellClicked.connect(self._on_row_clicked)
        layout.addWidget(self.table)
        return panel

    def _build_form_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("card")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        self.form_title = QLabel("ارزِ جدید")
        self.form_title.setObjectName("pageTitle")
        layout.addWidget(self.form_title)

        layout.addWidget(QLabel("کدِ ارز (مثلاً IRR)"))
        self.iso_code_field = QLineEdit()
        layout.addWidget(self.iso_code_field)

        layout.addWidget(QLabel("نماد"))
        self.symbol_field = QLineEdit()
        layout.addWidget(self.symbol_field)

        layout.addWidget(QLabel("رقمِ اعشار"))
        self.decimal_places_field = QSpinBox()
        self.decimal_places_field.setRange(0, 6)
        layout.addWidget(self.decimal_places_field)

        self.is_active_checkbox = QCheckBox("فعال")
        self.is_active_checkbox.setChecked(True)
        layout.addWidget(self.is_active_checkbox)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusError")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        buttons = QHBoxLayout()
        save_button = QPushButton("ذخیره")
        save_button.setObjectName("primaryButton")
        save_button.clicked.connect(self._save)
        buttons.addWidget(save_button)

        cancel_button = QPushButton("انصراف")
        cancel_button.setObjectName("flatButton")
        cancel_button.clicked.connect(self._reset_form)
        buttons.addWidget(cancel_button)

        self.delete_button = QPushButton("حذف")
        self.delete_button.setObjectName("dangerButton")
        self.delete_button.clicked.connect(self._delete)
        self.delete_button.setVisible(False)
        buttons.addWidget(self.delete_button)

        layout.addLayout(buttons)
        layout.addStretch(1)
        return panel

    def _build_rate_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("card")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        self.rate_panel_title = QLabel("نرخِ ارز")
        self.rate_panel_title.setObjectName("pageTitle")
        layout.addWidget(self.rate_panel_title)

        self.rate_panel_hint = QLabel("یک ارزِ غیرِپایه از فهرستِ سمتِ راست انتخاب کنید.")
        self.rate_panel_hint.setObjectName("sectionHint")
        self.rate_panel_hint.setWordWrap(True)
        layout.addWidget(self.rate_panel_hint)

        self.rate_panel_content = QWidget()
        content_layout = QVBoxLayout(self.rate_panel_content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(8)

        self.enable_for_company_checkbox = QCheckBox("فعال برایِ شرکتِ جاری")
        self.enable_for_company_checkbox.toggled.connect(self._on_enable_for_company_toggled)
        content_layout.addWidget(self.enable_for_company_checkbox)

        self.rate_table = QTableWidget(0, len(_RATE_COLUMNS))
        self.rate_table.setHorizontalHeaderLabels(_RATE_COLUMNS)
        self.rate_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.rate_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.rate_table.verticalHeader().setVisible(False)
        self.rate_table.horizontalHeader().setStretchLastSection(True)
        self.rate_table.setMaximumHeight(160)
        content_layout.addWidget(self.rate_table)

        divider = QFrame()
        divider.setFrameShape(QFrame.HLine)
        content_layout.addWidget(divider)

        new_rate_row = QHBoxLayout()
        new_rate_row.addWidget(QLabel("تاریخ:"))
        self.rate_date_field = JalaliDateEdit()
        self.rate_date_field.setMaximumWidth(120)
        new_rate_row.addWidget(self.rate_date_field)
        new_rate_row.addWidget(QLabel("نرخ:"))
        self.rate_value_field = QLineEdit()
        new_rate_row.addWidget(self.rate_value_field, stretch=1)
        content_layout.addLayout(new_rate_row)

        fetch_row = QHBoxLayout()
        fetch_button = QPushButton("🌐 دریافتِ خودکار از اینترنت")
        fetch_button.setObjectName("flatButton")
        fetch_button.clicked.connect(self._on_fetch_live_rate)
        fetch_row.addWidget(fetch_button)
        fetch_row.addStretch(1)
        content_layout.addLayout(fetch_row)

        fetch_hint = QLabel(
            "نرخِ خودکار از یک سرویسِ عمومیِ نرخِ ارز گرفته می‌شود؛ برایِ ریال ممکن است در دسترس نباشد یا "
            "با نرخِ بازارِ آزاد فرق داشته باشد — قبل از ثبت آن را بررسی کنید."
        )
        fetch_hint.setObjectName("sectionHint")
        fetch_hint.setWordWrap(True)
        content_layout.addWidget(fetch_hint)

        self.rate_status_label = QLabel("")
        self.rate_status_label.setObjectName("statusError")
        self.rate_status_label.setWordWrap(True)
        content_layout.addWidget(self.rate_status_label)

        save_rate_button = QPushButton("ثبتِ نرخ")
        save_rate_button.setObjectName("primaryButton")
        save_rate_button.clicked.connect(self._on_save_rate)
        content_layout.addWidget(save_rate_button)

        content_layout.addStretch(1)
        layout.addWidget(self.rate_panel_content)
        self.rate_panel_content.setVisible(False)
        return panel

    def refresh(self) -> None:
        self._reset_form()
        self._rows = currencies_service.list_all_currencies()
        self.table.setRowCount(len(self._rows))
        for row_index, currency in enumerate(self._rows):
            values = [
                "بله" if currency.is_active else "خیر",
                str(currency.decimal_places),
                currency.symbol or "—",
                currency.iso_code,
            ]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, currency.currency_id)
                self.table.setItem(row_index, col_index, item)

    def _on_row_clicked(self, row: int, _column: int) -> None:
        currency_id = self.table.item(row, 0).data(Qt.UserRole)
        currency = next((r for r in self._rows if r.currency_id == currency_id), None)
        if currency is not None:
            self._load_into_form(currency)

    def _load_into_form(self, currency: currencies_service.CurrencyRow) -> None:
        self._editing_id = currency.currency_id
        self.form_title.setText(f"ویرایشِ ارز — {currency.iso_code}")
        self.status_label.setText("")
        self.iso_code_field.setText(currency.iso_code)
        self.symbol_field.setText(currency.symbol or "")
        self.decimal_places_field.setValue(currency.decimal_places)
        self.is_active_checkbox.setChecked(currency.is_active)
        self.delete_button.setVisible(True)
        self._selected_currency = currency
        self._refresh_rate_panel()

    def _reset_form(self) -> None:
        self._editing_id = None
        self.form_title.setText("ارزِ جدید")
        self.status_label.setText("")
        self.iso_code_field.clear()
        self.symbol_field.clear()
        self.decimal_places_field.setValue(0)
        self.is_active_checkbox.setChecked(True)
        self.delete_button.setVisible(False)
        self.table.clearSelection()
        self._selected_currency = None
        self._refresh_rate_panel()

    def _company_id(self) -> int | None:
        return session.current_company.company_id if session.current_company else None

    def _refresh_rate_panel(self) -> None:
        company_id = self._company_id()
        currency = self._selected_currency
        is_base = (
            currency is not None
            and session.current_company is not None
            and currency.currency_id == session.current_company.base_currency_id
        )
        if currency is None or company_id is None:
            self.rate_panel_content.setVisible(False)
            self.rate_panel_hint.setVisible(True)
            self.rate_panel_hint.setText("یک ارزِ غیرِپایه از فهرستِ سمتِ راست انتخاب کنید.")
            return
        if is_base:
            self.rate_panel_content.setVisible(False)
            self.rate_panel_hint.setVisible(True)
            self.rate_panel_hint.setText(f"«{currency.iso_code}» ارزِ پایه‌یِ شرکتِ جاری است — نرخ همیشه ۱ است.")
            return

        self.rate_panel_hint.setVisible(False)
        self.rate_panel_content.setVisible(True)
        self.rate_panel_title.setText(f"نرخِ ارز — {currency.iso_code}")
        self.rate_status_label.setText("")

        company_currencies = currencies_service.list_company_currencies(company_id)
        row = next((r for r in company_currencies if r.currency_id == currency.currency_id), None)
        self.enable_for_company_checkbox.blockSignals(True)
        self.enable_for_company_checkbox.setChecked(bool(row and row.is_enabled))
        self.enable_for_company_checkbox.blockSignals(False)

        self._reload_rate_table()
        self.rate_date_field.setDate(datetime.date.today())
        self.rate_value_field.clear()

    def _reload_rate_table(self) -> None:
        company_id = self._company_id()
        if company_id is None or self._selected_currency is None:
            return
        rates = currencies_service.list_exchange_rates(company_id, self._selected_currency.currency_id)
        self.rate_table.setRowCount(len(rates))
        for row_index, rate in enumerate(rates):
            date_item = QTableWidgetItem(numerals.format_jalali_date(rate.rate_date))
            rate_item = QTableWidgetItem(numerals.format_amount(rate.rate_to_base))
            self.rate_table.setItem(row_index, 0, date_item)
            self.rate_table.setItem(row_index, 1, rate_item)

    def _on_enable_for_company_toggled(self, checked: bool) -> None:
        company_id = self._company_id()
        if company_id is None or self._selected_currency is None:
            return
        currencies_service.set_company_currency(company_id, self._selected_currency.currency_id, checked)

    def _on_fetch_live_rate(self) -> None:
        company = session.current_company
        if company is None or self._selected_currency is None:
            return
        base_currency = next(
            (c for c in currencies_service.list_all_currencies() if c.currency_id == company.base_currency_id), None
        )
        if base_currency is None:
            return
        try:
            rate = currencies_service.fetch_live_rate(base_currency.iso_code, self._selected_currency.iso_code)
        except ValueError as exc:
            self.rate_status_label.setText(str(exc))
            return
        self.rate_status_label.setText("")
        self.rate_value_field.setText(numerals.format_amount(rate))

    def _on_save_rate(self) -> None:
        company_id = self._company_id()
        if company_id is None or self._selected_currency is None:
            return
        try:
            rate_value = numerals.parse_decimal(self.rate_value_field.text())
            currencies_service.set_exchange_rate(
                company_id, self._selected_currency.currency_id, self.rate_date_field.date(), rate_value
            )
        except ValueError as exc:
            self.rate_status_label.setText(str(exc))
            return
        self.rate_status_label.setText("")
        self.rate_value_field.clear()
        self._reload_rate_table()

    def _save(self) -> None:
        iso_code = self.iso_code_field.text().strip()
        if not iso_code:
            self.status_label.setText("کدِ ارز را وارد کنید.")
            return
        symbol = self.symbol_field.text().strip() or None
        decimal_places = self.decimal_places_field.value()

        try:
            if self._editing_id is not None:
                currencies_service.update_currency(
                    self._editing_id, iso_code, symbol, decimal_places, self.is_active_checkbox.isChecked()
                )
            else:
                currencies_service.create_currency(iso_code, symbol, decimal_places)
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return

        self.refresh()

    def _delete(self) -> None:
        if self._editing_id is None:
            return
        confirm = QMessageBox.question(
            self, "حذفِ ارز", "این ارز حذف شود؟", QMessageBox.Yes | QMessageBox.No
        )
        if confirm != QMessageBox.Yes:
            return
        try:
            currencies_service.delete_currency(self._editing_id)
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self.refresh()
