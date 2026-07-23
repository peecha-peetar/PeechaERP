"""مدیریتِ ارزها — معادلِ Qt برایِ currencies.py/.kv در Kivy.

نسخه‌ی این مرحله از مهاجرت فقط فهرستِ سراسریِ ارزها (core.currencies) را
پوشش می‌دهد؛ اتصالِ ارز به شرکت/نرخِ روزانه (که در Kivy هم در همین صفحه
بود) در قدمِ بعدیِ مهاجرت اضافه می‌شود."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
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

from peecha.services import currencies as currencies_service

_COLUMNS = ["فعال", "رقمِ اعشار", "نماد", "کدِ ارز"]


class CurrenciesScreen(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._rows: list[currencies_service.CurrencyRow] = []
        self._editing_id: int | None = None

        outer = QHBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(16)
        outer.addWidget(self._build_list_panel(), stretch=3)
        outer.addWidget(self._build_form_panel(), stretch=1)

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
