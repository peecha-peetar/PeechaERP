"""فرمِ خلاصهٔ کارکردِ پرسنل — جمعِ روزهایِ حاضر و مجموعِ ساعتِ کارکردِ
هر کارمند در یک دوره، بر پایهٔ رکوردهایِ تاییدشدهٔ حضوروغیاب
(hr.attendance_records). طبقِ گزارشِ صریحِ کاربر: تا این نسخه چنین
گزارشی وجود نداشت."""

from __future__ import annotations

import datetime
import decimal

from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from peecha import numerals, session
from peecha.services import hr as hr_service
from peecha.services import hr_attendance as attendance_service
from peecha.services import payroll as payroll_service
from peecha.ui import report_export
from peecha.ui.widgets import FieldHelpMixin, wrap_scrollable_with_footer

_COLUMNS = ["مجموعِ ساعتِ کارکرد", "روزهایِ حاضر", "کارمند", "کد"]
_REPORT_TITLE = "خلاصهٔ کارکردِ پرسنل"


class HrAttendanceSummaryScreen(FieldHelpMixin, QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._rows: list[attendance_service.AttendanceSummaryRow] = []
        self._periods: list[payroll_service.PeriodRow] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        title = QLabel(_REPORT_TITLE)
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        hint = QLabel("فقط رکوردهایِ حضوروغیابِ تاییدشده در این خلاصه محاسبه می‌شوند.")
        hint.setObjectName("sectionHint")
        layout.addWidget(hint)

        filters_row = QHBoxLayout()
        filters_row.addWidget(QLabel("دوره"))
        self.period_combo = QComboBox()
        self.period_combo.currentIndexChanged.connect(lambda _i: self.refresh())
        filters_row.addWidget(self.period_combo)
        filters_row.addWidget(QLabel("کارمند"))
        self.employee_filter_combo = QComboBox()
        self.employee_filter_combo.currentIndexChanged.connect(lambda _i: self.refresh())
        filters_row.addWidget(self.employee_filter_combo)
        filters_row.addStretch(1)
        layout.addLayout(filters_row)

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        layout.addWidget(self.table, stretch=1)

        self.summary_label = QLabel("")
        self.summary_label.setObjectName("sectionHint")
        layout.addWidget(self.summary_label)

        print_button = QPushButton("🖨 چاپ")
        print_button.setObjectName("flatButton")
        print_button.clicked.connect(self._on_print)
        pdf_button = QPushButton("📄 خروجیِ PDF")
        pdf_button.setObjectName("flatButton")
        pdf_button.clicked.connect(self._on_export_pdf)
        excel_button = QPushButton("📊 خروجیِ Excel")
        excel_button.setObjectName("flatButton")
        excel_button.clicked.connect(self._on_export_excel)

        outer.addWidget(wrap_scrollable_with_footer(panel, [print_button, pdf_button, excel_button]))

        self.set_field_help([
            (self.period_combo, "دوره‌ای که خلاصهٔ کارکرد برایش محاسبه شود."),
            (self.employee_filter_combo, "محدودکردنِ خلاصه به یک کارمندِ مشخص؛ «— همه —» یعنی همه‌یِ کارکنان."),
        ])

    def _company_id(self) -> int | None:
        return session.current_company.company_id if session.current_company else None

    def refresh(self) -> None:
        company_id = self._company_id()
        self._rows = []
        self.table.setRowCount(0)
        self.summary_label.setText("")
        if company_id is None:
            return

        selected_period_id = self.period_combo.currentData()
        selected_employee_id = self.employee_filter_combo.currentData()

        self._periods = payroll_service.list_periods(company_id)
        self.period_combo.blockSignals(True)
        self.period_combo.clear()
        for p in self._periods:
            label = numerals.to_persian_digits(f"{p.jalali_year}/{p.jalali_month:02d}")
            self.period_combo.addItem(label, p.period_id)
        index = self.period_combo.findData(selected_period_id)
        self.period_combo.setCurrentIndex(index if index >= 0 else 0)
        self.period_combo.blockSignals(False)

        employees = hr_service.list_employees(company_id)
        self.employee_filter_combo.blockSignals(True)
        self.employee_filter_combo.clear()
        self.employee_filter_combo.addItem("— همه —", None)
        for e in employees:
            self.employee_filter_combo.addItem(f"{e.employee_code} — {e.full_name}", e.employee_id)
        index = self.employee_filter_combo.findData(selected_employee_id)
        self.employee_filter_combo.setCurrentIndex(index if index >= 0 else 0)
        self.employee_filter_combo.blockSignals(False)

        period_id = self.period_combo.currentData()
        period = next((p for p in self._periods if p.period_id == period_id), None)
        if period is None:
            return
        employee_id = self.employee_filter_combo.currentData()

        self._rows = attendance_service.compute_attendance_summary(
            company_id, period.period_start_date, period.period_end_date, employee_id
        )
        self.table.setRowCount(len(self._rows))
        total_hours = decimal.Decimal(0)
        total_days = 0
        for row_index, r in enumerate(self._rows):
            total_hours += r.total_hours
            total_days += r.present_days
            values = [
                numerals.to_persian_digits(str(r.total_hours)),
                numerals.to_persian_digits(str(r.present_days)),
                r.employee_name,
                r.employee_code,
            ]
            for col_index, value in enumerate(values):
                self.table.setItem(row_index, col_index, QTableWidgetItem(value))
        self.summary_label.setText(
            f"{numerals.to_persian_digits(str(len(self._rows)))} کارمند — "
            f"جمعِ روزهایِ حاضر: {numerals.to_persian_digits(str(total_days))} — "
            f"جمعِ ساعتِ کارکرد: {numerals.to_persian_digits(str(total_hours))}"
        )

    def _export_rows(self) -> tuple[list[str], list[list], list]:
        table_rows = [
            [numerals.to_persian_digits(str(r.total_hours)), numerals.to_persian_digits(str(r.present_days)), r.employee_name, r.employee_code]
            for r in self._rows
        ]
        total_hours = sum((r.total_hours for r in self._rows), decimal.Decimal(0))
        total_days = sum(r.present_days for r in self._rows)
        footer = [numerals.to_persian_digits(str(total_hours)), numerals.to_persian_digits(str(total_days)), "جمعِ کل", ""]
        return list(_COLUMNS), table_rows, footer

    def _export_kwargs(self) -> dict:
        period = next((p for p in self._periods if p.period_id == self.period_combo.currentData()), None)
        filters = [("دوره", self.period_combo.currentText())]
        if self.employee_filter_combo.currentData() is not None:
            filters.append(("کارمند", self.employee_filter_combo.currentText()))
        return {
            "company_name": session.current_company.display_name if session.current_company else "",
            "report_date": numerals.format_jalali_date(datetime.date.today()),
            "filters": filters,
        }

    def _on_print(self) -> None:
        headers, rows, footer = self._export_rows()
        report_export.print_report(self, _REPORT_TITLE, headers, rows, footer, **self._export_kwargs())

    def _on_export_pdf(self) -> None:
        headers, rows, footer = self._export_rows()
        report_export.export_report_pdf(self, _REPORT_TITLE, headers, rows, footer, **self._export_kwargs())

    def _on_export_excel(self) -> None:
        headers, rows, footer = self._export_rows()
        report_export.export_report_excel(self, _REPORT_TITLE, headers, rows, footer, **self._export_kwargs())
