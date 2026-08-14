"""رده‌هایِ شغلی — هستهٔ منابع انسانی، فازِ ۱."""

from __future__ import annotations

import decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
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
from peecha.ui.screens.journal_entry import _AmountField
from peecha.ui.widgets import FieldGrid, FieldHelpMixin, FieldSpec, LayoutEditMixin, ZeroPaddedSpinBox

_COLUMNS = ["فعال", "حداکثرِ حقوقِ پایه", "حداقلِ حقوقِ پایه", "سطح", "عنوان", "کد"]


class JobGradesScreen(FieldHelpMixin, LayoutEditMixin, QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._rows: list[hr_service.JobGradeRow] = []
        self._editing_id: int | None = None

        outer = QHBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(16)
        outer.addWidget(self._build_list_panel(), stretch=3)
        outer.addWidget(self._build_form_panel(), stretch=2)

        self.set_field_help([
            (self.code_field, "کدِ یکتایِ این ردهٔ شغلی در سطحِ شرکت."),
            (self.title_field, "عنوانِ رده، مثلاً «کارشناس» یا «سرپرست»."),
            (self.level_field, "عددِ ترتیبِ رده — رده‌هایِ بالاتر عددِ بزرگ‌تر دارند."),
            (self.min_salary_field, "کفِ پیشنهادیِ حقوقِ پایه برایِ این رده — فقط هشدارِ کنترلی، نه محدودیتِ سخت."),
            (self.max_salary_field, "سقفِ پیشنهادیِ حقوقِ پایه برایِ این رده."),
        ])
        self.register_field_grids("hr_job_grades", [self.form_grid])

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

        title = QLabel("رده‌هایِ شغلی")
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

        self.form_title = QLabel("ردهٔ شغلیِ جدید")
        self.form_title.setObjectName("pageTitle")
        layout.addWidget(self.form_title)

        self.code_field = QLineEdit()
        self.title_field = QLineEdit()
        self.level_field = ZeroPaddedSpinBox()
        self.level_field.setRange(0, 99)
        self.min_salary_field = _AmountField()
        self.max_salary_field = _AmountField()
        self.is_active_checkbox = QCheckBox("فعال")
        self.is_active_checkbox.setChecked(True)

        self.form_grid = FieldGrid([
            FieldSpec("code", "کد", self.code_field, span=1),
            FieldSpec("title", "عنوان", self.title_field, span=2),
            FieldSpec("level", "سطح", self.level_field, span=1),
            FieldSpec("min_salary", "حداقلِ حقوقِ پایه", self.min_salary_field, span=1),
            FieldSpec("max_salary", "حداکثرِ حقوقِ پایه", self.max_salary_field, span=1),
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
        save_button.setFixedWidth(40)
        save_button.setToolTip("ذخیره")
        save_button.clicked.connect(self._save)
        buttons.addWidget(save_button)

        cancel_button = QPushButton("↩️")
        cancel_button.setObjectName("iconButton")
        cancel_button.setFixedWidth(34)
        cancel_button.setToolTip("انصراف")
        cancel_button.clicked.connect(self._reset_form)
        buttons.addWidget(cancel_button)

        self.delete_button = QPushButton("🗑️")
        self.delete_button.setObjectName("dangerIconButton")
        self.delete_button.setFixedWidth(34)
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
        self._rows = hr_service.list_job_grades(company_id)
        self.table.setRowCount(len(self._rows))
        for row_index, g in enumerate(self._rows):
            values = [
                "بله" if g.is_active else "خیر",
                numerals.format_amount(g.max_base_salary) if g.max_base_salary is not None else "—",
                numerals.format_amount(g.min_base_salary) if g.min_base_salary is not None else "—",
                numerals.to_persian_digits(str(g.grade_level)),
                g.title,
                g.code,
            ]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, g.job_grade_id)
                self.table.setItem(row_index, col_index, item)

    def _on_row_clicked(self, row: int, _column: int) -> None:
        job_grade_id = self.table.item(row, 0).data(Qt.UserRole)
        grade = next((r for r in self._rows if r.job_grade_id == job_grade_id), None)
        if grade is not None:
            self._load_into_form(grade)

    def _load_into_form(self, grade: hr_service.JobGradeRow) -> None:
        self._editing_id = grade.job_grade_id
        self.form_title.setText(f"ویرایشِ رده — {grade.title}")
        self.status_label.setText("")
        self.code_field.setText(grade.code)
        self.code_field.setEnabled(False)
        self.title_field.setText(grade.title)
        self.level_field.setValue(grade.grade_level)
        self.min_salary_field.setValue(float(grade.min_base_salary or 0))
        self.max_salary_field.setValue(float(grade.max_base_salary or 0))
        self.is_active_checkbox.setChecked(grade.is_active)
        self.delete_button.setVisible(True)

    def _reset_form(self) -> None:
        self._editing_id = None
        self.form_title.setText("ردهٔ شغلیِ جدید")
        self.status_label.setText("")
        self.code_field.clear()
        self.code_field.setEnabled(True)
        self.title_field.clear()
        self.level_field.setValue(0)
        self.min_salary_field.setValue(0)
        self.max_salary_field.setValue(0)
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
        min_salary = decimal.Decimal(str(self.min_salary_field.value())) or None
        max_salary = decimal.Decimal(str(self.max_salary_field.value())) or None
        if not min_salary:
            min_salary = None
        if not max_salary:
            max_salary = None

        try:
            if self._editing_id is not None:
                hr_service.update_job_grade(
                    self._editing_id, title, self.level_field.value(), min_salary, max_salary,
                    self.is_active_checkbox.isChecked(),
                )
            else:
                code = self.code_field.text().strip()
                if not code:
                    self.status_label.setText("کد را وارد کنید.")
                    return
                hr_service.create_job_grade(company_id, code, title, self.level_field.value(), min_salary, max_salary)
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return

        self.refresh()

    def _delete(self) -> None:
        if self._editing_id is None:
            return
        confirm = QMessageBox.question(
            self, "حذفِ ردهٔ شغلی", "این رده حذف شود؟", QMessageBox.Yes | QMessageBox.No
        )
        if confirm != QMessageBox.Yes:
            return
        try:
            hr_service.delete_job_grade(self._editing_id)
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self.refresh()
