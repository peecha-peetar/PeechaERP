"""فرمِ ورود و خروجِ کارکنان — ثبتِ دستیِ حضوروغیابِ روزانه + تاییدِ
ردیف‌ها + ایمپورتِ دسته‌ای از فایلِ اکسل/CSVِ دستگاهِ حضوروغیاب (چه با
یک الگویِ ذخیره‌شده برایِ شرکتِ سازندهٔ دستگاه — لود و تاییدِ خودکار،
چه با تناظرِ دستیِ یک‌بارهٔ ستون‌ها برایِ دستگاه/شرکتِ ناشناخته).

طبقِ گزارشِ صریحِ کاربر: تا این نسخه فقط «ثبتِ ساعاتِ اضافه‌کاری»
(payroll_overtime_entries.py) وجود داشت، نه ثبتِ واقعیِ ورود/خروجِ
روزانهٔ کارکنان."""

from __future__ import annotations

import datetime
import decimal

from PySide6.QtCore import QTime, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from peecha import numerals
from peecha import session as app_session
from peecha.services import hr as hr_service
from peecha.services import hr_attendance as attendance_service
from peecha.ui import theme
from peecha.ui.excel_import import ExcelColumnMappingDialog, read_excel_rows
from peecha.ui.widgets import FieldHelpMixin, JalaliDateEdit, wrap_scrollable, wrap_scrollable_with_footer

_RECORD_COLUMNS = ["وضعیت", "ساعتِ کارکرد", "خروج", "ورود", "تاریخ", "کارمند"]
_STATUS_LABELS = {"PENDING_APPROVAL": "درانتظارِ تایید", "APPROVED": "تاییدشده", "REJECTED": "ردشده"}

_IMPORT_TARGET_FIELDS = [
    ("employee_code", "کدِ پرسنلیِ کارمند", True),
    ("work_date", "تاریخ", True),
    ("clock_in", "ساعتِ ورود", False),
    ("clock_out", "ساعتِ خروج", False),
    ("worked_hours", "مجموعِ ساعتِ کارکرد", False),
]
_IMPORT_GUESS_KEYWORDS = {
    "employee_code": ["کدِ پرسنلی", "کد پرسنلی", "کد کارمند", "employee", "code"],
    "work_date": ["تاریخ", "date"],
    "clock_in": ["ورود", "in", "start"],
    "clock_out": ["خروج", "out", "end"],
    "worked_hours": ["ساعتِ کارکرد", "ساعت کارکرد", "مجموع", "hours", "total"],
}


def _company_id() -> int | None:
    return app_session.current_company.company_id if app_session.current_company else None


def _q_to_py_time(value: QTime) -> datetime.time:
    return datetime.time(value.hour(), value.minute())


class HrAttendanceEntriesScreen(FieldHelpMixin, QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._employees: list[hr_service.EmployeeRow] = []
        self._templates: list[attendance_service.AttendanceImportTemplateRow] = []
        self._records: list[attendance_service.AttendanceRecordRow] = []
        self._selected_attendance_id: int | None = None

        outer = QHBoxLayout(self)
        outer.setContentsMargins(20, 14, 20, 14)
        outer.setSpacing(16)
        outer.addWidget(self._build_form_panel(), stretch=2)
        outer.addWidget(self._build_records_panel(), stretch=3)

        self.set_field_help([
            (
                self.hours_field_hint,
                "یا ساعتِ ورود و خروج را وارد کنید، یا مستقیماً مجموعِ ساعتِ کارکردِ آن روز را.",
            ),
            (
                self.template_import_button,
                "یک الگویِ ذخیره‌شده برایِ دستگاهِ حضوروغیابِ خودتان انتخاب کنید، سپس فایلِ CSV/اکسلِ "
                "خروجیِ دستگاه را بدهید — همه‌یِ ردیف‌ها بدونِ نیاز به تناظرِ دستیِ ستون‌ها، لود و تایید می‌شوند.",
            ),
            (
                self.manual_import_button,
                "اگر دستگاهِ شما در الگوهایِ ذخیره‌شده نیست، فایل را انتخاب کنید و ستون‌هایش را دستی مشخص کنید — "
                "ردیف‌هایِ ایمپورت‌شده در این حالت درانتظارِ تایید می‌مانند.",
            ),
        ])

    def _build_form_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(10)

        title = QLabel("ثبتِ حضوروغیاب")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        layout.addWidget(QLabel("کارمند"))
        self.employee_combo = QComboBox()
        layout.addWidget(self.employee_combo)

        layout.addWidget(QLabel("تاریخ"))
        self.date_field = JalaliDateEdit()
        layout.addWidget(self.date_field)

        row = QHBoxLayout()
        in_col = QVBoxLayout()
        in_col.addWidget(QLabel("ساعتِ ورود"))
        self.clock_in_field = QTimeEdit()
        self.clock_in_field.setDisplayFormat("HH:mm")
        in_col.addWidget(self.clock_in_field)
        row.addLayout(in_col)
        out_col = QVBoxLayout()
        out_col.addWidget(QLabel("ساعتِ خروج"))
        self.clock_out_field = QTimeEdit()
        self.clock_out_field.setDisplayFormat("HH:mm")
        out_col.addWidget(self.clock_out_field)
        row.addLayout(out_col)
        layout.addLayout(row)

        self.use_manual_hours_checkbox_hint = QLabel("یا به‌جایِ ورود/خروج، فقط مجموعِ ساعتِ کارکرد:")
        layout.addWidget(self.use_manual_hours_checkbox_hint)
        self.worked_hours_field = QComboBox()
        self.worked_hours_field.setEditable(True)
        self.worked_hours_field.addItem("")
        layout.addWidget(self.worked_hours_field)
        self.hours_field_hint = self.worked_hours_field

        create_button = QPushButton("➕")
        create_button.setObjectName("primaryIconButton")
        create_button.setFixedWidth(48)
        create_button.setToolTip("ثبت")
        create_button.clicked.connect(self._create_record)
        layout.addWidget(create_button)

        self.form_status_label = QLabel("")
        self.form_status_label.setWordWrap(True)
        layout.addWidget(self.form_status_label)

        layout.addWidget(QLabel("—" * 10))

        layout.addWidget(QLabel("ایمپورتِ دسته‌ای با الگویِ ذخیره‌شده"))
        self.template_combo = QComboBox()
        layout.addWidget(self.template_combo)
        self.template_import_button = QPushButton("✅")
        self.template_import_button.setObjectName("iconButton")
        self.template_import_button.setFixedWidth(44)
        self.template_import_button.setToolTip("انتخابِ فایل و ایمپورت (لود و تاییدِ خودکار)")
        self.template_import_button.clicked.connect(self._on_import_with_template)
        layout.addWidget(self.template_import_button)

        self.manual_import_button = QPushButton("📥")
        self.manual_import_button.setObjectName("iconButton")
        self.manual_import_button.setFixedWidth(44)
        self.manual_import_button.setToolTip("ایمپورتِ دستی (بدونِ الگو — تناظرِ ستون‌ها)")
        self.manual_import_button.clicked.connect(self._on_import_manual)
        layout.addWidget(self.manual_import_button)

        layout.addStretch(1)
        return wrap_scrollable(panel)

    def _build_records_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(10)

        title = QLabel("رکوردهایِ حضوروغیاب")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        filters_row = QHBoxLayout()
        filters_row.addWidget(QLabel("از تاریخ"))
        self.filter_from_date = JalaliDateEdit()
        self.filter_from_date.setDate(datetime.date.today() - datetime.timedelta(days=30))
        self.filter_from_date.editingFinished.connect(self._refresh_records)
        filters_row.addWidget(self.filter_from_date)
        filters_row.addWidget(QLabel("تا تاریخ"))
        self.filter_to_date = JalaliDateEdit()
        self.filter_to_date.editingFinished.connect(self._refresh_records)
        filters_row.addWidget(self.filter_to_date)
        filters_row.addWidget(QLabel("کارمند"))
        self.employee_filter_combo = QComboBox()
        self.employee_filter_combo.currentIndexChanged.connect(lambda _i: self._refresh_records())
        filters_row.addWidget(self.employee_filter_combo)
        layout.addLayout(filters_row)

        self.records_table = QTableWidget(0, len(_RECORD_COLUMNS))
        self.records_table.setHorizontalHeaderLabels(_RECORD_COLUMNS)
        self.records_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.records_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.records_table.verticalHeader().setVisible(False)
        self.records_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        self.records_table.cellClicked.connect(self._on_record_clicked)
        layout.addWidget(self.records_table, stretch=1)

        self.records_status_label = QLabel("")
        self.records_status_label.setWordWrap(True)
        layout.addWidget(self.records_status_label)

        approve_button = QPushButton("✅")
        approve_button.setObjectName("primaryIconButton")
        approve_button.setFixedWidth(48)
        approve_button.setToolTip("تایید")
        approve_button.clicked.connect(lambda: self._set_selected_status("APPROVED"))

        reject_button = QPushButton("❌")
        reject_button.setObjectName("iconButton")
        reject_button.setFixedWidth(44)
        reject_button.setToolTip("رد")
        reject_button.clicked.connect(lambda: self._set_selected_status("REJECTED"))

        delete_button = QPushButton("🗑️")
        delete_button.setObjectName("dangerIconButton")
        delete_button.setFixedWidth(44)
        delete_button.setToolTip("حذف")
        delete_button.clicked.connect(self._delete_selected)

        approve_all_button = QPushButton("✅✅")
        approve_all_button.setObjectName("iconButton")
        approve_all_button.setFixedWidth(44)
        approve_all_button.setToolTip("تاییدِ همه‌یِ درانتظار")
        approve_all_button.clicked.connect(self._approve_all_pending)

        return wrap_scrollable_with_footer(
            panel, [approve_button, reject_button, delete_button, approve_all_button]
        )

    def refresh(self) -> None:
        company_id = _company_id()
        if company_id is None:
            return
        self._employees = hr_service.list_employees(company_id)
        self._templates = attendance_service.list_attendance_import_templates(company_id)

        self.employee_combo.clear()
        self.employee_filter_combo.clear()
        self.employee_filter_combo.addItem("— همه —", None)
        for e in self._employees:
            label = f"{e.employee_code} — {e.full_name}"
            self.employee_combo.addItem(label, e.employee_id)
            self.employee_filter_combo.addItem(label, e.employee_id)

        self.template_combo.clear()
        self.template_combo.addItem("— بدونِ الگو —", None)
        for t in self._templates:
            self.template_combo.addItem(t.name, t.template_id)

        self._refresh_records()

    def _refresh_records(self) -> None:
        company_id = _company_id()
        if company_id is None:
            return
        self._records = []
        self.records_table.setRowCount(0)
        self._selected_attendance_id = None
        start_date = self.filter_from_date.date()
        end_date = self.filter_to_date.date()
        employee_id = self.employee_filter_combo.currentData()
        self._records = attendance_service.list_attendance_records(company_id, start_date, end_date, employee_id)
        self.records_table.setRowCount(len(self._records))
        for row_index, r in enumerate(self._records):
            values = [
                _STATUS_LABELS.get(r.status, r.status),
                numerals.to_persian_digits(str(r.worked_hours)) if r.worked_hours is not None else "—",
                numerals.to_persian_digits(r.clock_out.strftime("%H:%M")) if r.clock_out else "—",
                numerals.to_persian_digits(r.clock_in.strftime("%H:%M")) if r.clock_in else "—",
                numerals.format_jalali_date(r.work_date),
                f"{r.employee_code} — {r.employee_name}",
            ]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, r.attendance_id)
                self.records_table.setItem(row_index, col_index, item)

    def _on_record_clicked(self, row: int, _column: int) -> None:
        self._selected_attendance_id = self.records_table.item(row, 0).data(Qt.UserRole)

    def _create_record(self) -> None:
        company_id = _company_id()
        employee_id = self.employee_combo.currentData()
        if company_id is None or employee_id is None:
            theme.set_status_label(self.form_status_label, "کارمند را انتخاب کنید.", ok=False)
            return
        work_date = self.date_field.date()
        hours_text = numerals.to_ascii_digits(self.worked_hours_field.currentText().strip())
        worked_hours = None
        clock_in = None
        clock_out = None
        if hours_text:
            try:
                worked_hours = decimal.Decimal(hours_text)
            except decimal.InvalidOperation:
                theme.set_status_label(self.form_status_label, "مجموعِ ساعتِ کارکرد را به‌صورتِ عدد وارد کنید.", ok=False)
                return
        else:
            clock_in = _q_to_py_time(self.clock_in_field.time())
            clock_out = _q_to_py_time(self.clock_out_field.time())
        try:
            attendance_service.create_attendance_record(
                company_id, employee_id, work_date, clock_in=clock_in, clock_out=clock_out, worked_hours=worked_hours
            )
        except ValueError as exc:
            theme.set_status_label(self.form_status_label, str(exc), ok=False)
            return
        theme.set_status_label(self.form_status_label, "ثبت شد.", ok=True)
        self.worked_hours_field.setCurrentText("")
        # طبقِ الگویِ payroll_overtime_entries.py: بعدِ ثبت، فیلترهایِ فهرست
        # باید ردیفِ تازه‌ثبت‌شده را نشان دهند، حتی اگر تاریخش خارجِ بازه‌یِ
        # پیش‌فرضِ فهرست (۳۰ روزِ اخیر) باشد.
        if work_date < self.filter_from_date.date():
            self.filter_from_date.setDate(work_date)
        if work_date > self.filter_to_date.date():
            self.filter_to_date.setDate(work_date)
        index = self.employee_filter_combo.findData(employee_id)
        if index >= 0:
            self.employee_filter_combo.setCurrentIndex(index)
        self._refresh_records()

    def _set_selected_status(self, status: str) -> None:
        if self._selected_attendance_id is None:
            QMessageBox.information(self, "تغییرِ وضعیت", "یک ردیف را از فهرست انتخاب کنید.")
            return
        try:
            attendance_service.set_attendance_status(self._selected_attendance_id, status)
        except ValueError as exc:
            theme.set_status_label(self.records_status_label, str(exc), ok=False)
            return
        theme.set_status_label(self.records_status_label, "وضعیت به‌روزرسانی شد.", ok=True)
        self._refresh_records()

    def _delete_selected(self) -> None:
        if self._selected_attendance_id is None:
            QMessageBox.information(self, "حذف", "یک ردیف را از فهرست انتخاب کنید.")
            return
        confirm = QMessageBox.question(self, "حذفِ ردیف", "این رکوردِ حضوروغیاب حذف شود؟", QMessageBox.Yes | QMessageBox.No)
        if confirm != QMessageBox.Yes:
            return
        attendance_service.delete_attendance_record(self._selected_attendance_id)
        self._refresh_records()

    def _approve_all_pending(self) -> None:
        pending_ids = [r.attendance_id for r in self._records if r.status == "PENDING_APPROVAL"]
        if not pending_ids:
            theme.set_status_label(self.records_status_label, "ردیفِ درانتظارِ تاییدی در فهرستِ فعلی نیست.", ok=False)
            return
        attendance_service.bulk_set_attendance_status(pending_ids, "APPROVED")
        theme.set_status_label(self.records_status_label, f"{len(pending_ids)} ردیف تایید شد.", ok=True)
        self._refresh_records()

    def _on_import_with_template(self) -> None:
        company_id = _company_id()
        template_id = self.template_combo.currentData()
        if company_id is None:
            return
        if template_id is None:
            QMessageBox.information(self, "الگو", "یک الگو انتخاب کنید یا از «ایمپورتِ دستی» استفاده کنید.")
            return
        template = next((t for t in self._templates if t.template_id == template_id), None)
        if template is None:
            return
        path, _filter = QFileDialog.getOpenFileName(
            self, "انتخابِ فایلِ حضوروغیابِ دستگاه", "", "Excel/CSV Files (*.xlsx *.csv)"
        )
        if not path:
            return
        rows = read_excel_rows(self, path)
        if rows is None:
            return
        data_rows = rows[1:] if template.has_header_row else rows
        created, errors = attendance_service.import_attendance_rows(
            company_id, data_rows, template.column_mapping, template.date_format, template.time_format, auto_approve=True
        )
        if errors:
            QMessageBox.warning(self, "خطاهایِ ایمپورت", "\n".join(errors[:20]))
        theme.set_status_label(self.form_status_label, f"{created} ردیف لود و تایید شد.", ok=created > 0)
        self.refresh()

    def _on_import_manual(self) -> None:
        company_id = _company_id()
        if company_id is None:
            return
        path, _filter = QFileDialog.getOpenFileName(
            self, "انتخابِ فایلِ حضوروغیاب", "", "Excel/CSV Files (*.xlsx *.csv)"
        )
        if not path:
            return
        rows = read_excel_rows(self, path)
        if rows is None:
            return
        dialog = ExcelColumnMappingDialog(
            _IMPORT_TARGET_FIELDS, _IMPORT_GUESS_KEYWORDS, rows[0], self,
            title="ایمپورتِ حضوروغیاب از فایل — تناظرِ ستون‌ها",
        )
        if dialog.exec() != QDialog.Accepted:
            return
        mapping = dialog.mapping()
        if mapping.get("worked_hours") is None and (mapping.get("clock_in") is None or mapping.get("clock_out") is None):
            QMessageBox.warning(
                self, "ناقص", "یا «مجموعِ ساعتِ کارکرد» را مشخص کنید، یا هر دویِ «ساعتِ ورود» و «ساعتِ خروج» را."
            )
            return
        data_rows = rows[1:] if dialog.skip_header_row() else rows
        created, errors = attendance_service.import_attendance_rows(
            company_id, data_rows, mapping, "%Y-%m-%d", "%H:%M", auto_approve=False
        )
        if errors:
            QMessageBox.warning(self, "خطاهایِ ایمپورت", "\n".join(errors[:20]))
        theme.set_status_label(
            self.form_status_label, f"{created} ردیف واردِ لیستِ درانتظارِ تایید شد.", ok=created > 0
        )
        self.refresh()
