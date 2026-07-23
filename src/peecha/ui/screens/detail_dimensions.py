"""مدیریتِ ابعادِ تفصیلی — معادلِ Qt برایِ detail_dimensions.py/.kv در Kivy.

سه ستون: (۱) فهرستِ گروه‌های تفصیلی + ساختِ گروهِ تازه، (۲) پیکربندیِ
سطوح/فیلدهایِ اختصاصیِ گروهِ انتخاب‌شده، (۳) فرمِ حسابِ تفصیلی
(سلسله‌مراتبی، با انتخابِ والد) + فهرستِ حساب‌هایِ همان گروه."""

from __future__ import annotations

import datetime
import decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDoubleSpinBox,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from peecha import session
from peecha.services import detail_dimensions as dimensions_service

_FIELD_KIND_OPTIONS = [("text", "متن"), ("decimal", "عدد اعشاری"), ("date", "تاریخ"), ("boolean", "بله/خیر")]


class _GroupFieldRowWidget(QWidget):
    def __init__(self, on_remove, initial: dimensions_service.GroupFieldRow | None = None) -> None:
        super().__init__()
        self._on_remove = on_remove
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.key_field = QLineEdit()
        self.key_field.setPlaceholderText("کلید (مثلاً account_no)")
        layout.addWidget(self.key_field)

        self.label_field = QLineEdit()
        self.label_field.setPlaceholderText("عنوان")
        layout.addWidget(self.label_field)

        self.kind_combo = QComboBox()
        for code, label in _FIELD_KIND_OPTIONS:
            self.kind_combo.addItem(label, code)
        layout.addWidget(self.kind_combo)

        self.required_checkbox = QCheckBox("اجباری")
        layout.addWidget(self.required_checkbox)

        remove_button = QPushButton("حذف")
        remove_button.setObjectName("dangerButton")
        remove_button.clicked.connect(lambda: self._on_remove(self))
        layout.addWidget(remove_button)

        if initial is not None:
            self.key_field.setText(initial.field_key)
            self.label_field.setText(initial.label)
            index = self.kind_combo.findData(initial.kind)
            self.kind_combo.setCurrentIndex(index if index >= 0 else 0)
            self.required_checkbox.setChecked(initial.is_required)

    def to_field_dict(self, sort_order: int) -> dict:
        return {
            "field_key": self.key_field.text().strip(),
            "label": self.label_field.text().strip(),
            "kind": self.kind_combo.currentData(),
            "is_required": self.required_checkbox.isChecked(),
            "sort_order": sort_order,
        }


class DetailDimensionsScreen(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._types: list[dimensions_service.DimensionTypeRow] = []
        self._selected_type_id: int | None = None
        self._accounts_by_id: dict[int, dimensions_service.DetailAccountRow] = {}
        self._editing_account_id: int | None = None
        self._selected_parent_id: int | None = None
        self._field_rows: list[_GroupFieldRowWidget] = []
        self._extra_widgets: dict[str, QWidget] = {}

        outer = QHBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(16)
        outer.addWidget(self._build_types_panel(), stretch=2)
        outer.addWidget(self._build_config_panel(), stretch=3)
        outer.addWidget(self._build_account_panel(), stretch=3)

    # --- ستونِ ۱: گروه‌ها -----------------------------------------------
    def _build_types_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("card")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        title = QLabel("گروه‌هایِ تفصیلی")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        self.types_list = QListWidget()
        self.types_list.itemClicked.connect(self._on_type_selected)
        layout.addWidget(self.types_list)

        layout.addWidget(QLabel("کدِ گروهِ تازه"))
        self.new_type_code_field = QLineEdit()
        layout.addWidget(self.new_type_code_field)

        self.type_status_label = QLabel("")
        self.type_status_label.setObjectName("statusError")
        self.type_status_label.setWordWrap(True)
        layout.addWidget(self.type_status_label)

        create_button = QPushButton("افزودنِ گروه")
        create_button.setObjectName("primaryButton")
        create_button.clicked.connect(self._create_type)
        layout.addWidget(create_button)

        layout.addStretch(1)
        return panel

    # --- ستونِ ۲: پیکربندیِ سطوح/فیلدها ------------------------------------
    def _build_config_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("card")
        self.config_panel = panel
        panel.setEnabled(False)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        self.config_title = QLabel("پیکربندیِ گروه")
        self.config_title.setObjectName("pageTitle")
        layout.addWidget(self.config_title)

        layout.addWidget(QLabel("طولِ کدِ هر سطح (خالی = بدونِ محدودیت)"))
        levels_grid = QGridLayout()
        self.level_fields: dict[int, QSpinBox] = {}
        for level_no in range(1, 5):
            levels_grid.addWidget(QLabel(f"سطحِ {level_no}"), 0, level_no - 1)
            spin = QSpinBox()
            spin.setRange(0, 10)
            spin.setSpecialValueText(" ")
            levels_grid.addWidget(spin, 1, level_no - 1)
            self.level_fields[level_no] = spin
        layout.addLayout(levels_grid)

        save_levels_button = QPushButton("ذخیره‌ی پیکربندیِ سطوح")
        save_levels_button.setObjectName("flatButton")
        save_levels_button.clicked.connect(self._save_levels)
        layout.addWidget(save_levels_button)

        layout.addWidget(QLabel("فیلدهایِ اختصاصیِ این گروه"))
        self.fields_container = QVBoxLayout()
        fields_widget = QWidget()
        fields_widget.setLayout(self.fields_container)
        layout.addWidget(fields_widget)

        add_field_button = QPushButton("+ افزودنِ فیلد")
        add_field_button.setObjectName("flatButton")
        add_field_button.clicked.connect(lambda: self._add_field_row())
        layout.addWidget(add_field_button)

        save_fields_button = QPushButton("ذخیره‌ی فیلدها")
        save_fields_button.setObjectName("primaryButton")
        save_fields_button.clicked.connect(self._save_fields)
        layout.addWidget(save_fields_button)

        layout.addStretch(1)
        return panel

    # --- ستونِ ۳: حساب‌هایِ تفصیلی ------------------------------------------
    def _build_account_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("card")
        self.account_panel = panel
        panel.setEnabled(False)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        self.account_form_title = QLabel("حسابِ تفصیلیِ جدید")
        self.account_form_title.setObjectName("pageTitle")
        layout.addWidget(self.account_form_title)

        grid = QGridLayout()
        grid.addWidget(QLabel("والد"), 0, 0)
        self.parent_combo = QComboBox()
        grid.addWidget(self.parent_combo, 0, 1)

        grid.addWidget(QLabel("کد"), 1, 0)
        self.account_code_field = QLineEdit()
        grid.addWidget(self.account_code_field, 1, 1)

        grid.addWidget(QLabel("نام"), 2, 0)
        self.account_name_field = QLineEdit()
        grid.addWidget(self.account_name_field, 2, 1)

        self.account_active_checkbox = QCheckBox("فعال")
        self.account_active_checkbox.setChecked(True)
        grid.addWidget(self.account_active_checkbox, 3, 1)
        layout.addLayout(grid)

        layout.addWidget(QLabel("فیلدهایِ اختصاصی"))
        self.extra_fields_container = QVBoxLayout()
        extra_widget = QWidget()
        extra_widget.setLayout(self.extra_fields_container)
        layout.addWidget(extra_widget)

        self.account_status_label = QLabel("")
        self.account_status_label.setObjectName("statusError")
        self.account_status_label.setWordWrap(True)
        layout.addWidget(self.account_status_label)

        buttons = QHBoxLayout()
        save_button = QPushButton("ذخیره")
        save_button.setObjectName("primaryButton")
        save_button.clicked.connect(self._save_account)
        buttons.addWidget(save_button)
        cancel_button = QPushButton("انصراف")
        cancel_button.setObjectName("flatButton")
        cancel_button.clicked.connect(self._cancel_account_edit)
        buttons.addWidget(cancel_button)
        layout.addLayout(buttons)

        self.accounts_table = QTableWidget(0, 4)
        self.accounts_table.setHorizontalHeaderLabels(["وضعیت", "نام", "کدِ کامل", "سطح"])
        self.accounts_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.accounts_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.accounts_table.verticalHeader().setVisible(False)
        self.accounts_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.accounts_table.cellClicked.connect(self._on_account_row_clicked)
        layout.addWidget(self.accounts_table, stretch=1)

        return panel

    # --- بارگذاری --------------------------------------------------------
    def _company_id(self) -> int | None:
        return session.current_company.company_id if session.current_company else None

    def refresh(self) -> None:
        company_id = self._company_id()
        self._types = dimensions_service.list_dimension_types(company_id) if company_id is not None else []
        self.types_list.clear()
        for t in self._types:
            item = QListWidgetItem(f"{t.code} ({t.detail_account_count})")
            item.setData(Qt.UserRole, t.dimension_type_id)
            self.types_list.addItem(item)
        if self._selected_type_id is None:
            self.config_panel.setEnabled(False)
            self.account_panel.setEnabled(False)

    def _create_type(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        code = self.new_type_code_field.text().strip()
        if not code:
            self.type_status_label.setText("کد را وارد کنید.")
            return
        try:
            new_type = dimensions_service.create_dimension_type(company_id, code)
        except ValueError as exc:
            self.type_status_label.setText(str(exc))
            return
        self.type_status_label.setText("")
        self.new_type_code_field.clear()
        self.refresh()
        self._select_type(new_type.dimension_type_id)

    def _on_type_selected(self, item: QListWidgetItem) -> None:
        self._select_type(item.data(Qt.UserRole))

    def _select_type(self, dimension_type_id: int) -> None:
        self._selected_type_id = dimension_type_id
        dim_type = next((t for t in self._types if t.dimension_type_id == dimension_type_id), None)
        if dim_type is None:
            return
        self.config_title.setText(f"پیکربندیِ گروهِ «{dim_type.code}»")
        self.config_panel.setEnabled(True)
        self.account_panel.setEnabled(True)
        self._load_levels()
        self._load_fields()
        self._cancel_account_edit()
        self._reload_accounts()

    # --- سطوح ------------------------------------------------------------
    def _load_levels(self) -> None:
        levels = {row.level_no: row.code_length for row in dimensions_service.list_group_levels(self._selected_type_id)}
        for level_no, spin in self.level_fields.items():
            spin.setValue(levels.get(level_no, 0))

    def _save_levels(self) -> None:
        company_id = self._company_id()
        if company_id is None or self._selected_type_id is None:
            return
        levels = {level_no: spin.value() for level_no, spin in self.level_fields.items() if spin.value() > 0}
        try:
            dimensions_service.set_group_levels(self._selected_type_id, company_id, levels)
        except ValueError as exc:
            self.type_status_label.setText(str(exc))

    # --- فیلدهایِ اختصاصیِ گروه --------------------------------------------
    def _load_fields(self) -> None:
        while self.fields_container.count():
            child = self.fields_container.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        self._field_rows = []
        for field_row in dimensions_service.list_group_fields(self._selected_type_id):
            self._add_field_row(field_row)

    def _add_field_row(self, initial: dimensions_service.GroupFieldRow | None = None) -> None:
        row_widget = _GroupFieldRowWidget(self._remove_field_row, initial)
        self.fields_container.addWidget(row_widget)
        self._field_rows.append(row_widget)

    def _remove_field_row(self, row_widget: _GroupFieldRowWidget) -> None:
        self._field_rows.remove(row_widget)
        self.fields_container.removeWidget(row_widget)
        row_widget.deleteLater()

    def _save_fields(self) -> None:
        company_id = self._company_id()
        if company_id is None or self._selected_type_id is None:
            return
        fields = [row.to_field_dict(i) for i, row in enumerate(self._field_rows)]
        for f in fields:
            if not f["field_key"] or not f["label"]:
                self.type_status_label.setText("کلید و عنوانِ همه‌ی فیلدها را پر کنید.")
                return
        try:
            dimensions_service.set_group_fields(self._selected_type_id, company_id, fields)
        except ValueError as exc:
            self.type_status_label.setText(str(exc))
            return
        self.type_status_label.setText("")
        self._load_fields()
        self._render_extra_fields()

    # --- فرمِ حسابِ تفصیلی --------------------------------------------------
    def _reload_accounts(self) -> None:
        company_id = self._company_id()
        rows = dimensions_service.list_detail_accounts(company_id, self._selected_type_id)
        self._accounts_by_id = {r.detail_account_id: r for r in rows}

        self.parent_combo.clear()
        self.parent_combo.addItem("— بدونِ والد (سطحِ ۱) —", None)
        for r in rows:
            if r.level_no < dimensions_service.MAX_DETAIL_LEVEL and r.detail_account_id != self._editing_account_id:
                self.parent_combo.addItem(f"{r.full_code} — {r.name or ''}", r.detail_account_id)

        self.accounts_table.setRowCount(len(rows))
        for row_index, r in enumerate(rows):
            values = ["فعال" if r.is_active else "غیرفعال", r.name or "—", r.full_code, str(r.level_no)]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, r.detail_account_id)
                self.accounts_table.setItem(row_index, col_index, item)

        self._render_extra_fields()

    def _render_extra_fields(self, values: dict | None = None) -> None:
        while self.extra_fields_container.count():
            child = self.extra_fields_container.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        self._extra_widgets = {}
        if self._selected_type_id is None:
            return
        for field_def in dimensions_service.list_group_fields(self._selected_type_id):
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.addWidget(QLabel(field_def.label))
            widget: QWidget
            if field_def.kind == "boolean":
                widget = QCheckBox()
            elif field_def.kind == "decimal":
                widget = QDoubleSpinBox()
                widget.setRange(0, 10_000_000_000)
                widget.setDecimals(2)
            elif field_def.kind == "date":
                widget = QDateEdit()
                widget.setCalendarPopup(True)
                widget.setSpecialValueText(" ")
                widget.setDate(widget.minimumDate())
            else:
                widget = QLineEdit()
            row_layout.addWidget(widget)
            self.extra_fields_container.addWidget(row)
            self._extra_widgets[field_def.field_key] = (widget, field_def.kind)

            if values is not None and field_def.field_key in values and values[field_def.field_key] is not None:
                value = values[field_def.field_key]
                if field_def.kind == "boolean":
                    widget.setChecked(bool(value))
                elif field_def.kind == "decimal":
                    widget.setValue(float(value))
                elif field_def.kind == "date" and isinstance(value, datetime.date):
                    widget.setDate(value)
                else:
                    widget.setText(str(value))

    def _collect_extra_fields(self) -> dict:
        result = {}
        for key, (widget, kind) in self._extra_widgets.items():
            if kind == "boolean":
                result[key] = widget.isChecked()
            elif kind == "decimal":
                result[key] = decimal.Decimal(str(widget.value())) if widget.value() else None
            elif kind == "date":
                qdate = widget.date()
                result[key] = None if qdate == widget.minimumDate() else datetime.date(qdate.year(), qdate.month(), qdate.day())
            else:
                text = widget.text().strip()
                result[key] = text or None
        return result

    def _on_account_row_clicked(self, row: int, _column: int) -> None:
        detail_account_id = self.accounts_table.item(row, 0).data(Qt.UserRole)
        self.edit_detail_account(detail_account_id)

    def edit_detail_account(self, detail_account_id: int) -> None:
        account = self._accounts_by_id.get(detail_account_id)
        if account is None:
            return
        self._editing_account_id = detail_account_id
        self._reload_accounts()  # برایِ به‌روزکردنِ فهرستِ والدهای مجاز (بدونِ خودش)
        self.account_form_title.setText(f"ویرایشِ «{account.full_code}»")
        self.account_code_field.setText(account.code)
        self.account_name_field.setText(account.name or "")
        self.account_active_checkbox.setChecked(account.is_active)
        if account.parent_detail_account_id is not None:
            index = self.parent_combo.findData(account.parent_detail_account_id)
            self.parent_combo.setCurrentIndex(index if index >= 0 else 0)
        else:
            self.parent_combo.setCurrentIndex(0)
        self.parent_combo.setEnabled(False)
        self._render_extra_fields(account.extra_fields)

    def _cancel_account_edit(self) -> None:
        self._editing_account_id = None
        self._selected_parent_id = None
        self.account_form_title.setText("حسابِ تفصیلیِ جدید")
        self.account_status_label.setText("")
        self.account_code_field.clear()
        self.account_name_field.clear()
        self.account_active_checkbox.setChecked(True)
        self.parent_combo.setEnabled(True)
        if self.parent_combo.count():
            self.parent_combo.setCurrentIndex(0)
        self._render_extra_fields()
        self.accounts_table.clearSelection()

    def _save_account(self) -> None:
        company_id = self._company_id()
        if company_id is None or self._selected_type_id is None:
            return
        code = self.account_code_field.text().strip()
        if not code:
            self.account_status_label.setText("کد را وارد کنید.")
            return
        name = self.account_name_field.text().strip() or None
        extra_fields = self._collect_extra_fields()

        try:
            if self._editing_account_id is not None:
                dimensions_service.update_detail_account(
                    self._editing_account_id, company_id, code, self.account_active_checkbox.isChecked(),
                    name=name, extra_fields=extra_fields,
                )
            else:
                dimensions_service.create_detail_account(
                    company_id, self._selected_type_id, code, name=name,
                    parent_detail_account_id=self.parent_combo.currentData(), extra_fields=extra_fields,
                )
        except ValueError as exc:
            self.account_status_label.setText(str(exc))
            return

        self._cancel_account_edit()
        self.refresh()
        self._select_type(self._selected_type_id)

    # --- برایِ ناوبری از فهرستِ واحدِ تفصیلی‌ها -----------------------------
    def select_type_and_edit(self, dimension_type_id: int, detail_account_id: int) -> None:
        self.refresh()
        self._select_type(dimension_type_id)
        self.edit_detail_account(detail_account_id)
