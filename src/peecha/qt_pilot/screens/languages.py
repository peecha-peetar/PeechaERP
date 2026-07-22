"""مدیریتِ زبان‌ها — معادلِ Qt برایِ languages.py/.kv در Kivy."""

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

from peecha.services import languages as languages_service

_COLUMNS = ["فعال", "پیش‌فرض", "راست‌به‌چپ", "ترتیب", "نامِ بومی", "کد"]


class LanguagesScreen(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._rows: list[languages_service.LanguageRow] = []
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

        title = QLabel("زبان‌ها")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.table.cellClicked.connect(self._on_row_clicked)
        layout.addWidget(self.table)
        return panel

    def _build_form_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("card")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        self.form_title = QLabel("زبانِ جدید")
        self.form_title.setObjectName("pageTitle")
        layout.addWidget(self.form_title)

        layout.addWidget(QLabel("کد (مثلاً fa)"))
        self.code_field = QLineEdit()
        layout.addWidget(self.code_field)

        layout.addWidget(QLabel("نامِ بومی"))
        self.native_name_field = QLineEdit()
        layout.addWidget(self.native_name_field)

        layout.addWidget(QLabel("ترتیبِ نمایش"))
        self.sort_order_field = QSpinBox()
        self.sort_order_field.setRange(0, 999)
        layout.addWidget(self.sort_order_field)

        self.is_rtl_checkbox = QCheckBox("راست‌به‌چپ")
        layout.addWidget(self.is_rtl_checkbox)

        self.is_default_checkbox = QCheckBox("زبانِ پیش‌فرض")
        layout.addWidget(self.is_default_checkbox)

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
        self._rows = languages_service.list_languages()
        self.table.setRowCount(len(self._rows))
        for row_index, lang in enumerate(self._rows):
            values = [
                "بله" if lang.is_active else "خیر",
                "بله" if lang.is_default else "خیر",
                "بله" if lang.is_rtl else "خیر",
                str(lang.sort_order),
                lang.native_name,
                lang.code,
            ]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, lang.language_id)
                self.table.setItem(row_index, col_index, item)

    def _on_row_clicked(self, row: int, _column: int) -> None:
        language_id = self.table.item(row, 0).data(Qt.UserRole)
        lang = next((r for r in self._rows if r.language_id == language_id), None)
        if lang is not None:
            self._load_into_form(lang)

    def _load_into_form(self, lang: languages_service.LanguageRow) -> None:
        self._editing_id = lang.language_id
        self.form_title.setText(f"ویرایشِ زبان — {lang.native_name}")
        self.status_label.setText("")
        self.code_field.setText(lang.code)
        self.code_field.setEnabled(False)
        self.native_name_field.setText(lang.native_name)
        self.sort_order_field.setValue(lang.sort_order)
        self.is_rtl_checkbox.setChecked(lang.is_rtl)
        self.is_default_checkbox.setChecked(lang.is_default)
        self.is_active_checkbox.setChecked(lang.is_active)
        self.delete_button.setVisible(True)

    def _reset_form(self) -> None:
        self._editing_id = None
        self.form_title.setText("زبانِ جدید")
        self.status_label.setText("")
        self.code_field.clear()
        self.code_field.setEnabled(True)
        self.native_name_field.clear()
        self.sort_order_field.setValue(0)
        self.is_rtl_checkbox.setChecked(False)
        self.is_default_checkbox.setChecked(False)
        self.is_active_checkbox.setChecked(True)
        self.delete_button.setVisible(False)
        self.table.clearSelection()

    def _save(self) -> None:
        native_name = self.native_name_field.text().strip()
        if not native_name:
            self.status_label.setText("نامِ بومی را وارد کنید.")
            return

        try:
            if self._editing_id is not None:
                languages_service.update_language(
                    self._editing_id,
                    native_name,
                    self.is_rtl_checkbox.isChecked(),
                    self.is_default_checkbox.isChecked(),
                    self.is_active_checkbox.isChecked(),
                    self.sort_order_field.value(),
                )
            else:
                code = self.code_field.text().strip()
                if not code:
                    self.status_label.setText("کد را وارد کنید.")
                    return
                languages_service.create_language(
                    code,
                    native_name,
                    self.is_rtl_checkbox.isChecked(),
                    self.is_default_checkbox.isChecked(),
                    self.sort_order_field.value(),
                )
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return

        self.refresh()

    def _delete(self) -> None:
        if self._editing_id is None:
            return
        confirm = QMessageBox.question(
            self, "حذفِ زبان", "این زبان حذف شود؟", QMessageBox.Yes | QMessageBox.No
        )
        if confirm != QMessageBox.Yes:
            return
        try:
            languages_service.delete_language(self._editing_id)
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self.refresh()
