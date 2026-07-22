"""مدیریتِ شرکت‌ها — معادلِ Qt برایِ companies.py/.kv در Kivy."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from peecha.services import companies as companies_service
from peecha.services import languages as languages_service

_COLUMNS = ["فعال", "زبانِ پیش‌فرض", "ارزِ پایه", "نامِ نمایشی", "کد"]


class CompaniesScreen(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._rows: list[companies_service.CompanyRow] = []
        self._editing_id: int | None = None
        self._currency_options: list[companies_service.CurrencyOption] = []
        self._language_options: list[languages_service.LanguageRow] = []

        outer = QHBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(16)
        outer.addWidget(self._build_list_panel(), stretch=3)
        outer.addWidget(self._build_form_panel(), stretch=2)

    def _build_list_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("card")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        title = QLabel("شرکت‌ها")
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
        layout.setSpacing(8)

        self.form_title = QLabel("شرکتِ جدید")
        self.form_title.setObjectName("pageTitle")
        layout.addWidget(self.form_title)

        grid = QGridLayout()
        grid.setSpacing(8)
        row = 0

        grid.addWidget(QLabel("کد"), row, 0)
        self.code_field = QLineEdit()
        grid.addWidget(self.code_field, row, 1)
        row += 1

        grid.addWidget(QLabel("نامِ حقوقی"), row, 0)
        self.legal_name_field = QLineEdit()
        grid.addWidget(self.legal_name_field, row, 1)
        row += 1

        grid.addWidget(QLabel("نامِ نمایشی"), row, 0)
        self.display_name_field = QLineEdit()
        grid.addWidget(self.display_name_field, row, 1)
        row += 1

        grid.addWidget(QLabel("ارزِ پایه"), row, 0)
        self.currency_combo = QComboBox()
        grid.addWidget(self.currency_combo, row, 1)
        row += 1

        grid.addWidget(QLabel("زبانِ پیش‌فرض"), row, 0)
        self.language_combo = QComboBox()
        grid.addWidget(self.language_combo, row, 1)
        row += 1

        grid.addWidget(QLabel("ماهِ شروعِ سالِ مالی"), row, 0)
        self.fy_month_field = QSpinBox()
        self.fy_month_field.setRange(1, 12)
        self.fy_month_field.setValue(1)
        grid.addWidget(self.fy_month_field, row, 1)
        row += 1

        grid.addWidget(QLabel("روزِ شروعِ سالِ مالی"), row, 0)
        self.fy_day_field = QSpinBox()
        self.fy_day_field.setRange(1, 31)
        self.fy_day_field.setValue(1)
        grid.addWidget(self.fy_day_field, row, 1)
        row += 1

        grid.addWidget(QLabel("کدِ اقتصادی"), row, 0)
        self.economic_code_field = QLineEdit()
        grid.addWidget(self.economic_code_field, row, 1)
        row += 1

        grid.addWidget(QLabel("شماره‌ی ثبت"), row, 0)
        self.registration_no_field = QLineEdit()
        grid.addWidget(self.registration_no_field, row, 1)
        row += 1

        grid.addWidget(QLabel("شناسه‌ی ملی"), row, 0)
        self.national_id_field = QLineEdit()
        grid.addWidget(self.national_id_field, row, 1)
        row += 1

        self.is_active_checkbox = QCheckBox("فعال")
        self.is_active_checkbox.setChecked(True)
        grid.addWidget(self.is_active_checkbox, row, 1)
        row += 1

        layout.addLayout(grid)

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

        layout.addLayout(buttons)
        layout.addStretch(1)
        return panel

    def refresh(self) -> None:
        self._currency_options = companies_service.list_currencies()
        self._language_options = languages_service.list_languages()
        self._fill_combo(self.currency_combo, [(c.currency_id, c.iso_code) for c in self._currency_options])
        self._fill_combo(self.language_combo, [(l.language_id, l.native_name) for l in self._language_options])

        self._reset_form()
        self._rows = companies_service.list_companies()
        self.table.setRowCount(len(self._rows))
        for row_index, company in enumerate(self._rows):
            values = [
                "بله" if company.is_active else "خیر",
                company.default_language_name,
                company.base_currency_code,
                company.display_name,
                company.code,
            ]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, company.company_id)
                self.table.setItem(row_index, col_index, item)

    @staticmethod
    def _fill_combo(combo: QComboBox, options: list[tuple[int, str]]) -> None:
        combo.clear()
        for value, label in options:
            combo.addItem(label, value)

    def _on_row_clicked(self, row: int, _column: int) -> None:
        company_id = self.table.item(row, 0).data(Qt.UserRole)
        company = next((r for r in self._rows if r.company_id == company_id), None)
        if company is not None:
            self._load_into_form(company)

    def _load_into_form(self, company: companies_service.CompanyRow) -> None:
        self._editing_id = company.company_id
        self.form_title.setText(f"ویرایشِ شرکت — {company.display_name}")
        self.status_label.setText("")
        self.code_field.setText(company.code)
        self.code_field.setEnabled(False)
        self.legal_name_field.setText(company.legal_name)
        self.display_name_field.setText(company.display_name)
        self._select_combo(self.currency_combo, company.base_currency_id)
        self._select_combo(self.language_combo, company.default_language_id)
        self.fy_month_field.setValue(company.fiscal_year_start_month)
        self.fy_day_field.setValue(company.fiscal_year_start_day)
        self.economic_code_field.setText(company.economic_code or "")
        self.registration_no_field.setText(company.registration_no or "")
        self.national_id_field.setText(company.national_id or "")
        self.is_active_checkbox.setChecked(company.is_active)

    @staticmethod
    def _select_combo(combo: QComboBox, value: int) -> None:
        index = combo.findData(value)
        combo.setCurrentIndex(index if index >= 0 else 0)

    def _reset_form(self) -> None:
        self._editing_id = None
        self.form_title.setText("شرکتِ جدید")
        self.status_label.setText("")
        self.code_field.clear()
        self.code_field.setEnabled(True)
        self.legal_name_field.clear()
        self.display_name_field.clear()
        if self.currency_combo.count():
            self.currency_combo.setCurrentIndex(0)
        if self.language_combo.count():
            self.language_combo.setCurrentIndex(0)
        self.fy_month_field.setValue(1)
        self.fy_day_field.setValue(1)
        self.economic_code_field.clear()
        self.registration_no_field.clear()
        self.national_id_field.clear()
        self.is_active_checkbox.setChecked(True)
        self.table.clearSelection()

    def _save(self) -> None:
        legal_name = self.legal_name_field.text().strip()
        display_name = self.display_name_field.text().strip()
        if not legal_name or not display_name:
            self.status_label.setText("نامِ حقوقی و نامِ نمایشی را وارد کنید.")
            return

        base_currency_id = self.currency_combo.currentData()
        default_language_id = self.language_combo.currentData()

        try:
            if self._editing_id is not None:
                companies_service.update_company(
                    self._editing_id,
                    legal_name,
                    display_name,
                    base_currency_id,
                    default_language_id,
                    self.fy_month_field.value(),
                    self.fy_day_field.value(),
                    self.is_active_checkbox.isChecked(),
                    economic_code=self.economic_code_field.text().strip() or None,
                    registration_no=self.registration_no_field.text().strip() or None,
                    national_id=self.national_id_field.text().strip() or None,
                )
            else:
                code = self.code_field.text().strip()
                if not code:
                    self.status_label.setText("کد را وارد کنید.")
                    return
                companies_service.create_company(
                    code,
                    legal_name,
                    display_name,
                    base_currency_id,
                    default_language_id,
                    self.fy_month_field.value(),
                    self.fy_day_field.value(),
                    economic_code=self.economic_code_field.text().strip() or None,
                    registration_no=self.registration_no_field.text().strip() or None,
                    national_id=self.national_id_field.text().strip() or None,
                )
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return

        self.refresh()
