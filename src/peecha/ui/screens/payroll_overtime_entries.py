"""ثبت/تاییدِ ساعاتِ اضافه‌کاری (فصلِ ۱۲) + ایمپورتِ فایلِ اکسل/CSVِ
خروجیِ دستگاهِ حضوروغیاب.

طبقِ گزارشِ کاربر: `services/payroll_overtime.py` و موتورِ محاسبه از
قبل کامل بودند، ولی هیچ صفحه‌ای این سرویس را صدا نمی‌زد — یعنی هیچ‌وقت
یک ردیفِ اضافه‌کاریِ واقعی ساخته/تاییده نمی‌شد و مبلغِ اضافه‌کاری در فیش
همیشه صفر بود. این صفحه همان حلقه‌یِ گمشده است: ثبتِ دستیِ یک ردیف،
تایید/ردِ ردیف‌هایِ درانتظار، و ایمپورتِ دسته‌ای از فایلِ اکسل/CSVِ خروجیِ
دستگاه (طبقِ تاییدِ صریحِ کاربر: فقط ایمپورتِ فایل، نه اتصالِ مستقیم به
سخت‌افزار). قوانینِ اضافه‌کاری (ضریب/حالتِ ترکیب) در تبِ «قوانینِ
اضافه‌کاری»یِ تنظیماتِ حقوق‌ودستمزد مدیریت می‌شوند (payroll_settings.py)،
نه این‌جا — چون آن‌ها تنظیماتی‌اند، این‌جا فقط تراکنشی."""

from __future__ import annotations

import decimal

from PySide6.QtCore import Qt
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
    QVBoxLayout,
    QWidget,
)

from peecha import numerals
from peecha import session as app_session
from peecha.services import hr as hr_service
from peecha.services import payroll as payroll_service
from peecha.services import payroll_overtime as overtime_service
from peecha.ui import theme
from peecha.ui.excel_import import ExcelColumnMappingDialog, read_excel_rows
from peecha.ui.widgets import (
    FieldHelpMixin,
    PersianDigitLineEdit,
    wrap_scrollable,
    wrap_scrollable_with_footer,
)

_ENTRY_COLUMNS = ["وضعیت", "ساعت", "نوعِ اضافه‌کاری", "کارمند"]
_ENTRY_STATUS_LABELS = {"PENDING_APPROVAL": "درانتظارِ تایید", "APPROVED": "تاییدشده", "REJECTED": "ردشده"}
_RULE_CODE_LABELS = {
    "OVERTIME": "اضافه‌کاریِ عادی",
    "NIGHT_SHIFT": "شب‌کاری",
    "HOLIDAY_WORK": "تعطیل‌کاری",
    "FRIDAY_WORK": "جمعه‌کاری",
    "ROTATING_SHIFT_BONUS": "فوق‌العادهٔ شیفتِ گردشی",
}

_IMPORT_TARGET_FIELDS = [
    ("employee_code", "کدِ پرسنلیِ کارمند", True),
    ("period", "دوره (مثلاً ۱۴۰۳/۰۵)", True),
    ("rule_code", "نوعِ اضافه‌کاری (کد، مثلاً OVERTIME)", True),
    ("hours", "ساعت", True),
]
_IMPORT_GUESS_KEYWORDS = {
    "employee_code": ["کدِ پرسنلی", "کد پرسنلی", "کد کارمند", "employee"],
    "period": ["دوره", "ماه", "period"],
    "rule_code": ["نوع", "قانون", "rule"],
    "hours": ["ساعت", "hours"],
}


def _company_id() -> int | None:
    return app_session.current_company.company_id if app_session.current_company else None


class PayrollOvertimeEntriesScreen(FieldHelpMixin, QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._employees: list[hr_service.EmployeeRow] = []
        self._periods: list[payroll_service.PeriodRow] = []
        self._rules: list[overtime_service.OvertimeRuleRow] = []
        self._entries: list[overtime_service.OvertimeEntryRow] = []
        self._selected_entry_id: int | None = None

        outer = QHBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(16)
        outer.addWidget(self._build_form_panel(), stretch=2)
        outer.addWidget(self._build_entries_panel(), stretch=3)

        self.set_field_help([
            (self.hours_field, "تعدادِ ساعاتِ این نوعِ اضافه‌کاری برایِ این کارمند در این دوره."),
            (
                self.import_button,
                "فایلِ اکسل/CSVِ خروجیِ دستگاهِ حضوروغیاب را انتخاب کنید — با ستون‌هایِ کدِ پرسنلی، "
                "دوره، نوعِ اضافه‌کاری، و ساعت. ردیف‌هایِ ایمپورت‌شده هم مثلِ ثبتِ دستی، درانتظارِ تایید می‌مانند.",
            ),
        ])

    def _build_form_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        title = QLabel("ثبتِ اضافه‌کاری")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        layout.addWidget(QLabel("کارمند"))
        self.employee_combo = QComboBox()
        layout.addWidget(self.employee_combo)

        layout.addWidget(QLabel("دوره"))
        self.period_combo = QComboBox()
        layout.addWidget(self.period_combo)

        layout.addWidget(QLabel("نوعِ اضافه‌کاری"))
        self.rule_combo = QComboBox()
        layout.addWidget(self.rule_combo)

        layout.addWidget(QLabel("ساعت"))
        self.hours_field = PersianDigitLineEdit()
        layout.addWidget(self.hours_field)

        self.form_status_label = QLabel("")
        self.form_status_label.setWordWrap(True)
        layout.addWidget(self.form_status_label)

        create_button = QPushButton("➕")
        create_button.setObjectName("primaryIconButton")
        create_button.setFixedWidth(48)
        create_button.setToolTip("ثبت")
        create_button.clicked.connect(self._create_entry)

        self.import_button = QPushButton("📥")
        self.import_button.setObjectName("iconButton")
        self.import_button.setFixedWidth(44)
        self.import_button.setToolTip("ایمپورت از اکسل")
        self.import_button.clicked.connect(self._on_import_excel)

        return wrap_scrollable_with_footer(panel, [create_button, self.import_button])

    def _build_entries_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        title = QLabel("ردیف‌هایِ اضافه‌کاری")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        filters_row = QHBoxLayout()
        filters_row.addWidget(QLabel("دوره"))
        self.period_filter_combo = QComboBox()
        self.period_filter_combo.currentIndexChanged.connect(self._on_filter_changed)
        filters_row.addWidget(self.period_filter_combo)
        filters_row.addWidget(QLabel("کارمند"))
        self.employee_filter_combo = QComboBox()
        self.employee_filter_combo.currentIndexChanged.connect(self._on_filter_changed)
        filters_row.addWidget(self.employee_filter_combo)
        layout.addLayout(filters_row)

        self.entries_table = QTableWidget(0, len(_ENTRY_COLUMNS))
        self.entries_table.setHorizontalHeaderLabels(_ENTRY_COLUMNS)
        self.entries_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.entries_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.entries_table.verticalHeader().setVisible(False)
        self.entries_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.entries_table.cellClicked.connect(self._on_entry_clicked)
        layout.addWidget(self.entries_table, stretch=1)

        self.entries_status_label = QLabel("")
        self.entries_status_label.setWordWrap(True)
        layout.addWidget(self.entries_status_label)

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

        return wrap_scrollable_with_footer(panel, [approve_button, reject_button, delete_button])

    def refresh(self) -> None:
        company_id = _company_id()
        if company_id is None:
            return
        self._employees = hr_service.list_employees(company_id)
        self._periods = payroll_service.list_periods(company_id)
        self._rules = overtime_service.list_overtime_rules(company_id)

        self.employee_combo.clear()
        self.employee_filter_combo.clear()
        self.employee_filter_combo.addItem("— همه —", None)
        for e in self._employees:
            label = f"{e.employee_code} — {e.full_name}"
            self.employee_combo.addItem(label, e.employee_id)
            self.employee_filter_combo.addItem(label, e.employee_id)

        self.period_combo.clear()
        self.period_filter_combo.blockSignals(True)
        self.period_filter_combo.clear()
        for p in self._periods:
            label = numerals.to_persian_digits(f"{p.jalali_year}/{p.jalali_month:02d}")
            self.period_combo.addItem(label, p.period_id)
            self.period_filter_combo.addItem(label, p.period_id)
        self.period_filter_combo.blockSignals(False)

        self.rule_combo.clear()
        for r in self._rules:
            self.rule_combo.addItem(_RULE_CODE_LABELS.get(r.code, r.code), r.overtime_rule_id)

        self._refresh_entries()

    def _on_filter_changed(self, _index: int) -> None:
        self._refresh_entries()

    def _refresh_entries(self) -> None:
        self._entries = []
        self.entries_table.setRowCount(0)
        self._selected_entry_id = None
        period_id = self.period_filter_combo.currentData()
        if period_id is None:
            return
        employee_id = self.employee_filter_combo.currentData()
        self._entries = overtime_service.list_overtime_entries(period_id, employee_id)
        employees_by_id = {e.employee_id: e.full_name for e in self._employees}
        self.entries_table.setRowCount(len(self._entries))
        for row_index, entry in enumerate(self._entries):
            values = [
                _ENTRY_STATUS_LABELS.get(entry.status, entry.status),
                numerals.to_persian_digits(str(entry.hours)),
                _RULE_CODE_LABELS.get(entry.rule_code, entry.rule_code),
                employees_by_id.get(entry.employee_id, "—"),
            ]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, entry.overtime_entry_id)
                self.entries_table.setItem(row_index, col_index, item)

    def _on_entry_clicked(self, row: int, _column: int) -> None:
        self._selected_entry_id = self.entries_table.item(row, 0).data(Qt.UserRole)

    def _create_entry(self) -> None:
        employee_id = self.employee_combo.currentData()
        period_id = self.period_combo.currentData()
        rule_id = self.rule_combo.currentData()
        if employee_id is None or period_id is None or rule_id is None:
            theme.set_status_label(self.form_status_label, "کارمند، دوره، و نوعِ اضافه‌کاری را انتخاب کنید.", ok=False)
            return
        try:
            hours = decimal.Decimal(numerals.to_ascii_digits(self.hours_field.text()) or "0")
        except decimal.InvalidOperation:
            theme.set_status_label(self.form_status_label, "ساعت را به‌صورتِ عدد وارد کنید.", ok=False)
            return
        try:
            overtime_service.create_overtime_entry(employee_id, period_id, rule_id, hours)
        except ValueError as exc:
            theme.set_status_label(self.form_status_label, str(exc), ok=False)
            return
        theme.set_status_label(self.form_status_label, "ثبت شد.", ok=True)
        self.hours_field.clear()
        self._sync_filters_to_form()
        self._refresh_entries()

    def _sync_filters_to_form(self) -> None:
        # بعدِ ثبت، فیلترهایِ فهرست را روی همان دوره/کارمندی که تازه ثبت
        # شد ببر تا ردیفِ جدید بلافاصله دیده شود.
        index = self.period_filter_combo.findData(self.period_combo.currentData())
        if index >= 0:
            self.period_filter_combo.setCurrentIndex(index)

    def _set_selected_status(self, status: str) -> None:
        if self._selected_entry_id is None:
            QMessageBox.information(self, "تغییرِ وضعیت", "یک ردیف را از فهرست انتخاب کنید.")
            return
        try:
            overtime_service.set_overtime_entry_status(self._selected_entry_id, status)
        except ValueError as exc:
            theme.set_status_label(self.entries_status_label, str(exc), ok=False)
            return
        theme.set_status_label(self.entries_status_label, "وضعیت به‌روزرسانی شد.", ok=True)
        self._refresh_entries()

    def _delete_selected(self) -> None:
        if self._selected_entry_id is None:
            QMessageBox.information(self, "حذف", "یک ردیف را از فهرست انتخاب کنید.")
            return
        confirm = QMessageBox.question(self, "حذفِ ردیف", "این ردیفِ اضافه‌کاری حذف شود؟", QMessageBox.Yes | QMessageBox.No)
        if confirm != QMessageBox.Yes:
            return
        overtime_service.delete_overtime_entry(self._selected_entry_id)
        self._refresh_entries()

    def _on_import_excel(self) -> None:
        company_id = _company_id()
        if company_id is None:
            return
        path, _filter = QFileDialog.getOpenFileName(
            self, "انتخابِ فایلِ اکسل/CSVِ حضوروغیاب/اضافه‌کاری", "", "Excel/CSV Files (*.xlsx *.csv)"
        )
        if not path:
            return
        rows = read_excel_rows(self, path)
        if rows is None:
            return
        dialog = ExcelColumnMappingDialog(
            _IMPORT_TARGET_FIELDS, _IMPORT_GUESS_KEYWORDS, rows[0], self,
            title="ایمپورتِ اضافه‌کاری از اکسل — تناظرِ ستون‌ها",
        )
        if dialog.exec() != QDialog.Accepted:
            return
        mapping = dialog.mapping()
        data_rows = rows[1:] if dialog.skip_header_row() else rows

        employees_by_code = {e.employee_code: e.employee_id for e in self._employees}
        periods_by_key = {(p.jalali_year, p.jalali_month): p for p in self._periods}

        created = 0
        errors: list[str] = []
        for row_no, row in enumerate(data_rows, start=(2 if dialog.skip_header_row() else 1)):
            try:
                employee_code = str(row[mapping["employee_code"]]).strip()
                employee_id = employees_by_code.get(employee_code)
                if employee_id is None:
                    raise ValueError(f"کارمندی با کدِ «{employee_code}» یافت نشد.")

                period_text = numerals.to_ascii_digits(str(row[mapping["period"]]).strip())
                year_str, month_str = period_text.replace("-", "/").split("/")
                period = periods_by_key.get((int(year_str), int(month_str)))
                if period is None:
                    raise ValueError("دوره‌یِ متناظر با این تاریخ تعریف نشده است.")

                rule_code = str(row[mapping["rule_code"]]).strip().upper()
                rule = overtime_service.get_active_overtime_rule(company_id, rule_code, period.period_start_date)
                if rule is None:
                    raise ValueError(f"قانونِ اضافه‌کاریِ فعال برایِ «{rule_code}» در این دوره یافت نشد.")

                hours = decimal.Decimal(numerals.to_ascii_digits(str(row[mapping["hours"]]).strip()))
                overtime_service.create_overtime_entry(employee_id, period.period_id, rule.overtime_rule_id, hours)
                created += 1
            except (ValueError, IndexError, KeyError, decimal.InvalidOperation) as exc:
                errors.append(f"ردیفِ {row_no}: {exc}")

        if errors:
            QMessageBox.warning(self, "خطاهایِ ایمپورت", "\n".join(errors[:20]))
        theme.set_status_label(self.form_status_label, f"{created} ردیف واردِ لیستِ درانتظارِ تایید شد.", ok=created > 0)
        self.refresh()
