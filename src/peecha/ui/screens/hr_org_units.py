"""واحدهایِ سازمانی — هستهٔ منابع انسانی، فازِ ۱."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
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
from peecha.services import hr as hr_service
from peecha.ui.widgets import FieldGrid, FieldHelpMixin, FieldSpec, LayoutEditMixin

_COLUMNS = ["فعال", "والد", "نام", "کد"]


class OrgUnitsScreen(FieldHelpMixin, LayoutEditMixin, QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._rows: list[hr_service.OrgUnitRow] = []
        self._editing_id: int | None = None

        outer = QHBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(16)
        outer.addWidget(self._build_list_panel(), stretch=3)
        outer.addWidget(self._build_form_panel(), stretch=2)

        self.set_field_help([
            (self.code_field, "کدِ یکتایِ این واحدِ سازمانی در سطحِ شرکت."),
            (self.name_field, "نامِ واحدِ سازمانی، مثلاً «فناوری اطلاعات»."),
            (self.parent_combo, "واحدِ سازمانیِ بالادست — اگر این واحد زیرمجموعهٔ واحدِ دیگری است."),
            (self.is_active_checkbox, "واحدِ غیرِفعال دیگر در انتخابِ واحدِ سازمانی برایِ پست/قرارداد نشان داده نمی‌شود."),
        ])
        self.register_field_grids("hr_org_units", [self.form_grid])

    def _wrap_scrollable(self, content: QWidget) -> QWidget:
        # طبقِ آیتمِ ۱ (اسکرول+فوترِ ثابت): این صفحه دو ستونِ مستقل
        # (فهرست/فرم) دارد، نه یک فرمِ یکپارچه با یک فوترِ واحد — هرکدام
        # جداگانه، هم‌الگو با treasury_checks.py، در کارتِ خودش اسکرول
        # می‌شود تا دکمه‌هایِ فرم هیچ‌وقت با کوچک‌شدنِ زیرپنجره گم نشوند.
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

    def _build_list_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        title = QLabel("واحدهایِ سازمانی")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.cellClicked.connect(self._on_row_clicked)
        layout.addWidget(self.table)
        return self._wrap_scrollable(panel)

    def _build_form_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        self.form_title = QLabel("واحدِ سازمانیِ جدید")
        self.form_title.setObjectName("pageTitle")
        layout.addWidget(self.form_title)

        self.code_field = QLineEdit()
        self.name_field = QLineEdit()
        self.parent_combo = QComboBox()
        self.is_active_checkbox = QCheckBox("فعال")
        self.is_active_checkbox.setChecked(True)

        self.form_grid = FieldGrid([
            FieldSpec("code", "کد", self.code_field, span=1),
            FieldSpec("name", "نام", self.name_field, span=2),
            FieldSpec("parent", "والد", self.parent_combo, span=3),
            FieldSpec("is_active", "", self.is_active_checkbox, span=3),
        ])
        layout.addWidget(self.form_grid)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusError")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        buttons = QHBoxLayout()
        save_button = QPushButton("💾")
        save_button.setObjectName("primaryIconButton")
        save_button.setFixedWidth(48)
        save_button.setToolTip("ذخیره")
        save_button.clicked.connect(self._save)
        buttons.addWidget(save_button)

        cancel_button = QPushButton("↩️")
        cancel_button.setObjectName("iconButton")
        cancel_button.setFixedWidth(44)
        cancel_button.setToolTip("انصراف")
        cancel_button.clicked.connect(self._reset_form)
        buttons.addWidget(cancel_button)

        self.delete_button = QPushButton("🗑️")
        self.delete_button.setObjectName("dangerIconButton")
        self.delete_button.setFixedWidth(44)
        self.delete_button.setToolTip("حذف")
        self.delete_button.clicked.connect(self._delete)
        self.delete_button.setVisible(False)
        buttons.addWidget(self.delete_button)

        layout.addLayout(buttons)
        layout.addStretch(1)
        return self._wrap_scrollable(panel)

    def _company_id(self) -> int | None:
        return app_session.current_company.company_id if app_session.current_company else None

    def refresh(self) -> None:
        self._reset_form()
        company_id = self._company_id()
        if company_id is None:
            return
        self._rows = hr_service.list_org_units(company_id)

        self.parent_combo.blockSignals(True)
        self.parent_combo.clear()
        self.parent_combo.addItem("(بدونِ والد)", None)
        for u in self._rows:
            self.parent_combo.addItem(f"{u.code} — {u.name}", u.org_unit_id)
        self.parent_combo.blockSignals(False)

        self.table.setRowCount(len(self._rows))
        for row_index, u in enumerate(self._rows):
            values = [
                "بله" if u.is_active else "خیر",
                u.parent_name or "—",
                u.name,
                u.code,
            ]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, u.org_unit_id)
                self.table.setItem(row_index, col_index, item)

    def _on_row_clicked(self, row: int, _column: int) -> None:
        org_unit_id = self.table.item(row, 0).data(Qt.UserRole)
        unit = next((r for r in self._rows if r.org_unit_id == org_unit_id), None)
        if unit is not None:
            self._load_into_form(unit)

    def _load_into_form(self, unit: hr_service.OrgUnitRow) -> None:
        self._editing_id = unit.org_unit_id
        self.form_title.setText(f"ویرایشِ واحد — {unit.name}")
        self.status_label.setText("")
        self.code_field.setText(unit.code)
        self.code_field.setEnabled(False)
        self.name_field.setText(unit.name)
        index = self.parent_combo.findData(unit.parent_org_unit_id)
        self.parent_combo.setCurrentIndex(index if index >= 0 else 0)
        self.is_active_checkbox.setChecked(unit.is_active)
        self.delete_button.setVisible(True)

    def _reset_form(self) -> None:
        self._editing_id = None
        self.form_title.setText("واحدِ سازمانیِ جدید")
        self.status_label.setText("")
        self.code_field.clear()
        self.code_field.setEnabled(True)
        self.name_field.clear()
        self.parent_combo.setCurrentIndex(0)
        self.is_active_checkbox.setChecked(True)
        self.delete_button.setVisible(False)
        self.table.clearSelection()

    def _save(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        name = self.name_field.text().strip()
        if not name:
            self.status_label.setText("نام را وارد کنید.")
            return
        parent_id = self.parent_combo.currentData()

        try:
            if self._editing_id is not None:
                hr_service.update_org_unit(
                    self._editing_id, name, parent_id, None, self.is_active_checkbox.isChecked()
                )
            else:
                code = self.code_field.text().strip()
                if not code:
                    self.status_label.setText("کد را وارد کنید.")
                    return
                hr_service.create_org_unit(company_id, code, name, parent_id, None)
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return

        self.refresh()

    def _delete(self) -> None:
        if self._editing_id is None:
            return
        confirm = QMessageBox.question(
            self, "حذفِ واحدِ سازمانی", "این واحد حذف شود؟", QMessageBox.Yes | QMessageBox.No
        )
        if confirm != QMessageBox.Yes:
            return
        try:
            hr_service.delete_org_unit(self._editing_id)
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self.refresh()
