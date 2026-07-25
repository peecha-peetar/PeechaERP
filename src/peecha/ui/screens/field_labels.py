"""عنوانِ فیلدها — معادلِ Qt برایِ field_labels.py/.kv در Kivy."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from peecha.services import field_labels as field_labels_service
from peecha.services import languages as languages_service
from peecha.ui.widgets import FieldHelpMixin

_FORM_CODES = [
    "chart_of_accounts",
    "journal_entry",
    "languages",
    "companies",
    "fiscal_years",
    "users",
    "roles",
]
_FORM_LABELS = {
    "chart_of_accounts": "کدینگِ حساب‌ها",
    "journal_entry": "صدورِ سند",
    "languages": "زبان‌ها",
    "companies": "شرکت‌ها",
    "fiscal_years": "سال‌های مالی",
    "users": "کاربران",
    "roles": "نقش‌ها",
}


class _FieldEditRow(QWidget):
    def __init__(self, field_id: int, default_label: str, current_label: str | None, on_save, on_reset) -> None:
        super().__init__()
        self._field_id = field_id
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        layout.addWidget(QLabel(default_label))

        self.value_field = QLineEdit()
        self.value_field.setText(current_label or default_label)
        layout.addWidget(self.value_field)

        save_button = QPushButton("ذخیره")
        save_button.setObjectName("flatButton")
        save_button.clicked.connect(lambda: on_save(field_id, self.value_field.text().strip()))
        layout.addWidget(save_button)

        reset_button = QPushButton("بازگشت به پیش‌فرض")
        reset_button.setObjectName("flatButton")
        reset_button.clicked.connect(lambda: on_reset(field_id))
        layout.addWidget(reset_button)


class FieldLabelsScreen(FieldHelpMixin, QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._language_id: int | None = None
        self._rows: list[_FieldEditRow] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        title = QLabel("عنوانِ فیلدها")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        selectors = QHBoxLayout()
        selectors.addWidget(QLabel("فرم"))
        self.form_combo = QComboBox()
        for code in _FORM_CODES:
            self.form_combo.addItem(_FORM_LABELS.get(code, code), code)
        self.form_combo.currentIndexChanged.connect(self._reload_list)
        selectors.addWidget(self.form_combo)

        selectors.addWidget(QLabel("زبان"))
        self.language_combo = QComboBox()
        self.language_combo.currentIndexChanged.connect(self._reload_list)
        selectors.addWidget(self.language_combo)
        selectors.addStretch(1)
        layout.addLayout(selectors)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusError")
        layout.addWidget(self.status_label)

        self.rows_container = QVBoxLayout()
        rows_widget = QWidget()
        rows_widget.setLayout(self.rows_container)
        layout.addWidget(rows_widget)
        layout.addStretch(1)

        self.set_field_help([
            (self.form_combo, "فرمی که می‌خواهید نامِ فیلدهایش را تغییر دهید."),
            (
                self.language_combo,
                "زبانی که این تغییرِ نام برایش اعمال می‌شود. هر زبان می‌تواند نامِ جداگانه‌ای برایِ همان فیلد داشته باشد؛ "
                "این نام فقط جایِ نمایش را عوض می‌کند، خودِ فیلد در پایگاه‌داده تغییر نمی‌کند.",
            ),
        ])

    def refresh(self) -> None:
        languages = languages_service.list_languages()
        self.language_combo.blockSignals(True)
        self.language_combo.clear()
        for lang in languages:
            self.language_combo.addItem(lang.native_name, lang.language_id)
        self.language_combo.blockSignals(False)
        self._reload_list()

    def _current_form_code(self) -> str | None:
        return self.form_combo.currentData()

    def _reload_list(self) -> None:
        while self.rows_container.count():
            child = self.rows_container.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        self._rows = []

        form_code = self._current_form_code()
        language_id = self.language_combo.currentData()
        if form_code is None or language_id is None:
            return

        for field in field_labels_service.list_fields(form_code, language_id):
            row = _FieldEditRow(field.field_id, field.default_label, field.label, self._save_label, self._reset_label)
            self.rows_container.addWidget(row)
            self._rows.append(row)

    def _save_label(self, field_id: int, label: str) -> None:
        language_id = self.language_combo.currentData()
        if language_id is None:
            return
        field_labels_service.set_label(field_id, language_id, label or None)
        self.status_label.setText("")

    def _reset_label(self, field_id: int) -> None:
        language_id = self.language_combo.currentData()
        if language_id is None:
            return
        field_labels_service.set_label(field_id, language_id, None)
        self._reload_list()
