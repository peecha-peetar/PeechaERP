"""R359: شیفت کاری، واگذاری شیفت به کارکنان و گزارش تأخیر، تعجیل، اضافه‌ماندن و غیبت."""

from __future__ import annotations

import datetime

from PySide6.QtCore import Qt, QTime
from PySide6.QtWidgets import (
    QCheckBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QSpinBox, QTabWidget, QTimeEdit, QVBoxLayout, QWidget,
)

from peecha import numerals
from peecha.services import hr as hr_service
from peecha.services import hr_shifts as shifts_service
from peecha.ui import report_export, theme
from peecha.ui.screens.fixed_assets import P, combo, company_id, fill, selected_data, set_combo, table
from peecha.ui.widgets import FieldGrid, FieldSpec, JalaliDateEdit, build_page_header

_SUMMARY_HEADERS = ["کد", "کارمند", "روز کاری", "حاضر", "غایب", "مرخصی", "روزهای تأخیر", "تأخیر (دقیقه)", "تعجیل (دقیقه)",
                    "اضافه‌ماندن (دقیقه)", "روزهای غیبت"]
_DAY_HEADERS = ["تاریخ", "کارمند", "شیفت", "وضعیت", "ورود", "خروج", "تأخیر", "تعجیل", "اضافه‌ماندن"]


def _btn(label: str, glyph: str, kind: str = "") -> QPushButton:
    button = QPushButton(glyph)
    button.setToolTip(label)
    button.setAccessibleName(label)
    button.setObjectName({"primary": "primaryIconButton", "danger": "dangerIconButton"}.get(kind, "iconButton"))
    button.setFixedWidth(48 if kind == "primary" else 44)
    button.setCursor(Qt.PointingHandCursor)
    return button


def _time(t: datetime.time | None) -> str:
    return P(t.strftime("%H:%M")) if t else "—"


def _time_edit(hour: int) -> QTimeEdit:
    edit = QTimeEdit(QTime(hour, 0))
    edit.setDisplayFormat("HH:mm")
    return edit


class HrShiftsScreen(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setLayoutDirection(Qt.RightToLeft)
        self.shifts: list = []
        self.assignments: list = []
        self.summary_rows: list = []
        self.day_rows: list = []
        self._editing: int | None = None
        layout = QVBoxLayout(self)
        layout.addWidget(build_page_header(
            "شیفت، تأخیر و غیبت", "شیفت هر کارمند از تاریخ واگذاری؛ تأخیر، تعجیل، اضافه‌ماندن و غیبت از روی ورود و خروج‌های ثبت‌شده، "
            "روزهای استراحت شیفت، تقویم تعطیلات و مرخصی‌های تاییدشده محاسبه می‌شود."))
        self.tabs = QTabWidget()
        self.tabs.addTab(self._shifts_tab(), "شیفت‌ها")
        self.tabs.addTab(self._assign_tab(), "واگذاری شیفت")
        self.tabs.addTab(self._report_tab(), "تأخیر و غیبت")
        layout.addWidget(self.tabs, 1)
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

    # --- شیفت‌ها -------------------------------------------------------------------------------------------------
    def _shifts_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        self.code_field, self.name_field = QLineEdit(), QLineEdit()
        self.start_field, self.end_field = _time_edit(8), _time_edit(16)
        self.break_field, self.grace_field = QSpinBox(), QSpinBox()
        for spin in (self.break_field, self.grace_field):
            spin.setRange(0, 600)
        self.active_check = QCheckBox("فعال")
        self.active_check.setChecked(True)
        v.addWidget(FieldGrid([
            FieldSpec("shift_code", "کد", self.code_field, span=1), FieldSpec("shift_name", "نام شیفت", self.name_field, span=2),
            FieldSpec("shift_start", "شروع", self.start_field, span=1), FieldSpec("shift_end", "پایان", self.end_field, span=1),
            FieldSpec("shift_break", "استراحت (دقیقه)", self.break_field, span=1),
            FieldSpec("shift_grace", "ارفاق تأخیر (دقیقه)", self.grace_field, span=1),
            FieldSpec("shift_active", "", self.active_check, span=1),
        ]))
        days = QHBoxLayout()
        days.addWidget(QLabel("روزهای استراحت:"))
        self.day_checks: dict[int, QCheckBox] = {}
        for day, label in shifts_service.WEEKDAYS.items():
            box = QCheckBox(label)
            box.setChecked(day == 4)
            self.day_checks[day] = box
            days.addWidget(box)
        days.addStretch(1)
        v.addLayout(days)
        bar = QHBoxLayout()
        for label, glyph, kind, slot in (("ذخیرهٔ شیفت", "💾", "primary", self.save_shift), ("شیفت جدید", "🆕", "", self.clear_shift),
                                         ("حذف شیفت", "🗑️", "danger", self.delete_shift)):
            button = _btn(label, glyph, kind)
            button.clicked.connect(slot)
            bar.addWidget(button)
        bar.addStretch(1)
        v.addLayout(bar)
        self.shift_table = table(["کد", "نام", "شروع", "پایان", "استراحت", "ساعت کار", "ارفاق", "روزهای استراحت", "فعال"])
        self.shift_table.itemSelectionChanged.connect(self._load_shift)
        v.addWidget(self.shift_table, 1)
        return w

    def _shift_fields(self) -> shifts_service.ShiftFields:
        return shifts_service.ShiftFields(
            self.code_field.text(), self.name_field.text(), self.start_field.time().toPython(), self.end_field.time().toPython(),
            self.break_field.value(), self.grace_field.value(), tuple(d for d, b in self.day_checks.items() if b.isChecked()),
            self.active_check.isChecked())

    def save_shift(self) -> int | None:
        try:
            shift_id = shifts_service.save_shift(company_id(), self._shift_fields(), self._editing)
        except ValueError as exc:
            theme.set_status_label(self.status_label, str(exc), ok=False)
            return None
        theme.set_status_label(self.status_label, "شیفت ذخیره شد.", ok=True)
        self.clear_shift()
        self.refresh()
        return shift_id

    def clear_shift(self) -> None:
        self._editing = None
        self.code_field.clear()
        self.name_field.clear()
        self.start_field.setTime(QTime(8, 0))
        self.end_field.setTime(QTime(16, 0))
        self.break_field.setValue(0)
        self.grace_field.setValue(0)
        self.active_check.setChecked(True)
        for day, box in self.day_checks.items():
            box.setChecked(day == 4)
        self.shift_table.clearSelection()

    def _load_shift(self) -> None:
        shift_id = selected_data(self.shift_table)
        s = next((x for x in self.shifts if x.shift_id == shift_id), None)
        if s is None:
            return
        self._editing = s.shift_id
        self.code_field.setText(s.code)
        self.name_field.setText(s.name)
        self.start_field.setTime(QTime(s.start_time.hour, s.start_time.minute))
        self.end_field.setTime(QTime(s.end_time.hour, s.end_time.minute))
        self.break_field.setValue(s.break_minutes)
        self.grace_field.setValue(s.grace_minutes)
        self.active_check.setChecked(s.is_active)
        for day, box in self.day_checks.items():
            box.setChecked(day in s.off_weekdays)

    def delete_shift(self) -> bool:
        if self._editing is None:
            theme.set_status_label(self.status_label, "یک شیفت را از جدول انتخاب کنید.", ok=False)
            return False
        if QMessageBox.question(self, "حذف شیفت", "این شیفت حذف شود؟") != QMessageBox.Yes:
            return False
        try:
            shifts_service.delete_shift(company_id(), self._editing)
        except ValueError as exc:
            theme.set_status_label(self.status_label, str(exc), ok=False)
            return False
        self.clear_shift()
        self.refresh()
        return True

    # --- واگذاری ------------------------------------------------------------------------------------------------
    def _assign_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        self.employee_combo, self.shift_combo = combo([]), combo([])
        self.valid_from_field = JalaliDateEdit()
        self.valid_from_field.setDate(datetime.date.today())
        v.addWidget(FieldGrid([FieldSpec("assign_employee", "کارمند", self.employee_combo, span=2),
                               FieldSpec("assign_shift", "شیفت", self.shift_combo, span=2),
                               FieldSpec("assign_from", "از تاریخ", self.valid_from_field, span=1)]))
        bar = QHBoxLayout()
        for label, glyph, kind, slot in (("واگذاری شیفت", "➕", "primary", self.assign),
                                         ("حذف واگذاری انتخاب‌شده", "🗑️", "danger", self.unassign)):
            button = _btn(label, glyph, kind)
            button.clicked.connect(slot)
            bar.addWidget(button)
        bar.addStretch(1)
        v.addLayout(bar)
        self.assign_table = table(["کارمند", "شیفت", "از تاریخ"])
        v.addWidget(self.assign_table, 1)
        return w

    def assign(self) -> int | None:
        if self.employee_combo.currentData() is None or self.shift_combo.currentData() is None:
            theme.set_status_label(self.status_label, "کارمند و شیفت را انتخاب کنید.", ok=False)
            return None
        try:
            aid = shifts_service.assign_shift(company_id(), self.employee_combo.currentData(), self.shift_combo.currentData(),
                                              self.valid_from_field.date())
        except ValueError as exc:
            theme.set_status_label(self.status_label, str(exc), ok=False)
            return None
        theme.set_status_label(self.status_label, "شیفت واگذار شد.", ok=True)
        self.refresh()
        return aid

    def unassign(self) -> bool:
        aid = selected_data(self.assign_table)
        if aid is None:
            theme.set_status_label(self.status_label, "یک واگذاری را از جدول انتخاب کنید.", ok=False)
            return False
        shifts_service.remove_assignment(company_id(), aid)
        self.refresh()
        return True

    # --- گزارش --------------------------------------------------------------------------------------------------
    def _report_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        today = datetime.date.today()
        self.from_field, self.to_field = JalaliDateEdit(), JalaliDateEdit()
        self.from_field.setDate(today.replace(day=1))
        self.to_field.setDate(today)
        self.report_employee = combo([], "همهٔ کارکنان")
        top = QHBoxLayout()
        top.addWidget(FieldGrid([FieldSpec("rep_from", "از تاریخ", self.from_field, span=1),
                                 FieldSpec("rep_to", "تا تاریخ", self.to_field, span=1),
                                 FieldSpec("rep_employee", "کارمند", self.report_employee, span=2)]), 1)
        for label, glyph, kind, slot in (("محاسبهٔ گزارش", "🔄", "primary", self.load_report),
                                         ("خروجی Excel خلاصه", "📊", "", self.export_report)):
            button = _btn(label, glyph, kind)
            button.clicked.connect(slot)
            top.addWidget(button)
        v.addLayout(top)
        self.summary_table = table(_SUMMARY_HEADERS)
        self.summary_table.itemSelectionChanged.connect(self._show_days)
        v.addWidget(self.summary_table, 1)
        v.addWidget(QLabel("ریز روزهای کارمند انتخاب‌شده"))
        self.day_table = table(_DAY_HEADERS)
        v.addWidget(self.day_table, 1)
        return w

    def load_report(self) -> None:
        cid = company_id()
        start, end = self.from_field.date(), self.to_field.date()
        self.day_rows = shifts_service.daily_report(cid, start, end, self.report_employee.currentData())
        self.summary_rows = shifts_service.summary(cid, start, end, self.report_employee.currentData())
        fill(self.summary_table, self._summary_values(persian=True), [s.employee_id for s in self.summary_rows])
        self._show_days()

    def _summary_values(self, persian: bool) -> list[list]:
        fmt = P if persian else (lambda v: v)
        return [[s.employee_code, s.employee_name, fmt(s.workdays), fmt(s.present), fmt(s.absent), fmt(s.leave), fmt(s.late_days),
                 fmt(s.late_minutes), fmt(s.early_minutes), fmt(s.extra_minutes),
                 "، ".join(numerals.format_jalali_date(d) for d in s.absent_dates)] for s in self.summary_rows]

    def _show_days(self) -> None:
        employee_id = selected_data(self.summary_table)
        rows = [d for d in self.day_rows if employee_id is None or d.employee_id == employee_id]
        fill(self.day_table, [[d.work_date, d.employee_name, d.shift_label, d.kind_label + (" (منتظر تایید)" if d.pending else ""),
                               _time(d.clock_in), _time(d.clock_out), P(d.late_minutes) if d.late_minutes else "",
                               P(d.early_minutes) if d.early_minutes else "", P(d.extra_minutes) if d.extra_minutes else ""]
                              for d in rows])

    def export_report(self) -> None:
        from peecha import session as app_session

        company = app_session.current_company
        report_export.export_report_excel(
            self, "تأخیر و غیبت کارکنان", _SUMMARY_HEADERS, self._summary_values(persian=False),
            company_name=company.display_name if company else "",
            filters=[("از تاریخ", numerals.format_jalali_date(self.from_field.date())),
                     ("تا تاریخ", numerals.format_jalali_date(self.to_field.date()))])

    # --- بارگذاری -----------------------------------------------------------------------------------------------
    def refresh(self) -> None:
        cid = company_id()
        if cid is None:
            return
        self.shifts = shifts_service.list_shifts(cid)
        fill(self.shift_table, [[s.code, s.name, _time(s.start_time), _time(s.end_time), P(s.break_minutes),
                                 P(f"{s.work_minutes // 60}:{s.work_minutes % 60:02d}"), P(s.grace_minutes), s.off_label,
                                 "بله" if s.is_active else "خیر"] for s in self.shifts], [s.shift_id for s in self.shifts])
        employees = [(f"{e.employee_code} — {e.full_name}", e.employee_id) for e in hr_service.list_employees(cid)]
        for box, items, none in ((self.employee_combo, employees, None), (self.report_employee, employees, "همهٔ کارکنان"),
                                 (self.shift_combo, [(f"{s.code} — {s.name}", s.shift_id) for s in self.shifts if s.is_active], None)):
            current = box.currentData()
            box.clear()
            if none:
                box.addItem(none, None)
            for label, data in items:
                box.addItem(P(label), data)
            set_combo(box, current)
        self.assignments = shifts_service.list_assignments(cid)
        fill(self.assign_table, [[a.employee_name, a.shift_label, a.valid_from] for a in self.assignments],
             [a.assignment_id for a in self.assignments])
        self.load_report()
