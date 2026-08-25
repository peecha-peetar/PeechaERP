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
from peecha.ui.widgets import FieldGrid, FieldHelpMixin, FieldSpec, LayoutEditMixin, wrap_scrollable, wrap_scrollable_with_footer

_COLUMNS = ["فعال", "پیش‌فرض", "راست‌به‌چپ", "ترتیب", "نامِ بومی", "کد"]


class LanguagesScreen(FieldHelpMixin, LayoutEditMixin, QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._rows: list[languages_service.LanguageRow] = []
        self._editing_id: int | None = None

        outer = QHBoxLayout(self)
        outer.setContentsMargins(20, 14, 20, 14)
        outer.setSpacing(16)
        outer.addWidget(self._build_list_panel(), stretch=3)
        outer.addWidget(self._build_form_panel(), stretch=1)

        self.set_field_help([
            (
                self.code_field,
                "کدِ کوتاهِ زبان، مثلاً fa برایِ فارسی یا en برایِ انگلیسی. بعدِ ساختن قابلِ‌تغییر نیست.",
            ),
            (
                self.native_name_field,
                "نامِ زبان به خودِ همان زبان، مثلاً «فارسی» یا English. همین نام در فهرستِ انتخابِ زبان نشان داده می‌شود.",
            ),
            (
                self.sort_order_field,
                "ترتیبِ نمایشِ این زبان در فهرست‌هایِ انتخابِ زبان. عددِ کوچک‌تر بالاتر می‌آید.",
            ),
            (
                self.is_rtl_checkbox,
                "اگر این زبان راست‌به‌چپ نوشته می‌شود (مثلِ فارسی یا عربی) تیک بزنید. جهتِ متن و چیدمانِ فرم‌ها را تغییر می‌دهد.",
            ),
            (
                self.is_default_checkbox,
                "زبانِ پیش‌فرضِ کلِ سیستم — وقتی کاربر یا شرکتی زبانِ خاصی انتخاب نکرده باشد، همین زبان استفاده می‌شود.",
            ),
            (
                self.is_active_checkbox,
                "زبانِ غیرِفعال دیگر در فهرستِ انتخابِ زبان نشان داده نمی‌شود.",
            ),
        ])

    def _build_list_panel(self) -> QWidget:
        panel = QWidget()
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
        return wrap_scrollable(panel)

    def _build_form_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        self.form_title = QLabel("زبانِ جدید")
        self.form_title.setObjectName("pageTitle")
        layout.addWidget(self.form_title)

        self.code_field = QLineEdit()

        self.native_name_field = QLineEdit()

        self.sort_order_field = QSpinBox()
        self.sort_order_field.setRange(0, 999)

        self.is_rtl_checkbox = QCheckBox("راست‌به‌چپ")

        self.is_default_checkbox = QCheckBox("زبانِ پیش‌فرض")

        self.is_active_checkbox = QCheckBox("فعال")
        self.is_active_checkbox.setChecked(True)

        self.basic_grid = FieldGrid([
            FieldSpec("code", "کد (مثلاً fa)", self.code_field, span=1),
            FieldSpec("native_name", "نامِ بومی", self.native_name_field, span=3),
            FieldSpec("sort_order", "ترتیبِ نمایش", self.sort_order_field, span=1),
            FieldSpec("is_rtl", "", self.is_rtl_checkbox, span=1),
            FieldSpec("is_default", "", self.is_default_checkbox, span=1),
            FieldSpec("is_active", "", self.is_active_checkbox, span=1),
        ])
        layout.addWidget(self.basic_grid)
        self.register_field_grids("languages", [self.basic_grid])

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusError")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        save_button = QPushButton("💾")
        save_button.setObjectName("primaryIconButton")
        save_button.setFixedWidth(48)
        save_button.setToolTip("ذخیره")
        save_button.clicked.connect(self._save)

        cancel_button = QPushButton("↩️")
        cancel_button.setObjectName("iconButton")
        cancel_button.setFixedWidth(44)
        cancel_button.setToolTip("انصراف")
        cancel_button.clicked.connect(self._reset_form)

        self.delete_button = QPushButton("🗑️")
        self.delete_button.setObjectName("dangerIconButton")
        self.delete_button.setFixedWidth(44)
        self.delete_button.setToolTip("حذف")
        self.delete_button.clicked.connect(self._delete)
        self.delete_button.setVisible(False)

        layout.addStretch(1)
        return wrap_scrollable_with_footer(panel, [save_button, cancel_button, self.delete_button])

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
