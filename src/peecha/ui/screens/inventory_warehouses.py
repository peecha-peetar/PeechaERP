"""انبارها و مکان‌هایِ انبار (inv.warehouses/bin_locations)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from peecha import session as app_session
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import inventory_locations as locations_service
from peecha.ui.widgets import FieldHelpMixin

_COLUMNS = ["فعال", "پیش‌فرض", "نوع", "نام", "کد"]
_BIN_COLUMNS = ["فعال", "قابلِ‌برداشت", "نام", "کد"]
_TYPE_LABELS = {
    "GENERAL": "عمومی", "PROJECT": "پروژه‌ای", "PRODUCTION_LINE": "خطِ تولید",
    "QUARANTINE": "قرنطینه", "TRANSIT": "ترانزیت",
}


def _wrap_scrollable(content: QWidget) -> QWidget:
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.NoFrame)
    scroll.setWidget(content)
    wrapper = QWidget()
    wrapper.setObjectName("card")
    wrapper_layout = QVBoxLayout(wrapper)
    wrapper_layout.setContentsMargins(0, 0, 0, 0)
    wrapper_layout.setSpacing(0)
    wrapper_layout.addWidget(scroll)
    return wrapper


class _BinLocationDialog(QDialog):
    def __init__(self, parent: QWidget, existing_bins: list[locations_service.BinLocationRow]) -> None:
        super().__init__(parent)
        self.setWindowTitle("مکانِ انبارِ جدید")
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("کد"))
        self.code_field = QLineEdit()
        layout.addWidget(self.code_field)

        layout.addWidget(QLabel("نام"))
        self.name_field = QLineEdit()
        layout.addWidget(self.name_field)

        layout.addWidget(QLabel("والد (اختیاری)"))
        self.parent_combo = QComboBox()
        self.parent_combo.addItem("(بدونِ والد)", None)
        for b in existing_bins:
            self.parent_combo.addItem(f"{b.code} — {b.name or ''}", b.bin_location_id)
        layout.addWidget(self.parent_combo)

        self.pickable_checkbox = QCheckBox("قابلِ‌برداشت")
        self.pickable_checkbox.setChecked(True)
        layout.addWidget(self.pickable_checkbox)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self) -> tuple[str, str, int | None, bool]:
        return self.code_field.text().strip(), self.name_field.text().strip(), self.parent_combo.currentData(), self.pickable_checkbox.isChecked()


class InventoryWarehousesScreen(FieldHelpMixin, QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._rows: list[locations_service.WarehouseRow] = []
        self._bin_rows: list[locations_service.BinLocationRow] = []
        self._editing_id: int | None = None

        outer = QHBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(16)
        outer.addWidget(self._build_list_panel(), stretch=3)
        outer.addWidget(self._build_form_panel(), stretch=2)
        outer.addWidget(self._build_bins_panel(), stretch=2)

        self.set_field_help([
            (self.type_combo, "انبارِ پروژه‌ای باید به یک پروژهٔ تفصیلیِ حسابداری وصل شود."),
            (self.allow_negative_checkbox, "اگر روشن باشد، حواله/خروجی حتی با موجودیِ ناکافی نیز Post می‌شود."),
        ])

    def _build_list_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        title = QLabel("انبارها")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        new_button = QPushButton("+ انبارِ جدید")
        new_button.setObjectName("primaryButton")
        new_button.clicked.connect(self._reset_form)
        layout.addWidget(new_button, alignment=Qt.AlignLeft)

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.cellClicked.connect(self._on_row_clicked)
        layout.addWidget(self.table)
        return _wrap_scrollable(panel)

    def _build_form_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(8)

        self.form_title = QLabel("انبارِ جدید")
        self.form_title.setObjectName("pageTitle")
        layout.addWidget(self.form_title)

        layout.addWidget(QLabel("کد"))
        self.code_field = QLineEdit()
        layout.addWidget(self.code_field)

        layout.addWidget(QLabel("نام"))
        self.name_field = QLineEdit()
        layout.addWidget(self.name_field)

        layout.addWidget(QLabel("نوعِ انبار"))
        self.type_combo = QComboBox()
        for code, label in _TYPE_LABELS.items():
            self.type_combo.addItem(label, code)
        self.type_combo.currentIndexChanged.connect(self._on_type_changed)
        layout.addWidget(self.type_combo)

        self.project_row = QWidget()
        project_layout = QVBoxLayout(self.project_row)
        project_layout.setContentsMargins(0, 0, 0, 0)
        project_layout.addWidget(QLabel("پروژه"))
        self.project_combo = QComboBox()
        project_layout.addWidget(self.project_combo)
        layout.addWidget(self.project_row)

        self.allow_negative_checkbox = QCheckBox("اجازهٔ موجودیِ منفی")
        layout.addWidget(self.allow_negative_checkbox)

        self.temp_controlled_checkbox = QCheckBox("کنترلِ دما")
        self.temp_controlled_checkbox.toggled.connect(self._on_temp_toggled)
        layout.addWidget(self.temp_controlled_checkbox)

        self.temp_row = QWidget()
        temp_layout = QHBoxLayout(self.temp_row)
        temp_layout.setContentsMargins(0, 0, 0, 0)
        temp_layout.addWidget(QLabel("حداقل"))
        self.min_temp_field = QDoubleSpinBox()
        self.min_temp_field.setRange(-100, 100)
        temp_layout.addWidget(self.min_temp_field)
        temp_layout.addWidget(QLabel("حداکثر"))
        self.max_temp_field = QDoubleSpinBox()
        self.max_temp_field.setRange(-100, 100)
        temp_layout.addWidget(self.max_temp_field)
        layout.addWidget(self.temp_row)
        self.temp_row.setVisible(False)

        layout.addWidget(QLabel("آدرس"))
        self.address_field = QLineEdit()
        layout.addWidget(self.address_field)

        self.is_default_checkbox = QCheckBox("انبارِ پیش‌فرض")
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
        self._on_type_changed()
        return _wrap_scrollable(panel)

    def _build_bins_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        title = QLabel("مکان‌هایِ انبار")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        self.add_bin_button = QPushButton("+ مکانِ جدید")
        self.add_bin_button.setObjectName("primaryButton")
        self.add_bin_button.clicked.connect(self._add_bin)
        self.add_bin_button.setEnabled(False)
        layout.addWidget(self.add_bin_button, alignment=Qt.AlignLeft)

        self.bin_table = QTableWidget(0, len(_BIN_COLUMNS))
        self.bin_table.setHorizontalHeaderLabels(_BIN_COLUMNS)
        self.bin_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.bin_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.bin_table.verticalHeader().setVisible(False)
        self.bin_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        layout.addWidget(self.bin_table)

        self.delete_bin_button = QPushButton("حذفِ مکانِ انتخاب‌شده")
        self.delete_bin_button.setObjectName("dangerButton")
        self.delete_bin_button.clicked.connect(self._delete_bin)
        layout.addWidget(self.delete_bin_button)
        return _wrap_scrollable(panel)

    def _on_type_changed(self) -> None:
        self.project_row.setVisible(self.type_combo.currentData() == "PROJECT")

    def _on_temp_toggled(self, checked: bool) -> None:
        self.temp_row.setVisible(checked)

    def _company_id(self) -> int | None:
        return app_session.current_company.company_id if app_session.current_company else None

    def refresh(self) -> None:
        self._reset_form()
        company_id = self._company_id()
        if company_id is None:
            return
        self._rows = locations_service.list_warehouses(company_id)

        self.project_combo.blockSignals(True)
        self.project_combo.clear()
        self.project_combo.addItem("(انتخاب کنید)", None)
        project_type_id = dimensions_service.get_specialized_dimension_type_id(company_id, dimensions_service.PROJECT_CODE)
        for p in dimensions_service.list_leaf_detail_accounts(company_id, project_type_id):
            self.project_combo.addItem(f"{p.code} — {p.name or ''}", p.detail_account_id)
        self.project_combo.blockSignals(False)

        self.table.setRowCount(len(self._rows))
        for row_index, w in enumerate(self._rows):
            values = [
                "بله" if w.is_active else "خیر",
                "بله" if w.is_default else "خیر",
                _TYPE_LABELS.get(w.warehouse_type_code, w.warehouse_type_code),
                w.name,
                w.code,
            ]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, w.warehouse_id)
                self.table.setItem(row_index, col_index, item)

    def _on_row_clicked(self, row: int, _column: int) -> None:
        warehouse_id = self.table.item(row, 0).data(Qt.UserRole)
        w = next((r for r in self._rows if r.warehouse_id == warehouse_id), None)
        if w is not None:
            self._load_into_form(w)

    def _load_into_form(self, w: locations_service.WarehouseRow) -> None:
        self._editing_id = w.warehouse_id
        self.form_title.setText(f"ویرایشِ انبار — {w.name}")
        self.status_label.setText("")
        self.code_field.setText(w.code)
        self.code_field.setEnabled(False)
        self.name_field.setText(w.name)
        self.type_combo.setCurrentIndex(max(0, self.type_combo.findData(w.warehouse_type_code)))
        self.project_combo.setCurrentIndex(max(0, self.project_combo.findData(w.project_detail_account_id)))
        self.allow_negative_checkbox.setChecked(w.allow_negative_stock)
        self.temp_controlled_checkbox.setChecked(w.is_temperature_controlled)
        self.min_temp_field.setValue(float(w.min_temp_c or 0))
        self.max_temp_field.setValue(float(w.max_temp_c or 0))
        self.address_field.setText(w.address or "")
        self.is_default_checkbox.setChecked(w.is_default)
        self.is_active_checkbox.setChecked(w.is_active)
        self.delete_button.setVisible(True)
        self.add_bin_button.setEnabled(True)
        self._refresh_bins()

    def _refresh_bins(self) -> None:
        if self._editing_id is None:
            self.bin_table.setRowCount(0)
            self._bin_rows = []
            return
        self._bin_rows = locations_service.list_bin_locations(self._editing_id)
        self.bin_table.setRowCount(len(self._bin_rows))
        for row_index, b in enumerate(self._bin_rows):
            values = ["بله" if b.is_active else "خیر", "بله" if b.is_pickable else "خیر", b.name or "", b.code]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, b.bin_location_id)
                self.bin_table.setItem(row_index, col_index, item)

    def _reset_form(self) -> None:
        self._editing_id = None
        self.form_title.setText("انبارِ جدید")
        self.status_label.setText("")
        self.code_field.clear()
        self.code_field.setEnabled(True)
        self.name_field.clear()
        self.type_combo.setCurrentIndex(0)
        self.project_combo.setCurrentIndex(0)
        self.allow_negative_checkbox.setChecked(False)
        self.temp_controlled_checkbox.setChecked(False)
        self.min_temp_field.setValue(0)
        self.max_temp_field.setValue(0)
        self.address_field.clear()
        self.is_default_checkbox.setChecked(False)
        self.is_active_checkbox.setChecked(True)
        self.delete_button.setVisible(False)
        self.add_bin_button.setEnabled(False)
        self.table.clearSelection()
        self._refresh_bins()

    def _save(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        name = self.name_field.text().strip()
        code = self.code_field.text().strip()
        if not code:
            self.status_label.setText("کد را وارد کنید.")
            return
        if not name:
            self.status_label.setText("نام را وارد کنید.")
            return
        warehouse_type_code = self.type_combo.currentData()
        project_detail_account_id = self.project_combo.currentData() if warehouse_type_code == "PROJECT" else None
        temp_controlled = self.temp_controlled_checkbox.isChecked()

        try:
            if self._editing_id is not None:
                locations_service.update_warehouse(
                    self._editing_id, company_id, code, name, self.is_active_checkbox.isChecked(),
                    warehouse_type_code=warehouse_type_code, project_detail_account_id=project_detail_account_id,
                    allow_negative_stock=self.allow_negative_checkbox.isChecked(),
                    is_temperature_controlled=temp_controlled,
                    min_temp_c=self.min_temp_field.value() if temp_controlled else None,
                    max_temp_c=self.max_temp_field.value() if temp_controlled else None,
                    address=self.address_field.text().strip() or None,
                    is_default=self.is_default_checkbox.isChecked(),
                )
            else:
                locations_service.create_warehouse(
                    company_id, code, name, warehouse_type_code=warehouse_type_code,
                    project_detail_account_id=project_detail_account_id,
                    allow_negative_stock=self.allow_negative_checkbox.isChecked(),
                    is_temperature_controlled=temp_controlled,
                    min_temp_c=self.min_temp_field.value() if temp_controlled else None,
                    max_temp_c=self.max_temp_field.value() if temp_controlled else None,
                    address=self.address_field.text().strip() or None,
                    is_default=self.is_default_checkbox.isChecked(),
                )
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return

        self.refresh()

    def _delete(self) -> None:
        if self._editing_id is None:
            return
        confirm = QMessageBox.question(self, "حذفِ انبار", "این انبار حذف شود؟", QMessageBox.Yes | QMessageBox.No)
        if confirm != QMessageBox.Yes:
            return
        company_id = self._company_id()
        try:
            locations_service.delete_warehouse(self._editing_id, company_id)
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self.refresh()

    def _add_bin(self) -> None:
        if self._editing_id is None:
            return
        dialog = _BinLocationDialog(self, self._bin_rows)
        if dialog.exec() != QDialog.Accepted:
            return
        code, name, parent_id, pickable = dialog.values()
        if not code:
            return
        try:
            locations_service.create_bin_location(
                self._editing_id, code, name or None, parent_bin_location_id=parent_id, is_pickable=pickable
            )
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self._refresh_bins()

    def _delete_bin(self) -> None:
        selected = self.bin_table.selectedItems()
        if not selected or self._editing_id is None:
            return
        bin_location_id = selected[0].data(Qt.UserRole)
        confirm = QMessageBox.question(self, "حذفِ مکان", "این مکانِ انبار حذف شود؟", QMessageBox.Yes | QMessageBox.No)
        if confirm != QMessageBox.Yes:
            return
        try:
            locations_service.delete_bin_location(bin_location_id, self._editing_id)
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self._refresh_bins()
