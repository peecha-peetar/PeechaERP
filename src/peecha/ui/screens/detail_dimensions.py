"""ثبتِ حساب‌هایِ تفصیلیِ گروه‌هایِ «ساده» (بدونِ صفحه‌ی اختصاصی).

طبقِ درخواستِ صریح، این صفحه دیگر گروه نمی‌سازد و سطح/فیلدِ گروه را
پیکربندی نمی‌کند — آن دو کار به‌طورِ جدا در dimension_group_config.py
(«پیکربندیِ گروه‌هایِ تفصیلی») انجام می‌شود. این‌جا فقط برایِ گروه‌هایی که
صفحه‌ی اختصاصیِ خودشان را ندارند (یعنی نه یکی از ۷ نوعِ «فرمِ خاص»
کالا/دارایی‌ثابت/بانک/صندوق/تنخواه/مرکزِ هزینه/پروژه)، فرمِ سلسله‌مراتبیِ
حسابِ تفصیلی (تا ۴ سطح، با انتخابِ والد) + فهرستِ همان گروه را نشان
می‌دهد."""

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
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from peecha import session
from peecha.services import detail_dimensions as dimensions_service


class DetailDimensionsScreen(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._types: list[dimensions_service.DimensionTypeRow] = []
        self._selected_type_id: int | None = None
        self._accounts_by_id: dict[int, dimensions_service.DetailAccountRow] = {}
        self._editing_account_id: int | None = None
        self._extra_widgets: dict[str, tuple[QWidget, str]] = {}

        outer = QHBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(16)
        outer.addWidget(self._build_list_panel(), stretch=3)
        outer.addWidget(self._build_account_panel(), stretch=2)

    # --- ستونِ چپ: انتخابِ گروه + فهرستِ حساب‌ها -----------------------------
    def _build_list_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("card")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        title = QLabel("تفصیلی‌هایِ گروه‌هایِ ساده")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        hint = QLabel(
            "ساختِ گروهِ تازه و تنظیمِ تعدادِ رقم/بازه/فیلدِ اختصاصی در «پیکربندیِ گروه‌هایِ تفصیلی» انجام می‌شود."
        )
        hint.setObjectName("sectionHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        layout.addWidget(QLabel("گروه"))
        self.group_combo = QComboBox()
        self.group_combo.currentIndexChanged.connect(self._on_group_changed)
        layout.addWidget(self.group_combo)

        self.accounts_table = QTableWidget(0, 4)
        self.accounts_table.setHorizontalHeaderLabels(["وضعیت", "نام", "کدِ کامل", "سطح"])
        self.accounts_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.accounts_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.accounts_table.verticalHeader().setVisible(False)
        self.accounts_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.accounts_table.cellClicked.connect(self._on_account_row_clicked)
        layout.addWidget(self.accounts_table, stretch=1)

        return panel

    # --- ستونِ راست: فرمِ حسابِ تفصیلی ---------------------------------------
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

        layout.addStretch(1)
        return panel

    # --- بارگذاری --------------------------------------------------------
    def _company_id(self) -> int | None:
        return session.current_company.company_id if session.current_company else None

    def refresh(self) -> None:
        company_id = self._company_id()
        # فقط گروه‌هایِ «ساده» (بدونِ صفحه‌ی اختصاصیِ خودشان) این‌جا نمایان‌اند.
        self._types = [
            t
            for t in (dimensions_service.list_dimension_types(company_id) if company_id is not None else [])
            if t.code not in dimensions_service.SPECIALIZED_DIMENSION_LABELS
        ]
        previous_id = self._selected_type_id
        self.group_combo.blockSignals(True)
        self.group_combo.clear()
        self.group_combo.addItem("— انتخابِ گروه —", None)
        for t in self._types:
            self.group_combo.addItem(f"{t.code} ({t.detail_account_count})", t.dimension_type_id)
        self.group_combo.blockSignals(False)

        if previous_id is not None and any(t.dimension_type_id == previous_id for t in self._types):
            self.group_combo.setCurrentIndex(self.group_combo.findData(previous_id))
        else:
            self._selected_type_id = None
            self.account_panel.setEnabled(False)

    def _on_group_changed(self) -> None:
        self._select_type(self.group_combo.currentData())

    def _select_type(self, dimension_type_id: int | None) -> None:
        self._selected_type_id = dimension_type_id
        if dimension_type_id is None:
            self.account_panel.setEnabled(False)
            return
        self.account_panel.setEnabled(True)
        self._cancel_account_edit()
        self._reload_accounts()

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
        index = self.group_combo.findData(dimension_type_id)
        if index >= 0:
            self.group_combo.setCurrentIndex(index)
        self.edit_detail_account(detail_account_id)
