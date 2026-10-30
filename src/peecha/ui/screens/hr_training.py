"""R369: آموزش کارکنان — دوره‌ها و دوره‌های الزامی پست‌ها، کلاس و ثبت‌نام و نتیجه، ماتریس آموزش و گزارش ساعت و هزینه."""

from __future__ import annotations

import datetime
import decimal

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDoubleSpinBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton,
    QSpinBox, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from peecha import numerals
from peecha.services import hr as hr_service
from peecha.services import hr_training as tr
from peecha.ui import report_export, theme
from peecha.ui.screens.fixed_assets import P, combo, company_id, dec, fill, selected_data, set_combo, table
from peecha.ui.widgets import FieldGrid, FieldSpec, JalaliDateEdit, build_page_header

_MATRIX_COLOR = {"VALID": "SUCCESS", "EXPIRING": "WARNING", "EXPIRED": "DANGER", "PLANNED": "INFO", "MISSING": "DANGER"}


def _btn(label: str, glyph: str, kind: str = "") -> QPushButton:
    button = QPushButton(glyph)
    button.setToolTip(label)
    button.setAccessibleName(label)
    button.setObjectName({"primary": "primaryIconButton", "danger": "dangerIconButton"}.get(kind, "iconButton"))
    button.setFixedWidth(48 if kind == "primary" else 44)
    button.setCursor(Qt.PointingHandCursor)
    return button


def _bar(*buttons) -> QHBoxLayout:
    row = QHBoxLayout()
    for label, glyph, kind, slot in buttons:
        button = _btn(label, glyph, kind)
        button.clicked.connect(slot)
        row.addWidget(button)
    row.addStretch(1)
    return row


def _num(value) -> str:
    return P(f"{value.normalize():f}") if value is not None else ""


class HrTrainingScreen(QWidget):
    def __init__(self, main_window=None) -> None:
        super().__init__()
        self.setLayoutDirection(Qt.RightToLeft)
        self.courses: list = []
        self.sessions: list = []
        self.enrollments: list = []
        self.matrix_courses: list = []
        self.matrix_rows: list = []
        self._course_id: int | None = None
        self._session_id: int | None = None
        layout = QVBoxLayout(self)
        layout.addWidget(build_page_header(
            "آموزش کارکنان", "دوره‌ها و دوره‌های الزامی هر پست، کلاس با ظرفیت و هزینه، ثبت‌نام و نتیجه با گواهی و تاریخ انقضا، و "
            "ماتریس آموزش که نشان می‌دهد هر کارمند کدام دورهٔ الزامی را ندارد یا گواهی‌اش منقضی شده است."))
        self.tabs = QTabWidget()
        self.tabs.addTab(self._courses_tab(), "دوره‌ها")
        self.tabs.addTab(self._sessions_tab(), "کلاس‌ها و ثبت‌نام")
        self.matrix_tab = self._matrix_tab()
        self.tabs.addTab(self.matrix_tab, "ماتریس آموزش")
        self.tabs.addTab(self._report_tab(), "ساعت و هزینه")
        layout.addWidget(self.tabs, 1)
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

    def _status(self, text: str, ok: bool) -> None:
        theme.set_status_label(self.status_label, text, ok=ok)

    # --- دوره‌ها ------------------------------------------------------------------------------------------------------
    def _courses_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        self.course_table = table(["کد", "عنوان", "دسته", "ساعت", "اعتبار گواهی (ماه)", "برگزارکننده", "پست‌های الزامی", "فعال"])
        self.course_table.itemSelectionChanged.connect(self._load_course)
        v.addWidget(self.course_table, 1)
        self.co_code, self.co_title, self.co_provider = QLineEdit(), QLineEdit(), QLineEdit()
        self.co_category = QComboBox()
        for code, label in tr.CATEGORIES.items():
            self.co_category.addItem(label, code)
        self.co_hours = QDoubleSpinBox()
        self.co_hours.setRange(0.5, 1000)
        self.co_hours.setDecimals(1)
        self.co_validity = QSpinBox()
        self.co_validity.setRange(0, 240)
        self.co_validity.setSpecialValueText("بی‌انقضا")
        self.co_active = QCheckBox("فعال")
        self.co_active.setChecked(True)
        row = QHBoxLayout()
        row.addWidget(FieldGrid([
            FieldSpec("co_code", "کد", self.co_code, span=1), FieldSpec("co_title", "عنوان دوره", self.co_title, span=1),
            FieldSpec("co_category", "دسته", self.co_category, span=1), FieldSpec("co_hours", "ساعت", self.co_hours, span=1),
            FieldSpec("co_validity", "اعتبار گواهی (ماه)", self.co_validity, span=1), FieldSpec("co_active", "", self.co_active, span=1),
            FieldSpec("co_provider", "برگزارکننده", self.co_provider, span=3)]), 2)
        self.position_list = QListWidget()
        self.position_list.setMaximumHeight(150)
        box = QVBoxLayout()
        box.addWidget(QLabel("پست‌هایی که این دوره برایشان الزامی است"))
        box.addWidget(self.position_list)
        row.addLayout(box, 1)
        v.addLayout(row)
        v.addLayout(_bar(("ذخیرهٔ دوره و پست‌های الزامی", "💾", "primary", self.save_course), ("دورهٔ جدید", "🆕", "", self.new_course),
                         ("به‌روزرسانی", "🔄", "", self.refresh)))
        return w

    def refresh(self) -> None:
        cid = company_id()
        if cid is None:
            return
        positions = hr_service.list_positions(cid)
        names = {p.position_id: p.title for p in positions}
        self.position_list.clear()
        for p in positions:
            item = QListWidgetItem(P(f"{p.code} — {p.title}"))
            item.setData(Qt.UserRole, p.position_id)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            self.position_list.addItem(item)
        self.courses = tr.list_courses(cid)
        fill(self.course_table, [[c.code, c.title, c.category_label, _num(c.hours), c.validity_months or "بی‌انقضا", c.provider or "—",
                                  "، ".join(names.get(p, "") for p in c.position_ids) or "—", "بله" if c.is_active else "خیر"]
                                 for c in self.courses], [c.course_id for c in self.courses])
        current = self.se_course.currentData()
        self.se_course.clear()
        self.se_course.addItem("—", None)
        for c in self.courses:
            if c.is_active:
                self.se_course.addItem(P(c.label), c.course_id)
        set_combo(self.se_course, current)
        employees = [(f"{e.employee_code} — {e.full_name}", e.employee_id) for e in hr_service.list_employees(cid) if e.status == "ACTIVE"]
        for box, items, none in ((self.enroll_employee, employees, "—"),
                                 (self.mx_unit, [(f"{u.code} — {u.name}", u.org_unit_id) for u in hr_service.list_org_units(cid)],
                                  "— همهٔ واحدها —")):
            current = box.currentData()
            box.blockSignals(True)
            box.clear()
            box.addItem(none, None)
            for label, data in items:
                box.addItem(P(label), data)
            set_combo(box, current)
            box.blockSignals(False)
        self.refresh_sessions()
        self.refresh_matrix()
        self.refresh_report()

    def _load_course(self) -> None:
        c = next((x for x in self.courses if x.course_id == selected_data(self.course_table)), None)
        if c is None:
            return
        self._course_id = c.course_id
        self.co_code.setText(c.code)
        self.co_title.setText(c.title)
        self.co_category.setCurrentIndex(self.co_category.findData(c.category_code))
        self.co_hours.setValue(float(c.hours))
        self.co_validity.setValue(c.validity_months or 0)
        self.co_provider.setText(c.provider)
        self.co_active.setChecked(c.is_active)
        for i in range(self.position_list.count()):
            item = self.position_list.item(i)
            item.setCheckState(Qt.Checked if item.data(Qt.UserRole) in c.position_ids else Qt.Unchecked)

    def new_course(self) -> None:
        self._course_id = None
        self.course_table.clearSelection()
        for f in (self.co_code, self.co_title, self.co_provider):
            f.clear()
        self.co_hours.setValue(8)
        self.co_validity.setValue(0)
        self.co_active.setChecked(True)
        for i in range(self.position_list.count()):
            self.position_list.item(i).setCheckState(Qt.Unchecked)

    def save_course(self) -> int | None:
        try:
            course_id = tr.save_course(company_id(), tr.CourseFields(
                self.co_code.text(), self.co_title.text(), decimal.Decimal(str(self.co_hours.value())), self.co_category.currentData(),
                self.co_validity.value() or None, self.co_provider.text(), self.co_active.isChecked()), self._course_id)
            tr.set_required_positions(company_id(), course_id, [
                self.position_list.item(i).data(Qt.UserRole) for i in range(self.position_list.count())
                if self.position_list.item(i).checkState() == Qt.Checked])
        except ValueError as exc:
            self._status(str(exc), False)
            return None
        self.new_course()
        self.refresh()
        self._status("دوره ذخیره شد.", True)
        return course_id

    # --- کلاس‌ها ------------------------------------------------------------------------------------------------------
    def _sessions_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        self.session_table = table(["دوره", "از", "تا", "مدرس", "محل", "ظرفیت", "ثبت‌نام", "هزینه", "وضعیت"])
        self.session_table.itemSelectionChanged.connect(self._load_session)
        v.addWidget(self.session_table, 1)
        self.se_course = combo([], "—")
        self.se_from, self.se_to = JalaliDateEdit(), JalaliDateEdit()
        self.se_trainer, self.se_location, self.se_cost = QLineEdit(), QLineEdit(), QLineEdit()
        self.se_capacity = QSpinBox()
        self.se_capacity.setRange(0, 1000)
        self.se_capacity.setSpecialValueText("بی‌سقف")
        v.addWidget(FieldGrid([
            FieldSpec("se_course", "دوره", self.se_course, span=1), FieldSpec("se_from", "از تاریخ", self.se_from, span=1),
            FieldSpec("se_to", "تا تاریخ", self.se_to, span=1), FieldSpec("se_trainer", "مدرس", self.se_trainer, span=1),
            FieldSpec("se_location", "محل برگزاری", self.se_location, span=1), FieldSpec("se_capacity", "ظرفیت", self.se_capacity, span=1),
            FieldSpec("se_cost", "هزینهٔ کلاس", self.se_cost, span=1)]))
        v.addLayout(_bar(("ذخیرهٔ کلاس", "💾", "primary", self.save_session), ("کلاس جدید", "🆕", "", self.new_session),
                         ("ثبت برگزاری کلاس", "🏁", "", self.complete_session), ("لغو کلاس", "🚫", "danger", self.cancel_session)))
        row = QHBoxLayout()
        self.enroll_employee = combo([], "—")
        row.addWidget(FieldGrid([FieldSpec("en_employee", "ثبت‌نام کارمند", self.enroll_employee, span=1)], columns=1), 1)
        for label, glyph, kind, slot in (("ثبت‌نام کارمند در کلاس انتخاب‌شده", "➕", "primary", self.enroll),
                                         ("ثبت‌نام همهٔ کارکنانی که این دوره برایشان الزامی است و ندارند", "👥", "", self.enroll_required),
                                         ("حذف ثبت‌نام انتخاب‌شده", "➖", "danger", self.remove_enrollment)):
            button = _btn(label, glyph, kind)
            button.clicked.connect(slot)
            row.addWidget(button)
        v.addLayout(row)
        self.enroll_table = table(["کد", "کارمند", "نتیجه", "نمره", "شمارهٔ گواهی", "تاریخ گواهی", "انقضا"])
        self.enroll_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        v.addWidget(self.enroll_table, 1)
        self.result_combo = QComboBox()
        for code in ("PASSED", "FAILED", "ATTENDED", "ABSENT"):
            self.result_combo.addItem(tr.RESULTS[code], code)
        self.result_score, self.result_cert = QLineEdit(), QLineEdit()
        res = QHBoxLayout()
        res.addWidget(FieldGrid([FieldSpec("res_status", "نتیجه", self.result_combo, span=1), FieldSpec("res_score", "نمره (۰ تا ۱۰۰)", self.result_score, span=1),
                                 FieldSpec("res_cert", "شمارهٔ گواهی", self.result_cert, span=1)]), 1)
        record = _btn("ثبت نتیجه برای ثبت‌نام‌های انتخاب‌شده", "✅", "primary")
        record.clicked.connect(self.record_result)
        res.addWidget(record)
        v.addLayout(res)
        return w

    def refresh_sessions(self) -> None:
        self.sessions = tr.list_sessions(company_id())
        fill(self.session_table, [[s.course_label, s.start_date, s.end_date, s.trainer or "—", s.location or "—", s.capacity or "بی‌سقف",
                                   s.enrolled, s.cost, s.status_label] for s in self.sessions], [s.session_id for s in self.sessions])
        if self._session_id is not None:
            row = next((i for i, s in enumerate(self.sessions) if s.session_id == self._session_id), None)
            if row is not None:
                self.session_table.blockSignals(True)
                self.session_table.setCurrentCell(row, 0)
                self.session_table.blockSignals(False)
        self._show_enrollments()

    def _show_enrollments(self) -> None:
        self.enrollments = tr.list_enrollments(company_id(), self._session_id) if self._session_id else []
        fill(self.enroll_table, [[e.employee_code, e.employee_name, e.status_label, _num(e.score) or "—", e.certificate_no or "—",
                                  e.completed_on or "—", e.expires_on or "—"] for e in self.enrollments],
             [e.enrollment_id for e in self.enrollments])

    def _load_session(self) -> None:
        s = next((x for x in self.sessions if x.session_id == selected_data(self.session_table)), None)
        if s is None:
            return
        self._session_id = s.session_id
        set_combo(self.se_course, s.course_id)
        self.se_from.setDate(s.start_date)
        self.se_to.setDate(s.end_date)
        self.se_trainer.setText(s.trainer)
        self.se_location.setText(s.location)
        self.se_capacity.setValue(s.capacity or 0)
        self.se_cost.setText(_num(s.cost) if s.cost else "")
        self._show_enrollments()

    def new_session(self) -> None:
        self._session_id = None
        self.session_table.clearSelection()
        for f in (self.se_trainer, self.se_location, self.se_cost):
            f.clear()
        self.se_capacity.setValue(0)
        self.se_from.setDate(datetime.date.today())
        self.se_to.setDate(datetime.date.today())
        self._show_enrollments()

    def save_session(self) -> int | None:
        if self.se_course.currentData() is None:
            self._status("دوره را انتخاب کنید.", False)
            return None
        try:
            self._session_id = tr.save_session(company_id(), tr.SessionFields(
                self.se_course.currentData(), self.se_from.date(), self.se_to.date(), self.se_trainer.text(), self.se_location.text(),
                self.se_capacity.value() or None, dec(self.se_cost.text())), self._session_id)
        except (ValueError, decimal.InvalidOperation) as exc:
            self._status(str(exc) if isinstance(exc, ValueError) else "هزینه نامعتبر است.", False)
            return None
        self.refresh()
        self._status("کلاس ذخیره شد؛ کارکنان را ثبت‌نام کنید.", True)
        return self._session_id

    def _act(self, fn, done: str) -> bool:
        if self._session_id is None:
            self._status("یک کلاس را انتخاب کنید.", False)
            return False
        try:
            fn()
        except (ValueError, decimal.InvalidOperation) as exc:
            self._status(str(exc) if isinstance(exc, ValueError) else "نمره نامعتبر است.", False)
            return False
        self.refresh()
        self._status(done, True)
        return True

    def complete_session(self) -> bool:
        return self._act(lambda: tr.complete_session(company_id(), self._session_id), "کلاس برگزارشده ثبت شد.")

    def cancel_session(self) -> bool:
        return self._act(lambda: tr.cancel_session(company_id(), self._session_id), "کلاس لغو شد.")

    def enroll(self) -> bool:
        if self.enroll_employee.currentData() is None:
            self._status("کارمند را انتخاب کنید.", False)
            return False
        return self._act(lambda: tr.enroll(company_id(), self._session_id, [self.enroll_employee.currentData()]), "کارمند ثبت‌نام شد.")

    def enroll_required(self) -> bool:
        s = next((x for x in self.sessions if x.session_id == self._session_id), None)
        if s is None:
            self._status("یک کلاس را انتخاب کنید.", False)
            return False
        _courses, rows = tr.matrix(company_id())
        need = [r.employee_id for r in rows if s.course_id in r.cells and r.cells[s.course_id].status_code in ("MISSING", "EXPIRED", "EXPIRING")]
        if not need:
            self._status("همهٔ کسانی که این دوره برایشان الزامی است گواهی معتبر دارند یا ثبت‌نام شده‌اند.", True)
            return False
        return self._act(lambda: tr.enroll(company_id(), self._session_id, need), f"{P(len(need))} کارمند ثبت‌نام شدند.")

    def remove_enrollment(self) -> bool:
        eid = selected_data(self.enroll_table)
        if eid is None:
            self._status("یک ثبت‌نام را انتخاب کنید.", False)
            return False
        return self._act(lambda: tr.remove_enrollment(company_id(), eid), "ثبت‌نام حذف شد.")

    def record_result(self) -> bool:
        rows = sorted({i.row() for i in self.enroll_table.selectedIndexes()})
        ids = [self.enroll_table.item(r, 0).data(Qt.UserRole) for r in rows]
        if not ids:
            self._status("ثبت‌نام‌هایی را برای ثبت نتیجه انتخاب کنید.", False)
            return False
        score = dec(self.result_score.text()) if self.result_score.text().strip() else None
        cert = self.result_cert.text() if len(ids) == 1 else None
        return self._act(lambda: [tr.record_result(company_id(), i, self.result_combo.currentData(), score, cert) for i in ids],
                         f"نتیجهٔ {P(len(ids))} نفر ثبت شد.")

    # --- ماتریس -------------------------------------------------------------------------------------------------------
    def _matrix_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        row = QHBoxLayout()
        self.mx_unit = combo([], "— همهٔ واحدها —")
        self.mx_unit.currentIndexChanged.connect(self.refresh_matrix)
        row.addWidget(FieldGrid([FieldSpec("mx_unit", "واحد سازمانی", self.mx_unit, span=1)], columns=1), 1)
        export = _btn("خروجی Excel ماتریس آموزش", "📊")
        export.clicked.connect(self.export_matrix)
        row.addWidget(export)
        v.addLayout(row)
        self.gap_label = QLabel("")
        self.gap_label.setWordWrap(True)
        v.addWidget(self.gap_label)
        self.matrix_table = table(["کد", "کارمند", "پست", "واحد"])
        v.addWidget(self.matrix_table, 1)
        return w

    def refresh_matrix(self) -> None:
        cid = company_id()
        if cid is None:
            return
        self.matrix_courses, self.matrix_rows = tr.matrix(cid, self.mx_unit.currentData())
        headers = ["کد", "کارمند", "پست", "واحد"] + [c.code for c in self.matrix_courses]
        self.matrix_table.clear()
        self.matrix_table.setColumnCount(len(headers))
        self.matrix_table.setHorizontalHeaderLabels([P(h) for h in headers])
        for col, c in enumerate(self.matrix_courses, start=4):
            self.matrix_table.horizontalHeaderItem(col).setToolTip(c.title)
        self.matrix_table.setRowCount(len(self.matrix_rows))
        counts = {k: 0 for k in tr.MATRIX}
        for r, row in enumerate(self.matrix_rows):
            for c, text in enumerate([P(row.employee_code), row.employee_name, row.position, row.org_unit]):
                self.matrix_table.setItem(r, c, QTableWidgetItem(text))
            for col, course in enumerate(self.matrix_courses, start=4):
                cell = row.cells.get(course.course_id)
                if cell is None:
                    self.matrix_table.setItem(r, col, QTableWidgetItem(""))
                    continue
                counts[cell.status_code] += 1
                text = cell.status_label + (f" ({numerals.format_jalali_date(cell.expires_on)})" if cell.expires_on else "")
                item = QTableWidgetItem(text)
                item.setForeground(QColor(getattr(theme, _MATRIX_COLOR[cell.status_code])))
                self.matrix_table.setItem(r, col, item)
        self.gap_label.setText(" | ".join(f"{label}: {P(counts[code])}" for code, label in tr.MATRIX.items()))

    def export_matrix(self) -> bool:
        if not self.matrix_rows:
            return False
        headers = ["کد", "کارمند", "پست", "واحد"] + [c.title for c in self.matrix_courses]
        rows = [[r.employee_code, r.employee_name, r.position, r.org_unit] + [
            r.cells[c.course_id].status_label if c.course_id in r.cells else "" for c in self.matrix_courses] for r in self.matrix_rows]
        report_export.export_report_excel(self, "ماتریس آموزش", headers, rows)
        return True

    def open_matrix(self) -> None:
        self.refresh()
        self.tabs.setCurrentWidget(self.matrix_tab)

    # --- ساعت و هزینه -------------------------------------------------------------------------------------------------
    def _report_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        row = QHBoxLayout()
        self.rp_from, self.rp_to = JalaliDateEdit(), JalaliDateEdit()
        self.rp_from.setDate(datetime.date.today() - datetime.timedelta(days=365))
        row.addWidget(FieldGrid([FieldSpec("rp_from", "از تاریخ", self.rp_from, span=1), FieldSpec("rp_to", "تا تاریخ", self.rp_to, span=1)],
                                columns=2), 1)
        for label, glyph, slot in (("نمایش", "🔎", self.refresh_report), ("خروجی Excel", "📊", self.export_report)):
            button = _btn(label, glyph)
            button.clicked.connect(slot)
            row.addWidget(button)
        v.addLayout(row)
        self.report_table = table(["کد", "کارمند", "ساعت آموزش", "سهم هزینه"])
        v.addWidget(self.report_table, 1)
        return w

    def refresh_report(self) -> None:
        self.report_rows = tr.hours_report(company_id(), self.rp_from.date(), self.rp_to.date())
        fill(self.report_table, [[code, name, _num(hours), cost] for code, name, hours, cost in self.report_rows])

    def export_report(self) -> bool:
        if not self.report_rows:
            return False
        report_export.export_report_excel(self, "ساعت و هزینهٔ آموزش کارکنان", ["کد", "کارمند", "ساعت آموزش", "سهم هزینه"],
                                          [list(r) for r in self.report_rows])
        return True
