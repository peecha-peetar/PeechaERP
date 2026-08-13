"""پست‌هایِ سازمانی — هستهٔ منابع انسانی، فازِ ۱."""

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

from peecha import numerals
from peecha import session as app_session
from peecha.services import hr as hr_service
from peecha.ui.widgets import FieldHelpMixin, ZeroPaddedSpinBox

_COLUMNS = ["فعال", "ظرفیت", "ردهٔ شغلی", "واحدِ سازمانی", "عنوان", "کد"]


class PositionsScreen(FieldHelpMixin, QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._rows: list[hr_service.PositionRow] = []
        self._org_units: list[hr_service.OrgUnitRow] = []
        self._job_grades: list[hr_service.JobGradeRow] = []
        self._editing_id: int | None = None

        outer = QHBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(16)
        outer.addWidget(self._build_list_panel(), stretch=3)
        outer.addWidget(self._build_form_panel(), stretch=2)

        self.set_field_help([
            (self.code_field, "کدِ یکتایِ این پست در سطحِ شرکت."),
            (self.title_field, "عنوانِ پست، مثلاً «برنامه‌نویس» یا «حسابدار»."),
            (self.org_unit_combo, "واحدِ سازمانی‌ای که این پست به آن تعلق دارد."),
            (self.job_grade_combo, "ردهٔ شغلیِ این پست — اختیاری."),
            (self.capacity_field, "تعدادِ نفراتی که هم‌زمان می‌توانند این پست را داشته باشند."),
        ])

    def _wrap_scrollable(self, content: QWidget) -> QWidget:
        # طبقِ آیتمِ ۱ (اسکرول+فوترِ ثابت): دو ستونِ مستقل (فهرست/فرم)،
        # نه یک فرمِ یکپارچه با یک فوترِ واحد — هرکدام جداگانه، هم‌الگو
        # با treasury_checks.py، در کارتِ خودش اسکرول می‌شود.
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

        title = QLabel("پست‌هایِ سازمانی")
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
        return self._wrap_scrollable(panel)

    def _build_form_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        self.form_title = QLabel("پستِ جدید")
        self.form_title.setObjectName("pageTitle")
        layout.addWidget(self.form_title)

        layout.addWidget(QLabel("کد"))
        self.code_field = QLineEdit()
        layout.addWidget(self.code_field)

        layout.addWidget(QLabel("عنوان"))
        self.title_field = QLineEdit()
        layout.addWidget(self.title_field)

        layout.addWidget(QLabel("واحدِ سازمانی"))
        self.org_unit_combo = QComboBox()
        layout.addWidget(self.org_unit_combo)

        layout.addWidget(QLabel("ردهٔ شغلی"))
        self.job_grade_combo = QComboBox()
        layout.addWidget(self.job_grade_combo)

        layout.addWidget(QLabel("ظرفیت"))
        self.capacity_field = ZeroPaddedSpinBox()
        self.capacity_field.setRange(1, 999)
        self.capacity_field.setValue(1)
        layout.addWidget(self.capacity_field)

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
        return self._wrap_scrollable(panel)

    def _company_id(self) -> int | None:
        return app_session.current_company.company_id if app_session.current_company else None

    def refresh(self) -> None:
        self._reset_form()
        company_id = self._company_id()
        if company_id is None:
            return
        self._org_units = hr_service.list_org_units(company_id)
        self._job_grades = hr_service.list_job_grades(company_id)
        self._rows = hr_service.list_positions(company_id)

        self.org_unit_combo.blockSignals(True)
        self.org_unit_combo.clear()
        for u in self._org_units:
            self.org_unit_combo.addItem(f"{u.code} — {u.name}", u.org_unit_id)
        self.org_unit_combo.blockSignals(False)

        self.job_grade_combo.blockSignals(True)
        self.job_grade_combo.clear()
        self.job_grade_combo.addItem("(بدون رده)", None)
        for g in self._job_grades:
            self.job_grade_combo.addItem(f"{g.code} — {g.title}", g.job_grade_id)
        self.job_grade_combo.blockSignals(False)

        self.table.setRowCount(len(self._rows))
        for row_index, p in enumerate(self._rows):
            values = [
                "بله" if p.is_active else "خیر",
                numerals.to_persian_digits(str(p.capacity)),
                p.job_grade_title or "—",
                p.org_unit_name,
                p.title,
                p.code,
            ]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, p.position_id)
                self.table.setItem(row_index, col_index, item)

    def _on_row_clicked(self, row: int, _column: int) -> None:
        position_id = self.table.item(row, 0).data(Qt.UserRole)
        position = next((r for r in self._rows if r.position_id == position_id), None)
        if position is not None:
            self._load_into_form(position)

    def _load_into_form(self, position: hr_service.PositionRow) -> None:
        self._editing_id = position.position_id
        self.form_title.setText(f"ویرایشِ پست — {position.title}")
        self.status_label.setText("")
        self.code_field.setText(position.code)
        self.code_field.setEnabled(False)
        self.title_field.setText(position.title)
        index = self.org_unit_combo.findData(position.org_unit_id)
        self.org_unit_combo.setCurrentIndex(index if index >= 0 else 0)
        index = self.job_grade_combo.findData(position.job_grade_id)
        self.job_grade_combo.setCurrentIndex(index if index >= 0 else 0)
        self.capacity_field.setValue(position.capacity)
        self.is_active_checkbox.setChecked(position.is_active)
        self.delete_button.setVisible(True)

    def _reset_form(self) -> None:
        self._editing_id = None
        self.form_title.setText("پستِ جدید")
        self.status_label.setText("")
        self.code_field.clear()
        self.code_field.setEnabled(True)
        self.title_field.clear()
        self.org_unit_combo.setCurrentIndex(0)
        self.job_grade_combo.setCurrentIndex(0)
        self.capacity_field.setValue(1)
        self.is_active_checkbox.setChecked(True)
        self.delete_button.setVisible(False)
        self.table.clearSelection()

    def _save(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        title = self.title_field.text().strip()
        if not title:
            self.status_label.setText("عنوان را وارد کنید.")
            return
        org_unit_id = self.org_unit_combo.currentData()
        if org_unit_id is None:
            self.status_label.setText("واحدِ سازمانی را انتخاب کنید.")
            return
        job_grade_id = self.job_grade_combo.currentData()
        capacity = self.capacity_field.value()

        try:
            if self._editing_id is not None:
                hr_service.update_position(
                    self._editing_id, title, org_unit_id, job_grade_id, capacity, self.is_active_checkbox.isChecked()
                )
            else:
                code = self.code_field.text().strip()
                if not code:
                    self.status_label.setText("کد را وارد کنید.")
                    return
                hr_service.create_position(company_id, code, title, org_unit_id, job_grade_id, capacity)
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return

        self.refresh()

    def _delete(self) -> None:
        if self._editing_id is None:
            return
        confirm = QMessageBox.question(
            self, "حذفِ پست", "این پست حذف شود؟", QMessageBox.Yes | QMessageBox.No
        )
        if confirm != QMessageBox.Yes:
            return
        try:
            hr_service.delete_position(self._editing_id)
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self.refresh()
